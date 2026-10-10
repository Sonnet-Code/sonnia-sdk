// Búsqueda relámpago (docs/plan-juegos.md, 5.6; docs/juegos/busqueda.md): controlador de Unity.
//
// «¡El primero que me enseñe algo azul!». El orquestador lleva las rondas, el contador y las
// miradas de la cámara; Unity solo pinta lo que le manda (docs/protocolo.md, «busqueda»):
//
//  - La vista en vivo de la cámara sale sola en la franja alta (CameraPreviewPanel) y la
//    tarjeta común se coloca debajo (GameHud). Sobre la imagen van, en Preview.Overlay, el
//    barrido de «mirando» (un evento checking por foto al modelo) y un marco de color que
//    avisa de ¡encontrado! (verde) o ¡tiempo! (rojo).
//  - La tarjeta: cabecera con el título de colores, «RONDA 1 DE 3» y un punto por ronda
//    (verde si se encontró, rojo si no); debajo, el cuadro con el color del objeto y un «?»,
//    el objeto en grande y el contador circular a la derecha. Al ver el objeto, el cuadro
//    pasa a un visto, sale «¡Encontrado!» y lo que vio la cámara, con confeti.
//  - Cada mensaje de ronda (round, go, found, timeout) lleva el estado completo: tras
//    reconectar, el último que repite el orquestador basta para repintar todo.
//  - El final (end) lo cuenta la tarjeta de resultado común: «3 de 3», «2 de 3»...
//
// Nada se guarda: la imagen de la cámara no se toca aquí, solo se pintan marcas encima.

using System;
using Newtonsoft.Json;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia.Games.Busqueda
{
    /// <summary>Pantalla de «Búsqueda relámpago» (id <c>busqueda</c>).</summary>
    public class BusquedaController : GameControllerBase
    {
        /// <summary>Id del juego en el protocolo.</summary>
        public const string GameId = "busqueda";

        [Header("Reacciones de Sonnia (clips del set, como la trivia)")]
        [SerializeField]
        private string foundClip = "actions-highFive_actionSuccess";

        [SerializeField]
        private string foundFallbackClip = "QuickAction_twoThumbsUp";

        [SerializeField]
        private string timeoutClip = "actions-highFive_actionFail";

        [SerializeField]
        private string winClip = "QuickAction_vibe";

        [SerializeField]
        private string loseClip = "emotions-0049-traitsKind";

        [SerializeField]
        private string loseFallbackClip = "Peace";

        [Header("Diseño (px de la referencia 1080x1920)")]
        [SerializeField]
        [Tooltip("Alto del contenido de la tarjeta, bajo la cabecera.")]
        private float contentHeight = 196f;

        [SerializeField]
        [Tooltip("Lado del cuadro del color del objeto.")]
        private float swatchSize = 150f;

        [SerializeField]
        [Tooltip("Diámetro del contador circular.")]
        private float countdownSize = 168f;

        [SerializeField]
        [Range(0.3f, 3f)]
        [Tooltip("Segundos que dura el barrido de «mirando» sobre la vista en vivo.")]
        private float scanSeconds = 1.1f;

        // ------------------------------------------------------------------
        // data de los mensajes (docs/protocolo.md)
        // ------------------------------------------------------------------

        private sealed class StartData
        {
            [JsonProperty("rounds")] public int Rounds;
            [JsonProperty("round_seconds")] public float RoundSeconds;
            [JsonProperty("preview")] public bool ShowsPreview;
        }

        /// <summary>El estado completo de una ronda: round, go, found y timeout.</summary>
        private sealed class RoundData
        {
            [JsonProperty("index")] public int Index;
            [JsonProperty("total")] public int Total;
            [JsonProperty("object")] public string Target;
            [JsonProperty("color")] public string Color;
            [JsonProperty("seconds")] public float Seconds;
            [JsonProperty("found")] public int Found;
            [JsonProperty("phase")] public string Phase;
            [JsonProperty("what")] public string What;
            [JsonProperty("silent")] public bool Silent;
        }

        private sealed class CheckData
        {
            [JsonProperty("n")] public int N;
            [JsonProperty("max")] public int Max;
        }

        private sealed class EndData
        {
            [JsonProperty("found")] public int Found;
            [JsonProperty("total")] public int Total;
        }

        private enum Mode
        {
            Idle,
            Ready,
            Running,
            Found,
            Timeout
        }

        private enum Mark
        {
            Pending,
            Current,
            Found,
            Missed
        }

        // Cuadro del objeto y textos.
        private bool _built;
        private RectTransform _swatch;
        private Image _swatchFill;
        private TextMeshProUGUI _glyph;
        private Image _badge;
        private TextMeshProUGUI _label;
        private TextMeshProUGUI _name;

        // Puntos de progreso en la cabecera.
        private Image[] _dots = new Image[0];
        private Mark[] _marks = new Mark[0];

        // Encima de la vista en vivo.
        private RectTransform _overlay;
        private Image _frameGlow;
        private RectTransform _scanLine;
        private Image _scanLineImage;
        private RectTransform _scanHalo;
        private Image _scanHaloImage;
        private RectTransform _corners;
        private CanvasGroup _cornersGroup;
        private TextMeshProUGUI _scanText;
        private CanvasGroup _scanTextGroup;

        // Estado.
        private Mode _mode = Mode.Idle;
        private int _index;
        private int _total = 3;
        private float _roundSeconds = 25f;
        private float _clock;
        private float _scanAt = -10f;
        private float _flashAt = -10f;
        private Color _flashColor = Color.clear;
        private float _flashSeconds = 2.4f;

        public override string Id
        {
            get { return GameId; }
        }

        protected override string DefaultTitle
        {
            get { return "Búsqueda relámpago"; }
        }

        // ------------------------------------------------------------------
        // Ciclo de vida
        // ------------------------------------------------------------------

        protected override void OnStart(string dataJson)
        {
            StartData start = ParseData<StartData>(dataJson);
            _total = Mathf.Clamp(start.Rounds > 0 ? start.Rounds : 3, 1, 12);
            _roundSeconds = start.RoundSeconds > 0f ? start.RoundSeconds : 25f;
            _index = 0;
            _mode = Mode.Idle;
            EnsureBuilt();
            BuildDots();
            ClearOutcome();
            SetSwatch(string.Empty, "?");
            SetLabel("PREPÁRENSE…", GameColors.Muted);
            SetName(string.Empty, 1f);
            Hud.SetCaption(string.Empty);
            PlaceCountdown();
            Hud.StopCountdown(true);
        }

        protected override void OnGameEvent(string eventName, string dataJson)
        {
            if (!_built)
            {
                // Un evento sin start (no debería pasar): se monta y se sigue.
                EnsureBuilt();
            }

            switch (eventName)
            {
                case "round":
                    ShowRound(ParseData<RoundData>(dataJson), false);
                    break;
                case "go":
                    ShowRound(ParseData<RoundData>(dataJson), true);
                    break;
                case "checking":
                    StartScan(ParseData<CheckData>(dataJson));
                    break;
                case "found":
                    ShowFound(ParseData<RoundData>(dataJson));
                    break;
                case "timeout":
                    ShowTimeout(ParseData<RoundData>(dataJson));
                    break;
                default:
                    Log("evento sin pantalla: " + eventName);
                    break;
            }
        }

        /// <summary>El final: la tarjeta de resultado común con las rondas encontradas.</summary>
        protected override void ShowDefaultResult(string result, string dataJson)
        {
            EndData end = ParseData<EndData>(dataJson);
            int total = Mathf.Max(1, end.Total > 0 ? end.Total : _total);
            int found = Mathf.Clamp(end.Found, 0, total);
            bool won = result == GameResults.Win;
            string title;
            string line;
            if (found >= total)
            {
                title = "¡PLENO!";
                line = "¡Nada se les escapa!";
            }
            else if (won)
            {
                title = "¡BUEN OJO!";
                line = "¡Qué buena búsqueda!";
            }
            else
            {
                title = "¡CASI!";
                line = "¡Pídeme otra y lo intentan de nuevo!";
            }

            Hud.ShowResult(title, found + " de " + total, line, won);
            if (won)
            {
                PlayReaction(winClip, null);
                ShowEmotion(FacialExpressionController.Emotion.Joy, 4f);
            }
            else
            {
                PlayReaction(loseClip, loseFallbackClip);
                ShowEmotion(FacialExpressionController.Emotion.Joy, 2f);
            }
        }

        protected override void OnClosed()
        {
            _mode = Mode.Idle;
            _scanAt = -10f;
            _flashAt = -10f;
            if (Hud != null)
            {
                Hud.StopCountdown(true);
                Hud.HideBanner();
            }

            if (_overlay != null)
            {
                _overlay.gameObject.SetActive(false);
            }

            if (_built)
            {
                ClearOutcome();
                SetSwatch(string.Empty, "?");
                SetName(string.Empty, 1f);
            }
        }

        // ------------------------------------------------------------------
        // Rondas
        // ------------------------------------------------------------------

        /// <summary>round (lista, el contador quieto con el tiempo entero) y go (corriendo).</summary>
        private void ShowRound(RoundData data, bool running)
        {
            Apply(data);
            ClearOutcome();
            _mode = running ? Mode.Running : Mode.Ready;
            float seconds = data.Seconds > 0f ? data.Seconds : _roundSeconds;
            _roundSeconds = seconds;
            Hud.StartCountdown(seconds);
            if (running)
            {
                SetLabel("¡BUSCA!", GameColors.Green);
            }
            else
            {
                // Lista: el tiempo entero, parado, hasta que llegue el «¡Ya!».
                Hud.StopCountdown(false);
                SetLabel("PREPÁRENSE…", GameColors.Muted);
                Hud.PopCard();
                GameAnim.Pop(_swatch, 0.5f);
            }

            Log("ronda " + _index + " de " + _total + ": " + data.Target + (running ? " (corre)" : " (lista)"));
        }

        private void ShowFound(RoundData data)
        {
            Apply(data);
            ClearOutcome();
            _mode = Mode.Found;
            SetMark(_index, Mark.Found);
            Hud.StopCountdown(false);

            string what = string.IsNullOrEmpty(data.What) ? data.Target : data.What;
            SetLabel("¡LO VEO!", GameColors.Green);
            SetName(what, 1f);
            ShowBadge(Hud.CheckSprite, GameColors.Green);
            Hud.ShowBanner("¡Encontrado!", GameColors.Green);
            Flash(GameColors.Green, 2.6f);

            // Confeti desde las esquinas de abajo de la vista en vivo y destellos en la tarjeta.
            Hud.Burst(new Vector2(-430f, 225f), 55, 1500f, 62f);
            Hud.Burst(new Vector2(430f, 225f), 55, 1500f, 118f);
            Hud.SparklesAt(_swatch, 10);
            PlayReaction(foundClip, foundFallbackClip);
            ShowEmotion(FacialExpressionController.Emotion.Joy, 3f);
            Log("ronda " + _index + " encontrada: " + what);
        }

        private void ShowTimeout(RoundData data)
        {
            Apply(data);
            ClearOutcome();
            _mode = Mode.Timeout;
            SetMark(_index, Mark.Missed);
            Hud.StopCountdown(false);

            SetLabel(data.Silent ? "NO PUDE MIRAR BIEN" : "NADIE LO ENSEÑÓ", GameColors.Red);
            SetName(data.Target, 0.55f);
            ShowBadge(Hud.CrossSprite, GameColors.Red);
            Hud.ShowBanner("¡Tiempo!", GameColors.Red);
            Flash(GameColors.Red, 1.4f);
            PlayReaction(timeoutClip, null);
            ShowEmotion(FacialExpressionController.Emotion.Sad, 2.2f);
            Log("ronda " + _index + ": se acabó el tiempo");
        }

        /// <summary>Pinta lo común del estado de una ronda (idempotente: sirve también tras reconectar).</summary>
        private void Apply(RoundData data)
        {
            _index = Mathf.Max(1, data.Index);
            _total = Mathf.Clamp(data.Total > 0 ? data.Total : _total, 1, 12);
            EnsureDots(_total);
            FillUnknownMarks(_index, data.Phase == "found" ? data.Found - 1 : data.Found);
            for (int i = 0; i < _marks.Length; i++)
            {
                if (_marks[i] == Mark.Current)
                {
                    _marks[i] = Mark.Pending;
                }
            }

            if (_index - 1 < _marks.Length && _marks[_index - 1] == Mark.Pending)
            {
                _marks[_index - 1] = Mark.Current;
            }

            PaintDots();
            Hud.SetCaption("RONDA " + _index + " DE " + _total);
            SetSwatch(data.Color, "?");
            SetName(data.Target, 1f);
            PlaceCountdown();
        }

        // ------------------------------------------------------------------
        // Construcción
        // ------------------------------------------------------------------

        private void EnsureBuilt()
        {
            if (_built || Hud == null || Content == null)
            {
                return;
            }

            _built = true;
            RectTransform content = Content;
            Hud.SetContentHeight(Id, contentHeight);

            // El cuadro del color del objeto, con un «?» (o un visto / una cruz al terminar la ronda).
            _swatch = Hud.NewRect("Cuadro", content);
            _swatch.anchorMin = new Vector2(0f, 0.5f);
            _swatch.anchorMax = new Vector2(0f, 0.5f);
            _swatch.pivot = new Vector2(0.5f, 0.5f);
            _swatch.sizeDelta = new Vector2(swatchSize, swatchSize);
            _swatch.anchoredPosition = new Vector2((swatchSize * 0.5f) + 6f, 0f);
            _swatchFill = Hud.NewRound("Color", _swatch, GameColors.Brand, 38f);
            GameUi.Stretch(_swatchFill.rectTransform);
            _glyph = Hud.NewText("Signo", _swatch, "?", 112f, Color.white, TextAlignmentOptions.Center, Hud.DisplayFont);
            _glyph.textWrappingMode = TextWrappingModes.NoWrap;
            GameUi.Stretch(_glyph.rectTransform);
            _badge = Hud.NewImage("Marca", _swatch, Hud.CheckSprite, Color.white);
            _badge.preserveAspect = true;
            GameUi.Stretch(_badge.rectTransform);
            _badge.gameObject.SetActive(false);

            // La columna de texto, entre el cuadro y el contador.
            RectTransform column = Hud.NewRect("Texto", content);
            column.anchorMin = Vector2.zero;
            column.anchorMax = Vector2.one;
            column.offsetMin = new Vector2(swatchSize + 44f, 0f);
            column.offsetMax = new Vector2(-(countdownSize + 28f), 0f);

            _label = Hud.NewText("Rotulo", column, string.Empty, 28f, GameColors.Muted, TextAlignmentOptions.TopLeft, Hud.MonoFont);
            _label.characterSpacing = 6f;
            _label.textWrappingMode = TextWrappingModes.NoWrap;
            RectTransform labelRect = _label.rectTransform;
            labelRect.anchorMin = new Vector2(0f, 1f);
            labelRect.anchorMax = new Vector2(1f, 1f);
            labelRect.pivot = new Vector2(0.5f, 1f);
            labelRect.sizeDelta = new Vector2(0f, 40f);
            labelRect.anchoredPosition = new Vector2(0f, -6f);

            _name = Hud.NewText("Objeto", column, string.Empty, 66f, Color.white, TextAlignmentOptions.TopLeft, Hud.DisplayFont);
            _name.enableAutoSizing = true;
            _name.fontSizeMax = 66f;
            _name.fontSizeMin = 32f;
            _name.lineSpacing = -8f;
            RectTransform nameRect = _name.rectTransform;
            nameRect.anchorMin = Vector2.zero;
            nameRect.anchorMax = Vector2.one;
            nameRect.offsetMin = new Vector2(0f, 8f);
            nameRect.offsetMax = new Vector2(0f, -50f);

            BuildOverlay();
        }

        /// <summary>El contador circular, dentro del contenido y a la derecha.</summary>
        private void PlaceCountdown()
        {
            if (Hud == null || Content == null)
            {
                return;
            }

            Hud.PlaceCountdown(Content, new Vector2(1f, 0.5f), new Vector2(-((countdownSize * 0.5f) + 6f), 0f), countdownSize);
        }

        private void BuildOverlay()
        {
            if (Preview == null)
            {
                return;
            }

            RectTransform host = Preview.Overlay;
            if (host == null)
            {
                return;
            }

            _overlay = Hud.NewRect("Busqueda", host);
            GameUi.Stretch(_overlay);

            // Marco de color: verde al encontrar, rojo al acabarse el tiempo.
            _frameGlow = Hud.NewImage("Marco", _overlay, Hud.FrameSprite, Color.clear);
            GameHud.SetRadius(_frameGlow, 28f);
            GameUi.Stretch(_frameGlow.rectTransform);

            // Barrido: una línea clara con un halo que baja por la imagen.
            _scanHaloImage = Hud.NewRound("Halo", _overlay, GameUi.WithAlpha(Color.white, 0.18f), 20f);
            _scanHalo = _scanHaloImage.rectTransform;
            _scanHalo.anchorMin = new Vector2(0f, 1f);
            _scanHalo.anchorMax = new Vector2(1f, 1f);
            _scanHalo.pivot = new Vector2(0.5f, 0.5f);
            _scanHalo.sizeDelta = new Vector2(-40f, 56f);
            _scanLineImage = Hud.NewRound("Linea", _overlay, Color.white, 2.5f);
            _scanLine = _scanLineImage.rectTransform;
            _scanLine.anchorMin = new Vector2(0f, 1f);
            _scanLine.anchorMax = new Vector2(1f, 1f);
            _scanLine.pivot = new Vector2(0.5f, 0.5f);
            _scanLine.sizeDelta = new Vector2(-40f, 5f);

            // Esquinas de «enfocando».
            CanvasGroup corners = Hud.NewGroup("Esquinas", _overlay);
            _cornersGroup = corners;
            _corners = (RectTransform)corners.transform;
            float margin = 30f;
            float length = 64f;
            float thickness = 7f;
            for (int i = 0; i < 4; i++)
            {
                float sx = (i & 1) == 0 ? 0f : 1f;
                float sy = (i & 2) == 0 ? 1f : 0f;
                float dx = (i & 1) == 0 ? 1f : -1f;
                float dy = (i & 2) == 0 ? -1f : 1f;
                MakeCorner(_corners, sx, sy, dx * margin, dy * margin, length, thickness, dx, dy);
            }

            // «MIRANDO…» abajo, en el centro.
            RectTransform pill = Hud.NewRect("Mirando", _overlay);
            pill.anchorMin = new Vector2(0.5f, 0f);
            pill.anchorMax = new Vector2(0.5f, 0f);
            pill.pivot = new Vector2(0.5f, 0f);
            pill.sizeDelta = new Vector2(330f, 54f);
            pill.anchoredPosition = new Vector2(0f, 24f);
            _scanTextGroup = pill.gameObject.AddComponent<CanvasGroup>();
            _scanTextGroup.alpha = 0f;
            Image pillFill = Hud.NewRound("Fondo", pill, GameUi.WithAlpha(GameColors.Dark, 0.78f), 27f);
            GameUi.Stretch(pillFill.rectTransform);
            _scanText = Hud.NewText("Texto", pill, "MIRANDO…", 26f, Color.white, TextAlignmentOptions.Center, Hud.MonoFont);
            _scanText.characterSpacing = 6f;
            _scanText.textWrappingMode = TextWrappingModes.NoWrap;
            GameUi.Stretch(_scanText.rectTransform);

            _overlay.gameObject.SetActive(false);
        }

        /// <summary>Una esquina en L: dos barras finas pegadas al vértice.</summary>
        private void MakeCorner(RectTransform parent, float anchorX, float anchorY, float x, float y, float length, float thickness, float dx, float dy)
        {
            RectTransform corner = Hud.NewRect("Esquina", parent);
            corner.anchorMin = new Vector2(anchorX, anchorY);
            corner.anchorMax = new Vector2(anchorX, anchorY);
            corner.pivot = new Vector2(anchorX, anchorY);
            corner.anchoredPosition = new Vector2(x, y);
            corner.sizeDelta = Vector2.zero;
            Image horizontal = Hud.NewRound("H", corner, Color.white, thickness * 0.5f);
            horizontal.rectTransform.anchorMin = new Vector2(anchorX, anchorY);
            horizontal.rectTransform.anchorMax = new Vector2(anchorX, anchorY);
            horizontal.rectTransform.pivot = new Vector2(anchorX, anchorY);
            horizontal.rectTransform.sizeDelta = new Vector2(length, thickness);
            horizontal.rectTransform.anchoredPosition = Vector2.zero;
            Image vertical = Hud.NewRound("V", corner, Color.white, thickness * 0.5f);
            vertical.rectTransform.anchorMin = new Vector2(anchorX, anchorY);
            vertical.rectTransform.anchorMax = new Vector2(anchorX, anchorY);
            vertical.rectTransform.pivot = new Vector2(anchorX, anchorY);
            vertical.rectTransform.sizeDelta = new Vector2(thickness, length);
            vertical.rectTransform.anchoredPosition = Vector2.zero;
        }

        // ------------------------------------------------------------------
        // Puntos de progreso (cabecera)
        // ------------------------------------------------------------------

        private void BuildDots()
        {
            for (int i = 0; i < _dots.Length; i++)
            {
                if (_dots[i] != null)
                {
                    Destroy(_dots[i].gameObject);
                }
            }

            _dots = new Image[0];
            _marks = new Mark[0];
            EnsureDots(_total);
        }

        private void EnsureDots(int total)
        {
            RectTransform parent = Hud != null ? Hud.HeaderRight : null;
            if (parent == null || _dots.Length == total)
            {
                return;
            }

            for (int i = 0; i < _dots.Length; i++)
            {
                if (_dots[i] != null)
                {
                    Destroy(_dots[i].gameObject);
                }
            }

            _dots = new Image[total];
            Mark[] marks = new Mark[total];
            for (int i = 0; i < total && i < _marks.Length; i++)
            {
                marks[i] = _marks[i];
            }

            _marks = marks;
            for (int i = 0; i < total; i++)
            {
                Image dot = Hud.NewImage("Ronda" + (i + 1), parent, Hud.DotSprite, Color.white);
                LayoutElement layout = dot.gameObject.AddComponent<LayoutElement>();
                layout.preferredWidth = 28f;
                layout.preferredHeight = 28f;
                _dots[i] = dot;
            }

            PaintDots();
        }

        private void SetMark(int round, Mark mark)
        {
            int slot = round - 1;
            if (slot >= 0 && slot < _marks.Length)
            {
                _marks[slot] = mark;
                PaintDots();
            }
        }

        /// <summary>Tras reconectar solo llega el último estado: las rondas anteriores se reparten como se pueda.</summary>
        private void FillUnknownMarks(int currentRound, int foundBefore)
        {
            int known = 0;
            int unknown = 0;
            for (int i = 0; i < currentRound - 1 && i < _marks.Length; i++)
            {
                if (_marks[i] == Mark.Found)
                {
                    known++;
                }
                else if (_marks[i] == Mark.Pending || _marks[i] == Mark.Current)
                {
                    unknown++;
                }
            }

            int toFind = Mathf.Clamp(foundBefore - known, 0, unknown);
            for (int i = 0; i < currentRound - 1 && i < _marks.Length; i++)
            {
                if (_marks[i] == Mark.Pending || _marks[i] == Mark.Current)
                {
                    _marks[i] = toFind > 0 ? Mark.Found : Mark.Missed;
                    toFind--;
                }
            }
        }

        private void PaintDots()
        {
            for (int i = 0; i < _dots.Length && i < _marks.Length; i++)
            {
                if (_dots[i] == null)
                {
                    continue;
                }

                switch (_marks[i])
                {
                    case Mark.Found:
                        _dots[i].color = GameColors.Green;
                        break;
                    case Mark.Missed:
                        _dots[i].color = GameColors.Red;
                        break;
                    case Mark.Current:
                        _dots[i].color = Color.white;
                        break;
                    default:
                        _dots[i].color = GameUi.WithAlpha(Color.white, 0.25f);
                        break;
                }
            }
        }

        // ------------------------------------------------------------------
        // Piezas sueltas
        // ------------------------------------------------------------------

        /// <summary>Cuadro del objeto: su color (o el de la marca) y un signo.</summary>
        private void SetSwatch(string hexColor, string glyph)
        {
            if (_swatchFill == null)
            {
                return;
            }

            // Sin color propio (una botella, unas llaves): un cuadro neutro, para que no parezca
            // que el objeto es de un color.
            Color color = GameUi.WithAlpha(Color.white, 0.16f);
            bool hasColor = false;
            Color parsed;
            if (!string.IsNullOrEmpty(hexColor) && ColorUtility.TryParseHtmlString(hexColor, out parsed))
            {
                color = parsed;
                hasColor = true;
            }

            _swatchFill.color = color;
            float luminance = (0.2126f * color.r) + (0.7152f * color.g) + (0.0722f * color.b);
            _glyph.color = hasColor && luminance > 0.62f ? GameColors.Dark : Color.white;
            _glyph.text = glyph;
            _glyph.gameObject.SetActive(true);
            _badge.gameObject.SetActive(false);
        }

        /// <summary>Un visto o una cruz en el sitio del «?».</summary>
        private void ShowBadge(Sprite sprite, Color tint)
        {
            _glyph.gameObject.SetActive(false);
            _swatchFill.color = GameUi.WithAlpha(tint, 0.18f);
            _badge.sprite = sprite;
            _badge.color = Color.white;
            _badge.gameObject.SetActive(true);
            GameAnim.Pop(_badge.rectTransform, 0.5f);
        }

        /// <summary>Quita lo del final de la ronda anterior (visto, cruz, rótulo y marco).</summary>
        private void ClearOutcome()
        {
            if (!_built)
            {
                return;
            }

            _badge.gameObject.SetActive(false);
            _glyph.gameObject.SetActive(true);
            _swatch.localScale = Vector3.one;
            Hud.HideBanner();
            _flashAt = -10f;
            if (_frameGlow != null)
            {
                _frameGlow.color = Color.clear;
            }
        }

        private void SetLabel(string text, Color color)
        {
            if (_label != null)
            {
                _label.text = GameUi.Plain(text);
                _label.color = color;
            }
        }

        private void SetName(string text, float alpha)
        {
            if (_name != null)
            {
                _name.text = GameUi.Plain(text ?? string.Empty).ToUpperInvariant();
                _name.color = GameUi.WithAlpha(Color.white, alpha);
            }
        }

        // ------------------------------------------------------------------
        // Efectos sobre la vista en vivo
        // ------------------------------------------------------------------

        private void StartScan(CheckData data)
        {
            if (_overlay == null || _mode != Mode.Running)
            {
                return;
            }

            _overlay.gameObject.SetActive(true);
            _scanAt = _clock;
        }

        private void Flash(Color color, float seconds)
        {
            if (_overlay == null)
            {
                return;
            }

            _overlay.gameObject.SetActive(true);
            _flashColor = color;
            _flashAt = _clock;
            _flashSeconds = seconds;
        }

        private void Update()
        {
            if (!IsActive)
            {
                return;
            }

            _clock += Time.deltaTime;
            AnimateScan();
            AnimateFlash();
            AnimateSwatch();
        }

        private void AnimateScan()
        {
            if (_scanLine == null || _overlay == null)
            {
                return;
            }

            float t = Mathf.Clamp01((_clock - _scanAt) / scanSeconds);
            bool scanning = _scanAt >= 0f && _clock - _scanAt < scanSeconds;
            _scanLine.gameObject.SetActive(scanning);
            _scanHalo.gameObject.SetActive(scanning);
            _cornersGroup.alpha = scanning ? Mathf.Sin(t * Mathf.PI) : 0f;
            _scanTextGroup.alpha = scanning ? Mathf.Clamp01(Mathf.Sin(t * Mathf.PI) * 3f) : 0f;
            if (!scanning)
            {
                return;
            }

            // De arriba abajo de la imagen (16:9) con frenada suave al final.
            float height = Preview != null ? Preview.FrameSize.y : 540f;
            float y = Mathf.Lerp(-8f, -(height - 8f), GameUi.EaseInOutSine(t));
            float fade = Mathf.Sin(t * Mathf.PI);
            _scanLine.anchoredPosition = new Vector2(0f, y);
            _scanHalo.anchoredPosition = new Vector2(0f, y);
            _scanLineImage.color = GameUi.WithAlpha(Color.white, 0.95f * fade);
            _scanHaloImage.color = GameUi.WithAlpha(Color.white, 0.2f * fade);
            _cornersGroup.transform.localScale = Vector3.one * Mathf.Lerp(1.03f, 1f, GameUi.EaseOutCubic(Mathf.Clamp01(t * 3f)));
        }

        private void AnimateFlash()
        {
            if (_frameGlow == null)
            {
                return;
            }

            float s = _clock - _flashAt;
            if (_flashAt < 0f || s > _flashSeconds)
            {
                if (_frameGlow.color.a > 0f)
                {
                    _frameGlow.color = Color.clear;
                }

                return;
            }

            float pulse = 0.65f + (0.35f * Mathf.Sin(s * 9f));
            float fade = Mathf.Clamp01((_flashSeconds - s) / 0.5f);
            _frameGlow.color = GameUi.WithAlpha(_flashColor, pulse * fade);
        }

        /// <summary>El cuadro late un poco mientras corre el tiempo.</summary>
        private void AnimateSwatch()
        {
            if (_swatch == null || _mode != Mode.Running)
            {
                return;
            }

            float scale = 1f + (0.025f * Mathf.Sin(_clock * 4.2f));
            _swatch.localScale = new Vector3(scale, scale, 1f);
        }
    }
}
