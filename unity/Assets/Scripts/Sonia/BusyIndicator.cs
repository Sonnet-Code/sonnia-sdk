// On-screen busy indicator (busy message, docs/protocol.md). While Sonnia waits
// for something the user cannot see (the backend is thinking or searching the
// web), a large pill appears at the top with three bouncing dots, "SONNIA" and
// the text sent by the orchestrator ("Thinking...").
//
// It is built in code in Play (added by SoniaBootstrap) in its own Canvas nested
// in the HUD one and sorted above everything else: stage, subtitles and effects.
//
// Placement: the very top strip, the one used by the logo, which StageScreen
// moves aside while the pill is visible. It stays above the avatar's head in all
// framings, so it covers neither her face nor her hands.
//
// Timing: it enters in about 0.14 s, stays at least 0.6 s even if the off arrives
// earlier (so it does not flicker) and leaves in 0.2 s, with the same smooth curve
// both ways and no bounce: it shows on every delegation, even quick ones, and an
// on that arrives while it leaves brings it back from where it is. If the text
// changes while it is on, the new one fades in place and the width adjusts,
// without entering again. If the orchestrator drops, it hides itself. Nothing
// here throws: without a HUD it builds its own Canvas and without an orchestrator
// it does not show (or shows with Show, for testing).

using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>The "Sonnia is on it" pill requested by the <c>busy</c> message.</summary>
    [DisallowMultipleComponent]
    public class BusyIndicator : MonoBehaviour
    {
        private const string HudCanvasName = "SoniaHUD";
        private const string ResourceFolder = "Stage/";

        [Header("Text")]
        [SerializeField]
        [Tooltip("Label above the text: who is on it.")]
        private string speaker = "SONNIA";

        [Header("Timing (seconds)")]
        [SerializeField]
        [Range(0.05f, 0.5f)]
        [Tooltip("Enter: fade, a little scale and a short drop.")]
        private float enterSeconds = 0.14f;

        [SerializeField]
        [Range(0.05f, 0.6f)]
        [Tooltip("Short exit.")]
        private float exitSeconds = 0.2f;

        [SerializeField]
        [Range(0f, 3f)]
        [Tooltip("Minimum time it stays even if the off arrives earlier, so it does not flicker.")]
        private float minVisibleSeconds = 0.6f;

        [SerializeField]
        [Range(10f, 600f)]
        [Tooltip("Safety net: if the off does not arrive in this time, it hides itself.")]
        private float maxVisibleSeconds = 90f;

        [Header("Layout (pixels at the 1080x1920 reference)")]
        [SerializeField]
        [Tooltip("Distance from the top edge of the screen to the pill.")]
        private float top = 32f;

        [SerializeField]
        [Range(32f, 72f)]
        [Tooltip("Text size (shrinks if it does not fit). Subtitles use 64.")]
        private float textSize = 58f;

        [SerializeField]
        [Tooltip("Maximum width of the pill.")]
        private float maxWidth = 1008f;

        [SerializeField]
        [Tooltip("Sorting order of its Canvas above the HUD one: in front of everything.")]
        private int sortingAboveHud = 50;

        // Royal blue of the stage background (a bit deeper than the top so the pill
        // stands out from it) and the light sky blue of its glow.
        private static readonly Color Royal = new Color32(37, 87, 172, 255);
        private static readonly Color Sky = new Color32(143, 208, 255, 255);

        private const float PillHeight = 136f;
        private const float PadLeft = 40f;
        private const float PadRight = 46f;
        private const float DotSize = 22f;
        private const float DotGap = 12f;
        private const float DotsWidth = (DotSize * 3f) + (DotGap * 2f);
        private const float DotsGapToText = 28f;
        private const float MinTextSize = 34f;

        private SoniaClient _client;
        private StageScreen _stage;
        private bool _built;
        private bool _failed;
        private float _startedAt;

        private Canvas _canvas;
        private RectTransform _pill;
        private CanvasGroup _group;
        private TextMeshProUGUI _label;
        private TextMeshProUGUI _message;
        private readonly List<RectTransform> _dots = new List<RectTransform>(3);
        private readonly List<Image> _dotImages = new List<Image>(3);
        private Sprite _round;
        private Sprite _shadow;
        private Texture2D _roundTexture;

        // State: what the orchestrator asks for and what is shown.
        private bool _wanted;
        private string _text = string.Empty;
        private string _pendingText;
        private float _wantedSince = -100f;
        private float _shownAt = -100f;
        private float _visibility;
        private bool _showing;
        private float _width;
        private float _targetWidth;
        private float _textFade = 1f;

        /// <summary>True while the pill is visible, even partly (entering or leaving).</summary>
        public bool IsVisible
        {
            get { return _visibility > 0.001f || _wanted; }
        }

        /// <summary>
        /// True while it enters or stays (not while it leaves): StageScreen moves the
        /// logo aside with this, so it returns as the pill goes away.
        /// </summary>
        public bool IsShowing
        {
            get { return _wanted || _showing; }
        }

        /// <summary>True while the orchestrator asks for it (or it was requested with <see cref="Show"/>).</summary>
        public bool IsOn
        {
            get { return _wanted; }
        }

        /// <summary>What the pill says now.</summary>
        public string CurrentText
        {
            get { return _text; }
        }

        /// <summary>From 0 (hidden) to 1 (full): how much is visible.</summary>
        public float Visibility
        {
            get { return _visibility; }
        }

        private void Awake()
        {
            _client = GetComponentInChildren<SoniaClient>(true);
            _stage = GetComponentInChildren<StageScreen>(true);
        }

        private void OnEnable()
        {
            if (_client == null)
            {
                return;
            }

            _client.OnBusy += HandleBusy;
            _client.OnDisconnected += HandleDisconnected;
            _client.OnHello += HandleHello;
        }

        private void OnDisable()
        {
            if (_client == null)
            {
                return;
            }

            _client.OnBusy -= HandleBusy;
            _client.OnDisconnected -= HandleDisconnected;
            _client.OnHello -= HandleHello;
        }

        private void Start()
        {
            _startedAt = Time.unscaledTime;
        }

        private void OnDestroy()
        {
            if (_roundTexture != null)
            {
                Destroy(_roundTexture);
            }
        }

        // ------------------------------------------------------------------
        // API (also for testing without an orchestrator)
        // ------------------------------------------------------------------

        /// <summary>Shows the pill with that text, or changes it in place if already shown.</summary>
        public void Show(string text)
        {
            string clean = Clean(text);
            float now = Time.unscaledTime;
            if (!_wanted)
            {
                // Each on counts its minimum from now, also if it arrives while leaving.
                _wantedSince = now;
                _shownAt = now;
            }

            _wanted = true;
            _pendingText = clean != _text ? clean : null;
        }

        /// <summary>Asks to remove it: it leaves once it has been visible for <see cref="minVisibleSeconds"/>.</summary>
        public void Hide()
        {
            _wanted = false;
        }

        // ------------------------------------------------------------------
        // Protocol
        // ------------------------------------------------------------------

        private void HandleBusy(BusyMessage message)
        {
            if (message == null)
            {
                return;
            }

            if (message.On)
            {
                Show(message.Text);
            }
            else
            {
                Hide();
            }
        }

        private void HandleDisconnected()
        {
            // Without an orchestrator nobody will send the off; on return it repeats the notice if it still applies.
            Hide();
        }

        private void HandleHello(HelloMessage message)
        {
            Hide();
        }

        // ------------------------------------------------------------------
        // Loop
        // ------------------------------------------------------------------

        private void Update()
        {
            try
            {
                Tick();
            }
            catch (Exception ex)
            {
                // A failure here cannot bring down anything else on screen: drop the indicator.
                if (!_failed)
                {
                    _failed = true;
                    Debug.LogException(ex, this);
                }

                _wanted = false;
                _showing = false;
                _visibility = 0f;
                if (_pill != null)
                {
                    _pill.gameObject.SetActive(false);
                }
            }
        }

        private void Tick()
        {
            float now = Time.unscaledTime;
            float dt = Mathf.Min(Time.unscaledDeltaTime, 0.1f);
            if (!_built)
            {
                // Uses the stage screen fonts: wait for it to be built (or for a
                // moment to pass without it).
                bool stageReady = _stage == null || _stage.IsBuilt || !_stage.isActiveAndEnabled;
                if (!stageReady && now - _startedAt < 3f && !_wanted)
                {
                    return;
                }

                Build();
            }

            if (_pill == null)
            {
                return;
            }

            if (_wanted && now - _wantedSince > maxVisibleSeconds)
            {
                Debug.LogWarning("[Sonnia] The busy indicator has been on for " + maxVisibleSeconds.ToString("0")
                                 + " s without being cleared: hiding it.", this);
                _wanted = false;
            }

            if (_pendingText != null)
            {
                // Already on: the new text fades in and the width adjusts. Off or
                // just starting to enter: go straight to its size.
                bool inPlace = _visibility > 0.5f;
                SetText(_pendingText);
                _pendingText = null;
                _textFade = inPlace ? 0f : 1f;
                if (!inPlace)
                {
                    _width = _targetWidth;
                }
            }

            // It stays at least minVisibleSeconds from when it started to show.
            bool show = _wanted || (_visibility > 0.001f && now - _shownAt < minVisibleSeconds);
            _showing = show;
            float previous = _visibility;
            if (show)
            {
                if (previous <= 0.001f)
                {
                    _shownAt = now;
                    _width = _targetWidth;
                    Debug.Log("[Sonnia] Busy indicator: \"" + _text + "\"", this);
                }

                _visibility = Mathf.MoveTowards(_visibility, 1f, dt / Mathf.Max(0.01f, enterSeconds));
            }
            else
            {
                _visibility = Mathf.MoveTowards(_visibility, 0f, dt / Mathf.Max(0.01f, exitSeconds));
                if (previous > 0.001f && _visibility <= 0.001f)
                {
                    Debug.Log("[Sonnia] Busy indicator hidden after " + (now - _shownAt).ToString("0.00") + " s.", this);
                }
            }

            Apply(now, dt);
        }

        private void Apply(float now, float dt)
        {
            bool visible = _visibility > 0.001f;
            if (_pill.gameObject.activeSelf != visible)
            {
                _pill.gameObject.SetActive(visible);
            }

            if (!visible)
            {
                return;
            }

            // Enter and exit use the same curve, only the speed changes: it drops a
            // few pixels into place, grows a little without bounce and fades in; on
            // exit, the reverse. This way an on during an exit does not jump.
            float v = _visibility;
            float eased = EaseOutCubic(v);
            float alpha = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(v * 1.25f));
            float scale = Mathf.Lerp(0.94f, 1f, eased);
            float lift = 12f * (1f - eased);

            // The width adjusts to the new text without overshooting.
            _width = Mathf.Abs(_width - _targetWidth) < 0.5f
                ? _targetWidth
                : Mathf.Lerp(_width, _targetWidth, 1f - Mathf.Exp(-dt * 22f));

            _group.alpha = alpha;
            _pill.localScale = new Vector3(scale, scale, 1f);
            _pill.anchoredPosition = new Vector2(0f, -top + lift);
            _pill.sizeDelta = new Vector2(_width, PillHeight);

            // Text that changes in place fades in 0.18 s.
            if (_textFade < 1f)
            {
                _textFade = Mathf.MoveTowards(_textFade, 1f, dt / 0.18f);
            }

            float textAlpha = Mathf.Lerp(0.25f, 1f, Mathf.SmoothStep(0f, 1f, _textFade));
            if (!Mathf.Approximately(_message.alpha, textAlpha))
            {
                _message.alpha = textAlpha;
            }

            // Three dots that bounce one after another.
            for (int i = 0; i < _dots.Count; i++)
            {
                float phase = Mathf.Repeat((now * 1.5f) - (i * 0.16f), 1f);
                float up = phase < 0.5f ? Mathf.Sin(phase * 2f * Mathf.PI) : 0f;
                _dots[i].anchoredPosition = new Vector2(
                    (DotSize * 0.5f) + (i * (DotSize + DotGap)),
                    -4f + (16f * up));
                Color color = Color.Lerp(Sky, Color.white, up);
                color.a = 0.75f + (0.25f * up);
                _dotImages[i].color = color;
            }
        }

        private void SetText(string text)
        {
            // TextMeshPro measures better with the object active: enable it for a moment.
            bool wasActive = _pill.gameObject.activeSelf;
            if (!wasActive)
            {
                _pill.gameObject.SetActive(true);
            }

            try
            {
                Measure(text);
            }
            finally
            {
                if (!wasActive)
                {
                    _pill.gameObject.SetActive(false);
                }
            }
        }

        private void Measure(string text)
        {
            _text = text;
            _message.fontSize = textSize;
            _message.text = text;
            Vector2 preferred = _message.GetPreferredValues(text, 10000f, 0f);
            float labelWidth = _label.GetPreferredValues(_label.text, 10000f, 0f).x;
            float room = maxWidth - PadLeft - DotsWidth - DotsGapToText - PadRight;
            float textWidth = preferred.x;
            if (textWidth > room && textWidth > 0f)
            {
                _message.fontSize = Mathf.Max(MinTextSize, textSize * room / textWidth);
                textWidth = Mathf.Min(room, _message.GetPreferredValues(text, 10000f, 0f).x);
            }

            float content = Mathf.Max(textWidth, labelWidth);
            _targetWidth = Mathf.Ceil(PadLeft + DotsWidth + DotsGapToText + content + PadRight);
        }

        // ------------------------------------------------------------------
        // Build
        // ------------------------------------------------------------------

        private void Build()
        {
            _built = true;
            Canvas host = ResolveCanvas();
            int layer = host != null ? host.gameObject.layer : LayerMask.NameToLayer("UI");
            if (layer < 0)
            {
                layer = 0;
            }

            GameObject canvasObject = new GameObject("BusyIndicator", typeof(RectTransform));
            canvasObject.layer = layer;
            if (host != null)
            {
                // Nested Canvas with its own order: in front of everything in the HUD,
                // whatever is added later.
                canvasObject.transform.SetParent(host.transform, false);
                Stretch((RectTransform)canvasObject.transform);
                _canvas = canvasObject.AddComponent<Canvas>();
                _canvas.overrideSorting = true;
                _canvas.sortingLayerID = host.sortingLayerID;
                _canvas.sortingOrder = host.sortingOrder + sortingAboveHud;
            }
            else
            {
                // Without a HUD (another scene): its own Canvas on top of everything.
                canvasObject.transform.SetParent(transform, false);
                _canvas = canvasObject.AddComponent<Canvas>();
                _canvas.renderMode = RenderMode.ScreenSpaceOverlay;
                _canvas.sortingOrder = 1000;
                CanvasScaler scaler = canvasObject.AddComponent<CanvasScaler>();
                scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
                scaler.referenceResolution = new Vector2(1080f, 1920f);
                scaler.matchWidthOrHeight = 0.5f;
            }

            RectTransform root = (RectTransform)canvasObject.transform;
            LoadSprites();
            TMP_FontAsset display = _stage != null && _stage.DisplayFont != null ? _stage.DisplayFont : TMP_Settings.defaultFontAsset;
            TMP_FontAsset mono = _stage != null && _stage.MonoFont != null ? _stage.MonoFont : display;

            _pill = NewRect("Pill", root, layer);
            _pill.anchorMin = new Vector2(0.5f, 1f);
            _pill.anchorMax = new Vector2(0.5f, 1f);
            _pill.pivot = new Vector2(0.5f, 1f);
            _pill.anchoredPosition = new Vector2(0f, -top);
            _pill.sizeDelta = new Vector2(480f, PillHeight);
            _group = _pill.gameObject.AddComponent<CanvasGroup>();
            _group.interactable = false;
            _group.blocksRaycasts = false;
            _group.alpha = 0f;

            // Soft shadow, white border and the face in royal blue, like the
            // invitation speech bubble.
            if (_shadow != null)
            {
                Image shadow = NewImage("Shadow", _pill, _shadow, new Color(0f, 0f, 0f, 0.5f), layer);
                shadow.type = Image.Type.Sliced;
                Stretch(shadow.rectTransform);
                shadow.rectTransform.offsetMin = new Vector2(-54f, -74f);
                shadow.rectTransform.offsetMax = new Vector2(54f, 34f);
            }

            Image border = NewImage("Border", _pill, null, new Color(1f, 1f, 1f, 0.92f), layer);
            ConfigureRound(border, (PillHeight * 0.5f) + 5f);
            Stretch(border.rectTransform);
            border.rectTransform.offsetMin = new Vector2(-5f, -5f);
            border.rectTransform.offsetMax = new Vector2(5f, 5f);

            Image face = NewImage("Face", _pill, null, Royal, layer);
            ConfigureRound(face, PillHeight * 0.5f);
            Stretch(face.rectTransform);

            // The dots, on the left and vertically centered.
            RectTransform dots = NewRect("Dots", _pill, layer);
            dots.anchorMin = new Vector2(0f, 0.5f);
            dots.anchorMax = new Vector2(0f, 0.5f);
            dots.pivot = new Vector2(0f, 0.5f);
            dots.anchoredPosition = new Vector2(PadLeft, 0f);
            dots.sizeDelta = new Vector2(DotsWidth, 40f);
            for (int i = 0; i < 3; i++)
            {
                Image dot = NewImage("Dot" + (i + 1), dots, null, Sky, layer);
                ConfigureRound(dot, DotSize * 0.5f);
                RectTransform rect = dot.rectTransform;
                rect.anchorMin = new Vector2(0f, 0.5f);
                rect.anchorMax = new Vector2(0f, 0.5f);
                rect.pivot = new Vector2(0.5f, 0.5f);
                rect.sizeDelta = new Vector2(DotSize, DotSize);
                rect.anchoredPosition = new Vector2((DotSize * 0.5f) + (i * (DotSize + DotGap)), 0f);
                _dots.Add(rect);
                _dotImages.Add(dot);
            }

            // Small, spaced "SONNIA" above the text, as in the invitation.
            float textLeft = PadLeft + DotsWidth + DotsGapToText;
            _label = NewText("Speaker", _pill, mono, 22f, Sky, layer);
            _label.text = speaker;
            _label.characterSpacing = 14f;
            _label.alignment = TextAlignmentOptions.BottomLeft;
            PlaceLeft(_label.rectTransform, textLeft, 20f, 28f);

            _message = NewText("Text", _pill, display, textSize, Color.white, layer);
            _message.alignment = TextAlignmentOptions.TopLeft;
            _message.characterSpacing = -1f;
            PlaceLeft(_message.rectTransform, textLeft, 48f, 74f);

            SetText(string.IsNullOrEmpty(_pendingText) ? "Thinking…" : _pendingText);
            _width = _targetWidth;
            _pill.gameObject.SetActive(false);
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

        private void LoadSprites()
        {
            _round = LoadSprite("stage-round", new Vector4(64f, 64f, 64f, 64f));
            _shadow = LoadSprite("stage-shadow", new Vector4(112f, 112f, 112f, 112f));
            if (_round == null)
            {
                // Without the stage resources: a generated circle, 9-sliced.
                const int size = 128;
                _roundTexture = new Texture2D(size, size, TextureFormat.RGBA32, false);
                _roundTexture.wrapMode = TextureWrapMode.Clamp;
                Color32[] pixels = new Color32[size * size];
                float radius = size * 0.5f;
                for (int y = 0; y < size; y++)
                {
                    for (int x = 0; x < size; x++)
                    {
                        float dx = x + 0.5f - radius;
                        float dy = y + 0.5f - radius;
                        float d = Mathf.Sqrt((dx * dx) + (dy * dy));
                        byte a = (byte)Mathf.RoundToInt(255f * Mathf.Clamp01(radius - d));
                        pixels[(y * size) + x] = new Color32(255, 255, 255, a);
                    }
                }

                _roundTexture.SetPixels32(pixels);
                _roundTexture.Apply(false, true);
                _round = Sprite.Create(
                    _roundTexture,
                    new Rect(0f, 0f, size, size),
                    new Vector2(0.5f, 0.5f),
                    100f,
                    0,
                    SpriteMeshType.FullRect,
                    new Vector4(64f, 64f, 64f, 64f));
            }
        }

        /// <summary>Sprite from Resources/Stage (like StageScreen). If imported as a texture, it is made here.</summary>
        private static Sprite LoadSprite(string name, Vector4 border)
        {
            Sprite sprite = Resources.Load<Sprite>(ResourceFolder + name);
            if (sprite != null)
            {
                return sprite;
            }

            Texture2D texture = Resources.Load<Texture2D>(ResourceFolder + name);
            if (texture == null)
            {
                return null;
            }

            return Sprite.Create(
                texture,
                new Rect(0f, 0f, texture.width, texture.height),
                new Vector2(0.5f, 0.5f),
                100f,
                0,
                SpriteMeshType.FullRect,
                border);
        }

        // ------------------------------------------------------------------
        // Pieces
        // ------------------------------------------------------------------

        private static RectTransform NewRect(string name, Transform parent, int layer)
        {
            GameObject go = new GameObject(name, typeof(RectTransform));
            go.layer = layer;
            go.transform.SetParent(parent, false);
            return (RectTransform)go.transform;
        }

        private static Image NewImage(string name, RectTransform parent, Sprite sprite, Color color, int layer)
        {
            RectTransform rect = NewRect(name, parent, layer);
            Image image = rect.gameObject.AddComponent<Image>();
            image.sprite = sprite;
            image.color = color;
            image.raycastTarget = false;
            return image;
        }

        private static TextMeshProUGUI NewText(string name, RectTransform parent, TMP_FontAsset font, float size, Color color, int layer)
        {
            RectTransform rect = NewRect(name, parent, layer);
            TextMeshProUGUI text = rect.gameObject.AddComponent<TextMeshProUGUI>();
            if (font != null)
            {
                text.font = font;
            }

            text.fontSize = size;
            text.color = color;
            text.raycastTarget = false;
            text.richText = false;
            text.textWrappingMode = TextWrappingModes.NoWrap;
            text.overflowMode = TextOverflowModes.Overflow;
            return text;
        }

        /// <summary>Rounded rectangle from the radius-64 sprite with the requested radius.</summary>
        private void ConfigureRound(Image image, float radius)
        {
            image.sprite = _round;
            image.type = Image.Type.Sliced;
            image.pixelsPerUnitMultiplier = 64f / Mathf.Max(1f, radius);
        }

        private static void Stretch(RectTransform rect)
        {
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
        }

        /// <summary>Strip at the left of the pill, from <paramref name="left"/> to the right edge.</summary>
        private static void PlaceLeft(RectTransform rect, float left, float topOffset, float height)
        {
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(1f, 1f);
            rect.pivot = new Vector2(0f, 1f);
            rect.offsetMin = new Vector2(left, -topOffset - height);
            rect.offsetMax = new Vector2(0f, -topOffset);
        }

        /// <summary>No extra spaces or line breaks; empty becomes "Thinking...".</summary>
        private static string Clean(string text)
        {
            if (string.IsNullOrEmpty(text))
            {
                return "Thinking…";
            }

            string clean = text.Replace('\n', ' ').Replace('\r', ' ').Trim();
            return clean.Length == 0 ? "Thinking…" : clean;
        }

        private static float EaseOutCubic(float t)
        {
            float x = 1f - t;
            return 1f - (x * x * x);
        }
    }
}
