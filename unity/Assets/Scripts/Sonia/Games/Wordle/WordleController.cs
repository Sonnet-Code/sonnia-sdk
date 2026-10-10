// Wordle de tecnología (docs/plan-juegos.md, 5.5, y docs/juegos/wordle.md): pantalla de Unity.
//
// El orquestador elige la palabra, colorea cada intento con la regla del Wordle de verdad
// (también con letras repetidas) y manda el tablero entero: aquí solo se pinta.
//
//  - A la izquierda de la tarjeta, la rejilla de 6×5. En cada "guess" las letras entran, las
//    fichas se voltean una a una (GameAnim.Flip) con los colores clásicos (verde, amarillo y
//    gris) y, al acertar, la fila baila con confeti. Si la palabra no vale ("invalid"), la
//    fila se sacude con lo que se entendió y un rótulo dice por qué; el intento no se gasta.
//  - A la derecha, arriba la pista: candada hasta el intento que diga el start, luego sale y,
//    al terminar, enseña la palabra. Debajo, las letras usadas con su mejor color.
//  - Si Unity se reconecta o arranca a mitad, el último "guess" trae el tablero entero: las
//    filas que no se habían visto salen ya puestas y solo la última se voltea.
//
// Eventos (docs/protocolo.md, «Eventos de cada juego»): start, guess e invalid. Unity no
// manda ninguno. El final (end) lo cierra GameControllerBase.

using System;
using System.Collections;
using System.Collections.Generic;
using Newtonsoft.Json;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia.Games.Wordle
{
    /// <summary>data del start: la forma de la rejilla.</summary>
    [Serializable]
    public class WordleStartData
    {
        [JsonProperty("rows")] public int Rows = 6;
        [JsonProperty("cols")] public int Cols = 5;
        [JsonProperty("hint_after")] public int HintAfter = 4;
    }

    /// <summary>Una fila del tablero: sus letras y sus marcas (g verde, y amarilla, x gris).</summary>
    [Serializable]
    public class WordleRowData
    {
        [JsonProperty("letters")] public string Letters = string.Empty;
        [JsonProperty("marks")] public string Marks = string.Empty;
    }

    /// <summary>Las letras usadas, cada una en su mejor color.</summary>
    [Serializable]
    public class WordleUsedData
    {
        [JsonProperty("g")] public string Green = string.Empty;
        [JsonProperty("y")] public string Yellow = string.Empty;
        [JsonProperty("x")] public string Gray = string.Empty;
    }

    /// <summary>data de guess: el intento nuevo y el estado completo (tablero, letras, pista y final).</summary>
    [Serializable]
    public class WordleGuessData
    {
        [JsonProperty("row")] public int Row;
        [JsonProperty("letters")] public string Letters = string.Empty;
        [JsonProperty("marks")] public string Marks = string.Empty;
        [JsonProperty("board")] public List<WordleRowData> Board = new List<WordleRowData>();
        [JsonProperty("used")] public WordleUsedData Used = new WordleUsedData();
        [JsonProperty("hint")] public string Hint = string.Empty;
        [JsonProperty("result")] public string Result = string.Empty;
        [JsonProperty("word")] public string Word = string.Empty;
    }

    /// <summary>data de invalid: la palabra no vale (no es de cinco letras, lleva símbolos o ya la probaron).</summary>
    [Serializable]
    public class WordleInvalidData
    {
        [JsonProperty("letters")] public string Letters = string.Empty;
        [JsonProperty("reason")] public string Reason = string.Empty;
        [JsonProperty("message")] public string Message = string.Empty;
    }

    /// <summary>data del end de este juego: la palabra y los intentos.</summary>
    [Serializable]
    public class WordleEndData
    {
        [JsonProperty("word")] public string Word = string.Empty;
        [JsonProperty("attempts")] public int Attempts;
    }

    /// <summary>Pantalla de «Wordle de tecnología» (id <c>wordle</c>).</summary>
    public class WordleController : GameControllerBase
    {
        /// <summary>Id del juego en el protocolo.</summary>
        public const string GameId = "wordle";

        // Medidas, en píxeles de la referencia 1080x1920 (la tarjeta mide 960 y su contenido 872).
        private const float MaxTile = 88f;
        private const float TileGap = 10f;
        private const float GridMaxHeight = 578f;
        private const float BorderWidth = 3f;
        private const float ColumnGap = 28f;
        private const float KeySize = 46f;
        private const float KeyGap = 6f;
        private const int KeyColumns = 7;
        private const float KeyLabelHeight = 30f;
        private const float InfoGap = 20f;
        private const float MinInfoHeight = 170f;
        private const float InfoPadding = 26f;

        // Tiempos, en segundos.
        private const float TypeSeconds = 0.32f;
        private const float FlipSeconds = 0.5f;
        private const float FlipStagger = 0.2f;
        private const float InvalidSeconds = 1.4f;

        // Los colores clásicos del Wordle, algo más vivos para que se lean desde lejos.
        private static readonly Color CorrectColor = new Color32(76, 165, 83, 255);
        private static readonly Color PresentColor = new Color32(206, 168, 36, 255);
        private static readonly Color AbsentColor = new Color32(62, 70, 94, 255);
        // Los fondos son opacos: el borde es una pieza entera debajo y, si el fondo dejara pasar
        // algo, toda la ficha se vería del color del borde.
        private static readonly Color EmptyFill = new Color(0.07f, 0.11f, 0.22f, 1f);
        private static readonly Color EmptyBorder = new Color(0.27f, 0.37f, 0.6f, 1f);
        private static readonly Color TypedFill = new Color(0.11f, 0.17f, 0.32f, 1f);
        private static readonly Color TypedBorder = new Color(0.78f, 0.87f, 1f, 1f);
        private static readonly Color KeyFill = new Color(0.27f, 0.36f, 0.58f, 1f);
        private static readonly Color KeyAbsentFill = new Color(0.09f, 0.13f, 0.23f, 1f);
        private static readonly Color KeyAbsentLetter = new Color(0.42f, 0.48f, 0.62f, 1f);

        private sealed class Tile
        {
            public RectTransform Rect;
            public Image Border;
            public Image Fill;
            public TextMeshProUGUI Letter;
        }

        // Montaje (se rehace en cada partida: las filas pueden cambiar).
        private RectTransform _root;
        private RectTransform _right;
        private RectTransform _info;
        private TextMeshProUGUI _infoLabel;
        private RectTransform _lockedRoot;
        private TextMeshProUGUI _lockedText;
        private RectTransform _hintRoot;
        private TextMeshProUGUI _hintBody;
        private RectTransform _revealRoot;
        private TextMeshProUGUI _revealHint;
        private Tile[] _wordTiles;
        private Tile[,] _tiles;
        private RectTransform[] _rowRects;
        private Image[] _keyFill;
        private TextMeshProUGUI[] _keyLetter;
        private float _tile;
        private float _contentHeight;
        private int _builtRows;
        private int _builtCols;
        private int _builtHintAfter;

        // La partida.
        private int _rows = 6;
        private int _cols = 5;
        private int _hintAfter = 4;
        private bool[] _rowTaken;
        private bool[] _rowDone;
        private int _revealing;
        private bool _hintShown;
        private bool _celebrated;
        private WordleGuessData _last;
        private Coroutine _invalidRoutine;
        private float _bannerUntil;

        public override string Id
        {
            get { return GameId; }
        }

        protected override string DefaultTitle
        {
            get { return "Wordle de tecnología"; }
        }

        // ------------------------------------------------------------------
        // Ciclo de la partida
        // ------------------------------------------------------------------

        protected override void OnStart(string dataJson)
        {
            StopRunning();
            WordleStartData start = ParseData<WordleStartData>(dataJson);
            _rows = Mathf.Clamp(start.Rows, 3, 8);
            _cols = Mathf.Clamp(start.Cols, 3, 7);
            _hintAfter = start.HintAfter;
            _last = null;
            _hintShown = false;
            _celebrated = false;
            if (Hud == null || Content == null)
            {
                Log("sin pantalla de juegos: no se pinta");
                return;
            }

            if (_tiles != null && _builtRows == _rows && _builtCols == _cols && _builtHintAfter == _hintAfter)
            {
                // La misma rejilla que la partida anterior: no se vuelve a montar (son unos 250
                // objetos de interfaz), solo se deja como nueva.
                ResetBoard();
            }
            else
            {
                Build();
            }

            Hud.SetContentHeight(Id, _contentHeight);
            Hud.SetCaption(_rows + " INTENTOS");
            Hud.RefreshLayout();
        }

        protected override void OnGameEvent(string eventName, string dataJson)
        {
            switch (eventName)
            {
                case "guess":
                    HandleGuess(dataJson);
                    break;
                case "invalid":
                    HandleInvalid(dataJson);
                    break;
                default:
                    Log("evento desconocido: " + eventName);
                    break;
            }
        }

        protected override void OnFinish(string result, string dataJson)
        {
            // Lo que aún se anima, ya terminado y con el final puesto (el end llega al menos
            // unos segundos después del último intento, pero con otros ajustes podría llegar antes).
            FinishNow(result == GameResults.Win);
        }

        protected override void ShowDefaultResult(string result, string dataJson)
        {
            WordleEndData end = ParseData<WordleEndData>(dataJson);
            string word = !string.IsNullOrEmpty(end.Word)
                ? end.Word
                : (_last != null ? _last.Word : string.Empty);
            word = GameUi.Plain(word).ToUpperInvariant();
            if (result == GameResults.Win)
            {
                string score = end.Attempts > 0 ? word + " · " + end.Attempts + " DE " + _rows : word;
                Hud.ShowResult("¡GANARON!", score, "¡Eso es nivel DevFest!", true);
            }
            else
            {
                Hud.ShowResult("¡CASI!", string.IsNullOrEmpty(word) ? null : "ERA " + word, "¡Pídanme la revancha!", false);
            }
        }

        protected override void OnClosed()
        {
            // Sin tocar lo que se ve: la pantalla aún se está fundiendo. Lo borra el próximo start.
            StopRunning();
        }

        private void Update()
        {
            if (_bannerUntil > 0f && Time.time >= _bannerUntil)
            {
                _bannerUntil = 0f;
                if (Hud != null)
                {
                    Hud.HideBanner();
                }
            }
        }

        // ------------------------------------------------------------------
        // Un intento
        // ------------------------------------------------------------------

        private void HandleGuess(string dataJson)
        {
            if (_tiles == null)
            {
                return;
            }

            WordleGuessData guess = ParseData<WordleGuessData>(dataJson);
            List<WordleRowData> board = guess.Board ?? new List<WordleRowData>();
            int row = guess.Row;
            if (row < 0 || row >= _rows)
            {
                Log("intento fuera de la rejilla: fila " + row);
                return;
            }

            CancelInvalid();
            // Las filas anteriores que esta pantalla no había visto (se reconectó): ya puestas.
            for (int r = 0; r < row && r < board.Count; r++)
            {
                if (!_rowTaken[r])
                {
                    PaintRowFinal(r, board[r].Letters, board[r].Marks);
                }
            }

            _last = guess;
            StartCoroutine(RevealRow(guess));
        }

        private IEnumerator RevealRow(WordleGuessData guess)
        {
            int row = guess.Row;
            string letters = Clean(guess.Letters);
            string marks = guess.Marks ?? string.Empty;
            _rowTaken[row] = true;
            _revealing++;

            // 1. Las letras entran en la fila.
            for (int c = 0; c < _cols; c++)
            {
                Tile tile = _tiles[row, c];
                PaintTyped(tile, c < letters.Length ? letters[c] : ' ', false);
                GameAnim.Pulse(tile.Rect, 0.14f, 0.16f, c * 0.035f);
            }

            yield return new WaitForSeconds(TypeSeconds);

            // 2. Las fichas se voltean una a una y cambian de color a medio giro.
            for (int c = 0; c < _cols; c++)
            {
                Tile tile = _tiles[row, c];
                char mark = c < marks.Length ? marks[c] : 'x';
                GameAnim.Flip(tile.Rect, () => PaintMarked(tile, mark), FlipSeconds, c * FlipStagger);
            }

            yield return new WaitForSeconds(((_cols - 1) * FlipStagger) + FlipSeconds + 0.05f);
            _rowDone[row] = true;
            _revealing--;

            // 3. Lo que depende del intento: letras, rótulo, pista y final. Si ya llegó otro
            // intento, lo pone el suyo.
            if (_last == guess)
            {
                ApplyUsed(guess.Used);
                Settle(guess);
            }
        }

        /// <summary>Rótulo, pista y final tras voltear la fila (o de golpe, al saltarse la animación).</summary>
        private void Settle(WordleGuessData guess)
        {
            int attempts = guess.Row + 1;
            if (guess.Result == GameResults.Win)
            {
                Hud.SetCaption("¡EN " + attempts + (attempts == 1 ? " INTENTO!" : " INTENTOS!"));
                ShowWord(guess, true);
                Celebrate(guess);
                return;
            }

            if (guess.Result == GameResults.Lose)
            {
                Hud.SetCaption("SIN INTENTOS");
                ShowWord(guess, false);
                if (!_celebrated)
                {
                    _celebrated = true;
                    PlayReaction("emotions-0049-traitsKind", "Peace");
                    ShowEmotion(FacialExpressionController.Emotion.Joy, 2f);
                }

                return;
            }

            Hud.SetCaption("INTENTO " + attempts + " DE " + _rows);
            if (!string.IsNullOrEmpty(guess.Hint) && !_hintShown)
            {
                ShowHint(guess.Hint);
            }
            else if (!_hintShown)
            {
                CountDownHint(attempts);
            }

            int greens = CountMarks(guess.Marks, 'g');
            if (greens >= 3)
            {
                ShowEmotion(FacialExpressionController.Emotion.Joy, 1.6f);
            }
            else if (CountMarks(guess.Marks, 'x') == _cols)
            {
                ShowEmotion(FacialExpressionController.Emotion.Surprise, 1.2f);
            }
        }

        /// <summary>Al acertar: la fila baila, hay confeti y Sonnia lo celebra.</summary>
        private void Celebrate(WordleGuessData guess)
        {
            if (_celebrated)
            {
                return;
            }

            _celebrated = true;
            for (int c = 0; c < _cols; c++)
            {
                Tile tile = _tiles[guess.Row, c];
                Vector2 home = tile.Rect.anchoredPosition;
                float delay = c * 0.1f;
                GameAnim.Pulse(tile.Rect, 0.2f, 0.5f, delay);
                GameAnim.Move(
                    tile.Rect,
                    home + new Vector2(0f, 24f),
                    0.2f,
                    delay,
                    () => GameAnim.Move(tile.Rect, home, 0.32f));
            }

            Hud.Celebrate();
            PlayReaction("QuickAction_vibe", null);
            ShowEmotion(FacialExpressionController.Emotion.Joy, 4f);
        }

        // ------------------------------------------------------------------
        // La palabra no vale
        // ------------------------------------------------------------------

        private void HandleInvalid(string dataJson)
        {
            if (_tiles == null)
            {
                return;
            }

            WordleInvalidData invalid = ParseData<WordleInvalidData>(dataJson);
            int row = NextFreeRow();
            if (row < 0)
            {
                return;
            }

            CancelInvalid();
            string letters = Clean(invalid.Letters);
            for (int c = 0; c < _cols; c++)
            {
                if (c < letters.Length)
                {
                    PaintTyped(_tiles[row, c], letters[c], true);
                }
                else
                {
                    PaintEmpty(_tiles[row, c]);
                }
            }

            GameAnim.Shake(_rowRects[row], 0.55f, 16f);
            if (!string.IsNullOrEmpty(invalid.Message))
            {
                Hud.ShowBanner(GameUi.Plain(invalid.Message), GameColors.Red);
                _bannerUntil = Time.time + InvalidSeconds;
            }

            _invalidRoutine = StartCoroutine(ClearInvalid(row));
        }

        private IEnumerator ClearInvalid(int row)
        {
            yield return new WaitForSeconds(InvalidSeconds);
            _invalidRoutine = null;
            if (_rowTaken != null && !_rowTaken[row])
            {
                for (int c = 0; c < _cols; c++)
                {
                    PaintEmpty(_tiles[row, c]);
                }
            }
        }

        private void CancelInvalid()
        {
            if (_invalidRoutine != null)
            {
                StopCoroutine(_invalidRoutine);
                _invalidRoutine = null;
            }

            if (_bannerUntil > 0f && Hud != null)
            {
                Hud.HideBanner();
                _bannerUntil = 0f;
            }

            int row = NextFreeRow();
            if (row >= 0 && _tiles != null)
            {
                for (int c = 0; c < _cols; c++)
                {
                    PaintEmpty(_tiles[row, c]);
                }
            }
        }

        /// <summary>La primera fila sin intento (ni evaluado ni en pleno volteo), o -1 si el tablero está lleno.</summary>
        private int NextFreeRow()
        {
            if (_rowTaken == null)
            {
                return -1;
            }

            for (int r = 0; r < _rows; r++)
            {
                if (!_rowTaken[r])
                {
                    return r;
                }
            }

            return -1;
        }

        // ------------------------------------------------------------------
        // Pista, palabra y letras usadas
        // ------------------------------------------------------------------

        private void ShowHint(string hint)
        {
            _hintShown = true;
            _infoLabel.text = "PISTA";
            _infoLabel.color = GameColors.Yellow;
            _hintBody.text = GameUi.Plain(hint);
            _lockedRoot.gameObject.SetActive(false);
            _revealRoot.gameObject.SetActive(false);
            _hintRoot.gameObject.SetActive(true);
            GameAnim.Pop(_hintRoot, 0.5f);
            Vector2 center = Hud.EffectsPoint(_info) + new Vector2(_info.sizeDelta.x * 0.5f, -_info.sizeDelta.y * 0.5f);
            Hud.Sparkles(center, 6);
        }

        /// <summary>El rótulo de la pista candada: cuántos intentos faltan para que salga.</summary>
        private string LockedLabel(int attempts)
        {
            bool hasHint = _hintAfter >= 1 && _hintAfter < _rows;
            if (!hasHint)
            {
                return "SIN PISTA";
            }

            int left = _hintAfter - attempts;
            if (left <= 0 || attempts <= 0)
            {
                return "SALE TRAS " + _hintAfter + " INTENTOS";
            }

            return left == 1 ? "LA PISTA SALE TRAS EL PRÓXIMO INTENTO" : "FALTAN " + left + " INTENTOS PARA LA PISTA";
        }

        private void CountDownHint(int attempts)
        {
            string label = LockedLabel(attempts);
            if (_lockedText.text != label)
            {
                _lockedText.text = label;
                GameAnim.Pulse(_lockedText.rectTransform, 0.08f, 0.3f);
            }
        }

        /// <summary>Al terminar: la palabra en fichas con su pista (en verde si la acertaron).</summary>
        private void ShowWord(WordleGuessData guess, bool won)
        {
            string word = Clean(guess.Word);
            _infoLabel.text = won ? "¡LA PALABRA ERA!" : "LA PALABRA ERA";
            _infoLabel.color = won ? GameColors.Gold : Color.white;
            _revealHint.text = GameUi.Plain(guess.Hint ?? string.Empty);
            _lockedRoot.gameObject.SetActive(false);
            _hintRoot.gameObject.SetActive(false);
            _revealRoot.gameObject.SetActive(true);
            for (int c = 0; c < _wordTiles.Length; c++)
            {
                Tile tile = _wordTiles[c];
                tile.Letter.text = c < word.Length ? word[c].ToString() : string.Empty;
                Color color = won ? CorrectColor : GameColors.Blue;
                tile.Fill.color = color;
                tile.Border.color = Lighten(color);
                GameAnim.Pop(tile.Rect, 0.45f, c * 0.08f);
            }
        }

        private void ApplyUsed(WordleUsedData used)
        {
            if (_keyFill == null)
            {
                return;
            }

            for (int i = 0; i < _keyFill.Length; i++)
            {
                char letter = (char)('A' + i);
                Color fill = KeyFill;
                Color text = Color.white;
                if (used != null && Has(used.Green, letter))
                {
                    fill = CorrectColor;
                }
                else if (used != null && Has(used.Yellow, letter))
                {
                    fill = PresentColor;
                }
                else if (used != null && Has(used.Gray, letter))
                {
                    fill = KeyAbsentFill;
                    text = KeyAbsentLetter;
                }

                if (_keyFill[i].color != fill)
                {
                    _keyFill[i].color = fill;
                    _keyLetter[i].color = text;
                    GameAnim.Pulse(_keyFill[i].rectTransform, 0.16f, 0.3f);
                }
            }
        }

        // ------------------------------------------------------------------
        // Terminar y limpiar
        // ------------------------------------------------------------------

        /// <summary>Corta lo que se anima y deja puesto el último estado (con el final, si lo hubo).</summary>
        private void FinishNow(bool won)
        {
            StopRunning();
            if (_last == null || _tiles == null)
            {
                return;
            }

            List<WordleRowData> board = _last.Board ?? new List<WordleRowData>();
            for (int r = 0; r < board.Count && r < _rows; r++)
            {
                PaintRowFinal(r, board[r].Letters, board[r].Marks);
            }

            ApplyUsed(_last.Used);
            if (_last.Result == GameResults.Win || _last.Result == GameResults.Lose)
            {
                ShowWord(_last, _last.Result == GameResults.Win);
                if (won && !_celebrated)
                {
                    Celebrate(_last);
                }
            }
            else if (!string.IsNullOrEmpty(_last.Hint) && !_hintShown)
            {
                ShowHint(_last.Hint);
            }
        }

        private void StopRunning()
        {
            StopAllCoroutines();
            _revealing = 0;
            _invalidRoutine = null;
            _bannerUntil = 0f;
            if (Hud != null)
            {
                Hud.HideBanner();
            }

            if (_tiles != null)
            {
                // Con las medidas de lo montado (las de la partida nueva aún pueden no serlo).
                int rows = _tiles.GetLength(0);
                int cols = _tiles.GetLength(1);
                for (int r = 0; r < rows; r++)
                {
                    GameAnim.Stop(_rowRects[r]);
                    for (int c = 0; c < cols; c++)
                    {
                        GameAnim.Stop(_tiles[r, c].Rect);
                    }
                }
            }
        }

        // ------------------------------------------------------------------
        // Fichas
        // ------------------------------------------------------------------

        private void PaintEmpty(Tile tile)
        {
            tile.Letter.text = string.Empty;
            tile.Letter.color = Color.white;
            tile.Fill.color = EmptyFill;
            tile.Border.color = EmptyBorder;
        }

        /// <summary>Una letra puesta, sin evaluar todavía (con el borde en rojo si la palabra no vale).</summary>
        private void PaintTyped(Tile tile, char letter, bool invalid)
        {
            tile.Letter.text = letter == ' ' ? string.Empty : letter.ToString();
            tile.Letter.color = Color.white;
            tile.Fill.color = TypedFill;
            tile.Border.color = invalid ? GameColors.Red : TypedBorder;
        }

        private void PaintMarked(Tile tile, char mark)
        {
            Color color = mark == 'g' ? CorrectColor : mark == 'y' ? PresentColor : AbsentColor;
            tile.Fill.color = color;
            tile.Border.color = Lighten(color);
            tile.Letter.color = Color.white;
        }

        /// <summary>Una fila entera ya evaluada, sin animación (la que no se había visto, o al saltarse el volteo).</summary>
        private void PaintRowFinal(int row, string letters, string marks)
        {
            string clean = Clean(letters);
            string safeMarks = marks ?? string.Empty;
            for (int c = 0; c < _cols; c++)
            {
                Tile tile = _tiles[row, c];
                GameAnim.Stop(tile.Rect);
                tile.Letter.text = c < clean.Length ? clean[c].ToString() : string.Empty;
                PaintMarked(tile, c < safeMarks.Length ? safeMarks[c] : 'x');
            }

            _rowTaken[row] = true;
            _rowDone[row] = true;
        }

        private static Color Lighten(Color color)
        {
            return Color.Lerp(color, Color.white, 0.22f);
        }

        // ------------------------------------------------------------------
        // Construcción
        // ------------------------------------------------------------------

        private void Build()
        {
            RectTransform content = Content;
            if (_root == null)
            {
                _root = Hud.NewRect("Wordle", content);
                GameUi.Stretch(_root);
            }

            for (int i = _root.childCount - 1; i >= 0; i--)
            {
                GameObject old = _root.GetChild(i).gameObject;
                old.SetActive(false);
                Destroy(old);
            }

            _tile = Mathf.Min(MaxTile, Mathf.Floor((GridMaxHeight - ((_rows - 1) * TileGap)) / _rows));
            float gridW = (_cols * _tile) + ((_cols - 1) * TileGap);
            float gridH = (_rows * _tile) + ((_rows - 1) * TileGap);
            float keysH = (4f * KeySize) + (3f * KeyGap);
            float keyBlock = KeyLabelHeight + 8f + keysH;
            _contentHeight = Mathf.Max(gridH, MinInfoHeight + InfoGap + keyBlock);
            float rightW = Mathf.Max(260f, Hud.ContentWidth - gridW - ColumnGap);
            float infoH = _contentHeight - keyBlock - InfoGap;

            BuildGrid(gridW, gridH);
            _right = Hud.NewRect("Derecha", _root);
            Place(_right, new Vector2(1f, 1f), new Vector2(1f, 1f), Vector2.zero, new Vector2(rightW, _contentHeight));
            BuildInfo(rightW, infoH);
            BuildKeys(rightW, infoH + InfoGap);
            _builtRows = _rows;
            _builtCols = _cols;
            _builtHintAfter = _hintAfter;
        }

        /// <summary>Deja lo ya montado como al empezar: fichas vacías, letras sin usar y la pista candada.</summary>
        private void ResetBoard()
        {
            for (int r = 0; r < _rows; r++)
            {
                _rowTaken[r] = false;
                _rowDone[r] = false;
                _rowRects[r].anchoredPosition = new Vector2(0f, -r * (_tile + TileGap));
                _rowRects[r].localScale = Vector3.one;
                for (int c = 0; c < _cols; c++)
                {
                    Tile tile = _tiles[r, c];
                    tile.Rect.anchoredPosition = new Vector2(c * (_tile + TileGap), 0f);
                    tile.Rect.localScale = Vector3.one;
                    PaintEmpty(tile);
                }
            }

            for (int i = 0; i < _keyFill.Length; i++)
            {
                _keyFill[i].color = KeyFill;
                _keyFill[i].rectTransform.localScale = Vector3.one;
                _keyLetter[i].color = Color.white;
            }

            _infoLabel.text = "PISTA";
            _infoLabel.color = GameColors.Muted;
            _lockedText.text = LockedLabel(0);
            _hintBody.text = string.Empty;
            _revealHint.text = string.Empty;
            _hintRoot.localScale = Vector3.one;
            _lockedRoot.gameObject.SetActive(true);
            _hintRoot.gameObject.SetActive(false);
            _revealRoot.gameObject.SetActive(false);
            for (int c = 0; c < _wordTiles.Length; c++)
            {
                _wordTiles[c].Rect.localScale = Vector3.one;
            }
        }

        private void BuildGrid(float gridW, float gridH)
        {
            RectTransform grid = Hud.NewRect("Rejilla", _root);
            float top = -((_contentHeight - gridH) * 0.5f);
            Place(grid, new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(0f, top), new Vector2(gridW, gridH));
            _tiles = new Tile[_rows, _cols];
            _rowRects = new RectTransform[_rows];
            _rowTaken = new bool[_rows];
            _rowDone = new bool[_rows];
            for (int r = 0; r < _rows; r++)
            {
                RectTransform row = Hud.NewRect("Fila" + (r + 1), grid);
                Place(row, new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(0f, -r * (_tile + TileGap)), new Vector2(gridW, _tile));
                _rowRects[r] = row;
                for (int c = 0; c < _cols; c++)
                {
                    Tile tile = NewTile(row, _tile, 16f, _tile * 0.62f);
                    Place(tile.Rect, new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(c * (_tile + TileGap), 0f), new Vector2(_tile, _tile));
                    PaintEmpty(tile);
                    _tiles[r, c] = tile;
                }
            }
        }

        /// <summary>Una ficha: el borde, el fondo algo metido y la letra.</summary>
        private Tile NewTile(Transform parent, float size, float radius, float fontSize)
        {
            Tile tile = new Tile();
            tile.Rect = Hud.NewRect("Ficha", parent);
            tile.Rect.sizeDelta = new Vector2(size, size);
            tile.Border = Hud.NewRound("Borde", tile.Rect, EmptyBorder, radius);
            GameUi.Stretch(tile.Border.rectTransform);
            tile.Fill = Hud.NewRound("Fondo", tile.Rect, EmptyFill, radius - BorderWidth);
            GameUi.Stretch(tile.Fill.rectTransform);
            tile.Fill.rectTransform.offsetMin = new Vector2(BorderWidth, BorderWidth);
            tile.Fill.rectTransform.offsetMax = new Vector2(-BorderWidth, -BorderWidth);
            tile.Letter = Hud.NewText("Letra", tile.Rect, string.Empty, fontSize, Color.white, TextAlignmentOptions.Center, Hud.DisplayFont);
            tile.Letter.textWrappingMode = TextWrappingModes.NoWrap;
            GameUi.Stretch(tile.Letter.rectTransform);
            return tile;
        }

        private void BuildInfo(float width, float height)
        {
            Image border = Hud.NewRound("Pista", _right, GameColors.CardBorder, 28f);
            _info = border.rectTransform;
            Place(_info, new Vector2(0f, 1f), new Vector2(0f, 1f), Vector2.zero, new Vector2(width, height));
            Image fill = Hud.NewRound("Fondo", _info, GameColors.OptionFill, 25f);
            GameUi.Stretch(fill.rectTransform);
            fill.rectTransform.offsetMin = new Vector2(BorderWidth, BorderWidth);
            fill.rectTransform.offsetMax = new Vector2(-BorderWidth, -BorderWidth);

            _infoLabel = Hud.NewText("Etiqueta", _info, "PISTA", 25f, GameColors.Muted, TextAlignmentOptions.Left, Hud.MonoFont);
            _infoLabel.characterSpacing = 6f;
            _infoLabel.textWrappingMode = TextWrappingModes.NoWrap;
            Place(_infoLabel.rectTransform, new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(InfoPadding, -20f), new Vector2(width - (2f * InfoPadding), 32f));

            float bodyTop = 66f;
            float inner = width - (2f * InfoPadding);

            // Candada: un signo de pregunta y cuándo sale.
            _lockedRoot = Hud.NewRect("Candada", _info);
            Place(_lockedRoot, new Vector2(0f, 0f), new Vector2(0f, 0f), new Vector2(InfoPadding, 18f), new Vector2(inner, height - bodyTop - 18f));
            TextMeshProUGUI mark = Hud.NewText("Interrogante", _lockedRoot, "?", 130f, GameUi.WithAlpha(GameColors.Yellow, 0.9f), TextAlignmentOptions.Center, Hud.DisplayFont);
            Place(mark.rectTransform, new Vector2(0.5f, 1f), new Vector2(0.5f, 1f), new Vector2(0f, 6f), new Vector2(inner, 150f));
            _lockedText = Hud.NewText("Cuando", _lockedRoot, string.Empty, 24f, GameColors.Muted, TextAlignmentOptions.Center, Hud.BodyFont);
            _lockedText.characterSpacing = 3f;
            Place(_lockedText.rectTransform, new Vector2(0.5f, 0f), new Vector2(0.5f, 0f), Vector2.zero, new Vector2(inner, 64f));
            _lockedText.text = LockedLabel(0);

            // La pista.
            _hintRoot = Hud.NewRect("Texto", _info);
            Place(_hintRoot, new Vector2(0f, 0f), new Vector2(0f, 0f), new Vector2(InfoPadding, 20f), new Vector2(inner, height - bodyTop - 20f));
            _hintBody = Hud.NewText("Pista", _hintRoot, string.Empty, 32f, Color.white, TextAlignmentOptions.TopLeft, Hud.BodyFont);
            GameUi.Stretch(_hintBody.rectTransform);
            _hintBody.enableAutoSizing = true;
            _hintBody.fontSizeMin = 20f;
            _hintBody.fontSizeMax = 34f;
            _hintRoot.gameObject.SetActive(false);

            // La palabra al terminar: sus fichas y la pista.
            _revealRoot = Hud.NewRect("Palabra", _info);
            Place(_revealRoot, new Vector2(0f, 0f), new Vector2(0f, 0f), new Vector2(InfoPadding, 20f), new Vector2(inner, height - bodyTop - 20f));
            float small = Mathf.Min(58f, (inner - ((_cols - 1) * 8f)) / _cols);
            _wordTiles = new Tile[_cols];
            for (int c = 0; c < _cols; c++)
            {
                Tile tile = NewTile(_revealRoot, small, 14f, small * 0.62f);
                Place(tile.Rect, new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(c * (small + 8f), 0f), new Vector2(small, small));
                tile.Fill.color = CorrectColor;
                _wordTiles[c] = tile;
            }

            _revealHint = Hud.NewText("Dato", _revealRoot, string.Empty, 26f, GameColors.Muted, TextAlignmentOptions.TopLeft, Hud.BodyFont);
            Place(_revealHint.rectTransform, new Vector2(0f, 0f), new Vector2(0f, 0f), Vector2.zero, new Vector2(inner, _revealRoot.sizeDelta.y - small - 14f));
            _revealHint.enableAutoSizing = true;
            _revealHint.fontSizeMin = 18f;
            _revealHint.fontSizeMax = 28f;
            _revealRoot.gameObject.SetActive(false);
        }

        /// <summary>Las 26 letras en cuatro filas de siete, bajo la pista.</summary>
        private void BuildKeys(float width, float top)
        {
            TextMeshProUGUI label = Hud.NewText("Etiqueta", _right, "LETRAS", 25f, GameColors.Muted, TextAlignmentOptions.Left, Hud.MonoFont);
            label.characterSpacing = 6f;
            label.textWrappingMode = TextWrappingModes.NoWrap;
            Place(label.rectTransform, new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(6f, -top), new Vector2(width - 12f, KeyLabelHeight));

            float keysW = (KeyColumns * KeySize) + ((KeyColumns - 1) * KeyGap);
            RectTransform keys = Hud.NewRect("Teclas", _right);
            float keysTop = top + KeyLabelHeight + 8f;
            Place(keys, new Vector2(0.5f, 1f), new Vector2(0.5f, 1f), new Vector2(0f, -keysTop), new Vector2(keysW, (4f * KeySize) + (3f * KeyGap)));
            _keyFill = new Image[26];
            _keyLetter = new TextMeshProUGUI[26];
            for (int i = 0; i < 26; i++)
            {
                int row = i / KeyColumns;
                int column = i % KeyColumns;
                // La última fila (cinco letras) va centrada.
                float inset = row == 3 ? ((KeyColumns - 5) * 0.5f) * (KeySize + KeyGap) : 0f;
                Image key = Hud.NewRound("Tecla" + (char)('A' + i), keys, KeyFill, 11f);
                Place(key.rectTransform, new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(inset + (column * (KeySize + KeyGap)), -row * (KeySize + KeyGap)), new Vector2(KeySize, KeySize));
                TextMeshProUGUI letter = Hud.NewText("Letra", key.rectTransform, ((char)('A' + i)).ToString(), 27f, Color.white, TextAlignmentOptions.Center, Hud.DisplayFont);
                letter.textWrappingMode = TextWrappingModes.NoWrap;
                GameUi.Stretch(letter.rectTransform);
                _keyFill[i] = key;
                _keyLetter[i] = letter;
            }
        }

        private static void Place(RectTransform rect, Vector2 anchor, Vector2 pivot, Vector2 position, Vector2 size)
        {
            rect.anchorMin = anchor;
            rect.anchorMax = anchor;
            rect.pivot = pivot;
            rect.anchoredPosition = position;
            rect.sizeDelta = size;
        }

        // ------------------------------------------------------------------
        // Texto
        // ------------------------------------------------------------------

        /// <summary>Mayúsculas y solo A-Z (lo que llega del orquestador ya viene así; por si acaso).</summary>
        private static string Clean(string text)
        {
            if (string.IsNullOrEmpty(text))
            {
                return string.Empty;
            }

            char[] chars = new char[text.Length];
            int count = 0;
            for (int i = 0; i < text.Length; i++)
            {
                char c = char.ToUpperInvariant(text[i]);
                if (c >= 'A' && c <= 'Z')
                {
                    chars[count++] = c;
                }
            }

            return new string(chars, 0, count);
        }

        private static bool Has(string letters, char letter)
        {
            return !string.IsNullOrEmpty(letters) && letters.IndexOf(letter) >= 0;
        }

        private static int CountMarks(string marks, char mark)
        {
            int count = 0;
            if (!string.IsNullOrEmpty(marks))
            {
                for (int i = 0; i < marks.Length; i++)
                {
                    if (marks[i] == mark)
                    {
                        count++;
                    }
                }
            }

            return count;
        }
    }
}
