// La ruleta de Sonnia (docs/juegos/ruleta.md, docs/plan-juegos.md 5.1): su pantalla.
//
// El orquestador lleva la partida y manda estados completos (docs/protocolo.md,
// eventos de «ruleta»):
//   - start: las cinco casillas (texto, título e icono).
//   - spin: la casilla de destino y lo que dura el giro. La ruleta gira, frena,
//     «hace clic» en cada clavija y, al parar, contesta wheel_stopped.
//   - challenge: la tarjeta del reto (y sus cambios: la pista, los fallos, el
//     contador, el «¡Tiempo!»). Si llega mientras la casilla ganadora aún brilla,
//     espera a que se vea; si llega con la ruleta girando, la ruleta para ya.
//   - result: el resultado en la tarjeta, el rótulo, el confeti y la reacción de
//     Sonnia (los clips de la trivia).
// Tras reconectar, el orquestador repite start y el último estado: una tarjeta de
// una vuelta que no se vio girar se pinta con la ruleta ya parada en su casilla.

using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia.Games.Ruleta
{
    /// <summary>Pantalla de «La ruleta de Sonnia» (id <c>ruleta</c>).</summary>
    public class RuletaController : GameControllerBase
    {
        /// <summary>Id del juego en el protocolo.</summary>
        public const string GameId = "ruleta";

        [Header("Ruleta")]
        [SerializeField]
        [Tooltip("Diámetro de la ruleta en la tarjeta (px de la referencia 1080x1920): grande, para leer las casillas a 2-3 m.")]
        private float wheelDiameter = 680f;

        [SerializeField]
        [Range(0f, 3f)]
        [Tooltip("Segundos que se ve la casilla ganadora antes de la tarjeta del reto.")]
        private float landHoldSeconds = 1.1f;

        [SerializeField]
        [Range(0.05f, 1f)]
        [Tooltip("Segundos del fundido entre la ruleta y la tarjeta del reto.")]
        private float viewFadeSeconds = 0.3f;

        [SerializeField]
        [Range(0.5f, 6f)]
        [Tooltip("Segundos que se ve el rótulo de un fallo con intentos por delante.")]
        private float missBannerSeconds = 2.5f;

        [Header("Reacciones de Sonnia (clips de la trivia)")]
        [SerializeField]
        private string winClip = "actions-highFive_actionSuccess";

        [SerializeField]
        private string winFallbackClip = "QuickAction_twoThumbsUp";

        [SerializeField]
        private string loseClip = "actions-highFive_actionFail";

        [SerializeField]
        private string passClip = "emotions-0049-traitsKind";

        [SerializeField]
        private string passFallbackClip = "Peace";

        [SerializeField]
        private string greatClip = "QuickAction_vibe";

        [SerializeField]
        private string okClip = "QuickAction_twoThumbsUp";

        /// <summary>Las casillas por defecto (las del orquestador, por si un start llega sin ellas).</summary>
        private static readonly SegmentInfo[] Defaults =
        {
            new SegmentInfo("trivia", "Trivia relámpago", "TRIVIA RELÁMPAGO", "bolt"),
            new SegmentInfo("adivinanza", "Adivinanza geek", "ADIVINANZA GEEK", "riddle"),
            new SegmentInfo("explica", "Explica en 20 s", "EXPLICA EN 20 SEGUNDOS", "mic"),
            new SegmentInfo("futuro", "Futuro de la IA", "PREDICE EL FUTURO DE LA IA", "crystal"),
            new SegmentInfo("sonnet", "Reto Sonnet Code", "RETO SORPRESA DE SONNET CODE", "star"),
        };

        private sealed class Pending
        {
            public bool Result;
            public ChallengeData Data;
        }

        private readonly RuletaIcons _icons = new RuletaIcons();
        private readonly RuletaWheel _wheel = new RuletaWheel();
        private readonly RuletaCard _card = new RuletaCard();
        private readonly Queue<Pending> _pending = new Queue<Pending>();
        private List<SegmentInfo> _segments = new List<SegmentInfo>();

        private CanvasGroup _wheelGroup;
        private RectTransform _winsBadge;
        private TextMeshProUGUI _winsText;

        private float _clock;
        private int _spin;
        private int _stoppedSpin;
        private float _holdUntil = -1f;
        private bool _showingCard;
        private int _cardSpin = -1;
        private bool _resultShown;
        private int _lastMisses;
        private bool _lastHint;
        private bool _timerRunning;
        private bool _timeUp;
        private float _bannerUntil = -1f;
        private float _contentHeight = -1f;

        /// <summary>Hueco arriba de la ruleta para la lengüeta (sin pisar el título) y margen de abajo.</summary>
        private const float WheelTopMargin = 40f;
        private const float WheelBottomMargin = 12f;

        /// <summary>Lo que crece o encoge por segundo el contenido al pasar de la ruleta al reto.</summary>
        private const float HeightSpeed = 2000f;

        public override string Id
        {
            get { return GameId; }
        }

        protected override string DefaultTitle
        {
            get { return "La ruleta de Sonnia"; }
        }

        /// <summary>La casilla <paramref name="index"/> por defecto.</summary>
        internal static SegmentInfo DefaultSegment(int index)
        {
            return Defaults[Mathf.Clamp(index, 0, Defaults.Length - 1)];
        }

        // ------------------------------------------------------------------
        // Eventos
        // ------------------------------------------------------------------

        protected override void OnStart(string dataJson)
        {
            if (!EnsureBuilt())
            {
                Log("sin HUD: no se puede montar la ruleta");
                return;
            }

            RuletaStartData start = ParseData<RuletaStartData>(dataJson);
            _segments = start.Segments ?? new List<SegmentInfo>();
            _wheel.SetSegments(Hud, _icons, _segments);
            ResetScreen();
            SetContentHeight(WheelHeight);
            if (_winsBadge != null)
            {
                _winsBadge.gameObject.SetActive(true);
            }

            UpdateWins(0);
        }

        protected override void OnGameEvent(string eventName, string dataJson)
        {
            if (!_card.IsBuilt)
            {
                return;
            }

            switch (eventName)
            {
                case "spin":
                    HandleSpin(ParseData<SpinData>(dataJson));
                    break;
                case "challenge":
                    _pending.Enqueue(new Pending { Result = false, Data = ParseData<ChallengeData>(dataJson) });
                    ProcessPending();
                    break;
                case "result":
                    _pending.Enqueue(new Pending { Result = true, Data = ParseData<ChallengeData>(dataJson) });
                    ProcessPending();
                    break;
                default:
                    Log("evento desconocido: " + eventName);
                    break;
            }
        }

        protected override void OnClosed()
        {
            ResetScreen();
            _contentHeight = -1f;
            _spin = 0;
            _stoppedSpin = 0;
            if (_winsBadge != null)
            {
                _winsBadge.gameObject.SetActive(false);
            }
        }

        private void OnDestroy()
        {
            if (Hud != null)
            {
                Hud.Opened -= OnHudOpened;
            }

            _icons.Destroy();
        }

        // ------------------------------------------------------------------
        // Montaje
        // ------------------------------------------------------------------

        private bool EnsureBuilt()
        {
            if (_card.IsBuilt)
            {
                return true;
            }

            RectTransform content = Content;
            if (Hud == null || content == null)
            {
                return false;
            }

            _icons.Build();
            _wheelGroup = Hud.NewGroup("VistaRuleta", content);
            _wheel.Build(Hud, _icons, (RectTransform)_wheelGroup.transform, new Vector2(0f, -((wheelDiameter * 0.5f) + WheelTopMargin)), wheelDiameter);
            _wheel.Stopped += OnWheelStopped;
            _card.Build(Hud, _icons, content);

            // Retos superados, en el hueco de la derecha de la cabecera (solo con la ruleta).
            RectTransform right = Hud.HeaderRight;
            if (right != null)
            {
                _winsBadge = Hud.NewRect("RuletaSuperados", right);
                HorizontalLayoutGroup row = _winsBadge.gameObject.AddComponent<HorizontalLayoutGroup>();
                row.spacing = 8f;
                row.childAlignment = TextAnchor.MiddleRight;
                row.childControlWidth = true;
                row.childControlHeight = true;
                row.childForceExpandWidth = false;
                row.childForceExpandHeight = false;
                Image star = Hud.NewImage("Estrella", _winsBadge, Hud.StarSprite, GameColors.Gold);
                star.preserveAspect = true;
                LayoutElement starLayout = star.gameObject.AddComponent<LayoutElement>();
                starLayout.preferredWidth = 38f;
                starLayout.preferredHeight = 38f;
                _winsText = Hud.NewText("Cuenta", _winsBadge, "0", 34f, GameColors.Gold, TextAlignmentOptions.Left, Hud.DisplayFont);
                _winsText.textWrappingMode = TextWrappingModes.NoWrap;
                _winsBadge.gameObject.SetActive(false);
                Hud.Opened += OnHudOpened;
            }

            return true;
        }

        private void OnHudOpened(string gameId)
        {
            // Otro juego toma la cabecera: lo de la ruleta, fuera.
            if (gameId != Id && _winsBadge != null)
            {
                _winsBadge.gameObject.SetActive(false);
            }
        }

        private void ResetScreen()
        {
            _pending.Clear();
            _holdUntil = -1f;
            _showingCard = false;
            _cardSpin = -1;
            _resultShown = false;
            _timerRunning = false;
            _timeUp = false;
            _bannerUntil = -1f;
            if (!_card.IsBuilt)
            {
                return;
            }

            _wheel.ResetIdle(0);
            _card.Clear();
            _card.Group.alpha = 0f;
            _wheelGroup.alpha = 1f;
            _wheelGroup.gameObject.SetActive(true);
            if (Hud != null)
            {
                Hud.StopCountdown();
                Hud.HideBanner();
                Hud.SetCaption(string.Empty);
                PlaceCountdownInCorner();
            }
        }

        // ------------------------------------------------------------------
        // El giro
        // ------------------------------------------------------------------

        private void HandleSpin(SpinData data)
        {
            if (data.Spin > 0 && data.Spin == _spin && (_wheel.IsSpinning || _stoppedSpin == _spin))
            {
                return; // repetido (reconexión): ya giró
            }

            _spin = data.Spin;
            _pending.Clear();
            _holdUntil = -1f;
            _cardSpin = -1;
            _resultShown = false;
            _timerRunning = false;
            _timeUp = false;
            _bannerUntil = -1f;
            Hud.HideBanner();
            Hud.StopCountdown();
            PlaceCountdownInCorner();
            _showingCard = false;
            Hud.SetCaption(CaptionFor(data.Spin));
            UpdateWins(data.Wins);
            _wheel.Spin(data.Segment, data.Duration);
            Log("gira la vuelta " + data.Spin + " hacia la casilla " + data.Segment);
        }

        private void OnWheelStopped(int segment)
        {
            if (_stoppedSpin != _spin)
            {
                _stoppedSpin = _spin;
                Send("wheel_stopped", new Dictionary<string, object> { { "spin", _spin }, { "segment", segment } });
            }

            _holdUntil = _clock + landHoldSeconds;
            ShowEmotion(FacialExpressionController.Emotion.Surprise, 1.4f);
            Log("la ruleta paró en la casilla " + segment);
        }

        // ------------------------------------------------------------------
        // El reto
        // ------------------------------------------------------------------

        private void ProcessPending()
        {
            while (_pending.Count > 0)
            {
                Pending next = _pending.Peek();
                ChallengeData data = next.Data;
                if (data.Spin > 0 && data.Spin < _spin)
                {
                    _pending.Dequeue(); // de una vuelta anterior
                    continue;
                }

                if (data.Spin > _spin || (_stoppedSpin != _spin && !_wheel.IsSpinning))
                {
                    // Una vuelta que no se vio girar (reconexión): la ruleta, ya parada.
                    _spin = data.Spin;
                    _stoppedSpin = data.Spin;
                    _wheel.SnapTo(data.Segment);
                    _holdUntil = -1f;
                }
                else if (_wheel.IsSpinning)
                {
                    // El orquestador no esperó al final del giro: para ya.
                    _wheel.SnapTo(data.Segment);
                    _stoppedSpin = _spin;
                    _holdUntil = _clock + (landHoldSeconds * 0.5f);
                }

                if (_holdUntil > _clock)
                {
                    return; // que se vea la casilla ganadora
                }

                _pending.Dequeue();
                Apply(next.Result, data);
            }
        }

        private void Apply(bool result, ChallengeData data)
        {
            UpdateWins(data.Wins);
            Hud.SetCaption(CaptionFor(data.Spin));
            if (_cardSpin != data.Spin || !_showingCard)
            {
                ShowCard(data);
            }
            else
            {
                RefreshCard(data);
            }

            if (result && !_resultShown)
            {
                ShowResult(data);
            }
        }

        private void ShowCard(ChallengeData data)
        {
            SegmentInfo segment = SegmentAt(data.Segment);
            _card.Show(data, segment, data.Segment);
            _cardSpin = data.Spin;
            _resultShown = false;
            _lastMisses = data.Misses;
            _lastHint = !string.IsNullOrEmpty(data.Hint);
            _timerRunning = false;
            _timeUp = false;
            _showingCard = true;
            _card.Group.gameObject.SetActive(true);
            GameAnim.Pop(_card.Root, 0.45f);
            Hud.PopCard();
            ApplyTimer(data);
            Log("reto " + data.Kind + " (vuelta " + data.Spin + ")");
        }

        private void RefreshCard(ChallengeData data)
        {
            _card.Refresh(data);
            if (data.Misses > _lastMisses && string.IsNullOrEmpty(data.Outcome))
            {
                GameAnim.Shake(_card.TriesRect);
                Hud.ShowBanner("¡No es eso!", GameColors.Red);
                _bannerUntil = _clock + missBannerSeconds;
                ShowEmotion(FacialExpressionController.Emotion.Sad, 1.2f);
            }

            bool hint = !string.IsNullOrEmpty(data.Hint);
            if (hint && !_lastHint && string.IsNullOrEmpty(data.Outcome))
            {
                // Sin destellos encima: la pista hay que leerla.
                GameAnim.Pop(_card.HintBox, 0.45f);
            }

            _lastMisses = data.Misses;
            _lastHint = hint;
            ApplyTimer(data);
        }

        private void ApplyTimer(ChallengeData data)
        {
            if (!string.IsNullOrEmpty(data.Outcome))
            {
                return;
            }

            bool running = data.Timer != null && data.Timer.Running && data.Timer.Seconds > 0f;
            if (running && !_timerRunning && !data.TimeUp)
            {
                _timerRunning = true;
                if (data.Kind == "explica" && _card.CountdownSlot != null)
                {
                    Hud.PlaceCountdown(_card.CountdownSlot, new Vector2(0.5f, 0.5f), Vector2.zero, 200f);
                }
                else
                {
                    PlaceCountdownInCorner();
                }

                Hud.StartCountdown(data.Timer.Seconds);
            }

            if (data.TimeUp && !_timeUp)
            {
                // El contador, a cero (en rojo y con su latido), aunque fuera algo por detrás.
                _timeUp = true;
                Hud.StartCountdown(0.1f);
                Hud.ShowBanner("¡Tiempo!", GameColors.Red);
                _bannerUntil = -1f;
                ShowEmotion(FacialExpressionController.Emotion.Surprise, 1.6f);
            }
        }

        private void ShowResult(ChallengeData data)
        {
            _resultShown = true;
            _bannerUntil = -1f;
            Hud.StopCountdown();
            _card.ShowResult(data);
            string outcome = data.Outcome ?? string.Empty;
            switch (data.Kind)
            {
                case "trivia":
                    string letter = data.Correct >= 0 && data.Correct < 3 ? "ABC".Substring(data.Correct, 1) : "?";
                    if (outcome == "win")
                    {
                        Win("¡Correcto!", _card.OptionRect(data.Correct));
                    }
                    else if (outcome == "lose")
                    {
                        Lose("¡Uy! Era la " + letter);
                    }
                    else
                    {
                        Pass("Era la " + letter);
                    }

                    break;
                case "explica":
                    int score = Mathf.Clamp(data.Score, 0, 10);
                    string line = "¡Nota " + score + "!";
                    if (score >= 7)
                    {
                        Hud.ShowBanner(line, GameColors.Green);
                        Hud.BurstFrom(_card.StarsRect, 90, 1300f);
                        PlayReaction(greatClip, winFallbackClip);
                        ShowEmotion(FacialExpressionController.Emotion.Joy, 3f);
                    }
                    else if (score >= 4)
                    {
                        Hud.ShowBanner(line, GameColors.Blue);
                        PlayReaction(okClip, null);
                        ShowEmotion(FacialExpressionController.Emotion.Joy, 2f);
                    }
                    else
                    {
                        Hud.ShowBanner(line, GameColors.Red);
                        PlayReaction(passClip, passFallbackClip);
                        ShowEmotion(FacialExpressionController.Emotion.Joy, 2f);
                    }

                    break;
                case "futuro":
                    if (outcome == "pass")
                    {
                        Pass("¡Otra vez será!");
                        break;
                    }

                    Hud.ShowBanner("¡Lo veremos!", GameColors.Blue);
                    PlayReaction(okClip, null);
                    ShowEmotion(FacialExpressionController.Emotion.Surprise, 2f);
                    break;
                default:
                    // Adivinanza y reto de Sonnet Code.
                    if (outcome == "win")
                    {
                        Win(data.Kind == "sonnet" && data.Task ? "¡Genial!" : "¡Acertaste!", _card.AnswerRect);
                    }
                    else if (outcome == "lose")
                    {
                        Lose("¡Casi!");
                    }
                    else
                    {
                        Pass("¡Otra vez será!");
                    }

                    break;
            }

            Log("resultado de " + data.Kind + ": " + outcome);
        }

        private void Win(string banner, RectTransform from)
        {
            Hud.ShowBanner(banner, GameColors.Green);
            if (from != null)
            {
                Hud.BurstFrom(from, 90, 1300f);
                Hud.SparklesAt(from, 10);
            }

            PlayReaction(winClip, winFallbackClip);
            ShowEmotion(FacialExpressionController.Emotion.Joy, 3f);
        }

        private void Lose(string banner)
        {
            Hud.ShowBanner(banner, GameColors.Red);
            PlayReaction(loseClip, null);
            ShowEmotion(FacialExpressionController.Emotion.Sad, 2.4f);
        }

        private void Pass(string banner)
        {
            Hud.ShowBanner(banner, new Color(0.16f, 0.3f, 0.62f, 1f));
            PlayReaction(passClip, passFallbackClip);
            ShowEmotion(FacialExpressionController.Emotion.Joy, 2f);
        }

        // ------------------------------------------------------------------
        // Utilidades
        // ------------------------------------------------------------------

        private SegmentInfo SegmentAt(int index)
        {
            if (_segments != null && index >= 0 && index < _segments.Count && _segments[index] != null)
            {
                return _segments[index];
            }

            return DefaultSegment(index);
        }

        private static string CaptionFor(int spin)
        {
            return spin > 0 ? "VUELTA " + spin : string.Empty;
        }

        private void UpdateWins(int wins)
        {
            if (_winsBadge == null)
            {
                return;
            }

            bool show = wins > 0;
            if (_winsText != null)
            {
                _winsText.text = wins.ToString();
            }

            Transform star = _winsBadge.Find("Estrella");
            if (star != null)
            {
                star.gameObject.SetActive(show);
            }

            if (_winsText != null)
            {
                _winsText.gameObject.SetActive(show);
            }
        }

        /// <summary>Alto del contenido con la ruleta (la tarjeta crece mientras gira).</summary>
        private float WheelHeight
        {
            get { return wheelDiameter + WheelTopMargin + WheelBottomMargin; }
        }

        private void SetContentHeight(float height)
        {
            _contentHeight = height;
            Hud.SetContentHeight(Id, height);
        }

        /// <summary>
        /// El alto del contenido sigue a lo que se ve: crece en cuanto vuelve la ruleta y
        /// encoge al de la tarjeta del reto cuando la ruleta ya se fundió (si no, asomaría
        /// por debajo de la tarjeta). La cámara lo sigue sola (plano de panel automático).
        /// </summary>
        private void UpdateContentHeight(float dt)
        {
            if (!IsActive || _contentHeight < 0f)
            {
                return;
            }

            float target = _showingCard ? (_wheelGroup.alpha <= 0.02f ? RuletaCard.Height : _contentHeight) : WheelHeight;
            if (Mathf.Abs(target - _contentHeight) < 0.5f)
            {
                return;
            }

            SetContentHeight(Mathf.MoveTowards(_contentHeight, target, dt * HeightSpeed));
        }

        private void PlaceCountdownInCorner()
        {
            if (Hud != null && Hud.Card != null)
            {
                Hud.PlaceCountdown(Hud.Card, new Vector2(1f, 1f), new Vector2(-48f, 4f), 150f);
            }
        }

        private void Update()
        {
            if (!_card.IsBuilt)
            {
                return;
            }

            float dt = Time.deltaTime;
            _clock += dt;
            _wheel.Tick(dt);
            _card.Tick(dt);

            // Fundido entre la ruleta y la tarjeta del reto.
            float step = dt / Mathf.Max(0.05f, viewFadeSeconds);
            _wheelGroup.alpha = Mathf.MoveTowards(_wheelGroup.alpha, _showingCard ? 0f : 1f, step);
            _card.Group.alpha = Mathf.MoveTowards(_card.Group.alpha, _showingCard ? 1f : 0f, step);
            bool wheelVisible = _wheelGroup.alpha > 0.001f;
            if (_wheelGroup.gameObject.activeSelf != wheelVisible)
            {
                _wheelGroup.gameObject.SetActive(wheelVisible);
            }

            UpdateContentHeight(dt);

            if (_bannerUntil > 0f && _clock >= _bannerUntil)
            {
                _bannerUntil = -1f;
                if (!_resultShown && !_timeUp)
                {
                    Hud.HideBanner();
                }
            }

            if (_pending.Count > 0)
            {
                ProcessPending();
            }
        }
    }
}
