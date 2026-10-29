// Avatar state: head, living body (breathing and accents) and blinking.
//
// The state arrives over the protocol (idle, listening, thinking, speaking).
// Body animations are driven by AvatarChoreographer; on top of them, here:
//
//  - Head: follows the user (the camera) only partly: 0.3 at idle and while
//    thinking, 0.5 while listening and speaking. Mostly the idle animation moves it and the
//    eyes do the rest, like the Genies demo characters. It looks at the image panel for a
//    moment when it appears; while thinking, the head rises a little and looks up and to
//    one side.
//  - Listening: head tilted, torso slightly forward and an occasional slow
//    "uh-huh" nod.
//  - Continuous additive breathing, also while talking: one inhale every ~
//    5 s (with some randomness so it does not sync with the idle), chest +-1.1 deg and
//    shoulders. The head goes along with it. Values measured on the Genies demo characters.
//  - Accents while talking, like Genies "emphasis": on stressed syllables, a
//    0.8 s cascade (wind-up backwards, then spine, chest +3.4 deg,
//    neck, head +5.5 deg and arms, each a little after the previous one).
//    OnEmphasis fires at the same instant (the brows rise in
//    FacialExpressionController).
//  - Hands while talking: the Genies set has no talking clips, so the
//    gestures are made here. When a phrase starts (and sometimes on a stressed syllable), one
//    hand or both rise in front of the body palm up, like someone
//    explaining; each accent is a hand beat and, when the phrase ends or
//    after a few seconds, they return to place with a pause before the
//    next one. They wait while the body is busy (pointing at an image, a
//    dance, walking).
//  - Blinking like Genies: 0.38 s (closes fast in a third, opens
//    slowly in two), every 3-5 s plus those of the voice and gaze changes
//    (about 20 per minute), double in 18 %, eyes offset by a few ms and the
//    brows lowering a little. The eyelid follows the gaze when looking down.
//
// Everything is applied in LateUpdate, on top of the animation pose.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Assistant states, in the same order as the Animator parameter.</summary>
    public enum AvatarState
    {
        Idle = 0,
        Listening = 1,
        Thinking = 2,
        Speaking = 3
    }

    /// <summary>
    /// Orients the head according to state and voice, brings the body to life (breathing
    /// and accents) and blinks. Everything is optional: without bones or eye
    /// blendshapes that part does nothing.
    /// </summary>
    // Runs late in LateUpdate so the blink blendshapes written here take
    // precedence over anything else that writes the same shapes
    // during the frame.
    [DefaultExecutionOrder(12010)]
    [DisallowMultipleComponent]
    public class AvatarStateController : MonoBehaviour
    {
        [Header("Gaze")]
        [SerializeField]
        [Tooltip("Head bone. If empty, the gaze is not touched.")]
        private Transform headBone;

        [SerializeField]
        [Tooltip("Avatar root: provides the axes (right, up, forward) of the thinking point. Defaults to this object.")]
        private Transform avatarRoot;

        [SerializeField]
        [Tooltip("Where it looks while listening and talking. Normally the camera.")]
        private Transform lookTarget;

        [SerializeField]
        [Tooltip("Optional point it looks at while thinking. If empty, the offset below is used.")]
        private Transform thinkingLookTarget;

        [SerializeField]
        [Tooltip("Point it looks at while thinking, relative to the head and in avatar axes (right, up, forward). Up and to one side: a thinking glance, not turning the face away.")]
        private Vector3 thinkingGaze = new Vector3(0.35f, 0.3f, 1.4f);

        [SerializeField]
        [Tooltip("Image panel. Looks toward it while it is visible.")]
        private Transform imageLookTarget;

        [SerializeField]
        [Tooltip("Look at the image panel when it appears.")]
        private bool lookAtImageWhenVisible = true;

        [SerializeField]
        [Tooltip("Seconds it looks at the panel when an image appears; then it goes back to the user. 0 = while visible.")]
        private float imageGlanceSeconds = 1.6f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("How much the head follows the user over what the animation dictates. At 0.3 the head is moved mostly by the idle animation and the eyes look at the user (Genies demo characters: head at 0, eyes at 1).")]
        private float headFollow = 0.3f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("The same while talking: higher, since people look at whom they talk to. DefaultIdle turns the head quite a bit (about 18 deg side to side at 0.3) and in conversation it read as not looking at the user.")]
        private float speakingHeadFollow = 0.5f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("The same while listening.")]
        private float listeningHeadFollow = 0.5f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Gaze weight during dances and big gestures: the head animation leads more.")]
        private float wideShotLookWeight = 0.3f;

        [SerializeField]
        [Tooltip("Choreographer, to know when a big gesture is playing. Optional.")]
        private AvatarChoreographer choreographer;

        [SerializeField]
        [Range(0f, 90f)]
        [Tooltip("Maximum degrees the head moves away from the animation pose.")]
        private float maxLookAngle = 40f;

        [SerializeField]
        [Range(0.5f, 20f)]
        [Tooltip("Speed at which the head reaches its target.")]
        private float lookSmoothing = 5f;

        [SerializeField]
        [Tooltip("Correction in degrees if the head bone's forward axis is not Z+.")]
        private Vector3 headRotationOffset = Vector3.zero;

        [SerializeField]
        [Range(0f, 5f)]
        [Tooltip("Amplitude in degrees of the slow, continuous sway of the head, so it is never fixed in place (scaled by the following).")]
        private float headSwayDegrees = 1.4f;

        [SerializeField]
        [Tooltip("Lip-sync: voice events (syllables, phrases) come from it. Optional.")]
        private LipSyncController lipSync;

        [Header("Head with the voice")]
        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("Degrees of a nod on a stressed syllable (only with body accents off; with them on the head goes in the cascade).")]
        public float stressNodDegrees = 3.5f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probability of nodding on a stressed syllable (with accents off).")]
        public float stressNodChance = 0.65f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Minimum strength (0..1) for a syllable to count as stressed (with accents off).")]
        public float stressThreshold = 0.8f;

        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("Degrees of turn and tilt of the head pose chosen for each phrase.")]
        public float phrasePoseDegrees = 4f;

        [SerializeField]
        [Range(0f, 12f)]
        [Tooltip("Head tilt while listening (tilted to one side).")]
        public float listenTiltDegrees = 6f;

        [SerializeField]
        [Range(0f, 8f)]
        [Tooltip("Degrees of the \"uh-huh\" nods while listening.")]
        public float listenNodDegrees = 2.5f;

        [SerializeField]
        [Tooltip("Minimum and maximum seconds between nods while listening.")]
        public Vector2 listenNodEvery = new Vector2(4f, 8f);

        [SerializeField]
        [Range(0.5f, 4f)]
        [Tooltip("Speed of the nods while listening (spring Hz). Lower is slower and calmer.")]
        public float listenNodHz = 1.4f;

        [SerializeField]
        [Range(0f, 12f)]
        [Tooltip("Head tilt while thinking.")]
        public float thinkTiltDegrees = 5f;

        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("How much the head rises while thinking (degrees).")]
        public float thinkLiftDegrees = 4f;

        [Header("Body: breathing")]
        [SerializeField]
        [Tooltip("Continuous additive breathing over the animation, also while talking.")]
        private bool breathing = true;

        [SerializeField]
        [Range(2f, 10f)]
        [Tooltip("Seconds per breath (Genies demo characters: 5, about 12 per minute).")]
        private float breathSeconds = 5f;

        [SerializeField]
        [Range(0f, 0.4f)]
        [Tooltip("Randomness in the duration and depth of each breath, so it does not sync with the idle loop.")]
        private float breathJitter = 0.12f;

        [SerializeField]
        [Range(0f, 4f)]
        [Tooltip("Degrees the chest opens on inhale (Genies demo characters: +-1.1). The head goes along with it.")]
        private float breathChestDegrees = 1.1f;

        [SerializeField]
        [Range(0f, 3f)]
        [Tooltip("Degrees the shoulders rise on inhale.")]
        private float breathShoulderDegrees = 0.6f;

        [SerializeField]
        [Range(0f, 6f)]
        [Tooltip("Degrees the torso leans forward while listening: interest.")]
        private float listenLeanDegrees = 2f;

        [Header("Body: accents while talking")]
        [SerializeField]
        [Tooltip("Body accents on stressed syllables (Genies \"emphasis\"): cascade of spine, chest, neck, head and arms.")]
        private bool accents = true;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Minimum syllable strength (0..1) for an accent.")]
        private float accentThreshold = 0.8f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probability of an accent on a syllable that passes the threshold.")]
        private float accentChance = 0.6f;

        [SerializeField]
        [Range(0.3f, 2f)]
        [Tooltip("Minimum seconds between two accents (Genies: 0.6-1).")]
        private float accentMinGap = 0.9f;

        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Scale of the whole cascade. 1: the Genies degrees (chest +3.4 deg, neck +2 deg, head +5.5 deg), which add up along the chain and are a lot in close-up; 0.6 to start.")]
        private float accentScale = 0.6f;

        [SerializeField]
        [Range(0f, 6f)]
        [Tooltip("Degrees the arms move forward on an accent.")]
        private float accentArmDegrees = 2.5f;

        [Header("Body: hands while talking")]
        [SerializeField]
        [Tooltip("Hand gestures while talking, made in code (the Genies set has no talking clips).")]
        private bool handGestures = true;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probability of gesturing when a phrase starts.")]
        private float handGestureChance = 0.75f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probability that the gesture uses both hands (otherwise one, more often the right).")]
        private float handBothChance = 0.4f;

        [SerializeField]
        [Range(-30f, 120f)]
        [Tooltip("Degrees the elbow bends: the hand rises in front of the body.")]
        private float handElbowDegrees = 75f;

        [SerializeField]
        [Range(-20f, 50f)]
        [Tooltip("Degrees the arm moves forward.")]
        private float handArmForwardDegrees = 24f;

        [SerializeField]
        [Range(-20f, 40f)]
        [Tooltip("Degrees the arm opens outward (separates the elbow from the body).")]
        private float handArmOutDegrees = 12f;

        [SerializeField]
        [Range(-40f, 60f)]
        [Tooltip("Degrees the arm rotates inward: brings the hands toward the center.")]
        private float handArmInwardDegrees = 6f;

        [SerializeField]
        [Range(-120f, 120f)]
        [Tooltip("Degrees the forearm rotates to show the palm up (half in the forearm, half in the wrist).")]
        private float handPalmUpDegrees = 75f;

        [SerializeField]
        [Range(-40f, 40f)]
        [Tooltip("Degrees the wrist bends over the elbow hinge (positive raises the hand).")]
        private float handWristDegrees = 0f;

        [SerializeField]
        [Range(0f, 30f)]
        [Tooltip("Degrees the hand drops on each beat (voice accent).")]
        private float handBeatDegrees = 9f;

        [SerializeField]
        [Tooltip("Minimum and maximum seconds a gesture lasts if the phrase continues.")]
        private Vector2 handHoldSeconds = new Vector2(1.6f, 3.2f);

        [SerializeField]
        [Tooltip("Minimum and maximum seconds of pause between gestures.")]
        private Vector2 handRestSeconds = new Vector2(0.6f, 1.8f);

        [SerializeField]
        [Range(0.3f, 4f)]
        [Tooltip("Speed at which the hand rises (spring Hz; 1.3 arrives in a bit over half a second).")]
        private float handRiseHz = 1.3f;

        [SerializeField]
        [Range(0.3f, 4f)]
        [Tooltip("Speed at which the hand returns to place.")]
        private float handFallHz = 0.9f;

        [Header("Blinking")]
        [SerializeField]
        [Tooltip("Avatar face: the blink is written to its eyeBlinkLeft and eyeBlinkRight channels.")]
        private FaceRig faceRig;

        [SerializeField]
        [Tooltip("Minimum and maximum seconds between spontaneous blinks (Genies: 4 +- 1). With the voice ones and gaze changes it comes to about 20 per minute.")]
        private Vector2 blinkEvery = new Vector2(3f, 5f);

        [SerializeField]
        [Range(0.1f, 0.7f)]
        [Tooltip("Duration of a blink in seconds: closes in a third and opens slowly in the rest (Genies: 0.35-0.4).")]
        private float blinkSeconds = 0.38f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probability of blinking when a phrase starts or ends and on state changes.")]
        public float blinkOnSpeechChance = 0.35f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Share of spontaneous blinks that are double (Genies demo characters: 18 %).")]
        public float doubleBlinkShare = 0.18f;

        [SerializeField]
        [Range(0f, 0.04f)]
        [Tooltip("Maximum offset between the two eyes in a blink (s). Genies: 16 ms.")]
        private float blinkEyeOffset = 0.012f;

        [SerializeField]
        [Range(0f, 0.6f)]
        [Tooltip("How much the brows lower with the blink (0..1). They are slower than the eyelid: the real peak is a bit over half (Genies: up to 0.25).")]
        private float blinkBrowLower = 0.25f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("How much the upper eyelid lowers when looking down (per 10 deg of gaze).")]
        public float lidFollowsGaze = 0.25f;

        [SerializeField]
        [Tooltip("Eyes, so the eyelid follows the gaze. Optional.")]
        private EyeGazeController eyeGaze;

        // Body bones that drive breathing and accents.
        private const int BSpine = 0;
        private const int BChest = 1;
        private const int BUpperChest = 2;
        private const int BNeck = 3;
        private const int BLeftShoulder = 4;
        private const int BRightShoulder = 5;
        private const int BLeftArm = 6;
        private const int BRightArm = 7;
        private const int BLeftLowerArm = 8;
        private const int BRightLowerArm = 9;
        private const int BLeftHand = 10;
        private const int BRightHand = 11;
        private const int BodyBoneCount = 12;

        private static readonly HumanBodyBones[] BodyBoneIds =
        {
            HumanBodyBones.Spine, HumanBodyBones.Chest, HumanBodyBones.UpperChest, HumanBodyBones.Neck,
            HumanBodyBones.LeftShoulder, HumanBodyBones.RightShoulder, HumanBodyBones.LeftUpperArm, HumanBodyBones.RightUpperArm,
            HumanBodyBones.LeftLowerArm, HumanBodyBones.RightLowerArm, HumanBodyBones.LeftHand, HumanBodyBones.RightHand
        };

        /// <summary>A hand in a talking gesture: how high it is and the shape of this gesture.</summary>
        private sealed class HandGesture
        {
            /// <summary>0 in place, 1 fully up.</summary>
            public Spring Weight;
            public float Target;
            // Variation of this gesture (multiplies the scene's degrees).
            public float Elbow = 1f;
            public float Forward = 1f;
            public float Palm = 1f;
            public float Inward = 1f;
            public float BeatStart = -10f;
            public float BeatGain;
            public float NoiseSeed;
        }

        /// <summary>An accent in progress: when it started and how strong it is (0..1).</summary>
        private struct Accent
        {
            public float Start;
            public float Gain;
        }

        // Total duration of an accent cascade.
        private const float AccentSeconds = 0.85f;

        private AvatarState _state = AvatarState.Idle;
        private float _stateSince;

        // Gaze deviation relative to the animation, in the head's local space.
        // It is smoothed locally on purpose: if the rotation were smoothed in
        // world space, when the body turns fast the head would stay "nailed"
        // looking at the old spot.
        private Quaternion _lookOffset = Quaternion.identity;
        private float _currentWeight;
        private float _gestureWeight = 1f;
        private bool _lookInitialized;
        private bool _imageVisible;
        private float _imageShownAt = -999f;
        private float _noiseSeed;

        // Head gestures (degrees): pitch (positive lowers the chin), turn and tilt.
        private Spring _pitch;
        private Spring _slowNod;
        private Spring _yaw;
        private Spring _roll;
        private Spring _pitchPose;
        private float _poseYaw;
        private float _posePitch;
        private float _poseRoll;
        private float _lastNod = -10f;
        private float _nextListenNod;
        private int _tiltSide = 1;
        private bool _subscribed;

        // Body: bones, animation pose and what was last written (if the
        // Animator does not write a frame, the rotation is not accumulated).
        private readonly Transform[] _bodyBones = new Transform[BodyBoneCount];
        private readonly Quaternion[] _bodyBase = new Quaternion[BodyBoneCount];
        private readonly Quaternion[] _bodyWritten = new Quaternion[BodyBoneCount];
        private readonly bool[] _bodyHasWritten = new bool[BodyBoneCount];
        private Animator _bodyAnimator;
        private Transform _bodyResolvedFor;
        private bool _bodyResolved;
        private Spring _lean;
        private float _breathPhase;
        private float _breathPeriod = 5f;
        private float _breathDepth = 1f;
        private float _breathValue;
        private readonly List<Accent> _accents = new List<Accent>(4);
        private float _lastAccent = -10f;
        private float _accentHeadPitch;

        // Hands while talking.
        private readonly HandGesture _leftHand = new HandGesture { NoiseSeed = 11.3f };
        private readonly HandGesture _rightHand = new HandGesture { NoiseSeed = 47.9f };
        private bool _handsUp;
        private float _handsDownAt;
        private float _handsRestUntil;
        private bool _handsFree;
        // "Idle motion" setting (1 = as is).
        private float _breathTuning = 1f;
        private float _accentTuning = 1f;
        private float _speedTuning = 1f;

        // Blinking.
        private int _blinkLeftChannel = -1;
        private int _blinkRightChannel = -1;
        private int _browLeftChannel = -1;
        private int _browRightChannel = -1;
        private float _timeToNextBlink;
        private float _blinkElapsed = -1f;
        private float _blinkDepth = 1f;
        private float _blinkLeftDelay;
        private float _blinkRightDelay;
        private float _pendingSecondBlink = -1f;
        private float _lid;
        private Spring _browBlink;

        // Gaze directed from outside (walking out and in: looks where it is
        // going). Takes precedence over the user, the panel and the thinking point.
        private bool _lookOverride;
        private Vector3 _lookOverridePosition;
        private float _lookOverrideWeight = -1f;

        /// <summary>
        /// Voice accent: a stressed syllable that carries a body cascade. The
        /// value is its strength (0..1). FacialExpressionController raises the brows.
        /// </summary>
        public event Action<float> OnEmphasis;

        /// <summary>Current avatar state.</summary>
        public AvatarState State
        {
            get { return _state; }
        }

        /// <summary>True while another component decides where it looks.</summary>
        public bool HasLookOverride
        {
            get { return _lookOverride; }
        }

        /// <summary>Breathing right now: -1 exhaled, 1 inhaled. For measuring.</summary>
        public float BreathValue
        {
            get { return _breathValue; }
        }

        /// <summary>How much the head follows the target right now (0..1). For measuring.</summary>
        public float CurrentLookWeight
        {
            get { return _currentWeight; }
        }

        /// <summary>
        /// Looks at a world point instead of the user. Head and eyes
        /// (EyeGazeController reads the same point) go toward it with their usual
        /// smoothing, so a point change reads as a natural turn.
        /// Called every frame while it lasts; a negative <paramref name="weight"/>
        /// keeps the normal gaze weight.
        /// </summary>
        public void SetLookOverride(Vector3 worldPosition, float weight = -1f)
        {
            _lookOverride = true;
            _lookOverridePosition = worldPosition;
            _lookOverrideWeight = weight;
        }

        /// <summary>Head bone that gets rotated. Changes with the avatar (the SDK one replaces the fallback).</summary>
        public Transform HeadBone
        {
            get { return headBone; }
            set
            {
                headBone = value;
                _bodyResolved = false;
            }
        }

        /// <summary>Goes back to looking at whatever the state calls for (user, panel, thinking).</summary>
        public void ClearLookOverride()
        {
            _lookOverride = false;
            _lookOverrideWeight = -1f;
        }

        /// <summary>
        /// "Idle motion" setting: multipliers over the
        /// scene, 1 = as is. <paramref name="breath"/> scales breathing,
        /// <paramref name="accentAmount"/> the accents while talking and
        /// <paramref name="speed"/> the pace of breathing and the idle loop
        /// (its weight shift).
        /// </summary>
        public void SetIdleTuning(float breath, float accentAmount, float speed)
        {
            _breathTuning = Mathf.Clamp(breath, 0f, 3f);
            _accentTuning = Mathf.Clamp(accentAmount, 0f, 3f);
            _speedTuning = Mathf.Clamp(speed, 0.25f, 3f);
            if (choreographer != null)
            {
                choreographer.SetLoopSpeed(_speedTuning);
            }
        }

        private void Awake()
        {
            if (avatarRoot == null)
            {
                avatarRoot = transform;
            }

            if (lipSync == null)
            {
                lipSync = GetComponentInChildren<LipSyncController>(true);
            }

            if (choreographer == null)
            {
                choreographer = GetComponentInChildren<AvatarChoreographer>(true);
            }

            if (eyeGaze == null)
            {
                eyeGaze = GetComponentInChildren<EyeGazeController>(true);
            }

            _noiseSeed = UnityEngine.Random.value * 100f;
            _breathPhase = UnityEngine.Random.value;
            _breathPeriod = breathSeconds;
            RefreshBlendShapes();
            ScheduleNextBlink();
        }

        private void OnEnable()
        {
            if (lipSync != null && !_subscribed)
            {
                lipSync.OnSpeechEvent += HandleSpeechEvent;
                _subscribed = true;
            }

            if (faceRig != null)
            {
                faceRig.Rebuilt -= RefreshBlendShapes;
                faceRig.Rebuilt += RefreshBlendShapes;
            }
        }

        private void OnDisable()
        {
            if (lipSync != null && _subscribed)
            {
                lipSync.OnSpeechEvent -= HandleSpeechEvent;
                _subscribed = false;
            }

            if (faceRig != null)
            {
                faceRig.Rebuilt -= RefreshBlendShapes;
            }
        }

        /// <summary>Avatar face. Changing it re-resolves the blink channels.</summary>
        public FaceRig FaceRig
        {
            get { return faceRig; }
            set
            {
                if (faceRig != null)
                {
                    faceRig.Rebuilt -= RefreshBlendShapes;
                }

                faceRig = value;
                if (faceRig != null && isActiveAndEnabled)
                {
                    faceRig.Rebuilt += RefreshBlendShapes;
                }

                RefreshBlendShapes();
            }
        }

        /// <summary>Re-resolves the blink channels (when the avatar changes).</summary>
        public void RefreshBlendShapes()
        {
            _blinkLeftChannel = faceRig != null ? faceRig.Channel("eyeBlinkLeft") : -1;
            _blinkRightChannel = faceRig != null ? faceRig.Channel("eyeBlinkRight") : -1;
            _browLeftChannel = faceRig != null ? faceRig.Channel("browDownLeft") : -1;
            _browRightChannel = faceRig != null ? faceRig.Channel("browDownRight") : -1;
        }

        // ------------------------------------------------------------------
        // State
        // ------------------------------------------------------------------

        /// <summary>Applies the state that arrives in the protocol <c>state</c> message.</summary>
        public void SetState(string stateName)
        {
            SetState(ParseState(stateName));
        }

        /// <summary>Applies an avatar state.</summary>
        public void SetState(AvatarState state)
        {
            if (state == _state)
            {
                return;
            }

            _state = state;
            _stateSince = Time.time;
            _tiltSide = UnityEngine.Random.value < 0.5f ? -1 : 1;
            _nextListenNod = Time.time + UnityEngine.Random.Range(1.2f, 2.5f);
            if (state != AvatarState.Speaking)
            {
                _poseYaw = 0f;
                _posePitch = 0f;
                _poseRoll = 0f;
                LowerHands(false);
            }

            if (UnityEngine.Random.value < blinkOnSpeechChance + 0.15f)
            {
                TriggerBlink();
            }
        }

        /// <summary>Converts the protocol name to the enum; anything unknown becomes idle.</summary>
        public static AvatarState ParseState(string stateName)
        {
            if (string.IsNullOrEmpty(stateName))
            {
                return AvatarState.Idle;
            }

            if (string.Equals(stateName, AvatarStateNames.Listening, StringComparison.OrdinalIgnoreCase))
            {
                return AvatarState.Listening;
            }

            if (string.Equals(stateName, AvatarStateNames.Thinking, StringComparison.OrdinalIgnoreCase))
            {
                return AvatarState.Thinking;
            }

            if (string.Equals(stateName, AvatarStateNames.Speaking, StringComparison.OrdinalIgnoreCase))
            {
                return AvatarState.Speaking;
            }

            return AvatarState.Idle;
        }

        /// <summary>Tells the avatar whether the image panel is visible and where it is.</summary>
        public void SetImagePanel(Transform panel, bool visible)
        {
            if (panel != null)
            {
                imageLookTarget = panel;
            }

            if (visible && !_imageVisible)
            {
                _imageShownAt = Time.time;
            }

            _imageVisible = visible;
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
                    // Each phrase gets a slightly different head pose: this way it does not
                    // always talk with its face nailed to the same spot.
                    _poseYaw = UnityEngine.Random.Range(-1f, 1f) * phrasePoseDegrees;
                    _poseRoll = UnityEngine.Random.Range(-1f, 1f) * phrasePoseDegrees * 0.8f;
                    _posePitch = UnityEngine.Random.Range(-0.6f, 0.4f) * phrasePoseDegrees * 0.5f;
                    if (UnityEngine.Random.value < blinkOnSpeechChance)
                    {
                        TriggerBlink();
                    }

                    if (UnityEngine.Random.value < handGestureChance)
                    {
                        RaiseHands();
                    }

                    break;
                case SpeechAnalyzer.EventKind.PhraseEnd:
                    LowerHands(true);
                    Nod(stressNodDegrees * 0.6f);

                    _poseYaw *= 0.4f;
                    _poseRoll *= 0.4f;
                    _posePitch = 0f;
                    if (UnityEngine.Random.value < blinkOnSpeechChance)
                    {
                        TriggerBlink();
                    }

                    break;
                case SpeechAnalyzer.EventKind.Syllable:
                    HandBeat(e.Strength);
                    if (accents)
                    {
                        if (e.Strength >= accentThreshold && now - _lastAccent >= accentMinGap
                            && UnityEngine.Random.value < accentChance)
                        {
                            float strength = Mathf.InverseLerp(accentThreshold, 1f, e.Strength);
                            StartAccent(Mathf.Lerp(0.55f, 1f, strength));
                        }
                    }
                    else if (e.Strength >= stressThreshold && now - _lastNod > 0.45f
                             && UnityEngine.Random.value < stressNodChance)
                    {
                        float strength = Mathf.InverseLerp(stressThreshold, 1f, e.Strength);
                        Nod(stressNodDegrees * Mathf.Lerp(0.6f, 1f, strength));
                    }

                    break;
            }
        }

        /// <summary>Nod: a push to the pitch spring that reaches <paramref name="degrees"/>.</summary>
        private void Nod(float degrees)
        {
            // With a critically damped spring at rest, an initial velocity v
            // reaches a maximum of v / (omega * e).
            const float frequency = 2.6f;
            float omega = 2f * Mathf.PI * frequency;
            _pitch.Kick(degrees * omega * 2.718f);
            _lastNod = Time.time;
        }

        /// <summary>Slow listening nod, with its own spring (listenNodHz).</summary>
        private void SlowNod(float degrees)
        {
            float omega = 2f * Mathf.PI * Mathf.Max(0.3f, listenNodHz);
            _slowNod.Kick(degrees * omega * 2.718f);
            _lastNod = Time.time;
        }

        /// <summary>Starts an accent cascade and notifies whoever wants to go along with it (brows).</summary>
        private void StartAccent(float gain)
        {
            _lastAccent = Time.time;
            if (_accents.Count >= 3)
            {
                _accents.RemoveAt(0);
            }

            _accents.Add(new Accent { Start = Time.time, Gain = gain });
            Action<float> handler = OnEmphasis;
            if (handler != null)
            {
                handler(gain);
            }
        }

        // ------------------------------------------------------------------
        // Loop
        // ------------------------------------------------------------------

        private void LateUpdate()
        {
            float deltaTime = Time.deltaTime;
            UpdateGestures(deltaTime);
            UpdateBody(deltaTime);
            UpdateLook(deltaTime);
            UpdateBlink(deltaTime);
        }

        private void UpdateGestures(float dt)
        {
            float now = Time.time;
            float targetYaw = _poseYaw;
            float targetRoll = _poseRoll;
            float targetPitch = _posePitch;
            switch (_state)
            {
                case AvatarState.Listening:
                    // Tilted and slightly forward: attentive.
                    targetRoll = listenTiltDegrees * _tiltSide;
                    targetPitch = 1.5f;
                    if (now >= _nextListenNod)
                    {
                        float min = Mathf.Min(listenNodEvery.x, listenNodEvery.y);
                        float max = Mathf.Max(listenNodEvery.x, listenNodEvery.y);
                        _nextListenNod = now + UnityEngine.Random.Range(Mathf.Max(0.5f, min), Mathf.Max(0.6f, max));
                        SlowNod(listenNodDegrees * UnityEngine.Random.Range(0.7f, 1.1f));
                    }

                    break;
                case AvatarState.Thinking:
                    // Slightly up and tilted (the eyes go up and to one side).
                    targetRoll = thinkTiltDegrees * _tiltSide;
                    targetPitch = -thinkLiftDegrees;
                    break;
            }

            // Pitch has three parts: the pose (slow), the voice nods
            // and the listening nods (pushes that return to zero on their own).
            _pitch.Step(0f, 2.6f, dt);
            _slowNod.Step(0f, Mathf.Max(0.3f, listenNodHz), dt);
            _pitchPose.Step(targetPitch, 1.2f, dt);
            _yaw.Step(targetYaw, 1.1f, dt);
            _roll.Step(targetRoll, 1.0f, dt);
        }

        // ------------------------------------------------------------------
        // Body: breathing, listening and accents
        // ------------------------------------------------------------------

        private void UpdateBody(float dt)
        {
            UpdateBreath(dt);
            _lean.Step(_state == AvatarState.Listening ? listenLeanDegrees : 0f, 0.8f, dt);
            float now = Time.time;
            for (int i = _accents.Count - 1; i >= 0; i--)
            {
                if (now - _accents[i].Start > AccentSeconds)
                {
                    _accents.RemoveAt(i);
                }
            }

            // Angles for this frame (degrees; pitch positive forward).
            float breath = breathing ? _breathValue * breathChestDegrees * _breathDepth * _breathTuning : 0f;
            float shoulders = breathing ? (_breathValue * 0.5f + 0.5f) * breathShoulderDegrees * _breathDepth * _breathTuning : 0f;
            float spine = 0f;
            float chest = -breath + _lean.Value;
            float neck = 0f;
            float arms = 0f;
            _accentHeadPitch = 0f;
            // Arms only accent if nobody else is using them: not pointing at an image,
            // not walking, not in a directed moment (imposed gaze).
            bool armsFree = !_lookOverride
                            && (choreographer == null || (!choreographer.IsPresenting && !choreographer.IsSuspended));
            _handsFree = armsFree && (choreographer == null || !choreographer.IsPlayingOneShot);
            UpdateHands(dt);
            for (int i = 0; i < _accents.Count; i++)
            {
                float t = now - _accents[i].Start;
                float g = _accents[i].Gain * accentScale * _accentTuning;

                // Wind-up backwards and then the accent, each part a little
                // after the previous one (Genies "breakdown" sequence). The
                // "hip" goes on the lower spine so the legs do not move.
                spine += g * (-0.4f * Pulse(t, 0f, 0.2f) + 2f * Pulse(t, 0.025f, 0.45f));
                chest += g * (-1.2f * Pulse(t, 0f, 0.22f) + 3.4f * Pulse(t, 0.11f, 0.65f));
                neck += g * 2f * Pulse(t, 0.18f, 0.75f);
                _accentHeadPitch += g * 5.5f * Pulse(t, 0.18f, 0.8f);
                if (armsFree)
                {
                    arms += g * (1f * Pulse(t, 0f, 0.22f) - accentArmDegrees * Pulse(t, 0.2f, 0.75f));
                }
            }

            if (!ResolveBody())
            {
                return;
            }

            for (int i = 0; i < BodyBoneCount; i++)
            {
                PrepareBone(i);
            }

            Transform frame = _bodyAnimator.transform;
            Vector3 right = frame.right;
            Vector3 forward = frame.forward;
            RotateBone(BSpine, right, spine);
            RotateBone(_bodyBones[BUpperChest] != null ? BUpperChest : BChest, right, chest);
            RotateBone(BNeck, right, neck);
            LiftShoulder(BLeftShoulder, BLeftArm, forward, shoulders);
            LiftShoulder(BRightShoulder, BRightArm, forward, shoulders);
            RotateBone(BLeftArm, right, arms);
            RotateBone(BRightArm, right, arms);
            ApplyHand(_leftHand, BLeftArm, BLeftLowerArm, BLeftHand, frame, now);
            ApplyHand(_rightHand, BRightArm, BRightLowerArm, BRightHand, frame, now);

            for (int i = 0; i < BodyBoneCount; i++)
            {
                if (_bodyBones[i] != null)
                {
                    _bodyWritten[i] = _bodyBones[i].localRotation;
                    _bodyHasWritten[i] = true;
                }
            }
        }

        /// <summary>
        /// Advances breathing: inhales over 40 % of the cycle and exhales over the
        /// rest, with a smooth curve. Each breath lasts and opens slightly differently.
        /// </summary>
        private void UpdateBreath(float dt)
        {
            _breathPhase += dt * _speedTuning / Mathf.Max(0.5f, _breathPeriod);
            if (_breathPhase >= 1f)
            {
                _breathPhase -= Mathf.Floor(_breathPhase);
                float jitter = Mathf.Clamp(breathJitter, 0f, 0.5f);
                _breathPeriod = Mathf.Max(1f, breathSeconds * (1f + UnityEngine.Random.Range(-jitter, jitter)));
                _breathDepth = 1f + UnityEngine.Random.Range(-jitter, jitter);
            }

            const float inhale = 0.4f;
            float v = _breathPhase < inhale
                ? Smooth(_breathPhase / inhale)
                : 1f - Smooth((_breathPhase - inhale) / (1f - inhale));
            _breathValue = v * 2f - 1f;
        }

        /// <summary>Finds the body bones in the head's Animator (when the avatar changes).</summary>
        private bool ResolveBody()
        {
            if (_bodyResolved && _bodyResolvedFor == headBone)
            {
                return _bodyAnimator != null;
            }

            _bodyResolved = true;
            _bodyResolvedFor = headBone;
            _bodyAnimator = headBone != null ? headBone.GetComponentInParent<Animator>() : null;
            bool any = false;
            for (int i = 0; i < BodyBoneCount; i++)
            {
                _bodyBones[i] = _bodyAnimator != null && _bodyAnimator.isHuman ? _bodyAnimator.GetBoneTransform(BodyBoneIds[i]) : null;
                _bodyHasWritten[i] = false;
                any |= _bodyBones[i] != null;
            }

            if (!any)
            {
                _bodyAnimator = null;
            }

            return _bodyAnimator != null;
        }

        /// <summary>
        /// Leaves the bone at this frame's animation pose. If the
        /// Animator has not written it (it still holds what this component set),
        /// it goes back to the saved pose so the rotation does not accumulate frame by frame.
        /// </summary>
        private void PrepareBone(int index)
        {
            Transform bone = _bodyBones[index];
            if (bone == null)
            {
                return;
            }

            Quaternion now = bone.localRotation;
            Quaternion written = _bodyWritten[index];
            bool stale = _bodyHasWritten[index] && now.x == written.x && now.y == written.y && now.z == written.z && now.w == written.w;
            if (stale)
            {
                bone.localRotation = _bodyBase[index];
            }
            else
            {
                _bodyBase[index] = now;
            }
        }

        private void RotateBone(int index, Vector3 axis, float degrees)
        {
            Transform bone = _bodyBones[index];
            if (bone == null || Mathf.Abs(degrees) < 0.0001f)
            {
                return;
            }

            bone.rotation = Quaternion.AngleAxis(degrees, axis) * bone.rotation;
        }

        // ------------------------------------------------------------------
        // Hands while talking
        // ------------------------------------------------------------------

        /// <summary>Starts a gesture: one hand or both rise in front of the body.</summary>
        private void RaiseHands()
        {
            float now = Time.time;
            if (!handGestures || _state != AvatarState.Speaking || !_handsFree || _handsUp || now < _handsRestUntil)
            {
                return;
            }

            bool both = UnityEngine.Random.value < handBothChance;
            bool right = both || UnityEngine.Random.value < 0.6f;
            bool left = both || !right;
            ShapeHand(_rightHand, right, both);
            ShapeHand(_leftHand, left, both);
            _handsUp = true;
            float min = Mathf.Max(0.5f, Mathf.Min(handHoldSeconds.x, handHoldSeconds.y));
            float max = Mathf.Max(min, Mathf.Max(handHoldSeconds.x, handHoldSeconds.y));
            _handsDownAt = now + UnityEngine.Random.Range(min, max);
        }

        /// <summary>Shape of a hand in this gesture: each one comes out slightly different.</summary>
        private static void ShapeHand(HandGesture hand, bool up, bool both)
        {
            hand.Target = up ? 1f : 0f;
            if (!up)
            {
                return;
            }

            // With both hands, a bit less elbow and more inward: the hands
            // come together as if holding an idea.
            hand.Elbow = UnityEngine.Random.Range(0.85f, 1.05f) * (both ? 0.95f : 1f);
            hand.Forward = UnityEngine.Random.Range(0.7f, 1.2f);
            hand.Palm = UnityEngine.Random.Range(0.7f, 1.15f);
            hand.Inward = UnityEngine.Random.Range(0.6f, 1.1f) * (both ? 1.2f : 1f);
        }

        /// <summary>The hands return to place; with <paramref name="rest"/>, a pause before the next gesture.</summary>
        private void LowerHands(bool rest)
        {
            if (_handsUp && rest)
            {
                float min = Mathf.Max(0f, Mathf.Min(handRestSeconds.x, handRestSeconds.y));
                float max = Mathf.Max(min, Mathf.Max(handRestSeconds.x, handRestSeconds.y));
                _handsRestUntil = Time.time + UnityEngine.Random.Range(min, max);
            }

            _handsUp = false;
            _leftHand.Target = 0f;
            _rightHand.Target = 0f;
        }

        /// <summary>Voice accent: beat of the raised hands, or a new gesture if due.</summary>
        private void HandBeat(float strength)
        {
            if (!handGestures || _state != AvatarState.Speaking || strength < accentThreshold)
            {
                return;
            }

            float now = Time.time;
            if (!_handsUp)
            {
                // In the middle of a long phrase, some stressed syllables also raise the hand.
                if (UnityEngine.Random.value < handGestureChance * 0.35f)
                {
                    RaiseHands();
                }

                return;
            }

            float gain = Mathf.Lerp(0.6f, 1f, Mathf.InverseLerp(accentThreshold, 1f, strength));
            Beat(_leftHand, now, gain);
            Beat(_rightHand, now, gain);
        }

        private static void Beat(HandGesture hand, float now, float gain)
        {
            if (hand.Target > 0f && now - hand.BeatStart > 0.35f)
            {
                hand.BeatStart = now;
                hand.BeatGain = gain;
            }
        }

        /// <summary>Advances the weights: they rise and fall with a spring, and never while the body is busy.</summary>
        private void UpdateHands(float dt)
        {
            if (_handsUp && (!handGestures || _state != AvatarState.Speaking || !_handsFree || Time.time >= _handsDownAt))
            {
                LowerHands(true);
            }

            // With the body busy (a dance, pointing) they drop quickly.
            float fall = _handsFree ? handFallHz : Mathf.Max(handFallHz, 2.5f);
            _leftHand.Weight.Step(_leftHand.Target, handRiseHz, fall, dt);
            _rightHand.Weight.Step(_rightHand.Target, handRiseHz, fall, dt);
        }

        /// <summary>
        /// Moves a hand to its gesture according to its weight: arm forward and open, elbow
        /// bent, arm rotated inward, palm up and wrist back,
        /// plus the accent beats and slow noise so it does not freeze.
        /// </summary>
        private void ApplyHand(HandGesture hand, int arm, int lowerArm, int wrist, Transform frame, float now)
        {
            float w = Mathf.Clamp01(hand.Weight.Value);
            Transform upper = _bodyBones[arm];
            Transform fore = _bodyBones[lowerArm];
            Transform palm = _bodyBones[wrist];
            if (w < 0.001f || upper == null || fore == null)
            {
                return;
            }

            float scale = Mathf.Clamp(_accentTuning, 0f, 1.3f);
            w *= scale;
            if (w < 0.001f)
            {
                return;
            }

            Vector3 right = frame.right;
            Vector3 forward = frame.forward;
            // +1 the avatar's right arm, -1 the left.
            float side = Mathf.Sign(Vector3.Dot(upper.position - frame.position, right));
            float beat = hand.BeatGain * Pulse(now - hand.BeatStart, 0f, 0.42f);
            float t = now * 0.45f;
            float n1 = Mathf.PerlinNoise(hand.NoiseSeed, t) * 2f - 1f;
            float n2 = Mathf.PerlinNoise(hand.NoiseSeed + 3.1f, t * 0.8f) * 2f - 1f;
            float n3 = Mathf.PerlinNoise(hand.NoiseSeed + 7.7f, t * 1.2f) * 2f - 1f;

            float armForward = w * (handArmForwardDegrees * hand.Forward + 3f * n2);
            float armOut = w * handArmOutDegrees;
            float elbow = w * (handElbowDegrees * hand.Elbow + 5f * n1 - handBeatDegrees * beat);
            float inward = w * handArmInwardDegrees * hand.Inward;
            float palmUp = w * (handPalmUpDegrees * hand.Palm + 6f * n3 + handBeatDegrees * 0.6f * beat);
            float wristBack = w * handWristDegrees;

            // 1. Arm: forward (about "right", negative moves forward) and open
            //    (about "forward", the right one opens with positive).
            RotateBone(arm, right, -armForward);
            RotateBone(arm, forward, armOut * side);

            // 2. Elbow: the hinge is perpendicular to the arm and to "forward"; with a
            //    positive angle the hand rises in front.
            Vector3 upperDir = fore.position - upper.position;
            Vector3 hinge = Vector3.Cross(upperDir, forward);
            if (hinge.sqrMagnitude < 1e-8f)
            {
                hinge = -right;
            }

            hinge.Normalize();
            fore.rotation = Quaternion.AngleAxis(elbow, hinge) * fore.rotation;

            // 3. Arm rotated on its axis: the already bent forearm goes toward the center.
            if (upperDir.sqrMagnitude > 1e-8f)
            {
                upper.rotation = Quaternion.AngleAxis(inward * side, upperDir.normalized) * upper.rotation;
            }

            // 4. Palm up: rotation about the forearm axis, split between
            //    forearm and wrist so the skin does not twist at a single point.
            if (palm != null)
            {
                Vector3 foreDir = palm.position - fore.position;
                if (foreDir.sqrMagnitude > 1e-8f)
                {
                    foreDir.Normalize();
                    float supination = -palmUp * side;
                    fore.rotation = Quaternion.AngleAxis(supination * 0.5f, foreDir) * fore.rotation;
                    palm.rotation = Quaternion.AngleAxis(supination * 0.5f, foreDir) * palm.rotation;
                }

                // 5. Wrist: on the same hinge as the elbow (positive raises the hand).
                if (Mathf.Abs(wristBack) > 0.001f)
                {
                    palm.rotation = Quaternion.AngleAxis(wristBack, hinge) * palm.rotation;
                }
            }
        }

        /// <summary>Raises a shoulder <paramref name="degrees"/> (toward the ear), left or right.</summary>
        private void LiftShoulder(int shoulder, int arm, Vector3 forward, float degrees)
        {
            Transform s = _bodyBones[shoulder];
            Transform a = _bodyBones[arm];
            if (s == null || a == null || Mathf.Abs(degrees) < 0.0001f)
            {
                return;
            }

            // Rotating about "forward", an arm on the right rises with a
            // positive angle and one on the left with a negative one.
            float side = Mathf.Sign(Vector3.Dot(a.position - s.position, _bodyAnimator.transform.right));
            RotateBone(shoulder, forward, degrees * side);
        }

        /// <summary>Smooth rise and fall between <paramref name="start"/> and <paramref name="end"/> seconds, peaking at 35 %.</summary>
        private static float Pulse(float t, float start, float end)
        {
            if (t <= start || t >= end)
            {
                return 0f;
            }

            return FaceCurves.Bump((t - start) / (end - start), 0.35f);
        }

        private static float Smooth(float x)
        {
            x = Mathf.Clamp01(x);
            return x * x * (3f - 2f * x);
        }

        // ------------------------------------------------------------------
        // Head
        // ------------------------------------------------------------------

        private void UpdateLook(float deltaTime)
        {
            if (headBone == null)
            {
                return;
            }

            Quaternion baseRotation = headBone.rotation;
            bool wide = choreographer != null && choreographer.IsWideShot;
            float stateWeight = _state == AvatarState.Speaking ? speakingHeadFollow
                : _state == AvatarState.Listening ? listeningHeadFollow : headFollow;
            if (!_lookInitialized)
            {
                _lookOffset = Quaternion.identity;
                _currentWeight = stateWeight;
                _lookInitialized = true;
            }

            float targetWeight = wide ? wideShotLookWeight : stateWeight;
            if (_lookOverride && _lookOverrideWeight >= 0f)
            {
                targetWeight = Mathf.Clamp01(_lookOverrideWeight);
            }

            _currentWeight = Mathf.Lerp(_currentWeight, targetWeight, 1f - Mathf.Exp(-3f * deltaTime));
            _gestureWeight = Mathf.Lerp(_gestureWeight, wide ? 0f : 1f, 1f - Mathf.Exp(-3f * deltaTime));

            Quaternion desiredOffset = Quaternion.identity;
            Vector3 targetPosition;
            Vector3 lookDirection = headBone.forward;
            if (TryGetLookPosition(out targetPosition))
            {
                Vector3 direction = targetPosition - headBone.position;
                if (direction.sqrMagnitude > 0.0001f)
                {
                    lookDirection = direction.normalized;

                    // Slow sway (Perlin noise): a real head is never fixed in place.
                    float swayYaw = FaceCurves.Noise(_noiseSeed, Time.time * 0.35f) * headSwayDegrees;
                    float swayPitch = FaceCurves.Noise(_noiseSeed + 17f, Time.time * 0.28f) * headSwayDegrees;
                    Quaternion desired = Quaternion.LookRotation(lookDirection, Vector3.up)
                                         * Quaternion.Euler(headRotationOffset)
                                         * Quaternion.Euler(swayPitch, swayYaw, 0f);
                    Quaternion limited = Quaternion.RotateTowards(baseRotation, desired, maxLookAngle);

                    // Deviation from the animation, in local space: travels with the body.
                    desiredOffset = Quaternion.Inverse(baseRotation) * limited;
                }
            }

            _lookOffset = Quaternion.Slerp(_lookOffset, desiredOffset, StepFor(deltaTime));
            Quaternion looked = baseRotation * Quaternion.Slerp(Quaternion.identity, _lookOffset, _currentWeight);

            // Gestures on top of the gaze, in world axes aligned with it:
            // pitch about the "right" axis, turn about the vertical
            // and tilt about the gaze direction. During
            // dances the animation leads: the gestures are switched off.
            Vector3 forward = Vector3.ProjectOnPlane(lookDirection, Vector3.up);
            if (forward.sqrMagnitude < 0.0001f)
            {
                forward = Vector3.ProjectOnPlane(headBone.forward, Vector3.up);
            }

            forward.Normalize();
            Vector3 right = Vector3.Cross(Vector3.up, forward).normalized;
            float pitch = _pitch.Value + _slowNod.Value + _pitchPose.Value + _accentHeadPitch;
            Quaternion gesture = Quaternion.AngleAxis(_roll.Value * _gestureWeight, forward)
                                 * Quaternion.AngleAxis(pitch * _gestureWeight, right)
                                 * Quaternion.AngleAxis(_yaw.Value * _gestureWeight, Vector3.up);
            headBone.rotation = gesture * looked;
        }

        private float StepFor(float deltaTime)
        {
            return 1f - Mathf.Exp(-Mathf.Max(0.1f, lookSmoothing) * deltaTime);
        }

        /// <summary>World point the head is looking at right now (user, panel or the thinking point).</summary>
        public bool TryGetLookPosition(out Vector3 position)
        {
            if (TryGetOverrideOrPanel(out position))
            {
                return true;
            }

            if (_state == AvatarState.Thinking)
            {
                if (thinkingLookTarget != null)
                {
                    position = thinkingLookTarget.position;
                    return true;
                }

                Transform root = avatarRoot != null ? avatarRoot : transform;
                Vector3 origin = headBone != null ? headBone.position : root.position;
                Vector3 side = root.right * (thinkingGaze.x * _tiltSide);
                position = origin + side + Vector3.up * thinkingGaze.y + FacingOf(root) * thinkingGaze.z;
                return true;
            }

            return TryGetVisitor(out position);
        }

        /// <summary>
        /// Base point of the eyes: the same as the head except while thinking, where
        /// the eyes start from the user and their gaze template takes them up
        /// and to one side (EyeGazeController).
        /// </summary>
        public bool TryGetEyeTarget(out Vector3 position)
        {
            if (TryGetOverrideOrPanel(out position))
            {
                return true;
            }

            return TryGetVisitor(out position);
        }

        /// <summary>True if an imposed gaze (walking) or the glance at the panel is leading now.</summary>
        public bool HasDirectedGaze
        {
            get
            {
                Vector3 unused;
                return TryGetOverrideOrPanel(out unused);
            }
        }

        private bool TryGetOverrideOrPanel(out Vector3 position)
        {
            if (_lookOverride)
            {
                position = _lookOverridePosition;
                return true;
            }

            // A brief glance at the panel when the image appears; then the
            // gaze goes back to the user, which is natural in a conversation.
            bool glancing = imageGlanceSeconds <= 0f || Time.time - _imageShownAt < imageGlanceSeconds;
            if (lookAtImageWhenVisible && _imageVisible && imageLookTarget != null && glancing)
            {
                position = imageLookTarget.position;
                return true;
            }

            position = Vector3.zero;
            return false;
        }

        private bool TryGetVisitor(out Vector3 position)
        {
            if (lookTarget != null)
            {
                position = lookTarget.position;
                return true;
            }

            Camera main = Camera.main;
            if (main != null)
            {
                position = main.transform.position;
                return true;
            }

            position = Vector3.zero;
            return false;
        }

        /// <summary>Where the avatar looks horizontally: toward the camera if there is one.</summary>
        private Vector3 FacingOf(Transform root)
        {
            Vector3 toward = Vector3.zero;
            if (lookTarget != null && headBone != null)
            {
                toward = lookTarget.position - headBone.position;
            }
            else if (Camera.main != null && headBone != null)
            {
                toward = Camera.main.transform.position - headBone.position;
            }

            toward = Vector3.ProjectOnPlane(toward, Vector3.up);
            if (toward.sqrMagnitude < 0.0001f)
            {
                toward = Vector3.ProjectOnPlane(root.forward, Vector3.up);
            }

            return toward.normalized;
        }

        // ------------------------------------------------------------------
        // Blinking
        // ------------------------------------------------------------------

        private void UpdateBlink(float deltaTime)
        {
            if (faceRig == null || (_blinkLeftChannel < 0 && _blinkRightChannel < 0))
            {
                return;
            }

            float left = 0f;
            float right = 0f;
            if (_blinkElapsed >= 0f)
            {
                _blinkElapsed += deltaTime;
                float duration = Mathf.Max(0.08f, blinkSeconds);
                left = BlinkCurve(_blinkElapsed - _blinkLeftDelay, duration) * _blinkDepth;
                right = BlinkCurve(_blinkElapsed - _blinkRightDelay, duration) * _blinkDepth;
                if (_blinkElapsed >= duration + Mathf.Max(_blinkLeftDelay, _blinkRightDelay))
                {
                    _blinkElapsed = -1f;
                    if (_pendingSecondBlink >= 0f)
                    {
                        _timeToNextBlink = _pendingSecondBlink;
                        _pendingSecondBlink = -1f;
                    }
                    else
                    {
                        ScheduleNextBlink();
                    }
                }
            }
            else
            {
                _timeToNextBlink -= deltaTime;
                if (_timeToNextBlink <= 0f)
                {
                    StartBlink(UnityEngine.Random.value < 0.1f ? 0.6f : 1f);
                    if (UnityEngine.Random.value < doubleBlinkShare)
                    {
                        _pendingSecondBlink = UnityEngine.Random.Range(0.05f, 0.3f);
                    }
                }
            }

            // The upper eyelid follows the gaze: it lowers when looking down.
            float lidTarget = 0f;
            if (eyeGaze != null)
            {
                lidTarget = Mathf.Clamp01(eyeGaze.CurrentPitchDown / 10f) * lidFollowsGaze;
            }

            _lid = Mathf.Lerp(_lid, lidTarget, 1f - Mathf.Exp(-12f * deltaTime));
            faceRig.Add(_blinkLeftChannel, Mathf.Clamp01(Mathf.Max(left, _lid)));
            faceRig.Add(_blinkRightChannel, Mathf.Clamp01(Mathf.Max(right, _lid)));

            // The brows lower a little with the blink, more slowly than the eyelid.
            _browBlink.Step(Mathf.Max(left, right), 2.5f, deltaTime);
            float brow = Mathf.Clamp01(_browBlink.Value) * blinkBrowLower;
            faceRig.Add(_browLeftChannel, brow);
            faceRig.Add(_browRightChannel, brow);
        }

        /// <summary>
        /// Blink shape, 0..1: closes in a third of the duration (fast,
        /// slows as it closes) and opens in two thirds (starts slowly). This way the eye
        /// spends a bit over 0.25 s half closed, as in Genies.
        /// </summary>
        private static float BlinkCurve(float t, float duration)
        {
            if (t <= 0f || t >= duration)
            {
                return 0f;
            }

            float close = duration / 3f;
            if (t < close)
            {
                float x = t / close;
                return 1f - (1f - x) * (1f - x);
            }

            float y = (t - close) / (duration - close);
            return 1f - y * y;
        }

        /// <summary>Blinks right now (if not already blinking). Used by gaze changes.</summary>
        public void TriggerBlink()
        {
            if (_blinkElapsed < 0f)
            {
                StartBlink(1f);
            }
        }

        private void StartBlink(float depth)
        {
            _blinkElapsed = 0f;
            _blinkDepth = depth;

            // One eye starts a few milliseconds before the other.
            float offset = UnityEngine.Random.Range(0f, Mathf.Max(0f, blinkEyeOffset));
            bool leftFirst = UnityEngine.Random.value < 0.5f;
            _blinkLeftDelay = leftFirst ? 0f : offset;
            _blinkRightDelay = leftFirst ? offset : 0f;
        }

        private void ScheduleNextBlink()
        {
            float min = Mathf.Max(0.2f, Mathf.Min(blinkEvery.x, blinkEvery.y));
            float max = Mathf.Max(min + 0.1f, Mathf.Max(blinkEvery.x, blinkEvery.y));
            _timeToNextBlink = UnityEngine.Random.Range(min, max);
        }
    }
}
