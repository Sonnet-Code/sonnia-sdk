// Estado del avatar: cabeza, cuerpo vivo (respiración y acentos) y parpadeo.
//
// El estado llega por el protocolo (idle, listening, thinking, speaking). Las
// animaciones del cuerpo las lleva AvatarChoreographer; aquí, encima de ellas:
//
//  - Cabeza: sigue al visitante (la cámara) solo en parte: 0,3 en reposo y al
//    pensar, 0,5 al escuchar y al hablar. La mueve sobre todo el reposo y los
//    ojos hacen el resto, como Mia en genies.com (docs/informe-mia.md). Mira al panel de imágenes un
//    momento cuando aparece; al pensar, la cabeza sube un poco y mira arriba y a
//    un lado.
//  - Escuchando: la cabeza ladeada, el torso un poco hacia delante y algún
//    asentimiento lento de "ajá".
//  - Respiración aditiva continua, también al hablar: una inspiración cada unos
//    5 s (con algo de azar, para que no case con el reposo), pecho ±1,1° y
//    hombros. La cabeza la acompaña. Valores medidos en Mia.
//  - Acentos al hablar, como el "énfasis" de Genies: en las sílabas tónicas, una
//    cascada de 0,8 s (preparación hacia atrás, y luego columna, pecho +3,4°,
//    cuello, cabeza +5,5° y brazos, cada uno un poco después del anterior).
//    OnEmphasis avisa en el mismo instante (las cejas suben en
//    FacialExpressionController).
//  - Parpadeo como el de Genies: 0,38 s (cierra rápido en un tercio, abre
//    despacio en dos), cada 3-5 s más los de la voz y los cambios de mirada
//    (unos 20 por minuto), dobles en un 18 %, los ojos desfasados unos ms y las
//    cejas que bajan un poco. El párpado acompaña a la mirada al mirar abajo.
//
// Todo se aplica en LateUpdate, sobre la pose de la animación.

using System;
using System.Collections.Generic;
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
    /// Orienta la cabeza según el estado y la voz, da vida al cuerpo (respiración
    /// y acentos) y parpadea. Todo es opcional: sin huesos o sin blendshapes de
    /// ojos esa parte no hace nada.
    /// </summary>
    // Corre después del LateUpdate de Vrm10Instance (orden 11000), que aplica sus
    // expresiones (a cero) y la mirada; así los blendshapes de parpadeo que
    // escribimos aquí prevalecen.
    [DefaultExecutionOrder(12010)]
    [DisallowMultipleComponent]
    public class AvatarStateController : MonoBehaviour
    {
        [Header("Mirada")]
        [SerializeField]
        [Tooltip("Hueso de la cabeza. Si está vacío no se toca la mirada.")]
        private Transform headBone;

        [SerializeField]
        [Tooltip("Raíz del avatar: da los ejes (derecha, arriba, delante) del punto de pensar. Por defecto, este objeto.")]
        private Transform avatarRoot;

        [SerializeField]
        [Tooltip("A dónde mira al escuchar y al hablar. Normalmente la cámara.")]
        private Transform lookTarget;

        [SerializeField]
        [Tooltip("Punto opcional al que mira mientras piensa. Si está vacío se usa el desplazamiento de abajo.")]
        private Transform thinkingLookTarget;

        [SerializeField]
        [Tooltip("Punto al que mira mientras piensa, respecto a la cabeza y en los ejes del avatar (derecha, arriba, delante). Arriba y a un lado: un vistazo de pensar, no apartar la cara.")]
        private Vector3 thinkingGaze = new Vector3(0.35f, 0.3f, 1.4f);

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
        [Tooltip("Cuánto sigue la cabeza al visitante sobre lo que dicta la animación. Con 0,3 la cabeza la mueve sobre todo el reposo y los ojos miran al visitante (Mia: cabeza a 0, ojos a 1).")]
        private float headFollow = 0.3f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Lo mismo mientras habla: más, que hablando se mira a quien se habla. DefaultIdle gira bastante la cabeza (unos 18° de lado a lado con 0,3) y en conversación se leía como no mirar al visitante.")]
        private float speakingHeadFollow = 0.5f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Lo mismo mientras escucha.")]
        private float listeningHeadFollow = 0.5f;

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
        [Tooltip("Amplitud en grados del vaivén lento y continuo de la cabeza, para que nunca esté clavada (va escalado por el seguimiento).")]
        private float headSwayDegrees = 1.4f;

        [SerializeField]
        [Tooltip("Lip-sync: de él llegan los eventos de la voz (sílabas, frases). Opcional.")]
        private LipSyncController lipSync;

        [Header("Cabeza con la voz")]
        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("Grados de un asentimiento en una sílaba tónica (solo con los acentos de cuerpo apagados; con ellos la cabeza va en la cascada).")]
        public float stressNodDegrees = 3.5f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de asentir en una sílaba tónica (con los acentos apagados).")]
        public float stressNodChance = 0.65f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Fuerza mínima (0..1) para que una sílaba cuente como tónica (con los acentos apagados).")]
        public float stressThreshold = 0.8f;

        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("Grados de giro e inclinación de la pose de cabeza que se elige en cada frase.")]
        public float phrasePoseDegrees = 4f;

        [SerializeField]
        [Range(0f, 12f)]
        [Tooltip("Inclinación de la cabeza al escuchar (ladeada hacia un lado).")]
        public float listenTiltDegrees = 6f;

        [SerializeField]
        [Range(0f, 8f)]
        [Tooltip("Grados de los asentimientos de \"ajá\" al escuchar.")]
        public float listenNodDegrees = 2.5f;

        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre asentimientos al escuchar.")]
        public Vector2 listenNodEvery = new Vector2(4f, 8f);

        [SerializeField]
        [Range(0.5f, 4f)]
        [Tooltip("Rapidez de los asentimientos al escuchar (Hz del muelle). Más bajo, más lentos y tranquilos.")]
        public float listenNodHz = 1.4f;

        [SerializeField]
        [Range(0f, 12f)]
        [Tooltip("Inclinación de la cabeza al pensar.")]
        public float thinkTiltDegrees = 5f;

        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("Cuánto sube la cabeza al pensar (grados).")]
        public float thinkLiftDegrees = 4f;

        [Header("Cuerpo: respiración")]
        [SerializeField]
        [Tooltip("Respiración aditiva continua sobre la animación, también al hablar.")]
        private bool breathing = true;

        [SerializeField]
        [Range(2f, 10f)]
        [Tooltip("Segundos por respiración (Mia: 5, unas 12 por minuto).")]
        private float breathSeconds = 5f;

        [SerializeField]
        [Range(0f, 0.4f)]
        [Tooltip("Azar en la duración y la profundidad de cada respiración, para que no case con el bucle del reposo.")]
        private float breathJitter = 0.12f;

        [SerializeField]
        [Range(0f, 4f)]
        [Tooltip("Grados que se abre el pecho al inspirar (Mia: ±1,1). La cabeza lo acompaña.")]
        private float breathChestDegrees = 1.1f;

        [SerializeField]
        [Range(0f, 3f)]
        [Tooltip("Grados que suben los hombros al inspirar.")]
        private float breathShoulderDegrees = 0.6f;

        [SerializeField]
        [Range(0f, 6f)]
        [Tooltip("Grados que se inclina el torso hacia delante al escuchar: interés.")]
        private float listenLeanDegrees = 2f;

        [Header("Cuerpo: acentos al hablar")]
        [SerializeField]
        [Tooltip("Acentos de cuerpo en las sílabas tónicas (el \"énfasis\" de Genies): cascada de columna, pecho, cuello, cabeza y brazos.")]
        private bool accents = true;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Fuerza mínima (0..1) de la sílaba para un acento.")]
        private float accentThreshold = 0.8f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de acento en una sílaba que pasa el umbral.")]
        private float accentChance = 0.6f;

        [SerializeField]
        [Range(0.3f, 2f)]
        [Tooltip("Segundos mínimos entre dos acentos (Genies: 0,6-1).")]
        private float accentMinGap = 0.9f;

        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Escala de toda la cascada. 1: los grados de Genies (pecho +3,4°, cuello +2°, cabeza +5,5°), que se suman por la cadena y en primer plano son mucho; 0,6 de partida.")]
        private float accentScale = 0.6f;

        [SerializeField]
        [Range(0f, 6f)]
        [Tooltip("Grados que se adelantan los brazos en un acento.")]
        private float accentArmDegrees = 2.5f;

        [Header("Parpadeo")]
        [SerializeField]
        [Tooltip("Cara del avatar: el parpadeo se escribe en sus canales eyeBlinkLeft y eyeBlinkRight.")]
        private FaceRig faceRig;

        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre parpadeos espontáneos (Genies: 4 ± 1). Con los de la voz y los cambios de mirada salen unos 20 por minuto.")]
        private Vector2 blinkEvery = new Vector2(3f, 5f);

        [SerializeField]
        [Range(0.1f, 0.7f)]
        [Tooltip("Duración de un parpadeo en segundos: cierra en un tercio y abre despacio en el resto (Genies: 0,35-0,4).")]
        private float blinkSeconds = 0.38f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de parpadear al empezar o acabar una frase y al cambiar de estado.")]
        public float blinkOnSpeechChance = 0.35f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Parte de los parpadeos espontáneos que son dobles (Mia: 18 %).")]
        public float doubleBlinkShare = 0.18f;

        [SerializeField]
        [Range(0f, 0.04f)]
        [Tooltip("Desfase máximo entre los dos ojos en un parpadeo (s). Genies: 16 ms.")]
        private float blinkEyeOffset = 0.012f;

        [SerializeField]
        [Range(0f, 0.6f)]
        [Tooltip("Cuánto bajan las cejas con el parpadeo (0..1). Van más lentas que el párpado: el pico real es algo más de la mitad (Genies: hasta 0,25).")]
        private float blinkBrowLower = 0.25f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Cuánto baja el párpado superior al mirar abajo (por 10° de mirada).")]
        public float lidFollowsGaze = 0.25f;

        [SerializeField]
        [Tooltip("Ojos, para que el párpado acompañe a la mirada. Opcional.")]
        private EyeGazeController eyeGaze;

        // Huesos del cuerpo que mueven la respiración y los acentos.
        private const int BSpine = 0;
        private const int BChest = 1;
        private const int BUpperChest = 2;
        private const int BNeck = 3;
        private const int BLeftShoulder = 4;
        private const int BRightShoulder = 5;
        private const int BLeftArm = 6;
        private const int BRightArm = 7;
        private const int BodyBoneCount = 8;

        private static readonly HumanBodyBones[] BodyBoneIds =
        {
            HumanBodyBones.Spine, HumanBodyBones.Chest, HumanBodyBones.UpperChest, HumanBodyBones.Neck,
            HumanBodyBones.LeftShoulder, HumanBodyBones.RightShoulder, HumanBodyBones.LeftUpperArm, HumanBodyBones.RightUpperArm
        };

        /// <summary>Un acento en marcha: cuándo empezó y con qué fuerza (0..1).</summary>
        private struct Accent
        {
            public float Start;
            public float Gain;
        }

        // Duración total de la cascada de un acento.
        private const float AccentSeconds = 0.85f;

        private AvatarState _state = AvatarState.Idle;
        private float _stateSince;

        // Desvío de la mirada respecto a la animación, en el espacio local de la
        // cabeza. Se suaviza en local a propósito: si se suavizara la rotación en
        // el mundo, al girar el cuerpo deprisa la cabeza se quedaría "clavada"
        // mirando al sitio antiguo.
        private Quaternion _lookOffset = Quaternion.identity;
        private float _currentWeight;
        private float _gestureWeight = 1f;
        private bool _lookInitialized;
        private bool _imageVisible;
        private float _imageShownAt = -999f;
        private float _noiseSeed;

        // Gestos de cabeza (grados): cabeceo (positivo baja la barbilla), giro e inclinación.
        private Spring _pitch;
        private Spring _slowNod;
        private Spring _yaw;
        private Spring _roll;
        private Spring _pitchPose;
        private float _poseYaw;
        private float _posePitch;
        private float _poseRoll;
        private float _lastNod = -10f;
        private float _nextListenNod;
        private int _tiltSide = 1;
        private bool _subscribed;

        // Cuerpo: huesos, pose de la animación y lo último que se escribió (si el
        // Animator no escribe un fotograma, no se acumula el giro).
        private readonly Transform[] _bodyBones = new Transform[BodyBoneCount];
        private readonly Quaternion[] _bodyBase = new Quaternion[BodyBoneCount];
        private readonly Quaternion[] _bodyWritten = new Quaternion[BodyBoneCount];
        private readonly bool[] _bodyHasWritten = new bool[BodyBoneCount];
        private Animator _bodyAnimator;
        private Transform _bodyResolvedFor;
        private bool _bodyResolved;
        private Spring _lean;
        private float _breathPhase;
        private float _breathPeriod = 5f;
        private float _breathDepth = 1f;
        private float _breathValue;
        private readonly List<Accent> _accents = new List<Accent>(4);
        private float _lastAccent = -10f;
        private float _accentHeadPitch;

        // Ajuste «Movimiento en reposo» (1 = tal cual).
        private float _breathTuning = 1f;
        private float _accentTuning = 1f;
        private float _speedTuning = 1f;

        // Parpadeo.
        private int _blinkLeftChannel = -1;
        private int _blinkRightChannel = -1;
        private int _browLeftChannel = -1;
        private int _browRightChannel = -1;
        private float _timeToNextBlink;
        private float _blinkElapsed = -1f;
        private float _blinkDepth = 1f;
        private float _blinkLeftDelay;
        private float _blinkRightDelay;
        private float _pendingSecondBlink = -1f;
        private float _lid;
        private Spring _browBlink;

        // Mirada dirigida desde fuera (salida y entrada caminando: mira hacia
        // dónde va). Manda sobre el visitante, el panel y el punto de pensar.
        private bool _lookOverride;
        private Vector3 _lookOverridePosition;
        private float _lookOverrideWeight = -1f;

        /// <summary>
        /// Acento de la voz: una sílaba tónica que lleva cascada de cuerpo. El
        /// valor es su fuerza (0..1). FacialExpressionController sube las cejas.
        /// </summary>
        public event Action<float> OnEmphasis;

        /// <summary>Estado actual del avatar.</summary>
        public AvatarState State
        {
            get { return _state; }
        }

        /// <summary>Cierto mientras otro componente decide hacia dónde mira.</summary>
        public bool HasLookOverride
        {
            get { return _lookOverride; }
        }

        /// <summary>Respiración ahora mismo: -1 espirado, 1 inspirado. Para medir.</summary>
        public float BreathValue
        {
            get { return _breathValue; }
        }

        /// <summary>Cuánto sigue ahora la cabeza al objetivo (0..1). Para medir.</summary>
        public float CurrentLookWeight
        {
            get { return _currentWeight; }
        }

        /// <summary>
        /// Mira a un punto del mundo en lugar de al visitante. Cabeza y ojos
        /// (EyeGazeController lee el mismo punto) van hacia él con su suavizado
        /// de siempre, así que un cambio de punto se lee como un giro natural.
        /// Se llama cada frame mientras dure; <paramref name="weight"/> negativo
        /// deja el peso normal de la mirada.
        /// </summary>
        public void SetLookOverride(Vector3 worldPosition, float weight = -1f)
        {
            _lookOverride = true;
            _lookOverridePosition = worldPosition;
            _lookOverrideWeight = weight;
        }

        /// <summary>Hueso de la cabeza que se gira. Cambia con el avatar (el del SDK sustituye al doble).</summary>
        public Transform HeadBone
        {
            get { return headBone; }
            set
            {
                headBone = value;
                _bodyResolved = false;
            }
        }

        /// <summary>Vuelve a mirar a quien toque según el estado (visitante, panel, pensar).</summary>
        public void ClearLookOverride()
        {
            _lookOverride = false;
            _lookOverrideWeight = -1f;
        }

        /// <summary>
        /// Ajuste «Movimiento en reposo» (Developer): multiplicadores sobre la
        /// escena, 1 = tal cual. <paramref name="breath"/> escala la respiración,
        /// <paramref name="accentAmount"/> los acentos al hablar y
        /// <paramref name="speed"/> el ritmo de la respiración y del bucle de
        /// reposo (su traspaso de peso).
        /// </summary>
        public void SetIdleTuning(float breath, float accentAmount, float speed)
        {
            _breathTuning = Mathf.Clamp(breath, 0f, 3f);
            _accentTuning = Mathf.Clamp(accentAmount, 0f, 3f);
            _speedTuning = Mathf.Clamp(speed, 0.25f, 3f);
            if (choreographer != null)
            {
                choreographer.SetLoopSpeed(_speedTuning);
            }
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

            if (eyeGaze == null)
            {
                eyeGaze = GetComponentInChildren<EyeGazeController>(true);
            }

            _noiseSeed = UnityEngine.Random.value * 100f;
            _breathPhase = UnityEngine.Random.value;
            _breathPeriod = breathSeconds;
            RefreshBlendShapes();
            ScheduleNextBlink();
        }

        private void OnEnable()
        {
            if (lipSync != null && !_subscribed)
            {
                lipSync.OnSpeechEvent += HandleSpeechEvent;
                _subscribed = true;
            }

            if (faceRig != null)
            {
                faceRig.Rebuilt -= RefreshBlendShapes;
                faceRig.Rebuilt += RefreshBlendShapes;
            }
        }

        private void OnDisable()
        {
            if (lipSync != null && _subscribed)
            {
                lipSync.OnSpeechEvent -= HandleSpeechEvent;
                _subscribed = false;
            }

            if (faceRig != null)
            {
                faceRig.Rebuilt -= RefreshBlendShapes;
            }
        }

        /// <summary>Cara del avatar. Al cambiarla se vuelven a resolver los canales de parpadeo.</summary>
        public FaceRig FaceRig
        {
            get { return faceRig; }
            set
            {
                if (faceRig != null)
                {
                    faceRig.Rebuilt -= RefreshBlendShapes;
                }

                faceRig = value;
                if (faceRig != null && isActiveAndEnabled)
                {
                    faceRig.Rebuilt += RefreshBlendShapes;
                }

                RefreshBlendShapes();
            }
        }

        /// <summary>Vuelve a resolver los canales de parpadeo (al cambiar de avatar).</summary>
        public void RefreshBlendShapes()
        {
            _blinkLeftChannel = faceRig != null ? faceRig.Channel("eyeBlinkLeft") : -1;
            _blinkRightChannel = faceRig != null ? faceRig.Channel("eyeBlinkRight") : -1;
            _browLeftChannel = faceRig != null ? faceRig.Channel("browDownLeft") : -1;
            _browRightChannel = faceRig != null ? faceRig.Channel("browDownRight") : -1;
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
            if (state == _state)
            {
                return;
            }

            _state = state;
            _stateSince = Time.time;
            _tiltSide = UnityEngine.Random.value < 0.5f ? -1 : 1;
            _nextListenNod = Time.time + UnityEngine.Random.Range(1.2f, 2.5f);
            if (state != AvatarState.Speaking)
            {
                _poseYaw = 0f;
                _posePitch = 0f;
                _poseRoll = 0f;
            }

            if (UnityEngine.Random.value < blinkOnSpeechChance + 0.15f)
            {
                TriggerBlink();
            }
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
        // Voz
        // ------------------------------------------------------------------

        private void HandleSpeechEvent(SpeechAnalyzer.SpeechEvent e)
        {
            float now = Time.time;
            switch (e.Kind)
            {
                case SpeechAnalyzer.EventKind.PhraseStart:
                    // Cada frase, una pose de cabeza algo distinta: así no habla
                    // siempre con la cara clavada en el mismo sitio.
                    _poseYaw = UnityEngine.Random.Range(-1f, 1f) * phrasePoseDegrees;
                    _poseRoll = UnityEngine.Random.Range(-1f, 1f) * phrasePoseDegrees * 0.8f;
                    _posePitch = UnityEngine.Random.Range(-0.6f, 0.4f) * phrasePoseDegrees * 0.5f;
                    if (UnityEngine.Random.value < blinkOnSpeechChance)
                    {
                        TriggerBlink();
                    }

                    break;
                case SpeechAnalyzer.EventKind.PhraseEnd:
                    Nod(stressNodDegrees * 0.6f);
                    _poseYaw *= 0.4f;
                    _poseRoll *= 0.4f;
                    _posePitch = 0f;
                    if (UnityEngine.Random.value < blinkOnSpeechChance)
                    {
                        TriggerBlink();
                    }

                    break;
                case SpeechAnalyzer.EventKind.Syllable:
                    if (accents)
                    {
                        if (e.Strength >= accentThreshold && now - _lastAccent >= accentMinGap
                            && UnityEngine.Random.value < accentChance)
                        {
                            float strength = Mathf.InverseLerp(accentThreshold, 1f, e.Strength);
                            StartAccent(Mathf.Lerp(0.55f, 1f, strength));
                        }
                    }
                    else if (e.Strength >= stressThreshold && now - _lastNod > 0.45f
                             && UnityEngine.Random.value < stressNodChance)
                    {
                        float strength = Mathf.InverseLerp(stressThreshold, 1f, e.Strength);
                        Nod(stressNodDegrees * Mathf.Lerp(0.6f, 1f, strength));
                    }

                    break;
            }
        }

        /// <summary>Asentimiento: un empujón al muelle del cabeceo que llega a <paramref name="degrees"/>.</summary>
        private void Nod(float degrees)
        {
            // Con un muelle críticamente amortiguado en reposo, una velocidad v
            // inicial llega a un máximo de v / (omega · e).
            const float frequency = 2.6f;
            float omega = 2f * Mathf.PI * frequency;
            _pitch.Kick(degrees * omega * 2.718f);
            _lastNod = Time.time;
        }

        /// <summary>Asentimiento lento de escucha, con su propio muelle (listenNodHz).</summary>
        private void SlowNod(float degrees)
        {
            float omega = 2f * Mathf.PI * Mathf.Max(0.3f, listenNodHz);
            _slowNod.Kick(degrees * omega * 2.718f);
            _lastNod = Time.time;
        }

        /// <summary>Lanza la cascada de un acento y avisa a quien quiera acompañarlo (cejas).</summary>
        private void StartAccent(float gain)
        {
            _lastAccent = Time.time;
            if (_accents.Count >= 3)
            {
                _accents.RemoveAt(0);
            }

            _accents.Add(new Accent { Start = Time.time, Gain = gain });
            Action<float> handler = OnEmphasis;
            if (handler != null)
            {
                handler(gain);
            }
        }

        // ------------------------------------------------------------------
        // Bucle
        // ------------------------------------------------------------------

        private void LateUpdate()
        {
            float deltaTime = Time.deltaTime;
            UpdateGestures(deltaTime);
            UpdateBody(deltaTime);
            UpdateLook(deltaTime);
            UpdateBlink(deltaTime);
        }

        private void UpdateGestures(float dt)
        {
            float now = Time.time;
            float targetYaw = _poseYaw;
            float targetRoll = _poseRoll;
            float targetPitch = _posePitch;
            switch (_state)
            {
                case AvatarState.Listening:
                    // Ladeada y un poco hacia delante: atenta.
                    targetRoll = listenTiltDegrees * _tiltSide;
                    targetPitch = 1.5f;
                    if (now >= _nextListenNod)
                    {
                        float min = Mathf.Min(listenNodEvery.x, listenNodEvery.y);
                        float max = Mathf.Max(listenNodEvery.x, listenNodEvery.y);
                        _nextListenNod = now + UnityEngine.Random.Range(Mathf.Max(0.5f, min), Mathf.Max(0.6f, max));
                        SlowNod(listenNodDegrees * UnityEngine.Random.Range(0.7f, 1.1f));
                    }

                    break;
                case AvatarState.Thinking:
                    // Algo arriba y ladeada (los ojos van arriba y a un lado).
                    targetRoll = thinkTiltDegrees * _tiltSide;
                    targetPitch = -thinkLiftDegrees;
                    break;
            }

            // El cabeceo tiene tres partes: la pose (lenta), los asentimientos de
            // la voz y los de escucha (empujones que vuelven solos a cero).
            _pitch.Step(0f, 2.6f, dt);
            _slowNod.Step(0f, Mathf.Max(0.3f, listenNodHz), dt);
            _pitchPose.Step(targetPitch, 1.2f, dt);
            _yaw.Step(targetYaw, 1.1f, dt);
            _roll.Step(targetRoll, 1.0f, dt);
        }

        // ------------------------------------------------------------------
        // Cuerpo: respiración, escucha y acentos
        // ------------------------------------------------------------------

        private void UpdateBody(float dt)
        {
            UpdateBreath(dt);
            _lean.Step(_state == AvatarState.Listening ? listenLeanDegrees : 0f, 0.8f, dt);
            float now = Time.time;
            for (int i = _accents.Count - 1; i >= 0; i--)
            {
                if (now - _accents[i].Start > AccentSeconds)
                {
                    _accents.RemoveAt(i);
                }
            }

            // Ángulos de este fotograma (grados; cabeceo positivo hacia delante).
            float breath = breathing ? _breathValue * breathChestDegrees * _breathDepth * _breathTuning : 0f;
            float shoulders = breathing ? (_breathValue * 0.5f + 0.5f) * breathShoulderDegrees * _breathDepth * _breathTuning : 0f;
            float spine = 0f;
            float chest = -breath + _lean.Value;
            float neck = 0f;
            float arms = 0f;
            _accentHeadPitch = 0f;
            // Los brazos solo acentúan si nadie más los usa: ni señalando una imagen,
            // ni caminando, ni en un momento dirigido (mirada impuesta: la entrada
            // del invitado, el apretón de manos).
            bool armsFree = !_lookOverride
                            && (choreographer == null || (!choreographer.IsPresenting && !choreographer.IsSuspended));
            for (int i = 0; i < _accents.Count; i++)
            {
                float t = now - _accents[i].Start;
                float g = _accents[i].Gain * accentScale * _accentTuning;

                // Preparación hacia atrás y luego el acento, cada parte un poco
                // después de la anterior (secuencia "breakdown" de Genies). La
                // "cadera" va en la columna baja para no mover las piernas.
                spine += g * (-0.4f * Pulse(t, 0f, 0.2f) + 2f * Pulse(t, 0.025f, 0.45f));
                chest += g * (-1.2f * Pulse(t, 0f, 0.22f) + 3.4f * Pulse(t, 0.11f, 0.65f));
                neck += g * 2f * Pulse(t, 0.18f, 0.75f);
                _accentHeadPitch += g * 5.5f * Pulse(t, 0.18f, 0.8f);
                if (armsFree)
                {
                    arms += g * (1f * Pulse(t, 0f, 0.22f) - accentArmDegrees * Pulse(t, 0.2f, 0.75f));
                }
            }

            if (!ResolveBody())
            {
                return;
            }

            for (int i = 0; i < BodyBoneCount; i++)
            {
                PrepareBone(i);
            }

            Transform frame = _bodyAnimator.transform;
            Vector3 right = frame.right;
            Vector3 forward = frame.forward;
            RotateBone(BSpine, right, spine);
            RotateBone(_bodyBones[BUpperChest] != null ? BUpperChest : BChest, right, chest);
            RotateBone(BNeck, right, neck);
            LiftShoulder(BLeftShoulder, BLeftArm, forward, shoulders);
            LiftShoulder(BRightShoulder, BRightArm, forward, shoulders);
            RotateBone(BLeftArm, right, arms);
            RotateBone(BRightArm, right, arms);

            for (int i = 0; i < BodyBoneCount; i++)
            {
                if (_bodyBones[i] != null)
                {
                    _bodyWritten[i] = _bodyBones[i].localRotation;
                    _bodyHasWritten[i] = true;
                }
            }
        }

        /// <summary>
        /// Avanza la respiración: inspira en el 40 % del ciclo y espira en el
        /// resto, con curva suave. Cada respiración dura y abre algo distinto.
        /// </summary>
        private void UpdateBreath(float dt)
        {
            _breathPhase += dt * _speedTuning / Mathf.Max(0.5f, _breathPeriod);
            if (_breathPhase >= 1f)
            {
                _breathPhase -= Mathf.Floor(_breathPhase);
                float jitter = Mathf.Clamp(breathJitter, 0f, 0.5f);
                _breathPeriod = Mathf.Max(1f, breathSeconds * (1f + UnityEngine.Random.Range(-jitter, jitter)));
                _breathDepth = 1f + UnityEngine.Random.Range(-jitter, jitter);
            }

            const float inhale = 0.4f;
            float v = _breathPhase < inhale
                ? Smooth(_breathPhase / inhale)
                : 1f - Smooth((_breathPhase - inhale) / (1f - inhale));
            _breathValue = v * 2f - 1f;
        }

        /// <summary>Busca los huesos del cuerpo en el Animator de la cabeza (al cambiar de avatar).</summary>
        private bool ResolveBody()
        {
            if (_bodyResolved && _bodyResolvedFor == headBone)
            {
                return _bodyAnimator != null;
            }

            _bodyResolved = true;
            _bodyResolvedFor = headBone;
            _bodyAnimator = headBone != null ? headBone.GetComponentInParent<Animator>() : null;
            bool any = false;
            for (int i = 0; i < BodyBoneCount; i++)
            {
                _bodyBones[i] = _bodyAnimator != null && _bodyAnimator.isHuman ? _bodyAnimator.GetBoneTransform(BodyBoneIds[i]) : null;
                _bodyHasWritten[i] = false;
                any |= _bodyBones[i] != null;
            }

            if (!any)
            {
                _bodyAnimator = null;
            }

            return _bodyAnimator != null;
        }

        /// <summary>
        /// Deja el hueso en la pose de la animación de este fotograma. Si el
        /// Animator no lo ha escrito (sigue lo que puso este componente), se
        /// vuelve a la pose guardada para no acumular el giro fotograma a fotograma.
        /// </summary>
        private void PrepareBone(int index)
        {
            Transform bone = _bodyBones[index];
            if (bone == null)
            {
                return;
            }

            Quaternion now = bone.localRotation;
            Quaternion written = _bodyWritten[index];
            bool stale = _bodyHasWritten[index] && now.x == written.x && now.y == written.y && now.z == written.z && now.w == written.w;
            if (stale)
            {
                bone.localRotation = _bodyBase[index];
            }
            else
            {
                _bodyBase[index] = now;
            }
        }

        private void RotateBone(int index, Vector3 axis, float degrees)
        {
            Transform bone = _bodyBones[index];
            if (bone == null || Mathf.Abs(degrees) < 0.0001f)
            {
                return;
            }

            bone.rotation = Quaternion.AngleAxis(degrees, axis) * bone.rotation;
        }

        /// <summary>Sube un hombro <paramref name="degrees"/> (hacia la oreja), sea el izquierdo o el derecho.</summary>
        private void LiftShoulder(int shoulder, int arm, Vector3 forward, float degrees)
        {
            Transform s = _bodyBones[shoulder];
            Transform a = _bodyBones[arm];
            if (s == null || a == null || Mathf.Abs(degrees) < 0.0001f)
            {
                return;
            }

            // Girando sobre "delante", un brazo a la derecha sube con ángulo
            // positivo y uno a la izquierda con negativo.
            float side = Mathf.Sign(Vector3.Dot(a.position - s.position, _bodyAnimator.transform.right));
            RotateBone(shoulder, forward, degrees * side);
        }

        /// <summary>Subida y bajada suave entre <paramref name="start"/> y <paramref name="end"/> segundos, con el pico al 35 %.</summary>
        private static float Pulse(float t, float start, float end)
        {
            if (t <= start || t >= end)
            {
                return 0f;
            }

            return FaceCurves.Bump((t - start) / (end - start), 0.35f);
        }

        private static float Smooth(float x)
        {
            x = Mathf.Clamp01(x);
            return x * x * (3f - 2f * x);
        }

        // ------------------------------------------------------------------
        // Cabeza
        // ------------------------------------------------------------------

        private void UpdateLook(float deltaTime)
        {
            if (headBone == null)
            {
                return;
            }

            Quaternion baseRotation = headBone.rotation;
            bool wide = choreographer != null && choreographer.IsWideShot;
            float stateWeight = _state == AvatarState.Speaking ? speakingHeadFollow
                : _state == AvatarState.Listening ? listeningHeadFollow : headFollow;
            if (!_lookInitialized)
            {
                _lookOffset = Quaternion.identity;
                _currentWeight = stateWeight;
                _lookInitialized = true;
            }

            float targetWeight = wide ? wideShotLookWeight : stateWeight;
            if (_lookOverride && _lookOverrideWeight >= 0f)
            {
                targetWeight = Mathf.Clamp01(_lookOverrideWeight);
            }

            _currentWeight = Mathf.Lerp(_currentWeight, targetWeight, 1f - Mathf.Exp(-3f * deltaTime));
            _gestureWeight = Mathf.Lerp(_gestureWeight, wide ? 0f : 1f, 1f - Mathf.Exp(-3f * deltaTime));

            Quaternion desiredOffset = Quaternion.identity;
            Vector3 targetPosition;
            Vector3 lookDirection = headBone.forward;
            if (TryGetLookPosition(out targetPosition))
            {
                Vector3 direction = targetPosition - headBone.position;
                if (direction.sqrMagnitude > 0.0001f)
                {
                    lookDirection = direction.normalized;

                    // Vaivén lento (ruido Perlin): una cabeza real nunca se queda clavada.
                    float swayYaw = FaceCurves.Noise(_noiseSeed, Time.time * 0.35f) * headSwayDegrees;
                    float swayPitch = FaceCurves.Noise(_noiseSeed + 17f, Time.time * 0.28f) * headSwayDegrees;
                    Quaternion desired = Quaternion.LookRotation(lookDirection, Vector3.up)
                                         * Quaternion.Euler(headRotationOffset)
                                         * Quaternion.Euler(swayPitch, swayYaw, 0f);
                    Quaternion limited = Quaternion.RotateTowards(baseRotation, desired, maxLookAngle);

                    // Desvío respecto a la animación, en local: viaja con el cuerpo.
                    desiredOffset = Quaternion.Inverse(baseRotation) * limited;
                }
            }

            _lookOffset = Quaternion.Slerp(_lookOffset, desiredOffset, StepFor(deltaTime));
            Quaternion looked = baseRotation * Quaternion.Slerp(Quaternion.identity, _lookOffset, _currentWeight);

            // Gestos encima de la mirada, en ejes del mundo alineados con ella:
            // cabeceo alrededor del eje "derecha", giro alrededor de la vertical
            // e inclinación alrededor de la dirección de la mirada. Durante los
            // bailes manda la animación: los gestos se apagan.
            Vector3 forward = Vector3.ProjectOnPlane(lookDirection, Vector3.up);
            if (forward.sqrMagnitude < 0.0001f)
            {
                forward = Vector3.ProjectOnPlane(headBone.forward, Vector3.up);
            }

            forward.Normalize();
            Vector3 right = Vector3.Cross(Vector3.up, forward).normalized;
            float pitch = _pitch.Value + _slowNod.Value + _pitchPose.Value + _accentHeadPitch;
            Quaternion gesture = Quaternion.AngleAxis(_roll.Value * _gestureWeight, forward)
                                 * Quaternion.AngleAxis(pitch * _gestureWeight, right)
                                 * Quaternion.AngleAxis(_yaw.Value * _gestureWeight, Vector3.up);
            headBone.rotation = gesture * looked;
        }

        private float StepFor(float deltaTime)
        {
            return 1f - Mathf.Exp(-Mathf.Max(0.1f, lookSmoothing) * deltaTime);
        }

        /// <summary>Punto del mundo al que mira la cabeza ahora mismo (visitante, panel o el punto de pensar).</summary>
        public bool TryGetLookPosition(out Vector3 position)
        {
            if (TryGetOverrideOrPanel(out position))
            {
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
                Vector3 origin = headBone != null ? headBone.position : root.position;
                Vector3 side = root.right * (thinkingGaze.x * _tiltSide);
                position = origin + side + Vector3.up * thinkingGaze.y + FacingOf(root) * thinkingGaze.z;
                return true;
            }

            return TryGetVisitor(out position);
        }

        /// <summary>
        /// Punto base de los ojos: el mismo que la cabeza salvo al pensar, donde
        /// los ojos parten del visitante y su plantilla de mirada los lleva arriba
        /// y a un lado (EyeGazeController).
        /// </summary>
        public bool TryGetEyeTarget(out Vector3 position)
        {
            if (TryGetOverrideOrPanel(out position))
            {
                return true;
            }

            return TryGetVisitor(out position);
        }

        /// <summary>Cierto si ahora manda una mirada impuesta (caminar, invitado) o el vistazo al panel.</summary>
        public bool HasDirectedGaze
        {
            get
            {
                Vector3 unused;
                return TryGetOverrideOrPanel(out unused);
            }
        }

        private bool TryGetOverrideOrPanel(out Vector3 position)
        {
            if (_lookOverride)
            {
                position = _lookOverridePosition;
                return true;
            }

            // Un vistazo breve al panel cuando aparece la imagen; después la
            // mirada vuelve al visitante, que es lo natural en una conversación.
            bool glancing = imageGlanceSeconds <= 0f || Time.time - _imageShownAt < imageGlanceSeconds;
            if (lookAtImageWhenVisible && _imageVisible && imageLookTarget != null && glancing)
            {
                position = imageLookTarget.position;
                return true;
            }

            position = Vector3.zero;
            return false;
        }

        private bool TryGetVisitor(out Vector3 position)
        {
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

        /// <summary>Hacia dónde mira el avatar en horizontal: hacia la cámara si la hay.</summary>
        private Vector3 FacingOf(Transform root)
        {
            Vector3 toward = Vector3.zero;
            if (lookTarget != null && headBone != null)
            {
                toward = lookTarget.position - headBone.position;
            }
            else if (Camera.main != null && headBone != null)
            {
                toward = Camera.main.transform.position - headBone.position;
            }

            toward = Vector3.ProjectOnPlane(toward, Vector3.up);
            if (toward.sqrMagnitude < 0.0001f)
            {
                toward = Vector3.ProjectOnPlane(root.forward, Vector3.up);
            }

            return toward.normalized;
        }

        // ------------------------------------------------------------------
        // Parpadeo
        // ------------------------------------------------------------------

        private void UpdateBlink(float deltaTime)
        {
            if (faceRig == null || (_blinkLeftChannel < 0 && _blinkRightChannel < 0))
            {
                return;
            }

            float left = 0f;
            float right = 0f;
            if (_blinkElapsed >= 0f)
            {
                _blinkElapsed += deltaTime;
                float duration = Mathf.Max(0.08f, blinkSeconds);
                left = BlinkCurve(_blinkElapsed - _blinkLeftDelay, duration) * _blinkDepth;
                right = BlinkCurve(_blinkElapsed - _blinkRightDelay, duration) * _blinkDepth;
                if (_blinkElapsed >= duration + Mathf.Max(_blinkLeftDelay, _blinkRightDelay))
                {
                    _blinkElapsed = -1f;
                    if (_pendingSecondBlink >= 0f)
                    {
                        _timeToNextBlink = _pendingSecondBlink;
                        _pendingSecondBlink = -1f;
                    }
                    else
                    {
                        ScheduleNextBlink();
                    }
                }
            }
            else
            {
                _timeToNextBlink -= deltaTime;
                if (_timeToNextBlink <= 0f)
                {
                    StartBlink(UnityEngine.Random.value < 0.1f ? 0.6f : 1f);
                    if (UnityEngine.Random.value < doubleBlinkShare)
                    {
                        _pendingSecondBlink = UnityEngine.Random.Range(0.05f, 0.3f);
                    }
                }
            }

            // El párpado superior acompaña a la mirada: al mirar abajo baja.
            float lidTarget = 0f;
            if (eyeGaze != null)
            {
                lidTarget = Mathf.Clamp01(eyeGaze.CurrentPitchDown / 10f) * lidFollowsGaze;
            }

            _lid = Mathf.Lerp(_lid, lidTarget, 1f - Mathf.Exp(-12f * deltaTime));
            faceRig.Add(_blinkLeftChannel, Mathf.Clamp01(Mathf.Max(left, _lid)));
            faceRig.Add(_blinkRightChannel, Mathf.Clamp01(Mathf.Max(right, _lid)));

            // Las cejas bajan un poco con el parpadeo, más despacio que el párpado.
            _browBlink.Step(Mathf.Max(left, right), 2.5f, deltaTime);
            float brow = Mathf.Clamp01(_browBlink.Value) * blinkBrowLower;
            faceRig.Add(_browLeftChannel, brow);
            faceRig.Add(_browRightChannel, brow);
        }

        /// <summary>
        /// Forma del parpadeo, 0..1: cierra en un tercio de la duración (rápido,
        /// frena al cerrar) y abre en dos tercios (empieza despacio). Así el ojo
        /// pasa algo más de 0,25 s medio cerrado, como en Genies.
        /// </summary>
        private static float BlinkCurve(float t, float duration)
        {
            if (t <= 0f || t >= duration)
            {
                return 0f;
            }

            float close = duration / 3f;
            if (t < close)
            {
                float x = t / close;
                return 1f - (1f - x) * (1f - x);
            }

            float y = (t - close) / (duration - close);
            return 1f - y * y;
        }

        /// <summary>Parpadea ahora mismo (si no está ya parpadeando). Lo usan los cambios de mirada.</summary>
        public void TriggerBlink()
        {
            if (_blinkElapsed < 0f)
            {
                StartBlink(1f);
            }
        }

        private void StartBlink(float depth)
        {
            _blinkElapsed = 0f;
            _blinkDepth = depth;

            // Un ojo arranca unos milisegundos antes que el otro.
            float offset = UnityEngine.Random.Range(0f, Mathf.Max(0f, blinkEyeOffset));
            bool leftFirst = UnityEngine.Random.value < 0.5f;
            _blinkLeftDelay = leftFirst ? 0f : offset;
            _blinkRightDelay = leftFirst ? offset : 0f;
        }

        private void ScheduleNextBlink()
        {
            float min = Mathf.Max(0.2f, Mathf.Min(blinkEvery.x, blinkEvery.y));
            float max = Mathf.Max(min + 0.1f, Mathf.Max(blinkEvery.x, blinkEvery.y));
            _timeToNextBlink = UnityEngine.Random.Range(min, max);
        }
    }
}
