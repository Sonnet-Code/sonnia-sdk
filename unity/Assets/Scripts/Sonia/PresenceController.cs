// Walking out and in: the "away" mode of the control panel.
//
// With presence present=false Sonnia looks to one side, turns with a soft
// blend while taking her first steps and walks out of frame; once
// out, the away sign appears (AwaySignController). With present=true the sign
// leaves, Sonnia walks in from that same side, brakes, turns toward the camera
// and the choreographer takes the body back.
//
// How foot sliding is avoided: the walk cycle carries forward root motion
// (the official Genies Walk). While walking, applyRootMotion is turned
// on, Animator.deltaPosition is read every frame and Sonnia moves
// exactly as far as that motion covers across the width of the screen (its
// projection on the camera's lateral axis). What the clip advances toward or
// away from the camera is discarded: Sonnia never leaves her line, and that
// depth slide is invisible from the front. Since the
// projection depends on where she faces, when turning the lateral advance grows by itself
// (sine of the turn) and the start-up looks natural. To brake exactly in place, the
// root motion is replaced by a Hermite curve that starts from the measured
// velocity and arrives stopped at the mark: with a linearly decreasing velocity, just
// like the blend from walking to idle over that same time, the steps get
// shorter at the same time as the displacement.
//
// If there is no walk clip (the Genies Avatar SDK is not installed, so the set has none)
// or the clip has no root motion, Sonnia moves at an estimated speed:
// she slides, but never breaks or is left half way.
//
// Runs in LateUpdate with order 10500: after the animation is evaluated and
// Unity applies the root motion (which gets overwritten), and before the gaze
// (AvatarStateController 12000, EyeGazeController 12100), which thus already see
// Sonnia in her place for this frame.

using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Side of the screen Sonnia leaves by and walks back in from.</summary>
    public enum ScreenSide
    {
        Left = 0,
        Right = 1
    }

    /// <summary>
    /// Takes Sonnia off screen by walking and brings her back (message
    /// <c>presence</c>). SoniaBootstrap adds it in code if the scene does not have it.
    /// </summary>
    [DefaultExecutionOrder(10500)]
    [DisallowMultipleComponent]
    public class PresenceController : MonoBehaviour
    {
        /// <summary>Away sign text if the orchestrator does not send another.</summary>
        public const string DefaultAwayMessage = "I stepped away, back in a moment";

        private enum Phase
        {
            /// <summary>In place; the choreographer is in charge.</summary>
            Present,

            /// <summary>Just received "away": goes back to idle and looks toward the exit.</summary>
            Leaving,

            /// <summary>Turns toward the exit while starting to walk.</summary>
            TurningOut,

            /// <summary>Walks out until she is out of frame.</summary>
            WalkingOut,

            /// <summary>Out of frame, hidden, with the sign up.</summary>
            Away,

            /// <summary>Just received "back": the sign goes away; stays out for a moment.</summary>
            Returning,

            /// <summary>Walks in toward her place.</summary>
            WalkingIn,

            /// <summary>Brakes to her mark and turns toward the camera.</summary>
            Arriving
        }

        /// <summary>
        /// Cubic Hermite curve from one value to another in a given time, starting
        /// with a velocity and arriving stopped. With zero initial velocity it is a
        /// smoothstep; when restarted from the current value and velocity, a
        /// change of plans midway causes no jerks.
        /// </summary>
        private struct Hermite
        {
            public float From;
            public float Velocity;
            public float To;
            public float Duration;
            public float Elapsed;
            public bool Active;

            public void Start(float from, float velocity, float to, float duration)
            {
                From = from;
                Velocity = velocity;
                To = to;
                Duration = Mathf.Max(0.01f, duration);
                Elapsed = 0f;
                Active = true;
            }

            public float Step(float deltaTime, out float velocity)
            {
                if (!Active)
                {
                    velocity = 0f;
                    return To;
                }

                Elapsed += deltaTime;
                float s = Mathf.Clamp01(Elapsed / Duration);
                if (s >= 1f)
                {
                    Active = false;
                    velocity = 0f;
                    return To;
                }

                float s2 = s * s;
                float s3 = s2 * s;
                float h00 = (2f * s3) - (3f * s2) + 1f;
                float h10 = s3 - (2f * s2) + s;
                float h01 = (-2f * s3) + (3f * s2);
                float d00 = (6f * s2) - (6f * s);
                float d10 = (3f * s2) - (4f * s) + 1f;
                float d01 = (-6f * s2) + (6f * s);
                velocity = (((d00 * From) + (d01 * To)) / Duration) + (d10 * Velocity);
                return (h00 * From) + (h10 * Duration * Velocity) + (h01 * To);
            }
        }

        [Header("References")]
        [SerializeField]
        [Tooltip("Choreographer. Suspended while Sonnia leaves, is away and comes back. If empty, it is looked up on this object or its children.")]
        private AvatarChoreographer choreographer;

        [SerializeField]
        [Tooltip("Clip player. Empty: the choreographer's.")]
        private MotionPlayer motionPlayer;

        [SerializeField]
        [Tooltip("Avatar Animator: its transform is the one that moves. Empty: the player's.")]
        private Animator animator;

        [SerializeField]
        [Tooltip("Head gaze (and eyes, which read the same point). Empty: looked up in the children.")]
        private AvatarStateController stateController;

        [SerializeField]
        [Tooltip("Camera framing: opens the shot while she leaves and returns. Empty: looked up in the children.")]
        private CameraFramingController cameraFraming;

        [SerializeField]
        [Tooltip("Sign that stays while she is away. Empty: looked up or created on this object.")]
        private AwaySignController sign;

        [Header("Path")]
        [SerializeField]
        [Tooltip("Side of the screen she leaves by and walks back in from.")]
        private ScreenSide exitSide = ScreenSide.Right;

        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Seconds between receiving 'away' and starting to turn: goes back to idle, looks toward the exit (the gaze leads the body) and the camera starts to open.")]
        private float exitDelaySeconds = 0.5f;

        [SerializeField]
        [Range(0.3f, 2f)]
        [Tooltip("Duration of a 90 degree turn (smooth ease in and out). Larger turns take a bit longer.")]
        private float turnSecondsPer90 = 0.75f;

        [SerializeField]
        [Range(0.1f, 1.5f)]
        [Tooltip("Blend from idle to the walk cycle when starting. Matches the turn: the first steps are taken while turning.")]
        private float walkBlendInSeconds = 0.45f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Point of the walk cycle (0..1) at which it is entered when starting. Used to choose which foot takes the first step.")]
        private float walkStartNormalizedTime = 0f;

        [SerializeField]
        [Range(0.3f, 2f)]
        [Tooltip("Seconds of braking on arrival at her place, at normal walking speed. Also sets how far away she starts braking (speed x this time / 2).")]
        private float arriveSeconds = 0.9f;

        [SerializeField]
        [Range(0f, 0.9f)]
        [Tooltip("Fraction of the braking that passes before she starts turning toward the camera.")]
        private float arriveTurnDelay = 0.3f;

        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Seconds between receiving 'back' and starting to walk in from outside: lets the sign start to leave.")]
        private float entryDelaySeconds = 0.3f;

        [SerializeField]
        [Range(0.05f, 1f)]
        [Tooltip("Blend to idle on receiving 'away', in case she was talking, dancing or pointing.")]
        private float settleFadeSeconds = 0.4f;

        [SerializeField]
        [Range(0.05f, 1f)]
        [Tooltip("Blend with which the choreographer takes the state back on return, if it is not idle.")]
        private float resumeFadeSeconds = 0.4f;

        [Header("Out of frame")]
        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Meters added to the bones (hair, thickness of arms and hands) to decide that none of her is visible anymore.")]
        private float bodyMargin = 0.3f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Extra meters, out of frame, from which she starts to enter when coming back.")]
        private float extraOffscreenDistance = 0.2f;

        [SerializeField]
        [Range(1f, 12f)]
        [Tooltip("Maximum distance she travels: safety net if she fails to leave the frame.")]
        private float maxWalkDistance = 6f;

        [SerializeField]
        [Range(2f, 30f)]
        [Tooltip("Maximum seconds walking in one direction: safety net.")]
        private float maxWalkSeconds = 10f;

        [SerializeField]
        [Tooltip("Turn off the avatar renderers while away (not visible, casts no shadow, and costs no GPU).")]
        private bool hideRenderersWhenAway = true;

        [Header("Speed")]
        [SerializeField]
        [Tooltip("Move Sonnia with the walk clip's root motion (feet do not slide). Off: estimated speed.")]
        private bool useRootMotion = true;

        [SerializeField]
        [Range(0.3f, 3f)]
        [Tooltip("Speed (m/s) if the walk clip has no root motion or useful average speed.")]
        private float fallbackWalkSpeed = 1.3f;

        [SerializeField]
        [Range(0.3f, 3f)]
        [Tooltip("Speed (m/s) of the fallback without a walk clip: she slides out in idle.")]
        private float slideSpeed = 1.2f;

        [Header("Gaze")]
        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Weight of the gaze toward where she is going while walking (the clip's head leads the rest).")]
        private float walkLookWeight = 0.5f;

        [SerializeField]
        [Range(0.5f, 10f)]
        [Tooltip("Meters ahead she looks while walking.")]
        private float lookAheadDistance = 4f;

        [SerializeField]
        [Range(0f, 1.5f)]
        [Tooltip("Meters below the eyes of the point she looks at while walking (she looks slightly at the floor ahead).")]
        private float lookAheadDrop = 0.3f;

        [SerializeField]
        [Range(0f, 3f)]
        [Tooltip("On return, meters left to her place when she looks at the user again (with a blink). The gaze leads the body's turn.")]
        private float lookBackDistance = 0.9f;

        [Header("Sign")]
        [SerializeField]
        [Tooltip("Sign text if the orchestrator does not send any.")]
        private string defaultMessage = DefaultAwayMessage;

        [SerializeField]
        [Tooltip("Show the sign once out of frame.")]
        private bool useSign = true;

        [Header("Log")]
        [SerializeField]
        [Tooltip("Write every step of the exit and entrance to the console.")]
        private bool logEvents = true;

        private const float EdgeMargin = 0.02f;
        private const float VelocitySmoothing = 0.3f;

        private bool _initialized;
        private Phase _phase = Phase.Present;
        private bool _targetPresent = true;

        private float _phaseTime;
        private string _message;

        private Transform _avatar;
        private Transform _head;
        private Transform[] _probeBones = new Transform[0];
        private Renderer[] _renderers = new Renderer[0];
        private bool[] _rendererStates = new bool[0];
        private bool _hidden;
        private Vector3 _restLocalPosition;
        private Quaternion _restLocalRotation = Quaternion.identity;
        // Parent of the avatar when its place was taken: avatars that arrive
        // later under the same parent go to that place (see Initialize).
        private Transform _restParent;
        private bool _hasRest;

        // Lateral axis (world, horizontal) toward the exit side, and horizontal
        // direction toward the camera, which is where Sonnia looks at idle.
        private Vector3 _sideAxis = Vector3.right;
        private Vector3 _restFacing = Vector3.back;
        private float _yawExit = -90f;
        private float _yawHome = 90f;

        // Kinematics: displacement along the lateral axis (0 = her place,
        // positive toward the exit) and turn relative to the idle pose.
        private float _offset;
        private float _previousOffset;
        private float _lateralVelocity;
        private float _yaw;
        private float _yawVelocity;
        private Hermite _turn;
        private Hermite _arrive;
        private bool _arriveTurnStarted;
        private bool _lookedBack;

        // Walk weight according to the blends requested (for the
        // estimated speed; with root motion the Animator itself provides it).
        private float _walkWeight;
        private float _walkWeightTarget;
        private float _walkWeightRate = float.PositiveInfinity;

        private MotionPlayer.Handle _body;
        private bool _wantsWide;
        private float _clipSpeed;
        private bool _useEstimate;
        private float _probeEstimated;
        private float _probeMeasured;
        private readonly List<ShotPose> _poses = new List<ShotPose>();

        // ------------------------------------------------------------------
        // Public state
        // ------------------------------------------------------------------

        /// <summary>True with Sonnia in place and the choreographer in charge.</summary>
        public bool IsPresent
        {
            get { return _phase == Phase.Present; }
        }

        /// <summary>The last thing the orchestrator asked for: true if it wants Sonnia on screen.</summary>
        public bool TargetPresent
        {
            get { return _targetPresent; }
        }

        /// <summary>True with Sonnia already out of frame (sign up).</summary>
        public bool IsAway
        {
            get { return _phase == Phase.Away; }
        }

        /// <summary>Current phase, for debugging and for editor tests.</summary>
        public string PhaseName
        {
            get { return _phase.ToString(); }
        }

        /// <summary>Meters she is away from her place, toward the exit side.</summary>
        public float Offset
        {
            get { return _offset; }
        }

        /// <summary>True while the camera should be on the exit shot (full body).</summary>
        public bool WantsWideShot
        {
            get { return _wantsWide; }
        }

        /// <summary>Current sign text.</summary>
        public string Message
        {
            get { return string.IsNullOrEmpty(_message) ? defaultMessage : _message; }
        }

        /// <summary>Sign in use (created by this component if there is none and it uses a sign).</summary>
        public AwaySignController Sign
        {
            get { return sign; }
        }

        private AnimationClip WalkClip
        {
            get
            {
                SoniaMotionSet set = choreographer != null ? choreographer.MotionSet : null;
                return set != null ? set.walk : null;
            }
        }

        private AnimationClip IdleClip
        {
            get
            {
                SoniaMotionSet set = choreographer != null ? choreographer.MotionSet : null;
                return set != null ? set.idleLoop : null;
            }
        }

        private bool PlayerReady
        {
            get { return motionPlayer != null && motionPlayer.IsReady; }
        }

        // ------------------------------------------------------------------
        // Lifecycle
        // ------------------------------------------------------------------

        private void Awake()
        {
            if (choreographer == null)
            {
                choreographer = GetComponentInChildren<AvatarChoreographer>(true);
            }

            if (stateController == null)
            {
                stateController = GetComponentInChildren<AvatarStateController>(true);
            }

            if (cameraFraming == null)
            {
                cameraFraming = GetComponentInChildren<CameraFramingController>(true);
            }

            if (sign == null && useSign)
            {
                sign = GetComponentInChildren<AwaySignController>(true);
            }

            if (sign == null && useSign)
            {
                sign = gameObject.AddComponent<AwaySignController>();
            }

            _message = defaultMessage;
        }

        private void Start()
        {
            Initialize();
        }

        /// <summary>
        /// First step of an avatar change: the current one goes back to its idle
        /// pose (so the new one copies it) without forgetting whether Sonnia should be
        /// away. Afterwards <see cref="Rebind"/> must be called.
        /// </summary>
        public void ReleaseAvatar()
        {
            if (_initialized && _avatar != null && _phase != Phase.Present)
            {
                bool target = _targetPresent;
                Settle("avatar change");
                _targetPresent = target;
            }
        }

        /// <summary>
        /// Second step of an avatar change: takes the idle of the new one and, if
        /// Sonnia was away, takes it out instantly (no animation, with sign).
        /// </summary>
        public void Rebind(Animator newAnimator)
        {
            bool away = !_targetPresent;
            animator = newAnimator;
            _initialized = false;
            Initialize();
            if (away)
            {
                // Stays away without animation (and without touching the sign or its text).
                _targetPresent = false;
                GoAway(true);
            }
        }

        /// <summary>
        /// Takes the avatar's idle pose and the exit geometry. It is
        /// called automatically in Start (with Sonnia in place); earlier, if a
        /// <c>presence</c> arrives very early.
        /// </summary>
        private void Initialize()
        {
            if (_initialized)
            {
                return;
            }

            _initialized = true;
            if (motionPlayer == null && choreographer != null)
            {
                motionPlayer = choreographer.Player;
            }

            if (motionPlayer == null)
            {
                motionPlayer = GetComponentInChildren<MotionPlayer>(true);
            }

            if (animator == null && motionPlayer != null)
            {
                animator = motionPlayer.Animator;
            }

            if (animator == null)
            {
                animator = GetComponentInChildren<Animator>(true);
            }

            if (animator == null)
            {
                Debug.LogWarning("[Sonnia] Presence without Animator: away mode will only show the sign.", this);
                return;
            }

            _avatar = animator.transform;
            if (_hasRest && _avatar.parent == _restParent)
            {
                // Avatar change: its place is the usual one, not where the previous one
                // left it. If the previous one was out of frame, the new one copied
                // that position as idle and, on return, stopped out of camera.
                _avatar.localPosition = _restLocalPosition;
                _avatar.localRotation = _restLocalRotation;
            }
            else
            {
                _restLocalPosition = _avatar.localPosition;
                _restLocalRotation = _avatar.localRotation;
                _restParent = _avatar.parent;
                _hasRest = true;
            }

            Camera view = ViewCamera();
            Vector3 cameraRight = view != null ? view.transform.right : Vector3.right;
            cameraRight.y = 0f;
            if (cameraRight.sqrMagnitude < 0.0001f)
            {
                cameraRight = Vector3.right;
            }

            cameraRight.Normalize();
            _sideAxis = exitSide == ScreenSide.Right ? cameraRight : -cameraRight;

            // At idle Sonnia looks at the camera (the whole setup assumes it).
            Vector3 toCamera = view != null ? view.transform.position - _avatar.position : -_avatar.forward;
            toCamera.y = 0f;
            if (toCamera.sqrMagnitude < 0.0001f)
            {
                toCamera = Vector3.Cross(cameraRight, Vector3.up);
            }

            _restFacing = toCamera.normalized;
            _yawExit = Vector3.SignedAngle(_restFacing, _sideAxis, Vector3.up);
            _yawHome = Vector3.SignedAngle(_restFacing, -_sideAxis, Vector3.up);

            if (animator.isHuman)
            {
                _head = animator.GetBoneTransform(HumanBodyBones.Head);
                HumanBodyBones[] probes =
                {
                    HumanBodyBones.Head, HumanBodyBones.Hips, HumanBodyBones.Chest,
                    HumanBodyBones.LeftHand, HumanBodyBones.RightHand,
                    HumanBodyBones.LeftLowerArm, HumanBodyBones.RightLowerArm,
                    HumanBodyBones.LeftFoot, HumanBodyBones.RightFoot,
                    HumanBodyBones.LeftToes, HumanBodyBones.RightToes
                };
                List<Transform> found = new List<Transform>();
                for (int i = 0; i < probes.Length; i++)
                {
                    Transform bone = animator.GetBoneTransform(probes[i]);
                    if (bone != null)
                    {
                        found.Add(bone);
                    }
                }

                _probeBones = found.ToArray();
            }

            if (_probeBones.Length == 0)
            {
                _probeBones = new[] { _avatar };
            }

            // If it was hidden (away) with the previous avatar, visibility is
            // restored before switching renderers. Otherwise the new one inherited
            // _hidden without having saved its states and, on return, all of them
            // were switched off: Sonnia came back to her place invisible (avatar changed while away).
            SetHidden(false);
            _renderers = _avatar.GetComponentsInChildren<Renderer>(true);
            _rendererStates = new bool[_renderers.Length];

            // Average clip speed, as a fallback if no root motion arrives.
            AnimationClip walk = WalkClip;
            if (walk != null)
            {
                Vector3 average = walk.averageSpeed;
                float speed = new Vector2(average.x, average.z).magnitude * (animator.isHuman ? animator.humanScale : 1f);
                _clipSpeed = speed >= 0.3f && speed <= 3f ? speed : 0f;
            }
        }

        private void OnDisable()
        {
            // If the component is switched off midway through returning, Sonnia ends up in her
            // place. If she should be away, she stays as she is (hidden or leaving):
            // a script reload in Play switches all components off and on
            // and must not bring her back.
            if (_initialized && _avatar != null && _phase != Phase.Present && _targetPresent)
            {
                Settle("component disabled");
            }
        }

        // ------------------------------------------------------------------
        // Entry
        // ------------------------------------------------------------------

        /// <summary>
        /// Applies the <c>presence</c> message. With the same <paramref name="present"/>
        /// it already had it only changes the sign text. With
        /// <paramref name="instant"/> (right after connecting) it is applied without animation.
        /// A change of plans midway (back while leaving, or leaving while
        /// entering) chains on from where she is, without jumps.
        /// </summary>
        public void SetPresent(bool present, string message, bool instant)
        {
            Initialize();

            if (!string.IsNullOrWhiteSpace(message))
            {
                _message = message.Trim();
            }
            else if (!present)
            {
                _message = defaultMessage;
            }

            if (sign != null)
            {
                sign.SetMessage(Message);
            }

            if (present == _targetPresent)
            {
                return;
            }

            _targetPresent = present;
            if (present)
            {
                ComeBack(instant);
            }
            else
            {
                GoAway(instant);
            }
        }

        /// <summary>
        /// Where a point of the avatar (for example, her head) would be with Sonnia in
        /// her place, even if she is now out of frame or turned toward the exit. The
        /// camera frames with this: if a new avatar arrives while she is away, the
        /// head is a meter and a half from its place, and the conversation shot
        /// came out centered on the gap (on return, Sonnia ended up out of camera).
        /// </summary>
        public Vector3 AtHome(Vector3 worldPoint)
        {
            if (_avatar == null || !_hasRest)
            {
                return worldPoint;
            }

            Transform parent = _avatar.parent;
            Vector3 home = parent != null ? parent.TransformPoint(_restLocalPosition) : _restLocalPosition;
            Quaternion homeRotation = parent != null ? parent.rotation * _restLocalRotation : _restLocalRotation;
            Vector3 local = Quaternion.Inverse(_avatar.rotation) * (worldPoint - _avatar.position);
            return home + (homeRotation * local);
        }

        /// <summary>Toggles between away and present with animation (test button).</summary>
        public void TogglePresence()
        {
            SetPresent(!_targetPresent, null, false);
        }

        private bool CanShowSign
        {
            get { return sign != null; }
        }

        private void ShowSign(bool instant)
        {
            if (CanShowSign)
            {
                sign.Show(Message, instant);
            }
        }

        private void GoAway(bool instant)
        {
            if (_avatar == null)
            {
                _phase = Phase.Away;
                ShowSign(instant);
                return;
            }

            if (instant)
            {
                GoAwayInstant();
                return;
            }

            switch (_phase)
            {
                case Phase.Present:
                    BeginLeaving();
                    break;
                case Phase.Returning:
                    // Had not started entering yet: stays away.
                    _phase = Phase.Away;
                    _phaseTime = 0f;
                    ShowSign(false);

                    Log("stays away");
                    break;
                case Phase.WalkingIn:
                case Phase.Arriving:
                    TurnBackOut();
                    break;
            }
        }

        private void ComeBack(bool instant)
        {
            if (_avatar == null)
            {
                _phase = Phase.Present;
                if (sign != null)
                {
                    sign.Hide(instant);
                }

                return;
            }

            if (instant)
            {
                if (sign != null)
                {
                    sign.Hide(true);
                }

                Settle("returns without animation");
                if (cameraFraming != null)
                {
                    cameraFraming.SnapNextFrame();
                }

                return;
            }

            switch (_phase)
            {
                case Phase.Leaving:
                    // Had not moved from her place yet.
                    Settle("stays: had not left yet");
                    break;
                case Phase.TurningOut:
                case Phase.WalkingOut:
                    TurnBackIn();
                    break;
                case Phase.Away:
                    BeginReturning();
                    break;
            }
        }

        // ------------------------------------------------------------------
        // Transitions
        // ------------------------------------------------------------------

        private void BeginLeaving()
        {
            SetPhase(Phase.Leaving);
            _wantsWide = true;
            if (choreographer != null)
            {
                choreographer.Suspend();
            }

            PlayIdle(settleFadeSeconds, true);
            _offset = 0f;
            _previousOffset = 0f;
            _lateralVelocity = 0f;
            _yaw = 0f;
            _yawVelocity = 0f;
            _turn.Active = false;
            _arrive.Active = false;

            // The gaze leads: first the eyes (with a blink, as in
            // any big gaze change) and the head, then the body.
            if (stateController != null)
            {
                stateController.TriggerBlink();
            }

            Log("leaving: looks toward the exit (" + exitSide + ")");
        }

        private void StartTurnOut()
        {
            SetPhase(Phase.TurningOut);
            StartTurn(_yawExit);
            PlayWalk(walkBlendInSeconds);
            SetRootMotion(true);
            Log("turns and starts walking" + (WalkClip == null ? " (no walk clip: slides)" : string.Empty));
        }

        private void TurnBackOut()
        {
            SetPhase(Phase.TurningOut);
            _wantsWide = true;
            _lookedBack = false;
            _arrive.Active = false;
            SetHidden(false);
            StartTurn(_yawExit);
            PlayWalk(0.35f);
            SetRootMotion(true);
            Log("change of plans: turns around and leaves again");
        }

        private void TurnBackIn()
        {
            SetPhase(Phase.WalkingIn);
            _lookedBack = false;
            StartTurn(_yawHome);
            if (!WalkIsPlaying())
            {
                PlayWalk(0.35f);
            }

            SetRootMotion(true);
            Log("change of plans: turns around and returns");
        }

        private void EnterAway(bool instant)
        {
            SetPhase(Phase.Away);
            SetRootMotion(false);
            PlayIdle(instant ? 0f : 0.2f, false);
            SetHidden(true);
            _wantsWide = true;
            _lateralVelocity = 0f;
            if (stateController != null)
            {
                stateController.ClearLookOverride();
            }

            ShowSign(instant);
            Log("out of frame (" + _offset.ToString("F2") + " m)" + (CanShowSign ? ": sign up" : ", no sign"));
        }

        private void GoAwayInstant()
        {
            if (choreographer != null)
            {
                choreographer.Suspend();
            }

            if (cameraFraming != null)
            {
                cameraFraming.SnapNextFrame();
            }

            _turn.Active = false;
            _arrive.Active = false;
            _yawVelocity = 0f;

            // Out of any framing right now (computed before moving).
            float offscreen = ComputeOffscreenOffset() + extraOffscreenDistance;
            _offset = Mathf.Min(offscreen, maxWalkDistance);
            _previousOffset = _offset;
            _yaw = _yawExit;
            ApplyPose();
            EnterAway(true);
            Log("away without animation");
        }

        private void BeginReturning()
        {
            SetPhase(Phase.Returning);
            _wantsWide = true;
            if (sign != null)
            {
                sign.Hide(false);
            }

            Log("returns: sign is removed");
        }

        private void StartWalkIn()
        {
            float start = Mathf.Max(_offset, ComputeOffscreenOffset() + extraOffscreenDistance);
            _offset = Mathf.Min(start, maxWalkDistance);
            _previousOffset = _offset;
            _yaw = _yawHome;
            _yawVelocity = 0f;
            _turn.Active = false;
            _lookedBack = false;
            ApplyPose();
            SetHidden(false);
            PlayWalk(0f);
            SetRootMotion(true);
            _lateralVelocity = -EstimatedSpeed();
            SetPhase(Phase.WalkingIn);
            Log("walks in from " + _offset.ToString("F2") + " m");
        }

        private void StartArrive()
        {
            float from = _offset;
            float towardHome = -_lateralVelocity;
            float duration = towardHome > 0.25f && from > 0.01f
                ? Mathf.Clamp(2f * from / towardHome, 0.35f, 2.5f)
                : arriveSeconds;

            // Hermite from (current place, current velocity) to (her mark, stopped):
            // with this duration it is a parabola, linearly decreasing velocity to zero.
            _arrive.Start(from, _lateralVelocity, 0f, duration);
            _arriveTurnStarted = false;
            SetPhase(Phase.Arriving);

            // Walking blends into idle over the same time she brakes.
            PlayIdle(duration, false);
            SetRootMotion(false);

            // The camera starts to close while she arrives.
            _wantsWide = false;
            LookBackAtVisitor();
            Log("brakes " + from.ToString("F2") + " m from her place over " + duration.ToString("F2") + " s");
        }

        /// <summary>Leaves Sonnia in her place, facing front, and gives the body back to the choreographer.</summary>
        private void Settle(string why)
        {
            SetPhase(Phase.Present);
            _offset = 0f;
            _previousOffset = 0f;
            _lateralVelocity = 0f;
            _yaw = 0f;
            _yawVelocity = 0f;
            _turn.Active = false;
            _arrive.Active = false;
            _walkWeight = 0f;
            _walkWeightTarget = 0f;
            _wantsWide = false;
            SetRootMotion(false);
            if (_avatar != null)
            {
                _avatar.localPosition = _restLocalPosition;
                _avatar.localRotation = _restLocalRotation;
            }

            SetHidden(false);
            if (sign != null && sign.IsShown)
            {
                sign.Hide(false);
            }

            if (stateController != null)
            {
                stateController.ClearLookOverride();
            }

            if (choreographer != null)
            {
                choreographer.Resume(_body, resumeFadeSeconds);
            }

            _body = null;
            Log(why);
        }

        private void SetPhase(Phase phase)
        {
            _phase = phase;
            _phaseTime = 0f;
        }

        // ------------------------------------------------------------------
        // Loop
        // ------------------------------------------------------------------

        private void LateUpdate()
        {
            if (!_initialized || _avatar == null || _phase == Phase.Present)
            {
                return;
            }

            float dt = Time.deltaTime;
            if (dt <= 0f)
            {
                return;
            }

            _phaseTime += dt;
            Vector3 rootDelta = ReadRootMotion();
            _walkWeight = float.IsInfinity(_walkWeightRate)
                ? _walkWeightTarget
                : Mathf.MoveTowards(_walkWeight, _walkWeightTarget, _walkWeightRate * dt);
            if (_turn.Active)
            {
                _yaw = _turn.Step(dt, out _yawVelocity);
            }
            else
            {
                _yawVelocity = 0f;
            }

            switch (_phase)
            {
                case Phase.Leaving:
                    if (_phaseTime >= exitDelaySeconds)
                    {
                        StartTurnOut();
                    }

                    break;

                case Phase.TurningOut:
                case Phase.WalkingOut:
                    KeepWalkAlive();
                    _offset += LocomotionStep(rootDelta, dt);
                    if (_phase == Phase.TurningOut && !_turn.Active)
                    {
                        SetPhase(Phase.WalkingOut);
                    }

                    if ((_offset > bodyMargin && IsOutOfFrame()) || _offset >= maxWalkDistance
                        || _phaseTime > maxWalkSeconds)
                    {
                        ApplyPose();
                        EnterAway(false);
                        return;
                    }

                    break;

                case Phase.Away:
                    // Still and hidden. Unity does not move her (root motion off).
                    return;

                case Phase.Returning:
                    if (_phaseTime >= entryDelaySeconds)
                    {
                        StartWalkIn();
                    }

                    break;

                case Phase.WalkingIn:
                    KeepWalkAlive();
                    _offset += LocomotionStep(rootDelta, dt);
                    if (!_lookedBack && _offset <= lookBackDistance)
                    {
                        LookBackAtVisitor();
                    }

                    float towardHome = Mathf.Max(0.05f, -_lateralVelocity);
                    if (_offset <= towardHome * arriveSeconds * 0.5f || _phaseTime > maxWalkSeconds)
                    {
                        StartArrive();
                    }

                    break;

                case Phase.Arriving:
                    float unused;
                    _offset = _arrive.Step(dt, out unused);
                    if (!_arriveTurnStarted && _phaseTime >= _arrive.Duration * arriveTurnDelay)
                    {
                        _arriveTurnStarted = true;
                        StartTurn(0f);
                    }

                    if (!_arrive.Active && _arriveTurnStarted && !_turn.Active)
                    {
                        Settle("back in place");
                        return;
                    }

                    break;
            }

            float velocity = (_offset - _previousOffset) / dt;
            _previousOffset = _offset;
            _lateralVelocity = Mathf.Lerp(_lateralVelocity, velocity, 1f - Mathf.Exp(-dt / VelocitySmoothing));

            ApplyPose();
            UpdateLook();
        }

        /// <summary>Places the avatar: her place, plus the lateral displacement, with the turn applied.</summary>
        private void ApplyPose()
        {
            if (_avatar == null)
            {
                return;
            }

            Transform parent = _avatar.parent;
            Vector3 home = parent != null ? parent.TransformPoint(_restLocalPosition) : _restLocalPosition;
            Quaternion homeRotation = parent != null ? parent.rotation * _restLocalRotation : _restLocalRotation;
            _avatar.SetPositionAndRotation(
                home + (_sideAxis * _offset),
                Quaternion.AngleAxis(_yaw, Vector3.up) * homeRotation);
        }

        /// <summary>Turns to an angle with a smooth curve that respects the current turn velocity.</summary>
        private void StartTurn(float targetYaw)
        {
            float delta = Mathf.Abs(targetYaw - _yaw);
            if (delta < 0.5f && Mathf.Abs(_yawVelocity) < 1f)
            {
                _yaw = targetYaw;
                _yawVelocity = 0f;
                _turn.Active = false;
                return;
            }

            float duration = Mathf.Clamp(turnSecondsPer90 * Mathf.Sqrt(Mathf.Max(delta, 10f) / 90f), 0.25f, 2.5f);
            _turn.Start(_yaw, _yawVelocity, targetYaw, duration);
        }

        private Vector3 CurrentFacing()
        {
            return Quaternion.AngleAxis(_yaw, Vector3.up) * _restFacing;
        }

        // ------------------------------------------------------------------
        // Displacement
        // ------------------------------------------------------------------

        private void SetRootMotion(bool on)
        {
            if (animator == null)
            {
                return;
            }

            animator.applyRootMotion = on && useRootMotion && !_useEstimate && WalkClip != null;
        }

        private Vector3 ReadRootMotion()
        {
            if (animator == null || !animator.applyRootMotion)
            {
                return Vector3.zero;
            }

            return animator.deltaPosition;
        }

        private float EstimatedSpeed()
        {
            if (WalkClip == null)
            {
                return slideSpeed;
            }

            return _clipSpeed > 0f ? _clipSpeed : fallbackWalkSpeed;
        }

        /// <summary>
        /// Meters advanced this frame across the width of the screen (positive toward
        /// the exit). With root motion it is the exact projection of the clip's
        /// advance; otherwise, the velocity estimated from the walk weight and
        /// how much she faces sideways.
        /// </summary>
        private float LocomotionStep(Vector3 rootDelta, float dt)
        {
            float facingAlong = Vector3.Dot(CurrentFacing(), _sideAxis);
            float estimated = EstimatedSpeed() * _walkWeight * facingAlong * dt;
            if (animator == null || !animator.applyRootMotion)
            {
                return estimated;
            }

            // Cap of 3.5 m/s: a stray spike (loop wrap, long
            // frame) cannot launch her suddenly. Normal walking never reaches it.
            float maxStep = 3.5f * dt;
            float measured = Mathf.Clamp(Vector3.Dot(rootDelta, _sideAxis), -maxStep, maxStep);

            // If the clip turns out to be "in place" (no root motion), it switches to the
            // estimated velocity instead of staying walking without advancing.
            if (_walkWeight > 0.6f && Mathf.Abs(facingAlong) > 0.7f)
            {
                Vector3 flat = rootDelta;
                flat.y = 0f;
                _probeEstimated += Mathf.Abs(estimated);
                _probeMeasured += flat.magnitude;
                if (_probeEstimated > 0.6f)
                {
                    if (_probeMeasured < 0.15f * _probeEstimated)
                    {
                        _useEstimate = true;
                        animator.applyRootMotion = false;
                        Debug.LogWarning(
                            "[Sonnia] The walk clip has no root motion (imported 'in place' or with the "
                            + "XZ translation inside the pose?). An estimated speed is used and the feet may "
                            + "slide. Check the import with Sonnia > Create Motion Set.",
                            this);
                        return estimated;
                    }

                    _probeEstimated = 0f;
                    _probeMeasured = 0f;
                }
            }

            return measured;
        }

        // ------------------------------------------------------------------
        // Clips
        // ------------------------------------------------------------------

        private void PlayWalk(float fade)
        {
            _walkWeightTarget = 1f;
            _walkWeightRate = fade > 0.0001f ? 1f / fade : float.PositiveInfinity;
            AnimationClip walk = WalkClip;
            if (walk == null || !PlayerReady)
            {
                return;
            }

            float start = walk.length * Mathf.Clamp01(walkStartNormalizedTime);
            _body = motionPlayer.Play(walk, MotionPlayer.BodyLayer, fade, 1f, start);
        }

        private void PlayIdle(float fade, bool onlyIfNeeded)
        {
            _walkWeightTarget = 0f;
            _walkWeightRate = fade > 0.0001f ? 1f / fade : float.PositiveInfinity;
            AnimationClip idle = IdleClip;
            if (idle == null || !PlayerReady)
            {
                return;
            }

            if (onlyIfNeeded && motionPlayer.CurrentClip(MotionPlayer.BodyLayer) == idle)
            {
                return;
            }

            float start = idle.isLooping ? Random.Range(0f, Mathf.Max(0f, idle.length - 0.5f)) : 0f;
            _body = motionPlayer.Play(idle, MotionPlayer.BodyLayer, fade, 1f, start);
        }

        private bool WalkIsPlaying()
        {
            AnimationClip walk = WalkClip;
            return walk != null && _body != null && _body.IsCurrent && _body.Clip == walk;
        }

        /// <summary>
        /// Keeps the walk cycle going while walking: if the clip is not
        /// looping (set not regenerated) or someone overrode the layer, it is restarted.
        /// </summary>
        private void KeepWalkAlive()
        {
            AnimationClip walk = WalkClip;
            if (walk == null || !PlayerReady)
            {
                return;
            }

            if (_body == null || !_body.IsCurrent || _body.Clip != walk || _body.IsDone)
            {
                _body = motionPlayer.Play(walk, MotionPlayer.BodyLayer, 0.25f, 1f, 0f);
            }
        }

        // ------------------------------------------------------------------
        // Gaze
        // ------------------------------------------------------------------

        private void UpdateLook()
        {
            if (stateController == null || _head == null)
            {
                return;
            }

            switch (_phase)
            {
                case Phase.Leaving:
                    LookAlong(_sideAxis, -1f);
                    break;
                case Phase.TurningOut:
                case Phase.WalkingOut:
                    LookAlong(_sideAxis, walkLookWeight);
                    break;
                case Phase.WalkingIn:
                    if (!_lookedBack)
                    {
                        LookAlong(-_sideAxis, walkLookWeight);
                    }

                    break;
            }
        }

        private void LookAlong(Vector3 direction, float weight)
        {
            Vector3 target = _head.position + (direction * lookAheadDistance) + (Vector3.down * lookAheadDrop);
            stateController.SetLookOverride(target, weight);
        }

        private void LookBackAtVisitor()
        {
            if (_lookedBack)
            {
                return;
            }

            _lookedBack = true;
            if (stateController != null)
            {
                stateController.ClearLookOverride();
                stateController.TriggerBlink();
            }
        }

        // ------------------------------------------------------------------
        // Out of frame
        // ------------------------------------------------------------------

        private Camera ViewCamera()
        {
            if (cameraFraming != null && cameraFraming.TargetCamera != null)
            {
                return cameraFraming.TargetCamera;
            }

            return Camera.main;
        }

        private void CollectPoses()
        {
            _poses.Clear();
            Camera view = ViewCamera();
            if (view != null)
            {
                _poses.Add(new ShotPose(view.transform.position, view.transform.rotation, view.fieldOfView));
            }

            if (cameraFraming != null)
            {
                cameraFraming.CollectShotPoses(_poses);
            }
        }

        private float ViewAspect()
        {
            Camera view = ViewCamera();
            return view != null && view.aspect > 0.01f ? view.aspect : 9f / 16f;
        }

        /// <summary>
        /// Normalized horizontal coordinate (-1..1 inside the frame) of a point,
        /// signed toward the exit side: more than 1 is out on that side.
        /// </summary>
        private float SideCoordinate(ShotPose pose, float aspect, Vector3 point)
        {
            Vector3 local = Quaternion.Inverse(pose.Rotation) * (point - pose.Position);
            if (local.z <= 0.01f)
            {
                return float.PositiveInfinity;
            }

            float halfWidth = local.z * Mathf.Tan(pose.FieldOfView * 0.5f * Mathf.Deg2Rad) * aspect;
            float x = local.x / Mathf.Max(0.0001f, halfWidth);
            return Vector3.Dot(_sideAxis, pose.Rotation * Vector3.right) >= 0f ? x : -x;
        }

        /// <summary>
        /// True when no bone (plus the body margin) is visible in any
        /// of the possible framings: this way she does not reappear if the camera is still
        /// opening.
        /// </summary>
        private bool IsOutOfFrame()
        {
            CollectPoses();
            if (_poses.Count == 0)
            {
                return _offset > 2f;
            }

            float aspect = ViewAspect();
            for (int b = 0; b < _probeBones.Length; b++)
            {
                if (_probeBones[b] == null)
                {
                    continue;
                }

                Vector3 inner = _probeBones[b].position - (_sideAxis * bodyMargin);
                for (int p = 0; p < _poses.Count; p++)
                {
                    if (SideCoordinate(_poses[p], aspect, inner) <= 1f + EdgeMargin)
                    {
                        return false;
                    }
                }
            }

            return true;
        }

        /// <summary>Minimum displacement from her place to not be visible in any framing.</summary>
        private float ComputeOffscreenOffset()
        {
            CollectPoses();
            if (_poses.Count == 0)
            {
                return 2f;
            }

            float aspect = ViewAspect();
            float required = 0f;
            for (int b = 0; b < _probeBones.Length; b++)
            {
                if (_probeBones[b] == null)
                {
                    continue;
                }

                // Bone position with Sonnia in her place, already with the margin.
                Vector3 inner = _probeBones[b].position - (_sideAxis * (_offset + bodyMargin));
                for (int p = 0; p < _poses.Count; p++)
                {
                    if (SideCoordinate(_poses[p], aspect, inner) > 1f + EdgeMargin)
                    {
                        continue;
                    }

                    float low = 0f;
                    float high = maxWalkDistance;
                    for (int i = 0; i < 24; i++)
                    {
                        float mid = (low + high) * 0.5f;
                        if (SideCoordinate(_poses[p], aspect, inner + (_sideAxis * mid)) > 1f + EdgeMargin)
                        {
                            high = mid;
                        }
                        else
                        {
                            low = mid;
                        }
                    }

                    required = Mathf.Max(required, high);
                }
            }

            return required;
        }

        private void SetHidden(bool hidden)
        {
            if (hidden && !hideRenderersWhenAway)
            {
                return;
            }

            if (hidden == _hidden)
            {
                return;
            }

            _hidden = hidden;
            for (int i = 0; i < _renderers.Length; i++)
            {
                Renderer renderer = _renderers[i];
                if (renderer == null)
                {
                    continue;
                }

                if (hidden)
                {
                    _rendererStates[i] = renderer.enabled;
                    renderer.enabled = false;
                }
                else
                {
                    renderer.enabled = _rendererStates[i];
                }
            }
        }

        private void Log(string message)
        {
            if (logEvents)
            {
                Debug.Log("[Sonnia] Presence: " + message, this);
            }
        }
    }
}
