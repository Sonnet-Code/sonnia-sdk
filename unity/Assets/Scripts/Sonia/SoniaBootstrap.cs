// Raíz de la escena de Sonia: enlaza el cliente WebSocket con el audio, el
// lip-sync, el estado del avatar, el panel de imágenes y la cámara, y aplica los
// ajustes de kiosco para el stand.

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

        [Header("Registro")]
        [SerializeField]
        [Tooltip("Escribir en la consola los eventos importantes del protocolo.")]
        private bool logEvents = true;

        private void Awake()
        {
            ResolveReferences();
            ApplyKioskSettings();
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
            if (cameraFraming != null)
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
        }

        private void HandleState(StateMessage message)
        {
            if (message == null)
            {
                return;
            }

            AvatarState state = AvatarStateController.ParseState(message.State);
            ApplyAvatarState(state);

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
            // Cada frase estrena una forma de gesticular distinta de la anterior.
            if (choreographer != null)
            {
                choreographer.NotifySpeechStart();
            }

            if (logEvents && message != null)
            {
                Debug.Log("[Sonia] frase " + message.UtteranceId + ": " + message.Text, this);
            }
        }

        private void HandleAudioFrame(AudioFrame frame)
        {
            if (audioPlayer != null)
            {
                audioPlayer.Enqueue(frame);
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
        }

        private void HandleStopSpeaking(StopSpeakingMessage message)
        {
            if (audioPlayer != null)
            {
                audioPlayer.Flush();
            }

            if (lipSync != null)
            {
                lipSync.StopAndClose();
            }

            if (logEvents)
            {
                Debug.Log("[Sonia] stop_speaking: " + (message != null ? message.Reason : "?"), this);
            }
        }

        private void HandleShowImage(ShowImageMessage message)
        {
            if (imagePanel == null)
            {
                return;
            }

            imagePanel.Show(message);

            if (avatarState != null)
            {
                avatarState.SetImagePanel(imagePanel.PanelTransform, imagePanel.IsVisible);
            }

            if (logEvents && message != null)
            {
                Debug.Log("[Sonia] show_image: " + message.ImageId + " (" + message.Source + ")", this);
            }
        }

        private void HandleHideImage(HideImageMessage message)
        {
            if (imagePanel == null)
            {
                return;
            }

            imagePanel.Hide();

            if (avatarState != null)
            {
                avatarState.SetImagePanel(imagePanel.PanelTransform, false);
            }

            if (logEvents)
            {
                Debug.Log("[Sonia] hide_image", this);
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
