// Modo Jean en la pantalla: el invitado sorpresa (Jean, CTO de Sonnet Code)
// entra en el stand, se da la mano con Sonia, ella se va y él habla desde lejos
// con su avatar.
//
// Lo manda el orquestador con guest_mode (mensaje fijo: se repite tras cada
// hello) y aquí se le avisa de cada paso con guest_state:
//
//   enter   entering: plano entero de los dos; el invitado entra caminando
//           desde la izquierda hasta su marca, se dan la mano y Sonia sale por
//           la derecha, sin letrero.
//           live: plano medio del invitado. Su voz (frames SNGU) suena por su
//           propio reproductor, con su lip-sync, y su cuerpo la acompaña.
//   leave   leaving: se despide con la mano y sale por la izquierda mientras
//           Sonia vuelve. off: el plano de siempre.
//
// Si guest_mode llega nada más conectar (justo tras un hello), se aplica sin
// animación. Si tras un hello no llega y el invitado estaba dentro (el
// orquestador se reinició), se despide.
//
// Qué es de quién:
//   - caminar: PresenceController (el del invitado, sin letrero y saliendo por
//     la izquierda; el de Sonia, con HoldForGuest);
//   - la mano: HandshakeRig;
//   - el cuerpo entre medias (reposo, mirada, gestos al hablar): IAvatarBody.
//     Hoy ChoreographerBody; el motor de comportamiento de Genies entra con su
//     propio adaptador sin tocar este archivo;
//   - la cámara: CameraFramingController.SetOverride;
//   - la voz y la boca: el AudioStreamPlayer, el LipSyncController y el
//     analizador de fonemas de la raíz «Invitado».
//
// La raíz «Invitado» la monta Sonia > Montar invitado (Modo Jean): su posición
// es la marca del invitado, a la izquierda de Sonia.

using System.Collections;
using UnityEngine;

namespace Sonia
{
    /// <summary>Secuencia del Modo Jean en Unity: entrada, apretón de manos, voz del invitado y salida.</summary>
    [DisallowMultipleComponent]
    public class GuestPresenter : MonoBehaviour
    {
        private enum Stage
        {
            Off,
            Entering,
            Live,
            Leaving
        }

        [Header("Sonia")]
        [SerializeField]
        [Tooltip("Raíz de Sonia. De ella salen el cliente, su presencia, su cabeza y la cámara. Vacío: la de la escena.")]
        private SoniaBootstrap sonia;

        [SerializeField]
        [Tooltip("Conexión con el orquestador. Vacío: la de Sonia.")]
        private SoniaClient client;

        [Header("Invitado (esta raíz)")]
        [SerializeField]
        [Tooltip("Presencia del invitado: entra y sale caminando, sin letrero. Vacío: la de este objeto.")]
        private PresenceController guestPresence;

        [SerializeField]
        [Tooltip("Reproductor de la voz del invitado. Vacío: el de este objeto.")]
        private AudioStreamPlayer guestPlayer;

        [SerializeField]
        [Tooltip("Lip-sync del invitado. Vacío: el de este objeto.")]
        private LipSyncController guestLipSync;

        [SerializeField]
        [Tooltip("Cabeza y parpadeo del invitado (de él sale su hueso de la cabeza). Vacío: el de este objeto.")]
        private AvatarStateController guestState;

        [SerializeField]
        [Tooltip("Reproductor de clips del invitado (de él sale su Animator). Vacío: el de este objeto.")]
        private MotionPlayer guestMotion;

        [SerializeField]
        [Tooltip("Apretón de manos. Vacío: el de este objeto (se añade si falta).")]
        private HandshakeRig handshake;

        [Header("Tiempos")]
        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("Un guest_mode que llega en estos segundos tras el hello se aplica sin animación.")]
        private float instantWindowSeconds = 2f;

        [SerializeField]
        [Range(1f, 20f)]
        [Tooltip("Tras un hello, si el invitado está dentro y no llega guest_mode en este tiempo, se despide (el orquestador se reinició).")]
        private float helloGraceSeconds = 5f;

        [SerializeField]
        [Range(3f, 30f)]
        [Tooltip("Lo más que se espera a que alguien llegue a su sitio o salga de cuadro caminando.")]
        private float walkTimeoutSeconds = 12f;

        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Silencio tras la última frase del invitado antes de pasar a escuchar.")]
        private float talkReleaseSeconds = 0.35f;

        [SerializeField]
        [Range(0f, 4f)]
        [Tooltip("Lo que dura su saludo de despedida antes de echar a andar.")]
        private float waveSeconds = 1.6f;

        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Al irse el invitado, Sonia echa a andar este tiempo después de él.")]
        private float soniaReturnDelaySeconds = 0.6f;

        [Header("Encuadre")]
        [SerializeField]
        [Range(0.2f, 1.5f)]
        [Tooltip("Metros que se ven a cada lado de los dos (desde el centro de cada uno) en el plano entero.")]
        private float duoSideMargin = 0.5f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Cuánto mira Sonia al invitado mientras entra y se dan la mano.")]
        private float soniaLookWeight = 0.75f;

        [Header("Registro")]
        [SerializeField]
        private bool logEvents = true;

        private Stage _stage = Stage.Off;
        private float _stageSince;
        private Coroutine _routine;
        private IAvatarBody _body;
        private PresenceController _soniaPresence;
        private CameraFramingController _framing;
        private AvatarStateController _soniaState;
        private MotionPlayer _soniaMotion;
        private AvatarChoreographer _soniaChoreographer;
        private readonly ChoreographerHold _soniaHold = new ChoreographerHold();
        private bool _resolved;
        private bool _subscribed;

        private float _helloAt = -999f;
        private bool _guestModeSinceHello = true;
        private int _currentUtterance = -1;
        private bool _talking;
        private float _silentSince = -1f;

        private Vector3 _soniaHeadRest;
        private bool _haveSoniaHeadRest;
        private float _nextHiddenCheck;

        /// <summary>Paso de la secuencia: off, entering, live o leaving.</summary>
        public string StageName
        {
            get
            {
                switch (_stage)
                {
                    case Stage.Entering:
                        return "entering";
                    case Stage.Live:
                        return "live";
                    case Stage.Leaving:
                        return "leaving";
                    default:
                        return "off";
                }
            }
        }

        /// <summary>Cuerpo en uso (el motor de Genies si hay adaptador; si no, el de respaldo).</summary>
        public IAvatarBody Body
        {
            get { return _body; }
        }

        /// <summary>Cierto mientras suena la voz del invitado.</summary>
        public bool GuestTalking
        {
            get { return _talking; }
        }

        private void Awake()
        {
            if (sonia == null)
            {
                sonia = FindAnyObjectByType<SoniaBootstrap>();
            }

            if (client == null && sonia != null)
            {
                client = sonia.GetComponentInChildren<SoniaClient>(true);
            }

            if (guestPresence == null)
            {
                guestPresence = GetComponent<PresenceController>();
            }

            if (guestPlayer == null)
            {
                guestPlayer = GetComponent<AudioStreamPlayer>();
            }

            if (guestLipSync == null)
            {
                guestLipSync = GetComponent<LipSyncController>();
            }

            if (guestState == null)
            {
                guestState = GetComponent<AvatarStateController>();
            }

            if (guestMotion == null)
            {
                guestMotion = GetComponent<MotionPlayer>();
            }

            if (handshake == null)
            {
                handshake = GetComponent<HandshakeRig>();
            }

            if (handshake == null)
            {
                handshake = gameObject.AddComponent<HandshakeRig>();
            }
        }

        private void OnEnable()
        {
            if (client != null && !_subscribed)
            {
                client.OnHello += HandleHello;
                client.OnGuestMode += HandleGuestMode;
                client.OnGuestAnimation += HandleGuestAnimation;
                client.OnGuestAudioFrame += HandleGuestAudio;
                client.OnSetVolume += HandleSetVolume;
                client.OnSetTuning += HandleSetTuning;
                _subscribed = true;
            }

            if (guestPlayer != null)
            {
                guestPlayer.OnUtterancePlaybackDone += HandlePlaybackDone;
            }
        }

        private void OnDisable()
        {
            if (client != null && _subscribed)
            {
                client.OnHello -= HandleHello;
                client.OnGuestMode -= HandleGuestMode;
                client.OnGuestAnimation -= HandleGuestAnimation;
                client.OnGuestAudioFrame -= HandleGuestAudio;
                client.OnSetVolume -= HandleSetVolume;
                client.OnSetTuning -= HandleSetTuning;
                _subscribed = false;
            }

            if (guestPlayer != null)
            {
                guestPlayer.OnUtterancePlaybackDone -= HandlePlaybackDone;
            }
        }

        private void Start()
        {
            ResolveSonia();
            _body = PickBody();

            // El invitado empieza fuera de cuadro y oculto.
            if (guestPresence != null)
            {
                guestPresence.SetPresent(false, null, true);
            }

            Log("listo (cuerpo: " + (_body != null && !_body.IsFallback ? "motor de Genies" : "coreógrafo") + ")");
        }

        /// <summary>Lo de Sonia: lo añade SoniaBootstrap en su Awake, así que se busca aquí.</summary>
        private void ResolveSonia()
        {
            if (_resolved || sonia == null)
            {
                return;
            }

            _resolved = true;
            _soniaPresence = sonia.GetComponentInChildren<PresenceController>(true);
            _framing = sonia.GetComponentInChildren<CameraFramingController>(true);
            _soniaState = sonia.GetComponentInChildren<AvatarStateController>(true);
            _soniaMotion = sonia.GetComponentInChildren<MotionPlayer>(true);
            _soniaChoreographer = sonia.GetComponentInChildren<AvatarChoreographer>(true);
        }

        /// <summary>El primer IAvatarBody de esta raíz que no sea el de respaldo; si no hay, el de respaldo.</summary>
        private IAvatarBody PickBody()
        {
            IAvatarBody fallback = null;
            foreach (MonoBehaviour behaviour in GetComponentsInChildren<MonoBehaviour>(true))
            {
                IAvatarBody body = behaviour as IAvatarBody;
                if (body == null)
                {
                    continue;
                }

                if (!body.IsFallback)
                {
                    return body;
                }

                if (fallback == null)
                {
                    fallback = body;
                }
            }

            return fallback ?? gameObject.AddComponent<ChoreographerBody>();
        }

        // ------------------------------------------------------------------
        // Mensajes del orquestador
        // ------------------------------------------------------------------

        private void HandleHello(HelloMessage message)
        {
            _helloAt = Time.unscaledTime;
            _guestModeSinceHello = false;
        }

        private void HandleGuestMode(GuestModeMessage message)
        {
            if (message == null)
            {
                return;
            }

            _guestModeSinceHello = true;
            if (guestPlayer != null && message.SampleRate > 0)
            {
                guestPlayer.SetSourceSampleRate(message.SampleRate);
            }

            bool instant = Time.unscaledTime - _helloAt <= instantWindowSeconds;
            string phase = (message.Phase ?? string.Empty).ToLowerInvariant();
            if (phase == "enter")
            {
                Enter(instant);
            }
            else if (phase == "leave")
            {
                Leave(instant);
            }
        }

        private void HandleGuestAnimation(GuestAnimationMessage message)
        {
            if (message == null || string.IsNullOrEmpty(message.Clip))
            {
                return;
            }

            if (_stage != Stage.Live || _body == null)
            {
                Log("gesto «" + message.Clip + "» ignorado: el invitado no está en directo");
                return;
            }

            bool played = _body.PlayGesture(message.Clip);
            Log("gesto «" + message.Clip + "»" + (played ? string.Empty : " (no está en el set o no toca ahora)"));
        }

        private void HandleSetVolume(SetVolumeMessage message)
        {
            if (message != null && guestPlayer != null)
            {
                guestPlayer.SetVolume(message.Value);
            }
        }

        /// <summary>La boca del invitado lleva los mismos ajustes de «Developer» que la de Sonia.</summary>
        private void HandleSetTuning(SetTuningMessage message)
        {
            if (message == null || guestLipSync == null)
            {
                return;
            }

            MouthTuning mouth = message.Mouth ?? new MouthTuning();
            guestLipSync.ApplyTuning(mouth.Open, mouth.Jaw, mouth.Closure, mouth.Speed);
        }

        // ------------------------------------------------------------------
        // Voz del invitado
        // ------------------------------------------------------------------

        private void HandleGuestAudio(AudioFrame frame)
        {
            if (guestPlayer == null || _stage == Stage.Off || _stage == Stage.Leaving)
            {
                return;
            }

            guestPlayer.Enqueue(frame);
            bool hasAudio = frame.Samples != null && frame.Samples.Length > 0;
            if (hasAudio)
            {
                _silentSince = -1f;
            }

            if (!hasAudio || frame.UtteranceId == _currentUtterance)
            {
                return;
            }

            // Frase nueva: habla, y cada frase puede estrenar gesto.
            _currentUtterance = frame.UtteranceId;
            if (_stage == Stage.Live && _body != null)
            {
                if (!_talking)
                {
                    _talking = true;
                    _body.SetTalking(true);
                }

                _body.NotifyPhrase();
            }
        }

        private void HandlePlaybackDone(int utteranceId)
        {
            if (guestLipSync != null)
            {
                guestLipSync.NotifyUtteranceFinished(utteranceId);
            }

            if (utteranceId >= _currentUtterance)
            {
                _silentSince = Time.time;
            }
        }

        private void StopVoice()
        {
            if (guestPlayer != null)
            {
                guestPlayer.Flush();
            }

            if (guestLipSync != null)
            {
                guestLipSync.StopAndClose();
            }

            _currentUtterance = -1;
            _silentSince = -1f;
            if (_talking)
            {
                _talking = false;
                if (_body != null)
                {
                    _body.SetTalking(false);
                }
            }
        }

        // ------------------------------------------------------------------
        // Bucle
        // ------------------------------------------------------------------

        private void Update()
        {
            ResolveSonia();

            // Se calla: tras un respiro sin voz, vuelve a escuchar.
            if (_talking && _silentSince >= 0f && Time.time - _silentSince > talkReleaseSeconds
                && (guestPlayer == null || !guestPlayer.IsPlaying))
            {
                _talking = false;
                _silentSince = -1f;
                if (_body != null)
                {
                    _body.SetTalking(false);
                }
            }

            // Tras un hello sin guest_mode, con el invitado dentro: el orquestador
            // ya no está en el Modo Jean (se reinició), así que se despide.
            if (!_guestModeSinceHello && _stage != Stage.Off && _stage != Stage.Leaving
                && Time.unscaledTime - _helloAt > helloGraceSeconds)
            {
                _guestModeSinceHello = true;
                Log("tras el hello no llegó guest_mode: el invitado se despide");
                Leave(false);
            }

            // Sin Modo Jean, el invitado no se ve nunca. Si algo lo trajo de vuelta
            // (una recarga de scripts, un cambio de avatar a destiempo, renderers
            // encendidos por otro), se esconde al momento.
            if (_stage == Stage.Off && guestPresence != null && Time.unscaledTime >= _nextHiddenCheck)
            {
                _nextHiddenCheck = Time.unscaledTime + 0.5f;
                if (guestPresence.EnsureAway())
                {
                    Debug.LogWarning("[Sonia] Modo Jean apagado y el invitado se veía: se esconde.", this);
                }
            }

            // Red de seguridad: una secuencia que se queda a medias se termina sin animación.
            float stuck = _stage == Stage.Entering ? 40f : _stage == Stage.Leaving ? 30f : -1f;
            if (stuck > 0f && Time.time - _stageSince > stuck)
            {
                Debug.LogWarning("[Sonia] Modo Jean: la secuencia se quedó a medias; se completa sin animación.", this);
                if (_stage == Stage.Entering)
                {
                    Enter(true);
                }
                else
                {
                    Leave(true);
                }
            }
        }

        private void LateUpdate()
        {
            // Con Sonia en su sitio y sin invitado, se apunta dónde tiene la cabeza:
            // el plano medio del invitado se calcula respecto a él.
            if (_stage == Stage.Off && _soniaPresence != null && _soniaPresence.IsPresent && _soniaState != null
                && _soniaState.HeadBone != null)
            {
                _soniaHeadRest = _soniaState.HeadBone.position;
                _haveSoniaHeadRest = true;
            }
        }

        // ------------------------------------------------------------------
        // Secuencia
        // ------------------------------------------------------------------

        /// <summary>Entra el invitado (con animación o al instante). También para pruebas en el editor.</summary>
        public void Enter(bool instant)
        {
            ResolveSonia();
            if (_stage == Stage.Live || (_stage == Stage.Entering && !instant))
            {
                Send(_stage == Stage.Live ? "live" : "entering");
                return;
            }

            Run(instant ? EnterInstant() : EnterRoutine());
        }

        /// <summary>Se va el invitado y vuelve Sonia (con animación o al instante). También para pruebas.</summary>
        public void Leave(bool instant)
        {
            ResolveSonia();
            if (_stage == Stage.Off)
            {
                Send("off");
                return;
            }

            if (_stage == Stage.Leaving && !instant)
            {
                return;
            }

            Run(instant ? LeaveInstant() : LeaveRoutine());
        }

        private void Run(IEnumerator routine)
        {
            if (_routine != null)
            {
                StopCoroutine(_routine);
                _routine = null;
            }

            _routine = StartCoroutine(routine);
        }

        private void SetStage(Stage stage)
        {
            _stage = stage;
            _stageSince = Time.time;
        }

        private IEnumerator EnterRoutine()
        {
            SetStage(Stage.Entering);
            Send("entering");
            StopVoice();
            Log("entra el invitado");

            // Los dos en plano entero.
            ShotPose duo;
            if (_framing != null && TryDuoShot(out duo))
            {
                _framing.SetOverride(duo);
            }

            // Si Sonia está volviendo (un enter a mitad de la despedida), se le deja llegar.
            float until = Time.time + walkTimeoutSeconds;
            while (_soniaPresence != null && !_soniaPresence.HeldByGuest && !_soniaPresence.IsPresent
                   && !_soniaPresence.IsAway && Time.time < until)
            {
                yield return null;
            }

            // Entra caminando desde la izquierda; Sonia lo mira llegar.
            if (guestPresence != null)
            {
                guestPresence.SetPresent(true, null, false);
                until = Time.time + walkTimeoutSeconds;
                while (!guestPresence.IsPresent && Time.time < until)
                {
                    SoniaLooksAt(GuestHead());
                    yield return null;
                }
            }

            // Se dan la mano (si Sonia está en su sitio).
            bool soniaHere = _soniaPresence == null || (_soniaPresence.IsPresent && !_soniaPresence.HeldByGuest);
            if (soniaHere && handshake != null && _soniaMotion != null && guestMotion != null
                && handshake.Begin(_soniaMotion.Animator, guestMotion.Animator))
            {
                // Los dos quietos en su reposo: sin variaciones ni gestos a mitad.
                _soniaHold.Hold(_soniaChoreographer);
                if (_body != null)
                {
                    _body.Hold(true);
                }

                Log("se dan la mano");
                while (handshake.IsActive)
                {
                    SoniaLooksAt(GuestHead());
                    if (_body != null)
                    {
                        _body.SetAttention(SoniaHead());
                    }

                    yield return null;
                }

                ReleaseHolds();
            }

            ClearSoniaLook();

            // Sonia se va por la derecha, sin letrero; el invitado la mira irse.
            if (_soniaPresence != null && !_soniaPresence.HeldByGuest)
            {
                _soniaPresence.HoldForGuest(false);
                Log("Sonia le deja el sitio");
            }

            until = Time.time + walkTimeoutSeconds;
            while (_soniaPresence != null && !_soniaPresence.IsAway && Time.time < until)
            {
                if (_body != null)
                {
                    _body.SetAttention(SoniaHead());
                }

                yield return null;
            }

            if (_body != null)
            {
                _body.SetAttention(null);
                _body.SetTalking(false);
            }

            // Plano medio del invitado: en directo.
            if (_framing != null)
            {
                _framing.SetOverride(GuestLiveShot());
            }

            SetStage(Stage.Live);
            Send("live");
            Log("en directo");
            _routine = null;
        }

        private IEnumerator EnterInstant()
        {
            SetStage(Stage.Live);
            StopVoice();
            if (handshake != null)
            {
                handshake.Cancel();
            }

            ReleaseHolds();

            ClearSoniaLook();
            if (_soniaPresence != null)
            {
                _soniaPresence.HoldForGuest(true);
            }

            if (guestPresence != null)
            {
                guestPresence.SetPresent(true, null, true);
            }

            if (_body != null)
            {
                _body.SetAttention(null);
                _body.SetTalking(false);
            }

            if (_framing != null)
            {
                _framing.SetOverride(GuestLiveShot());
                _framing.SnapNextFrame();
            }

            Send("live");
            Log("en directo (sin animación)");
            _routine = null;
            yield break;
        }

        private IEnumerator LeaveRoutine()
        {
            SetStage(Stage.Leaving);
            Send("leaving");
            StopVoice();
            ClearSoniaLook();
            if (handshake != null)
            {
                handshake.Cancel();
            }

            ReleaseHolds();

            if (_body != null)
            {
                _body.SetAttention(null);
            }

            Log("el invitado se despide");

            // Se despide con la mano, si está en su sitio.
            if (guestPresence != null && guestPresence.IsPresent && _body != null && _body.Wave())
            {
                yield return new WaitForSeconds(waveSeconds);
            }

            // Los dos en plano entero: él sale por la izquierda y Sonia vuelve por la derecha.
            ShotPose duo;
            if (_framing != null && TryDuoShot(out duo))
            {
                _framing.SetOverride(duo);
            }

            if (guestPresence != null)
            {
                guestPresence.SetPresent(false, null, false);
            }

            yield return new WaitForSeconds(soniaReturnDelaySeconds);
            if (_soniaPresence != null)
            {
                _soniaPresence.ReleaseFromGuest(false);
            }

            float until = Time.time + (walkTimeoutSeconds * 1.5f);
            while (Time.time < until
                   && ((guestPresence != null && !guestPresence.IsAway)
                       || (_soniaPresence != null && !_soniaPresence.IsPresent && !_soniaPresence.IsAway)))
            {
                yield return null;
            }

            if (_framing != null)
            {
                _framing.ClearOverride();
            }

            SetStage(Stage.Off);
            Send("off");
            Log("Sonia de vuelta");
            _routine = null;
        }

        private IEnumerator LeaveInstant()
        {
            SetStage(Stage.Off);
            StopVoice();
            ClearSoniaLook();
            if (handshake != null)
            {
                handshake.Cancel();
            }

            ReleaseHolds();

            if (_body != null)
            {
                _body.SetAttention(null);
            }

            if (guestPresence != null)
            {
                guestPresence.SetPresent(false, null, true);
            }

            if (_soniaPresence != null)
            {
                _soniaPresence.ReleaseFromGuest(true);
            }

            if (_framing != null)
            {
                _framing.ClearOverride();
                _framing.SnapNextFrame();
            }

            Send("off");
            Log("fuera (sin animación)");
            _routine = null;
            yield break;
        }

        // ------------------------------------------------------------------
        // Miradas
        // ------------------------------------------------------------------

        private Transform GuestHead()
        {
            return guestState != null ? guestState.HeadBone : null;
        }

        private Transform SoniaHead()
        {
            return _soniaState != null ? _soniaState.HeadBone : null;
        }

        /// <summary>Sonia mira al invitado (cada frame mientras dure).</summary>
        private void SoniaLooksAt(Transform target)
        {
            if (_soniaState != null && target != null)
            {
                _soniaState.SetLookOverride(target.position + (Vector3.up * 0.04f), soniaLookWeight);
            }
        }

        /// <summary>Devuelve a cada uno a lo suyo tras el apretón de manos (o si se corta a mitad).</summary>
        private void ReleaseHolds()
        {
            _soniaHold.Release(_soniaChoreographer);
            if (_body != null)
            {
                _body.Hold(false);
            }
        }

        private void ClearSoniaLook()
        {
            // Solo si no camina: entonces la mirada es de su presencia.
            if (_soniaState != null && (_soniaPresence == null || _soniaPresence.IsPresent))
            {
                _soniaState.ClearLookOverride();
            }
        }

        // ------------------------------------------------------------------
        // Encuadres
        // ------------------------------------------------------------------

        /// <summary>
        /// Los dos en plano entero: el de la salida caminando, centrado entre
        /// Sonia y la marca del invitado y, si no caben, algo más atrás.
        /// </summary>
        private bool TryDuoShot(out ShotPose pose)
        {
            pose = default(ShotPose);
            if (_framing == null || !_framing.IsReady || sonia == null)
            {
                return false;
            }

            ShotPose full = _framing.FullBodyShot;
            Vector3 right = Flat(full.Rotation * Vector3.right);
            Vector3 forward = Flat(full.Rotation * Vector3.forward);
            if (right.sqrMagnitude < 0.0001f || forward.sqrMagnitude < 0.0001f)
            {
                return false;
            }

            right.Normalize();
            forward.Normalize();
            Vector3 soniaMark = sonia.transform.position;
            Vector3 guestMark = transform.position;
            float span = Vector3.Dot(guestMark - soniaMark, right);
            float lateral = span * 0.5f;

            // Ancho que se ve a la distancia de los dos y el que hace falta.
            Camera view = _framing.TargetCamera;
            float aspect = view != null && view.aspect > 0.01f ? view.aspect : 9f / 16f;
            float tanHalf = Mathf.Tan(full.FieldOfView * 0.5f * Mathf.Deg2Rad) * aspect;
            float depth = Mathf.Max(0.5f, Vector3.Dot(soniaMark - full.Position, forward));
            float visible = depth * tanHalf;
            float needed = (Mathf.Abs(span) * 0.5f) + duoSideMargin;
            float back = needed > visible ? (needed - visible) / Mathf.Max(0.01f, tanHalf) : 0f;
            pose = new ShotPose(full.Position + (right * lateral) - (forward * back), full.Rotation, full.FieldOfView);
            return true;
        }

        /// <summary>
        /// El plano medio de Sonia, llevado a la cabeza del invitado: el mismo
        /// encuadre (con los ajustes de «Developer») para quien esté hablando.
        /// </summary>
        private ShotPose GuestLiveShot()
        {
            ShotPose shot = _framing.BaseShot;
            Transform head = GuestHead();
            if (head == null)
            {
                return shot;
            }

            Vector3 reference;
            if (_haveSoniaHeadRest)
            {
                reference = _soniaHeadRest;
            }
            else
            {
                // Sin medir a Sonia: a la altura del invitado, en el sitio de Sonia.
                reference = sonia != null ? sonia.transform.position : Vector3.zero;
                reference.y = head.position.y;
            }

            Vector3 right = Flat(shot.Rotation * Vector3.right);
            if (right.sqrMagnitude < 0.0001f)
            {
                return shot;
            }

            right.Normalize();
            Vector3 delta = head.position - reference;
            Vector3 offset = (right * Vector3.Dot(delta, right)) + (Vector3.up * delta.y);
            return new ShotPose(shot.Position + offset, shot.Rotation, shot.FieldOfView);
        }

        private static Vector3 Flat(Vector3 v)
        {
            v.y = 0f;
            return v;
        }

        // ------------------------------------------------------------------
        // Utilidades
        // ------------------------------------------------------------------

        private void Send(string phase)
        {
            if (client != null)
            {
                client.SendGuestState(phase);
            }
        }

        private void Log(string message)
        {
            if (logEvents)
            {
                Debug.Log("[Sonia] Modo Jean: " + message, this);
            }
        }

        /// <summary>
        /// Para pruebas sin orquestador: encola una voz entera como si llegara de
        /// la sala (trozos de 100 ms, la última marcada), con la tasa dada.
        /// </summary>
        public void DebugPlayVoice(float[] samples, int sampleRate, int utteranceId)
        {
            if (samples == null || samples.Length == 0 || guestPlayer == null)
            {
                return;
            }

            guestPlayer.SetSourceSampleRate(sampleRate);
            int chunk = Mathf.Max(1, sampleRate / 10);
            for (int start = 0; start < samples.Length; start += chunk)
            {
                int count = Mathf.Min(chunk, samples.Length - start);
                float[] part = new float[count];
                System.Array.Copy(samples, start, part, 0, count);
                HandleGuestAudio(new AudioFrame
                {
                    UtteranceId = utteranceId,
                    IsLast = start + count >= samples.Length,
                    Samples = part
                });
            }
        }
    }
}
