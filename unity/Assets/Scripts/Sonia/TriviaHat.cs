// Gorro de fiesta de la trivia: un cono con franjas en los colores de Google
// (azul, rojo, amarillo y verde), un aro blanco en la base y un pompón. Sonia se
// lo pone y se lo quita con las dos manos.
//
// Se construye por código (malla, textura y materiales), sin assets ni red. Las
// prendas del catálogo de Genies se descartaron: equiparlas descarga y
// reconstruye el avatar entero en mitad de la partida y no hay ninguna
// temática (docs/trivia.md).
//
// Ponérselo (una línea de tiempo de 1,7 s; quitárselo es la misma al revés):
//   0,00-0,45  las manos suben delante del pecho y el gorro aparece entre ellas;
//   0,45-1,00  lo llevan en arco por encima de la cabeza hasta su sitio;
//   1,00-1,15  un apretón (el gorro se aplasta un poco al encajar);
//   1,15-1,70  las manos sueltan y vuelven a lo que hacía la animación.
// Al quitárselo: las manos suben al gorro, lo levantan, lo bajan delante del
// pecho, el gorro se encoge hasta desaparecer y las manos bajan. Si se pide lo
// contrario a medias, la línea de tiempo da la vuelta desde donde está.
//
// Genies no trae ninguna animación de ponerse un gorro, así que los brazos van
// con IK de dos huesos (hombro, codo, muñeca) encima de lo que suene, como el
// apretón de manos del Modo Jean (HandshakeRig). Corre en LateUpdate al final
// de todo (12600: después de la cabeza, los ojos y la cara), así que el gorro
// sigue a la cabeza ya girada y los brazos no se pelean con nadie.
//
// El pelo de Sonia es voluminoso: el gorro va algo por encima de la coronilla
// y ladeado; la altura, el tamaño y la inclinación se ajustan en el inspector
// mirando capturas 9:16 en Play. Solo se pone en Sonia (nunca en el invitado
// del Modo Jean) y se esconde si Sonia sale de cuadro.

using UnityEngine;

namespace Sonia
{
    /// <summary>Gorro de fiesta procedural que Sonia se pone y se quita con las manos.</summary>
    [DefaultExecutionOrder(12600)]
    [DisallowMultipleComponent]
    public class TriviaHat : MonoBehaviour
    {
        [Header("Colocación (en la cabeza)")]
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
        [Tooltip("Velocidad de la secuencia (1 = 1,7 s).")]
        private float speed = 1f;

        [SerializeField]
        [Tooltip("Dónde aparece el gorro entre las manos, respecto a la cabeza: delante (z) y abajo (y), en metros.")]
        private Vector2 holdOffset = new Vector2(0.22f, -0.3f);

        [SerializeField]
        [Range(0f, 0.3f)]
        [Tooltip("Cuánto sube el arco del gorro por encima de la recta al llevarlo a la cabeza, en metros.")]
        private float carryArc = 0.08f;

        [SerializeField]
        [Range(0f, 0.06f)]
        [Tooltip("Separación de cada mano del borde del gorro, en metros.")]
        private float gripGap = 0.012f;

        [SerializeField]
        [Range(0f, 60f)]
        [Tooltip("Dedos algo cerrados sobre el ala del gorro, en grados.")]
        private float fingerCurl = 18f;

        [Header("Animación")]
        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("Grados del bamboleo del gorro al moverse la cabeza.")]
        private float wobble = 4f;

        // Línea de tiempo (segundos con speed = 1).
        private const float RiseEnd = 0.45f;
        private const float PopStart = 0.15f;
        private const float CarryEnd = 1.0f;
        private const float PressEnd = 1.15f;
        private const float Total = 1.7f;

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
        private readonly HandArm _right = new HandArm(false);
        private readonly HandArm _left = new HandArm(true);
        private Transform _root;
        private Transform _cone;
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

        /// <summary>Cierto si el gorro está puesto o poniéndose.</summary>
        public bool IsOn
        {
            get { return _wanted; }
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
        }

        private void OnDisable()
        {
            if (_binder != null)
            {
                _binder.AvatarChanged -= HandleAvatarChanged;
            }
        }

        private void OnDestroy()
        {
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

        private void HandleAvatarChanged(Transform avatar)
        {
            // Avatar nuevo (el SDK entregó otro o se cambió el aspecto): el gorro
            // pasa a su cabeza y los brazos a sus huesos.
            _head = null;
            if (_wanted || _time > 0f)
            {
                Attach();
            }
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
                return;
            }

            // Bamboleo: el gorro se queda un poco atrás cuando la cabeza se mueve.
            Vector3 velocity = dt > 0f ? (_head.position - _lastHeadPosition) / dt : Vector3.zero;
            _lastHeadPosition = _head.position;
            float target = Mathf.Clamp(-_avatar.InverseTransformDirection(velocity).x * 60f, -wobble, wobble);
            _sway = Mathf.SmoothDamp(_sway, target, ref _swayVelocity, 0.12f);

            // Pose del gorro: en la cabeza, entre las manos o de camino.
            Vector3 headPosition = _head.TransformPoint(_headLocalPosition);
            Quaternion headRotation = _head.rotation * _headLocalRotation;
            float t = useHands ? _time : Total;
            Vector3 holdPosition = _head.position + (_avatar.forward * holdOffset.x) + (_avatar.up * holdOffset.y);
            Quaternion holdRotation = Quaternion.LookRotation(_avatar.forward, _avatar.up) * Quaternion.Euler(-12f, 0f, 0f);
            float carry = Smooth(Mathf.InverseLerp(RiseEnd, CarryEnd, t));
            Vector3 position = Vector3.Lerp(holdPosition, headPosition, carry)
                               + (_avatar.up * (Mathf.Sin(carry * Mathf.PI) * carryArc));
            Quaternion rotation = Quaternion.Slerp(holdRotation, headRotation, carry);

            // Tamaño: aparece (o se va) entre las manos con un rebote, y se aplasta al encajar.
            float pop = useHands ? Mathf.InverseLerp(PopStart, RiseEnd, t) : t / Total;
            float scale = _wanted ? EaseOutBack(pop) : pop * pop;
            float press = Mathf.InverseLerp(CarryEnd, PressEnd, t);
            float squash = press > 0f && press < 1f ? 1f - (0.12f * Mathf.Sin(press * Mathf.PI)) : 1f;
            float parent = transform.lossyScale.y > 0.0001f ? transform.lossyScale.y : 1f;
            _root.SetPositionAndRotation(position, rotation);
            _root.localScale = new Vector3(scale / squash, scale * squash, scale / squash) * (_avatar.lossyScale.y / parent);
            _cone.localRotation = Quaternion.Euler(0f, 0f, _sway + (Mathf.Sin(_clock * 1.7f) * 0.6f));

            if (!useHands)
            {
                return;
            }

            // Manos: suben, sujetan el gorro por el ala mientras viaja y sueltan.
            float rise = Smooth(Mathf.InverseLerp(0f, RiseEnd, t));
            float release = Smooth(Mathf.InverseLerp(PressEnd, Total, t));
            float weight = rise * (1f - release);
            if (weight <= 0.001f)
            {
                return;
            }

            Vector3 up = rotation * Vector3.up;
            Vector3 across = rotation * Vector3.right;
            float rim = (radius * scale) + gripGap;
            Vector3 brim = position + (up * 0.015f);
            _right.Hold(brim + (across * rim), -across, up, _avatar, weight, fingerCurl);
            _left.Hold(brim - (across * rim), across, up, _avatar, weight, fingerCurl);
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
            _headLocalPosition = ((up * height) + (fwd * forward) + (right * side)) * s;
            _headLocalRotation = Quaternion.LookRotation(fwd, up) * Quaternion.Euler(pitch, 0f, -tilt);
        }

        private void Build()
        {
            if (_root != null)
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
            /// Lleva la mano al punto <paramref name="grip"/> del ala, con los dedos
            /// hacia arriba y hacia el gorro (<paramref name="inward"/>) y la palma
            /// mirándolo. Con <paramref name="weight"/> 0 deja el brazo como está.
            /// </summary>
            public void Hold(Vector3 grip, Vector3 inward, Vector3 up, Transform avatar, float weight, float curl)
            {
                if (_shoulder == null || _elbow == null || _wrist == null)
                {
                    return;
                }

                Vector3 fingers = ((up * 0.75f) + (inward * 0.65f)).normalized;
                Vector3 wristTarget = grip - (fingers * _palm);
                // Codo hacia fuera y algo atrás, como al levantar los brazos sobre la cabeza.
                Vector3 outward = -inward;
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

                // Dedos algo cerrados sobre el ala (el eje cruza la palma).
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

        private static float EaseOutBack(float t)
        {
            const float c1 = 1.70158f;
            const float c3 = c1 + 1f;
            float p = Mathf.Clamp01(t) - 1f;
            return 1f + (c3 * p * p * p) + (c1 * p * p);
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
