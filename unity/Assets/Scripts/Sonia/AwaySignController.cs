// Letrero del modo "Fuera": aparece cuando Sonia ha salido de cuadro y se
// retira cuando vuelve.
//
// Va dentro del Canvas del HUD (SoniaHUD, Screen Space - Camera sobre la cámara
// del HUD, sin postprocesado), así que sale en las capturas 9:16 y en la build,
// y no lo esconde F1 (cuelga del Canvas, no del grupo de depuración). Se
// construye por código, sin prefabs ni assets nuevos: las esquinas redondeadas y
// el halo son texturas generadas al arrancar.
//
// Diseño para el monitor vertical (1080x1920 de referencia, legible a varios
// metros): una tarjeta navy de 900 px con borde fino y halo en el azul de la
// marca, la etiqueta "SONIA" espaciada, el mensaje en blanco y en negrita a 80
// px (unos 2,5 cm de altura de letra en un monitor de 43"), tres puntos que
// laten (vuelve enseguida) y una línea discreta con Sonnet Code. El logo ya está
// arriba a la izquierda del HUD y no se repite. Aparece subiendo y fundiéndose,
// flota muy despacio mientras está y se va con otro fundido.

using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Letrero de "me fui, vuelvo enseguida" con fundidos de entrada y salida.</summary>
    [DisallowMultipleComponent]
    public class AwaySignController : MonoBehaviour
    {
        [Header("Montaje")]
        [SerializeField]
        [Tooltip("Canvas donde va el letrero. Vacío: el del HUD (SoniaHUD) o, si no hay, uno propio.")]
        private Canvas hostCanvas;

        [Header("Texto")]
        [SerializeField]
        [Tooltip("Etiqueta pequeña sobre el mensaje.")]
        private string eyebrow = "SONIA";

        [SerializeField]
        [Tooltip("Línea discreta bajo el mensaje. Vacía: no se muestra.")]
        private string footer = "Asistente virtual de Sonnet Code";

        [Header("Diseño (píxeles de la referencia 1080x1920)")]
        [SerializeField]
        [Tooltip("Ancho de la tarjeta.")]
        private float cardWidth = 900f;

        [SerializeField]
        [Range(0.2f, 0.8f)]
        [Tooltip("Altura del centro del letrero, en fracción de la pantalla desde abajo.")]
        private float verticalCenter = 0.53f;

        [SerializeField]
        [Tooltip("Tamaño del mensaje. Los mensajes largos bajan hasta el mínimo.")]
        private float headlineSize = 80f;

        [SerializeField]
        [Tooltip("Tamaño mínimo del mensaje para textos muy largos.")]
        private float minHeadlineSize = 54f;

        [SerializeField]
        [Tooltip("Fondo de la tarjeta (navy de la marca, casi opaco).")]
        private Color cardColor = new Color(0.035f, 0.07f, 0.15f, 0.9f);

        [SerializeField]
        [Tooltip("Azul de la marca: borde, halo, etiqueta y puntos.")]
        private Color accentColor = new Color(0.44f, 0.66f, 1f, 1f);

        [SerializeField]
        [Tooltip("Color del mensaje.")]
        private Color textColor = Color.white;

        [SerializeField]
        [Tooltip("Color de la línea inferior.")]
        private Color mutedColor = new Color(0.66f, 0.73f, 0.85f, 1f);

        [Header("Animación")]
        [SerializeField]
        [Range(0.05f, 3f)]
        [Tooltip("Segundos del fundido de entrada.")]
        private float fadeInSeconds = 0.7f;

        [SerializeField]
        [Range(0.05f, 3f)]
        [Tooltip("Segundos del fundido de salida.")]
        private float fadeOutSeconds = 0.45f;

        [SerializeField]
        [Tooltip("Píxeles que sube al aparecer (y baja al irse).")]
        private float riseDistance = 40f;

        [SerializeField]
        [Tooltip("Amplitud en píxeles de la flotación lenta mientras está puesto. 0 la apaga.")]
        private float floatAmplitude = 5f;

        [SerializeField]
        [Range(1f, 20f)]
        [Tooltip("Periodo en segundos de la flotación.")]
        private float floatPeriod = 6f;

        [SerializeField]
        [Range(0.4f, 4f)]
        [Tooltip("Periodo en segundos del latido de los tres puntos.")]
        private float dotsPeriod = 1.4f;

        private const string HudCanvasName = "SoniaHUD";
        private const int CornerRadius = 40;

        private GameObject _root;
        private RectTransform _rootRect;
        private CanvasGroup _group;
        private RectTransform _cardRect;
        private RectTransform _glowRect;
        private TextMeshProUGUI _headline;
        private Image[] _dots = new Image[0];
        private string _message = PresenceController.DefaultAwayMessage;
        private bool _shown;
        private float _progress;
        private float _clock;
        private bool _warnedNoCanvas;

        private Texture2D _roundTexture;
        private Texture2D _glowTexture;
        private Texture2D _dotTexture;
        private Sprite _roundSprite;
        private Sprite _glowSprite;
        private Sprite _dotSprite;

        /// <summary>Cierto si el letrero está puesto o apareciendo.</summary>
        public bool IsShown
        {
            get { return _shown; }
        }

        /// <summary>Texto actual del letrero.</summary>
        public string MessageText
        {
            get { return _message; }
        }

        private void Start()
        {
            // Se construye ya (oculto) para que aparecer no cueste nada.
            Build();
        }

        private void OnDestroy()
        {
            DestroyAsset(_roundSprite);
            DestroyAsset(_glowSprite);
            DestroyAsset(_dotSprite);
            DestroyAsset(_roundTexture);
            DestroyAsset(_glowTexture);
            DestroyAsset(_dotTexture);
        }

        // ------------------------------------------------------------------
        // API
        // ------------------------------------------------------------------

        /// <summary>Pone el letrero con un fundido (o de golpe con <paramref name="instant"/>).</summary>
        public void Show(string message, bool instant)
        {
            Build();
            SetMessage(message);
            _shown = true;
            if (_root != null)
            {
                _root.SetActive(true);
            }

            if (instant)
            {
                _progress = 1f;
                ApplyAnimation(0f);
            }
        }

        /// <summary>Retira el letrero con un fundido (o de golpe con <paramref name="instant"/>).</summary>
        public void Hide(bool instant)
        {
            _shown = false;
            if (instant)
            {
                _progress = 0f;
                if (_root != null)
                {
                    ApplyAnimation(0f);
                    _root.SetActive(false);
                }
            }
        }

        /// <summary>Cambia el texto, esté o no puesto. Vacío: el de por defecto.</summary>
        public void SetMessage(string message)
        {
            _message = string.IsNullOrWhiteSpace(message) ? PresenceController.DefaultAwayMessage : message.Trim();
            if (_headline == null)
            {
                return;
            }

            _headline.text = _message;
            _headline.fontSize = HeadlineSizeFor(_message);
            RefreshLayout();
        }

        // ------------------------------------------------------------------
        // Animación
        // ------------------------------------------------------------------

        private void Update()
        {
            if (_root == null || (!_shown && _progress <= 0f))
            {
                return;
            }

            float dt = Time.deltaTime;
            _clock += dt;
            float rate = _shown ? 1f / Mathf.Max(0.05f, fadeInSeconds) : 1f / Mathf.Max(0.05f, fadeOutSeconds);
            _progress = Mathf.MoveTowards(_progress, _shown ? 1f : 0f, rate * dt);
            ApplyAnimation(_clock);

            if (!_shown && _progress <= 0f)
            {
                _root.SetActive(false);
            }
        }

        private void ApplyAnimation(float clock)
        {
            if (_group == null)
            {
                return;
            }

            // Smoothstep: continua aunque cambie de sentido a medias.
            float eased = _progress * _progress * (3f - (2f * _progress));
            _group.alpha = eased;

            float floating = floatAmplitude > 0f
                ? Mathf.Sin(clock * (2f * Mathf.PI / Mathf.Max(1f, floatPeriod))) * floatAmplitude * eased
                : 0f;
            _rootRect.anchoredPosition = new Vector2(0f, (-(1f - eased) * riseDistance) + floating);
            float scale = Mathf.Lerp(0.96f, 1f, eased);
            _rootRect.localScale = new Vector3(scale, scale, 1f);

            for (int i = 0; i < _dots.Length; i++)
            {
                if (_dots[i] == null)
                {
                    continue;
                }

                float phase = (clock / Mathf.Max(0.4f, dotsPeriod)) - (i * 0.18f);
                float pulse = 0.5f + (0.5f * Mathf.Cos(phase * 2f * Mathf.PI));
                Color color = accentColor;
                color.a = Mathf.Lerp(0.25f, 1f, pulse);
                _dots[i].color = color;
                float dotScale = Mathf.Lerp(0.8f, 1f, pulse);
                _dots[i].rectTransform.localScale = new Vector3(dotScale, dotScale, 1f);
            }
        }

        private float HeadlineSizeFor(string message)
        {
            int length = message != null ? message.Length : 0;
            float t = Mathf.InverseLerp(70f, 180f, length);
            return Mathf.Round(Mathf.Lerp(headlineSize, Mathf.Min(headlineSize, minHeadlineSize), t));
        }

        // ------------------------------------------------------------------
        // Construcción
        // ------------------------------------------------------------------

        private void Build()
        {
            if (_root != null)
            {
                return;
            }

            Canvas canvas = ResolveCanvas();
            if (canvas == null)
            {
                if (!_warnedNoCanvas)
                {
                    _warnedNoCanvas = true;
                    Debug.LogWarning("[Sonia] No hay Canvas para el letrero del modo Fuera.", this);
                }

                return;
            }

            CreateSprites();
            int layer = canvas.gameObject.layer;
            TMP_FontAsset font = FindFont(canvas);

            _root = new GameObject("AwaySign", typeof(RectTransform), typeof(CanvasGroup));
            _root.layer = layer;
            _root.transform.SetParent(canvas.transform, false);
            _rootRect = (RectTransform)_root.transform;
            _rootRect.anchorMin = new Vector2(0.5f, verticalCenter);
            _rootRect.anchorMax = new Vector2(0.5f, verticalCenter);
            _rootRect.pivot = new Vector2(0.5f, 0.5f);
            _rootRect.sizeDelta = new Vector2(cardWidth, 0f);

            // Detrás de los subtítulos y del resto del HUD, delante del logo.
            if (canvas.name == HudCanvasName && _root.transform.parent.childCount > 1)
            {
                _root.transform.SetSiblingIndex(1);
            }

            _group = _root.GetComponent<CanvasGroup>();
            _group.alpha = 0f;
            _group.interactable = false;
            _group.blocksRaycasts = false;

            // Halo suave en el azul de la marca, para que la tarjeta se despegue
            // del telón oscuro.
            GameObject glow = MakeImage("Glow", _root.transform, _glowSprite, WithAlpha(accentColor, 0.22f));
            _glowRect = (RectTransform)glow.transform;
            Center(_glowRect);

            // Tarjeta: el borde es la propia imagen y el relleno, un hijo inset.
            GameObject card = MakeImage("Card", _root.transform, _roundSprite, WithAlpha(accentColor, 0.5f));
            _cardRect = (RectTransform)card.transform;
            Center(_cardRect);
            _cardRect.sizeDelta = new Vector2(cardWidth, 0f);
            VerticalLayoutGroup layout = card.AddComponent<VerticalLayoutGroup>();
            layout.padding = new RectOffset(72, 72, 58, 54);
            layout.spacing = 22f;
            layout.childAlignment = TextAnchor.UpperCenter;
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = false;
            layout.childForceExpandHeight = false;
            ContentSizeFitter fitter = card.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            GameObject fill = MakeImage("Fill", card.transform, _roundSprite, cardColor);
            fill.AddComponent<LayoutElement>().ignoreLayout = true;
            RectTransform fillRect = (RectTransform)fill.transform;
            fillRect.anchorMin = Vector2.zero;
            fillRect.anchorMax = Vector2.one;
            fillRect.offsetMin = new Vector2(3f, 3f);
            fillRect.offsetMax = new Vector2(-3f, -3f);

            GameObject accent = MakeImage("Accent", card.transform, _roundSprite, accentColor);
            accent.GetComponent<Image>().pixelsPerUnitMultiplier = CornerRadius / 4f;
            LayoutElement accentLayout = accent.AddComponent<LayoutElement>();
            accentLayout.preferredWidth = 96f;
            accentLayout.preferredHeight = 8f;

            TextMeshProUGUI eyebrowText = MakeText("Eyebrow", card.transform, font, eyebrow, 30f, accentColor);
            eyebrowText.fontStyle = FontStyles.Bold;
            eyebrowText.characterSpacing = 14f;

            _headline = MakeText("Message", card.transform, font, _message, HeadlineSizeFor(_message), textColor);
            _headline.fontStyle = FontStyles.Bold;
            _headline.lineSpacing = -8f;

            GameObject dots = new GameObject("Dots", typeof(RectTransform));
            dots.layer = layer;
            dots.transform.SetParent(card.transform, false);
            HorizontalLayoutGroup row = dots.AddComponent<HorizontalLayoutGroup>();
            row.spacing = 18f;
            row.childAlignment = TextAnchor.MiddleCenter;
            row.childControlWidth = true;
            row.childControlHeight = true;
            row.childForceExpandWidth = false;
            row.childForceExpandHeight = false;
            LayoutElement dotsLayout = dots.AddComponent<LayoutElement>();
            dotsLayout.preferredHeight = 18f;
            dotsLayout.preferredWidth = 3f * 16f + 2f * 18f;
            _dots = new Image[3];
            for (int i = 0; i < _dots.Length; i++)
            {
                GameObject dot = MakeImage("Dot" + i, dots.transform, _dotSprite, accentColor);
                LayoutElement dotLayout = dot.AddComponent<LayoutElement>();
                dotLayout.preferredWidth = 16f;
                dotLayout.preferredHeight = 16f;
                _dots[i] = dot.GetComponent<Image>();
            }

            if (!string.IsNullOrEmpty(footer))
            {
                MakeText("Footer", card.transform, font, footer, 28f, mutedColor);
            }

            RefreshLayout();
            _progress = 0f;
            ApplyAnimation(0f);
            _root.SetActive(_shown);
        }

        /// <summary>Recalcula el alto de la tarjeta y ajusta el halo a su tamaño.</summary>
        private void RefreshLayout()
        {
            if (_cardRect == null)
            {
                return;
            }

            bool wasActive = _root.activeSelf;
            if (!wasActive)
            {
                _root.SetActive(true);
            }

            LayoutRebuilder.ForceRebuildLayoutImmediate(_cardRect);
            Vector2 size = _cardRect.rect.size;
            _rootRect.sizeDelta = size;
            if (_glowRect != null)
            {
                _glowRect.sizeDelta = size + new Vector2(150f, 150f);
            }

            if (!wasActive)
            {
                _root.SetActive(false);
            }
        }

        private Canvas ResolveCanvas()
        {
            if (hostCanvas != null)
            {
                return hostCanvas;
            }

            Canvas[] canvases = GetComponentsInChildren<Canvas>(true);
            for (int i = 0; i < canvases.Length; i++)
            {
                if (canvases[i].isRootCanvas && canvases[i].name == HudCanvasName)
                {
                    hostCanvas = canvases[i];
                    return hostCanvas;
                }
            }

            for (int i = 0; i < canvases.Length; i++)
            {
                if (canvases[i].isRootCanvas && canvases[i].renderMode == RenderMode.ScreenSpaceCamera)
                {
                    hostCanvas = canvases[i];
                    return hostCanvas;
                }
            }

            // Sin HUD: Canvas propio, en la cámara del HUD si existe para que salga
            // en las capturas y sin postprocesado.
            GameObject go = SoniaUiKit.MakeOverlayCanvas(transform, "SoniaAwaySign", 90);
            Canvas canvas = go.GetComponent<Canvas>();
            Camera main = Camera.main;
            if (main != null)
            {
                Transform hud = main.transform.Find("HudCamera");
                Camera hudCamera = hud != null ? hud.GetComponent<Camera>() : null;
                canvas.renderMode = RenderMode.ScreenSpaceCamera;
                canvas.worldCamera = hudCamera != null ? hudCamera : main;
                canvas.planeDistance = 0.3f;
                int uiLayer = LayerMask.NameToLayer("UI");
                if (hudCamera != null && uiLayer >= 0)
                {
                    go.layer = uiLayer;
                }
            }

            hostCanvas = canvas;
            return hostCanvas;
        }

        private static TMP_FontAsset FindFont(Canvas canvas)
        {
            TMP_Text[] texts = canvas.GetComponentsInChildren<TMP_Text>(true);
            for (int i = 0; i < texts.Length; i++)
            {
                if (texts[i].font != null)
                {
                    return texts[i].font;
                }
            }

            return TMP_Settings.defaultFontAsset;
        }

        private GameObject MakeImage(string name, Transform parent, Sprite sprite, Color color)
        {
            GameObject go = new GameObject(name, typeof(RectTransform));
            go.layer = parent.gameObject.layer;
            go.transform.SetParent(parent, false);
            Image image = go.AddComponent<Image>();
            image.sprite = sprite;
            image.type = sprite != null && sprite.border.sqrMagnitude > 0f ? Image.Type.Sliced : Image.Type.Simple;
            image.color = color;
            image.raycastTarget = false;
            return go;
        }

        private static TextMeshProUGUI MakeText(
            string name, Transform parent, TMP_FontAsset font, string content, float size, Color color)
        {
            GameObject go = new GameObject(name, typeof(RectTransform));
            go.layer = parent.gameObject.layer;
            go.transform.SetParent(parent, false);
            TextMeshProUGUI text = go.AddComponent<TextMeshProUGUI>();
            if (font != null)
            {
                text.font = font;
            }

            text.text = content;
            text.fontSize = size;
            text.color = color;
            text.alignment = TextAlignmentOptions.Center;
            text.textWrappingMode = TextWrappingModes.Normal;
            text.raycastTarget = false;
            return text;
        }

        private static void Center(RectTransform rect)
        {
            rect.anchorMin = new Vector2(0.5f, 0.5f);
            rect.anchorMax = new Vector2(0.5f, 0.5f);
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = Vector2.zero;
        }

        private static Color WithAlpha(Color color, float alpha)
        {
            color.a = alpha;
            return color;
        }

        // ------------------------------------------------------------------
        // Texturas generadas
        // ------------------------------------------------------------------

        private void CreateSprites()
        {
            if (_roundSprite != null)
            {
                return;
            }

            // Rectángulo redondeado, para cortar en nueve (tarjeta, borde, barra).
            const int roundSize = 128;
            _roundTexture = MakeTexture("SoniaSignRound", roundSize, (x, y) =>
                Mathf.Clamp01(0.5f - RoundedRectDistance(x, y, roundSize, roundSize, 0f, CornerRadius)));
            float roundBorder = CornerRadius + 2f;
            _roundSprite = Sprite.Create(
                _roundTexture, new Rect(0f, 0f, roundSize, roundSize), new Vector2(0.5f, 0.5f), 100f, 0,
                SpriteMeshType.FullRect, new Vector4(roundBorder, roundBorder, roundBorder, roundBorder));

            // Halo: el mismo rectángulo con un borde muy difuso de 75 px.
            const int glowSize = 256;
            const float glowSpread = 75f;
            _glowTexture = MakeTexture("SoniaSignGlow", glowSize, (x, y) =>
            {
                float d = RoundedRectDistance(x, y, glowSize, glowSize, glowSpread, CornerRadius);
                float t = Mathf.Clamp01(1f - (d / glowSpread));
                return t * t * (3f - (2f * t));
            });
            float glowBorder = glowSpread + CornerRadius + 2f;
            _glowSprite = Sprite.Create(
                _glowTexture, new Rect(0f, 0f, glowSize, glowSize), new Vector2(0.5f, 0.5f), 100f, 0,
                SpriteMeshType.FullRect, new Vector4(glowBorder, glowBorder, glowBorder, glowBorder));

            // Círculo para los puntos.
            const int dotSize = 64;
            _dotTexture = MakeTexture("SoniaSignDot", dotSize, (x, y) =>
            {
                float dx = x - (dotSize * 0.5f);
                float dy = y - (dotSize * 0.5f);
                return Mathf.Clamp01((dotSize * 0.5f) - 1f - Mathf.Sqrt((dx * dx) + (dy * dy)) + 0.5f);
            });
            _dotSprite = Sprite.Create(
                _dotTexture, new Rect(0f, 0f, dotSize, dotSize), new Vector2(0.5f, 0.5f), 100f);
        }

        /// <summary>
        /// Distancia con signo (en píxeles, negativa dentro) del centro de un
        /// píxel al borde de un rectángulo redondeado inscrito con un margen.
        /// </summary>
        private static float RoundedRectDistance(int x, int y, int width, int height, float inset, float radius)
        {
            float px = x + 0.5f - (width * 0.5f);
            float py = y + 0.5f - (height * 0.5f);
            float halfW = (width * 0.5f) - inset;
            float halfH = (height * 0.5f) - inset;
            float qx = Mathf.Abs(px) - (halfW - radius);
            float qy = Mathf.Abs(py) - (halfH - radius);
            float outside = new Vector2(Mathf.Max(qx, 0f), Mathf.Max(qy, 0f)).magnitude;
            float inside = Mathf.Min(Mathf.Max(qx, qy), 0f);
            return outside + inside - radius;
        }

        private static Texture2D MakeTexture(string name, int size, System.Func<int, int, float> alpha)
        {
            Texture2D texture = new Texture2D(size, size, TextureFormat.RGBA32, false);
            texture.name = name;
            texture.wrapMode = TextureWrapMode.Clamp;
            texture.filterMode = FilterMode.Bilinear;
            Color32[] pixels = new Color32[size * size];
            for (int y = 0; y < size; y++)
            {
                for (int x = 0; x < size; x++)
                {
                    byte a = (byte)Mathf.RoundToInt(Mathf.Clamp01(alpha(x, y)) * 255f);
                    pixels[(y * size) + x] = new Color32(255, 255, 255, a);
                }
            }

            texture.SetPixels32(pixels);
            texture.Apply(false, true);
            return texture;
        }

        private static void DestroyAsset(Object asset)
        {
            if (asset != null)
            {
                Destroy(asset);
            }
        }
    }
}
