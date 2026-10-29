// Away mode sign: it appears when the avatar has left the frame and is removed
// when she comes back.
//
// It lives inside the HUD Canvas (SoniaHUD, Screen Space - Camera over the HUD
// camera, without post-processing), so it shows in the 9:16 captures and in the
// build, and F1 does not hide it (it hangs from the Canvas, not from the debug
// group). It is built in code, with no prefabs or new assets: the rounded
// corners and the glow are textures generated at startup.
//
// Design for the vertical monitor (1080x1920 reference, readable from several
// meters): a navy card 900 px wide with a thin border and a glow in the accent
// blue, the spaced "SONNIA" label, the message in white bold at 80 px (about
// 2.5 cm letter height on a 43" monitor), three pulsing dots (back soon) and a
// discreet footer line. The logo is already at the top left of the HUD and is not
// repeated. It appears rising and fading in, floats very slowly while shown and
// leaves with another fade.

using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>"I stepped away, back soon" sign with fade-in and fade-out.</summary>
    [DisallowMultipleComponent]
    public class AwaySignController : MonoBehaviour
    {
        [Header("Setup")]
        [SerializeField]
        [Tooltip("Canvas that holds the sign. Empty: the HUD one (SoniaHUD) or, if there is none, its own.")]
        private Canvas hostCanvas;

        [Header("Text")]
        [SerializeField]
        [Tooltip("Small label above the message.")]
        private string eyebrow = "SONNIA";

        [SerializeField]
        [Tooltip("Discreet line under the message. Empty: not shown.")]
        private string footer = "Virtual assistant";

        [Header("Layout (pixels at the 1080x1920 reference)")]
        [SerializeField]
        [Tooltip("Width of the card.")]
        private float cardWidth = 900f;

        [SerializeField]
        [Range(0.2f, 0.8f)]
        [Tooltip("Height of the sign center, as a fraction of the screen from the bottom.")]
        private float verticalCenter = 0.53f;

        [SerializeField]
        [Tooltip("Message size. Long messages shrink down to the minimum.")]
        private float headlineSize = 80f;

        [SerializeField]
        [Tooltip("Minimum message size for very long texts.")]
        private float minHeadlineSize = 54f;

        [SerializeField]
        [Tooltip("Card background (navy, almost opaque).")]
        private Color cardColor = new Color(0.035f, 0.07f, 0.15f, 0.9f);

        [SerializeField]
        [Tooltip("Accent blue: border, glow, label and dots.")]
        private Color accentColor = new Color(0.44f, 0.66f, 1f, 1f);

        [SerializeField]
        [Tooltip("Message color.")]
        private Color textColor = Color.white;

        [SerializeField]
        [Tooltip("Color of the bottom line.")]
        private Color mutedColor = new Color(0.66f, 0.73f, 0.85f, 1f);

        [Header("Animation")]
        [SerializeField]
        [Range(0.05f, 3f)]
        [Tooltip("Seconds of the fade-in.")]
        private float fadeInSeconds = 0.7f;

        [SerializeField]
        [Range(0.05f, 3f)]
        [Tooltip("Seconds of the fade-out.")]
        private float fadeOutSeconds = 0.45f;

        [SerializeField]
        [Tooltip("Pixels it rises when appearing (and drops when leaving).")]
        private float riseDistance = 40f;

        [SerializeField]
        [Tooltip("Amplitude in pixels of the slow float while shown. 0 turns it off.")]
        private float floatAmplitude = 5f;

        [SerializeField]
        [Range(1f, 20f)]
        [Tooltip("Float period in seconds.")]
        private float floatPeriod = 6f;

        [SerializeField]
        [Range(0.4f, 4f)]
        [Tooltip("Pulse period in seconds of the three dots.")]
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

        /// <summary>True if the sign is shown or appearing.</summary>
        public bool IsShown
        {
            get { return _shown; }
        }

        /// <summary>Current text of the sign.</summary>
        public string MessageText
        {
            get { return _message; }
        }

        private void Start()
        {
            // Built right away (hidden) so appearing costs nothing.
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

        /// <summary>Shows the sign with a fade (or at once with <paramref name="instant"/>).</summary>
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

        /// <summary>Removes the sign with a fade (or at once with <paramref name="instant"/>).</summary>
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

        /// <summary>Changes the text, whether shown or not. Empty: the default one.</summary>
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
        // Animation
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

            // Smoothstep: continuous even if it changes direction midway.
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
        // Construction
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
                    Debug.LogWarning("[Sonnia] No Canvas for the away sign.", this);
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

            // Behind the subtitles and the rest of the HUD, in front of the logo.
            if (canvas.name == HudCanvasName && _root.transform.parent.childCount > 1)
            {
                _root.transform.SetSiblingIndex(1);
            }

            _group = _root.GetComponent<CanvasGroup>();
            _group.alpha = 0f;
            _group.interactable = false;
            _group.blocksRaycasts = false;

            // Soft glow in the accent blue, so the card stands out from the dark
            // backdrop.
            GameObject glow = MakeImage("Glow", _root.transform, _glowSprite, WithAlpha(accentColor, 0.22f));
            _glowRect = (RectTransform)glow.transform;
            Center(_glowRect);

            // Card: the border is the image itself and the fill is an inset child.
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

        /// <summary>Recomputes the card height and fits the glow to its size.</summary>
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

            // Without a HUD: own Canvas, on the HUD camera if it exists so it shows
            // in captures and without post-processing.
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
        // Generated textures
        // ------------------------------------------------------------------

        private void CreateSprites()
        {
            if (_roundSprite != null)
            {
                return;
            }

            // Rounded rectangle, to 9-slice (card, border, bar).
            const int roundSize = 128;
            _roundTexture = MakeTexture("SoniaSignRound", roundSize, (x, y) =>
                Mathf.Clamp01(0.5f - RoundedRectDistance(x, y, roundSize, roundSize, 0f, CornerRadius)));
            float roundBorder = CornerRadius + 2f;
            _roundSprite = Sprite.Create(
                _roundTexture, new Rect(0f, 0f, roundSize, roundSize), new Vector2(0.5f, 0.5f), 100f, 0,
                SpriteMeshType.FullRect, new Vector4(roundBorder, roundBorder, roundBorder, roundBorder));

            // Glow: the same rectangle with a very soft 75 px edge.
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

            // Circle for the dots.
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
        /// Signed distance (in pixels, negative inside) from the center of a
        /// pixel to the edge of a rounded rectangle inscribed with a margin.
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
