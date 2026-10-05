// Expresiones faciales: cejas, párpados, mejillas, sonrisa y gestos de labios.
//
// Una cara que solo mueve la boca parece un muñeco. Sobre los blendshapes ARKit
// del avatar se compone, cada frame:
//
//  - Una sonrisa de base constante, como la emoción "Happy" que Mia lleva
//    siempre puesta (docs/informe-mia.md), y encima un gesto por estado:
//    escuchando, cejas algo arriba y sonrisa abierta (interés); pensando, una
//    ceja arriba y la otra abajo, los labios apretados y llevados a un lado
//    ("mmm", con media sonrisa de base); hablando, sonrisa de conversación.
//  - La voz: en los acentos (AvatarStateController.OnEmphasis, el mismo instante
//    que la cascada del cuerpo) suben las cejas y se abren un poco los ojos; el
//    arranque de cada frase hace un "flash" de cejas y el final, una sonrisa que
//    sube y baja. Los eventos llegan del analizador de voz de LipSyncController
//    un poco antes de su sílaba, como en una persona.
//  - Microexpresiones al azar en reposo y escuchando (cejas, media sonrisa,
//    labios apretados, entornar los ojos), para que la cara nunca esté quieta.
//  - Coordinación con la boca: con los labios redondos (o, u) o cerrados (p, b,
//    m) la sonrisa baja, porque las dos cosas a la vez deforman la boca.
//
// Todo pasa por muelles críticamente amortiguados y lleva una asimetría suave
// entre lado izquierdo y derecho. No toca visemas, jawOpen ni el parpadeo.

using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Cejas, párpados, mejillas, sonrisa y gestos de labios según el estado y la voz.</summary>
    [DefaultExecutionOrder(12050)]
    [DisallowMultipleComponent]
    public class FacialExpressionController : MonoBehaviour
    {
        /// <summary>Canales de expresión (blendshapes ARKit).</summary>
        private enum Ch
        {
            BrowInnerUp,
            BrowOuterUpL,
            BrowOuterUpR,
            BrowDownL,
            BrowDownR,
            EyeSquintL,
            EyeSquintR,
            EyeWideL,
            EyeWideR,
            CheekSquintL,
            CheekSquintR,
            SmileL,
            SmileR,
            DimpleL,
            DimpleR,
            PressL,
            PressR,
            MouthLeft,
            MouthRight,
            Pucker,
            FrownL,
            FrownR,
            SneerL,
            SneerR,
            Count
        }

        private static readonly string[] ChannelNames =
        {
            "browInnerUp", "browOuterUpLeft", "browOuterUpRight", "browDownLeft", "browDownRight",
            "eyeSquintLeft", "eyeSquintRight", "eyeWideLeft", "eyeWideRight", "cheekSquintLeft", "cheekSquintRight",
            "mouthSmileLeft", "mouthSmileRight", "mouthDimpleLeft", "mouthDimpleRight", "mouthPressLeft",
            "mouthPressRight", "mouthLeft", "mouthRight", "mouthPucker", "mouthFrownLeft", "mouthFrownRight",
            "noseSneerLeft", "noseSneerRight"
        };

        /// <summary>Un gesto pasajero: pesos por canal con una envolvente de subida y bajada.</summary>
        private struct Gesture
        {
            public float Start;
            public float Duration;
            public float Peak;
            public float Gain;
            public int Kind;
            public bool Left;
        }

        // Gestos pasajeros (Kind): cada uno es una pequeña receta de canales.
        private const int GBrowFlash = 0;
        private const int GBrowEmphasis = 1;
        private const int GSmilePulse = 2;
        private const int GHalfSmile = 3;
        private const int GLipPress = 4;
        private const int GSquint = 5;
        private const int GBrowKnit = 6;

        /// <summary>Emociones pasajeras que se piden desde fuera (trivia).</summary>
        public enum Emotion
        {
            None,
            Joy,
            Sad,
            Surprise
        }

        [Header("Referencias")]
        [SerializeField]
        [Tooltip("Cara del avatar: las expresiones se escriben en sus canales ARKit.")]
        private FaceRig faceRig;

        [SerializeField]
        [Tooltip("Estado del avatar (para saber si escucha, piensa o habla).")]
        private AvatarStateController stateController;

        [SerializeField]
        [Tooltip("Lip-sync: forma de la boca y eventos de la voz (sílabas, frases).")]
        private LipSyncController lipSync;

        [Header("Sonrisa de base (0..1)")]
        [Range(0f, 1f)]
        [Tooltip("Sonrisa constante en todos los estados, como la emoción \"Happy\" de Mia (LIP_CORNER_PULLER 0,52). Amable, no forzada; con la boca redonda baja sola para no estorbar al lip-sync.")]
        public float baseSmile = 0.35f;

        [Range(0f, 1f)]
        [Tooltip("Parte de la sonrisa de base que queda al pensar (el \"mmm\" aprieta los labios).")]
        public float baseSmileWhileThinking = 0.5f;

        [Range(0f, 0.5f)]
        [Tooltip("Cejas algo arriba de base, amables (Mia: INNER_BROW_RAISER 0,26 con su sonrisa).")]
        public float baseBrows = 0.08f;

        [Range(0f, 1f)] public float restSmile = 0.3f;
        [Range(0f, 1f)] public float listenSmile = 0.4f;
        [Range(0f, 1f)] public float thinkSmile = 0.08f;
        [Range(0f, 1f)] public float talkSmile = 0.26f;

        [Header("Voz")]
        [Range(0f, 1f)]
        [Tooltip("Cejas en un acento de la voz (o en una sílaba tónica, sin AvatarStateController).")]
        public float stressBrows = 0.5f;

        [Range(0f, 1f)]
        [Tooltip("Probabilidad de que una sílaba tónica levante las cejas, solo sin AvatarStateController (con él, van con cada acento de cuerpo).")]
        public float stressBrowChance = 0.55f;

        [Range(0f, 1f)]
        [Tooltip("Fuerza mínima (0..1) para que una sílaba cuente como tónica, solo sin AvatarStateController.")]
        public float stressThreshold = 0.82f;

        [Range(0f, 1f)]
        [Tooltip("Flash de cejas al arrancar una frase.")]
        public float phraseBrows = 0.45f;

        [Range(0f, 1f)]
        [Tooltip("Sonrisa extra al acabar una frase.")]
        public float phraseEndSmile = 0.2f;

        [Range(0f, 1f)]
        [Tooltip("Cuánto baja la sonrisa con los labios redondos o cerrados.")]
        public float mouthShapeSmileCut = 0.75f;

        [Header("Vida")]
        [Tooltip("Segundos mínimo y máximo entre microexpresiones en reposo y escuchando.")]
        public Vector2 microInterval = new Vector2(2.5f, 6f);

        [Range(0f, 1f)]
        [Tooltip("Intensidad de las microexpresiones.")]
        public float microAmount = 0.6f;

        [Range(0f, 0.3f)]
        [Tooltip("Vaivén lento y continuo de cejas y sonrisa.")]
        public float wander = 0.07f;

        [Range(0f, 0.3f)]
        [Tooltip("Asimetría entre lado izquierdo y derecho.")]
        public float asymmetry = 0.12f;

        [Range(1f, 15f)]
        [Tooltip("Velocidad de los cambios de expresión (Hz del muelle).")]
        public float expressionSpeed = 3.5f;

        [Range(2f, 20f)]
        [Tooltip("Velocidad de las cejas en los gestos de la voz (Hz del muelle).")]
        public float browSpeed = 7f;

        private readonly int[] _index = new int[(int)Ch.Count];
        private readonly float[] _target = new float[(int)Ch.Count];
        private readonly Spring[] _springs = new Spring[(int)Ch.Count];
        private readonly List<Gesture> _gestures = new List<Gesture>();
        private Emotion _emotion;
        private float _emotionStart;
        private float _emotionEnd;
        private bool _ready;
        private bool _subscribed;
        private bool _emphasisLinked;
        private float _seed;
        private float _nextMicro;
        private float _lastStressBrow = -10f;
        private AvatarState _state = AvatarState.Idle;
        private float _stateSince;
        private int _thinkSide = 1;

        /// <summary>Cara del avatar. Al cambiarla se vuelven a resolver los canales.</summary>
        public FaceRig FaceRig
        {
            get { return faceRig; }
            set
            {
                if (faceRig != null)
                {
                    faceRig.Rebuilt -= Bind;
                }

                faceRig = value;
                if (faceRig != null && isActiveAndEnabled)
                {
                    faceRig.Rebuilt += Bind;
                }

                Bind();
            }
        }

        private void Awake()
        {
            if (stateController == null)
            {
                stateController = GetComponentInChildren<AvatarStateController>(true);
            }

            if (lipSync == null)
            {
                lipSync = GetComponentInChildren<LipSyncController>(true);
            }

            _seed = Random.value * 100f;
            _nextMicro = Time.time + Random.Range(microInterval.x, microInterval.y);
            Bind();
        }

        private void OnEnable()
        {
            if (lipSync != null && !_subscribed)
            {
                lipSync.OnSpeechEvent += HandleSpeechEvent;
                _subscribed = true;
            }

            if (stateController != null && !_emphasisLinked)
            {
                stateController.OnEmphasis += HandleEmphasis;
                _emphasisLinked = true;
            }

            if (faceRig != null)
            {
                faceRig.Rebuilt -= Bind;
                faceRig.Rebuilt += Bind;
            }
        }

        private void OnDisable()
        {
            if (lipSync != null && _subscribed)
            {
                lipSync.OnSpeechEvent -= HandleSpeechEvent;
                _subscribed = false;
            }

            if (stateController != null && _emphasisLinked)
            {
                stateController.OnEmphasis -= HandleEmphasis;
                _emphasisLinked = false;
            }

            if (faceRig != null)
            {
                faceRig.Rebuilt -= Bind;
            }
        }

        /// <summary>Resuelve los canales en la cara. Se llama sola y al cambiar de avatar.</summary>
        public void Bind()
        {
            _ready = false;
            if (faceRig == null)
            {
                return;
            }

            bool any = false;
            for (int i = 0; i < _index.Length; i++)
            {
                _index[i] = faceRig.Channel(ChannelNames[i]);
                any |= _index[i] >= 0;
            }

            _ready = any;
        }

        // ------------------------------------------------------------------
        // Voz
        // ------------------------------------------------------------------

        private void HandleSpeechEvent(SpeechAnalyzer.SpeechEvent e)
        {
            float now = Time.time;
            switch (e.Kind)
            {
                case SpeechAnalyzer.EventKind.PhraseStart:
                    AddGesture(GBrowFlash, 0.55f, 0.3f, phraseBrows * Random.Range(0.75f, 1.1f));
                    break;
                case SpeechAnalyzer.EventKind.PhraseEnd:
                    AddGesture(GSmilePulse, 1.3f, 0.35f, phraseEndSmile * Random.Range(0.7f, 1.2f));
                    break;
                case SpeechAnalyzer.EventKind.Syllable:
                    // Con AvatarStateController las cejas van con sus acentos (HandleEmphasis).
                    if (!_emphasisLinked && e.Strength >= stressThreshold && now - _lastStressBrow > 0.7f
                        && Random.value < stressBrowChance)
                    {
                        _lastStressBrow = now;
                        float strength = Mathf.InverseLerp(stressThreshold, 1f, e.Strength);
                        AddGesture(GBrowEmphasis, Random.Range(0.35f, 0.55f), 0.3f, stressBrows * Mathf.Lerp(0.6f, 1f, strength));
                    }

                    break;
            }
        }

        /// <summary>Acento de la voz (cascada de cuerpo en AvatarStateController): cejas arriba en el mismo instante.</summary>
        private void HandleEmphasis(float strength)
        {
            _lastStressBrow = Time.time;
            AddGesture(GBrowEmphasis, Random.Range(0.35f, 0.55f), 0.3f, stressBrows * Mathf.Lerp(0.6f, 1f, Mathf.Clamp01(strength)));
        }

        /// <summary>
        /// Pone una emoción durante <paramref name="seconds"/> (sube en 0,25 s y se
        /// va en 0,6 s) encima de la expresión del estado: alegría al acertar,
        /// pena al fallar, sorpresa. La boca la sigue moviendo el lip-sync.
        /// </summary>
        public void ShowEmotion(Emotion emotion, float seconds)
        {
            _emotion = emotion;
            _emotionStart = Time.time;
            _emotionEnd = Time.time + Mathf.Max(0.3f, seconds);
        }

        private void ComposeEmotion(float now)
        {
            if (_emotion == Emotion.None)
            {
                return;
            }

            const float rise = 0.25f;
            const float fall = 0.6f;
            if (now > _emotionEnd + fall)
            {
                _emotion = Emotion.None;
                return;
            }

            float w = Mathf.Clamp01((now - _emotionStart) / rise);
            if (now > _emotionEnd)
            {
                w = Mathf.Min(w, 1f - ((now - _emotionEnd) / fall));
            }

            w = w * w * (3f - (2f * w));
            switch (_emotion)
            {
                case Emotion.Joy:
                    SetPair(Ch.SmileL, Ch.SmileR, 0.55f * w, 21f);
                    SetPair(Ch.CheekSquintL, Ch.CheekSquintR, 0.45f * w, 23f);
                    SetPair(Ch.EyeSquintL, Ch.EyeSquintR, 0.2f * w, 25f);
                    SetPair(Ch.DimpleL, Ch.DimpleR, 0.25f * w, 27f);
                    Set(Ch.BrowInnerUp, 0.2f * w);
                    SetPair(Ch.BrowOuterUpL, Ch.BrowOuterUpR, 0.3f * w, 29f);
                    break;
                case Emotion.Sad:
                    // Cejas en tejado, comisuras abajo y la sonrisa de base fuera.
                    Set(Ch.BrowInnerUp, 0.7f * w);
                    SetPair(Ch.BrowDownL, Ch.BrowDownR, 0.12f * w, 31f);
                    SetPair(Ch.FrownL, Ch.FrownR, 0.5f * w, 33f);
                    SetPair(Ch.PressL, Ch.PressR, 0.25f * w, 35f);
                    SetPair(Ch.SmileL, Ch.SmileR, -0.6f * w, 37f);
                    SetPair(Ch.CheekSquintL, Ch.CheekSquintR, -0.3f * w, 39f);
                    break;
                case Emotion.Surprise:
                    SetPair(Ch.EyeWideL, Ch.EyeWideR, 0.55f * w, 41f);
                    Set(Ch.BrowInnerUp, 0.5f * w);
                    SetPair(Ch.BrowOuterUpL, Ch.BrowOuterUpR, 0.55f * w, 43f);
                    break;
            }
        }

        private void AddGesture(int kind, float duration, float peak, float gain)
        {
            if (_gestures.Count > 12)
            {
                _gestures.RemoveAt(0);
            }

            _gestures.Add(new Gesture
            {
                Kind = kind, Start = Time.time, Duration = duration, Peak = peak, Gain = gain, Left = Random.value < 0.5f
            });
        }

        // ------------------------------------------------------------------
        // Composición
        // ------------------------------------------------------------------

        private void LateUpdate()
        {
            if (!_ready || faceRig == null)
            {
                return;
            }

            float dt = Time.deltaTime;
            float now = Time.time;
            AvatarState state = stateController != null ? stateController.State : AvatarState.Idle;
            if (state != _state)
            {
                OnStateChanged(state, now);
            }

            for (int i = 0; i < _target.Length; i++)
            {
                _target[i] = 0f;
            }

            float talking = lipSync != null && lipSync.IsTalking ? 1f : 0f;
            ComposeBase(state, now, talking);
            UpdateMicro(state, now, talking);
            ComposeGestures(now);
            ComposeEmotion(now);
            ApplyMouthCoordination();

            for (int i = 0; i < _target.Length; i++)
            {
                bool brow = i <= (int)Ch.BrowDownR || i == (int)Ch.EyeWideL || i == (int)Ch.EyeWideR;
                float speed = brow ? browSpeed : expressionSpeed;
                _springs[i].Step(Mathf.Clamp01(_target[i]), speed, speed * 0.8f, dt);
                faceRig.Add(_index[i], Mathf.Clamp01(_springs[i].Value));
            }
        }

        private void OnStateChanged(AvatarState state, float now)
        {
            if (state == AvatarState.Listening)
            {
                // "Te escucho": flash de cejas y ojos algo más abiertos.
                AddGesture(GBrowFlash, 0.6f, 0.3f, 0.45f);
            }
            else if (state == AvatarState.Thinking)
            {
                _thinkSide = Random.value < 0.5f ? -1 : 1;
            }

            _state = state;
            _stateSince = now;
        }

        private void Set(Ch channel, float value)
        {
            _target[(int)channel] += value;
        }

        /// <summary>Lado izquierdo y derecho con asimetría lenta.</summary>
        private void SetPair(Ch left, Ch right, float value, float noiseOffset)
        {
            float skew = FaceCurves.Noise(_seed + noiseOffset, Time.time * 0.11f) * asymmetry;
            _target[(int)left] += value * (1f + skew);
            _target[(int)right] += value * (1f - skew);
        }

        private void ComposeBase(AvatarState state, float now, float talking)
        {
            float w1 = FaceCurves.Noise(_seed, now * 0.21f) * wander;
            float w2 = FaceCurves.Noise(_seed + 37f, now * 0.17f) * wander;
            float smile;
            switch (state)
            {
                case AvatarState.Listening:
                    smile = listenSmile;
                    Set(Ch.BrowInnerUp, 0.18f + w1);
                    SetPair(Ch.BrowOuterUpL, Ch.BrowOuterUpR, 0.14f + w1 * 0.5f, 3f);
                    SetPair(Ch.EyeWideL, Ch.EyeWideR, 0.06f, 5f);
                    break;
                case AvatarState.Thinking:
                {
                    smile = thinkSmile;
                    // "Mmm": una ceja arriba y la otra frunce; labios apretados y a un lado.
                    float t = Mathf.Clamp01((now - _stateSince) / 0.4f);
                    Set(Ch.BrowInnerUp, 0.25f * t);
                    Set(_thinkSide > 0 ? Ch.BrowOuterUpL : Ch.BrowOuterUpR, 0.35f * t);
                    Set(_thinkSide > 0 ? Ch.BrowDownR : Ch.BrowDownL, 0.3f * t);
                    SetPair(Ch.EyeSquintL, Ch.EyeSquintR, 0.18f * t, 7f);
                    SetPair(Ch.PressL, Ch.PressR, 0.35f * t, 9f);
                    Set(_thinkSide > 0 ? Ch.MouthLeft : Ch.MouthRight, 0.22f * t);
                    Set(Ch.Pucker, 0.08f * t);
                    break;
                }

                case AvatarState.Speaking:
                    smile = talkSmile;
                    Set(Ch.BrowInnerUp, 0.08f + Mathf.Max(0f, w1));
                    SetPair(Ch.BrowOuterUpL, Ch.BrowOuterUpR, 0.06f + Mathf.Max(0f, w2) * 0.6f, 3f);
                    break;
                default:
                    smile = restSmile;
                    Set(Ch.BrowInnerUp, 0.04f + Mathf.Max(0f, w1) * 0.7f);
                    break;
            }

            // Frases del stand en reposo (ambient): sonrisa de hablar.
            if (state == AvatarState.Idle && talking > 0f)
            {
                smile = Mathf.Max(smile, talkSmile);
            }

            // Sonrisa de base constante (media al pensar) y cejas amables.
            float floor = state == AvatarState.Thinking ? baseSmile * baseSmileWhileThinking : baseSmile;
            smile = Mathf.Max(smile, floor);
            if (state != AvatarState.Thinking)
            {
                Set(Ch.BrowInnerUp, baseBrows);
            }

            smile = Mathf.Clamp01(smile + w2);
            SetPair(Ch.SmileL, Ch.SmileR, smile, 11f);
            SetPair(Ch.CheekSquintL, Ch.CheekSquintR, smile * 0.55f, 13f);
            SetPair(Ch.EyeSquintL, Ch.EyeSquintR, smile * 0.3f, 15f);
            SetPair(Ch.DimpleL, Ch.DimpleR, smile * 0.25f, 17f);
        }

        private void UpdateMicro(AvatarState state, float now, float talking)
        {
            if (now < _nextMicro)
            {
                return;
            }

            _nextMicro = now + Random.Range(microInterval.x, microInterval.y);
            if (state == AvatarState.Thinking || talking > 0f)
            {
                return;
            }

            float roll = Random.value;
            float gain = microAmount * Random.Range(0.6f, 1f);
            if (state == AvatarState.Listening)
            {
                // Escuchando: gestos de interés.
                if (roll < 0.35f)
                {
                    AddGesture(GBrowFlash, 0.6f, 0.3f, 0.35f * gain);
                }
                else if (roll < 0.65f)
                {
                    AddGesture(GSmilePulse, 1.4f, 0.3f, 0.25f * gain);
                }
                else if (roll < 0.85f)
                {
                    AddGesture(GHalfSmile, 1.6f, 0.3f, 0.3f * gain);
                }
                else
                {
                    AddGesture(GBrowKnit, 1.1f, 0.35f, 0.3f * gain);
                }

                return;
            }

            if (roll < 0.25f)
            {
                AddGesture(GHalfSmile, 1.8f, 0.3f, 0.3f * gain);
            }
            else if (roll < 0.45f)
            {
                AddGesture(GBrowFlash, 0.7f, 0.3f, 0.3f * gain);
            }
            else if (roll < 0.65f)
            {
                AddGesture(GLipPress, 1.2f, 0.35f, 0.35f * gain);
            }
            else if (roll < 0.85f)
            {
                AddGesture(GSquint, 1.4f, 0.35f, 0.25f * gain);
            }
            else
            {
                AddGesture(GSmilePulse, 1.6f, 0.3f, 0.2f * gain);
            }
        }

        private void ComposeGestures(float now)
        {
            for (int i = _gestures.Count - 1; i >= 0; i--)
            {
                Gesture g = _gestures[i];
                float t = (now - g.Start) / Mathf.Max(0.05f, g.Duration);
                if (t >= 1f)
                {
                    _gestures.RemoveAt(i);
                    continue;
                }

                float k = FaceCurves.Bump(t, g.Peak) * g.Gain;
                switch (g.Kind)
                {
                    case GBrowFlash:
                        Set(Ch.BrowInnerUp, k);
                        SetPair(Ch.BrowOuterUpL, Ch.BrowOuterUpR, k * 0.8f, 21f);
                        SetPair(Ch.EyeWideL, Ch.EyeWideR, k * 0.3f, 23f);
                        break;
                    case GBrowEmphasis:
                        Set(Ch.BrowInnerUp, k * 0.8f);
                        SetPair(Ch.BrowOuterUpL, Ch.BrowOuterUpR, k, 25f);
                        SetPair(Ch.EyeWideL, Ch.EyeWideR, k * 0.2f, 27f);
                        break;
                    case GSmilePulse:
                        SetPair(Ch.SmileL, Ch.SmileR, k, 29f);
                        SetPair(Ch.CheekSquintL, Ch.CheekSquintR, k * 0.6f, 31f);
                        SetPair(Ch.EyeSquintL, Ch.EyeSquintR, k * 0.35f, 33f);
                        break;
                    case GHalfSmile:
                        Set(g.Left ? Ch.SmileL : Ch.SmileR, k);
                        Set(g.Left ? Ch.DimpleL : Ch.DimpleR, k * 0.5f);
                        Set(g.Left ? Ch.CheekSquintL : Ch.CheekSquintR, k * 0.4f);
                        break;
                    case GLipPress:
                        SetPair(Ch.PressL, Ch.PressR, k, 35f);
                        Set(Ch.BrowInnerUp, k * 0.2f);
                        break;
                    case GSquint:
                        SetPair(Ch.EyeSquintL, Ch.EyeSquintR, k, 37f);
                        SetPair(Ch.CheekSquintL, Ch.CheekSquintR, k * 0.3f, 39f);
                        break;
                    case GBrowKnit:
                        SetPair(Ch.BrowDownL, Ch.BrowDownR, k * 0.6f, 41f);
                        Set(Ch.BrowInnerUp, k * 0.5f);
                        break;
                }
            }
        }

        /// <summary>Con la boca redonda o cerrada, la sonrisa baja: las dos cosas a la vez la deforman.</summary>
        private void ApplyMouthCoordination()
        {
            if (lipSync == null)
            {
                return;
            }

            float cut = Mathf.Clamp01(lipSync.Roundness) * mouthShapeSmileCut;
            float keep = 1f - cut;
            _target[(int)Ch.SmileL] *= keep;
            _target[(int)Ch.SmileR] *= keep;
            _target[(int)Ch.DimpleL] *= keep;
            _target[(int)Ch.DimpleR] *= keep;

            // Hablando, los labios no se aprietan ni se van a un lado.
            float open = lipSync.MouthOpen;
            float free = 1f - Mathf.Clamp01(open * 2f);
            _target[(int)Ch.PressL] *= free;
            _target[(int)Ch.PressR] *= free;
            _target[(int)Ch.MouthLeft] *= free;
            _target[(int)Ch.MouthRight] *= free;
            _target[(int)Ch.Pucker] *= free;
        }
    }
}
