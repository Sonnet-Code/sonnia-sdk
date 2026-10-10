// Lo común de pantalla de los juegos (docs/plan-juegos.md, 4.3), en el Canvas del
// HUD (SoniaHUD), construido por código como la trivia: sale en las capturas 9:16
// y en la build, sin prefabs.
//
// Diseño para el monitor vertical (1080x1920 de referencia), con el estilo de la
// trivia y del diseño F de la pantalla:
//  - La tarjeta va en la franja alta, la misma del panel de imágenes y de la
//    trivia, y la cámara pasa al plano de panel (algo más atrás) para que no tape
//    la cara de Sonnia. Los subtítulos de abajo quedan libres.
//  - Cabecera con el título del juego en los colores de Google, un rótulo corto a
//    su derecha («RONDA 2 DE 6») y un hueco a la derecha del todo para lo que
//    quiera el juego (puntos de progreso...). Debajo, el contenedor de cada juego.
//  - El contador circular cuelga de la esquina de arriba a la derecha de la
//    tarjeta (cada juego lo puede mover).
//  - El rótulo de acierto o fallo salta sobre el borde de abajo de la tarjeta y
//    la tarjeta del resultado final la sustituye, como en la trivia.
//  - Confeti y destellos copiados de la trivia (sin tocar TriviaController).
//  - Mientras hay juego en pantalla o vista en vivo, StageScreen aparta el QR y la
//    invitación a hablar (HoldsTopStrip).
//
// Cada juego tiene su propio contenedor dentro de la tarjeta (ContentOf) y su
// propia capa a pantalla completa (LayerOf): se construyen una vez y se
// reutilizan; Open activa los del juego que empieza y apaga los de los demás.

using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using Random = UnityEngine.Random;

namespace Sonia
{
    /// <summary>Tarjeta, contador, rótulos, confeti y plano de cámara comunes a los juegos.</summary>
    [DisallowMultipleComponent]
    public class GameHud : MonoBehaviour
    {
        [Header("Diseño (píxeles de la referencia 1080x1920)")]
        [SerializeField]
        [Tooltip("Ancho de la tarjeta de los juegos (el de la trivia).")]
        private float cardWidth = 960f;

        [SerializeField]
        [Range(0f, 0.5f)]
        [Tooltip("Distancia del borde superior de la tarjeta al de la pantalla, en fracción del alto.")]
        private float cardTop = 0.105f;

        [SerializeField]
        [Tooltip("Tamaño del título de la cabecera.")]
        private float titleSize = 40f;

        [SerializeField]
        [Tooltip("Diámetro del contador circular.")]
        private float countdownSize = 150f;

        [Header("Cámara (plano de panel automático)")]
        // Calibrado con capturas 1080x1920 (RunHudCheck, 10 de octubre de 2026): con
        // la tarjeta hasta 644 px, (0, 0,08, -0,2) deja la coronilla de Sonnia entre
        // 96 y 122 px por debajo; con la vista en vivo y la tarjeta hasta 1062 px,
        // (0, 0,55, -1,43) la deja a unos 100 px. Entre medias se interpola. El margen
        // es por la pose: el plano base sale de dónde está la cabeza cuando llega el
        // avatar y cambia de una vez a otra (CameraFramingController).
        [SerializeField]
        [Tooltip("Borde de abajo de lo de la franja alta (px desde arriba) con el que se calibra el plano corto.")]
        private float shortShotBottom = 644f;

        [SerializeField]
        [Tooltip("Desplazamiento de la cámara sobre el plano de panel (metros) cuando lo de arriba acaba en shortShotBottom.")]
        private Vector3 shortShotExtra = new Vector3(0f, 0.08f, -0.2f);

        [SerializeField]
        [Tooltip("Borde de abajo de lo de la franja alta (px desde arriba) con el que se calibra el plano largo (vista en vivo y tarjeta).")]
        private float tallShotBottom = 1062f;

        [SerializeField]
        [Tooltip("Desplazamiento de la cámara sobre el plano de panel (metros) cuando lo de arriba acaba en tallShotBottom.")]
        private Vector3 tallShotExtra = new Vector3(0f, 0.55f, -1.43f);

        [Header("Tiempos")]
        [SerializeField]
        [Range(0.1f, 2f)]
        [Tooltip("Segundos del fundido al retirar la pantalla del juego.")]
        private float closeFadeSeconds = 0.4f;

        [SerializeField]
        [Tooltip("Escribir en la consola lo que pasa en la pantalla de los juegos.")]
        private bool logEvents;

        /// <summary>Resolución de referencia de la pantalla vertical del stand.</summary>
        public const float ReferenceWidth = 1080f;

        public const float ReferenceHeight = 1920f;

        private const string HudCanvasName = "SoniaHUD";

        /// <summary>Radio con el que se genera <see cref="RoundSprite"/> (para otros radios, <see cref="NewRound"/>).</summary>
        public const int CornerRadius = 36;

        /// <summary>Segundos entre que se va la tarjeta y llega el resultado.</summary>
        private const float ResultDelay = 0.35f;

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

        private CameraFramingController _framing;
        private CameraPreviewPanel _preview;
        private StageScreen _stage;
        private Canvas _canvas;
        private bool _warnedNoCanvas;
        private float _waitStageUntil = -1f;

        // Kit.
        private TMP_FontAsset _display;
        private TMP_FontAsset _bodyFont;
        private TMP_FontAsset _mono;
        private TMP_FontAsset _fallback;
        private Sprite _roundSprite;
        private Sprite _frameSprite;
        private Sprite _glowSprite;
        private Sprite _dotSprite;
        private Sprite _ringSprite;
        private Sprite _checkSprite;
        private Sprite _crossSprite;
        private Sprite _sparkleSprite;
        private Sprite _starSprite;
        private Sprite _pieceSprite;
        private readonly List<Texture2D> _textures = new List<Texture2D>();
        private readonly List<Sprite> _sprites = new List<Sprite>();

        // Construcción.
        private RectTransform _root;
        private CanvasGroup _rootGroup;
        private RectTransform _card;
        private CanvasGroup _cardGroup;
        private RectTransform _body;
        private TextMeshProUGUI _title;
        private TextMeshProUGUI _caption;
        private RectTransform _headerRight;
        private RectTransform _banner;
        private Image _bannerFill;
        private TextMeshProUGUI _bannerText;
        private RectTransform _countdown;
        private CanvasGroup _countdownGroup;
        private Image _countdownArc;
        private TextMeshProUGUI _countdownNumber;
        private RectTransform _result;
        private CanvasGroup _resultGroup;
        private TextMeshProUGUI _resultEyebrow;
        private TextMeshProUGUI _resultTitle;
        private TextMeshProUGUI _resultScore;
        private TextMeshProUGUI _resultLine;
        private RectTransform _layers;
        private RectTransform _effects;
        private readonly Dictionary<string, RectTransform> _contents = new Dictionary<string, RectTransform>();
        private readonly Dictionary<string, RectTransform> _gameLayers = new Dictionary<string, RectTransform>();

        // Estado.
        private bool _open;
        private string _game = string.Empty;
        private string _gameTitle = string.Empty;
        // Plano de panel: lo pide el juego abierto (auto o con un desplazamiento
        // propio) o la vista en vivo; se aplica solo cuando cambia.
        private bool _panelWanted;
        private bool _panelCustom;
        private Vector3 _panelExtra;
        private bool _panelApplied;
        private Vector3 _appliedExtra;
        private float _reservedBottom;
        private bool _cardTopCustom;
        private float _clock;
        private float _rootAlpha;
        private bool _cardShown;
        private float _cardAlpha;
        private float _cardAppear = -1f;
        private float _bannerAt = -1f;
        private bool _resultShown;
        private float _resultAt = -1f;
        private float _resultAlpha;
        private bool _countdownShown;
        private bool _countdownRunning;
        private float _countdownTotal;
        private float _countdownEnd;
        private float _countdownFrozen;
        private int _countdownShownNumber = -1;
        private float _countdownBeat = -1f;
        private float _rainUntil = -1f;
        private float _rainAccumulator;
        private readonly List<Piece> _pieces = new List<Piece>();
        private readonly Stack<Piece> _pool = new Stack<Piece>();

        // ------------------------------------------------------------------
        // Estado público
        // ------------------------------------------------------------------

        /// <summary>Cierto cuando ya está montado en el Canvas del HUD.</summary>
        public bool IsBuilt
        {
            get { return _root != null; }
        }

        /// <summary>Cierto mientras un juego tiene la pantalla (entre <see cref="Open"/> y <see cref="Close"/>).</summary>
        public bool IsOpen
        {
            get { return _open; }
        }

        /// <summary>Id del juego que tiene la pantalla, o vacío.</summary>
        public string CurrentGame
        {
            get { return _open ? _game : string.Empty; }
        }

        /// <summary>
        /// Cierto mientras hay un juego en pantalla o la vista en vivo de la cámara:
        /// StageScreen aparta el QR y no saca la invitación a hablar.
        /// </summary>
        public bool HoldsTopStrip
        {
            get { return _open || (_preview != null && _preview.IsVisible); }
        }

        /// <summary>Cierto mientras está puesta la tarjeta del resultado final (<see cref="ShowResult"/>).</summary>
        public bool IsResultShown
        {
            get { return _resultShown; }
        }

        /// <summary>Cierto mientras el contador circular corre.</summary>
        public bool IsCountdownRunning
        {
            get { return _countdownRunning; }
        }

        /// <summary>Segundos que le quedan al contador (0 si no corre).</summary>
        public float CountdownRemaining
        {
            get { return _countdownRunning ? Mathf.Max(0f, _countdownEnd - _clock) : 0f; }
        }

        /// <summary>La tarjeta de la franja alta (para moverla o animarla). Null si no hay HUD.</summary>
        public RectTransform Card
        {
            get
            {
                EnsureBuilt();
                return _card;
            }
        }

        /// <summary>Hueco a la derecha de la cabecera de la tarjeta (puntos de progreso, marcador...).</summary>
        public RectTransform HeaderRight
        {
            get
            {
                EnsureBuilt();
                return _headerRight;
            }
        }

        /// <summary>El contador circular (para moverlo con <see cref="PlaceCountdown"/>).</summary>
        public RectTransform Countdown
        {
            get
            {
                EnsureBuilt();
                return _countdown;
            }
        }

        /// <summary>Capa del confeti, encima de todo lo del juego.</summary>
        public RectTransform Effects
        {
            get
            {
                EnsureBuilt();
                return _effects;
            }
        }

        /// <summary>Ancho de la tarjeta, en píxeles de la referencia.</summary>
        public float CardWidth
        {
            get { return cardWidth; }
        }

        /// <summary>Ancho útil dentro de la tarjeta (sin los márgenes de su contenido).</summary>
        public float ContentWidth
        {
            get { return cardWidth - 88f; }
        }

        /// <summary>Se acaba el contador circular (llega a 0). Solo visual: el tiempo de verdad lo lleva el orquestador.</summary>
        public event Action CountdownFinished;

        /// <summary>Un juego toma la pantalla (su id).</summary>
        public event Action<string> Opened;

        /// <summary>La pantalla del juego terminó de retirarse (su id).</summary>
        public event Action<string> Closed;

        // ------------------------------------------------------------------
        // Kit para los juegos: fuentes, sprites y piezas
        // ------------------------------------------------------------------

        /// <summary>Fuente de títulos y números grandes (Manrope ExtraBold, la de la pantalla del stand).</summary>
        public TMP_FontAsset DisplayFont
        {
            get
            {
                EnsureBuilt();
                return _display;
            }
        }

        /// <summary>Fuente de los textos de lectura (Manrope SemiBold).</summary>
        public TMP_FontAsset BodyFont
        {
            get
            {
                EnsureBuilt();
                return _bodyFont;
            }
        }

        /// <summary>Fuente de las etiquetas pequeñas en mayúsculas (Geist Mono).</summary>
        public TMP_FontAsset MonoFont
        {
            get
            {
                EnsureBuilt();
                return _mono;
            }
        }

        /// <summary>Rectángulo redondeado de radio <see cref="CornerRadius"/>, cortado en 9.</summary>
        public Sprite RoundSprite
        {
            get { CreateSprites(); return _roundSprite; }
        }

        /// <summary>Solo el contorno (4 px) de un rectángulo redondeado, cortado en 9.</summary>
        public Sprite FrameSprite
        {
            get { CreateSprites(); return _frameSprite; }
        }

        /// <summary>Halo difuminado alrededor de un rectángulo redondeado, cortado en 9.</summary>
        public Sprite GlowSprite
        {
            get { CreateSprites(); return _glowSprite; }
        }

        /// <summary>Círculo lleno.</summary>
        public Sprite DotSprite
        {
            get { CreateSprites(); return _dotSprite; }
        }

        /// <summary>Anillo (el del contador); con Image.Type.Filled hace de arco.</summary>
        public Sprite RingSprite
        {
            get { CreateSprites(); return _ringSprite; }
        }

        /// <summary>Círculo verde con un visto blanco.</summary>
        public Sprite CheckSprite
        {
            get { CreateSprites(); return _checkSprite; }
        }

        /// <summary>Círculo rojo con una cruz blanca.</summary>
        public Sprite CrossSprite
        {
            get { CreateSprites(); return _crossSprite; }
        }

        /// <summary>Destello de cuatro puntas.</summary>
        public Sprite SparkleSprite
        {
            get { CreateSprites(); return _sparkleSprite; }
        }

        /// <summary>Estrella de cinco puntas.</summary>
        public Sprite StarSprite
        {
            get { CreateSprites(); return _starSprite; }
        }

        /// <summary>Papelito del confeti.</summary>
        public Sprite PieceSprite
        {
            get { CreateSprites(); return _pieceSprite; }
        }

        /// <summary>RectTransform nuevo en la capa del HUD.</summary>
        public RectTransform NewRect(string name, Transform parent)
        {
            GameObject go = new GameObject(name, typeof(RectTransform));
            go.layer = parent != null ? parent.gameObject.layer : (_canvas != null ? _canvas.gameObject.layer : 0);
            go.transform.SetParent(parent, false);
            return (RectTransform)go.transform;
        }

        /// <summary>Imagen sin raycast; los sprites con borde se pintan cortados en 9.</summary>
        public Image NewImage(string name, Transform parent, Sprite sprite, Color color)
        {
            RectTransform rect = NewRect(name, parent);
            Image image = rect.gameObject.AddComponent<Image>();
            image.sprite = sprite;
            image.type = sprite != null && sprite.border.sqrMagnitude > 0f ? Image.Type.Sliced : Image.Type.Simple;
            image.color = color;
            image.raycastTarget = false;
            return image;
        }

        /// <summary>Rectángulo redondeado del color y radio (px de la referencia) pedidos.</summary>
        public Image NewRound(string name, Transform parent, Color color, float radius = CornerRadius)
        {
            Image image = NewImage(name, parent, RoundSprite, color);
            SetRadius(image, radius);
            return image;
        }

        /// <summary>Cambia el radio de un rectángulo redondeado hecho con <see cref="RoundSprite"/> o <see cref="FrameSprite"/>.</summary>
        public static void SetRadius(Image image, float radius)
        {
            if (image != null)
            {
                image.type = Image.Type.Sliced;
                image.pixelsPerUnitMultiplier = CornerRadius / Mathf.Max(1f, radius);
            }
        }

        /// <summary>
        /// Texto TextMeshPro sin raycast. Por defecto con <see cref="DisplayFont"/>;
        /// el texto admite etiquetas (para lo que llega del orquestador, <see cref="GameUi.Plain"/>).
        /// </summary>
        public TextMeshProUGUI NewText(
            string name,
            Transform parent,
            string content,
            float size,
            Color color,
            TextAlignmentOptions alignment = TextAlignmentOptions.Center,
            TMP_FontAsset font = null)
        {
            EnsureBuilt();
            RectTransform rect = NewRect(name, parent);
            TextMeshProUGUI text = rect.gameObject.AddComponent<TextMeshProUGUI>();
            TMP_FontAsset chosen = font != null ? font : _display;
            if (chosen != null)
            {
                text.font = chosen;
            }

            // Con la de TextMeshPro (sin las de la pantalla del stand) se engorda a mano.
            text.fontStyle = chosen == null || chosen == _fallback ? FontStyles.Bold : FontStyles.Normal;
            text.richText = true;
            text.text = content ?? string.Empty;
            text.fontSize = size;
            text.color = color;
            text.alignment = alignment;
            text.textWrappingMode = TextWrappingModes.Normal;
            text.overflowMode = TextOverflowModes.Overflow;
            text.raycastTarget = false;
            return text;
        }

        /// <summary>Grupo con opacidad (sin raycast) que ocupa todo su padre.</summary>
        public CanvasGroup NewGroup(string name, Transform parent)
        {
            RectTransform rect = NewRect(name, parent);
            GameUi.Stretch(rect);
            CanvasGroup group = rect.gameObject.AddComponent<CanvasGroup>();
            group.interactable = false;
            group.blocksRaycasts = false;
            return group;
        }

        // ------------------------------------------------------------------
        // Ciclo de vida
        // ------------------------------------------------------------------

        private void Awake()
        {
            _framing = GetComponentInChildren<CameraFramingController>(true);
            _preview = GetComponent<CameraPreviewPanel>();
        }

        private void Start()
        {
            _stage = GetComponentInChildren<StageScreen>(true);
            if (_preview == null)
            {
                _preview = GetComponent<CameraPreviewPanel>();
            }

            // Se monta en cuanto esté la pantalla del stand (sus fuentes), oculto:
            // así aparecer no cuesta nada. Si tarda, se monta igual.
            _waitStageUntil = Time.unscaledTime + 5f;
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

        /// <summary>
        /// Un juego toma la pantalla: tarjeta con su título, su contenedor y su capa
        /// encendidos (los de los demás, apagados), plano de panel y aviso a la
        /// pantalla del stand. Devuelve el contenedor del juego en la tarjeta.
        /// </summary>
        public RectTransform Open(string gameId, string title)
        {
            EnsureBuilt();
            if (_root == null || string.IsNullOrEmpty(gameId))
            {
                return null;
            }

            _open = true;
            _game = gameId;
            _gameTitle = title ?? string.Empty;
            _root.gameObject.SetActive(true);

            // Lo del juego anterior, fuera.
            _resultShown = false;
            _resultAt = -1f;
            _bannerAt = -1f;
            _rainUntil = -1f;
            StopCountdown();
            PlaceCountdownDefault();
            _card.anchorMin = new Vector2(0.5f, 1f - cardTop);
            _card.anchorMax = _card.anchorMin;
            _card.anchoredPosition = Vector2.zero;
            _cardTopCustom = false;
            PlaceCardAuto(true);

            RectTransform content = ContentOf(gameId);
            foreach (KeyValuePair<string, RectTransform> pair in _contents)
            {
                pair.Value.gameObject.SetActive(pair.Key == gameId);
            }

            LayerOf(gameId);
            foreach (KeyValuePair<string, RectTransform> pair in _gameLayers)
            {
                pair.Value.gameObject.SetActive(pair.Key == gameId);
            }

            SetTitle(_gameTitle);
            SetCaption(string.Empty);
            _cardShown = true;
            _cardAppear = _clock;
            _reservedBottom = 0f;
            RequestPanelShot();
            Log("abre " + gameId + " (" + _gameTitle + ")");
            RaiseOpened(gameId);
            return content;
        }

        /// <summary>
        /// Retira la pantalla del juego (con un fundido) y suelta el plano de panel.
        /// Solo si la tiene ese juego: un juego que ya cedió la pantalla a otro no
        /// se la quita.
        /// </summary>
        public void Close(string gameId)
        {
            if (!_open || gameId != _game)
            {
                return;
            }

            _open = false;
            _cardShown = false;
            _resultShown = false;
            _bannerAt = -1f;
            _rainUntil = -1f;
            StopCountdown();
            ReleasePanelShot();
            Log("cierra " + gameId);
        }

        /// <summary>El contenedor del juego dentro de la tarjeta, bajo la cabecera (se crea la primera vez).</summary>
        public RectTransform ContentOf(string gameId)
        {
            EnsureBuilt();
            if (_body == null || string.IsNullOrEmpty(gameId))
            {
                return null;
            }

            RectTransform content;
            if (_contents.TryGetValue(gameId, out content) && content != null)
            {
                return content;
            }

            content = NewRect("Juego_" + gameId, _body);
            LayoutElement layout = content.gameObject.AddComponent<LayoutElement>();
            layout.minHeight = 0f;
            layout.flexibleWidth = 1f;
            content.gameObject.SetActive(_open && _game == gameId);
            _contents[gameId] = content;
            return content;
        }

        /// <summary>
        /// Capa del juego a pantalla completa (1080x1920), por encima de la tarjeta y de
        /// la vista en vivo y por debajo del confeti: para lo que no va en la tarjeta.
        /// </summary>
        public RectTransform LayerOf(string gameId)
        {
            EnsureBuilt();
            if (_layers == null || string.IsNullOrEmpty(gameId))
            {
                return null;
            }

            RectTransform layer;
            if (_gameLayers.TryGetValue(gameId, out layer) && layer != null)
            {
                return layer;
            }

            layer = NewRect("Capa_" + gameId, _layers);
            GameUi.Stretch(layer);
            layer.gameObject.SetActive(_open && _game == gameId);
            _gameLayers[gameId] = layer;
            return layer;
        }

        /// <summary>
        /// Alto del contenedor del juego en la tarjeta (px). Sin llamarlo, manda lo
        /// que pida su propio LayoutGroup (si le pone uno) o 0.
        /// </summary>
        public void SetContentHeight(string gameId, float height)
        {
            RectTransform content = ContentOf(gameId);
            if (content == null)
            {
                return;
            }

            LayoutElement layout = content.GetComponent<LayoutElement>();
            layout.minHeight = Mathf.Max(0f, height);
            layout.preferredHeight = Mathf.Max(0f, height);
        }

        /// <summary>Título de la cabecera, en mayúsculas; por defecto con las letras en los colores de Google.</summary>
        public void SetTitle(string title, bool googleColors = true)
        {
            EnsureBuilt();
            if (_title == null)
            {
                return;
            }

            string upper = GameUi.Plain(title ?? string.Empty).ToUpperInvariant();
            _title.text = googleColors ? GameUi.ColoredWord(upper) : upper;
        }

        /// <summary>Rótulo corto en gris a la derecha del título («RONDA 2 DE 6»); vacío lo quita.</summary>
        public void SetCaption(string caption)
        {
            EnsureBuilt();
            if (_caption != null)
            {
                _caption.text = GameUi.Plain(caption ?? string.Empty).ToUpperInvariant();
            }
        }

        /// <summary>Enseña u oculta la tarjeta (con fundido). El resultado final la oculta solo.</summary>
        public void SetCardVisible(bool visible)
        {
            if (visible && !_cardShown)
            {
                _cardAppear = _clock;
            }

            _cardShown = visible;
        }

        /// <summary>
        /// Mueve el borde de arriba de la tarjeta (fracción del alto, 0 arriba). Sin
        /// llamarlo, la tarjeta va arriba y, con la vista en vivo puesta, justo debajo
        /// de ella. Open la devuelve a lo automático.
        /// </summary>
        public void SetCardTop(float topFraction)
        {
            EnsureBuilt();
            if (_card == null)
            {
                return;
            }

            _cardTopCustom = true;
            _card.anchorMin = new Vector2(0.5f, 1f - Mathf.Clamp01(topFraction));
            _card.anchorMax = _card.anchorMin;
        }

        /// <summary>Tarjeta arriba o, con la vista en vivo, debajo de ella (si el juego no la colocó).</summary>
        private void PlaceCardAuto(bool snap)
        {
            if (_card == null || _cardTopCustom)
            {
                return;
            }

            bool previewUp = _preview != null && _preview.IsVisible;
            float top = previewUp ? _preview.BottomFraction + 0.015f : cardTop;
            float current = 1f - _card.anchorMin.y;
            if (Mathf.Abs(current - top) < 0.0005f)
            {
                return;
            }

            float next = snap ? top : Mathf.MoveTowards(current, top, Time.deltaTime * 1.2f);
            _card.anchorMin = new Vector2(0.5f, 1f - next);
            _card.anchorMax = _card.anchorMin;
        }

        /// <summary>Vuelve a hacer la entrada con rebote de la tarjeta (ronda nueva).</summary>
        public void PopCard()
        {
            _cardAppear = _clock;
        }

        /// <summary>
        /// Recalcula ya el alto de la tarjeta tras cambiar su contenido (si no, se
        /// ajusta solo en el fotograma siguiente).
        /// </summary>
        public void RefreshLayout()
        {
            if (_card == null || _body == null)
            {
                return;
            }

            bool rootActive = _root.gameObject.activeSelf;
            bool cardActive = _card.gameObject.activeSelf;
            _root.gameObject.SetActive(true);
            _card.gameObject.SetActive(true);
            LayoutRebuilder.ForceRebuildLayoutImmediate(_body);
            _card.sizeDelta = new Vector2(cardWidth, _body.rect.height);
            _card.gameObject.SetActive(cardActive);
            _root.gameObject.SetActive(rootActive);
        }

        // ------------------------------------------------------------------
        // Contador circular
        // ------------------------------------------------------------------

        /// <summary>Enseña el contador y lo pone a correr desde <paramref name="seconds"/> hasta 0.</summary>
        public void StartCountdown(float seconds)
        {
            EnsureBuilt();
            if (_countdown == null)
            {
                return;
            }

            _countdownTotal = Mathf.Max(0.1f, seconds);
            _countdownEnd = _clock + _countdownTotal;
            _countdownRunning = true;
            _countdownShown = true;
            _countdownShownNumber = -1;
            _countdownBeat = -1f;
            _countdown.gameObject.SetActive(true);
            GameAnim.Pop(_countdown, 0.4f);
        }

        /// <summary>Para el contador; con <paramref name="hide"/> también lo quita, si no se queda quieto donde iba.</summary>
        public void StopCountdown(bool hide = true)
        {
            if (_countdownRunning)
            {
                _countdownFrozen = Mathf.Max(0f, _countdownEnd - _clock);
            }

            _countdownRunning = false;
            if (hide)
            {
                _countdownShown = false;
            }
        }

        /// <summary>
        /// Coloca el contador dentro de <paramref name="parent"/> (por ejemplo, en el
        /// centro del contenido del juego) con el ancla, la posición y el diámetro dados.
        /// </summary>
        public void PlaceCountdown(RectTransform parent, Vector2 anchor, Vector2 position, float size)
        {
            EnsureBuilt();
            if (_countdown == null || parent == null)
            {
                return;
            }

            _countdown.SetParent(parent, false);
            _countdown.anchorMin = anchor;
            _countdown.anchorMax = anchor;
            _countdown.pivot = new Vector2(0.5f, 0.5f);
            _countdown.anchoredPosition = position;
            _countdown.sizeDelta = new Vector2(size, size);
            _countdownNumber.fontSize = size * 0.42f;
            LayoutElement ignore = _countdown.GetComponent<LayoutElement>();
            ignore.ignoreLayout = true;
        }

        private void PlaceCountdownDefault()
        {
            if (_card != null)
            {
                // Colgando de la esquina de arriba a la derecha de la tarjeta.
                PlaceCountdown(_card, new Vector2(1f, 1f), new Vector2(-48f, 4f), countdownSize);
            }
        }

        // ------------------------------------------------------------------
        // Rótulos
        // ------------------------------------------------------------------

        /// <summary>Rótulo corto que salta sobre el borde de abajo de la tarjeta («¡Correcto!», en verde).</summary>
        public void ShowBanner(string text, Color color)
        {
            EnsureBuilt();
            if (_bannerText == null)
            {
                return;
            }

            _bannerText.text = GameUi.Plain(text);
            _bannerFill.color = color;
            _bannerAt = _clock;
            LayoutRebuilder.ForceRebuildLayoutImmediate(_banner);
        }

        /// <summary>Quita el rótulo de la tarjeta.</summary>
        public void HideBanner()
        {
            _bannerAt = -1f;
        }

        /// <summary>
        /// Tarjeta del resultado final, en el sitio de la tarjeta del juego (que se
        /// va): el nombre del juego arriba, <paramref name="title"/> en grande
        /// («¡GANASTE!»), <paramref name="score"/> debajo («7 de 9») y una frase.
        /// Con <paramref name="won"/>, en dorado y con lluvia de confeti.
        /// </summary>
        public void ShowResult(string title, string score = null, string line = null, bool won = true)
        {
            EnsureBuilt();
            if (_result == null)
            {
                return;
            }

            _resultEyebrow.text = GameUi.ColoredWord(GameUi.Plain(_gameTitle).ToUpperInvariant()) + "  DEVFEST";
            _resultTitle.text = GameUi.Plain(title ?? string.Empty);
            _resultTitle.colorGradient = won
                ? new VertexGradient(GameColors.Gold, GameColors.Gold, GameColors.Yellow, new Color(1f, 0.62f, 0.1f))
                : new VertexGradient(Color.white, Color.white, new Color(0.75f, 0.85f, 1f), new Color(0.75f, 0.85f, 1f));
            _resultScore.text = GameUi.Plain(score ?? string.Empty);
            _resultScore.gameObject.SetActive(!string.IsNullOrEmpty(score));
            _resultLine.text = GameUi.Plain(line ?? string.Empty);
            _resultLine.gameObject.SetActive(!string.IsNullOrEmpty(line));

            _resultShown = true;
            _resultAt = _clock + ResultDelay;
            _bannerAt = -1f;
            StopCountdown();
            // Arriba del todo, en la franja de la tarjeta: la vista en vivo se aparta
            // mientras se ve el resultado (y Sonnia sube).
            _result.anchorMin = new Vector2(0.5f, 1f - cardTop);
            _result.anchorMax = _result.anchorMin;
            _result.anchoredPosition = Vector2.zero;
            RectTransform body = (RectTransform)_result.Find("Contenido");
            bool wasActive = _result.gameObject.activeSelf;
            _result.gameObject.SetActive(true);
            LayoutRebuilder.ForceRebuildLayoutImmediate(body);
            _result.sizeDelta = new Vector2(cardWidth, body.rect.height);
            _result.gameObject.SetActive(wasActive);

            if (won)
            {
                Celebrate();
            }
            else
            {
                Sparkles(new Vector2(0f, ReferenceHeight * 0.5f * (1f - (2f * cardTop)) - 160f), 8);
            }
        }

        /// <summary>Quita la tarjeta del resultado (vuelve la del juego si no se ocultó).</summary>
        public void HideResult()
        {
            _resultShown = false;
        }

        // ------------------------------------------------------------------
        // Confeti y destellos
        // ------------------------------------------------------------------

        /// <summary>Punto de un elemento en coordenadas de la capa de efectos (para <see cref="Burst"/>).</summary>
        public Vector2 EffectsPoint(RectTransform target)
        {
            EnsureBuilt();
            if (target == null || _effects == null)
            {
                return Vector2.zero;
            }

            Vector3 local = _effects.InverseTransformPoint(target.position);
            return new Vector2(local.x, local.y);
        }

        /// <summary>
        /// Ráfaga de papelitos desde <paramref name="at"/> (coordenadas de la capa de
        /// efectos: 0,0 es el centro de la pantalla) hacia <paramref name="angleDeg"/>.
        /// </summary>
        public void Burst(Vector2 at, int count = 90, float speed = 1300f, float angleDeg = 90f)
        {
            EnsureBuilt();
            if (_effects == null)
            {
                return;
            }

            ShowEffects();
            for (int i = 0; i < count; i++)
            {
                float angle = (angleDeg + Random.Range(-38f, 38f)) * Mathf.Deg2Rad;
                float magnitude = speed * Random.Range(0.45f, 1f);
                Spawn(at, new Vector2(Mathf.Cos(angle), Mathf.Sin(angle)) * magnitude, false);
            }
        }

        /// <summary>Ráfaga de papelitos desde un elemento (una opción acertada, una ficha...).</summary>
        public void BurstFrom(RectTransform target, int count = 90, float speed = 1300f)
        {
            Burst(EffectsPoint(target), count, speed);
        }

        /// <summary>Destellos alrededor de un punto de la capa de efectos.</summary>
        public void Sparkles(Vector2 at, int count = 10)
        {
            EnsureBuilt();
            if (_effects == null)
            {
                return;
            }

            ShowEffects();
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

        /// <summary>Destellos alrededor de un elemento.</summary>
        public void SparklesAt(RectTransform target, int count = 10)
        {
            Sparkles(EffectsPoint(target), count);
        }

        /// <summary>Lluvia de confeti desde arriba durante unos segundos.</summary>
        public void Rain(float seconds = 5.5f)
        {
            EnsureBuilt();
            ShowEffects();
            _rainUntil = _clock + Mathf.Max(0f, seconds);
        }

        /// <summary>La celebración de ganar la trivia: dos ráfagas desde abajo y lluvia.</summary>
        public void Celebrate()
        {
            Rain(5.5f);
            Burst(new Vector2(-420f, -700f), 80, 1700f, 60f);
            Burst(new Vector2(420f, -700f), 80, 1700f, 120f);
        }

        // ------------------------------------------------------------------
        // Cámara
        // ------------------------------------------------------------------

        /// <summary>
        /// Pide el plano de panel automático (Open ya lo pide): la cámara se aleja y
        /// sube lo justo para que Sonnia quede debajo de lo que haya en la franja alta
        /// (<see cref="TopStripBottom"/>), calibrado entre el plano corto (tarjeta de la
        /// trivia) y el largo (vista en vivo más tarjeta).
        /// </summary>
        public void RequestPanelShot()
        {
            _panelWanted = true;
            _panelCustom = false;
        }

        /// <summary>
        /// Pide el plano de panel con un desplazamiento fijo (metros: x a la derecha, y
        /// arriba, z hacia Sonnia; negativo la aleja), en vez del automático. Para lo
        /// que el automático no ve (una capa propia que baja mucho, por ejemplo). Vale
        /// hasta el siguiente RequestPanelShot() o Close.
        /// </summary>
        public void RequestPanelShot(Vector3 extra)
        {
            _panelWanted = true;
            _panelCustom = true;
            _panelExtra = extra;
        }

        /// <summary>Suelta el plano de panel (Close ya lo suelta). Con la vista en vivo puesta, sigue.</summary>
        public void ReleasePanelShot()
        {
            _panelWanted = false;
            _panelCustom = false;
        }

        /// <summary>
        /// Avisa de que algo del juego (en su <see cref="LayerOf"/>) baja hasta
        /// <paramref name="bottomPixels"/> (px desde arriba): el plano automático deja
        /// a Sonnia debajo. 0 lo quita. Open lo pone a 0.
        /// </summary>
        public void ReserveTopStrip(float bottomPixels)
        {
            _reservedBottom = Mathf.Max(0f, bottomPixels);
        }

        /// <summary>
        /// Borde de abajo de lo que hay ahora en la franja alta, en px de la referencia
        /// desde arriba (0 si no hay nada): la tarjeta o el resultado, la vista en vivo y
        /// lo reservado con <see cref="ReserveTopStrip"/>.
        /// </summary>
        public float TopStripBottom
        {
            get
            {
                float bottom = _open ? _reservedBottom : 0f;
                if (_card != null && _cardShown && !_resultShown)
                {
                    bottom = Mathf.Max(bottom, BottomOf(_card));
                }

                if (_result != null && _resultShown)
                {
                    bottom = Mathf.Max(bottom, BottomOf(_result));
                }

                if (_preview != null && _preview.IsVisible)
                {
                    bottom = Mathf.Max(bottom, _preview.BottomFraction * ReferenceHeight);
                }

                return bottom;
            }
        }

        /// <summary>El desplazamiento del plano automático para lo que acaba en <paramref name="bottomPixels"/>.</summary>
        public Vector3 AutoPanelExtra(float bottomPixels)
        {
            // A saltos de 40 px: que un cambio pequeño de la tarjeta no mueva la cámara.
            float quantized = Mathf.Round(bottomPixels / 40f) * 40f;
            float t = Mathf.Clamp((quantized - shortShotBottom) / Mathf.Max(1f, tallShotBottom - shortShotBottom), 0f, 1.6f);
            return Vector3.LerpUnclamped(shortShotExtra, tallShotExtra, t);
        }

        /// <summary>Borde de abajo (px desde arriba) de un rectángulo con un ancla de punto, como la tarjeta.</summary>
        private static float BottomOf(RectTransform rect)
        {
            float pivotFromTop = ((1f - rect.anchorMin.y) * ReferenceHeight) - rect.anchoredPosition.y;
            return pivotFromTop + (rect.sizeDelta.y * rect.pivot.y);
        }

        private void UpdatePanelShot()
        {
            if (_framing == null)
            {
                _framing = GetComponentInChildren<CameraFramingController>(true);
                if (_framing == null)
                {
                    return;
                }
            }

            bool previewUp = _preview != null && _preview.IsVisible;
            bool want = (_open && _panelWanted) || previewUp;
            if (want)
            {
                Vector3 extra = _open && _panelCustom ? _panelExtra : AutoPanelExtra(TopStripBottom);
                if (!_panelApplied || (extra - _appliedExtra).sqrMagnitude > 0.000001f || !_framing.PanelRequested)
                {
                    _framing.PanelRequestOffset = extra;
                    _framing.PanelRequested = true;
                    _panelApplied = true;
                    _appliedExtra = extra;
                }
            }
            else if (_panelApplied)
            {
                _framing.PanelRequested = false;
                _framing.PanelRequestOffset = Vector3.zero;
                _panelApplied = false;
            }
        }

        // ------------------------------------------------------------------
        // Animación
        // ------------------------------------------------------------------

        private void Update()
        {
            if (_root == null)
            {
                bool stageReady = _stage == null || _stage.IsBuilt || !_stage.enabled;
                if (_waitStageUntil > 0f && (stageReady || Time.unscaledTime > _waitStageUntil))
                {
                    _waitStageUntil = -1f;
                    EnsureBuilt();
                }

                return;
            }

            float dt = Time.deltaTime;
            _clock += dt;
            PlaceCardAuto(_cardAlpha <= 0.001f);
            UpdatePanelShot();

            bool visible = _open || _cardAlpha > 0.001f || _resultAlpha > 0.001f || _pieces.Count > 0 || _rootAlpha > 0.001f;
            if (!visible)
            {
                if (_root.gameObject.activeSelf)
                {
                    FinishClose();
                }

                return;
            }

            if (!_root.gameObject.activeSelf)
            {
                _root.gameObject.SetActive(true);
            }

            bool closing = !_open;
            _rootAlpha = Mathf.MoveTowards(_rootAlpha, closing ? 0f : 1f, dt / (closing ? closeFadeSeconds : 0.3f));
            _rootGroup.alpha = _rootAlpha;
            if (closing && _rootAlpha <= 0.001f)
            {
                FinishClose();
                return;
            }

            if (_preview != null)
            {
                _preview.Suppressed = _resultShown && (_open || _resultAlpha > 0.001f);
            }

            AnimateCard(dt);
            AnimateBanner();
            AnimateCountdown(dt);
            AnimateResult(dt);
            AnimatePieces(dt);
        }

        private void LateUpdate()
        {
            // La tarjeta mide lo que su contenido (cabecera y contenedor del juego).
            if (_card != null && _card.gameObject.activeInHierarchy && _body != null)
            {
                float height = _body.rect.height;
                if (Mathf.Abs(_card.sizeDelta.y - height) > 0.5f || Mathf.Abs(_card.sizeDelta.x - cardWidth) > 0.5f)
                {
                    _card.sizeDelta = new Vector2(cardWidth, height);
                }
            }
        }

        /// <summary>Al acabar el fundido de salida: todo apagado y listo para el siguiente juego.</summary>
        private void FinishClose()
        {
            string closed = _game;
            _rootAlpha = 0f;
            _rootGroup.alpha = 0f;
            _cardAlpha = 0f;
            _resultAlpha = 0f;
            _countdownShown = false;
            _countdown.gameObject.SetActive(false);
            for (int i = _pieces.Count - 1; i >= 0; i--)
            {
                _pieces[i].Rect.gameObject.SetActive(false);
                _pool.Push(_pieces[i]);
            }

            _pieces.Clear();
            if (!_open)
            {
                foreach (RectTransform content in _contents.Values)
                {
                    content.gameObject.SetActive(false);
                }

                foreach (RectTransform layer in _gameLayers.Values)
                {
                    layer.gameObject.SetActive(false);
                }

                _game = string.Empty;
            }

            if (_preview != null)
            {
                _preview.Suppressed = false;
            }

            _root.gameObject.SetActive(false);
            if (!_open && !string.IsNullOrEmpty(closed))
            {
                RaiseClosed(closed);
            }
        }

        private void AnimateCard(float dt)
        {
            bool show = _cardShown && !_resultShown;
            _cardAlpha = Mathf.MoveTowards(_cardAlpha, show ? 1f : 0f, dt / (show ? 0.35f : 0.3f));
            _cardGroup.alpha = _cardAlpha;
            bool active = _cardAlpha > 0.001f;
            if (_card.gameObject.activeSelf != active)
            {
                _card.gameObject.SetActive(active);
            }

            float appear = _cardAppear >= 0f ? Mathf.Clamp01((_clock - _cardAppear) / 0.5f) : 1f;
            float scale = Mathf.Lerp(0.9f, 1f, GameUi.EaseOutBack(appear)) * Mathf.Lerp(0.96f, 1f, _cardAlpha);
            _card.localScale = new Vector3(scale, scale, 1f);
        }

        private void AnimateBanner()
        {
            if (_bannerAt < 0f || !_cardShown || _resultShown)
            {
                if (_banner.gameObject.activeSelf)
                {
                    _banner.gameObject.SetActive(false);
                }

                return;
            }

            float s = _clock - _bannerAt;
            _banner.gameObject.SetActive(true);
            float pop = GameUi.EaseOutBack(Mathf.Clamp01(s / 0.35f));
            float wiggle = 1f + (0.02f * Mathf.Sin(s * 6f));
            _banner.localScale = new Vector3(pop * wiggle, pop * wiggle, 1f);
            _banner.localRotation = Quaternion.Euler(0f, 0f, -4f + (Mathf.Sin(s * 3f) * 1.5f));
        }

        private void AnimateCountdown(float dt)
        {
            if (_countdown == null)
            {
                return;
            }

            float target = _countdownShown ? 1f : 0f;
            _countdownGroup.alpha = Mathf.MoveTowards(_countdownGroup.alpha, target, dt * 5f);
            bool active = _countdownGroup.alpha > 0.001f || _countdownShown;
            if (_countdown.gameObject.activeSelf != active)
            {
                _countdown.gameObject.SetActive(active);
            }

            if (!active)
            {
                return;
            }

            float remaining = _countdownRunning ? Mathf.Max(0f, _countdownEnd - _clock) : _countdownFrozen;
            float fraction = _countdownTotal > 0f ? remaining / _countdownTotal : 0f;
            _countdownArc.fillAmount = fraction;
            _countdownArc.color = fraction > 0.5f
                ? GameColors.Green
                : fraction > 0.25f ? GameColors.Yellow : GameColors.Red;

            int number = Mathf.CeilToInt(remaining - 0.0001f);
            if (number != _countdownShownNumber)
            {
                _countdownShownNumber = number;
                _countdownNumber.text = number.ToString();
                if (_countdownRunning && number <= 5)
                {
                    _countdownBeat = _clock;
                }
            }

            float beat = 1f;
            if (_countdownBeat >= 0f)
            {
                float s = _clock - _countdownBeat;
                beat = s < 0.3f ? 1f + (0.12f * Mathf.Sin(s / 0.3f * Mathf.PI)) : 1f;
            }

            _countdownNumber.rectTransform.localScale = new Vector3(beat, beat, 1f);

            if (_countdownRunning && remaining <= 0f)
            {
                _countdownRunning = false;
                _countdownFrozen = 0f;
                _countdownBeat = _clock;
                try
                {
                    Action handler = CountdownFinished;
                    if (handler != null)
                    {
                        handler();
                    }
                }
                catch (Exception ex)
                {
                    Debug.LogException(ex, this);
                }
            }
        }

        private void AnimateResult(float dt)
        {
            bool show = _resultShown && _clock >= _resultAt;
            _resultAlpha = Mathf.MoveTowards(_resultAlpha, show ? 1f : 0f, dt / (show ? 0.4f : 0.5f));
            _resultGroup.alpha = _resultAlpha;
            bool active = _resultAlpha > 0.001f;
            if (_result.gameObject.activeSelf != active)
            {
                _result.gameObject.SetActive(active);
            }

            if (_resultAt < 0f || !active)
            {
                return;
            }

            float s = Mathf.Max(0f, _clock - _resultAt);
            float pop = GameUi.EaseOutBack(Mathf.Clamp01(s / 0.55f));
            float breathe = 1f + (0.012f * Mathf.Sin(s * 2.4f));
            float scale = Mathf.Lerp(0.6f, 1f, pop) * breathe;
            _result.localScale = new Vector3(scale, scale, 1f);
            float hop = Mathf.Abs(Mathf.Sin(s * 4f)) * 6f * Mathf.Clamp01(1f - ((s - 3f) / 3f));
            _resultTitle.rectTransform.anchoredPosition = new Vector2(0f, hop);
        }

        private void ShowEffects()
        {
            if (_root != null && !_root.gameObject.activeSelf)
            {
                _root.gameObject.SetActive(true);
            }
        }

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
                    float t = Mathf.Max(0f, piece.Age) / piece.Life;
                    float twinkle = Mathf.Sin(t * Mathf.PI);
                    piece.Rect.localScale = Vector3.one * twinkle;
                    piece.Angle += piece.Spin * dt;
                    piece.Rect.localRotation = Quaternion.Euler(0f, 0f, piece.Angle);
                    piece.Image.color = GameUi.WithAlpha(piece.Image.color, twinkle);
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
                piece.Image.color = GameUi.WithAlpha(piece.Image.color, fade);
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
                piece.Image.color = Random.value < 0.5f ? Color.white : GameColors.Yellow;
                piece.Rect.sizeDelta = new Vector2(piece.Size, piece.Size);
            }
            else
            {
                piece.Life = Random.Range(2.2f, 3.6f);
                piece.Spin = Random.Range(-540f, 540f);
                piece.FlipSpeed = Random.Range(6f, 14f);
                bool round = Random.value < 0.25f;
                piece.Image.sprite = round ? _dotSprite : _pieceSprite;
                Color color = Random.value < 0.15f ? Color.white : GameColors.Google[Random.Range(0, GameColors.Google.Length)];
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
            Image image = NewImage("Confeti", _effects, _pieceSprite, Color.white);
            RectTransform rect = image.rectTransform;
            rect.anchorMin = new Vector2(0.5f, 0.5f);
            rect.anchorMax = new Vector2(0.5f, 0.5f);
            return new Piece { Rect = rect, Image = image };
        }

        // ------------------------------------------------------------------
        // Construcción
        // ------------------------------------------------------------------

        /// <summary>Monta la pantalla común si aún no lo está (lo hace solo; llamarlo no cuesta nada).</summary>
        public void EnsureBuilt()
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
                    Debug.LogWarning("[Sonia] No hay Canvas del HUD para los juegos.", this);
                }

                return;
            }

            if (_stage == null)
            {
                _stage = GetComponentInChildren<StageScreen>(true);
            }

            CreateSprites();
            ResolveFonts();

            GameObject root = new GameObject("Juegos", typeof(RectTransform), typeof(CanvasGroup));
            root.layer = _canvas.gameObject.layer;
            root.transform.SetParent(_canvas.transform, false);
            _root = (RectTransform)root.transform;
            GameUi.Stretch(_root);
            _rootGroup = root.GetComponent<CanvasGroup>();
            _rootGroup.interactable = false;
            _rootGroup.blocksRaycasts = false;
            _rootGroup.alpha = 0f;

            // Detrás de los subtítulos y del resto del HUD, delante de la pantalla del
            // stand (fondo, logo y QR, el primero).
            if (_root.parent.childCount > 1)
            {
                _root.SetSiblingIndex(1);
            }

            BuildCard();
            BuildResult();

            _layers = NewRect("Capas", _root);
            GameUi.Stretch(_layers);

            _effects = NewRect("Efectos", _root);
            GameUi.Stretch(_effects);

            BuildCountdown();
            PlaceCountdownDefault();

            root.SetActive(false);

            // La vista en vivo, justo detrás de lo de los juegos.
            if (_preview == null)
            {
                _preview = GetComponent<CameraPreviewPanel>();
            }

            if (_preview != null)
            {
                _preview.BuildUnder(_canvas, _root.GetSiblingIndex());
            }
        }

        private void ResolveFonts()
        {
            _fallback = FindFont(_canvas);
            bool stageFonts = _stage != null && _stage.IsBuilt;
            _display = stageFonts && _stage.DisplayFont != null ? _stage.DisplayFont : _fallback;
            _bodyFont = stageFonts && _stage.SemiboldFont != null ? _stage.SemiboldFont : _display;
            _mono = stageFonts && _stage.MonoFont != null ? _stage.MonoFont : _bodyFont;
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
            _card.sizeDelta = new Vector2(cardWidth, 120f);
            _cardGroup = cardRoot.GetComponent<CanvasGroup>();
            _cardGroup.alpha = 0f;
            _cardGroup.interactable = false;
            _cardGroup.blocksRaycasts = false;

            Image border = NewImage("Borde", _card, _roundSprite, GameColors.CardBorder);
            GameUi.Stretch(border.rectTransform);
            Image fill = NewImage("Fondo", _card, _roundSprite, GameColors.CardFill);
            GameUi.Stretch(fill.rectTransform);
            fill.rectTransform.offsetMin = new Vector2(3f, 3f);
            fill.rectTransform.offsetMax = new Vector2(-3f, -3f);

            _body = NewRect("Contenido", _card);
            _body.anchorMin = new Vector2(0f, 1f);
            _body.anchorMax = new Vector2(1f, 1f);
            _body.pivot = new Vector2(0.5f, 1f);
            _body.sizeDelta = Vector2.zero;
            VerticalLayoutGroup layout = _body.gameObject.AddComponent<VerticalLayoutGroup>();
            layout.padding = new RectOffset(44, 44, 34, 40);
            layout.spacing = 18f;
            layout.childAlignment = TextAnchor.UpperCenter;
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = false;
            ContentSizeFitter fitter = _body.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            // Cabecera: el título de colores, el rótulo corto y el hueco del juego.
            RectTransform header = NewRect("Cabecera", _body);
            HorizontalLayoutGroup headerRow = header.gameObject.AddComponent<HorizontalLayoutGroup>();
            headerRow.spacing = 18f;
            headerRow.childAlignment = TextAnchor.MiddleLeft;
            headerRow.childControlWidth = true;
            headerRow.childControlHeight = true;
            headerRow.childForceExpandWidth = false;
            headerRow.childForceExpandHeight = false;
            header.gameObject.AddComponent<LayoutElement>().preferredHeight = 50f;

            _title = NewText("Titulo", header, string.Empty, titleSize, Color.white, TextAlignmentOptions.Left, _display);
            _title.characterSpacing = 8f;
            _title.textWrappingMode = TextWrappingModes.NoWrap;
            _title.enableAutoSizing = true;
            _title.fontSizeMin = titleSize * 0.6f;
            _title.fontSizeMax = titleSize;

            _caption = NewText("Rotulo", header, string.Empty, 26f, GameColors.Muted, TextAlignmentOptions.Left, _bodyFont);
            _caption.characterSpacing = 4f;
            _caption.textWrappingMode = TextWrappingModes.NoWrap;
            _caption.gameObject.AddComponent<LayoutElement>().flexibleWidth = 1f;

            _headerRight = NewRect("Derecha", header);
            HorizontalLayoutGroup rightRow = _headerRight.gameObject.AddComponent<HorizontalLayoutGroup>();
            rightRow.spacing = 12f;
            rightRow.childAlignment = TextAnchor.MiddleRight;
            rightRow.childControlWidth = true;
            rightRow.childControlHeight = true;
            rightRow.childForceExpandWidth = false;
            rightRow.childForceExpandHeight = false;

            // Rótulo de acierto o fallo, sobre el borde de abajo de la tarjeta.
            _banner = NewRect("RotuloResultado", _card);
            _banner.anchorMin = new Vector2(0.5f, 0f);
            _banner.anchorMax = new Vector2(0.5f, 0f);
            _banner.pivot = new Vector2(0.5f, 0.5f);
            _banner.anchoredPosition = new Vector2(0f, -10f);
            HorizontalLayoutGroup bannerRow = _banner.gameObject.AddComponent<HorizontalLayoutGroup>();
            bannerRow.padding = new RectOffset(48, 48, 16, 18);
            bannerRow.childAlignment = TextAnchor.MiddleCenter;
            bannerRow.childControlWidth = true;
            bannerRow.childControlHeight = true;
            ContentSizeFitter bannerFit = _banner.gameObject.AddComponent<ContentSizeFitter>();
            bannerFit.horizontalFit = ContentSizeFitter.FitMode.PreferredSize;
            bannerFit.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            _bannerFill = NewImage("Fondo", _banner, _roundSprite, GameColors.Green);
            _bannerFill.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;
            GameUi.Stretch(_bannerFill.rectTransform);
            _bannerText = NewText("Texto", _banner, "¡Correcto!", 52f, Color.white, TextAlignmentOptions.Center, _display);
            _bannerText.textWrappingMode = TextWrappingModes.NoWrap;
            _banner.gameObject.SetActive(false);
        }

        private void BuildCountdown()
        {
            CanvasGroup group = NewGroup("Contador", _root);
            _countdownGroup = group;
            _countdownGroup.alpha = 0f;
            _countdown = (RectTransform)group.transform;
            _countdown.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            Image glow = NewImage("Sombra", _countdown, _dotSprite, new Color(0f, 0f, 0f, 0.35f));
            GameUi.Stretch(glow.rectTransform);
            glow.rectTransform.offsetMin = new Vector2(-6f, -12f);
            glow.rectTransform.offsetMax = new Vector2(6f, 0f);
            Image disc = NewImage("Fondo", _countdown, _dotSprite, new Color(0.035f, 0.07f, 0.15f, 0.97f));
            GameUi.Stretch(disc.rectTransform);
            Image track = NewImage("Pista", _countdown, _ringSprite, GameUi.WithAlpha(Color.white, 0.14f));
            GameUi.Stretch(track.rectTransform);
            track.rectTransform.offsetMin = new Vector2(8f, 8f);
            track.rectTransform.offsetMax = new Vector2(-8f, -8f);
            _countdownArc = NewImage("Arco", _countdown, _ringSprite, GameColors.Green);
            _countdownArc.type = Image.Type.Filled;
            _countdownArc.fillMethod = Image.FillMethod.Radial360;
            _countdownArc.fillOrigin = (int)Image.Origin360.Top;
            _countdownArc.fillClockwise = true;
            _countdownArc.fillAmount = 1f;
            GameUi.Stretch(_countdownArc.rectTransform);
            _countdownArc.rectTransform.offsetMin = new Vector2(8f, 8f);
            _countdownArc.rectTransform.offsetMax = new Vector2(-8f, -8f);
            _countdownNumber = NewText("Numero", _countdown, "0", countdownSize * 0.42f, Color.white, TextAlignmentOptions.Center, _display);
            _countdownNumber.textWrappingMode = TextWrappingModes.NoWrap;
            GameUi.Stretch(_countdownNumber.rectTransform);
            _countdown.gameObject.SetActive(false);
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
            _resultGroup.interactable = false;
            _resultGroup.blocksRaycasts = false;

            Image glow = NewImage("Halo", _result, _glowSprite, GameUi.WithAlpha(GameColors.Yellow, 0.3f));
            glow.rectTransform.anchorMin = Vector2.zero;
            glow.rectTransform.anchorMax = Vector2.one;
            glow.rectTransform.offsetMin = new Vector2(-80f, -80f);
            glow.rectTransform.offsetMax = new Vector2(80f, 80f);
            Image border = NewImage("Borde", _result, _roundSprite, GameUi.WithAlpha(GameColors.Yellow, 0.75f));
            GameUi.Stretch(border.rectTransform);
            // Opaco: la UI mezcla en espacio lineal y el 7 % del halo amarillo que se
            // veía a través del de la tarjeta lo volvía marrón.
            Image fill = NewImage("Fondo", _result, _roundSprite, GameUi.WithAlpha(GameColors.CardFill, 1f));
            GameUi.Stretch(fill.rectTransform);
            fill.rectTransform.offsetMin = new Vector2(4f, 4f);
            fill.rectTransform.offsetMax = new Vector2(-4f, -4f);

            RectTransform body = NewRect("Contenido", _result);
            body.anchorMin = new Vector2(0f, 1f);
            body.anchorMax = new Vector2(1f, 1f);
            body.pivot = new Vector2(0.5f, 1f);
            VerticalLayoutGroup layout = body.gameObject.AddComponent<VerticalLayoutGroup>();
            layout.padding = new RectOffset(56, 56, 40, 52);
            layout.spacing = 16f;
            layout.childAlignment = TextAnchor.UpperCenter;
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = false;
            body.gameObject.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            _resultEyebrow = NewText("Titulo", body, string.Empty, 34f, Color.white, TextAlignmentOptions.Center, _display);
            _resultEyebrow.characterSpacing = 8f;
            _resultEyebrow.enableAutoSizing = true;
            _resultEyebrow.fontSizeMin = 22f;
            _resultEyebrow.fontSizeMax = 34f;
            _resultEyebrow.textWrappingMode = TextWrappingModes.NoWrap;

            RectTransform titleBox = NewRect("Resultado", body);
            titleBox.gameObject.AddComponent<LayoutElement>().preferredHeight = 150f;
            _resultTitle = NewText("Texto", titleBox, "¡GANASTE!", 128f, Color.white, TextAlignmentOptions.Center, _display);
            _resultTitle.enableVertexGradient = true;
            _resultTitle.textWrappingMode = TextWrappingModes.NoWrap;
            _resultTitle.enableAutoSizing = true;
            _resultTitle.fontSizeMin = 64f;
            _resultTitle.fontSizeMax = 128f;
            GameUi.Stretch(_resultTitle.rectTransform);

            _resultScore = NewText("Marcador", body, string.Empty, 58f, Color.white, TextAlignmentOptions.Center, _display);
            _resultLine = NewText("Frase", body, string.Empty, 38f, GameColors.Muted, TextAlignmentOptions.Center, _bodyFont);
            resultRoot.SetActive(false);
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
                if (canvases[i].isRootCanvas && canvases[i].renderMode == RenderMode.ScreenSpaceCamera
                    && canvases[i].name != "StageBackdrop")
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

        private void RaiseOpened(string gameId)
        {
            Action<string> handler = Opened;
            if (handler == null)
            {
                return;
            }

            try
            {
                handler(gameId);
            }
            catch (Exception ex)
            {
                Debug.LogException(ex, this);
            }
        }

        private void RaiseClosed(string gameId)
        {
            Action<string> handler = Closed;
            if (handler == null)
            {
                return;
            }

            try
            {
                handler(gameId);
            }
            catch (Exception ex)
            {
                Debug.LogException(ex, this);
            }
        }

        private void Log(string message)
        {
            if (logEvents)
            {
                Debug.Log("[Sonia] Pantalla de juegos: " + message, this);
            }
        }

        // ------------------------------------------------------------------
        // Texturas generadas (las de la trivia, más el anillo y el contorno)
        // ------------------------------------------------------------------

        private void CreateSprites()
        {
            if (_roundSprite != null)
            {
                return;
            }

            const int roundSize = 128;
            Texture2D round = MakeTexture("GameRound", roundSize, (x, y) =>
                Mathf.Clamp01(0.5f - RoundedRectDistance(x, y, roundSize, roundSize, 0f, CornerRadius)));
            float roundBorder = CornerRadius + 2f;
            _roundSprite = MakeSprite(round, new Vector4(roundBorder, roundBorder, roundBorder, roundBorder));

            const float stroke = 4f;
            Texture2D frame = MakeTexture("GameFrame", roundSize, (x, y) =>
            {
                float d = RoundedRectDistance(x, y, roundSize, roundSize, 0f, CornerRadius);
                return Mathf.Clamp01(0.5f - (Mathf.Abs(d + (stroke * 0.5f)) - (stroke * 0.5f)));
            });
            _frameSprite = MakeSprite(frame, new Vector4(roundBorder, roundBorder, roundBorder, roundBorder));

            const int glowSize = 256;
            const float glowSpread = 70f;
            Texture2D glow = MakeTexture("GameGlow", glowSize, (x, y) =>
            {
                float d = RoundedRectDistance(x, y, glowSize, glowSize, glowSpread, CornerRadius);
                float t = Mathf.Clamp01(1f - (d / glowSpread));
                return t * t * (3f - (2f * t));
            });
            float glowBorder = glowSpread + CornerRadius + 2f;
            _glowSprite = MakeSprite(glow, new Vector4(glowBorder, glowBorder, glowBorder, glowBorder));

            const int dotSize = 64;
            Texture2D dot = MakeTexture("GameDot", dotSize, (x, y) =>
            {
                float dx = x + 0.5f - (dotSize * 0.5f);
                float dy = y + 0.5f - (dotSize * 0.5f);
                return Mathf.Clamp01((dotSize * 0.5f) - 1f - Mathf.Sqrt((dx * dx) + (dy * dy)) + 0.5f);
            });
            _dotSprite = MakeSprite(dot, Vector4.zero);

            // Anillo: grosor de un 11 % del diámetro, con los bordes suaves.
            const int ringSize = 256;
            Texture2D ring = MakeTexture("GameRing", ringSize, (x, y) =>
            {
                float dx = x + 0.5f - (ringSize * 0.5f);
                float dy = y + 0.5f - (ringSize * 0.5f);
                float r = Mathf.Sqrt((dx * dx) + (dy * dy));
                float outer = (ringSize * 0.5f) - 1f;
                float inner = outer - (ringSize * 0.11f);
                return Mathf.Clamp01(Mathf.Min(outer - r, r - inner) + 0.5f);
            });
            _ringSprite = MakeSprite(ring, Vector4.zero);

            const int markSize = 128;
            _checkSprite = MakeSprite(MakeMark("GameCheck", markSize, GameColors.Green, true), Vector4.zero);
            _crossSprite = MakeSprite(MakeMark("GameCross", markSize, GameColors.Red, false), Vector4.zero);

            // Destello de cuatro puntas (astroide).
            const int sparkleSize = 64;
            Texture2D sparkle = MakeTexture("GameSparkle", sparkleSize, (x, y) =>
            {
                float dx = Mathf.Abs((x + 0.5f - (sparkleSize * 0.5f)) / (sparkleSize * 0.5f));
                float dy = Mathf.Abs((y + 0.5f - (sparkleSize * 0.5f)) / (sparkleSize * 0.5f));
                float shape = Mathf.Pow(dx, 0.5f) + Mathf.Pow(dy, 0.5f);
                return Mathf.Clamp01((1f - shape) * 6f);
            });
            _sparkleSprite = MakeSprite(sparkle, Vector4.zero);

            // Estrella de cinco puntas.
            const int starSize = 128;
            Texture2D star = MakeTexture("GameStar", starSize, (x, y) =>
            {
                float px = (x + 0.5f - (starSize * 0.5f)) / (starSize * 0.5f);
                float py = (y + 0.5f - (starSize * 0.5f)) / (starSize * 0.5f);
                return Mathf.Clamp01((-StarDistance(px, py) * starSize * 0.5f) + 0.5f);
            });
            _starSprite = MakeSprite(star, Vector4.zero);

            // Papelito: rectángulo con las esquinas algo redondeadas.
            const int pieceSize = 32;
            Texture2D piece = MakeTexture("GamePiece", pieceSize, (x, y) =>
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
                    float d = check
                        ? Mathf.Min(
                            SegmentDistance(px, py, -0.42f, 0.02f, -0.12f, -0.3f),
                            SegmentDistance(px, py, -0.12f, -0.3f, 0.46f, 0.34f))
                        : Mathf.Min(
                            SegmentDistance(px, py, -0.34f, -0.34f, 0.34f, 0.34f),
                            SegmentDistance(px, py, -0.34f, 0.34f, 0.34f, -0.34f));
                    float mark = Mathf.Clamp01((((stroke / half) - d) * half) + 0.5f);
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

        private Texture2D MakeTexture(string name, int size, Func<int, int, float> alpha)
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
