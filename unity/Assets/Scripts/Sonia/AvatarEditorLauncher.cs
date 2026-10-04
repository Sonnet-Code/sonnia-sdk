// Lleva la pantalla de Sonia al editor de personaje de Genies y la trae de vuelta.
//
// El editor es el del sample «Creating an Avatar Editor» del Genies Avatar SDK,
// copiado a Assets/Sonia/AvatarEditor (Assets/Samples no está en git). Cuando el
// panel pide open_avatar_editor, su escena se carga encima de la de Sonia, que
// sigue conectada al orquestador pero deja de pintarse: se apagan las demás
// raíces de la escena (cámaras, luces, volumen, EventSystem, escenario) y, dentro
// de la raíz de Sonia, sus renderers y lienzos. El editor arranca con el
// personaje que Sonia lleva puesto (AvatarEditorSession.CurrentDefinition).
//
// Al pulsar Guardar en el editor, la definición sale hacia el orquestador
// (avatar_saved), que la guarda en la nube y la reparte a todas las Sonias con
// set_avatar; luego se vuelve a Sonia. Si al guardar no hay conexión, la
// definición se repite al reconectar hasta que llega su set_avatar. El botón de
// salir del editor o close_avatar_editor vuelven sin guardar.

using System;
using System.Collections;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.SceneManagement;

namespace Sonia
{
    /// <summary>Lo que comparten el editor de personaje (Genies) y Sonia.</summary>
    public static class AvatarEditorSession
    {
        /// <summary>
        /// Definición de Genies (JSON) del personaje que lleva Sonia ahora. La pone
        /// el cargador de avatares; el editor arranca con ella.
        /// </summary>
        public static string CurrentDefinition { get; set; }

        /// <summary>Cierto mientras la escena del editor está en pantalla.</summary>
        public static bool IsOpen { get; internal set; }

        internal static event Action<string> SaveRequested;
        internal static event Action CloseRequested;

        /// <summary>El editor guardó un personaje: su definición de Genies en JSON.</summary>
        public static void Save(string definition)
        {
            Action<string> handler = SaveRequested;
            if (handler != null)
            {
                handler(definition);
            }
        }

        /// <summary>Volver a Sonia sin guardar.</summary>
        public static void Close()
        {
            Action handler = CloseRequested;
            if (handler != null)
            {
                handler();
            }
        }
    }

    /// <summary>Abre y cierra la escena del editor de personaje sobre la de Sonia.</summary>
    [DisallowMultipleComponent]
    public class AvatarEditorLauncher : MonoBehaviour
    {
        /// <summary>Escena del editor (tiene que estar en Build Settings).</summary>
        public const string DefaultSceneName = "SoniaAvatarEditor";

        [SerializeField]
        [Tooltip("Nombre de la escena del editor de personaje en Build Settings.")]
        private string sceneName = DefaultSceneName;

        [SerializeField]
        [Tooltip("Conexión con el orquestador. Si está vacío se busca en este objeto.")]
        private SoniaClient client;

        [SerializeField]
        [Tooltip("Sin tocar ratón ni teclado durante estos segundos, el editor se cierra sin guardar y vuelve Sonia. 0: nunca.")]
        private float idleCloseSeconds = 300f;

        [NonSerialized]
        private readonly List<GameObject> _hiddenRoots = new List<GameObject>();

        [NonSerialized]
        private readonly List<Renderer> _hiddenRenderers = new List<Renderer>();

        [NonSerialized]
        private readonly List<Canvas> _hiddenCanvases = new List<Canvas>();

        [NonSerialized]
        private bool _busy;

        [NonSerialized]
        private Scene _editorScene;

        // Definición guardada que el orquestador aún no ha confirmado con set_avatar.
        [NonSerialized]
        private string _pendingDefinition;

        // Última vez que alguien tocó el ratón o el teclado con el editor abierto.
        [NonSerialized]
        private float _lastInputTime;

        private void Awake()
        {
            if (client == null)
            {
                client = GetComponent<SoniaClient>();
            }
        }

        private void OnEnable()
        {
            AvatarEditorSession.SaveRequested += HandleSave;
            AvatarEditorSession.CloseRequested += Close;
            if (client != null)
            {
                client.OnOpenAvatarEditor += HandleOpenMessage;
                client.OnCloseAvatarEditor += HandleCloseMessage;
                client.OnSetAvatar += HandleSetAvatar;
                client.OnConnected += HandleConnected;
            }
        }

        private void OnDisable()
        {
            AvatarEditorSession.SaveRequested -= HandleSave;
            AvatarEditorSession.CloseRequested -= Close;
            if (client != null)
            {
                client.OnOpenAvatarEditor -= HandleOpenMessage;
                client.OnCloseAvatarEditor -= HandleCloseMessage;
                client.OnSetAvatar -= HandleSetAvatar;
                client.OnConnected -= HandleConnected;
            }
        }

        /// <summary>Pasa la pantalla al editor de personaje.</summary>
        public void Open()
        {
            if (_busy || AvatarEditorSession.IsOpen)
            {
                return;
            }

            StartCoroutine(OpenRoutine());
        }

        /// <summary>Vuelve a Sonia (sin guardar si no se ha guardado).</summary>
        public void Close()
        {
            if (_busy || !AvatarEditorSession.IsOpen)
            {
                return;
            }

            StartCoroutine(CloseRoutine());
        }

        private IEnumerator OpenRoutine()
        {
            _busy = true;
            AsyncOperation loading = SceneManager.LoadSceneAsync(sceneName, LoadSceneMode.Additive);
            if (loading == null)
            {
                Debug.LogError("[Sonia] No se puede abrir el editor de personaje: falta la escena " + sceneName + " en Build Settings.", this);
                _busy = false;
                yield break;
            }

            // Sonia deja de pintarse justo antes de que aparezca el editor.
            loading.allowSceneActivation = false;
            while (loading.progress < 0.9f)
            {
                yield return null;
            }

            HideSonia();
            loading.allowSceneActivation = true;
            yield return loading;

            _editorScene = SceneManager.GetSceneByName(sceneName);
            if (_editorScene.IsValid())
            {
                SceneManager.SetActiveScene(_editorScene);
            }

            AvatarEditorSession.IsOpen = true;
            _lastInputTime = Time.realtimeSinceStartup;
            _busy = false;
            Debug.Log("[Sonia] Editor de personaje abierto.", this);
            if (client != null)
            {
                client.SendAvatarEditor(true);
            }
        }

        private IEnumerator CloseRoutine()
        {
            _busy = true;
            if (_editorScene.IsValid() && _editorScene.isLoaded)
            {
                AsyncOperation unloading = SceneManager.UnloadSceneAsync(_editorScene);
                if (unloading != null)
                {
                    yield return unloading;
                }
            }

            SceneManager.SetActiveScene(gameObject.scene);
            ShowSonia();
            AvatarEditorSession.IsOpen = false;
            _busy = false;
            Debug.Log("[Sonia] Editor de personaje cerrado.", this);
            if (client != null)
            {
                client.SendAvatarEditor(false);
            }
        }

        private void Update()
        {
            if (!AvatarEditorSession.IsOpen || _busy)
            {
                return;
            }

            if (AnyInput())
            {
                _lastInputTime = Time.realtimeSinceStartup;
            }
            else if (idleCloseSeconds > 0f && Time.realtimeSinceStartup - _lastInputTime > idleCloseSeconds)
            {
                // Que el stand no se quede sin Sonia si alguien deja el editor abierto.
                Debug.Log("[Sonia] Editor de personaje sin usar " + idleCloseSeconds.ToString("F0") + " s: se cierra sin guardar.", this);
                Close();
            }
        }

        private static bool AnyInput()
        {
            Mouse mouse = Mouse.current;
            if (mouse != null && (mouse.delta.ReadValue().sqrMagnitude > 0f || mouse.leftButton.isPressed
                                  || mouse.rightButton.isPressed || mouse.scroll.ReadValue().sqrMagnitude > 0f))
            {
                return true;
            }

            Keyboard keyboard = Keyboard.current;
            if (keyboard != null && keyboard.anyKey.isPressed)
            {
                return true;
            }

            Touchscreen touch = Touchscreen.current;
            return touch != null && touch.primaryTouch.press.isPressed;
        }

        /// <summary>¿Es una definición de Genies con piezas? Una vacía dejaría sin cuerpo ni ropa a todas las Sonias.</summary>
        private static bool IsValidDefinition(string definition)
        {
            try
            {
                JObject parsed = JObject.Parse(definition);
                JArray pieces = parsed["equippedAssetIds"] as JArray;
                return parsed["JsonVersion"] != null && pieces != null && pieces.Count > 0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        private void HandleSave(string definition)
        {
            if (string.IsNullOrEmpty(definition))
            {
                return;
            }

            if (!IsValidDefinition(definition))
            {
                Debug.LogWarning("[Sonia] El editor devolvió una definición sin piezas: no se guarda.", this);
                return;
            }

            string current = AvatarEditorSession.CurrentDefinition;
            if (!string.IsNullOrEmpty(current)
                && GeniesAvatarSnapshot.HashDefinition(current) == GeniesAvatarSnapshot.HashDefinition(definition))
            {
                Debug.Log("[Sonia] Personaje sin cambios: no se guarda nada.", this);
                Close();
                return;
            }

            _pendingDefinition = definition;
            if (client != null)
            {
                client.SendAvatarSaved(definition);
            }

            Debug.Log("[Sonia] Personaje guardado en el editor (" + definition.Length + " caracteres).", this);
            Close();
        }

        private void HandleSetAvatar(SetAvatarMessage message)
        {
            // El orquestador ya tiene la definición guardada: no hace falta repetirla.
            if (message != null && !string.IsNullOrEmpty(_pendingDefinition) && message.Definition == _pendingDefinition)
            {
                _pendingDefinition = null;
            }
        }

        private void HandleConnected()
        {
            if (!string.IsNullOrEmpty(_pendingDefinition) && client != null)
            {
                client.SendAvatarSaved(_pendingDefinition);
            }

            if (AvatarEditorSession.IsOpen && client != null)
            {
                client.SendAvatarEditor(true);
            }
        }

        private void HandleOpenMessage(OpenAvatarEditorMessage message)
        {
            Open();
        }

        private void HandleCloseMessage(CloseAvatarEditorMessage message)
        {
            Close();
        }

        private void HideSonia()
        {
            _hiddenRoots.Clear();
            _hiddenRenderers.Clear();
            _hiddenCanvases.Clear();

            // Las demás raíces de la escena: cámaras, luces, volumen, EventSystem...
            Transform root = transform.root;
            foreach (GameObject other in gameObject.scene.GetRootGameObjects())
            {
                if (other.transform != root && other.activeSelf)
                {
                    other.SetActive(false);
                    _hiddenRoots.Add(other);
                }
            }

            // La raíz de Sonia sigue viva (conexión, pipeline), pero sin pintar nada.
            foreach (Renderer renderer in root.GetComponentsInChildren<Renderer>(true))
            {
                if (renderer.enabled)
                {
                    renderer.enabled = false;
                    _hiddenRenderers.Add(renderer);
                }
            }

            foreach (Canvas canvas in root.GetComponentsInChildren<Canvas>(true))
            {
                if (canvas.enabled)
                {
                    canvas.enabled = false;
                    _hiddenCanvases.Add(canvas);
                }
            }
        }

        private void ShowSonia()
        {
            foreach (GameObject other in _hiddenRoots)
            {
                if (other != null)
                {
                    other.SetActive(true);
                }
            }

            foreach (Renderer renderer in _hiddenRenderers)
            {
                if (renderer != null)
                {
                    renderer.enabled = true;
                }
            }

            foreach (Canvas canvas in _hiddenCanvases)
            {
                if (canvas != null)
                {
                    canvas.enabled = true;
                }
            }

            _hiddenRoots.Clear();
            _hiddenRenderers.Clear();
            _hiddenCanvases.Clear();
        }
    }
}
