// Estado del avatar: cabeza, mirada y parpadeo.
//
// El estado llega por el protocolo (idle, listening, thinking, speaking). Las
// animaciones del cuerpo las lleva AvatarChoreographer; aquí se decide hacia
// dónde mira la cabeza y cómo se mueve con la voz, y se parpadea:
//
//  - Mirada: al visitante (la cámara), al panel de imágenes un momento cuando
//    aparece, o arriba y a un lado mientras piensa (un vistazo, no un giro de
//    perfil: mirar abajo y apartar la cara se leía como enfado).
//  - Con la voz (eventos de LipSyncController, un poco antes de su sílaba):
//    asentimientos breves en las sílabas tónicas, un cambio de pose de cabeza
//    (giro e inclinación pequeños) en cada frase y un asentimiento suave al
//    terminarla.
//  - Escuchando: la cabeza ladeada hacia un lado y algún asentimiento de "ajá".
//  - Parpadeo con forma real (cierra rápido, abre más despacio), a ritmo de
//    2-5 s, al empezar y acabar frases y en los saltos de mirada; a veces doble
//    o a medias. El párpado acompaña a la mirada: al mirar abajo baja un poco.
//
// Todo se aplica en LateUpdate, sobre la pose de la animación.

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
    /// Orienta la cabeza según el estado y la voz y añade el parpadeo. Todo es
    /// opcional: sin hueso de cabeza o sin blendshapes de ojos no hace nada.
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
        [Tooltip("Cuánto manda la mirada sobre la rotación que dicta la animación.")]
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
        [Tooltip("Lip-sync: de él llegan los eventos de la voz (sílabas, frases). Opcional.")]
        private LipSyncController lipSync;

        [Header("Cabeza con la voz")]
        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("Grados de un asentimiento en una sílaba tónica.")]
        public float stressNodDegrees = 3.5f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de asentir en una sílaba tónica.")]
        public float stressNodChance = 0.65f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Fuerza mínima (0..1) para que una sílaba cuente como tónica.")]
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
        public Vector2 listenNodInterval = new Vector2(2.8f, 5.5f);

        [SerializeField]
        [Range(0f, 12f)]
        [Tooltip("Inclinación de la cabeza al pensar.")]
        public float thinkTiltDegrees = 5f;

        [Header("Parpadeo")]
        [SerializeField]
        [Tooltip("Cara del avatar: el parpadeo se escribe en sus canales eyeBlinkLeft y eyeBlinkRight.")]
        private FaceRig faceRig;

        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre parpadeos espontáneos.")]
        private Vector2 blinkIntervalRange = new Vector2(2.5f, 6f);

        [SerializeField]
        [Tooltip("Duración de un parpadeo en segundos (cierra en un tercio, abre en el resto).")]
        private float blinkDuration = 0.14f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de parpadear al empezar o acabar una frase y al cambiar de estado.")]
        public float blinkOnSpeechChance = 0.35f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de que un parpadeo espontáneo sea doble.")]
        public float doubleBlinkChance = 0.12f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Cuánto baja el párpado superior al mirar abajo (por 10° de mirada).")]
        public float lidFollowsGaze = 0.25f;

        [SerializeField]
        [Tooltip("Ojos, para que el párpado acompañe a la mirada. Opcional.")]
        private EyeGazeController eyeGaze;

        private AvatarState _state = AvatarState.Idle;
        private float _stateSince;

        // Desvío de la mirada respecto a la animación, en el espacio local de la
        // cabeza. Se suaviza en local a propósito: si se suavizara la rotación en
        // el mundo, al girar el cuerpo deprisa la cabeza se quedaría "clavada"
        // mirando al sitio antiguo.
        private Quaternion _lookOffset = Quaternion.identity;
        private float _currentWeight;
        private bool _lookInitialized;
        private bool _imageVisible;
        private float _imageShownAt = -999f;
        private float _noiseSeed;

        // Gestos de cabeza (grados): cabeceo (positivo baja la barbilla), giro e inclinación.
        private Spring _pitch;
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

        // Parpadeo.
        private int _blinkLeftChannel = -1;
        private int _blinkRightChannel = -1;
        private float _timeToNextBlink;
        private float _blinkElapsed = -1f;
        private float _blinkDepth = 1f;
        private float _pendingSecondBlink = -1f;
        private float _lid;

        // Mirada dirigida desde fuera (salida y entrada caminando: mira hacia
        // dónde va). Manda sobre el visitante, el panel y el punto de pensar.
        private bool _lookOverride;
        private Vector3 _lookOverridePosition;
        private float _lookOverrideWeight = -1f;

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
            set { headBone = value; }
        }

        /// <summary>Vuelve a mirar a quien toque según el estado (visitante, panel, pensar).</summary>
        public void ClearLookOverride()
        {
            _lookOverride = false;
            _lookOverrideWeight = -1f;
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
                    if (e.Strength >= stressThreshold && now - _lastNod > 0.45f
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

        // ------------------------------------------------------------------
        // Mirada y parpadeo
        // ------------------------------------------------------------------

        private void LateUpdate()
        {
            float deltaTime = Time.deltaTime;
            UpdateGestures(deltaTime);
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
                        _nextListenNod = now + UnityEngine.Random.Range(listenNodInterval.x, listenNodInterval.y);
                        Nod(listenNodDegrees * UnityEngine.Random.Range(0.7f, 1.1f));
                    }

                    break;
                case AvatarState.Thinking:
                    targetRoll = thinkTiltDegrees * _tiltSide;
                    break;
            }

            // El cabeceo tiene dos partes: la pose (lenta) y los asentimientos
            // (empujones que vuelven solos a cero).
            _pitch.Step(0f, 2.6f, dt);
            _pitchPose.Step(targetPitch, 1.2f, dt);
            _yaw.Step(targetYaw, 1.1f, dt);
            _roll.Step(targetRoll, 1.0f, dt);
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
            if (_lookOverride && _lookOverrideWeight >= 0f)
            {
                targetWeight = Mathf.Clamp01(_lookOverrideWeight);
            }

            _currentWeight = Mathf.Lerp(_currentWeight, targetWeight, 1f - Mathf.Exp(-3f * deltaTime));

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
            // bailes manda la animación: los gestos se apagan con el peso.
            Vector3 forward = Vector3.ProjectOnPlane(lookDirection, Vector3.up);
            if (forward.sqrMagnitude < 0.0001f)
            {
                forward = Vector3.ProjectOnPlane(headBone.forward, Vector3.up);
            }

            forward.Normalize();
            Vector3 right = Vector3.Cross(Vector3.up, forward).normalized;
            float gestureWeight = Mathf.InverseLerp(0f, Mathf.Max(0.01f, lookWeight), _currentWeight);
            Quaternion gesture = Quaternion.AngleAxis(_roll.Value * gestureWeight, forward)
                                 * Quaternion.AngleAxis((_pitch.Value + _pitchPose.Value) * gestureWeight, right)
                                 * Quaternion.AngleAxis(_yaw.Value * gestureWeight, Vector3.up);
            headBone.rotation = gesture * looked;
        }

        private float StepFor(float deltaTime)
        {
            return 1f - Mathf.Exp(-Mathf.Max(0.1f, lookSmoothing) * deltaTime);
        }

        /// <summary>Punto del mundo al que mira ahora mismo (visitante, panel o el punto de pensar).</summary>
        public bool TryGetLookPosition(out Vector3 position)
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

            float blink = 0f;
            if (_blinkElapsed >= 0f)
            {
                _blinkElapsed += deltaTime;
                float duration = Mathf.Max(0.06f, blinkDuration);
                float close = duration * 0.35f;
                float hold = duration * 0.1f;
                if (_blinkElapsed < close)
                {
                    float t = _blinkElapsed / close;
                    blink = t * t;
                }
                else if (_blinkElapsed < close + hold)
                {
                    blink = 1f;
                }
                else if (_blinkElapsed < duration)
                {
                    float t = (_blinkElapsed - close - hold) / (duration - close - hold);
                    blink = 1f - (t * (2f - t));
                }
                else
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

                blink *= _blinkDepth;
            }
            else
            {
                _timeToNextBlink -= deltaTime;
                if (_timeToNextBlink <= 0f)
                {
                    StartBlink(UnityEngine.Random.value < 0.1f ? 0.6f : 1f);
                    if (UnityEngine.Random.value < doubleBlinkChance)
                    {
                        _pendingSecondBlink = 0.08f;
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
            float weight = Mathf.Clamp01(Mathf.Max(blink, _lid));
            ApplyBlink(weight * 100f);
        }

        /// <summary>Parpadea ahora mismo (si no está ya parpadeando). Lo usan las sacadas grandes.</summary>
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
        }

        private void ScheduleNextBlink()
        {
            float min = Mathf.Max(0.2f, Mathf.Min(blinkIntervalRange.x, blinkIntervalRange.y));
            float max = Mathf.Max(min + 0.1f, Mathf.Max(blinkIntervalRange.x, blinkIntervalRange.y));
            _timeToNextBlink = UnityEngine.Random.Range(min, max);
        }

        private void ApplyBlink(float weight)
        {
            // weight llega en 0..100; FaceRig suma en 0..1.
            faceRig.Add(_blinkLeftChannel, weight / 100f);
            faceRig.Add(_blinkRightChannel, weight / 100f);
        }
    }
}
