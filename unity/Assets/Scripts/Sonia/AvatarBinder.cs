// Engancha el pipeline de Sonia a un avatar.
//
// Todo lo que mueve al avatar vive en el objeto Sonia y apunta a sus huesos y
// mallas: MotionPlayer (el Animator), la presencia del modo Fuera, la cabeza
// (AvatarStateController), los ojos (EyeGazeController) y la cara (FaceRig, que
// avisa al lip-sync, al parpadeo y a las expresiones). El doble del editor ya
// llega cableado desde Sonia > Colocar avatar; cuando el SDK de Genies entrega el
// avatar de verdad (GeniesAvatarLoader), Bind lo pone exactamente en el sitio del
// doble, le pasa todas esas referencias y apaga el doble, que queda de respaldo.

using System;
using UnityEngine;

namespace Sonia
{
    /// <summary>Pasa el pipeline de Sonia (animación, cabeza, ojos y cara) a otro avatar.</summary>
    [DisallowMultipleComponent]
    public class AvatarBinder : MonoBehaviour
    {
        [SerializeField]
        [Tooltip("Avatar que hay ahora en escena: el doble (Sticker) hasta que el SDK entrega el de verdad.")]
        private Transform current;

        /// <summary>Avatar enganchado ahora mismo.</summary>
        public Transform Current
        {
            get { return current; }
        }

        /// <summary>Se lanza después de enganchar un avatar nuevo.</summary>
        public event Action<Transform> AvatarChanged;

        /// <summary>
        /// Pone <paramref name="avatar"/> en el sitio del actual, le engancha todo
        /// el pipeline y apaga el anterior. Devuelve falso (y no cambia nada) si el
        /// avatar no tiene un Animator Humanoid.
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
                Debug.LogWarning("[Sonia] El avatar " + avatar.name + " no tiene un Animator Humanoid; sigue el anterior.", avatar);
                return false;
            }

            // La presencia devuelve antes el avatar actual a su reposo: si estaba
            // fuera de cuadro, el nuevo no debe copiar esa posición.
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

            // Los clips se reproducen en el sitio y el avatar no debe congelarse si
            // la cámara lo pierde un instante.
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
            Debug.Log("[Sonia] Avatar enganchado: " + avatar.name
                      + (face != null && face.IsGenies ? " (cara FACS de Genies)" : string.Empty), avatar);

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
