// WebSocket client toward the Sonnia orchestrator.
//
// Threading rules, important:
//  - All network work (connecting, receiving, parsing JSON, decoding PCM)
//    happens in a background Task. That thread NEVER touches the Unity API.
//  - Parsed messages are queued in a ConcurrentQueue and dispatched as C#
//    events in Update(), that is, on the main thread.
//
// The orchestrator URL can be changed at startup with -sonia-ws
// ws://127.0.0.1:<port> (handy for testing against a fake orchestrator).

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
    /// Keeps the connection to the orchestrator, reconnects on its own and exposes
    /// each protocol message as a C# event raised on the main thread.
    /// </summary>
    [DisallowMultipleComponent]
    public class SoniaClient : MonoBehaviour
    {
        [Header("Connection")]
        [SerializeField]
        [Tooltip("Orchestrator WebSocket URL. Defaults to ws://127.0.0.1:8765")]
        private string serverUrl = "ws://127.0.0.1:8765";

        [SerializeField]
        [Tooltip("Connect automatically when the scene starts.")]
        private bool autoConnect = true;

        [SerializeField]
        [Tooltip("Initial wait before retrying the connection, in seconds.")]
        private float reconnectDelaySeconds = 1f;

        [SerializeField]
        [Tooltip("Maximum wait between retries, in seconds. The delay doubles until it reaches this.")]
        private float maxReconnectDelaySeconds = 10f;

        [SerializeField]
        [Tooltip("Version Unity announces in client_hello.")]
        private string clientVersion = "0.1.0";

        [Header("Debug")]
        [SerializeField]
        [Tooltip("Logs every received message to the console (except audio frames).")]
        private bool verboseLog;

        // ------------------------------------------------------------------
        // Events (always on the main thread)
        // ------------------------------------------------------------------

        /// <summary>Connection to the orchestrator established.</summary>
        public event Action OnConnected;

        /// <summary>Connection lost. The client will retry on its own.</summary>
        public event Action OnDisconnected;

        /// <summary>Audio format announced by the orchestrator.</summary>
        public event Action<HelloMessage> OnHello;

        /// <summary>Assistant state change.</summary>
        public event Action<StateMessage> OnState;

        /// <summary>Text from the user or from Sonnia.</summary>
        public event Action<TranscriptMessage> OnTranscript;

        /// <summary>A synthesized utterance begins.</summary>
        public event Action<SpeechStartMessage> OnSpeechStart;

        /// <summary>An already decoded PCM audio chunk.</summary>
        public event Action<AudioFrame> OnAudioFrame;

        /// <summary>No more audio for that utterance.</summary>
        public event Action<SpeechEndMessage> OnSpeechEnd;

        /// <summary>Interruption: flush the buffer and close the mouth.</summary>
        public event Action<StopSpeakingMessage> OnStopSpeaking;

        /// <summary>Show an image in the scene's image panel.</summary>
        public event Action<ShowImageMessage> OnShowImage;

        /// <summary>Hide the image panel.</summary>
        public event Action<HideImageMessage> OnHideImage;

        /// <summary>Attention gesture requested by the orchestrator (dance, fourth wall, soft, greeting).</summary>
        public event Action<AttentionMessage> OnAttention;

        /// <summary>The panel asks for a specific animation from the catalog.</summary>
        public event Action<PlayAnimationMessage> OnPlayAnimation;

        /// <summary>Subtitles on screen or not.</summary>
        public event Action<SetSubtitlesMessage> OnSetSubtitles;

        /// <summary>Clips Sonnia must not use on her own.</summary>
        public event Action<SetDisabledAnimationsMessage> OnSetDisabledAnimations;

        /// <summary>Panel debug mode: nothing automatic on the body.</summary>
        public event Action<SetDebugMessage> OnSetDebug;

        /// <summary>Panel "Developer" settings: mouth and camera.</summary>
        public event Action<SetTuningMessage> OnSetTuning;

        /// <summary>Sonnia's look: Genies avatar definition (null: the app's own).</summary>
        public event Action<SetAvatarMessage> OnSetAvatar;

        /// <summary>A trivia game starts (theme and scoreboard).</summary>
        public event Action<TriviaStartMessage> OnTriviaStart;

        /// <summary>A trivia question with its three options.</summary>
        public event Action<TriviaQuestionMessage> OnTriviaQuestion;

        /// <summary>Result of a trivia question.</summary>
        public event Action<TriviaAnswerMessage> OnTriviaAnswer;

        /// <summary>End of the trivia (won, lost or cancelled).</summary>
        public event Action<TriviaEndMessage> OnTriviaEnd;

        /// <summary>Sonnia is searching the web or a task is taking long (<see cref="ActivityMessage"/>).</summary>
        public event Action<ActivityMessage> OnActivity;

        /// <summary>On-screen busy indicator: the <see cref="BusyIndicator"/> pill (<see cref="BusyMessage"/>).</summary>
        public event Action<BusyMessage> OnBusy;

        /// <summary>Sonnia leaves the screen (away mode) or comes back.</summary>
        public event Action<PresenceMessage> OnPresence;

        /// <summary>Operating mode and whether Sonnia can converse (the invitation to talk).</summary>
        public event Action<StageModeMessage> OnStageMode;

        /// <summary>Voice volume.</summary>
        public event Action<SetVolumeMessage> OnSetVolume;

        /// <summary>Microphones on the machine and the current choice (reply to <see cref="SendListDevices"/>).</summary>
        public event Action<DevicesMessage> OnDevices;

        /// <summary>Error reported by the orchestrator.</summary>
        public event Action<ErrorMessage> OnError;

        /// <summary>The orchestrator asks for a capture from Unity's camera.</summary>
        public event Action<RequestFrameMessage> OnRequestFrame;

        // ------------------------------------------------------------------
        // Internal state
        // ------------------------------------------------------------------

        /// <summary>Command-line argument that changes the orchestrator URL.</summary>
        public const string ServerUrlArgument = "-sonia-ws";

        private static readonly object ConnectedSignal = new object();
        private static readonly object DisconnectedSignal = new object();

        private readonly ConcurrentQueue<object> _inbox = new ConcurrentQueue<object>();
        private readonly SemaphoreSlim _sendLock = new SemaphoreSlim(1, 1);

        // [NonSerialized]: after recompiling in Play, Unity keeps the private
        // serializable fields but kills the background thread; if _isConnected
        // survived as "true", the client would look connected without receiving
        // anything. With the fields reset, Update reconnects.
        private volatile ClientWebSocket _socket;
        private CancellationTokenSource _cancellation;
        private Task _connectionTask;

        [NonSerialized]
        private bool _shuttingDown;

        [NonSerialized]
        private bool _isConnected;

        /// <summary>True between <see cref="OnConnected"/> and <see cref="OnDisconnected"/>.</summary>
        public bool IsConnected
        {
            get { return _isConnected; }
        }

        /// <summary>URL this client connects to (the -sonia-ws one if started with it).</summary>
        public string ServerUrl
        {
            get { return EffectiveServerUrl(); }
        }

        /// <summary>The -sonia-ws ws://... URL from the command line, or null if absent.</summary>
        public static string CommandLineServerUrl()
        {
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == ServerUrlArgument && !string.IsNullOrEmpty(args[i + 1]))
                {
                    return args[i + 1].Trim();
                }
            }

            return null;
        }

        private string EffectiveServerUrl()
        {
            string fromCommandLine = CommandLineServerUrl();
            return string.IsNullOrEmpty(fromCommandLine) ? serverUrl : fromCommandLine;
        }

        // ------------------------------------------------------------------
        // Lifecycle
        // ------------------------------------------------------------------

        private void Start()
        {
            if (autoConnect)
            {
                Connect();
            }
        }

        /// <summary>Starts the connection task if it is not already running.</summary>
        public void Connect()
        {
            if (_connectionTask != null || _shuttingDown)
            {
                return;
            }

            string url = EffectiveServerUrl();
            Uri uri;
            if (!Uri.TryCreate(url, UriKind.Absolute, out uri))
            {
                Debug.LogError("[Sonnia] Invalid orchestrator URL: " + url, this);
                return;
            }

            if (url != serverUrl)
            {
                Debug.Log("[Sonnia] Orchestrator from " + ServerUrlArgument + ": " + url, this);
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
            // With no connection task (startup, or domain reload in Play) it reconnects.
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
                    // Safeguard so a flood of messages does not freeze a frame.
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
                    // The background task had already released it.
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
                    // Closing abruptly is acceptable on exit.
                }
            }
        }

        /// <summary>
        /// Dispatches a JSON message as if it had arrived from the orchestrator,
        /// immediately. For test tools without a network; returns false if the type is unknown.
        /// </summary>
        public bool InjectMessage(string json)
        {
            object parsed = ParseTextMessage(json);
            if (parsed == null)
            {
                return false;
            }

            Dispatch(parsed);
            return true;
        }

        /// <summary>
        /// Dispatches a chunk of voice as if it arrived from the orchestrator (binary
        /// frame), immediately. For test tools without a network.
        /// </summary>
        public void InjectAudioFrame(AudioFrame frame)
        {
            Dispatch(frame);
        }

        // ------------------------------------------------------------------
        // Sending (call from the main thread)
        // ------------------------------------------------------------------

        /// <summary>Tells the orchestrator the user has interrupted.</summary>
        public void SendInterrupt()
        {
            SendJson(Protocol.InterruptMessage());
        }

        /// <summary>Confirms an utterance finished playing.</summary>
        public void SendPlaybackDone(int utteranceId)
        {
            SendJson(Protocol.PlaybackDoneMessage(utteranceId));
        }

        /// <summary>Sends a typed turn, equivalent to speaking into the microphone.</summary>
        public void SendTextInput(string text)
        {
            if (string.IsNullOrEmpty(text) || text.Trim().Length == 0)
            {
                return;
            }

            SendJson(Protocol.TextInputMessage(text));
        }

        /// <summary>Sends a capture from Unity's camera, JPEG-encoded.</summary>
        public void SendCameraFrame(byte[] jpeg)
        {
            if (jpeg == null || jpeg.Length == 0)
            {
                return;
            }

            SendJson(Protocol.CameraFrameMessage(jpeg));
        }

        /// <summary>Sends the catalog of animations the panel can trigger one by one.</summary>
        public void SendAnimations(IList<KeyValuePair<string, string>> clips)
        {
            SendJson(Protocol.AnimationsMessage(clips));
        }

        /// <summary>Asks the orchestrator for the microphones and the current choice (arrives via <see cref="OnDevices"/>).</summary>
        public void SendListDevices()
        {
            SendJson(Protocol.ListDevicesMessage());
        }

        /// <summary>Chooses a microphone on the orchestrator (empty: the system default).</summary>
        public void SendSetMicrophone(string name)
        {
            SendJson(Protocol.SetMicrophoneMessage(name));
        }

        /// <summary>Chooses a camera on the orchestrator (index, as in <c>WebCamTexture.devices</c>).</summary>
        public void SendSetCamera(int index)
        {
            SendJson(Protocol.SetCameraMessage(index));
        }

        /// <summary>Reports which catalog clip is playing now (null: none).</summary>
        public void SendAnimationPlaying(string clip)
        {
            SendJson(Protocol.AnimationPlayingMessage(clip));
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
                    Debug.Log("[Sonnia] Message dropped, not connected: " + json, this);
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

            // Fire and forget: SendSafeAsync catches its own exceptions.
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
                // Normal exit on close.
            }
            catch (Exception ex)
            {
                _inbox.Enqueue(new LogSignal("Could not send the message: " + ex.Message, true));
            }
        }

        // ------------------------------------------------------------------
        // Connection loop (background thread)
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

                    string hello = Protocol.ClientHelloMessage(Protocol.ClientName, version);
                    await SendSafeAsync(socket, hello, token).ConfigureAwait(false);
                    await ReceiveLoopAsync(socket, token).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    // Close requested: exits the loop below.
                }
                catch (Exception ex)
                {
                    _inbox.Enqueue(new LogSignal("Connection failed: " + ex.Message, false));
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
                            // Nothing to do if it was already broken.
                        }

                        try
                        {
                            socket.Dispose();
                        }
                        catch (Exception)
                        {
                            // Same.
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
                                // The server is already gone; no matter.
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
        /// Converts the received JSON to the matching message object. Unknown
        /// types return null and are ignored, as the protocol requires.
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
                case MessageTypes.SetSubtitles:
                    return Protocol.Deserialize<SetSubtitlesMessage>(payload);
                case MessageTypes.SetDisabledAnimations:
                    return Protocol.Deserialize<SetDisabledAnimationsMessage>(payload);
                case MessageTypes.SetDebug:
                    return Protocol.Deserialize<SetDebugMessage>(payload);
                case MessageTypes.SetTuning:
                    return Protocol.Deserialize<SetTuningMessage>(payload);
                case MessageTypes.SetAvatar:
                    return Protocol.Deserialize<SetAvatarMessage>(payload);
                case MessageTypes.TriviaStart:
                    return Protocol.Deserialize<TriviaStartMessage>(payload);
                case MessageTypes.TriviaQuestion:
                    return Protocol.Deserialize<TriviaQuestionMessage>(payload);
                case MessageTypes.TriviaAnswer:
                    return Protocol.Deserialize<TriviaAnswerMessage>(payload);
                case MessageTypes.TriviaEnd:
                    return Protocol.Deserialize<TriviaEndMessage>(payload);
                case MessageTypes.Activity:
                    return Protocol.Deserialize<ActivityMessage>(payload);
                case MessageTypes.Busy:
                    return Protocol.Deserialize<BusyMessage>(payload);
                case MessageTypes.Presence:
                    return Protocol.Deserialize<PresenceMessage>(payload);
                case MessageTypes.StageMode:
                    return Protocol.Deserialize<StageModeMessage>(payload);
                case MessageTypes.SetVolume:
                    return Protocol.Deserialize<SetVolumeMessage>(payload);
                case MessageTypes.Devices:
                    return Protocol.Deserialize<DevicesMessage>(payload);
                case MessageTypes.Error:
                    return Protocol.Deserialize<ErrorMessage>(payload);
                case MessageTypes.RequestFrame:
                    return Protocol.Deserialize<RequestFrameMessage>(payload);
                default:
                    return null;
            }
        }

        // ------------------------------------------------------------------
        // Dispatch on the main thread
        // ------------------------------------------------------------------

        private void Dispatch(object message)
        {
            if (ReferenceEquals(message, ConnectedSignal))
            {
                _isConnected = true;
                if (verboseLog)
                {
                    Debug.Log("[Sonnia] Connected to " + serverUrl, this);
                }

                Raise(OnConnected);
                return;
            }

            if (ReferenceEquals(message, DisconnectedSignal))
            {
                _isConnected = false;
                if (verboseLog)
                {
                    Debug.Log("[Sonnia] Disconnected from " + serverUrl, this);
                }

                Raise(OnDisconnected);
                return;
            }

            LogSignal log = message as LogSignal;
            if (log != null)
            {
                if (log.IsWarning)
                {
                    Debug.LogWarning("[Sonnia] " + log.Message, this);
                }
                else if (verboseLog)
                {
                    Debug.Log("[Sonnia] " + log.Message, this);
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
                Debug.Log("[Sonnia] Message received: " + message.GetType().Name, this);
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

            SetSubtitlesMessage setSubtitles = message as SetSubtitlesMessage;
            if (setSubtitles != null)
            {
                Raise(OnSetSubtitles, setSubtitles);
                return;
            }

            SetDisabledAnimationsMessage setDisabled = message as SetDisabledAnimationsMessage;
            if (setDisabled != null)
            {
                Raise(OnSetDisabledAnimations, setDisabled);
                return;
            }

            SetDebugMessage setDebug = message as SetDebugMessage;
            if (setDebug != null)
            {
                Raise(OnSetDebug, setDebug);
                return;
            }

            SetTuningMessage setTuning = message as SetTuningMessage;
            if (setTuning != null)
            {
                Raise(OnSetTuning, setTuning);
                return;
            }

            SetAvatarMessage setAvatar = message as SetAvatarMessage;
            if (setAvatar != null)
            {
                Raise(OnSetAvatar, setAvatar);
                return;
            }

            TriviaStartMessage triviaStart = message as TriviaStartMessage;
            if (triviaStart != null)
            {
                Raise(OnTriviaStart, triviaStart);
                return;
            }

            TriviaQuestionMessage triviaQuestion = message as TriviaQuestionMessage;
            if (triviaQuestion != null)
            {
                Raise(OnTriviaQuestion, triviaQuestion);
                return;
            }

            TriviaAnswerMessage triviaAnswer = message as TriviaAnswerMessage;
            if (triviaAnswer != null)
            {
                Raise(OnTriviaAnswer, triviaAnswer);
                return;
            }

            TriviaEndMessage triviaEnd = message as TriviaEndMessage;
            if (triviaEnd != null)
            {
                Raise(OnTriviaEnd, triviaEnd);
                return;
            }

            ActivityMessage activity = message as ActivityMessage;
            if (activity != null)
            {
                Raise(OnActivity, activity);
                return;
            }

            BusyMessage busy = message as BusyMessage;
            if (busy != null)
            {
                Raise(OnBusy, busy);
                return;
            }

            PresenceMessage presence = message as PresenceMessage;
            if (presence != null)
            {
                Raise(OnPresence, presence);
                return;
            }

            StageModeMessage stageMode = message as StageModeMessage;
            if (stageMode != null)
            {
                Raise(OnStageMode, stageMode);
                return;
            }

            SetVolumeMessage setVolume = message as SetVolumeMessage;
            if (setVolume != null)
            {
                Raise(OnSetVolume, setVolume);
                return;
            }

            DevicesMessage devices = message as DevicesMessage;
            if (devices != null)
            {
                Raise(OnDevices, devices);
                return;
            }

            ErrorMessage error = message as ErrorMessage;
            if (error != null)
            {
                Debug.LogWarning("[Sonnia] Orchestrator error: " + error.Message, this);
                Raise(OnError, error);
                return;
            }

            RequestFrameMessage requestFrame = message as RequestFrameMessage;
            if (requestFrame != null)
            {
                Raise(OnRequestFrame, requestFrame);
                return;
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

        /// <summary>Log entry generated on the network thread and shown on the main thread.</summary>
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
