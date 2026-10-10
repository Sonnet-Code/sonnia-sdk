// Akinator dev (docs/plan-juegos.md, 5.3): pantalla de Unity.
//
// El visitante piensa en algo del mundo tech y Sonnia lo adivina con preguntas de sí o
// no. Las preguntas las hace GPT-Live sin delegar; el orquestador las cuenta en su
// transcripción y manda aquí el estado entero de la partida en cada evento
// (docs/protocolo.md, «akinator»): fase, preguntas hechas, la pregunta en curso, la
// respuesta que arriesga y los fallos. Unity solo pinta:
//
//  - Una tarjeta en la franja alta con una bola de cristal a la izquierda (esfera con
//    brillo, arcos de colores que giran, destellos que orbitan y un «?» que flota), la
//    pregunta o lo que toque a la derecha, los puntos de progreso (uno por pregunta) y
//    una línea de ayuda debajo. Es compacta: acaba hacia donde la de la trivia, para que
//    Sonnia siga grande debajo.
//  - waiting: «Piensa en algo… y no lo digas», los temas del banco y los puntos vacíos.
//  - asking: la pregunta en curso y «PREGUNTA 7 DE 20» en la cabecera.
//  - guessing: la tarjeta grande «¿Es… Kotlin?» con destellos.
//  - miss: «¡No era Kotlin!» y vuelve a preguntar.
//  - giving_up: «Me rindo… ¿qué era?».
//  - reveal: la tarjeta de resultado (confeti si lo adivina; «¡Me ganaste!» si no).
//
// Mientras la partida está abierta, Sonnia piensa con la mano en la barbilla (touchBeard
// de Sage, sostenido por AvatarChoreographer) cada vez que el avatar pasa a «pensando»:
// sobre todo mientras el backend registra su respuesta o el veredicto.
//
// Todo se construye por código con el kit de GameHud, una vez, y se reutiliza.

using System;
using Newtonsoft.Json;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia.Games.Akinator
{
    /// <summary>Pantalla de «Akinator dev» (id <c>akinator</c>).</summary>
    public class AkinatorController : GameControllerBase
    {
        /// <summary>Id del juego en el protocolo.</summary>
        public const string GameId = "akinator";

        // Eventos del orquestador (cada uno trae el estado entero).
        private const string EventWaiting = "waiting";
        private const string EventQuestion = "question";
        private const string EventGuess = "guess";
        private const string EventMiss = "miss";
        private const string EventGiveUp = "giveup";
        private const string EventReveal = "reveal";

        // Fases.
        private const string PhaseWaiting = "waiting";
        private const string PhaseAsking = "asking";
        private const string PhaseGuessing = "guessing";
        private const string PhaseGivingUp = "giving_up";
        private const string PhaseRevealed = "revealed";

        // Diseño de la tarjeta (píxeles de la referencia 1080x1920; el contenido mide 872 de ancho).
        private const float ContentHeight = 372f;
        private const float BallBox = 230f;
        private const float BallDiameter = 196f;
        private const float TextLeft = 250f;
        private const float TextHeight = 230f;
        private const float DotsTop = 248f;
        private const float DotsHeight = 76f;
        private const float HintTop = 338f;
        private const float HintHeight = 34f;
        private static readonly Vector2 BallCenter = new Vector2(0f, 10f);
        private const int SparkleCount = 6;
        private const int ArcCount = 3;
        private const int MinQuestions = 3;
        private const int MaxQuestions = 40;

        [Header("Animación")]
        [SerializeField]
        [Range(1f, 8f)]
        [Tooltip("Segundos que se queda el rótulo «¡No era …!» sobre la tarjeta.")]
        private float missBannerSeconds = 2.6f;

        [SerializeField]
        [Tooltip("Sonnia piensa con la mano en la barbilla mientras el avatar está pensando (el gesto lo hace AvatarChoreographer).")]
        private bool ponderWhileThinking = true;

        [Header("Clips de Sonnia (los del set, como la trivia)")]
        [SerializeField]
        private string winClip = "QuickAction_vibe";

        [SerializeField]
        private string loseClip = "emotions-0049-traitsKind";

        [SerializeField]
        private string loseFallbackClip = "Peace";

        [SerializeField]
        private string missClip = "actions-highFive_actionFail";

        // ------------------------------------------------------------------
        // Lo que llega del orquestador
        // ------------------------------------------------------------------

        [Serializable]
        private sealed class StartData
        {
            [JsonProperty("max")] public int Max = 20;
            [JsonProperty("themes")] public string[] Themes = new string[0];
        }

        [Serializable]
        private sealed class StateData
        {
            [JsonProperty("phase")] public string Phase = PhaseWaiting;
            [JsonProperty("asked")] public int Asked;
            [JsonProperty("max")] public int Max = 20;
            [JsonProperty("question")] public string Question = string.Empty;
            [JsonProperty("guess")] public string Guess = string.Empty;
            [JsonProperty("missed")] public string[] Missed = new string[0];
            [JsonProperty("outcome")] public string Outcome = string.Empty;
            [JsonProperty("answer")] public string Answer = string.Empty;
        }

        private sealed class Sparkle
        {
            public RectTransform Rect;
            public Image Image;
            public float Radius;
            public float Speed;
            public float Phase;
            public float Size;
            public float Twinkle;
        }

        private sealed class Arc
        {
            public RectTransform Rect;
            public Image Image;
            public float Speed;
            public float Angle;
        }

        // Construcción (una vez).
        private bool _built;
        private RectTransform _root;
        private RectTransform _ball;
        private RectTransform _ballBody;
        private Image _glowOuter;
        private Image _glowInner;
        private TextMeshProUGUI _mark;
        private readonly Sparkle[] _sparkles = new Sparkle[SparkleCount];
        private readonly Arc[] _arcs = new Arc[ArcCount];
        private TextMeshProUGUI _mainText;
        private RectTransform _answerBox;
        private TextMeshProUGUI _eyebrow;
        private TextMeshProUGUI _answer;
        private RectTransform _dotsRow;
        private Image[] _dots = new Image[0];
        private float _dotSize;
        private TextMeshProUGUI _themesText;
        private TextMeshProUGUI _hint;
        private Texture2D _sphereTexture;
        private Sprite _sphereSprite;

        // Estado de la partida.
        private string[] _themes = new string[0];
        private string _phase = PhaseWaiting;
        private int _max = 20;
        private int _asked;
        private string _question = string.Empty;
        private string _guess = string.Empty;
        private bool _wantPonder;
        private float _clock;
        private float _bannerUntil = -1f;
        private Color _glowColor = GameColors.Blue;
        private float _glowStrength = 1f;
        private float _speedBoost = 1f;
        private float _speedBoostUntil = -1f;

        public override string Id
        {
            get { return GameId; }
        }

        protected override string DefaultTitle
        {
            get { return "Akinator dev"; }
        }

        // ------------------------------------------------------------------
        // Ciclo de vida
        // ------------------------------------------------------------------

        protected override void OnStart(string dataJson)
        {
            EnsureBuilt();
            if (!_built)
            {
                return;
            }

            StartData start = ParseData<StartData>(dataJson);
            _themes = start.Themes ?? new string[0];
            _max = Mathf.Clamp(start.Max, MinQuestions, MaxQuestions);
            _asked = 0;
            _question = string.Empty;
            _guess = string.Empty;
            _clock = 0f;
            _bannerUntil = -1f;
            _speedBoostUntil = -1f;
            Hud.SetContentHeight(Id, ContentHeight);
            BuildDots(_max);
            SetPonder(true);
            ShowWaiting();
            Hud.RefreshLayout();
        }

        protected override void OnGameEvent(string eventName, string dataJson)
        {
            if (!_built)
            {
                return;
            }

            switch (eventName)
            {
                case EventWaiting:
                    ApplyWaiting(ParseData<StateData>(dataJson));
                    break;
                case EventQuestion:
                    ApplyQuestion(ParseData<StateData>(dataJson));
                    break;
                case EventGuess:
                    ApplyGuess(ParseData<StateData>(dataJson));
                    break;
                case EventMiss:
                    ApplyMiss(ParseData<StateData>(dataJson));
                    break;
                case EventGiveUp:
                    ApplyGiveUp(ParseData<StateData>(dataJson));
                    break;
                case EventReveal:
                    ApplyReveal(ParseData<StateData>(dataJson));
                    break;
                default:
                    Log("evento desconocido: " + eventName);
                    break;
            }
        }

        /// <summary>Si el end llega sin que se viera el resultado (Unity reconectada), se enseña el de los datos.</summary>
        protected override void ShowDefaultResult(string result, string dataJson)
        {
            StateData data = ParseData<StateData>(dataJson);
            if (string.IsNullOrEmpty(data.Outcome))
            {
                data.Outcome = result == GameResults.Win ? "sonnia" : "visitor";
            }

            data.Asked = Mathf.Max(data.Asked, _asked);
            data.Max = _max;
            ApplyReveal(data);
        }

        protected override void OnClosed()
        {
            SetPonder(false);
            _phase = PhaseWaiting;
            _asked = 0;
            _question = string.Empty;
            _guess = string.Empty;
            _bannerUntil = -1f;
            if (Hud != null)
            {
                Hud.HideBanner();
            }
        }

        private void OnDestroy()
        {
            if (_sphereSprite != null)
            {
                Destroy(_sphereSprite);
            }

            if (_sphereTexture != null)
            {
                Destroy(_sphereTexture);
            }
        }

        // ------------------------------------------------------------------
        // Cada evento
        // ------------------------------------------------------------------

        private void ApplyWaiting(StateData state)
        {
            _max = Mathf.Clamp(state.Max, MinQuestions, MaxQuestions);
            _asked = 0;
            if (_dots.Length != _max)
            {
                BuildDots(_max);
            }

            ShowWaiting();
        }

        private void ApplyQuestion(StateData state)
        {
            bool newQuestion = state.Asked != _asked || !string.Equals(state.Question, _question, StringComparison.Ordinal);
            int before = _asked;
            Sync(state);
            _phase = PhaseAsking;
            SetPonder(true);
            ShowAsking();
            FillDots(before, _asked, true);
            if (newQuestion)
            {
                GameAnim.Pop(_mainText.rectTransform, 0.35f);
                GameAnim.Pulse(_ball, 0.05f, 0.3f);
                BoostBall(0.6f);
            }
        }

        private void ApplyGuess(StateData state)
        {
            bool already = _phase == PhaseGuessing && string.Equals(state.Guess, _guess, StringComparison.Ordinal);
            int before = _asked;
            Sync(state);
            _phase = PhaseGuessing;
            SetPonder(true);
            ShowGuess();
            FillDots(before, _asked, false);
            if (!already)
            {
                GameAnim.Pop(_answerBox, 0.5f);
                GameAnim.Pulse(_ball, 0.12f, 0.5f);
                Hud.PopCard();
                Hud.SparklesAt(_ball, 12);
                BoostBall(1.6f);
            }
        }

        private void ApplyMiss(StateData state)
        {
            int before = _asked;
            Sync(state);
            _phase = PhaseAsking;
            SetPonder(true);
            ShowAsking();
            FillDots(before, _asked, false);
            string missed = LastOf(state.Missed);
            Hud.ShowBanner(string.IsNullOrEmpty(missed) ? "¡No era!" : "¡No era " + GameUi.Plain(missed) + "!", GameColors.Red);
            _bannerUntil = _clock + missBannerSeconds;
            GameAnim.Shake(_ball, 0.55f, 14f);
            PlayReaction(missClip, null);
            ShowEmotion(FacialExpressionController.Emotion.Sad, 1.8f);
        }

        private void ApplyGiveUp(StateData state)
        {
            int before = _asked;
            Sync(state);
            _phase = PhaseGivingUp;
            SetPonder(true);
            ShowGivingUp();
            FillDots(before, _asked, false);
            GameAnim.Pop(_mainText.rectTransform, 0.4f);
            PlayReaction(missClip, null);
            ShowEmotion(FacialExpressionController.Emotion.Surprise, 1.6f);
        }

        private void ApplyReveal(StateData state)
        {
            int before = _asked;
            Sync(state);
            _phase = PhaseRevealed;
            SetPonder(false);
            FillDots(before, _asked, false);
            Hud.HideBanner();
            _bannerUntil = -1f;
            string answer = GameUi.Plain(state.Answer ?? string.Empty);
            if (state.Outcome == "sonnia")
            {
                Hud.ShowResult(
                    "¡LO SABÍA!",
                    answer.ToUpperInvariant(),
                    "¡Lo adiviné en " + _asked + " pregunta" + (_asked == 1 ? string.Empty : "s") + "!",
                    true);
                PlayReaction(winClip, null);
                ShowEmotion(FacialExpressionController.Emotion.Joy, 4f);
            }
            else
            {
                string line = _asked >= _max ? "Me quedé sin preguntas. ¡Eres un crack!" : "No lo saqué. ¡Eres un crack!";
                Hud.ShowResult(
                    "¡ME GANASTE!",
                    answer.Length > 0 ? "ERA: " + answer.ToUpperInvariant() : null,
                    line,
                    false);
                PlayReaction(loseClip, loseFallbackClip);
                ShowEmotion(FacialExpressionController.Emotion.Joy, 2f);
            }

            Log("resultado: " + state.Outcome + " (" + answer + ", " + _asked + " preguntas)");
        }

        private void Sync(StateData state)
        {
            _max = Mathf.Clamp(state.Max, MinQuestions, MaxQuestions);
            if (_dots.Length != _max)
            {
                BuildDots(_max);
            }

            _asked = Mathf.Clamp(state.Asked, 0, _max);
            _question = state.Question ?? string.Empty;
            _guess = state.Guess ?? string.Empty;
        }

        // ------------------------------------------------------------------
        // Lo que se ve en cada fase
        // ------------------------------------------------------------------

        private void ShowWaiting()
        {
            _phase = PhaseWaiting;
            string yellow = ColorUtility.ToHtmlStringRGB(GameColors.Yellow);
            _mainText.text = "PIENSA EN ALGO…\n<color=#" + yellow + ">Y NO LO DIGAS</color>";
            _mainText.gameObject.SetActive(true);
            _answerBox.gameObject.SetActive(false);
            _mark.text = "?";
            _themesText.text = ThemesLine();
            _themesText.gameObject.SetActive(true);
            _dotsRow.gameObject.SetActive(false);
            _hint.text = "CUANDO LO TENGAS, AVÍSALE A SONNIA";
            Hud.SetCaption(string.Empty);
            SetGlow(GameColors.Blue, 1f);
            PaintDots(0);
        }

        private void ShowAsking()
        {
            _mainText.text = GameUi.Plain(_question);
            _mainText.gameObject.SetActive(true);
            _answerBox.gameObject.SetActive(false);
            _mark.text = "?";
            _themesText.gameObject.SetActive(false);
            _dotsRow.gameObject.SetActive(true);
            _hint.text = "RESPONDE: SÍ · NO · NO SÉ · A VECES";
            Hud.SetCaption("PREGUNTA " + _asked + " DE " + _max);
            SetGlow(GameColors.Blue, 1f);
        }

        private void ShowGuess()
        {
            string yellow = ColorUtility.ToHtmlStringRGB(GameColors.Yellow);
            _eyebrow.text = "¿ES…";
            _answer.text = GameUi.Plain(_guess) + "<color=#" + yellow + ">?</color>";
            _mainText.gameObject.SetActive(false);
            _answerBox.gameObject.SetActive(true);
            _mark.text = "!";
            _themesText.gameObject.SetActive(false);
            _dotsRow.gameObject.SetActive(true);
            _hint.text = "¿ACERTÉ? DILE A SONNIA SÍ O NO";
            Hud.SetCaption("PREGUNTA " + _asked + " DE " + _max);
            SetGlow(GameColors.Yellow, 1.5f);
        }

        private void ShowGivingUp()
        {
            string yellow = ColorUtility.ToHtmlStringRGB(GameColors.Yellow);
            _mainText.text = "ME RINDO…\n<color=#" + yellow + ">¿QUÉ ERA?</color>";
            _mainText.gameObject.SetActive(true);
            _answerBox.gameObject.SetActive(false);
            _mark.text = "…";
            _themesText.gameObject.SetActive(false);
            _dotsRow.gameObject.SetActive(true);
            _hint.text = "DILE A SONNIA QUÉ ERA";
            Hud.SetCaption("PREGUNTA " + _asked + " DE " + _max);
            SetGlow(GameColors.Muted, 0.55f);
        }

        private string ThemesLine()
        {
            if (_themes == null || _themes.Length == 0)
            {
                return string.Empty;
            }

            string[] parts = new string[_themes.Length];
            for (int i = 0; i < _themes.Length; i++)
            {
                parts[i] = GameUi.Plain(_themes[i] ?? string.Empty).ToUpperInvariant();
            }

            return string.Join("  ·  ", parts);
        }

        private static string LastOf(string[] values)
        {
            return values != null && values.Length > 0 ? values[values.Length - 1] ?? string.Empty : string.Empty;
        }

        // ------------------------------------------------------------------
        // Puntos de progreso
        // ------------------------------------------------------------------

        private void BuildDots(int count)
        {
            for (int i = 0; i < _dots.Length; i++)
            {
                if (_dots[i] != null)
                {
                    Destroy(_dots[i].gameObject);
                }
            }

            const float gap = 12f;
            float width = Hud.ContentWidth;
            _dotSize = Mathf.Min(34f, (width - ((count - 1) * gap)) / count);
            _dots = new Image[count];
            float pitch = _dotSize + gap;
            for (int i = 0; i < count; i++)
            {
                Image dot = Hud.NewImage("Punto" + (i + 1), _dotsRow, Hud.DotSprite, EmptyDot);
                RectTransform rect = dot.rectTransform;
                rect.anchorMin = new Vector2(0.5f, 0.5f);
                rect.anchorMax = rect.anchorMin;
                rect.pivot = new Vector2(0.5f, 0.5f);
                rect.sizeDelta = new Vector2(_dotSize, _dotSize);
                rect.anchoredPosition = new Vector2((i - ((count - 1) * 0.5f)) * pitch, 0f);
                _dots[i] = dot;
            }
        }

        private static Color EmptyDot
        {
            get { return GameUi.WithAlpha(Color.white, 0.16f); }
        }

        private static Color DotColor(int index)
        {
            return GameColors.Google[index % GameColors.Google.Length];
        }

        /// <summary>Pinta el progreso de golpe, sin animar.</summary>
        private void PaintDots(int filled)
        {
            for (int i = 0; i < _dots.Length; i++)
            {
                _dots[i].color = i < filled ? DotColor(i) : EmptyDot;
                _dots[i].rectTransform.localScale = Vector3.one;
            }
        }

        /// <summary>Lleva el progreso de <paramref name="from"/> a <paramref name="to"/> puntos; los nuevos entran con rebote.</summary>
        private void FillDots(int from, int to, bool animate)
        {
            to = Mathf.Clamp(to, 0, _dots.Length);
            from = Mathf.Clamp(from, 0, _dots.Length);
            for (int i = 0; i < _dots.Length; i++)
            {
                bool on = i < to;
                _dots[i].color = on ? DotColor(i) : EmptyDot;
                if (!on)
                {
                    _dots[i].rectTransform.localScale = Vector3.one;
                }
            }

            if (!animate || to <= from)
            {
                return;
            }

            for (int i = from; i < to; i++)
            {
                GameAnim.Pop(_dots[i].rectTransform, 0.45f, 0.04f * (i - from));
            }
        }

        // ------------------------------------------------------------------
        // Sonnia piensa
        // ------------------------------------------------------------------

        private void SetPonder(bool on)
        {
            _wantPonder = on && ponderWhileThinking;
            if (Choreographer != null)
            {
                Choreographer.SetPondering(_wantPonder);
            }
        }

        // ------------------------------------------------------------------
        // Animación de la bola
        // ------------------------------------------------------------------

        private void SetGlow(Color color, float strength)
        {
            _glowColor = color;
            _glowStrength = strength;
        }

        private void BoostBall(float seconds)
        {
            _speedBoost = 3.2f;
            _speedBoostUntil = _clock + seconds;
        }

        private void Update()
        {
            if (!_built || !IsActive || Hud == null || !Hud.IsOpen || Hud.CurrentGame != Id)
            {
                return;
            }

            _clock += Time.deltaTime;
            if (_wantPonder && Choreographer != null)
            {
                // El orquestador manda «activity» (think/none) y lo apaga cuando una tarea acaba.
                Choreographer.SetPondering(true);
            }

            if (_bannerUntil > 0f && _clock >= _bannerUntil)
            {
                _bannerUntil = -1f;
                Hud.HideBanner();
            }

            float boost = _clock < _speedBoostUntil ? _speedBoost : 1f;
            AnimateBall(boost);
            AnimateDots();
        }

        private void AnimateBall(float boost)
        {
            float t = _clock;
            float pulse = 0.5f + (0.5f * Mathf.Sin(t * 2.1f));
            Color target = _glowColor;
            float strength = _glowStrength * Mathf.Lerp(0.75f, 1f, pulse);
            _glowOuter.color = GameUi.WithAlpha(target, 0.16f * strength);
            _glowInner.color = GameUi.WithAlpha(target, 0.24f * strength);
            float breathe = 1f + (0.03f * Mathf.Sin(t * 1.7f));
            _glowOuter.rectTransform.localScale = new Vector3(breathe, breathe, 1f);

            Vector2 center = BallCenter;
            for (int i = 0; i < _sparkles.Length; i++)
            {
                Sparkle s = _sparkles[i];
                float angle = (s.Phase + (t * s.Speed * boost)) * Mathf.Deg2Rad;
                float wobble = 1f + (0.12f * Mathf.Sin((t * 1.3f) + s.Phase));
                Vector2 position = center + new Vector2(Mathf.Cos(angle), Mathf.Sin(angle) * 0.82f) * (s.Radius * wobble);
                s.Rect.anchoredPosition = position;
                float twinkle = 0.55f + (0.45f * Mathf.Sin((t * s.Twinkle) + s.Phase));
                s.Rect.localScale = Vector3.one * Mathf.Lerp(0.55f, 1.1f, twinkle);
                s.Rect.localRotation = Quaternion.Euler(0f, 0f, (t * 40f) + s.Phase);
                s.Image.color = GameUi.WithAlpha(s.Image.color, Mathf.Lerp(0.55f, 1f, twinkle));
            }

            for (int i = 0; i < _arcs.Length; i++)
            {
                Arc a = _arcs[i];
                a.Angle += a.Speed * boost * Time.deltaTime;
                a.Rect.localRotation = Quaternion.Euler(0f, 0f, a.Angle);
            }

            _mark.rectTransform.anchoredPosition = BallCenter + new Vector2(0f, 4f * Mathf.Sin(t * 2.4f));
            float markScale = 1f + (0.04f * Mathf.Sin(t * 3.1f));
            _mark.rectTransform.localScale = new Vector3(markScale, markScale, 1f);
        }

        private void AnimateDots()
        {
            // El último punto lleno late despacio: ahí va la partida.
            bool pulse = _phase == PhaseAsking || _phase == PhaseGuessing;
            for (int i = 0; i < _dots.Length; i++)
            {
                GameAnim anim = _dots[i].GetComponent<GameAnim>();
                if (anim != null && anim.IsAnimating)
                {
                    continue;
                }

                float scale = pulse && i == _asked - 1 ? 1f + (0.1f * Mathf.Sin(_clock * 5f)) : 1f;
                _dots[i].rectTransform.localScale = new Vector3(scale, scale, 1f);
            }
        }

        // ------------------------------------------------------------------
        // Construcción
        // ------------------------------------------------------------------

        private void EnsureBuilt()
        {
            if (_built)
            {
                return;
            }

            _root = Content;
            if (_root == null || Hud == null)
            {
                return;
            }

            BuildBall();
            BuildTexts();
            BuildDotsRow();
            _hint = Hud.NewText("Ayuda", _root, string.Empty, 24f, GameColors.Muted, TextAlignmentOptions.Center, Hud.MonoFont);
            _hint.characterSpacing = 3f;
            _hint.textWrappingMode = TextWrappingModes.NoWrap;
            _hint.enableAutoSizing = true;
            _hint.fontSizeMin = 14f;
            _hint.fontSizeMax = 24f;
            Place(_hint.rectTransform, 0f, HintTop, Hud.ContentWidth, HintHeight);
            _built = true;
        }

        private static void Place(RectTransform rect, float x, float y, float width, float height)
        {
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(0f, 1f);
            rect.pivot = new Vector2(0f, 1f);
            rect.anchoredPosition = new Vector2(x, -y);
            rect.sizeDelta = new Vector2(width, height);
        }

        private static void Center(RectTransform rect, Vector2 position, float width, float height)
        {
            rect.anchorMin = new Vector2(0.5f, 0.5f);
            rect.anchorMax = rect.anchorMin;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = position;
            rect.sizeDelta = new Vector2(width, height);
        }

        private void BuildBall()
        {
            _ball = Hud.NewRect("BolaDeCristal", _root);
            Place(_ball, 0f, 0f, BallBox, BallBox);

            // La bola queda un poco más arriba del centro de su caja: debajo va el soporte.
            Vector2 center = BallCenter;

            _glowOuter = Hud.NewImage("HaloExterior", _ball, Hud.DotSprite, GameUi.WithAlpha(GameColors.Blue, 0.16f));
            Center(_glowOuter.rectTransform, center, 262f, 262f);
            _glowInner = Hud.NewImage("HaloInterior", _ball, Hud.DotSprite, GameUi.WithAlpha(GameColors.Blue, 0.24f));
            Center(_glowInner.rectTransform, center, 228f, 228f);

            // Soporte dorado, detrás de la esfera.
            Color gold = new Color(0.86f, 0.62f, 0.12f, 1f);
            Image baseDark = Hud.NewRound("SoporteBase", _ball, new Color(0.62f, 0.40f, 0.06f, 1f), 11f);
            Center(baseDark.rectTransform, new Vector2(0f, -104f), 150f, 22f);
            Image baseNeck = Hud.NewRound("SoporteCuello", _ball, gold, 12f);
            Center(baseNeck.rectTransform, new Vector2(0f, -90f), 104f, 26f);
            Image baseShine = Hud.NewRound("SoporteBrillo", _ball, new Color(1f, 0.86f, 0.42f, 0.9f), 3f);
            Center(baseShine.rectTransform, new Vector2(0f, -83f), 76f, 5f);

            _sphereTexture = MakeSphereTexture(256);
            _sphereSprite = Sprite.Create(
                _sphereTexture,
                new Rect(0f, 0f, _sphereTexture.width, _sphereTexture.height),
                new Vector2(0.5f, 0.5f),
                100f);
            Image body = Hud.NewImage("Esfera", _ball, _sphereSprite, Color.white);
            _ballBody = body.rectTransform;
            Center(_ballBody, center, BallDiameter, BallDiameter);

            // Arcos de colores que giran dentro de la esfera.
            Color[] arcColors =
            {
                GameUi.WithAlpha(new Color(0.7f, 0.85f, 1f), 0.55f),
                GameUi.WithAlpha(GameColors.Yellow, 0.55f),
                GameUi.WithAlpha(GameColors.Green, 0.5f)
            };
            float[] arcSizes = { 168f, 128f, 92f };
            float[] arcFill = { 0.34f, 0.26f, 0.4f };
            float[] arcSpeed = { 38f, -62f, 95f };
            for (int i = 0; i < ArcCount; i++)
            {
                Image arc = Hud.NewImage("Arco" + (i + 1), _ball, Hud.RingSprite, arcColors[i]);
                arc.type = Image.Type.Filled;
                arc.fillMethod = Image.FillMethod.Radial360;
                arc.fillOrigin = (int)Image.Origin360.Top;
                arc.fillClockwise = true;
                arc.fillAmount = arcFill[i];
                Center(arc.rectTransform, center, arcSizes[i], arcSizes[i]);
                _arcs[i] = new Arc { Rect = arc.rectTransform, Image = arc, Speed = arcSpeed[i], Angle = i * 70f };
            }

            // Destellos que orbitan.
            float[] radii = { 44f, 62f, 30f, 70f, 52f, 36f };
            float[] speeds = { 52f, -38f, 80f, 28f, -66f, 100f };
            float[] sizes = { 30f, 24f, 22f, 28f, 20f, 18f };
            for (int i = 0; i < SparkleCount; i++)
            {
                Color color = GameColors.Google[i % GameColors.Google.Length];
                Image image = Hud.NewImage("Destello" + (i + 1), _ball, Hud.SparkleSprite, color);
                Center(image.rectTransform, center, sizes[i], sizes[i]);
                _sparkles[i] = new Sparkle
                {
                    Rect = image.rectTransform,
                    Image = image,
                    Radius = radii[i],
                    Speed = speeds[i],
                    Phase = i * 61f,
                    Size = sizes[i],
                    Twinkle = 2.2f + (i * 0.7f)
                };
            }

            _mark = Hud.NewText("Marca", _ball, "?", 112f, GameUi.WithAlpha(Color.white, 0.94f), TextAlignmentOptions.Center, Hud.DisplayFont);
            _mark.textWrappingMode = TextWrappingModes.NoWrap;
            Center(_mark.rectTransform, center, 120f, 130f);

            // Brillo de cristal arriba a la izquierda.
            Image glint = Hud.NewImage("Reflejo", _ball, Hud.DotSprite, GameUi.WithAlpha(Color.white, 0.5f));
            Center(glint.rectTransform, center + new Vector2(-46f, 50f), 56f, 26f);
            glint.rectTransform.localRotation = Quaternion.Euler(0f, 0f, 38f);
            Image glintSmall = Hud.NewImage("ReflejoPequeno", _ball, Hud.DotSprite, GameUi.WithAlpha(Color.white, 0.7f));
            Center(glintSmall.rectTransform, center + new Vector2(-20f, 70f), 14f, 14f);
        }

        private void BuildTexts()
        {
            float width = Hud.ContentWidth - TextLeft;
            _mainText = Hud.NewText("Pregunta", _root, string.Empty, 54f, Color.white, TextAlignmentOptions.MidlineLeft, Hud.DisplayFont);
            _mainText.enableAutoSizing = true;
            _mainText.fontSizeMin = 28f;
            _mainText.fontSizeMax = 54f;
            _mainText.lineSpacing = -8f;
            Place(_mainText.rectTransform, TextLeft, 0f, width, TextHeight);

            _answerBox = Hud.NewRect("Adivinanza", _root);
            Place(_answerBox, TextLeft, 0f, width, TextHeight);
            _eyebrow = Hud.NewText("PrimeraParte", _answerBox, "¿ES…", 40f, GameColors.Muted, TextAlignmentOptions.TopLeft, Hud.DisplayFont);
            _eyebrow.characterSpacing = 8f;
            _eyebrow.textWrappingMode = TextWrappingModes.NoWrap;
            Place(_eyebrow.rectTransform, 0f, 8f, width, 52f);
            _answer = Hud.NewText("Respuesta", _answerBox, string.Empty, 96f, Color.white, TextAlignmentOptions.MidlineLeft, Hud.DisplayFont);
            _answer.enableAutoSizing = true;
            _answer.fontSizeMin = 40f;
            _answer.fontSizeMax = 96f;
            _answer.enableVertexGradient = true;
            _answer.colorGradient = new VertexGradient(GameColors.Gold, GameColors.Gold, GameColors.Yellow, new Color(1f, 0.62f, 0.1f));
            _answer.lineSpacing = -10f;
            Place(_answer.rectTransform, 0f, 56f, width, TextHeight - 56f);
            _answerBox.gameObject.SetActive(false);

            _themesText = Hud.NewText("Temas", _root, string.Empty, 22f, GameColors.Muted, TextAlignmentOptions.Center, Hud.MonoFont);
            _themesText.characterSpacing = 2f;
            _themesText.enableAutoSizing = true;
            _themesText.fontSizeMin = 13f;
            _themesText.fontSizeMax = 22f;
            _themesText.lineSpacing = 6f;
            Place(_themesText.rectTransform, 0f, DotsTop, Hud.ContentWidth, DotsHeight);
        }

        private void BuildDotsRow()
        {
            _dotsRow = Hud.NewRect("Progreso", _root);
            Place(_dotsRow, 0f, DotsTop, Hud.ContentWidth, DotsHeight);
        }

        // ------------------------------------------------------------------
        // La esfera de cristal, dibujada pixel a pixel
        // ------------------------------------------------------------------

        /// <summary>
        /// Una esfera de cristal azul: sombreado difuso desde arriba a la izquierda, brillo
        /// especular, borde más claro (Fresnel) y borde suavizado. Con transparencia, para
        /// que el halo se vea a través del cristal.
        /// </summary>
        private static Texture2D MakeSphereTexture(int size)
        {
            Texture2D texture = new Texture2D(size, size, TextureFormat.RGBA32, false);
            texture.name = "AkinatorEsfera";
            texture.wrapMode = TextureWrapMode.Clamp;
            texture.filterMode = FilterMode.Bilinear;
            Color32[] pixels = new Color32[size * size];
            Vector3 light = new Vector3(-0.45f, 0.58f, 0.68f).normalized;
            Vector3 half = (light + Vector3.forward).normalized;
            Color deep = new Color(0.04f, 0.07f, 0.32f);
            Color mid = new Color(0.14f, 0.3f, 0.86f);
            Color core = new Color(0.42f, 0.62f, 1f);
            Color rimColor = new Color(0.45f, 0.68f, 1f);
            float radius = size * 0.5f;
            for (int y = 0; y < size; y++)
            {
                for (int x = 0; x < size; x++)
                {
                    float u = (x + 0.5f - radius) / radius;
                    float v = (y + 0.5f - radius) / radius;
                    float r2 = (u * u) + (v * v);
                    float edge = Mathf.Clamp01((1f - Mathf.Sqrt(r2)) * radius * 0.5f);
                    if (edge <= 0f)
                    {
                        pixels[(y * size) + x] = new Color32(0, 0, 0, 0);
                        continue;
                    }

                    float z = Mathf.Sqrt(Mathf.Max(0f, 1f - r2));
                    Vector3 normal = new Vector3(u, v, z);
                    float diffuse = Mathf.Clamp01(Vector3.Dot(normal, light));
                    float specular = Mathf.Pow(Mathf.Clamp01(Vector3.Dot(normal, half)), 90f);
                    float rim = Mathf.Pow(1f - z, 2.4f);
                    Color color = Color.Lerp(deep, mid, Mathf.Pow(z, 0.7f));
                    color = Color.Lerp(color, core, Mathf.Pow(z, 5f) * 0.55f);
                    color *= 0.62f + (0.6f * diffuse);
                    color += rimColor * (rim * 0.6f);
                    color += Color.white * (specular * 0.75f);
                    float alpha = Mathf.Lerp(0.9f, 0.97f, z) * edge;
                    pixels[(y * size) + x] = new Color32(
                        (byte)(Mathf.Clamp01(color.r) * 255f),
                        (byte)(Mathf.Clamp01(color.g) * 255f),
                        (byte)(Mathf.Clamp01(color.b) * 255f),
                        (byte)(alpha * 255f));
                }
            }

            texture.SetPixels32(pixels);
            texture.Apply(false, true);
            return texture;
        }
    }
}
