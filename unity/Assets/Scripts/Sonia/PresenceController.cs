// Salida y entrada caminando: el modo "Fuera" del panel del stand.
//
// Con presence present=false Sonia mira hacia un lado, se gira con un fundido
// suave mientras da los primeros pasos y sale caminando de cuadro; al quedar
// fuera aparece el letrero (AwaySignController). Con present=true el letrero se
// va, Sonia entra caminando desde ese mismo lado, frena, se gira hacia la cámara
// y el coreógrafo recupera el cuerpo.
//
// Cómo se evita que los pies patinen: el ciclo de caminar trae root motion
// hacia delante (la Walk oficial de Genies). Mientras camina se enciende
// applyRootMotion, se lee Animator.deltaPosition cada frame y Sonia se desplaza
// exactamente lo que ese avance recorre a lo ancho de la pantalla (su
// proyección sobre el eje lateral de la cámara). Lo que el clip avanza hacia o
// desde la cámara se descarta: Sonia nunca se sale de su línea, y ese
// deslizamiento en profundidad es invisible desde el frente. Como la
// proyección depende de hacia dónde mira, al girar el avance lateral crece solo
// (seno del giro) y la arrancada sale natural. Para frenar justo en su sitio se
// sustituye el root motion por una curva de Hermite que parte de la velocidad
// medida y llega parada a la marca: con la velocidad lineal decreciente, igual
// que el fundido del caminar al reposo en ese mismo tiempo, los pasos se van
// acortando a la vez que el desplazamiento.
//
// Si no hay clip de caminar (el set no se ha regenerado) o el clip no trae
// root motion, Sonia se desplaza a una velocidad estimada: desliza, pero nunca
// se rompe ni se queda a medias.
//
// Modo Jean: el invitado lleva su propia presencia (sin letrero, saliendo por
// la izquierda) y Sonia sale sin letrero para dejarle el sitio (HoldForGuest).
// Mientras tanto, los presence del orquestador se apuntan y se aplican al
// soltarla (ReleaseFromGuest): un hello a mitad no la trae de vuelta.
//
// Corre en LateUpdate con orden 10500: después de evaluar la animación y de
// que Unity aplique el root motion (que se pisa), y antes de la mirada
// (AvatarStateController 12000, EyeGazeController 12100) y de Vrm10Instance
// (11000), que así ya ven a Sonia en su sitio de este frame.

using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Lado de la pantalla por el que Sonia sale y vuelve a entrar.</summary>
    public enum ScreenSide
    {
        Left = 0,
        Right = 1
    }

    /// <summary>
    /// Saca a Sonia de pantalla caminando y la trae de vuelta (mensaje
    /// <c>presence</c>). Lo añade SoniaBootstrap por código si la escena no lo trae.
    /// </summary>
    [DefaultExecutionOrder(10500)]
    [DisallowMultipleComponent]
    public class PresenceController : MonoBehaviour
    {
        /// <summary>Texto del letrero si el orquestador no manda otro.</summary>
        public const string DefaultAwayMessage = "Me fui a ver una charla, regreso en un momento";

        private enum Phase
        {
            /// <summary>En su sitio; el coreógrafo manda.</summary>
            Present,

            /// <summary>Acaba de recibir "fuera": vuelve al reposo y mira hacia la salida.</summary>
            Leaving,

            /// <summary>Gira hacia la salida mientras arranca a caminar.</summary>
            TurningOut,

            /// <summary>Camina hacia fuera hasta quedar fuera de cuadro.</summary>
            WalkingOut,

            /// <summary>Fuera de cuadro, oculta, con el letrero puesto.</summary>
            Away,

            /// <summary>Acaba de recibir "vuelve": el letrero se va; sigue fuera un instante.</summary>
            Returning,

            /// <summary>Entra caminando hacia su sitio.</summary>
            WalkingIn,

            /// <summary>Frena hasta su marca y se gira hacia la cámara.</summary>
            Arriving
        }

        /// <summary>
        /// Curva cúbica de Hermite de un valor a otro en un tiempo dado, partiendo
        /// con una velocidad y llegando parada. Con velocidad inicial cero es un
        /// smoothstep; al reiniciarla desde el valor y la velocidad actuales, un
        /// cambio de planes a medias no da tirones.
        /// </summary>
        private struct Hermite
        {
            public float From;
            public float Velocity;
            public float To;
            public float Duration;
            public float Elapsed;
            public bool Active;

            public void Start(float from, float velocity, float to, float duration)
            {
                From = from;
                Velocity = velocity;
                To = to;
                Duration = Mathf.Max(0.01f, duration);
                Elapsed = 0f;
                Active = true;
            }

            public float Step(float deltaTime, out float velocity)
            {
                if (!Active)
                {
                    velocity = 0f;
                    return To;
                }

                Elapsed += deltaTime;
                float s = Mathf.Clamp01(Elapsed / Duration);
                if (s >= 1f)
                {
                    Active = false;
                    velocity = 0f;
                    return To;
                }

                float s2 = s * s;
                float s3 = s2 * s;
                float h00 = (2f * s3) - (3f * s2) + 1f;
                float h10 = s3 - (2f * s2) + s;
                float h01 = (-2f * s3) + (3f * s2);
                float d00 = (6f * s2) - (6f * s);
                float d10 = (3f * s2) - (4f * s) + 1f;
                float d01 = (-6f * s2) + (6f * s);
                velocity = (((d00 * From) + (d01 * To)) / Duration) + (d10 * Velocity);
                return (h00 * From) + (h10 * Duration * Velocity) + (h01 * To);
            }
        }

        [Header("Referencias")]
        [SerializeField]
        [Tooltip("Coreógrafo. Se suspende mientras Sonia sale, está fuera y vuelve. Si está vacío se busca en este objeto o sus hijos.")]
        private AvatarChoreographer choreographer;

        [SerializeField]
        [Tooltip("Reproductor de clips. Vacío: el del coreógrafo.")]
        private MotionPlayer motionPlayer;

        [SerializeField]
        [Tooltip("Animator del avatar: su transform es el que se desplaza. Vacío: el del reproductor.")]
        private Animator animator;

        [SerializeField]
        [Tooltip("Mirada de la cabeza (y de los ojos, que leen el mismo punto). Vacío: se busca en los hijos.")]
        private AvatarStateController stateController;

        [SerializeField]
        [Tooltip("Encuadre de cámara: abre el plano mientras sale y vuelve. Vacío: se busca en los hijos.")]
        private CameraFramingController cameraFraming;

        [SerializeField]
        [Tooltip("Letrero que queda mientras está fuera. Vacío: se busca o se crea en este objeto.")]
        private AwaySignController sign;

        [Header("Recorrido")]
        [SerializeField]
        [Tooltip("Lado de la pantalla por el que sale y por el que vuelve a entrar.")]
        private ScreenSide exitSide = ScreenSide.Right;

        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Segundos entre recibir 'fuera' y empezar a girar: vuelve al reposo, mira hacia la salida (la mirada se adelanta al cuerpo) y la cámara empieza a abrirse.")]
        private float exitDelaySeconds = 0.5f;

        [SerializeField]
        [Range(0.3f, 2f)]
        [Tooltip("Duración de un giro de 90 grados (curva suave de entrada y salida). Los giros mayores tardan algo más.")]
        private float turnSecondsPer90 = 0.75f;

        [SerializeField]
        [Range(0.1f, 1.5f)]
        [Tooltip("Fundido del reposo al ciclo de caminar al arrancar. Coincide con el giro: los primeros pasos se dan girando.")]
        private float walkBlendInSeconds = 0.45f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Punto del ciclo de caminar (0..1) por el que se entra al arrancar. Sirve para elegir con qué pie da el primer paso.")]
        private float walkStartNormalizedTime = 0f;

        [SerializeField]
        [Range(0.3f, 2f)]
        [Tooltip("Segundos de frenada al llegar a su sitio, a la velocidad normal del caminar. Fija también a qué distancia empieza a frenar (velocidad x este tiempo / 2).")]
        private float arriveSeconds = 0.9f;

        [SerializeField]
        [Range(0f, 0.9f)]
        [Tooltip("Fracción de la frenada que pasa antes de empezar a girarse hacia la cámara.")]
        private float arriveTurnDelay = 0.3f;

        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Segundos entre recibir 'vuelve' y empezar a caminar desde fuera: deja que el letrero empiece a irse.")]
        private float entryDelaySeconds = 0.3f;

        [SerializeField]
        [Range(0.05f, 1f)]
        [Tooltip("Fundido al reposo al recibir 'fuera', por si estaba hablando, bailando o señalando.")]
        private float settleFadeSeconds = 0.4f;

        [SerializeField]
        [Range(0.05f, 1f)]
        [Tooltip("Fundido con el que el coreógrafo retoma el estado al volver, si no es el reposo.")]
        private float resumeFadeSeconds = 0.4f;

        [Header("Fuera de cuadro")]
        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Metros que se añaden a los huesos (pelo, grosor de brazos y manos) para decidir que ya no se ve nada de ella.")]
        private float bodyMargin = 0.3f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Metros de más, fuera de cuadro, desde los que empieza a entrar al volver.")]
        private float extraOffscreenDistance = 0.2f;

        [SerializeField]
        [Range(1f, 12f)]
        [Tooltip("Distancia máxima que recorre: red de seguridad si no consigue salir de cuadro.")]
        private float maxWalkDistance = 6f;

        [SerializeField]
        [Range(2f, 30f)]
        [Tooltip("Segundos máximos caminando en un sentido: red de seguridad.")]
        private float maxWalkSeconds = 10f;

        [SerializeField]
        [Tooltip("Apagar los renderers del avatar mientras está fuera (no se ve ni proyecta sombra, y no gasta GPU).")]
        private bool hideRenderersWhenAway = true;

        [Header("Velocidad")]
        [SerializeField]
        [Tooltip("Desplazar a Sonia con el root motion del clip de caminar (los pies no patinan). Apagado: velocidad estimada.")]
        private bool useRootMotion = true;

        [SerializeField]
        [Range(0.3f, 3f)]
        [Tooltip("Velocidad (m/s) si el clip de caminar no trae root motion ni velocidad media útil.")]
        private float fallbackWalkSpeed = 1.3f;

        [SerializeField]
        [Range(0.3f, 3f)]
        [Tooltip("Velocidad (m/s) del respaldo sin clip de caminar: sale deslizándose en reposo.")]
        private float slideSpeed = 1.2f;

        [Header("Mirada")]
        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Peso de la mirada hacia dónde va mientras camina (la cabeza del clip manda el resto).")]
        private float walkLookWeight = 0.5f;

        [SerializeField]
        [Range(0.5f, 10f)]
        [Tooltip("Metros por delante a los que mira mientras camina.")]
        private float lookAheadDistance = 4f;

        [SerializeField]
        [Range(0f, 1.5f)]
        [Tooltip("Metros por debajo de los ojos del punto al que mira al caminar (se mira un poco al suelo por delante).")]
        private float lookAheadDrop = 0.3f;

        [SerializeField]
        [Range(0f, 3f)]
        [Tooltip("Al volver, metros que le quedan hasta su sitio cuando vuelve a mirar al visitante (con un parpadeo). La mirada se adelanta al giro del cuerpo.")]
        private float lookBackDistance = 0.9f;

        [Header("Letrero")]
        [SerializeField]
        [Tooltip("Texto del letrero si el orquestador no manda ninguno.")]
        private string defaultMessage = DefaultAwayMessage;

        [SerializeField]
        [Tooltip("Poner el letrero al quedar fuera. El invitado del Modo Jean no lleva (y así no se crea otro en el HUD).")]
        private bool useSign = true;

        [Header("Registro")]
        [SerializeField]
        [Tooltip("Escribir en la consola cada paso de la salida y la entrada.")]
        private bool logEvents = true;

        private const float EdgeMargin = 0.02f;
        private const float VelocitySmoothing = 0.3f;

        private bool _initialized;
        private Phase _phase = Phase.Present;
        private bool _targetPresent = true;

        // Modo Jean: Sonia está fuera por el invitado. Lo que pida el orquestador
        // entretanto se apunta aquí y se aplica al soltarla.
        private bool _guestHold;
        private bool _heldPresent = true;
        private float _phaseTime;
        private string _message;

        private Transform _avatar;
        private Transform _head;
        private Transform[] _probeBones = new Transform[0];
        private Renderer[] _renderers = new Renderer[0];
        private bool[] _rendererStates = new bool[0];
        private bool _hidden;
        private Vector3 _restLocalPosition;
        private Quaternion _restLocalRotation = Quaternion.identity;
        // Padre del avatar cuando se tomó su sitio: los avatares que llegan
        // después bajo el mismo padre van a ese sitio (ver Initialize).
        private Transform _restParent;
        private bool _hasRest;

        // Eje lateral (mundo, horizontal) hacia el lado de salida, y dirección
        // horizontal hacia la cámara, que es hacia donde mira Sonia en reposo.
        private Vector3 _sideAxis = Vector3.right;
        private Vector3 _restFacing = Vector3.back;
        private float _yawExit = -90f;
        private float _yawHome = 90f;

        // Cinemática: desplazamiento sobre el eje lateral (0 = su sitio,
        // positivo hacia la salida) y giro respecto a la pose de reposo.
        private float _offset;
        private float _previousOffset;
        private float _lateralVelocity;
        private float _yaw;
        private float _yawVelocity;
        private Hermite _turn;
        private Hermite _arrive;
        private bool _arriveTurnStarted;
        private bool _lookedBack;

        // Peso del caminar según los fundidos que se han pedido (para la
        // velocidad estimada; con root motion lo da el propio Animator).
        private float _walkWeight;
        private float _walkWeightTarget;
        private float _walkWeightRate = float.PositiveInfinity;

        private MotionPlayer.Handle _body;
        private bool _wantsWide;
        private float _clipSpeed;
        private bool _useEstimate;
        private float _probeEstimated;
        private float _probeMeasured;
        private readonly List<ShotPose> _poses = new List<ShotPose>();

        // ------------------------------------------------------------------
        // Estado público
        // ------------------------------------------------------------------

        /// <summary>Cierto con Sonia en su sitio y el coreógrafo al mando.</summary>
        public bool IsPresent
        {
            get { return _phase == Phase.Present; }
        }

        /// <summary>Lo último que pidió el orquestador: cierto si quiere a Sonia en pantalla.</summary>
        public bool TargetPresent
        {
            get { return _targetPresent; }
        }

        /// <summary>Cierto con Sonia ya fuera de cuadro (letrero puesto).</summary>
        public bool IsAway
        {
            get { return _phase == Phase.Away; }
        }

        /// <summary>Fase actual, para depuración y para las pruebas en el editor.</summary>
        public string PhaseName
        {
            get { return _phase.ToString(); }
        }

        /// <summary>Metros que está apartada de su sitio, hacia el lado de salida.</summary>
        public float Offset
        {
            get { return _offset; }
        }

        /// <summary>Cierto mientras la cámara debe estar en el plano de salida (cuerpo entero).</summary>
        public bool WantsWideShot
        {
            get { return _wantsWide; }
        }

        /// <summary>Texto actual del letrero.</summary>
        public string Message
        {
            get { return string.IsNullOrEmpty(_message) ? defaultMessage : _message; }
        }

        /// <summary>Letrero en uso (lo crea este componente si no hay ninguno y lleva letrero).</summary>
        public AwaySignController Sign
        {
            get { return sign; }
        }

        /// <summary>Cierto mientras el Modo Jean tiene a Sonia fuera (o saliendo, o volviendo).</summary>
        public bool HeldByGuest
        {
            get { return _guestHold; }
        }

        private AnimationClip WalkClip
        {
            get
            {
                SoniaMotionSet set = choreographer != null ? choreographer.MotionSet : null;
                return set != null ? set.walk : null;
            }
        }

        private AnimationClip IdleClip
        {
            get
            {
                SoniaMotionSet set = choreographer != null ? choreographer.MotionSet : null;
                return set != null ? set.idleLoop : null;
            }
        }

        private bool PlayerReady
        {
            get { return motionPlayer != null && motionPlayer.IsReady; }
        }

        // ------------------------------------------------------------------
        // Ciclo de vida
        // ------------------------------------------------------------------

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

            if (cameraFraming == null)
            {
                cameraFraming = GetComponentInChildren<CameraFramingController>(true);
            }

            if (sign == null && useSign)
            {
                sign = GetComponentInChildren<AwaySignController>(true);
            }

            if (sign == null && useSign)
            {
                sign = gameObject.AddComponent<AwaySignController>();
            }

            _message = defaultMessage;
        }

        private void Start()
        {
            Initialize();
        }

        /// <summary>
        /// Primer paso de un cambio de avatar: el actual vuelve a su pose de
        /// reposo (para que el nuevo la copie) sin olvidar si Sonia debe estar
        /// fuera. Después hay que llamar a <see cref="Rebind"/>.
        /// </summary>
        public void ReleaseAvatar()
        {
            if (_initialized && _avatar != null && _phase != Phase.Present)
            {
                bool target = _targetPresent;
                Settle("cambio de avatar");
                _targetPresent = target;
            }
        }

        /// <summary>
        /// Segundo paso de un cambio de avatar: toma el reposo del nuevo y, si
        /// Sonia estaba fuera, lo saca al instante (sin animación, con letrero).
        /// </summary>
        public void Rebind(Animator newAnimator)
        {
            bool away = !_targetPresent;
            animator = newAnimator;
            _initialized = false;
            Initialize();
            if (away)
            {
                // Sigue fuera sin animación (y sin tocar el letrero ni su texto).
                _targetPresent = false;
                GoAway(true);
            }
        }

        /// <summary>
        /// Toma la pose de reposo del avatar y la geometría de la salida. Se
        /// llama sola en Start (con Sonia en su sitio); antes, si llega un
        /// <c>presence</c> muy pronto.
        /// </summary>
        private void Initialize()
        {
            if (_initialized)
            {
                return;
            }

            _initialized = true;
            if (motionPlayer == null && choreographer != null)
            {
                motionPlayer = choreographer.Player;
            }

            if (motionPlayer == null)
            {
                motionPlayer = GetComponentInChildren<MotionPlayer>(true);
            }

            if (animator == null && motionPlayer != null)
            {
                animator = motionPlayer.Animator;
            }

            if (animator == null)
            {
                animator = GetComponentInChildren<Animator>(true);
            }

            if (animator == null)
            {
                Debug.LogWarning("[Sonia] Presencia sin Animator: el modo Fuera solo pondrá el letrero.", this);
                return;
            }

            _avatar = animator.transform;
            if (_hasRest && _avatar.parent == _restParent)
            {
                // Cambio de avatar: su sitio es el de siempre, no donde lo dejó el
                // anterior. Si el anterior estaba fuera de cuadro, el nuevo copiaba
                // esa posición como reposo y, al volver, se paraba fuera de cámara.
                _avatar.localPosition = _restLocalPosition;
                _avatar.localRotation = _restLocalRotation;
            }
            else
            {
                _restLocalPosition = _avatar.localPosition;
                _restLocalRotation = _avatar.localRotation;
                _restParent = _avatar.parent;
                _hasRest = true;
            }

            Camera view = ViewCamera();
            Vector3 cameraRight = view != null ? view.transform.right : Vector3.right;
            cameraRight.y = 0f;
            if (cameraRight.sqrMagnitude < 0.0001f)
            {
                cameraRight = Vector3.right;
            }

            cameraRight.Normalize();
            _sideAxis = exitSide == ScreenSide.Right ? cameraRight : -cameraRight;

            // En reposo Sonia mira a la cámara (lo da por hecho todo el montaje).
            Vector3 toCamera = view != null ? view.transform.position - _avatar.position : -_avatar.forward;
            toCamera.y = 0f;
            if (toCamera.sqrMagnitude < 0.0001f)
            {
                toCamera = Vector3.Cross(cameraRight, Vector3.up);
            }

            _restFacing = toCamera.normalized;
            _yawExit = Vector3.SignedAngle(_restFacing, _sideAxis, Vector3.up);
            _yawHome = Vector3.SignedAngle(_restFacing, -_sideAxis, Vector3.up);

            if (animator.isHuman)
            {
                _head = animator.GetBoneTransform(HumanBodyBones.Head);
                HumanBodyBones[] probes =
                {
                    HumanBodyBones.Head, HumanBodyBones.Hips, HumanBodyBones.Chest,
                    HumanBodyBones.LeftHand, HumanBodyBones.RightHand,
                    HumanBodyBones.LeftLowerArm, HumanBodyBones.RightLowerArm,
                    HumanBodyBones.LeftFoot, HumanBodyBones.RightFoot,
                    HumanBodyBones.LeftToes, HumanBodyBones.RightToes
                };
                List<Transform> found = new List<Transform>();
                for (int i = 0; i < probes.Length; i++)
                {
                    Transform bone = animator.GetBoneTransform(probes[i]);
                    if (bone != null)
                    {
                        found.Add(bone);
                    }
                }

                _probeBones = found.ToArray();
            }

            if (_probeBones.Length == 0)
            {
                _probeBones = new[] { _avatar };
            }

            // Si estaba oculta (fuera) con el avatar anterior, se le devuelve la
            // visibilidad antes de cambiar de renderers. Si no, el nuevo heredaba
            // _hidden sin haber guardado sus estados y, al volver, se le apagaban
            // todos: Sonia volvía a su sitio invisible (avatar cambiado estando Fuera).
            SetHidden(false);
            _renderers = _avatar.GetComponentsInChildren<Renderer>(true);
            _rendererStates = new bool[_renderers.Length];

            // Velocidad media del clip, como respaldo si no llega root motion.
            AnimationClip walk = WalkClip;
            if (walk != null)
            {
                Vector3 average = walk.averageSpeed;
                float speed = new Vector2(average.x, average.z).magnitude * (animator.isHuman ? animator.humanScale : 1f);
                _clipSpeed = speed >= 0.3f && speed <= 3f ? speed : 0f;
            }
        }

        private void OnDisable()
        {
            // Si el componente se apaga a medias volviendo, Sonia termina en su
            // sitio. Si debía estar fuera, se queda como está (oculta o saliendo):
            // antes volvía siempre a su sitio, y una recarga de scripts en Play
            // (que apaga y enciende todos los componentes) plantaba al invitado
            // del Modo Jean, que está fuera casi siempre, al lado de Sonia.
            if (_initialized && _avatar != null && _phase != Phase.Present && _targetPresent)
            {
                Settle("componente desactivado");
            }
        }

        // ------------------------------------------------------------------
        // Entrada
        // ------------------------------------------------------------------

        /// <summary>
        /// Aplica el mensaje <c>presence</c>. Con el mismo <paramref name="present"/>
        /// que ya tenía solo cambia el texto del letrero. Con
        /// <paramref name="instant"/> (nada más conectar) se aplica sin animación.
        /// Un cambio de planes a medias (vuelve mientras sale, o se va mientras
        /// entra) se encadena desde donde está, sin saltos.
        /// </summary>
        public void SetPresent(bool present, string message, bool instant)
        {
            Initialize();

            if (!string.IsNullOrWhiteSpace(message))
            {
                _message = message.Trim();
            }
            else if (!present)
            {
                _message = defaultMessage;
            }

            if (sign != null)
            {
                sign.SetMessage(Message);
            }

            if (_guestHold)
            {
                // El Modo Jean manda: se aplica al terminar (ReleaseFromGuest).
                _heldPresent = present;
                return;
            }

            if (present == _targetPresent)
            {
                return;
            }

            _targetPresent = present;
            if (present)
            {
                ComeBack(instant);
            }
            else
            {
                GoAway(instant);
            }
        }

        /// <summary>
        /// Dónde estaría un punto del avatar (por ejemplo, su cabeza) con Sonia en
        /// su sitio, aunque ahora esté fuera de cuadro o girada hacia la salida. La
        /// cámara encuadra con esto: si llega un avatar nuevo estando fuera, la
        /// cabeza está a metro y medio de su sitio, y el plano de conversación
        /// salía centrado en el hueco (al volver, Sonia quedaba fuera de cámara).
        /// </summary>
        public Vector3 AtHome(Vector3 worldPoint)
        {
            if (_avatar == null || !_hasRest)
            {
                return worldPoint;
            }

            Transform parent = _avatar.parent;
            Vector3 home = parent != null ? parent.TransformPoint(_restLocalPosition) : _restLocalPosition;
            Quaternion homeRotation = parent != null ? parent.rotation * _restLocalRotation : _restLocalRotation;
            Vector3 local = Quaternion.Inverse(_avatar.rotation) * (worldPoint - _avatar.position);
            return home + (homeRotation * local);
        }

        /// <summary>
        /// Fuera de cuadro y oculto ya, sin animación ni letrero nuevo, pase lo que
        /// haya pasado: red de seguridad del invitado del Modo Jean, que solo se ve
        /// durante el modo. Corrige un avatar que volvió a su sitio, renderers que
        /// alguien volvió a encender y piezas nuevas del avatar que aún no se habían
        /// ocultado. Devuelve cierto si tuvo que corregir algo.
        /// </summary>
        public bool EnsureAway()
        {
            Initialize();
            if (_guestHold)
            {
                return false;
            }

            if (_targetPresent || _phase != Phase.Away)
            {
                _targetPresent = false;
                GoAway(true);
                return true;
            }

            if (!hideRenderersWhenAway || _avatar == null)
            {
                return false;
            }

            bool fixedSomething = false;
            Renderer[] current = _avatar.GetComponentsInChildren<Renderer>(true);
            if (current.Length != _renderers.Length)
            {
                // Piezas que llegaron después de esconderlo: se vuelven a reunir.
                SetHidden(false);
                _renderers = current;
                _rendererStates = new bool[_renderers.Length];
                fixedSomething = true;
            }

            if (!_hidden)
            {
                SetHidden(true);
                return true;
            }

            for (int i = 0; i < _renderers.Length; i++)
            {
                if (_renderers[i] != null && _renderers[i].enabled)
                {
                    _renderers[i].enabled = false;
                    fixedSomething = true;
                }
            }

            return fixedSomething;
        }

        /// <summary>Alterna entre fuera y presente con animación (botón de pruebas).</summary>
        public void TogglePresence()
        {
            SetPresent(!_targetPresent, null, false);
        }

        /// <summary>
        /// Modo Jean: Sonia sale caminando (o al instante) sin letrero para
        /// dejarle el sitio al invitado. Si ya estaba fuera (modo Fuera), se
        /// queda y se quita el letrero. Lo que pida el orquestador mientras tanto
        /// se aplica en <see cref="ReleaseFromGuest"/>.
        /// </summary>
        public void HoldForGuest(bool instant)
        {
            Initialize();
            if (!_guestHold)
            {
                _guestHold = true;
                _heldPresent = _targetPresent;
            }

            if (!_targetPresent)
            {
                if (sign != null && sign.IsShown)
                {
                    sign.Hide(instant);
                }

                return;
            }

            _targetPresent = false;
            GoAway(instant);
            Log("deja el sitio al invitado del Modo Jean");
        }

        /// <summary>
        /// Termina el Modo Jean: Sonia vuelve caminando (o al instante). Si el
        /// orquestador la quería fuera, se queda fuera, ahora con su letrero.
        /// </summary>
        public void ReleaseFromGuest(bool instant)
        {
            if (!_guestHold)
            {
                return;
            }

            _guestHold = false;
            bool present = _heldPresent;
            if (present == _targetPresent)
            {
                if (!present && _phase == Phase.Away)
                {
                    ShowSign(instant);
                }

                return;
            }

            _targetPresent = present;
            if (present)
            {
                ComeBack(instant);
            }
            else
            {
                GoAway(instant);
            }
        }

        private bool CanShowSign
        {
            get { return sign != null && !_guestHold; }
        }

        private void ShowSign(bool instant)
        {
            if (CanShowSign)
            {
                sign.Show(Message, instant);
            }
        }

        private void GoAway(bool instant)
        {
            if (_avatar == null)
            {
                _phase = Phase.Away;
                ShowSign(instant);
                return;
            }

            if (instant)
            {
                GoAwayInstant();
                return;
            }

            switch (_phase)
            {
                case Phase.Present:
                    BeginLeaving();
                    break;
                case Phase.Returning:
                    // Aún no había empezado a entrar: se queda fuera.
                    _phase = Phase.Away;
                    _phaseTime = 0f;
                    ShowSign(false);

                    Log("se queda fuera");
                    break;
                case Phase.WalkingIn:
                case Phase.Arriving:
                    TurnBackOut();
                    break;
            }
        }

        private void ComeBack(bool instant)
        {
            if (_avatar == null)
            {
                _phase = Phase.Present;
                if (sign != null)
                {
                    sign.Hide(instant);
                }

                return;
            }

            if (instant)
            {
                if (sign != null)
                {
                    sign.Hide(true);
                }

                Settle("vuelve sin animación");
                if (cameraFraming != null)
                {
                    cameraFraming.SnapNextFrame();
                }

                return;
            }

            switch (_phase)
            {
                case Phase.Leaving:
                    // Aún no se había movido de su sitio.
                    Settle("se queda: aún no había salido");
                    break;
                case Phase.TurningOut:
                case Phase.WalkingOut:
                    TurnBackIn();
                    break;
                case Phase.Away:
                    BeginReturning();
                    break;
            }
        }

        // ------------------------------------------------------------------
        // Transiciones
        // ------------------------------------------------------------------

        private void BeginLeaving()
        {
            SetPhase(Phase.Leaving);
            _wantsWide = true;
            if (choreographer != null)
            {
                choreographer.Suspend();
            }

            PlayIdle(settleFadeSeconds, true);
            _offset = 0f;
            _previousOffset = 0f;
            _lateralVelocity = 0f;
            _yaw = 0f;
            _yawVelocity = 0f;
            _turn.Active = false;
            _arrive.Active = false;

            // La mirada se adelanta: primero los ojos (con un parpadeo, como en
            // cualquier cambio grande de mirada) y la cabeza, luego el cuerpo.
            if (stateController != null)
            {
                stateController.TriggerBlink();
            }

            Log("se va: mira hacia la salida (" + exitSide + ")");
        }

        private void StartTurnOut()
        {
            SetPhase(Phase.TurningOut);
            StartTurn(_yawExit);
            PlayWalk(walkBlendInSeconds);
            SetRootMotion(true);
            Log("gira y echa a andar" + (WalkClip == null ? " (sin clip de caminar: desliza)" : string.Empty));
        }

        private void TurnBackOut()
        {
            SetPhase(Phase.TurningOut);
            _wantsWide = true;
            _lookedBack = false;
            _arrive.Active = false;
            SetHidden(false);
            StartTurn(_yawExit);
            PlayWalk(0.35f);
            SetRootMotion(true);
            Log("cambio de planes: se da la vuelta y vuelve a salir");
        }

        private void TurnBackIn()
        {
            SetPhase(Phase.WalkingIn);
            _lookedBack = false;
            StartTurn(_yawHome);
            if (!WalkIsPlaying())
            {
                PlayWalk(0.35f);
            }

            SetRootMotion(true);
            Log("cambio de planes: se da la vuelta y regresa");
        }

        private void EnterAway(bool instant)
        {
            SetPhase(Phase.Away);
            SetRootMotion(false);
            PlayIdle(instant ? 0f : 0.2f, false);
            SetHidden(true);
            _wantsWide = true;
            _lateralVelocity = 0f;
            if (stateController != null)
            {
                stateController.ClearLookOverride();
            }

            ShowSign(instant);
            Log("fuera de cuadro (" + _offset.ToString("F2") + " m)" + (CanShowSign ? ": letrero puesto" : ", sin letrero"));
        }

        private void GoAwayInstant()
        {
            if (choreographer != null)
            {
                choreographer.Suspend();
            }

            if (cameraFraming != null)
            {
                cameraFraming.SnapNextFrame();
            }

            _turn.Active = false;
            _arrive.Active = false;
            _yawVelocity = 0f;

            // Fuera de cualquier encuadre ya mismo (se calcula antes de mover).
            float offscreen = ComputeOffscreenOffset() + extraOffscreenDistance;
            _offset = Mathf.Min(offscreen, maxWalkDistance);
            _previousOffset = _offset;
            _yaw = _yawExit;
            ApplyPose();
            EnterAway(true);
            Log("fuera sin animación");
        }

        private void BeginReturning()
        {
            SetPhase(Phase.Returning);
            _wantsWide = true;
            if (sign != null)
            {
                sign.Hide(false);
            }

            Log("vuelve: se retira el letrero");
        }

        private void StartWalkIn()
        {
            float start = Mathf.Max(_offset, ComputeOffscreenOffset() + extraOffscreenDistance);
            _offset = Mathf.Min(start, maxWalkDistance);
            _previousOffset = _offset;
            _yaw = _yawHome;
            _yawVelocity = 0f;
            _turn.Active = false;
            _lookedBack = false;
            ApplyPose();
            SetHidden(false);
            PlayWalk(0f);
            SetRootMotion(true);
            _lateralVelocity = -EstimatedSpeed();
            SetPhase(Phase.WalkingIn);
            Log("entra caminando desde " + _offset.ToString("F2") + " m");
        }

        private void StartArrive()
        {
            float from = _offset;
            float towardHome = -_lateralVelocity;
            float duration = towardHome > 0.25f && from > 0.01f
                ? Mathf.Clamp(2f * from / towardHome, 0.35f, 2.5f)
                : arriveSeconds;

            // Hermite de (sitio actual, velocidad actual) a (su marca, parada):
            // con esta duración es una parábola, velocidad lineal hasta cero.
            _arrive.Start(from, _lateralVelocity, 0f, duration);
            _arriveTurnStarted = false;
            SetPhase(Phase.Arriving);

            // El caminar se funde al reposo en el mismo tiempo que frena.
            PlayIdle(duration, false);
            SetRootMotion(false);

            // La cámara empieza a cerrar mientras llega.
            _wantsWide = false;
            LookBackAtVisitor();
            Log("frena a " + from.ToString("F2") + " m de su sitio en " + duration.ToString("F2") + " s");
        }

        /// <summary>Deja a Sonia en su sitio, de cara, y devuelve el cuerpo al coreógrafo.</summary>
        private void Settle(string why)
        {
            SetPhase(Phase.Present);
            _offset = 0f;
            _previousOffset = 0f;
            _lateralVelocity = 0f;
            _yaw = 0f;
            _yawVelocity = 0f;
            _turn.Active = false;
            _arrive.Active = false;
            _walkWeight = 0f;
            _walkWeightTarget = 0f;
            _wantsWide = false;
            SetRootMotion(false);
            if (_avatar != null)
            {
                _avatar.localPosition = _restLocalPosition;
                _avatar.localRotation = _restLocalRotation;
            }

            SetHidden(false);
            if (sign != null && sign.IsShown)
            {
                sign.Hide(false);
            }

            if (stateController != null)
            {
                stateController.ClearLookOverride();
            }

            if (choreographer != null)
            {
                choreographer.Resume(_body, resumeFadeSeconds);
            }

            _body = null;
            Log(why);
        }

        private void SetPhase(Phase phase)
        {
            _phase = phase;
            _phaseTime = 0f;
        }

        // ------------------------------------------------------------------
        // Bucle
        // ------------------------------------------------------------------

        private void LateUpdate()
        {
            if (!_initialized || _avatar == null || _phase == Phase.Present)
            {
                return;
            }

            float dt = Time.deltaTime;
            if (dt <= 0f)
            {
                return;
            }

            _phaseTime += dt;
            Vector3 rootDelta = ReadRootMotion();
            _walkWeight = float.IsInfinity(_walkWeightRate)
                ? _walkWeightTarget
                : Mathf.MoveTowards(_walkWeight, _walkWeightTarget, _walkWeightRate * dt);
            if (_turn.Active)
            {
                _yaw = _turn.Step(dt, out _yawVelocity);
            }
            else
            {
                _yawVelocity = 0f;
            }

            switch (_phase)
            {
                case Phase.Leaving:
                    if (_phaseTime >= exitDelaySeconds)
                    {
                        StartTurnOut();
                    }

                    break;

                case Phase.TurningOut:
                case Phase.WalkingOut:
                    KeepWalkAlive();
                    _offset += LocomotionStep(rootDelta, dt);
                    if (_phase == Phase.TurningOut && !_turn.Active)
                    {
                        SetPhase(Phase.WalkingOut);
                    }

                    if ((_offset > bodyMargin && IsOutOfFrame()) || _offset >= maxWalkDistance
                        || _phaseTime > maxWalkSeconds)
                    {
                        ApplyPose();
                        EnterAway(false);
                        return;
                    }

                    break;

                case Phase.Away:
                    // Quieta y oculta. Unity no la mueve (root motion apagado).
                    return;

                case Phase.Returning:
                    if (_phaseTime >= entryDelaySeconds)
                    {
                        StartWalkIn();
                    }

                    break;

                case Phase.WalkingIn:
                    KeepWalkAlive();
                    _offset += LocomotionStep(rootDelta, dt);
                    if (!_lookedBack && _offset <= lookBackDistance)
                    {
                        LookBackAtVisitor();
                    }

                    float towardHome = Mathf.Max(0.05f, -_lateralVelocity);
                    if (_offset <= towardHome * arriveSeconds * 0.5f || _phaseTime > maxWalkSeconds)
                    {
                        StartArrive();
                    }

                    break;

                case Phase.Arriving:
                    float unused;
                    _offset = _arrive.Step(dt, out unused);
                    if (!_arriveTurnStarted && _phaseTime >= _arrive.Duration * arriveTurnDelay)
                    {
                        _arriveTurnStarted = true;
                        StartTurn(0f);
                    }

                    if (!_arrive.Active && _arriveTurnStarted && !_turn.Active)
                    {
                        Settle("de vuelta en su sitio");
                        return;
                    }

                    break;
            }

            float velocity = (_offset - _previousOffset) / dt;
            _previousOffset = _offset;
            _lateralVelocity = Mathf.Lerp(_lateralVelocity, velocity, 1f - Mathf.Exp(-dt / VelocitySmoothing));

            ApplyPose();
            UpdateLook();
        }

        /// <summary>Coloca el avatar: su sitio, más el desplazamiento lateral, con el giro aplicado.</summary>
        private void ApplyPose()
        {
            if (_avatar == null)
            {
                return;
            }

            Transform parent = _avatar.parent;
            Vector3 home = parent != null ? parent.TransformPoint(_restLocalPosition) : _restLocalPosition;
            Quaternion homeRotation = parent != null ? parent.rotation * _restLocalRotation : _restLocalRotation;
            _avatar.SetPositionAndRotation(
                home + (_sideAxis * _offset),
                Quaternion.AngleAxis(_yaw, Vector3.up) * homeRotation);
        }

        /// <summary>Gira hasta un ángulo con una curva suave que respeta la velocidad de giro actual.</summary>
        private void StartTurn(float targetYaw)
        {
            float delta = Mathf.Abs(targetYaw - _yaw);
            if (delta < 0.5f && Mathf.Abs(_yawVelocity) < 1f)
            {
                _yaw = targetYaw;
                _yawVelocity = 0f;
                _turn.Active = false;
                return;
            }

            float duration = Mathf.Clamp(turnSecondsPer90 * Mathf.Sqrt(Mathf.Max(delta, 10f) / 90f), 0.25f, 2.5f);
            _turn.Start(_yaw, _yawVelocity, targetYaw, duration);
        }

        private Vector3 CurrentFacing()
        {
            return Quaternion.AngleAxis(_yaw, Vector3.up) * _restFacing;
        }

        // ------------------------------------------------------------------
        // Desplazamiento
        // ------------------------------------------------------------------

        private void SetRootMotion(bool on)
        {
            if (animator == null)
            {
                return;
            }

            animator.applyRootMotion = on && useRootMotion && !_useEstimate && WalkClip != null;
        }

        private Vector3 ReadRootMotion()
        {
            if (animator == null || !animator.applyRootMotion)
            {
                return Vector3.zero;
            }

            return animator.deltaPosition;
        }

        private float EstimatedSpeed()
        {
            if (WalkClip == null)
            {
                return slideSpeed;
            }

            return _clipSpeed > 0f ? _clipSpeed : fallbackWalkSpeed;
        }

        /// <summary>
        /// Metros que avanza este frame a lo ancho de la pantalla (positivo hacia
        /// la salida). Con root motion es la proyección exacta del avance del
        /// clip; si no, la velocidad estimada por el peso del caminar y por
        /// cuánto mira hacia el lado.
        /// </summary>
        private float LocomotionStep(Vector3 rootDelta, float dt)
        {
            float facingAlong = Vector3.Dot(CurrentFacing(), _sideAxis);
            float estimated = EstimatedSpeed() * _walkWeight * facingAlong * dt;
            if (animator == null || !animator.applyRootMotion)
            {
                return estimated;
            }

            // Tope de 3,5 m/s: un pico suelto (vuelta del bucle, fotograma
            // largo) no puede lanzarla de golpe. Caminando normal no se alcanza.
            float maxStep = 3.5f * dt;
            float measured = Mathf.Clamp(Vector3.Dot(rootDelta, _sideAxis), -maxStep, maxStep);

            // Si el clip resulta ser "en el sitio" (sin root motion), se pasa a la
            // velocidad estimada en lugar de quedarse caminando sin avanzar.
            if (_walkWeight > 0.6f && Mathf.Abs(facingAlong) > 0.7f)
            {
                Vector3 flat = rootDelta;
                flat.y = 0f;
                _probeEstimated += Mathf.Abs(estimated);
                _probeMeasured += flat.magnitude;
                if (_probeEstimated > 0.6f)
                {
                    if (_probeMeasured < 0.15f * _probeEstimated)
                    {
                        _useEstimate = true;
                        animator.applyRootMotion = false;
                        Debug.LogWarning(
                            "[Sonia] El clip de caminar no trae root motion (¿importado 'en el sitio' o con la "
                            + "traslación XZ dentro de la pose?). Se usa una velocidad estimada y los pies pueden "
                            + "patinar. Revisa la importación con Sonia > Crear set de animaciones.",
                            this);
                        return estimated;
                    }

                    _probeEstimated = 0f;
                    _probeMeasured = 0f;
                }
            }

            return measured;
        }

        // ------------------------------------------------------------------
        // Clips
        // ------------------------------------------------------------------

        private void PlayWalk(float fade)
        {
            _walkWeightTarget = 1f;
            _walkWeightRate = fade > 0.0001f ? 1f / fade : float.PositiveInfinity;
            AnimationClip walk = WalkClip;
            if (walk == null || !PlayerReady)
            {
                return;
            }

            float start = walk.length * Mathf.Clamp01(walkStartNormalizedTime);
            _body = motionPlayer.Play(walk, MotionPlayer.BodyLayer, fade, 1f, start);
        }

        private void PlayIdle(float fade, bool onlyIfNeeded)
        {
            _walkWeightTarget = 0f;
            _walkWeightRate = fade > 0.0001f ? 1f / fade : float.PositiveInfinity;
            AnimationClip idle = IdleClip;
            if (idle == null || !PlayerReady)
            {
                return;
            }

            if (onlyIfNeeded && motionPlayer.CurrentClip(MotionPlayer.BodyLayer) == idle)
            {
                return;
            }

            float start = idle.isLooping ? Random.Range(0f, Mathf.Max(0f, idle.length - 0.5f)) : 0f;
            _body = motionPlayer.Play(idle, MotionPlayer.BodyLayer, fade, 1f, start);
        }

        private bool WalkIsPlaying()
        {
            AnimationClip walk = WalkClip;
            return walk != null && _body != null && _body.IsCurrent && _body.Clip == walk;
        }

        /// <summary>
        /// Mantiene el ciclo de caminar mientras camina: si el clip no está en
        /// bucle (set sin regenerar) o alguien pisó la capa, se relanza.
        /// </summary>
        private void KeepWalkAlive()
        {
            AnimationClip walk = WalkClip;
            if (walk == null || !PlayerReady)
            {
                return;
            }

            if (_body == null || !_body.IsCurrent || _body.Clip != walk || _body.IsDone)
            {
                _body = motionPlayer.Play(walk, MotionPlayer.BodyLayer, 0.25f, 1f, 0f);
            }
        }

        // ------------------------------------------------------------------
        // Mirada
        // ------------------------------------------------------------------

        private void UpdateLook()
        {
            if (stateController == null || _head == null)
            {
                return;
            }

            switch (_phase)
            {
                case Phase.Leaving:
                    LookAlong(_sideAxis, -1f);
                    break;
                case Phase.TurningOut:
                case Phase.WalkingOut:
                    LookAlong(_sideAxis, walkLookWeight);
                    break;
                case Phase.WalkingIn:
                    if (!_lookedBack)
                    {
                        LookAlong(-_sideAxis, walkLookWeight);
                    }

                    break;
            }
        }

        private void LookAlong(Vector3 direction, float weight)
        {
            Vector3 target = _head.position + (direction * lookAheadDistance) + (Vector3.down * lookAheadDrop);
            stateController.SetLookOverride(target, weight);
        }

        private void LookBackAtVisitor()
        {
            if (_lookedBack)
            {
                return;
            }

            _lookedBack = true;
            if (stateController != null)
            {
                stateController.ClearLookOverride();
                stateController.TriggerBlink();
            }
        }

        // ------------------------------------------------------------------
        // Fuera de cuadro
        // ------------------------------------------------------------------

        private Camera ViewCamera()
        {
            if (cameraFraming != null && cameraFraming.TargetCamera != null)
            {
                return cameraFraming.TargetCamera;
            }

            return Camera.main;
        }

        private void CollectPoses()
        {
            _poses.Clear();
            Camera view = ViewCamera();
            if (view != null)
            {
                _poses.Add(new ShotPose(view.transform.position, view.transform.rotation, view.fieldOfView));
            }

            if (cameraFraming != null)
            {
                cameraFraming.CollectShotPoses(_poses);
            }
        }

        private float ViewAspect()
        {
            Camera view = ViewCamera();
            return view != null && view.aspect > 0.01f ? view.aspect : 9f / 16f;
        }

        /// <summary>
        /// Coordenada horizontal normalizada (-1..1 dentro de cuadro) de un punto,
        /// con signo hacia el lado de salida: más de 1 es fuera por ese lado.
        /// </summary>
        private float SideCoordinate(ShotPose pose, float aspect, Vector3 point)
        {
            Vector3 local = Quaternion.Inverse(pose.Rotation) * (point - pose.Position);
            if (local.z <= 0.01f)
            {
                return float.PositiveInfinity;
            }

            float halfWidth = local.z * Mathf.Tan(pose.FieldOfView * 0.5f * Mathf.Deg2Rad) * aspect;
            float x = local.x / Mathf.Max(0.0001f, halfWidth);
            return Vector3.Dot(_sideAxis, pose.Rotation * Vector3.right) >= 0f ? x : -x;
        }

        /// <summary>
        /// Cierto cuando ningún hueso (más el margen del cuerpo) se ve en ninguno
        /// de los encuadres posibles: así no reaparece si la cámara aún se está
        /// abriendo.
        /// </summary>
        private bool IsOutOfFrame()
        {
            CollectPoses();
            if (_poses.Count == 0)
            {
                return _offset > 2f;
            }

            float aspect = ViewAspect();
            for (int b = 0; b < _probeBones.Length; b++)
            {
                if (_probeBones[b] == null)
                {
                    continue;
                }

                Vector3 inner = _probeBones[b].position - (_sideAxis * bodyMargin);
                for (int p = 0; p < _poses.Count; p++)
                {
                    if (SideCoordinate(_poses[p], aspect, inner) <= 1f + EdgeMargin)
                    {
                        return false;
                    }
                }
            }

            return true;
        }

        /// <summary>Desplazamiento mínimo desde su sitio para no verse en ningún encuadre.</summary>
        private float ComputeOffscreenOffset()
        {
            CollectPoses();
            if (_poses.Count == 0)
            {
                return 2f;
            }

            float aspect = ViewAspect();
            float required = 0f;
            for (int b = 0; b < _probeBones.Length; b++)
            {
                if (_probeBones[b] == null)
                {
                    continue;
                }

                // Posición del hueso con Sonia en su sitio, ya con el margen.
                Vector3 inner = _probeBones[b].position - (_sideAxis * (_offset + bodyMargin));
                for (int p = 0; p < _poses.Count; p++)
                {
                    if (SideCoordinate(_poses[p], aspect, inner) > 1f + EdgeMargin)
                    {
                        continue;
                    }

                    float low = 0f;
                    float high = maxWalkDistance;
                    for (int i = 0; i < 24; i++)
                    {
                        float mid = (low + high) * 0.5f;
                        if (SideCoordinate(_poses[p], aspect, inner + (_sideAxis * mid)) > 1f + EdgeMargin)
                        {
                            high = mid;
                        }
                        else
                        {
                            low = mid;
                        }
                    }

                    required = Mathf.Max(required, high);
                }
            }

            return required;
        }

        private void SetHidden(bool hidden)
        {
            if (hidden && !hideRenderersWhenAway)
            {
                return;
            }

            if (hidden == _hidden)
            {
                return;
            }

            _hidden = hidden;
            for (int i = 0; i < _renderers.Length; i++)
            {
                Renderer renderer = _renderers[i];
                if (renderer == null)
                {
                    continue;
                }

                if (hidden)
                {
                    _rendererStates[i] = renderer.enabled;
                    renderer.enabled = false;
                }
                else
                {
                    renderer.enabled = _rendererStates[i];
                }
            }
        }

        private void Log(string message)
        {
            if (logEvents)
            {
                Debug.Log("[Sonia] Presencia: " + message, this);
            }
        }
    }
}
