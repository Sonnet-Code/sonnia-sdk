// Estado del avatar: animaciones, mirada y parpadeo.
//
// El estado llega por el protocolo (idle, listening, thinking, speaking) y se
// traduce al parámetro entero "State" del Animator. La mirada se aplica en
// LateUpdate para que no la pise el Animator.

using System;
using UnityEngine;

namespace Sonia
{
    /// <summary>Estados del asistente, en el mismo orden que el parámetro del Animator.</summary>
    public enum AvatarState
    {
        Idle = 0,
        Listening = 1,
        Thinking = 2,
        Speaking = 3
    }

    /// <summary>
    /// Traduce el estado del orquestador a animaciones, orienta la cabeza hacia
    /// donde toca y añade parpadeo aleatorio. Todo es opcional: sin Animator, sin
    /// hueso de cabeza o sin blendshapes de ojos el componente no hace nada.
    /// </summary>
    // Corre después del LateUpdate de Vrm10Instance (orden 11000), que aplica sus
    // expresiones (a cero) y la mirada; así los blendshapes de boca y parpadeo
    // que escribimos aquí prevalecen y los ojos ya tienen la mirada aplicada.
    [DefaultExecutionOrder(12000)]
    [DisallowMultipleComponent]
    public class AvatarStateController : MonoBehaviour
    {
        [Header("Animator")]
        [SerializeField]
        [Tooltip("Animator del avatar. El controlador debe tener un parámetro entero llamado State.")]
        private Animator animator;

        [SerializeField]
        [Tooltip("Nombre del parámetro entero del Animator: 0 idle, 1 listening, 2 thinking, 3 speaking.")]
        private string stateParameter = "State";

        [Header("Mirada")]
        [SerializeField]
        [Tooltip("Hueso de la cabeza. Si está vacío no se toca la mirada.")]
        private Transform headBone;

        [SerializeField]
        [Tooltip("Raíz del avatar, para calcular el punto al que mira mientras piensa. Por defecto, este objeto.")]
        private Transform avatarRoot;

        [SerializeField]
        [Tooltip("A dónde mira al escuchar y al hablar. Normalmente la cámara.")]
        private Transform lookTarget;

        [SerializeField]
        [Tooltip("Punto opcional al que mira mientras piensa. Si está vacío se usa el desplazamiento de abajo.")]
        private Transform thinkingLookTarget;

        [SerializeField]
        [Tooltip("Desplazamiento local, respecto a la raíz del avatar, del punto al que mira mientras piensa. En pantalla vertical conviene más arriba que de lado.")]
        private Vector3 thinkingLookOffset = new Vector3(0.45f, 0.9f, 1.5f);

        [SerializeField]
        [Tooltip("Panel de imágenes. Mira hacia él mientras está visible.")]
        private Transform imageLookTarget;

        [SerializeField]
        [Tooltip("Mirar al panel de imágenes cuando aparece.")]
        private bool lookAtImageWhenVisible = true;

        [SerializeField]
        [Tooltip("Segundos que mira al panel cuando aparece una imagen; después vuelve al visitante. 0 = mientras esté visible.")]
        private float imageGlanceSeconds = 1.6f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Cuánto manda la mirada sobre la rotación que dicta el Animator.")]
        private float lookWeight = 0.7f;

        [SerializeField]
        [Range(0f, 90f)]
        [Tooltip("Grados máximos que la cabeza se aparta de la pose de la animación.")]
        private float maxLookAngle = 40f;

        [SerializeField]
        [Range(0.5f, 20f)]
        [Tooltip("Velocidad con la que la cabeza alcanza su objetivo.")]
        private float lookSmoothing = 5f;

        [SerializeField]
        [Tooltip("Corrección en grados si el eje hacia delante del hueso de la cabeza no es Z+.")]
        private Vector3 headRotationOffset = Vector3.zero;

        [Header("Parpadeo")]
        [SerializeField]
        [Tooltip("Malla con los blendshapes de los ojos. Si está vacía se usa la del lip-sync o ninguna.")]
        private SkinnedMeshRenderer faceRenderer;

        [SerializeField]
        [Tooltip("Blendshape del párpado izquierdo (convención ARKit / Ready Player Me).")]
        private string blinkLeftBlendShape = "eyeBlinkLeft";

        [SerializeField]
        [Tooltip("Blendshape del párpado derecho.")]
        private string blinkRightBlendShape = "eyeBlinkRight";

        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre parpadeos.")]
        private Vector2 blinkIntervalRange = new Vector2(2.5f, 6f);

        [SerializeField]
        [Tooltip("Duración de un parpadeo en segundos.")]
        private float blinkDuration = 0.14f;

        private AvatarState _state = AvatarState.Idle;
        private int _stateParameterHash;
        private bool _hasStateParameter;
        private RuntimeAnimatorController _checkedController;
        private Quaternion _smoothedLook = Quaternion.identity;
        private bool _lookInitialized;
        private bool _imageVisible;
        private float _imageShownAt = -999f;
        private int _blinkLeftIndex = -1;
        private int _blinkRightIndex = -1;
        private float _timeToNextBlink;
        private float _blinkRemaining;

        /// <summary>Estado actual del avatar.</summary>
        public AvatarState State
        {
            get { return _state; }
        }

        private void Awake()
        {
            if (avatarRoot == null)
            {
                avatarRoot = transform;
            }

            if (animator == null)
            {
                animator = GetComponentInChildren<Animator>();
            }

            _stateParameterHash = string.IsNullOrEmpty(stateParameter) ? 0 : Animator.StringToHash(stateParameter);
            RefreshBlendShapes();
            ScheduleNextBlink();
        }

        /// <summary>Vuelve a resolver los blendshapes de parpadeo (útil si el avatar se asigna tarde).</summary>
        public void RefreshBlendShapes()
        {
            _blinkLeftIndex = -1;
            _blinkRightIndex = -1;

            Mesh mesh = faceRenderer != null ? faceRenderer.sharedMesh : null;
            if (mesh == null)
            {
                return;
            }

            _blinkLeftIndex = mesh.GetBlendShapeIndex(blinkLeftBlendShape);
            _blinkRightIndex = mesh.GetBlendShapeIndex(blinkRightBlendShape);
        }

        // ------------------------------------------------------------------
        // Estado
        // ------------------------------------------------------------------

        /// <summary>Aplica el estado que llega en el mensaje <c>state</c> del protocolo.</summary>
        public void SetState(string stateName)
        {
            SetState(ParseState(stateName));
        }

        /// <summary>Aplica un estado del avatar.</summary>
        public void SetState(AvatarState state)
        {
            _state = state;
            ApplyStateToAnimator();
        }

        /// <summary>Convierte el nombre del protocolo al enum; lo desconocido queda en idle.</summary>
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

        private void ApplyStateToAnimator()
        {
            if (animator == null || _stateParameterHash == 0)
            {
                return;
            }

            RuntimeAnimatorController controller = animator.runtimeAnimatorController;
            if (controller == null)
            {
                _hasStateParameter = false;
                _checkedController = null;
                return;
            }

            if (!ReferenceEquals(controller, _checkedController))
            {
                _checkedController = controller;
                _hasStateParameter = false;
                AnimatorControllerParameter[] parameters = animator.parameters;
                for (int i = 0; i < parameters.Length; i++)
                {
                    if (parameters[i].type == AnimatorControllerParameterType.Int
                        && parameters[i].nameHash == _stateParameterHash)
                    {
                        _hasStateParameter = true;
                        break;
                    }
                }

                if (!_hasStateParameter)
                {
                    Debug.LogWarning(
                        "[Sonia] El Animator no tiene un parámetro entero llamado \"" + stateParameter
                        + "\"; no se cambiarán las animaciones.",
                        this);
                }
            }

            if (_hasStateParameter)
            {
                animator.SetInteger(_stateParameterHash, (int)_state);
            }
        }

        /// <summary>Le dice al avatar si el panel de imágenes está visible y dónde está.</summary>
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
        // Mirada y parpadeo
        // ------------------------------------------------------------------

        private void LateUpdate()
        {
            float deltaTime = Time.deltaTime;
            UpdateLook(deltaTime);
            UpdateBlink(deltaTime);
        }

        private void UpdateLook(float deltaTime)
        {
            if (headBone == null)
            {
                return;
            }

            Quaternion baseRotation = headBone.rotation;
            if (!_lookInitialized)
            {
                _smoothedLook = baseRotation;
                _lookInitialized = true;
            }

            Vector3 targetPosition;
            if (!TryGetLookPosition(out targetPosition))
            {
                _smoothedLook = Quaternion.Slerp(_smoothedLook, baseRotation, StepFor(deltaTime));
                headBone.rotation = Quaternion.Slerp(baseRotation, _smoothedLook, lookWeight);
                return;
            }

            Vector3 direction = targetPosition - headBone.position;
            if (direction.sqrMagnitude < 0.0001f)
            {
                return;
            }

            Quaternion desired = Quaternion.LookRotation(direction.normalized, Vector3.up)
                                 * Quaternion.Euler(headRotationOffset);
            Quaternion limited = Quaternion.RotateTowards(baseRotation, desired, maxLookAngle);
            _smoothedLook = Quaternion.Slerp(_smoothedLook, limited, StepFor(deltaTime));
            headBone.rotation = Quaternion.Slerp(baseRotation, _smoothedLook, lookWeight);
        }

        private float StepFor(float deltaTime)
        {
            return 1f - Mathf.Exp(-Mathf.Max(0.1f, lookSmoothing) * deltaTime);
        }

        private bool TryGetLookPosition(out Vector3 position)
        {
            // Un vistazo breve al panel cuando aparece la imagen; después la
            // mirada vuelve al visitante, que es lo natural en una conversación.
            bool glancing = imageGlanceSeconds <= 0f || Time.time - _imageShownAt < imageGlanceSeconds;
            if (lookAtImageWhenVisible && _imageVisible && imageLookTarget != null && glancing)
            {
                position = imageLookTarget.position;
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
                position = root.TransformPoint(thinkingLookOffset);
                return true;
            }

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

        private void UpdateBlink(float deltaTime)
        {
            if (faceRenderer == null || (_blinkLeftIndex < 0 && _blinkRightIndex < 0))
            {
                return;
            }

            if (_blinkRemaining > 0f)
            {
                _blinkRemaining -= deltaTime;
                float duration = Mathf.Max(0.02f, blinkDuration);
                float half = duration * 0.5f;
                float weight = _blinkRemaining > half
                    ? Mathf.InverseLerp(duration, half, _blinkRemaining)
                    : Mathf.InverseLerp(0f, half, _blinkRemaining);

                if (_blinkRemaining <= 0f)
                {
                    _blinkRemaining = 0f;
                    weight = 0f;
                    ScheduleNextBlink();
                }

                ApplyBlink(Mathf.Clamp01(weight) * 100f);
                return;
            }

            _timeToNextBlink -= deltaTime;
            if (_timeToNextBlink <= 0f)
            {
                _blinkRemaining = Mathf.Max(0.02f, blinkDuration);
            }
        }

        private void ScheduleNextBlink()
        {
            float min = Mathf.Max(0.2f, Mathf.Min(blinkIntervalRange.x, blinkIntervalRange.y));
            float max = Mathf.Max(min + 0.1f, Mathf.Max(blinkIntervalRange.x, blinkIntervalRange.y));
            _timeToNextBlink = UnityEngine.Random.Range(min, max);
        }

        private void ApplyBlink(float weight)
        {
            if (_blinkLeftIndex >= 0)
            {
                faceRenderer.SetBlendShapeWeight(_blinkLeftIndex, weight);
            }

            if (_blinkRightIndex >= 0)
            {
                faceRenderer.SetBlendShapeWeight(_blinkRightIndex, weight);
            }
        }
    }
}
