// Vista en vivo de la cámara en los juegos que la usan (docs/plan-juegos.md, 4.2 y
// 4.3; decisión de Jean del 10 de octubre de 2026): poses, piedra, papel o
// tijera y búsqueda relámpago.
//
// - Va en la franja alta, encima de Sonnia, en 16:9 con las esquinas redondeadas
//   y el rótulo «En vivo · no se graba». Es la única excepción a que las imágenes
//   de la cámara no salgan en pantalla: solo en directo, mientras dura el juego.
//   Unity no guarda nada: cada frame pisa al anterior en la misma textura.
// - El orquestador la enciende con camera_preview (on) y manda frames binarios
//   "SNCV" (JPEG de 640x360, unos 10 por segundo, con los esqueletos y las marcas
//   ya dibujados). Sale con el primer frame y se retira con on: false o si pasan
//   frameTimeoutSeconds sin frames.
// - El JPEG se decodifica con Texture2D.LoadImage, en el hilo principal: como
//   mucho uno por fotograma (el más reciente) y siempre en la misma textura.
// - mirror: true con un frame que no viene ya en espejo (bit 0 de los flags) se
//   voltea aquí. Si la imagen no es 16:9, se recorta al centro para llenar el marco.
// - Tras reconectar (hello), mientras no llegue un camera_preview, los frames que
//   lleguen se enseñan igual: el orquestador solo los manda con la vista encendida.
//
// Cada juego puede poner sus marcas encima (Overlay) o moverla y agrandarla
// (SetPlacement); al retirarse vuelve a su sitio.

using System;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>La imagen en vivo de la cámara durante los juegos, encima de Sonnia.</summary>
    [DisallowMultipleComponent]
    public class CameraPreviewPanel : MonoBehaviour
    {
        [Header("Diseño (píxeles de la referencia 1080x1920)")]
        [SerializeField]
        [Tooltip("Ancho de la vista; el alto sale de 16:9.")]
        private float width = 960f;

        [SerializeField]
        [Range(0f, 0.5f)]
        [Tooltip("Distancia del borde superior de la vista al de la pantalla, en fracción del alto.")]
        private float top = 0.105f;

        [SerializeField]
        [Tooltip("Radio de las esquinas.")]
        private float cornerRadius = 28f;

        [SerializeField]
        [Tooltip("Rótulo fijo de la esquina: que se vea que no se graba.")]
        private string label = "En vivo · no se graba";

        [Header("Tiempos")]
        [SerializeField]
        [Range(0.5f, 10f)]
        [Tooltip("Sin frames durante este tiempo, la vista se retira.")]
        private float frameTimeoutSeconds = 2f;

        [SerializeField]
        [Tooltip("Escribir en la consola cuándo sale y se retira.")]
        private bool logEvents = true;

        /// <summary>Proporción de la vista (ancho entre alto).</summary>
        public const float Aspect = 16f / 9f;

        private const string HudCanvasName = "SoniaHUD";

        private enum Switch
        {
            Unknown,
            On,
            Off
        }

        private GameHud _hud;
        private RectTransform _root;
        private CanvasGroup _group;
        private RectTransform _frame;
        private RawImage _image;
        private RectTransform _overlay;
        private Image _liveDot;
        private Texture2D _texture;

        private Switch _switch = Switch.Unknown;
        private bool _mirrorRequested = true;
        private bool _frameMirrored;
        private PreviewFrame _pending;
        private bool _showing;
        private float _lastFrameAt = -100f;
        private float _alpha;
        private float _shownAt = -1f;
        private float _currentWidth;
        private float _currentTop;
        private int _imageWidth;
        private int _imageHeight;
        private int _framesShown;
        private bool _suppressed;

        /// <summary>Cierto mientras la vista se ve (también mientras se funde al salir).</summary>
        public bool IsVisible
        {
            get { return (_showing && !_suppressed) || _alpha > 0.001f; }
        }

        /// <summary>
        /// Apartada (sin dejar de recibir frames) mientras otra cosa ocupa su sitio: la
        /// tarjeta del resultado final de GameHud.
        /// </summary>
        public bool Suppressed
        {
            get { return _suppressed; }
            set { _suppressed = value; }
        }

        /// <summary>Cierto si el orquestador la tiene encendida (camera_preview on).</summary>
        public bool IsOn
        {
            get { return _switch == Switch.On; }
        }

        /// <summary>Todo lo de la vista (para ordenarlo con otras capas).</summary>
        public RectTransform Root
        {
            get
            {
                EnsureBuilt();
                return _root;
            }
        }

        /// <summary>El marco 16:9 de la imagen.</summary>
        public RectTransform Frame
        {
            get
            {
                EnsureBuilt();
                return _frame;
            }
        }

        /// <summary>
        /// Capa encima de la imagen, del tamaño del marco y sin recortar: para las
        /// marcas del juego (pictograma, contador...). Las limpia cada juego.
        /// </summary>
        public RectTransform Overlay
        {
            get
            {
                EnsureBuilt();
                return _overlay;
            }
        }

        /// <summary>Tamaño del marco ahora, en píxeles de la referencia.</summary>
        public Vector2 FrameSize
        {
            get
            {
                float w = _currentWidth > 0f ? _currentWidth : width;
                return new Vector2(w, w / Aspect);
            }
        }

        /// <summary>Borde de abajo del marco, en fracción del alto de la pantalla (0 arriba): para colocar algo debajo.</summary>
        public float BottomFraction
        {
            get
            {
                float t = _currentWidth > 0f ? _currentTop : top;
                return t + (FrameSize.y / GameHud.ReferenceHeight);
            }
        }

        /// <summary>Frames enseñados desde que salió la vista (para pruebas).</summary>
        public int FramesShown
        {
            get { return _framesShown; }
        }

        /// <summary>La vista sale (true) o termina de retirarse (false).</summary>
        public event Action<bool> VisibilityChanged;

        // ------------------------------------------------------------------
        // Mensajes (los pasa GameRouter)
        // ------------------------------------------------------------------

        /// <summary>camera_preview: on enciende (sale con el primer frame), off la retira ya.</summary>
        public void HandleSwitch(CameraPreviewMessage message)
        {
            if (message == null)
            {
                return;
            }

            _switch = message.On ? Switch.On : Switch.Off;
            _mirrorRequested = message.Mirror;
            if (!message.On)
            {
                _pending = null;
                Hide("apagada");
            }
            else
            {
                UpdateUv();
            }
        }

        /// <summary>Un frame "SNCV": se guarda el más reciente y se decodifica en este fotograma.</summary>
        public void HandleFrame(PreviewFrame frame)
        {
            if (frame == null || frame.Jpeg == null || _switch == Switch.Off)
            {
                return;
            }

            _pending = frame;
        }

        /// <summary>Nueva conexión con el orquestador: hasta que diga otra cosa, los frames que lleguen se enseñan.</summary>
        public void HandleReconnect()
        {
            _switch = Switch.Unknown;
            _mirrorRequested = true;
        }

        /// <summary>Retira la vista ya (sin esperar al orquestador).</summary>
        public void Hide()
        {
            Hide("retirada");
        }

        /// <summary>
        /// Coloca la vista: borde de arriba a <paramref name="topFraction"/> del alto
        /// de la pantalla y <paramref name="frameWidth"/> píxeles de ancho (16:9).
        /// Al retirarse vuelve a su sitio de siempre.
        /// </summary>
        public void SetPlacement(float topFraction, float frameWidth)
        {
            EnsureBuilt();
            _currentTop = Mathf.Clamp01(topFraction);
            _currentWidth = Mathf.Clamp(frameWidth, 160f, GameHud.ReferenceWidth);
            ApplyPlacement();
        }

        /// <summary>Vuelve a su sitio y tamaño de siempre (el de la tarjeta de los juegos).</summary>
        public void ResetPlacement()
        {
            _currentTop = top;
            _currentWidth = width;
            ApplyPlacement();
        }

        // ------------------------------------------------------------------
        // Bucle
        // ------------------------------------------------------------------

        private void Awake()
        {
            _hud = GetComponent<GameHud>();
            _currentTop = top;
            _currentWidth = width;
        }

        private void OnDestroy()
        {
            if (_texture != null)
            {
                Destroy(_texture);
                _texture = null;
            }
        }

        private void LateUpdate()
        {
            // Después de los Update: el frame que entregó el cliente en este
            // fotograma se decodifica ya. Uno por fotograma como mucho.
            PreviewFrame frame = _pending;
            _pending = null;
            if (frame != null)
            {
                Decode(frame);
            }

            if (_root == null)
            {
                return;
            }

            float now = Time.unscaledTime;
            if (_showing && now - _lastFrameAt > frameTimeoutSeconds)
            {
                Hide("sin frames en " + frameTimeoutSeconds.ToString("0.#") + " s");
            }

            float dt = Time.unscaledDeltaTime;
            bool show = _showing && !_suppressed;
            _alpha = Mathf.MoveTowards(_alpha, show ? 1f : 0f, dt / (show ? 0.25f : 0.35f));
            _group.alpha = _alpha;
            if (!_showing && _alpha <= 0.001f)
            {
                if (_root.gameObject.activeSelf)
                {
                    _root.gameObject.SetActive(false);
                    ResetPlacement();
                    Raise(false);
                }

                return;
            }

            if (_suppressed && _alpha <= 0.001f)
            {
                return;
            }

            if (_shownAt >= 0f)
            {
                float s = now - _shownAt;
                float scale = Mathf.Lerp(0.94f, 1f, GameUi.EaseOutBack(Mathf.Clamp01(s / 0.4f)));
                _frame.localScale = new Vector3(scale, scale, 1f);
            }

            if (_liveDot != null)
            {
                float pulse = 0.55f + (0.45f * Mathf.Abs(Mathf.Sin(now * 2.6f)));
                _liveDot.color = GameUi.WithAlpha(GameColors.Live, pulse);
            }
        }

        private void Decode(PreviewFrame frame)
        {
            if (_switch == Switch.Off)
            {
                return;
            }

            EnsureBuilt();
            if (_root == null)
            {
                return;
            }

            if (_texture == null)
            {
                _texture = new Texture2D(2, 2, TextureFormat.RGB24, false);
                _texture.name = "VistaEnVivo";
                _texture.wrapMode = TextureWrapMode.Clamp;
                _texture.filterMode = FilterMode.Bilinear;
            }

            // Misma textura siempre: LoadImage la redimensiona si cambia el tamaño.
            if (!_texture.LoadImage(frame.Jpeg, false))
            {
                return;
            }

            _frameMirrored = frame.Mirrored;
            if (_texture.width != _imageWidth || _texture.height != _imageHeight || _image.texture != _texture)
            {
                _imageWidth = _texture.width;
                _imageHeight = _texture.height;
                _image.texture = _texture;
            }

            UpdateUv();
            _lastFrameAt = Time.unscaledTime;
            _framesShown++;
            if (!_showing)
            {
                Show();
            }
        }

        private void Show()
        {
            _showing = true;
            _shownAt = Time.unscaledTime;
            _framesShown = 1;
            ApplyPlacement();
            _root.gameObject.SetActive(true);
            Log("vista en vivo encendida");
            Raise(true);
        }

        private void Hide(string why)
        {
            if (!_showing)
            {
                return;
            }

            _showing = false;
            Log("vista en vivo retirada (" + why + ")");
        }

        /// <summary>Recorte al centro para llenar el 16:9 y, si toca, espejo.</summary>
        private void UpdateUv()
        {
            if (_image == null)
            {
                return;
            }

            Rect uv = new Rect(0f, 0f, 1f, 1f);
            if (_imageWidth > 0 && _imageHeight > 0)
            {
                float aspect = _imageWidth / (float)_imageHeight;
                if (aspect > Aspect + 0.01f)
                {
                    float w = Aspect / aspect;
                    uv = new Rect((1f - w) * 0.5f, 0f, w, 1f);
                }
                else if (aspect < Aspect - 0.01f)
                {
                    float h = aspect / Aspect;
                    uv = new Rect(0f, (1f - h) * 0.5f, 1f, h);
                }
            }

            if (_mirrorRequested && !_frameMirrored)
            {
                uv = new Rect(uv.x + uv.width, uv.y, -uv.width, uv.height);
            }

            _image.uvRect = uv;
        }

        private void ApplyPlacement()
        {
            if (_frame == null)
            {
                return;
            }

            GameUi.PlaceTop(_frame, _currentTop, FrameSize);
        }

        // ------------------------------------------------------------------
        // Construcción
        // ------------------------------------------------------------------

        /// <summary>
        /// Monta la vista en el Canvas del HUD en esa posición entre sus hermanos (la
        /// llama GameHud al montarse, para que quede justo detrás de los juegos).
        /// </summary>
        public void BuildUnder(Canvas canvas, int siblingIndex)
        {
            if (_root != null)
            {
                _root.SetSiblingIndex(Mathf.Clamp(siblingIndex, 0, _root.parent.childCount - 1));
                return;
            }

            if (canvas == null)
            {
                return;
            }

            if (_hud == null)
            {
                _hud = GetComponent<GameHud>();
            }

            if (_hud == null)
            {
                _hud = gameObject.AddComponent<GameHud>();
            }

            CanvasGroup group = _hud.NewGroup("VistaEnVivo", canvas.transform);
            _root = (RectTransform)group.transform;
            _root.SetSiblingIndex(Mathf.Clamp(siblingIndex, 0, canvas.transform.childCount - 1));
            _group = group;
            _group.alpha = 0f;

            _frame = _hud.NewRect("Marco", _root);
            ApplyPlacement();

            // Sombra suave alrededor, como la de las tarjetas.
            Image shadow = _hud.NewImage("Sombra", _frame, _hud.GlowSprite, new Color(0f, 0f, 0f, 0.55f));
            shadow.rectTransform.anchorMin = Vector2.zero;
            shadow.rectTransform.anchorMax = Vector2.one;
            shadow.rectTransform.offsetMin = new Vector2(-70f, -84f);
            shadow.rectTransform.offsetMax = new Vector2(70f, 56f);

            // La imagen, recortada con las esquinas redondeadas (máscara de la UI).
            Image maskShape = _hud.NewImage("Mascara", _frame, _hud.RoundSprite, Color.white);
            GameHud.SetRadius(maskShape, cornerRadius);
            GameUi.Stretch(maskShape.rectTransform);
            Mask mask = maskShape.gameObject.AddComponent<Mask>();
            mask.showMaskGraphic = false;

            RectTransform imageRect = _hud.NewRect("Imagen", maskShape.rectTransform);
            GameUi.Stretch(imageRect);
            _image = imageRect.gameObject.AddComponent<RawImage>();
            _image.raycastTarget = false;
            _image.color = Color.white;

            // Contorno encima: tapa el borde dentado de la máscara.
            Image border = _hud.NewImage("Borde", _frame, _hud.FrameSprite, GameUi.WithAlpha(new Color(0.62f, 0.78f, 1f), 0.95f));
            GameHud.SetRadius(border, cornerRadius);
            GameUi.Stretch(border.rectTransform);

            _overlay = _hud.NewRect("Encima", _frame);
            GameUi.Stretch(_overlay);

            BuildLabel();
            _root.gameObject.SetActive(false);
        }

        /// <summary>Pastilla oscura arriba a la izquierda: punto rojo y «En vivo · no se graba».</summary>
        private void BuildLabel()
        {
            RectTransform pill = _hud.NewRect("Rotulo", _frame);
            pill.anchorMin = new Vector2(0f, 1f);
            pill.anchorMax = new Vector2(0f, 1f);
            pill.pivot = new Vector2(0f, 1f);
            pill.anchoredPosition = new Vector2(22f, -22f);
            HorizontalLayoutGroup row = pill.gameObject.AddComponent<HorizontalLayoutGroup>();
            row.padding = new RectOffset(20, 26, 10, 12);
            row.spacing = 12f;
            row.childAlignment = TextAnchor.MiddleLeft;
            row.childControlWidth = true;
            row.childControlHeight = true;
            row.childForceExpandWidth = false;
            row.childForceExpandHeight = false;
            ContentSizeFitter fit = pill.gameObject.AddComponent<ContentSizeFitter>();
            fit.horizontalFit = ContentSizeFitter.FitMode.PreferredSize;
            fit.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            Image face = _hud.NewRound("Fondo", pill, GameUi.WithAlpha(GameColors.Dark, 0.8f), 24f);
            face.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;
            GameUi.Stretch(face.rectTransform);

            _liveDot = _hud.NewImage("Punto", pill, _hud.DotSprite, GameColors.Live);
            LayoutElement dotLayout = _liveDot.gameObject.AddComponent<LayoutElement>();
            dotLayout.preferredWidth = 18f;
            dotLayout.preferredHeight = 18f;

            TextMeshProUGUI text = _hud.NewText("Texto", pill, label, 28f, Color.white, TextAlignmentOptions.MidlineLeft, _hud.BodyFont);
            text.textWrappingMode = TextWrappingModes.NoWrap;
        }

        private void EnsureBuilt()
        {
            if (_root != null)
            {
                return;
            }

            if (_hud == null)
            {
                _hud = GetComponent<GameHud>();
            }

            if (_hud != null)
            {
                // GameHud llama a BuildUnder al montarse.
                _hud.EnsureBuilt();
            }

            if (_root == null)
            {
                BuildUnder(ResolveCanvas(), 1);
            }
        }

        private Canvas ResolveCanvas()
        {
            Canvas[] canvases = GetComponentsInChildren<Canvas>(true);
            for (int i = 0; i < canvases.Length; i++)
            {
                if (canvases[i].isRootCanvas && canvases[i].name == HudCanvasName)
                {
                    return canvases[i];
                }
            }

            return null;
        }

        private void Raise(bool visible)
        {
            Action<bool> handler = VisibilityChanged;
            if (handler == null)
            {
                return;
            }

            try
            {
                handler(visible);
            }
            catch (Exception ex)
            {
                Debug.LogException(ex, this);
            }
        }

        private void Log(string message)
        {
            if (logEvents)
            {
                Debug.Log("[Sonia] " + message, this);
            }
        }
    }
}
