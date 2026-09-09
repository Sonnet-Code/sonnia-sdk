// HUD de depuración: estado de la conexión, subtítulos, entrada de texto y
// botón de interrupción. Todo opcional y todo null-safe: si no se asigna nada,
// el componente no hace nada.
//
// El proyecto usa solo el Input System nuevo (activeInputHandler = 1), así que
// el teclado se lee con UnityEngine.InputSystem.Keyboard, nunca con UnityEngine.Input.

using TMPro;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>
    /// Interfaz mínima para probar a Sonia sin micrófono y ver qué está pasando.
    /// F1 la muestra y la esconde, Escape interrumpe.
    /// </summary>
    [DisallowMultipleComponent]
    public class SoniaDebugUI : MonoBehaviour
    {
        /// <summary>
        /// Etiqueta que acepta tanto TextMeshPro como el Text clásico de uGUI.
        /// </summary>
        [System.Serializable]
        public class UiLabel
        {
            [Tooltip("Etiqueta TextMeshPro. Opcional.")]
            public TMP_Text tmp;

            [Tooltip("Etiqueta Text clásica de uGUI. Opcional.")]
            public Text legacy;

            /// <summary>Escribe el mismo texto en las etiquetas que estén asignadas.</summary>
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
            }
        }

        [Header("Referencias")]
        [SerializeField]
        [Tooltip("Cliente del que se leen los eventos y por el que se envía el texto.")]
        private SoniaClient client;

        [SerializeField]
        [Tooltip("Objeto raíz del HUD, el que se activa y desactiva con F1.")]
        private GameObject hudRoot;

        [Header("Etiquetas")]
        [SerializeField]
        [Tooltip("Estado de la conexión con el orquestador.")]
        private UiLabel connectionLabel = new UiLabel();

        [SerializeField]
        [Tooltip("Estado del asistente: idle, listening, thinking o speaking.")]
        private UiLabel stateLabel = new UiLabel();

        [SerializeField]
        [Tooltip("Último texto transcrito del usuario.")]
        private UiLabel userLabel = new UiLabel();

        [SerializeField]
        [Tooltip("Último texto que dice Sonia.")]
        private UiLabel assistantLabel = new UiLabel();

        [Header("Entrada")]
        [SerializeField]
        [Tooltip("Campo de texto para enviar un turno escrito con Enter.")]
        private TMP_InputField inputField;

        [SerializeField]
        [Tooltip("Botón que envía el mensaje interrupt.")]
        private Button interruptButton;

        [Header("Comportamiento")]
        [SerializeField]
        [Tooltip("Mostrar el HUD al arrancar.")]
        private bool visibleOnStart = true;

        [SerializeField]
        [Tooltip("Escape envía interrupt.")]
        private bool escapeInterrupts = true;

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
            SetVisible(visibleOnStart);
            connectionLabel.Set(client != null && client.IsConnected ? "Conectado" : "Sin conexión");
            stateLabel.Set("idle");
        }

        private void Update()
        {
            Keyboard keyboard = Keyboard.current;
            if (keyboard == null)
            {
                return;
            }

            if (keyboard.f1Key.wasPressedThisFrame)
            {
                SetVisible(!_visible);
            }

            if (escapeInterrupts && keyboard.escapeKey.wasPressedThisFrame && client != null)
            {
                client.SendInterrupt();
            }
        }

        /// <summary>Muestra o esconde el HUD.</summary>
        public void SetVisible(bool value)
        {
            _visible = value;

            // hudRoot tiene que ser otro objeto: si fuera este, al desactivarlo
            // dejaría de correr Update() y F1 no volvería a encenderlo.
            if (hudRoot == null || hudRoot == gameObject)
            {
                if (!_warnedAboutHudRoot)
                {
                    _warnedAboutHudRoot = true;
                    Debug.LogWarning(
                        "[Sonia] SoniaDebugUI no tiene un objeto raíz de HUD distinto de este; F1 no hará nada.",
                        this);
                }

                return;
            }

            hudRoot.SetActive(value);
        }

        // ------------------------------------------------------------------
        // Eventos del cliente
        // ------------------------------------------------------------------

        private void HandleConnected()
        {
            connectionLabel.Set("Conectado a " + (client != null ? client.ServerUrl : "?"));
        }

        private void HandleDisconnected()
        {
            connectionLabel.Set("Sin conexión, reintentando…");
        }

        private void HandleState(StateMessage message)
        {
            if (message != null)
            {
                stateLabel.Set(message.State);
            }
        }

        private void HandleTranscript(TranscriptMessage message)
        {
            if (message == null)
            {
                return;
            }

            if (message.Role == "assistant")
            {
                assistantLabel.Set(message.Text);
            }
            else
            {
                userLabel.Set(message.Text);
            }
        }

        private void HandleSpeechStart(SpeechStartMessage message)
        {
            if (message != null && !string.IsNullOrEmpty(message.Text))
            {
                assistantLabel.Set(message.Text);
            }
        }

        // ------------------------------------------------------------------
        // Interacción
        // ------------------------------------------------------------------

        private void HandleSubmit(string text)
        {
            if (client == null || string.IsNullOrEmpty(text) || text.Trim().Length == 0)
            {
                return;
            }

            client.SendTextInput(text);
            userLabel.Set(text);

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
