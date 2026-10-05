// Mirada de los ojos: los huesos de los ojos siguen al objetivo con fijaciones
// y microsacadas.
//
// La cabeza la orienta AvatarStateController, y solo en parte (sigue al
// visitante con peso 0,3): son los ojos los que miran a quien habla con Sonia,
// como en Mia (docs/informe-mia.md). Aquí se giran los propios ojos dentro de la
// cabeza:
//
//  - Fijaciones por estado, con las plantillas de atención de Genies medidas en
//    Mia. Hablando, fija en el visitante; escuchando, mira al visitante unos 6 s
//    y aparta la vista un momento (1,5-3 s, hasta ±11°) unas 8 veces por minuto:
//    Mia deja de mirar más (37 % de contacto), pero en un stand, con alguien
//    hablándole delante, eso se leía como no hacer caso; pensando, unos 20 por
//    minuto hacia arriba y a un lado; con el stand en calma, unos 17 por minuto,
//    amplios y a menudo hacia abajo. Un cambio de fijación grande suele llevar
//    parpadeo, como en Genies.
//  - Microsacadas: alrededor de la fijación, saltitos de un par de grados cada
//    poco; la mayoría vuelven cerca del centro.
//  - Microtemblor: ruido muy pequeño y continuo para que nunca estén quietos.
//  - Durante bailes y gestos grandes (plano abierto) las microsacadas son más
//    amplias y frecuentes.
//  - Los dos ojos convergen en el punto que toca, cada uno desde su posición, y
//    los límites se aplican a los dos por igual: si uno llega al tope, el otro
//    se corrige lo mismo y la vergencia no cambia (nada de bizquear).
//
// Los huesos de los ojos no están mapeados en el rig humanoide a propósito
// (los clips no traen curvas de ojos y el retargeting los dejaba bizcos), así
// que nadie más los toca y no hace falta pelearse con el Animator.

using System;
using UnityEngine;
using Random = UnityEngine.Random;

namespace Sonia
{
    /// <summary>
    /// Plantilla de mirada de un estado (como las plantillas de atención de
    /// Genies): cada cuánto cambia el punto de fijación, cuánto mira al visitante
    /// y hasta dónde se va cuando no.
    /// </summary>
    [Serializable]
    public struct GazeTemplate
    {
        [Tooltip("Cambios de punto de fijación por minuto. 0: fija en el visitante.")]
        public float jumpsPerMinute;

        [Range(0f, 1f)]
        [Tooltip("Parte de las fijaciones que van al visitante.")]
        public float eyeContact;

        [Tooltip("Desvío horizontal cuando no mira al visitante (grados, mínimo y máximo; el lado se elige al azar).")]
        public Vector2 yawDegrees;

        [Tooltip("Desvío vertical cuando no mira al visitante (grados, mínimo y máximo). Negativo es arriba.")]
        public Vector2 pitchDegrees;

        [Range(0f, 2f)]
        [Tooltip("Escala de las microsacadas alrededor de la fijación.")]
        public float micro;

        [Tooltip("Si es mayor que 0, mirar a otro sitio es un vistazo de esta duración (segundos, mínimo y máximo) y después vuelve al visitante.")]
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

    /// <summary>Gira los huesos de los ojos hacia el objetivo con fijaciones por estado y microsacadas.</summary>
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
        [Tooltip("De dónde sale el punto al que mirar (visitante, panel, caminar) y el estado. Si está vacío, la cámara principal.")]
        private AvatarStateController stateController;

        [SerializeField]
        [Tooltip("Coreógrafo, para saber cuándo hay un gesto grande y animar más los ojos.")]
        private AvatarChoreographer choreographer;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de parpadear en un cambio de fijación grande (más de 4°). Genies parpadea en cada cambio de objetivo.")]
        private float blinkOnShift = 0.7f;

        [SerializeField]
        [Range(0.5f, 6f)]
        [Tooltip("Distancia mínima de enfoque en metros. La cámara está muy cerca y mirarla tal cual hace converger los ojos como si bizqueara; se mira al mismo sitio pero más lejos.")]
        private float minFocusDistance = 2.5f;

        [Header("Mirada por estado")]
        [SerializeField]
        [Tooltip("Hablando: fija en el visitante, solo microsacadas (Genies, plantilla Speaking).")]
        private GazeTemplate speakingGaze = new GazeTemplate(0f, 1f, Vector2.zero, Vector2.zero, 0.6f);

        [SerializeField]
        [Tooltip("Escuchando: al visitante unos 6 s y un vistazo a otro sitio de 1,5-3 s, unas 8 veces por minuto (Mia, plantilla Listening, con más contacto).")]
        private GazeTemplate listeningGaze = new GazeTemplate(10f, 0.15f, new Vector2(4f, 11f), new Vector2(-3f, 3f), 1f, new Vector2(1.5f, 3f));

        [SerializeField]
        [Tooltip("Pensando: unos 20 por minuto, arriba y a un lado (Mia, plantilla Thinking).")]
        private GazeTemplate thinkingGaze = new GazeTemplate(20f, 0.29f, new Vector2(4f, 11f), new Vector2(-9f, -3f), 1f);

        [SerializeField]
        [Tooltip("Con el stand en calma (idle): unos 17 por minuto, amplios y a menudo abajo (Mia, plantilla Bored).")]
        private GazeTemplate idleGaze = new GazeTemplate(17f, 0.13f, new Vector2(5f, 14f), new Vector2(-3f, 8f), 1f);

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Al pensar, parte de las fijaciones que van al mismo lado (el resto, al otro).")]
        private float thinkingSameSide = 0.75f;

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
        [Tooltip("Giro horizontal máximo de cada ojo dentro de la cabeza.")]
        private float yawLimit = 16f;

        [SerializeField]
        [Range(5f, 30f)]
        [Tooltip("Giro vertical máximo de cada ojo dentro de la cabeza.")]
        private float pitchLimit = 11f;

        [SerializeField]
        [Range(2f, 30f)]
        [Tooltip("Desvío máximo total (fijación + microsacada) respecto al objetivo, en grados.")]
        private float excursionLimit = 14f;

        [Header("Microsacadas")]
        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre microsacadas.")]
        private Vector2 saccadeInterval = new Vector2(0.7f, 2.6f);

        [SerializeField]
        [Tooltip("Amplitud máxima de una microsacada, en grados (horizontal, vertical). La escala la plantilla del estado.")]
        private Vector2 saccadeAmplitude = new Vector2(2.5f, 1.5f);

        [SerializeField]
        [Tooltip("Multiplicador de amplitud y frecuencia de las microsacadas durante bailes y gestos grandes.")]
        [Range(1f, 4f)]
        private float wideShotLiveliness = 1.6f;

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

        /// <summary>Desviación actual de la mirada respecto al objetivo (yaw, pitch en grados).</summary>
        public Vector2 CurrentOffset
        {
            get { return _current; }
        }

        /// <summary>Punto de fijación actual respecto al visitante (yaw, pitch en grados). 0: lo mira.</summary>
        public Vector2 CurrentFixation
        {
            get { return _fixation; }
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

            // Hacia dentro es +X local (derecha de la cabeza) para el ojo izquierdo
            // y -X para el derecho: la convergencia se aplica con signo opuesto.
            Vector2 left = Angles(leftEye, _leftRest, hasTarget, target, offset, convergenceDegrees);
            Vector2 right = Angles(rightEye, _rightRest, hasTarget, target, offset, -convergenceDegrees);

            // Límites iguales para los dos ojos: si uno se pasa, los dos se
            // corrigen lo mismo y no cambia la vergencia.
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
                // Al empezar a hablar, al visitante ya.
                SetFixation(Vector2.zero);
                _fixationTimer = float.PositiveInfinity;
                return;
            }

            // La plantilla nueva manda desde la próxima fijación, que llega pronto.
            _fixationTimer = Mathf.Min(_fixationTimer, Random.Range(0.3f, 1.2f));
        }

        /// <summary>
        /// Elige el siguiente punto de fijación cuando toca: el visitante o un
        /// desvío dentro de la plantilla. Con una mirada dirigida (caminar, el
        /// panel, el invitado) se fija en ese punto.
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
                // Tras un vistazo se vuelve siempre al visitante.
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

            // La mayoría de las microsacadas vuelven cerca del centro: si no, la
            // mirada deriva y parece que no mira a nadie.
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
        /// Giro (yaw, pitch en grados) de un ojo hacia el objetivo más la
        /// desviación, respecto a su rotación de reposo dentro de la cabeza. El
        /// eje Z local del hueso es hacia delante (así vienen Ready Player Me,
        /// Mixamo, VRM y Genies).
        /// </summary>
        private Vector2 Angles(Transform eye, Quaternion rest, bool hasTarget, Vector3 target, Vector2 offset, float inwardDegrees)
        {
            if (eye == null || eye.parent == null)
            {
                return Vector2.zero;
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

            Quaternion restInverse = Quaternion.Inverse(rest);
            Vector3 inRest = restInverse * desiredLocal;
            float yaw = Mathf.Atan2(inRest.x, inRest.z) * Mathf.Rad2Deg * gazeGain + offset.x + inwardDegrees;
            float pitch = -Mathf.Asin(Mathf.Clamp(inRest.y, -1f, 1f)) * Mathf.Rad2Deg * gazeGain + offset.y;
            return new Vector2(yaw, pitch);
        }

        /// <summary>Lo que hay que restar a los dos ojos para que ninguno pase de ±<paramref name="limit"/>.</summary>
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
