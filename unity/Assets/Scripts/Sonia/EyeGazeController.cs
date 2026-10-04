// Mirada de los ojos: los huesos de los ojos siguen al objetivo con sacadas.
//
// La cabeza la orienta AvatarStateController; aquí se giran los propios ojos
// dentro de la cabeza, que es lo que separa una mirada viva de una estatua:
//
//  - Fijación: los dos ojos convergen en el punto que toca (la cámara, el panel
//    de imágenes, el punto de "pensar"), cada uno desde su posición.
//  - Sacadas: cada poco tiempo la mirada salta unos grados a un lado y vuelve;
//    un salto grande va acompañado de un parpadeo, como en una persona.
//  - Vistazos: de vez en cuando aparta la vista un momento y regresa.
//  - Microtemblor: ruido muy pequeño y continuo para que nunca estén quietos.
//  - Durante bailes y gestos grandes (plano abierto) todo es más amplio y más
//    frecuente, que es cuando más cantaban los ojos fijos.
//
// Los huesos de los ojos no están mapeados en el rig humanoide a propósito
// (los clips no traen curvas de ojos y el retargeting los dejaba bizcos), así
// que nadie más los toca y no hace falta pelearse con el Animator.

using UnityEngine;

namespace Sonia
{
    /// <summary>Gira los huesos de los ojos hacia el objetivo con sacadas y vistazos.</summary>
    [DefaultExecutionOrder(12100)]
    [DisallowMultipleComponent]
    public class EyeGazeController : MonoBehaviour
    {
        [Header("Huesos")]
        [SerializeField]
        [Tooltip("Hueso del ojo izquierdo. Si está vacío se busca un hijo de la cabeza llamado LeftEye.")]
        private Transform leftEye;

        [SerializeField]
        [Tooltip("Hueso del ojo derecho. Si está vacío se busca un hijo de la cabeza llamado RightEye.")]
        private Transform rightEye;

        [SerializeField]
        [Tooltip("Hueso de la cabeza, para buscar los ojos y medir la mirada.")]
        private Transform headBone;

        [Header("Objetivo")]
        [SerializeField]
        [Tooltip("De dónde sale el punto al que mirar (cámara, panel, pensar). Si está vacío, la cámara principal.")]
        private AvatarStateController stateController;

        [SerializeField]
        [Tooltip("Coreógrafo, para saber cuándo hay un gesto grande y animar más los ojos.")]
        private AvatarChoreographer choreographer;

        [SerializeField]
        [Tooltip("Parpadeo: un salto grande de la mirada dispara un parpadeo.")]
        private bool blinkOnBigSaccade = true;

        [SerializeField]
        [Range(0.5f, 6f)]
        [Tooltip("Distancia mínima de enfoque en metros. La cámara está muy cerca y mirarla tal cual hace converger los ojos como si bizqueara; se mira al mismo sitio pero más lejos.")]
        private float minFocusDistance = 2.5f;

        [Header("Límites (grados)")]
        [SerializeField]
        [Range(0.2f, 1f)]
        [Tooltip("Cuánto compensan los ojos lo que la cabeza no gira. Con ojos grandes estilizados, compensarlo todo lee como mirar de reojo; con 0,65 los ojos acompañan a la cabeza y solo la corrigen en parte.")]
        private float gazeGain = 0.65f;

        [SerializeField]
        [Range(-10f, 10f)]
        [Tooltip("Separación de las pupilas, en grados por ojo: negativo las separa (mirada más paralela), positivo las junta (converge). 0 deja la geometría pura hacia el punto de enfoque.")]
        private float convergenceDegrees = -8f;

        [SerializeField]
        [Range(5f, 40f)]
        private float maxYaw = 10f;

        [SerializeField]
        [Range(5f, 30f)]
        private float maxPitch = 8f;

        [Header("Sacadas")]
        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre sacadas en conversación.")]
        private Vector2 saccadeInterval = new Vector2(0.7f, 2.6f);

        [SerializeField]
        [Tooltip("Amplitud máxima de una sacada normal, en grados (horizontal, vertical).")]
        private Vector2 saccadeAmplitude = new Vector2(2.5f, 1.5f);

        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre vistazos a otro sitio.")]
        private Vector2 glanceInterval = new Vector2(4f, 9f);

        [SerializeField]
        [Tooltip("Duración de un vistazo, en segundos (mínimo y máximo).")]
        private Vector2 glanceDuration = new Vector2(0.35f, 0.9f);

        [SerializeField]
        [Tooltip("Amplitud de un vistazo, en grados (horizontal, vertical).")]
        private Vector2 glanceAmplitude = new Vector2(5f, 3f);

        [SerializeField]
        [Tooltip("Multiplicador de amplitud y frecuencia durante bailes y gestos grandes.")]
        [Range(1f, 4f)]
        private float wideShotLiveliness = 1.6f;

        [SerializeField]
        [Range(2f, 15f)]
        [Tooltip("Desviación máxima total (sacada + vistazo) respecto al objetivo, en grados. Con la cabeza quieta, un ojo que se va más de esto parece bizco.")]
        private float maxOffsetDegrees = 7f;

        [Header("Movimiento")]
        [SerializeField]
        [Range(5f, 60f)]
        [Tooltip("Velocidad con la que los ojos alcanzan su destino. Las sacadas son casi instantáneas.")]
        private float speed = 30f;

        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Amplitud del microtemblor continuo, en grados.")]
        private float jitterDegrees = 0.35f;

        private Quaternion _leftRest;
        private Quaternion _rightRest;
        private Vector2 _saccade;
        private Vector2 _glance;
        private Vector2 _current;
        private float _saccadeTimer;
        private float _glanceTimer;
        private float _glanceRemaining;
        private float _noiseSeed;
        private float _lastPitch;
        private bool _ready;

        /// <summary>Desviación actual de la mirada respecto al objetivo (yaw, pitch en grados).</summary>
        public Vector2 CurrentOffset
        {
            get { return _current; }
        }

        /// <summary>Grados que miran los ojos hacia abajo dentro de la cabeza (0 si miran al frente o arriba). El párpado lo sigue.</summary>
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

        /// <summary>Pasa a otro avatar: cabeza nueva y ojos buscados de nuevo bajo ella.</summary>
        public void Bind(Transform head)
        {
            headBone = head;
            leftEye = null;
            rightEye = null;
            Bind();
        }

        /// <summary>Busca los huesos y guarda su pose de reposo. Se llama sola al arrancar.</summary>
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
            _glanceTimer = Random.Range(glanceInterval.x, glanceInterval.y);
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

            UpdateSaccades(dt, mult);
            UpdateGlances(dt, mult);

            Vector2 jitter = new Vector2(
                (Mathf.PerlinNoise(_noiseSeed, Time.time * 7f) - 0.5f) * 2f * jitterDegrees,
                (Mathf.PerlinNoise(_noiseSeed + 31f, Time.time * 6f) - 0.5f) * 2f * jitterDegrees);

            Vector2 wanted = _saccade + _glance;
            if (wanted.magnitude > maxOffsetDegrees)
            {
                wanted = wanted.normalized * maxOffsetDegrees;
            }

            float step = 1f - Mathf.Exp(-speed * dt);
            _current = Vector2.Lerp(_current, wanted, step);
            Vector2 offset = _current + jitter;

            Vector3 target;
            bool hasTarget = TryGetTarget(out target);

            // Hacia dentro es +X local (derecha de la cabeza) para el ojo izquierdo
            // y -X para el derecho: la convergencia se aplica con signo opuesto.
            Aim(leftEye, _leftRest, hasTarget, target, offset, convergenceDegrees);
            Aim(rightEye, _rightRest, hasTarget, target, offset, -convergenceDegrees);
        }

        private void UpdateSaccades(float dt, float mult)
        {
            _saccadeTimer -= dt * mult;
            if (_saccadeTimer > 0f)
            {
                return;
            }

            _saccadeTimer = Random.Range(saccadeInterval.x, saccadeInterval.y);
            Vector2 next = new Vector2(
                Random.Range(-saccadeAmplitude.x, saccadeAmplitude.x) * mult,
                Random.Range(-saccadeAmplitude.y, saccadeAmplitude.y) * mult);

            // La mayoría de las sacadas vuelven cerca del centro: si no, la
            // mirada deriva y parece que no mira a nadie.
            if (Random.value < 0.45f)
            {
                next *= 0.25f;
            }

            if (blinkOnBigSaccade && stateController != null && (next - _saccade).magnitude > 6f)
            {
                stateController.TriggerBlink();
            }

            _saccade = next;
        }

        private void UpdateGlances(float dt, float mult)
        {
            if (_glanceRemaining > 0f)
            {
                _glanceRemaining -= dt;
                if (_glanceRemaining <= 0f)
                {
                    _glance = Vector2.zero;
                    _glanceTimer = Random.Range(glanceInterval.x, glanceInterval.y);
                }

                return;
            }

            _glanceTimer -= dt * mult;
            if (_glanceTimer > 0f)
            {
                return;
            }

            _glanceRemaining = Random.Range(glanceDuration.x, glanceDuration.y);
            _glance = new Vector2(
                Random.Range(-glanceAmplitude.x, glanceAmplitude.x) * mult,
                Random.Range(-glanceAmplitude.y, glanceAmplitude.y * 0.6f) * mult);

            if (blinkOnBigSaccade && stateController != null && _glance.magnitude > 8f)
            {
                stateController.TriggerBlink();
            }
        }

        private bool TryGetTarget(out Vector3 target)
        {
            bool found = false;
            target = Vector3.zero;
            if (stateController != null && stateController.TryGetLookPosition(out target))
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

            // Se aleja el punto de enfoque a lo largo de la misma dirección para
            // que los dos ojos no converjan en exceso.
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
        /// Orienta un ojo hacia el objetivo más la desviación, dentro de los
        /// límites, partiendo de su rotación de reposo dentro de la cabeza. El
        /// eje Z local del hueso es hacia delante (así vienen Ready Player Me,
        /// Mixamo y VRM).
        /// </summary>
        private void Aim(Transform eye, Quaternion rest, bool hasTarget, Vector3 target, Vector2 offset, float inwardDegrees)
        {
            if (eye == null || eye.parent == null)
            {
                return;
            }

            // Dirección deseada en el espacio del padre (la cabeza).
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

            // Yaw y pitch respecto a la mirada de reposo, más la desviación.
            Quaternion restInverse = Quaternion.Inverse(rest);
            Vector3 inRest = restInverse * desiredLocal;
            float yaw = Mathf.Atan2(inRest.x, inRest.z) * Mathf.Rad2Deg * gazeGain + offset.x + inwardDegrees;
            float pitch = -Mathf.Asin(Mathf.Clamp(inRest.y, -1f, 1f)) * Mathf.Rad2Deg * gazeGain + offset.y;
            yaw = Mathf.Clamp(yaw, -maxYaw, maxYaw);
            pitch = Mathf.Clamp(pitch, -maxPitch, maxPitch);
            _lastPitch = pitch;

            eye.localRotation = rest * Quaternion.Euler(pitch, yaw, 0f);
        }
    }
}
