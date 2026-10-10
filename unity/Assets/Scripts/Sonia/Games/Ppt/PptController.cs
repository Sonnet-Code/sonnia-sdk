// Piedra, papel o tijera (docs/juegos/piedra_papel_tijera.md): la pantalla en Unity.
//
// El orquestador lleva la partida (elige la jugada de Sonnia antes de mirar, lee
// la mano del jugador con la cámara y cuenta los puntos); aquí solo se pinta:
//
//  - La vista en vivo arriba (la manda el orquestador, con el jugador resaltado)
//    y, debajo, la tarjeta: el marcador «SONNIA 1 – 2 TÚ» y una fila con las dos
//    jugadas en grande, que durante la cuenta enseña «PIEDRA», «PAPEL»,
//    «TIJERA» y «¡YA!» al ritmo de los golpes del puño.
//  - La mano de Sonnia (SoniaHandPoser): sube el puño con «ready», lo agita con
//    «countdown» al ritmo de la frase grabada «¡Piedra, papel o tijera… ya!» y
//    en el «¡ya!» enseña su jugada. El «¡ya!» sale del audio de la frase que
//    está sonando (AudioStreamPlayer), así que la mano se abre a la vez que la
//    voz; si no hay audio (o no se sabe dónde cae), con el reloj o con «go».
//  - El resultado de cada ronda (rótulo y las dos jugadas) y el final.
//
// Plan B (SoniaHandEnabled = false): sin brazo ni dedos; la jugada de Sonnia solo
// sale en la tarjeta.
//
// Eventos (orquestador → Unity, docs/protocolo.md): start, round, ready,
// countdown, go, abort, result, final y hint. Unity no manda nada.

using System;
using Newtonsoft.Json;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia.Games.Ppt
{
    /// <summary>Pantalla de «Piedra, papel o tijera» (id <c>piedra_papel_tijera</c>).</summary>
    public class PptController : GameControllerBase
    {
        /// <summary>Id del juego en el protocolo.</summary>
        public const string GameId = "piedra_papel_tijera";

        /// <summary>
        /// Plan B: con false, Sonnia no saca la mano con el avatar y su jugada solo sale en
        /// la tarjeta (por si los dedos no quedan bien en algún avatar).
        /// </summary>
        public static readonly bool SoniaHandEnabled = true;

        // Alto del contenido de la tarjeta: marcador y fila de jugadas.
        private const float ContentHeight = 292f;

        // Retraso esperado entre que llega «countdown» y que suena la frase (si no se oye el audio).
        private const float FallbackAudioLag = 0.12f;

        // Tiempo que se espera al audio de la frase antes de contar con el reloj.
        private const float AudioWait = 0.35f;

        // Si «go» llega y la mano no se ha abierto en este tiempo, se abre.
        private const float GoSafety = 0.4f;

        // Si el audio de la frase no avanza en este tiempo, se cuenta con el reloj.
        private const float AudioStall = 0.3f;

        // El final espera a que el resultado de la última ronda se vea este tiempo.
        private const float FinalDelay = 1.5f;

        // La mano baja sola este tiempo después de enseñar el resultado.
        private const float LowerAfterResult = 2.4f;

        private sealed class ScoreData
        {
            [JsonProperty("sonnia")] public int Sonnia;
            [JsonProperty("player")] public int Player;
        }

        private sealed class StartData
        {
            [JsonProperty("rounds")] public int Rounds;
            [JsonProperty("target")] public int Target;
            [JsonProperty("round")] public int Round;
            [JsonProperty("score")] public ScoreData Score;
        }

        private sealed class RoundData
        {
            [JsonProperty("round")] public int Round;
            [JsonProperty("retry")] public bool Retry;
            [JsonProperty("rounds")] public int Rounds;
            [JsonProperty("target")] public int Target;
            [JsonProperty("score")] public ScoreData Score;
        }

        private sealed class CountdownData
        {
            [JsonProperty("round")] public int Round;
            [JsonProperty("sonnia")] public string Sonnia;
            [JsonProperty("go_s")] public float? GoSeconds;
            [JsonProperty("beats")] public int Beats;
        }

        private sealed class MoveData
        {
            [JsonProperty("round")] public int Round;
            [JsonProperty("sonnia")] public string Sonnia;
        }

        private sealed class ResultData
        {
            [JsonProperty("round")] public int Round;
            [JsonProperty("sonnia")] public string Sonnia;
            [JsonProperty("player")] public string Player;
            [JsonProperty("winner")] public string Winner;
            [JsonProperty("reason")] public string Reason;
            [JsonProperty("retry")] public bool Retry;
            [JsonProperty("rounds")] public int Rounds;
            [JsonProperty("target")] public int Target;
            [JsonProperty("score")] public ScoreData Score;
        }

        private sealed class FinalData
        {
            [JsonProperty("winner")] public string Winner;
            [JsonProperty("score")] public ScoreData Score;
            [JsonProperty("rounds")] public int Rounds;
            [JsonProperty("sonnia")] public string Sonnia;
            [JsonProperty("player")] public string Player;
            [JsonProperty("contact")] public string Contact;
        }

        private sealed class HintData
        {
            [JsonProperty("text")] public string Text;
        }

        /// <summary>Una ficha de jugada: etiqueta (SONNIA o TÚ) y la jugada en grande.</summary>
        private sealed class MoveChip
        {
            public RectTransform Rect;
            public Image Fill;
            public Image Glow;
            public TextMeshProUGUI Label;
            public TextMeshProUGUI Move;
        }

        private SoniaHandPoser _hand;
        private AudioStreamPlayer _audio;

        // Pantalla (se monta una vez).
        private RectTransform _board;
        private TextMeshProUGUI _sonniaScore;
        private TextMeshProUGUI _playerScore;
        private TextMeshProUGUI _dash;
        private MoveChip _sonniaChip;
        private MoveChip _playerChip;
        private TextMeshProUGUI _versus;
        private TextMeshProUGUI _beat;

        // Partida.
        private int _rounds = 3;
        private int _round = 1;
        private int _scoreSonnia;
        private int _scorePlayer;

        // Cuenta en curso.
        private bool _counting;
        private int _countRound = -1;
        private float _countAt = -1f;
        private float _go = -1f;
        private int _beats = 3;
        private int _baseUtterance = -1;
        private int _phraseUtterance = -1;
        private bool _audioLocked;
        private float _lastHeard;
        private float _lastHeardAt;
        private float _heardRaw = -1f;
        private float _heardRawAt;
        private int _clockMode = -1;
        private float _clockOffset;
        private float _lastClock;
        private int _beatShown = -1;
        private float _goAt = -1f;
        private bool _revealed;
        private PptHand _sonniaMove = PptHand.Rock;

        // Resultado y final.
        private float _resultAt = -10f;
        private float _lowerAt = -1f;
        private FinalData _pendingFinal;
        private float _finalAt = -1f;

        /// <summary>La mano de Sonnia (para pruebas).</summary>
        public SoniaHandPoser Hand
        {
            get { return _hand; }
        }

        public override string Id
        {
            get { return GameId; }
        }

        protected override string DefaultTitle
        {
            get { return "Piedra, papel o tijera"; }
        }

        protected override void Awake()
        {
            base.Awake();
            _audio = GetComponentInChildren<AudioStreamPlayer>(true);
            if (SoniaHandEnabled)
            {
                _hand = GetComponent<SoniaHandPoser>();
                if (_hand == null)
                {
                    _hand = gameObject.AddComponent<SoniaHandPoser>();
                }
            }
        }

        // ------------------------------------------------------------------
        // Eventos
        // ------------------------------------------------------------------

        protected override void OnStart(string dataJson)
        {
            StartData data = ParseData<StartData>(dataJson);
            BuildOnce();
            ResetBoard();
            _rounds = data.Rounds > 0 ? data.Rounds : 3;
            _round = Mathf.Max(1, data.Round);
            ApplyScore(data.Score, false);
            SetRoundCaption(false);
            if (Hud != null)
            {
                Hud.SetContentHeight(Id, ContentHeight);
                Hud.RefreshLayout();
            }
        }

        protected override void OnGameEvent(string eventName, string dataJson)
        {
            switch (eventName)
            {
                case "round":
                    HandleRound(ParseData<RoundData>(dataJson));
                    break;
                case "ready":
                    HandleReady();
                    break;
                case "countdown":
                    HandleCountdown(ParseData<CountdownData>(dataJson));
                    break;
                case "go":
                    HandleGo(ParseData<MoveData>(dataJson));
                    break;
                case "abort":
                    HandleAbort();
                    break;
                case "result":
                    HandleResult(ParseData<ResultData>(dataJson));
                    break;
                case "final":
                    HandleFinal(ParseData<FinalData>(dataJson));
                    break;
                case "hint":
                    HandleHint(ParseData<HintData>(dataJson));
                    break;
                default:
                    Log("evento desconocido: " + eventName);
                    break;
            }
        }

        protected override void OnFinish(string result, string dataJson)
        {
            StopCount();
            if (_pendingFinal != null)
            {
                // El end llegó antes de enseñar el final: se enseña ya.
                ShowFinal(_pendingFinal);
            }

            if (_hand != null)
            {
                _hand.Lower();
            }
        }

        protected override void ShowDefaultResult(string result, string dataJson)
        {
            // Sin final propio (un orquestador sin «final»): el genérico con el marcador.
            string score = "Sonnia " + _scoreSonnia + " - " + _scorePlayer + " Tú";
            if (result == GameResults.Win)
            {
                Hud.ShowResult("¡GANASTE!", score, "¡Le ganaste a Sonnia!", true);
            }
            else
            {
                Hud.ShowResult("¡GANA SONNIA!", score, "¡Pídeme la revancha!", false);
            }
        }

        protected override void OnClosed()
        {
            StopCount();
            _pendingFinal = null;
            _finalAt = -1f;
            _lowerAt = -1f;
            _countRound = -1;
            if (_hand != null)
            {
                // Baja con su fundido: si la pantalla se cierra con la mano arriba, no salta.
                _hand.Lower();
            }

            ResetBoard();
        }

        private void HandleRound(RoundData data)
        {
            StopCount();
            _round = Mathf.Max(1, data.Round);
            if (data.Rounds > 0)
            {
                _rounds = data.Rounds;
            }

            ApplyScore(data.Score, false);
            SetRoundCaption(data.Retry);
            ClearMoves();
            ShowBeat(data.Retry ? "¡OTRA VEZ!" : "¿LISTOS?", GameColors.Muted, false);
            if (Hud != null)
            {
                Hud.HideBanner();
                Hud.PopCard();
            }
        }

        private void HandleReady()
        {
            _lowerAt = -1f;
            if (_hand != null)
            {
                _hand.Raise();
            }
        }

        private void HandleCountdown(CountdownData data)
        {
            _sonniaMove = ParseMove(data.Sonnia, PptHand.Rock);
            _counting = true;
            _revealed = false;
            _countRound = data.Round;
            _countAt = Time.time;
            _go = data.GoSeconds.HasValue && data.GoSeconds.Value > 0.2f ? data.GoSeconds.Value : -1f;
            _beats = data.Beats > 0 ? data.Beats : 3;
            _beatShown = -1;
            _goAt = -1f;
            _phraseUtterance = -1;
            _audioLocked = false;
            _heardRaw = -1f;
            _heardRawAt = Time.time;
            _clockMode = -1;
            _clockOffset = 0f;
            _lastClock = 0f;
            _lowerAt = -1f;
            int id;
            float seconds;
            float rms;
            _baseUtterance = -1;
            if (_audio != null)
            {
                _audio.GetPlaybackPosition(out id, out seconds, out rms);
                _baseUtterance = id;
            }

            ClearMoves();
            if (Hud != null)
            {
                Hud.HideBanner();
            }

            if (_hand != null)
            {
                _hand.BeginCount(_sonniaMove, _go, CountClock);
            }

            Log("cuenta: Sonnia saca " + _sonniaMove + (_go > 0f ? ", «ya» a " + _go.ToString("0.00") + " s" : ", «ya» con go"));
        }

        private void HandleGo(MoveData data)
        {
            if (!string.IsNullOrEmpty(data.Sonnia))
            {
                _sonniaMove = ParseMove(data.Sonnia, _sonniaMove);
                if (_hand != null && !_hand.IsRevealed)
                {
                    _hand.Prepare(_sonniaMove);
                }
            }

            if (!_counting)
            {
                return;
            }

            if (_go <= 0f)
            {
                Reveal();
            }
            else if (_goAt < 0f)
            {
                // Red de seguridad: si el audio no la abre enseguida, se abre igual.
                _goAt = Time.time;
            }
        }

        private void HandleAbort()
        {
            StopCount();
            ShowBeat(string.Empty, GameColors.Muted, false);
            if (_hand != null)
            {
                _hand.Lower();
            }
        }

        private void HandleResult(ResultData data)
        {
            bool sameCount = data.Round == _countRound;
            if (_counting && !_revealed)
            {
                Reveal();
            }

            StopCount();
            _round = Mathf.Max(1, data.Round);
            if (data.Rounds > 0)
            {
                _rounds = data.Rounds;
            }

            PptHand sonnia = ParseMove(data.Sonnia, _sonniaMove);
            bool hasPlayer = !string.IsNullOrEmpty(data.Player);
            PptHand player = ParseMove(data.Player, PptHand.Rock);
            string winner = data.Winner ?? "none";
            ShowMoves(sonnia, hasPlayer ? (PptHand?)player : null, winner);
            ApplyScore(data.Score, true);
            _resultAt = Time.time;

            Color color;
            string banner;
            switch (winner)
            {
                case "player":
                    banner = "¡GANAS TÚ!";
                    color = GameColors.Green;
                    ShowEmotion(FacialExpressionController.Emotion.Surprise, 1.6f);
                    if (Hud != null && _playerChip != null)
                    {
                        Hud.BurstFrom(_playerChip.Rect, 40, 1000f);
                    }

                    break;
                case "sonnia":
                    banner = "¡GANA SONNIA!";
                    color = GameColors.Blue;
                    ShowEmotion(FacialExpressionController.Emotion.Joy, 2f);
                    break;
                case "tie":
                    banner = "¡EMPATE!";
                    color = GameColors.Yellow;
                    ShowEmotion(FacialExpressionController.Emotion.Surprise, 1.2f);
                    break;
                default:
                    banner = data.Reason == "unclear" ? "¡NO TE ENTENDÍ LA MANO!" : "¡NO TE VI LA MANO!";
                    color = GameColors.Red;
                    break;
            }

            if (Hud != null)
            {
                Hud.ShowBanner(banner, color);
            }

            // La mano de Sonnia se queda enseñando su jugada un rato y baja sola.
            if (_hand != null && sameCount)
            {
                if (!_hand.IsRevealed)
                {
                    _hand.Show(sonnia);
                }

                _lowerAt = Time.time + LowerAfterResult;
            }
        }

        private void HandleFinal(FinalData data)
        {
            if (data.Score != null)
            {
                ApplyScore(data.Score, false);
            }

            // Si el resultado de la última ronda acaba de salir, que se vea antes del final.
            float wait = (_resultAt + FinalDelay) - Time.time;
            if (wait > 0f)
            {
                _pendingFinal = data;
                _finalAt = Time.time + wait;
                return;
            }

            ShowFinal(data);
        }

        private void HandleHint(HintData data)
        {
            if (Hud != null && !string.IsNullOrEmpty(data.Text))
            {
                Hud.ShowBanner(GameUi.Plain(data.Text), GameColors.Blue);
            }
        }

        private void ShowFinal(FinalData data)
        {
            _pendingFinal = null;
            _finalAt = -1f;
            if (Hud == null)
            {
                return;
            }

            string score = "Sonnia " + _scoreSonnia + " - " + _scorePlayer + " Tú";
            string contact = string.IsNullOrEmpty(data.Contact) ? "el equipo del stand" : GameUi.Plain(data.Contact);
            switch (data.Winner)
            {
                case "player":
                    Hud.ShowResult("¡GANASTE!", score, "Pasa a ver a " + contact + " del equipo", true);
                    ShowEmotion(FacialExpressionController.Emotion.Joy, 3f);
                    break;
                case "tie":
                    Hud.ShowResult("¡EMPATE!", score, "¡Pídeme la revancha!", false);
                    break;
                default:
                    Hud.ShowResult("¡GANA SONNIA!", score, "¡Pídeme la revancha!", false);
                    ShowEmotion(FacialExpressionController.Emotion.Joy, 3f);
                    break;
            }

            if (_hand != null && _lowerAt < 0f)
            {
                _lowerAt = Time.time + 0.8f;
            }
        }

        // ------------------------------------------------------------------
        // Cada fotograma
        // ------------------------------------------------------------------

        private void Update()
        {
            if (!IsActive)
            {
                return;
            }

            if (_counting)
            {
                UpdateCount();
            }

            if (_lowerAt > 0f && Time.time >= _lowerAt)
            {
                _lowerAt = -1f;
                if (_hand != null)
                {
                    _hand.Lower();
                }
            }

            if (_pendingFinal != null && Time.time >= _finalAt)
            {
                ShowFinal(_pendingFinal);
            }
        }

        private void UpdateCount()
        {
            float t = CountClock();
            if (_go > 0f)
            {
                float beat = _go / 4f;
                int index = Mathf.Clamp(Mathf.FloorToInt((t / beat) + 0.001f), 0, 4);
                if (index != _beatShown && index >= 1)
                {
                    ShowCountWord(index);
                }

                bool handOpen = _hand != null && _hand.IsRevealed;
                if (!_revealed && (t >= _go || handOpen || (_goAt > 0f && Time.time - _goAt >= GoSafety)))
                {
                    Reveal();
                }
            }
            else
            {
                // Sin «ya» conocido: las palabras al ritmo del puño, hasta que llegue go.
                int index = Mathf.Clamp(Mathf.FloorToInt((Time.time - _countAt) / 0.42f), 0, 3);
                if (index != _beatShown && index >= 1)
                {
                    ShowCountWord(index);
                }
            }

            if (Time.time - _countAt > 12f)
            {
                // Nunca se quedó la cuenta a medias.
                StopCount();
            }
        }

        private void Reveal()
        {
            if (_revealed)
            {
                return;
            }

            _revealed = true;
            ShowCountWord(4);
            if (_hand != null)
            {
                _hand.Prepare(_sonniaMove);
                _hand.Reveal();
            }
        }

        private void StopCount()
        {
            _counting = false;
            _goAt = -1f;
        }

        /// <summary>
        /// Segundos de la frase que ya se han oído: del audio que suena si es la frase (la
        /// primera voz nueva tras «countdown»), si no del reloj desde que llegó el mensaje.
        /// Al cambiar de fuente se funde la diferencia para que el puño no salte.
        /// </summary>
        private float CountClock()
        {
            float now = Time.time;
            int mode;
            float source;
            float heard;
            if (TryHeard(out heard))
            {
                mode = 1;
                source = heard;
            }
            else if (_audioLocked)
            {
                // La frase ya terminó (o hay un hueco): sigue al ritmo del reloj.
                mode = 2;
                source = _lastHeard + (now - _lastHeardAt);
            }
            else
            {
                mode = 0;
                float since = now - _countAt;
                source = since < AudioWait ? 0f : Mathf.Max(0f, since - FallbackAudioLag);
            }

            if (mode != _clockMode)
            {
                _clockOffset = _clockMode < 0 ? 0f : _lastClock - source;
                _clockMode = mode;
            }

            _clockOffset = Mathf.MoveTowards(_clockOffset, 0f, 1.5f * Time.deltaTime);
            _lastClock = Mathf.Max(0f, source + _clockOffset);
            return _lastClock;
        }

        private bool TryHeard(out float heard)
        {
            heard = 0f;
            if (_audio == null)
            {
                return false;
            }

            int id;
            float seconds;
            float rms;
            _audio.GetPlaybackPosition(out id, out seconds, out rms);
            if (id < 0 || id == _baseUtterance)
            {
                return false;
            }

            if (_phraseUtterance < 0)
            {
                if (Time.time - _countAt > 1.5f)
                {
                    return false;
                }

                _phraseUtterance = id;
            }

            if (id != _phraseUtterance)
            {
                return false;
            }

            // Si el audio no avanza (sin salida de sonido no corre su hilo), no sirve de reloj:
            // se sigue con el de la pared desde lo último que se oyó.
            if (!Mathf.Approximately(seconds, _heardRaw))
            {
                _heardRaw = seconds;
                _heardRawAt = Time.time;
            }
            else if (Time.time - _heardRawAt > AudioStall)
            {
                return false;
            }

            heard = Mathf.Max(0f, seconds - (_audio.LipSyncLeadMs / 1000f));
            _lastHeard = heard;
            _lastHeardAt = Time.time;
            _audioLocked = true;
            return true;
        }

        // ------------------------------------------------------------------
        // Pantalla
        // ------------------------------------------------------------------

        private void BuildOnce()
        {
            RectTransform content = Content;
            if (_board != null || content == null || Hud == null)
            {
                return;
            }

            _board = Hud.NewRect("Ppt", content);
            GameUi.Stretch(_board);

            // Marcador: SONNIA 1 – 2 TÚ.
            RectTransform scoreRow = Hud.NewRect("Marcador", _board);
            scoreRow.anchorMin = new Vector2(0f, 1f);
            scoreRow.anchorMax = new Vector2(1f, 1f);
            scoreRow.pivot = new Vector2(0.5f, 1f);
            scoreRow.sizeDelta = new Vector2(0f, 104f);
            scoreRow.anchoredPosition = new Vector2(0f, -4f);
            TextMeshProUGUI sonniaLabel = Hud.NewText("SonniaNombre", scoreRow, "SONNIA", 40f, GameColors.Muted, TextAlignmentOptions.Right);
            Place(sonniaLabel.rectTransform, new Vector2(0f, 0f), new Vector2(0.5f, 1f), new Vector2(0f, 0f), new Vector2(-150f, 0f));
            _sonniaScore = Hud.NewText("SonniaPuntos", scoreRow, "0", 92f, Color.white);
            Place(_sonniaScore.rectTransform, new Vector2(0.5f, 0f), new Vector2(0.5f, 1f), new Vector2(-140f, 0f), new Vector2(-50f, 0f));
            _dash = Hud.NewText("Guion", scoreRow, "–", 70f, GameColors.Muted);
            Place(_dash.rectTransform, new Vector2(0.5f, 0f), new Vector2(0.5f, 1f), new Vector2(-40f, 0f), new Vector2(40f, 0f));
            _playerScore = Hud.NewText("TuPuntos", scoreRow, "0", 92f, Color.white);
            Place(_playerScore.rectTransform, new Vector2(0.5f, 0f), new Vector2(0.5f, 1f), new Vector2(50f, 0f), new Vector2(140f, 0f));
            TextMeshProUGUI playerLabel = Hud.NewText("TuNombre", scoreRow, "TÚ", 40f, GameColors.Muted, TextAlignmentOptions.Left);
            Place(playerLabel.rectTransform, new Vector2(0.5f, 0f), new Vector2(1f, 1f), new Vector2(150f, 0f), new Vector2(0f, 0f));

            // Fila de jugadas: SONNIA y TÚ, con «contra» en medio, y la palabra de la cuenta encima.
            RectTransform movesRow = Hud.NewRect("Jugadas", _board);
            movesRow.anchorMin = new Vector2(0f, 0f);
            movesRow.anchorMax = new Vector2(1f, 0f);
            movesRow.pivot = new Vector2(0.5f, 0f);
            movesRow.sizeDelta = new Vector2(0f, 168f);
            movesRow.anchoredPosition = new Vector2(0f, 12f);
            _sonniaChip = NewChip("FichaSonnia", movesRow, "SONNIA", new Vector2(0f, 0f), new Vector2(0.43f, 1f));
            _playerChip = NewChip("FichaTu", movesRow, "TÚ", new Vector2(0.57f, 0f), new Vector2(1f, 1f));
            _versus = Hud.NewText("Contra", movesRow, "contra", 34f, GameColors.Muted);
            Place(_versus.rectTransform, new Vector2(0.43f, 0f), new Vector2(0.57f, 1f), Vector2.zero, Vector2.zero);
            _beat = Hud.NewText("Cuenta", movesRow, string.Empty, 104f, Color.white);
            GameUi.Stretch(_beat.rectTransform);
            _beat.textWrappingMode = TextWrappingModes.NoWrap;
        }

        private MoveChip NewChip(string name, RectTransform parent, string label, Vector2 anchorMin, Vector2 anchorMax)
        {
            MoveChip chip = new MoveChip();
            chip.Rect = Hud.NewRect(name, parent);
            Place(chip.Rect, anchorMin, anchorMax, Vector2.zero, Vector2.zero);
            chip.Glow = Hud.NewRound("Brillo", chip.Rect, GameUi.WithAlpha(GameColors.Green, 0f), 30f);
            GameUi.Stretch(chip.Glow.rectTransform);
            chip.Glow.rectTransform.offsetMin = new Vector2(-8f, -8f);
            chip.Glow.rectTransform.offsetMax = new Vector2(8f, 8f);
            chip.Fill = Hud.NewRound("Fondo", chip.Rect, GameColors.OptionFill, 26f);
            GameUi.Stretch(chip.Fill.rectTransform);
            chip.Label = Hud.NewText("Etiqueta", chip.Rect, label, 30f, GameColors.Muted);
            Place(chip.Label.rectTransform, new Vector2(0f, 0.62f), new Vector2(1f, 1f), new Vector2(10f, 0f), new Vector2(-10f, -6f));
            chip.Move = Hud.NewText("Jugada", chip.Rect, string.Empty, 62f, Color.white);
            Place(chip.Move.rectTransform, new Vector2(0f, 0f), new Vector2(1f, 0.68f), new Vector2(8f, 10f), new Vector2(-8f, 0f));
            chip.Move.textWrappingMode = TextWrappingModes.NoWrap;
            chip.Move.enableAutoSizing = true;
            chip.Move.fontSizeMin = 36f;
            chip.Move.fontSizeMax = 62f;
            return chip;
        }

        private static void Place(RectTransform rect, Vector2 anchorMin, Vector2 anchorMax, Vector2 offsetMin, Vector2 offsetMax)
        {
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.offsetMin = offsetMin;
            rect.offsetMax = offsetMax;
        }

        private void ResetBoard()
        {
            _scoreSonnia = 0;
            _scorePlayer = 0;
            _resultAt = -10f;
            if (_board == null)
            {
                return;
            }

            _sonniaScore.text = "0";
            _playerScore.text = "0";
            ClearMoves();
            ShowBeat(string.Empty, GameColors.Muted, false);
        }

        private void ApplyScore(ScoreData score, bool animate)
        {
            if (score == null || _board == null)
            {
                return;
            }

            bool sonniaUp = score.Sonnia > _scoreSonnia;
            bool playerUp = score.Player > _scorePlayer;
            _scoreSonnia = Mathf.Max(0, score.Sonnia);
            _scorePlayer = Mathf.Max(0, score.Player);
            _sonniaScore.text = _scoreSonnia.ToString();
            _playerScore.text = _scorePlayer.ToString();
            if (animate && sonniaUp)
            {
                GameAnim.Pulse(_sonniaScore.rectTransform, 0.3f, 0.45f);
            }

            if (animate && playerUp)
            {
                GameAnim.Pulse(_playerScore.rectTransform, 0.3f, 0.45f);
            }
        }

        private void SetRoundCaption(bool retry)
        {
            if (Hud == null)
            {
                return;
            }

            string caption = "AL MEJOR DE " + _rounds + " · RONDA " + _round;
            Hud.SetCaption(retry ? caption + " · OTRA VEZ" : caption);
        }

        private void ShowCountWord(int index)
        {
            _beatShown = index;
            switch (index)
            {
                case 1:
                    ShowBeat("PIEDRA", Color.white, true);
                    break;
                case 2:
                    ShowBeat("PAPEL", Color.white, true);
                    break;
                case 3:
                    ShowBeat("TIJERA", Color.white, true);
                    break;
                default:
                    ShowBeat("¡YA!", GameColors.Yellow, true);
                    break;
            }
        }

        private void ShowBeat(string text, Color color, bool pop)
        {
            if (_beat == null)
            {
                return;
            }

            _beat.text = text;
            _beat.color = color;
            _beat.gameObject.SetActive(!string.IsNullOrEmpty(text));
            SetChipsVisible(string.IsNullOrEmpty(text));
            if (pop && !string.IsNullOrEmpty(text))
            {
                GameAnim.Pop(_beat.rectTransform, 0.28f);
            }
        }

        private void ClearMoves()
        {
            if (_sonniaChip == null)
            {
                return;
            }

            PaintChip(_sonniaChip, "?", GameColors.OptionFill, GameColors.Muted, 0f);
            PaintChip(_playerChip, "?", GameColors.OptionFill, GameColors.Muted, 0f);
        }

        private void ShowMoves(PptHand sonnia, PptHand? player, string winner)
        {
            if (_sonniaChip == null)
            {
                return;
            }

            ShowBeat(string.Empty, GameColors.Muted, false);
            Color win = GameColors.RightFill;
            Color lose = new Color(0.16f, 0.2f, 0.3f, 0.96f);
            Color tie = new Color(0.55f, 0.42f, 0.05f, 1f);
            Color sonniaFill = winner == "sonnia" ? win : winner == "tie" ? tie : winner == "player" ? lose : GameColors.OptionFill;
            Color playerFill = winner == "player" ? win : winner == "tie" ? tie : winner == "sonnia" ? lose : GameColors.WrongFill;
            PaintChip(_sonniaChip, MoveName(sonnia), sonniaFill, winner == "player" ? GameColors.Muted : Color.white, winner == "sonnia" ? 0.6f : 0f);
            PaintChip(
                _playerChip,
                player.HasValue ? MoveName(player.Value) : "¿?",
                playerFill,
                winner == "sonnia" ? GameColors.Muted : Color.white,
                winner == "player" ? 0.6f : 0f);
            GameAnim.Pop(_sonniaChip.Rect, 0.35f);
            GameAnim.Pop(_playerChip.Rect, 0.35f, 0.08f);
        }

        private static void PaintChip(MoveChip chip, string move, Color fill, Color text, float glow)
        {
            chip.Move.text = move;
            chip.Move.color = text;
            chip.Fill.color = fill;
            chip.Glow.color = GameUi.WithAlpha(GameColors.Green, glow);
        }

        private void SetChipsVisible(bool visible)
        {
            if (_sonniaChip == null)
            {
                return;
            }

            _sonniaChip.Rect.gameObject.SetActive(visible);
            _playerChip.Rect.gameObject.SetActive(visible);
            _versus.gameObject.SetActive(visible);
        }

        private static string MoveName(PptHand move)
        {
            switch (move)
            {
                case PptHand.Paper:
                    return "PAPEL";
                case PptHand.Scissors:
                    return "TIJERA";
                default:
                    return "PIEDRA";
            }
        }

        private static PptHand ParseMove(string move, PptHand fallback)
        {
            switch (move)
            {
                case "piedra":
                    return PptHand.Rock;
                case "papel":
                    return PptHand.Paper;
                case "tijera":
                    return PptHand.Scissors;
                default:
                    return fallback;
            }
        }
    }
}
