// Expresiones faciales: cejas, párpados, mejillas, sonrisa y gestos de labios.
//
// Una cara que solo mueve la boca parece un muñeco. Sobre los blendshapes ARKit
// del avatar se compone, cada frame:
//
//  - Un gesto de base por estado: en reposo una sonrisa amable; escuchando,
//    cejas algo arriba y sonrisa abierta (interés); pensando, una ceja arriba y
//    la otra abajo, los labios apretados y llevados a un lado ("mmm"); hablando,
//    una sonrisa de conversación.
//  - La voz: las sílabas tónicas levantan las cejas y abren un poco los ojos, el
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

        [Header("Referencias")]
        [SerializeField]
        [Tooltip("Malla con los blendshapes ARKit de la cara.")]
        private SkinnedMeshRenderer faceRenderer;

        [SerializeField]
        [Tooltip("Estado del avatar (para saber si escucha, piensa o habla).")]
        private AvatarStateController stateController;

        [SerializeField]
        [Tooltip("Lip-sync: forma de la boca y eventos de la voz (sílabas, frases).")]
        private LipSyncController lipSync;

        [Header("Sonrisa de base (0..1)")]
        [Range(0f, 1f)] public float restSmile = 0.3f;
        [Range(0f, 1f)] public float listenSmile = 0.4f;
        [Range(0f, 1f)] public float thinkSmile = 0.08f;
        [Range(0f, 1f)] public float talkSmile = 0.26f;

        [Header("Voz")]
        [Range(0f, 1f)]
        [Tooltip("Cejas en una sílaba tónica.")]
        public float stressBrows = 0.5f;

        [Range(0f, 1f)]
        [Tooltip("Probabilidad de que una sílaba tónica levante las cejas (no todas lo hacen).")]
        public float stressBrowChance = 0.55f;

        [Range(0f, 1f)]
        [Tooltip("Fuerza mínima (0..1) para que una sílaba cuente como tónica.")]
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
        private float _scale = 1f;
        private bool _ready;
        private bool _subscribed;
        private float _seed;
        private float _nextMicro;
        private float _lastStressBrow = -10f;
        private AvatarState _state = AvatarState.Idle;
        private float _stateSince;
        private int _thinkSide = 1;

        /// <summary>Malla de la cara.</summary>
        public SkinnedMeshRenderer FaceRenderer
        {
            get { return faceRenderer; }
            set
            {
                faceRenderer = value;
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
        }

        private void OnDisable()
        {
            if (lipSync != null && _subscribed)
            {
                lipSync.OnSpeechEvent -= HandleSpeechEvent;
                _subscribed = false;
            }
        }

        /// <summary>Resuelve los blendshapes. Se llama sola; repetir si cambia la malla.</summary>
        public void Bind()
        {
            _ready = false;
            Mesh mesh = faceRenderer != null ? faceRenderer.sharedMesh : null;
            if (mesh == null)
            {
                return;
            }

            _scale = LipSyncController.BlendShapeScale(mesh);
            bool any = false;
            for (int i = 0; i < _index.Length; i++)
            {
                _index[i] = LipSyncController.FindBlendShape(mesh, ChannelNames[i]);
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
                    if (e.Strength >= stressThreshold && now - _lastStressBrow > 0.7f && Random.value < stressBrowChance)
                    {
                        _lastStressBrow = now;
                        float strength = Mathf.InverseLerp(stressThreshold, 1f, e.Strength);
                        AddGesture(GBrowEmphasis, Random.Range(0.35f, 0.55f), 0.3f, stressBrows * Mathf.Lerp(0.6f, 1f, strength));
                    }

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
            if (!_ready || faceRenderer == null)
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
            ApplyMouthCoordination();

            for (int i = 0; i < _target.Length; i++)
            {
                bool brow = i <= (int)Ch.BrowDownR || i == (int)Ch.EyeWideL || i == (int)Ch.EyeWideR;
                float speed = brow ? browSpeed : expressionSpeed;
                _springs[i].Step(Mathf.Clamp01(_target[i]), speed, speed * 0.8f, dt);
                if (_index[i] >= 0)
                {
                    faceRenderer.SetBlendShapeWeight(_index[i], Mathf.Clamp01(_springs[i].Value) * 100f * _scale);
                }
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
