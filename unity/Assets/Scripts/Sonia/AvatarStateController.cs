// Estado del avatar: mirada y parpadeo.
//
// El estado llega por el protocolo (idle, listening, thinking, speaking). Las
// animaciones del cuerpo las lleva AvatarChoreographer; aquí se decide hacia
// dónde mira Sonia según el estado y se añade el parpadeo. La mirada se aplica
// en LateUpdate para que no la pise la animación.

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
    /// Orienta la cabeza hacia donde toca según el estado y añade parpadeo
    /// aleatorio. Todo es opcional: sin hueso de cabeza o sin blendshapes de
    /// ojos el componente no hace nada.
    /// </summary>
    // Corre después del LateUpdate de Vrm10Instance (orden 11000), que aplica sus
    // expresiones (a cero) y la mirada; así los blendshapes de boca y parpadeo
    // que escribimos aquí prevalecen y los ojos ya tienen la mirada aplicada.
    [DefaultExecutionOrder(12000)]
    [DisallowMultipleComponent]
    public class AvatarStateController : MonoBehaviour
    {
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
        [Range(0f, 1f)]
        [Tooltip("Peso de la mirada durante bailes y gestos grandes: la animación de la cabeza manda más.")]
        private float wideShotLookWeight = 0.3f;

        [SerializeField]
        [Tooltip("Coreógrafo, para saber cuándo hay un gesto grande. Opcional.")]
        private AvatarChoreographer choreographer;

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

        [SerializeField]
        [Range(0f, 5f)]
        [Tooltip("Amplitud en grados del vaivén lento y continuo de la cabeza, para que nunca esté clavada.")]
        private float headSwayDegrees = 1.4f;

        [SerializeField]
        [Range(0f, 8f)]
        [Tooltip("Grados que baja la cabeza en las sílabas fuertes mientras habla (según la boca del lip-sync).")]
        private float speechNodDegrees = 2.5f;

        [SerializeField]
        [Tooltip("Lip-sync, para acompasar los pequeños asentimientos a la voz. Opcional.")]
        private LipSyncController lipSync;

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
        // Desvío de la mirada respecto a la animación, en el espacio local de la
        // cabeza. Se suaviza en local a propósito: si se suavizara la rotación en
        // el mundo, al girar el cuerpo deprisa la cabeza se quedaría "clavada"
        // mirando al sitio antiguo.
        private Quaternion _lookOffset = Quaternion.identity;
        private float _currentWeight;
        private bool _lookInitialized;
        private bool _imageVisible;
        private float _imageShownAt = -999f;
        private int _blinkLeftIndex = -1;
        private int _blinkRightIndex = -1;
        private float _blinkScale = 1f;
        private float _timeToNextBlink;
        private float _blinkRemaining;
        private float _noiseSeed;
        private float _nodLevel;

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

            if (lipSync == null)
            {
                lipSync = GetComponentInChildren<LipSyncController>(true);
            }

            if (choreographer == null)
            {
                choreographer = GetComponentInChildren<AvatarChoreographer>(true);
            }

            _noiseSeed = UnityEngine.Random.value * 100f;

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
            _blinkScale = LipSyncController.BlendShapeScale(mesh);
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
                _lookOffset = Quaternion.identity;
                _currentWeight = lookWeight;
                _lookInitialized = true;
            }

            bool wide = choreographer != null && choreographer.IsWideShot;
            float targetWeight = wide ? wideShotLookWeight : lookWeight;
            _currentWeight = Mathf.Lerp(_currentWeight, targetWeight, 1f - Mathf.Exp(-3f * deltaTime));

            Quaternion desiredOffset = Quaternion.identity;
            Vector3 targetPosition;
            if (TryGetLookPosition(out targetPosition))
            {
                Vector3 direction = targetPosition - headBone.position;
                if (direction.sqrMagnitude > 0.0001f)
                {
                    // Vaivén lento (ruido Perlin) y un asentimiento leve en las sílabas
                    // fuertes: una cabeza real nunca se queda clavada mirando un punto.
                    float swayYaw = (Mathf.PerlinNoise(_noiseSeed, Time.time * 0.35f) - 0.5f) * 2f * headSwayDegrees;
                    float swayPitch = (Mathf.PerlinNoise(_noiseSeed + 17f, Time.time * 0.28f) - 0.5f) * 2f * headSwayDegrees;
                    float open = lipSync != null ? lipSync.MouthOpen : 0f;
                    _nodLevel = Mathf.Lerp(_nodLevel, open, 1f - Mathf.Exp(-6f * deltaTime));
                    Quaternion desired = Quaternion.LookRotation(direction.normalized, Vector3.up)
                                         * Quaternion.Euler(headRotationOffset)
                                         * Quaternion.Euler(swayPitch + _nodLevel * speechNodDegrees, swayYaw, 0f);
                    Quaternion limited = Quaternion.RotateTowards(baseRotation, desired, maxLookAngle);

                    // Desvío respecto a la animación, en local: viaja con el cuerpo.
                    desiredOffset = Quaternion.Inverse(baseRotation) * limited;
                }
            }

            _lookOffset = Quaternion.Slerp(_lookOffset, desiredOffset, StepFor(deltaTime));
            headBone.rotation = baseRotation * Quaternion.Slerp(Quaternion.identity, _lookOffset, _currentWeight);
        }

        private float StepFor(float deltaTime)
        {
            return 1f - Mathf.Exp(-Mathf.Max(0.1f, lookSmoothing) * deltaTime);
        }

        /// <summary>Punto del mundo al que mira ahora mismo (visitante, panel o el punto de pensar).</summary>
        public bool TryGetLookPosition(out Vector3 position)
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

        /// <summary>Parpadea ahora mismo (si no está ya parpadeando). Lo usan las sacadas grandes.</summary>
        public void TriggerBlink()
        {
            if (_blinkRemaining <= 0f)
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
                faceRenderer.SetBlendShapeWeight(_blinkLeftIndex, weight * _blinkScale);
            }

            if (_blinkRightIndex >= 0)
            {
                faceRenderer.SetBlendShapeWeight(_blinkRightIndex, weight * _blinkScale);
            }
        }
    }
}
