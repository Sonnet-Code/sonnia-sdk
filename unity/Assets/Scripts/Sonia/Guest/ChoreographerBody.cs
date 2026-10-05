// Cuerpo de respaldo del invitado: el mismo de Sonia.
//
// Reposo, escuchar con asentimientos y gestos al hablar con los clips del set
// (AvatarChoreographer), y cabeza, parpadeo y mirada con AvatarStateController.
// Es lo que hay hasta que el motor de comportamiento de Genies tenga su
// adaptador de IAvatarBody (ver IAvatarBody.cs).

using UnityEngine;

namespace Sonia
{
    /// <summary>IAvatarBody sobre el coreógrafo y el control de estado de siempre.</summary>
    [DisallowMultipleComponent]
    public class ChoreographerBody : MonoBehaviour, IAvatarBody
    {
        [SerializeField]
        [Tooltip("Coreógrafo del avatar. Vacío: el de este objeto o sus hijos.")]
        private AvatarChoreographer choreographer;

        [SerializeField]
        [Tooltip("Cabeza, parpadeo y mirada. Vacío: el de este objeto o sus hijos.")]
        private AvatarStateController stateController;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Cuánto manda la mirada hacia quien atiende (el resto lo pone la animación de la cabeza).")]
        private float attentionWeight = 0.8f;

        [SerializeField]
        [Tooltip("Altura sobre el punto que atiende, en metros (al mirar a una cabeza, a los ojos y no a la nuca).")]
        private float attentionHeight = 0.04f;

        private bool _attending;
        private readonly ChoreographerHold _hold = new ChoreographerHold();

        /// <inheritdoc />
        public bool IsReady
        {
            get { return choreographer != null && choreographer.Ready; }
        }

        /// <inheritdoc />
        public bool IsFallback
        {
            get { return true; }
        }

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
        }

        /// <inheritdoc />
        public void SetTalking(bool talking)
        {
            // Callado escucha (bucle atento y asentimientos), no se queda en reposo:
            // es un invitado en directo y los visitantes le hablan.
            AvatarState state = talking ? AvatarState.Speaking : AvatarState.Listening;
            if (choreographer != null)
            {
                choreographer.SetState(state);
            }

            if (stateController != null)
            {
                stateController.SetState(state);
            }
        }

        /// <inheritdoc />
        public void NotifyPhrase()
        {
            if (choreographer != null)
            {
                choreographer.NotifySpeechStart();
            }
        }

        /// <inheritdoc />
        public void SetAttention(Transform target)
        {
            if (stateController == null)
            {
                return;
            }

            if (target != null)
            {
                stateController.SetLookOverride(target.position + (Vector3.up * attentionHeight), attentionWeight);
                _attending = true;
                return;
            }

            // Solo se suelta la mirada que puso este componente: al caminar la
            // dirige PresenceController.
            if (_attending)
            {
                _attending = false;
                stateController.ClearLookOverride();
            }
        }

        /// <inheritdoc />
        public bool PlayGesture(string clipName)
        {
            if (!IsReady)
            {
                return false;
            }

            AnimationCatalog.Entry entry;
            if (!AnimationCatalog.TryFind(choreographer.MotionSet, clipName, out entry))
            {
                return false;
            }

            choreographer.Preview(entry.Clip);
            return true;
        }

        /// <inheritdoc />
        public bool Wave()
        {
            if (!IsReady || choreographer.MotionSet.greeting == null)
            {
                return false;
            }

            choreographer.Preview(choreographer.MotionSet.greeting);
            return true;
        }

        /// <inheritdoc />
        public void Hold(bool hold)
        {
            if (hold)
            {
                _hold.Hold(choreographer);
            }
            else
            {
                _hold.Release(choreographer);
            }
        }
    }

    /// <summary>
    /// Deja un coreógrafo quieto en su bucle de reposo, sin variaciones ni
    /// gestos (lo suspende, como al caminar), y luego se lo devuelve sin
    /// reiniciar el bucle. Si ya estaba suspendido por otro (caminando), no hace nada.
    /// </summary>
    public sealed class ChoreographerHold
    {
        private MotionPlayer.Handle _rest;
        private bool _held;

        /// <summary>Cierto mientras lo tiene quieto este objeto.</summary>
        public bool IsHeld
        {
            get { return _held; }
        }

        public void Hold(AvatarChoreographer choreographer)
        {
            if (_held || choreographer == null || !choreographer.Ready || choreographer.IsSuspended)
            {
                return;
            }

            choreographer.Suspend();
            _held = true;

            // Una variación a medias se quedaría congelada en su último fotograma:
            // vuelve al bucle de reposo.
            AnimationClip rest = choreographer.MotionSet.idleLoop;
            MotionPlayer player = choreographer.Player;
            _rest = rest != null && player != null && player.CurrentClip(MotionPlayer.BodyLayer) != rest
                ? player.Play(rest, MotionPlayer.BodyLayer, 0.35f, 1f, Random.Range(0f, Mathf.Max(0f, rest.length - 0.5f)))
                : null;
        }

        public void Release(AvatarChoreographer choreographer)
        {
            if (!_held)
            {
                return;
            }

            _held = false;
            if (choreographer != null)
            {
                choreographer.Resume(_rest, 0.4f);
            }

            _rest = null;
        }
    }
}
