// Animaciones de atención mientras Sonia está en idle.
//
// En un stand nadie se acerca a un avatar que está quieto. Mientras no hay
// conversación, este componente lanza cada cierto tiempo un baile o un gesto
// dirigido a quien pasa por delante (señalar, saludar, tocar la pantalla). En
// cuanto llega cualquier otro estado el temporizador se cancela: el propio
// Animator corta la animación porque el parámetro State cambia.

using UnityEngine;

namespace Sonia
{
    /// <summary>
    /// Programa las animaciones de atención del idle y el saludo de bienvenida.
    /// Sin Animator, o con un controlador sin los parámetros esperados, no hace
    /// nada y avisa una sola vez.
    /// </summary>
    [DisallowMultipleComponent]
    public class IdleAttentionController : MonoBehaviour
    {
        [Header("Animator")]
        [SerializeField]
        [Tooltip("Animator del avatar. Debe tener los parámetros IdleVariant, Attention y Greet.")]
        private Animator animator;

        [Header("Ritmo")]
        [SerializeField]
        [Tooltip("Segundos hasta la primera animación de atención al entrar en idle.")]
        private float firstDelaySeconds = 6f;

        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre animaciones de atención.")]
        private Vector2 intervalRange = new Vector2(12f, 30f);

        [Header("Pesos por categoría")]
        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de un gesto de cuarta pared: señalar, saludar, tocar la pantalla.")]
        private float fourthWallWeight = 0.45f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de un baile completo.")]
        private float danceWeight = 0.30f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de un gesto suave de relleno.")]
        private float softWeight = 0.25f;

        [Header("Saludo")]
        [SerializeField]
        [Tooltip("Segundos que hay que llevar en idle para que el siguiente listening dispare un saludo.")]
        private float minIdleSecondsForGreeting = 25f;

        [SerializeField]
        [Tooltip("Segundos mínimos entre dos saludos, para no saludar a la misma persona dos veces.")]
        private float greetingCooldownSeconds = 20f;

        [Header("Registro")]
        [SerializeField]
        [Tooltip("Escribir en la consola cada animación de atención que se lanza.")]
        private bool logEvents;

        /// <summary>Tope del contador del saludo, para que no crezca sin límite.</summary>
        private const float MaxTrackedSeconds = 3600f;

        private AvatarState _state = AvatarState.Idle;
        private float _stateSeconds;
        private float _lastIdleSeconds;
        private float _timeToNextAttention = -1f;
        private float _secondsSinceGreeting = MaxTrackedSeconds;
        private int _lastAttentionIndex = -1;
        private RuntimeAnimatorController _checkedController;
        private bool _parametersReady;

        /// <summary>Estado que se le ha comunicado al componente.</summary>
        public AvatarState State
        {
            get { return _state; }
        }

        /// <summary>Segundos que lleva Sonia en el estado actual.</summary>
        public float SecondsInState
        {
            get { return _stateSeconds; }
        }

        private void Awake()
        {
            if (animator == null)
            {
                animator = GetComponentInChildren<Animator>(true);
            }

            ScheduleFirstAttention();
        }

        /// <summary>
        /// Recibe el estado del orquestador. Solo el idle programa animaciones de
        /// atención; cualquier otro estado cancela el temporizador.
        /// </summary>
        public void SetState(AvatarState state)
        {
            if (state == _state)
            {
                return;
            }

            if (_state == AvatarState.Idle)
            {
                // Se guarda cuánto tiempo llevaba sola para decidir si toca saludar.
                _lastIdleSeconds = _stateSeconds;
            }

            _state = state;
            _stateSeconds = 0f;

            if (state == AvatarState.Idle)
            {
                ScheduleFirstAttention();
            }
            else
            {
                _timeToNextAttention = -1f;
            }

            // Un trigger que nadie consume se queda pendiente y saltaría al volver
            // al idle, con lo que Sonia se pondría a bailar sin venir a cuento.
            ClearPendingTriggers();
        }

        private void ClearPendingTriggers()
        {
            if (!AnimatorReady())
            {
                return;
            }

            if (_state != AvatarState.Idle)
            {
                animator.ResetTrigger(SoniaAnimations.AttentionTrigger);
            }

            if (_state != AvatarState.Idle && _state != AvatarState.Listening)
            {
                animator.ResetTrigger(SoniaAnimations.GreetTrigger);
            }
        }

        private void Update()
        {
            float deltaTime = Time.deltaTime;
            _stateSeconds += deltaTime;
            if (_secondsSinceGreeting < MaxTrackedSeconds)
            {
                _secondsSinceGreeting += deltaTime;
            }

            if (_state != AvatarState.Idle || _timeToNextAttention < 0f)
            {
                return;
            }

            _timeToNextAttention -= deltaTime;
            if (_timeToNextAttention > 0f)
            {
                return;
            }

            PlayRandomAttention();
            _timeToNextAttention = RandomInterval();
        }

        // ------------------------------------------------------------------
        // Animaciones de atención
        // ------------------------------------------------------------------

        /// <summary>Lanza ya una animación de atención elegida al azar con los pesos configurados.</summary>
        public void PlayRandomAttention()
        {
            AttentionClip clip = PickAttentionClip();
            if (clip != null)
            {
                PlayAttention(clip.Index);
            }
        }

        /// <summary>
        /// Lanza la animación de atención con ese índice de <c>IdleVariant</c>.
        /// Útil para probar un gesto concreto desde el inspector o desde el HUD.
        /// </summary>
        public void PlayAttention(int index)
        {
            if (!AnimatorReady())
            {
                return;
            }

            animator.SetInteger(SoniaAnimations.IdleVariantParameter, index);
            animator.SetTrigger(SoniaAnimations.AttentionTrigger);
            _lastAttentionIndex = index;

            if (logEvents)
            {
                AttentionClip clip = SoniaAnimations.FindByIndex(index);
                Debug.Log("[Sonia] atención: " + (clip != null ? clip.Name : index.ToString()), this);
            }
        }

        /// <summary>
        /// Saluda con la mano si Sonia está en idle o escuchando, llevaba un buen
        /// rato sola y no acaba de saludar. Devuelve cierto si lanzó el saludo.
        /// </summary>
        public bool PlayGreeting()
        {
            if (_state != AvatarState.Idle && _state != AvatarState.Listening)
            {
                return false;
            }

            float idleSeconds = _state == AvatarState.Idle ? _stateSeconds : _lastIdleSeconds;
            if (idleSeconds < minIdleSecondsForGreeting)
            {
                return false;
            }

            if (_secondsSinceGreeting < greetingCooldownSeconds)
            {
                return false;
            }

            if (!AnimatorReady())
            {
                return false;
            }

            animator.SetTrigger(SoniaAnimations.GreetTrigger);
            _secondsSinceGreeting = 0f;

            // Un saludo ya rompe el idle: no encadenar un gesto justo detrás.
            if (_state == AvatarState.Idle)
            {
                _timeToNextAttention = RandomInterval();
            }

            if (logEvents)
            {
                Debug.Log("[Sonia] saludo tras " + Mathf.RoundToInt(idleSeconds) + " s en idle.", this);
            }

            return true;
        }

        // ------------------------------------------------------------------
        // Elección y temporizadores
        // ------------------------------------------------------------------

        private AttentionClip PickAttentionClip()
        {
            AttentionClip[] all = SoniaAnimations.AttentionClips;
            if (all.Length == 0)
            {
                return null;
            }

            AttentionCategory category = PickCategory();

            // Se descarta la última animación para que no se repita seguida, salvo
            // que la categoría tenga una sola opción.
            AttentionClip candidate = null;
            int seen = 0;
            for (int i = 0; i < all.Length; i++)
            {
                if (all[i].Category != category || all[i].Index == _lastAttentionIndex)
                {
                    continue;
                }

                seen++;
                if (UnityEngine.Random.Range(0, seen) == 0)
                {
                    candidate = all[i];
                }
            }

            if (candidate != null)
            {
                return candidate;
            }

            // La categoría estaba vacía (o solo tenía la última): cualquiera vale.
            seen = 0;
            for (int i = 0; i < all.Length; i++)
            {
                if (all[i].Index == _lastAttentionIndex)
                {
                    continue;
                }

                seen++;
                if (UnityEngine.Random.Range(0, seen) == 0)
                {
                    candidate = all[i];
                }
            }

            return candidate != null ? candidate : all[0];
        }

        private AttentionCategory PickCategory()
        {
            float fourthWall = Mathf.Max(0f, fourthWallWeight);
            float dance = Mathf.Max(0f, danceWeight);
            float soft = Mathf.Max(0f, softWeight);
            float total = fourthWall + dance + soft;
            if (total <= 0f)
            {
                return AttentionCategory.FourthWall;
            }

            float roll = UnityEngine.Random.value * total;
            if (roll < fourthWall)
            {
                return AttentionCategory.FourthWall;
            }

            if (roll < fourthWall + dance)
            {
                return AttentionCategory.Dance;
            }

            return AttentionCategory.Soft;
        }

        private void ScheduleFirstAttention()
        {
            _timeToNextAttention = Mathf.Max(0.5f, firstDelaySeconds);
        }

        private float RandomInterval()
        {
            float min = Mathf.Max(1f, Mathf.Min(intervalRange.x, intervalRange.y));
            float max = Mathf.Max(min + 0.5f, Mathf.Max(intervalRange.x, intervalRange.y));
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
                    animator, SoniaAnimations.IdleVariantParameter, AnimatorControllerParameterType.Int)
                && SoniaAnimations.HasParameter(
                    animator, SoniaAnimations.AttentionTrigger, AnimatorControllerParameterType.Trigger)
                && SoniaAnimations.HasParameter(
                    animator, SoniaAnimations.GreetTrigger, AnimatorControllerParameterType.Trigger);

            if (!_parametersReady)
            {
                Debug.LogWarning(
                    "[Sonia] El Animator no tiene los parámetros IdleVariant, Attention y Greet; "
                    + "no habrá animaciones de atención. Ejecuta Sonia > Crear Animator Controller.",
                    this);
            }

            return _parametersReady;
        }
    }
}
