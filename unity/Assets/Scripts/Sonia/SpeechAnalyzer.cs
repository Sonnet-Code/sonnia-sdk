// Análisis de la voz de Sonia para la cara: nivel, bandas y prosodia.
//
// El lip-sync y las expresiones no pueden depender solo del clasificador de
// vocales (uLipSync trabaja con ventanas de 64 ms, que emborronan justo lo que
// más se ve: el golpe de cada sílaba y el cierre de los labios en p, b y m).
// Aquí se analiza la voz con ventanas de 5 ms:
//
//  - Nivel en dB con control automático de ganancia: 0..1 respecto al pico
//    reciente, así la boca abre igual con una sesión más baja o más alta.
//  - Energía por bandas (graves 100-500 Hz, medios 500-1500, agudos 1500-3500 y
//    sibilantes 4-10 kHz) para distinguir vocales abiertas, frontales, nasales
//    y la "s".
//  - Eventos de prosodia: arranque de sílaba con su fuerza (para asentir,
//    levantar las cejas o parpadear con la voz), principio y fin de frase.
//
// Hilos: el hilo de audio solo copia muestras (Push) a un anillo; todo el
// cálculo corre en el hilo principal (Process), con el audio que va por
// delante de lo que suena gracias a la línea de retardo de AudioStreamPlayer.
// Cada dato lleva su índice de muestra "fresca" (el reloj del análisis); quien
// consulta pide el instante que quiere (lo que suena ahora más un adelanto).

using System;
using System.Collections.Generic;
using System.Threading;
using UnityEngine;

namespace Sonia
{
    /// <summary>Nivel, bandas y eventos de prosodia de la voz, con ventanas de 5 ms.</summary>
    public sealed class SpeechAnalyzer
    {
        /// <summary>Lo que se sabe de la voz en un instante.</summary>
        public struct Features
        {
            /// <summary>Nivel 0..1 respecto al pico reciente (0 = silencio, 1 = sílaba fuerte).</summary>
            public float Level;

            /// <summary>Nivel suavizado a 25 ms (la "sílaba", sin el grano de cada periodo).</summary>
            public float Syllable;

            /// <summary>Apertura de la vocal 0..1: medios fuertes frente a graves (a frente a i, u).</summary>
            public float Openness;

            /// <summary>Vocal frontal 0..1: agudos frente a medios (i, e).</summary>
            public float Frontness;

            /// <summary>Sibilante 0..1 (s, z, ch, j): energía por encima de 4 kHz sin graves.</summary>
            public float Sibilance;

            /// <summary>Nasal o murmullo 0..1 (m, n): graves sin medios ni agudos.</summary>
            public float Nasality;

            /// <summary>Hay voz (nivel por encima del umbral).</summary>
            public bool Voiced;
        }

        /// <summary>Tipo de evento de prosodia.</summary>
        public enum EventKind
        {
            /// <summary>Arranca una sílaba; Strength es su fuerza 0..1 (las tónicas pasan de 0,7).</summary>
            Syllable,

            /// <summary>Empieza a hablar tras una pausa.</summary>
            PhraseStart,

            /// <summary>Se calla: pausa de más de PauseSeconds.</summary>
            PhraseEnd
        }

        /// <summary>Evento de prosodia con su instante en muestras frescas.</summary>
        public struct SpeechEvent
        {
            public EventKind Kind;
            public long Sample;
            public float Strength;
        }

        private struct Frame
        {
            public float Db;
            public float LowDb;
            public float MidDb;
            public float HighDb;
            public float SibDb;
            public float RefDb;
            public float Fast;
        }

        /// <summary>Filtro bicuadrático (forma directa II transpuesta).</summary>
        private struct Biquad
        {
            private float _b0, _b1, _b2, _a1, _a2, _z1, _z2;

            public static Biquad LowPass(float rate, float freq)
            {
                return Make(rate, freq, 0.7071f, false);
            }

            public static Biquad HighPass(float rate, float freq)
            {
                return Make(rate, freq, 0.7071f, true);
            }

            private static Biquad Make(float rate, float freq, float q, bool high)
            {
                float w0 = 2f * Mathf.PI * Mathf.Clamp(freq, 10f, rate * 0.45f) / rate;
                float cos = Mathf.Cos(w0);
                float alpha = Mathf.Sin(w0) / (2f * q);
                float a0 = 1f + alpha;
                Biquad b = new Biquad();
                if (high)
                {
                    b._b0 = (1f + cos) / 2f / a0;
                    b._b1 = -(1f + cos) / a0;
                    b._b2 = (1f + cos) / 2f / a0;
                }
                else
                {
                    b._b0 = (1f - cos) / 2f / a0;
                    b._b1 = (1f - cos) / a0;
                    b._b2 = (1f - cos) / 2f / a0;
                }

                b._a1 = -2f * cos / a0;
                b._a2 = (1f - alpha) / a0;
                return b;
            }

            public float Run(float x)
            {
                float y = (_b0 * x) + _z1;
                _z1 = (_b1 * x) - (_a1 * y) + _z2;
                _z2 = (_b2 * x) - (_a2 * y);
                return y;
            }

            public void Reset()
            {
                _z1 = 0f;
                _z2 = 0f;
            }
        }

        // ------------------------------------------------------------------
        // Parámetros
        // ------------------------------------------------------------------

        /// <summary>Rango dinámico en dB que va de nivel 0 a nivel 1.</summary>
        public float RangeDb = 30f;

        /// <summary>El pico de referencia nunca baja de aquí (dBFS): la voz floja no se amplifica sin fin.</summary>
        public float MinReferenceDb = -32f;

        /// <summary>Caída del pico de referencia en dB por segundo.</summary>
        public float ReferenceDecayDbPerSecond = 4f;

        /// <summary>Nivel por debajo del cual no hay voz.</summary>
        public float VoiceThreshold = 0.12f;

        /// <summary>Segundos de silencio que cierran una frase.</summary>
        public float PauseSeconds = 0.22f;

        /// <summary>Subida mínima de nivel (0..1) para contar una sílaba nueva.</summary>
        public float SyllableProminence = 0.14f;

        // ------------------------------------------------------------------
        // Estado
        // ------------------------------------------------------------------

        private const int RingSize = 1 << 17;
        private const int HistorySize = 2048;

        private readonly float[] _ring = new float[RingSize];
        private long _written;

        private readonly Frame[] _history = new Frame[HistorySize];
        private long _frames;
        private long _processed;
        private long _historyBase;

        private int _rate;
        private int _hop;
        private Biquad _dc;
        private Biquad _lowHp, _lowLp, _midHp, _midLp, _highHp, _highLp, _sibHp, _sibLp;
        private double _accTotal, _accLow, _accMid, _accHigh, _accSib;
        private int _accCount;
        private float _refDb = -26f;
        private float _fast;

        // Detección de sílabas y pausas (sobre la serie Fast).
        private float _valley = 1f;
        private long _valleyHop;
        private bool _rising;
        private float _peak;
        private int _silentHops;
        private bool _inPhrase;
        private long _lastVoicedHop;

        private readonly Queue<SpeechEvent> _events = new Queue<SpeechEvent>();

        /// <summary>Muestras por ventana de análisis.</summary>
        public int HopSamples
        {
            get { return _hop; }
        }

        /// <summary>Tasa de muestreo del análisis.</summary>
        public int SampleRate
        {
            get { return _rate; }
        }

        /// <summary>Muestras frescas recibidas del hilo de audio (reloj del análisis).</summary>
        public long Written
        {
            get { return Volatile.Read(ref _written); }
        }

        /// <summary>Muestras ya analizadas.</summary>
        public long Processed
        {
            get { return _processed; }
        }

        public SpeechAnalyzer(int sampleRate)
        {
            Configure(sampleRate);
        }

        /// <summary>Prepara los filtros para una tasa de muestreo. Hilo principal.</summary>
        public void Configure(int sampleRate)
        {
            _rate = Mathf.Max(8000, sampleRate);
            _hop = Mathf.Max(32, Mathf.RoundToInt(_rate * 0.005f));
            _dc = Biquad.HighPass(_rate, 70f);
            _lowHp = Biquad.HighPass(_rate, 100f);
            _lowLp = Biquad.LowPass(_rate, 500f);
            _midHp = Biquad.HighPass(_rate, 500f);
            _midLp = Biquad.LowPass(_rate, 1500f);
            _highHp = Biquad.HighPass(_rate, 1500f);
            _highLp = Biquad.LowPass(_rate, 3500f);
            _sibHp = Biquad.HighPass(_rate, 4000f);
            _sibLp = Biquad.LowPass(_rate, Mathf.Min(10000f, _rate * 0.45f));
        }

        // ------------------------------------------------------------------
        // Hilo de audio
        // ------------------------------------------------------------------

        /// <summary>Copia un bloque (intercalado) al anillo. Hilo de audio: sin API de Unity.</summary>
        public void Push(float[] data, int channels)
        {
            if (data == null || channels <= 0)
            {
                return;
            }

            int frames = data.Length / channels;
            long w = _written;
            for (int i = 0; i < frames; i++)
            {
                _ring[(int)((w + i) & (RingSize - 1))] = data[i * channels];
            }

            Volatile.Write(ref _written, w + frames);
        }

        // ------------------------------------------------------------------
        // Hilo principal
        // ------------------------------------------------------------------

        /// <summary>Analiza lo que haya llegado desde la última llamada. Hilo principal, una vez por frame.</summary>
        public void Process()
        {
            long written = Volatile.Read(ref _written);
            if (written - _processed > RingSize / 2)
            {
                // Demasiado atrasado (el editor estuvo parado): se salta al
                // presente. Cada ventana empieza en un múltiplo de _hop, así que el
                // índice de ventana y el de muestra siguen cuadrando.
                long target = written - _hop * 8;
                _processed = target - (target % _hop);
                _frames = _processed / _hop;
                _historyBase = _frames;
                ResetFilters();
            }

            while (_processed < written)
            {
                float x = _dc.Run(_ring[(int)(_processed & (RingSize - 1))]);
                float low = _lowLp.Run(_lowHp.Run(x));
                float mid = _midLp.Run(_midHp.Run(x));
                float high = _highLp.Run(_highHp.Run(x));
                float sib = _sibLp.Run(_sibHp.Run(x));
                _accTotal += x * x;
                _accLow += low * low;
                _accMid += mid * mid;
                _accHigh += high * high;
                _accSib += sib * sib;
                _processed++;
                if (++_accCount >= _hop)
                {
                    EmitFrame();
                }
            }
        }

        private void ResetFilters()
        {
            _dc.Reset();
            _lowHp.Reset();
            _lowLp.Reset();
            _midHp.Reset();
            _midLp.Reset();
            _highHp.Reset();
            _highLp.Reset();
            _sibHp.Reset();
            _sibLp.Reset();
            _accTotal = _accLow = _accMid = _accHigh = _accSib = 0.0;
            _accCount = 0;
        }

        private static float ToDb(double sumSquares, int count)
        {
            double rms = Math.Sqrt(sumSquares / Math.Max(1, count));
            return (float)(20.0 * Math.Log10(rms + 1e-7));
        }

        private void EmitFrame()
        {
            Frame f = new Frame
            {
                Db = ToDb(_accTotal, _accCount),
                LowDb = ToDb(_accLow, _accCount),
                MidDb = ToDb(_accMid, _accCount),
                HighDb = ToDb(_accHigh, _accCount),
                SibDb = ToDb(_accSib, _accCount)
            };
            _accTotal = _accLow = _accMid = _accHigh = _accSib = 0.0;
            _accCount = 0;

            // Pico de referencia: sube al instante, baja despacio y nunca por
            // debajo del mínimo (si no, el ruido de fondo abriría la boca).
            float hopSeconds = _hop / (float)_rate;
            _refDb = Mathf.Max(MinReferenceDb, Mathf.Max(f.Db, _refDb - ReferenceDecayDbPerSecond * hopSeconds));
            f.RefDb = _refDb;

            float level = LevelOf(f);
            // Envolvente de sílaba: ataque de 10 ms y caída de 35 ms.
            float k = level > _fast ? 1f - Mathf.Exp(-hopSeconds / 0.010f) : 1f - Mathf.Exp(-hopSeconds / 0.035f);
            _fast += (level - _fast) * k;
            f.Fast = _fast;

            long hop = _frames;
            if (_frames - _historyBase >= HistorySize)
            {
                _historyBase++;
            }

            _history[(int)(hop % HistorySize)] = f;
            _frames++;
            DetectEvents(hop, _fast);
        }

        private float LevelOf(Frame f)
        {
            return Mathf.Clamp01((f.Db - (f.RefDb - RangeDb)) / Mathf.Max(1f, RangeDb));
        }

        private void DetectEvents(long hop, float fast)
        {
            long sample = hop * _hop;
            bool voiced = fast > VoiceThreshold;
            if (voiced)
            {
                if (!_inPhrase)
                {
                    _inPhrase = true;
                    _events.Enqueue(new SpeechEvent { Kind = EventKind.PhraseStart, Sample = sample, Strength = 1f });
                }

                _silentHops = 0;
                _lastVoicedHop = hop;
            }
            else if (_inPhrase)
            {
                _silentHops++;
                if (_silentHops * _hop >= PauseSeconds * _rate)
                {
                    _inPhrase = false;
                    _events.Enqueue(new SpeechEvent { Kind = EventKind.PhraseEnd, Sample = (_lastVoicedHop + 1) * _hop, Strength = 1f });
                }
            }

            // Sílabas: un valle seguido de una subida de al menos SyllableProminence.
            // El evento se fecha en el valle (donde arranca la sílaba) y su fuerza
            // es el pico que alcanza.
            if (!_rising)
            {
                if (fast < _valley)
                {
                    _valley = fast;
                    _valleyHop = hop;
                }
                else if (fast - _valley >= SyllableProminence && fast > VoiceThreshold)
                {
                    _rising = true;
                    _peak = fast;
                }
            }
            else
            {
                if (fast > _peak)
                {
                    _peak = fast;
                }
                else if (_peak - fast >= SyllableProminence * 0.5f || fast < VoiceThreshold)
                {
                    _events.Enqueue(new SpeechEvent { Kind = EventKind.Syllable, Sample = _valleyHop * _hop, Strength = _peak });
                    _rising = false;
                    _valley = fast;
                    _valleyHop = hop;
                }
            }

            while (_events.Count > 256)
            {
                _events.Dequeue();
            }
        }

        // ------------------------------------------------------------------
        // Consultas
        // ------------------------------------------------------------------

        /// <summary>Saca los eventos fechados hasta <paramref name="upToSample"/> (inclusive).</summary>
        public void TakeEvents(long upToSample, List<SpeechEvent> into)
        {
            while (_events.Count > 0 && _events.Peek().Sample <= upToSample)
            {
                into.Add(_events.Dequeue());
            }
        }

        /// <summary>Descarta los eventos pendientes (interrupción).</summary>
        public void ClearEvents()
        {
            _events.Clear();
        }

        /// <summary>Rasgos de la voz en el instante <paramref name="sample"/> (muestras frescas), interpolados.</summary>
        public Features Sample(double sample)
        {
            Features result = new Features();
            double hopPos = sample / _hop;
            long h0 = (long)Math.Floor(hopPos);
            if (_frames == 0 || h0 < _historyBase || h0 >= _frames)
            {
                return result;
            }

            long h1 = Math.Min(h0 + 1, _frames - 1);
            float t = (float)(hopPos - h0);
            Frame a = _history[(int)(h0 % HistorySize)];
            Frame b = _history[(int)(h1 % HistorySize)];
            float level = Mathf.Lerp(LevelOf(a), LevelOf(b), t);
            result.Level = level;
            result.Syllable = Mathf.Lerp(a.Fast, b.Fast, t);
            result.Voiced = result.Syllable > VoiceThreshold;

            float low = Mathf.Lerp(a.LowDb, b.LowDb, t);
            float mid = Mathf.Lerp(a.MidDb, b.MidDb, t);
            float high = Mathf.Lerp(a.HighDb, b.HighDb, t);
            float sib = Mathf.Lerp(a.SibDb, b.SibDb, t);
            float loudest = Mathf.Max(low, mid);

            // Medido con la voz de Sonia: en las vocales los graves van 10-20 dB
            // por encima de los medios (la a, más cerca); en la s las sibilantes
            // pasan de los graves y medios en 10-30 dB.
            result.Openness = Mathf.Clamp01((mid - low + 16f) / 14f);
            result.Frontness = Mathf.Clamp01((high - mid + 12f) / 14f);
            result.Sibilance = Mathf.Clamp01((sib - loudest + 2f) / 14f) * Mathf.Clamp01(level * 3f);
            result.Nasality = Mathf.Clamp01((low - Mathf.Max(mid, high) - 18f) / 8f) * (result.Voiced ? 1f : 0f);
            return result;
        }

        /// <summary>
        /// Cierre de labios 0..1 en <paramref name="sample"/>: un valle hondo del
        /// nivel entre dos tramos con voz (las oclusivas p, b, t, d, k, g y la
        /// m). Mira <paramref name="windowSeconds"/> a cada lado.
        /// </summary>
        public float ClosureAt(double sample, float windowSeconds)
        {
            Features here = Sample(sample);
            if (here.Syllable > 0.55f)
            {
                return 0f;
            }

            int span = Mathf.Max(1, Mathf.RoundToInt(windowSeconds * _rate / _hop));
            long center = (long)Math.Floor(sample / _hop);
            float before = 0f;
            float after = 0f;
            for (int i = 1; i <= span; i++)
            {
                before = Mathf.Max(before, FastAt(center - i));
                after = Mathf.Max(after, FastAt(center + i));
            }

            // Hace falta voz a los dos lados: un silencio largo no es un cierre
            // de consonante sino reposo, y de eso se ocupa el nivel.
            float sides = Mathf.Min(before, after);
            float depth = sides - here.Syllable;
            return Mathf.Clamp01((depth - 0.18f) / 0.3f) * Mathf.Clamp01(sides / 0.4f);
        }

        private float FastAt(long hop)
        {
            if (hop < _historyBase || hop >= _frames || hop < 0)
            {
                return 0f;
            }

            return _history[(int)(hop % HistorySize)].Fast;
        }

        /// <summary>Primera muestra fresca que aún no se ha analizado (hasta aquí hay datos).</summary>
        public long AnalyzedUpTo
        {
            get { return _frames * _hop; }
        }
    }
}
