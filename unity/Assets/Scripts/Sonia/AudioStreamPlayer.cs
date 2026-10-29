// Streaming playback of the PCM that arrives over the WebSocket.
//
// Threading rules:
//  - Enqueue() is called from the main thread (SoniaClient dispatch). There the
//    chunk is resampled to the output rate and copied into the ring buffer.
//  - OnAudioFilterRead() runs on the audio thread and consumes that buffer.
//  - The buffer, the segment list and the counters are protected with a lock.
//    The critical sections are memory copies: no Unity API is called inside
//    the lock from the audio thread.
//
// Mouth sync: the phoneme analysis (OnAudioFrame listeners) sees the "fresh"
// audio and the real output comes out lipSyncLeadMs behind through a small
// delay line. Measured: without a lead the mouth arrived about 75 ms late
// relative to the generated block (analysis, wait frame and smoothing), that
// is, 40-50 ms late relative to the speaker.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>
    /// PCM audio queue with linear resampling, per-utterance accounting and an
    /// end-of-playback notification. Lip-sync relies on <see cref="CurrentUtteranceId"/>
    /// and <see cref="CurrentUtteranceTime"/> to know what is playing and how far along.
    /// </summary>
    [RequireComponent(typeof(AudioSource))]
    [DisallowMultipleComponent]
    public class AudioStreamPlayer : MonoBehaviour
    {
        [Header("Input format")]
        [SerializeField]
        [Tooltip("Sample rate of the audio the orchestrator sends. The hello message overrides it.")]
        private int sourceSampleRate = Protocol.DefaultSampleRate;

        [Header("Buffer")]
        [SerializeField]
        [Tooltip("Seconds of audio the ring buffer reserves at start. It grows only if needed.")]
        private float initialBufferSeconds = 4f;

        [SerializeField]
        [Tooltip("Ring buffer cap in seconds. Above it, audio that does not fit is dropped.")]
        private float maxBufferSeconds = 120f;

        [Header("Output")]
        [SerializeField]
        [Range(0f, MaxVolume)]
        [Tooltip("Voice volume (1 = normal). Changed by the orchestrator's set_volume message. It only affects what is heard: lip-sync analyzes the audio before the gain, so the mouth moves the same at any volume.")]
        private float volume = 1f;

        [SerializeField]
        [Tooltip("Logs to the console when the buffer runs empty in the middle of an utterance.")]
        private bool logUnderruns;

        [Header("Lip-sync")]
        [SerializeField]
        [Range(0f, 200f)]
        [Tooltip("Milliseconds the audio output runs behind the phoneme analysis. The analysis, the wait frame and the mouth smoothing add up to about 75 ms; with this lead the mouth arrives together with the voice (measured: without it it is 40-50 ms late relative to the speaker). 0 disables it.")]
        private float lipSyncLeadMs = 60f;

        /// <summary>
        /// Fired on the main thread when the last sample of an utterance marked as
        /// finished has been consumed. The argument is the utterance_id.
        /// </summary>
        public event Action<int> OnUtterancePlaybackDone;

        /// <summary>
        /// Audio that just went out through the AudioSource, on the audio thread:
        /// interleaved samples and channel count. Consumed by the lip-sync
        /// phoneme analysis. Do not touch Unity from here.
        /// </summary>
        public event Action<float[], int> OnAudioFrame;

        private readonly object _lock = new object();
        private readonly List<Segment> _segments = new List<Segment>();
        private readonly List<int> _pendingDone = new List<int>();
        private readonly List<int> _dispatchBuffer = new List<int>();

        private float[] _ring = new float[0];
        private int _readPosition;
        private int _writePosition;
        private int _available;
        private int _outputSampleRate = 48000;
        private float _currentRms;
        private int _lastReportedDoneId = -1;

        private double _resamplePhase;
        private float _previousSourceSample;
        private float[] _scratch = new float[4096];

        private AudioSource _audioSource;
        private AudioClip _silence;
        private volatile bool _hadUnderrun;
        private bool _droppedAudio;

        // Gain applied in the last block. Only the audio thread touches it: a
        // volume change is spread as a ramp over one block so it does not click.
        private float _appliedGain = 1f;

        // Mono delay line between the analysis (what OnAudioFrame listeners see)
        // and the real output. Only the audio thread touches it except in Flush
        // and when reconfiguring, always under the lock.
        private float[] _fresh = new float[0];
        private float[] _analysis = new float[0];
        private float[] _delayLine = new float[0];
        private int _delayWrite;
        private int _delaySamples;

        // ------------------------------------------------------------------
        // Properties for lip-sync and the debug interface
        // ------------------------------------------------------------------

        /// <summary>Utterance being played, or -1 if nothing is playing.</summary>
        public int CurrentUtteranceId
        {
            get
            {
                lock (_lock)
                {
                    return _segments.Count > 0 ? _segments[0].UtteranceId : -1;
                }
            }
        }

        /// <summary>Seconds already played of the current utterance.</summary>
        public float CurrentUtteranceTime
        {
            get
            {
                lock (_lock)
                {
                    if (_segments.Count == 0 || _outputSampleRate <= 0)
                    {
                        return 0f;
                    }

                    return (float)(_segments[0].ConsumedSamples / (double)_outputSampleRate);
                }
            }
        }

        /// <summary>RMS level of the last audio block written, between 0 and 1.</summary>
        public float CurrentRms
        {
            get
            {
                lock (_lock)
                {
                    return _currentRms;
                }
            }
        }

        /// <summary>Seconds of audio pending playback.</summary>
        public float BufferedSeconds
        {
            get
            {
                lock (_lock)
                {
                    return _outputSampleRate > 0 ? _available / (float)_outputSampleRate : 0f;
                }
            }
        }

        /// <summary>True if audio remains to be played.</summary>
        public bool IsPlaying
        {
            get
            {
                lock (_lock)
                {
                    return _available > 0;
                }
            }
        }

        /// <summary>Output sample rate of the audio engine.</summary>
        public int OutputSampleRate
        {
            get { return _outputSampleRate; }
        }

        /// <summary>Maximum volume <see cref="SetVolume"/> accepts (the protocol's).</summary>
        public const float MaxVolume = 1.5f;

        /// <summary>Current voice volume (0 to <see cref="MaxVolume"/>; 1 is normal).</summary>
        public float Volume
        {
            get { return volume; }
        }

        /// <summary>
        /// Changes the voice volume (<c>set_volume</c> message). It is clamped to
        /// 0..<see cref="MaxVolume"/> and applied as a ramp in the next audio
        /// block. Main thread.
        /// </summary>
        public void SetVolume(float value)
        {
            if (float.IsNaN(value) || float.IsInfinity(value))
            {
                return;
            }

            volume = Mathf.Clamp(value, 0f, MaxVolume);
        }

        /// <summary>
        /// Reads the playback position and the level at once, so lip-sync takes
        /// the lock once per frame instead of three times.
        /// </summary>
        public void GetPlaybackPosition(out int utteranceId, out float seconds, out float rms)
        {
            lock (_lock)
            {
                if (_segments.Count == 0 || _outputSampleRate <= 0)
                {
                    utteranceId = -1;
                    seconds = 0f;
                }
                else
                {
                    utteranceId = _segments[0].UtteranceId;
                    seconds = (float)(_segments[0].ConsumedSamples / (double)_outputSampleRate);
                }

                rms = _currentRms;
            }
        }

        // ------------------------------------------------------------------
        // Lifecycle
        // ------------------------------------------------------------------

        private void Awake()
        {
            _audioSource = GetComponent<AudioSource>();
            volume = Mathf.Clamp(volume, 0f, MaxVolume);
            _appliedGain = volume;
            RefreshOutputSampleRate();
            AllocateRing(initialBufferSeconds);
            ConfigureDelayLine();

            // OnAudioFilterRead is only called if the AudioSource is playing, so
            // a one-second silence clip is looped.
            int clipSamples = Mathf.Max(1024, _outputSampleRate);
            _silence = AudioClip.Create("SoniaSilence", clipSamples, 1, _outputSampleRate, false);
            _audioSource.clip = _silence;
            _audioSource.loop = true;
            _audioSource.playOnAwake = false;
            _audioSource.spatialBlend = 0f;
            _audioSource.volume = 1f;
            _audioSource.Play();
        }

        private void OnEnable()
        {
            AudioSettings.OnAudioConfigurationChanged += HandleAudioConfigurationChanged;
        }

        private void OnDisable()
        {
            AudioSettings.OnAudioConfigurationChanged -= HandleAudioConfigurationChanged;
        }

        private void OnDestroy()
        {
            if (_silence != null)
            {
                Destroy(_silence);
                _silence = null;
            }
        }

        private void HandleAudioConfigurationChanged(bool deviceWasChanged)
        {
            RefreshOutputSampleRate();
            Flush();
            AllocateRing(initialBufferSeconds);
            ConfigureDelayLine();
            if (_audioSource != null && !_audioSource.isPlaying)
            {
                _audioSource.Play();
            }
        }

        private void RefreshOutputSampleRate()
        {
            int rate = AudioSettings.outputSampleRate;
            _outputSampleRate = rate > 0 ? rate : 48000;
        }

        /// <summary>Milliseconds of lip-sync lead over the audio output.</summary>
        public float LipSyncLeadMs
        {
            get { return lipSyncLeadMs; }
            set
            {
                lipSyncLeadMs = Mathf.Clamp(value, 0f, 200f);
                ConfigureDelayLine();
            }
        }

        /// <summary>Sizes the delay line according to the requested lead. Main thread.</summary>
        private void ConfigureDelayLine()
        {
            int samples = Mathf.RoundToInt(Mathf.Clamp(lipSyncLeadMs, 0f, 200f) / 1000f * _outputSampleRate);
            lock (_lock)
            {
                _delaySamples = samples;
                // Capacity: delay plus the largest block Unity requests at once.
                int capacity = samples + 8192;
                if (_delayLine.Length != capacity)
                {
                    _delayLine = new float[capacity];
                }
                else
                {
                    Array.Clear(_delayLine, 0, _delayLine.Length);
                }

                _delayWrite = 0;
            }
        }

        private void AllocateRing(float seconds)
        {
            int samples = Mathf.Max(1024, Mathf.RoundToInt(Mathf.Max(0.1f, seconds) * _outputSampleRate));
            lock (_lock)
            {
                _ring = new float[samples];
                _readPosition = 0;
                _writePosition = 0;
                _available = 0;
            }
        }

        private void Update()
        {
            _dispatchBuffer.Clear();
            lock (_lock)
            {
                if (_pendingDone.Count > 0)
                {
                    _dispatchBuffer.AddRange(_pendingDone);
                    _pendingDone.Clear();
                }
            }

            for (int i = 0; i < _dispatchBuffer.Count; i++)
            {
                Action<int> handler = OnUtterancePlaybackDone;
                if (handler == null)
                {
                    continue;
                }

                try
                {
                    handler(_dispatchBuffer[i]);
                }
                catch (Exception ex)
                {
                    Debug.LogException(ex, this);
                }
            }

            if (_hadUnderrun)
            {
                _hadUnderrun = false;
                if (logUnderruns)
                {
                    Debug.Log("[Sonnia] The audio buffer ran short; it was filled with silence.", this);
                }
            }

            if (_droppedAudio)
            {
                _droppedAudio = false;
                Debug.LogWarning("[Sonnia] Audio buffer full: samples were dropped.", this);
            }
        }

        // ------------------------------------------------------------------
        // Public API
        // ------------------------------------------------------------------

        /// <summary>Sets the input sample rate announced in <c>hello</c>.</summary>
        public void SetSourceSampleRate(int sampleRate)
        {
            if (sampleRate <= 0 || sampleRate == sourceSampleRate)
            {
                return;
            }

            sourceSampleRate = sampleRate;
            lock (_lock)
            {
                _resamplePhase = 0.0;
                _previousSourceSample = 0f;
            }
        }

        /// <summary>Enqueues a freshly arrived audio chunk (main thread).</summary>
        public void Enqueue(AudioFrame frame)
        {
            if (frame.Samples == null || frame.Samples.Length == 0)
            {
                if (frame.IsLast)
                {
                    MarkUtteranceComplete(frame.UtteranceId);
                }

                return;
            }

            int produced = Resample(frame.Samples, frame.Samples.Length);
            if (produced <= 0)
            {
                if (frame.IsLast)
                {
                    MarkUtteranceComplete(frame.UtteranceId);
                }

                return;
            }

            bool dropped = false;
            lock (_lock)
            {
                EnsureCapacity(_available + produced);

                int space = _ring.Length - _available;
                int toWrite = Mathf.Min(produced, space);
                if (toWrite < produced)
                {
                    dropped = true;
                }

                if (toWrite > 0)
                {
                    int first = Mathf.Min(toWrite, _ring.Length - _writePosition);
                    Array.Copy(_scratch, 0, _ring, _writePosition, first);
                    int rest = toWrite - first;
                    if (rest > 0)
                    {
                        Array.Copy(_scratch, first, _ring, 0, rest);
                    }

                    _writePosition = (_writePosition + toWrite) % _ring.Length;
                    _available += toWrite;
                }

                Segment segment = null;
                if (_segments.Count > 0)
                {
                    Segment last = _segments[_segments.Count - 1];
                    if (last.UtteranceId == frame.UtteranceId && !last.IsLast)
                    {
                        segment = last;
                    }
                }

                if (segment == null)
                {
                    segment = new Segment(frame.UtteranceId);
                    _segments.Add(segment);
                }

                segment.TotalSamples += toWrite;
                if (frame.IsLast)
                {
                    segment.IsLast = true;
                }
            }

            if (dropped)
            {
                _droppedAudio = true;
            }
        }

        /// <summary>
        /// Marks an utterance as finished even if the last-chunk bit has not
        /// arrived. Called on receiving <c>speech_end</c>. If the utterance was
        /// already fully played (or never had audio), it notifies immediately.
        /// </summary>
        public void MarkUtteranceComplete(int utteranceId)
        {
            lock (_lock)
            {
                bool found = false;
                for (int i = 0; i < _segments.Count; i++)
                {
                    if (_segments[i].UtteranceId == utteranceId)
                    {
                        _segments[i].IsLast = true;
                        found = true;
                    }
                }

                if (!found)
                {
                    ReportDoneLocked(utteranceId);
                }
            }
        }

        /// <summary>
        /// Empties all queued audio and the utterance accounting. Used with
        /// <c>stop_speaking</c>: no playback-finished notification is sent because
        /// the orchestrator already canceled the turn.
        /// </summary>
        public void Flush()
        {
            lock (_lock)
            {
                _readPosition = 0;
                _writePosition = 0;
                _available = 0;
                _segments.Clear();
                _pendingDone.Clear();
                _resamplePhase = 0.0;
                _previousSourceSample = 0f;
                _currentRms = 0f;
                _lastReportedDoneId = -1;
                Array.Clear(_delayLine, 0, _delayLine.Length);
            }
        }

        // ------------------------------------------------------------------
        // Resampling (main thread)
        // ------------------------------------------------------------------

        /// <summary>
        /// Linearly resamples from the orchestrator's rate to the output rate and
        /// leaves the result in <c>_scratch</c>. Keeps the phase and the last sample
        /// between chunks so there are no clicks at the joins.
        /// </summary>
        private int Resample(float[] source, int count)
        {
            if (count < 1)
            {
                return 0;
            }

            int inputRate = sourceSampleRate > 0 ? sourceSampleRate : Protocol.DefaultSampleRate;
            int outputRate = _outputSampleRate > 0 ? _outputSampleRate : 48000;
            double ratio = (double)inputRate / outputRate;
            if (ratio <= 0.0)
            {
                ratio = 1.0;
            }

            int estimate = (int)(count / ratio) + 8;
            if (_scratch.Length < estimate)
            {
                _scratch = new float[Mathf.NextPowerOfTwo(estimate)];
            }

            double position = _resamplePhase;
            double limit = count - 1;
            int produced = 0;

            while (position < limit && produced < _scratch.Length)
            {
                int index = (int)Math.Floor(position);
                float fraction = (float)(position - index);
                float a = index < 0 ? _previousSourceSample : source[index];
                float b = source[index + 1];
                _scratch[produced] = a + ((b - a) * fraction);
                produced++;
                position += ratio;
            }

            _resamplePhase = position - count;
            _previousSourceSample = source[count - 1];
            return produced;
        }

        /// <summary>Grows the ring buffer keeping what was already there. Lock held.</summary>
        private void EnsureCapacity(int needed)
        {
            if (_ring.Length >= needed)
            {
                return;
            }

            int maxSamples = Mathf.Max(1024, Mathf.RoundToInt(Mathf.Max(0.1f, maxBufferSeconds) * _outputSampleRate));
            int capacity = Mathf.Max(1024, _ring.Length);
            while (capacity < needed && capacity < maxSamples)
            {
                capacity *= 2;
            }

            if (capacity > maxSamples)
            {
                capacity = maxSamples;
            }

            if (capacity <= _ring.Length)
            {
                return;
            }

            float[] grown = new float[capacity];
            int toCopy = Mathf.Min(_available, capacity);
            if (toCopy > 0 && _ring.Length > 0)
            {
                int first = Mathf.Min(toCopy, _ring.Length - _readPosition);
                Array.Copy(_ring, _readPosition, grown, 0, first);
                int rest = toCopy - first;
                if (rest > 0)
                {
                    Array.Copy(_ring, 0, grown, first, rest);
                }
            }

            _ring = grown;
            _readPosition = 0;
            _writePosition = toCopy % capacity;
            _available = toCopy;
        }

        // ------------------------------------------------------------------
        // Audio thread
        // ------------------------------------------------------------------

        private void OnAudioFilterRead(float[] data, int channels)
        {
            if (data == null || channels <= 0)
            {
                return;
            }

            int frames = data.Length / channels;
            if (frames <= 0)
            {
                return;
            }

            int written = 0;
            double sumSquares = 0.0;

            // One-block gain ramp: from the gain of the previous block to the one
            // requested now. With steady volume it is constant.
            float gainStart = _appliedGain;
            float gainTarget = volume;
            float gainStep = (gainTarget - gainStart) / frames;
            _appliedGain = gainTarget;

            lock (_lock)
            {
                if (_fresh.Length < frames)
                {
                    _fresh = new float[Mathf.Max(frames, 4096)];
                }

                if (_analysis.Length != data.Length)
                {
                    // Exactly the same size as data: listeners walk the whole block.
                    _analysis = new float[data.Length];
                }

                if (_ring.Length > 0)
                {
                    while (written < frames && _available > 0)
                    {
                        Segment segment = _segments.Count > 0 ? _segments[0] : null;
                        long segmentRemaining = long.MaxValue;
                        if (segment != null)
                        {
                            segmentRemaining = segment.TotalSamples - segment.ConsumedSamples;
                            if (segmentRemaining <= 0L)
                            {
                                if (segment.IsLast)
                                {
                                    ReportDoneLocked(segment.UtteranceId);
                                    _segments.RemoveAt(0);
                                    continue;
                                }

                                // Audio of this utterance is missing: fill with silence
                                // and the utterance time does not advance.
                                break;
                            }
                        }

                        int chunk = frames - written;
                        if (chunk > _available)
                        {
                            chunk = _available;
                        }

                        if (segmentRemaining < chunk)
                        {
                            chunk = (int)segmentRemaining;
                        }

                        if (chunk <= 0)
                        {
                            break;
                        }

                        for (int i = 0; i < chunk; i++)
                        {
                            // No gain: the analysis and the RMS see the voice as is.
                            float sample = _ring[_readPosition];
                            _readPosition++;
                            if (_readPosition >= _ring.Length)
                            {
                                _readPosition = 0;
                            }

                            _fresh[written + i] = sample;
                            sumSquares += sample * sample;
                        }

                        _available -= chunk;
                        written += chunk;
                        if (segment != null)
                        {
                            segment.ConsumedSamples += chunk;
                        }
                    }

                    // An utterance may have ended exactly with the last sample.
                    while (_segments.Count > 0)
                    {
                        Segment head = _segments[0];
                        if (head.IsLast && head.ConsumedSamples >= head.TotalSamples)
                        {
                            ReportDoneLocked(head.UtteranceId);
                            _segments.RemoveAt(0);
                        }
                        else
                        {
                            break;
                        }
                    }
                }

                _currentRms = (float)Math.Sqrt(sumSquares / frames);

                if (written < frames)
                {
                    Array.Clear(_fresh, written, frames - written);
                    if (written > 0)
                    {
                        _hadUnderrun = true;
                    }
                }

                // What the analysis sees is the fresh audio; what plays comes out
                // _delaySamples late, so the mouth does not arrive late.
                int delay = _delaySamples;
                if (delay > 0 && _delayLine.Length >= delay + frames)
                {
                    int capacity = _delayLine.Length;
                    int read = _delayWrite - delay;
                    if (read < 0)
                    {
                        read += capacity;
                    }

                    for (int i = 0; i < frames; i++)
                    {
                        _delayLine[_delayWrite] = _fresh[i];
                        _delayWrite++;
                        if (_delayWrite >= capacity)
                        {
                            _delayWrite = 0;
                        }

                        float sample = ApplyGain(_delayLine[read], gainStart + (gainStep * (i + 1)));
                        read++;
                        if (read >= capacity)
                        {
                            read = 0;
                        }

                        int baseIndex = i * channels;
                        for (int c = 0; c < channels; c++)
                        {
                            data[baseIndex + c] = sample;
                        }
                    }
                }
                else
                {
                    for (int i = 0; i < frames; i++)
                    {
                        float sample = ApplyGain(_fresh[i], gainStart + (gainStep * (i + 1)));
                        int baseIndex = i * channels;
                        for (int c = 0; c < channels; c++)
                        {
                            data[baseIndex + c] = sample;
                        }
                    }
                }

                for (int i = 0; i < frames; i++)
                {
                    float sample = _fresh[i];
                    int baseIndex = i * channels;
                    for (int c = 0; c < channels; c++)
                    {
                        _analysis[baseIndex + c] = sample;
                    }
                }
            }

            Action<float[], int> listeners = OnAudioFrame;
            if (listeners != null)
            {
                try
                {
                    // Listeners receive a block of the same size and shape as
                    // data, but with the audio that will play in lipSyncLeadMs.
                    listeners(_analysis, channels);
                }
                catch (Exception)
                {
                    // An analysis failure must not cut the audio.
                }
            }
        }

        /// <summary>
        /// Applies the gain. With volume above 1 (up to 1.5) it goes through a
        /// soft limiter: peaks are rounded instead of being hard-clipped, which
        /// is what distorts. With 1 or less the sample goes out as is. Audio
        /// thread.
        /// </summary>
        private static float ApplyGain(float sample, float gain)
        {
            float value = sample * gain;
            if (gain <= 1f)
            {
                return value;
            }

            const float knee = 0.85f;
            float magnitude = value < 0f ? -value : value;
            if (magnitude <= knee)
            {
                return value;
            }

            float headroom = 1f - knee;
            float over = (magnitude - knee) / headroom;
            float limited = knee + (headroom * (over / (1f + over)));
            return value < 0f ? -limited : limited;
        }

        /// <summary>Records an utterance as played. Lock held.</summary>
        private void ReportDoneLocked(int utteranceId)
        {
            if (utteranceId <= _lastReportedDoneId)
            {
                return;
            }

            _lastReportedDoneId = utteranceId;
            _pendingDone.Add(utteranceId);
        }

        /// <summary>Stretch of audio of one utterance inside the ring buffer.</summary>
        private sealed class Segment
        {
            public readonly int UtteranceId;
            public long TotalSamples;
            public long ConsumedSamples;
            public bool IsLast;

            public Segment(int utteranceId)
            {
                UtteranceId = utteranceId;
            }
        }
    }
}
