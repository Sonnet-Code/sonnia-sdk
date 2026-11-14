// Card of a talk of the agenda (show_talk), drawn on the HUD where images go.
//
// The orchestrator picks the talk and writes every text in its language; this card only
// lays them out: a badge (on now, up next, later, already over, from the screen texts),
// the title, the speakers, the day and times, the room and track and a few tags. It shares
// the top strip with the image panel: SoniaBootstrap hides one when the other shows, and
// hide_image removes both.
//
// Built from code inside the HUD Canvas (SoniaHUD), like the trivia card, with the stage
// fonts when the stage screen has them.

using System.Collections.Generic;
using System.Text;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Shows and hides the card of a <c>show_talk</c> message.</summary>
    [DisallowMultipleComponent]
    public class TalkCardController : MonoBehaviour
    {
        [SerializeField]
        [Tooltip("Card width in reference pixels (the HUD is 1080 wide).")]
        private float cardWidth = 940f;

        [SerializeField]
        [Range(0f, 0.4f)]
        [Tooltip("Distance from the top of the screen to the card, as a fraction of the height.")]
        private float cardTop = 0.105f;

        [SerializeField]
        [Tooltip("Seconds of the show and hide animation.")]
        private float animationSeconds = 0.3f;

        [SerializeField]
        [Tooltip("Ask the camera to pull back while the card is up, as with an image.")]
        private bool requestPanelShot = true;

        [SerializeField]
        [Tooltip("Extra camera offset over the panel shot (meters) for the tallest card, so the avatar fits under it. A shorter card gets a part of it.")]
        private Vector3 panelShotExtra = new Vector3(0f, 0.3f, -0.8f);

        [SerializeField]
        [Tooltip("Card heights, as a fraction of the screen, that get none and all of the extra offset.")]
        private Vector2 extraForHeight = new Vector2(0.12f, 0.28f);

        private const string HudCanvasName = "SoniaHUD";
        private const int CornerRadius = 40;
        private const int MaxTags = 4;

        /// <summary>Longest title written whole; a longer one is cut with an ellipsis (three lines at the smallest size).</summary>
        private const int MaxTitleLength = 110;

        private static readonly Color CardFill = new Color(0.035f, 0.07f, 0.15f, 0.94f);
        private static readonly Color TitleColor = Color.white;
        private static readonly Color SpeakerColor = new Color(0.62f, 0.78f, 1f, 1f);
        private static readonly Color Muted = new Color(0.68f, 0.75f, 0.88f, 1f);
        private static readonly Color NowColor = new Color(0.204f, 0.659f, 0.325f);
        private static readonly Color NextColor = new Color(0.259f, 0.522f, 0.957f);
        private static readonly Color LaterColor = new Color(0.36f, 0.42f, 0.58f);
        private static readonly Color OverColor = new Color(0.4f, 0.4f, 0.45f);

        private Canvas _canvas;
        private RectTransform _card;
        private CanvasGroup _group;
        private Image _border;
        private Image _badge;
        private TextMeshProUGUI _badgeText;
        private TextMeshProUGUI _title;
        private TextMeshProUGUI _speakers;
        private TextMeshProUGUI _when;
        private TextMeshProUGUI _place;
        private TextMeshProUGUI _tags;
        private GameObject _divider;
        private Sprite _round;
        private Texture2D _roundTexture;
        private bool _warnedNoCanvas;

        private ShowTalkMessage _current;
        private bool _visible;
        private float _fade;
        private float _shownAt;
        private CameraFramingController _framing;
        private readonly StringBuilder _builder = new StringBuilder(128);

        /// <summary>True while a card is on screen (or coming in).</summary>
        public bool IsVisible
        {
            get { return _visible; }
        }

        /// <summary>Id of the talk on the card, for debugging.</summary>
        public string CurrentTalkId
        {
            get { return _current != null ? _current.TalkId : null; }
        }

        /// <summary>Where the avatar can look while the card is up.</summary>
        public Transform Anchor
        {
            get { return _card != null ? _card : transform; }
        }

        private void Awake()
        {
            _framing = GetComponentInChildren<CameraFramingController>(true);
            ScreenTexts.Changed += ApplyScreenTexts;
        }

        private void OnDestroy()
        {
            ScreenTexts.Changed -= ApplyScreenTexts;
            if (_round != null)
            {
                Destroy(_round);
            }

            if (_roundTexture != null)
            {
                Destroy(_roundTexture);
            }
        }

        // ------------------------------------------------------------------
        // Public API
        // ------------------------------------------------------------------

        /// <summary>Shows (or replaces) the card.</summary>
        public void Show(ShowTalkMessage message)
        {
            if (message == null || string.IsNullOrEmpty(message.Title))
            {
                return;
            }

            Build();
            if (_card == null)
            {
                return;
            }

            _current = message;
            // Active before filling: the layout of an inactive card measures nothing, and its
            // height decides how far back the camera goes.
            _card.gameObject.SetActive(true);
            Fill(message);
            if (!_visible)
            {
                _fade = 0f;
            }

            _visible = true;
            _shownAt = Time.time;
            if (requestPanelShot && _framing != null)
            {
                // A taller card needs the camera further back for Sonnia to fit below it.
                float height = _card.rect.height / ReferenceHeight();
                float share = Mathf.InverseLerp(extraForHeight.x, extraForHeight.y, height);
                _framing.PanelRequestOffset = panelShotExtra * share;
                _framing.PanelRequested = true;
            }

            Animate();
        }

        /// <summary>Removes the card with its exit animation.</summary>
        public void Hide()
        {
            if (!_visible)
            {
                return;
            }

            _visible = false;
            if (requestPanelShot && _framing != null)
            {
                _framing.PanelRequested = false;
            }
        }

        /// <summary>Removes the card at once.</summary>
        public void HideImmediate()
        {
            Hide();
            _fade = 0f;
            if (_card != null)
            {
                Animate();
                _card.gameObject.SetActive(false);
            }
        }

        // ------------------------------------------------------------------
        // Frame
        // ------------------------------------------------------------------

        private void Update()
        {
            if (_card == null || !_card.gameObject.activeSelf)
            {
                return;
            }

            float step = animationSeconds > 0.001f ? Time.deltaTime / animationSeconds : 1f;
            _fade = Mathf.MoveTowards(_fade, _visible ? 1f : 0f, step);
            Animate();
            if (!_visible && _fade <= 0f)
            {
                _card.gameObject.SetActive(false);
                _current = null;
            }
        }

        private void Animate()
        {
            float eased = _fade * _fade * (3f - (2f * _fade));
            _group.alpha = eased;
            float scale = Mathf.Lerp(0.94f, 1f, eased);
            _card.localScale = new Vector3(scale, scale, 1f);
            _card.anchoredPosition = new Vector2(0f, Mathf.Lerp(40f, 0f, eased));

            // On now: the badge breathes.
            if (_current != null && _current.Status == "now" && _badge != null)
            {
                float pulse = 0.5f + (0.5f * Mathf.Sin((Time.time - _shownAt) * 4f));
                _badge.color = Color.Lerp(NowColor, Color.Lerp(NowColor, Color.white, 0.35f), pulse);
            }
        }

        // ------------------------------------------------------------------
        // Content
        // ------------------------------------------------------------------

        private float ReferenceHeight()
        {
            CanvasScaler scaler = _canvas != null ? _canvas.GetComponent<CanvasScaler>() : null;
            if (scaler != null && scaler.uiScaleMode == CanvasScaler.ScaleMode.ScaleWithScreenSize)
            {
                return Mathf.Max(1f, scaler.referenceResolution.y);
            }

            RectTransform canvasRect = _canvas != null ? (RectTransform)_canvas.transform : null;
            return canvasRect != null ? Mathf.Max(1f, canvasRect.rect.height) : 1920f;
        }

        private void ApplyScreenTexts()
        {
            if (_current != null && _badgeText != null)
            {
                _badgeText.text = BadgeText(_current.Status);
            }
        }

        private void Fill(ShowTalkMessage message)
        {
            Color accent = AccentFor(message.Status);
            _badge.color = accent;
            _badgeText.text = BadgeText(message.Status);
            _border.color = WithAlpha(Color.Lerp(accent, Color.white, 0.25f), 0.6f);

            string title = message.Title.Trim();
            if (title.Length > MaxTitleLength)
            {
                title = title.Substring(0, MaxTitleLength - 1).TrimEnd() + "…";
            }

            // Shorter titles bigger; a long one smaller, so it stays within three lines.
            _title.fontSize = title.Length <= 36 ? 54f : title.Length <= 64 ? 46f : 40f;
            _title.text = title;
            SetLine(_speakers, Joined(message.Speakers, ", "));
            SetLine(_when, message.When);
            SetLine(_place, message.Place);
            SetLine(_tags, TagLine(message.Tags));
            _divider.SetActive(_when.gameObject.activeSelf || _place.gameObject.activeSelf);

            LayoutRebuilder.ForceRebuildLayoutImmediate(_card);
        }

        private static string BadgeText(string status)
        {
            switch (status)
            {
                case "now":
                    return ScreenTexts.Get(ScreenTexts.TalkNow);
                case "next":
                    return ScreenTexts.Get(ScreenTexts.TalkNext);
                case "over":
                    return ScreenTexts.Get(ScreenTexts.TalkOver);
                default:
                    return ScreenTexts.Get(ScreenTexts.TalkLabel);
            }
        }

        private static Color AccentFor(string status)
        {
            switch (status)
            {
                case "now":
                    return NowColor;
                case "next":
                    return NextColor;
                case "over":
                    return OverColor;
                default:
                    return LaterColor;
            }
        }

        private static void SetLine(TMP_Text text, string value)
        {
            bool has = !string.IsNullOrEmpty(value);
            text.text = has ? value : string.Empty;
            text.gameObject.SetActive(has);
        }

        private string Joined(List<string> items, string separator)
        {
            _builder.Length = 0;
            if (items == null)
            {
                return string.Empty;
            }

            for (int i = 0; i < items.Count; i++)
            {
                if (string.IsNullOrEmpty(items[i]))
                {
                    continue;
                }

                if (_builder.Length > 0)
                {
                    _builder.Append(separator);
                }

                _builder.Append(items[i]);
            }

            return _builder.ToString();
        }

        private string TagLine(List<string> tags)
        {
            _builder.Length = 0;
            if (tags == null)
            {
                return string.Empty;
            }

            int count = 0;
            for (int i = 0; i < tags.Count && count < MaxTags; i++)
            {
                string tag = tags[i] != null ? tags[i].Trim().TrimStart('#') : string.Empty;
                if (tag.Length == 0)
                {
                    continue;
                }

                if (_builder.Length > 0)
                {
                    _builder.Append("   ");
                }

                _builder.Append('#').Append(tag);
                count++;
            }

            return _builder.ToString();
        }

        // ------------------------------------------------------------------
        // Construction
        // ------------------------------------------------------------------

        private void Build()
        {
            if (_card != null)
            {
                return;
            }

            _canvas = ResolveCanvas();
            if (_canvas == null)
            {
                if (!_warnedNoCanvas)
                {
                    _warnedNoCanvas = true;
                    Debug.LogWarning("[Sonnia] No HUD Canvas for the talk card.", this);
                }

                return;
            }

            StageScreen stage = GetComponentInChildren<StageScreen>(true);
            TMP_FontAsset fallback = FindFont(_canvas);
            TMP_FontAsset display = stage != null && stage.DisplayFont != null ? stage.DisplayFont : fallback;
            TMP_FontAsset reading = stage != null && stage.SemiboldFont != null ? stage.SemiboldFont : fallback;
            TMP_FontAsset label = stage != null && stage.MonoFont != null ? stage.MonoFont : reading;
            CreateSprite();

            GameObject cardRoot = new GameObject("TalkCard", typeof(RectTransform), typeof(CanvasGroup));
            cardRoot.layer = _canvas.gameObject.layer;
            cardRoot.transform.SetParent(_canvas.transform, false);
            _card = (RectTransform)cardRoot.transform;
            _card.anchorMin = new Vector2(0.5f, 1f - cardTop);
            _card.anchorMax = _card.anchorMin;
            _card.pivot = new Vector2(0.5f, 1f);
            _card.sizeDelta = new Vector2(cardWidth, 0f);
            _group = cardRoot.GetComponent<CanvasGroup>();
            _group.alpha = 0f;
            _group.interactable = false;
            _group.blocksRaycasts = false;
            // Behind the subtitles and the rest of the HUD, in front of the logo (like the trivia).
            if (_canvas.name == HudCanvasName && _card.parent.childCount > 1)
            {
                _card.SetSiblingIndex(1);
            }

            VerticalLayoutGroup layout = cardRoot.AddComponent<VerticalLayoutGroup>();
            layout.padding = new RectOffset(48, 48, 32, 36);
            layout.spacing = 10f;
            layout.childAlignment = TextAnchor.UpperLeft;
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = false;
            ContentSizeFitter fitter = cardRoot.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            _border = MakeImage("Border", _card, Color.white);
            IgnoreLayout(_border.gameObject);
            Image fill = MakeImage("Fill", _card, CardFill);
            IgnoreLayout(fill.gameObject);
            RectTransform fillRect = (RectTransform)fill.transform;
            fillRect.offsetMin = new Vector2(4f, 4f);
            fillRect.offsetMax = new Vector2(-4f, -4f);

            // Badge: a pill sized to its text, on the left.
            GameObject row = new GameObject("BadgeRow", typeof(RectTransform));
            row.layer = cardRoot.layer;
            row.transform.SetParent(_card, false);
            HorizontalLayoutGroup rowLayout = row.AddComponent<HorizontalLayoutGroup>();
            rowLayout.childAlignment = TextAnchor.MiddleLeft;
            rowLayout.childControlWidth = true;
            rowLayout.childControlHeight = true;
            rowLayout.childForceExpandWidth = false;
            rowLayout.childForceExpandHeight = false;

            _badge = MakeImage("Badge", row.transform, NextColor);
            HorizontalLayoutGroup pill = _badge.gameObject.AddComponent<HorizontalLayoutGroup>();
            pill.padding = new RectOffset(22, 22, 6, 6);
            pill.childControlWidth = true;
            pill.childControlHeight = true;
            pill.childForceExpandWidth = false;
            pill.childForceExpandHeight = false;
            _badgeText = MakeText("Label", _badge.transform, label, 26f, Color.white, FontStyles.Bold);
            _badgeText.characterSpacing = 6f;
            _badgeText.textWrappingMode = TextWrappingModes.NoWrap;

            _title = MakeText("Title", _card, display, 54f, TitleColor, FontStyles.Normal);
            _title.lineSpacing = -8f;
            AddSpace(_title.gameObject, 2f);

            _speakers = MakeText("Speakers", _card, reading, 36f, SpeakerColor, FontStyles.Normal);

            Image divider = MakeImage("Divider", _card, WithAlpha(Color.white, 0.14f));
            divider.sprite = null;
            divider.type = Image.Type.Simple;
            LayoutElement dividerSize = divider.gameObject.AddComponent<LayoutElement>();
            dividerSize.minHeight = 3f;
            dividerSize.preferredHeight = 3f;
            _divider = divider.gameObject;

            _when = MakeText("When", _card, reading, 34f, Color.white, FontStyles.Normal);
            _place = MakeText("Place", _card, reading, 32f, Muted, FontStyles.Normal);
            _tags = MakeText("Tags", _card, label, 26f, Muted, FontStyles.Normal);
            _tags.textWrappingMode = TextWrappingModes.NoWrap;
            _tags.overflowMode = TextOverflowModes.Ellipsis;

            cardRoot.SetActive(false);
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

            for (int i = 0; i < canvases.Length; i++)
            {
                if (canvases[i].isRootCanvas && canvases[i].renderMode == RenderMode.ScreenSpaceCamera)
                {
                    return canvases[i];
                }
            }

            return null;
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

        private Image MakeImage(string name, Transform parent, Color color)
        {
            GameObject go = new GameObject(name, typeof(RectTransform));
            go.layer = parent.gameObject.layer;
            go.transform.SetParent(parent, false);
            Image image = go.AddComponent<Image>();
            image.sprite = _round;
            image.type = Image.Type.Sliced;
            image.color = color;
            image.raycastTarget = false;
            return image;
        }

        private static TextMeshProUGUI MakeText(
            string name, Transform parent, TMP_FontAsset font, float size, Color color, FontStyles style)
        {
            GameObject go = new GameObject(name, typeof(RectTransform));
            go.layer = parent.gameObject.layer;
            go.transform.SetParent(parent, false);
            TextMeshProUGUI text = go.AddComponent<TextMeshProUGUI>();
            if (font != null)
            {
                text.font = font;
            }

            text.fontSize = size;
            text.fontStyle = style;
            text.color = color;
            text.richText = false;
            text.textWrappingMode = TextWrappingModes.Normal;
            text.alignment = TextAlignmentOptions.TopLeft;
            text.raycastTarget = false;
            return text;
        }

        private static void IgnoreLayout(GameObject go)
        {
            go.AddComponent<LayoutElement>().ignoreLayout = true;
            RectTransform rect = (RectTransform)go.transform;
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
        }

        private static void AddSpace(GameObject go, float below)
        {
            // A little air under the title: an empty element after it.
            GameObject space = new GameObject(go.name + "Space", typeof(RectTransform));
            space.layer = go.layer;
            space.transform.SetParent(go.transform.parent, false);
            LayoutElement element = space.AddComponent<LayoutElement>();
            element.minHeight = below;
            element.preferredHeight = below;
        }

        private void CreateSprite()
        {
            if (_round != null)
            {
                return;
            }

            const int size = 128;
            _roundTexture = new Texture2D(size, size, TextureFormat.RGBA32, false);
            _roundTexture.name = "TalkCardRound";
            _roundTexture.wrapMode = TextureWrapMode.Clamp;
            _roundTexture.filterMode = FilterMode.Bilinear;
            Color32[] pixels = new Color32[size * size];
            for (int y = 0; y < size; y++)
            {
                for (int x = 0; x < size; x++)
                {
                    float d = RoundedRectDistance(x, y, size, CornerRadius);
                    byte a = (byte)Mathf.RoundToInt(Mathf.Clamp01(0.5f - d) * 255f);
                    pixels[(y * size) + x] = new Color32(255, 255, 255, a);
                }
            }

            _roundTexture.SetPixels32(pixels);
            _roundTexture.Apply(false, true);
            float border = CornerRadius + 2f;
            _round = Sprite.Create(
                _roundTexture, new Rect(0f, 0f, size, size), new Vector2(0.5f, 0.5f), 100f, 0,
                SpriteMeshType.FullRect, new Vector4(border, border, border, border));
        }

        private static float RoundedRectDistance(int x, int y, int size, float radius)
        {
            float half = size * 0.5f;
            float qx = Mathf.Abs(x + 0.5f - half) - (half - radius);
            float qy = Mathf.Abs(y + 0.5f - half) - (half - radius);
            float outside = new Vector2(Mathf.Max(qx, 0f), Mathf.Max(qy, 0f)).magnitude;
            float inside = Mathf.Min(Mathf.Max(qx, qy), 0f);
            return outside + inside - radius;
        }

        private static Color WithAlpha(Color color, float alpha)
        {
            color.a = alpha;
            return color;
        }
    }
}
