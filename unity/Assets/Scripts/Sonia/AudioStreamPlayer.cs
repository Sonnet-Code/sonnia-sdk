// Reproducción en streaming del PCM que llega por el WebSocket.
//
// Reglas de hilos:
//  - Enqueue() se llama desde el hilo principal (despacho de SoniaClient). Ahí
//    se remuestrea el chunk a la tasa de salida y se copia al buffer circular.
//  - OnAudioFilterRead() corre en el hilo de audio y consume ese buffer.
//  - El buffer, la lista de segmentos y los contadores se protegen con un lock.
//    Las secciones críticas son copias de memoria: no se llama a la API de Unity
//    dentro del lock desde el hilo de audio.
//
// Sincronía con la boca: el análisis de fonemas (oyentes de OnAudioFrame) ve
// el audio "fresco" y la salida real sale lipSyncLeadMs por detrás a través de
// una pequeña línea de retardo. Medido con la voz de Gemini: sin adelanto la
// boca llegaba unos 75 ms tarde respecto al bloque generado (análisis, frame de
// espera y suavizado), es decir, 40-50 ms tarde respecto al altavoz.

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
        [Range(0f, MaxVolume)]
        [Tooltip("Volumen de la voz (1 = normal). Lo cambia el mensaje set_volume del orquestador. Solo afecta a lo que suena: el lip-sync analiza el audio antes de la ganancia, así que la boca se mueve igual a cualquier volumen.")]
        private float volume = 1f;

        [SerializeField]
        [Tooltip("Avisa en la consola cuando el buffer se queda vacío en mitad de una frase.")]
        private bool logUnderruns;

        [Header("Lip-sync")]
        [SerializeField]
        [Range(0f, 200f)]
        [Tooltip("Milisegundos que la salida de audio va por detrás del análisis de fonemas. El análisis, el frame de espera y el suavizado de la boca suman unos 75 ms; con este adelanto la boca llega a la vez que la voz (medido: sin él va 40-50 ms tarde respecto al altavoz). 0 lo desactiva.")]
        private float lipSyncLeadMs = 60f;

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

        // Ganancia que se aplicó en el último bloque. Solo la toca el hilo de
        // audio: un cambio de volumen se reparte en rampa a lo largo de un
        // bloque para que no chasquee.
        private float _appliedGain = 1f;

        // Línea de retardo mono entre el análisis (lo que ven los oyentes de
        // OnAudioFrame) y la salida real. Solo la toca el hilo de audio salvo en
        // Flush y al reconfigurar, siempre con el lock.
        private float[] _fresh = new float[0];
        private float[] _analysis = new float[0];
        private float[] _delayLine = new float[0];
        private int _delayWrite;
        private int _delaySamples;

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

        /// <summary>Volumen máximo que acepta <see cref="SetVolume"/> (el del protocolo).</summary>
        public const float MaxVolume = 1.5f;

        /// <summary>Volumen actual de la voz (0 a <see cref="MaxVolume"/>; 1 es el normal).</summary>
        public float Volume
        {
            get { return volume; }
        }

        /// <summary>
        /// Cambia el volumen de la voz (mensaje <c>set_volume</c>). Se recorta a
        /// 0..<see cref="MaxVolume"/> y se aplica en rampa en el siguiente bloque
        /// de audio. Hilo principal.
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
            volume = Mathf.Clamp(volume, 0f, MaxVolume);
            _appliedGain = volume;
            RefreshOutputSampleRate();
            AllocateRing(initialBufferSeconds);
            ConfigureDelayLine();

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

        /// <summary>Milisegundos de adelanto del lip-sync sobre la salida de audio.</summary>
        public float LipSyncLeadMs
        {
            get { return lipSyncLeadMs; }
            set
            {
                lipSyncLeadMs = Mathf.Clamp(value, 0f, 200f);
                ConfigureDelayLine();
            }
        }

        /// <summary>Dimensiona la línea de retardo según el adelanto pedido. Hilo principal.</summary>
        private void ConfigureDelayLine()
        {
            int samples = Mathf.RoundToInt(Mathf.Clamp(lipSyncLeadMs, 0f, 200f) / 1000f * _outputSampleRate);
            lock (_lock)
            {
                _delaySamples = samples;
                // Capacidad: retardo más el bloque más grande que Unity pide de una vez.
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
                Array.Clear(_delayLine, 0, _delayLine.Length);
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

            // Rampa de ganancia de un bloque: de la que sonó en el bloque anterior
            // a la pedida ahora. Con el volumen quieto es constante.
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
                    // Mismo tamaño exacto que data: los oyentes recorren el bloque entero.
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
                            // Sin ganancia: el análisis y el RMS ven la voz tal cual.
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

                if (written < frames)
                {
                    Array.Clear(_fresh, written, frames - written);
                    if (written > 0)
                    {
                        _hadUnderrun = true;
                    }
                }

                // Lo que ve el análisis es el audio fresco; lo que suena sale con
                // _delaySamples de retraso, para que la boca no llegue tarde.
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
                    // Los oyentes reciben un bloque del mismo tamaño y forma que
                    // data, pero con el audio que sonará dentro de lipSyncLeadMs.
                    listeners(_analysis, channels);
                }
                catch (Exception)
                {
                    // Un fallo del análisis no debe cortar el audio.
                }
            }
        }

        /// <summary>
        /// Aplica la ganancia. Con volumen por encima de 1 (hasta 1,5) pasa por un
        /// limitador suave: los picos se redondean en lugar de recortarse en
        /// seco, que es lo que distorsiona. Con 1 o menos la muestra sale tal
        /// cual, como siempre. Hilo de audio.
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
