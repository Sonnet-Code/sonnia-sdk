// Pantalla del stand, diseño F («Navy en vivo»): fondo navy de la marca fijo a
// la pantalla, logo arriba a la izquierda con la etiqueta «SONIA · EN VIVO», la
// tarjeta blanca con el QR de Sonnet Code arriba a la derecha, la invitación a
// hablar abajo mientras nadie conversa y, cuando sí, subtítulos grandes estilo
// karaoke con lo que dijo el visitante en una pastilla encima.
//
// Se construye por código en Play, como la trivia y el letrero del modo Fuera:
// el fondo va en un Canvas propio que dibuja la cámara principal a varios metros
// (detrás de Sonia y con el mismo postprocesado que la escena) y lo demás dentro
// del Canvas del HUD (sin postprocesado). Recursos en Resources/Stage, generados
// con scripts/stage_assets.py; el diseño está en el canvas «Pantalla de Sonia
// 9:16» (columna F).
//
// Reglas:
//  - La invitación solo sale si Sonia puede conversar (stage_mode, talk), está en
//    reposo, no hay subtítulos recientes y no hay imagen, trivia ni modo Fuera.
//  - Los subtítulos de Sonia crecen con su voz: lo que acaba de llegar sale
//    atenuado y se aclara enseguida. Si la frase llega entera en speech_start
//    (las frases grabadas), lo que aún no ha dicho se ve atenuado y se va
//    encendiendo al ritmo estimado de la voz: el karaoke del diseño.
//  - Con una imagen o la trivia en la franja alta, el QR y la etiqueta se apartan.

using System.Collections.Generic;
using System.Text;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Monta la pantalla del stand (diseño F) y decide qué se ve en cada momento.</summary>
    [DisallowMultipleComponent]
    public class StageScreen : MonoBehaviour
    {
        private const string HudCanvasName = "SoniaHUD";
        private const string ResourceFolder = "Stage/";

        [Header("Textos")]
        [SerializeField]
        private string invitation = "Acércate y pregúntame lo que quieras.";

        [SerializeField]
        private string invitationHint = "Solo háblame: no hay que tocar nada.";

        [SerializeField]
        private string liveLabel = "SONIA · EN VIVO";

        [SerializeField]
        private string qrTitle = "Sonnet Code";

        [SerializeField]
        private string qrCaption = "¡Conoce más de nosotros!";

        [Header("Fondo")]
        [SerializeField]
        [Tooltip("Distancia del fondo a la cámara, en metros. Tiene que quedar detrás de todo lo de la escena y antes del plano lejano de la cámara.")]
        private float backdropDistance = 12f;

        [SerializeField]
        [Tooltip("Tinte del fondo. El tonemapping de la escena lo oscurece un poco; por encima de blanco lo compensa.")]
        private Color backdropTint = Color.white;

        [Header("Subtítulos")]
        [SerializeField]
        [Range(32f, 96f)]
        private float subtitleSize = 64f;

        [SerializeField]
        [Tooltip("Caracteres como mucho en pantalla: de una frase larga se ve el final.")]
        private int maxSubtitleCharacters = 110;

        [SerializeField]
        [Range(0.05f, 2f)]
        [Tooltip("Segundos que tarda una palabra nueva en pasar de atenuada a blanca.")]
        private float revealSeconds = 0.45f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Opacidad de lo que aún no ha dicho (o acaba de llegar).")]
        private float dimAlpha = 0.42f;

        [SerializeField]
        [Range(5f, 40f)]
        [Tooltip("Ritmo estimado de la voz en las frases que llegan enteras (caracteres por segundo).")]
        private float spokenCharactersPerSecond = 15f;

        [SerializeField]
        [Range(10f, 80f)]
        [Tooltip("Como mucho tan deprisa se encienden los trozos de texto que llegan de golpe.")]
        private float streamCharactersPerSecond = 28f;

        [SerializeField]
        [Range(1f, 20f)]
        [Tooltip("Segundos que se quedan los subtítulos cuando ya nadie habla.")]
        private float lingerSeconds = 6f;

        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("Segundos de calma antes de que vuelva la invitación a hablar.")]
        private float invitationDelay = 1.5f;

        // Colores de la marca (landing de sonnetcode.com).
        private static readonly Color Navy = new Color32(20, 39, 82, 255);
        private static readonly Color Ink = new Color32(62, 81, 119, 255);
        private static readonly Color Brand = new Color32(3, 113, 245, 255);
        private static readonly Color Accent = new Color32(113, 191, 255, 255);
        private static readonly Color Dark = new Color32(11, 19, 34, 255);

        private SoniaClient _client;
        private Canvas _hud;
        private ImagePanelController _imagePanel;
        private TriviaController _trivia;
        private PresenceController _presence;
        private bool _built;

        private TMP_FontAsset _display;
        private TMP_FontAsset _semibold;
        private TMP_FontAsset _mono;
        private Sprite _round;
        private Sprite _shadow;
        private Sprite _glow;

        private CanvasGroup _topGroup;
        private CanvasGroup _invitationGroup;
        private RectTransform _invitationRect;
        private CanvasGroup _subtitleGroup;
        private CanvasGroup _visitorGroup;
        private TextMeshProUGUI _visitorText;
        private LayoutElement _visitorTextLayout;
        private TextMeshProUGUI _soniaText;
        private Image _liveGlow;

        // Estado de la conversación.
        private bool _talk = true;
        private bool _subtitlesOn = true;
        private string _state = AvatarStateNames.Idle;
        private float _lastActivity = -100f;

        // Frase de Sonia en curso: texto y, por carácter, cuándo se enciende.
        private string _sonia = string.Empty;
        private readonly List<float> _revealAt = new List<float>();
        private int _utterance = -1;
        private bool _speaking;
        private string _pendingText;
        private bool _soniaDirty;

        private string _visitor = string.Empty;
        private bool _visitorDirty;

        private readonly StringBuilder _builder = new StringBuilder(256);

        /// <summary>Cierto cuando la pantalla ya está montada.</summary>
        public bool IsBuilt
        {
            get { return _built; }
        }

        private void Awake()
        {
            _client = GetComponentInChildren<SoniaClient>(true);
            _imagePanel = GetComponentInChildren<ImagePanelController>(true);
        }

        private void OnEnable()
        {
            if (_client == null)
            {
                return;
            }

            _client.OnState += HandleState;
            _client.OnTranscript += HandleTranscript;
            _client.OnSpeechStart += HandleSpeechStart;
            _client.OnAudioFrame += HandleAudioFrame;
            _client.OnSpeechEnd += HandleSpeechEnd;
            _client.OnStopSpeaking += HandleStopSpeaking;
            _client.OnSetSubtitles += HandleSetSubtitles;
            _client.OnStageMode += HandleStageMode;
            _client.OnDisconnected += HandleDisconnected;
        }

        private void OnDisable()
        {
            if (_client == null)
            {
                return;
            }

            _client.OnState -= HandleState;
            _client.OnTranscript -= HandleTranscript;
            _client.OnSpeechStart -= HandleSpeechStart;
            _client.OnAudioFrame -= HandleAudioFrame;
            _client.OnSpeechEnd -= HandleSpeechEnd;
            _client.OnStopSpeaking -= HandleStopSpeaking;
            _client.OnSetSubtitles -= HandleSetSubtitles;
            _client.OnStageMode -= HandleStageMode;
            _client.OnDisconnected -= HandleDisconnected;
        }

        private void Start()
        {
            // La trivia y la presencia las añade SoniaBootstrap por código en su Awake.
            _trivia = GetComponentInChildren<TriviaController>(true);
            _presence = GetComponentInChildren<PresenceController>(true);
            Build();
        }

        // ------------------------------------------------------------------
        // Pruebas sin orquestador (capturas desde el editor, sin gastar GPT-Live)
        // ------------------------------------------------------------------

        /// <summary>Como si llegara un <c>transcript</c> (rol <c>user</c> o <c>assistant</c>).</summary>
        public void SimulateTranscript(string role, string text, bool final)
        {
            HandleTranscript(new TranscriptMessage { Role = role, Text = text, Final = final });
        }

        /// <summary>Como si empezara una frase de Sonia (con el texto entero si es grabada).</summary>
        public void SimulateSpeechStart(int utterance, string text)
        {
            HandleSpeechStart(new SpeechStartMessage { UtteranceId = utterance, Text = text ?? string.Empty });
        }

        /// <summary>Como si llegara audio de esa frase.</summary>
        public void SimulateAudio(int utterance)
        {
            HandleAudioFrame(new AudioFrame { UtteranceId = utterance });
        }

        /// <summary>Como si terminara esa frase.</summary>
        public void SimulateSpeechEnd(int utterance)
        {
            HandleSpeechEnd(new SpeechEndMessage { UtteranceId = utterance });
        }

        /// <summary>Como si llegara un <c>state</c> (idle, listening, thinking o speaking).</summary>
        public void SimulateState(string state)
        {
            HandleState(new StateMessage { State = state });
        }

        /// <summary>Como si llegara <c>stage_mode</c>.</summary>
        public void SimulateStageMode(bool talk)
        {
            HandleStageMode(new StageModeMessage { Talk = talk });
        }

        // ------------------------------------------------------------------
        // Eventos del protocolo
        // ------------------------------------------------------------------

        private void HandleState(StateMessage message)
        {
            if (message != null)
            {
                _state = message.State;
                if (_state != AvatarStateNames.Idle)
                {
                    _lastActivity = Time.time;
                }
            }
        }

        private void HandleStageMode(StageModeMessage message)
        {
            if (message != null)
            {
                _talk = message.Talk;
            }
        }

        private void HandleSetSubtitles(SetSubtitlesMessage message)
        {
            if (message == null)
            {
                return;
            }

            _subtitlesOn = message.Enabled;
            if (!_subtitlesOn)
            {
                ClearSubtitles();
            }
        }

        private void HandleDisconnected()
        {
            _speaking = false;
            _pendingText = null;
        }

        private void HandleTranscript(TranscriptMessage message)
        {
            if (message == null || !_subtitlesOn)
            {
                return;
            }

            float now = Time.time;
            if (message.Role == "assistant")
            {
                if (!string.IsNullOrEmpty(message.Text))
                {
                    SetSoniaText(message.Text, now, streaming: true);
                }

                return;
            }

            string text = Clean(message.Text);
            if (string.IsNullOrEmpty(text))
            {
                return;
            }

            // Una pregunta nueva con Sonia callada abre otro intercambio: fuera la
            // respuesta anterior.
            if (!_speaking && text != _visitor)
            {
                SetSonia(string.Empty);
            }

            _visitor = text;
            _visitorDirty = true;
            _lastActivity = now;
        }

        private void HandleSpeechStart(SpeechStartMessage message)
        {
            if (message == null || !_subtitlesOn)
            {
                return;
            }

            _utterance = message.UtteranceId;
            _speaking = true;
            _lastActivity = Time.time;
            SetSonia(string.Empty);

            // Si llega entera (frases grabadas), se enseña con el primer audio, no
            // antes: el subtítulo va con la voz.
            _pendingText = string.IsNullOrEmpty(message.Text) ? null : Clean(message.Text);
        }

        private void HandleAudioFrame(AudioFrame frame)
        {
            if (frame.UtteranceId < _utterance)
            {
                return;
            }

            float now = Time.time;
            _lastActivity = now;
            if (_pendingText != null)
            {
                string text = _pendingText;
                _pendingText = null;
                SetSoniaText(text, now, streaming: false);
            }
        }

        private void HandleSpeechEnd(SpeechEndMessage message)
        {
            if (message == null || message.UtteranceId != _utterance)
            {
                return;
            }

            FinishUtterance();
        }

        private void HandleStopSpeaking(StopSpeakingMessage message)
        {
            FinishUtterance();
        }

        /// <summary>La frase terminó o se cortó: lo que quedaba por encender se enciende ya, rápido.</summary>
        private void FinishUtterance()
        {
            float now = Time.time;
            _speaking = false;
            _pendingText = null;
            _lastActivity = now;
            float next = now;
            for (int i = 0; i < _revealAt.Count; i++)
            {
                if (_revealAt[i] > next)
                {
                    next += 1f / 90f;
                    _revealAt[i] = next;
                }
            }

            _soniaDirty = true;
        }

        // ------------------------------------------------------------------
        // Texto de Sonia
        // ------------------------------------------------------------------

        /// <summary>
        /// Pone el texto de la frase en curso. Si amplía el que había, solo lo nuevo
        /// se va encendiendo; si cambia, se vuelve a encender entero.
        /// </summary>
        private void SetSoniaText(string text, float now, bool streaming)
        {
            text = Clean(text);
            if (text == _sonia)
            {
                return;
            }

            int keep = text.StartsWith(_sonia) ? _sonia.Length : 0;
            if (keep == 0)
            {
                _revealAt.Clear();
            }
            else if (_revealAt.Count > keep)
            {
                _revealAt.RemoveRange(keep, _revealAt.Count - keep);
            }

            // Con texto en directo, lo que llega ya está sonando: se enciende a
            // partir de ahora, sin correr más que streamCharactersPerSecond. Con la
            // frase entera por delante, al ritmo estimado de la voz.
            float rate = streaming ? streamCharactersPerSecond : spokenCharactersPerSecond;
            float step = 1f / Mathf.Max(1f, rate);
            float last = keep > 0 && _revealAt.Count > 0 ? _revealAt[_revealAt.Count - 1] : now - step;
            for (int i = keep; i < text.Length; i++)
            {
                last = Mathf.Max(now, last + step);
                _revealAt.Add(last);
            }

            _sonia = text;
            _soniaDirty = true;
            _lastActivity = now;
        }

        private void SetSonia(string text)
        {
            _sonia = text ?? string.Empty;
            _revealAt.Clear();
            for (int i = 0; i < _sonia.Length; i++)
            {
                _revealAt.Add(0f);
            }

            _soniaDirty = true;
        }

        private void ClearSubtitles()
        {
            SetSonia(string.Empty);
            _pendingText = null;
            _visitor = string.Empty;
            _visitorDirty = true;
        }

        /// <summary>Sin espacios de más ni signos que TextMeshPro leería como etiquetas.</summary>
        private static string Clean(string text)
        {
            if (string.IsNullOrEmpty(text))
            {
                return string.Empty;
            }

            return text.Replace('<', '‹').Replace('>', '›').Replace('\n', ' ').Trim();
        }

        /// <summary>
        /// Texto con cada tramo a su opacidad: encendido lo dicho, atenuado lo que
        /// falta. Si no cabe, se ve el final empezando en una palabra entera.
        /// </summary>
        private string BuildKaraoke(float now, out bool animating)
        {
            animating = false;
            string text = _sonia;
            int start = 0;
            _builder.Length = 0;
            if (text.Length > maxSubtitleCharacters)
            {
                start = text.Length - maxSubtitleCharacters;
                int space = text.IndexOf(' ', start);
                if (space >= 0 && space < text.Length - 1)
                {
                    start = space + 1;
                }

                _builder.Append("<alpha=#FF>… ");
            }

            int level = -1;
            for (int i = start; i < text.Length; i++)
            {
                float alpha = 1f;
                if (i < _revealAt.Count)
                {
                    float age = now - _revealAt[i];
                    if (age < revealSeconds)
                    {
                        animating = true;
                        alpha = age <= 0f
                            ? dimAlpha
                            : Mathf.Lerp(dimAlpha, 1f, Mathf.SmoothStep(0f, 1f, age / revealSeconds));
                    }
                }

                int quantized = Mathf.Clamp(Mathf.RoundToInt(alpha * 16f), 0, 16);
                if (quantized != level)
                {
                    level = quantized;
                    int value = Mathf.Clamp(Mathf.RoundToInt(quantized / 16f * 255f), 0, 255);
                    _builder.Append("<alpha=#").Append(value.ToString("X2")).Append('>');
                }

                _builder.Append(text[i]);
            }

            return _builder.ToString();
        }

        // ------------------------------------------------------------------
        // Bucle
        // ------------------------------------------------------------------

        private void Update()
        {
            if (!_built)
            {
                return;
            }

            float now = Time.time;
            float dt = Time.deltaTime;
            bool imageUp = _imagePanel != null && _imagePanel.IsVisible;
            bool triviaUp = _trivia != null && _trivia.IsActive;
            bool away = _presence != null && (_presence.IsAway || !_presence.TargetPresent);
            bool hasText = _sonia.Length > 0 || _pendingText != null || _visitor.Length > 0;
            bool recent = _speaking || now - _lastActivity < lingerSeconds;
            bool subtitles = _subtitlesOn && hasText && recent && !away;
            bool invitationUp = _talk
                                && !subtitles
                                && _state == AvatarStateNames.Idle
                                && !imageUp && !triviaUp && !away
                                && now - _lastActivity > lingerSeconds + invitationDelay;

            Fade(_topGroup, imageUp || triviaUp ? 0f : 1f, dt, 4f);
            Fade(_subtitleGroup, subtitles ? 1f : 0f, dt, subtitles ? 8f : 3f);
            Fade(_visitorGroup, _visitor.Length > 0 ? 1f : 0f, dt, 6f);
            Fade(_invitationGroup, invitationUp ? 1f : 0f, dt, invitationUp ? 2.5f : 6f);
            _invitationRect.anchoredPosition = new Vector2(0f, 72f - 24f * (1f - _invitationGroup.alpha));

            // Al terminar de apagarse, fuera el texto viejo.
            if (!subtitles && _subtitleGroup.alpha <= 0.001f && hasText && !_speaking)
            {
                ClearSubtitles();
            }

            if (_visitorDirty)
            {
                _visitorDirty = false;
                UpdateVisitor();
            }

            if (_soniaDirty)
            {
                bool animating = false;
                _soniaText.text = _sonia.Length == 0 ? string.Empty : BuildKaraoke(now, out animating);
                _soniaDirty = animating;
            }

            // El punto de «en vivo» late despacio.
            if (_liveGlow != null)
            {
                float pulse = 0.5f + 0.5f * Mathf.Sin(now * Mathf.PI * 2f / 1.8f);
                _liveGlow.color = new Color(Accent.r, Accent.g, Accent.b, Mathf.Lerp(0.25f, 0.85f, pulse));
            }
        }

        private static void Fade(CanvasGroup group, float target, float dt, float speed)
        {
            if (group != null)
            {
                group.alpha = Mathf.MoveTowards(group.alpha, target, dt * speed);
            }
        }

        private void UpdateVisitor()
        {
            string text = _visitor;
            const int maxCharacters = 70;
            if (text.Length > maxCharacters)
            {
                int start = text.Length - maxCharacters;
                int space = text.IndexOf(' ', start);
                text = "… " + text.Substring(space >= 0 && space < text.Length - 1 ? space + 1 : start);
            }

            _visitorText.text = text;
            Vector2 preferred = _visitorText.GetPreferredValues(text, 10000f, 0f);
            _visitorTextLayout.preferredWidth = Mathf.Min(preferred.x + 2f, 820f);
        }

        // ------------------------------------------------------------------
        // Montaje
        // ------------------------------------------------------------------

        private void Build()
        {
            _hud = ResolveCanvas();
            if (_hud == null)
            {
                Debug.LogWarning("[Sonia] No hay Canvas del HUD: la pantalla del stand no se monta.", this);
                enabled = false;
                return;
            }

            LoadAssets();
            BuildBackdrop();
            HideLegacyScreen();

            // Debajo de todo lo demás del HUD (trivia, letrero, depuración).
            RectTransform stage = NewRect("Stage", _hud.transform);
            Stretch(stage);
            stage.SetAsFirstSibling();

            BuildScrim(stage);
            BuildLogo(stage);
            _topGroup = NewGroup("Arriba", stage);
            BuildLivePill((RectTransform)_topGroup.transform);
            BuildQrCard((RectTransform)_topGroup.transform);
            BuildInvitation(stage);

            // Los subtítulos, encima de todo el HUD.
            RectTransform subtitles = NewRect("StageSubtitles", _hud.transform);
            Stretch(subtitles);
            subtitles.SetAsLastSibling();
            BuildSubtitles(subtitles);

            _subtitleGroup.alpha = 0f;
            _invitationGroup.alpha = 0f;
            _built = true;
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

        private void LoadAssets()
        {
            TMP_FontAsset fallback = TMP_Settings.defaultFontAsset;
            _display = LoadFont("Manrope-ExtraBold", fallback);
            _semibold = LoadFont("Manrope-SemiBold", fallback);
            _mono = LoadFont("GeistMono-Medium", fallback);
            _round = LoadSprite("stage-round", new Vector4(64f, 64f, 64f, 64f));
            _shadow = LoadSprite("stage-shadow", new Vector4(112f, 112f, 112f, 112f));
            _glow = LoadSprite("stage-glow", Vector4.zero);
        }

        private static TMP_FontAsset LoadFont(string name, TMP_FontAsset fallback)
        {
            Font font = Resources.Load<Font>(ResourceFolder + "Fonts/" + name);
            if (font == null)
            {
                Debug.LogWarning("[Sonia] Falta la fuente " + name + " en Resources/Stage/Fonts; uso la de TextMeshPro.");
                return fallback;
            }

            TMP_FontAsset asset = TMP_FontAsset.CreateFontAsset(font);
            if (asset == null)
            {
                return fallback;
            }

            asset.name = name;
            if (fallback != null)
            {
                asset.fallbackFontAssetTable = new List<TMP_FontAsset> { fallback };
            }

            return asset;
        }

        /// <summary>Sprite de Resources/Stage. Si se importó como textura, se hace aquí con su corte en 9.</summary>
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
                Debug.LogWarning("[Sonia] Falta Resources/Stage/" + name + "; ejecuta scripts/stage_assets.py.");
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

        /// <summary>
        /// Fondo de la marca en un Canvas que dibuja la cámara principal a
        /// <see cref="backdropDistance"/> metros: sigue a la cámara (fijo en la
        /// pantalla) y queda detrás de Sonia, del halo y del invitado.
        /// </summary>
        private void BuildBackdrop()
        {
            Camera main = Camera.main;
            Sprite background = LoadSprite("stage-bg", Vector4.zero);
            if (main == null || background == null)
            {
                return;
            }

            GameObject canvasObject = new GameObject("StageBackdrop", typeof(RectTransform));
            canvasObject.transform.SetParent(transform, false);
            canvasObject.layer = 0;
            Canvas canvas = canvasObject.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceCamera;
            canvas.worldCamera = main;
            canvas.planeDistance = Mathf.Min(backdropDistance, main.farClipPlane * 0.9f);
            canvas.sortingOrder = -100;
            CanvasScaler scaler = canvasObject.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1080f, 1920f);
            scaler.matchWidthOrHeight = 0.5f;

            // En la capa por defecto, la que dibuja la cámara principal (la del HUD solo ve UI).
            Image image = NewImage("Fondo", (RectTransform)canvasObject.transform, background, backdropTint);
            image.gameObject.layer = 0;
            image.preserveAspect = false;
            Stretch(image.rectTransform);
        }

        /// <summary>Apaga lo que pintaba la pantalla anterior: el telón 3D, el logo y las burbujas de subtítulos.</summary>
        private void HideLegacyScreen()
        {
            Transform backdrop = transform.Find("Backdrop");
            if (backdrop != null)
            {
                backdrop.gameObject.SetActive(false);
            }

            Transform logo = _hud.transform.Find("BrandLogo");
            if (logo != null)
            {
                logo.gameObject.SetActive(false);
            }

            Transform bubbles = _hud.transform.Find("Debug/Subtitles");
            if (bubbles != null)
            {
                bubbles.gameObject.SetActive(false);
            }
        }

        private void BuildScrim(RectTransform stage)
        {
            Sprite scrim = LoadSprite("stage-scrim", Vector4.zero);
            Image image = NewImage("Sombra", stage, scrim, new Color(Dark.r, Dark.g, Dark.b, 0.92f));
            RectTransform rect = image.rectTransform;
            rect.anchorMin = new Vector2(0f, 0f);
            rect.anchorMax = new Vector2(1f, 0f);
            rect.pivot = new Vector2(0.5f, 0f);
            rect.anchoredPosition = Vector2.zero;
            rect.sizeDelta = new Vector2(0f, 760f);
        }

        private void BuildLogo(RectTransform stage)
        {
            Sprite logo = LoadSprite("stage-logo", Vector4.zero);
            Image image = NewImage("Logo", stage, logo, Color.white);
            image.preserveAspect = true;
            float aspect = logo != null ? logo.rect.width / logo.rect.height : 1200f / 486f;
            PlaceTopLeft(image.rectTransform, new Vector2(56f, 64f), new Vector2(250f, 250f / aspect));
        }

        private void BuildLivePill(RectTransform parent)
        {
            RectTransform pill = NewRect("EnVivo", parent);
            PlaceTopLeft(pill, new Vector2(56f, 196f), new Vector2(0f, 40f));
            Image background = pill.gameObject.AddComponent<Image>();
            ConfigureRound(background, new Color(1f, 1f, 1f, 0.09f), 20f);
            HorizontalLayoutGroup row = pill.gameObject.AddComponent<HorizontalLayoutGroup>();
            row.padding = new RectOffset(18, 20, 0, 0);
            row.spacing = 12f;
            row.childAlignment = TextAnchor.MiddleLeft;
            row.childControlWidth = true;
            row.childControlHeight = true;
            row.childForceExpandWidth = false;
            row.childForceExpandHeight = false;
            ContentSizeFitter fitter = pill.gameObject.AddComponent<ContentSizeFitter>();
            fitter.horizontalFit = ContentSizeFitter.FitMode.PreferredSize;

            RectTransform dotHolder = NewRect("Punto", pill);
            LayoutElement dotLayout = dotHolder.gameObject.AddComponent<LayoutElement>();
            dotLayout.preferredWidth = 12f;
            dotLayout.preferredHeight = 12f;
            _liveGlow = NewImage("Brillo", dotHolder, _glow, Accent);
            _liveGlow.rectTransform.sizeDelta = new Vector2(44f, 44f);
            Image dot = NewImage("Punto", dotHolder, _round, Accent);
            dot.type = Image.Type.Sliced;
            dot.pixelsPerUnitMultiplier = 64f / 6f;
            dot.rectTransform.sizeDelta = new Vector2(12f, 12f);

            TextMeshProUGUI label = NewText("Texto", pill, _mono, 18f, Color.white);
            label.text = liveLabel;
            label.characterSpacing = 14f;
            label.alignment = TextAlignmentOptions.MidlineLeft;
        }

        private void BuildQrCard(RectTransform parent)
        {
            const float width = 232f;
            const float height = 298f;
            RectTransform card = NewRect("QR", parent);
            card.anchorMin = new Vector2(1f, 1f);
            card.anchorMax = new Vector2(1f, 1f);
            card.pivot = new Vector2(1f, 1f);
            card.anchoredPosition = new Vector2(-56f, -56f);
            card.sizeDelta = new Vector2(width, height);

            Image shadow = NewImage("Sombra", card, _shadow, new Color(0f, 0f, 0f, 0.55f));
            shadow.type = Image.Type.Sliced;
            RectTransform shadowRect = shadow.rectTransform;
            Stretch(shadowRect);
            shadowRect.offsetMin = new Vector2(-56f, -76f);
            shadowRect.offsetMax = new Vector2(56f, 36f);

            Image face = NewImage("Tarjeta", card, null, Color.white);
            ConfigureRound(face, Color.white, 26f);
            Stretch(face.rectTransform);

            Image qr = NewImage("Codigo", card, LoadSprite("stage-qr", Vector4.zero), Color.white);
            qr.preserveAspect = true;
            RectTransform qrRect = qr.rectTransform;
            qrRect.anchorMin = new Vector2(0.5f, 1f);
            qrRect.anchorMax = new Vector2(0.5f, 1f);
            qrRect.pivot = new Vector2(0.5f, 1f);
            qrRect.anchoredPosition = new Vector2(0f, -28f);
            qrRect.sizeDelta = new Vector2(176f, 176f);

            TextMeshProUGUI title = NewText("Titulo", card, _display, 24f, Navy);
            title.text = qrTitle;
            title.alignment = TextAlignmentOptions.Center;
            PlaceTopStretch(title.rectTransform, 222f, 30f);

            TextMeshProUGUI caption = NewText("Pie", card, _semibold, 19f, Ink);
            caption.text = qrCaption;
            caption.alignment = TextAlignmentOptions.Center;
            PlaceTopStretch(caption.rectTransform, 254f, 26f);
        }

        private void BuildInvitation(RectTransform stage)
        {
            _invitationGroup = NewGroup("Invitacion", stage);
            _invitationRect = (RectTransform)_invitationGroup.transform;
            _invitationRect.anchorMin = new Vector2(0f, 0f);
            _invitationRect.anchorMax = new Vector2(1f, 0f);
            _invitationRect.pivot = new Vector2(0.5f, 0f);
            _invitationRect.offsetMin = new Vector2(56f, 72f);
            _invitationRect.offsetMax = new Vector2(-56f, 72f + 120f);

            Image shadow = NewImage("Sombra", _invitationRect, _shadow, new Color(0f, 0f, 0f, 0.5f));
            shadow.type = Image.Type.Sliced;
            Stretch(shadow.rectTransform);
            shadow.rectTransform.offsetMin = new Vector2(-60f, -84f);
            shadow.rectTransform.offsetMax = new Vector2(60f, 40f);

            RectTransform pill = NewRect("Pastilla", _invitationRect);
            Stretch(pill);
            Image face = pill.gameObject.AddComponent<Image>();
            ConfigureRound(face, Color.white, 60f);
            HorizontalLayoutGroup row = pill.gameObject.AddComponent<HorizontalLayoutGroup>();
            row.padding = new RectOffset(22, 34, 22, 22);
            row.spacing = 22f;
            row.childAlignment = TextAnchor.MiddleLeft;
            row.childControlWidth = true;
            row.childControlHeight = true;
            row.childForceExpandWidth = false;
            row.childForceExpandHeight = false;

            RectTransform circle = NewRect("Microfono", pill);
            LayoutElement circleLayout = circle.gameObject.AddComponent<LayoutElement>();
            circleLayout.preferredWidth = 76f;
            circleLayout.preferredHeight = 76f;
            Image circleFace = circle.gameObject.AddComponent<Image>();
            ConfigureRound(circleFace, Brand, 38f);
            Image mic = NewImage("Icono", circle, LoadSprite("stage-mic", Vector4.zero), Color.white);
            mic.preserveAspect = true;
            mic.rectTransform.sizeDelta = new Vector2(36f, 36f);

            RectTransform column = NewRect("Textos", pill);
            VerticalLayoutGroup stack = column.gameObject.AddComponent<VerticalLayoutGroup>();
            stack.spacing = 4f;
            stack.childAlignment = TextAnchor.MiddleLeft;
            stack.childControlWidth = true;
            stack.childControlHeight = true;
            stack.childForceExpandWidth = true;
            stack.childForceExpandHeight = false;
            LayoutElement columnLayout = column.gameObject.AddComponent<LayoutElement>();
            columnLayout.flexibleWidth = 1f;

            TextMeshProUGUI line = NewText("Invitacion", column, _display, 34f, Navy);
            line.text = invitation;
            line.characterSpacing = -1f;
            line.alignment = TextAlignmentOptions.MidlineLeft;
            TextMeshProUGUI hint = NewText("Pista", column, _semibold, 24f, Ink);
            hint.text = invitationHint;
            hint.alignment = TextAlignmentOptions.MidlineLeft;
        }

        private void BuildSubtitles(RectTransform parent)
        {
            _subtitleGroup = NewGroup("Subtitulos", parent);
            RectTransform block = (RectTransform)_subtitleGroup.transform;
            block.anchorMin = new Vector2(0.5f, 0f);
            block.anchorMax = new Vector2(0.5f, 0f);
            block.pivot = new Vector2(0.5f, 0f);
            block.anchoredPosition = new Vector2(0f, 96f);
            block.sizeDelta = new Vector2(968f, 0f);
            VerticalLayoutGroup stack = block.gameObject.AddComponent<VerticalLayoutGroup>();
            stack.spacing = 34f;
            stack.childAlignment = TextAnchor.LowerCenter;
            stack.childControlWidth = true;
            stack.childControlHeight = true;
            stack.childForceExpandWidth = true;
            stack.childForceExpandHeight = false;
            ContentSizeFitter fitter = block.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            // Pastilla del visitante, centrada sobre el texto de Sonia.
            RectTransform holder = NewRect("Visitante", block);
            HorizontalLayoutGroup center = holder.gameObject.AddComponent<HorizontalLayoutGroup>();
            center.childAlignment = TextAnchor.MiddleCenter;
            center.childControlWidth = true;
            center.childControlHeight = true;
            center.childForceExpandWidth = false;
            center.childForceExpandHeight = false;
            _visitorGroup = holder.gameObject.AddComponent<CanvasGroup>();
            _visitorGroup.alpha = 0f;

            RectTransform pill = NewRect("Pastilla", holder);
            Image face = pill.gameObject.AddComponent<Image>();
            ConfigureRound(face, new Color(1f, 1f, 1f, 0.12f), 34f);
            HorizontalLayoutGroup row = pill.gameObject.AddComponent<HorizontalLayoutGroup>();
            row.padding = new RectOffset(26, 26, 14, 14);
            row.spacing = 12f;
            row.childAlignment = TextAnchor.MiddleCenter;
            row.childControlWidth = true;
            row.childControlHeight = true;
            row.childForceExpandWidth = false;
            row.childForceExpandHeight = false;

            TextMeshProUGUI label = NewText("Etiqueta", pill, _mono, 18f, new Color(1f, 1f, 1f, 0.75f));
            label.text = "TÚ";
            label.characterSpacing = 14f;
            label.alignment = TextAlignmentOptions.Midline;

            _visitorText = NewText("Texto", pill, _semibold, 32f, Color.white);
            _visitorText.alignment = TextAlignmentOptions.MidlineLeft;
            _visitorText.textWrappingMode = TextWrappingModes.Normal;
            _visitorTextLayout = _visitorText.gameObject.AddComponent<LayoutElement>();

            // Lo que dice Sonia: grande, centrado, sin caja.
            _soniaText = NewText("Sonia", block, _display, subtitleSize, Color.white);
            _soniaText.alignment = TextAlignmentOptions.Bottom;
            _soniaText.textWrappingMode = TextWrappingModes.Normal;
            _soniaText.characterSpacing = -1.5f;
            _soniaText.lineSpacing = -20f;
            _soniaText.richText = true;
        }

        // ------------------------------------------------------------------
        // Piezas
        // ------------------------------------------------------------------

        private RectTransform NewRect(string name, Transform parent)
        {
            GameObject go = new GameObject(name, typeof(RectTransform));
            go.layer = _hud != null ? _hud.gameObject.layer : parent.gameObject.layer;
            go.transform.SetParent(parent, false);
            return (RectTransform)go.transform;
        }

        private CanvasGroup NewGroup(string name, RectTransform parent)
        {
            RectTransform rect = NewRect(name, parent);
            Stretch(rect);
            CanvasGroup group = rect.gameObject.AddComponent<CanvasGroup>();
            group.interactable = false;
            group.blocksRaycasts = false;
            return group;
        }

        private Image NewImage(string name, RectTransform parent, Sprite sprite, Color color)
        {
            RectTransform rect = NewRect(name, parent);
            Image image = rect.gameObject.AddComponent<Image>();
            image.sprite = sprite;
            image.color = color;
            image.raycastTarget = false;
            return image;
        }

        private TextMeshProUGUI NewText(string name, RectTransform parent, TMP_FontAsset font, float size, Color color)
        {
            RectTransform rect = NewRect(name, parent);
            TextMeshProUGUI text = rect.gameObject.AddComponent<TextMeshProUGUI>();
            if (font != null)
            {
                text.font = font;
            }

            text.fontSize = size;
            text.color = color;
            text.raycastTarget = false;
            text.textWrappingMode = TextWrappingModes.NoWrap;
            text.overflowMode = TextOverflowModes.Overflow;
            return text;
        }

        /// <summary>Rectángulo redondeado del sprite de radio 64 con el radio pedido.</summary>
        private void ConfigureRound(Image image, Color color, float radius)
        {
            image.sprite = _round;
            image.type = Image.Type.Sliced;
            image.pixelsPerUnitMultiplier = 64f / Mathf.Max(1f, radius);
            image.color = color;
            image.raycastTarget = false;
        }

        private static void Stretch(RectTransform rect)
        {
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
        }

        private static void PlaceTopLeft(RectTransform rect, Vector2 offset, Vector2 size)
        {
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(0f, 1f);
            rect.pivot = new Vector2(0f, 1f);
            rect.anchoredPosition = new Vector2(offset.x, -offset.y);
            rect.sizeDelta = size;
        }

        private static void PlaceTopStretch(RectTransform rect, float top, float height)
        {
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(1f, 1f);
            rect.pivot = new Vector2(0.5f, 1f);
            rect.anchoredPosition = new Vector2(0f, -top);
            rect.sizeDelta = new Vector2(-24f, height);
        }
    }
}
