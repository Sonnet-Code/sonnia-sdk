// La mano de Sonnia en piedra, papel o tijera (docs/juegos/piedra_papel_tijera.md).
//
// Sonnia sube el brazo derecho y enseña la mano a la cámara delante del pecho,
// como quien enseña un gesto: palma hacia el público y dedos hacia arriba, que
// es como mejor se lee piedra, papel o tijera en la pantalla vertical (con los
// dedos apuntando a la cámara, el papel se vería de canto).
//
//   Raise         sube el puño (el «preparados» de antes de la cuenta).
//   BeginCount    agita el puño con la frase grabada «¡Piedra, papel o tijera…
//                 ya!»: tres golpes hacia abajo y, en el cuarto (el «¡ya!»), la
//                 mano se abre en su forma. El reloj lo da el controlador
//                 (sincronizado con el audio de la frase); sin «ya» conocido,
//                 agita en bucle hasta Reveal.
//   Reveal        enseña ya la forma (el «¡ya!» del orquestador).
//   Show          la forma de golpe, sin cuenta (al reconectar).
//   Lower         baja el brazo y la mano vuelve a la animación.
//
// El brazo va con IK de dos huesos (hombro, codo, muñeca) encima de lo que
// suene, como el gorro de la trivia (TriviaHat), y la muñeca se orienta con los
// ejes de la mano medidos en el hueso. Los dedos se mueven con los músculos del
// humanoide: al enganchar el avatar se calcula, con HumanPoseHandler, la
// rotación local de cada falange para cada forma (puño, papel y tijera), y luego
// cada fotograma solo se mezclan esas rotaciones con las de la animación, sin
// tocar el resto del cuerpo. Los valores de los músculos están en el inspector
// (y en código para el componente que se añade en Play).
//
// Corre en LateUpdate al final (12650: tras la cara, la cabeza, los ojos y el
// gorro de la trivia), así que nadie pisa el brazo mientras enseña la mano.

using System;
using UnityEngine;

namespace Sonia.Games.Ppt
{
    /// <summary>Forma de la mano de Sonnia.</summary>
    public enum PptHand
    {
        /// <summary>Puño cerrado (la piedra y la cuenta).</summary>
        Rock = 0,
        Paper = 1,
        Scissors = 2,
    }

    /// <summary>Músculos de un dedo del humanoide (-1 cerrado, 1 estirado).</summary>
    [Serializable]
    public struct FingerMuscles
    {
        [Range(-1f, 1f)] public float Stretch1;
        [Range(-1f, 1f)] public float Spread;
        [Range(-1f, 1f)] public float Stretch2;
        [Range(-1f, 1f)] public float Stretch3;

        public FingerMuscles(float stretch1, float spread, float stretch2, float stretch3)
        {
            Stretch1 = stretch1;
            Spread = spread;
            Stretch2 = stretch2;
            Stretch3 = stretch3;
        }
    }

    /// <summary>Músculos de los cinco dedos para una forma de la mano.</summary>
    [Serializable]
    public class HandMuscles
    {
        public FingerMuscles Thumb;
        public FingerMuscles Index;
        public FingerMuscles Middle;
        public FingerMuscles Ring;
        public FingerMuscles Little;

        /// <summary>
        /// Cuánto más se doblan los dedos cerrados (índice a meñique con «1 Stretched»
        /// negativo) que lo que permiten los límites del avatar: 1 es lo del músculo; con
        /// más, el puño se cierra del todo (los límites de Unity dejan la mano en garra).
        /// </summary>
        [Range(1f, 2.5f)] public float Curl = 1f;

        /// <summary>Lo mismo para el pulgar si va cerrado.</summary>
        [Range(1f, 2.5f)] public float ThumbCurl = 1f;

        public HandMuscles()
        {
        }

        public HandMuscles(FingerMuscles thumb, FingerMuscles index, FingerMuscles middle, FingerMuscles ring, FingerMuscles little, float curl = 1f, float thumbCurl = 1f)
        {
            Thumb = thumb;
            Index = index;
            Middle = middle;
            Ring = ring;
            Little = little;
            Curl = curl;
            ThumbCurl = thumbCurl;
        }

        public FingerMuscles Finger(int finger)
        {
            switch (finger)
            {
                case 0: return Thumb;
                case 1: return Index;
                case 2: return Middle;
                case 3: return Ring;
                default: return Little;
            }
        }
    }

    /// <summary>Sube el brazo derecho de Sonnia y enseña piedra, papel o tijera con los dedos.</summary>
    [DefaultExecutionOrder(12650)]
    [DisallowMultipleComponent]
    public class SoniaHandPoser : MonoBehaviour
    {
        [Header("Brazo (metros, respecto al hombro derecho: x a su derecha, y arriba, z hacia la cámara)")]
        [SerializeField]
        [Tooltip("Dónde va la muñeca con el puño arriba, antes de cada golpe.")]
        private Vector3 wristOffset = new Vector3(-0.04f, -0.2f, 0.27f);

        [SerializeField]
        [Tooltip("Hacia dónde va el codo (pista del IK), respecto al hombro.")]
        private Vector3 elbowHint = new Vector3(0.32f, -0.42f, -0.08f);

        [SerializeField]
        [Tooltip("Hacia dónde apuntan los dedos (en los ejes del avatar): casi arriba, un poco hacia la cámara y hacia dentro.")]
        private Vector3 fingersDirection = new Vector3(-0.12f, 1f, 0.12f);

        [SerializeField]
        [Tooltip("Hacia dónde mira la palma (en los ejes del avatar): al público.")]
        private Vector3 palmDirection = new Vector3(0f, 0f, 1f);

        [Header("Cuenta")]
        [SerializeField]
        [Range(0f, 0.2f)]
        [Tooltip("Cuánto baja el puño en cada golpe, en metros.")]
        private float pumpDrop = 0.09f;

        [SerializeField]
        [Range(0f, 40f)]
        [Tooltip("Cuánto se inclina el puño hacia delante en cada golpe, en grados (como un martillo).")]
        private float pumpTilt = 20f;

        [SerializeField]
        [Range(0.2f, 1f)]
        [Tooltip("Segundos de cada golpe si no se sabe cuándo cae el «¡ya!» (agita en bucle).")]
        private float loopBeatSeconds = 0.42f;

        [SerializeField]
        [Range(0f, 0.1f)]
        [Tooltip("Cuánto avanza la mano hacia la cámara al enseñarla, en metros.")]
        private float revealPush = 0.035f;

        [Header("Tiempos")]
        [SerializeField]
        [Range(0.1f, 1f)]
        [Tooltip("Segundos para subir el brazo.")]
        private float raiseSeconds = 0.4f;

        [SerializeField]
        [Range(0.1f, 1.5f)]
        [Tooltip("Segundos para bajarlo.")]
        private float lowerSeconds = 0.55f;

        [SerializeField]
        [Range(0.04f, 0.4f)]
        [Tooltip("Segundos en que la mano pasa del puño a su forma.")]
        private float revealSeconds = 0.13f;

        [SerializeField]
        [Range(1f, 20f)]
        [Tooltip("Tope de segundos con el brazo arriba sin que nadie lo baje (por si se pierde un mensaje).")]
        private float maxHoldSeconds = 9f;

        // Valores elegidos el 10 de octubre de 2026 en una galería de variantes renderizadas
        // con el avatar de Sonnia (laboratorio en batch): con los límites de Unity el puño
        // se queda en garra, así que los dedos cerrados se doblan 1,9 veces lo del músculo y
        // el pulgar, 1,4 veces, cruzado por delante de los dedos como en ✊.
        [Header("Dedos (músculos del humanoide: -1 cerrado, 1 estirado)")]
        [SerializeField]
        private HandMuscles rock = new HandMuscles(
            new FingerMuscles(-0.5f, -0.5f, -1f, -1f),
            new FingerMuscles(-1f, 0f, -1f, -1f),
            new FingerMuscles(-1f, 0f, -1f, -1f),
            new FingerMuscles(-1f, 0f, -1f, -1f),
            new FingerMuscles(-1f, 0f, -1f, -1f),
            1.9f,
            1.4f);

        [SerializeField]
        private HandMuscles paper = new HandMuscles(
            new FingerMuscles(0.25f, 0.45f, 0.45f, 0.4f),
            new FingerMuscles(0.7f, 0.35f, 0.75f, 0.7f),
            new FingerMuscles(0.7f, 0.1f, 0.75f, 0.7f),
            new FingerMuscles(0.7f, -0.2f, 0.75f, 0.7f),
            new FingerMuscles(0.7f, -0.45f, 0.75f, 0.7f));

        [SerializeField]
        private HandMuscles scissors = new HandMuscles(
            new FingerMuscles(-0.5f, -0.5f, -1f, -1f),
            new FingerMuscles(0.7f, 0.85f, 0.75f, 0.7f),
            new FingerMuscles(0.7f, -0.85f, 0.75f, 0.7f),
            new FingerMuscles(-1f, 0f, -1f, -1f),
            new FingerMuscles(-1f, 0f, -1f, -1f),
            1.9f,
            1.4f);

        [SerializeField]
        [Tooltip("Escribir en la consola lo que hace la mano.")]
        private bool logEvents = true;

        private static readonly HumanBodyBones[] FingerBones =
        {
            HumanBodyBones.RightThumbProximal, HumanBodyBones.RightThumbIntermediate, HumanBodyBones.RightThumbDistal,
            HumanBodyBones.RightIndexProximal, HumanBodyBones.RightIndexIntermediate, HumanBodyBones.RightIndexDistal,
            HumanBodyBones.RightMiddleProximal, HumanBodyBones.RightMiddleIntermediate, HumanBodyBones.RightMiddleDistal,
            HumanBodyBones.RightRingProximal, HumanBodyBones.RightRingIntermediate, HumanBodyBones.RightRingDistal,
            HumanBodyBones.RightLittleProximal, HumanBodyBones.RightLittleIntermediate, HumanBodyBones.RightLittleDistal,
        };

        private static readonly string[] FingerNames = { "Thumb", "Index", "Middle", "Ring", "Little" };

        private const int ShapeCount = 3;

        private AvatarBinder _binder;
        private Transform _avatar;
        private Animator _animator;
        private Transform _shoulder;
        private Transform _elbow;
        private Transform _wrist;
        private readonly Transform[] _fingers = new Transform[FingerBones.Length];
        private readonly Quaternion[,] _targets = new Quaternion[ShapeCount, FingerBones.Length];
        private Vector3 _fingerLocal = Vector3.forward;
        private Vector3 _thumbLocal = Vector3.up;
        private bool _bound;
        private bool _fingersReady;
        private bool _warnedFingers;
        private bool _broken;

        // Estado de la mano.
        private bool _up;
        private float _blend;
        private float _raisedAt = -1f;
        private bool _counting;
        private float _go = -1f;
        private Func<float> _clock;
        private float _countStart;
        private bool _revealed;
        private float _revealedAt = -1f;
        // _shape es la jugada que enseñará (o enseña) en el «¡ya!»; los dedos muestran
        // _shownTo, pasando de _shownFrom en revealSeconds desde _shownAt.
        private PptHand _shape = PptHand.Rock;
        private PptHand _shownFrom = PptHand.Rock;
        private PptHand _shownTo = PptHand.Rock;
        private float _shownAt = -10f;

        /// <summary>Cierto si hay avatar con brazo y mano derechos.</summary>
        public bool IsBound
        {
            get { return _bound; }
        }

        /// <summary>Cierto si los dedos pueden tomar las formas (el avatar es humanoide con dedos).</summary>
        public bool CanShapeFingers
        {
            get { return _bound && _fingersReady; }
        }

        /// <summary>Cierto con el brazo arriba o subiendo (lo que pide el juego).</summary>
        public bool IsUp
        {
            get { return _up; }
        }

        /// <summary>Peso actual del brazo (0 abajo, 1 arriba del todo), para pruebas.</summary>
        public float Weight
        {
            get { return Smooth(_blend); }
        }

        /// <summary>Cierto si la mano ya enseña su forma (pasó el «¡ya!»).</summary>
        public bool IsRevealed
        {
            get { return _revealed; }
        }

        /// <summary>La forma que enseña (o enseñará) la mano.</summary>
        public PptHand Shape
        {
            get { return _shape; }
        }

        private void Awake()
        {
            _binder = GetComponentInChildren<AvatarBinder>(true);
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

            _up = false;
            _blend = 0f;
            _counting = false;
        }

        // ------------------------------------------------------------------
        // API (la usa PptController)
        // ------------------------------------------------------------------

        /// <summary>Sube el puño delante del pecho («preparados»).</summary>
        public void Raise()
        {
            if (!_up)
            {
                _raisedAt = Time.time;
            }

            _up = true;
            _counting = false;
            _revealed = false;
            ShowFingers(PptHand.Rock, _blend <= 0f);
            Log("puño arriba");
        }

        /// <summary>
        /// Empieza la cuenta: el puño baja <c>3</c> veces y en el «¡ya!» se abre en
        /// <paramref name="shape"/>. <paramref name="goSeconds"/> es cuándo cae el «¡ya!» en
        /// el reloj <paramref name="clock"/> (segundos desde que empezó la frase; null:
        /// desde ahora). Con <paramref name="goSeconds"/> negativo no se sabe: agita en bucle
        /// hasta <see cref="Reveal"/>.
        /// </summary>
        public void BeginCount(PptHand shape, float goSeconds, Func<float> clock)
        {
            if (!_up)
            {
                Raise();
            }

            _shape = shape;
            ShowFingers(PptHand.Rock, false);
            _go = goSeconds;
            _clock = clock;
            _countStart = Time.time;
            _counting = true;
            _revealed = false;
            _raisedAt = Time.time;
            Log("cuenta con " + shape + (goSeconds > 0f ? " («ya» a " + goSeconds.ToString("0.00") + " s)" : " (sin «ya» conocido)"));
        }

        /// <summary>El «¡ya!»: la mano se abre en su forma (si no se había abierto ya).</summary>
        public void Reveal()
        {
            if (_revealed)
            {
                return;
            }

            if (!_up)
            {
                Raise();
            }

            _revealed = true;
            _counting = false;
            _revealedAt = Time.time;
            _raisedAt = Time.time;
            ShowFingers(_shape, false);
            Log("enseña " + _shape);
        }

        /// <summary>Elige la forma que enseñará la mano en el «¡ya!» (sin enseñarla aún).</summary>
        public void Prepare(PptHand shape)
        {
            _shape = shape;
        }

        /// <summary>Enseña <paramref name="shape"/> ya, con el brazo arriba (al reconectar a mitad de un resultado).</summary>
        public void Show(PptHand shape)
        {
            _shape = shape;
            _up = true;
            _counting = false;
            _revealed = true;
            _revealedAt = Time.time;
            _raisedAt = Time.time;
            ShowFingers(shape, _blend <= 0f);
        }

        /// <summary>Baja el brazo: la mano vuelve a la animación.</summary>
        public void Lower()
        {
            if (_up)
            {
                Log("baja la mano");
            }

            _up = false;
            _counting = false;
        }

        /// <summary>Baja el brazo de golpe (al cerrar la pantalla del juego).</summary>
        public void Clear()
        {
            _up = false;
            _counting = false;
            _revealed = false;
            _blend = 0f;
        }

        /// <summary>Cambia los músculos de una forma (pruebas y ajuste) y recalcula los dedos.</summary>
        public void SetMuscles(PptHand shape, HandMuscles muscles)
        {
            if (muscles == null)
            {
                return;
            }

            switch (shape)
            {
                case PptHand.Paper:
                    paper = muscles;
                    break;
                case PptHand.Scissors:
                    scissors = muscles;
                    break;
                default:
                    rock = muscles;
                    break;
            }

            if (_bound)
            {
                _fingersReady = ComputeFingerTargets();
            }
        }

        // ------------------------------------------------------------------
        // Cada fotograma
        // ------------------------------------------------------------------

        private void LateUpdate()
        {
            if (_broken)
            {
                return;
            }

            try
            {
                Pose();
            }
            catch (Exception ex)
            {
                // Un fallo aquí se repetiría en cada fotograma: se avisa una vez y la mano se
                // queda con la animación (la jugada sigue saliendo en la tarjeta).
                _broken = true;
                _up = false;
                _blend = 0f;
                Debug.LogException(ex, this);
                Debug.LogWarning("[Sonia] Piedra, papel o tijera: la mano de Sonnia se apaga por un error.", this);
            }
        }

        private void Pose()
        {
            if (!_bound && (_up || _blend > 0f))
            {
                Bind();
            }

            float dt = Time.deltaTime;
            if (_up && Time.time - _raisedAt > maxHoldSeconds)
            {
                // Nadie lo bajó (un mensaje perdido): que no se quede así.
                Lower();
            }

            float rate = _up ? 1f / Mathf.Max(0.05f, raiseSeconds) : 1f / Mathf.Max(0.05f, lowerSeconds);
            _blend = Mathf.Clamp01(_blend + ((_up ? 1f : -1f) * rate * dt));
            if (!_bound || _blend <= 0f)
            {
                return;
            }

            if (_avatar == null || _shoulder == null || _elbow == null || _wrist == null)
            {
                _bound = false;
                return;
            }

            float weight = Smooth(_blend);

            // Cuenta: cuánto ha bajado el puño (0 arriba, 1 abajo) y si toca enseñar la mano.
            float drop = 0f;
            float push = 0f;
            if (_counting)
            {
                float t = CountTime();
                if (_go > 0f)
                {
                    drop = PumpDrop(t / (_go / 4f));
                    if (t >= _go)
                    {
                        Reveal();
                    }
                }
                else
                {
                    drop = LoopDrop(t / Mathf.Max(0.2f, loopBeatSeconds));
                }
            }

            if (_revealed)
            {
                // El último golpe: la mano baja, se abre y empuja un poco hacia el público.
                float since = Time.time - _revealedAt;
                drop = Mathf.Lerp(1f, 0.85f, Mathf.Clamp01(since / 0.25f));
                push = revealPush * GameUi.EaseOutBack(Mathf.Clamp01(since / 0.22f));
            }

            Vector3 right = _avatar.right;
            Vector3 up = _avatar.up;
            Vector3 forward = _avatar.forward;
            Vector3 shoulder = _shoulder.position;
            Vector3 target = shoulder + (right * wristOffset.x) + (up * wristOffset.y) + (forward * wristOffset.z);
            target += (-up * pumpDrop * drop) + (forward * push);
            Vector3 pole = shoulder + (right * elbowHint.x) + (up * elbowHint.y) + (forward * elbowHint.z);
            SolveArm(target, pole, weight);

            // La muñeca: dedos hacia arriba y la palma al público; en cada golpe el puño se inclina.
            Vector3 fingers = ((right * fingersDirection.x) + (up * fingersDirection.y) + (forward * fingersDirection.z)).normalized;
            Vector3 palm = ((right * palmDirection.x) + (up * palmDirection.y) + (forward * palmDirection.z)).normalized;
            Vector3 thumbSide = Vector3.Cross(palm, fingers);
            if (thumbSide.sqrMagnitude < 1e-6f)
            {
                thumbSide = -right;
            }

            // Mano derecha con los dedos arriba y la palma delante: el pulgar va hacia su izquierda.
            if (Vector3.Dot(thumbSide, right) > 0f)
            {
                thumbSide = -thumbSide;
            }

            Quaternion tilt = Quaternion.AngleAxis(pumpTilt * drop, thumbSide.normalized);
            Quaternion localFrame = Quaternion.LookRotation(_fingerLocal, _thumbLocal);
            Quaternion worldFrame = tilt * Quaternion.LookRotation(fingers, thumbSide.normalized);
            _wrist.rotation = Quaternion.Slerp(_wrist.rotation, worldFrame * Quaternion.Inverse(localFrame), weight);

            ApplyFingers(weight);
        }

        /// <summary>Segundos de la cuenta en el reloj del controlador (el audio de la frase) o desde que empezó.</summary>
        private float CountTime()
        {
            if (_clock != null)
            {
                try
                {
                    return _clock();
                }
                catch (Exception ex)
                {
                    Debug.LogException(ex, this);
                    _clock = null;
                }
            }

            return Time.time - _countStart;
        }

        /// <summary>
        /// Bajada del puño en la cuenta (0 arriba, 1 abajo), con <paramref name="beat"/> en
        /// golpes: baja en el 1, 2 y 3 y en el 4 (el «¡ya!»). Cada golpe baja rápido y sube
        /// más despacio, como al agitar el puño de verdad.
        /// </summary>
        private static float PumpDrop(float beat)
        {
            if (beat <= 0f)
            {
                return 0f;
            }

            if (beat < 1f)
            {
                // Del puño arriba al primer golpe.
                return GameUi.EaseInCubic(beat);
            }

            if (beat >= 4f)
            {
                return 1f;
            }

            return CycleDrop(beat - Mathf.Floor(beat));
        }

        /// <summary>Agitar en bucle (sin «¡ya!» conocido).</summary>
        private static float LoopDrop(float beat)
        {
            if (beat <= 0f)
            {
                return 0f;
            }

            if (beat < 1f)
            {
                return GameUi.EaseInCubic(beat);
            }

            return CycleDrop(beat - Mathf.Floor(beat));
        }

        /// <summary>Un golpe entero: sube del 0 al 55 % y baja de golpe hasta el final.</summary>
        private static float CycleDrop(float phase)
        {
            if (phase < 0.55f)
            {
                return 1f - GameUi.EaseOutCubic(phase / 0.55f);
            }

            return GameUi.EaseInCubic((phase - 0.55f) / 0.45f);
        }

        /// <summary>Los dedos pasan a <paramref name="shape"/> (en revealSeconds, o de golpe).</summary>
        private void ShowFingers(PptHand shape, bool instant)
        {
            if (instant)
            {
                _shownFrom = shape;
                _shownTo = shape;
                _shownAt = -10f;
                return;
            }

            if (shape == _shownTo && _shownAt < 0f)
            {
                return;
            }

            // Desde lo que se ve ahora (si estaba a medio cambiar, desde su destino).
            _shownFrom = _shownTo;
            _shownTo = shape;
            _shownAt = Time.time;
        }

        private void ApplyFingers(float weight)
        {
            if (!_fingersReady)
            {
                if (!_warnedFingers)
                {
                    _warnedFingers = true;
                    Debug.LogWarning("[Sonia] Piedra, papel o tijera: los dedos de este avatar no se pueden mover; la mano sale sin forma.", this);
                }

                return;
            }

            float change = _shownAt < 0f ? 1f : Mathf.Clamp01((Time.time - _shownAt) / Mathf.Max(0.01f, revealSeconds));
            change = GameUi.EaseOutCubic(change);
            int from = (int)_shownFrom;
            int to = (int)_shownTo;
            for (int i = 0; i < _fingers.Length; i++)
            {
                Transform bone = _fingers[i];
                if (bone == null)
                {
                    continue;
                }

                Quaternion shaped = Quaternion.Slerp(_targets[from, i], _targets[to, i], change);
                bone.localRotation = Quaternion.Slerp(bone.localRotation, shaped, weight);
            }
        }

        // ------------------------------------------------------------------
        // Montaje
        // ------------------------------------------------------------------

        private void HandleAvatarChanged(Transform avatar)
        {
            // Avatar nuevo (el SDK entregó otro o se cambió el aspecto): los huesos y
            // los dedos se recalculan con él.
            _bound = false;
            _fingersReady = false;
            _warnedFingers = false;
            _avatar = null;
            if (_up || _blend > 0f)
            {
                Bind();
            }
        }

        private void Bind()
        {
            Transform avatar = _binder != null ? _binder.Current : null;
            if (avatar == null && _binder == null)
            {
                _binder = GetComponentInChildren<AvatarBinder>(true);
                avatar = _binder != null ? _binder.Current : null;
            }

            Animator animator = avatar != null ? avatar.GetComponentInChildren<Animator>(true) : null;
            if (animator == null || !animator.isHuman)
            {
                return;
            }

            _avatar = avatar;
            _animator = animator;
            _shoulder = animator.GetBoneTransform(HumanBodyBones.RightUpperArm);
            _elbow = animator.GetBoneTransform(HumanBodyBones.RightLowerArm);
            _wrist = animator.GetBoneTransform(HumanBodyBones.RightHand);
            if (_shoulder == null || _elbow == null || _wrist == null)
            {
                return;
            }

            for (int i = 0; i < FingerBones.Length; i++)
            {
                _fingers[i] = animator.GetBoneTransform(FingerBones[i]);
            }

            // Ejes de la mano en el espacio del hueso: hacia los dedos (al nudillo del
            // corazón) y hacia el lado del pulgar (del meñique al índice). Como TriviaHat.
            Transform middle = animator.GetBoneTransform(HumanBodyBones.RightMiddleProximal);
            Transform index = animator.GetBoneTransform(HumanBodyBones.RightIndexProximal);
            Transform little = animator.GetBoneTransform(HumanBodyBones.RightLittleProximal);
            Vector3 finger = middle != null ? _wrist.InverseTransformPoint(middle.position) : Vector3.zero;
            if (finger.sqrMagnitude < 1e-8f)
            {
                finger = _wrist.InverseTransformDirection(_wrist.position - _elbow.position);
            }

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
            _bound = true;
            _fingersReady = ComputeFingerTargets();
            Log("mano enganchada a " + avatar.name + (_fingersReady ? "" : " (sin dedos)"));
        }

        /// <summary>
        /// Rotación local de cada falange para cada forma, sacada de los músculos del
        /// humanoide: se pone la pose con esos músculos, se leen los dedos y se deja el
        /// cuerpo como estaba (la animación lo vuelve a escribir en el fotograma siguiente).
        /// </summary>
        private bool ComputeFingerTargets()
        {
            if (_animator == null || _animator.avatar == null || !_animator.avatar.isHuman)
            {
                return false;
            }

            int found = 0;
            for (int i = 0; i < _fingers.Length; i++)
            {
                if (_fingers[i] != null)
                {
                    found++;
                }
            }

            if (found < 9)
            {
                return false;
            }

            int[,] muscle = MuscleIndices();
            if (muscle == null)
            {
                return false;
            }

            HumanPoseHandler handler = null;
            try
            {
                handler = new HumanPoseHandler(_animator.avatar, _animator.transform);
                HumanPose original = new HumanPose();
                handler.GetHumanPose(ref original);
                float[] saved = (float[])original.muscles.Clone();

                // Los dedos en su reposo (todos los músculos a 0): de ahí se exagera el cierre.
                Quaternion[] rest = new Quaternion[_fingers.Length];
                HumanPose neutral = original;
                neutral.muscles = (float[])saved.Clone();
                for (int f = 0; f < 5; f++)
                {
                    for (int k = 0; k < 4; k++)
                    {
                        Set(neutral.muscles, muscle[f, k], 0f);
                    }
                }

                handler.SetHumanPose(ref neutral);
                for (int i = 0; i < _fingers.Length; i++)
                {
                    rest[i] = _fingers[i] != null ? _fingers[i].localRotation : Quaternion.identity;
                }

                for (int s = 0; s < ShapeCount; s++)
                {
                    HandMuscles values = Muscles((PptHand)s);
                    HumanPose pose = original;
                    pose.muscles = (float[])saved.Clone();
                    for (int f = 0; f < 5; f++)
                    {
                        FingerMuscles m = values.Finger(f);
                        Set(pose.muscles, muscle[f, 0], m.Stretch1);
                        Set(pose.muscles, muscle[f, 1], m.Spread);
                        Set(pose.muscles, muscle[f, 2], m.Stretch2);
                        Set(pose.muscles, muscle[f, 3], m.Stretch3);
                    }

                    handler.SetHumanPose(ref pose);
                    for (int i = 0; i < _fingers.Length; i++)
                    {
                        Quaternion target = _fingers[i] != null ? _fingers[i].localRotation : Quaternion.identity;
                        int finger = i / 3;
                        bool closed = values.Finger(finger).Stretch1 < 0f;
                        float gain = finger == 0 ? values.ThumbCurl : values.Curl;
                        if (closed && gain > 1.001f)
                        {
                            target = Quaternion.SlerpUnclamped(rest[i], target, gain);
                        }

                        _targets[s, i] = target;
                    }
                }

                original.muscles = saved;
                handler.SetHumanPose(ref original);
                return true;
            }
            catch (Exception ex)
            {
                Debug.LogException(ex, this);
                return false;
            }
            finally
            {
                if (handler != null)
                {
                    handler.Dispose();
                }
            }
        }

        private HandMuscles Muscles(PptHand shape)
        {
            switch (shape)
            {
                case PptHand.Paper:
                    return paper;
                case PptHand.Scissors:
                    return scissors;
                default:
                    return rock;
            }
        }

        private static void Set(float[] muscles, int index, float value)
        {
            if (index >= 0 && index < muscles.Length)
            {
                muscles[index] = Mathf.Clamp(value, -1f, 1f);
            }
        }

        /// <summary>Índices de los músculos de los dedos de la mano derecha: [dedo, (1, Spread, 2, 3)].</summary>
        private static int[,] MuscleIndices()
        {
            string[] names = HumanTrait.MuscleName;
            int[,] result = new int[5, 4];
            int missing = 0;
            for (int f = 0; f < 5; f++)
            {
                string finger = FingerNames[f];
                result[f, 0] = FindMuscle(names, "Right " + finger + " 1 Stretched", "RightHand." + finger + ".1 Stretched");
                result[f, 1] = FindMuscle(names, "Right " + finger + " Spread", "RightHand." + finger + ".Spread");
                result[f, 2] = FindMuscle(names, "Right " + finger + " 2 Stretched", "RightHand." + finger + ".2 Stretched");
                result[f, 3] = FindMuscle(names, "Right " + finger + " 3 Stretched", "RightHand." + finger + ".3 Stretched");
                for (int k = 0; k < 4; k++)
                {
                    if (result[f, k] < 0)
                    {
                        missing++;
                    }
                }
            }

            if (missing > 0)
            {
                Debug.LogWarning("[Sonia] Piedra, papel o tijera: faltan " + missing + " músculos de los dedos en HumanTrait.");
            }

            return missing >= 20 ? null : result;
        }

        private static int FindMuscle(string[] names, string a, string b)
        {
            for (int i = 0; i < names.Length; i++)
            {
                if (names[i] == a || names[i] == b)
                {
                    return i;
                }
            }

            return -1;
        }

        // ------------------------------------------------------------------
        // IK de dos huesos (como TriviaHat)
        // ------------------------------------------------------------------

        /// <summary>El codo en el plano de la pista y la muñeca en el objetivo.</summary>
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

        private static float Smooth(float t)
        {
            t = Mathf.Clamp01(t);
            return t * t * (3f - (2f * t));
        }

        private void Log(string message)
        {
            if (logEvents)
            {
                Debug.Log("[Sonia] PPT mano: " + message, this);
            }
        }
    }
}
