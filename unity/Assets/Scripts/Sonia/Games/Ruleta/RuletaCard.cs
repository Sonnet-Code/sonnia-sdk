// Las tarjetas de los cinco retos de la ruleta (docs/juegos/ruleta.md), dentro del
// contenido del juego en la tarjeta común: arriba una píldora con el icono y el
// nombre del reto en el color de su casilla, y debajo lo de cada reto.
//
// - Trivia relámpago: la pregunta y tres opciones (A, B y C, como la trivia), con el
//   contador del HUD en la esquina; al resultado, la buena en verde y la elegida en rojo.
// - Adivinanza geek: la adivinanza, los intentos y la pista cuando toca; al final, la
//   solución.
// - Explica en 20 segundos: la tecnología en grande con el contador circular en el
//   centro y, al acabar, la nota con estrellas.
// - Predice el futuro de la IA: la pregunta y una bola de cristal; al resultado, la
//   predicción y su barra de probabilidad.
// - Reto sorpresa de Sonnet Code: la pregunta o el reto y su resultado.
//
// Todo lo que llega del orquestador pasa por GameUi.Plain. Posiciones absolutas desde
// arriba, en píxeles de la referencia 1080x1920.

using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia.Games.Ruleta
{
    /// <summary>La tarjeta del reto en juego y su resultado.</summary>
    internal sealed class RuletaCard
    {
        /// <summary>Alto del contenido del juego con el reto (y con la ruleta).</summary>
        public const float Height = 540f;

        private const float BadgeSize = 64f;
        private static readonly string[] Letters = { "A", "B", "C" };
        private static readonly Color[] LetterColors = { GameColors.Blue, GameColors.Red, GameColors.Green };

        private sealed class OptionRow
        {
            public RectTransform Row;
            public Image Border;
            public Image Fill;
            public TextMeshProUGUI Text;
            public Image Mark;
            public CanvasGroup Group;
        }

        private sealed class AnswerBox
        {
            public RectTransform Root;
            public Image Fill;
            public Image Border;
            public TextMeshProUGUI Label;
            public TextMeshProUGUI Text;
        }

        private sealed class TriesRow
        {
            public RectTransform Root;
            public readonly List<Image> Dots = new List<Image>();
            public readonly List<Image> Crosses = new List<Image>();
        }

        private GameHud _hud;
        private RuletaIcons _icons;
        private RectTransform _root;
        private CanvasGroup _group;

        // Píldora con el reto.
        private RectTransform _pill;
        private Image _pillFill;
        private Image _pillIcon;
        private TextMeshProUGUI _pillGlyph;
        private TextMeshProUGUI _pillText;

        private readonly Dictionary<string, RectTransform> _views = new Dictionary<string, RectTransform>();

        // Trivia relámpago.
        private TextMeshProUGUI _question;
        private readonly OptionRow[] _options = new OptionRow[3];

        // Adivinanza.
        private TextMeshProUGUI _riddle;
        private RectTransform _hintBox;
        private TextMeshProUGUI _hintText;
        private AnswerBox _riddleAnswer;
        private TriesRow _riddleTries;

        // Explica en 20 segundos.
        private TextMeshProUGUI _explainLead;
        private TextMeshProUGUI _tech;
        private RectTransform _countdownSlot;
        private TextMeshProUGUI _explainHelp;
        private RectTransform _stars;
        private readonly Image[] _starFills = new Image[5];
        private TextMeshProUGUI _score;
        private float _starsAt = -1f;
        private int _starsScore;

        // Futuro de la IA.
        private TextMeshProUGUI _futurePrompt;
        private RectTransform _crystal;
        private TextMeshProUGUI _futureHelp;
        private TextMeshProUGUI _prediction;
        private RectTransform _bar;
        private Image _barFill;
        private TextMeshProUGUI _percent;
        private float _barAt = -1f;
        private int _barTarget;

        // Reto de Sonnet Code.
        private TextMeshProUGUI _sonnetKind;
        private TextMeshProUGUI _sonnetText;
        private TextMeshProUGUI _sonnetHelp;
        private TriesRow _sonnetTries;
        private AnswerBox _sonnetAnswer;

        private float _clock;
        private string _kind = string.Empty;

        public RectTransform Root
        {
            get { return _root; }
        }

        public CanvasGroup Group
        {
            get { return _group; }
        }

        /// <summary>El hueco del contador circular en «explica» (el controlador coloca ahí el del HUD).</summary>
        public RectTransform CountdownSlot
        {
            get { return _countdownSlot; }
        }

        /// <summary>La fila de una opción de la trivia (para el confeti).</summary>
        public RectTransform OptionRect(int index)
        {
            return index >= 0 && index < _options.Length && _options[index] != null ? _options[index].Row : null;
        }

        public RectTransform AnswerRect
        {
            get { return _kind == "sonnet" ? _sonnetAnswer.Root : _riddleAnswer.Root; }
        }

        public RectTransform StarsRect
        {
            get { return _stars; }
        }

        public RectTransform BarRect
        {
            get { return _bar; }
        }

        public bool IsBuilt
        {
            get { return _root != null; }
        }

        // ------------------------------------------------------------------
        // Montaje
        // ------------------------------------------------------------------

        public void Build(GameHud hud, RuletaIcons icons, RectTransform parent)
        {
            _hud = hud;
            _icons = icons;
            _group = hud.NewGroup("Reto", parent);
            _root = (RectTransform)_group.transform;
            _group.alpha = 0f;

            BuildPill();
            BuildTrivia();
            BuildRiddle();
            BuildExplain();
            BuildFuture();
            BuildSonnet();
        }

        private void BuildPill()
        {
            _pill = _hud.NewRect("Pildora", _root);
            _pill.anchorMin = new Vector2(0.5f, 1f);
            _pill.anchorMax = _pill.anchorMin;
            _pill.pivot = new Vector2(0.5f, 1f);
            _pill.anchoredPosition = Vector2.zero;
            HorizontalLayoutGroup row = _pill.gameObject.AddComponent<HorizontalLayoutGroup>();
            row.padding = new RectOffset(22, 30, 8, 8);
            row.spacing = 12f;
            row.childAlignment = TextAnchor.MiddleCenter;
            row.childControlWidth = true;
            row.childControlHeight = true;
            row.childForceExpandWidth = false;
            row.childForceExpandHeight = false;
            ContentSizeFitter fit = _pill.gameObject.AddComponent<ContentSizeFitter>();
            fit.horizontalFit = ContentSizeFitter.FitMode.PreferredSize;
            fit.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            _pillFill = _hud.NewRound("Fondo", _pill, GameColors.Blue, 29f);
            _pillFill.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;
            GameUi.Stretch(_pillFill.rectTransform);

            _pillIcon = _hud.NewImage("Icono", _pill, null, Color.white);
            _pillIcon.preserveAspect = true;
            LayoutElement iconLayout = _pillIcon.gameObject.AddComponent<LayoutElement>();
            iconLayout.preferredWidth = 40f;
            iconLayout.preferredHeight = 40f;

            _pillGlyph = _hud.NewText("Signo", _pill, "?", 40f, Color.white, TextAlignmentOptions.Center, _hud.DisplayFont);
            _pillGlyph.textWrappingMode = TextWrappingModes.NoWrap;
            LayoutElement glyphLayout = _pillGlyph.gameObject.AddComponent<LayoutElement>();
            glyphLayout.preferredWidth = 40f;
            glyphLayout.preferredHeight = 42f;

            _pillText = _hud.NewText("Texto", _pill, string.Empty, 30f, Color.white, TextAlignmentOptions.Left, _hud.DisplayFont);
            _pillText.textWrappingMode = TextWrappingModes.NoWrap;
            _pillText.characterSpacing = 4f;
        }

        private RectTransform NewView(string kind)
        {
            RectTransform view = _hud.NewRect("Vista_" + kind, _root);
            GameUi.Stretch(view);
            view.gameObject.SetActive(false);
            _views[kind] = view;
            return view;
        }

        /// <summary>Una franja a todo lo ancho, de <paramref name="top"/> a <paramref name="top"/> + <paramref name="height"/> px desde arriba.</summary>
        private RectTransform Band(RectTransform parent, string name, float top, float height, float inset = 0f)
        {
            RectTransform rect = _hud.NewRect(name, parent);
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(1f, 1f);
            rect.pivot = new Vector2(0.5f, 1f);
            rect.offsetMin = new Vector2(inset, 0f);
            rect.offsetMax = new Vector2(-inset, 0f);
            rect.anchoredPosition = new Vector2(0f, -top);
            rect.sizeDelta = new Vector2(-2f * inset, height);
            return rect;
        }

        private TextMeshProUGUI BandText(RectTransform parent, string name, float top, float height, float size, float minSize, Color color, TMP_FontAsset font = null, float inset = 0f)
        {
            RectTransform band = Band(parent, name, top, height, inset);
            TextMeshProUGUI text = _hud.NewText("Texto", band, string.Empty, size, color, TextAlignmentOptions.Center, font != null ? font : _hud.DisplayFont);
            GameUi.Stretch(text.rectTransform);
            text.enableAutoSizing = true;
            text.fontSizeMin = minSize;
            text.fontSizeMax = size;
            text.verticalAlignment = VerticalAlignmentOptions.Middle;
            text.overflowMode = TextOverflowModes.Ellipsis;
            return text;
        }

        private void BuildTrivia()
        {
            RectTransform view = NewView("trivia");
            _question = BandText(view, "Pregunta", 72f, 142f, 46f, 30f, Color.white);
            _question.lineSpacing = -6f;
            for (int i = 0; i < _options.Length; i++)
            {
                _options[i] = BuildOption(view, i, 226f + (i * 104f), 94f);
            }
        }

        private OptionRow BuildOption(RectTransform parent, int index, float top, float height)
        {
            OptionRow option = new OptionRow();
            option.Row = Band(parent, "Opcion" + Letters[index], top, height);
            option.Group = option.Row.gameObject.AddComponent<CanvasGroup>();
            option.Border = _hud.NewRound("Borde", option.Row, GameUi.WithAlpha(Color.white, 0.18f), 26f);
            GameUi.Stretch(option.Border.rectTransform);
            option.Fill = _hud.NewRound("Fondo", option.Row, GameColors.OptionFill, 24f);
            GameUi.Stretch(option.Fill.rectTransform);
            option.Fill.rectTransform.offsetMin = new Vector2(3f, 3f);
            option.Fill.rectTransform.offsetMax = new Vector2(-3f, -3f);

            Image badge = _hud.NewImage("Letra", option.Row, _hud.DotSprite, LetterColors[index]);
            RectTransform badgeRect = badge.rectTransform;
            badgeRect.anchorMin = new Vector2(0f, 0.5f);
            badgeRect.anchorMax = badgeRect.anchorMin;
            badgeRect.pivot = new Vector2(0f, 0.5f);
            badgeRect.anchoredPosition = new Vector2(16f, 0f);
            badgeRect.sizeDelta = new Vector2(BadgeSize, BadgeSize);
            TextMeshProUGUI letter = _hud.NewText("Texto", badgeRect, Letters[index], BadgeSize * 0.56f, Color.white, TextAlignmentOptions.Center, _hud.DisplayFont);
            GameUi.Stretch(letter.rectTransform);

            option.Text = _hud.NewText("Opcion", option.Row, string.Empty, 38f, Color.white, TextAlignmentOptions.Left, _hud.DisplayFont);
            option.Text.enableAutoSizing = true;
            option.Text.fontSizeMin = 24f;
            option.Text.fontSizeMax = 38f;
            option.Text.verticalAlignment = VerticalAlignmentOptions.Middle;
            option.Text.overflowMode = TextOverflowModes.Ellipsis;
            RectTransform text = option.Text.rectTransform;
            text.anchorMin = Vector2.zero;
            text.anchorMax = Vector2.one;
            text.offsetMin = new Vector2(16f + BadgeSize + 24f, 6f);
            text.offsetMax = new Vector2(-(BadgeSize + 24f), -6f);

            option.Mark = _hud.NewImage("Marca", option.Row, _hud.CheckSprite, Color.white);
            RectTransform mark = option.Mark.rectTransform;
            mark.anchorMin = new Vector2(1f, 0.5f);
            mark.anchorMax = mark.anchorMin;
            mark.pivot = new Vector2(1f, 0.5f);
            mark.anchoredPosition = new Vector2(-16f, 0f);
            mark.sizeDelta = new Vector2(BadgeSize, BadgeSize);
            option.Mark.gameObject.SetActive(false);
            return option;
        }

        private void BuildRiddle()
        {
            RectTransform view = NewView("adivinanza");
            _riddle = BandText(view, "Adivinanza", 72f, 232f, 44f, 28f, Color.white);
            _riddle.lineSpacing = -4f;

            _hintBox = Band(view, "Pista", 318f, 134f, 20f);
            Image hintBorder = _hud.NewRound("Borde", _hintBox, GameUi.WithAlpha(GameColors.Yellow, 0.75f), 28f);
            GameUi.Stretch(hintBorder.rectTransform);
            Image hintFill = _hud.NewRound("Fondo", _hintBox, new Color(0.16f, 0.15f, 0.08f, 0.96f), 26f);
            GameUi.Stretch(hintFill.rectTransform);
            hintFill.rectTransform.offsetMin = new Vector2(3f, 3f);
            hintFill.rectTransform.offsetMax = new Vector2(-3f, -3f);
            TextMeshProUGUI hintLabel = _hud.NewText("Etiqueta", _hintBox, "PISTA", 24f, GameColors.Yellow, TextAlignmentOptions.Center, _hud.DisplayFont);
            hintLabel.characterSpacing = 6f;
            RectTransform labelRect = hintLabel.rectTransform;
            labelRect.anchorMin = new Vector2(0f, 1f);
            labelRect.anchorMax = new Vector2(1f, 1f);
            labelRect.pivot = new Vector2(0.5f, 1f);
            labelRect.anchoredPosition = new Vector2(0f, -10f);
            labelRect.sizeDelta = new Vector2(0f, 32f);
            _hintText = _hud.NewText("Texto", _hintBox, string.Empty, 32f, Color.white, TextAlignmentOptions.Center, _hud.BodyFont);
            _hintText.enableAutoSizing = true;
            _hintText.fontSizeMin = 22f;
            _hintText.fontSizeMax = 32f;
            _hintText.verticalAlignment = VerticalAlignmentOptions.Middle;
            _hintText.overflowMode = TextOverflowModes.Ellipsis;
            RectTransform hintRect = _hintText.rectTransform;
            hintRect.anchorMin = Vector2.zero;
            hintRect.anchorMax = Vector2.one;
            hintRect.offsetMin = new Vector2(24f, 10f);
            hintRect.offsetMax = new Vector2(-24f, -42f);

            _riddleAnswer = BuildAnswer(view, 318f, 134f);
            _riddleTries = BuildTries(view, 470f);
        }

        private AnswerBox BuildAnswer(RectTransform parent, float top, float height)
        {
            AnswerBox box = new AnswerBox();
            box.Root = Band(parent, "Solucion", top, height, 20f);
            box.Border = _hud.NewRound("Borde", box.Root, GameUi.WithAlpha(Color.white, 0.6f), 28f);
            GameUi.Stretch(box.Border.rectTransform);
            box.Fill = _hud.NewRound("Fondo", box.Root, GameColors.RightFill, 26f);
            GameUi.Stretch(box.Fill.rectTransform);
            box.Fill.rectTransform.offsetMin = new Vector2(3f, 3f);
            box.Fill.rectTransform.offsetMax = new Vector2(-3f, -3f);
            box.Label = _hud.NewText("Etiqueta", box.Root, "ERA", 24f, GameUi.WithAlpha(Color.white, 0.85f), TextAlignmentOptions.Center, _hud.DisplayFont);
            box.Label.characterSpacing = 6f;
            RectTransform labelRect = box.Label.rectTransform;
            labelRect.anchorMin = new Vector2(0f, 1f);
            labelRect.anchorMax = new Vector2(1f, 1f);
            labelRect.pivot = new Vector2(0.5f, 1f);
            labelRect.anchoredPosition = new Vector2(0f, -12f);
            labelRect.sizeDelta = new Vector2(0f, 32f);
            box.Text = _hud.NewText("Texto", box.Root, string.Empty, 52f, Color.white, TextAlignmentOptions.Center, _hud.DisplayFont);
            box.Text.enableAutoSizing = true;
            box.Text.fontSizeMin = 28f;
            box.Text.fontSizeMax = 52f;
            box.Text.verticalAlignment = VerticalAlignmentOptions.Middle;
            box.Text.overflowMode = TextOverflowModes.Ellipsis;
            RectTransform textRect = box.Text.rectTransform;
            textRect.anchorMin = Vector2.zero;
            textRect.anchorMax = Vector2.one;
            textRect.offsetMin = new Vector2(24f, 10f);
            textRect.offsetMax = new Vector2(-24f, -44f);
            box.Root.gameObject.SetActive(false);
            return box;
        }

        private TriesRow BuildTries(RectTransform parent, float top)
        {
            TriesRow tries = new TriesRow();
            tries.Root = Band(parent, "Intentos", top, 52f);
            HorizontalLayoutGroup row = tries.Root.gameObject.AddComponent<HorizontalLayoutGroup>();
            row.spacing = 14f;
            row.childAlignment = TextAnchor.MiddleCenter;
            row.childControlWidth = true;
            row.childControlHeight = true;
            row.childForceExpandWidth = false;
            row.childForceExpandHeight = false;
            TextMeshProUGUI label = _hud.NewText("Etiqueta", tries.Root, "INTENTOS", 24f, GameColors.Muted, TextAlignmentOptions.Center, _hud.DisplayFont);
            label.characterSpacing = 5f;
            label.textWrappingMode = TextWrappingModes.NoWrap;
            for (int i = 0; i < 3; i++)
            {
                Image dot = _hud.NewImage("Intento" + i, tries.Root, _hud.DotSprite, Color.white);
                LayoutElement layout = dot.gameObject.AddComponent<LayoutElement>();
                layout.preferredWidth = 34f;
                layout.preferredHeight = 34f;
                Image cross = _hud.NewImage("Fallo", dot.rectTransform, _hud.CrossSprite, Color.white);
                GameUi.Stretch(cross.rectTransform);
                cross.rectTransform.offsetMin = new Vector2(5f, 5f);
                cross.rectTransform.offsetMax = new Vector2(-5f, -5f);
                cross.gameObject.SetActive(false);
                tries.Dots.Add(dot);
                tries.Crosses.Add(cross);
            }

            return tries;
        }

        private void BuildExplain()
        {
            RectTransform view = NewView("explica");
            _explainLead = BandText(view, "Pide", 72f, 40f, 26f, 20f, GameColors.Muted);
            _explainLead.characterSpacing = 5f;
            _explainLead.text = "EXPLÍCALE A SONNIA QUÉ ES";
            _tech = BandText(view, "Tecnologia", 112f, 132f, 96f, 48f, Color.white);
            _tech.textWrappingMode = TextWrappingModes.NoWrap;
            _countdownSlot = Band(view, "Contador", 254f, 210f);
            _explainHelp = BandText(view, "Ayuda", 474f, 50f, 28f, 20f, GameColors.Muted, _hud.BodyFont);

            _stars = Band(view, "Estrellas", 266f, 100f);
            HorizontalLayoutGroup row = _stars.gameObject.AddComponent<HorizontalLayoutGroup>();
            row.spacing = 16f;
            row.childAlignment = TextAnchor.MiddleCenter;
            row.childControlWidth = true;
            row.childControlHeight = true;
            row.childForceExpandWidth = false;
            row.childForceExpandHeight = false;
            for (int i = 0; i < _starFills.Length; i++)
            {
                Image back = _hud.NewImage("Estrella" + i, _stars, _hud.StarSprite, GameUi.WithAlpha(Color.white, 0.16f));
                back.preserveAspect = true;
                LayoutElement layout = back.gameObject.AddComponent<LayoutElement>();
                layout.preferredWidth = 88f;
                layout.preferredHeight = 88f;
                Image fill = _hud.NewImage("Relleno", back.rectTransform, _hud.StarSprite, GameColors.Gold);
                fill.preserveAspect = true;
                GameUi.Stretch(fill.rectTransform);
                fill.type = Image.Type.Filled;
                fill.fillMethod = Image.FillMethod.Horizontal;
                fill.fillOrigin = (int)Image.OriginHorizontal.Left;
                fill.fillAmount = 0f;
                _starFills[i] = fill;
            }

            _score = BandText(view, "Nota", 378f, 96f, 76f, 40f, GameColors.Gold);
            _stars.gameObject.SetActive(false);
            _score.transform.parent.gameObject.SetActive(false);
        }

        private void BuildFuture()
        {
            RectTransform view = NewView("futuro");
            _futurePrompt = BandText(view, "Pregunta", 72f, 120f, 42f, 28f, Color.white);

            _crystal = Band(view, "Bola", 196f, 230f);
            Image glow = _hud.NewImage("Halo", _crystal, _icons.Glow, GameUi.WithAlpha(GameColors.Brand, 0.7f));
            RectTransform glowRect = glow.rectTransform;
            glowRect.anchorMin = new Vector2(0.5f, 0.5f);
            glowRect.anchorMax = glowRect.anchorMin;
            glowRect.sizeDelta = new Vector2(330f, 330f);
            Image ball = _hud.NewImage("Icono", _crystal, _icons.Crystal, new Color(0.78f, 0.86f, 1f, 1f));
            ball.preserveAspect = true;
            RectTransform ballRect = ball.rectTransform;
            ballRect.anchorMin = new Vector2(0.5f, 0.5f);
            ballRect.anchorMax = ballRect.anchorMin;
            ballRect.sizeDelta = new Vector2(200f, 200f);
            Image sparkle = _hud.NewImage("Destello", _crystal, _hud.SparkleSprite, GameColors.Yellow);
            RectTransform sparkleRect = sparkle.rectTransform;
            sparkleRect.anchorMin = new Vector2(0.5f, 0.5f);
            sparkleRect.anchorMax = sparkleRect.anchorMin;
            sparkleRect.anchoredPosition = new Vector2(78f, 70f);
            sparkleRect.sizeDelta = new Vector2(54f, 54f);

            _futureHelp = BandText(view, "Ayuda", 440f, 80f, 30f, 20f, GameColors.Muted, _hud.BodyFont, 40f);
            _futureHelp.text = "Haz tu predicción y Sonnia le pone probabilidad";

            _prediction = BandText(view, "Prediccion", 190f, 186f, 42f, 26f, Color.white, null, 20f);
            _prediction.fontStyle = FontStyles.Italic;
            _prediction.transform.parent.gameObject.SetActive(false);

            _bar = Band(view, "Barra", 398f, 48f, 56f);
            Image track = _hud.NewRound("Pista", _bar, GameUi.WithAlpha(Color.white, 0.14f), 24f);
            GameUi.Stretch(track.rectTransform);
            _barFill = _hud.NewRound("Relleno", _bar, GameColors.Green, 24f);
            RectTransform fillRect = _barFill.rectTransform;
            fillRect.anchorMin = new Vector2(0f, 0f);
            fillRect.anchorMax = new Vector2(0f, 1f);
            fillRect.pivot = new Vector2(0f, 0.5f);
            fillRect.anchoredPosition = Vector2.zero;
            fillRect.sizeDelta = new Vector2(48f, 0f);
            _bar.gameObject.SetActive(false);

            _percent = BandText(view, "Porcentaje", 452f, 84f, 64f, 32f, Color.white);
            _percent.transform.parent.gameObject.SetActive(false);
        }

        private void BuildSonnet()
        {
            RectTransform view = NewView("sonnet");
            _sonnetKind = BandText(view, "Tipo", 72f, 40f, 26f, 20f, GameColors.Yellow);
            _sonnetKind.characterSpacing = 5f;
            _sonnetText = BandText(view, "Texto", 114f, 214f, 44f, 28f, Color.white, null, 10f);
            _sonnetText.lineSpacing = -4f;
            _sonnetHelp = BandText(view, "Ayuda", 352f, 50f, 28f, 20f, GameColors.Muted, _hud.BodyFont);
            _sonnetTries = BuildTries(view, 352f);
            _sonnetAnswer = BuildAnswer(view, 346f, 134f);
        }

        // ------------------------------------------------------------------
        // Estado
        // ------------------------------------------------------------------

        /// <summary>Monta la tarjeta del reto (de cero): la píldora y la vista del reto, sin resultado.</summary>
        public void Show(ChallengeData data, SegmentInfo segment, int index)
        {
            _kind = data.Kind ?? string.Empty;
            foreach (KeyValuePair<string, RectTransform> pair in _views)
            {
                pair.Value.gameObject.SetActive(pair.Key == _kind);
            }

            int color = Mathf.Clamp(index, 0, RuletaWheel.Count - 1);
            _pillFill.color = RuletaWheel.Fill[color];
            Color ink = RuletaWheel.Ink[color];
            _pillText.color = ink;
            _pillIcon.color = ink;
            _pillGlyph.color = ink;
            string title = !string.IsNullOrEmpty(data.Title) ? data.Title : segment.Title;
            _pillText.text = GameUi.Plain(title).ToUpperInvariant();
            Sprite icon = RuletaWheel.IconFor(_hud, _icons, segment.Icon);
            _pillIcon.sprite = icon;
            _pillIcon.gameObject.SetActive(icon != null);
            _pillGlyph.gameObject.SetActive(icon == null);
            LayoutRebuilder.ForceRebuildLayoutImmediate(_pill);

            string prompt = GameUi.Plain(data.Prompt);
            switch (_kind)
            {
                case "trivia":
                    _question.text = prompt;
                    for (int i = 0; i < _options.Length; i++)
                    {
                        OptionRow option = _options[i];
                        string text = data.Options != null && i < data.Options.Count ? data.Options[i] : string.Empty;
                        option.Text.text = GameUi.Plain(text);
                        option.Fill.color = GameColors.OptionFill;
                        option.Border.color = GameUi.WithAlpha(Color.white, 0.18f);
                        option.Mark.gameObject.SetActive(false);
                        option.Group.alpha = 1f;
                    }

                    break;
                case "adivinanza":
                    _riddle.text = prompt;
                    _riddleAnswer.Root.gameObject.SetActive(false);
                    _hintBox.gameObject.SetActive(false);
                    break;
                case "explica":
                    _tech.text = prompt;
                    _explainLead.transform.parent.gameObject.SetActive(true);
                    _stars.gameObject.SetActive(false);
                    _score.transform.parent.gameObject.SetActive(false);
                    _explainHelp.transform.parent.gameObject.SetActive(true);
                    _starsAt = -1f;
                    break;
                case "futuro":
                    _futurePrompt.text = prompt;
                    _crystal.gameObject.SetActive(true);
                    _futureHelp.transform.parent.gameObject.SetActive(true);
                    _prediction.transform.parent.gameObject.SetActive(false);
                    _bar.gameObject.SetActive(false);
                    _percent.transform.parent.gameObject.SetActive(false);
                    _barAt = -1f;
                    break;
                case "sonnet":
                    _sonnetKind.text = data.Task ? "RETO SORPRESA" : "PREGUNTA SORPRESA";
                    _sonnetText.text = prompt;
                    _sonnetAnswer.Root.gameObject.SetActive(false);
                    _sonnetHelp.text = "Cuando lo hagas, díselo a Sonnia";
                    _sonnetHelp.transform.parent.gameObject.SetActive(data.Task);
                    _sonnetTries.Root.gameObject.SetActive(!data.Task);
                    break;
            }

            Refresh(data);
        }

        /// <summary>Lo que cambia sin cambiar de reto: la pista, los fallos, el contador y el «¡Tiempo!».</summary>
        public void Refresh(ChallengeData data)
        {
            switch (_kind)
            {
                case "adivinanza":
                    bool hint = !string.IsNullOrEmpty(data.Hint) && string.IsNullOrEmpty(data.Outcome);
                    _hintText.text = GameUi.Plain(data.Hint);
                    _hintBox.gameObject.SetActive(hint);
                    PaintTries(_riddleTries, data.Tries, data.Misses);
                    break;
                case "sonnet":
                    if (!data.Task)
                    {
                        PaintTries(_sonnetTries, data.Tries, data.Misses);
                    }

                    break;
                case "explica":
                    bool running = data.Timer != null && data.Timer.Running;
                    _explainHelp.text = data.TimeUp
                        ? "¡Se acabó el tiempo!"
                        : running ? "¡El tiempo corre!" : "El tiempo arranca cuando empiezas a hablar";
                    _explainHelp.color = data.TimeUp ? GameColors.Red : running ? GameColors.Yellow : GameColors.Muted;
                    break;
            }
        }

        public RectTransform HintBox
        {
            get { return _hintBox; }
        }

        public RectTransform TriesRect
        {
            get { return _kind == "sonnet" ? _sonnetTries.Root : _riddleTries.Root; }
        }

        private static void PaintTries(TriesRow tries, int total, int misses)
        {
            int count = Mathf.Clamp(total, 0, tries.Dots.Count);
            tries.Root.gameObject.SetActive(count > 0);
            for (int i = 0; i < tries.Dots.Count; i++)
            {
                bool shown = i < count;
                tries.Dots[i].gameObject.SetActive(shown);
                // Los fallos se gastan por la derecha.
                bool used = shown && i >= count - Mathf.Clamp(misses, 0, count);
                tries.Dots[i].color = used ? GameColors.Red : Color.white;
                tries.Crosses[i].gameObject.SetActive(used);
            }
        }

        /// <summary>Pinta el resultado del reto (sin efectos: el confeti y las reacciones los pone el controlador).</summary>
        public void ShowResult(ChallengeData data)
        {
            string outcome = data.Outcome ?? string.Empty;
            switch (_kind)
            {
                case "trivia":
                    for (int i = 0; i < _options.Length; i++)
                    {
                        OptionRow option = _options[i];
                        if (i == data.Correct)
                        {
                            option.Fill.color = GameColors.RightFill;
                            option.Border.color = GameUi.WithAlpha(new Color(0.75f, 1f, 0.8f), 0.9f);
                            option.Mark.sprite = _hud.CheckSprite;
                            option.Mark.color = Color.white;
                            option.Mark.gameObject.SetActive(true);
                            option.Group.alpha = 1f;
                            GameAnim.Pulse(option.Row, 0.06f, 0.4f, 0.2f);
                        }
                        else if (i == data.Chosen)
                        {
                            option.Fill.color = GameColors.WrongFill;
                            option.Border.color = GameUi.WithAlpha(new Color(1f, 0.75f, 0.72f), 0.9f);
                            option.Mark.sprite = _hud.CrossSprite;
                            option.Mark.color = Color.white;
                            option.Mark.gameObject.SetActive(true);
                            option.Group.alpha = 1f;
                            GameAnim.Shake(option.Row);
                        }
                        else
                        {
                            option.Group.alpha = 0.4f;
                        }
                    }

                    break;
                case "adivinanza":
                    _hintBox.gameObject.SetActive(false);
                    PaintTries(_riddleTries, data.Tries, data.Misses);
                    PaintAnswer(_riddleAnswer, outcome, data.Answer, null);
                    break;
                case "explica":
                    _explainHelp.transform.parent.gameObject.SetActive(false);
                    _stars.gameObject.SetActive(true);
                    _score.transform.parent.gameObject.SetActive(true);
                    _starsScore = Mathf.Clamp(data.Score, 0, 10);
                    _starsAt = _clock;
                    for (int i = 0; i < _starFills.Length; i++)
                    {
                        _starFills[i].fillAmount = 0f;
                    }

                    _score.text = _starsScore + "<size=60%> / 10</size>";
                    GameAnim.Pop((RectTransform)_score.transform.parent, 0.45f, 0.9f);
                    break;
                case "futuro":
                    _crystal.gameObject.SetActive(false);
                    _futureHelp.transform.parent.gameObject.SetActive(false);
                    if (outcome == "pass" || string.IsNullOrEmpty(data.Prediction))
                    {
                        _prediction.transform.parent.gameObject.SetActive(true);
                        _prediction.fontStyle = FontStyles.Normal;
                        _prediction.text = "Hoy el futuro se queda en misterio";
                        break;
                    }

                    _prediction.fontStyle = FontStyles.Italic;
                    _prediction.text = "«" + GameUi.Plain(data.Prediction) + "»";
                    _prediction.transform.parent.gameObject.SetActive(true);
                    _bar.gameObject.SetActive(true);
                    _percent.transform.parent.gameObject.SetActive(true);
                    _barTarget = Mathf.Clamp(data.Probability, 0, 100);
                    _barAt = _clock;
                    _barFill.color = BarColor(_barTarget);
                    GameAnim.Pop((RectTransform)_prediction.transform.parent, 0.45f);
                    break;
                case "sonnet":
                    _sonnetHelp.transform.parent.gameObject.SetActive(false);
                    _sonnetTries.Root.gameObject.SetActive(false);
                    if (data.Task)
                    {
                        string line = outcome == "win" ? "¡RETO CUMPLIDO!" : outcome == "lose" ? "¡LA PRÓXIMA SALE!" : "¡OTRA VEZ SERÁ!";
                        PaintAnswer(_sonnetAnswer, outcome, line, string.Empty);
                    }
                    else
                    {
                        PaintAnswer(_sonnetAnswer, outcome, data.Answer, null);
                    }

                    break;
            }
        }

        private void PaintAnswer(AnswerBox box, string outcome, string text, string label)
        {
            Color fill = outcome == "win" ? GameColors.RightFill : outcome == "lose" ? GameColors.WrongFill : new Color(0.16f, 0.3f, 0.62f, 1f);
            box.Fill.color = fill;
            box.Label.text = label ?? (outcome == "win" ? "¡ACERTASTE! ERA" : "LA RESPUESTA ERA");
            box.Label.gameObject.SetActive(!string.IsNullOrEmpty(box.Label.text));
            RectTransform textRect = box.Text.rectTransform;
            textRect.offsetMax = new Vector2(-24f, string.IsNullOrEmpty(box.Label.text) ? -10f : -44f);
            box.Text.text = GameUi.Plain(text);
            box.Root.gameObject.SetActive(true);
            GameAnim.Pop(box.Root, 0.45f, 0.1f);
        }

        private static Color BarColor(int percent)
        {
            return percent >= 66 ? GameColors.Green : percent >= 33 ? GameColors.Yellow : GameColors.Red;
        }

        /// <summary>Todo oculto, como al montar.</summary>
        public void Clear()
        {
            _kind = string.Empty;
            _starsAt = -1f;
            _barAt = -1f;
            foreach (RectTransform view in _views.Values)
            {
                view.gameObject.SetActive(false);
            }
        }

        public void Tick(float dt)
        {
            _clock += dt;
            if (_starsAt >= 0f)
            {
                // Las estrellas se llenan una a una (media estrella por punto).
                float stars = _starsScore / 2f;
                for (int i = 0; i < _starFills.Length; i++)
                {
                    float start = _starsAt + 0.15f + (i * 0.18f);
                    float t = Mathf.Clamp01((_clock - start) / 0.22f);
                    float target = Mathf.Clamp01(stars - i);
                    _starFills[i].fillAmount = target * t;
                    float pop = t > 0f && t < 1f && target > 0f ? 1f + (0.25f * Mathf.Sin(t * Mathf.PI)) : 1f;
                    _starFills[i].transform.parent.localScale = new Vector3(pop, pop, 1f);
                }
            }

            if (_barAt >= 0f && _bar != null)
            {
                float t = Mathf.Clamp01((_clock - _barAt - 0.25f) / 1.3f);
                float eased = GameUi.EaseOutCubic(t);
                float value = _barTarget * eased;
                float width = _bar.rect.width;
                float minWidth = _bar.rect.height;
                RectTransform fill = _barFill.rectTransform;
                fill.sizeDelta = new Vector2(Mathf.Lerp(minWidth, Mathf.Max(minWidth, width), value / 100f), 0f);
                _barFill.color = BarColor(Mathf.RoundToInt(value));
                _percent.text = "<color=#" + ColorUtility.ToHtmlStringRGB(BarColor(Mathf.RoundToInt(value))) + ">"
                    + Mathf.RoundToInt(value) + " %</color><size=45%>  DE PROBABILIDAD</size>";
            }
        }
    }
}
