// Raíz de la escena de Sonia: enlaza el cliente WebSocket con el audio, el
// lip-sync, el estado del avatar, el panel de imágenes y la cámara, y aplica los
// ajustes de kiosco para el stand.

using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>
    /// Único punto donde se conectan los componentes entre sí. Si falta alguno,
    /// el resto sigue funcionando.
    /// </summary>
    [DisallowMultipleComponent]
    public class SoniaBootstrap : MonoBehaviour
    {
        [Header("Componentes")]
        [SerializeField]
        [Tooltip("Cliente WebSocket hacia el orquestador.")]
        private SoniaClient client;

        [SerializeField]
        [Tooltip("Reproductor del audio en streaming.")]
        private AudioStreamPlayer audioPlayer;

        [SerializeField]
        [Tooltip("Lip-sync por visemas o por envolvente.")]
        private LipSyncController lipSync;

        [SerializeField]
        [Tooltip("Animaciones, mirada y parpadeo del avatar.")]
        private AvatarStateController avatarState;

        [SerializeField]
        [Tooltip("Coreógrafo: elige el clip de cada estado, los gestos del idle y el saludo. Opcional.")]
        private AvatarChoreographer choreographer;

        [SerializeField]
        [Tooltip("Abre el plano de la cámara durante los bailes y el saludo. Opcional.")]
        private CameraFramingController cameraFraming;

        [SerializeField]
        [Tooltip("Panel de imágenes de la escena.")]
        private ImagePanelController imagePanel;

        [SerializeField]
        [Tooltip("Envío de capturas de webcam. Solo con VISION_SOURCE=unity.")]
        private WebcamFrameSender webcam;

        [SerializeField]
        [Tooltip("HUD de depuración. Opcional.")]
        private SoniaDebugUI debugUI;

        [SerializeField]
        [Tooltip("Salida y entrada caminando (modo Fuera) con su letrero. Si la escena no lo trae, se añade por código en este objeto.")]
        private PresenceController presence;

        [SerializeField]
        [Tooltip("Gestos de Genies al hablar (los elige el director de gestos del orquestador, mensaje gesture). Si está vacío se busca junto al coreógrafo.")]
        private GeniesGestureLayer gestureLayer;

        [Header("Modo Fuera")]
        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("Un presence 'fuera' que llega en estos segundos tras el hello (el orquestador lo repite a cada cliente nuevo) se aplica sin animación: Sonia ya oculta y el letrero puesto.")]
        private float presenceInstantWindowSeconds = 2f;

        [Header("Modo kiosco")]
        [SerializeField]
        [Tooltip("Seguir corriendo aunque la ventana pierda el foco. Imprescindible en el stand.")]
        private bool runInBackground = true;

        [SerializeField]
        [Tooltip("Impedir que la pantalla se apague.")]
        private bool preventScreenSleep = true;

        [SerializeField]
        [Tooltip("Mostrar el cursor del ratón.")]
        private bool showCursor = true;

        [SerializeField]
        [Tooltip("Fotogramas por segundo objetivo. 0 deja el valor por defecto de la plataforma.")]
        private int targetFrameRate = 60;

        [Header("Sincronía")]
        [SerializeField]
        [Tooltip("Retrasar el estado 'hablando' (gestos, cejas) hasta que llegue el primer audio de la frase. El orquestador manda speech_start y el estado al empezar a sintetizar, y la voz tarda entre 0,3 y 1,5 s en llegar: sin esto Sonia gesticula con la boca cerrada.")]
        private bool waitAudioBeforeSpeaking = true;

        [SerializeField]
        [Range(0.5f, 10f)]
        [Tooltip("Segundos de espera del audio antes de aplicar el estado 'hablando' igualmente (por si el TTS falla en silencio). Los gestos de hablar siguen en pausa hasta que llegue audio de verdad.")]
        private float speakingAudioTimeout = 4f;

        [SerializeField]
        [Range(0f, 3f)]
        [Tooltip("Si en mitad de una respuesta se acaba el audio y no llega más en estos segundos, los gestos de hablar se pausan (espera atenta) hasta que vuelva la voz. 0 lo desactiva.")]
        private float speechGapPauseSeconds = 0.4f;


        [Header("Registro")]
        [SerializeField]
        [Tooltip("Escribir en la consola los eventos importantes del protocolo.")]
        private bool logEvents = true;

        // Frase anunciada por speech_start cuyo audio aún no ha llegado.
        private int _pendingUtteranceId = -1;
        private bool _pendingSpeechStart;
        private bool _pendingSpeakingState;
        private float _pendingSince;
        private int _lastAudioUtteranceId = -1;
        // Frase cuya voz ya suena (la última que arrancó la gesticulación) y la última cerrada.
        private int _speakingUtteranceId = -1;
        private int _endedUtteranceId = -1;
        // Gesto del director que espera a su frase (o a la siguiente, si es de apertura).
        private string _pendingGesture;
        private int _pendingGestureUtterance = -1;
        private float _pendingGestureUntil;
        private const float GestureWaitSeconds = 4f;
        // Momento en que se agotó el audio en mitad de 'hablando' (-1 si suena).
        private float _audioDrainedAt = -1f;
        // Imagen anunciada que espera a que la mano llegue arriba.
        private ShowImageMessage _pendingImage;
        // Momento del último hello (para aplicar sin animación el presence que lo sigue).
        private float _helloAt = -999f;

        // Set de animaciones completo (el asset) y la copia sin lo que el panel
        // desactivó, que es la que usa el coreógrafo para lo que hace solo.
        private SoniaMotionSet _fullMotionSet;
        private SoniaMotionSet _filteredMotionSet;
        private readonly HashSet<string> _disabledClips = new HashSet<string>();
        private bool _debugQuiet;

        // Último clip avisado con animation_playing (para mandar solo los cambios).
        private string _reportedClip;
        private bool _clipReported;

        private void Awake()
        {
            ResolveReferences();
            ApplyKioskSettings();
            ScreenshotService.InstallFromCommandLine(gameObject);
        }

        private void OnEnable()
        {
            if (client != null)
            {
                client.OnConnected += HandleConnected;
                client.OnDisconnected += HandleDisconnected;
                client.OnHello += HandleHello;
                client.OnState += HandleState;
                client.OnTranscript += HandleTranscript;
                client.OnSpeechStart += HandleSpeechStart;
                client.OnAudioFrame += HandleAudioFrame;
                client.OnVisemes += HandleVisemes;
                client.OnEnvelope += HandleEnvelope;
                client.OnSpeechEnd += HandleSpeechEnd;
                client.OnStopSpeaking += HandleStopSpeaking;
                client.OnShowImage += HandleShowImage;
                client.OnHideImage += HandleHideImage;
                client.OnAttention += HandleAttention;
                client.OnPlayAnimation += HandlePlayAnimation;
                client.OnGesture += HandleGesture;
                client.OnSetDisabledAnimations += HandleSetDisabledAnimations;
                client.OnSetDebug += HandleSetDebug;
                client.OnSetTuning += HandleSetTuning;
                client.OnPresence += HandlePresence;
                client.OnSetVolume += HandleSetVolume;
                client.OnError += HandleError;
                client.OnRequestFrame += HandleRequestFrame;
            }

            if (audioPlayer != null)
            {
                audioPlayer.OnUtterancePlaybackDone += HandlePlaybackDone;
            }
        }

        private void OnDisable()
        {
            if (client != null)
            {
                client.OnConnected -= HandleConnected;
                client.OnDisconnected -= HandleDisconnected;
                client.OnHello -= HandleHello;
                client.OnState -= HandleState;
                client.OnTranscript -= HandleTranscript;
                client.OnSpeechStart -= HandleSpeechStart;
                client.OnAudioFrame -= HandleAudioFrame;
                client.OnVisemes -= HandleVisemes;
                client.OnEnvelope -= HandleEnvelope;
                client.OnSpeechEnd -= HandleSpeechEnd;
                client.OnStopSpeaking -= HandleStopSpeaking;
                client.OnShowImage -= HandleShowImage;
                client.OnHideImage -= HandleHideImage;
                client.OnAttention -= HandleAttention;
                client.OnPlayAnimation -= HandlePlayAnimation;
                client.OnGesture -= HandleGesture;
                client.OnSetDisabledAnimations -= HandleSetDisabledAnimations;
                client.OnSetDebug -= HandleSetDebug;
                client.OnSetTuning -= HandleSetTuning;
                client.OnPresence -= HandlePresence;
                client.OnSetVolume -= HandleSetVolume;
                client.OnError -= HandleError;
                client.OnRequestFrame -= HandleRequestFrame;
            }

            if (audioPlayer != null)
            {
                audioPlayer.OnUtterancePlaybackDone -= HandlePlaybackDone;
            }
        }

        private void ResolveReferences()
        {
            if (client == null)
            {
                client = GetComponentInChildren<SoniaClient>(true);
            }

            if (audioPlayer == null)
            {
                audioPlayer = GetComponentInChildren<AudioStreamPlayer>(true);
            }

            if (lipSync == null)
            {
                lipSync = GetComponentInChildren<LipSyncController>(true);
            }

            if (avatarState == null)
            {
                avatarState = GetComponentInChildren<AvatarStateController>(true);
            }

            if (choreographer == null)
            {
                choreographer = GetComponentInChildren<AvatarChoreographer>(true);
            }

            if (gestureLayer == null && choreographer != null)
            {
                gestureLayer = choreographer.GetComponent<GeniesGestureLayer>();
            }

            if (cameraFraming == null)
            {
                cameraFraming = GetComponentInChildren<CameraFramingController>(true);
            }

            if (imagePanel == null)
            {
                // Solo se busca entre los hijos: si el panel vive en otra parte de
                // la escena hay que asignarlo a mano en el inspector.
                imagePanel = GetComponentInChildren<ImagePanelController>(true);
            }

            if (webcam == null)
            {
                webcam = GetComponentInChildren<WebcamFrameSender>(true);
            }

            if (debugUI == null)
            {
                debugUI = GetComponentInChildren<SoniaDebugUI>(true);
            }

            if (presence == null)
            {
                presence = GetComponentInChildren<PresenceController>(true);
            }

            if (presence == null)
            {
                // Por código, para no tocar la escena: se monta solo con lo que
                // encuentra (coreógrafo, mirada, cámara) y crea su letrero.
                presence = gameObject.AddComponent<PresenceController>();
            }

            if (cameraFraming != null)
            {
                cameraFraming.Presence = presence;
            }

            if (GetComponent<TriviaController>() == null)
            {
                // También por código: pinta la trivia en el HUD (tarjeta, confeti,
                // gorro de fiesta) cuando la manda el orquestador.
                gameObject.AddComponent<TriviaController>();
            }

            if (GetComponent<StageScreen>() == null)
            {
                // También por código: la pantalla del stand (fondo de la marca,
                // logo, QR, invitación a hablar y subtítulos).
                gameObject.AddComponent<StageScreen>();
            }

            if (GetComponent<AvatarEditorLauncher>() == null)
            {
                // También por código: abre la escena del editor de personaje cuando
                // la pide el panel y la cierra al guardar o salir.
                gameObject.AddComponent<AvatarEditorLauncher>();
            }
        }

        private void ApplyKioskSettings()
        {
            Application.runInBackground = runInBackground;

            if (preventScreenSleep)
            {
                Screen.sleepTimeout = SleepTimeout.NeverSleep;
            }

            Cursor.visible = showCursor;

            if (targetFrameRate > 0)
            {
                Application.targetFrameRate = targetFrameRate;
            }
        }

        // ------------------------------------------------------------------
        // Eventos del protocolo
        // ------------------------------------------------------------------

        private void HandleConnected()
        {
            if (logEvents)
            {
                Debug.Log("[Sonia] Conectada al orquestador.", this);
            }
        }

        private void HandleDisconnected()
        {
            _pendingSpeakingState = false;
            _pendingSpeechStart = false;
            _pendingUtteranceId = -1;
            if (logEvents)
            {
                Debug.Log("[Sonia] Conexión perdida; el cliente reintentará.", this);
            }

            if (audioPlayer != null)
            {
                audioPlayer.Flush();
            }

            if (lipSync != null)
            {
                lipSync.StopAndClose();
            }

            ApplyAvatarState(AvatarState.Idle);

            // Si se cae la conexión en mitad de un baile, la cámara se queda
            // abierta hasta que termine el clip. Mejor volver al plano medio ya.
            // Fuera (o saliendo) no: Sonia sigue fuera hasta que el orquestador
            // diga otra cosa al reconectar, y la cámara sigue en su plano.
            if (cameraFraming != null && (presence == null || presence.IsPresent))
            {
                cameraFraming.ResetToBase();
            }
        }

        /// <summary>
        /// Reparte el estado entre todos los componentes que animan al avatar. El
        /// que no esté asignado simplemente se salta.
        /// </summary>
        private void ApplyAvatarState(AvatarState state)
        {
            _audioDrainedAt = -1f;
            if (avatarState != null)
            {
                avatarState.SetState(state);
            }

            if (choreographer != null)
            {
                choreographer.SetState(state);
            }
        }

        private void HandleHello(HelloMessage message)
        {
            if (message == null)
            {
                return;
            }

            _helloAt = Time.unscaledTime;
            if (audioPlayer != null)
            {
                audioPlayer.SetSourceSampleRate(message.SampleRate);
            }

            if (logEvents)
            {
                Debug.Log(
                    "[Sonia] hello: versión " + message.Version + ", " + message.SampleRate + " Hz, "
                    + message.Channels + " canal(es), formato " + message.Format,
                    this);
            }

            SendAnimationCatalog();
            _clipReported = false;
        }

        /// <summary>
        /// El set completo, tal cual lo asignó la escena. Se apunta la primera vez
        /// porque luego el coreógrafo recibe la copia filtrada.
        /// </summary>
        private SoniaMotionSet FullMotionSet
        {
            get
            {
                if (_fullMotionSet == null && choreographer != null)
                {
                    _fullMotionSet = choreographer.MotionSet;
                }

                return _fullMotionSet;
            }
        }

        /// <summary>Le dice al orquestador qué animaciones puede lanzar el panel una a una.</summary>
        private void SendAnimationCatalog()
        {
            if (client == null || FullMotionSet == null)
            {
                return;
            }

            List<KeyValuePair<string, string>> pairs = AnimationCatalog.ToPairs(AnimationCatalog.Build(FullMotionSet));
            GeniesGestureSet gestures = gestureLayer != null ? gestureLayer.Set : null;
            if (gestures != null)
            {
                foreach (GeniesGestureSet.Gesture gesture in gestures.gestures)
                {
                    if (gesture != null && gesture.clip != null && !string.IsNullOrEmpty(gesture.name))
                    {
                        pairs.Add(new KeyValuePair<string, string>(gesture.name, "sage"));
                    }
                }
            }

            client.SendAnimations(pairs);
            if (gestures != null)
            {
                client.SendGestureCatalog(gestures);
            }
        }

        private void HandleSetDisabledAnimations(SetDisabledAnimationsMessage message)
        {
            if (message == null)
            {
                return;
            }

            _disabledClips.Clear();
            if (message.Clips != null)
            {
                foreach (string clip in message.Clips)
                {
                    if (!string.IsNullOrEmpty(clip))
                    {
                        _disabledClips.Add(clip);
                    }
                }
            }

            ApplyMotionFilter();
            if (logEvents)
            {
                Debug.Log("[Sonia] animaciones que no usa por su cuenta: " + _disabledClips.Count, this);
            }
        }

        private void HandleSetDebug(SetDebugMessage message)
        {
            if (message == null)
            {
                return;
            }

            _debugQuiet = message.Enabled;
            ApplyMotionFilter();
            if (logEvents)
            {
                Debug.Log("[Sonia] modo debug " + (_debugQuiet ? "activado: nada automático" : "desactivado"), this);
            }
        }

        /// <summary>Ajustes de «Developer» del panel: boca (lip-sync) y encuadre de la cámara.</summary>
        private void HandleSetTuning(SetTuningMessage message)
        {
            if (message == null)
            {
                return;
            }

            MouthTuning mouth = message.Mouth ?? new MouthTuning();
            CameraTuning view = message.Camera ?? new CameraTuning();
            IdleTuning idle = message.Idle ?? new IdleTuning();
            if (lipSync != null)
            {
                lipSync.ApplyTuning(mouth.Open, mouth.Jaw, mouth.Closure, mouth.Speed);
            }

            if (avatarState != null)
            {
                avatarState.SetIdleTuning(idle.Breath, idle.Accents, idle.Speed);
            }

            if (cameraFraming != null)
            {
                cameraFraming.SetTuning(new Vector3(view.Side, view.Height, view.Distance), view.Zoom, view.Tilt);
            }

            if (logEvents)
            {
                Debug.Log("[Sonia] Developer: boca x" + mouth.Open.ToString("F2") + ", zoom x" + view.Zoom.ToString("F2"), this);
            }
        }

        /// <summary>
        /// Da al coreógrafo el set sin lo que no debe hacer por su cuenta: las
        /// animaciones desactivadas en el panel y, en modo debug, todos los gestos
        /// de atención, bailes, variaciones y asentimientos. Los bucles base, el
        /// caminar y el gesto de presentar imagen se quedan. Lo que se lanza desde
        /// el panel (play_animation) sale del set completo y suena igual.
        /// </summary>
        private void ApplyMotionFilter()
        {
            SoniaMotionSet full = FullMotionSet;
            if (choreographer == null || full == null)
            {
                return;
            }

            if (_filteredMotionSet != null)
            {
                Destroy(_filteredMotionSet);
                _filteredMotionSet = null;
            }

            if (_disabledClips.Count == 0 && !_debugQuiet)
            {
                choreographer.MotionSet = full;
                return;
            }

            SoniaMotionSet copy = Instantiate(full);
            copy.name = full.name + " (filtrado)";
            copy.talking = KeepEnabled(full.talking);
            copy.greeting = full.greeting != null && _disabledClips.Contains(full.greeting.name) ? null : full.greeting;
            copy.idleVariations = _debugQuiet ? new AnimationClip[0] : KeepEnabled(full.idleVariations);
            copy.thinkingVariations = _debugQuiet ? new AnimationClip[0] : KeepEnabled(full.thinkingVariations);
            copy.nods = _debugQuiet ? new AnimationClip[0] : KeepEnabled(full.nods);

            List<AttentionMotion> attention = new List<AttentionMotion>();
            if (!_debugQuiet && full.attention != null)
            {
                foreach (AttentionMotion motion in full.attention)
                {
                    if (motion != null && motion.clip != null && !_disabledClips.Contains(motion.clip.name))
                    {
                        attention.Add(motion);
                    }
                }
            }

            copy.attention = attention.ToArray();
            _filteredMotionSet = copy;
            choreographer.MotionSet = copy;
        }

        private AnimationClip[] KeepEnabled(AnimationClip[] clips)
        {
            List<AnimationClip> kept = new List<AnimationClip>();
            if (clips != null)
            {
                foreach (AnimationClip clip in clips)
                {
                    if (clip != null && !_disabledClips.Contains(clip.name))
                    {
                        kept.Add(clip);
                    }
                }
            }

            return kept.ToArray();
        }

        /// <summary>
        /// Avisa al panel de qué clip del catálogo suena (para resaltar su botón),
        /// solo cuando cambia. Los bucles base no cuentan: sin gesto, null.
        /// </summary>
        private void ReportPlayingAnimation()
        {
            if (client == null || !client.IsConnected || choreographer == null || choreographer.Player == null
                || !choreographer.Player.IsReady)
            {
                return;
            }

            MotionPlayer player = choreographer.Player;
            string playing = OneShotName(player.CurrentClip(MotionPlayer.BodyLayer))
                             ?? OneShotName(player.CurrentClip(MotionPlayer.UpperLayer))
                             ?? OneShotName(player.CurrentClip(MotionPlayer.RightArmLayer))
                             ?? (gestureLayer != null ? gestureLayer.Current : null);
            if (_clipReported && playing == _reportedClip)
            {
                return;
            }

            _clipReported = true;
            _reportedClip = playing;
            client.SendAnimationPlaying(playing);
        }

        private static string OneShotName(AnimationClip clip)
        {
            return clip != null && !clip.isLooping ? clip.name : null;
        }

        /// <summary>
        /// El panel pide una animación concreta: se reproduce una vez sobre el
        /// cuerpo y el coreógrafo vuelve a lo que tocaba en el estado actual.
        /// </summary>
        private void HandlePlayAnimation(PlayAnimationMessage message)
        {
            if (choreographer == null || message == null)
            {
                return;
            }

            AnimationCatalog.Entry entry;
            if (!AnimationCatalog.TryFind(FullMotionSet, message.Clip, out entry))
            {
                if (gestureLayer != null && gestureLayer.Has(message.Clip))
                {
                    // Gesto de Genies (grupo sage): suena en el estado que haya, para probarlo.
                    bool played = gestureLayer.Play(message.Clip);
                    if (logEvents)
                    {
                        Debug.Log("[Sonia] gesto de Genies pedido por el panel: " + message.Clip
                            + (played ? string.Empty : " (sin avatar todavía)"), this);
                    }

                    return;
                }

                Debug.LogWarning("[Sonia] se pidió una animación que no está en el set: " + message.Clip, this);
                return;
            }

            if (message.Whole)
            {
                choreographer.PlayReaction(entry.Clip);
            }
            else
            {
                choreographer.Preview(entry.Clip);
            }

            if (logEvents)
            {
                Debug.Log("[Sonia] animación pedida (" + (message.Whole ? "por voz" : "panel") + "): "
                    + entry.Clip.name, this);
            }
        }

        /// <summary>
        /// El director de gestos del orquestador pide un gesto de Genies para una
        /// frase. Suena cuando la voz de esa frase ya se oye y el coreógrafo lo
        /// permite (hablando, sin imagen, reacción ni saludo); si su frase ya
        /// terminó se descarta, y uno de apertura (sin frase) espera a la
        /// siguiente. Ninguno espera más de <see cref="GestureWaitSeconds"/>.
        /// </summary>
        private void HandleGesture(GestureMessage message)
        {
            if (message == null || gestureLayer == null)
            {
                return;
            }

            if (!gestureLayer.Has(message.Name))
            {
                Debug.LogWarning("[Sonia] el director pidió un gesto que no está en el set: " + message.Name, this);
                return;
            }

            if (_debugQuiet || _disabledClips.Contains(message.Name))
            {
                return;
            }

            int utterance = message.UtteranceId.HasValue ? message.UtteranceId.Value : -1;
            if (utterance >= 0 && utterance <= _endedUtteranceId)
            {
                if (logEvents)
                {
                    Debug.Log("[Sonia] gesto " + message.Name + " descartado: la frase " + utterance + " ya terminó", this);
                }

                return;
            }

            _pendingGesture = message.Name;
            _pendingGestureUtterance = utterance;
            _pendingGestureUntil = Time.time + GestureWaitSeconds;
            TryStartPendingGesture();
        }

        /// <summary>La voz de una frase empezó a sonar: puede arrancar su gesto.</summary>
        private void OnSpeechAudible(int utteranceId)
        {
            _speakingUtteranceId = Mathf.Max(_speakingUtteranceId, utteranceId);
            if (!string.IsNullOrEmpty(_pendingGesture))
            {
                TryStartPendingGesture();
            }
        }

        private void TryStartPendingGesture()
        {
            // Tras una recarga del editor un string privado puede llegar vacío en vez de null.
            if (string.IsNullOrEmpty(_pendingGesture))
            {
                return;
            }

            bool expired = Time.time > _pendingGestureUntil;
            bool passed = _pendingGestureUtterance >= 0
                          && (_pendingGestureUtterance <= _endedUtteranceId || _pendingGestureUtterance < _speakingUtteranceId);
            if (expired || passed)
            {
                if (logEvents)
                {
                    Debug.Log("[Sonia] gesto " + _pendingGesture + " descartado: " + (passed ? "su frase ya pasó" : "no llegó a sonar"), this);
                }

                ClearPendingGesture();
                return;
            }

            bool audible = _speakingUtteranceId >= 0 && _speakingUtteranceId > _endedUtteranceId;
            if (_pendingGestureUtterance >= 0 ? _pendingGestureUtterance != _speakingUtteranceId || !audible : !audible)
            {
                return;
            }

            if (choreographer == null || !choreographer.CanTalkGesture)
            {
                return;
            }

            string name = _pendingGesture;
            ClearPendingGesture();
            if (gestureLayer.Play(name) && logEvents)
            {
                Debug.Log("[Sonia] gesto " + name + " con la frase " + _speakingUtteranceId, this);
            }
        }

        private void ClearPendingGesture()
        {
            _pendingGesture = null;
            _pendingGestureUtterance = -1;
        }

        private void HandleState(StateMessage message)
        {
            if (message == null)
            {
                return;
            }

            AvatarState state = AvatarStateController.ParseState(message.State);
            if (state == AvatarState.Speaking && waitAudioBeforeSpeaking && _pendingUtteranceId >= 0
                && _lastAudioUtteranceId < _pendingUtteranceId)
            {
                // La voz todavía no ha llegado: se mantiene el estado anterior
                // (pensando) y se aplica 'hablando' con el primer chunk de audio.
                _pendingSpeakingState = true;
            }
            else
            {
                _pendingSpeakingState = false;
                ApplyAvatarState(state);
            }

            // Si alguien se acerca después de un buen rato sin nadie, Sonia saluda
            // con la mano. El propio componente decide si toca o si acaba de hacerlo.
            if (state == AvatarState.Listening && choreographer != null)
            {
                choreographer.PlayGreeting();
            }

            if (logEvents)
            {
                Debug.Log("[Sonia] estado: " + message.State, this);
            }
        }

        private void HandleTranscript(TranscriptMessage message)
        {
            if (logEvents && message != null && message.Final)
            {
                Debug.Log("[Sonia] " + message.Role + ": " + message.Text, this);
            }
        }

        private void HandleSpeechStart(SpeechStartMessage message)
        {
            // Una frase de la animación de stand (ambient) no toca el cuerpo: si
            // está bailando, sigue bailando mientras "canta". Cada frase de una
            // respuesta real estrena una forma de gesticular distinta.
            bool ambient = message != null && message.Ambient;
            if (!ambient && message != null)
            {
                _pendingUtteranceId = message.UtteranceId;
                _pendingSince = Time.time;
                if (waitAudioBeforeSpeaking && _lastAudioUtteranceId < message.UtteranceId)
                {
                    _pendingSpeechStart = true;
                }
                else
                {
                    _pendingSpeechStart = false;
                    if (choreographer != null)
                    {
                        choreographer.NotifySpeechStart();
                    }

                    OnSpeechAudible(message.UtteranceId);
                }
            }

            if (logEvents && message != null)
            {
                Debug.Log("[Sonia] frase " + message.UtteranceId + ": " + message.Text, this);
            }
        }

        /// <summary>Aplica lo que esperaba al audio: estado 'hablando' y arranque de la gesticulación.</summary>
        private void ReleasePendingSpeech(string why)
        {
            if (_pendingSpeakingState)
            {
                _pendingSpeakingState = false;
                ApplyAvatarState(AvatarState.Speaking);
            }

            if (_pendingSpeechStart)
            {
                _pendingSpeechStart = false;
                if (choreographer != null)
                {
                    choreographer.NotifySpeechStart();
                }

                OnSpeechAudible(_pendingUtteranceId);
            }

            if (logEvents && why != null)
            {
                Debug.Log("[Sonia] 'hablando' aplicado " + why, this);
            }
        }

        private void Update()
        {
            ReportPlayingAnimation();
            if (!string.IsNullOrEmpty(_pendingGesture))
            {
                TryStartPendingGesture();
            }

            if (_pendingSpeakingState && Time.time - _pendingSince > speakingAudioTimeout)
            {
                // El TTS tarda demasiado: se aplica el estado (cejas, cabeza) pero
                // sin gesticular; los gestos esperan al primer chunk de audio.
                _pendingSpeakingState = false;
                ApplyAvatarState(AvatarState.Speaking);
                if (choreographer != null)
                {
                    choreographer.SetSpeechPaused(true);
                }

                if (logEvents)
                {
                    Debug.Log("[Sonia] 'hablando' sin audio tras " + speakingAudioTimeout + " s: gestos en pausa", this);
                }
            }

            if (_pendingImage != null && choreographer != null)
            {
                if (choreographer.IsPresentHolding)
                {
                    ShowImageMessage message = _pendingImage;
                    _pendingImage = null;
                    ShowImageNow(message);
                }
                else if (!choreographer.IsPresenting)
                {
                    // El gesto se cortó (otro estado, otro clip): la imagen sale igual.
                    ShowImageMessage message = _pendingImage;
                    _pendingImage = null;
                    ShowImageNow(message);
                }
            }

            if (_audioDrainedAt >= 0f && speechGapPauseSeconds > 0f && choreographer != null
                && !choreographer.SpeechPaused && Time.time - _audioDrainedAt > speechGapPauseSeconds
                && avatarState != null && avatarState.State == AvatarState.Speaking)
            {
                choreographer.SetSpeechPaused(true);
            }
        }

        /// <summary>El orquestador pide un gesto de atención (por ejemplo un baile para cantar encima).</summary>
        private void HandleAttention(AttentionMessage message)
        {
            if (choreographer == null || message == null)
            {
                return;
            }

            AttentionCategory category = AttentionCategory.Soft;
            string name = (message.Category ?? string.Empty).ToLowerInvariant();
            if (name == "greeting" || name == "wave")
            {
                // Saludo con la mano ya (botón del panel, modo saludos), sin las
                // condiciones del saludo automático. En idle o escuchando.
                bool waved = choreographer.PlayGreetingNow();
                if (logEvents)
                {
                    Debug.Log("[Sonia] saludo pedido por el orquestador" + (waved ? string.Empty : " (ahora no toca)"), this);
                }

                return;
            }

            if (name == "dance")
            {
                category = AttentionCategory.Dance;
            }
            else if (name == "fourth_wall" || name == "fourthwall")
            {
                category = AttentionCategory.FourthWall;
            }

            choreographer.PlayAttention(category, message.Clip);

            if (logEvents)
            {
                Debug.Log("[Sonia] atención pedida por el orquestador: " + message.Category, this);
            }
        }

        private void HandleAudioFrame(AudioFrame frame)
        {
            if (audioPlayer != null)
            {
                audioPlayer.Enqueue(frame);
            }

            if (frame.UtteranceId > _lastAudioUtteranceId)
            {
                _lastAudioUtteranceId = frame.UtteranceId;
            }

            if ((_pendingSpeakingState || _pendingSpeechStart) && frame.UtteranceId >= _pendingUtteranceId)
            {
                ReleasePendingSpeech(null);
            }

            // Vuelve la voz: se retoman los gestos si estaban en pausa.
            _audioDrainedAt = -1f;
            if (choreographer != null && choreographer.SpeechPaused)
            {
                choreographer.SetSpeechPaused(false);
            }
        }

        private void HandleVisemes(VisemesMessage message)
        {
            if (lipSync != null)
            {
                lipSync.SetVisemes(message);
            }
        }

        private void HandleEnvelope(EnvelopeMessage message)
        {
            if (lipSync != null)
            {
                lipSync.SetEnvelope(message);
            }
        }

        private void HandleSpeechEnd(SpeechEndMessage message)
        {
            if (message == null)
            {
                return;
            }

            // Red de seguridad por si no llegó el bit de último chunk.
            if (audioPlayer != null)
            {
                audioPlayer.MarkUtteranceComplete(message.UtteranceId);
            }

            _endedUtteranceId = Mathf.Max(_endedUtteranceId, message.UtteranceId);
            if (!string.IsNullOrEmpty(_pendingGesture))
            {
                TryStartPendingGesture();
            }
        }

        private void HandleStopSpeaking(StopSpeakingMessage message)
        {
            StopSpeechNow();

            if (logEvents)
            {
                Debug.Log("[Sonia] stop_speaking: " + (message != null ? message.Reason : "?"), this);
            }
        }

        /// <summary>Descarta el audio en cola y cierra la boca (stop_speaking y salida a "Fuera").</summary>
        private void StopSpeechNow()
        {
            _pendingSpeakingState = false;
            _pendingSpeechStart = false;
            ClearPendingGesture();
            if (gestureLayer != null)
            {
                gestureLayer.Stop();
            }

            _audioDrainedAt = -1f;
            if (audioPlayer != null)
            {
                audioPlayer.Flush();
            }

            if (lipSync != null)
            {
                lipSync.StopAndClose();
            }
        }

        /// <summary>
        /// Modo "Fuera" del panel. Al irse corta la voz y la boca (como
        /// stop_speaking) y retira la imagen; la salida caminando, el letrero y
        /// la vuelta los lleva PresenceController. El presence que el orquestador
        /// repite justo tras el hello se aplica sin animación.
        /// </summary>
        private void HandlePresence(PresenceMessage message)
        {
            if (message == null || presence == null)
            {
                return;
            }

            bool leaving = !message.Present && presence.TargetPresent;
            if (leaving)
            {
                StopSpeechNow();
                HideImageNow();
            }

            bool instant = !message.Present && Time.unscaledTime - _helloAt <= presenceInstantWindowSeconds;
            presence.SetPresent(message.Present, message.Message, instant);

            if (logEvents)
            {
                Debug.Log(
                    "[Sonia] presence: " + (message.Present ? "en pantalla" : "fuera")
                    + (instant ? " (sin animación)" : string.Empty)
                    + (string.IsNullOrEmpty(message.Message) ? string.Empty : ", \"" + message.Message + "\""),
                    this);
            }
        }

        /// <summary>Volumen de la voz (0 a 1,5).</summary>
        private void HandleSetVolume(SetVolumeMessage message)
        {
            if (message == null || audioPlayer == null)
            {
                return;
            }

            audioPlayer.SetVolume(message.Value);
            if (logEvents)
            {
                Debug.Log("[Sonia] set_volume: " + audioPlayer.Volume.ToString("F2"), this);
            }
        }

        private void HandleShowImage(ShowImageMessage message)
        {
            if (imagePanel == null || message == null)
            {
                return;
            }

            // Sonia levanta la mano y señala; la imagen aparece encima del dedo
            // cuando la mano llega arriba (ver Update), no antes.
            if (choreographer != null && choreographer.BeginPresent())
            {
                _pendingImage = message;
            }
            else
            {
                _pendingImage = null;
                ShowImageNow(message);
            }

            if (logEvents)
            {
                Debug.Log("[Sonia] show_image: " + message.ImageId + " (" + message.Source + ")", this);
            }
        }

        private void ShowImageNow(ShowImageMessage message)
        {
            // Elemento de pantalla: el panel se coloca en su sitio fijo al mostrarse.
            imagePanel.Show(message);

            if (avatarState != null)
            {
                avatarState.SetImagePanel(imagePanel.PanelTransform, imagePanel.IsVisible);
            }
        }

        private void HandleHideImage(HideImageMessage message)
        {
            if (imagePanel == null)
            {
                return;
            }

            HideImageNow();

            if (logEvents)
            {
                Debug.Log("[Sonia] hide_image", this);
            }
        }

        /// <summary>Retira la imagen (y la que esperaba a la mano) y suelta el gesto de señalar.</summary>
        private void HideImageNow()
        {
            _pendingImage = null;
            if (imagePanel == null)
            {
                return;
            }

            imagePanel.Hide();
            if (choreographer != null)
            {
                choreographer.EndPresent();
            }

            if (avatarState != null)
            {
                avatarState.SetImagePanel(imagePanel.PanelTransform, false);
            }
        }

        private void HandleError(ErrorMessage message)
        {
            if (message != null)
            {
                Debug.LogWarning("[Sonia] error del orquestador: " + message.Message, this);
            }
        }

        private void HandleRequestFrame(RequestFrameMessage message)
        {
            if (webcam != null)
            {
                webcam.RequestFrameNow();
            }
            else if (logEvents)
            {
                Debug.Log("[Sonia] request_frame pero no hay WebcamFrameSender activo.", this);
            }
        }

        private void HandlePlaybackDone(int utteranceId)
        {
            if (client != null)
            {
                client.SendPlaybackDone(utteranceId);
            }

            // Se agotó lo que había: si el orquestador sigue en 'hablando' y no
            // manda más audio enseguida, los gestos se pausan (ver Update).
            if (_lastAudioUtteranceId <= utteranceId)
            {
                _audioDrainedAt = Time.time;
            }

            if (lipSync != null)
            {
                lipSync.NotifyUtteranceFinished(utteranceId);
            }

            if (logEvents)
            {
                Debug.Log("[Sonia] playback_done: " + utteranceId, this);
            }
        }
    }
}
