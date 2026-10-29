// Dynamic camera framing.
//
// The base shot is a very tight medium shot: from the hips to a hand's width
// above the head, so the face and mouth look big. That framing is perfect for
// talking and listening, but it cuts Sonnia off at the sides as soon as she
// dances or greets with her arm raised.
//
// This component handles several shots and goes to whichever applies, always with
// a smooth interpolation so it reads as a camera move:
//
//   wide     dances, attention gestures and greeting (the choreographer says so)
//   panel    while an image is shown: it pulls back a little and rises so
//            the image, fixed in the upper strip of the screen, doesn't cover
//            Sonnia (who stays visible from the waist up)
//   base     the usual medium shot, with the face big
//
// That is the priority: if Sonnia dances while an image is up, the dance wins.
// The wide shot is off by default (the camera doesn't move for
// dances or bows); the panel shot is a soft pull-back.
//
// Above all of them goes the away shot (away mode): while Sonnia
// walks off, is away and comes back, the camera opens to the full-body
// shot so the walk can be seen (the medium shot doesn't show the legs and
// she would leave the frame in one step). That move is a dolly with
// SmoothDamp, which starts and stops softly; the rest keep their smoothing.
//
// The control panel ("Developer" section) can move the base shot: offset,
// zoom and tilt over the pose left by the editor menu. The panel
// shot goes with it (it is an offset of the base); the full-body shots
// (wide and away) stay where they are.
//
// And above everything, a framing imposed from outside (SetOverride), which
// uses the same dolly.
//
// Screen shots: the base shot is the conversation shot, from the waist up with
// the eyes at the height of those of whoever speaks in front, and when nobody
// is conversing the camera opens a little, from the knees
// up (idle shot). Both are computed from the bones of the attached
// avatar (the SDK one when it arrives), not from the scene pose, so
// they hold if the character changes. The idle shot waits a few seconds
// at rest before opening: between turns the camera doesn't breathe.

using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Camera pose of a shot (position, rotation and vertical field of view).</summary>
    public struct ShotPose
    {
        public Vector3 Position;
        public Quaternion Rotation;
        public float FieldOfView;

        public ShotPose(Vector3 position, Quaternion rotation, float fieldOfView)
        {
            Position = position;
            Rotation = rotation;
            FieldOfView = fieldOfView;
        }
    }

    /// <summary>
    /// Pulls the camera back while Sonnia does a big animation and returns it to the
    /// medium shot when done. Without a camera or choreographer it does nothing.
    /// </summary>
    [DisallowMultipleComponent]
    public class CameraFramingController : MonoBehaviour
    {
        [Header("References")]
        [SerializeField]
        [Tooltip("Screen camera. If empty, the main camera is used.")]
        private Camera targetCamera;

        [SerializeField]
        [Tooltip("Avatar choreographer. Says when a big gesture that calls for the wide shot is playing.")]
        private AvatarChoreographer choreographer;

        [SerializeField]
        [Tooltip("Image panel. While it is visible, the panel framing is used.")]
        private ImagePanelController imagePanel;

        [Header("Wide shot")]
        [SerializeField]
        [Tooltip("Open the shot during dances and big gestures. Off: the camera stays on the medium shot even if the full body doesn't fit.")]
        private bool wideShotEnabled;

        [SerializeField]
        [Tooltip("Camera position in the wide shot. Computed by Sonnia > Place Avatar from the model's measurements.")]
        private Vector3 wideShotPosition = new Vector3(0f, 0.83f, -2.7f);

        [SerializeField]
        [Tooltip("Field of view in the wide shot. Zero or less keeps the same as the base shot.")]
        private float wideShotFieldOfView;

        [Header("Panel shot")]
        [SerializeField]
        [Tooltip("Pull the camera back a little while an image is shown, so the image (fixed at the top of the screen) doesn't cover Sonnia.")]
        private bool panelShotEnabled = true;

        [SerializeField]
        [Tooltip("Camera offset from the base shot while an image is shown: a bit higher and farther back. Sonnia stays visible from the waist up, a bit smaller.")]
        private Vector3 panelShotOffset = new Vector3(0f, 0.13f, -0.45f);

        [SerializeField]
        [Tooltip("Absolute camera position with an image (only if the offset is zero). It was computed by Sonnia > Place Avatar.")]
        private Vector3 panelShotPosition = new Vector3(0f, 1.62f, -1.42f);

        [SerializeField]
        [Tooltip("Field of view with an image shown. Zero or less keeps the same as the base shot.")]
        private float panelShotFieldOfView;

        [Header("Walking out and in")]
        [SerializeField]
        [Tooltip("Sonnia's presence (away mode). If empty, it is searched for on this object or its children.")]
        private PresenceController presence;

        [SerializeField]
        [Tooltip("Open to full body while Sonnia walks out, is away and comes back. Off: the camera stays on the medium shot and Sonnia leaves the frame in a couple of steps, with the legs never visible.")]
        private bool presenceShotEnabled = true;

        [SerializeField]
        [Tooltip("Camera position for walking out and in. Zero: that of the wide shot (Wide Shot Position), which already frames the full body.")]
        private Vector3 presenceShotPosition = Vector3.zero;

        [SerializeField]
        [Tooltip("Field of view for walking out and in. Zero or less: that of the wide shot or, if it has none either, that of the base shot.")]
        private float presenceShotFieldOfView = 0f;

        [SerializeField]
        [Range(0.1f, 3f)]
        [Tooltip("Smoothing time (SmoothDamp) of the dolly when opening and closing the away shot. About 2.5 times this value until the camera settles.")]
        private float presenceSmoothTime = 0.75f;

        [Header("Screen shots")]
        [SerializeField]
        [Tooltip("Compute the conversation (base) and idle shots from the attached avatar's bones, instead of using the camera pose in the scene.")]
        private bool stageFraming = true;

        [SerializeField]
        [Range(0.5f, 2.5f)]
        [Tooltip("Height visible at head level when conversing, in meters. 1.24: from mid-thigh up, with the gesture hands in view.")]
        private float conversationHeight = 1.24f;

        [SerializeField]
        [Range(0.1f, 0.6f)]
        [Tooltip("Where the eyes sit when conversing, as a fraction of the screen height from the top.")]
        private float conversationEyeLine = 0.27f;

        [SerializeField]
        [Tooltip("Open to a knees-up shot when nobody is conversing.")]
        private bool idleShotEnabled = true;

        [SerializeField]
        [Range(0.5f, 2.5f)]
        [Tooltip("Height visible at head level at idle, in meters. 1.42: from the knees up, with the hips and hands above the invitation.")]
        private float idleHeight = 1.42f;

        [SerializeField]
        [Range(0.1f, 0.6f)]
        [Tooltip("Where the eyes sit at idle, as a fraction of the screen height from the top.")]
        private float idleEyeLine = 0.26f;

        [SerializeField]
        [Range(0f, 30f)]
        [Tooltip("Seconds at idle before opening the shot: between turns the camera doesn't move.")]
        private float idleShotDelay = 8f;

        [SerializeField]
        [Range(0f, 0.3f)]
        [Tooltip("Height of the eyes above the head bone, in meters (about 11 cm on Genies avatars).")]
        private float eyesAboveHeadBone = 0.11f;

        [Header("Movement")]
        [SerializeField]
        [Range(0.2f, 10f)]
        [Tooltip("Speed at which the camera reaches the current framing. Higher is more abrupt.")]
        private float smoothing = 2.5f;

        private Vector3 _basePosition;
        private Quaternion _baseRotation;
        private float _baseFieldOfView;

        // Scene pose (the one from the editor menu), before the control panel's "Developer" settings.
        private Vector3 _capturedPosition;
        private Quaternion _capturedRotation = Quaternion.identity;
        private float _capturedFieldOfView = 40f;
        private Vector3 _tuningOffset;
        private float _tuningZoom = 1f;
        private float _tuningTilt;
        private bool _wide;
        private bool _panel;
        private bool _presenceShot;
        private bool _ready;

        // Dolly of the away shot: lasts until the camera arrives and settles
        // on the current framing, even if the away shot has already ended.
        private bool _dolly;
        private Vector3 _dollyVelocity;
        private float _fieldOfViewVelocity;
        private bool _snapNextFrame;
        private bool _presenceSearched;

        // Framing imposed from outside: it overrides all the others.
        private bool _hasOverride;
        private ShotPose _override;
        private bool _hasTargetShot;
        private ShotPose _targetShot;

        // Screen shots: the idle shot is the base plus this offset.
        private AvatarStateController _avatarState;
        private AvatarBinder _binder;
        private bool _stageReady;
        private Vector3 _idleOffset;
        private bool _idle;

        // Since when it has been idle. At startup nobody is there: idle shot right away.
        private float _idleSince = float.NegativeInfinity;

        /// <summary>True while the camera is opening or already open.</summary>
        public bool IsWideShot
        {
            get { return _wide; }
        }

        /// <summary>True while the camera is on the image panel framing.</summary>
        public bool IsPanelShot
        {
            get { return _panel; }
        }

        /// <summary>True while the idle shot is in charge (nobody is conversing).</summary>
        public bool IsIdleShot
        {
            get { return _idle; }
        }

        /// <summary>
        /// Requests the panel framing without an image shown (for content
        /// that takes the same upper strip of the screen).
        /// </summary>
        public bool PanelRequested { get; set; }

        /// <summary>
        /// The framing the camera is heading to (the one computed in its last frame).
        /// With the camera halfway, it tells whether something will be in
        /// frame when it arrives.
        /// </summary>
        public bool TryGetTargetShot(out ShotPose pose)
        {
            pose = _targetShot;
            return _hasTargetShot;
        }

        /// <summary>
        /// Extra offset (meters) over the panel shot while it is requested
        /// with <see cref="PanelRequested"/>: the content may be taller
        /// than an image and Sonnia has to fit below it.
        /// </summary>
        public Vector3 PanelRequestOffset { get; set; }

        /// <summary>True while the walking out and in shot is in charge.</summary>
        public bool IsPresenceShot
        {
            get { return _presenceShot; }
        }

        /// <summary>Camera moved by this component.</summary>
        public Camera TargetCamera
        {
            get { return targetCamera; }
        }

        /// <summary>True once it has taken the scene pose (there is a camera).</summary>
        public bool IsReady
        {
            get { return _ready; }
        }

        /// <summary>Base shot: Sonnia's medium shot, with the control panel's "Developer" settings.</summary>
        public ShotPose BaseShot
        {
            get { return new ShotPose(_basePosition, _baseRotation, _baseFieldOfView); }
        }

        /// <summary>Full-body shot (the one for walking out and in).</summary>
        public ShotPose FullBodyShot
        {
            get { return new ShotPose(PresencePosition(), _capturedRotation, PresenceFieldOfView()); }
        }

        /// <summary>True while a framing imposed from outside is in charge.</summary>
        public bool HasOverride
        {
            get { return _hasOverride; }
        }

        /// <summary>
        /// Imposes a framing above all the others, with the
        /// dolly of the away shot, until <see cref="ClearOverride"/>. It
        /// can be called again with another pose: the camera moves toward it smoothly.
        /// </summary>
        public void SetOverride(ShotPose pose)
        {
            _override = pose;
            _hasOverride = true;
        }

        /// <summary>Removes the imposed framing: the camera returns, with a dolly, to the current one.</summary>
        public void ClearOverride()
        {
            if (_hasOverride)
            {
                _hasOverride = false;
                _dolly = true;
            }
        }

        /// <summary>Sonnia's presence, for the away shot. Assigned by SoniaBootstrap.</summary>
        public PresenceController Presence
        {
            get { return presence; }
            set { presence = value; }
        }

        /// <summary>
        /// Adds the poses of all possible framings (base, wide, panel and
        /// away). Useful to know whether a point falls out of frame in
        /// any of them, even if the camera is halfway.
        /// </summary>
        public void CollectShotPoses(List<ShotPose> poses)
        {
            if (!_ready || poses == null)
            {
                return;
            }

            poses.Add(new ShotPose(_basePosition, _baseRotation, _baseFieldOfView));
            if (_stageReady && idleShotEnabled)
            {
                poses.Add(new ShotPose(_basePosition + _idleOffset, _baseRotation, _baseFieldOfView));
            }

            poses.Add(new ShotPose(wideShotPosition, _capturedRotation, WideFieldOfView()));
            poses.Add(new ShotPose(PanelPosition(), _baseRotation, PanelFieldOfView()));
            if (presenceShotEnabled)
            {
                poses.Add(new ShotPose(PresencePosition(), _capturedRotation, PresenceFieldOfView()));
            }

            if (_hasOverride)
            {
                poses.Add(_override);
            }
        }

        /// <summary>
        /// On the next frame the camera jumps to the current framing, without
        /// a dolly. Used when Sonnia is applied as "away" right after
        /// connecting: there is no point watching the camera open on an empty stage.
        /// </summary>
        public void SnapNextFrame()
        {
            _snapNextFrame = true;
        }

        private void Awake()
        {
            if (targetCamera == null)
            {
                targetCamera = Camera.main;
            }

            if (choreographer == null)
            {
                choreographer = GetComponentInChildren<AvatarChoreographer>(true);
            }

            if (imagePanel == null)
            {
                imagePanel = GetComponentInChildren<ImagePanelController>(true);
            }

            _avatarState = GetComponentInChildren<AvatarStateController>(true);
            _binder = GetComponentInChildren<AvatarBinder>(true);
            CaptureBasePose();
        }

        private void OnEnable()
        {
            if (_binder != null)
            {
                _binder.AvatarChanged += HandleAvatarChanged;
            }
        }

        private void OnDisable()
        {
            if (_binder != null)
            {
                _binder.AvatarChanged -= HandleAvatarChanged;
            }
        }

        private void Start()
        {
            // The editor's fallback avatar is already attached; the SDK one notifies on arrival.
            if (_binder != null && _binder.Current != null)
            {
                HandleAvatarChanged(_binder.Current);
            }
        }

        private void HandleAvatarChanged(Transform avatar)
        {
            if (stageFraming && _ready)
            {
                ComputeStageShots(avatar);
            }
        }

        /// <summary>
        /// Conversation and idle shots from the avatar's head: the
        /// camera looks straight on as in the scene, at the exact distance so that
        /// the requested height shows at head level, and at the height that puts
        /// the eyes on their line of the screen.
        /// </summary>
        private void ComputeStageShots(Transform avatar)
        {
            Animator animator = avatar != null ? avatar.GetComponentInChildren<Animator>(true) : null;
            Transform head = animator != null && animator.isHuman ? animator.GetBoneTransform(HumanBodyBones.Head) : null;
            if (head == null)
            {
                return;
            }

            Vector3 forward = _capturedRotation * Vector3.forward;
            forward.y = 0f;
            if (forward.sqrMagnitude < 0.000001f)
            {
                forward = Vector3.forward;
            }

            forward.Normalize();
            float tangentHalf = Mathf.Tan(_capturedFieldOfView * 0.5f * Mathf.Deg2Rad);
            // The head in place: if the avatar arrives with Sonnia out of frame, the
            // head is far away and the shot would end up centered on the gap.
            if (presence == null)
            {
                presence = GetComponentInChildren<PresenceController>(true);
            }

            Vector3 subject = presence != null ? presence.AtHome(head.position) : head.position;
            float eyesY = subject.y + eyesAboveHeadBone;
            Vector3 conversation = StageShot(subject, eyesY, conversationHeight, conversationEyeLine, forward, tangentHalf);
            Vector3 idle = StageShot(subject, eyesY, idleHeight, idleEyeLine, forward, tangentHalf);

            _capturedPosition = conversation;
            _idleOffset = idle - conversation;
            _stageReady = true;
            ApplyTuningToBase();
        }

        private static Vector3 StageShot(
            Vector3 subject, float eyesY, float visibleHeight, float eyeLine, Vector3 forward, float tangentHalf)
        {
            float distance = visibleHeight / (2f * Mathf.Max(0.01f, tangentHalf));
            Vector3 position = subject - forward * distance;
            position.y = eyesY - (0.5f - eyeLine) * visibleHeight;
            return position;
        }

        /// <summary>
        /// Takes the camera's current pose as the base shot. Called at startup,
        /// while the camera is still where the editor menu left it.
        /// </summary>
        public void CaptureBasePose()
        {
            if (targetCamera == null)
            {
                _ready = false;
                return;
            }

            _capturedPosition = targetCamera.transform.position;
            _capturedRotation = targetCamera.transform.rotation;
            _capturedFieldOfView = targetCamera.fieldOfView;
            _ready = true;
            ApplyTuningToBase();
        }

        /// <summary>
        /// Control panel "Developer" settings over the base shot: <paramref name="offset"/>
        /// in meters (x to the right of the screen, y up, z moving away from
        /// Sonnia), <paramref name="zoom"/> (above 1 zooms in) and
        /// <paramref name="tiltDegrees"/> (positive looks lower). The camera
        /// reaches the new framing smoothly with its usual interpolation.
        /// </summary>
        public void SetTuning(Vector3 offset, float zoom, float tiltDegrees)
        {
            _tuningOffset = offset;
            _tuningZoom = Mathf.Clamp(zoom, 0.25f, 4f);
            _tuningTilt = Mathf.Clamp(tiltDegrees, -45f, 45f);
            ApplyTuningToBase();
        }

        private void ApplyTuningToBase()
        {
            if (!_ready)
            {
                return;
            }

            // Lateral and distance on the ground plane, depending on where the camera looks.
            Vector3 forward = _capturedRotation * Vector3.forward;
            forward.y = 0f;
            if (forward.sqrMagnitude < 0.000001f)
            {
                forward = Vector3.forward;
            }

            forward.Normalize();
            Vector3 right = Vector3.Cross(Vector3.up, forward);
            _basePosition = _capturedPosition
                            + right * _tuningOffset.x
                            + Vector3.up * _tuningOffset.y
                            - forward * _tuningOffset.z;
            _baseRotation = _capturedRotation * Quaternion.Euler(_tuningTilt, 0f, 0f);

            // Zoom narrows the field of view like a longer lens.
            float halfTan = Mathf.Tan(_capturedFieldOfView * 0.5f * Mathf.Deg2Rad) / _tuningZoom;
            _baseFieldOfView = Mathf.Clamp(2f * Mathf.Atan(halfTan) * Mathf.Rad2Deg, 5f, 120f);
        }

        /// <summary>Returns to the medium shot at once, without animation.</summary>
        public void ResetToBase()
        {
            _wide = false;
            _panel = false;
            _presenceShot = false;
            _dolly = false;
            _dollyVelocity = Vector3.zero;
            _fieldOfViewVelocity = 0f;
            if (!_ready)
            {
                return;
            }

            targetCamera.transform.position = _basePosition;
            targetCamera.transform.rotation = _baseRotation;
            targetCamera.fieldOfView = _baseFieldOfView;
        }

        private void LateUpdate()
        {
            if (!_ready)
            {
                return;
            }

            if (presence == null && !_presenceSearched)
            {
                // SoniaBootstrap adds it from code in its Awake; it may not exist
                // yet when this component's Awake runs.
                _presenceSearched = true;
                presence = GetComponentInChildren<PresenceController>(true);
            }

            _presenceShot = !_hasOverride && presenceShotEnabled && presence != null && presence.WantsWideShot;
            _wide = !_hasOverride && !_presenceShot && NeedsWideShot();
            _panel = panelShotEnabled && !_hasOverride && !_presenceShot && !_wide
                     && ((imagePanel != null && imagePanel.IsVisible) || PanelRequested);

            // Idle shot: nobody has been conversing for a while.
            bool resting = _avatarState == null || _avatarState.State == AvatarState.Idle;
            if (!resting)
            {
                _idleSince = float.PositiveInfinity;
            }
            else if (float.IsPositiveInfinity(_idleSince))
            {
                _idleSince = Time.time;
            }

            _idle = idleShotEnabled && _stageReady && !_hasOverride && !_presenceShot && !_wide && !_panel
                    && resting && Time.time - _idleSince >= idleShotDelay;

            Vector3 targetPosition = _basePosition;
            Quaternion targetRotation = _baseRotation;
            float targetFieldOfView = _baseFieldOfView;

            if (_hasOverride)
            {
                targetPosition = _override.Position;
                targetRotation = _override.Rotation;
                targetFieldOfView = _override.FieldOfView;
                _dolly = true;
            }
            else if (_presenceShot)
            {
                targetPosition = PresencePosition();
                targetRotation = _capturedRotation;
                targetFieldOfView = PresenceFieldOfView();
                _dolly = true;
            }
            else if (_wide)
            {
                targetPosition = wideShotPosition;
                targetRotation = _capturedRotation;
                targetFieldOfView = WideFieldOfView();
            }
            else if (_panel)
            {
                targetPosition = PanelPosition() + (PanelRequested ? PanelRequestOffset : Vector3.zero);
                targetFieldOfView = PanelFieldOfView();
            }
            else if (_idle)
            {
                targetPosition = _basePosition + _idleOffset;
            }

            _targetShot = new ShotPose(targetPosition, targetRotation, targetFieldOfView);
            _hasTargetShot = true;

            Transform cameraTransform = targetCamera.transform;

            if (_snapNextFrame)
            {
                _snapNextFrame = false;
                _dolly = false;
                _dollyVelocity = Vector3.zero;
                _fieldOfViewVelocity = 0f;
                cameraTransform.position = targetPosition;
                cameraTransform.rotation = targetRotation;
                targetCamera.fieldOfView = targetFieldOfView;
                return;
            }

            float dt = Time.deltaTime;
            if (_dolly)
            {
                // Dolly: continuous speed, soft start and stop.
                float smoothTime = Mathf.Max(0.05f, presenceSmoothTime);
                cameraTransform.position = Vector3.SmoothDamp(
                    cameraTransform.position, targetPosition, ref _dollyVelocity, smoothTime, Mathf.Infinity, dt);
                targetCamera.fieldOfView = Mathf.SmoothDamp(
                    targetCamera.fieldOfView, targetFieldOfView, ref _fieldOfViewVelocity, smoothTime, Mathf.Infinity, dt);
                cameraTransform.rotation = Quaternion.Slerp(
                    cameraTransform.rotation, targetRotation, 1f - Mathf.Exp(-4f * dt));

                bool arrived = (cameraTransform.position - targetPosition).sqrMagnitude < 0.000004f
                               && _dollyVelocity.sqrMagnitude < 0.0001f
                               && Mathf.Abs(targetCamera.fieldOfView - targetFieldOfView) < 0.01f;
                if (!_presenceShot && !_hasOverride && arrived)
                {
                    _dolly = false;
                    _dollyVelocity = Vector3.zero;
                    _fieldOfViewVelocity = 0f;
                }

                return;
            }

            float step = 1f - Mathf.Exp(-Mathf.Max(0.2f, smoothing) * dt);
            cameraTransform.position = Vector3.Lerp(cameraTransform.position, targetPosition, step);
            cameraTransform.rotation = Quaternion.Slerp(cameraTransform.rotation, targetRotation, step);
            targetCamera.fieldOfView = Mathf.Lerp(targetCamera.fieldOfView, targetFieldOfView, step);
        }

        private float WideFieldOfView()
        {
            return wideShotFieldOfView > 0f ? wideShotFieldOfView : _capturedFieldOfView;
        }

        private Vector3 PanelPosition()
        {
            return panelShotOffset.sqrMagnitude > 0.0001f ? _basePosition + panelShotOffset : panelShotPosition;
        }

        private float PanelFieldOfView()
        {
            return panelShotFieldOfView > 0f ? panelShotFieldOfView : _baseFieldOfView;
        }

        private Vector3 PresencePosition()
        {
            return presenceShotPosition.sqrMagnitude > 0.0001f ? presenceShotPosition : wideShotPosition;
        }

        private float PresenceFieldOfView()
        {
            return presenceShotFieldOfView > 0f ? presenceShotFieldOfView : WideFieldOfView();
        }

        /// <summary>
        /// Looks at the current state and, if a transition is under way, also at the
        /// target one: this way the camera starts opening as the dance starts
        /// instead of lagging a quarter of a second behind.
        /// </summary>
        private bool NeedsWideShot()
        {
            return wideShotEnabled && choreographer != null && choreographer.IsWideShot;
        }
    }
}
