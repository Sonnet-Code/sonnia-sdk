// Gorro de la trivia: la gorra Noogler con hélice (gajo amarillo delante y el
// texto «Noogler»), que Sonia se pone y se quita con las dos manos.
//
// El modelo es el «HAT - Propeller Silly Hat» de Dekogon, recoloreado y con el
// texto en Blender (scripts/gorro_noogler), y lo monta "Sonia > Crear gorro
// Noogler" como prefab en Resources (TriviaCapRig). Va donde iría una gorra
// oficial de Genies: su sitio en la cabeza se midió encajándolo (ICP) con la
// gorra oficial que llevaba Sonia, en el espacio del hueso de la cabeza, como
// va pegada esa gorra. Y se integra como una prenda oficial:
//  - mientras lo lleva se esconde la gorra oficial, si Sonia lleva una. Genies
//    (NAF) junta cuerpo, pelo, ropa y gorro en un solo renderer con una submalla
//    por material, así que se apaga solo la submalla del gorro (FindHatParts),
//    con un material sin pasadas de render;
//  - el pelo se aplasta bajo el gorro como bajo una gorra de Genies, con el
//    pelo que lleve. NAF solo lo aplasta con una gorra oficial puesta (y lo
//    hornea en la malla), así que GeniesHatHair saca esa forma de una gemela
//    del avatar con la gorra oficial con la que se encajó este gorro (HatHair),
//    y aquí el pelo pasa a ella según encaja el gorro y vuelve al quitárselo.
//    Si Sonia ya lleva una gorra oficial, su pelo ya va aplastado y el gorro
//    Noogler va justo donde iba ella. Si el avatar trae los blendshapes de pelo
//    bajo gorro («hair_geo_blendShape...hat», como el doble del editor), se
//    activan mientras lo lleva;
//  - ya puesto no se bambolea (las prendas de Genies van rígidas con la cabeza);
//  - la hélice gira, y más deprisa al acertar o ganar.
// Sin el prefab queda el gorro de fiesta procedural de antes (cono de franjas).
//
// Ponérselo (una línea de tiempo de 2 s; quitárselo es la misma al revés):
//   0,00-0,45  se inclina hacia delante y las manos bajan a por el gorro, que
//              espera abajo, delante de los muslos: se inclina lo justo para
//              que la cámara no lo vea, así que nunca aparece de la nada;
//   0,45-0,60  lo cogen por los costados de la copa;
//   0,60-1,30  se endereza y lo sube en arco, separado del pecho, hasta su
//              sitio en la cabeza (si hay que aplastar el pelo, hasta unos
//              centímetros por encima);
//   1,30-1,45  lo encajan: baja recto hasta su sitio mientras el pelo se aplasta
//              debajo (la copa tapa la coronilla antes de que el pelo se recoja
//              y no lo atraviesa), con un apretón al final;
//   1,45-2,00  las manos sueltan y vuelven a lo que hacía la animación.
// Quitárselo es lo mismo hacia atrás: lo levanta recto, lo baja en arco, se
// inclina y lo deja abajo, fuera de cuadro. Si se pide lo contrario a medias,
// la línea de tiempo da la vuelta desde donde está. Las palmas se apoyan por
// fuera de la copa (puntos de agarre de TriviaCapRig) con los dedos a lo largo
// de la tela, sin atravesarla.
//
// Genies no trae ninguna animación de ponerse un gorro, así que los brazos van
// con IK de dos huesos (hombro, codo, muñeca) encima de lo que suene, como el
// apretón de manos del Modo Jean (HandshakeRig), y para inclinarse se dobla la
// columna (Spine, Chest y UpperChest) sobre la pose animada. Corre en
// LateUpdate al final de todo (12600: después de la cabeza, los ojos y la
// cara), así que el gorro sigue a la cabeza ya girada y los brazos no se
// pelean con nadie.
//
// Solo se pone en Sonia (nunca en el invitado del Modo Jean) y se esconde si
// Sonia sale de cuadro.

using UnityEngine;

namespace Sonia
{
    /// <summary>Gorro de fiesta procedural que Sonia se pone y se quita con las manos.</summary>
    [DefaultExecutionOrder(12600)]
    [DisallowMultipleComponent]
    public class TriviaHat : MonoBehaviour
    {
        [Header("Modelo")]
        [SerializeField]
        [Tooltip("Prefab del gorro en Resources (lo monta Sonia > Crear gorro Noogler). Vacío o sin prefab: el gorro de fiesta procedural.")]
        private string capResource = "Trivia/NooglerCap";

        [Header("Colocación aproximada del modelo (si el prefab no trae el encaje medido)")]
        [SerializeField]
        [Tooltip("Centro de la boca del gorro respecto al hueso de la cabeza, en metros: derecha (x), arriba (y) y delante (z) del avatar.")]
        private Vector3 fitOffset = new Vector3(0f, 0.12f, 0.02f);

        [SerializeField]
        [Tooltip("Giro del gorro respecto a la cabeza, en grados: cabeceo (x, positivo hacia delante), guiñada (y) y alabeo (z).")]
        private Vector3 fitEuler = Vector3.zero;

        [SerializeField]
        [Tooltip("Escala del modelo (a tamaño real) en la cabeza de Sonia.")]
        private float fitScale = 1.3f;

        [Header("Integración con el avatar")]
        [SerializeField]
        [Tooltip("Esconder la gorra oficial de Genies (la submalla del gorro) mientras Sonia lleva este.")]
        private bool hideOfficialHat = true;

        [SerializeField]
        [Tooltip("Prefijo de los blendshapes del pelo que Genies usa bajo los gorros (modo blendshape): los que siguen con «hat» se activan mientras lo lleva puesto.")]
        private string hatHairBlendShape = "hair_geo_blendShape";

        [SerializeField]
        [Tooltip("Grados por segundo de la hélice.")]
        private float propellerSpeed = 600f;

        [Header("Colocación del gorro procedural (en la cabeza)")]
        [SerializeField]
        [Tooltip("Altura de la base del gorro sobre el hueso de la cabeza, en metros, a lo largo del 'arriba' del avatar.")]
        private float height = 0.235f;

        [SerializeField]
        [Tooltip("Desplazamiento hacia delante (positivo) o atrás, en metros.")]
        private float forward = -0.015f;

        [SerializeField]
        [Tooltip("Desplazamiento lateral, en metros (positivo hacia la derecha de Sonia).")]
        private float side = 0.008f;

        [SerializeField]
        [Range(-40f, 40f)]
        [Tooltip("Inclinación lateral en grados: ladeado queda más festivo.")]
        private float tilt = 9f;

        [SerializeField]
        [Range(-30f, 30f)]
        [Tooltip("Inclinación hacia delante (positivo) o atrás, en grados.")]
        private float pitch = -8f;

        [Header("Forma")]
        [SerializeField]
        [Tooltip("Radio de la base del cono, en metros.")]
        private float radius = 0.08f;

        [SerializeField]
        [Tooltip("Altura del cono, en metros.")]
        private float coneHeight = 0.205f;

        [SerializeField]
        [Tooltip("Radio del pompón, en metros.")]
        private float pompomRadius = 0.027f;

        [Header("Manos")]
        [SerializeField]
        [Tooltip("Ponérselo y quitárselo con las manos. Apagado: el gorro aparece y desaparece en su sitio.")]
        private bool useHands = true;

        [SerializeField]
        [Range(0.5f, 2f)]
        [Tooltip("Velocidad de la secuencia (1 = 2 s).")]
        private float speed = 1f;

        [SerializeField]
        [Range(0f, 60f)]
        [Tooltip("Cuánto se inclina hacia delante, como mínimo, para coger y dejar el gorro abajo, en grados. Se inclina más si con esto la cámara vería el gorro.")]
        private float minBow = 20f;

        [SerializeField]
        [Range(0f, 90f)]
        [Tooltip("Cuánto se inclina, como mucho, para que la cámara no vea el gorro abajo, en grados. Con el encuadre de medio muslo hace falta casi doblarse del todo: Sonnia es bajita y la cámara de conversación ve hasta las rodillas.")]
        private float maxBow = 88f;

        [SerializeField]
        [Range(0f, 0.3f)]
        [Tooltip("Cuánto sube el arco del gorro por encima de la recta al llevarlo a la cabeza, en metros.")]
        private float carryArc = 0.08f;

        [SerializeField]
        [Range(0f, 0.3f)]
        [Tooltip("Cuánto se separa del cuerpo al subirlo, en metros (para que no roce el pecho).")]
        private float carryForward = 0.1f;

        [SerializeField]
        [Range(0f, 0.12f)]
        [Tooltip("Si el pelo se aplasta bajo el gorro (HatHair), el gorro llega esto por encima de su sitio y baja recto mientras el pelo se aplasta debajo, en metros.")]
        private float hoverHeight = 0.05f;

        [SerializeField]
        [Range(0f, 0.06f)]
        [Tooltip("Separación de la muñeca de la tela al cogerlo, en metros (el grosor de la mano).")]
        private float gripGap = 0.02f;

        [SerializeField]
        [Range(0f, 60f)]
        [Tooltip("Dedos algo cerrados, siguiendo la copa, en grados.")]
        private float fingerCurl = 12f;

        [Header("Animación")]
        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("Grados del bamboleo del gorro al moverse la cabeza.")]
        private float wobble = 4f;

        // Línea de tiempo (segundos con speed = 1).
        private const float ReachEnd = 0.45f;
        private const float GrabEnd = 0.6f;
        private const float CarryEnd = 1.3f;
        private const float PressEnd = 1.45f;
        private const float Total = 2f;

        // Se endereza en este rato después de coger el gorro (con speed = 1).
        private const float StraightenSeconds = 0.45f;

        // Grados por segundo a los que puede cambiar la inclinación que busca.
        private const float BowRate = 120f;

        // Dónde coge el gorro respecto a los hombros inclinados, en largos de brazo:
        // casi colgando (más lejos de la cámara y más abajo que con los brazos por delante).
        private const float PickupForward = 0.15f;
        private const float PickupDrop = 0.95f;

        // Margen de cuadro para dar el gorro por visto (en coordenadas de -1 a 1).
        private const float FrameMargin = 0.06f;

        // Parte de la inclinación que se hace por la cadera (el resto, en la columna). En
        // los avatares de Genies Spine, Chest y UpperChest están altos: doblándose solo
        // por ahí los hombros apenas bajaban (88° y las manos a 0,52 m del suelo).
        private const float HipShare = 0.65f;

        // Reparto de la inclinación entre Spine, Chest y UpperChest.
        private static readonly float[] BowShares = { 0.45f, 0.35f, 0.2f };

        private static readonly Color Blue = new Color(0.259f, 0.522f, 0.957f);
        private static readonly Color Red = new Color(0.918f, 0.263f, 0.208f);
        private static readonly Color Yellow = new Color(0.984f, 0.737f, 0.02f);
        private static readonly Color Green = new Color(0.204f, 0.659f, 0.325f);

        private AvatarBinder _binder;
        private PresenceController _presence;
        private Transform _head;
        private Transform _avatar;
        private Vector3 _headLocalPosition;
        private Quaternion _headLocalRotation = Quaternion.identity;
        private Vector3 _pickupLocal;
        private bool _pickupSet;
        private float _bow;
        // Esquinas del gorro respecto a su punto de agarre, medidas con él abajo
        // (con la hélice y la visera): para saber si la cámara lo vería.
        private readonly Vector3[] _capCorners = new Vector3[8];
        private bool _capMeasured;
        private bool _grabLogged;
        private CameraFramingController _framing;
        private readonly Transform[] _spine = new Transform[3];
        private Transform _hips;
        private Transform _leftThigh;
        private Transform _rightThigh;
        private readonly System.Collections.Generic.List<Transform> _dynamicBones = new System.Collections.Generic.List<Transform>();
        private Vector3[] _dynamicPositions = new Vector3[0];
        private Quaternion[] _dynamicRotations = new Quaternion[0];
        private readonly HandArm _right = new HandArm(false);
        private readonly HandArm _left = new HandArm(true);
        private Transform _root;
        private Transform _cone;
        private Transform _model;
        private TriviaCapRig _rig;
        private Quaternion _propellerRest = Quaternion.identity;
        private float _spin;
        private float _spinBoostUntil;
        private readonly System.Collections.Generic.List<HiddenPart> _officialHat = new System.Collections.Generic.List<HiddenPart>();
        private readonly System.Collections.Generic.List<Material> _slots = new System.Collections.Generic.List<Material>();
        private bool _officialHidden;
        private readonly System.Collections.Generic.List<HairShape> _hairShapes = new System.Collections.Generic.List<HairShape>();
        private float _hairWeight = -1f;
        private HatHair.Flat _flatHair;
        private float _flatWeight = -1f;
        private Renderer[] _renderers = new Renderer[0];
        private Material _coneMaterial;
        private Material _trimMaterial;
        private Texture2D _stripes;
        private Mesh _coneMesh;
        private Mesh _ringMesh;
        private bool _wanted;
        private float _time;
        private float _clock;
        private Vector3 _lastHeadPosition;
        private float _sway;
        private float _swayVelocity;

        // Pasadas de URP: un material con todas apagadas no dibuja nada, ni sombra.
        private static readonly string[] RenderPasses =
        {
            "UniversalForward", "UniversalForwardOnly", "UniversalGBuffer", "ShadowCaster", "DepthOnly",
            "DepthNormals", "DepthNormalsOnly", "MotionVectors", "Meta", "Universal2D", "SRPDefaultUnlit"
        };

        /// <summary>Una submalla de gorro del avatar.</summary>
        public struct HatPart
        {
            public SkinnedMeshRenderer Renderer;
            public int SubMesh;
        }

        /// <summary>La submalla de la gorra oficial y su material de verdad mientras está escondida.</summary>
        private struct HiddenPart
        {
            public SkinnedMeshRenderer Renderer;
            public int SubMesh;
            public Material Original;
            public Material Hidden;
        }

        /// <summary>Altura de una submalla respecto al hueso de la cabeza.</summary>
        private struct SubMeshSpan
        {
            public HatPart Part;
            public float Min;
            public float Max;
        }

        private struct HairShape
        {
            public SkinnedMeshRenderer Renderer;
            public int Index;
            public float Original;
            public float Full;
        }

        /// <summary>Cierto si el gorro está puesto o poniéndose.</summary>
        public bool IsOn
        {
            get { return _wanted; }
        }

        /// <summary>Cierto cuando el gorro ya está abajo del todo (quitado) y no se lo quiere poner.</summary>
        public bool IsOff
        {
            get { return !_wanted && _time <= 0f; }
        }

        /// <summary>Cierto mientras las manos están poniendo o quitando el gorro.</summary>
        public bool IsMoving
        {
            get { return _time > 0f && _time < Total; }
        }

        private void Awake()
        {
            _binder = GetComponentInChildren<AvatarBinder>(true);
            _presence = GetComponentInChildren<PresenceController>(true);
        }

        private void OnEnable()
        {
            if (_binder != null)
            {
                _binder.AvatarChanged += HandleAvatarChanged;
            }

            HatHair.Published += HandleHatHairPublished;
        }

        private void OnDisable()
        {
            if (_binder != null)
            {
                _binder.AvatarChanged -= HandleAvatarChanged;
            }

            HatHair.Published -= HandleHatHairPublished;
        }

        private void OnDestroy()
        {
            RestoreAvatar();
            if (_root != null)
            {
                Destroy(_root.gameObject);
            }

            DestroyAsset(_coneMaterial);
            DestroyAsset(_trimMaterial);
            DestroyAsset(_stripes);
            DestroyAsset(_coneMesh);
            DestroyAsset(_ringMesh);
        }

        /// <summary>Se pone el gorro con las manos o se lo quita (<paramref name="instant"/>: de golpe).</summary>
        public void SetOn(bool on, bool instant = false)
        {
            if (!on && _wanted)
            {
                // Al quitárselo, dónde lo deja se busca con la cámara y la pose de ahora.
                _pickupSet = false;
            }

            _wanted = on;
            if (on)
            {
                Attach();
            }

            if (instant || !useHands)
            {
                _time = on ? Total : 0f;
            }
        }

        /// <summary>La hélice gira más deprisa unos segundos (al acertar, al ganar).</summary>
        public void SpinBoost(float seconds = 2.5f)
        {
            _spinBoostUntil = Time.time + Mathf.Max(0f, seconds);
        }

        private void HandleAvatarChanged(Transform avatar)
        {
            // Avatar nuevo (el SDK entregó otro o se cambió el aspecto): el gorro
            // pasa a su cabeza y los brazos a sus huesos.
            RestoreAvatar();
            _head = null;
            if (_wanted || _time > 0f)
            {
                Attach();
            }
        }

        private void HandleHatHairPublished(Transform avatar)
        {
            // Llegó el pelo aplastado de este avatar (tarda unos segundos en salir
            // tras ponerse el avatar): se usa desde ya, aunque el gorro esté puesto.
            if (avatar == null || avatar != _avatar || _head == null || _officialHat.Count > 0)
            {
                return;
            }

            SetFlatHair(0f);
            _flatHair = HatHair.Find(avatar);
            _flatWeight = -1f;
        }

        // ------------------------------------------------------------------
        // Cada frame
        // ------------------------------------------------------------------

        private void LateUpdate()
        {
            if (_root == null)
            {
                return;
            }

            float dt = Time.deltaTime;
            _clock += dt;
            float rate = useHands ? Mathf.Max(0.1f, speed) : Total / 0.4f;
            _time = Mathf.Clamp(_time + ((_wanted ? 1f : -1f) * rate * dt), 0f, Total);

            bool hidden = _presence != null && _presence.IsAway;
            bool visible = _time > 0.001f && !hidden && _head != null && _avatar != null;
            if (_root.gameObject.activeSelf != visible)
            {
                _root.gameObject.SetActive(visible);
            }

            if (!visible)
            {
                ApplyAvatarIntegration(0f, 0f);
                return;
            }

            // Dónde está el gorro abajo y cuánto se inclina para cogerlo o dejarlo
            // (con la pose animada de este frame, antes de doblar la columna).
            float t = useHands ? _time : Total;
            if (t < GrabEnd || !_pickupSet)
            {
                UpdatePickup();
            }

            if (useHands)
            {
                Bow(_bow * BowWeight(t));
            }

            // Bamboleo: el gorro se queda un poco atrás cuando la cabeza se mueve.
            Vector3 velocity = dt > 0f ? (_head.position - _lastHeadPosition) / dt : Vector3.zero;
            _lastHeadPosition = _head.position;
            float target = Mathf.Clamp(-_avatar.InverseTransformDirection(velocity).x * 60f, -wobble, wobble);
            _sway = Mathf.SmoothDamp(_sway, target, ref _swayVelocity, 0.12f);

            // Pose del gorro: abajo fuera de cuadro, entre las manos de camino o en la cabeza.
            Vector3 headPosition = _head.TransformPoint(_headLocalPosition);
            Quaternion headRotation = _head.rotation * _headLocalRotation;

            // Si hay que aplastar el pelo, el gorro llega por encima de su sitio y
            // baja recto, a lo largo de su eje, mientras el pelo se aplasta debajo.
            float lower = Smooth(Mathf.InverseLerp(CarryEnd, PressEnd, t));
            Vector3 hover = headPosition;
            if (_flatHair != null)
            {
                hover += headRotation * Vector3.up * hoverHeight;
            }

            Vector3 pickup = _avatar.TransformPoint(_pickupLocal);
            Quaternion holdRotation = Quaternion.LookRotation(_avatar.forward, _avatar.up) * Quaternion.Euler(-12f, 0f, 0f);
            float carry = Smooth(Mathf.InverseLerp(GrabEnd, CarryEnd, t));
            float bulge = Mathf.Sin(carry * Mathf.PI);
            Vector3 position = Vector3.Lerp(pickup, hover, carry)
                               + (_avatar.up * (bulge * carryArc))
                               + (_avatar.forward * (bulge * carryForward))
                               + ((headPosition - hover) * lower);
            Quaternion rotation = Quaternion.Slerp(holdRotation, headRotation, carry);

            // Con las manos el gorro está siempre a su tamaño (sale de fuera de
            // cuadro); sin ellas aparece en su sitio creciendo. Se aplasta al encajar.
            float scale = useHands ? 1f : Smooth(_time / Total);
            float press = Mathf.InverseLerp(CarryEnd, PressEnd, t);
            float squash = press > 0f && press < 1f ? 1f - (0.12f * Mathf.Sin(press * Mathf.PI)) : 1f;
            float parent = transform.lossyScale.y > 0.0001f ? transform.lossyScale.y : 1f;
            _root.SetPositionAndRotation(useHands ? position : headPosition, useHands ? rotation : headRotation);
            float size = ModelSize();
            _root.localScale = new Vector3(scale / squash, scale * squash, scale / squash) * (size / parent);
            if (useHands && t < ReachEnd)
            {
                MeasureCap(position);
            }

            if (useHands && t >= GrabEnd && !_grabLogged)
            {
                _grabLogged = true;
                Camera cam = Camera.main;
                bool seen = cam != null && SeenByCamera(cam, pickup);
                Debug.Log("[Sonia] Gorro de la trivia: recogida con " + _bow.ToString("F0") + "° de inclinación, a "
                          + _avatar.InverseTransformPoint(pickup).y.ToString("F2") + " m del suelo"
                          + (seen ? " (la cámara lo ve: falta inclinación)" : ", fuera de cuadro") + ".");
            }
            else if (t < GrabEnd)
            {
                _grabLogged = false;
            }
            Transform swayed = _rig != null ? _model : _cone;
            if (swayed != null)
            {
                // El gorro medido va rígido con la cabeza como una prenda de Genies:
                // solo se bambolea mientras viaja entre las manos.
                float loose = _rig != null && _rig.fitted ? 1f - press : 1f;
                swayed.localRotation = Quaternion.Euler(0f, 0f, (_sway + (Mathf.Sin(_clock * 1.7f) * 0.6f)) * loose);
            }

            if (_rig != null && _rig.propeller != null)
            {
                float boost = Time.time < _spinBoostUntil ? 2.2f : 1f;
                _spin = Mathf.Repeat(_spin + (propellerSpeed * boost * dt), 360f);
                // El eje está en el espacio de la propia hélice: el giro va después del reposo.
                _rig.propeller.localRotation = _propellerRest * Quaternion.AngleAxis(_spin, _rig.propellerAxis);
            }

            // Ya en la cabeza: fuera la gorra oficial y el pelo con la forma de bajo
            // el gorro, que se aplasta según baja el gorro y se ahueca al levantarlo.
            ApplyAvatarIntegration(Mathf.InverseLerp(CarryEnd - 0.05f, CarryEnd, t), lower);

            if (!useHands)
            {
                return;
            }

            // Manos: bajan a por el gorro, lo sujetan por los costados mientras viaja y sueltan.
            float reach = Smooth(Mathf.InverseLerp(0f, ReachEnd, t));
            float release = Smooth(Mathf.InverseLerp(PressEnd, Total, t));
            float weight = reach * (1f - release);
            if (weight <= 0.001f)
            {
                return;
            }

            Vector3 up = rotation * Vector3.up;
            Grip(true, position, rotation, size, out Vector3 rightPoint, out Vector3 rightNormal);
            Grip(false, position, rotation, size, out Vector3 leftPoint, out Vector3 leftNormal);
            _right.Hold(rightPoint, rightNormal, up, _avatar, weight, fingerCurl, gripGap);
            _left.Hold(leftPoint, leftNormal, up, _avatar, weight, fingerCurl, gripGap);
        }

        /// <summary>
        /// Dónde coge (o deja) el gorro y cuánto se inclina para llegar: abajo,
        /// delante de los muslos, con los brazos casi estirados desde los hombros
        /// ya inclinados. Prueba de la inclinación mínima a la máxima, de 2,5 en 2,5
        /// grados, hasta que la cámara no vea el gorro. Se recalcula hasta que las
        /// manos lo cogen (la cámara puede estar yendo al plano de la trivia), en el
        /// espacio del avatar; la inclinación nunca cambia de golpe.
        /// </summary>
        private void UpdatePickup()
        {
            Vector3 up = _avatar.up;
            Vector3 forward = _avatar.forward;
            Vector3 shoulders = (_right.ShoulderPosition + _left.ShoulderPosition) * 0.5f;
            float reach = Mathf.Min(_right.Reach, _left.Reach);
            if (reach < 0.1f)
            {
                // Sin brazos de verdad: un poco por delante de la cadera.
                reach = 0.55f;
                shoulders = _head.position - (up * 0.2f);
            }

            Camera cam = Camera.main;
            float bow = Mathf.Min(minBow, maxBow);
            Vector3 point = shoulders;
            while (true)
            {
                point = BentShoulders(shoulders, bow) + (forward * (reach * PickupForward)) - (up * (reach * PickupDrop));
                if (bow >= maxBow || cam == null || !SeenByCamera(cam, point))
                {
                    break;
                }

                bow = Mathf.Min(bow + 2.5f, maxBow);
            }

            _bow = _pickupSet ? Mathf.MoveTowards(_bow, bow, BowRate * Time.deltaTime) : bow;
            // Con la inclinación de verdad (que puede ir por detrás de la buscada), las manos llegan aquí.
            point = BentShoulders(shoulders, _bow) + (forward * (reach * PickupForward)) - (up * (reach * PickupDrop));
            _pickupLocal = _avatar.InverseTransformPoint(point);
            _pickupSet = true;
        }

        /// <summary>
        /// Cuánto se inclina (de 0 a 1) en el instante <paramref name="t"/>: baja
        /// mientras las manos van a por el gorro, sigue inclinada mientras lo coge y
        /// se endereza al empezar a subirlo. Al quitárselo, lo mismo al revés.
        /// </summary>
        private static float BowWeight(float t)
        {
            if (t <= GrabEnd)
            {
                return Smooth(Mathf.InverseLerp(0f, ReachEnd, t));
            }

            return 1f - Smooth(Mathf.InverseLerp(GrabEnd, GrabEnd + StraightenSeconds, t));
        }

        /// <summary>
        /// Dobla la columna hacia delante <paramref name="angle"/> grados, repartidos
        /// entre sus huesos. Los huesos que mueven las físicas de Genies se quedan
        /// donde los dejó su simulación (ver FindDynamicBones).
        /// </summary>
        private void Bow(float angle)
        {
            if (angle <= 0.01f)
            {
                return;
            }

            for (int i = 0; i < _dynamicBones.Count; i++)
            {
                if (_dynamicBones[i] != null)
                {
                    _dynamicPositions[i] = _dynamicBones[i].position;
                    _dynamicRotations[i] = _dynamicBones[i].rotation;
                }
            }

            Vector3 axis = _avatar.right;
            float hipAngle = HipAngle(angle);
            if (hipAngle > 0.01f)
            {
                // Por la cadera, como una persona: gira la pelvis y los muslos se quedan
                // donde estaban, así que las piernas no se mueven.
                Quaternion back = Quaternion.AngleAxis(-hipAngle, axis);
                Quaternion leftThigh = back * _leftThigh.rotation;
                Quaternion rightThigh = back * _rightThigh.rotation;
                _hips.rotation = Quaternion.AngleAxis(hipAngle, axis) * _hips.rotation;
                _leftThigh.rotation = leftThigh;
                _rightThigh.rotation = rightThigh;
            }

            float spineAngle = angle - hipAngle;
            float total = BowShareTotal();
            for (int i = 0; i < _spine.Length; i++)
            {
                if (_spine[i] != null)
                {
                    // Cada hueso gira sobre sí mismo y arrastra a los de encima.
                    _spine[i].rotation = Quaternion.AngleAxis(spineAngle * BowShares[i] / total, axis) * _spine[i].rotation;
                }
            }

            // En orden de jerarquía (padres antes que hijos), así cada uno acaba en su sitio.
            for (int i = 0; i < _dynamicBones.Count; i++)
            {
                if (_dynamicBones[i] != null)
                {
                    _dynamicBones[i].SetPositionAndRotation(_dynamicPositions[i], _dynamicRotations[i]);
                }
            }
        }

        /// <summary>
        /// Huesos que mueven las físicas de Genies (DynamicsParticle con
        /// AffectsTransform: el flequillo, los mechones, la coleta...). Genies los
        /// coloca en el mundo en su LateUpdate, antes que este, con la simulación del
        /// frame anterior, que ya contaba con la inclinación. Si la columna los
        /// arrastrara otra vez, se doblarían dos veces: el pelo salía despegado y
        /// retorcido delante de la cara.
        /// </summary>
        private void FindDynamicBones()
        {
            _dynamicBones.Clear();
            foreach (MonoBehaviour behaviour in _avatar.GetComponentsInChildren<MonoBehaviour>(true))
            {
                if (behaviour == null || behaviour.GetType().Name != "DynamicsParticle")
                {
                    continue;
                }

                // DynamicsParticle es interna del SDK: su campo público se lee por reflexión.
                System.Reflection.FieldInfo affects = behaviour.GetType().GetField("AffectsTransform");
                if (affects != null && affects.GetValue(behaviour) is bool moves && !moves)
                {
                    continue;
                }

                _dynamicBones.Add(behaviour.transform);
            }

            _dynamicPositions = new Vector3[_dynamicBones.Count];
            _dynamicRotations = new Quaternion[_dynamicBones.Count];
        }

        /// <summary>Dónde quedarían los hombros (<paramref name="shoulders"/>, en la pose de ahora) con la columna doblada <paramref name="angle"/> grados, como en Bow.</summary>
        private Vector3 BentShoulders(Vector3 shoulders, float angle)
        {
            Vector3 axis = _avatar.right;
            float total = BowShareTotal();
            var joints = new Vector3[_spine.Length];
            for (int i = 0; i < _spine.Length; i++)
            {
                joints[i] = _spine[i] != null ? _spine[i].position : Vector3.zero;
            }

            Vector3 point = shoulders;
            float hipAngle = HipAngle(angle);
            if (hipAngle > 0.01f)
            {
                Quaternion hipTurn = Quaternion.AngleAxis(hipAngle, axis);
                Vector3 hipPivot = _hips.position;
                for (int j = 0; j < joints.Length; j++)
                {
                    joints[j] = hipPivot + (hipTurn * (joints[j] - hipPivot));
                }

                point = hipPivot + (hipTurn * (point - hipPivot));
            }

            float spineAngle = angle - hipAngle;
            for (int i = 0; i < _spine.Length; i++)
            {
                if (_spine[i] == null)
                {
                    continue;
                }

                Quaternion turn = Quaternion.AngleAxis(spineAngle * BowShares[i] / total, axis);
                Vector3 pivot = joints[i];
                for (int j = i + 1; j < joints.Length; j++)
                {
                    joints[j] = pivot + (turn * (joints[j] - pivot));
                }

                point = pivot + (turn * (point - pivot));
            }

            return point;
        }

        /// <summary>Cuánto de <paramref name="angle"/> se hace por la cadera (0 si el avatar no tiene cadera y muslos).</summary>
        private float HipAngle(float angle)
        {
            return _hips != null && _leftThigh != null && _rightThigh != null ? angle * HipShare : 0f;
        }

        /// <summary>Suma de los repartos de los huesos de la columna que tiene el avatar.</summary>
        private float BowShareTotal()
        {
            float total = 0f;
            for (int i = 0; i < _spine.Length; i++)
            {
                if (_spine[i] != null)
                {
                    total += BowShares[i];
                }
            }

            return total > 0f ? total : 1f;
        }

        /// <summary>
        /// Cierto si se vería el gorro con su punto de agarre en <paramref name="point"/>:
        /// desde la cámara de ahora o desde el encuadre al que va (al empezar la trivia
        /// la cámara se está yendo al plano de la trivia mientras Sonia se agacha).
        /// Mira las esquinas del gorro de verdad, con la hélice y la visera.
        /// </summary>
        private bool SeenByCamera(Camera cam, Vector3 point)
        {
            if (SeenFrom(cam.transform.position, cam.transform.rotation, cam.fieldOfView, cam.aspect, point))
            {
                return true;
            }

            if (_framing == null || _framing.TargetCamera != cam)
            {
                _framing = null;
                foreach (CameraFramingController framing in FindObjectsByType<CameraFramingController>(FindObjectsSortMode.None))
                {
                    if (framing.TargetCamera == cam)
                    {
                        _framing = framing;
                        break;
                    }
                }
            }

            return _framing != null
                   && _framing.TryGetTargetShot(out ShotPose shot)
                   && SeenFrom(shot.Position, shot.Rotation, shot.FieldOfView, cam.aspect, point);
        }

        private bool SeenFrom(Vector3 eye, Quaternion look, float fieldOfView, float aspect, Vector3 point)
        {
            float tanY = Mathf.Tan(fieldOfView * 0.5f * Mathf.Deg2Rad);
            float tanX = tanY * Mathf.Max(0.01f, aspect);
            Quaternion inverse = Quaternion.Inverse(look);
            for (int i = 0; i < _capCorners.Length; i++)
            {
                Vector3 local = inverse * (point + CapCorner(i) - eye);
                if (local.z <= 0.01f)
                {
                    continue;
                }

                float y = local.y / (local.z * tanY);
                float x = local.x / (local.z * tanX);
                if (y > -1f - FrameMargin && y < 1f + FrameMargin && x > -1f - FrameMargin && x < 1f + FrameMargin)
                {
                    return true;
                }
            }

            return false;
        }

        /// <summary>Esquina <paramref name="index"/> del gorro abajo respecto a su punto de agarre.</summary>
        private Vector3 CapCorner(int index)
        {
            if (_capMeasured)
            {
                return _capCorners[index];
            }

            // Antes de medirlo, la caja del gorro Noogler medida a mano (en tamaños de cabeza):
            // sube 0,2 con la hélice, baja 0,08, la visera sale 0,25 hacia delante.
            float size = ModelSize();
            float x = (index & 1) == 0 ? -0.11f : 0.11f;
            float y = (index & 2) == 0 ? -0.08f : 0.2f;
            float z = (index & 4) == 0 ? -0.13f : 0.25f;
            return ((_avatar.right * x) + (_avatar.up * y) + (_avatar.forward * z)) * size;
        }

        /// <summary>Mide las esquinas del gorro, ya puesto abajo con su punto de agarre en <paramref name="point"/>.</summary>
        private void MeasureCap(Vector3 point)
        {
            Bounds bounds = default;
            bool any = false;
            foreach (Renderer renderer in _root.GetComponentsInChildren<Renderer>())
            {
                if (!renderer.enabled)
                {
                    continue;
                }

                if (any)
                {
                    bounds.Encapsulate(renderer.bounds);
                }
                else
                {
                    bounds = renderer.bounds;
                    any = true;
                }
            }

            if (!any)
            {
                return;
            }

            for (int i = 0; i < _capCorners.Length; i++)
            {
                Vector3 corner = new Vector3(
                    (i & 1) == 0 ? bounds.min.x : bounds.max.x,
                    (i & 2) == 0 ? bounds.min.y : bounds.max.y,
                    (i & 4) == 0 ? bounds.min.z : bounds.max.z);
                _capCorners[i] = corner - point;
            }

            _capMeasured = true;
        }

        /// <summary>
        /// Punto de agarre de una mano en el mundo y la normal de la tela ahí
        /// (hacia fuera): los del prefab (TriviaCapRig) o, en el gorro procedural,
        /// los costados del borde.
        /// </summary>
        private void Grip(bool right, Vector3 position, Quaternion rotation, float size, out Vector3 point, out Vector3 normal)
        {
            if (_rig != null && _model != null && _rig.gripPoints != null && _rig.gripPoints.Length >= 2
                && _rig.gripNormals != null && _rig.gripNormals.Length >= 2)
            {
                // La mano derecha coge el costado derecho del gorro (+X del prefab).
                int index = (_rig.gripPoints[0].x > 0f) == right ? 0 : 1;
                point = _model.TransformPoint(_rig.gripPoints[index]);
                normal = _model.TransformDirection(_rig.gripNormals[index]).normalized;
                return;
            }

            Vector3 across = rotation * Vector3.right;
            float halfWidth = _rig != null ? _rig.openingWidth * 0.5f * size : radius * size;
            normal = right ? across : -across;
            point = position + (rotation * Vector3.up * 0.015f) + (normal * halfWidth);
        }

        // ------------------------------------------------------------------
        // Montaje
        // ------------------------------------------------------------------

        private void Attach()
        {
            if (_head == null)
            {
                Transform avatar = _binder != null ? _binder.Current : null;
                Animator animator = avatar != null ? avatar.GetComponentInChildren<Animator>(true) : null;
                if (animator == null || !animator.isHuman)
                {
                    return;
                }

                _avatar = avatar;
                _head = animator.GetBoneTransform(HumanBodyBones.Head);
                if (_head == null)
                {
                    return;
                }

                _lastHeadPosition = _head.position;
                _right.Bind(animator);
                _left.Bind(animator);
                _spine[0] = animator.GetBoneTransform(HumanBodyBones.Spine);
                _spine[1] = animator.GetBoneTransform(HumanBodyBones.Chest);
                _spine[2] = animator.GetBoneTransform(HumanBodyBones.UpperChest);
                _hips = animator.GetBoneTransform(HumanBodyBones.Hips);
                _leftThigh = animator.GetBoneTransform(HumanBodyBones.LeftUpperLeg);
                _rightThigh = animator.GetBoneTransform(HumanBodyBones.RightUpperLeg);
                FindDynamicBones();
                _pickupSet = false;
                FindAvatarParts();
            }

            Build();

            // Arriba y delante del avatar vistos desde el hueso: así da igual cómo
            // estén orientados los ejes del esqueleto. Se calcula con el avatar en
            // su pose actual, casi siempre de pie mirando a cámara.
            Vector3 up = _head.InverseTransformDirection(_avatar.up).normalized;
            Vector3 fwd = Vector3.ProjectOnPlane(_head.InverseTransformDirection(_avatar.forward), up).normalized;
            if (fwd.sqrMagnitude < 0.5f)
            {
                fwd = Vector3.ProjectOnPlane(Vector3.forward, up).normalized;
            }

            Vector3 right = Vector3.Cross(up, fwd);
            float s = 1f / Mathf.Max(0.0001f, _head.lossyScale.y);
            Quaternion basis = Quaternion.LookRotation(fwd, up);
            if (_rig != null && _rig.fitted)
            {
                // Medido con la gorra oficial, que va pegada al hueso de la cabeza.
                _headLocalPosition = _rig.headPosition;
                _headLocalRotation = _rig.headRotation;
            }
            else if (_rig != null)
            {
                _headLocalPosition = ((right * fitOffset.x) + (up * fitOffset.y) + (fwd * fitOffset.z)) * s;
                _headLocalRotation = basis * Quaternion.Euler(fitEuler);
            }
            else
            {
                _headLocalPosition = ((up * height) + (fwd * forward) + (right * side)) * s;
                _headLocalRotation = basis * Quaternion.Euler(pitch, 0f, -tilt);
            }
        }

        /// <summary>Escala en el mundo del gorro (el modelo está a tamaño real; el procedural, en metros del avatar).</summary>
        private float ModelSize()
        {
            if (_rig != null && _rig.fitted)
            {
                return _rig.headScale * _head.lossyScale.y;
            }

            return (_rig != null ? fitScale : 1f) * _avatar.lossyScale.y;
        }

        /// <summary>
        /// Submallas de gorro del avatar. Genies (NAF) junta cuerpo, pelo, ropa y
        /// gorro en un solo renderer, con una submalla por material: el gorro es la
        /// ropa (no la piel, el pelo, los ojos ni las cejas, que llevan los shaders
        /// «Mega» de Genies) que queda entera por encima del hueso de la cabeza y
        /// sube más allá de la coronilla (las gafas y los pendientes no llegan). Mira
        /// la pose de ahora (BakeMesh): se llama una vez, al enganchar el avatar.
        /// </summary>
        public static void FindHatParts(Transform avatar, Transform head, System.Collections.Generic.List<HatPart> parts)
        {
            parts.Clear();
            if (avatar == null || head == null)
            {
                return;
            }

            float unit = Mathf.Max(0.0001f, head.lossyScale.y);
            Vector3 up = avatar.up;
            float scalp = float.NegativeInfinity;
            var gear = new System.Collections.Generic.List<SubMeshSpan>();
            Mesh baked = new Mesh();
            foreach (SkinnedMeshRenderer renderer in avatar.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                Mesh mesh = renderer.sharedMesh;
                if (mesh == null || !mesh.isReadable)
                {
                    continue;
                }

                Material[] materials = renderer.sharedMaterials;
                renderer.BakeMesh(baked, true);
                Vector3[] vertices = baked.vertices;
                Matrix4x4 toWorld = renderer.transform.localToWorldMatrix;
                for (int s = 0; s < mesh.subMeshCount; s++)
                {
                    Material material = s < materials.Length ? materials[s] : null;
                    string shader = material != null && material.shader != null ? material.shader.name : string.Empty;
                    float min = float.PositiveInfinity;
                    float max = float.NegativeInfinity;
                    foreach (int index in mesh.GetIndices(s))
                    {
                        float h = Vector3.Dot(toWorld.MultiplyPoint3x4(vertices[index]) - head.position, up) / unit;
                        min = Mathf.Min(min, h);
                        max = Mathf.Max(max, h);
                    }

                    if (max < min)
                    {
                        continue;
                    }

                    if (shader.IndexOf("MegaSkin", System.StringComparison.Ordinal) >= 0)
                    {
                        scalp = Mathf.Max(scalp, max);
                    }
                    else if (!shader.StartsWith("Shader Graphs/Mega", System.StringComparison.Ordinal))
                    {
                        gear.Add(new SubMeshSpan { Part = new HatPart { Renderer = renderer, SubMesh = s }, Min = min, Max = max });
                    }
                }
            }

            if (Application.isPlaying)
            {
                Destroy(baked);
            }
            else
            {
                DestroyImmediate(baked);
            }

            // Sin piel de Genies (el doble del editor): la coronilla, más o menos.
            if (float.IsNegativeInfinity(scalp))
            {
                scalp = 0.22f;
            }

            foreach (SubMeshSpan span in gear)
            {
                if (span.Min > -0.01f && span.Max > scalp - 0.03f)
                {
                    parts.Add(span.Part);
                }
            }
        }

        /// <summary>La gorra oficial (para esconderla), el pelo aplastado de Genies y los blendshapes de pelo bajo gorro del avatar.</summary>
        private void FindAvatarParts()
        {
            RestoreAvatar();
            if (hideOfficialHat)
            {
                var parts = new System.Collections.Generic.List<HatPart>();
                FindHatParts(_avatar, _head, parts);
                foreach (HatPart part in parts)
                {
                    _officialHat.Add(new HiddenPart { Renderer = part.Renderer, SubMesh = part.SubMesh });
                    Debug.Log("[Sonia] Gorro de la trivia: mientras lo lleve se esconde la gorra oficial (" + part.Renderer.name + ", submalla " + part.SubMesh + ").");
                }
            }

            // Con gorra oficial el pelo ya va aplastado; si no, el de la gemela con
            // gorra (y, si aún no está, que se saque).
            if (_officialHat.Count == 0)
            {
                _flatHair = HatHair.Find(_avatar);
                if (_flatHair == null)
                {
                    HatHair.Request(_avatar);
                }
            }

            foreach (SkinnedMeshRenderer skinned in _avatar.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                Mesh mesh = skinned.sharedMesh;
                if (mesh == null || string.IsNullOrEmpty(hatHairBlendShape))
                {
                    continue;
                }

                for (int i = 0; i < mesh.blendShapeCount; i++)
                {
                    // Solo las formas de bajo el gorro (hair_geo_blendShape.clip_0001_hatA...),
                    // no el reajuste al cuerpo (hair_geo_blendShape.refitting_female).
                    string shapeName = mesh.GetBlendShapeName(i);
                    int key = shapeName.IndexOf(hatHairBlendShape, System.StringComparison.Ordinal);
                    if (key >= 0 && shapeName.IndexOf("hat", key + hatHairBlendShape.Length, System.StringComparison.OrdinalIgnoreCase) >= 0)
                    {
                        // El peso «del todo» es el del último fotograma (100 en Unity, pero no siempre).
                        int frames = mesh.GetBlendShapeFrameCount(i);
                        float full = frames > 0 ? mesh.GetBlendShapeFrameWeight(i, frames - 1) : 100f;
                        _hairShapes.Add(new HairShape { Renderer = skinned, Index = i, Original = skinned.GetBlendShapeWeight(i), Full = full });
                    }
                }
            }

            _hairWeight = -1f;
        }

        /// <summary>
        /// Con el gorro en la cabeza (<paramref name="onHead"/> de 0 a 1): la gorra
        /// oficial se esconde y el pelo toma la forma de bajo el gorro, como hace
        /// Genies con sus gorros (el de Genies, según <paramref name="flatten"/>).
        /// Con 0 todo vuelve a como estaba.
        /// </summary>
        private void ApplyAvatarIntegration(float onHead, float flatten)
        {
            SetFlatHair(flatten);
            bool hide = onHead > 0.5f;
            // Con el gorro puesto se mira cada frame: Genies puede cambiar los materiales.
            if (hide || hide != _officialHidden)
            {
                _officialHidden = hide;
                for (int i = 0; i < _officialHat.Count; i++)
                {
                    _officialHat[i] = SetHidden(_officialHat[i], hide);
                }
            }

            if (Mathf.Approximately(onHead, _hairWeight))
            {
                return;
            }

            _hairWeight = onHead;
            foreach (HairShape shape in _hairShapes)
            {
                if (shape.Renderer != null)
                {
                    shape.Renderer.SetBlendShapeWeight(shape.Index, Mathf.Lerp(shape.Original, Mathf.Max(shape.Original, shape.Full), onHead));
                }
            }
        }

        /// <summary>
        /// Pelo aplastado de Genies (HatHair) con este peso, de 0 a 1. Con algo de
        /// peso el avatar lleva la copia de su malla con el blendshape del pelo; con
        /// 0, su malla de siempre.
        /// </summary>
        private void SetFlatHair(float weight)
        {
            if (_flatHair == null || _flatHair.Renderer == null || _flatHair.Mesh == null
                || Mathf.Approximately(weight, _flatWeight))
            {
                return;
            }

            _flatWeight = weight;
            SkinnedMeshRenderer renderer = _flatHair.Renderer;
            if (weight <= 0f)
            {
                if (renderer.sharedMesh == _flatHair.Mesh)
                {
                    renderer.sharedMesh = _flatHair.Source;
                }

                return;
            }

            // Si Genies ha cambiado la malla entretanto, la copia ya no vale: se deja.
            if (renderer.sharedMesh == _flatHair.Source)
            {
                renderer.sharedMesh = _flatHair.Mesh;
            }

            if (renderer.sharedMesh == _flatHair.Mesh)
            {
                renderer.SetBlendShapeWeight(_flatHair.Shape, weight * 100f);
            }
        }

        /// <summary>Pone o quita el material invisible en la submalla de la gorra oficial.</summary>
        private HiddenPart SetHidden(HiddenPart part, bool hide)
        {
            if (part.Renderer == null)
            {
                return part;
            }

            part.Renderer.GetSharedMaterials(_slots);
            if (part.SubMesh >= _slots.Count)
            {
                return part;
            }

            Material current = _slots[part.SubMesh];
            if (hide)
            {
                if (current == null || current == part.Hidden)
                {
                    return part;
                }

                // El material de la gorra (o el nuevo, si Genies lo ha cambiado).
                part.Original = current;
                if (part.Hidden != null)
                {
                    Destroy(part.Hidden);
                }

                part.Hidden = new Material(current);
                part.Hidden.name = current.name + " (escondida por la trivia)";
                foreach (string pass in RenderPasses)
                {
                    part.Hidden.SetShaderPassEnabled(pass, false);
                }

                _slots[part.SubMesh] = part.Hidden;
            }
            else
            {
                if (current != part.Hidden || part.Original == null)
                {
                    return part;
                }

                _slots[part.SubMesh] = part.Original;
            }

            part.Renderer.sharedMaterials = _slots.ToArray();
            return part;
        }

        /// <summary>Deja la gorra oficial y el pelo como estaban (cambio de avatar, destrucción).</summary>
        private void RestoreAvatar()
        {
            for (int i = 0; i < _officialHat.Count; i++)
            {
                HiddenPart part = SetHidden(_officialHat[i], false);
                if (part.Hidden != null)
                {
                    Destroy(part.Hidden);
                }
            }

            foreach (HairShape shape in _hairShapes)
            {
                if (shape.Renderer != null)
                {
                    shape.Renderer.SetBlendShapeWeight(shape.Index, shape.Original);
                }
            }

            _flatWeight = -1f;
            SetFlatHair(0f);
            _officialHidden = false;
            _hairWeight = -1f;
            _flatHair = null;
            _flatWeight = -1f;
            _officialHat.Clear();
            _hairShapes.Clear();
        }

        private void Build()
        {
            if (_root != null)
            {
                return;
            }

            if (BuildModel())
            {
                return;
            }

            _stripes = MakeStripes();
            _coneMaterial = MakeMaterial("TriviaHatCone", Color.white, _stripes, 0.45f);
            _trimMaterial = MakeMaterial("TriviaHatTrim", new Color(0.97f, 0.97f, 0.99f), null, 0.2f);

            GameObject root = new GameObject("TriviaHat");
            _root = root.transform;
            _root.SetParent(transform, false);

            GameObject cone = new GameObject("Cone", typeof(MeshFilter), typeof(MeshRenderer));
            cone.transform.SetParent(_root, false);
            _cone = cone.transform;
            _coneMesh = MakeCone(radius, coneHeight, 40);
            cone.GetComponent<MeshFilter>().sharedMesh = _coneMesh;
            cone.GetComponent<MeshRenderer>().sharedMaterial = _coneMaterial;

            GameObject ring = new GameObject("Trim", typeof(MeshFilter), typeof(MeshRenderer));
            ring.transform.SetParent(_root, false);
            _ringMesh = MakeTorus(radius * 0.98f, radius * 0.16f, 40, 12);
            ring.GetComponent<MeshFilter>().sharedMesh = _ringMesh;
            ring.GetComponent<MeshRenderer>().sharedMaterial = _trimMaterial;

            GameObject pompom = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            pompom.name = "Pompom";
            Collider collider = pompom.GetComponent<Collider>();
            if (collider != null)
            {
                Destroy(collider);
            }

            pompom.transform.SetParent(_cone, false);
            pompom.transform.localPosition = new Vector3(0f, coneHeight, 0f);
            pompom.transform.localScale = Vector3.one * (pompomRadius * 2f);
            pompom.GetComponent<MeshRenderer>().sharedMaterial = _trimMaterial;

            _renderers = root.GetComponentsInChildren<Renderer>(true);
            for (int i = 0; i < _renderers.Length; i++)
            {
                _renderers[i].shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
                _renderers[i].receiveShadows = false;
            }

            root.SetActive(false);
        }

        /// <summary>El gorro del prefab de Resources, si está. Falso: se usa el procedural.</summary>
        private bool BuildModel()
        {
            GameObject prefab = string.IsNullOrEmpty(capResource) ? null : Resources.Load<GameObject>(capResource);
            if (prefab == null)
            {
                return false;
            }

            GameObject root = new GameObject("TriviaHat");
            _root = root.transform;
            _root.SetParent(transform, false);
            GameObject model = Instantiate(prefab, _root, false);
            model.name = prefab.name;
            _model = model.transform;
            _rig = model.GetComponent<TriviaCapRig>();
            if (_rig == null)
            {
                _rig = model.AddComponent<TriviaCapRig>();
            }

            if (_rig.propeller != null)
            {
                _propellerRest = _rig.propeller.localRotation;
            }

            _renderers = root.GetComponentsInChildren<Renderer>(true);
            root.SetActive(false);
            return true;
        }

        // ------------------------------------------------------------------
        // Brazos (IK de dos huesos)
        // ------------------------------------------------------------------

        /// <summary>Un brazo que sujeta el ala del gorro: muñeca al borde, palma hacia el gorro.</summary>
        private sealed class HandArm
        {
            private readonly bool _isLeft;
            private Transform _shoulder;
            private Transform _elbow;
            private Transform _wrist;
            private Transform[] _fingers = new Transform[0];
            private Vector3 _fingerLocal = Vector3.forward;
            private Vector3 _thumbLocal = Vector3.up;
            private float _palm = 0.04f;

            public HandArm(bool isLeft)
            {
                _isLeft = isLeft;
            }

            /// <summary>Dónde está ahora el hombro (el hueso del brazo).</summary>
            public Vector3 ShoulderPosition
            {
                get { return _shoulder != null ? _shoulder.position : Vector3.zero; }
            }

            /// <summary>Alcance del brazo estirado, del hombro a la palma, en metros (0 sin huesos).</summary>
            public float Reach
            {
                get
                {
                    if (_shoulder == null || _elbow == null || _wrist == null)
                    {
                        return 0f;
                    }

                    return (_elbow.position - _shoulder.position).magnitude
                           + (_wrist.position - _elbow.position).magnitude + _palm;
                }
            }

            public void Bind(Animator animator)
            {
                _shoulder = animator.GetBoneTransform(_isLeft ? HumanBodyBones.LeftUpperArm : HumanBodyBones.RightUpperArm);
                _elbow = animator.GetBoneTransform(_isLeft ? HumanBodyBones.LeftLowerArm : HumanBodyBones.RightLowerArm);
                _wrist = animator.GetBoneTransform(_isLeft ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand);
                if (_wrist == null || _elbow == null)
                {
                    return;
                }

                HumanBodyBones[] fingerBones = _isLeft
                    ? new[]
                    {
                        HumanBodyBones.LeftIndexProximal, HumanBodyBones.LeftMiddleProximal,
                        HumanBodyBones.LeftRingProximal, HumanBodyBones.LeftLittleProximal,
                        HumanBodyBones.LeftIndexIntermediate, HumanBodyBones.LeftMiddleIntermediate,
                        HumanBodyBones.LeftRingIntermediate, HumanBodyBones.LeftLittleIntermediate
                    }
                    : new[]
                    {
                        HumanBodyBones.RightIndexProximal, HumanBodyBones.RightMiddleProximal,
                        HumanBodyBones.RightRingProximal, HumanBodyBones.RightLittleProximal,
                        HumanBodyBones.RightIndexIntermediate, HumanBodyBones.RightMiddleIntermediate,
                        HumanBodyBones.RightRingIntermediate, HumanBodyBones.RightLittleIntermediate
                    };
                System.Collections.Generic.List<Transform> fingers = new System.Collections.Generic.List<Transform>();
                foreach (HumanBodyBones bone in fingerBones)
                {
                    Transform t = animator.GetBoneTransform(bone);
                    if (t != null)
                    {
                        fingers.Add(t);
                    }
                }

                _fingers = fingers.ToArray();

                // Ejes de la mano en el espacio del hueso: hacia los dedos (al
                // nudillo del corazón) y hacia el lado del pulgar (del meñique al índice).
                Transform middle = animator.GetBoneTransform(_isLeft ? HumanBodyBones.LeftMiddleProximal : HumanBodyBones.RightMiddleProximal);
                Transform index = animator.GetBoneTransform(_isLeft ? HumanBodyBones.LeftIndexProximal : HumanBodyBones.RightIndexProximal);
                Transform little = animator.GetBoneTransform(_isLeft ? HumanBodyBones.LeftLittleProximal : HumanBodyBones.RightLittleProximal);
                Vector3 finger = middle != null ? _wrist.InverseTransformPoint(middle.position) : Vector3.zero;
                if (finger.sqrMagnitude < 1e-8f)
                {
                    finger = _wrist.InverseTransformDirection(_wrist.position - _elbow.position);
                }

                _palm = middle != null ? Mathf.Max(0.02f, (middle.position - _wrist.position).magnitude * 0.75f) : 0.04f;
                finger.Normalize();
                Vector3 thumbSide = index != null && little != null
                    ? _wrist.InverseTransformPoint(index.position) - _wrist.InverseTransformPoint(little.position)
                    : Vector3.up;
                thumbSide = Vector3.ProjectOnPlane(thumbSide, finger);
                if (thumbSide.sqrMagnitude < 1e-8f)
                {
                    thumbSide = Vector3.ProjectOnPlane(Vector3.up, finger);
                }

                _fingerLocal = finger;
                _thumbLocal = thumbSide.normalized;
            }

            /// <summary>
            /// Apoya la palma en la tela por fuera: el nudillo del medio en
            /// <paramref name="surface"/>, la muñeca separada <paramref name="gap"/>
            /// hacia <paramref name="outward"/> (la normal de la tela) y los dedos a lo
            /// largo de la copa, hacia arriba, sin atravesarla. Con
            /// <paramref name="weight"/> 0 deja el brazo como está.
            /// </summary>
            public void Hold(Vector3 surface, Vector3 outward, Vector3 up, Transform avatar, float weight, float curl, float gap)
            {
                if (_shoulder == null || _elbow == null || _wrist == null)
                {
                    return;
                }

                Vector3 fingers = Vector3.ProjectOnPlane(up, outward);
                fingers = fingers.sqrMagnitude > 1e-6f ? fingers.normalized : up;
                Vector3 wristTarget = surface + (outward * gap) - (fingers * _palm);
                // Codo hacia fuera y algo atrás, como al levantar los brazos sobre la cabeza.
                Vector3 pole = _shoulder.position + (outward * 0.3f) - (avatar.forward * 0.12f) - (avatar.up * 0.1f);
                SolveArm(wristTarget, pole, weight);

                // Pulgar hacia atrás: con los dedos arriba y la palma hacia el gorro,
                // tanto en la mano derecha como en la izquierda (espejo).
                Vector3 thumb = Vector3.ProjectOnPlane(-avatar.forward, fingers);
                if (thumb.sqrMagnitude < 1e-6f)
                {
                    return;
                }

                Quaternion localFrame = Quaternion.LookRotation(_fingerLocal, _thumbLocal);
                Quaternion worldFrame = Quaternion.LookRotation(fingers, thumb.normalized);
                _wrist.rotation = Quaternion.Slerp(_wrist.rotation, worldFrame * Quaternion.Inverse(localFrame), weight);

                if (curl <= 0f)
                {
                    return;
                }

                // Dedos algo cerrados, siguiendo la curva de la copa (el eje cruza la palma).
                Vector3 axis = _wrist.rotation * _thumbLocal;
                Quaternion bend = Quaternion.AngleAxis((_isLeft ? curl : -curl) * weight, axis);
                for (int i = 0; i < _fingers.Length; i++)
                {
                    _fingers[i].rotation = bend * _fingers[i].rotation;
                }
            }

            /// <summary>IK de dos huesos: el codo en el plano de la pista y la muñeca en el objetivo.</summary>
            private void SolveArm(Vector3 target, Vector3 pole, float weight)
            {
                Vector3 shoulder = _shoulder.position;
                Vector3 elbow = _elbow.position;
                Vector3 wrist = _wrist.position;
                float upper = (elbow - shoulder).magnitude;
                float lower = (wrist - elbow).magnitude;
                if (upper < 1e-4f || lower < 1e-4f)
                {
                    return;
                }

                Vector3 goal = Vector3.Lerp(wrist, target, weight);
                Vector3 toGoal = goal - shoulder;
                if (toGoal.sqrMagnitude < 1e-8f)
                {
                    return;
                }

                Vector3 direction = toGoal.normalized;
                float distance = Mathf.Clamp(toGoal.magnitude, Mathf.Abs(upper - lower) + 0.001f, upper + lower - 0.001f);
                Vector3 animatedBend = Vector3.ProjectOnPlane(elbow - shoulder, direction);
                Vector3 hintBend = Vector3.ProjectOnPlane(pole - shoulder, direction);
                Vector3 bendDirection;
                if (animatedBend.sqrMagnitude < 1e-8f)
                {
                    bendDirection = hintBend;
                }
                else if (hintBend.sqrMagnitude < 1e-8f)
                {
                    bendDirection = animatedBend;
                }
                else
                {
                    bendDirection = Vector3.Slerp(animatedBend.normalized, hintBend.normalized, weight);
                }

                if (bendDirection.sqrMagnitude < 1e-8f)
                {
                    return;
                }

                bendDirection.Normalize();
                float along = ((upper * upper) - (lower * lower) + (distance * distance)) / (2f * distance);
                float height = Mathf.Sqrt(Mathf.Max(0f, (upper * upper) - (along * along)));
                Vector3 elbowGoal = shoulder + (direction * along) + (bendDirection * height);
                Vector3 wristGoal = shoulder + (direction * distance);

                _shoulder.rotation = Quaternion.FromToRotation(elbow - shoulder, elbowGoal - shoulder) * _shoulder.rotation;
                Vector3 newElbow = _elbow.position;
                _elbow.rotation = Quaternion.FromToRotation(_wrist.position - newElbow, wristGoal - newElbow) * _elbow.rotation;
            }
        }

        // ------------------------------------------------------------------
        // Malla, textura y materiales
        // ------------------------------------------------------------------

        private static Material MakeMaterial(string name, Color color, Texture texture, float smoothness)
        {
            Shader shader = Shader.Find("Universal Render Pipeline/Lit");
            if (shader == null)
            {
                shader = Shader.Find("Universal Render Pipeline/Simple Lit");
            }

            if (shader == null)
            {
                shader = Shader.Find("Standard");
            }

            Material material = new Material(shader);
            material.name = name;
            material.color = color;
            if (material.HasProperty("_BaseColor"))
            {
                material.SetColor("_BaseColor", color);
            }

            if (texture != null)
            {
                material.mainTexture = texture;
                if (material.HasProperty("_BaseMap"))
                {
                    material.SetTexture("_BaseMap", texture);
                }
            }

            if (material.HasProperty("_Smoothness"))
            {
                material.SetFloat("_Smoothness", smoothness);
            }

            // Las dos caras: el cono es abierto y así no depende del sentido de los triángulos.
            if (material.HasProperty("_Cull"))
            {
                material.SetFloat("_Cull", 0f);
            }

            return material;
        }

        /// <summary>Franjas diagonales en los cuatro colores de Google con un filo blanco.</summary>
        private static Texture2D MakeStripes()
        {
            const int size = 128;
            Color[] colors = { Blue, Red, Yellow, Green };
            Texture2D texture = new Texture2D(size, size, TextureFormat.RGBA32, true);
            texture.name = "TriviaHatStripes";
            texture.wrapMode = TextureWrapMode.Repeat;
            texture.filterMode = FilterMode.Bilinear;
            Color[] pixels = new Color[size * size];
            for (int y = 0; y < size; y++)
            {
                for (int x = 0; x < size; x++)
                {
                    // u da la vuelta al cono; v sube. 8 franjas por vuelta, en diagonal.
                    float u = x / (float)size;
                    float v = y / (float)size;
                    float band = ((u * 8f) + (v * 2f)) % 4f;
                    int index = Mathf.FloorToInt(band);
                    float edge = band - index;
                    Color color = colors[index % 4];
                    if (edge < 0.08f)
                    {
                        color = Color.Lerp(Color.white, color, edge / 0.08f);
                    }

                    pixels[(y * size) + x] = color;
                }
            }

            texture.SetPixels(pixels);
            texture.Apply(true, true);
            return texture;
        }

        /// <summary>Cono abierto con la base en y=0 y la punta en y=height; UV: u alrededor, v hacia arriba.</summary>
        private static Mesh MakeCone(float baseRadius, float height, int segments)
        {
            Mesh mesh = new Mesh();
            mesh.name = "TriviaHatCone";
            int rings = 6;
            Vector3[] vertices = new Vector3[(segments + 1) * (rings + 1)];
            Vector3[] normals = new Vector3[vertices.Length];
            Vector2[] uv = new Vector2[vertices.Length];
            float slope = baseRadius / height;
            for (int r = 0; r <= rings; r++)
            {
                float v = r / (float)rings;
                float y = v * height;
                float ringRadius = baseRadius * (1f - v);
                for (int i = 0; i <= segments; i++)
                {
                    float angle = (i / (float)segments) * Mathf.PI * 2f;
                    float cx = Mathf.Cos(angle);
                    float cz = Mathf.Sin(angle);
                    int index = (r * (segments + 1)) + i;
                    vertices[index] = new Vector3(cx * ringRadius, y, cz * ringRadius);
                    normals[index] = new Vector3(cx, slope, cz).normalized;
                    uv[index] = new Vector2(i / (float)segments, v);
                }
            }

            int[] triangles = new int[segments * rings * 6];
            int t = 0;
            for (int r = 0; r < rings; r++)
            {
                for (int i = 0; i < segments; i++)
                {
                    int a = (r * (segments + 1)) + i;
                    int b = a + segments + 1;
                    triangles[t++] = a;
                    triangles[t++] = b;
                    triangles[t++] = a + 1;
                    triangles[t++] = a + 1;
                    triangles[t++] = b;
                    triangles[t++] = b + 1;
                }
            }

            mesh.vertices = vertices;
            mesh.normals = normals;
            mesh.uv = uv;
            mesh.triangles = triangles;
            mesh.RecalculateBounds();
            return mesh;
        }

        /// <summary>Aro (toro) horizontal centrado en el origen.</summary>
        private static Mesh MakeTorus(float majorRadius, float minorRadius, int segments, int sides)
        {
            Mesh mesh = new Mesh();
            mesh.name = "TriviaHatTrim";
            Vector3[] vertices = new Vector3[(segments + 1) * (sides + 1)];
            Vector3[] normals = new Vector3[vertices.Length];
            for (int i = 0; i <= segments; i++)
            {
                float a = (i / (float)segments) * Mathf.PI * 2f;
                Vector3 center = new Vector3(Mathf.Cos(a) * majorRadius, 0f, Mathf.Sin(a) * majorRadius);
                Vector3 outward = center.normalized;
                for (int j = 0; j <= sides; j++)
                {
                    float b = (j / (float)sides) * Mathf.PI * 2f;
                    Vector3 normal = (outward * Mathf.Cos(b)) + (Vector3.up * Mathf.Sin(b));
                    int index = (i * (sides + 1)) + j;
                    vertices[index] = center + (normal * minorRadius);
                    normals[index] = normal;
                }
            }

            int[] triangles = new int[segments * sides * 6];
            int t = 0;
            for (int i = 0; i < segments; i++)
            {
                for (int j = 0; j < sides; j++)
                {
                    int a = (i * (sides + 1)) + j;
                    int b = a + sides + 1;
                    triangles[t++] = a;
                    triangles[t++] = a + 1;
                    triangles[t++] = b;
                    triangles[t++] = a + 1;
                    triangles[t++] = b + 1;
                    triangles[t++] = b;
                }
            }

            mesh.vertices = vertices;
            mesh.normals = normals;
            mesh.triangles = triangles;
            mesh.RecalculateBounds();
            return mesh;
        }

        private static float Smooth(float t)
        {
            t = Mathf.Clamp01(t);
            return t * t * (3f - (2f * t));
        }

        private static void DestroyAsset(Object asset)
        {
            if (asset != null)
            {
                Destroy(asset);
            }
        }
    }
}
