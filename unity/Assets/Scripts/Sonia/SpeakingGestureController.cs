// Gesticulación mientras Sonia habla y asentimientos mientras escucha.
//
// Repetir siempre la misma animación al hablar canta muchísimo en una demo. En
// cada frase se elige una variante distinta de las tres de "hablar"; mientras
// escucha se dispara un asentimiento cada pocos segundos.

using UnityEngine;

namespace Sonia
{
    /// <summary>
    /// Mueve el parámetro <c>GestureVariant</c> y el trigger <c>Gesture</c> del
    /// Animator. Sin Animator o sin esos parámetros no hace nada.
    /// </summary>
    [DisallowMultipleComponent]
    public class SpeakingGestureController : MonoBehaviour
    {
        [Header("Animator")]
        [SerializeField]
        [Tooltip("Animator del avatar. Debe tener los parámetros GestureVariant y Gesture.")]
        private Animator animator;

        [Header("Al hablar")]
        [SerializeField]
        [Tooltip("Número de variantes de gesticulación disponibles (Speaking0, Speaking1, Speaking2).")]
        [Range(1, 8)]
        private int speakingVariantCount = SoniaAnimations.SpeakingVariantCount;

        [Header("Al escuchar")]
        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre asentimientos mientras escucha.")]
        private Vector2 nodIntervalRange = new Vector2(4f, 8f);

        [Header("Registro")]
        [SerializeField]
        [Tooltip("Escribir en la consola cada cambio de gesto.")]
        private bool logEvents;

        private AvatarState _state = AvatarState.Idle;
        private int _lastVariant = -1;
        private float _timeToNextNod = -1f;
        private RuntimeAnimatorController _checkedController;
        private bool _parametersReady;

        /// <summary>Variante de gesticulación elegida en la última frase.</summary>
        public int CurrentVariant
        {
            get { return _lastVariant; }
        }

        private void Awake()
        {
            if (animator == null)
            {
                animator = GetComponentInChildren<Animator>(true);
            }
        }

        /// <summary>Recibe el estado del orquestador; solo el listening programa asentimientos.</summary>
        public void SetState(AvatarState state)
        {
            if (state == _state)
            {
                return;
            }

            _state = state;
            _timeToNextNod = state == AvatarState.Listening ? RandomNodInterval() : -1f;

            // Si el trigger se quedó sin consumir, saltaría más tarde y cambiaría
            // de gesto en un momento absurdo.
            if (state != AvatarState.Listening && state != AvatarState.Speaking && AnimatorReady())
            {
                animator.ResetTrigger(SoniaAnimations.GestureTrigger);
            }
        }

        /// <summary>
        /// Se llama en cada <c>speech_start</c>: elige una variante de gesticulación
        /// distinta de la anterior y avisa al Animator.
        /// </summary>
        public void NotifySpeechStart()
        {
            if (!AnimatorReady())
            {
                return;
            }

            int variant = PickVariant();
            animator.SetInteger(SoniaAnimations.GestureVariantParameter, variant);
            animator.SetTrigger(SoniaAnimations.GestureTrigger);
            _lastVariant = variant;

            if (logEvents)
            {
                Debug.Log("[Sonia] gesto al hablar: variante " + variant, this);
            }
        }

        private void Update()
        {
            if (_state != AvatarState.Listening || _timeToNextNod < 0f)
            {
                return;
            }

            _timeToNextNod -= Time.deltaTime;
            if (_timeToNextNod > 0f)
            {
                return;
            }

            _timeToNextNod = RandomNodInterval();
            if (!AnimatorReady())
            {
                return;
            }

            animator.SetTrigger(SoniaAnimations.GestureTrigger);

            if (logEvents)
            {
                Debug.Log("[Sonia] asentimiento al escuchar.", this);
            }
        }

        private int PickVariant()
        {
            int count = Mathf.Max(1, speakingVariantCount);
            if (count == 1)
            {
                return 0;
            }

            int variant = UnityEngine.Random.Range(0, count);
            if (variant == _lastVariant)
            {
                variant = (variant + 1 + UnityEngine.Random.Range(0, count - 1)) % count;
            }

            return variant;
        }

        private float RandomNodInterval()
        {
            float min = Mathf.Max(0.5f, Mathf.Min(nodIntervalRange.x, nodIntervalRange.y));
            float max = Mathf.Max(min + 0.5f, Mathf.Max(nodIntervalRange.x, nodIntervalRange.y));
            return UnityEngine.Random.Range(min, max);
        }

        /// <summary>Comprueba una sola vez por controlador que están los parámetros que hacen falta.</summary>
        private bool AnimatorReady()
        {
            if (animator == null)
            {
                return false;
            }

            RuntimeAnimatorController controller = animator.runtimeAnimatorController;
            if (controller == null)
            {
                _checkedController = null;
                return false;
            }

            if (ReferenceEquals(controller, _checkedController))
            {
                return _parametersReady;
            }

            _checkedController = controller;
            _parametersReady =
                SoniaAnimations.HasParameter(
                    animator, SoniaAnimations.GestureVariantParameter, AnimatorControllerParameterType.Int)
                && SoniaAnimations.HasParameter(
                    animator, SoniaAnimations.GestureTrigger, AnimatorControllerParameterType.Trigger);

            if (!_parametersReady)
            {
                Debug.LogWarning(
                    "[Sonia] El Animator no tiene los parámetros GestureVariant y Gesture; no habrá "
                    + "gesticulación al hablar. Ejecuta Sonia > Crear Animator Controller.",
                    this);
            }

            return _parametersReady;
        }
    }
}
