// Reproducción en streaming del PCM que llega por el WebSocket.
//
// Reglas de hilos:
//  - Enqueue() se llama desde el hilo principal (despacho de SoniaClient). Ahí
//    se remuestrea el chunk a la tasa de salida y se copia al buffer circular.
//  - OnAudioFilterRead() corre en el hilo de audio y consume ese buffer.
//  - El buffer, la lista de segmentos y los contadores se protegen con un lock.
//    Las secciones críticas son copias de memoria: no se llama a la API de Unity
//    dentro del lock desde el hilo de audio.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>
    /// Cola de audio PCM con remuestreo lineal, contabilidad por frase y aviso de
    /// fin de reproducción. El lip-sync se apoya en <see cref="CurrentUtteranceId"/>
    /// y <see cref="CurrentUtteranceTime"/> para saber qué suena y por dónde va.
    /// </summary>
    [RequireComponent(typeof(AudioSource))]
    [DisallowMultipleComponent]
    public class AudioStreamPlayer : MonoBehaviour
    {
        [Header("Formato de entrada")]
        [SerializeField]
        [Tooltip("Tasa de muestreo del audio que envía el orquestador. El mensaje hello la sobrescribe.")]
        private int sourceSampleRate = Protocol.DefaultSampleRate;

        [Header("Buffer")]
        [SerializeField]
        [Tooltip("Segundos de audio que reserva el buffer circular al arrancar. Crece solo si hace falta.")]
        private float initialBufferSeconds = 4f;

        [SerializeField]
        [Tooltip("Tope del buffer circular en segundos. Por encima se descarta el audio que no cabe.")]
        private float maxBufferSeconds = 120f;

        [Header("Salida")]
        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Ganancia aplicada a las muestras antes de escribirlas en la salida.")]
        private float volume = 1f;

        [SerializeField]
        [Tooltip("Avisa en la consola cuando el buffer se queda vacío en mitad de una frase.")]
        private bool logUnderruns;

        /// <summary>
        /// Se dispara en el hilo principal cuando se ha consumido la última muestra
        /// de una frase marcada como terminada. El argumento es el utterance_id.
        /// </summary>
        public event Action<int> OnUtterancePlaybackDone;

        /// <summary>
        /// Audio que acaba de salir por el AudioSource, en el hilo de audio:
        /// muestras intercaladas y número de canales. Lo consume el análisis de
        /// fonemas del lip-sync. No tocar Unity desde aquí.
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

        // ------------------------------------------------------------------
        // Propiedades para el lip-sync y la interfaz de depuración
        // ------------------------------------------------------------------

        /// <summary>Frase que se está reproduciendo, o -1 si no suena nada.</summary>
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

        /// <summary>Segundos ya reproducidos de la frase actual.</summary>
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

        /// <summary>Nivel RMS del último bloque de audio escrito, entre 0 y 1.</summary>
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

        /// <summary>Segundos de audio pendientes de reproducir.</summary>
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

        /// <summary>Cierto si queda audio por reproducir.</summary>
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

        /// <summary>Tasa de muestreo de salida del motor de audio.</summary>
        public int OutputSampleRate
        {
            get { return _outputSampleRate; }
        }

        /// <summary>
        /// Lee de una sola vez la posición de reproducción y el nivel, para que el
        /// lip-sync tome el lock una vez por frame en lugar de tres.
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
        // Ciclo de vida
        // ------------------------------------------------------------------

        private void Awake()
        {
            _audioSource = GetComponent<AudioSource>();
            RefreshOutputSampleRate();
            AllocateRing(initialBufferSeconds);

            // OnAudioFilterRead solo se llama si el AudioSource está sonando, así
            // que se reproduce en bucle un clip de silencio de un segundo.
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
                    Debug.Log("[Sonia] El buffer de audio se quedó corto; se rellenó con silencio.", this);
                }
            }

            if (_droppedAudio)
            {
                _droppedAudio = false;
                Debug.LogWarning("[Sonia] Buffer de audio lleno: se descartaron muestras.", this);
            }
        }

        // ------------------------------------------------------------------
        // API pública
        // ------------------------------------------------------------------

        /// <summary>Ajusta la tasa de muestreo de entrada anunciada en <c>hello</c>.</summary>
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

        /// <summary>Encola un chunk de audio recién llegado (hilo principal).</summary>
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
        /// Marca una frase como terminada aunque no haya llegado el bit de último
        /// chunk. Se llama al recibir <c>speech_end</c>. Si la frase ya se reprodujo
        /// entera (o nunca trajo audio), avisa de inmediato.
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
        /// Vacía todo el audio en cola y la contabilidad de frases. Se usa con
        /// <c>stop_speaking</c>: no se avisa de reproducción terminada porque el
        /// orquestador ya canceló el turno.
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
            }
        }

        // ------------------------------------------------------------------
        // Remuestreo (hilo principal)
        // ------------------------------------------------------------------

        /// <summary>
        /// Remuestrea linealmente de la tasa del orquestador a la de salida y deja
        /// el resultado en <c>_scratch</c>. Conserva la fase y la última muestra
        /// entre chunks para que no haya chasquidos en las uniones.
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

        /// <summary>Agranda el buffer circular conservando lo que ya había. Con el lock tomado.</summary>
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
        // Hilo de audio
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
            float gain = volume;

            lock (_lock)
            {
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

                                // Falta audio de esta frase: se rellena con silencio
                                // y el tiempo de la frase no avanza.
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
                            float sample = _ring[_readPosition] * gain;
                            _readPosition++;
                            if (_readPosition >= _ring.Length)
                            {
                                _readPosition = 0;
                            }

                            int baseIndex = (written + i) * channels;
                            for (int c = 0; c < channels; c++)
                            {
                                data[baseIndex + c] = sample;
                            }

                            sumSquares += sample * sample;
                        }

                        _available -= chunk;
                        written += chunk;
                        if (segment != null)
                        {
                            segment.ConsumedSamples += chunk;
                        }
                    }

                    // Una frase puede haber terminado justo con la última muestra.
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
            }

            if (written < frames)
            {
                Array.Clear(data, written * channels, (frames - written) * channels);
                if (written > 0)
                {
                    _hadUnderrun = true;
                }
            }

            Action<float[], int> listeners = OnAudioFrame;
            if (listeners != null)
            {
                try
                {
                    listeners(data, channels);
                }
                catch (Exception)
                {
                    // Un fallo del análisis no debe cortar el audio.
                }
            }
        }

        /// <summary>Anota una frase como reproducida. Con el lock tomado.</summary>
        private void ReportDoneLocked(int utteranceId)
        {
            if (utteranceId <= _lastReportedDoneId)
            {
                return;
            }

            _lastReportedDoneId = utteranceId;
            _pendingDone.Add(utteranceId);
        }

        /// <summary>Tramo de audio de una misma frase dentro del buffer circular.</summary>
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
