// Modo trivia en la pantalla: la pregunta con sus opciones A, B y C, el acierto
// en verde y el fallo en rojo con confeti, el marcador, la pantalla final, el
// gorro de fiesta y el tema de colores de la escena (docs/trivia.md).
//
// La partida la llevan el orquestador y GPT-Live; aquí solo se pinta lo que
// llega por el protocolo (trivia_start, trivia_question, trivia_answer y
// trivia_end) y se le da a Sonia su reacción: gesto, cara y gorro.
//
// Todo se construye por código dentro del Canvas del HUD (SoniaHUD, Screen
// Space - Camera sobre la cámara del HUD, sin postprocesado), como el letrero
// del modo Fuera: sale en las capturas 9:16 y en la build, sin prefabs.
//
// Diseño para el monitor vertical (1080x1920 de referencia):
//  - La tarjeta va en la franja alta, la misma del panel de imágenes, y la
//    cámara pasa al plano de panel (un poco más atrás) para que no tape la cara.
//    Los subtítulos de abajo quedan libres.
//  - Cabecera "TRIVIA" con las letras en los colores de Google y una fila de
//    puntos con el progreso (verde acierto, rojo fallo, blanco la actual).
//  - Opciones grandes, legibles a varios metros, con la letra en un círculo.
//  - Acierto: la opción se llena de verde con un círculo con el visto, sale
//    un rótulo "¡Correcto!" y una ráfaga de confeti y destellos desde ella.
//  - Fallo: la elegida se pone roja y tiembla, la buena se marca en verde.
//  - Final: tarjeta grande con el resultado; si gana, lluvia de confeti.
//  - Tema: un marco de luz en los bordes que va pasando por los colores de
//    Google, y el halo y los contraluces de la escena se tiñen igual.

using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Pinta la trivia en el HUD y hace reaccionar a Sonia.</summary>
    [DisallowMultipleComponent]
    public class TriviaController : MonoBehaviour
    {
        [Header("Gestos de Sonia (clips del set)")]
        [SerializeField]
        [Tooltip("Al empezar la trivia. Vacío: ninguno, porque Sonia se pone el gorro con las dos manos (TriviaHat).")]
        private string startClip = "";

        [SerializeField]
        [Tooltip("Al acertar. Si no está en el set, se usa el de respaldo.")]
        private string correctClip = "actions-highFive_actionSuccess";

        [SerializeField]
        private string correctFallbackClip = "QuickAction_twoThumbsUp";

        [SerializeField]
        [Tooltip("Al fallar o no saberla.")]
        private string wrongClip = "actions-highFive_actionFail";

        [SerializeField]
        [Tooltip("Al ganar la partida.")]
        private string winClip = "QuickAction_vibe";

        [SerializeField]
        [Tooltip("Al perder la partida: ánimo. Si no está en el set, se usa el de respaldo.")]
        private string loseClip = "emotions-0049-traitsKind";

        [SerializeField]
        private string loseFallbackClip = "Peace";

        [Header("Diseño (píxeles de la referencia 1080x1920)")]
        [SerializeField]
        [Tooltip("Ancho de la tarjeta de la pregunta.")]
        private float cardWidth = 960f;

        [SerializeField]
        [Range(0f, 0.5f)]
        [Tooltip("Distancia del borde superior de la tarjeta al de la pantalla, en fracción del alto.")]
        private float cardTop = 0.105f;

        [SerializeField]
        [Tooltip("Tamaño del texto de la pregunta.")]
        private float questionSize = 50f;

        [SerializeField]
        [Tooltip("Alto fijo de la pregunta (hasta tres líneas; el texto se encoge si no cabe). Así la tarjeta mide siempre lo mismo y no tapa a Sonia.")]
        private float questionHeight = 150f;

        [SerializeField]
        [Tooltip("Tamaño del texto de las opciones.")]
        private float optionSize = 40f;

        [SerializeField]
        [Tooltip("Alto de cada opción.")]
        private float optionHeight = 98f;

        [SerializeField]
        [Tooltip("Pedir a la cámara el plano de panel mientras hay trivia (Sonia algo más atrás, la tarjeta arriba).")]
        private bool usePanelShot = true;

        [SerializeField]
        [Tooltip("Desplazamiento extra de la cámara sobre el plano de panel (metros): más alta y más atrás para que Sonia y su gorro quepan bajo la tarjeta.")]
        private Vector3 panelShotExtra = new Vector3(0f, 0.3f, -0.8f);

        [SerializeField]
        [Range(0f, 3f)]
        [Tooltip("Segundos que espera Sonia para agacharse a por el gorro al empezar: antes sube la cámara al plano de la trivia, que ve menos abajo que el de conversación, y así el gorro sale de fuera de cuadro.")]
        private float hatDelay = 0.9f;

        [Header("Tiempos")]
        [SerializeField]
        [Range(2f, 30f)]
        [Tooltip("Segundos que se queda la pantalla final antes de quitar el gorro y el tema.")]
        private float endScreenSeconds = 9f;

        [SerializeField]
        [Range(0.5f, 10f)]
        [Tooltip("Tras reconectar con el orquestador, si en este tiempo no vuelve a llegar trivia_start, la partida ya no existe y se retira.")]
        private float replayGraceSeconds = 2.5f;

        [SerializeField]
        [Tooltip("Escribir en la consola los eventos de la trivia.")]
        private bool logEvents = true;

        private const string HudCanvasName = "SoniaHUD";
        private const int CornerRadius = 36;

        /// <summary>Segundos entre que se va la tarjeta de la pregunta y llega la del resultado.</summary>
        private const float ResultDelay = 0.35f;

        // Colores de Google y de la tarjeta.
        private static readonly Color Blue = new Color(0.259f, 0.522f, 0.957f);
        private static readonly Color Red = new Color(0.918f, 0.263f, 0.208f);
        private static readonly Color Yellow = new Color(0.984f, 0.737f, 0.02f);
        private static readonly Color Green = new Color(0.204f, 0.659f, 0.325f);
        private static readonly Color[] GoogleColors = { Blue, Red, Yellow, Green };
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
        private TriviaHat _hat;
        private Canvas _canvas;
        private TMP_FontAsset _font;
        private bool _warnedNoCanvas;

        // Construcción.
        private RectTransform _root;
        private CanvasGroup _rootGroup;
        private Image _frame;
        private RectTransform _card;
        private CanvasGroup _cardGroup;
        private Image _cardGlow;
        private TextMeshProUGUI _eyebrow;
        private TextMeshProUGUI _counter;

        /// <summary>Nivel de la partida para el contador («PREGUNTA 2 DE 5 · DIFÍCIL»).</summary>
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
        private Sprite _frameSprite;
        private Sprite _checkSprite;
        private Sprite _crossSprite;
        private Sprite _sparkleSprite;
        private Sprite _starSprite;
        private Sprite _pieceSprite;
        private readonly List<Texture2D> _textures = new List<Texture2D>();
        private readonly List<Sprite> _sprites = new List<Sprite>();

        // Estado de la partida.
        private bool _active;
        private int _total = 5;
        private int _threshold = 3;
        private int _number;
        private int _score;
        private bool _ending;
        private float _endAt;
        private float _awaitReplayUntil = -1f;

        // Animación.
        private float _clock;
        // Cuándo va Sonia a por el gorro (-1: no toca) y si falta devolver la cámara.
        private float _hatAt = -1f;
        private bool _releaseCamera;
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

        // Tema de la escena.
        private float _theme;
        private Renderer _halo;
        private string _haloColorProperty;
        private Color _haloOriginal;
        private readonly List<Light> _rims = new List<Light>();
        private readonly List<Color> _rimOriginals = new List<Color>();
        private bool _sceneThemeCaptured;

        /// <summary>Cierto mientras hay una trivia en pantalla (también la pantalla final).</summary>
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
            _hat = GetComponent<TriviaHat>();
            if (_hat == null)
            {
                _hat = gameObject.AddComponent<TriviaHat>();
            }
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
            // Se construye ya (oculto) para que aparecer no cueste nada.
            Build();
        }

        private void OnDestroy()
        {
            RestoreSceneTheme();
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
        // Mensajes del protocolo
        // ------------------------------------------------------------------

        private void HandleHello(HelloMessage message)
        {
            // Si la partida terminó mientras no había conexión, el orquestador ya
            // no repetirá trivia_start: pasado el margen se retira.
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

            // El gorro, cuando la cámara ya va por el plano de la trivia (ver hatDelay).
            _releaseCamera = false;
            _hatAt = hatDelay > 0f ? _clock + hatDelay : -1f;
            if (_hat != null && hatDelay <= 0f)
            {
                _hat.SetOn(true);
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

            CaptureSceneTheme();
            PlayClip(startClip, null);
            ShowEmotion(FacialExpressionController.Emotion.Joy, 2f);
            Burst(new Vector2(0f, 300f), 40, 900f);
            Log("empieza la trivia: " + _total + " preguntas, gana con " + _threshold);
        }

        private void HandleQuestion(TriviaQuestionMessage message)
        {
            if (message == null || message.Options == null || message.Options.Length < 3)
            {
                return;
            }

            if (!_active || _ending)
            {
                // Pregunta sin trivia_start (Unity antigua o mensajes cruzados): se arranca igual.
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

            // Puntos: los ya contestados que no cuadren (tras reconectar) se rellenan
            // con los aciertos primero.
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

            _counter.text = "PREGUNTA " + _number + " DE " + _total
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
            Log("pregunta " + _number + "/" + _total);
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
                SetBanner("¡Correcto!", Green);
                if (_hat != null)
                {
                    _hat.SpinBoost();
                }

                Vector2 at = EffectsPoint(_options[correct].Row);
                Burst(at, 90, 1300f);
                Sparkles(at, 10);
                PlayClip(correctClip, correctFallbackClip);
                ShowEmotion(FacialExpressionController.Emotion.Joy, 3f);
            }
            else
            {
                SetBanner(chosen < 0 ? "Era la " + letter : "¡Uy! Era la " + letter, Red);
                PlayClip(wrongClip, null);
                ShowEmotion(FacialExpressionController.Emotion.Sad, 2.4f);
            }

            Log("respuesta " + message.Number + ": " + (message.IsCorrect ? "acierto" : "fallo") + " (" + _score + ")");
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
                Log("trivia cancelada");
                Finish();
                return;
            }

            _score = Mathf.Clamp(message.Score, 0, Mathf.Max(1, message.Total));
            _total = Mathf.Max(1, message.Total);
            ShowResult(message.Won, message.Prize);
            _ending = true;
            _endAt = _clock + endScreenSeconds;
            if (message.Won)
            {
                if (_hat != null)
                {
                    _hat.SpinBoost(6f);
                }

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

            Log("trivia terminada: " + _score + " de " + _total + (message.Won ? ", gana" : ", pierde"));
        }

        /// <summary>Quita la trivia de la pantalla: tarjetas fuera, gorro fuera y tema fuera.</summary>
        private void Finish()
        {
            _active = false;
            _ending = false;
            _cardShown = false;
            _resultShown = false;
            _rainUntil = -1f;
            _bannerAt = -1f;
            _hatAt = -1f;
            if (_hat != null)
            {
                _hat.SetOn(false);
            }

            // La cámara vuelve cuando el gorro ya está abajo: el plano de conversación ve
            // hasta las rodillas y Sonia lo deja fuera del de la trivia.
            _releaseCamera = true;
            ReleaseCameraWhenHatIsDown();

            if (_choreographer != null)
            {
                _choreographer.GreetingSuppressed = false;
            }
        }

        private void ReleaseCameraWhenHatIsDown()
        {
            if (!_releaseCamera || _active)
            {
                _releaseCamera = false;
                return;
            }

            if (_hat != null && !_hat.IsOff)
            {
                return;
            }

            _releaseCamera = false;
            if (_framing != null)
            {
                _framing.PanelRequested = false;
            }
        }

        // ------------------------------------------------------------------
        // Reacciones de Sonia
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
        // Animación
        // ------------------------------------------------------------------

        private void Update()
        {
            if (_root == null)
            {
                return;
            }

            float dt = Time.deltaTime;
            _clock += dt;

            if (_hatAt >= 0f && _clock >= _hatAt)
            {
                _hatAt = -1f;
                if (_active && _hat != null)
                {
                    _hat.SetOn(true);
                }
            }

            ReleaseCameraWhenHatIsDown();

            if (_awaitReplayUntil > 0f && Time.unscaledTime > _awaitReplayUntil)
            {
                _awaitReplayUntil = -1f;
                Log("tras reconectar no volvió la trivia: se retira");
                Finish();
            }

            if (_ending && _clock >= _endAt)
            {
                Finish();
            }

            bool visible = _active || _cardAlpha > 0.001f || _resultAlpha > 0.001f || _pieces.Count > 0 || _theme > 0.001f;
            if (!visible)
            {
                if (_root.gameObject.activeSelf)
                {
                    _root.gameObject.SetActive(false);
                }

                RestoreSceneTheme();
                return;
            }

            if (!_root.gameObject.activeSelf)
            {
                _root.gameObject.SetActive(true);
            }

            _rootAlpha = Mathf.MoveTowards(_rootAlpha, 1f, dt * 3f);
            _rootGroup.alpha = _rootAlpha;

            AnimateTheme(dt);
            AnimateCard(dt);
            AnimateOptions(dt);
            AnimateDots();
            AnimateBanner();
            AnimateResult(dt);
            AnimatePieces(dt);
        }

        private void AnimateTheme(float dt)
        {
            _theme = Mathf.MoveTowards(_theme, _active ? 1f : 0f, dt / 0.8f);
            float eased = _theme * _theme * (3f - (2f * _theme));
            Color cycle = CycleColor(_clock * 0.25f);
            if (_frame != null)
            {
                _frame.color = WithAlpha(cycle, 0.55f * eased);
            }

            if (_cardGlow != null)
            {
                _cardGlow.color = WithAlpha(cycle, 0.3f * _cardAlpha);
            }

            ApplySceneTheme(cycle, eased);
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

                // Entrada escalonada: cada opción llega desde la derecha.
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
        // Confeti y destellos
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

                // Papelitos: caen con resistencia del aire, giran y dan la vuelta.
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

        /// <summary>Ráfaga de papelitos desde <paramref name="at"/> (coordenadas de la capa de efectos).</summary>
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
                Color color = Random.value < 0.15f ? Color.white : GoogleColors[Random.Range(0, GoogleColors.Length)];
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
            GameObject go = new GameObject("Confeti", typeof(RectTransform));
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
        // Resultado y rótulos
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

        private void ShowResult(bool won, string prize = "")
        {
            Build();
            if (_result == null)
            {
                return;
            }

            _resultTitle.text = won ? "¡GANASTE!" : "¡CASI!";
            _resultTitle.colorGradient = won
                ? new VertexGradient(new Color(1f, 0.93f, 0.55f), new Color(1f, 0.93f, 0.55f), Yellow, new Color(1f, 0.62f, 0.1f))
                : new VertexGradient(Color.white, Color.white, new Color(0.75f, 0.85f, 1f), new Color(0.75f, 0.85f, 1f));
            _resultScore.text = _score + " de " + _total + (_score == 1 ? " acierto" : " aciertos");
            _resultLine.text = (won
                ? "¡Eres un crack del DevFest!"
                : "Hacían falta " + _threshold + ". ¡Pídeme otra trivia y lo intentas otra vez!")
                + (string.IsNullOrWhiteSpace(prize)
                    ? string.Empty
                    : "\nTu premio: " + prize.Trim() + ". ¡Recógelo con el staff del stand!");
            for (int i = 0; i < _resultStars.Count; i++)
            {
                bool lit = i < _score;
                _resultStars[i].gameObject.SetActive(i < _total);
                _resultStars[i].color = lit ? Yellow : WithAlpha(Color.white, 0.18f);
            }

            _resultShown = true;
            _resultAt = _clock + ResultDelay;
            RectTransform body = (RectTransform)_result.Find("Contenido");
            bool wasActive = _result.gameObject.activeSelf;
            _result.gameObject.SetActive(true);
            LayoutRebuilder.ForceRebuildLayoutImmediate(body);
            _result.sizeDelta = new Vector2(cardWidth, body.rect.height);
            _result.gameObject.SetActive(wasActive);
        }

        // ------------------------------------------------------------------
        // Tema de la escena
        // ------------------------------------------------------------------

        private void CaptureSceneTheme()
        {
            if (_sceneThemeCaptured)
            {
                return;
            }

            _sceneThemeCaptured = true;
            _halo = null;
            _rims.Clear();
            _rimOriginals.Clear();
            GameObject stage = GameObject.Find("SoniaStage");
            if (stage != null)
            {
                Transform halo = stage.transform.Find("Halo");
                Renderer renderer = halo != null ? halo.GetComponent<Renderer>() : null;
                if (renderer != null)
                {
                    Material material = renderer.material;
                    foreach (string property in new[] { "_BaseColor", "_Color", "_TintColor" })
                    {
                        if (material.HasProperty(property))
                        {
                            _halo = renderer;
                            _haloColorProperty = property;
                            _haloOriginal = material.GetColor(property);
                            break;
                        }
                    }
                }
            }

            foreach (Light light in FindObjectsByType<Light>(FindObjectsInactive.Exclude, FindObjectsSortMode.None))
            {
                if (light != null && light.name.IndexOf("Rim", System.StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    _rims.Add(light);
                    _rimOriginals.Add(light.color);
                }
            }
        }

        private void ApplySceneTheme(Color cycle, float amount)
        {
            if (!_sceneThemeCaptured)
            {
                return;
            }

            if (_halo != null)
            {
                Color tinted = Color.Lerp(_haloOriginal, cycle * Mathf.Max(1f, _haloOriginal.maxColorComponent), 0.75f * amount);
                tinted.a = _haloOriginal.a;
                _halo.material.SetColor(_haloColorProperty, tinted);
            }

            for (int i = 0; i < _rims.Count; i++)
            {
                if (_rims[i] != null)
                {
                    _rims[i].color = Color.Lerp(_rimOriginals[i], cycle, 0.6f * amount);
                }
            }
        }

        private void RestoreSceneTheme()
        {
            if (!_sceneThemeCaptured)
            {
                return;
            }

            if (_halo != null)
            {
                _halo.material.SetColor(_haloColorProperty, _haloOriginal);
            }

            for (int i = 0; i < _rims.Count; i++)
            {
                if (_rims[i] != null)
                {
                    _rims[i].color = _rimOriginals[i];
                }
            }

            _sceneThemeCaptured = false;
        }

        private static Color CycleColor(float t)
        {
            float x = Mathf.Repeat(t, GoogleColors.Length);
            int i = Mathf.FloorToInt(x);
            float f = x - i;
            f = f * f * (3f - (2f * f));
            return Color.Lerp(GoogleColors[i], GoogleColors[(i + 1) % GoogleColors.Length], f);
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

            _canvas = ResolveCanvas();
            if (_canvas == null)
            {
                if (!_warnedNoCanvas)
                {
                    _warnedNoCanvas = true;
                    Debug.LogWarning("[Sonia] No hay Canvas del HUD para la trivia.", this);
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
            // Detrás de los subtítulos y del resto del HUD, delante del logo.
            if (_canvas.name == HudCanvasName && _root.parent.childCount > 1)
            {
                _root.SetSiblingIndex(1);
            }

            // Marco de luz en los bordes (tema).
            GameObject frame = MakeImage("Marco", _root, _frameSprite, Color.clear);
            _frame = frame.GetComponent<Image>();
            _frame.type = Image.Type.Sliced;
            Stretch((RectTransform)frame.transform);

            BuildCard();
            BuildResult();

            GameObject effects = new GameObject("Efectos", typeof(RectTransform));
            effects.layer = root.layer;
            effects.transform.SetParent(_root, false);
            _effects = (RectTransform)effects.transform;
            Stretch(_effects);

            root.SetActive(false);
        }

        private void BuildCard()
        {
            GameObject cardRoot = new GameObject("Tarjeta", typeof(RectTransform), typeof(CanvasGroup));
            cardRoot.layer = _root.gameObject.layer;
            cardRoot.transform.SetParent(_root, false);
            _card = (RectTransform)cardRoot.transform;
            _card.anchorMin = new Vector2(0.5f, 1f - cardTop);
            _card.anchorMax = _card.anchorMin;
            _card.pivot = new Vector2(0.5f, 1f);
            _card.sizeDelta = new Vector2(cardWidth, 0f);
            _cardGroup = cardRoot.GetComponent<CanvasGroup>();
            _cardGroup.alpha = 0f;

            GameObject glow = MakeImage("Halo", _card, _glowSprite, Color.clear);
            _cardGlow = glow.GetComponent<Image>();
            RectTransform glowRect = (RectTransform)glow.transform;
            glowRect.anchorMin = Vector2.zero;
            glowRect.anchorMax = Vector2.one;
            glowRect.offsetMin = new Vector2(-70f, -70f);
            glowRect.offsetMax = new Vector2(70f, 70f);

            GameObject border = MakeImage("Borde", _card, _roundSprite, WithAlpha(new Color(0.44f, 0.66f, 1f), 0.55f));
            Stretch((RectTransform)border.transform);
            GameObject fill = MakeImage("Fondo", _card, _roundSprite, CardFill);
            RectTransform fillRect = (RectTransform)fill.transform;
            Stretch(fillRect);
            fillRect.offsetMin = new Vector2(3f, 3f);
            fillRect.offsetMax = new Vector2(-3f, -3f);

            GameObject body = new GameObject("Contenido", typeof(RectTransform));
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

            // Cabecera: TRIVIA de colores, el contador y los puntos.
            GameObject header = new GameObject("Cabecera", typeof(RectTransform));
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

            _eyebrow = MakeText("Titulo", header.transform, ColoredWord("TRIVIA"), 40f, Color.white, TextAlignmentOptions.Left);
            _eyebrow.fontStyle = FontStyles.Bold;
            _eyebrow.characterSpacing = 10f;
            _eyebrow.textWrappingMode = TextWrappingModes.NoWrap;

            _counter = MakeText("Contador", header.transform, "PREGUNTA 1 DE 5", 26f, Muted, TextAlignmentOptions.Left);
            _counter.fontStyle = FontStyles.Bold;
            _counter.characterSpacing = 4f;
            _counter.textWrappingMode = TextWrappingModes.NoWrap;
            _counter.gameObject.AddComponent<LayoutElement>().flexibleWidth = 1f;

            GameObject dots = new GameObject("Puntos", typeof(RectTransform));
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

            _question = MakeText("Pregunta", body.transform, string.Empty, questionSize, Color.white, TextAlignmentOptions.Center);
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

            // Rótulo de acierto o fallo, sobre la esquina de la tarjeta.
            GameObject banner = new GameObject("Rotulo", typeof(RectTransform));
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
            GameObject bannerFill = MakeImage("Fondo", _banner, _roundSprite, Green);
            bannerFill.AddComponent<LayoutElement>().ignoreLayout = true;
            Stretch((RectTransform)bannerFill.transform);
            _bannerFill = bannerFill.GetComponent<Image>();
            _bannerText = MakeText("Texto", _banner, "¡Correcto!", 52f, Color.white, TextAlignmentOptions.Center);
            _bannerText.fontStyle = FontStyles.Bold;
            _bannerText.textWrappingMode = TextWrappingModes.NoWrap;
            banner.SetActive(false);

            EnsureDots(_total);
        }

        private OptionView BuildOption(Transform parent, string letter, Color letterColor)
        {
            OptionView view = new OptionView();
            GameObject row = new GameObject("Opcion" + letter, typeof(RectTransform), typeof(CanvasGroup));
            row.layer = parent.gameObject.layer;
            row.transform.SetParent(parent, false);
            view.Row = (RectTransform)row.transform;
            LayoutElement rowLayout = row.AddComponent<LayoutElement>();
            rowLayout.preferredHeight = optionHeight;
            rowLayout.minHeight = optionHeight;

            GameObject inner = new GameObject("Contenido", typeof(RectTransform));
            inner.layer = row.layer;
            inner.transform.SetParent(row.transform, false);
            view.Inner = (RectTransform)inner.transform;
            Stretch(view.Inner);

            view.Border = MakeImage("Borde", view.Inner, _roundSprite, WithAlpha(Color.white, 0.18f)).GetComponent<Image>();
            Stretch(view.Border.rectTransform);
            view.Fill = MakeImage("Fondo", view.Inner, _roundSprite, OptionFill).GetComponent<Image>();
            Stretch(view.Fill.rectTransform);
            view.Fill.rectTransform.offsetMin = new Vector2(3f, 3f);
            view.Fill.rectTransform.offsetMax = new Vector2(-3f, -3f);

            float badgeSize = optionHeight - 28f;
            view.Badge = MakeImage("Letra", view.Inner, _dotSprite, letterColor).GetComponent<Image>();
            RectTransform badge = view.Badge.rectTransform;
            badge.anchorMin = new Vector2(0f, 0.5f);
            badge.anchorMax = new Vector2(0f, 0.5f);
            badge.pivot = new Vector2(0f, 0.5f);
            badge.anchoredPosition = new Vector2(16f, 0f);
            badge.sizeDelta = new Vector2(badgeSize, badgeSize);
            view.Letter = MakeText("Texto", badge, letter, badgeSize * 0.56f, Color.white, TextAlignmentOptions.Center);
            view.Letter.fontStyle = FontStyles.Bold;
            Stretch(view.Letter.rectTransform);

            view.Text = MakeText("Opcion", view.Inner, string.Empty, optionSize, Color.white, TextAlignmentOptions.Left);
            view.Text.fontStyle = FontStyles.Bold;
            view.Text.enableAutoSizing = true;
            view.Text.fontSizeMin = optionSize * 0.7f;
            view.Text.fontSizeMax = optionSize;
            RectTransform text = view.Text.rectTransform;
            text.anchorMin = Vector2.zero;
            text.anchorMax = Vector2.one;
            text.offsetMin = new Vector2(16f + badgeSize + 24f, 8f);
            text.offsetMax = new Vector2(-(badgeSize + 20f), -8f);

            view.Mark = MakeImage("Marca", view.Inner, _checkSprite, Color.white).GetComponent<Image>();
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
            GameObject resultRoot = new GameObject("Resultado", typeof(RectTransform), typeof(CanvasGroup));
            resultRoot.layer = _root.gameObject.layer;
            resultRoot.transform.SetParent(_root, false);
            _result = (RectTransform)resultRoot.transform;
            _result.anchorMin = new Vector2(0.5f, 1f - cardTop);
            _result.anchorMax = _result.anchorMin;
            _result.pivot = new Vector2(0.5f, 1f);
            _result.sizeDelta = new Vector2(cardWidth, 0f);
            _resultGroup = resultRoot.GetComponent<CanvasGroup>();
            _resultGroup.alpha = 0f;

            GameObject glow = MakeImage("Halo", _result, _glowSprite, WithAlpha(Yellow, 0.3f));
            RectTransform glowRect = (RectTransform)glow.transform;
            glowRect.anchorMin = Vector2.zero;
            glowRect.anchorMax = Vector2.one;
            glowRect.offsetMin = new Vector2(-80f, -80f);
            glowRect.offsetMax = new Vector2(80f, 80f);
            GameObject border = MakeImage("Borde", _result, _roundSprite, WithAlpha(Yellow, 0.75f));
            Stretch((RectTransform)border.transform);
            GameObject fill = MakeImage("Fondo", _result, _roundSprite, CardFill);
            Stretch((RectTransform)fill.transform);
            ((RectTransform)fill.transform).offsetMin = new Vector2(4f, 4f);
            ((RectTransform)fill.transform).offsetMax = new Vector2(-4f, -4f);

            GameObject body = new GameObject("Contenido", typeof(RectTransform));
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

            TextMeshProUGUI eyebrow = MakeText("Titulo", body.transform, ColoredWord("TRIVIA") + "  DEVFEST", 34f, Color.white, TextAlignmentOptions.Center);
            eyebrow.fontStyle = FontStyles.Bold;
            eyebrow.characterSpacing = 10f;

            GameObject titleBox = new GameObject("Resultado", typeof(RectTransform));
            titleBox.layer = body.layer;
            titleBox.transform.SetParent(body.transform, false);
            titleBox.AddComponent<LayoutElement>().preferredHeight = 150f;
            _resultTitle = MakeText("Texto", titleBox.transform, "¡GANASTE!", 128f, Color.white, TextAlignmentOptions.Center);
            _resultTitle.fontStyle = FontStyles.Bold;
            _resultTitle.enableVertexGradient = true;
            _resultTitle.textWrappingMode = TextWrappingModes.NoWrap;
            Stretch(_resultTitle.rectTransform);

            GameObject stars = new GameObject("Estrellas", typeof(RectTransform));
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
                Image star = MakeImage("Estrella" + i, stars.transform, _starSprite, Yellow).GetComponent<Image>();
                LayoutElement starLayout = star.gameObject.AddComponent<LayoutElement>();
                starLayout.preferredWidth = 88f;
                starLayout.preferredHeight = 88f;
                _resultStars.Add(star);
            }

            _resultScore = MakeText("Aciertos", body.transform, "4 de 5 aciertos", 58f, Color.white, TextAlignmentOptions.Center);
            _resultScore.fontStyle = FontStyles.Bold;
            _resultLine = MakeText("Frase", body.transform, string.Empty, 38f, Muted, TextAlignmentOptions.Center);
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
                Image dot = MakeImage("Punto" + _dots.Count, _dotsRow, _dotSprite, Color.white).GetComponent<Image>();
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
            RectTransform body = (RectTransform)_card.Find("Contenido");
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

        /// <summary>Una palabra con cada letra en un color de Google, en texto enriquecido.</summary>
        private static string ColoredWord(string word)
        {
            System.Text.StringBuilder builder = new System.Text.StringBuilder();
            for (int i = 0; i < word.Length; i++)
            {
                Color color = GoogleColors[i % GoogleColors.Length];
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
                Debug.Log("[Sonia] Trivia: " + message, this);
            }
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

            // Marco: transparente en el centro y con luz en los bordes de la pantalla.
            const int frameSize = 256;
            const float frameSpread = 110f;
            Texture2D frame = MakeTexture("TriviaFrame", frameSize, (x, y) =>
            {
                float edge = Mathf.Min(Mathf.Min(x, frameSize - 1 - x), Mathf.Min(y, frameSize - 1 - y));
                float t = Mathf.Clamp01(1f - (edge / frameSpread));
                return t * t * t;
            });
            _frameSprite = MakeSprite(frame, new Vector4(frameSpread + 4f, frameSpread + 4f, frameSpread + 4f, frameSpread + 4f));

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

            // Destello de cuatro puntas (astroide).
            const int sparkleSize = 64;
            Texture2D sparkle = MakeTexture("TriviaSparkle", sparkleSize, (x, y) =>
            {
                float dx = Mathf.Abs((x + 0.5f - (sparkleSize * 0.5f)) / (sparkleSize * 0.5f));
                float dy = Mathf.Abs((y + 0.5f - (sparkleSize * 0.5f)) / (sparkleSize * 0.5f));
                float shape = Mathf.Pow(dx, 0.5f) + Mathf.Pow(dy, 0.5f);
                return Mathf.Clamp01((1f - shape) * 6f);
            });
            _sparkleSprite = MakeSprite(sparkle, Vector4.zero);

            // Estrella de cinco puntas.
            const int starSize = 128;
            Texture2D star = MakeTexture("TriviaStar", starSize, (x, y) =>
            {
                float px = (x + 0.5f - (starSize * 0.5f)) / (starSize * 0.5f);
                float py = (y + 0.5f - (starSize * 0.5f)) / (starSize * 0.5f);
                return Mathf.Clamp01(-StarDistance(px, py) * starSize * 0.5f + 0.5f);
            });
            _starSprite = MakeSprite(star, Vector4.zero);

            // Papelito: rectángulo con las esquinas algo redondeadas.
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

        /// <summary>Círculo de color con un visto o una cruz blancos.</summary>
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

        /// <summary>Distancia con signo a una estrella de cinco puntas de radio 0,95 (negativa dentro).</summary>
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
