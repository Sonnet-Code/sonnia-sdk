// Simón dice con poses (docs/juegos/poses.md, docs/plan-juegos.md 5.2): pantalla
// de Unity y demostración de Sonnia.
//
// Pantalla (vertical 9:16, sin tapar la cara de Sonnia), toda en la franja alta
// para que a Sonnia le quede sitio de levantar los brazos:
//  - Arriba, una cabecera fina con el título en los colores de Google y «RONDA 2
//    DE 6» (la tarjeta común no se enseña: aquí lo principal es la imagen).
//  - Debajo, la vista en vivo grande (CameraPreviewPanel), con los esqueletos que
//    dibuja el orquestador. Encima de ella, en la capa del juego:
//      · el pictograma de la pose (monigote blanco) arriba a la derecha (arriba a
//        la izquierda ya está «En vivo · no se graba»);
//      · el rótulo de la orden abajo, como un rótulo de televisión, con «Simón
//        dice» en amarillo cuando lo dijo;
//      · el contador circular de la ventana a la izquierda;
//      · el resultado en el centro: «7 de 9» o «¡Cayeron 4!» en las trampas;
//      · al colocarse, cuántos juegan y el aviso (un paso atrás...).
//  - Al final, la tarjeta del resultado (la común) arriba, encima de la vista, con
//    el total del grupo y celebración.
// La cámara usa el plano de panel automático del GameHud, con la franja reservada
// hasta el borde de abajo de la vista en vivo aunque aún no haya llegado imagen.
//
// Sonnia demuestra cada pose sostenida por código (PosesDemo) desde «round»
// hasta «result». Con data.demo con el nombre de un clip, lo enseña con ese clip
// (gesto de Genies o del set) en vez de la pose por código; con «ninguna», nada.
//
// Cada evento trae el estado completo (protocolo en docs/protocolo.md, «poses»),
// así que una Unity que se reconecta lo pinta todo con el último.

using System;
using Newtonsoft.Json;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia.Games.Poses
{
    /// <summary>data del start de «poses».</summary>
    [Serializable]
    public class PosesStartData
    {
        [JsonProperty("rounds")] public int Rounds;
    }

    /// <summary>El estado completo que trae cada evento de «poses».</summary>
    [Serializable]
    public class PosesState
    {
        [JsonProperty("phase")] public string Phase;
        [JsonProperty("round")] public int Round;
        [JsonProperty("rounds")] public int Rounds;
        [JsonProperty("pose")] public string Pose;
        [JsonProperty("label")] public string Label;
        [JsonProperty("meme")] public string Meme;
        [JsonProperty("demo")] public string Demo;
        [JsonProperty("order")] public string Order;
        [JsonProperty("simon")] public bool Simon = true;
        [JsonProperty("seconds")] public float Seconds;
        [JsonProperty("count")] public int Count;
        [JsonProperty("total")] public int Total;
        [JsonProperty("players")] public int Players;
        [JsonProperty("hint")] public string Hint;
        [JsonProperty("done")] public int Done;
        [JsonProperty("possible")] public int Possible;
        [JsonProperty("fell")] public int Fell;
    }

    /// <summary>Pantalla de «Simón dice con poses» (id <c>poses</c>).</summary>
    public class PosesController : GameControllerBase
    {
        /// <summary>Id del juego en el protocolo.</summary>
        public const string GameId = "poses";

        private const string NoDemo = "ninguna";
        private const string SimonWords = "Simón dice";

        [Header("Diseño (píxeles de la referencia 1080x1920)")]
        [SerializeField]
        [Range(0f, 0.5f)]
        [Tooltip("Borde de arriba de la cabecera (título y ronda), en fracción del alto: el de la tarjeta de los juegos.")]
        private float headerTop = 0.105f;

        [SerializeField]
        [Tooltip("Alto de la cabecera.")]
        private float headerHeight = 76f;

        [SerializeField]
        [Tooltip("Separación entre la cabecera y la vista en vivo.")]
        private float headerGap = 12f;

        [SerializeField]
        [Tooltip("Ancho de la vista en vivo (16:9).")]
        private float previewWidth = 960f;

        [SerializeField]
        [Tooltip("Lado del pictograma de la pose.")]
        private float pictogramSize = 196f;

        [Header("Cámara")]
        [SerializeField]
        [Tooltip("Píxeles de más que se reservan bajo la vista en vivo para el plano automático: sitio para que se vean las manos de Sonnia arriba.")]
        private float extraReserve = 80f;

        [SerializeField]
        [Tooltip("Mientras Sonnia enseña la pose T, la cámara se aleja como si la franja alta bajara estos píxeles más: así se le ven las dos manos.")]
        private float wideReserve = 300f;

        private PosesDemo _demo;
        private bool _built;
        private RectTransform _header;
        private TextMeshProUGUI _headerTitle;
        private TextMeshProUGUI _headerCaption;
        private RectTransform _stage;
        private CanvasGroup _stageGroup;
        private RectTransform _waiting;
        private RectTransform _pictoBox;
        private PosesPictogram _picto;
        private TextMeshProUGUI _pictoLabel;
        private RectTransform _chip;
        private TextMeshProUGUI _chipText;
        private RectTransform _lower;
        private TextMeshProUGUI _orderText;
        private RectTransform _badge;
        private Image _badgeFill;
        private TextMeshProUGUI _badgeText;
        private TextMeshProUGUI _badgeSub;

        private PosesState _state = new PosesState();
        private bool _wide;
        private string _shownPose;
        private bool _demoClip;
        private int _demoRound = -1;
        private bool _finalShown;
        private float _attentionPulseAt = -1f;

        public override string Id
        {
            get { return GameId; }
        }

        protected override string DefaultTitle
        {
            get { return "Simón dice con poses"; }
        }

        protected override void Awake()
        {
            base.Awake();
            _demo = GetComponent<PosesDemo>();
            if (_demo == null)
            {
                _demo = gameObject.AddComponent<PosesDemo>();
            }
        }

        private void Update()
        {
            if (!_built || !IsActive)
            {
                return;
            }

            float dt = Time.deltaTime;
            if (_picto != null)
            {
                _picto.Tick(dt);
            }

            // Sin imagen de la cámara, un fondo con aviso donde iría la vista.
            bool live = Preview != null && Preview.IsVisible;
            if (_waiting != null && _waiting.gameObject.activeSelf == live)
            {
                _waiting.gameObject.SetActive(!live);
            }

            // Si la vista se retiró (sin frames) y vuelve, vuelve a su sitio de siempre: a la nuestra.
            if (live && !IsEnding)
            {
                float expected = PreviewTop + ((previewWidth / CameraPreviewPanel.Aspect) / GameHud.ReferenceHeight);
                if (Mathf.Abs(Preview.BottomFraction - expected) > 0.001f)
                {
                    Preview.SetPlacement(PreviewTop, previewWidth);
                }
            }

            // Con el resultado final (la tarjeta común, debajo de esta capa) o al terminar, lo nuestro se va.
            if (_stageGroup != null)
            {
                bool away = IsEnding || _finalShown;
                _stageGroup.alpha = Mathf.MoveTowards(_stageGroup.alpha, away ? 0f : 1f, dt / 0.3f);
            }

            // «¡Atentos a Sonnia!» late mientras enseña la pose.
            if (_attentionPulseAt >= 0f && Time.time >= _attentionPulseAt && _state.Phase == "round")
            {
                _attentionPulseAt = Time.time + 1.1f;
                GameAnim.Pulse(_lower, 0.05f, 0.4f);
            }
        }

        // ------------------------------------------------------------------
        // Eventos
        // ------------------------------------------------------------------

        protected override void OnStart(string dataJson)
        {
            Build();
            PosesStartData start = ParseData<PosesStartData>(dataJson);
            _state = new PosesState { Phase = "placement", Rounds = Mathf.Max(0, start.Rounds) };
            _shownPose = null;
            _demoClip = false;
            _demoRound = -1;
            _finalShown = false;

            // La tarjeta común no sale: la cabecera fina y la vista en vivo ocupan menos.
            Hud.SetContentHeight(Id, 0f);
            Hud.SetCardVisible(false);
            float top = PreviewTop;
            Preview.SetPlacement(top, previewWidth);
            Vector2 frame = new Vector2(previewWidth, previewWidth / CameraPreviewPanel.Aspect);
            GameUi.PlaceTop(_stage, top, frame);
            GameUi.PlaceTop(_header, headerTop, new Vector2(previewWidth, headerHeight));
            _headerTitle.text = GameUi.ColoredWord(GameUi.Plain(Title ?? DefaultTitle).ToUpperInvariant());
            Hud.RequestPanelShot();
            _wide = false;
            ReserveStrip();
            Hud.PlaceCountdown(_stage, new Vector2(0f, 0.5f), new Vector2(112f, -6f), 150f);
            _stageGroup.gameObject.SetActive(true);
            _stage.gameObject.SetActive(true);
            _header.gameObject.SetActive(true);
            _stageGroup.alpha = 0f;
            ShowPlacement(_state);
        }

        protected override void OnGameEvent(string eventName, string dataJson)
        {
            Build();
            PosesState state = ParseData<PosesState>(dataJson);
            if (state.Rounds <= 0)
            {
                state.Rounds = _state.Rounds;
            }

            state.Phase = eventName;
            switch (eventName)
            {
                case "placement":
                    ShowPlacement(state);
                    break;
                case "round":
                    ShowRound(state);
                    break;
                case "command":
                    ShowCommand(state, true);
                    break;
                case "window":
                    ShowWindow(state);
                    break;
                case "result":
                    ShowRoundResult(state);
                    break;
                case "final":
                    ShowFinal(state);
                    break;
                default:
                    Log("evento desconocido: " + eventName);
                    return;
            }

            _state = state;
        }

        protected override void OnFinish(string result, string dataJson)
        {
            Release();
            Hud.StopCountdown();
            if (result == GameResults.Win && !_finalShown)
            {
                ShowFinal(ParseData<PosesState>(dataJson));
            }
        }

        protected override void OnClosed()
        {
            _demo.ReleaseNow();
            _shownPose = null;
            _demoClip = false;
            _demoRound = -1;
            _attentionPulseAt = -1f;
            _wide = false;
            if (_stageGroup != null)
            {
                _stageGroup.gameObject.SetActive(false);
            }

            if (Preview != null)
            {
                Preview.ResetPlacement();
            }
        }

        // ------------------------------------------------------------------
        // Estados
        // ------------------------------------------------------------------

        private void ShowPlacement(PosesState s)
        {
            Release();
            Hud.StopCountdown();
            SetCaption("Colócate");
            _attentionPulseAt = -1f;
            _pictoBox.gameObject.SetActive(false);
            _badge.gameObject.SetActive(false);
            _chip.gameObject.SetActive(true);
            _chipText.text = s.Players == 1 ? "1 JUGANDO" : s.Players > 1 ? s.Players + " JUGANDO" : "NO VEO A NADIE";
            // El aviso del orquestador (un paso atrás...) en amarillo; sin aviso, la indicación de siempre.
            bool warn = !string.IsNullOrEmpty(s.Hint);
            string hint = warn ? s.Hint : "Ponte donde te vea entero, a unos 2 m de la pantalla";
            SetLower(GameUi.Plain(hint), warn ? GameColors.Yellow : GameColors.Muted, 44f);
        }

        private void ShowRound(PosesState s)
        {
            Hud.StopCountdown();
            SetCaption(RoundCaption(s));
            GameAnim.Pulse(_header, 0.04f, 0.35f);
            _chip.gameObject.SetActive(false);
            _badge.gameObject.SetActive(false);
            ShowPictogram(s);
            SetLower("¡Atentos a Sonnia!", GameColors.Muted, 44f);
            _attentionPulseAt = Time.time + 0.6f;
            Demonstrate(s);
        }

        private void ShowCommand(PosesState s, bool pop)
        {
            SetCaption(RoundCaption(s));
            _chip.gameObject.SetActive(false);
            _badge.gameObject.SetActive(false);
            ShowPictogram(s);
            _attentionPulseAt = -1f;
            SetLower(OrderText(s), Color.white, 50f);
            if (pop)
            {
                GameAnim.Pop(_lower, 0.35f);
            }

            Demonstrate(s);
        }

        private void ShowWindow(PosesState s)
        {
            ShowCommand(s, _state.Phase != "command");
            Hud.StartCountdown(s.Seconds > 0f ? s.Seconds : 1.8f);
        }

        private void ShowRoundResult(PosesState s)
        {
            Hud.StopCountdown();
            SetCaption(RoundCaption(s));
            _chip.gameObject.SetActive(false);
            _attentionPulseAt = -1f;
            ShowPictogram(s);
            SetLower(OrderText(s), GameUi.WithAlpha(Color.white, 0.75f), 50f);
            Release();

            bool trick = !s.Simon;
            int count = Mathf.Max(0, s.Count);
            int total = Mathf.Max(0, s.Total);
            Color fill;
            string big;
            string sub;
            bool great;
            if (trick)
            {
                great = count == 0;
                big = great ? "¡Nadie cayó!" : count == 1 ? "¡Cayó 1!" : "¡Cayeron " + count + "!";
                sub = "Era trampa: sin «Simón dice»";
                fill = great ? GameColors.RightFill : GameColors.WrongFill;
            }
            else if (total <= 0)
            {
                great = false;
                big = "No veo a nadie";
                sub = "Ponte donde te vea entero";
                fill = GameColors.OptionFill;
            }
            else
            {
                great = count >= total;
                big = count + " de " + total;
                sub = great ? "¡Todos hicieron la pose!" : count == 1 ? "hizo la pose" : "hicieron la pose";
                fill = great ? GameColors.RightFill : count * 2 >= total ? GameColors.Brand : GameColors.OptionFill;
            }

            _badgeFill.color = fill;
            _badgeText.text = big;
            _badgeSub.text = sub;
            _badge.gameObject.SetActive(true);
            GameAnim.Pop(_badge, 0.45f);
            if (great)
            {
                Hud.SparklesAt(_badge, 12);
                Hud.BurstFrom(_badge, 60, 1100f);
                ShowEmotion(FacialExpressionController.Emotion.Joy, 2.5f);
            }
            else if (trick)
            {
                GameAnim.Shake(_badge);
                ShowEmotion(FacialExpressionController.Emotion.Surprise, 2f);
            }
        }

        private void ShowFinal(PosesState s)
        {
            Release();
            Hud.StopCountdown();
            _attentionPulseAt = -1f;
            _badge.gameObject.SetActive(false);
            _finalShown = true;
            string title;
            string score = null;
            string line;
            if (s.Possible > 0)
            {
                title = "¡QUÉ EQUIPO!";
                score = s.Done + " de " + s.Possible;
                line = "poses bien hechas";
                if (s.Fell > 0)
                {
                    line += s.Fell == 1 ? " · 1 cayó en la trampa" : " · " + s.Fell + " cayeron en la trampa";
                }
            }
            else
            {
                title = "¡GRACIAS POR JUGAR!";
                line = "Pídele otra partida a Sonnia";
            }

            // La tarjeta del resultado arriba, encima de la vista en vivo (si no, iría debajo).
            Hud.SetCardTop(headerTop);
            Hud.ShowResult(title, score, line, true);
            _pictoBox.gameObject.SetActive(false);
            _lower.gameObject.SetActive(false);
            PlayReaction("QuickAction_vibe", null);
            ShowEmotion(FacialExpressionController.Emotion.Joy, 4f);
        }

        // ------------------------------------------------------------------
        // Sonnia
        // ------------------------------------------------------------------

        /// <summary>Sonnia enseña la pose de la ronda (una vez por ronda) y la sostiene.</summary>
        private void Demonstrate(PosesState s)
        {
            string demo = (s.Demo ?? string.Empty).Trim();
            if (demo == NoDemo)
            {
                Release();
                return;
            }

            if (demo.Length > 0)
            {
                // Un clip en vez de la pose por código: suena entero, una vez por ronda.
                if (_demoRound == s.Round && _demoClip)
                {
                    return;
                }

                _demo.Release();
                _shownPose = null;
                _demoRound = s.Round;
                if (Choreographer != null && Choreographer.PlayGenieReaction(demo))
                {
                    _demoClip = true;
                    return;
                }

                SoniaMotionSet set = Choreographer != null ? Choreographer.MotionSet : null;
                AnimationCatalog.Entry entry;
                if (set != null && AnimationCatalog.TryFind(set, demo, out entry))
                {
                    Choreographer.PlayReaction(entry.Clip);
                    _demoClip = true;
                    return;
                }

                Log("no hay clip «" + demo + "»: pose por código");
            }

            _demoClip = false;
            _demoRound = s.Round;
            SetWide(s.Pose == "pose_t");
            if (_shownPose == s.Pose && _demo.Current == s.Pose)
            {
                return;
            }

            _shownPose = _demo.Show(s.Pose) ? s.Pose : null;
        }

        /// <summary>
        /// Con la pose T, la cámara se aleja (el plano automático de una franja más baja)
        /// para que se vean las dos manos; al soltarla, vuelve al automático.
        /// </summary>
        private void SetWide(bool wide)
        {
            if (_wide == wide || Hud == null)
            {
                return;
            }

            _wide = wide;
            if (wide)
            {
                Hud.RequestPanelShot(Hud.AutoPanelExtra(StripBottom() + wideReserve));
            }
            else
            {
                Hud.RequestPanelShot();
            }
        }

        /// <summary>La franja reservada hasta el borde de abajo de la vista en vivo, con el margen para las manos arriba.</summary>
        private void ReserveStrip()
        {
            if (Hud != null)
            {
                Hud.ReserveTopStrip(StripBottom());
            }
        }

        private float StripBottom()
        {
            float frameHeight = previewWidth / CameraPreviewPanel.Aspect;
            return (PreviewTop * GameHud.ReferenceHeight) + frameHeight + extraReserve;
        }

        private void Release()
        {
            _demo.Release();
            _shownPose = null;
            _demoClip = false;
            SetWide(false);
        }

        // ------------------------------------------------------------------
        // Pantalla
        // ------------------------------------------------------------------

        private void ShowPictogram(PosesState s)
        {
            bool changed = !_pictoBox.gameObject.activeSelf || _pictoLabel.text != PoseLabel(s);
            _pictoBox.gameObject.SetActive(true);
            _pictoLabel.text = PoseLabel(s);
            if (changed)
            {
                _picto.SetPose(s.Pose, false);
                GameAnim.Pop(_pictoBox, 0.4f);
            }
            else
            {
                _picto.SetPose(s.Pose, false);
            }
        }

        /// <summary>Borde de arriba de la vista en vivo: justo debajo de la cabecera.</summary>
        private float PreviewTop
        {
            get { return headerTop + ((headerHeight + headerGap) / GameHud.ReferenceHeight); }
        }

        private void SetCaption(string caption)
        {
            if (_headerCaption != null)
            {
                _headerCaption.text = GameUi.Plain(caption ?? string.Empty).ToUpperInvariant();
            }
        }

        private void SetLower(string text, Color color, float size)
        {
            _lower.gameObject.SetActive(true);
            _orderText.text = text;
            _orderText.color = color;
            _orderText.fontSizeMax = size;
            _orderText.fontSize = size;
        }

        private static string RoundCaption(PosesState s)
        {
            return s.Rounds > 0 ? "Ronda " + Mathf.Max(1, s.Round) + " de " + s.Rounds : "Ronda " + Mathf.Max(1, s.Round);
        }

        private static string PoseLabel(PosesState s)
        {
            string label = string.IsNullOrEmpty(s.Label) ? s.Pose : s.Label;
            return GameUi.Plain(label ?? string.Empty).ToUpperInvariant();
        }

        /// <summary>La orden tal cual, con «Simón dice» en amarillo si lo dijo.</summary>
        private static string OrderText(PosesState s)
        {
            string order = GameUi.Plain(s.Order ?? string.Empty).Trim();
            if (order.Length == 0)
            {
                order = GameUi.Plain(s.Label ?? string.Empty);
            }

            int at = order.IndexOf(SimonWords, StringComparison.OrdinalIgnoreCase);
            if (at < 0)
            {
                return order;
            }

            string yellow = ColorUtility.ToHtmlStringRGB(GameColors.Yellow);
            return order.Substring(0, at) + "<color=#" + yellow + ">" + order.Substring(at, SimonWords.Length) + "</color>"
                   + order.Substring(at + SimonWords.Length);
        }

        private void Build()
        {
            if (_built || Hud == null || Layer == null)
            {
                return;
            }

            _built = true;

            // Todo lo del juego en un grupo a pantalla completa (se funde junto).
            _stageGroup = Hud.NewGroup("Poses", Layer);
            RectTransform all = (RectTransform)_stageGroup.transform;

            // Cabecera fina: título y ronda, como la de la tarjeta común.
            _header = Hud.NewRect("Cabecera", all);
            GameUi.PlaceTop(_header, headerTop, new Vector2(previewWidth, headerHeight));
            Image headerBorder = Hud.NewRound("Borde", _header, GameColors.CardBorder, 24f);
            GameUi.Stretch(headerBorder.rectTransform);
            Image headerFill = Hud.NewRound("Fondo", _header, GameColors.CardFill, 22f);
            GameUi.Stretch(headerFill.rectTransform);
            headerFill.rectTransform.offsetMin = new Vector2(3f, 3f);
            headerFill.rectTransform.offsetMax = new Vector2(-3f, -3f);
            _headerTitle = Hud.NewText("Titulo", _header, string.Empty, 38f, Color.white, TextAlignmentOptions.MidlineLeft, Hud.DisplayFont);
            GameUi.Stretch(_headerTitle.rectTransform);
            _headerTitle.rectTransform.offsetMin = new Vector2(34f, 0f);
            _headerTitle.rectTransform.offsetMax = new Vector2(-260f, 0f);
            _headerTitle.characterSpacing = 6f;
            _headerTitle.textWrappingMode = TextWrappingModes.NoWrap;
            _headerTitle.enableAutoSizing = true;
            _headerTitle.fontSizeMin = 24f;
            _headerTitle.fontSizeMax = 38f;
            _headerCaption = Hud.NewText("Rotulo", _header, string.Empty, 28f, GameColors.Muted, TextAlignmentOptions.MidlineRight, Hud.BodyFont);
            GameUi.Stretch(_headerCaption.rectTransform);
            _headerCaption.rectTransform.offsetMin = new Vector2(34f, 0f);
            _headerCaption.rectTransform.offsetMax = new Vector2(-34f, 0f);
            _headerCaption.characterSpacing = 4f;
            _headerCaption.textWrappingMode = TextWrappingModes.NoWrap;

            _stage = Hud.NewRect("Vista", all);
            GameUi.PlaceTop(_stage, PreviewTop, new Vector2(previewWidth, previewWidth / CameraPreviewPanel.Aspect));

            // Sin imagen: un fondo oscuro con aviso en el sitio de la vista.
            Image waiting = Hud.NewRound("SinImagen", _stage, GameUi.WithAlpha(GameColors.Dark, 0.92f), 28f);
            GameUi.Stretch(waiting.rectTransform);
            _waiting = waiting.rectTransform;
            TextMeshProUGUI waitingText = Hud.NewText("Texto", _waiting, "Esperando la cámara…", 40f, GameColors.Muted, TextAlignmentOptions.Center, Hud.BodyFont);
            GameUi.Stretch(waitingText.rectTransform);

            // Pictograma arriba a la derecha.
            _pictoBox = Hud.NewRect("Pictograma", _stage);
            _pictoBox.anchorMin = new Vector2(1f, 1f);
            _pictoBox.anchorMax = new Vector2(1f, 1f);
            _pictoBox.pivot = new Vector2(1f, 1f);
            _pictoBox.anchoredPosition = new Vector2(-20f, -20f);
            _pictoBox.sizeDelta = new Vector2(pictogramSize + 40f, pictogramSize + 86f);
            Image pictoFill = Hud.NewRound("Fondo", _pictoBox, GameUi.WithAlpha(GameColors.Dark, 0.82f), 26f);
            GameUi.Stretch(pictoFill.rectTransform);
            Image pictoBorder = Hud.NewImage("Borde", _pictoBox, Hud.FrameSprite, GameUi.WithAlpha(GameColors.CardBorder, 0.9f));
            GameHud.SetRadius(pictoBorder, 26f);
            GameUi.Stretch(pictoBorder.rectTransform);
            RectTransform figureArea = Hud.NewRect("Figura", _pictoBox);
            figureArea.anchorMin = new Vector2(0.5f, 1f);
            figureArea.anchorMax = new Vector2(0.5f, 1f);
            figureArea.pivot = new Vector2(0.5f, 1f);
            figureArea.anchoredPosition = new Vector2(0f, -14f);
            figureArea.sizeDelta = new Vector2(pictogramSize, pictogramSize);
            _picto = new PosesPictogram(Hud, figureArea, pictogramSize * 0.92f, Color.white);
            _pictoLabel = Hud.NewText("Nombre", _pictoBox, string.Empty, 26f, Color.white, TextAlignmentOptions.Center, Hud.DisplayFont);
            RectTransform labelRect = _pictoLabel.rectTransform;
            labelRect.anchorMin = new Vector2(0f, 0f);
            labelRect.anchorMax = new Vector2(1f, 0f);
            labelRect.pivot = new Vector2(0.5f, 0f);
            labelRect.anchoredPosition = new Vector2(0f, 14f);
            labelRect.sizeDelta = new Vector2(-20f, 60f);
            _pictoLabel.enableAutoSizing = true;
            _pictoLabel.fontSizeMin = 16f;
            _pictoLabel.fontSizeMax = 26f;
            _pictoLabel.characterSpacing = 3f;
            _pictoBox.gameObject.SetActive(false);

            // Cuántos juegan, al colocarse (arriba a la derecha).
            _chip = Hud.NewRect("Jugando", _stage);
            _chip.anchorMin = new Vector2(1f, 1f);
            _chip.anchorMax = new Vector2(1f, 1f);
            _chip.pivot = new Vector2(1f, 1f);
            _chip.anchoredPosition = new Vector2(-22f, -22f);
            HorizontalLayoutGroup chipRow = _chip.gameObject.AddComponent<HorizontalLayoutGroup>();
            chipRow.padding = new RectOffset(24, 24, 10, 12);
            chipRow.childAlignment = TextAnchor.MiddleCenter;
            chipRow.childControlWidth = true;
            chipRow.childControlHeight = true;
            ContentSizeFitter chipFit = _chip.gameObject.AddComponent<ContentSizeFitter>();
            chipFit.horizontalFit = ContentSizeFitter.FitMode.PreferredSize;
            chipFit.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            Image chipFill = Hud.NewRound("Fondo", _chip, GameUi.WithAlpha(GameColors.Brand, 0.9f), 24f);
            chipFill.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;
            GameUi.Stretch(chipFill.rectTransform);
            _chipText = Hud.NewText("Texto", _chip, string.Empty, 28f, Color.white, TextAlignmentOptions.Center, Hud.BodyFont);
            _chipText.textWrappingMode = TextWrappingModes.NoWrap;
            _chipText.characterSpacing = 3f;
            _chip.gameObject.SetActive(false);

            // La orden abajo, como un rótulo de televisión sobre la imagen.
            _lower = Hud.NewRect("Orden", _stage);
            _lower.anchorMin = new Vector2(0f, 0f);
            _lower.anchorMax = new Vector2(1f, 0f);
            _lower.pivot = new Vector2(0.5f, 0f);
            _lower.anchoredPosition = new Vector2(0f, 16f);
            _lower.sizeDelta = new Vector2(-32f, 132f);
            Image lowerFill = Hud.NewRound("Fondo", _lower, GameUi.WithAlpha(GameColors.Dark, 0.84f), 24f);
            GameUi.Stretch(lowerFill.rectTransform);
            _orderText = Hud.NewText("Texto", _lower, string.Empty, 50f, Color.white, TextAlignmentOptions.Center, Hud.DisplayFont);
            GameUi.Stretch(_orderText.rectTransform);
            _orderText.rectTransform.offsetMin = new Vector2(28f, 8f);
            _orderText.rectTransform.offsetMax = new Vector2(-28f, -8f);
            _orderText.enableAutoSizing = true;
            _orderText.fontSizeMin = 28f;
            _orderText.fontSizeMax = 50f;

            // El resultado de la ronda, en el centro.
            _badge = Hud.NewRect("Resultado", _stage);
            _badge.anchorMin = new Vector2(0.5f, 0.5f);
            _badge.anchorMax = new Vector2(0.5f, 0.5f);
            _badge.pivot = new Vector2(0.5f, 0.5f);
            // A la izquierda del centro: a la derecha está el pictograma.
            _badge.anchoredPosition = new Vector2(-118f, 40f);
            _badge.sizeDelta = new Vector2(500f, 200f);
            Image badgeShadow = Hud.NewImage("Sombra", _badge, Hud.GlowSprite, new Color(0f, 0f, 0f, 0.5f));
            GameUi.Stretch(badgeShadow.rectTransform);
            badgeShadow.rectTransform.offsetMin = new Vector2(-50f, -60f);
            badgeShadow.rectTransform.offsetMax = new Vector2(50f, 40f);
            _badgeFill = Hud.NewRound("Fondo", _badge, GameColors.Brand, 40f);
            GameUi.Stretch(_badgeFill.rectTransform);
            Image badgeBorder = Hud.NewImage("Borde", _badge, Hud.FrameSprite, GameUi.WithAlpha(Color.white, 0.85f));
            GameHud.SetRadius(badgeBorder, 40f);
            GameUi.Stretch(badgeBorder.rectTransform);
            _badgeText = Hud.NewText("Numero", _badge, string.Empty, 92f, Color.white, TextAlignmentOptions.Center, Hud.DisplayFont);
            RectTransform bigRect = _badgeText.rectTransform;
            bigRect.anchorMin = new Vector2(0f, 0.36f);
            bigRect.anchorMax = new Vector2(1f, 1f);
            bigRect.offsetMin = new Vector2(20f, 0f);
            bigRect.offsetMax = new Vector2(-20f, -6f);
            _badgeText.textWrappingMode = TextWrappingModes.NoWrap;
            _badgeText.enableAutoSizing = true;
            _badgeText.fontSizeMin = 40f;
            _badgeText.fontSizeMax = 92f;
            _badgeSub = Hud.NewText("Frase", _badge, string.Empty, 32f, GameUi.WithAlpha(Color.white, 0.92f), TextAlignmentOptions.Center, Hud.BodyFont);
            RectTransform subRect = _badgeSub.rectTransform;
            subRect.anchorMin = new Vector2(0f, 0f);
            subRect.anchorMax = new Vector2(1f, 0.38f);
            subRect.offsetMin = new Vector2(20f, 14f);
            subRect.offsetMax = new Vector2(-20f, 0f);
            _badgeSub.enableAutoSizing = true;
            _badgeSub.fontSizeMin = 20f;
            _badgeSub.fontSizeMax = 32f;
            _badge.gameObject.SetActive(false);

            _stageGroup.gameObject.SetActive(false);
        }
    }
}
