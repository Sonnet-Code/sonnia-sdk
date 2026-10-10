// La demostración de Sonnia en «Simón dice con poses» (docs/juegos/poses.md):
// sostiene por código la pose de cada ronda sobre lo que suene (reposo, gestos
// al hablar, escuchar), para que salga exacta y quieta.
//
// Cómo:
//  - IK de dos huesos por brazo (hombro, codo y muñeca) hacia objetivos medidos
//    sobre el propio cuerpo de este frame: hombros, largo del brazo y la cabeza
//    (su volumen real, con el pelo, medido una vez en la malla al enganchar el
//    avatar). Así vale para cualquier avatar de Genies y la pose sigue al cuerpo
//    (respira, se balancea) sin pelearse con él.
//  - El codo se dobla por su bisagra: el brazo gira sobre su eje para que el
//    codo doble en el plano de la pose, y el antebrazo se lleva la mitad del
//    giro de la muñeca (sin «caramelo» en el antebrazo).
//  - La mano se orienta entera (dedos y palma) y cada falange se apunta a su
//    dirección: abierta y relajada, puño (bíceps) o puño suelto bajo la barbilla.
//    Nunca en garra: los dedos siempre algo doblados hacia la palma.
//  - Entra en ~0,5 s y sale en ~0,45 s con curva suave; el camino de la mano se
//    abomba hacia fuera y hacia delante para no atravesar el cuerpo ni la cabeza.
//
// Corre en LateUpdate muy tarde (12650): después del Animator, de los clips de
// Genies (GeniesGestureLayer, -20), de la cabeza que sigue al visitante
// (AvatarStateController) y de los ojos, así que gana a todo lo que mueva los
// brazos y pone las manos en la cabeza ya girada. Un hueso que nadie anima no se
// queda posado al soltar: se le devuelve lo que tenía antes de tocarlo.

using System.Collections.Generic;
using UnityEngine;

namespace Sonia.Games.Poses
{
    /// <summary>Pose sostenida de Sonnia para enseñar cada pose del juego.</summary>
    [DefaultExecutionOrder(12650)]
    [DisallowMultipleComponent]
    public class PosesDemo : MonoBehaviour
    {
        [SerializeField]
        [Range(0.1f, 2f)]
        [Tooltip("Segundos en llegar a la pose.")]
        private float blendIn = 0.5f;

        [SerializeField]
        [Range(0.1f, 2f)]
        [Tooltip("Segundos en soltarla.")]
        private float blendOut = 0.45f;

        [SerializeField]
        [Range(0f, 0.4f)]
        [Tooltip("Cuánto se abomba el camino de la mano hacia fuera y delante al entrar y salir, en largos de brazo.")]
        private float pathBow = 0.16f;

        [SerializeField]
        [Range(0f, 0.05f)]
        [Tooltip("Separación de la palma con la cabeza o la barbilla, en metros (el grosor de la mano).")]
        private float contactGap = 0.018f;

        [SerializeField]
        [Range(-0.5f, 1f)]
        [Tooltip("Barbilla: cuánto queda el nudillo del medio por debajo de la barbilla medida, en largos de palma (el puño suelto apoya en ella).")]
        private float chinDrop = 0.12f;

        [SerializeField]
        [Tooltip("Escribir en la consola lo que mide y qué pose enseña.")]
        private bool logEvents = true;

        /// <summary>Las poses que sabe enseñar (ids del protocolo).</summary>
        public static readonly string[] Poses =
        {
            "brazos_arriba", "un_brazo", "pose_t", "manos_cabeza", "biceps", "barbilla"
        };

        private AvatarBinder _binder;
        private Transform _avatar;
        private Animator _animator;
        private Transform _head;
        private readonly Arm _left = new Arm(true);
        private readonly Arm _right = new Arm(false);
        private HeadShape _headShape;

        private string _pose;
        private bool _holding;
        private float _weight;

        /// <summary>¿Sabe enseñar esta pose?</summary>
        public static bool Knows(string pose)
        {
            return System.Array.IndexOf(Poses, pose) >= 0;
        }

        /// <summary>La pose que enseña o soltaba (vacío si ninguna).</summary>
        public string Current
        {
            get { return _holding ? _pose : string.Empty; }
        }

        /// <summary>Cierto mientras la pose pesa algo (entrando, sostenida o saliendo).</summary>
        public bool IsActive
        {
            get { return _weight > 0.0001f; }
        }

        /// <summary>Cuánto manda la pose ahora (0 a 1, ya con la curva).</summary>
        public float Weight
        {
            get { return Smooth(_weight); }
        }

        /// <summary>Empieza a enseñar <paramref name="pose"/> y la sostiene. Falso si no la conoce.</summary>
        public bool Show(string pose)
        {
            if (!Knows(pose))
            {
                return false;
            }

            if (_holding && _pose == pose)
            {
                return true;
            }

            if (_weight > 0.0001f && _pose != pose)
            {
                // Otra pose con la anterior aún puesta: se pasa desde donde iba.
                _weight = Mathf.Min(_weight, 0.35f);
            }

            _pose = pose;
            _holding = true;
            Log("enseña " + pose);
            return true;
        }

        /// <summary>Suelta la pose con su fundido.</summary>
        public void Release()
        {
            if (_holding)
            {
                Log("suelta " + _pose);
            }

            _holding = false;
        }

        /// <summary>Suelta la pose ya, sin fundido (al cerrar el juego).</summary>
        public void ReleaseNow()
        {
            _holding = false;
            _weight = 0f;
            RestoreGuards();
        }

        private void Awake()
        {
            _binder = GetComponentInChildren<AvatarBinder>(true);
            if (_binder == null)
            {
                _binder = FindAnyObjectByType<AvatarBinder>();
            }
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

            ReleaseNow();
        }

        private void HandleAvatarChanged(Transform avatar)
        {
            // Otro avatar: huesos y cabeza nuevos (se miden al hacer falta).
            RestoreGuards();
            _avatar = null;
            _head = null;
        }

        private void LateUpdate()
        {
            float dt = Time.deltaTime;
            float target = _holding ? 1f : 0f;
            float seconds = _holding ? blendIn : blendOut;
            _weight = Mathf.MoveTowards(_weight, target, dt / Mathf.Max(0.05f, seconds));
            if (_weight <= 0.0001f || string.IsNullOrEmpty(_pose))
            {
                // Sin pose: lo que no anime nadie vuelve a lo que tenía.
                RestoreGuards();
                return;
            }

            if (!Attach())
            {
                return;
            }

            _left.BeginFrame();
            _right.BeginFrame();
            float w = Smooth(_weight);
            float bow = Mathf.Sin(Mathf.PI * Mathf.Clamp01(_weight)) * pathBow;
            Apply(_pose, w, bow);
        }

        // ------------------------------------------------------------------
        // Poses
        // ------------------------------------------------------------------

        private void Apply(string pose, float w, float bow)
        {
            Vector3 up = _avatar.up;
            Vector3 fwd = _avatar.forward;
            Vector3 right = _avatar.right;
            float reach = Mathf.Max(0.2f, (_left.Reach + _right.Reach) * 0.5f);

            switch (pose)
            {
                case "brazos_arriba":
                    _left.Shrug(up, 14f * w);
                    _right.Shrug(up, 14f * w);
                    RaisedArm(_left, up, fwd, right, reach, 0.32f, w, bow);
                    RaisedArm(_right, up, fwd, right, reach, 0.32f, w, bow);
                    break;

                case "un_brazo":
                    // El derecho de Sonnia: en la pantalla, a la izquierda, como en el pictograma.
                    _right.Shrug(up, 12f * w);
                    RaisedArm(_right, up, fwd, right, reach, 0.12f, w, bow);
                    RestingArm(_left, up, fwd, right, reach, w, bow);
                    break;

                case "pose_t":
                    TArm(_left, up, fwd, right, reach, w, bow);
                    TArm(_right, up, fwd, right, reach, w, bow);
                    break;

                case "manos_cabeza":
                    _left.Shrug(up, 6f * w);
                    _right.Shrug(up, 6f * w);
                    HeadArm(_left, up, fwd, right, reach, w, bow);
                    HeadArm(_right, up, fwd, right, reach, w, bow);
                    break;

                case "biceps":
                    _left.Shrug(up, 5f * w);
                    _right.Shrug(up, 5f * w);
                    BicepsArm(_left, up, fwd, right, w, bow, reach);
                    BicepsArm(_right, up, fwd, right, w, bow, reach);
                    break;

                case "barbilla":
                    ChinArm(_right, up, fwd, right, reach, w, bow);
                    RestingArm(_left, up, fwd, right, reach, w, bow);
                    break;
            }
        }

        /// <summary>Brazo arriba estirado, algo abierto (<paramref name="spread"/> en largos de brazo) y la palma al público.</summary>
        private void RaisedArm(Arm arm, Vector3 up, Vector3 fwd, Vector3 right, float reach, float spread, float w, float bow)
        {
            Vector3 outward = arm.Outward(right);
            Vector3 s = arm.ShoulderPosition;
            Vector3 wrist = s + (up * (reach * 0.9f)) + (outward * (reach * spread)) + (fwd * (reach * 0.05f));
            wrist = s + ((wrist - s).normalized * (arm.ArmLength * 0.985f));
            Vector3 pole = s + (outward * 0.6f) - (fwd * 0.35f);
            Vector3 fingers = (wrist - s).normalized;
            Vector3 palm = Vector3.ProjectOnPlane(fwd, fingers).normalized;
            arm.Solve(Bowed(arm, wrist, outward, fwd, reach, bow), pole, w);
            arm.Orient(fingers, palm, w);
            arm.Shape(HandShapeKind.Open, w);
        }

        /// <summary>Brazo caído y relajado junto al muslo.</summary>
        private void RestingArm(Arm arm, Vector3 up, Vector3 fwd, Vector3 right, float reach, float w, float bow)
        {
            Vector3 outward = arm.Outward(right);
            Vector3 s = arm.ShoulderPosition;
            Vector3 wrist = s - (up * (arm.ArmLength * 0.95f)) + (outward * (reach * 0.1f)) + (fwd * (reach * 0.06f));
            Vector3 pole = s - (fwd * 0.5f) + (outward * 0.15f) - (up * 0.2f);
            Vector3 fingers = (-up + (fwd * 0.12f)).normalized;
            Vector3 palm = Vector3.ProjectOnPlane(-outward, fingers).normalized;
            arm.Solve(Bowed(arm, wrist, outward, fwd, reach, bow * 0.5f), pole, w);
            arm.Orient(fingers, palm, w);
            arm.Shape(HandShapeKind.Relaxed, w);
        }

        /// <summary>
        /// Brazo en cruz, palma abajo: casi horizontal, unos grados hacia delante y abajo
        /// (sigue siendo una T de frente y no se sale tanto por los lados del encuadre).
        /// </summary>
        private void TArm(Arm arm, Vector3 up, Vector3 fwd, Vector3 right, float reach, float w, float bow)
        {
            Vector3 outward = arm.Outward(right);
            Vector3 s = arm.ShoulderPosition;
            Vector3 along = ((outward * 0.93f) + (fwd * 0.33f) - (up * 0.1f)).normalized;
            Vector3 wrist = s + (along * (arm.ArmLength * 0.985f));
            Vector3 pole = s - (fwd * 0.6f) - (up * 0.15f);
            Vector3 fingers = along;
            Vector3 palm = Vector3.ProjectOnPlane(-up, fingers).normalized;
            arm.Solve(Bowed(arm, wrist, outward, fwd, reach, bow), pole, w);
            arm.Orient(fingers, palm, w);
            arm.Shape(HandShapeKind.Open, w);
        }

        /// <summary>Mano a un lado de la cabeza, palma contra ella y dedos hacia arriba y atrás: el «¡ay, no!».</summary>
        private void HeadArm(Arm arm, Vector3 up, Vector3 fwd, Vector3 right, float reach, float w, float bow)
        {
            Vector3 outward = arm.Outward(right);
            HeadShape head = _headShape;
            Vector3 center = _head.TransformPoint(head.Center);
            Vector3 side = arm.IsLeft ? head.LeftSide : head.RightSide;
            Vector3 contact = _head.TransformPoint(side) + (up * (head.HalfHeight * 0.12f)) + (outward * contactGap);
            Vector3 fingers = ((up * 0.85f) - (fwd * 0.4f) - (outward * 0.12f)).normalized;
            Vector3 palm = (center - contact);
            palm = Vector3.ProjectOnPlane(palm, fingers).normalized;
            if (palm.sqrMagnitude < 0.5f)
            {
                palm = -outward;
            }

            // La palma (hacia el nudillo del medio) sobre la sien: la muñeca un poco por debajo y fuera.
            Vector3 wrist = contact - (fingers * (arm.Palm * 0.9f)) + (outward * (arm.Palm * 0.15f));
            Vector3 s = arm.ShoulderPosition;
            Vector3 pole = s + (outward * 0.7f) + (fwd * 0.3f) + (up * 0.1f);
            arm.Solve(Bowed(arm, wrist, outward, fwd, reach, bow * 1.6f), pole, w);
            arm.Orient(fingers, palm, w);
            arm.Shape(HandShapeKind.Cupped, w);
        }

        /// <summary>Bíceps: codo a la altura del hombro y algo adelantado, antebrazo arriba y puño cerrado hacia la cabeza.</summary>
        private void BicepsArm(Arm arm, Vector3 up, Vector3 fwd, Vector3 right, float w, float bow, float reach)
        {
            Vector3 outward = arm.Outward(right);
            Vector3 s = arm.ShoulderPosition;
            Vector3 elbow = s + (outward * (arm.UpperLength * 0.93f)) + (up * (arm.UpperLength * 0.12f)) + (fwd * (arm.UpperLength * 0.22f));
            Vector3 forearm = ((up * 0.94f) - (outward * 0.22f) + (fwd * 0.08f)).normalized;
            Vector3 wrist = elbow + (forearm * (arm.LowerLength * 0.98f));
            Vector3 pole = elbow + ((elbow - s).normalized * 0.3f) - (up * 0.3f);
            Vector3 fingers = ((up * 0.9f) - (outward * 0.25f)).normalized;
            Vector3 palm = Vector3.ProjectOnPlane(-outward - (fwd * 0.3f), fingers).normalized;
            arm.Solve(Bowed(arm, wrist, outward, fwd, reach, bow), pole, w);
            arm.Orient(fingers, palm, w);
            arm.Shape(HandShapeKind.Fist, w);
        }

        /// <summary>Mano bajo la barbilla, pensando: puño suelto con la barbilla sobre el índice doblado.</summary>
        private void ChinArm(Arm arm, Vector3 up, Vector3 fwd, Vector3 right, float reach, float w, float bow)
        {
            Vector3 outward = arm.Outward(right);
            HeadShape head = _headShape;
            Vector3 chin = _head.TransformPoint(head.Chin);
            // Los dedos doblados quedan bajo la barbilla: el nudillo del medio un poco por
            // debajo y delante de ella, y la muñeca debajo, con el antebrazo casi vertical.
            Vector3 fingers = ((up * 0.92f) + (fwd * 0.2f) - (outward * 0.12f)).normalized;
            Vector3 palm = Vector3.ProjectOnPlane(-fwd + (outward * 0.25f), fingers).normalized;
            Vector3 knuckle = chin - (up * (arm.Palm * chinDrop)) + (fwd * (arm.Palm * 0.36f)) + (outward * (arm.Palm * 0.08f));
            Vector3 wrist = knuckle - (fingers * arm.Palm);
            Vector3 s = arm.ShoulderPosition;
            Vector3 pole = s - (up * 0.6f) + (outward * 0.25f) + (fwd * 0.2f);
            arm.Solve(Bowed(arm, wrist, outward, fwd, reach, bow * 1.2f), pole, w);
            arm.Orient(fingers, palm, w);
            arm.Shape(HandShapeKind.LooseFist, w);
        }

        /// <summary>Abomba el camino de la muñeca hacia fuera y delante mientras entra o sale.</summary>
        private static Vector3 Bowed(Arm arm, Vector3 target, Vector3 outward, Vector3 fwd, float reach, float bow)
        {
            if (bow <= 0f)
            {
                return target;
            }

            return target + (((outward * 0.8f) + (fwd * 0.6f)) * (reach * bow));
        }

        private static float Smooth(float t)
        {
            t = Mathf.Clamp01(t);
            return t * t * (3f - (2f * t));
        }

        // ------------------------------------------------------------------
        // Montaje
        // ------------------------------------------------------------------

        private bool Attach()
        {
            Transform avatar = _binder != null ? _binder.Current : null;
            if (avatar == null)
            {
                return false;
            }

            if (avatar == _avatar && _head != null)
            {
                return true;
            }

            Animator animator = avatar.GetComponentInChildren<Animator>(true);
            if (animator == null || !animator.isHuman)
            {
                return false;
            }

            Transform head = animator.GetBoneTransform(HumanBodyBones.Head);
            if (head == null || !_left.Bind(animator) || !_right.Bind(animator))
            {
                return false;
            }

            _avatar = avatar;
            _animator = animator;
            _head = head;
            _headShape = HeadShape.Measure(avatar, head);
            Log(string.Format(
                System.Globalization.CultureInfo.InvariantCulture,
                "avatar {0}: brazo {1:0.000} m, palma {6:0.000} m, cabeza {2:0.000} x {3:0.000} x {4:0.000} m ({5}), barbilla {7:0.000} m bajo el hueso de la cabeza y {8:0.000} m delante",
                avatar.name,
                (_left.ArmLength + _right.ArmLength) * 0.5f,
                _headShape.HalfWidth * 2f,
                _headShape.HalfHeight * 2f,
                _headShape.HalfDepth * 2f,
                _headShape.Measured ? "medida en la malla" : "estimada",
                _right.Palm,
                -Vector3.Dot(head.TransformPoint(_headShape.Chin) - head.position, avatar.up),
                Vector3.Dot(head.TransformPoint(_headShape.Chin) - head.position, avatar.forward)));
            return true;
        }

        private void RestoreGuards()
        {
            _left.Restore();
            _right.Restore();
        }

        private void Log(string message)
        {
            if (logEvents)
            {
                Debug.Log("[Sonia] poses: " + message, this);
            }
        }

        // ------------------------------------------------------------------
        // Cabeza medida
        // ------------------------------------------------------------------

        /// <summary>El volumen de la cabeza (con el pelo) en el espacio del hueso de la cabeza.</summary>
        private struct HeadShape
        {
            public Vector3 Center;
            public Vector3 Chin;
            public Vector3 LeftSide;
            public Vector3 RightSide;
            public float HalfWidth;
            public float HalfHeight;
            public float HalfDepth;
            public bool Measured;

            /// <summary>
            /// Mide la cabeza en la malla: los vértices que mueve sobre todo la cabeza o
            /// sus hijos (mandíbula, ojos, pelo), en la pose de ahora. Sin malla legible,
            /// unas medidas aproximadas de un avatar de Genies.
            /// </summary>
            public static HeadShape Measure(Transform avatar, Transform head)
            {
                Vector3 upL = head.InverseTransformDirection(avatar.up).normalized;
                Vector3 fwdL = head.InverseTransformDirection(avatar.forward).normalized;
                Vector3 rightL = head.InverseTransformDirection(avatar.right).normalized;
                float scale = Mathf.Max(0.0001f, head.lossyScale.y);
                HeadShape shape = Estimate(upL, fwdL, rightL, scale);
                try
                {
                    List<Vector3> core = new List<Vector3>();
                    List<Vector3> points = HeadPoints(avatar, head, core);
                    if (points.Count < 200)
                    {
                        return shape;
                    }

                    float minX = float.MaxValue, maxX = float.MinValue;
                    float minY = float.MaxValue, maxY = float.MinValue;
                    float minZ = float.MaxValue, maxZ = float.MinValue;
                    foreach (Vector3 p in points)
                    {
                        float x = Vector3.Dot(p, rightL);
                        float y = Vector3.Dot(p, upL);
                        float z = Vector3.Dot(p, fwdL);
                        minX = Mathf.Min(minX, x);
                        maxX = Mathf.Max(maxX, x);
                        minY = Mathf.Min(minY, y);
                        maxY = Mathf.Max(maxY, y);
                        minZ = Mathf.Min(minZ, z);
                        maxZ = Mathf.Max(maxZ, z);
                    }

                    float cx = (minX + maxX) * 0.5f;
                    float cy = (minY + maxY) * 0.5f;
                    float cz = (minZ + maxZ) * 0.5f;
                    float halfW = (maxX - minX) * 0.5f;
                    float halfH = (maxY - minY) * 0.5f;
                    float halfD = (maxZ - minZ) * 0.5f;

                    // Barbilla: lo más bajo de la cara, cerca del centro y en la mitad de delante,
                    // solo con la piel que mueve la cabeza sola (sin el cuello ni el pelo).
                    float chinY = float.MaxValue;
                    float chinZ = maxZ;
                    foreach (Vector3 p in core.Count >= 100 ? core : points)
                    {
                        float x = Vector3.Dot(p, rightL) - cx;
                        float z = Vector3.Dot(p, fwdL);
                        if (Mathf.Abs(x) > halfW * 0.18f || z < cz + (halfD * 0.25f))
                        {
                            continue;
                        }

                        float y = Vector3.Dot(p, upL);
                        if (y < chinY)
                        {
                            chinY = y;
                            chinZ = z;
                        }
                    }

                    // Los lados, a la altura de las sienes: lo más ancho en esa franja.
                    float templeY = cy + (halfH * 0.05f);
                    float sideMin = cx, sideMax = cx;
                    foreach (Vector3 p in points)
                    {
                        float y = Vector3.Dot(p, upL);
                        if (Mathf.Abs(y - templeY) > halfH * 0.18f)
                        {
                            continue;
                        }

                        float x = Vector3.Dot(p, rightL);
                        sideMin = Mathf.Min(sideMin, x);
                        sideMax = Mathf.Max(sideMax, x);
                    }

                    if (chinY == float.MaxValue || sideMax - sideMin < halfW * 0.8f)
                    {
                        return shape;
                    }

                    shape.Center = (rightL * cx) + (upL * cy) + (fwdL * cz);
                    shape.HalfWidth = halfW;
                    shape.HalfHeight = halfH;
                    shape.HalfDepth = halfD;
                    shape.Chin = (rightL * cx) + (upL * chinY) + (fwdL * chinZ);
                    shape.LeftSide = (rightL * sideMin) + (upL * templeY) + (fwdL * (cz + (halfD * 0.08f)));
                    shape.RightSide = (rightL * sideMax) + (upL * templeY) + (fwdL * (cz + (halfD * 0.08f)));
                    shape.Measured = true;
                    return shape;
                }
                catch (System.Exception ex)
                {
                    Debug.LogWarning("[Sonia] poses: no se pudo medir la cabeza (" + ex.Message + "); medidas aproximadas.");
                    return shape;
                }
            }

            private static HeadShape Estimate(Vector3 upL, Vector3 fwdL, Vector3 rightL, float scale)
            {
                float s = 1f / scale;
                HeadShape shape = new HeadShape();
                shape.HalfWidth = 0.1f * s;
                shape.HalfHeight = 0.13f * s;
                shape.HalfDepth = 0.11f * s;
                shape.Center = (upL * (0.11f * s)) + (fwdL * (0.02f * s));
                shape.Chin = (upL * (0.0f * s)) + (fwdL * (0.09f * s));
                shape.LeftSide = shape.Center - (rightL * shape.HalfWidth);
                shape.RightSide = shape.Center + (rightL * shape.HalfWidth);
                shape.Measured = false;
                return shape;
            }

            /// <summary>Vértices (en el espacio del hueso de la cabeza) que mueve sobre todo la cabeza o algo que cuelga de ella.</summary>
            private static List<Vector3> HeadPoints(Transform avatar, Transform head, List<Vector3> core)
            {
                List<Vector3> points = new List<Vector3>();
                SkinnedMeshRenderer[] renderers = avatar.GetComponentsInChildren<SkinnedMeshRenderer>(false);
                Mesh baked = new Mesh();
                try
                {
                    foreach (SkinnedMeshRenderer renderer in renderers)
                    {
                        Mesh mesh = renderer.sharedMesh;
                        Transform[] bones = renderer.bones;
                        if (mesh == null || bones == null || bones.Length == 0 || !mesh.isReadable)
                        {
                            continue;
                        }

                        bool[] headBone = new bool[bones.Length];
                        bool[] headOnly = new bool[bones.Length];
                        bool any = false;
                        for (int i = 0; i < bones.Length; i++)
                        {
                            headBone[i] = bones[i] != null && (bones[i] == head || bones[i].IsChildOf(head));
                            headOnly[i] = bones[i] == head;
                            any |= headBone[i];
                        }

                        if (!any)
                        {
                            continue;
                        }

                        BoneWeight[] weights = mesh.boneWeights;
                        if (weights == null || weights.Length != mesh.vertexCount)
                        {
                            continue;
                        }

                        renderer.BakeMesh(baked);
                        Vector3[] vertices = baked.vertices;
                        if (vertices.Length != weights.Length)
                        {
                            continue;
                        }

                        Matrix4x4 toHead = head.worldToLocalMatrix * renderer.transform.localToWorldMatrix;
                        for (int v = 0; v < vertices.Length; v++)
                        {
                            BoneWeight bw = weights[v];
                            float onHead = (Within(headBone, bw.boneIndex0) ? bw.weight0 : 0f)
                                           + (Within(headBone, bw.boneIndex1) ? bw.weight1 : 0f)
                                           + (Within(headBone, bw.boneIndex2) ? bw.weight2 : 0f)
                                           + (Within(headBone, bw.boneIndex3) ? bw.weight3 : 0f);
                            if (onHead >= 0.6f)
                            {
                                Vector3 local = toHead.MultiplyPoint3x4(vertices[v]);
                                points.Add(local);
                                float only = (Within(headOnly, bw.boneIndex0) ? bw.weight0 : 0f)
                                             + (Within(headOnly, bw.boneIndex1) ? bw.weight1 : 0f)
                                             + (Within(headOnly, bw.boneIndex2) ? bw.weight2 : 0f)
                                             + (Within(headOnly, bw.boneIndex3) ? bw.weight3 : 0f);
                                if (only >= 0.97f)
                                {
                                    core.Add(local);
                                }
                            }
                        }
                    }
                }
                finally
                {
                    Object.Destroy(baked);
                }

                return points;
            }

            private static bool Within(bool[] flags, int index)
            {
                return index >= 0 && index < flags.Length && flags[index];
            }
        }

        // ------------------------------------------------------------------
        // Brazo, mano y dedos
        // ------------------------------------------------------------------

        private enum HandShapeKind
        {
            /// <summary>Abierta, con los dedos un poco doblados (nunca en garra).</summary>
            Open,
            /// <summary>Colgando, algo más doblada.</summary>
            Relaxed,
            /// <summary>Abierta y algo curvada, para apoyarla en la cabeza.</summary>
            Cupped,
            /// <summary>Puño cerrado (bíceps).</summary>
            Fist,
            /// <summary>Puño suelto (bajo la barbilla).</summary>
            LooseFist
        }

        /// <summary>Un hueso que se toca: si nadie lo anima, se le devuelve lo que tenía antes de tocarlo.</summary>
        private sealed class Guard
        {
            public Transform Bone;
            private Quaternion _before;
            private Quaternion _written;
            private bool _touched;

            public Guard(Transform bone)
            {
                Bone = bone;
            }

            /// <summary>Al empezar el frame: si sigue lo que se escribió, nadie lo animó y vuelve a lo de antes.</summary>
            public void BeginFrame()
            {
                if (Bone == null)
                {
                    return;
                }

                if (_touched && Bone.localRotation == _written)
                {
                    Bone.localRotation = _before;
                }

                _before = Bone.localRotation;
                _touched = false;
            }

            /// <summary>Tras escribir: lo apunta.</summary>
            public void Wrote()
            {
                if (Bone == null)
                {
                    return;
                }

                _written = Bone.localRotation;
                _touched = true;
            }

            public void Restore()
            {
                if (Bone != null && _touched && Bone.localRotation == _written)
                {
                    Bone.localRotation = _before;
                }

                _touched = false;
            }
        }

        private sealed class Finger
        {
            public readonly Transform[] Bones = new Transform[3];
            public readonly Vector3[] Along = new Vector3[3];
            public readonly Guard[] Guards = new Guard[3];
            public readonly float[] Lengths = new float[3];
            public bool Valid;
        }

        private sealed class Arm
        {
            private readonly bool _isLeft;
            private Transform _clavicle;
            private Transform _upper;
            private Transform _lower;
            private Transform _hand;
            private Guard _clavicleGuard;
            private Guard _upperGuard;
            private Guard _lowerGuard;
            private Guard _handGuard;
            private readonly Finger[] _fingers = new Finger[4];
            private readonly Finger _thumb = new Finger();
            private Vector3 _fingerLocal;
            private Vector3 _thumbLocal;
            private Vector3 _hingeLocal;
            private bool _hingeKnown;
            private float _upperLength;
            private float _lowerLength;
            private float _palm;

            public Arm(bool isLeft)
            {
                _isLeft = isLeft;
                for (int i = 0; i < _fingers.Length; i++)
                {
                    _fingers[i] = new Finger();
                }
            }

            public bool IsLeft
            {
                get { return _isLeft; }
            }

            public Vector3 ShoulderPosition
            {
                get { return _upper != null ? _upper.position : Vector3.zero; }
            }

            public float UpperLength
            {
                get { return _upperLength; }
            }

            public float LowerLength
            {
                get { return _lowerLength; }
            }

            /// <summary>Hombro a muñeca con el brazo estirado.</summary>
            public float ArmLength
            {
                get { return _upperLength + _lowerLength; }
            }

            /// <summary>Hombro a la palma (nudillo del medio) con el brazo estirado.</summary>
            public float Reach
            {
                get { return _upperLength + _lowerLength + _palm; }
            }

            /// <summary>Muñeca al nudillo del medio.</summary>
            public float Palm
            {
                get { return _palm; }
            }

            /// <summary>Hacia fuera del cuerpo por este lado.</summary>
            public Vector3 Outward(Vector3 right)
            {
                return _isLeft ? -right : right;
            }

            public bool Bind(Animator animator)
            {
                _clavicle = animator.GetBoneTransform(_isLeft ? HumanBodyBones.LeftShoulder : HumanBodyBones.RightShoulder);
                _upper = animator.GetBoneTransform(_isLeft ? HumanBodyBones.LeftUpperArm : HumanBodyBones.RightUpperArm);
                _lower = animator.GetBoneTransform(_isLeft ? HumanBodyBones.LeftLowerArm : HumanBodyBones.RightLowerArm);
                _hand = animator.GetBoneTransform(_isLeft ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand);
                if (_upper == null || _lower == null || _hand == null)
                {
                    return false;
                }

                _clavicleGuard = new Guard(_clavicle);
                _upperGuard = new Guard(_upper);
                _lowerGuard = new Guard(_lower);
                _handGuard = new Guard(_hand);
                _upperLength = (_lower.position - _upper.position).magnitude;
                _lowerLength = (_hand.position - _lower.position).magnitude;

                HumanBodyBones[,] chains = _isLeft
                    ? new[,]
                    {
                        { HumanBodyBones.LeftIndexProximal, HumanBodyBones.LeftIndexIntermediate, HumanBodyBones.LeftIndexDistal },
                        { HumanBodyBones.LeftMiddleProximal, HumanBodyBones.LeftMiddleIntermediate, HumanBodyBones.LeftMiddleDistal },
                        { HumanBodyBones.LeftRingProximal, HumanBodyBones.LeftRingIntermediate, HumanBodyBones.LeftRingDistal },
                        { HumanBodyBones.LeftLittleProximal, HumanBodyBones.LeftLittleIntermediate, HumanBodyBones.LeftLittleDistal },
                        { HumanBodyBones.LeftThumbProximal, HumanBodyBones.LeftThumbIntermediate, HumanBodyBones.LeftThumbDistal }
                    }
                    : new[,]
                    {
                        { HumanBodyBones.RightIndexProximal, HumanBodyBones.RightIndexIntermediate, HumanBodyBones.RightIndexDistal },
                        { HumanBodyBones.RightMiddleProximal, HumanBodyBones.RightMiddleIntermediate, HumanBodyBones.RightMiddleDistal },
                        { HumanBodyBones.RightRingProximal, HumanBodyBones.RightRingIntermediate, HumanBodyBones.RightRingDistal },
                        { HumanBodyBones.RightLittleProximal, HumanBodyBones.RightLittleIntermediate, HumanBodyBones.RightLittleDistal },
                        { HumanBodyBones.RightThumbProximal, HumanBodyBones.RightThumbIntermediate, HumanBodyBones.RightThumbDistal }
                    };
                for (int f = 0; f < 5; f++)
                {
                    Finger finger = f < 4 ? _fingers[f] : _thumb;
                    BindFinger(animator, finger, chains[f, 0], chains[f, 1], chains[f, 2]);
                }

                // Ejes de la mano en el espacio del hueso (como TriviaHat): hacia el nudillo
                // del medio y hacia el lado del pulgar (del meñique al índice).
                Transform middle = _fingers[1].Bones[0];
                Transform index = _fingers[0].Bones[0];
                Transform little = _fingers[3].Bones[0];
                Vector3 finger3 = middle != null ? _hand.InverseTransformPoint(middle.position) : Vector3.zero;
                if (finger3.sqrMagnitude < 1e-8f)
                {
                    finger3 = _hand.InverseTransformDirection(_hand.position - _lower.position);
                }

                _palm = middle != null ? Mathf.Max(0.02f, (middle.position - _hand.position).magnitude) : 0.06f;
                finger3.Normalize();
                Vector3 thumbSide = index != null && little != null
                    ? _hand.InverseTransformPoint(index.position) - _hand.InverseTransformPoint(little.position)
                    : Vector3.up;
                thumbSide = Vector3.ProjectOnPlane(thumbSide, finger3);
                if (thumbSide.sqrMagnitude < 1e-8f)
                {
                    thumbSide = Vector3.ProjectOnPlane(Vector3.up, finger3);
                }

                _fingerLocal = finger3;
                _thumbLocal = thumbSide.normalized;
                _hingeKnown = false;
                UpdateHinge();
                return true;
            }

            private static void BindFinger(Animator animator, Finger finger, HumanBodyBones a, HumanBodyBones b, HumanBodyBones c)
            {
                finger.Bones[0] = animator.GetBoneTransform(a);
                finger.Bones[1] = animator.GetBoneTransform(b);
                finger.Bones[2] = animator.GetBoneTransform(c);
                finger.Valid = finger.Bones[0] != null && finger.Bones[1] != null;
                if (!finger.Valid)
                {
                    return;
                }

                for (int i = 0; i < 3; i++)
                {
                    Transform bone = finger.Bones[i];
                    if (bone == null)
                    {
                        continue;
                    }

                    finger.Guards[i] = new Guard(bone);
                    Transform next = i < 2 ? finger.Bones[i + 1] : (bone.childCount > 0 ? bone.GetChild(0) : null);
                    Vector3 along;
                    if (next != null && (next.position - bone.position).sqrMagnitude > 1e-8f)
                    {
                        along = bone.InverseTransformDirection(next.position - bone.position);
                    }
                    else
                    {
                        // La última falange sin punta: sigue la dirección de la anterior.
                        Transform previous = finger.Bones[i - 1];
                        along = bone.InverseTransformDirection(bone.position - previous.position);
                    }

                    finger.Along[i] = along.sqrMagnitude > 1e-10f ? along.normalized : Vector3.right;
                    float length = next != null ? (next.position - bone.position).magnitude : 0f;
                    finger.Lengths[i] = length > 1e-4f ? length : (i > 0 ? finger.Lengths[i - 1] * 0.8f : 0.03f);
                }
            }

            /// <summary>Al empezar el frame: lo que nadie animó vuelve a lo de antes y se apunta la bisagra del codo.</summary>
            public void BeginFrame()
            {
                if (_upper == null)
                {
                    return;
                }

                _clavicleGuard.BeginFrame();
                _upperGuard.BeginFrame();
                _lowerGuard.BeginFrame();
                _handGuard.BeginFrame();
                ForEachFingerGuard(g => g.BeginFrame());
                UpdateHinge();
            }

            public void Restore()
            {
                if (_upper == null)
                {
                    return;
                }

                ForEachFingerGuard(g => g.Restore());
                _handGuard.Restore();
                _lowerGuard.Restore();
                _upperGuard.Restore();
                _clavicleGuard.Restore();
            }

            private void ForEachFingerGuard(System.Action<Guard> action)
            {
                for (int f = 0; f < 5; f++)
                {
                    Finger finger = f < 4 ? _fingers[f] : _thumb;
                    if (!finger.Valid)
                    {
                        continue;
                    }

                    for (int i = 0; i < 3; i++)
                    {
                        if (finger.Guards[i] != null)
                        {
                            action(finger.Guards[i]);
                        }
                    }
                }
            }

            /// <summary>La bisagra del codo en el espacio del brazo, sacada de la pose animada cuando el codo está doblado.</summary>
            private void UpdateHinge()
            {
                Vector3 upperDir = _lower.position - _upper.position;
                Vector3 lowerDir = _hand.position - _lower.position;
                Vector3 hinge = Vector3.Cross(upperDir, lowerDir);
                float bend = Vector3.Angle(upperDir, lowerDir);
                if (bend > 12f && hinge.sqrMagnitude > 1e-10f)
                {
                    _hingeLocal = _upper.InverseTransformDirection(hinge.normalized);
                    _hingeKnown = true;
                }
            }

            /// <summary>Sube (o baja) el hombro <paramref name="degrees"/> grados.</summary>
            public void Shrug(Vector3 up, float degrees)
            {
                if (_clavicle == null || Mathf.Abs(degrees) < 0.01f)
                {
                    return;
                }

                Vector3 dir = _upper.position - _clavicle.position;
                if (dir.sqrMagnitude < 1e-8f)
                {
                    return;
                }

                Vector3 axis = Vector3.Cross(dir.normalized, up);
                if (axis.sqrMagnitude < 1e-8f)
                {
                    return;
                }

                _clavicle.rotation = Quaternion.AngleAxis(degrees, axis.normalized) * _clavicle.rotation;
                _clavicleGuard.Wrote();
            }

            /// <summary>
            /// IK de dos huesos hacia <paramref name="target"/> (la muñeca), con el codo hacia
            /// <paramref name="pole"/>, mezclado con la pose animada por <paramref name="weight"/>.
            /// El brazo gira sobre su eje para que el codo doble por su bisagra.
            /// </summary>
            public void Solve(Vector3 target, Vector3 pole, float weight)
            {
                if (_upper == null || weight <= 0f)
                {
                    return;
                }

                Vector3 shoulder = _upper.position;
                Vector3 elbow = _lower.position;
                Vector3 wrist = _hand.position;
                float upper = _upperLength;
                float lower = _lowerLength;
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
                float distance = Mathf.Clamp(toGoal.magnitude, Mathf.Abs(upper - lower) + 0.002f, upper + lower - 0.002f);
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

                // 1. El brazo apunta al codo nuevo.
                _upper.rotation = Quaternion.FromToRotation(elbow - shoulder, elbowGoal - shoulder) * _upper.rotation;

                // 2. Gira sobre su eje para que la bisagra del codo quede en el plano de la pose.
                Vector3 upperAxis = (elbowGoal - shoulder).normalized;
                Vector3 wantedHinge = Vector3.Cross(elbowGoal - shoulder, wristGoal - elbowGoal);
                if (_hingeKnown && wantedHinge.sqrMagnitude > 1e-8f && Vector3.Angle(elbowGoal - shoulder, wristGoal - elbowGoal) > 8f)
                {
                    Vector3 hingeNow = Vector3.ProjectOnPlane(_upper.TransformDirection(_hingeLocal), upperAxis);
                    Vector3 hingeWanted = Vector3.ProjectOnPlane(wantedHinge.normalized, upperAxis);
                    if (hingeNow.sqrMagnitude > 1e-8f && hingeWanted.sqrMagnitude > 1e-8f)
                    {
                        float twist = Vector3.SignedAngle(hingeNow, hingeWanted, upperAxis);
                        _upper.rotation = Quaternion.AngleAxis(twist * weight, upperAxis) * _upper.rotation;
                    }
                }

                _upperGuard.Wrote();

                // 3. El antebrazo apunta a la muñeca.
                Vector3 newElbow = _lower.position;
                _lower.rotation = Quaternion.FromToRotation(_hand.position - newElbow, wristGoal - newElbow) * _lower.rotation;
                _lowerGuard.Wrote();
            }

            /// <summary>
            /// Orienta la mano: dedos hacia <paramref name="fingers"/> y la palma hacia
            /// <paramref name="palm"/>. El antebrazo se lleva la mitad del giro.
            /// </summary>
            public void Orient(Vector3 fingers, Vector3 palm, float weight)
            {
                if (_hand == null || weight <= 0f)
                {
                    return;
                }

                fingers.Normalize();
                palm = Vector3.ProjectOnPlane(palm, fingers);
                if (palm.sqrMagnitude < 1e-8f)
                {
                    return;
                }

                palm.Normalize();
                Vector3 thumb = _isLeft ? Vector3.Cross(fingers, palm) : Vector3.Cross(palm, fingers);
                Quaternion localFrame = Quaternion.LookRotation(_fingerLocal, _thumbLocal);
                Quaternion target = Quaternion.LookRotation(fingers, thumb) * Quaternion.Inverse(localFrame);

                // Reparto del giro sobre el eje del antebrazo: la mitad para el antebrazo.
                Vector3 axis = (_hand.position - _lower.position).normalized;
                Quaternion delta = target * Quaternion.Inverse(_hand.rotation);
                float twist = TwistAngle(delta, axis);
                if (Mathf.Abs(twist) > 0.5f)
                {
                    _lower.rotation = Quaternion.AngleAxis(twist * 0.5f * weight, axis) * _lower.rotation;
                    _lowerGuard.Wrote();
                }

                _hand.rotation = Quaternion.Slerp(_hand.rotation, target, weight);
                _handGuard.Wrote();
            }

            /// <summary>Forma de los dedos (con la mano ya orientada).</summary>
            public void Shape(HandShapeKind kind, float weight)
            {
                if (_hand == null || weight <= 0f)
                {
                    return;
                }

                Vector3 fingers = _hand.TransformDirection(_fingerLocal);
                Vector3 thumbSide = _hand.TransformDirection(_thumbLocal);
                Vector3 palm = _isLeft ? Vector3.Cross(thumbSide, fingers) : Vector3.Cross(fingers, thumbSide);
                palm.Normalize();

                // Curvas por falange (grados hacia la palma) y abanico (grados hacia el pulgar).
                Vector3 curls;
                float[] spread = { 5f, 0f, -4f, -9f };
                switch (kind)
                {
                    case HandShapeKind.Fist:
                        curls = new Vector3(78f, 98f, 55f);
                        spread = new[] { 2f, 0f, -2f, -4f };
                        break;
                    case HandShapeKind.LooseFist:
                        curls = new Vector3(62f, 78f, 40f);
                        spread = new[] { 2f, 0f, -2f, -5f };
                        break;
                    case HandShapeKind.Relaxed:
                        curls = new Vector3(14f, 24f, 12f);
                        break;
                    case HandShapeKind.Cupped:
                        curls = new Vector3(12f, 16f, 10f);
                        spread = new[] { 4f, 0f, -3f, -7f };
                        break;
                    default:
                        curls = new Vector3(7f, 10f, 7f);
                        break;
                }

                for (int f = 0; f < 4; f++)
                {
                    Finger finger = _fingers[f];
                    if (!finger.Valid)
                    {
                        continue;
                    }

                    // El meñique y el anular se cierran un poco más (como una mano de verdad).
                    float extra = kind == HandShapeKind.Fist || kind == HandShapeKind.LooseFist ? 0f : f * 2.5f;
                    float side = _isLeft ? -spread[f] : spread[f];
                    Vector3 baseDir = Quaternion.AngleAxis(side, palm) * fingers;
                    Vector3 hinge = Vector3.Cross(baseDir, palm).normalized;
                    float a1 = curls.x + extra;
                    float a2 = a1 + curls.y + extra;
                    float a3 = a2 + curls.z;
                    Aim(finger, 0, Quaternion.AngleAxis(a1, hinge) * baseDir, weight);
                    Aim(finger, 1, Quaternion.AngleAxis(a2, hinge) * baseDir, weight);
                    Aim(finger, 2, Quaternion.AngleAxis(a3, hinge) * baseDir, weight);
                }

                if (!_thumb.Valid)
                {
                    return;
                }

                // Pulgar: abierto, hacia delante y a su lado, casi en el plano de la palma;
                // en el puño, con la punta sobre el índice y el corazón doblados (ThumbOverFist).
                if (kind == HandShapeKind.Fist && ThumbOverFist(fingers, thumbSide, palm, weight))
                {
                    return;
                }

                Vector3 t1, t2, t3;
                if (kind == HandShapeKind.Fist || kind == HandShapeKind.LooseFist)
                {
                    t1 = ((fingers * 0.4f) + (thumbSide * 0.3f) + (palm * 0.85f)).normalized;
                    t2 = ((fingers * 0.3f) - (thumbSide * 0.65f) + (palm * 0.7f)).normalized;
                    t3 = ((fingers * 0.05f) - (thumbSide * 0.95f) + (palm * 0.3f)).normalized;
                }
                else
                {
                    t1 = ((fingers * 0.55f) + (thumbSide * 0.75f) + (palm * 0.22f)).normalized;
                    t2 = ((fingers * 0.85f) + (thumbSide * 0.42f) + (palm * 0.12f)).normalized;
                    t3 = ((fingers * 0.92f) + (thumbSide * 0.25f) + (palm * 0.18f)).normalized;
                }

                Aim(_thumb, 0, t1, weight);
                Aim(_thumb, 1, t2, weight);
                Aim(_thumb, 2, t3, weight);
            }

            /// <summary>
            /// Pulgar del puño: el metacarpiano hacia la palma y la punta apoyada por fuera
            /// sobre las falanges medias del índice y el corazón ya doblados (IK de dos
            /// huesos con el nudillo del pulgar hacia fuera). Falso si faltan huesos.
            /// </summary>
            private bool ThumbOverFist(Vector3 fingers, Vector3 thumbSide, Vector3 palm, float weight)
            {
                Transform i2 = _fingers[0].Bones[1];
                Transform i3 = _fingers[0].Bones[2];
                Transform m2 = _fingers[1].Bones[1];
                Transform m3 = _fingers[1].Bones[2];
                if (i2 == null || i3 == null || m2 == null || m3 == null || _thumb.Bones[2] == null)
                {
                    return false;
                }

                // Donde apoya la punta: sobre la falange media del índice doblado, por su lado
                // del pulgar, pegada al puño (sin asomar por delante de los dedos).
                Vector3 face = Vector3.Lerp(i2.position, i3.position, 0.45f);
                face += thumbSide * (_palm * 0.13f);
                face += palm * (_palm * 0.05f);

                // El metacarpiano, junto al del índice: hacia arriba, a su lado y algo hacia la palma.
                Aim(_thumb, 0, ((fingers * 0.65f) + (thumbSide * 0.4f) + (palm * 0.45f)).normalized, weight);

                // Falange proximal y distal: dos huesos hasta la punta, con el nudillo hacia fuera.
                Vector3 start = _thumb.Bones[1].position;
                float l2 = _thumb.Lengths[1];
                float l3 = _thumb.Lengths[2];
                Vector3 toFace = face - start;
                float distance = toFace.magnitude;
                if (distance < 1e-4f)
                {
                    return true;
                }

                Vector3 direction = toFace / distance;
                Vector3 joint;
                if (distance >= l2 + l3)
                {
                    joint = start + (direction * l2);
                }
                else
                {
                    float along = ((l2 * l2) - (l3 * l3) + (distance * distance)) / (2f * distance);
                    float height = Mathf.Sqrt(Mathf.Max(0f, (l2 * l2) - (along * along)));
                    Vector3 bend = Vector3.ProjectOnPlane(thumbSide + (fingers * 0.4f), direction);
                    bend = bend.sqrMagnitude > 1e-8f ? bend.normalized : palm;
                    joint = start + (direction * along) + (bend * height);
                }

                Aim(_thumb, 1, (joint - start).normalized, weight);
                Vector3 tipStart = _thumb.Bones[2].position;
                Aim(_thumb, 2, (face - tipStart).normalized, weight);
                return true;
            }

            private static void Aim(Finger finger, int index, Vector3 direction, float weight)
            {
                Transform bone = finger.Bones[index];
                if (bone == null || direction.sqrMagnitude < 1e-8f)
                {
                    return;
                }

                Vector3 now = bone.rotation * finger.Along[index];
                Quaternion target = Quaternion.FromToRotation(now, direction) * bone.rotation;
                bone.rotation = Quaternion.Slerp(bone.rotation, target, weight);
                if (finger.Guards[index] != null)
                {
                    finger.Guards[index].Wrote();
                }
            }

            /// <summary>Ángulo (grados) del giro de <paramref name="rotation"/> alrededor de <paramref name="axis"/> (descomposición giro-columpio).</summary>
            private static float TwistAngle(Quaternion rotation, Vector3 axis)
            {
                Vector3 r = new Vector3(rotation.x, rotation.y, rotation.z);
                Vector3 p = Vector3.Project(r, axis);
                Quaternion twist = new Quaternion(p.x, p.y, p.z, rotation.w);
                float mag = Mathf.Sqrt((twist.x * twist.x) + (twist.y * twist.y) + (twist.z * twist.z) + (twist.w * twist.w));
                if (mag < 1e-6f)
                {
                    return 0f;
                }

                twist = new Quaternion(twist.x / mag, twist.y / mag, twist.z / mag, twist.w / mag);
                float angle;
                Vector3 twistAxis;
                twist.ToAngleAxis(out angle, out twistAxis);
                if (angle > 180f)
                {
                    angle -= 360f;
                }

                return Vector3.Dot(twistAxis, axis) >= 0f ? angle : -angle;
            }
        }
    }
}
