// Aviso de espera en pantalla (mensaje busy, docs/protocolo.md): «la gente es
// bruta y se desespera» (Jean, 10 de octubre de 2026). Mientras Sonia espera
// algo que el visitante no ve (el backend piensa o busca en internet, el juez de
// un juego mira la foto, la cámara arranca), sale arriba una pastilla grande en
// el azul royal del DevFest 2026 con tres puntos que saltan, «SONNIA» y el texto
// que manda el orquestador («Pensando…»).
//
// Se monta por código en Play (lo añade SoniaBootstrap) en un Canvas propio
// anidado en el del HUD y ordenado por encima de todo lo demás: escenario,
// juegos, vista en vivo, confeti y subtítulos.
//
// Sitio, elegido con capturas (docs/unity.md, «Aviso de espera»): la franja de
// arriba del todo, la del logo y el QR, que StageScreen aparta mientras se ve.
// Queda por encima de la tarjeta de los juegos y de la vista en vivo (empiezan
// al 10,5 % del alto) y de la coronilla de Sonnia en todos sus encuadres, así
// que no tapa ni su cara ni sus manos.
//
// Tiempos: entra en unos 0,14 s, se queda al menos 0,6 s aunque llegue antes el
// off (para que no parpadee), cambia el texto en el sitio y sale en 0,2 s. Si se
// cae el orquestador se retira sola. Nada de aquí lanza: sin HUD monta su propio
// Canvas y sin orquestador no sale (o sale con Show, para probar).

using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>La pastilla de «Sonnia está en ello» que pide el mensaje <c>busy</c>.</summary>
    [DisallowMultipleComponent]
    public class BusyIndicator : MonoBehaviour
    {
        private const string HudCanvasName = "SoniaHUD";
        private const string ResourceFolder = "Stage/";

        [Header("Textos")]
        [SerializeField]
        [Tooltip("Etiqueta sobre el texto: quién está en ello.")]
        private string speaker = "SONNIA";

        [Header("Tiempos (segundos)")]
        [SerializeField]
        [Range(0.05f, 0.5f)]
        [Tooltip("Entrada: fundido, un poco de escala y una caída corta.")]
        private float enterSeconds = 0.14f;

        [SerializeField]
        [Range(0.05f, 0.6f)]
        [Tooltip("Salida corta.")]
        private float exitSeconds = 0.2f;

        [SerializeField]
        [Range(0f, 3f)]
        [Tooltip("Lo mínimo que se queda aunque llegue antes el off: así no parpadea.")]
        private float minVisibleSeconds = 0.6f;

        [SerializeField]
        [Range(10f, 600f)]
        [Tooltip("Red de seguridad: si en este tiempo no llega el off, se retira sola.")]
        private float maxVisibleSeconds = 90f;

        [Header("Diseño (píxeles de la referencia 1080x1920)")]
        [SerializeField]
        [Tooltip("Distancia del borde de arriba de la pantalla al de la pastilla.")]
        private float top = 40f;

        [SerializeField]
        [Range(32f, 72f)]
        [Tooltip("Tamaño del texto (se encoge si no cabe).")]
        private float textSize = 52f;

        [SerializeField]
        [Tooltip("Ancho máximo de la pastilla.")]
        private float maxWidth = 1008f;

        [SerializeField]
        [Tooltip("Orden de su Canvas por encima del del HUD: delante de todo.")]
        private int sortingAboveHud = 50;

        // Azul royal del arte del DevFest 2026 (el del fondo a media altura, algo
        // más hondo que el de arriba para que la pastilla se separe de él) y el
        // celeste de su brillo (scripts/stage_assets.py).
        private static readonly Color Royal = new Color32(37, 87, 172, 255);
        private static readonly Color Sky = new Color32(143, 208, 255, 255);

        private const float PillHeight = 124f;
        private const float PadLeft = 40f;
        private const float PadRight = 46f;
        private const float DotSize = 20f;
        private const float DotGap = 12f;
        private const float DotsWidth = (DotSize * 3f) + (DotGap * 2f);
        private const float DotsGapToText = 28f;
        private const float MinTextSize = 34f;

        private SoniaClient _client;
        private StageScreen _stage;
        private bool _built;
        private bool _failed;
        private float _startedAt;

        private Canvas _canvas;
        private RectTransform _pill;
        private CanvasGroup _group;
        private TextMeshProUGUI _label;
        private TextMeshProUGUI _message;
        private readonly List<RectTransform> _dots = new List<RectTransform>(3);
        private readonly List<Image> _dotImages = new List<Image>(3);
        private Sprite _round;
        private Sprite _shadow;
        private Texture2D _roundTexture;

        // Estado: lo que pide el orquestador y lo que se ve.
        private bool _wanted;
        private string _text = string.Empty;
        private string _pendingText;
        private float _wantedSince = -100f;
        private float _shownAt = -100f;
        private float _visibility;
        private float _width;
        private float _targetWidth;
        private float _pulse;

        /// <summary>Cierto mientras la pastilla se ve, aunque sea a medias (entrando o saliendo).</summary>
        public bool IsVisible
        {
            get { return _visibility > 0.001f || _wanted; }
        }

        /// <summary>Cierto mientras el orquestador la pide (o se pidió con <see cref="Show"/>).</summary>
        public bool IsOn
        {
            get { return _wanted; }
        }

        /// <summary>Lo que dice ahora la pastilla.</summary>
        public string CurrentText
        {
            get { return _text; }
        }

        /// <summary>De 0 (fuera) a 1 (entera): cuánto se ve.</summary>
        public float Visibility
        {
            get { return _visibility; }
        }

        private void Awake()
        {
            _client = GetComponentInChildren<SoniaClient>(true);
            _stage = GetComponentInChildren<StageScreen>(true);
        }

        private void OnEnable()
        {
            if (_client == null)
            {
                return;
            }

            _client.OnBusy += HandleBusy;
            _client.OnDisconnected += HandleDisconnected;
            _client.OnHello += HandleHello;
        }

        private void OnDisable()
        {
            if (_client == null)
            {
                return;
            }

            _client.OnBusy -= HandleBusy;
            _client.OnDisconnected -= HandleDisconnected;
            _client.OnHello -= HandleHello;
        }

        private void Start()
        {
            _startedAt = Time.unscaledTime;
        }

        private void OnDestroy()
        {
            if (_roundTexture != null)
            {
                Destroy(_roundTexture);
            }
        }

        // ------------------------------------------------------------------
        // API (también para probar sin orquestador)
        // ------------------------------------------------------------------

        /// <summary>Enseña la pastilla con ese texto, o lo cambia en el sitio si ya estaba.</summary>
        public void Show(string text)
        {
            string clean = Clean(text);
            float now = Time.unscaledTime;
            if (!_wanted)
            {
                // Cada on cuenta su mínimo desde ahora, también si llega mientras sale.
                _wantedSince = now;
                _shownAt = now;
            }

            _wanted = true;
            if (clean != _text)
            {
                _pendingText = clean;
            }
        }

        /// <summary>Pide quitarla: se va en cuanto lleve <see cref="minVisibleSeconds"/> a la vista.</summary>
        public void Hide()
        {
            _wanted = false;
        }

        // ------------------------------------------------------------------
        // Protocolo
        // ------------------------------------------------------------------

        private void HandleBusy(BusyMessage message)
        {
            if (message == null)
            {
                return;
            }

            if (message.On)
            {
                Show(message.Text);
            }
            else
            {
                Hide();
            }
        }

        private void HandleDisconnected()
        {
            // Sin orquestador nadie mandará el off; al volver repite el aviso si sigue.
            Hide();
        }

        private void HandleHello(HelloMessage message)
        {
            Hide();
        }

        // ------------------------------------------------------------------
        // Bucle
        // ------------------------------------------------------------------

        private void Update()
        {
            try
            {
                Tick();
            }
            catch (Exception ex)
            {
                // Un fallo aquí no puede tumbar nada más de la pantalla: fuera el aviso.
                if (!_failed)
                {
                    _failed = true;
                    Debug.LogException(ex, this);
                }

                _wanted = false;
                if (_group != null)
                {
                    _group.alpha = 0f;
                }
            }
        }

        private void Tick()
        {
            float now = Time.unscaledTime;
            float dt = Mathf.Min(Time.unscaledDeltaTime, 0.1f);
            if (!_built)
            {
                // Con las fuentes de la pantalla del stand: espera a que se monte (o a
                // que pase un momento sin ella).
                bool stageReady = _stage == null || _stage.IsBuilt || !_stage.isActiveAndEnabled;
                if (!stageReady && now - _startedAt < 3f && !_wanted)
                {
                    return;
                }

                Build();
                if (!_built)
                {
                    return;
                }
            }

            if (_wanted && now - _wantedSince > maxVisibleSeconds)
            {
                Debug.LogWarning("[Sonia] El aviso de espera lleva " + maxVisibleSeconds.ToString("0")
                                 + " s sin retirarse: lo quito.", this);
                _wanted = false;
            }

            if (_pendingText != null)
            {
                bool inPlace = _visibility > 0.5f;
                SetText(_pendingText);
                _pendingText = null;
                if (inPlace)
                {
                    _pulse = 1f;
                }
                else
                {
                    _width = _targetWidth;
                }
            }

            // Se queda al menos minVisibleSeconds desde que empezó a verse.
            bool show = _wanted || (_visibility > 0.001f && now - _shownAt < minVisibleSeconds);
            float previous = _visibility;
            if (show)
            {
                if (previous <= 0.001f)
                {
                    _shownAt = now;
                    _width = _targetWidth;
                    Debug.Log("[Sonia] Aviso de espera: «" + _text + "»", this);
                }

                _visibility = Mathf.MoveTowards(_visibility, 1f, dt / Mathf.Max(0.01f, enterSeconds));
            }
            else
            {
                _visibility = Mathf.MoveTowards(_visibility, 0f, dt / Mathf.Max(0.01f, exitSeconds));
                if (previous > 0.001f && _visibility <= 0.001f)
                {
                    Debug.Log("[Sonia] Aviso de espera retirado tras " + (now - _shownAt).ToString("0.00") + " s.", this);
                }
            }

            Apply(now, dt, show);
        }

        private void Apply(float now, float dt, bool entering)
        {
            bool visible = _visibility > 0.001f;
            if (_pill.gameObject.activeSelf != visible)
            {
                _pill.gameObject.SetActive(visible);
            }

            if (!visible)
            {
                return;
            }

            // Entrada: cae unos píxeles, crece con un pequeño rebote y se funde.
            // Salida: sube un poco, encoge y se funde, más corta.
            float v = _visibility;
            float alpha;
            float scale;
            float drop;
            if (entering)
            {
                alpha = Mathf.Clamp01(v * 1.6f);
                scale = Mathf.LerpUnclamped(0.86f, 1f, EaseOutBack(v));
                drop = -18f * (1f - EaseOutCubic(v));
            }
            else
            {
                alpha = v;
                scale = Mathf.Lerp(0.94f, 1f, v);
                drop = 10f * (1f - v);
            }

            // Al cambiar el texto en el sitio: un latido y el ancho que se acomoda.
            if (_pulse > 0f)
            {
                _pulse = Mathf.Max(0f, _pulse - (dt / 0.25f));
                scale *= 1f + (0.045f * Mathf.Sin(_pulse * Mathf.PI));
            }

            _width = Mathf.Abs(_width - _targetWidth) < 0.5f
                ? _targetWidth
                : Mathf.Lerp(_width, _targetWidth, 1f - Mathf.Exp(-dt * 22f));

            _group.alpha = alpha;
            _pill.localScale = new Vector3(scale, scale, 1f);
            _pill.anchoredPosition = new Vector2(0f, -top - drop);
            _pill.sizeDelta = new Vector2(_width, PillHeight);

            // Tres puntos que saltan uno detrás de otro.
            for (int i = 0; i < _dots.Count; i++)
            {
                float phase = Mathf.Repeat((now * 1.5f) - (i * 0.16f), 1f);
                float up = phase < 0.5f ? Mathf.Sin(phase * 2f * Mathf.PI) : 0f;
                _dots[i].anchoredPosition = new Vector2(
                    (DotSize * 0.5f) + (i * (DotSize + DotGap)),
                    -4f + (16f * up));
                Color color = Color.Lerp(Sky, Color.white, up);
                color.a = 0.75f + (0.25f * up);
                _dotImages[i].color = color;
            }
        }

        private void SetText(string text)
        {
            // TextMeshPro mide mejor con el objeto activo: se enciende un momento.
            bool wasActive = _pill.gameObject.activeSelf;
            if (!wasActive)
            {
                _pill.gameObject.SetActive(true);
            }

            try
            {
                Measure(text);
            }
            finally
            {
                if (!wasActive)
                {
                    _pill.gameObject.SetActive(false);
                }
            }
        }

        private void Measure(string text)
        {
            _text = text;
            _message.fontSize = textSize;
            _message.text = text;
            Vector2 preferred = _message.GetPreferredValues(text, 10000f, 0f);
            float labelWidth = _label.GetPreferredValues(_label.text, 10000f, 0f).x;
            float room = maxWidth - PadLeft - DotsWidth - DotsGapToText - PadRight;
            float textWidth = preferred.x;
            if (textWidth > room && textWidth > 0f)
            {
                _message.fontSize = Mathf.Max(MinTextSize, textSize * room / textWidth);
                textWidth = Mathf.Min(room, _message.GetPreferredValues(text, 10000f, 0f).x);
            }

            float content = Mathf.Max(textWidth, labelWidth);
            _targetWidth = Mathf.Ceil(PadLeft + DotsWidth + DotsGapToText + content + PadRight);
        }

        // ------------------------------------------------------------------
        // Montaje
        // ------------------------------------------------------------------

        private void Build()
        {
            _built = true;
            Canvas host = ResolveCanvas();
            int layer = host != null ? host.gameObject.layer : LayerMask.NameToLayer("UI");
            if (layer < 0)
            {
                layer = 0;
            }

            GameObject canvasObject = new GameObject("AvisoEspera", typeof(RectTransform));
            canvasObject.layer = layer;
            if (host != null)
            {
                // Canvas anidado con su propio orden: delante de todo lo del HUD, se
                // añada lo que se añada después.
                canvasObject.transform.SetParent(host.transform, false);
                Stretch((RectTransform)canvasObject.transform);
                _canvas = canvasObject.AddComponent<Canvas>();
                _canvas.overrideSorting = true;
                _canvas.sortingLayerID = host.sortingLayerID;
                _canvas.sortingOrder = host.sortingOrder + sortingAboveHud;
            }
            else
            {
                // Sin HUD (otra escena): un Canvas propio encima de todo.
                canvasObject.transform.SetParent(transform, false);
                _canvas = canvasObject.AddComponent<Canvas>();
                _canvas.renderMode = RenderMode.ScreenSpaceOverlay;
                _canvas.sortingOrder = 1000;
                CanvasScaler scaler = canvasObject.AddComponent<CanvasScaler>();
                scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
                scaler.referenceResolution = new Vector2(1080f, 1920f);
                scaler.matchWidthOrHeight = 0.5f;
            }

            RectTransform root = (RectTransform)canvasObject.transform;
            LoadSprites();
            TMP_FontAsset display = _stage != null && _stage.DisplayFont != null ? _stage.DisplayFont : TMP_Settings.defaultFontAsset;
            TMP_FontAsset mono = _stage != null && _stage.MonoFont != null ? _stage.MonoFont : display;

            _pill = NewRect("Pastilla", root, layer);
            _pill.anchorMin = new Vector2(0.5f, 1f);
            _pill.anchorMax = new Vector2(0.5f, 1f);
            _pill.pivot = new Vector2(0.5f, 1f);
            _pill.anchoredPosition = new Vector2(0f, -top);
            _pill.sizeDelta = new Vector2(480f, PillHeight);
            _group = _pill.gameObject.AddComponent<CanvasGroup>();
            _group.interactable = false;
            _group.blocksRaycasts = false;
            _group.alpha = 0f;

            // Sombra suave, borde blanco y la cara en azul royal, como el bocadillo
            // de la invitación pero en el color del arte del DevFest.
            if (_shadow != null)
            {
                Image shadow = NewImage("Sombra", _pill, _shadow, new Color(0f, 0f, 0f, 0.5f), layer);
                shadow.type = Image.Type.Sliced;
                Stretch(shadow.rectTransform);
                shadow.rectTransform.offsetMin = new Vector2(-54f, -74f);
                shadow.rectTransform.offsetMax = new Vector2(54f, 34f);
            }

            Image border = NewImage("Borde", _pill, null, new Color(1f, 1f, 1f, 0.92f), layer);
            ConfigureRound(border, (PillHeight * 0.5f) + 5f);
            Stretch(border.rectTransform);
            border.rectTransform.offsetMin = new Vector2(-5f, -5f);
            border.rectTransform.offsetMax = new Vector2(5f, 5f);

            Image face = NewImage("Cara", _pill, null, Royal, layer);
            ConfigureRound(face, PillHeight * 0.5f);
            Stretch(face.rectTransform);

            // Los puntos, a la izquierda y centrados en el alto.
            RectTransform dots = NewRect("Puntos", _pill, layer);
            dots.anchorMin = new Vector2(0f, 0.5f);
            dots.anchorMax = new Vector2(0f, 0.5f);
            dots.pivot = new Vector2(0f, 0.5f);
            dots.anchoredPosition = new Vector2(PadLeft, 0f);
            dots.sizeDelta = new Vector2(DotsWidth, 40f);
            for (int i = 0; i < 3; i++)
            {
                Image dot = NewImage("Punto" + (i + 1), dots, null, Sky, layer);
                ConfigureRound(dot, DotSize * 0.5f);
                RectTransform rect = dot.rectTransform;
                rect.anchorMin = new Vector2(0f, 0.5f);
                rect.anchorMax = new Vector2(0f, 0.5f);
                rect.pivot = new Vector2(0.5f, 0.5f);
                rect.sizeDelta = new Vector2(DotSize, DotSize);
                rect.anchoredPosition = new Vector2((DotSize * 0.5f) + (i * (DotSize + DotGap)), 0f);
                _dots.Add(rect);
                _dotImages.Add(dot);
            }

            // «SONNIA» pequeño y espaciado encima del texto, como en la invitación.
            float textLeft = PadLeft + DotsWidth + DotsGapToText;
            _label = NewText("Quien", _pill, mono, 21f, Sky, layer);
            _label.text = speaker;
            _label.characterSpacing = 14f;
            _label.alignment = TextAlignmentOptions.BottomLeft;
            PlaceLeft(_label.rectTransform, textLeft, 18f, 26f);

            _message = NewText("Texto", _pill, display, textSize, Color.white, layer);
            _message.alignment = TextAlignmentOptions.TopLeft;
            _message.characterSpacing = -1f;
            PlaceLeft(_message.rectTransform, textLeft, 44f, 66f);

            SetText(string.IsNullOrEmpty(_pendingText) ? "Pensando…" : _pendingText);
            _width = _targetWidth;
            _pill.gameObject.SetActive(false);
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

            return null;
        }

        private void LoadSprites()
        {
            _round = LoadSprite("stage-round", new Vector4(64f, 64f, 64f, 64f));
            _shadow = LoadSprite("stage-shadow", new Vector4(112f, 112f, 112f, 112f));
            if (_round == null)
            {
                // Sin los recursos de la pantalla: un círculo generado, cortado en 9.
                const int size = 128;
                _roundTexture = new Texture2D(size, size, TextureFormat.RGBA32, false);
                _roundTexture.wrapMode = TextureWrapMode.Clamp;
                Color32[] pixels = new Color32[size * size];
                float radius = size * 0.5f;
                for (int y = 0; y < size; y++)
                {
                    for (int x = 0; x < size; x++)
                    {
                        float dx = x + 0.5f - radius;
                        float dy = y + 0.5f - radius;
                        float d = Mathf.Sqrt((dx * dx) + (dy * dy));
                        byte a = (byte)Mathf.RoundToInt(255f * Mathf.Clamp01(radius - d));
                        pixels[(y * size) + x] = new Color32(255, 255, 255, a);
                    }
                }

                _roundTexture.SetPixels32(pixels);
                _roundTexture.Apply(false, true);
                _round = Sprite.Create(
                    _roundTexture,
                    new Rect(0f, 0f, size, size),
                    new Vector2(0.5f, 0.5f),
                    100f,
                    0,
                    SpriteMeshType.FullRect,
                    new Vector4(64f, 64f, 64f, 64f));
            }
        }

        /// <summary>Sprite de Resources/Stage (como StageScreen). Si se importó como textura, se hace aquí.</summary>
        private static Sprite LoadSprite(string name, Vector4 border)
        {
            Sprite sprite = Resources.Load<Sprite>(ResourceFolder + name);
            if (sprite != null)
            {
                return sprite;
            }

            Texture2D texture = Resources.Load<Texture2D>(ResourceFolder + name);
            if (texture == null)
            {
                return null;
            }

            return Sprite.Create(
                texture,
                new Rect(0f, 0f, texture.width, texture.height),
                new Vector2(0.5f, 0.5f),
                100f,
                0,
                SpriteMeshType.FullRect,
                border);
        }

        // ------------------------------------------------------------------
        // Piezas
        // ------------------------------------------------------------------

        private static RectTransform NewRect(string name, Transform parent, int layer)
        {
            GameObject go = new GameObject(name, typeof(RectTransform));
            go.layer = layer;
            go.transform.SetParent(parent, false);
            return (RectTransform)go.transform;
        }

        private static Image NewImage(string name, RectTransform parent, Sprite sprite, Color color, int layer)
        {
            RectTransform rect = NewRect(name, parent, layer);
            Image image = rect.gameObject.AddComponent<Image>();
            image.sprite = sprite;
            image.color = color;
            image.raycastTarget = false;
            return image;
        }

        private static TextMeshProUGUI NewText(string name, RectTransform parent, TMP_FontAsset font, float size, Color color, int layer)
        {
            RectTransform rect = NewRect(name, parent, layer);
            TextMeshProUGUI text = rect.gameObject.AddComponent<TextMeshProUGUI>();
            if (font != null)
            {
                text.font = font;
            }

            text.fontSize = size;
            text.color = color;
            text.raycastTarget = false;
            text.richText = false;
            text.textWrappingMode = TextWrappingModes.NoWrap;
            text.overflowMode = TextOverflowModes.Overflow;
            return text;
        }

        /// <summary>Rectángulo redondeado del sprite de radio 64 con el radio pedido.</summary>
        private void ConfigureRound(Image image, float radius)
        {
            image.sprite = _round;
            image.type = Image.Type.Sliced;
            image.pixelsPerUnitMultiplier = 64f / Mathf.Max(1f, radius);
        }

        private static void Stretch(RectTransform rect)
        {
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
        }

        /// <summary>Franja a la izquierda de la pastilla, desde <paramref name="left"/> hasta el borde derecho.</summary>
        private static void PlaceLeft(RectTransform rect, float left, float topOffset, float height)
        {
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(1f, 1f);
            rect.pivot = new Vector2(0f, 1f);
            rect.offsetMin = new Vector2(left, -topOffset - height);
            rect.offsetMax = new Vector2(0f, -topOffset);
        }

        /// <summary>Sin espacios de más ni saltos de línea; vacío, «Pensando…».</summary>
        private static string Clean(string text)
        {
            if (string.IsNullOrEmpty(text))
            {
                return "Pensando…";
            }

            string clean = text.Replace('\n', ' ').Replace('\r', ' ').Trim();
            return clean.Length == 0 ? "Pensando…" : clean;
        }

        private static float EaseOutBack(float t)
        {
            const float c1 = 1.70158f;
            const float c3 = c1 + 1f;
            float x = t - 1f;
            return 1f + (c3 * x * x * x) + (c1 * x * x);
        }

        private static float EaseOutCubic(float t)
        {
            float x = 1f - t;
            return 1f - (x * x * x);
        }
    }
}
