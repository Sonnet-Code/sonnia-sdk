// Capturas 9:16 de las pantallas de los juegos con Unity en batch, conducidas por
// el orquestador falso (scripts/juegos_demo.py). Receta en docs/juegos-unity.md.
//
//   UNITY_MCP_DISABLE_BATCH=1 Unity -batchmode -projectPath <clon>/unity \
//     -executeMethod Sonia.EditorTools.SoniaGameCapture.Run \
//     -sonia-ws ws://127.0.0.1:8791 -sonia-captures /ruta/capturas -logFile /ruta/unity.log
//
// Qué hace:
//  1. Abre la escena del stand, deja el cliente WebSocket sin conectar y la webcam
//     apagada, y entra en Play.
//  2. En Play, la cámara principal pinta a una RenderTexture fija de 1080x1920 y la
//     cámara del HUD también se ata a una de 1080x1920: así la proporción del
//     encuadre y el tamaño de los Canvas son los de la pantalla vertical del stand,
//     sea cual sea la «pantalla» del modo batch. Los Canvas superpuestos (Overlay)
//     pasan a Screen Space - Camera sobre la cámara del HUD para salir en la foto.
//  3. Espera a que el SDK de Genies entregue el avatar (como mucho
//     -sonia-avatar-timeout, 60 s) y entonces conecta SoniaClient a -sonia-ws: el
//     orquestador falso empieza al recibir el client_hello.
//  4. Cada dev_capture guarda <carpeta>/<name>.png (1080x1920, cámara principal con
//     el HUD) y una línea en <carpeta>/capturas.txt. dev_done sale de Unity (código
//     0). Si pasa -sonia-capture-timeout (600 s desde que arrancó Unity), sale con 3.
//
// Con -executeMethod Sonia.EditorTools.SoniaGameCapture.RunHudCheck no hace falta
// orquestador: recorre la pantalla común de los juegos (tarjeta, contador, rótulo,
// confeti, resultado y la vista en vivo con la foto de -sonia-preview-image) y guarda
// sus capturas. Es la comprobación de los cimientos.
//
// Solo editor: en la build no existe. No guarda nada fuera de la carpeta de capturas.

#if UNITY_EDITOR

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering.Universal;
using Object = UnityEngine.Object;

namespace Sonia.EditorTools
{
    /// <summary>Herramienta de capturas en batch para las pantallas de los juegos.</summary>
    [InitializeOnLoad]
    public static class SoniaGameCapture
    {
        /// <summary>Carpeta donde se guardan las capturas (obligatorio).</summary>
        public const string CapturesArgument = "-sonia-captures";

        /// <summary>Segundos como mucho desde que arranca Unity; luego sale con código 3.</summary>
        public const string TimeoutArgument = "-sonia-capture-timeout";

        /// <summary>Segundos como mucho esperando al avatar del SDK antes de conectar.</summary>
        public const string AvatarTimeoutArgument = "-sonia-avatar-timeout";

        /// <summary>Solo RunHudCheck: foto (JPEG) para la vista en vivo.</summary>
        public const string PreviewImageArgument = "-sonia-preview-image";

        public const int Width = 1080;
        public const int Height = 1920;

        private const string ScenePath = "Assets/Scenes/SampleScene.unity";
        private const string ModeKey = "SoniaGameCapture.Mode";
        private const string ModeOrchestrator = "ws";
        private const string ModeHudCheck = "hud";
        /// <summary>Metros de la base de la cabeza (hueso Head) a lo alto del pelo de Sonnia (medido en las capturas).</summary>
        private const float CrownAboveHead = 0.25f;

        private const float DefaultTimeout = 600f;
        private const float DefaultAvatarTimeout = 60f;

        private static Session s_session;
        private static bool s_exiting;

        static SoniaGameCapture()
        {
            // Tras la recarga de dominio al entrar en Play vuelve a pasar por aquí:
            // si la línea de órdenes pide capturas, se engancha la sesión.
            if (string.IsNullOrEmpty(Argument(CapturesArgument)))
            {
                return;
            }

            EditorApplication.update -= Tick;
            EditorApplication.update += Tick;
        }

        /// <summary>Entrada por línea de órdenes, con el orquestador falso en -sonia-ws.</summary>
        public static void Run()
        {
            Prepare(ModeOrchestrator);
        }

        /// <summary>Entrada por línea de órdenes, sin orquestador: comprueba la pantalla común.</summary>
        public static void RunHudCheck()
        {
            Prepare(ModeHudCheck);
        }

        private static void Prepare(string mode)
        {
            string folder = Argument(CapturesArgument);
            if (string.IsNullOrEmpty(folder))
            {
                Fail(2, "falta " + CapturesArgument + " <carpeta>");
                return;
            }

            if (mode == ModeOrchestrator && string.IsNullOrEmpty(SoniaClient.CommandLineServerUrl()))
            {
                Fail(2, "falta " + SoniaClient.ServerUrlArgument + " ws://127.0.0.1:<puerto> (el orquestador falso)");
                return;
            }

            if (EditorApplication.isPlaying)
            {
                Fail(2, "sal de Play antes de lanzar la herramienta");
                return;
            }

            Directory.CreateDirectory(Path.GetFullPath(folder));
            EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);

            // El cliente conecta cuando el avatar ya está (lo hace la sesión) y la
            // webcam de Unity no se abre nunca: ni cámaras de verdad ni gasto.
            foreach (SoniaClient client in Object.FindObjectsByType<SoniaClient>(FindObjectsInactive.Include))
            {
                SerializedObject so = new SerializedObject(client);
                SerializedProperty auto = so.FindProperty("autoConnect");
                if (auto != null)
                {
                    auto.boolValue = false;
                    so.ApplyModifiedPropertiesWithoutUndo();
                }
            }

            foreach (WebcamFrameSender webcam in Object.FindObjectsByType<WebcamFrameSender>(FindObjectsInactive.Include))
            {
                webcam.enabled = false;
            }

            SessionState.SetString(ModeKey, mode);
            Debug.Log("[Capturas] escena preparada (" + mode + "), entrando en Play. Capturas en " + Path.GetFullPath(folder));
            EditorApplication.EnterPlaymode();
        }

        private static void Tick()
        {
            if (s_exiting)
            {
                return;
            }

            float timeout = FloatArgument(TimeoutArgument, DefaultTimeout);
            if (EditorApplication.timeSinceStartup > timeout)
            {
                if (s_session != null)
                {
                    s_session.Close("tiempo agotado");
                }

                Fail(3, "tiempo agotado (" + timeout.ToString("0", CultureInfo.InvariantCulture) + " s desde que arrancó Unity)");
                return;
            }

            if (!EditorApplication.isPlaying)
            {
                if (s_session != null && s_session.Started)
                {
                    s_session.Close("se salió de Play");
                    Fail(4, "Unity salió de Play antes de dev_done");
                }

                return;
            }

            if (s_session == null)
            {
                string mode = SessionState.GetString(ModeKey, ModeOrchestrator);
                s_session = new Session(mode, Path.GetFullPath(Argument(CapturesArgument)));
            }

            try
            {
                s_session.Tick();
            }
            catch (Exception ex)
            {
                Debug.LogException(ex);
                s_session.Close("error: " + ex.Message);
                Fail(5, "error en la sesión de capturas: " + ex.Message);
                return;
            }

            if (s_session.Done)
            {
                s_session.Close("dev_done");
                Exit(0, "terminado: " + s_session.Count + " capturas en " + s_session.Folder);
            }
        }

        private static void Fail(int code, string message)
        {
            Debug.LogError("[Capturas] " + message);
            Exit(code, message);
        }

        private static void Exit(int code, string message)
        {
            if (s_exiting)
            {
                return;
            }

            s_exiting = true;
            EditorApplication.update -= Tick;
            Debug.Log("[Capturas] sale con código " + code + ": " + message);
            if (Application.isBatchMode)
            {
                EditorApplication.Exit(code);
            }
            else if (EditorApplication.isPlaying)
            {
                EditorApplication.isPlaying = false;
            }
        }

        // ------------------------------------------------------------------
        // Línea de órdenes
        // ------------------------------------------------------------------

        /// <summary>Valor que sigue a <paramref name="name"/> en la línea de órdenes, o null.</summary>
        public static string Argument(string name)
        {
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == name)
                {
                    return args[i + 1];
                }
            }

            return null;
        }

        private static float FloatArgument(string name, float fallback)
        {
            float value;
            string text = Argument(name);
            return text != null && float.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out value) && value > 0f
                ? value
                : fallback;
        }

        /// <summary>Nombre de archivo seguro: letras, números, '-', '_' y '.'; lo demás, '_'.</summary>
        public static string SafeName(string name, int index)
        {
            if (string.IsNullOrEmpty(name))
            {
                return "captura_" + index.ToString("D3", CultureInfo.InvariantCulture);
            }

            StringBuilder builder = new StringBuilder(name.Length);
            foreach (char c in name)
            {
                bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.';
                builder.Append(ok ? c : '_');
            }

            string safe = builder.ToString().Trim('.');
            return safe.Length == 0 ? "captura_" + index.ToString("D3", CultureInfo.InvariantCulture) : safe;
        }

        // ------------------------------------------------------------------
        // Sesión en Play
        // ------------------------------------------------------------------

        /// <summary>Todo lo de una ejecución en Play: cámaras fijas a 9:16, espera del avatar y capturas.</summary>
        private sealed class Session
        {
            private readonly string _mode;
            private readonly string _folder;
            private readonly Queue<string> _pending = new Queue<string>();
            private readonly List<Camera> _overlays = new List<Camera>();

            private SoniaBootstrap _bootstrap;
            private SoniaClient _client;
            private GameHud _hud;
            private CameraPreviewPanel _preview;
            private StageScreen _stage;
            private AvatarBinder _binder;
            private CameraFramingController _framing;
            private Camera _main;
            private RenderTexture _mainTarget;
            private RenderTexture _hudTarget;
            private Texture2D _image;
            private Texture2D _layer;
            private StreamWriter _log;
            private HudCheck _check;

            private bool _setUp;
            private bool _ready;
            private bool _connectRequested;
            private float _playStart = -1f;
            private float _avatarAt = -1f;
            private int _count;
            private bool _done;
            private bool _closed;
            private bool _warnedComposite;

            public Session(string mode, string folder)
            {
                _mode = mode;
                _folder = folder;
            }

            public bool Started
            {
                get { return _setUp; }
            }

            public bool Done
            {
                get { return _done; }
            }

            public int Count
            {
                get { return _count; }
            }

            public string Folder
            {
                get { return _folder; }
            }

            public GameHud Hud
            {
                get { return _hud; }
            }

            public CameraPreviewPanel Preview
            {
                get { return _preview; }
            }

            public void Tick()
            {
                if (_playStart < 0f)
                {
                    _playStart = Time.realtimeSinceStartup;
                }

                if (!_setUp && !TrySetUp())
                {
                    return;
                }

                if (!_ready)
                {
                    if (!WaitReady())
                    {
                        return;
                    }

                    _ready = true;
                    if (_mode == ModeHudCheck)
                    {
                        _check = new HudCheck(this, Argument(PreviewImageArgument));
                    }
                    else if (_client != null && !_connectRequested)
                    {
                        _connectRequested = true;
                        Write("conectando a " + _client.ServerUrl);
                        _client.Connect();
                    }
                }

                // Se mantiene a 9:16 aunque algo la toque.
                if (_main != null && _main.targetTexture != _mainTarget)
                {
                    _main.targetTexture = _mainTarget;
                }

                while (_pending.Count > 0)
                {
                    Capture(_pending.Dequeue());
                }

                if (_client != null && _client.PauseDispatch)
                {
                    _client.PauseDispatch = false;
                }

                if (_check != null && _check.Tick())
                {
                    _done = true;
                }
            }

            /// <summary>Pide una captura para el siguiente paso (también la usa HudCheck).</summary>
            public void Request(string name)
            {
                _pending.Enqueue(SafeName(name, _count + _pending.Count + 1));
            }

            private bool TrySetUp()
            {
                _bootstrap = Object.FindAnyObjectByType<SoniaBootstrap>();
                _main = Camera.main;
                if (_bootstrap == null || _main == null)
                {
                    return false;
                }

                _client = _bootstrap.GetComponentInChildren<SoniaClient>(true);
                _hud = _bootstrap.GetComponentInChildren<GameHud>(true);
                _preview = _bootstrap.GetComponentInChildren<CameraPreviewPanel>(true);
                _stage = _bootstrap.GetComponentInChildren<StageScreen>(true);
                _framing = _bootstrap.GetComponentInChildren<CameraFramingController>(true);
                _binder = _bootstrap.GetComponentInChildren<AvatarBinder>(true);
                if (_binder == null)
                {
                    _binder = Object.FindAnyObjectByType<AvatarBinder>();
                }

                Directory.CreateDirectory(_folder);
                _log = new StreamWriter(Path.Combine(_folder, "capturas.txt"), false, new UTF8Encoding(false));
                _log.AutoFlush = true;

                // Cámara principal y del HUD atadas a 1080x1920 durante toda la sesión.
                _mainTarget = new RenderTexture(Width, Height, 24, RenderTextureFormat.ARGB32);
                _mainTarget.name = "CapturaPrincipal";
                _mainTarget.antiAliasing = 4;
                _mainTarget.Create();
                _hudTarget = new RenderTexture(Width, Height, 24, RenderTextureFormat.ARGB32);
                _hudTarget.name = "CapturaHUD";
                _hudTarget.antiAliasing = 4;
                _hudTarget.Create();
                _main.targetTexture = _mainTarget;
                UniversalAdditionalCameraData data = _main.GetUniversalAdditionalCameraData();
                if (data != null && data.cameraStack != null)
                {
                    foreach (Camera overlay in data.cameraStack)
                    {
                        if (overlay != null)
                        {
                            overlay.targetTexture = _hudTarget;
                            _overlays.Add(overlay);
                        }
                    }
                }

                _image = new Texture2D(Width, Height, TextureFormat.RGBA32, false);
                _layer = new Texture2D(Width, Height, TextureFormat.RGBA32, false);

                // La malla sigue a los huesos aunque se renderice fuera del bucle.
                foreach (SkinnedMeshRenderer skinned in Object.FindObjectsByType<SkinnedMeshRenderer>(FindObjectsInactive.Include))
                {
                    skinned.forceMatrixRecalculationPerRender = true;
                }

                if (_client != null)
                {
                    _client.OnDevCapture += HandleDevCapture;
                    _client.OnDevDone += HandleDevDone;
                    _client.OnConnected += HandleConnected;
                    _client.OnDisconnected += HandleDisconnected;
                }

                ConvertOverlayCanvases();
                _setUp = true;
                Write("en Play: cámara " + _main.name + " a " + Width + "x" + Height + ", " + _overlays.Count + " cámara(s) del HUD, modo " + _mode);
                return true;
            }

            /// <summary>Avatar del SDK puesto (o tiempo de espera agotado), pantalla montada y un par de segundos de calma.</summary>
            private bool WaitReady()
            {
                float now = Time.realtimeSinceStartup;
                bool stageReady = _stage == null || _stage.IsBuilt;
                bool avatar = _binder != null && _binder.Current != null && _binder.Current.name.Contains("(Genies)");
                float avatarTimeout = FloatArgument(AvatarTimeoutArgument, DefaultAvatarTimeout);
                bool gaveUp = now - _playStart > avatarTimeout;
                if (!(stageReady && (avatar || gaveUp)))
                {
                    return false;
                }

                if (_avatarAt < 0f)
                {
                    _avatarAt = now;
                    Write(avatar
                        ? "avatar del SDK listo tras " + (now - _playStart).ToString("0.0", CultureInfo.InvariantCulture) + " s"
                        : "sin avatar del SDK tras " + avatarTimeout.ToString("0", CultureInfo.InvariantCulture) + " s: sigue el doble");
                    if (_hud != null)
                    {
                        _hud.EnsureBuilt();
                    }

                    if (_framing != null)
                    {
                        _framing.SnapNextFrame();
                    }
                }

                // Que la cámara llegue a su plano y la animación de reposo se asiente.
                return now - _avatarAt >= 2.5f;
            }

            private void HandleDevCapture(DevCaptureMessage message)
            {
                Request(message != null ? message.Name : null);

                // Lo que llegue detrás espera a que esté hecha la captura.
                if (_client != null)
                {
                    _client.PauseDispatch = true;
                }
            }

            private void HandleDevDone(DevDoneMessage message)
            {
                Write("dev_done");
                _done = true;
            }

            private void HandleConnected()
            {
                Write("conectada al orquestador falso");
            }

            private void HandleDisconnected()
            {
                Write("desconectada del orquestador falso");
            }

            /// <summary>Los Canvas en Overlay no salen en una RenderTexture: pasan a la cámara del HUD.</summary>
            private void ConvertOverlayCanvases()
            {
                Camera hudCamera = _overlays.Count > 0 ? _overlays[0] : _main;
                int layer = LayerMask.NameToLayer("UI");
                foreach (Canvas canvas in Object.FindObjectsByType<Canvas>(FindObjectsInactive.Include))
                {
                    if (!canvas.isRootCanvas || canvas.renderMode != RenderMode.ScreenSpaceOverlay)
                    {
                        continue;
                    }

                    canvas.renderMode = RenderMode.ScreenSpaceCamera;
                    canvas.worldCamera = hudCamera;
                    canvas.planeDistance = 0.25f;
                    if (layer >= 0 && hudCamera != _main)
                    {
                        foreach (Transform child in canvas.GetComponentsInChildren<Transform>(true))
                        {
                            child.gameObject.layer = layer;
                        }
                    }
                }
            }

            private void Capture(string name)
            {
                ConvertOverlayCanvases();
                if (_main.targetTexture != _mainTarget)
                {
                    _main.targetTexture = _mainTarget;
                }

                // 1. La escena sin el HUD: con la cámara del HUD atada a su propia
                //    RenderTexture (para que los Canvas midan 1080x1920), URP la pinta
                //    allí y no encima de la principal. Así no sale dos veces.
                bool[] wasEnabled = new bool[_overlays.Count];
                for (int i = 0; i < _overlays.Count; i++)
                {
                    wasEnabled[i] = _overlays[i] != null && _overlays[i].enabled;
                    if (_overlays[i] != null)
                    {
                        _overlays[i].enabled = false;
                    }
                }

                try
                {
                    _main.Render();
                }
                finally
                {
                    for (int i = 0; i < _overlays.Count; i++)
                    {
                        if (_overlays[i] != null)
                        {
                            _overlays[i].enabled = wasEnabled[i];
                        }
                    }
                }

                ReadInto(_mainTarget, _image);

                // 2. El HUD solo, sobre transparente, y encima de la escena.
                int layers = 0;
                foreach (Camera overlay in _overlays)
                {
                    if (overlay != null && overlay.isActiveAndEnabled && RenderOverlay(overlay))
                    {
                        CompositePremultiplied(_image, _layer);
                        layers++;
                    }
                }

                string path = Path.Combine(_folder, name + ".png");
                File.WriteAllBytes(path, _image.EncodeToPNG());
                _count++;
                string shot = _framing == null ? "?" : _framing.IsPanelShot ? "panel" : _framing.IsIdleShot ? "reposo" : _framing.IsWideShot ? "abierto" : "conversación";
                Write(string.Format(
                    CultureInfo.InvariantCulture,
                    "captura {0}: {1}.png (t={2:0.0} s, juego «{3}», vista en vivo {4}, plano de {5}, {6} capa(s) de HUD; {7})",
                    _count,
                    name,
                    Time.realtimeSinceStartup - _playStart,
                    _hud != null ? _hud.CurrentGame : "?",
                    _preview != null && _preview.IsVisible ? "sí (" + _preview.FramesShown + " frames)" : "no",
                    shot,
                    layers,
                    FaceReport()));
                if (layers == 0 && _overlays.Count > 0 && !_warnedComposite)
                {
                    _warnedComposite = true;
                    Write("aviso: no se pudo pintar el HUD");
                }
            }

            /// <summary>
            /// Dónde queda la cabeza de Sonnia en la captura frente a lo de la franja
            /// alta, en px desde arriba: para ver sin mirar si algo le tapa la cara.
            /// </summary>
            private string FaceReport()
            {
                Animator animator = _binder != null && _binder.Current != null
                    ? _binder.Current.GetComponentInChildren<Animator>()
                    : null;
                Transform head = animator != null && animator.isHuman ? animator.GetBoneTransform(HumanBodyBones.Head) : null;
                if (head == null)
                {
                    return "cabeza de Sonnia sin localizar";
                }

                float crown = ToPixels(head.position + (Vector3.up * CrownAboveHead));
                float neck = ToPixels(head.position);
                float strip = _hud != null ? _hud.TopStripBottom : 0f;
                string warning = strip > crown + 8f ? " ¡LO DE ARRIBA TAPA LA CABEZA DE SONNIA!" : string.Empty;
                return string.Format(
                    CultureInfo.InvariantCulture,
                    "franja alta hasta {0:0} px, coronilla de Sonnia ~{1:0} px, base de la cabeza {2:0} px{3}",
                    strip,
                    crown,
                    neck,
                    warning);
            }

            private float ToPixels(Vector3 world)
            {
                Vector3 viewport = _main.WorldToViewportPoint(world);
                return (1f - viewport.y) * Height;
            }

            private bool RenderOverlay(Camera overlay)
            {
                UniversalAdditionalCameraData data = overlay.GetUniversalAdditionalCameraData();
                CameraRenderType savedType = data.renderType;
                CameraClearFlags savedClear = overlay.clearFlags;
                Color savedBackground = overlay.backgroundColor;
                try
                {
                    data.renderType = CameraRenderType.Base;
                    overlay.clearFlags = CameraClearFlags.SolidColor;
                    overlay.backgroundColor = new Color(0f, 0f, 0f, 0f);
                    overlay.targetTexture = _hudTarget;
                    overlay.Render();
                    ReadInto(_hudTarget, _layer);
                    return true;
                }
                catch (Exception ex)
                {
                    Debug.LogException(ex);
                    return false;
                }
                finally
                {
                    overlay.clearFlags = savedClear;
                    overlay.backgroundColor = savedBackground;
                    data.renderType = savedType;
                }
            }

            private static void ReadInto(RenderTexture source, Texture2D target)
            {
                RenderTexture previous = RenderTexture.active;
                RenderTexture.active = source;
                target.ReadPixels(new Rect(0f, 0f, source.width, source.height), 0, 0);
                target.Apply(false);
                RenderTexture.active = previous;
            }

            /// <summary>
            /// Pone <paramref name="layer"/> encima de <paramref name="image"/>. El HUD se
            /// pinta con alfa premultiplicado (los shaders de la UI y de TextMeshPro
            /// mezclan con One, OneMinusSrcAlpha) sobre un fondo transparente, así que
            /// su color ya viene multiplicado por su alfa.
            /// </summary>
            private static void CompositePremultiplied(Texture2D image, Texture2D layer)
            {
                Color32[] basePixels = image.GetPixels32();
                Color32[] top = layer.GetPixels32();
                int count = Mathf.Min(basePixels.Length, top.Length);
                for (int i = 0; i < count; i++)
                {
                    Color32 t = top[i];
                    if (t.a == 0 && t.r == 0 && t.g == 0 && t.b == 0)
                    {
                        continue;
                    }

                    int inv = 255 - t.a;
                    Color32 b = basePixels[i];
                    basePixels[i] = new Color32(
                        (byte)Mathf.Min(255, t.r + ((b.r * inv) / 255)),
                        (byte)Mathf.Min(255, t.g + ((b.g * inv) / 255)),
                        (byte)Mathf.Min(255, t.b + ((b.b * inv) / 255)),
                        255);
                }

                image.SetPixels32(basePixels);
                image.Apply(false);
            }

            public void Write(string line)
            {
                string text = "[Capturas] " + line;
                Debug.Log(text);
                if (_log != null)
                {
                    _log.WriteLine(DateTime.Now.ToString("HH:mm:ss", CultureInfo.InvariantCulture) + " " + line);
                }
            }

            public void Close(string why)
            {
                if (_closed)
                {
                    return;
                }

                _closed = true;
                Write("fin (" + why + "): " + _count + " capturas");
                if (_client != null)
                {
                    _client.OnDevCapture -= HandleDevCapture;
                    _client.OnDevDone -= HandleDevDone;
                    _client.OnConnected -= HandleConnected;
                    _client.OnDisconnected -= HandleDisconnected;
                }

                if (_log != null)
                {
                    _log.Dispose();
                    _log = null;
                }
            }
        }

        // ------------------------------------------------------------------
        // Comprobación de la pantalla común (sin orquestador)
        // ------------------------------------------------------------------

        /// <summary>Recorre la tarjeta, el contador, el rótulo, el confeti, el resultado y la vista en vivo.</summary>
        private sealed class HudCheck
        {
            private readonly Session _session;
            private readonly byte[] _jpeg;
            private readonly List<KeyValuePair<float, Action>> _steps = new List<KeyValuePair<float, Action>>();
            private float _start = -1f;
            private int _next;
            private bool _feeding;
            private float _nextFrame;
            private uint _seq;

            public HudCheck(Session session, string imagePath)
            {
                _session = session;
                if (!string.IsNullOrEmpty(imagePath) && File.Exists(imagePath))
                {
                    _jpeg = File.ReadAllBytes(imagePath);
                }
                else
                {
                    session.Write("sin " + PreviewImageArgument + ": la vista en vivo usa una imagen sintética");
                    _jpeg = SyntheticJpeg();
                }

                GameHud hud = session.Hud;
                CameraPreviewPanel preview = session.Preview;
                const string demo = "ruleta";
                float t = 0f;
                At(t, () => session.Request("hud-00-reposo"));
                At(t += 0.5f, () =>
                {
                    RectTransform content = hud.Open(demo, "La ruleta de Sonnia");
                    hud.SetCaption("RONDA 1 DE 3");
                    hud.SetContentHeight(demo, 300f);
                    FillDemoContent(hud, content);
                });
                At(t += 1.6f, () => session.Request("hud-01-tarjeta"));
                At(t += 0.2f, () => hud.StartCountdown(20f));
                At(t += 2.4f, () => session.Request("hud-02-contador"));
                At(t += 0.2f, () =>
                {
                    hud.ShowBanner("¡Correcto!", GameColors.Green);
                    hud.BurstFrom(hud.Card, 90, 1300f);
                    hud.SparklesAt(hud.Card, 10);
                });
                At(t += 0.45f, () => session.Request("hud-03-rotulo-confeti"));
                At(t += 2.0f, () =>
                {
                    hud.StopCountdown(false);
                    hud.ShowResult("¡GANASTE!", "7 de 9", "¡Eres un crack del DevFest!", true);
                });
                At(t += 1.3f, () => session.Request("hud-04-resultado"));
                At(t += 1.2f, () => session.Request("hud-05-resultado-lluvia"));
                At(t += 0.3f, () => hud.Close(demo));
                At(t += 1.5f, () => session.Request("hud-06-cerrado"));
                At(t += 0.2f, () =>
                {
                    preview.HandleSwitch(new CameraPreviewMessage { On = true, Mirror = true });
                    _feeding = true;
                });
                At(t += 1.8f, () => session.Request("hud-07-vista-en-vivo"));
                At(t += 0.2f, () =>
                {
                    RectTransform content = hud.Open("busqueda", "Búsqueda relámpago");
                    hud.SetCardTop(preview.BottomFraction + 0.02f);
                    hud.SetCaption("RONDA 2 DE 3");
                    hud.SetContentHeight("busqueda", 150f);
                    FillDemoContent(hud, content);
                    hud.StartCountdown(25f);
                });
                At(t += 1.6f, () => session.Request("hud-08-vista-y-tarjeta"));
                At(t += 0.2f, () =>
                {
                    hud.ShowResult("¡CASI!", "2 de 3", "¡Pídeme otra partida!", false);
                });
                At(t += 1.4f, () => session.Request("hud-09-resultado-con-vista"));
                At(t += 0.2f, () =>
                {
                    hud.Close("busqueda");
                    _feeding = false;
                });
                At(t += 1.0f, () => session.Request("hud-10-sin-frames-1s"));
                At(t += 2.0f, () => session.Request("hud-11-vista-retirada"));

                // Planos: tarjeta sola y vista en vivo con tarjeta, con desplazamientos
                // fijos y con el automático (para calibrarlo: ver capturas.txt).
                Vector3[] shortShots = { Vector3.zero, new Vector3(0f, 0.15f, -0.4f), new Vector3(0f, 0.3f, -0.8f) };
                Vector3[] tallShots = { new Vector3(0f, 0.5f, -1.3f), new Vector3(0f, 0.75f, -2f), new Vector3(0f, 1f, -2.7f) };
                At(t += 0.3f, () =>
                {
                    RectTransform content = hud.Open(demo, "La ruleta de Sonnia");
                    hud.SetContentHeight(demo, 300f);
                    FillDemoContent(hud, content);
                });
                for (int i = 0; i < shortShots.Length; i++)
                {
                    Vector3 extra = shortShots[i];
                    string label = "plano-corto-" + i;
                    At(t += 0.1f, () => hud.RequestPanelShot(extra));
                    At(t += 3f, () => session.Request(label));
                }

                At(t += 0.1f, () => hud.RequestPanelShot());
                At(t += 3f, () => session.Request("plano-corto-auto"));
                At(t += 0.1f, () =>
                {
                    preview.HandleSwitch(new CameraPreviewMessage { On = true, Mirror = true });
                    _feeding = true;
                    RectTransform content = hud.Open("busqueda", "Búsqueda relámpago");
                    hud.SetContentHeight("busqueda", 150f);
                    FillDemoContent(hud, content);
                });
                for (int i = 0; i < tallShots.Length; i++)
                {
                    Vector3 extra = tallShots[i];
                    string label = "plano-largo-" + i;
                    At(t += 0.1f, () => hud.RequestPanelShot(extra));
                    At(t += 3f, () => session.Request(label));
                }

                At(t += 0.1f, () => hud.RequestPanelShot());
                At(t += 3f, () => session.Request("plano-largo-auto"));
                At(t += 0.1f, () =>
                {
                    hud.Close("busqueda");
                    _feeding = false;
                });
                At(t += 3f, () => session.Request("hud-12-final"));
                At(t += 0.3f, () => { });
            }

            /// <summary>Avanza; devuelve cierto al acabar.</summary>
            public bool Tick()
            {
                float now = Time.realtimeSinceStartup;
                if (_start < 0f)
                {
                    _start = now;
                }

                if (_feeding && now >= _nextFrame)
                {
                    _nextFrame = now + 0.1f;
                    _seq++;
                    _session.Preview.HandleFrame(new PreviewFrame { Seq = _seq, Width = 640, Height = 360, Mirrored = false, Jpeg = _jpeg });
                }

                while (_next < _steps.Count && now - _start >= _steps[_next].Key)
                {
                    _steps[_next].Value();
                    _next++;
                }

                return _next >= _steps.Count;
            }

            private void At(float seconds, Action action)
            {
                _steps.Add(new KeyValuePair<float, Action>(seconds, action));
            }

            /// <summary>Un contenido de ejemplo dentro de la tarjeta: lo que pondría un juego.</summary>
            private static void FillDemoContent(GameHud hud, RectTransform content)
            {
                if (content == null || content.childCount > 0)
                {
                    return;
                }

                TMPro.TextMeshProUGUI text = hud.NewText(
                    "Ejemplo", content, "Contenido del juego\n(lo pinta cada juego)", 46f, Color.white);
                GameUi.Stretch(text.rectTransform);
                text.color = GameUi.WithAlpha(Color.white, 0.85f);
            }

            /// <summary>Degradado con cuadrícula, por si no hay foto: nunca una cámara de verdad.</summary>
            private static byte[] SyntheticJpeg()
            {
                Texture2D texture = new Texture2D(640, 360, TextureFormat.RGB24, false);
                Color32[] pixels = new Color32[640 * 360];
                for (int y = 0; y < 360; y++)
                {
                    for (int x = 0; x < 640; x++)
                    {
                        bool grid = x % 80 < 3 || y % 80 < 3;
                        byte r = (byte)(40 + (x * 150 / 640));
                        byte g = (byte)(60 + (y * 120 / 360));
                        pixels[(y * 640) + x] = grid ? new Color32(255, 255, 255, 255) : new Color32(r, g, 170, 255);
                    }
                }

                texture.SetPixels32(pixels);
                texture.Apply(false);
                byte[] jpeg = texture.EncodeToJPG(80);
                Object.DestroyImmediate(texture);
                return jpeg;
            }
        }
    }
}

#endif
