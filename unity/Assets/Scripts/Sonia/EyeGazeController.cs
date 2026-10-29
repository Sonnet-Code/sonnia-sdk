// Eye gaze: the eye bones follow the target with fixations
// and microsaccades.
//
// AvatarStateController orients the head, and only partly (it follows the
// user with weight 0.3): the eyes are what look at whoever talks to Sonnia,
// as with the Genies demo characters. Here the eyes themselves turn inside
// the head:
//
//  - Fixations per state, with Genies attention templates measured on the
//    Genies demo characters. Speaking, it fixes on the user; listening, it looks at the user about 6 s
//    and looks away for a moment (1.5-3 s, up to +-11 deg) about 8 times per minute:
//    the demo characters look away more (37 % contact), but with someone
//    talking in front of the screen, that read as not paying attention; thinking, about 20 per
//    minute up and to one side; at rest, about 17 per minute,
//    wide and often downward. A large fixation change usually carries a
//    blink, as in Genies.
//  - Microsaccades: around the fixation, small jumps of a couple of degrees every
//    so often; most return close to the center.
//  - Microtremor: very small continuous noise so they are never still.
//  - During dances and big gestures (wide shot) the microsaccades are wider
//    and more frequent.
//  - Both eyes converge on the current point, each from its own position, and
//    the limits apply to both equally: if one reaches the cap, the other
//    is corrected the same amount and the vergence doesn't change (no crossed eyes).
//
// The eye bones are deliberately not mapped in the humanoid rig
// (the clips carry no eye curves and retargeting left them cross-eyed), so
// nobody else touches them and there is no need to fight the Animator.

using System;
using UnityEngine;
using Random = UnityEngine.Random;

namespace Sonia
{
    /// <summary>
    /// Gaze template for a state (like Genies attention templates):
    /// how often the fixation point changes, how much it looks at the user
    /// and how far it goes when it doesn't.
    /// </summary>
    [Serializable]
    public struct GazeTemplate
    {
        [Tooltip("Fixation point changes per minute. 0: fixed on the user.")]
        public float jumpsPerMinute;

        [Range(0f, 1f)]
        [Tooltip("Share of fixations that go to the user.")]
        public float eyeContact;

        [Tooltip("Horizontal offset when not looking at the user (degrees, min and max; the side is picked at random).")]
        public Vector2 yawDegrees;

        [Tooltip("Vertical offset when not looking at the user (degrees, min and max). Negative is up.")]
        public Vector2 pitchDegrees;

        [Range(0f, 2f)]
        [Tooltip("Scale of the microsaccades around the fixation.")]
        public float micro;

        [Tooltip("If greater than 0, looking elsewhere is a glance of this duration (seconds, min and max), then it returns to the user.")]
        public Vector2 glanceSeconds;

        public GazeTemplate(float jumpsPerMinute, float eyeContact, Vector2 yawDegrees, Vector2 pitchDegrees, float micro, Vector2 glanceSeconds = default)
        {
            this.jumpsPerMinute = jumpsPerMinute;
            this.eyeContact = eyeContact;
            this.yawDegrees = yawDegrees;
            this.pitchDegrees = pitchDegrees;
            this.micro = micro;
            this.glanceSeconds = glanceSeconds;
        }
    }

    /// <summary>Turns the eye bones toward the target with per-state fixations and microsaccades.</summary>
    [DefaultExecutionOrder(12100)]
    [DisallowMultipleComponent]
    public class EyeGazeController : MonoBehaviour
    {
        [Header("Bones")]
        [SerializeField]
        [Tooltip("Left eye bone. If empty, a child of the head named LeftEye is searched for.")]
        private Transform leftEye;

        [SerializeField]
        [Tooltip("Right eye bone. If empty, a child of the head named RightEye is searched for.")]
        private Transform rightEye;

        [SerializeField]
        [Tooltip("Head bone, used to find the eyes and measure the gaze.")]
        private Transform headBone;

        [Header("Target")]
        [SerializeField]
        [Tooltip("Where the point to look at (user, panel, walking) and the state come from. If empty, the main camera.")]
        private AvatarStateController stateController;

        [SerializeField]
        [Tooltip("Choreographer, to know when there is a big gesture and animate the eyes more.")]
        private AvatarChoreographer choreographer;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Chance of blinking on a large fixation change (over 4 deg). Genies blinks on every target change.")]
        private float blinkOnShift = 0.7f;

        [SerializeField]
        [Range(0.5f, 6f)]
        [Tooltip("Minimum focus distance in meters. The camera is very close and looking at it as is makes the eyes converge as if cross-eyed; it looks at the same spot but farther away.")]
        private float minFocusDistance = 2.5f;

        [Header("Gaze per state")]
        [SerializeField]
        [Tooltip("Speaking: fixed on the user, only microsaccades (Genies, Speaking template).")]
        private GazeTemplate speakingGaze = new GazeTemplate(0f, 1f, Vector2.zero, Vector2.zero, 0.6f);

        [SerializeField]
        [Tooltip("Listening: at the user about 6 s and a glance elsewhere of 1.5-3 s, about 8 times per minute (Genies demo characters, Listening template, with more contact).")]
        private GazeTemplate listeningGaze = new GazeTemplate(10f, 0.15f, new Vector2(4f, 11f), new Vector2(-3f, 3f), 1f, new Vector2(1.5f, 3f));

        [SerializeField]
        [Tooltip("Thinking: about 20 per minute, up and to one side (Genies demo characters, Thinking template).")]
        private GazeTemplate thinkingGaze = new GazeTemplate(20f, 0.29f, new Vector2(4f, 11f), new Vector2(-9f, -3f), 1f);

        [SerializeField]
        [Tooltip("At rest (idle): about 17 per minute, wide and often downward (Genies demo characters, Bored template).")]
        private GazeTemplate idleGaze = new GazeTemplate(17f, 0.13f, new Vector2(5f, 14f), new Vector2(-3f, 8f), 1f);

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("When thinking, share of fixations that go to the same side (the rest go to the other).")]
        private float thinkingSameSide = 0.75f;

        [Header("Limits (degrees)")]
        [SerializeField]
        [Range(0.2f, 1f)]
        [Tooltip("How much the eyes make up for what the head doesn't turn. With large stylized eyes, compensating everything reads as a sidelong look; at 0.65 the eyes accompany the head and only partly correct it.")]
        private float gazeGain = 0.65f;

        [SerializeField]
        [Range(-10f, 10f)]
        [Tooltip("Pupil separation, in degrees per eye: negative spreads them (more parallel gaze), positive brings them together (converges). 0 leaves pure geometry toward the focus point.")]
        private float convergenceDegrees = -8f;

        [SerializeField]
        [Range(5f, 40f)]
        [Tooltip("Maximum horizontal turn of each eye inside the head.")]
        private float yawLimit = 16f;

        [SerializeField]
        [Range(5f, 30f)]
        [Tooltip("Maximum vertical turn of each eye inside the head.")]
        private float pitchLimit = 11f;

        [SerializeField]
        [Range(2f, 30f)]
        [Tooltip("Maximum total offset (fixation + microsaccade) from the target, in degrees.")]
        private float excursionLimit = 14f;

        [Header("Microsaccades")]
        [SerializeField]
        [Tooltip("Minimum and maximum seconds between microsaccades.")]
        private Vector2 saccadeInterval = new Vector2(0.7f, 2.6f);

        [SerializeField]
        [Tooltip("Maximum amplitude of a microsaccade, in degrees (horizontal, vertical). The state template scales it.")]
        private Vector2 saccadeAmplitude = new Vector2(2.5f, 1.5f);

        [SerializeField]
        [Tooltip("Amplitude and frequency multiplier of the microsaccades during dances and big gestures.")]
        [Range(1f, 4f)]
        private float wideShotLiveliness = 1.6f;

        [Header("Movement")]
        [SerializeField]
        [Range(5f, 60f)]
        [Tooltip("Speed at which the eyes reach their destination. Saccades are almost instantaneous.")]
        private float speed = 30f;

        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Amplitude of the continuous microtremor, in degrees.")]
        private float jitterDegrees = 0.35f;

        private Quaternion _leftRest;
        private Quaternion _rightRest;
        private Vector2 _saccade;
        private Vector2 _fixation;
        private Vector2 _current;
        private float _saccadeTimer;
        private float _fixationTimer;
        private float _noiseSeed;
        private float _lastPitch;
        private bool _ready;
        private AvatarState _state = AvatarState.Idle;
        private int _thinkSide = 1;
        private bool _directed;

        /// <summary>Current gaze offset from the target (yaw, pitch in degrees).</summary>
        public Vector2 CurrentOffset
        {
            get { return _current; }
        }

        /// <summary>Current fixation point relative to the user (yaw, pitch in degrees). 0: looking at them.</summary>
        public Vector2 CurrentFixation
        {
            get { return _fixation; }
        }

        /// <summary>Degrees the eyes look down inside the head (0 if looking forward or up). The eyelid follows it.</summary>
        public float CurrentPitchDown
        {
            get { return Mathf.Max(0f, _lastPitch); }
        }

        private void Awake()
        {
            if (stateController == null)
            {
                stateController = GetComponentInChildren<AvatarStateController>(true);
            }

            if (choreographer == null)
            {
                choreographer = GetComponentInChildren<AvatarChoreographer>(true);
            }

            _noiseSeed = Random.value * 100f;
        }

        private void Start()
        {
            Bind();
        }

        /// <summary>Switches to another avatar: new head and eyes searched again beneath it.</summary>
        public void Bind(Transform head)
        {
            headBone = head;
            leftEye = null;
            rightEye = null;
            Bind();
        }

        /// <summary>Finds the bones and stores their rest pose. Called by itself at startup.</summary>
        public void Bind()
        {
            if (headBone == null)
            {
                Animator animator = GetComponentInChildren<Animator>(true);
                if (animator != null && animator.isHuman)
                {
                    headBone = animator.GetBoneTransform(HumanBodyBones.Head);
                }
            }

            if (headBone != null)
            {
                if (leftEye == null)
                {
                    leftEye = FindChild(headBone, "LeftEye", "Eye_L", "eye_L", "J_Adj_L_FaceEye", "LeftEyeBone");
                }

                if (rightEye == null)
                {
                    rightEye = FindChild(headBone, "RightEye", "Eye_R", "eye_R", "J_Adj_R_FaceEye", "RightEyeBone");
                }
            }

            _ready = leftEye != null || rightEye != null;
            if (leftEye != null)
            {
                _leftRest = leftEye.localRotation;
            }

            if (rightEye != null)
            {
                _rightRest = rightEye.localRotation;
            }

            _saccadeTimer = Random.Range(saccadeInterval.x, saccadeInterval.y);
            _fixationTimer = Random.Range(0.5f, 2f);
        }

        private static Transform FindChild(Transform root, params string[] names)
        {
            Transform[] all = root.GetComponentsInChildren<Transform>(true);
            for (int n = 0; n < names.Length; n++)
            {
                for (int i = 0; i < all.Length; i++)
                {
                    if (all[i].name == names[n] || all[i].name.EndsWith(":" + names[n]))
                    {
                        return all[i];
                    }
                }
            }

            return null;
        }

        private void LateUpdate()
        {
            if (!_ready)
            {
                return;
            }

            float dt = Time.deltaTime;
            bool lively = choreographer != null && choreographer.IsWideShot;
            float mult = lively ? wideShotLiveliness : 1f;

            AvatarState state = stateController != null ? stateController.State : AvatarState.Idle;
            if (state != _state)
            {
                OnStateChanged(state);
            }

            GazeTemplate template = TemplateFor(_state);
            UpdateFixation(dt, template);
            UpdateSaccades(dt, mult, template.micro);

            Vector2 jitter = new Vector2(
                (Mathf.PerlinNoise(_noiseSeed, Time.time * 7f) - 0.5f) * 2f * jitterDegrees,
                (Mathf.PerlinNoise(_noiseSeed + 31f, Time.time * 6f) - 0.5f) * 2f * jitterDegrees);

            Vector2 wanted = _fixation + _saccade;
            if (wanted.magnitude > excursionLimit)
            {
                wanted = wanted.normalized * excursionLimit;
            }

            float step = 1f - Mathf.Exp(-speed * dt);
            _current = Vector2.Lerp(_current, wanted, step);
            Vector2 offset = _current + jitter;

            Vector3 target;
            bool hasTarget = TryGetTarget(out target);

            // Inward is local +X (right of the head) for the left eye
            // and -X for the right: convergence is applied with opposite signs.
            Vector2 left = Angles(leftEye, _leftRest, hasTarget, target, offset, convergenceDegrees);
            Vector2 right = Angles(rightEye, _rightRest, hasTarget, target, offset, -convergenceDegrees);

            // Same limits for both eyes: if one overshoots, both are
            // corrected the same amount and the vergence doesn't change.
            float yawShift = Shift(leftEye != null ? left.x : right.x, rightEye != null ? right.x : left.x, yawLimit);
            float pitchShift = Shift(leftEye != null ? left.y : right.y, rightEye != null ? right.y : left.y, pitchLimit);
            Apply(leftEye, _leftRest, left.x - yawShift, left.y - pitchShift);
            Apply(rightEye, _rightRest, right.x - yawShift, right.y - pitchShift);
            _lastPitch = ((leftEye != null ? left.y : right.y) + (rightEye != null ? right.y : left.y)) * 0.5f - pitchShift;
        }

        private GazeTemplate TemplateFor(AvatarState state)
        {
            switch (state)
            {
                case AvatarState.Speaking:
                    return speakingGaze;
                case AvatarState.Listening:
                    return listeningGaze;
                case AvatarState.Thinking:
                    return thinkingGaze;
                default:
                    return idleGaze;
            }
        }

        private void OnStateChanged(AvatarState state)
        {
            _state = state;
            if (state == AvatarState.Thinking)
            {
                _thinkSide = Random.value < 0.5f ? -1 : 1;
            }

            if (state == AvatarState.Speaking)
            {
                // When starting to speak, straight to the user.
                SetFixation(Vector2.zero);
                _fixationTimer = float.PositiveInfinity;
                return;
            }

            // The new template takes over from the next fixation, which comes soon.
            _fixationTimer = Mathf.Min(_fixationTimer, Random.Range(0.3f, 1.2f));
        }

        /// <summary>
        /// Picks the next fixation point when due: the user or an
        /// offset within the template. With a directed gaze (walking, the
        /// panel) it fixes on that point.
        /// </summary>
        private void UpdateFixation(float dt, GazeTemplate template)
        {
            bool directed = stateController != null && stateController.HasDirectedGaze;
            if (directed)
            {
                if (!_directed)
                {
                    SetFixation(Vector2.zero);
                }

                _directed = true;
                return;
            }

            if (_directed)
            {
                _directed = false;
                _fixationTimer = Random.Range(0.5f, 1.5f);
            }

            if (template.jumpsPerMinute <= 0.01f)
            {
                if (_fixation != Vector2.zero)
                {
                    SetFixation(Vector2.zero);
                }

                return;
            }

            _fixationTimer -= dt;
            if (_fixationTimer > 0f)
            {
                return;
            }

            float mean = 60f / template.jumpsPerMinute;
            bool glances = template.glanceSeconds.y > 0.01f;
            bool away = _fixation.sqrMagnitude > 0.0001f;
            _fixationTimer = mean * Random.Range(0.6f, 1.4f);
            if ((glances && away) || Random.value < template.eyeContact)
            {
                // After a glance it always returns to the user.
                SetFixation(Vector2.zero);
                return;
            }

            if (glances)
            {
                _fixationTimer = Random.Range(Mathf.Min(template.glanceSeconds.x, template.glanceSeconds.y),
                    Mathf.Max(template.glanceSeconds.x, template.glanceSeconds.y));
            }

            float yawMin = Mathf.Min(template.yawDegrees.x, template.yawDegrees.y);
            float yawMax = Mathf.Max(template.yawDegrees.x, template.yawDegrees.y);
            float side = Random.value < 0.5f ? -1f : 1f;
            if (_state == AvatarState.Thinking)
            {
                side = Random.value < thinkingSameSide ? _thinkSide : -_thinkSide;
            }

            float pitchMin = Mathf.Min(template.pitchDegrees.x, template.pitchDegrees.y);
            float pitchMax = Mathf.Max(template.pitchDegrees.x, template.pitchDegrees.y);
            SetFixation(new Vector2(side * Random.Range(yawMin, yawMax), Random.Range(pitchMin, pitchMax)));
        }

        private void SetFixation(Vector2 next)
        {
            if (stateController != null && (next - _fixation).magnitude > 4f && Random.value < blinkOnShift)
            {
                stateController.TriggerBlink();
            }

            _fixation = next;
            _saccade = Vector2.zero;
        }

        private void UpdateSaccades(float dt, float mult, float scale)
        {
            _saccadeTimer -= dt * mult;
            if (_saccadeTimer > 0f)
            {
                return;
            }

            _saccadeTimer = Random.Range(saccadeInterval.x, saccadeInterval.y);
            Vector2 next = new Vector2(
                Random.Range(-saccadeAmplitude.x, saccadeAmplitude.x) * mult * scale,
                Random.Range(-saccadeAmplitude.y, saccadeAmplitude.y) * mult * scale);

            // Most microsaccades return close to the center: otherwise the
            // gaze drifts and looks like it isn't looking at anyone.
            if (Random.value < 0.45f)
            {
                next *= 0.25f;
            }

            _saccade = next;
        }

        private bool TryGetTarget(out Vector3 target)
        {
            bool found = false;
            target = Vector3.zero;
            if (stateController != null && stateController.TryGetEyeTarget(out target))
            {
                found = true;
            }
            else
            {
                Camera main = Camera.main;
                if (main != null)
                {
                    target = main.transform.position;
                    found = true;
                }
            }

            if (!found)
            {
                return false;
            }

            // The focus point is moved away along the same direction so
            // the two eyes don't converge too much.
            Vector3 origin = EyesCenter();
            Vector3 dir = target - origin;
            float dist = dir.magnitude;
            if (dist > 0.001f && dist < minFocusDistance)
            {
                target = origin + dir / dist * minFocusDistance;
            }

            return true;
        }

        private Vector3 EyesCenter()
        {
            if (leftEye != null && rightEye != null)
            {
                return (leftEye.position + rightEye.position) * 0.5f;
            }

            Transform any = leftEye != null ? leftEye : rightEye;
            return any != null ? any.position : (headBone != null ? headBone.position : transform.position);
        }

        /// <summary>
        /// Turn (yaw, pitch in degrees) of an eye toward the target plus the
        /// offset, relative to its rest rotation inside the head. The
        /// bone's local Z axis points forward (as Genies rigs come).
        /// </summary>
        private Vector2 Angles(Transform eye, Quaternion rest, bool hasTarget, Vector3 target, Vector2 offset, float inwardDegrees)
        {
            if (eye == null || eye.parent == null)
            {
                return Vector2.zero;
            }

            // Desired direction in the parent's space (the head).
            Quaternion parentInverse = Quaternion.Inverse(eye.parent.rotation);
            Vector3 restForward = rest * Vector3.forward;
            Vector3 desiredLocal = restForward;
            if (hasTarget)
            {
                Vector3 dirWorld = target - eye.position;
                if (dirWorld.sqrMagnitude > 0.0001f)
                {
                    desiredLocal = (parentInverse * dirWorld).normalized;
                }
            }

            Quaternion restInverse = Quaternion.Inverse(rest);
            Vector3 inRest = restInverse * desiredLocal;
            float yaw = Mathf.Atan2(inRest.x, inRest.z) * Mathf.Rad2Deg * gazeGain + offset.x + inwardDegrees;
            float pitch = -Mathf.Asin(Mathf.Clamp(inRest.y, -1f, 1f)) * Mathf.Rad2Deg * gazeGain + offset.y;
            return new Vector2(yaw, pitch);
        }

        /// <summary>What to subtract from both eyes so neither exceeds ±<paramref name="limit"/>.</summary>
        private static float Shift(float a, float b, float limit)
        {
            float high = Mathf.Max(a, b);
            float low = Mathf.Min(a, b);
            if (high > limit)
            {
                return high - limit;
            }

            if (low < -limit)
            {
                return low + limit;
            }

            return 0f;
        }

        private static void Apply(Transform eye, Quaternion rest, float yaw, float pitch)
        {
            if (eye == null || eye.parent == null)
            {
                return;
            }

            eye.localRotation = rest * Quaternion.Euler(pitch, yaw, 0f);
        }
    }
}
