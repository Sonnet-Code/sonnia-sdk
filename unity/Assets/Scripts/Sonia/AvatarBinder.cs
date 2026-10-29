// Hooks the Sonia pipeline up to an avatar.
//
// Everything that moves the avatar lives on the Sonia object and points at its
// bones and meshes: MotionPlayer (the Animator), away-mode presence, the head
// (AvatarStateController), the eyes (EyeGazeController) and the face (FaceRig,
// which notifies lip-sync, blinking and expressions). In edit mode the scene
// only holds an empty anchor and, outside the Sonia hierarchy and disabled, the
// fallback avatar (Sticker, from the Genies Avatar Starter Pack).
//
// Without the Genies Avatar SDK installed, the fallback avatar is bound at
// startup and that is the avatar shown. With the SDK, the optional integration
// (Sonia.Genies) installs itself into ExternalSource before the scene loads: it
// adds GeniesAvatarLoader, which loads the SDK avatar and calls Bind when it is
// ready; the fallback only appears if the SDK delivers none.

using System;
using System.Collections;
using UnityEngine;

namespace Sonia
{
    /// <summary>Moves the Sonia pipeline (animation, head, eyes and face) to another avatar.</summary>
    [DisallowMultipleComponent]
    public class AvatarBinder : MonoBehaviour
    {
        [SerializeField]
        [Tooltip("Avatar currently bound: the empty anchor until the first Bind.")]
        private Transform current;

        [SerializeField]
        [Tooltip("Fallback avatar (Sticker) that the scene keeps disabled. It is the avatar if the Genies Avatar SDK is not installed, and the last resort if the SDK delivers none.")]
        private Transform standIn;

        [SerializeField]
        [Tooltip("Genies avatar definition (SDK JSON) loaded at startup. Only used with the Genies Avatar SDK installed.")]
        private TextAsset geniesDefinition;

        [SerializeField]
        [Tooltip("Wave hello when the fallback avatar appears.")]
        private bool greetOnAppear = true;

        /// <summary>Delay between the avatar appearing and the greeting, so the player is already driving it.</summary>
        private const float GreetDelaySeconds = 0.4f;

        /// <summary>
        /// Optional avatar source (the Genies integration installs it before the
        /// scene loads). Returns true if it takes care of providing the avatar;
        /// if it is null or returns false, the fallback avatar is bound.
        /// </summary>
        public static Func<AvatarBinder, bool> ExternalSource;

        private bool _external;

        /// <summary>Fallback avatar (Sticker), disabled until needed.</summary>
        public Transform StandIn
        {
            get { return standIn; }
        }

        /// <summary>Genies definition of the app's character (null if none).</summary>
        public TextAsset GeniesDefinition
        {
            get { return geniesDefinition; }
        }

        /// <summary>Avatar bound right now.</summary>
        public Transform Current
        {
            get { return current; }
        }

        /// <summary>Raised after a new avatar is bound.</summary>
        public event Action<Transform> AvatarChanged;

        private void Awake()
        {
            Func<AvatarBinder, bool> source = ExternalSource;
            _external = source != null && source(this);
            if (!_external && standIn != null && current != standIn)
            {
                standIn.gameObject.SetActive(false);
            }
        }

        private void Start()
        {
            if (!_external)
            {
                ShowStandIn();
            }
        }

        /// <summary>
        /// Binds the fallback avatar (Sticker). Returns false if there is none or
        /// it has no Humanoid Animator.
        /// </summary>
        public bool ShowStandIn()
        {
            if (standIn == null)
            {
                Debug.LogWarning("[Sonnia] AvatarBinder has no fallback avatar: nothing to show.", this);
                return false;
            }

            if (current == standIn)
            {
                return true;
            }

            standIn.gameObject.SetActive(true);
            if (!Bind(standIn))
            {
                standIn.gameObject.SetActive(false);
                return false;
            }

            if (greetOnAppear && isActiveAndEnabled)
            {
                StartCoroutine(GreetSoon());
            }

            return true;
        }

        private IEnumerator GreetSoon()
        {
            yield return new WaitForSecondsRealtime(GreetDelaySeconds);
            AvatarChoreographer choreographer = Find<AvatarChoreographer>();
            if (choreographer != null && choreographer.Ready)
            {
                choreographer.PlayGreetingNow();
            }
        }

        /// <summary>
        /// Puts <paramref name="avatar"/> in the current one's place, hooks the
        /// whole pipeline up to it and turns the previous one off. Returns false
        /// (and changes nothing) if the avatar has no Humanoid Animator.
        /// </summary>
        public bool Bind(Transform avatar)
        {
            if (avatar == null)
            {
                return false;
            }

            Animator animator = avatar.GetComponentInChildren<Animator>(true);
            if (animator == null || !animator.isHuman)
            {
                Debug.LogWarning("[Sonnia] Avatar " + avatar.name + " has no Humanoid Animator; keeping the previous one.", avatar);
                return false;
            }

            // Presence first returns the current avatar to its idle pose: if it was
            // out of frame, the new one must not copy that position.
            PresenceController presence = Find<PresenceController>();
            if (presence != null)
            {
                presence.ReleaseAvatar();
            }

            Transform previous = current;
            if (previous != null && previous != avatar)
            {
                avatar.SetParent(previous.parent, false);
                avatar.localPosition = previous.localPosition;
                avatar.localRotation = previous.localRotation;
                avatar.localScale = previous.localScale;
            }

            // Clips play in place and the avatar must not freeze if the camera
            // loses it for a moment.
            animator.applyRootMotion = false;
            animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            Transform head = animator.GetBoneTransform(HumanBodyBones.Head);

            MotionPlayer motion = Find<MotionPlayer>();
            if (motion != null)
            {
                motion.Animator = animator;
            }

            if (presence != null)
            {
                presence.Rebind(animator);
            }

            AvatarStateController state = Find<AvatarStateController>();
            if (state != null)
            {
                state.HeadBone = head;
            }

            EyeGazeController gaze = Find<EyeGazeController>();
            if (gaze != null)
            {
                gaze.Bind(head);
            }

            FaceRig face = Find<FaceRig>();
            if (face != null)
            {
                face.AvatarRoot = avatar;
            }

            if (previous != null && previous != avatar)
            {
                previous.gameObject.SetActive(false);
            }

            current = avatar;
            Debug.Log("[Sonnia] Avatar bound: " + avatar.name
                      + (face != null && face.IsGenies ? " (Genies FACS face)" : string.Empty), avatar);

            Action<Transform> handler = AvatarChanged;
            if (handler != null)
            {
                handler(avatar);
            }

            return true;
        }

        private T Find<T>() where T : Component
        {
            T component = GetComponent<T>();
            return component != null ? component : GetComponentInChildren<T>(true);
        }
    }
}
