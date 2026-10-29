// Trivia mode on screen: the question with its options A, B and C, the right
// answer in green and the wrong one in red with confetti, the scoreboard and the
// final screen.
//
// The game is run by the orchestrator and the realtime model; here only what
// arrives through the protocol (trivia_start, trivia_question, trivia_answer and
// trivia_end) is drawn and the avatar gets its reaction: gesture and face.
//
// Everything is built in code inside the HUD Canvas (SoniaHUD, Screen Space -
// Camera over the HUD camera, without post-processing), like the away sign: it
// shows in the 9:16 captures and in the build, without prefabs.
//
// Design for the vertical monitor (1080x1920 reference):
//  - The card goes in the top strip, the same as the image panel, and the
//    camera moves to the panel shot (a bit further back) so it does not cover the
//    face. The subtitles at the bottom stay free.
//  - "TRIVIA" header with the letters in playful party colors and a row of dots
//    with the progress (green right, red wrong, white the current one).
//  - Large options, readable from several meters, with the letter in a circle.
//  - Right answer: the option fills with green with a circle with the check, a
//    "Correct!" banner appears and a burst of confetti and sparkles comes from it.
//  - Wrong answer: the chosen one turns red and shakes, the right one is marked
//    in green.
//  - End: large card with the result; if the user wins, a confetti rain.
//  - No colored light frame on the edges and no tinted scene.

using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Draws the trivia on the HUD and makes the avatar react.</summary>
    [DisallowMultipleComponent]
    public class TriviaController : MonoBehaviour
    {
        [Header("Avatar gestures (clips of the set)")]
        [SerializeField]
        [Tooltip("When the trivia starts. Empty: none.")]
        private string startClip = "";

        [SerializeField]
        [Tooltip("On a right answer. If it is not in the set, the fallback one is used.")]
        private string correctClip = "QuickAction_twoThumbsUp";

        [SerializeField]
        private string correctFallbackClip = "Peace";

        [SerializeField]
        [Tooltip("On a wrong answer or not knowing it. Empty: none (face only).")]
        private string wrongClip = "";

        [SerializeField]
        [Tooltip("When the game is won.")]
        private string winClip = "QuickAction_vibe";

        [SerializeField]
        [Tooltip("When the game is lost: encouragement. If it is not in the set, the fallback one is used.")]
        private string loseClip = "QuickAction_salute";

        [SerializeField]
        private string loseFallbackClip = "Peace";

        [Header("Layout (pixels at the 1080x1920 reference)")]
        [SerializeField]
        [Tooltip("Width of the question card.")]
        private float cardWidth = 960f;

        [SerializeField]
        [Range(0f, 0.5f)]
        [Tooltip("Distance from the top edge of the card to the top of the screen, as a fraction of the height.")]
        private float cardTop = 0.105f;

        [SerializeField]
        [Tooltip("Size of the question text.")]
        private float questionSize = 50f;

        [SerializeField]
        [Tooltip("Fixed height of the question (up to three lines; the text shrinks if it does not fit). This way the card is always the same size and does not cover the avatar.")]
        private float questionHeight = 150f;

        [SerializeField]
        [Tooltip("Size of the option text.")]
        private float optionSize = 40f;

        [SerializeField]
        [Tooltip("Height of each option.")]
        private float optionHeight = 98f;

        [SerializeField]
        [Tooltip("Ask the camera for the panel shot while a trivia is on (avatar a bit further back, card on top).")]
        private bool usePanelShot = true;

        [SerializeField]
        [Tooltip("Extra camera offset over the panel shot (meters): higher and further back so the avatar fits under the card.")]
        private Vector3 panelShotExtra = new Vector3(0f, 0.3f, -0.8f);

        [Header("Timing")]
        [SerializeField]
        [Range(2f, 30f)]
        [Tooltip("Seconds the final screen stays before the trivia is removed.")]
        private float endScreenSeconds = 9f;

        [SerializeField]
        [Range(0.5f, 10f)]
        [Tooltip("After reconnecting to the orchestrator, if trivia_start does not arrive again in this time, the game no longer exists and is removed.")]
        private float replayGraceSeconds = 2.5f;

        [SerializeField]
        [Tooltip("Write the trivia events to the console.")]
        private bool logEvents = true;

        private const string HudCanvasName = "SoniaHUD";
        private const int CornerRadius = 36;

        /// <summary>Seconds between the question card leaving and the result card arriving.</summary>
        private const float ResultDelay = 0.35f;

        // Party colors and card colors.
        private static readonly Color Blue = new Color(0.259f, 0.522f, 0.957f);
        private static readonly Color Red = new Color(0.918f, 0.263f, 0.208f);
        private static readonly Color Yellow = new Color(0.984f, 0.737f, 0.02f);
        private static readonly Color Green = new Color(0.204f, 0.659f, 0.325f);
        private static readonly Color[] PartyColors = { Blue, Red, Yellow, Green };
        private static readonly Color CardFill = new Color(0.035f, 0.07f, 0.15f, 0.93f);
        private static readonly Color OptionFill = new Color(0.1f, 0.16f, 0.3f, 0.96f);
        private static readonly Color RightFill = new Color(0.12f, 0.56f, 0.27f, 1f);
        private static readonly Color WrongFill = new Color(0.8f, 0.2f, 0.17f, 1f);
        private static readonly Color Muted = new Color(0.68f, 0.75f, 0.88f, 1f);

        private enum DotState
        {
            Pending,
            Current,
            Right,
            Wrong
        }

        private sealed class OptionView
        {
            public RectTransform Row;
            public RectTransform Inner;
            public Image Fill;
            public Image Border;
            public Image Badge;
            public TextMeshProUGUI Letter;
            public TextMeshProUGUI Text;
            public Image Mark;
            public float MarkPop = -1f;
            public float Shake = -1f;
            public float Pulse = -1f;
            public Color FillFrom;
            public Color FillTo;
            public float FillT = 1f;
            public float Alpha = 1f;
            public float AlphaTarget = 1f;
        }

        private sealed class Piece
        {
            public RectTransform Rect;
            public Image Image;
            public Vector2 Velocity;
            public float Spin;
            public float Angle;
            public float Flip;
            public float FlipSpeed;
            public float Age;
            public float Life;
            public bool Sparkle;
            public float Size;
        }

        private SoniaClient _client;
        private AvatarChoreographer _choreographer;
        private FacialExpressionController _face;
        private CameraFramingController _framing;
        private Canvas _canvas;
        private TMP_FontAsset _font;
        private bool _warnedNoCanvas;

        // Construction.
        private RectTransform _root;
        private CanvasGroup _rootGroup;
        private RectTransform _card;
        private CanvasGroup _cardGroup;
        private TextMeshProUGUI _eyebrow;
        private TextMeshProUGUI _counter;

        /// <summary>Game level for the counter ("QUESTION 2 OF 5 · HARD").</summary>
        private string _level = string.Empty;
        private TextMeshProUGUI _question;
        private readonly List<Image> _dots = new List<Image>();
        private readonly List<DotState> _dotStates = new List<DotState>();
        private RectTransform _dotsRow;
        private readonly OptionView[] _options = new OptionView[3];
        private RectTransform _banner;
        private TextMeshProUGUI _bannerText;
        private Image _bannerFill;
        private RectTransform _result;
        private CanvasGroup _resultGroup;
        private TextMeshProUGUI _resultTitle;
        private TextMeshProUGUI _resultScore;
        private TextMeshProUGUI _resultLine;
        private readonly List<Image> _resultStars = new List<Image>();
        private RectTransform _effects;

        private Sprite _roundSprite;
        private Sprite _glowSprite;
        private Sprite _dotSprite;
        private Sprite _checkSprite;
        private Sprite _crossSprite;
        private Sprite _sparkleSprite;
        private Sprite _starSprite;
        private Sprite _pieceSprite;
        private readonly List<Texture2D> _textures = new List<Texture2D>();
        private readonly List<Sprite> _sprites = new List<Sprite>();

        // Game state.
        private bool _active;
        private int _total = 5;
        private int _threshold = 3;
        private int _number;
        private int _score;
        private bool _ending;
        private float _endAt;
        private float _awaitReplayUntil = -1f;

        // Animation.
        private float _clock;
        private float _rootAlpha;
        private float _cardAppear = -1f;
        private bool _cardShown;
        private float _cardAlpha;
        private float _bannerAt = -1f;
        private float _resultAt = -1f;
        private bool _resultShown;
        private float _resultAlpha;
        private float _rainUntil = -1f;
        private float _rainAccumulator;
        private readonly List<Piece> _pieces = new List<Piece>();
        private readonly Stack<Piece> _pool = new Stack<Piece>();

        /// <summary>True while a trivia is on screen (also the final screen).</summary>
        public bool IsActive
        {
            get { return _active; }
        }

        private void Awake()
        {
            _client = GetComponentInChildren<SoniaClient>(true);
            _choreographer = GetComponentInChildren<AvatarChoreographer>(true);
            _face = GetComponentInChildren<FacialExpressionController>(true);
            _framing = GetComponentInChildren<CameraFramingController>(true);
        }

        private void OnEnable()
        {
            if (_client == null)
            {
                return;
            }

            _client.OnHello += HandleHello;
            _client.OnTriviaStart += HandleStart;
            _client.OnTriviaQuestion += HandleQuestion;
            _client.OnTriviaAnswer += HandleAnswer;
            _client.OnTriviaEnd += HandleEnd;
        }

        private void OnDisable()
        {
            if (_client == null)
            {
                return;
            }

            _client.OnHello -= HandleHello;
            _client.OnTriviaStart -= HandleStart;
            _client.OnTriviaQuestion -= HandleQuestion;
            _client.OnTriviaAnswer -= HandleAnswer;
            _client.OnTriviaEnd -= HandleEnd;
        }

        private void Start()
        {
            // Built right away (hidden) so appearing costs nothing.
            Build();
        }

        private void OnDestroy()
        {
            foreach (Sprite sprite in _sprites)
            {
                if (sprite != null)
                {
                    Destroy(sprite);
                }
            }

            foreach (Texture2D texture in _textures)
            {
                if (texture != null)
                {
                    Destroy(texture);
                }
            }
        }

        // ------------------------------------------------------------------
        // Protocol messages
        // ------------------------------------------------------------------

        private void HandleHello(HelloMessage message)
        {
            // If the game ended while there was no connection, the orchestrator will
            // not repeat trivia_start: after the grace period it is removed.
            if (_active && !_ending)
            {
                _awaitReplayUntil = Time.unscaledTime + replayGraceSeconds;
            }
        }

        private void HandleStart(TriviaStartMessage message)
        {
            if (message == null)
            {
                return;
            }

            _awaitReplayUntil = -1f;
            bool replay = _active && !_ending;
            _total = Mathf.Clamp(message.Total, 1, 20);
            _threshold = Mathf.Clamp(message.Threshold, 1, _total);
            _level = (message.Level ?? string.Empty).Trim();
            if (replay)
            {
                return;
            }

            Build();
            _active = true;
            _ending = false;
            _number = 0;
            _score = 0;
            _resultShown = false;
            _cardShown = false;
            _rainUntil = -1f;
            ResetDots();
            if (_root != null)
            {
                _root.gameObject.SetActive(true);
            }

            if (_framing != null && usePanelShot)
            {
                _framing.PanelRequestOffset = panelShotExtra;
                _framing.PanelRequested = true;
            }

            if (_choreographer != null)
            {
                _choreographer.GreetingSuppressed = true;
            }

            PlayClip(startClip, null);
            ShowEmotion(FacialExpressionController.Emotion.Joy, 2f);
            Burst(new Vector2(0f, 300f), 40, 900f);
            Log("trivia starts: " + _total + " questions, wins with " + _threshold);
        }

        private void HandleQuestion(TriviaQuestionMessage message)
        {
            if (message == null || message.Options == null || message.Options.Length < 3)
            {
                return;
            }

            if (!_active || _ending)
            {
                // Question without trivia_start (old client or crossed messages): start anyway.
                HandleStart(new TriviaStartMessage { Total = message.Total, Threshold = _threshold });
            }

            _awaitReplayUntil = -1f;
            _total = Mathf.Clamp(message.Total, 1, 20);
            _number = Mathf.Clamp(message.Number, 1, _total);
            _score = Mathf.Clamp(message.Score, 0, _total);
            Build();
            if (_card == null)
            {
                return;
            }

            // Dots: already answered ones that do not add up (after reconnecting) are
            // filled with the right ones first.
            EnsureDots(_total);
            int answered = _number - 1;
            int right = 0;
            for (int i = 0; i < answered; i++)
            {
                if (_dotStates[i] == DotState.Right)
                {
                    right++;
                }
            }

            for (int i = 0; i < _dotStates.Count; i++)
            {
                if (i < answered)
                {
                    if (_dotStates[i] != DotState.Right && _dotStates[i] != DotState.Wrong)
                    {
                        _dotStates[i] = right < _score ? DotState.Right : DotState.Wrong;
                        if (_dotStates[i] == DotState.Right)
                        {
                            right++;
                        }
                    }
                }
                else
                {
                    _dotStates[i] = i == answered ? DotState.Current : DotState.Pending;
                }
            }

            _counter.text = "QUESTION " + _number + " OF " + _total
                            + (_level.Length > 0 ? " · " + _level.ToUpperInvariant() : string.Empty);
            _question.text = message.Question ?? string.Empty;
            for (int i = 0; i < _options.Length; i++)
            {
                OptionView option = _options[i];
                option.Text.text = message.Options[i] ?? string.Empty;
                option.Fill.color = OptionFill;
                option.FillFrom = OptionFill;
                option.FillTo = OptionFill;
                option.FillT = 1f;
                option.Border.color = WithAlpha(Color.white, 0.18f);
                option.Mark.gameObject.SetActive(false);
                option.MarkPop = -1f;
                option.Shake = -1f;
                option.Pulse = -1f;
                option.Alpha = 0f;
                option.AlphaTarget = 1f;
                option.Inner.anchoredPosition = Vector2.zero;
                option.Inner.localScale = Vector3.one;
            }

            _bannerAt = -1f;
            _banner.gameObject.SetActive(false);
            _cardShown = true;
            _cardAppear = _clock;
            RefreshLayout();
            Log("question " + _number + "/" + _total);
        }

        private void HandleAnswer(TriviaAnswerMessage message)
        {
            if (message == null || !_active || _card == null)
            {
                return;
            }

            int correct = Mathf.Clamp(message.Correct, 0, 2);
            int chosen = message.Chosen;
            _score = Mathf.Clamp(message.Score, 0, _total);
            int index = Mathf.Clamp(message.Number, 1, _total) - 1;
            EnsureDots(_total);
            _dotStates[index] = message.IsCorrect ? DotState.Right : DotState.Wrong;

            for (int i = 0; i < _options.Length; i++)
            {
                OptionView option = _options[i];
                bool isCorrect = i == correct;
                bool isChosen = i == chosen;
                if (isCorrect)
                {
                    option.FillFrom = option.Fill.color;
                    option.FillTo = RightFill;
                    option.FillT = 0f;
                    option.Border.color = WithAlpha(new Color(0.75f, 1f, 0.8f), 0.9f);
                    option.Mark.sprite = _checkSprite;
                    option.Mark.gameObject.SetActive(true);
                    option.MarkPop = _clock + (message.IsCorrect ? 0f : 0.35f);
                    option.Pulse = _clock;
                    option.AlphaTarget = 1f;
                }
                else if (isChosen)
                {
                    option.FillFrom = option.Fill.color;
                    option.FillTo = WrongFill;
                    option.FillT = 0f;
                    option.Border.color = WithAlpha(new Color(1f, 0.75f, 0.72f), 0.9f);
                    option.Mark.sprite = _crossSprite;
                    option.Mark.gameObject.SetActive(true);
                    option.MarkPop = _clock;
                    option.Shake = _clock;
                    option.AlphaTarget = 1f;
                }
                else
                {
                    option.AlphaTarget = 0.4f;
                }
            }

            string letter = "ABC".Substring(correct, 1);
            if (message.IsCorrect)
            {
                SetBanner("Correct!", Green);
                Vector2 at = EffectsPoint(_options[correct].Row);
                Burst(at, 90, 1300f);
                Sparkles(at, 10);
                PlayClip(correctClip, correctFallbackClip);
                ShowEmotion(FacialExpressionController.Emotion.Joy, 3f);
            }
            else
            {
                SetBanner(chosen < 0 ? "It was " + letter : "Oops! It was " + letter, Red);
                PlayClip(wrongClip, null);
                ShowEmotion(FacialExpressionController.Emotion.Sad, 2.4f);
            }

            Log("answer " + message.Number + ": " + (message.IsCorrect ? "right" : "wrong") + " (" + _score + ")");
        }

        private void HandleEnd(TriviaEndMessage message)
        {
            if (message == null || !_active)
            {
                return;
            }

            _awaitReplayUntil = -1f;
            bool cancelled = message.Reason == "cancelled";
            if (cancelled)
            {
                Log("trivia cancelled");
                Finish();
                return;
            }

            _score = Mathf.Clamp(message.Score, 0, Mathf.Max(1, message.Total));
            _total = Mathf.Max(1, message.Total);
            ShowResult(message.Won);
            _ending = true;
            _endAt = _clock + endScreenSeconds;
            if (message.Won)
            {
                PlayClip(winClip, null);
                ShowEmotion(FacialExpressionController.Emotion.Joy, 5f);
                _rainUntil = _clock + 5.5f;
                Burst(new Vector2(-420f, -700f), 80, 1700f, 60f);
                Burst(new Vector2(420f, -700f), 80, 1700f, 120f);
            }
            else
            {
                PlayClip(loseClip, loseFallbackClip);
                ShowEmotion(FacialExpressionController.Emotion.Joy, 2f);
                Sparkles(EffectsPoint(_result), 8);
            }

            Log("trivia ended: " + _score + " of " + _total + (message.Won ? ", wins" : ", loses"));
        }

        /// <summary>Removes the trivia from the screen: cards out and camera shot released.</summary>
        private void Finish()
        {
            _active = false;
            _ending = false;
            _cardShown = false;
            _resultShown = false;
            _rainUntil = -1f;
            _bannerAt = -1f;
            if (_framing != null)
            {
                _framing.PanelRequested = false;
            }

            if (_choreographer != null)
            {
                _choreographer.GreetingSuppressed = false;
            }
        }

        // ------------------------------------------------------------------
        // Avatar reactions
        // ------------------------------------------------------------------

        private void PlayClip(string clipName, string fallback)
        {
            if (_choreographer == null)
            {
                return;
            }

            SoniaMotionSet set = _choreographer.MotionSet;
            AnimationCatalog.Entry entry;
            if (!AnimationCatalog.TryFind(set, clipName, out entry)
                && !AnimationCatalog.TryFind(set, fallback, out entry))
            {
                return;
            }

            _choreographer.PlayReaction(entry.Clip);
        }

        private void ShowEmotion(FacialExpressionController.Emotion emotion, float seconds)
        {
            if (_face != null)
            {
                _face.ShowEmotion(emotion, seconds);
            }
        }

        // ------------------------------------------------------------------
        // Animation
        // ------------------------------------------------------------------

        private void Update()
        {
            if (_root == null)
            {
                return;
            }

            float dt = Time.deltaTime;
            _clock += dt;

            if (_awaitReplayUntil > 0f && Time.unscaledTime > _awaitReplayUntil)
            {
                _awaitReplayUntil = -1f;
                Log("the trivia did not come back after reconnecting: removing it");
                Finish();
            }

            if (_ending && _clock >= _endAt)
            {
                Finish();
            }

            bool visible = _active || _cardAlpha > 0.001f || _resultAlpha > 0.001f || _pieces.Count > 0;
            if (!visible)
            {
                if (_root.gameObject.activeSelf)
                {
                    _root.gameObject.SetActive(false);
                }

                return;
            }

            if (!_root.gameObject.activeSelf)
            {
                _root.gameObject.SetActive(true);
            }

            _rootAlpha = Mathf.MoveTowards(_rootAlpha, 1f, dt * 3f);
            _rootGroup.alpha = _rootAlpha;

            AnimateCard(dt);
            AnimateOptions(dt);
            AnimateDots();
            AnimateBanner();
            AnimateResult(dt);
            AnimatePieces(dt);
        }

        private void AnimateCard(float dt)
        {
            if (_card == null)
            {
                return;
            }

            bool show = _cardShown && !_resultShown;
            _cardAlpha = Mathf.MoveTowards(_cardAlpha, show ? 1f : 0f, dt / (show ? 0.35f : 0.3f));
            _cardGroup.alpha = _cardAlpha;
            _card.gameObject.SetActive(_cardAlpha > 0.001f);
            float appear = _cardAppear >= 0f ? Mathf.Clamp01((_clock - _cardAppear) / 0.5f) : 1f;
            float scale = Mathf.Lerp(0.9f, 1f, EaseOutBack(appear)) * Mathf.Lerp(0.96f, 1f, _cardAlpha);
            _card.localScale = new Vector3(scale, scale, 1f);
        }

        private void AnimateOptions(float dt)
        {
            for (int i = 0; i < _options.Length; i++)
            {
                OptionView option = _options[i];
                if (option == null)
                {
                    continue;
                }

                // Staggered entrance: each option arrives from the right.
                float delay = 0.18f + (i * 0.09f);
                float t = _cardAppear >= 0f ? Mathf.Clamp01((_clock - _cardAppear - delay) / 0.35f) : 1f;
                float slide = (1f - EaseOutCubic(t)) * 80f;

                option.Alpha = Mathf.MoveTowards(option.Alpha, option.AlphaTarget * t, dt * 3f);
                CanvasGroup group = option.Row.GetComponent<CanvasGroup>();
                group.alpha = option.Alpha;

                if (option.FillT < 1f)
                {
                    option.FillT = Mathf.Min(1f, option.FillT + (dt / 0.25f));
                    option.Fill.color = Color.Lerp(option.FillFrom, option.FillTo, option.FillT);
                }

                float shake = 0f;
                if (option.Shake >= 0f)
                {
                    float s = _clock - option.Shake;
                    shake = s < 0.55f ? Mathf.Sin(s * 46f) * 16f * (1f - (s / 0.55f)) : 0f;
                }

                float pulse = 1f;
                if (option.Pulse >= 0f)
                {
                    float s = _clock - option.Pulse;
                    pulse = 1f + (s < 0.35f ? 0.06f * Mathf.Sin(s / 0.35f * Mathf.PI) : 0.012f * Mathf.Sin(s * 5f));
                }

                option.Inner.anchoredPosition = new Vector2(slide + shake, 0f);
                option.Inner.localScale = new Vector3(pulse, pulse, 1f);

                if (option.MarkPop >= 0f && option.Mark.gameObject.activeSelf)
                {
                    float s = Mathf.Clamp01((_clock - option.MarkPop) / 0.4f);
                    float markScale = _clock < option.MarkPop ? 0f : EaseOutBack(s);
                    option.Mark.rectTransform.localScale = new Vector3(markScale, markScale, 1f);
                }
            }
        }

        private void AnimateDots()
        {
            for (int i = 0; i < _dots.Count; i++)
            {
                Image dot = _dots[i];
                DotState state = i < _dotStates.Count ? _dotStates[i] : DotState.Pending;
                float scale = 1f;
                Color color;
                switch (state)
                {
                    case DotState.Right:
                        color = Green;
                        break;
                    case DotState.Wrong:
                        color = Red;
                        break;
                    case DotState.Current:
                        color = Color.white;
                        scale = 1f + (0.18f * (0.5f + (0.5f * Mathf.Sin(_clock * 5f))));
                        break;
                    default:
                        color = WithAlpha(Color.white, 0.25f);
                        break;
                }

                dot.color = color;
                dot.rectTransform.localScale = new Vector3(scale, scale, 1f);
            }
        }

        private void AnimateBanner()
        {
            if (_banner == null)
            {
                return;
            }

            if (_bannerAt < 0f || !_cardShown || _resultShown)
            {
                _banner.gameObject.SetActive(false);
                return;
            }

            float s = _clock - _bannerAt;
            _banner.gameObject.SetActive(true);
            float pop = EaseOutBack(Mathf.Clamp01(s / 0.35f));
            float wiggle = 1f + (0.02f * Mathf.Sin(s * 6f));
            _banner.localScale = new Vector3(pop * wiggle, pop * wiggle, 1f);
            _banner.localRotation = Quaternion.Euler(0f, 0f, -4f + (Mathf.Sin(s * 3f) * 1.5f));
        }

        private void AnimateResult(float dt)
        {
            if (_result == null)
            {
                return;
            }

            bool show = _resultShown && _clock >= _resultAt;
            _resultAlpha = Mathf.MoveTowards(_resultAlpha, show ? 1f : 0f, dt / (show ? 0.4f : 0.5f));
            _resultGroup.alpha = _resultAlpha;
            _result.gameObject.SetActive(_resultAlpha > 0.001f);
            if (_resultAt < 0f)
            {
                return;
            }

            float s = Mathf.Max(0f, _clock - _resultAt);
            float pop = EaseOutBack(Mathf.Clamp01(s / 0.55f));
            float breathe = 1f + (0.012f * Mathf.Sin(s * 2.4f));
            float scale = Mathf.Lerp(0.6f, 1f, pop) * breathe;
            _result.localScale = new Vector3(scale, scale, 1f);
            for (int i = 0; i < _resultStars.Count; i++)
            {
                float starT = Mathf.Clamp01((s - 0.35f - (i * 0.12f)) / 0.35f);
                float starScale = EaseOutBack(starT);
                _resultStars[i].rectTransform.localScale = new Vector3(starScale, starScale, 1f);
                _resultStars[i].rectTransform.localRotation = Quaternion.Euler(0f, 0f, (1f - starT) * 90f);
            }

            if (_resultTitle != null && _resultShown)
            {
                float hop = Mathf.Abs(Mathf.Sin(s * 4f)) * 6f * Mathf.Clamp01(1f - ((s - 3f) / 3f));
                _resultTitle.rectTransform.anchoredPosition = new Vector2(0f, hop);
            }
        }

        // ------------------------------------------------------------------
        // Confetti and sparkles
        // ------------------------------------------------------------------

        private void AnimatePieces(float dt)
        {
            if (_rainUntil > 0f && _clock < _rainUntil && _effects != null)
            {
                _rainAccumulator += dt * 55f;
                Vector2 size = _effects.rect.size;
                while (_rainAccumulator >= 1f)
                {
                    _rainAccumulator -= 1f;
                    Vector2 at = new Vector2(Random.Range(-0.5f, 0.5f) * size.x, (size.y * 0.5f) + 40f);
                    Spawn(at, new Vector2(Random.Range(-120f, 120f), Random.Range(-260f, -60f)), false);
                }
            }

            const float gravity = 1500f;
            for (int i = _pieces.Count - 1; i >= 0; i--)
            {
                Piece piece = _pieces[i];
                piece.Age += dt;
                if (piece.Age >= piece.Life)
                {
                    piece.Rect.gameObject.SetActive(false);
                    _pieces.RemoveAt(i);
                    _pool.Push(piece);
                    continue;
                }

                float fade = Mathf.Clamp01((piece.Life - piece.Age) / 0.6f);
                if (piece.Sparkle)
                {
                    float t = piece.Age / piece.Life;
                    float twinkle = Mathf.Sin(t * Mathf.PI);
                    piece.Rect.localScale = Vector3.one * twinkle;
                    piece.Angle += piece.Spin * dt;
                    piece.Rect.localRotation = Quaternion.Euler(0f, 0f, piece.Angle);
                    piece.Image.color = WithAlpha(piece.Image.color, twinkle);
                    continue;
                }

                // Paper pieces: they fall with air drag, spin and flip.
                piece.Velocity.y -= gravity * dt;
                piece.Velocity *= Mathf.Pow(0.35f, dt);
                piece.Velocity.x += Mathf.Sin((piece.Age * 5f) + piece.Flip) * 90f * dt;
                piece.Rect.anchoredPosition += piece.Velocity * dt;
                piece.Angle += piece.Spin * dt;
                piece.Rect.localRotation = Quaternion.Euler(0f, 0f, piece.Angle);
                float flip = Mathf.Cos((piece.Age * piece.FlipSpeed) + piece.Flip);
                piece.Rect.localScale = new Vector3(flip, 1f, 1f);
                piece.Image.color = WithAlpha(piece.Image.color, fade);
            }
        }

        /// <summary>Burst of paper pieces from <paramref name="at"/> (effects layer coordinates).</summary>
        private void Burst(Vector2 at, int count, float speed, float angleDeg = 90f)
        {
            if (_effects == null)
            {
                return;
            }

            for (int i = 0; i < count; i++)
            {
                float angle = (angleDeg + Random.Range(-38f, 38f)) * Mathf.Deg2Rad;
                float magnitude = speed * Random.Range(0.45f, 1f);
                Spawn(at, new Vector2(Mathf.Cos(angle), Mathf.Sin(angle)) * magnitude, false);
            }
        }

        private void Sparkles(Vector2 at, int count)
        {
            for (int i = 0; i < count; i++)
            {
                Vector2 offset = Random.insideUnitCircle * new Vector2(380f, 90f);
                Piece piece = Spawn(at + offset, Vector2.zero, true);
                if (piece != null)
                {
                    piece.Age = -Random.Range(0f, 0.5f);
                }
            }
        }

        private Piece Spawn(Vector2 at, Vector2 velocity, bool sparkle)
        {
            if (_effects == null || _pieces.Count > 420)
            {
                return null;
            }

            Piece piece = _pool.Count > 0 ? _pool.Pop() : CreatePiece();
            piece.Sparkle = sparkle;
            piece.Velocity = velocity;
            piece.Age = 0f;
            piece.Angle = Random.Range(0f, 360f);
            piece.Flip = Random.Range(0f, Mathf.PI * 2f);
            if (sparkle)
            {
                piece.Life = Random.Range(0.8f, 1.3f);
                piece.Spin = Random.Range(-90f, 90f);
                piece.Size = Random.Range(40f, 70f);
                piece.Image.sprite = _sparkleSprite;
                piece.Image.color = Random.value < 0.5f ? Color.white : Yellow;
                piece.Rect.sizeDelta = new Vector2(piece.Size, piece.Size);
            }
            else
            {
                piece.Life = Random.Range(2.2f, 3.6f);
                piece.Spin = Random.Range(-540f, 540f);
                piece.FlipSpeed = Random.Range(6f, 14f);
                bool round = Random.value < 0.25f;
                piece.Image.sprite = round ? _dotSprite : _pieceSprite;
                Color color = Random.value < 0.15f ? Color.white : PartyColors[Random.Range(0, PartyColors.Length)];
                piece.Image.color = color;
                piece.Rect.sizeDelta = round ? new Vector2(16f, 16f) : new Vector2(Random.Range(12f, 18f), Random.Range(22f, 32f));
            }

            piece.Rect.anchoredPosition = at;
            piece.Rect.localScale = sparkle ? Vector3.zero : Vector3.one;
            piece.Rect.gameObject.SetActive(true);
            _pieces.Add(piece);
            return piece;
        }

        private Piece CreatePiece()
        {
            GameObject go = new GameObject("Confetti", typeof(RectTransform));
            go.layer = _effects.gameObject.layer;
            go.transform.SetParent(_effects, false);
            Image image = go.AddComponent<Image>();
            image.raycastTarget = false;
            RectTransform rect = (RectTransform)go.transform;
            rect.anchorMin = new Vector2(0.5f, 0.5f);
            rect.anchorMax = new Vector2(0.5f, 0.5f);
            return new Piece { Rect = rect, Image = image };
        }

        private Vector2 EffectsPoint(RectTransform target)
        {
            if (target == null || _effects == null)
            {
                return Vector2.zero;
            }

            Vector3 local = _effects.InverseTransformPoint(target.position);
            return new Vector2(local.x, local.y);
        }

        // ------------------------------------------------------------------
        // Result and banners
        // ------------------------------------------------------------------

        private void SetBanner(string text, Color color)
        {
            if (_bannerText == null)
            {
                return;
            }

            _bannerText.text = text;
            _bannerFill.color = color;
            _bannerAt = _clock;
            LayoutRebuilder.ForceRebuildLayoutImmediate(_banner);
        }

        private void ShowResult(bool won)
        {
            Build();
            if (_result == null)
            {
                return;
            }

            _resultTitle.text = won ? "YOU WON!" : "SO CLOSE!";
            _resultTitle.colorGradient = won
                ? new VertexGradient(new Color(1f, 0.93f, 0.55f), new Color(1f, 0.93f, 0.55f), Yellow, new Color(1f, 0.62f, 0.1f))
                : new VertexGradient(Color.white, Color.white, new Color(0.75f, 0.85f, 1f), new Color(0.75f, 0.85f, 1f));
            _resultScore.text = _score + " of " + _total + " correct";
            _resultLine.text = won
                ? "Great job, trivia champ!"
                : "You needed " + _threshold + ". Ask me for another trivia and try again!";
            for (int i = 0; i < _resultStars.Count; i++)
            {
                bool lit = i < _score;
                _resultStars[i].gameObject.SetActive(i < _total);
                _resultStars[i].color = lit ? Yellow : WithAlpha(Color.white, 0.18f);
            }

            _resultShown = true;
            _resultAt = _clock + ResultDelay;
            RectTransform body = (RectTransform)_result.Find("Content");
            bool wasActive = _result.gameObject.activeSelf;
            _result.gameObject.SetActive(true);
            LayoutRebuilder.ForceRebuildLayoutImmediate(body);
            _result.sizeDelta = new Vector2(cardWidth, body.rect.height);
            _result.gameObject.SetActive(wasActive);
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

            _canvas = ResolveCanvas();
            if (_canvas == null)
            {
                if (!_warnedNoCanvas)
                {
                    _warnedNoCanvas = true;
                    Debug.LogWarning("[Sonnia] No HUD Canvas for the trivia.", this);
                }

                return;
            }

            CreateSprites();
            _font = FindFont(_canvas);

            GameObject root = new GameObject("Trivia", typeof(RectTransform), typeof(CanvasGroup));
            root.layer = _canvas.gameObject.layer;
            root.transform.SetParent(_canvas.transform, false);
            _root = (RectTransform)root.transform;
            Stretch(_root);
            _rootGroup = root.GetComponent<CanvasGroup>();
            _rootGroup.interactable = false;
            _rootGroup.blocksRaycasts = false;
            // Behind the subtitles and the rest of the HUD, in front of the logo.
            if (_canvas.name == HudCanvasName && _root.parent.childCount > 1)
            {
                _root.SetSiblingIndex(1);
            }

            BuildCard();
            BuildResult();

            GameObject effects = new GameObject("Effects", typeof(RectTransform));
            effects.layer = root.layer;
            effects.transform.SetParent(_root, false);
            _effects = (RectTransform)effects.transform;
            Stretch(_effects);

            root.SetActive(false);
        }

        private void BuildCard()
        {
            GameObject cardRoot = new GameObject("Card", typeof(RectTransform), typeof(CanvasGroup));
            cardRoot.layer = _root.gameObject.layer;
            cardRoot.transform.SetParent(_root, false);
            _card = (RectTransform)cardRoot.transform;
            _card.anchorMin = new Vector2(0.5f, 1f - cardTop);
            _card.anchorMax = _card.anchorMin;
            _card.pivot = new Vector2(0.5f, 1f);
            _card.sizeDelta = new Vector2(cardWidth, 0f);
            _cardGroup = cardRoot.GetComponent<CanvasGroup>();
            _cardGroup.alpha = 0f;

            GameObject border = MakeImage("Border", _card, _roundSprite, WithAlpha(new Color(0.44f, 0.66f, 1f), 0.55f));
            Stretch((RectTransform)border.transform);
            GameObject fill = MakeImage("Fill", _card, _roundSprite, CardFill);
            RectTransform fillRect = (RectTransform)fill.transform;
            Stretch(fillRect);
            fillRect.offsetMin = new Vector2(3f, 3f);
            fillRect.offsetMax = new Vector2(-3f, -3f);

            GameObject body = new GameObject("Content", typeof(RectTransform));
            body.layer = _card.gameObject.layer;
            body.transform.SetParent(_card, false);
            RectTransform bodyRect = (RectTransform)body.transform;
            bodyRect.anchorMin = new Vector2(0f, 1f);
            bodyRect.anchorMax = new Vector2(1f, 1f);
            bodyRect.pivot = new Vector2(0.5f, 1f);
            bodyRect.sizeDelta = Vector2.zero;
            VerticalLayoutGroup layout = body.AddComponent<VerticalLayoutGroup>();
            layout.padding = new RectOffset(44, 44, 34, 40);
            layout.spacing = 18f;
            layout.childAlignment = TextAnchor.UpperCenter;
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = false;
            ContentSizeFitter fitter = body.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            // Header: colored TRIVIA, the counter and the dots.
            GameObject header = new GameObject("Header", typeof(RectTransform));
            header.layer = body.layer;
            header.transform.SetParent(body.transform, false);
            HorizontalLayoutGroup headerRow = header.AddComponent<HorizontalLayoutGroup>();
            headerRow.spacing = 18f;
            headerRow.childAlignment = TextAnchor.MiddleLeft;
            headerRow.childControlWidth = true;
            headerRow.childControlHeight = true;
            headerRow.childForceExpandWidth = false;
            headerRow.childForceExpandHeight = false;
            header.AddComponent<LayoutElement>().preferredHeight = 46f;

            _eyebrow = MakeText("Title", header.transform, ColoredWord("TRIVIA"), 40f, Color.white, TextAlignmentOptions.Left);
            _eyebrow.fontStyle = FontStyles.Bold;
            _eyebrow.characterSpacing = 10f;
            _eyebrow.textWrappingMode = TextWrappingModes.NoWrap;

            _counter = MakeText("Counter", header.transform, "QUESTION 1 OF 5", 26f, Muted, TextAlignmentOptions.Left);
            _counter.fontStyle = FontStyles.Bold;
            _counter.characterSpacing = 4f;
            _counter.textWrappingMode = TextWrappingModes.NoWrap;
            _counter.gameObject.AddComponent<LayoutElement>().flexibleWidth = 1f;

            GameObject dots = new GameObject("Dots", typeof(RectTransform));
            dots.layer = body.layer;
            dots.transform.SetParent(header.transform, false);
            HorizontalLayoutGroup dotsRow = dots.AddComponent<HorizontalLayoutGroup>();
            dotsRow.spacing = 12f;
            dotsRow.childAlignment = TextAnchor.MiddleRight;
            dotsRow.childControlWidth = true;
            dotsRow.childControlHeight = true;
            dotsRow.childForceExpandWidth = false;
            dotsRow.childForceExpandHeight = false;
            _dotsRow = (RectTransform)dots.transform;

            _question = MakeText("Question", body.transform, string.Empty, questionSize, Color.white, TextAlignmentOptions.Center);
            _question.fontStyle = FontStyles.Bold;
            _question.lineSpacing = -6f;
            _question.enableAutoSizing = true;
            _question.fontSizeMin = questionSize * 0.72f;
            _question.fontSizeMax = questionSize;
            _question.verticalAlignment = VerticalAlignmentOptions.Middle;
            LayoutElement questionLayout = _question.gameObject.AddComponent<LayoutElement>();
            questionLayout.minHeight = questionHeight;
            questionLayout.preferredHeight = questionHeight;

            string[] letters = { "A", "B", "C" };
            Color[] letterColors = { Blue, Red, Green };
            for (int i = 0; i < _options.Length; i++)
            {
                _options[i] = BuildOption(body.transform, letters[i], letterColors[i]);
            }

            // Right or wrong banner, over the corner of the card.
            GameObject banner = new GameObject("Banner", typeof(RectTransform));
            banner.layer = _card.gameObject.layer;
            banner.transform.SetParent(_card, false);
            _banner = (RectTransform)banner.transform;
            _banner.anchorMin = new Vector2(0.5f, 0f);
            _banner.anchorMax = new Vector2(0.5f, 0f);
            _banner.pivot = new Vector2(0.5f, 0.5f);
            _banner.anchoredPosition = new Vector2(0f, -10f);
            HorizontalLayoutGroup bannerRow = banner.AddComponent<HorizontalLayoutGroup>();
            bannerRow.padding = new RectOffset(48, 48, 16, 18);
            bannerRow.childAlignment = TextAnchor.MiddleCenter;
            bannerRow.childControlWidth = true;
            bannerRow.childControlHeight = true;
            ContentSizeFitter bannerFit = banner.AddComponent<ContentSizeFitter>();
            bannerFit.horizontalFit = ContentSizeFitter.FitMode.PreferredSize;
            bannerFit.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            GameObject bannerFill = MakeImage("Fill", _banner, _roundSprite, Green);
            bannerFill.AddComponent<LayoutElement>().ignoreLayout = true;
            Stretch((RectTransform)bannerFill.transform);
            _bannerFill = bannerFill.GetComponent<Image>();
            _bannerText = MakeText("Text", _banner, "Correct!", 52f, Color.white, TextAlignmentOptions.Center);
            _bannerText.fontStyle = FontStyles.Bold;
            _bannerText.textWrappingMode = TextWrappingModes.NoWrap;
            banner.SetActive(false);

            EnsureDots(_total);
        }

        private OptionView BuildOption(Transform parent, string letter, Color letterColor)
        {
            OptionView view = new OptionView();
            GameObject row = new GameObject("Option" + letter, typeof(RectTransform), typeof(CanvasGroup));
            row.layer = parent.gameObject.layer;
            row.transform.SetParent(parent, false);
            view.Row = (RectTransform)row.transform;
            LayoutElement rowLayout = row.AddComponent<LayoutElement>();
            rowLayout.preferredHeight = optionHeight;
            rowLayout.minHeight = optionHeight;

            GameObject inner = new GameObject("Content", typeof(RectTransform));
            inner.layer = row.layer;
            inner.transform.SetParent(row.transform, false);
            view.Inner = (RectTransform)inner.transform;
            Stretch(view.Inner);

            view.Border = MakeImage("Border", view.Inner, _roundSprite, WithAlpha(Color.white, 0.18f)).GetComponent<Image>();
            Stretch(view.Border.rectTransform);
            view.Fill = MakeImage("Fill", view.Inner, _roundSprite, OptionFill).GetComponent<Image>();
            Stretch(view.Fill.rectTransform);
            view.Fill.rectTransform.offsetMin = new Vector2(3f, 3f);
            view.Fill.rectTransform.offsetMax = new Vector2(-3f, -3f);

            float badgeSize = optionHeight - 28f;
            view.Badge = MakeImage("Letter", view.Inner, _dotSprite, letterColor).GetComponent<Image>();
            RectTransform badge = view.Badge.rectTransform;
            badge.anchorMin = new Vector2(0f, 0.5f);
            badge.anchorMax = new Vector2(0f, 0.5f);
            badge.pivot = new Vector2(0f, 0.5f);
            badge.anchoredPosition = new Vector2(16f, 0f);
            badge.sizeDelta = new Vector2(badgeSize, badgeSize);
            view.Letter = MakeText("Text", badge, letter, badgeSize * 0.56f, Color.white, TextAlignmentOptions.Center);
            view.Letter.fontStyle = FontStyles.Bold;
            Stretch(view.Letter.rectTransform);

            view.Text = MakeText("Option", view.Inner, string.Empty, optionSize, Color.white, TextAlignmentOptions.Left);
            view.Text.fontStyle = FontStyles.Bold;
            view.Text.enableAutoSizing = true;
            view.Text.fontSizeMin = optionSize * 0.7f;
            view.Text.fontSizeMax = optionSize;
            RectTransform text = view.Text.rectTransform;
            text.anchorMin = Vector2.zero;
            text.anchorMax = Vector2.one;
            text.offsetMin = new Vector2(16f + badgeSize + 24f, 8f);
            text.offsetMax = new Vector2(-(badgeSize + 20f), -8f);

            view.Mark = MakeImage("Mark", view.Inner, _checkSprite, Color.white).GetComponent<Image>();
            RectTransform mark = view.Mark.rectTransform;
            mark.anchorMin = new Vector2(1f, 0.5f);
            mark.anchorMax = new Vector2(1f, 0.5f);
            mark.pivot = new Vector2(1f, 0.5f);
            mark.anchoredPosition = new Vector2(-16f, 0f);
            mark.sizeDelta = new Vector2(badgeSize, badgeSize);
            view.Mark.gameObject.SetActive(false);
            return view;
        }

        private void BuildResult()
        {
            GameObject resultRoot = new GameObject("Result", typeof(RectTransform), typeof(CanvasGroup));
            resultRoot.layer = _root.gameObject.layer;
            resultRoot.transform.SetParent(_root, false);
            _result = (RectTransform)resultRoot.transform;
            _result.anchorMin = new Vector2(0.5f, 1f - cardTop);
            _result.anchorMax = _result.anchorMin;
            _result.pivot = new Vector2(0.5f, 1f);
            _result.sizeDelta = new Vector2(cardWidth, 0f);
            _resultGroup = resultRoot.GetComponent<CanvasGroup>();
            _resultGroup.alpha = 0f;

            GameObject glow = MakeImage("Glow", _result, _glowSprite, WithAlpha(Yellow, 0.3f));
            RectTransform glowRect = (RectTransform)glow.transform;
            glowRect.anchorMin = Vector2.zero;
            glowRect.anchorMax = Vector2.one;
            glowRect.offsetMin = new Vector2(-80f, -80f);
            glowRect.offsetMax = new Vector2(80f, 80f);
            GameObject border = MakeImage("Border", _result, _roundSprite, WithAlpha(Yellow, 0.75f));
            Stretch((RectTransform)border.transform);
            GameObject fill = MakeImage("Fill", _result, _roundSprite, CardFill);
            Stretch((RectTransform)fill.transform);
            ((RectTransform)fill.transform).offsetMin = new Vector2(4f, 4f);
            ((RectTransform)fill.transform).offsetMax = new Vector2(-4f, -4f);

            GameObject body = new GameObject("Content", typeof(RectTransform));
            body.layer = _result.gameObject.layer;
            body.transform.SetParent(_result, false);
            RectTransform bodyRect = (RectTransform)body.transform;
            bodyRect.anchorMin = new Vector2(0f, 1f);
            bodyRect.anchorMax = new Vector2(1f, 1f);
            bodyRect.pivot = new Vector2(0.5f, 1f);
            VerticalLayoutGroup layout = body.AddComponent<VerticalLayoutGroup>();
            layout.padding = new RectOffset(56, 56, 40, 52);
            layout.spacing = 16f;
            layout.childAlignment = TextAnchor.UpperCenter;
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = false;
            body.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            TextMeshProUGUI eyebrow = MakeText("Title", body.transform, ColoredWord("TRIVIA"), 34f, Color.white, TextAlignmentOptions.Center);
            eyebrow.fontStyle = FontStyles.Bold;
            eyebrow.characterSpacing = 10f;

            GameObject titleBox = new GameObject("Result", typeof(RectTransform));
            titleBox.layer = body.layer;
            titleBox.transform.SetParent(body.transform, false);
            titleBox.AddComponent<LayoutElement>().preferredHeight = 150f;
            _resultTitle = MakeText("Text", titleBox.transform, "YOU WON!", 128f, Color.white, TextAlignmentOptions.Center);
            _resultTitle.fontStyle = FontStyles.Bold;
            _resultTitle.enableVertexGradient = true;
            _resultTitle.textWrappingMode = TextWrappingModes.NoWrap;
            Stretch(_resultTitle.rectTransform);

            GameObject stars = new GameObject("Stars", typeof(RectTransform));
            stars.layer = body.layer;
            stars.transform.SetParent(body.transform, false);
            HorizontalLayoutGroup starsRow = stars.AddComponent<HorizontalLayoutGroup>();
            starsRow.spacing = 18f;
            starsRow.childAlignment = TextAnchor.MiddleCenter;
            starsRow.childControlWidth = true;
            starsRow.childControlHeight = true;
            starsRow.childForceExpandWidth = false;
            starsRow.childForceExpandHeight = false;
            stars.AddComponent<LayoutElement>().preferredHeight = 96f;
            for (int i = 0; i < 10; i++)
            {
                Image star = MakeImage("Star" + i, stars.transform, _starSprite, Yellow).GetComponent<Image>();
                LayoutElement starLayout = star.gameObject.AddComponent<LayoutElement>();
                starLayout.preferredWidth = 88f;
                starLayout.preferredHeight = 88f;
                _resultStars.Add(star);
            }

            _resultScore = MakeText("Correct", body.transform, "4 of 5 correct", 58f, Color.white, TextAlignmentOptions.Center);
            _resultScore.fontStyle = FontStyles.Bold;
            _resultLine = MakeText("Line", body.transform, string.Empty, 38f, Muted, TextAlignmentOptions.Center);
            resultRoot.SetActive(false);
        }

        private void ResetDots()
        {
            for (int i = 0; i < _dotStates.Count; i++)
            {
                _dotStates[i] = DotState.Pending;
            }

            EnsureDots(_total);
        }

        private void EnsureDots(int count)
        {
            if (_dotsRow == null)
            {
                return;
            }

            while (_dots.Count < count)
            {
                Image dot = MakeImage("Dot" + _dots.Count, _dotsRow, _dotSprite, Color.white).GetComponent<Image>();
                LayoutElement dotLayout = dot.gameObject.AddComponent<LayoutElement>();
                dotLayout.preferredWidth = 26f;
                dotLayout.preferredHeight = 26f;
                _dots.Add(dot);
            }

            while (_dotStates.Count < _dots.Count)
            {
                _dotStates.Add(DotState.Pending);
            }

            for (int i = 0; i < _dots.Count; i++)
            {
                _dots[i].gameObject.SetActive(i < count);
            }
        }

        private void RefreshLayout()
        {
            if (_card == null)
            {
                return;
            }

            bool wasActive = _root.gameObject.activeSelf;
            bool cardActive = _card.gameObject.activeSelf;
            _root.gameObject.SetActive(true);
            _card.gameObject.SetActive(true);
            RectTransform body = (RectTransform)_card.Find("Content");
            LayoutRebuilder.ForceRebuildLayoutImmediate(body);
            _card.sizeDelta = new Vector2(cardWidth, body.rect.height);
            _card.gameObject.SetActive(cardActive);
            _root.gameObject.SetActive(wasActive);
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

        private TextMeshProUGUI MakeText(
            string name, Transform parent, string content, float size, Color color, TextAlignmentOptions alignment)
        {
            GameObject go = new GameObject(name, typeof(RectTransform));
            go.layer = parent.gameObject.layer;
            go.transform.SetParent(parent, false);
            TextMeshProUGUI text = go.AddComponent<TextMeshProUGUI>();
            if (_font != null)
            {
                text.font = _font;
            }

            text.richText = true;
            text.text = content;
            text.fontSize = size;
            text.color = color;
            text.alignment = alignment;
            text.textWrappingMode = TextWrappingModes.Normal;
            text.raycastTarget = false;
            return text;
        }

        /// <summary>A word with each letter in a party color, as rich text.</summary>
        private static string ColoredWord(string word)
        {
            System.Text.StringBuilder builder = new System.Text.StringBuilder();
            for (int i = 0; i < word.Length; i++)
            {
                Color color = PartyColors[i % PartyColors.Length];
                builder.Append("<color=#").Append(ColorUtility.ToHtmlStringRGB(color)).Append('>').Append(word[i]).Append("</color>");
            }

            return builder.ToString();
        }

        private static void Stretch(RectTransform rect)
        {
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
        }

        private static Color WithAlpha(Color color, float alpha)
        {
            color.a = alpha;
            return color;
        }

        private static float EaseOutBack(float t)
        {
            const float c1 = 1.70158f;
            const float c3 = c1 + 1f;
            float p = t - 1f;
            return 1f + (c3 * p * p * p) + (c1 * p * p);
        }

        private static float EaseOutCubic(float t)
        {
            float p = 1f - t;
            return 1f - (p * p * p);
        }

        private void Log(string message)
        {
            if (logEvents)
            {
                Debug.Log("[Sonnia] Trivia: " + message, this);
            }
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

            const int roundSize = 128;
            Texture2D round = MakeTexture("TriviaRound", roundSize, (x, y) =>
                Mathf.Clamp01(0.5f - RoundedRectDistance(x, y, roundSize, roundSize, 0f, CornerRadius)));
            float roundBorder = CornerRadius + 2f;
            _roundSprite = MakeSprite(round, new Vector4(roundBorder, roundBorder, roundBorder, roundBorder));

            const int glowSize = 256;
            const float glowSpread = 70f;
            Texture2D glow = MakeTexture("TriviaGlow", glowSize, (x, y) =>
            {
                float d = RoundedRectDistance(x, y, glowSize, glowSize, glowSpread, CornerRadius);
                float t = Mathf.Clamp01(1f - (d / glowSpread));
                return t * t * (3f - (2f * t));
            });
            float glowBorder = glowSpread + CornerRadius + 2f;
            _glowSprite = MakeSprite(glow, new Vector4(glowBorder, glowBorder, glowBorder, glowBorder));

            const int dotSize = 64;
            Texture2D dot = MakeTexture("TriviaDot", dotSize, (x, y) =>
            {
                float dx = x + 0.5f - (dotSize * 0.5f);
                float dy = y + 0.5f - (dotSize * 0.5f);
                return Mathf.Clamp01((dotSize * 0.5f) - 1f - Mathf.Sqrt((dx * dx) + (dy * dy)) + 0.5f);
            });
            _dotSprite = MakeSprite(dot, Vector4.zero);

            const int markSize = 128;
            _checkSprite = MakeSprite(MakeMark("TriviaCheck", markSize, Green, true), Vector4.zero);
            _crossSprite = MakeSprite(MakeMark("TriviaCross", markSize, Red, false), Vector4.zero);

            // Four-pointed sparkle (astroid).
            const int sparkleSize = 64;
            Texture2D sparkle = MakeTexture("TriviaSparkle", sparkleSize, (x, y) =>
            {
                float dx = Mathf.Abs((x + 0.5f - (sparkleSize * 0.5f)) / (sparkleSize * 0.5f));
                float dy = Mathf.Abs((y + 0.5f - (sparkleSize * 0.5f)) / (sparkleSize * 0.5f));
                float shape = Mathf.Pow(dx, 0.5f) + Mathf.Pow(dy, 0.5f);
                return Mathf.Clamp01((1f - shape) * 6f);
            });
            _sparkleSprite = MakeSprite(sparkle, Vector4.zero);

            // Five-pointed star.
            const int starSize = 128;
            Texture2D star = MakeTexture("TriviaStar", starSize, (x, y) =>
            {
                float px = (x + 0.5f - (starSize * 0.5f)) / (starSize * 0.5f);
                float py = (y + 0.5f - (starSize * 0.5f)) / (starSize * 0.5f);
                return Mathf.Clamp01(-StarDistance(px, py) * starSize * 0.5f + 0.5f);
            });
            _starSprite = MakeSprite(star, Vector4.zero);

            // Paper piece: rectangle with slightly rounded corners.
            const int pieceSize = 32;
            Texture2D piece = MakeTexture("TriviaPiece", pieceSize, (x, y) =>
                Mathf.Clamp01(0.5f - RoundedRectDistance(x, y, pieceSize, pieceSize, 0f, 5f)));
            _pieceSprite = MakeSprite(piece, Vector4.zero);
        }

        private Sprite MakeSprite(Texture2D texture, Vector4 border)
        {
            Sprite sprite = Sprite.Create(
                texture, new Rect(0f, 0f, texture.width, texture.height), new Vector2(0.5f, 0.5f), 100f, 0,
                SpriteMeshType.FullRect, border);
            _sprites.Add(sprite);
            return sprite;
        }

        /// <summary>Colored circle with a white check or cross.</summary>
        private Texture2D MakeMark(string name, int size, Color color, bool check)
        {
            Texture2D texture = new Texture2D(size, size, TextureFormat.RGBA32, false);
            texture.name = name;
            texture.wrapMode = TextureWrapMode.Clamp;
            Color32[] pixels = new Color32[size * size];
            float half = size * 0.5f;
            float stroke = size * 0.075f;
            for (int y = 0; y < size; y++)
            {
                for (int x = 0; x < size; x++)
                {
                    float px = (x + 0.5f - half) / half;
                    float py = (y + 0.5f - half) / half;
                    float circle = Mathf.Clamp01((1f - Mathf.Sqrt((px * px) + (py * py))) * half);
                    float d;
                    if (check)
                    {
                        d = Mathf.Min(
                            SegmentDistance(px, py, -0.42f, 0.02f, -0.12f, -0.3f),
                            SegmentDistance(px, py, -0.12f, -0.3f, 0.46f, 0.34f));
                    }
                    else
                    {
                        d = Mathf.Min(
                            SegmentDistance(px, py, -0.34f, -0.34f, 0.34f, 0.34f),
                            SegmentDistance(px, py, -0.34f, 0.34f, 0.34f, -0.34f));
                    }

                    float mark = Mathf.Clamp01(((stroke / half) - d) * half + 0.5f);
                    Color c = Color.Lerp(color, Color.white, mark);
                    c.a = circle;
                    pixels[(y * size) + x] = c;
                }
            }

            texture.SetPixels32(pixels);
            texture.Apply(false, true);
            _textures.Add(texture);
            return texture;
        }

        private Texture2D MakeTexture(string name, int size, System.Func<int, int, float> alpha)
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
            _textures.Add(texture);
            return texture;
        }

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

        private static float SegmentDistance(float px, float py, float ax, float ay, float bx, float by)
        {
            Vector2 p = new Vector2(px, py);
            Vector2 a = new Vector2(ax, ay);
            Vector2 b = new Vector2(bx, by);
            Vector2 ab = b - a;
            float t = Mathf.Clamp01(Vector2.Dot(p - a, ab) / ab.sqrMagnitude);
            return (p - (a + (ab * t))).magnitude;
        }

        /// <summary>Signed distance to a five-pointed star of radius 0.95 (negative inside).</summary>
        private static float StarDistance(float x, float y)
        {
            const float outer = 0.95f;
            const float inner = 0.42f;
            float angle = Mathf.Atan2(x, y);
            float sector = Mathf.PI * 2f / 5f;
            float a = Mathf.Repeat(angle + (sector * 0.5f), sector) - (sector * 0.5f);
            float r = Mathf.Sqrt((x * x) + (y * y));
            Vector2 p = new Vector2(Mathf.Abs(Mathf.Sin(a)) * r, Mathf.Cos(a) * r);
            Vector2 tip = new Vector2(0f, outer);
            Vector2 valley = new Vector2(Mathf.Sin(sector * 0.5f) * inner, Mathf.Cos(sector * 0.5f) * inner);
            Vector2 edge = valley - tip;
            float t = Mathf.Clamp01(Vector2.Dot(p - tip, edge) / edge.sqrMagnitude);
            float distance = (p - (tip + (edge * t))).magnitude;
            float side = (edge.x * (p.y - tip.y)) - (edge.y * (p.x - tip.x));
            return side > 0f ? -distance : distance;
        }
    }
}
