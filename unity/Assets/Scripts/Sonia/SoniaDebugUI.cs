// Debug HUD: connection state, subtitles, text input and interrupt button.
// Everything is optional and null-safe: if nothing is assigned, the component
// does nothing.
//
// The project uses only the new Input System (activeInputHandler = 1), so the
// keyboard is read with UnityEngine.InputSystem.Keyboard, never UnityEngine.Input.

using TMPro;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>
    /// Minimal UI to test the assistant without a microphone and see what is
    /// happening. F1 shows and hides it; the Interrupt button cuts the assistant
    /// off (Esc opens the options menu, SoniaOptionsMenu).
    /// </summary>
    [DisallowMultipleComponent]
    public class SoniaDebugUI : MonoBehaviour
    {
        /// <summary>
        /// Label that accepts both TextMeshPro and the classic uGUI Text.
        /// </summary>
        [System.Serializable]
        public class UiLabel
        {
            [Tooltip("TextMeshPro label. Optional.")]
            public TMP_Text tmp;

            [Tooltip("Classic uGUI Text label. Optional.")]
            public Text legacy;

            [Tooltip("Bubble that turns on with text and off without it. Optional.")]
            public GameObject container;

            /// <summary>Writes the same text to whichever labels are assigned.</summary>
            public void Set(string value)
            {
                if (tmp != null)
                {
                    tmp.text = value;
                }

                if (legacy != null)
                {
                    legacy.text = value;
                }

                if (container != null)
                {
                    container.SetActive(!string.IsNullOrEmpty(value));
                }
            }
        }

        [Header("References")]
        [SerializeField]
        [Tooltip("Client the events are read from and the text is sent through.")]
        private SoniaClient client;

        [SerializeField]
        [Tooltip("Root object of the HUD, the one toggled with F1.")]
        private GameObject hudRoot;

        [Header("Labels")]
        [SerializeField]
        [Tooltip("State of the connection with the orchestrator.")]
        private UiLabel connectionLabel = new UiLabel();

        [SerializeField]
        [Tooltip("Assistant state: idle, listening, thinking or speaking.")]
        private UiLabel stateLabel = new UiLabel();

        [SerializeField]
        [Tooltip("Last transcribed user text.")]
        private UiLabel userLabel = new UiLabel();

        [SerializeField]
        [Tooltip("Last text the assistant said.")]
        private UiLabel assistantLabel = new UiLabel();

        // Subtitle announced by speech_start, waiting for its first audio.
        private int _pendingSubtitleId = -1;
        private string _pendingSubtitle;

        // The control panel can turn subtitles off (set_subtitles): nothing is drawn.
        private bool _subtitlesOn = true;

        [Header("Input")]
        [SerializeField]
        [Tooltip("Text field to send a typed turn with Enter.")]
        private TMP_InputField inputField;

        [SerializeField]
        [Tooltip("Button that sends the interrupt message.")]
        private Button interruptButton;

        [Header("Behavior")]
        [SerializeField]
        [Tooltip("Show the HUD at startup.")]
        private bool visibleOnStart = true;

        private bool _visible = true;
        private bool _warnedAboutHudRoot;

        private void Awake()
        {
            if (client == null)
            {
                client = GetComponentInParent<SoniaClient>();
            }
        }

        private void OnEnable()
        {
            if (client != null)
            {
                client.OnConnected += HandleConnected;
                client.OnDisconnected += HandleDisconnected;
                client.OnState += HandleState;
                client.OnTranscript += HandleTranscript;
                client.OnSpeechStart += HandleSpeechStart;
                client.OnAudioFrame += HandleAudioFrame;
                client.OnSetSubtitles += HandleSetSubtitles;
            }

            if (inputField != null)
            {
                inputField.onSubmit.AddListener(HandleSubmit);
            }

            if (interruptButton != null)
            {
                interruptButton.onClick.AddListener(HandleInterruptClicked);
            }
        }

        private void OnDisable()
        {
            if (client != null)
            {
                client.OnConnected -= HandleConnected;
                client.OnDisconnected -= HandleDisconnected;
                client.OnState -= HandleState;
                client.OnTranscript -= HandleTranscript;
                client.OnSpeechStart -= HandleSpeechStart;
                client.OnAudioFrame -= HandleAudioFrame;
                client.OnSetSubtitles -= HandleSetSubtitles;
            }

            if (inputField != null)
            {
                inputField.onSubmit.RemoveListener(HandleSubmit);
            }

            if (interruptButton != null)
            {
                interruptButton.onClick.RemoveListener(HandleInterruptClicked);
            }
        }

        private void Start()
        {
            connectionLabel.Set(client != null && client.IsConnected ? "Connected" : "Disconnected");
            stateLabel.Set("idle");
            if (!SoniaDevMode.Enabled)
            {
                // Normal operation: only the subtitles remain on screen.
                // Connection, state and controls live in the control panel.
                HideLabel(connectionLabel);
                HideLabel(stateLabel);
                SoniaDevMode.HideUnlessEnabled(inputField);
                SoniaDevMode.HideUnlessEnabled(interruptButton);
                SetVisible(true);
                return;
            }

            SetVisible(visibleOnStart);
        }

        private static void HideLabel(UiLabel label)
        {
            SoniaDevMode.HideUnlessEnabled(label.tmp);
            SoniaDevMode.HideUnlessEnabled(label.legacy);
            if (label.container != null)
            {
                label.container.SetActive(false);
            }

            // Without references, Set() no longer turns anything back on.
            label.tmp = null;
            label.legacy = null;
            label.container = null;
        }

        private void Update()
        {
            if (!SoniaDevMode.Enabled)
            {
                return;
            }

            Keyboard keyboard = Keyboard.current;
            if (keyboard == null)
            {
                return;
            }

            if (keyboard.f1Key.wasPressedThisFrame)
            {
                SetVisible(!_visible);
            }
        }

        /// <summary>Shows or hides the HUD.</summary>
        public void SetVisible(bool value)
        {
            _visible = value;

            // hudRoot has to be another object: if it were this one, deactivating
            // it would stop Update() and F1 could never turn it back on.
            if (hudRoot == null || hudRoot == gameObject)
            {
                if (!_warnedAboutHudRoot)
                {
                    _warnedAboutHudRoot = true;
                    Debug.LogWarning(
                        "[Sonnia] SoniaDebugUI has no HUD root object other than itself; F1 will do nothing.",
                        this);
                }

                return;
            }

            hudRoot.SetActive(value);
        }

        // ------------------------------------------------------------------
        // Client events
        // ------------------------------------------------------------------

        private void HandleConnected()
        {
            connectionLabel.Set("Connected to " + (client != null ? client.ServerUrl : "?"));
        }

        private void HandleDisconnected()
        {
            connectionLabel.Set("Disconnected, retrying…");
        }

        private void HandleState(StateMessage message)
        {
            if (message != null)
            {
                stateLabel.Set(message.State);
            }
        }

        /// <summary>The control panel turns subtitles on or off; when off, any current ones are cleared.</summary>
        private void HandleSetSubtitles(SetSubtitlesMessage message)
        {
            if (message == null)
            {
                return;
            }

            _subtitlesOn = message.Enabled;
            if (!_subtitlesOn)
            {
                _pendingSubtitle = null;
                userLabel.Set(string.Empty);
                assistantLabel.Set(string.Empty);
            }
        }

        private void HandleTranscript(TranscriptMessage message)
        {
            if (message == null || !_subtitlesOn)
            {
                return;
            }

            if (message.Role == "assistant")
            {
                // The assistant's full text is shown when it starts sounding
                // (see HandleAudioFrame), not when the orchestrator decides: the
                // subtitle goes with the voice, not ahead of it. With the realtime
                // model the text arrives in pieces (final = false) along with its
                // audio, so those pieces are drawn as they arrive.
                if (!message.Final && !string.IsNullOrEmpty(message.Text))
                {
                    assistantLabel.Set(message.Text);
                }

                return;
            }

            userLabel.Set(message.Text);
        }

        private void HandleSpeechStart(SpeechStartMessage message)
        {
            if (_subtitlesOn && message != null && !string.IsNullOrEmpty(message.Text))
            {
                _pendingSubtitleId = message.UtteranceId;
                _pendingSubtitle = message.Text;
            }
        }

        private void HandleAudioFrame(AudioFrame frame)
        {
            if (_pendingSubtitle != null && frame.UtteranceId >= _pendingSubtitleId)
            {
                assistantLabel.Set(_pendingSubtitle);
                _pendingSubtitle = null;
            }
        }

        // ------------------------------------------------------------------
        // Interaction
        // ------------------------------------------------------------------

        private void HandleSubmit(string text)
        {
            if (client == null || string.IsNullOrEmpty(text) || text.Trim().Length == 0)
            {
                return;
            }

            client.SendTextInput(text);
            if (_subtitlesOn)
            {
                userLabel.Set(text);
            }

            if (inputField != null)
            {
                inputField.text = string.Empty;
                inputField.ActivateInputField();
            }
        }

        private void HandleInterruptClicked()
        {
            if (client != null)
            {
                client.SendInterrupt();
            }
        }
    }
}
