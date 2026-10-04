// Cliente WebSocket hacia el orquestador de Sonia.
//
// Reglas de hilos, importantes:
//  - Todo el trabajo de red (conectar, recibir, parsear JSON, decodificar PCM)
//    ocurre en un Task de fondo. Ese hilo NUNCA toca la API de Unity.
//  - Los mensajes ya parseados se encolan en una ConcurrentQueue y se despachan
//    como eventos de C# en Update(), es decir, en el hilo principal.

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace Sonia
{
    /// <summary>
    /// Mantiene la conexión con el orquestador, reconecta sola y expone cada
    /// mensaje del protocolo como un evento de C# disparado en el hilo principal.
    /// </summary>
    [DisallowMultipleComponent]
    public class SoniaClient : MonoBehaviour
    {
        [Header("Conexión")]
        [SerializeField]
        [Tooltip("URL del WebSocket del orquestador. Por defecto ws://127.0.0.1:8765")]
        private string serverUrl = "ws://127.0.0.1:8765";

        [SerializeField]
        [Tooltip("Conectar automáticamente al arrancar la escena.")]
        private bool autoConnect = true;

        [SerializeField]
        [Tooltip("Espera inicial antes de reintentar la conexión, en segundos.")]
        private float reconnectDelaySeconds = 1f;

        [SerializeField]
        [Tooltip("Espera máxima entre reintentos, en segundos. El retardo se dobla hasta llegar aquí.")]
        private float maxReconnectDelaySeconds = 10f;

        [SerializeField]
        [Tooltip("Versión que Unity anuncia en client_hello.")]
        private string clientVersion = "0.1.0";

        [Header("Depuración")]
        [SerializeField]
        [Tooltip("Escribe en la consola cada mensaje recibido (salvo los frames de audio).")]
        private bool verboseLog;

        // ------------------------------------------------------------------
        // Eventos (siempre en el hilo principal)
        // ------------------------------------------------------------------

        /// <summary>Se ha establecido la conexión con el orquestador.</summary>
        public event Action OnConnected;

        /// <summary>Se ha perdido la conexión. El cliente reintentará solo.</summary>
        public event Action OnDisconnected;

        /// <summary>Formato del audio anunciado por el orquestador.</summary>
        public event Action<HelloMessage> OnHello;

        /// <summary>Cambio de estado del asistente.</summary>
        public event Action<StateMessage> OnState;

        /// <summary>Texto del usuario o de Sonia.</summary>
        public event Action<TranscriptMessage> OnTranscript;

        /// <summary>Empieza una frase sintetizada.</summary>
        public event Action<SpeechStartMessage> OnSpeechStart;

        /// <summary>Un chunk de audio PCM ya decodificado.</summary>
        public event Action<AudioFrame> OnAudioFrame;

        /// <summary>Visemas de una frase.</summary>
        public event Action<VisemesMessage> OnVisemes;

        /// <summary>Envolvente de amplitud de una frase.</summary>
        public event Action<EnvelopeMessage> OnEnvelope;

        /// <summary>No habrá más audio de esa frase.</summary>
        public event Action<SpeechEndMessage> OnSpeechEnd;

        /// <summary>Interrupción: hay que vaciar el buffer y cerrar la boca.</summary>
        public event Action<StopSpeakingMessage> OnStopSpeaking;

        /// <summary>Mostrar una imagen en el panel de la escena.</summary>
        public event Action<ShowImageMessage> OnShowImage;

        /// <summary>Retirar el panel de imágenes.</summary>
        public event Action<HideImageMessage> OnHideImage;

        /// <summary>Gesto de atención pedido por el orquestador (baile, cuarta pared, suave, saludo).</summary>
        public event Action<AttentionMessage> OnAttention;

        /// <summary>El panel pide una animación concreta del catálogo.</summary>
        public event Action<PlayAnimationMessage> OnPlayAnimation;

        /// <summary>Sonia se va de la pantalla (modo "Fuera") o vuelve.</summary>
        public event Action<PresenceMessage> OnPresence;

        /// <summary>Volumen de la voz.</summary>
        public event Action<SetVolumeMessage> OnSetVolume;

        /// <summary>Error informado por el orquestador.</summary>
        public event Action<ErrorMessage> OnError;

        /// <summary>El orquestador pide una captura de la cámara de Unity.</summary>
        public event Action<RequestFrameMessage> OnRequestFrame;

        // ------------------------------------------------------------------
        // Estado interno
        // ------------------------------------------------------------------

        private static readonly object ConnectedSignal = new object();
        private static readonly object DisconnectedSignal = new object();

        private readonly ConcurrentQueue<object> _inbox = new ConcurrentQueue<object>();
        private readonly SemaphoreSlim _sendLock = new SemaphoreSlim(1, 1);

        // [NonSerialized]: tras recompilar en Play, Unity conserva los campos
        // privados serializables pero mata el hilo de fondo; si _isConnected
        // sobreviviera como "true", el cliente parecería conectado sin recibir
        // nada. Con los campos a cero, Update vuelve a conectar.
        private volatile ClientWebSocket _socket;
        private CancellationTokenSource _cancellation;
        private Task _connectionTask;

        [NonSerialized]
        private bool _shuttingDown;

        [NonSerialized]
        private bool _isConnected;

        /// <summary>Cierto entre <see cref="OnConnected"/> y <see cref="OnDisconnected"/>.</summary>
        public bool IsConnected
        {
            get { return _isConnected; }
        }

        /// <summary>URL a la que se conecta este cliente.</summary>
        public string ServerUrl
        {
            get { return serverUrl; }
        }

        // ------------------------------------------------------------------
        // Ciclo de vida
        // ------------------------------------------------------------------

        private void Start()
        {
            if (autoConnect)
            {
                Connect();
            }
        }

        /// <summary>Arranca la tarea de conexión si no estaba ya en marcha.</summary>
        public void Connect()
        {
            if (_connectionTask != null || _shuttingDown)
            {
                return;
            }

            Uri uri;
            if (!Uri.TryCreate(serverUrl, UriKind.Absolute, out uri))
            {
                Debug.LogError("[Sonia] URL del orquestador inválida: " + serverUrl, this);
                return;
            }

            _cancellation = new CancellationTokenSource();
            float initialDelay = Mathf.Max(0.1f, reconnectDelaySeconds);
            float maxDelay = Mathf.Max(initialDelay, maxReconnectDelaySeconds);
            string version = clientVersion;
            CancellationToken token = _cancellation.Token;
            _connectionTask = Task.Run(
                () => ConnectionLoopAsync(uri, version, initialDelay, maxDelay, token),
                token);
        }

        private void Update()
        {
            // Sin tarea de conexión (arranque, o recarga de dominio en Play) se reconecta.
            if (_connectionTask == null && !_shuttingDown && autoConnect)
            {
                Connect();
            }

            object message;
            int processed = 0;
            while (_inbox.TryDequeue(out message))
            {
                Dispatch(message);
                processed++;
                if (processed >= 4096)
                {
                    // Salvaguarda para no congelar un frame si llega una avalancha.
                    break;
                }
            }
        }

        private void OnDestroy()
        {
            Shutdown();
        }

        private void OnApplicationQuit()
        {
            Shutdown();
        }

        private void Shutdown()
        {
            if (_shuttingDown)
            {
                return;
            }

            _shuttingDown = true;
            _isConnected = false;

            CancellationTokenSource cancellation = _cancellation;
            if (cancellation != null)
            {
                try
                {
                    cancellation.Cancel();
                }
                catch (ObjectDisposedException)
                {
                    // La tarea de fondo ya la había liberado.
                }
            }

            ClientWebSocket socket = _socket;
            _socket = null;
            if (socket != null)
            {
                try
                {
                    socket.Abort();
                }
                catch (Exception)
                {
                    // Cerrar de golpe es aceptable al salir.
                }
            }
        }

        // ------------------------------------------------------------------
        // Envío (llamar desde el hilo principal)
        // ------------------------------------------------------------------

        /// <summary>Avisa al orquestador de que el usuario ha interrumpido.</summary>
        public void SendInterrupt()
        {
            SendJson(Protocol.InterruptMessage());
        }

        /// <summary>Confirma que se terminó de reproducir una frase.</summary>
        public void SendPlaybackDone(int utteranceId)
        {
            SendJson(Protocol.PlaybackDoneMessage(utteranceId));
        }

        /// <summary>Envía un turno escrito, equivalente a hablar por el micrófono.</summary>
        public void SendTextInput(string text)
        {
            if (string.IsNullOrEmpty(text) || text.Trim().Length == 0)
            {
                return;
            }

            SendJson(Protocol.TextInputMessage(text));
        }

        /// <summary>Envía una captura de la cámara de Unity codificada en JPEG.</summary>
        public void SendCameraFrame(byte[] jpeg)
        {
            if (jpeg == null || jpeg.Length == 0)
            {
                return;
            }

            SendJson(Protocol.CameraFrameMessage(jpeg));
        }

        /// <summary>Manda el catálogo de animaciones que el panel puede lanzar una a una.</summary>
        public void SendAnimations(IList<KeyValuePair<string, string>> clips)
        {
            SendJson(Protocol.AnimationsMessage(clips));
        }

        private void SendJson(string json)
        {
            if (string.IsNullOrEmpty(json))
            {
                return;
            }

            ClientWebSocket socket = _socket;
            CancellationTokenSource cancellation = _cancellation;
            if (socket == null || cancellation == null || socket.State != WebSocketState.Open)
            {
                if (verboseLog)
                {
                    Debug.Log("[Sonia] Mensaje descartado, no hay conexión: " + json, this);
                }

                return;
            }

            CancellationToken token = CancellationToken.None;
            try
            {
                token = cancellation.Token;
            }
            catch (ObjectDisposedException)
            {
                return;
            }

            // Fuego y olvido: SendSafeAsync captura sus propias excepciones.
            Task ignored = SendSafeAsync(socket, json, token);
            GC.KeepAlive(ignored);
        }

        private async Task SendSafeAsync(ClientWebSocket socket, string json, CancellationToken token)
        {
            try
            {
                byte[] bytes = Encoding.UTF8.GetBytes(json);
                await _sendLock.WaitAsync(token).ConfigureAwait(false);
                try
                {
                    if (socket.State == WebSocketState.Open)
                    {
                        await socket
                            .SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, token)
                            .ConfigureAwait(false);
                    }
                }
                finally
                {
                    _sendLock.Release();
                }
            }
            catch (OperationCanceledException)
            {
                // Salida normal al cerrar.
            }
            catch (Exception ex)
            {
                _inbox.Enqueue(new LogSignal("No se pudo enviar el mensaje: " + ex.Message, true));
            }
        }

        // ------------------------------------------------------------------
        // Bucle de conexión (hilo de fondo)
        // ------------------------------------------------------------------

        private async Task ConnectionLoopAsync(
            Uri uri,
            string version,
            float initialDelay,
            float maxDelay,
            CancellationToken token)
        {
            double delay = initialDelay;

            while (!token.IsCancellationRequested)
            {
                bool announcedConnection = false;
                ClientWebSocket socket = null;

                try
                {
                    socket = new ClientWebSocket();
                    _socket = socket;
                    await socket.ConnectAsync(uri, token).ConfigureAwait(false);

                    delay = initialDelay;
                    announcedConnection = true;
                    _inbox.Enqueue(ConnectedSignal);

                    await SendSafeAsync(socket, Protocol.ClientHelloMessage(Protocol.ClientName, version), token)
                        .ConfigureAwait(false);
                    await ReceiveLoopAsync(socket, token).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    // Cierre pedido: se sale del bucle abajo.
                }
                catch (Exception ex)
                {
                    _inbox.Enqueue(new LogSignal("Conexión fallida: " + ex.Message, false));
                }
                finally
                {
                    if (ReferenceEquals(_socket, socket))
                    {
                        _socket = null;
                    }

                    if (socket != null)
                    {
                        try
                        {
                            socket.Abort();
                        }
                        catch (Exception)
                        {
                            // Nada que hacer si ya estaba roto.
                        }

                        try
                        {
                            socket.Dispose();
                        }
                        catch (Exception)
                        {
                            // Ídem.
                        }
                    }

                    if (announcedConnection)
                    {
                        _inbox.Enqueue(DisconnectedSignal);
                    }
                }

                if (token.IsCancellationRequested)
                {
                    break;
                }

                try
                {
                    await Task.Delay(TimeSpan.FromSeconds(delay), token).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    break;
                }

                delay = Math.Min(delay * 2.0, maxDelay);
            }
        }

        private async Task ReceiveLoopAsync(ClientWebSocket socket, CancellationToken token)
        {
            byte[] buffer = new byte[16384];
            using (MemoryStream assembled = new MemoryStream())
            {
                while (!token.IsCancellationRequested && socket.State == WebSocketState.Open)
                {
                    assembled.SetLength(0);
                    WebSocketMessageType messageType = WebSocketMessageType.Text;
                    bool firstFragment = true;
                    WebSocketReceiveResult result;

                    do
                    {
                        result = await socket
                            .ReceiveAsync(new ArraySegment<byte>(buffer), token)
                            .ConfigureAwait(false);

                        if (result.MessageType == WebSocketMessageType.Close)
                        {
                            try
                            {
                                await socket
                                    .CloseOutputAsync(WebSocketCloseStatus.NormalClosure, string.Empty, token)
                                    .ConfigureAwait(false);
                            }
                            catch (Exception)
                            {
                                // El servidor ya se fue; no importa.
                            }

                            return;
                        }

                        if (firstFragment)
                        {
                            messageType = result.MessageType;
                            firstFragment = false;
                        }

                        if (result.Count > 0)
                        {
                            assembled.Write(buffer, 0, result.Count);
                        }
                    }
                    while (!result.EndOfMessage);

                    if (assembled.Length == 0)
                    {
                        continue;
                    }

                    if (messageType == WebSocketMessageType.Binary)
                    {
                        byte[] payload = assembled.ToArray();
                        AudioFrame frame;
                        if (Protocol.TryDecodeAudioFrame(payload, payload.Length, out frame))
                        {
                            _inbox.Enqueue(frame);
                        }
                    }
                    else
                    {
                        string json = Encoding.UTF8.GetString(assembled.ToArray());
                        object parsed = ParseTextMessage(json);
                        if (parsed != null)
                        {
                            _inbox.Enqueue(parsed);
                        }
                    }
                }
            }
        }

        /// <summary>
        /// Convierte el JSON recibido al objeto de mensaje correspondiente. Los
        /// tipos desconocidos devuelven null y se ignoran, como manda el protocolo.
        /// </summary>
        private static object ParseTextMessage(string json)
        {
            string type;
            JObject payload;
            if (!Protocol.TryParse(json, out type, out payload))
            {
                return null;
            }

            switch (type)
            {
                case MessageTypes.Hello:
                    return Protocol.Deserialize<HelloMessage>(payload);
                case MessageTypes.State:
                    return Protocol.Deserialize<StateMessage>(payload);
                case MessageTypes.Transcript:
                    return Protocol.Deserialize<TranscriptMessage>(payload);
                case MessageTypes.SpeechStart:
                    return Protocol.Deserialize<SpeechStartMessage>(payload);
                case MessageTypes.Visemes:
                    return Protocol.Deserialize<VisemesMessage>(payload);
                case MessageTypes.Envelope:
                    return Protocol.Deserialize<EnvelopeMessage>(payload);
                case MessageTypes.SpeechEnd:
                    return Protocol.Deserialize<SpeechEndMessage>(payload);
                case MessageTypes.StopSpeaking:
                    return Protocol.Deserialize<StopSpeakingMessage>(payload);
                case MessageTypes.ShowImage:
                    return Protocol.Deserialize<ShowImageMessage>(payload);
                case MessageTypes.HideImage:
                    return Protocol.Deserialize<HideImageMessage>(payload);
                case MessageTypes.Attention:
                    return Protocol.Deserialize<AttentionMessage>(payload);
                case MessageTypes.PlayAnimation:
                    return Protocol.Deserialize<PlayAnimationMessage>(payload);
                case MessageTypes.Presence:
                    return Protocol.Deserialize<PresenceMessage>(payload);
                case MessageTypes.SetVolume:
                    return Protocol.Deserialize<SetVolumeMessage>(payload);
                case MessageTypes.Error:
                    return Protocol.Deserialize<ErrorMessage>(payload);
                case MessageTypes.RequestFrame:
                    return Protocol.Deserialize<RequestFrameMessage>(payload);
                default:
                    return null;
            }
        }

        // ------------------------------------------------------------------
        // Despacho en el hilo principal
        // ------------------------------------------------------------------

        private void Dispatch(object message)
        {
            if (ReferenceEquals(message, ConnectedSignal))
            {
                _isConnected = true;
                if (verboseLog)
                {
                    Debug.Log("[Sonia] Conectado a " + serverUrl, this);
                }

                Raise(OnConnected);
                return;
            }

            if (ReferenceEquals(message, DisconnectedSignal))
            {
                _isConnected = false;
                if (verboseLog)
                {
                    Debug.Log("[Sonia] Desconectado de " + serverUrl, this);
                }

                Raise(OnDisconnected);
                return;
            }

            LogSignal log = message as LogSignal;
            if (log != null)
            {
                if (log.IsWarning)
                {
                    Debug.LogWarning("[Sonia] " + log.Message, this);
                }
                else if (verboseLog)
                {
                    Debug.Log("[Sonia] " + log.Message, this);
                }

                return;
            }

            if (message is AudioFrame)
            {
                Raise(OnAudioFrame, (AudioFrame)message);
                return;
            }

            if (verboseLog)
            {
                Debug.Log("[Sonia] Mensaje recibido: " + message.GetType().Name, this);
            }

            HelloMessage hello = message as HelloMessage;
            if (hello != null)
            {
                Raise(OnHello, hello);
                return;
            }

            StateMessage state = message as StateMessage;
            if (state != null)
            {
                Raise(OnState, state);
                return;
            }

            TranscriptMessage transcript = message as TranscriptMessage;
            if (transcript != null)
            {
                Raise(OnTranscript, transcript);
                return;
            }

            SpeechStartMessage speechStart = message as SpeechStartMessage;
            if (speechStart != null)
            {
                Raise(OnSpeechStart, speechStart);
                return;
            }

            VisemesMessage visemes = message as VisemesMessage;
            if (visemes != null)
            {
                Raise(OnVisemes, visemes);
                return;
            }

            EnvelopeMessage envelope = message as EnvelopeMessage;
            if (envelope != null)
            {
                Raise(OnEnvelope, envelope);
                return;
            }

            SpeechEndMessage speechEnd = message as SpeechEndMessage;
            if (speechEnd != null)
            {
                Raise(OnSpeechEnd, speechEnd);
                return;
            }

            StopSpeakingMessage stopSpeaking = message as StopSpeakingMessage;
            if (stopSpeaking != null)
            {
                Raise(OnStopSpeaking, stopSpeaking);
                return;
            }

            ShowImageMessage showImage = message as ShowImageMessage;
            if (showImage != null)
            {
                Raise(OnShowImage, showImage);
                return;
            }

            HideImageMessage hideImage = message as HideImageMessage;
            if (hideImage != null)
            {
                Raise(OnHideImage, hideImage);
                return;
            }

            AttentionMessage attention = message as AttentionMessage;
            if (attention != null)
            {
                Raise(OnAttention, attention);
                return;
            }

            PlayAnimationMessage playAnimation = message as PlayAnimationMessage;
            if (playAnimation != null)
            {
                Raise(OnPlayAnimation, playAnimation);
                return;
            }

            PresenceMessage presence = message as PresenceMessage;
            if (presence != null)
            {
                Raise(OnPresence, presence);
                return;
            }

            SetVolumeMessage setVolume = message as SetVolumeMessage;
            if (setVolume != null)
            {
                Raise(OnSetVolume, setVolume);
                return;
            }

            ErrorMessage error = message as ErrorMessage;
            if (error != null)
            {
                Debug.LogWarning("[Sonia] Error del orquestador: " + error.Message, this);
                Raise(OnError, error);
                return;
            }

            RequestFrameMessage requestFrame = message as RequestFrameMessage;
            if (requestFrame != null)
            {
                Raise(OnRequestFrame, requestFrame);
            }
        }

        private void Raise(Action handler)
        {
            if (handler == null)
            {
                return;
            }

            try
            {
                handler();
            }
            catch (Exception ex)
            {
                Debug.LogException(ex, this);
            }
        }

        private void Raise<T>(Action<T> handler, T argument)
        {
            if (handler == null)
            {
                return;
            }

            try
            {
                handler(argument);
            }
            catch (Exception ex)
            {
                Debug.LogException(ex, this);
            }
        }

        /// <summary>Aviso generado en el hilo de red y mostrado en el hilo principal.</summary>
        private sealed class LogSignal
        {
            public readonly string Message;
            public readonly bool IsWarning;

            public LogSignal(string message, bool isWarning)
            {
                Message = message;
                IsWarning = isWarning;
            }
        }
    }
}
