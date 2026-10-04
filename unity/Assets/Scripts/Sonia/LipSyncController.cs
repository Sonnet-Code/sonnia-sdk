// Lip-sync del avatar a partir de la voz que suena.
//
// La boca se compone, cada frame, de tres cosas medidas en el audio:
//
//  1. Cuánto abre: la envolvente de sílaba (SpeechAnalyzer, ventanas de 5 ms y
//     control de ganancia). Es lo que más se nota desde lejos y lo que nunca
//     puede ir a destiempo, así que se toma del propio audio con un pequeño
//     adelanto: la boca se prepara un poco antes de que suene la sílaba, como
//     en una persona.
//  2. Con qué forma: la vocal que reconoce uLipSync (A, E, I, O, U) a través de
//     PhonemeLipSyncBridge, suavizada y mezclada con una forma neutra según lo
//     seguro que esté, porque una "o" que no toca se ve más que una "a" de más.
//  3. Las consonantes que se ven: cierre de labios en los valles hondos entre
//     sílabas (p, b, m y el resto de oclusivas) y dientes juntos en la "s".
//
// La boca se escribe en los canales de FaceRig (viseme_aa, viseme_PP...,
// jawOpen), que los traduce a las formas del avatar: en los de Genies, a las
// recetas FACS. Los visemas se usan casi enteros (con 0,2 la boca apenas se
// entreabría) y la mandíbula se suma en las sílabas fuertes. Todo pasa por
// muelles críticamente amortiguados.
//
// También reparte la prosodia: los eventos de sílaba y de frase del analizador
// salen por OnSpeechEvent cuando les llega su momento, para que cabeza, cejas y
// parpadeo vayan con la voz.
//
// Los visemas y la envolvente que mandaba el orquestador antiguo ya no llegan
// con GPT-Live; SetVisemes y SetEnvelope se quedan sin efecto por compatibilidad.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Mueve la boca con la voz que suena y reparte los eventos de prosodia.</summary>
    [DefaultExecutionOrder(12000)]
    [DisallowMultipleComponent]
    public class LipSyncController : MonoBehaviour
    {
        [Header("Referencias")]
        [SerializeField]
        [Tooltip("Cara del avatar: la boca se escribe en sus canales de visemas y jawOpen.")]
        private FaceRig faceRig;

        [SerializeField]
        [Tooltip("Reproductor del audio en streaming: de él sale la voz que se analiza.")]
        private AudioStreamPlayer audioPlayer;

        [Header("Sincronía")]
        [SerializeField]
        [Range(40f, 200f)]
        [Tooltip("Retardo de la voz respecto al análisis (ms). Es lo que la cara puede ver por delante: adelanto de la boca, cierres antes de la p y gestos que preceden a la sílaba. Se aplica a AudioStreamPlayer al arrancar si el suyo es menor.")]
        public float voiceDelayMs = 100f;

        [SerializeField]
        [Range(-60f, 120f)]
        [Tooltip("Cuánto se adelanta la boca a lo que suena (ms). Positivo: la boca va antes, como en el habla real.")]
        public float mouthLeadMs = 35f;

        [SerializeField]
        [Range(0f, 160f)]
        [Tooltip("Cuánto se adelantan los gestos (cabeza, cejas, parpadeo) a su sílaba (ms).")]
        public float gestureLeadMs = 70f;

        [SerializeField]
        [Range(-1f, 200f)]
        [Tooltip("Latencia de la salida de audio en ms (lo que tarda el bloque en sonar). -1: un búfer DSP.")]
        public float outputLatencyMs = -1f;

        [Header("Boca")]
        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Peso del visema de la vocal en una sílaba fuerte. Con 1 la boca hace la forma completa de Ready Player Me.")]
        public float vowelWeight = 0.85f;

        [SerializeField]
        [Range(0.3f, 1.5f)]
        [Tooltip("Curva de apertura: menos de 1 abre antes con voz floja.")]
        public float openCurve = 1f;

        [SerializeField]
        [Range(0f, 0.6f)]
        [Tooltip("Mandíbula extra (jawOpen) en las sílabas más fuertes con vocal abierta.")]
        public float jawBoost = 0.18f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Cuánto manda la vocal reconocida frente a una forma neutra (a, e).")]
        public float vowelTrust = 0.75f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Cierre de labios (viseme_PP) en los valles entre sílabas: p, b, m y demás oclusivas.")]
        public float closureWeight = 0.85f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Dientes juntos (viseme_SS) en la s.")]
        public float sibilantWeight = 0.5f;

        [SerializeField]
        [Range(2f, 20f)]
        [Tooltip("Velocidad de la boca (Hz del muelle). Más alto, más nítida; más bajo, más blanda.")]
        public float mouthSpeed = 10f;

        [SerializeField]
        [Range(2f, 30f)]
        [Tooltip("Velocidad del cierre de labios (Hz del muelle). Un cierre lento no se ve.")]
        public float closureSpeed = 16f;

        [SerializeField]
        [Range(0.01f, 0.2f)]
        [Tooltip("Constante de tiempo (s) del suavizado de la vocal reconocida. Muy baja: la forma tiembla.")]
        public float vowelSmoothing = 0.05f;

        /// <summary>Evento de prosodia cuando le llega su momento (ver gestureLeadMs). Hilo principal.</summary>
        public event Action<SpeechAnalyzer.SpeechEvent> OnSpeechEvent;

        // Vocales en el orden de los canales de la boca.
        private const int VA = 0, VE = 1, VI = 2, VO = 3, VU = 4;
        private static readonly string[] VowelChannels = { "viseme_aa", "viseme_E", "viseme_I", "viseme_O", "viseme_U" };

        // Forma neutra de una sílaba cuando no se sabe la vocal: abierta y relajada.
        private static readonly float[] NeutralMix = { 0.6f, 0.3f, 0.1f, 0f, 0f };

        private struct VowelSample
        {
            public long Sample;
            public float A, E, I, O, U;
        }

        private SpeechAnalyzer _analyzer;
        private readonly List<SpeechAnalyzer.SpeechEvent> _eventBuffer = new List<SpeechAnalyzer.SpeechEvent>();
        private readonly VowelSample[] _vowels = new VowelSample[64];
        private int _vowelCount;
        private int _vowelHead;
        private long _writtenLastFrame;
        private bool _subscribed;

        private bool _hasVisemeShapes;
        private readonly int[] _vowelChannels = { -1, -1, -1, -1, -1 };
        private int _ppChannel = -1;
        private int _ssChannel = -1;
        private int _jawChannel = -1;

        private double _clock;
        private bool _clockReady;
        private readonly float[] _mix = { 0.6f, 0.3f, 0.1f, 0f, 0f };
        private Spring _open;
        private Spring _closure;
        private Spring _sibilant;
        private Spring _jaw;
        private readonly Spring[] _vowelSprings = new Spring[5];
        private float _roundness;
        private bool _active;

        /// <summary>Cierto si la cara tiene canales de visemas utilizables.</summary>
        public bool HasVisemeShapes
        {
            get { return _hasVisemeShapes; }
        }

        /// <summary>Apertura actual de la boca, 0..1. Sirve para acompasar gestos a la voz.</summary>
        public float MouthOpen
        {
            get { return Mathf.Clamp01(_open.Value); }
        }

        /// <summary>Cuánto redondea los labios ahora (o, u), 0..1: con la boca redonda no cabe una sonrisa ancha.</summary>
        public float Roundness
        {
            get { return _roundness; }
        }

        /// <summary>Cierto mientras hay voz en la boca (sílabas sonando o a punto de sonar).</summary>
        public bool IsTalking
        {
            get { return _active; }
        }

        /// <summary>Cierto mientras la vocal llega del análisis de fonemas en tiempo real.</summary>
        public bool UsingPhonemes
        {
            get { return _vowelCount > 0; }
        }

        /// <summary>Analizador de la voz (nivel, bandas, prosodia). Puede ser null sin reproductor.</summary>
        public SpeechAnalyzer Analyzer
        {
            get { return _analyzer; }
        }

        /// <summary>Muestra (reloj del análisis) que suena ahora mismo.</summary>
        public double AudibleSample
        {
            get { return _clock; }
        }

        /// <summary>Muestras de latencia de la salida que se están suponiendo (para el laboratorio).</summary>
        public int OutputLatencySamples
        {
            get { return LatencySamples(); }
        }

        /// <summary>Cara del avatar. Al cambiarla se vuelven a resolver los canales.</summary>
        public FaceRig FaceRig
        {
            get { return faceRig; }
            set
            {
                if (faceRig != null)
                {
                    faceRig.Rebuilt -= RebindBlendShapes;
                }

                faceRig = value;
                if (faceRig != null && isActiveAndEnabled)
                {
                    faceRig.Rebuilt += RebindBlendShapes;
                }

                RebindBlendShapes();
            }
        }

        private void Awake()
        {
            if (audioPlayer == null)
            {
                audioPlayer = GetComponentInParent<AudioStreamPlayer>();
            }

            if (audioPlayer != null)
            {
                _analyzer = new SpeechAnalyzer(audioPlayer.OutputSampleRate);
                if (audioPlayer.LipSyncLeadMs < voiceDelayMs)
                {
                    audioPlayer.LipSyncLeadMs = voiceDelayMs;
                }
            }

            RebindBlendShapes();
        }

        private void OnEnable()
        {
            if (audioPlayer != null && _analyzer != null && !_subscribed)
            {
                audioPlayer.OnAudioFrame += _analyzer.Push;
                _subscribed = true;
            }

            if (faceRig != null)
            {
                faceRig.Rebuilt -= RebindBlendShapes;
                faceRig.Rebuilt += RebindBlendShapes;
            }
        }

        private void OnDisable()
        {
            if (audioPlayer != null && _analyzer != null && _subscribed)
            {
                audioPlayer.OnAudioFrame -= _analyzer.Push;
                _subscribed = false;
            }

            if (faceRig != null)
            {
                faceRig.Rebuilt -= RebindBlendShapes;
            }
        }

        /// <summary>Resuelve los canales de la boca en la cara. Se llama sola y al cambiar de avatar.</summary>
        public void RebindBlendShapes()
        {
            _hasVisemeShapes = false;
            for (int v = 0; v < VowelChannels.Length; v++)
            {
                _vowelChannels[v] = faceRig != null ? faceRig.Channel(VowelChannels[v]) : -1;
                _hasVisemeShapes |= _vowelChannels[v] >= 0;
            }

            _ppChannel = faceRig != null ? faceRig.Channel("viseme_PP") : -1;
            _ssChannel = faceRig != null ? faceRig.Channel("viseme_SS") : -1;
            _jawChannel = faceRig != null ? faceRig.Channel("jawOpen") : -1;
            if (_jawChannel < 0 && faceRig != null)
            {
                _jawChannel = faceRig.Channel("mouthOpen");
            }
        }

        /// <summary>
        /// Factor que convierte un peso de 0..100 a la escala real de la malla:
        /// 1 para FBX/VRM (frames a 100) y 0,01 para GLB de glTFast (frames a 1).
        /// </summary>
        public static float BlendShapeScale(Mesh mesh)
        {
            if (mesh == null || mesh.blendShapeCount == 0)
            {
                return 1f;
            }

            int frames = mesh.GetBlendShapeFrameCount(0);
            float full = frames > 0 ? mesh.GetBlendShapeFrameWeight(0, frames - 1) : 100f;
            return full > 0.0001f ? full / 100f : 1f;
        }

        /// <summary>Busca un blendshape por nombre, sin distinguir mayúsculas y aceptando el prefijo con punto.</summary>
        public static int FindBlendShape(Mesh mesh, string name)
        {
            if (mesh == null || string.IsNullOrEmpty(name))
            {
                return -1;
            }

            int direct = mesh.GetBlendShapeIndex(name);
            if (direct >= 0)
            {
                return direct;
            }

            int total = mesh.blendShapeCount;
            for (int i = 0; i < total; i++)
            {
                string candidate = mesh.GetBlendShapeName(i);
                if (string.IsNullOrEmpty(candidate))
                {
                    continue;
                }

                if (string.Equals(candidate, name, StringComparison.OrdinalIgnoreCase))
                {
                    return i;
                }

                int dot = candidate.LastIndexOf('.');
                if (dot >= 0 && dot + 1 < candidate.Length
                    && string.Equals(candidate.Substring(dot + 1), name, StringComparison.OrdinalIgnoreCase))
                {
                    return i;
                }
            }

            return -1;
        }

        // ------------------------------------------------------------------
        // Entradas
        // ------------------------------------------------------------------

        /// <summary>
        /// Proporciones de vocal que reconoce uLipSync (PhonemeLipSyncBridge),
        /// calculadas sobre una ventana de <paramref name="windowSamples"/>
        /// muestras que acaba en el último audio que vio el analizador.
        /// </summary>
        public void PushVowelRatios(float a, float i, float u, float e, float o, int windowSamples)
        {
            float sum = a + i + u + e + o;
            if (sum <= 0.0001f)
            {
                return;
            }

            VowelSample sample = new VowelSample
            {
                // El análisis de fonemas de este frame usó el audio que había al
                // terminar el anterior; la ventana se fecha en su centro.
                Sample = _writtenLastFrame - (windowSamples / 2),
                A = a / sum,
                E = e / sum,
                I = i / sum,
                O = o / sum,
                U = u / sum
            };
            _vowelHead = (_vowelHead + 1) % _vowels.Length;
            _vowels[_vowelHead] = sample;
            _vowelCount = Mathf.Min(_vowelCount + 1, _vowels.Length);
        }

        /// <summary>Compatibilidad: los visemas por texto del orquestador ya no se usan (la boca sale del audio).</summary>
        public void SetVisemes(VisemesMessage message)
        {
        }

        /// <summary>Compatibilidad: la envolvente del orquestador ya no se usa (el nivel se mide aquí).</summary>
        public void SetEnvelope(EnvelopeMessage message)
        {
        }

        /// <summary>Una frase terminó de sonar. No hay nada que soltar: todo se mide sobre la marcha.</summary>
        public void NotifyUtteranceFinished(int utteranceId)
        {
        }

        /// <summary>Interrupción: se olvida la voz pendiente y la boca se cierra en el acto.</summary>
        public void StopAndClose()
        {
            if (_analyzer != null)
            {
                _analyzer.ClearEvents();
            }

            _open.Reset();
            _closure.Reset();
            _sibilant.Reset();
            _jaw.Reset();
            for (int v = 0; v < _vowelSprings.Length; v++)
            {
                _vowelSprings[v].Reset();
            }

            _vowelCount = 0;
            _active = false;
            _roundness = 0f;
            Apply(0f);
        }

        /// <summary>Estado interno en texto, para depurar desde el editor o el HUD.</summary>
        public string DebugInfo()
        {
            return "face=" + (faceRig != null && faceRig.PrimaryRenderer != null ? faceRig.PrimaryRenderer.name : "null")
                   + " visemas=" + _hasVisemeShapes
                   + " reloj=" + _clock.ToString("F0")
                   + " abre=" + _open.Value.ToString("F2")
                   + " cierre=" + _closure.Value.ToString("F2")
                   + " s=" + _sibilant.Value.ToString("F2")
                   + " vocal=[" + _mix[VA].ToString("F2") + " " + _mix[VE].ToString("F2") + " " + _mix[VI].ToString("F2")
                   + " " + _mix[VO].ToString("F2") + " " + _mix[VU].ToString("F2") + "]";
        }

        // ------------------------------------------------------------------
        // Animación
        // ------------------------------------------------------------------

        private void Update()
        {
            if (_analyzer == null)
            {
                return;
            }

            // Lo que haya llegado del hilo de audio se analiza antes de que nadie
            // (cara, cabeza) lo consulte en LateUpdate.
            _writtenLastFrame = _analyzer.Written;
            _analyzer.Process();
            AdvanceClock(Time.deltaTime);
            DispatchEvents();
        }

        private int LatencySamples()
        {
            int rate = _analyzer != null ? _analyzer.SampleRate : 48000;
            if (outputLatencyMs >= 0f)
            {
                return Mathf.RoundToInt(outputLatencyMs / 1000f * rate);
            }

            int length;
            int buffers;
            AudioSettings.GetDSPBufferSize(out length, out buffers);
            return Mathf.Max(0, length);
        }

        /// <summary>
        /// Reloj de lo que suena: lo último que vio el análisis menos el retardo
        /// de la voz y la latencia de salida. Los bloques de audio llegan a
        /// saltos (21 ms con 1024 muestras a 48 kHz), así que el reloj avanza con
        /// el tiempo del juego y se corrige poco a poco hacia la medida.
        /// </summary>
        private void AdvanceClock(float dt)
        {
            int rate = _analyzer.SampleRate;
            float delayMs = audioPlayer != null ? audioPlayer.LipSyncLeadMs : 0f;
            double measured = _analyzer.Written - (delayMs / 1000.0 * rate) - LatencySamples();
            if (!_clockReady || Math.Abs(measured - _clock) > rate * 0.1)
            {
                _clock = measured;
                _clockReady = true;
                return;
            }

            _clock += dt * rate;
            _clock += (measured - _clock) * Mathf.Clamp01(dt * 6f);
        }

        private void DispatchEvents()
        {
            _eventBuffer.Clear();
            double horizon = _clock + gestureLeadMs / 1000.0 * _analyzer.SampleRate;
            _analyzer.TakeEvents((long)horizon, _eventBuffer);
            Action<SpeechAnalyzer.SpeechEvent> handler = OnSpeechEvent;
            for (int i = 0; i < _eventBuffer.Count; i++)
            {
                if (handler != null)
                {
                    handler(_eventBuffer[i]);
                }
            }
        }

        private void LateUpdate()
        {
            float dt = Time.deltaTime;
            if (_analyzer == null)
            {
                return;
            }

            int rate = _analyzer.SampleRate;
            double at = _clock + mouthLeadMs / 1000.0 * rate;
            SpeechAnalyzer.Features f = _analyzer.Sample(at);
            float closure = _analyzer.ClosureAt(at, 0.07f);
            float nasal = f.Nasality * 0.5f;
            closure = Mathf.Max(closure, nasal);

            // Apertura: la envolvente de sílaba con su curva, recortada por el
            // cierre de labios y por la s (dientes juntos).
            float open = Mathf.Pow(Mathf.Clamp01(f.Syllable), openCurve);
            float sib = f.Sibilance;
            float openTarget = open * (1f - closure) * (1f - 0.6f * sib);
            _active = f.Voiced || openTarget > 0.05f;

            UpdateVowelMix(at, dt);

            _open.Step(openTarget, mouthSpeed * 1.4f, mouthSpeed, dt);
            _closure.Step(closure * closureWeight, closureSpeed, closureSpeed * 0.7f, dt);
            _sibilant.Step(sib * sibilantWeight * (1f - closure), mouthSpeed, dt);

            float a = Mathf.Clamp01(_open.Value);
            for (int v = 0; v < _vowelSprings.Length; v++)
            {
                _vowelSprings[v].Step(a * vowelWeight * _mix[v], mouthSpeed * 1.4f, mouthSpeed, dt);
            }

            float jawTarget = jawBoost * Mathf.Clamp01((a - 0.5f) / 0.5f) * (_mix[VA] + 0.6f * _mix[VO] + 0.3f * _mix[VE]);
            _jaw.Step(jawTarget, mouthSpeed, dt);
            _roundness = Mathf.Clamp01((_mix[VO] + _mix[VU]) * a * 1.6f);
            Apply(a);
        }

        /// <summary>Mezcla de vocales en el instante pedido: la del clasificador, suavizada y con confianza.</summary>
        private void UpdateVowelMix(double at, float dt)
        {
            float a, e, i, o, u;
            if (!SampleVowels(at, out a, out e, out i, out o, out u))
            {
                // Sin clasificador: forma neutra.
                a = NeutralMix[VA];
                e = NeutralMix[VE];
                i = NeutralMix[VI];
                o = NeutralMix[VO];
                u = NeutralMix[VU];
            }

            // Se afila la distribución (una vocal clara manda) y se mide la
            // confianza: con 0,2 en cada vocal no se sabe nada; con 0,6 en una, sí.
            float sa = a * a, se = e * e, si = i * i, so = o * o, su = u * u;
            float sum = Mathf.Max(0.0001f, sa + se + si + so + su);
            float max = Mathf.Max(Mathf.Max(a, e), Mathf.Max(Mathf.Max(i, o), u));
            float trust = Mathf.Clamp01((max - 0.3f) / 0.35f) * vowelTrust;
            float k = 1f - Mathf.Exp(-dt / Mathf.Max(0.005f, vowelSmoothing));
            _mix[VA] = Mathf.Lerp(_mix[VA], Mathf.Lerp(NeutralMix[VA], sa / sum, trust), k);
            _mix[VE] = Mathf.Lerp(_mix[VE], Mathf.Lerp(NeutralMix[VE], se / sum, trust), k);
            _mix[VI] = Mathf.Lerp(_mix[VI], Mathf.Lerp(NeutralMix[VI], si / sum, trust), k);
            _mix[VO] = Mathf.Lerp(_mix[VO], Mathf.Lerp(NeutralMix[VO], so / sum, trust), k);
            _mix[VU] = Mathf.Lerp(_mix[VU], Mathf.Lerp(NeutralMix[VU], su / sum, trust), k);
        }

        private bool SampleVowels(double at, out float a, out float e, out float i, out float o, out float u)
        {
            a = e = i = o = u = 0f;
            if (_vowelCount == 0)
            {
                return false;
            }

            // La muestra más cercana al instante pedido (las hay cada frame).
            int best = -1;
            double bestDistance = double.MaxValue;
            for (int n = 0; n < _vowelCount; n++)
            {
                int index = (_vowelHead - n + _vowels.Length) % _vowels.Length;
                double distance = Math.Abs(_vowels[index].Sample - at);
                if (distance < bestDistance)
                {
                    bestDistance = distance;
                    best = index;
                }
            }

            if (best < 0 || bestDistance > _analyzer.SampleRate * 0.25)
            {
                return false;
            }

            VowelSample s = _vowels[best];
            a = s.A;
            e = s.E;
            i = s.I;
            o = s.O;
            u = s.U;
            return true;
        }

        private void Apply(float open)
        {
            if (faceRig == null)
            {
                return;
            }

            // FaceRig suma lo de todos y escribe una vez: varios canales comparten
            // formas (en Genies casi todas las vocales llevan JAW_DROP).
            float keep = 1f - Mathf.Clamp01(_closure.Value);
            for (int v = 0; v < _vowelChannels.Length; v++)
            {
                faceRig.Add(_vowelChannels[v], _vowelSprings[v].Value * keep);
            }

            faceRig.Add(_ppChannel, _closure.Value);
            faceRig.Add(_ssChannel, _sibilant.Value);

            // Sin visemas (avatares con solo jawOpen), la mandíbula hace todo el trabajo.
            float jaw = _hasVisemeShapes ? _jaw.Value * keep : open * 0.5f * keep;
            faceRig.Add(_jawChannel, Mathf.Clamp01(jaw));
        }
    }
}
