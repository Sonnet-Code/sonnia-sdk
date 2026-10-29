// Avatar screen: background fixed to the screen, an optional logo at the top
// left, the invitation to talk at the bottom while nobody is conversing and, when
// someone is, large karaoke-style subtitles with what the user said in a pill
// above them.
//
// It is built in code in Play, like the trivia and the away sign: the
// background goes in its own Canvas drawn by the main camera several meters away
// (behind the avatar and with the same post-processing as the scene) and the rest
// inside the HUD Canvas (without post-processing). Resources are in
// Resources/Stage. The logo is optional: it is drawn if Resources/Stage/stage-logo
// exists (a PNG with alpha; stage-logo-shadow, if it exists, is its shadow) and,
// if not, it takes no space. There is no QR code.
//
// Rules:
//  - The invitation only shows if the avatar can converse (stage_mode, talk), is
//    idle, there are no recent subtitles and there is no image, trivia or away
//    mode.
//  - The avatar's subtitles grow with her voice: what just arrived is dimmed and
//    brightens soon after. If the whole phrase arrives in speech_start (recorded
//    phrases), what has not been said yet is dimmed and lights up at the
//    estimated pace of the voice: the karaoke effect.
//  - With the busy indicator (BusyIndicator) in the top strip, the logo is moved
//    aside: the pill takes its place while it is visible.

using System.Collections.Generic;
using System.Text;
using TMPro;
using UnityEngine;
using UnityEngine.TextCore.LowLevel;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Builds the avatar screen and decides what is visible at each moment.</summary>
    [DisallowMultipleComponent]
    public class StageScreen : MonoBehaviour
    {
        private const string HudCanvasName = "SoniaHUD";
        private const string ResourceFolder = "Stage/";

        /// <summary>Distance from the invitation speech bubble to the bottom edge (reference px).</summary>
        private const float InvitationBottom = 96f;

        [Header("Text")]
        [SerializeField]
        [Tooltip("What the avatar says in the invitation speech bubble. The line break is part of the design.")]
        [TextArea(2, 3)]
        private string invitation = "Come closer and ask me\nanything!";

        [SerializeField]
        [Tooltip("Who speaks in the speech bubble.")]
        private string invitationSpeaker = "SONNIA";

        [Header("Background")]
        [SerializeField]
        [Tooltip("Distance from the background to the camera, in meters. It must stay behind everything in the scene and before the camera far plane.")]
        private float backdropDistance = 12f;

        [SerializeField]
        [Tooltip("Background tint. The scene tonemapping darkens it a bit; above white compensates.")]
        private Color backdropTint = Color.white;

        [SerializeField]
        [Tooltip("Dark blue gradient at the bottom (the permanent shade and the one that turns on with subtitles). Off for now: it covered the avatar's hands.")]
        private bool bottomShade;

        [Header("Subtitles")]
        [SerializeField]
        [Range(32f, 96f)]
        private float subtitleSize = 64f;

        [SerializeField]
        [Tooltip("Maximum characters on screen: for a long phrase the end is shown.")]
        private int maxSubtitleCharacters = 110;

        [SerializeField]
        [Range(0.05f, 2f)]
        [Tooltip("Seconds a new word takes to go from dimmed to white.")]
        private float revealSeconds = 0.45f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Opacity of what has not been said yet (or just arrived).")]
        private float dimAlpha = 0.42f;

        [SerializeField]
        [Range(5f, 40f)]
        [Tooltip("Estimated voice pace for phrases that arrive whole (characters per second).")]
        private float spokenCharactersPerSecond = 15f;

        [SerializeField]
        [Range(10f, 80f)]
        [Tooltip("At most this fast do text chunks that arrive at once light up.")]
        private float streamCharactersPerSecond = 28f;

        [SerializeField]
        [Range(1f, 20f)]
        [Tooltip("Seconds the subtitles stay once nobody is speaking.")]
        private float lingerSeconds = 6f;

        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("Seconds of calm before the invitation to talk returns.")]
        private float invitationDelay = 1.5f;

        // Screen colors.
        private static readonly Color Navy = new Color32(20, 39, 82, 255);
        private static readonly Color Brand = new Color32(3, 113, 245, 255);
        private static readonly Color Dark = new Color32(11, 19, 34, 255);

        /// <summary>What the background darkens towards (the glyph rain of StageParticles).</summary>
        private static readonly Color ShadedBackdrop = Color.black;

        private SoniaClient _client;
        private Canvas _hud;
        private ImagePanelController _imagePanel;
        private TriviaController _trivia;
        private PresenceController _presence;
        private BusyIndicator _busy;
        private bool _built;

        private TMP_FontAsset _display;
        private TMP_FontAsset _semibold;
        private TMP_FontAsset _mono;
        private Sprite _round;
        private Sprite _shadow;

        private CanvasGroup _logoGroup;
        private CanvasGroup _invitationGroup;
        private RectTransform _invitationRect;
        private CanvasGroup _subtitleGroup;
        private CanvasGroup _visitorGroup;
        private TextMeshProUGUI _visitorText;
        private LayoutElement _visitorTextLayout;
        private TextMeshProUGUI _soniaText;
        private Image _scrim;
        private Image _conversationScrim;
        private Image _backdrop;
        private float _backdropShade;

        // Conversation state.
        private bool _talk = true;
        private bool _subtitlesOn = true;
        private string _state = AvatarStateNames.Idle;
        private float _lastActivity = -100f;

        // Current phrase of the avatar: text and, per character, when it lights up.
        private string _sonia = string.Empty;
        private readonly List<float> _revealAt = new List<float>();
        private int _utterance = -1;
        private bool _speaking;
        private string _pendingText;
        private bool _soniaDirty;

        private string _visitor = string.Empty;
        private bool _visitorDirty;

        private readonly StringBuilder _builder = new StringBuilder(256);

        /// <summary>True once the screen is built.</summary>
        public bool IsBuilt
        {
            get { return _built; }
        }

        /// <summary>Headline font (Manrope ExtraBold), so other UI can use the same one. Null until built.</summary>
        public TMP_FontAsset DisplayFont
        {
            get { return _display; }
        }

        /// <summary>Font for reading text (Manrope SemiBold).</summary>
        public TMP_FontAsset SemiboldFont
        {
            get { return _semibold; }
        }

        /// <summary>Font for labels (Geist Mono).</summary>
        public TMP_FontAsset MonoFont
        {
            get { return _mono; }
        }

        /// <summary>
        /// How much black is put over the background: 0 is the normal one, 0.3
        /// leaves it at 70 % and 1 is black. StageParticles moves it while the
        /// glyph rain falls.
        /// </summary>
        public float BackdropShade
        {
            get { return _backdropShade; }
            set
            {
                _backdropShade = Mathf.Clamp01(value);
                if (_backdrop != null)
                {
                    _backdrop.color = Color.Lerp(backdropTint, ShadedBackdrop, _backdropShade);
                }
            }
        }

        private void Awake()
        {
            _client = GetComponentInChildren<SoniaClient>(true);
            _imagePanel = GetComponentInChildren<ImagePanelController>(true);
        }

        private void OnEnable()
        {
            if (_client == null)
            {
                return;
            }

            _client.OnState += HandleState;
            _client.OnTranscript += HandleTranscript;
            _client.OnSpeechStart += HandleSpeechStart;
            _client.OnAudioFrame += HandleAudioFrame;
            _client.OnSpeechEnd += HandleSpeechEnd;
            _client.OnStopSpeaking += HandleStopSpeaking;
            _client.OnSetSubtitles += HandleSetSubtitles;
            _client.OnStageMode += HandleStageMode;
            _client.OnDisconnected += HandleDisconnected;
        }

        private void OnDisable()
        {
            if (_client == null)
            {
                return;
            }

            _client.OnState -= HandleState;
            _client.OnTranscript -= HandleTranscript;
            _client.OnSpeechStart -= HandleSpeechStart;
            _client.OnAudioFrame -= HandleAudioFrame;
            _client.OnSpeechEnd -= HandleSpeechEnd;
            _client.OnStopSpeaking -= HandleStopSpeaking;
            _client.OnSetSubtitles -= HandleSetSubtitles;
            _client.OnStageMode -= HandleStageMode;
            _client.OnDisconnected -= HandleDisconnected;
        }

        private void Start()
        {
            // Trivia and presence are added by SoniaBootstrap in code in its Awake.
            _trivia = GetComponentInChildren<TriviaController>(true);
            _presence = GetComponentInChildren<PresenceController>(true);
            _busy = GetComponentInChildren<BusyIndicator>(true);
            Build();
        }

        // ------------------------------------------------------------------
        // Tests without an orchestrator (captures from the editor, no API usage)
        // ------------------------------------------------------------------

        /// <summary>As if a <c>transcript</c> arrived (role <c>user</c> or <c>assistant</c>).</summary>
        public void SimulateTranscript(string role, string text, bool final)
        {
            HandleTranscript(new TranscriptMessage { Role = role, Text = text, Final = final });
        }

        /// <summary>As if a phrase of the avatar started (with the whole text if recorded).</summary>
        public void SimulateSpeechStart(int utterance, string text)
        {
            HandleSpeechStart(new SpeechStartMessage { UtteranceId = utterance, Text = text ?? string.Empty });
        }

        /// <summary>As if audio of that phrase arrived.</summary>
        public void SimulateAudio(int utterance)
        {
            HandleAudioFrame(new AudioFrame { UtteranceId = utterance });
        }

        /// <summary>As if that phrase ended.</summary>
        public void SimulateSpeechEnd(int utterance)
        {
            HandleSpeechEnd(new SpeechEndMessage { UtteranceId = utterance });
        }

        /// <summary>As if a <c>state</c> arrived (idle, listening, thinking or speaking).</summary>
        public void SimulateState(string state)
        {
            HandleState(new StateMessage { State = state });
        }

        /// <summary>As if <c>stage_mode</c> arrived.</summary>
        public void SimulateStageMode(bool talk)
        {
            HandleStageMode(new StageModeMessage { Talk = talk });
        }

        // ------------------------------------------------------------------
        // Protocol events
        // ------------------------------------------------------------------

        private void HandleState(StateMessage message)
        {
            if (message != null)
            {
                _state = message.State;
                if (_state != AvatarStateNames.Idle)
                {
                    _lastActivity = Time.time;
                }
            }
        }

        private void HandleStageMode(StageModeMessage message)
        {
            if (message != null)
            {
                _talk = message.Talk;
            }
        }

        private void HandleSetSubtitles(SetSubtitlesMessage message)
        {
            if (message == null)
            {
                return;
            }

            _subtitlesOn = message.Enabled;
            if (!_subtitlesOn)
            {
                ClearSubtitles();
            }
        }

        private void HandleDisconnected()
        {
            _speaking = false;
            _pendingText = null;
        }

        private void HandleTranscript(TranscriptMessage message)
        {
            if (message == null || !_subtitlesOn)
            {
                return;
            }

            float now = Time.time;
            if (message.Role == "assistant")
            {
                if (!string.IsNullOrEmpty(message.Text))
                {
                    SetSoniaText(message.Text, now, streaming: true);
                }

                return;
            }

            string text = Clean(message.Text);
            if (string.IsNullOrEmpty(text))
            {
                return;
            }

            // A new question while the avatar is silent opens another exchange: drop
            // the previous answer.
            if (!_speaking && text != _visitor)
            {
                SetSonia(string.Empty);
            }

            _visitor = text;
            _visitorDirty = true;
            _lastActivity = now;
        }

        private void HandleSpeechStart(SpeechStartMessage message)
        {
            if (message == null || !_subtitlesOn)
            {
                return;
            }

            _utterance = message.UtteranceId;
            _speaking = true;
            _lastActivity = Time.time;
            SetSonia(string.Empty);

            // If it arrives whole (recorded phrases), it is shown with the first
            // audio, not before: the subtitle goes with the voice.
            _pendingText = string.IsNullOrEmpty(message.Text) ? null : Clean(message.Text);
        }

        private void HandleAudioFrame(AudioFrame frame)
        {
            if (frame.UtteranceId < _utterance)
            {
                return;
            }

            float now = Time.time;
            _lastActivity = now;
            if (_pendingText != null)
            {
                string text = _pendingText;
                _pendingText = null;
                SetSoniaText(text, now, streaming: false);
            }
        }

        private void HandleSpeechEnd(SpeechEndMessage message)
        {
            if (message == null || message.UtteranceId != _utterance)
            {
                return;
            }

            FinishUtterance();
        }

        private void HandleStopSpeaking(StopSpeakingMessage message)
        {
            FinishUtterance();
        }

        /// <summary>The phrase ended or was cut: what was left to light up lights up now, fast.</summary>
        private void FinishUtterance()
        {
            float now = Time.time;
            _speaking = false;
            _pendingText = null;
            _lastActivity = now;
            float next = now;
            for (int i = 0; i < _revealAt.Count; i++)
            {
                if (_revealAt[i] > next)
                {
                    next += 1f / 90f;
                    _revealAt[i] = next;
                }
            }

            _soniaDirty = true;
        }

        // ------------------------------------------------------------------
        // Avatar text
        // ------------------------------------------------------------------

        /// <summary>
        /// Sets the text of the current phrase. If it extends the previous one, only
        /// the new part lights up; if it changes, it lights up again entirely.
        /// </summary>
        private void SetSoniaText(string text, float now, bool streaming)
        {
            text = Clean(text);
            if (text == _sonia)
            {
                return;
            }

            int keep = text.StartsWith(_sonia) ? _sonia.Length : 0;
            if (keep == 0)
            {
                _revealAt.Clear();
            }
            else if (_revealAt.Count > keep)
            {
                _revealAt.RemoveRange(keep, _revealAt.Count - keep);
            }

            // With live text, what arrives is already being spoken: it lights up
            // from now on, no faster than streamCharactersPerSecond. With the whole
            // phrase ahead, at the estimated pace of the voice.
            float rate = streaming ? streamCharactersPerSecond : spokenCharactersPerSecond;
            float step = 1f / Mathf.Max(1f, rate);
            float last = keep > 0 && _revealAt.Count > 0 ? _revealAt[_revealAt.Count - 1] : now - step;
            for (int i = keep; i < text.Length; i++)
            {
                last = Mathf.Max(now, last + step);
                _revealAt.Add(last);
            }

            _sonia = text;
            _soniaDirty = true;
            _lastActivity = now;
        }

        private void SetSonia(string text)
        {
            _sonia = text ?? string.Empty;
            _revealAt.Clear();
            for (int i = 0; i < _sonia.Length; i++)
            {
                _revealAt.Add(0f);
            }

            _soniaDirty = true;
        }

        private void ClearSubtitles()
        {
            SetSonia(string.Empty);
            _pendingText = null;
            _visitor = string.Empty;
            _visitorDirty = true;
        }

        /// <summary>No extra spaces or signs that TextMeshPro would read as tags.</summary>
        private static string Clean(string text)
        {
            if (string.IsNullOrEmpty(text))
            {
                return string.Empty;
            }

            return text.Replace('<', '‹').Replace('>', '›').Replace('\n', ' ').Trim();
        }

        /// <summary>
        /// Text with each span at its opacity: lit what was said, dimmed what is
        /// left. If it does not fit, the end is shown starting at a whole word.
        /// </summary>
        private string BuildKaraoke(float now, out bool animating)
        {
            animating = false;
            string text = _sonia;
            int start = 0;
            _builder.Length = 0;
            if (text.Length > maxSubtitleCharacters)
            {
                start = text.Length - maxSubtitleCharacters;
                int space = text.IndexOf(' ', start);
                if (space >= 0 && space < text.Length - 1)
                {
                    start = space + 1;
                }

                _builder.Append("<alpha=#FF>… ");
            }

            int level = -1;
            for (int i = start; i < text.Length; i++)
            {
                float alpha = 1f;
                if (i < _revealAt.Count)
                {
                    float age = now - _revealAt[i];
                    if (age < revealSeconds)
                    {
                        animating = true;
                        alpha = age <= 0f
                            ? dimAlpha
                            : Mathf.Lerp(dimAlpha, 1f, Mathf.SmoothStep(0f, 1f, age / revealSeconds));
                    }
                }

                int quantized = Mathf.Clamp(Mathf.RoundToInt(alpha * 16f), 0, 16);
                if (quantized != level)
                {
                    level = quantized;
                    int value = Mathf.Clamp(Mathf.RoundToInt(quantized / 16f * 255f), 0, 255);
                    _builder.Append("<alpha=#").Append(value.ToString("X2")).Append('>');
                }

                _builder.Append(text[i]);
            }

            return _builder.ToString();
        }

        // ------------------------------------------------------------------
        // Loop
        // ------------------------------------------------------------------

        private void Update()
        {
            if (!_built)
            {
                return;
            }

            float now = Time.time;
            float dt = Time.deltaTime;
            bool imageUp = _imagePanel != null && _imagePanel.IsVisible;
            bool triviaUp = _trivia != null && _trivia.IsActive;
            bool away = _presence != null && (_presence.IsAway || !_presence.TargetPresent);
            bool busyUp = _busy != null && _busy.IsShowing;
            bool hasText = _sonia.Length > 0 || _pendingText != null || _visitor.Length > 0;
            bool recent = _speaking || now - _lastActivity < lingerSeconds;
            bool subtitles = _subtitlesOn && hasText && recent && !away;
            bool invitationUp = _talk
                                && !subtitles
                                && _state == AvatarStateNames.Idle
                                && !imageUp && !triviaUp && !away
                                && now - _lastActivity > lingerSeconds + invitationDelay;

            Fade(_logoGroup, busyUp ? 0f : 1f, dt, busyUp ? 8f : 4f);
            Fade(_subtitleGroup, subtitles ? 1f : 0f, dt, subtitles ? 8f : 3f);
            Fade(_visitorGroup, _visitor.Length > 0 ? 1f : 0f, dt, 6f);
            Fade(_invitationGroup, invitationUp ? 1f : 0f, dt, invitationUp ? 2.5f : 6f);
            _invitationRect.anchoredPosition = new Vector2(0f, InvitationBottom - 24f * (1f - _invitationGroup.alpha));
            _scrim.enabled = bottomShade;
            _conversationScrim.enabled = bottomShade;
            _conversationScrim.color = new Color(Dark.r, Dark.g, Dark.b, 0.9f * _subtitleGroup.alpha);

            // When it finishes fading out, drop the old text.
            if (!subtitles && _subtitleGroup.alpha <= 0.001f && hasText && !_speaking)
            {
                ClearSubtitles();
            }

            if (_visitorDirty)
            {
                _visitorDirty = false;
                UpdateVisitor();
            }

            if (_soniaDirty)
            {
                bool animating = false;
                _soniaText.text = _sonia.Length == 0 ? string.Empty : BuildKaraoke(now, out animating);
                _soniaDirty = animating;
            }
        }

        private static void Fade(CanvasGroup group, float target, float dt, float speed)
        {
            if (group != null)
            {
                group.alpha = Mathf.MoveTowards(group.alpha, target, dt * speed);
            }
        }

        private void UpdateVisitor()
        {
            string text = _visitor;
            const int maxCharacters = 70;
            if (text.Length > maxCharacters)
            {
                int start = text.Length - maxCharacters;
                int space = text.IndexOf(' ', start);
                text = "… " + text.Substring(space >= 0 && space < text.Length - 1 ? space + 1 : start);
            }

            _visitorText.text = text;
            Vector2 preferred = _visitorText.GetPreferredValues(text, 10000f, 0f);
            _visitorTextLayout.preferredWidth = Mathf.Min(preferred.x + 2f, 820f);
        }

        // ------------------------------------------------------------------
        // Build
        // ------------------------------------------------------------------

        private void Build()
        {
            _hud = ResolveCanvas();
            if (_hud == null)
            {
                Debug.LogWarning("[Sonnia] No HUD Canvas: the stage screen is not built.", this);
                enabled = false;
                return;
            }

            LoadAssets();
            BuildBackdrop();
            HideLegacyScreen();

            // Below everything else in the HUD (trivia, away sign, debug).
            RectTransform stage = NewRect("Stage", _hud.transform);
            Stretch(stage);
            stage.SetAsFirstSibling();

            BuildScrim(stage);
            _logoGroup = NewGroup("Logo", stage);
            BuildLogo((RectTransform)_logoGroup.transform);
            BuildInvitation(stage);

            // Subtitles, above the whole HUD.
            RectTransform subtitles = NewRect("StageSubtitles", _hud.transform);
            Stretch(subtitles);
            subtitles.SetAsLastSibling();
            BuildConversationScrim(subtitles);
            BuildSubtitles(subtitles);

            _subtitleGroup.alpha = 0f;
            _invitationGroup.alpha = 0f;
            _built = true;
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

        private void LoadAssets()
        {
            TMP_FontAsset fallback = TMP_Settings.defaultFontAsset;
            _display = LoadFont("Manrope-ExtraBold", fallback);
            _semibold = LoadFont("Manrope-SemiBold", fallback);
            _mono = LoadFont("GeistMono-Medium", fallback);
            _round = LoadSprite("stage-round", new Vector4(64f, 64f, 64f, 64f));
            _shadow = LoadSprite("stage-shadow", new Vector4(112f, 112f, 112f, 112f));
        }

        /// <summary>Characters loaded into each font when created: ASCII, common Latin accents and subtitle typography.</summary>
        private const string Charset =
            " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~"
            + "¡¿ÁÉÍÓÚÜÑáéíóúüñ«»·–—‘’“”…‹›€°ºª";

        private static TMP_FontAsset LoadFont(string name, TMP_FontAsset fallback)
        {
            Font font = Resources.Load<Font>(ResourceFolder + "Fonts/" + name);
            if (font == null)
            {
                Debug.LogWarning("[Sonnia] Missing font " + name + " in Resources/Stage/Fonts; using the TextMeshPro one.");
                return fallback;
            }

            TMP_FontAsset asset = TMP_FontAsset.CreateFontAsset(
                font, 72, 8, GlyphRenderMode.SDFAA, 2048, 2048, AtlasPopulationMode.Dynamic, true);
            if (asset == null)
            {
                return fallback;
            }

            asset.name = name;

            // All the characters at once: this avoids hiccups when a new character
            // shows up mid-conversation and each font rasterizes its own back to
            // back, without mixing with the others.
            string missing;
            if (!asset.TryAddCharacters(Charset, out missing) && !string.IsNullOrEmpty(missing))
            {
                Debug.LogWarning("[Sonnia] The font " + name + " lacks: " + missing);
            }

            if (fallback != null)
            {
                asset.fallbackFontAssetTable = new List<TMP_FontAsset> { fallback };
            }

            return asset;
        }

        /// <summary>Sprite from Resources/Stage. If imported as a texture, it is made here with its 9-slice border.</summary>
        private static Sprite LoadSprite(string name, Vector4 border, bool optional = false)
        {
            Sprite sprite = Resources.Load<Sprite>(ResourceFolder + name);
            if (sprite != null)
            {
                return sprite;
            }

            Texture2D texture = Resources.Load<Texture2D>(ResourceFolder + name);
            if (texture == null)
            {
                if (!optional)
                {
                    Debug.LogWarning("[Sonnia] Missing Resources/Stage/" + name + ".");
                }

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

        /// <summary>
        /// Screen background in a Canvas drawn by the main camera at
        /// <see cref="backdropDistance"/> meters: it follows the camera (fixed to the
        /// screen) and stays behind the avatar and the halo.
        /// </summary>
        private void BuildBackdrop()
        {
            Camera main = Camera.main;
            Sprite background = LoadSprite("stage-bg", Vector4.zero);
            if (main == null || background == null)
            {
                return;
            }

            GameObject canvasObject = new GameObject("StageBackdrop", typeof(RectTransform));
            canvasObject.transform.SetParent(transform, false);
            canvasObject.layer = 0;
            Canvas canvas = canvasObject.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceCamera;
            canvas.worldCamera = main;
            canvas.planeDistance = Mathf.Min(backdropDistance, main.farClipPlane * 0.9f);
            canvas.sortingOrder = -100;
            CanvasScaler scaler = canvasObject.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1080f, 1920f);
            scaler.matchWidthOrHeight = 0.5f;

            // On the default layer, the one the main camera draws (the HUD one only sees UI).
            Image image = NewImage("Background", (RectTransform)canvasObject.transform, background, backdropTint);
            image.gameObject.layer = 0;
            image.preserveAspect = false;
            Stretch(image.rectTransform);
            _backdrop = image;
            BackdropShade = _backdropShade;
        }

        /// <summary>Turns off what the scene used to draw on its own: the 3D backdrop and the subtitle bubbles.</summary>
        private void HideLegacyScreen()
        {
            Transform backdrop = transform.Find("Backdrop");
            if (backdrop != null)
            {
                backdrop.gameObject.SetActive(false);
            }

            Transform bubbles = _hud.transform.Find("Debug/Subtitles");
            if (bubbles != null)
            {
                bubbles.gameObject.SetActive(false);
            }
        }

        private void BuildScrim(RectTransform stage)
        {
            Sprite scrim = LoadSprite("stage-scrim", Vector4.zero);
            _scrim = NewImage("Scrim", stage, scrim, new Color(Dark.r, Dark.g, Dark.b, 0.92f));
            _scrim.enabled = bottomShade;
            RectTransform rect = _scrim.rectTransform;
            rect.anchorMin = new Vector2(0f, 0f);
            rect.anchorMax = new Vector2(1f, 0f);
            rect.pivot = new Vector2(0.5f, 0f);
            rect.anchoredPosition = Vector2.zero;
            rect.sizeDelta = new Vector2(0f, 760f);
        }

        private void BuildLogo(RectTransform stage)
        {
            const float width = 250f;
            Vector2 offset = new Vector2(56f, 64f);
            Sprite logo = LoadSprite("stage-logo", Vector4.zero, true);
            if (logo == null)
            {
                // No logo in Resources/Stage: the slot is not drawn.
                return;
            }

            float aspect = logo.rect.width / logo.rect.height;
            Vector2 size = new Vector2(width, width / aspect);

            // Soft shadow behind: the blurred outline of the logo
            // (stage-logo-shadow, with margin around it), 12 px lower.
            Sprite shadow = LoadSprite("stage-logo-shadow", Vector4.zero, true);
            if (shadow != null)
            {
                Vector2 shadowSize = shadow.rect.size * (width / logo.rect.width);
                Vector2 margin = (shadowSize - size) * 0.5f;
                Image shade = NewImage("LogoShadow", stage, shadow, new Color(0f, 0f, 0f, 0.55f));
                PlaceTopLeft(shade.rectTransform, offset - margin + new Vector2(0f, 12f), shadowSize);
            }

            Image image = NewImage("Logo", stage, logo, Color.white);
            image.preserveAspect = true;
            PlaceTopLeft(image.rectTransform, offset, size);
        }

        /// <summary>
        /// Invitation to talk: a white speech bubble from the avatar, centered at the
        /// bottom, with the tail to one side tilted towards her.
        /// </summary>
        private void BuildInvitation(RectTransform stage)
        {
            _invitationGroup = NewGroup("Invitation", stage);
            _invitationRect = (RectTransform)_invitationGroup.transform;
            _invitationRect.anchorMin = new Vector2(0f, 0f);
            _invitationRect.anchorMax = new Vector2(1f, 0f);
            _invitationRect.pivot = new Vector2(0.5f, 0f);
            _invitationRect.offsetMin = new Vector2(72f, InvitationBottom);
            _invitationRect.offsetMax = new Vector2(-72f, InvitationBottom);
            VerticalLayoutGroup stack = _invitationRect.gameObject.AddComponent<VerticalLayoutGroup>();
            stack.padding = new RectOffset(48, 48, 38, 46);
            stack.spacing = 12f;
            stack.childAlignment = TextAnchor.UpperCenter;
            stack.childControlWidth = true;
            stack.childControlHeight = true;
            stack.childForceExpandWidth = true;
            stack.childForceExpandHeight = false;
            ContentSizeFitter fitter = _invitationRect.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            // Shadow, face and tail do not count for the size: the texts give it.
            Image shadow = NewImage("Shadow", _invitationRect, _shadow, new Color(0f, 0f, 0f, 0.5f));
            shadow.type = Image.Type.Sliced;
            IgnoreLayout(shadow.rectTransform);
            Stretch(shadow.rectTransform);
            shadow.rectTransform.offsetMin = new Vector2(-60f, -86f);
            shadow.rectTransform.offsetMax = new Vector2(60f, 40f);

            Image face = NewImage("Bubble", _invitationRect, null, Color.white);
            ConfigureRound(face, Color.white, 44f);
            IgnoreLayout(face.rectTransform);
            Stretch(face.rectTransform);

            // The tail comes out of the top edge, left of center, and tilts
            // towards the center of the screen, where the avatar is.
            Image tail = NewImage("Tail", _invitationRect, LoadSprite("stage-tail", Vector4.zero), Color.white);
            IgnoreLayout(tail.rectTransform);
            RectTransform tailRect = tail.rectTransform;
            tailRect.anchorMin = new Vector2(0f, 1f);
            tailRect.anchorMax = new Vector2(0f, 1f);
            tailRect.pivot = new Vector2(0f, 0f);
            tailRect.anchoredPosition = new Vector2(236f, -6f);
            tailRect.sizeDelta = new Vector2(110f, 70f);

            // The name, large and bold: it is easy to read from afar who is speaking.
            TextMeshProUGUI speaker = NewText("Speaker", _invitationRect, _display, 34f, Brand);
            speaker.text = invitationSpeaker;
            speaker.characterSpacing = 12f;
            speaker.alignment = TextAlignmentOptions.Center;
            Thicken(speaker, 0.12f);

            TextMeshProUGUI line = NewText("Invitation", _invitationRect, _display, 62f, Navy);
            line.text = invitation;
            line.characterSpacing = -2.5f;
            line.lineSpacing = -22f;
            line.alignment = TextAlignmentOptions.Center;
            line.textWrappingMode = TextWrappingModes.Normal;
        }

        private void BuildSubtitles(RectTransform parent)
        {
            _subtitleGroup = NewGroup("Subtitles", parent);
            RectTransform block = (RectTransform)_subtitleGroup.transform;
            block.anchorMin = new Vector2(0.5f, 0f);
            block.anchorMax = new Vector2(0.5f, 0f);
            block.pivot = new Vector2(0.5f, 0f);
            block.anchoredPosition = new Vector2(0f, 96f);
            block.sizeDelta = new Vector2(968f, 0f);
            VerticalLayoutGroup stack = block.gameObject.AddComponent<VerticalLayoutGroup>();
            stack.spacing = 34f;
            stack.childAlignment = TextAnchor.LowerCenter;
            stack.childControlWidth = true;
            stack.childControlHeight = true;
            stack.childForceExpandWidth = true;
            stack.childForceExpandHeight = false;
            ContentSizeFitter fitter = block.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            // Pill for the user, centered above the avatar text.
            RectTransform holder = NewRect("User", block);
            HorizontalLayoutGroup center = holder.gameObject.AddComponent<HorizontalLayoutGroup>();
            center.childAlignment = TextAnchor.MiddleCenter;
            center.childControlWidth = true;
            center.childControlHeight = true;
            center.childForceExpandWidth = false;
            center.childForceExpandHeight = false;
            _visitorGroup = holder.gameObject.AddComponent<CanvasGroup>();
            _visitorGroup.alpha = 0f;

            // Dark: over a light outfit a translucent white one was hard to read.
            RectTransform pill = NewRect("Pill", holder);
            Image face = pill.gameObject.AddComponent<Image>();
            ConfigureRound(face, new Color(Dark.r, Dark.g, Dark.b, 0.78f), 34f);
            HorizontalLayoutGroup row = pill.gameObject.AddComponent<HorizontalLayoutGroup>();
            row.padding = new RectOffset(26, 26, 14, 14);
            row.spacing = 12f;
            row.childAlignment = TextAnchor.MiddleCenter;
            row.childControlWidth = true;
            row.childControlHeight = true;
            row.childForceExpandWidth = false;
            row.childForceExpandHeight = false;

            TextMeshProUGUI label = NewText("Label", pill, _mono, 18f, new Color(1f, 1f, 1f, 0.75f));
            label.text = "YOU";
            label.characterSpacing = 14f;
            label.alignment = TextAlignmentOptions.Midline;

            _visitorText = NewText("Text", pill, _semibold, 32f, Color.white);
            _visitorText.alignment = TextAlignmentOptions.MidlineLeft;
            _visitorText.textWrappingMode = TextWrappingModes.Normal;
            _visitorTextLayout = _visitorText.gameObject.AddComponent<LayoutElement>();

            // What the avatar says: large, centered, no box.
            _soniaText = NewText("Sonia", block, _display, subtitleSize, Color.white);
            _soniaText.alignment = TextAlignmentOptions.Bottom;
            _soniaText.textWrappingMode = TextWrappingModes.Normal;
            _soniaText.characterSpacing = -1.5f;
            _soniaText.lineSpacing = -20f;
            _soniaText.richText = true;

            // Soft shadow hugging the letters: the text goes over the outfit.
            Material material = _soniaText.fontMaterial;
            material.EnableKeyword(ShaderUtilities.Keyword_Underlay);
            material.SetColor(ShaderUtilities.ID_UnderlayColor, new Color(0f, 0f, 0f, 0.65f));
            material.SetFloat(ShaderUtilities.ID_UnderlaySoftness, 0.6f);
            material.SetFloat(ShaderUtilities.ID_UnderlayDilate, 0.35f);
            material.SetFloat(ShaderUtilities.ID_UnderlayOffsetY, -0.5f);
            _soniaText.fontMaterial = material;
        }

        /// <summary>
        /// Extra darkening behind the subtitles, taller than the permanent shade:
        /// it turns on with them.
        /// </summary>
        private void BuildConversationScrim(RectTransform parent)
        {
            Sprite scrim = LoadSprite("stage-scrim", Vector4.zero);
            _conversationScrim = NewImage("ConversationShade", parent, scrim, new Color(Dark.r, Dark.g, Dark.b, 0f));
            _conversationScrim.enabled = bottomShade;
            RectTransform rect = _conversationScrim.rectTransform;
            rect.anchorMin = new Vector2(0f, 0f);
            rect.anchorMax = new Vector2(1f, 0f);
            rect.pivot = new Vector2(0.5f, 0f);
            rect.anchoredPosition = Vector2.zero;
            rect.sizeDelta = new Vector2(0f, 1000f);
        }

        // ------------------------------------------------------------------
        // Pieces
        // ------------------------------------------------------------------

        private RectTransform NewRect(string name, Transform parent)
        {
            GameObject go = new GameObject(name, typeof(RectTransform));
            go.layer = _hud != null ? _hud.gameObject.layer : parent.gameObject.layer;
            go.transform.SetParent(parent, false);
            return (RectTransform)go.transform;
        }

        private CanvasGroup NewGroup(string name, RectTransform parent)
        {
            RectTransform rect = NewRect(name, parent);
            Stretch(rect);
            CanvasGroup group = rect.gameObject.AddComponent<CanvasGroup>();
            group.interactable = false;
            group.blocksRaycasts = false;
            return group;
        }

        private Image NewImage(string name, RectTransform parent, Sprite sprite, Color color)
        {
            RectTransform rect = NewRect(name, parent);
            Image image = rect.gameObject.AddComponent<Image>();
            image.sprite = sprite;
            image.color = color;
            image.raycastTarget = false;
            return image;
        }

        private TextMeshProUGUI NewText(string name, RectTransform parent, TMP_FontAsset font, float size, Color color)
        {
            RectTransform rect = NewRect(name, parent);
            TextMeshProUGUI text = rect.gameObject.AddComponent<TextMeshProUGUI>();
            if (font != null)
            {
                text.font = font;
            }

            text.fontSize = size;
            text.color = color;
            text.raycastTarget = false;
            text.textWrappingMode = TextWrappingModes.NoWrap;
            text.overflowMode = TextOverflowModes.Overflow;
            return text;
        }

        /// <summary>Rounded rectangle from the radius-64 sprite with the requested radius.</summary>
        private void ConfigureRound(Image image, Color color, float radius)
        {
            image.sprite = _round;
            image.type = Image.Type.Sliced;
            image.pixelsPerUnitMultiplier = 64f / Mathf.Max(1f, radius);
            image.color = color;
            image.raycastTarget = false;
        }

        /// <summary>So it does not count for the size computed by its parent group.</summary>
        private static void IgnoreLayout(RectTransform rect)
        {
            rect.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;
        }

        /// <summary>
        /// Thickens the stroke of dark text on white. With the project linear color
        /// space, TextMeshPro draws that text thinner than the font
        /// (measured: ExtraBold at 23 px came out with 2.7 px strokes instead of 3.5).
        /// </summary>
        private static void Thicken(TextMeshProUGUI text, float dilate)
        {
            Material material = text.fontMaterial;
            material.SetFloat(ShaderUtilities.ID_FaceDilate, dilate);
            text.fontMaterial = material;
        }

        /// <summary>Shrinks the text down to <paramref name="min"/> if it does not fit at <paramref name="max"/>.</summary>
        private static void FitToWidth(TextMeshProUGUI text, float min, float max)
        {
            text.enableAutoSizing = true;
            text.fontSizeMin = min;
            text.fontSizeMax = max;
        }

        private static void Stretch(RectTransform rect)
        {
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
        }

        private static void PlaceTopLeft(RectTransform rect, Vector2 offset, Vector2 size)
        {
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(0f, 1f);
            rect.pivot = new Vector2(0f, 1f);
            rect.anchoredPosition = new Vector2(offset.x, -offset.y);
            rect.sizeDelta = size;
        }

        private static void PlaceTopStretch(RectTransform rect, float top, float height)
        {
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(1f, 1f);
            rect.pivot = new Vector2(0.5f, 1f);
            rect.anchoredPosition = new Vector2(0f, -top);
            rect.sizeDelta = new Vector2(-24f, height);
        }
    }
}
