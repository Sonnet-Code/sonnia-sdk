// Facial expressions: brows, eyelids, cheeks, smile and lip gestures.
//
// A face that only moves the mouth looks like a puppet. On top of the avatar's
// ARKit blendshapes, every frame this composes:
//
//  - A constant base smile, like the "Happy" emotion the Genies demo characters
//    always wear, and on top a gesture per state:
//    listening, brows slightly raised and an open smile (interest); thinking, one
//    brow up and the other down, lips pressed and pulled to one side
//    ("hmm", with a base half smile); speaking, a conversational smile.
//  - The voice: on accents (AvatarStateController.OnEmphasis, the same instant
//    as the body cascade) the brows rise and the eyes open a little; the
//    start of each phrase makes a brow "flash" and the end, a smile that
//    rises and falls. The events come from LipSyncController's voice analyzer
//    a little before their syllable, as in a person.
//  - Random micro-expressions at rest and while listening (brows, half smile,
//    pressed lips, narrowed eyes), so the face is never still.
//  - Coordination with the mouth: with rounded (o, u) or closed (p, b,
//    m) lips the smile drops, because both at once deform the mouth.
//
// Everything goes through critically damped springs and carries a soft asymmetry
// between left and right sides. It doesn't touch visemes, jawOpen or blinking.

using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Brows, eyelids, cheeks, smile and lip gestures according to the state and the voice.</summary>
    [DefaultExecutionOrder(12050)]
    [DisallowMultipleComponent]
    public class FacialExpressionController : MonoBehaviour
    {
        /// <summary>Expression channels (ARKit blendshapes).</summary>
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

        /// <summary>A passing gesture: per-channel weights with a rise-and-fall envelope.</summary>
        private struct Gesture
        {
            public float Start;
            public float Duration;
            public float Peak;
            public float Gain;
            public int Kind;
            public bool Left;
        }

        // Passing gestures (Kind): each is a small recipe of channels.
        private const int GBrowFlash = 0;
        private const int GBrowEmphasis = 1;
        private const int GSmilePulse = 2;
        private const int GHalfSmile = 3;
        private const int GLipPress = 4;
        private const int GSquint = 5;
        private const int GBrowKnit = 6;

        /// <summary>Passing emotions requested from outside (for example, trivia answers).</summary>
        public enum Emotion
        {
            None,
            Joy,
            Sad,
            Surprise
        }

        [Header("References")]
        [SerializeField]
        [Tooltip("Avatar face: expressions are written to its ARKit channels.")]
        private FaceRig faceRig;

        [SerializeField]
        [Tooltip("Avatar state (to know whether it listens, thinks or speaks).")]
        private AvatarStateController stateController;

        [SerializeField]
        [Tooltip("Lip-sync: mouth shape and voice events (syllables, phrases).")]
        private LipSyncController lipSync;

        [Header("Base smile (0..1)")]
        [Range(0f, 1f)]
        [Tooltip("Constant smile in all states, like the \"Happy\" emotion of the Genies demo characters (LIP_CORNER_PULLER 0.52). Friendly, not forced; with a rounded mouth it drops by itself so it doesn't get in the way of the lip-sync.")]
        public float baseSmile = 0.35f;

        [Range(0f, 1f)]
        [Tooltip("Share of the base smile that remains when thinking (the \"hmm\" presses the lips).")]
        public float baseSmileWhileThinking = 0.5f;

        [Range(0f, 0.5f)]
        [Tooltip("Brows slightly raised by default, friendly (Genies demo characters: INNER_BROW_RAISER 0.26 with their smile).")]
        public float baseBrows = 0.08f;

        [Range(0f, 1f)] public float restSmile = 0.3f;
        [Range(0f, 1f)] public float listenSmile = 0.4f;
        [Range(0f, 1f)] public float thinkSmile = 0.08f;
        [Range(0f, 1f)] public float talkSmile = 0.26f;

        [Header("Voice")]
        [Range(0f, 1f)]
        [Tooltip("Brows on a voice accent (or on a stressed syllable, without AvatarStateController).")]
        public float stressBrows = 0.5f;

        [Range(0f, 1f)]
        [Tooltip("Chance that a stressed syllable raises the brows, only without AvatarStateController (with it, they go with each body accent).")]
        public float stressBrowChance = 0.55f;

        [Range(0f, 1f)]
        [Tooltip("Minimum strength (0..1) for a syllable to count as stressed, only without AvatarStateController.")]
        public float stressThreshold = 0.82f;

        [Range(0f, 1f)]
        [Tooltip("Brow flash at the start of a phrase.")]
        public float phraseBrows = 0.45f;

        [Range(0f, 1f)]
        [Tooltip("Extra smile at the end of a phrase.")]
        public float phraseEndSmile = 0.2f;

        [Range(0f, 1f)]
        [Tooltip("How much the smile drops with rounded or closed lips.")]
        public float mouthShapeSmileCut = 0.75f;

        [Header("Life")]
        [Tooltip("Minimum and maximum seconds between micro-expressions at rest and while listening.")]
        public Vector2 microInterval = new Vector2(2.5f, 6f);

        [Range(0f, 1f)]
        [Tooltip("Intensity of the micro-expressions.")]
        public float microAmount = 0.6f;

        [Range(0f, 0.3f)]
        [Tooltip("Slow, continuous sway of brows and smile.")]
        public float wander = 0.07f;

        [Range(0f, 0.3f)]
        [Tooltip("Asymmetry between left and right sides.")]
        public float asymmetry = 0.12f;

        [Range(1f, 15f)]
        [Tooltip("Speed of expression changes (spring Hz).")]
        public float expressionSpeed = 3.5f;

        [Range(2f, 20f)]
        [Tooltip("Speed of the brows in voice gestures (spring Hz).")]
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

        /// <summary>Avatar face. When it changes, the channels are resolved again.</summary>
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

        /// <summary>Resolves the channels on the face. Called by itself and when the avatar changes.</summary>
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
        // Voice
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
                    // With AvatarStateController the brows go with its accents (HandleEmphasis).
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

        /// <summary>Voice accent (body cascade in AvatarStateController): brows up at the same instant.</summary>
        private void HandleEmphasis(float strength)
        {
            _lastStressBrow = Time.time;
            AddGesture(GBrowEmphasis, Random.Range(0.35f, 0.55f), 0.3f, stressBrows * Mathf.Lerp(0.6f, 1f, Mathf.Clamp01(strength)));
        }

        /// <summary>
        /// Sets an emotion for <paramref name="seconds"/> (rises in 0.25 s and
        /// fades in 0.6 s) on top of the state's expression: joy, sadness,
        /// surprise. The lip-sync keeps moving the mouth.
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
                    // Brows in a roof shape, mouth corners down and the base smile gone.
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
        // Composition
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
                // "I'm listening": brow flash and slightly wider eyes.
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

        /// <summary>Left and right sides with slow asymmetry.</summary>
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
                    // "Hmm": one brow up and the other frowning; lips pressed and to one side.
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

            // Idle ambient phrases: speaking smile.
            if (state == AvatarState.Idle && talking > 0f)
            {
                smile = Mathf.Max(smile, talkSmile);
            }

            // Constant base smile (half when thinking) and friendly brows.
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
                // Listening: gestures of interest.
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

        /// <summary>With a rounded or closed mouth, the smile drops: both at once deform it.</summary>
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

            // When speaking, the lips are not pressed or pulled to one side.
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
