// Partículas del escenario: las motas de siempre y un efecto distinto según lo
// que pasa, de uno en uno y con fundido entre ellos.
//
//  - Ambiente: las motas del escenario (SoniaStage/Motes, que monta
//    Sonia > Iluminación de estudio). Se adoptan tal cual y se reescalan.
//  - Trivia: destellos y símbolos («?», «!», estrellas) en los colores de
//    Google mientras hay una trivia en pantalla (también la pantalla final), una
//    explosión de destellos en cada acierto y otra mayor al ganar.
//  - Matrix: lluvia de glifos verdes en columnas detrás de Sonia, con el fondo
//    oscurecido, mientras el orquestador dice que busca en internet (mensaje
//    activity, search). Se queda al menos matrixMinSeconds. El fondo se
//    oscurece un 30 %: se sigue viendo, más apagado. Cuando una tarea solo
//    tarda (think) no hay efecto: Sonia se lleva la mano a la barbilla
//    (AvatarChoreographer).
//
// Si coinciden, manda la trivia: sus respuestas pasan por el backend y no deben
// encender la lluvia cada vez. Con el «Cambio automático» apagado siempre
// se ve el ambiente. Cantidad, velocidad, tamaño y brillo de cada efecto vienen
// de ParticleSettings (menú Esc > Partículas); la opción «Partículas» de la
// calidad gráfica las apaga todas (SetQualityAllows).
//
// Todo se monta por código en Play, como la trivia y la pantalla del stand. Los
// glifos son texturas de Resources/Particles (scripts/particulas_glifos.py). Los
// materiales se clonan del de las motas, que ya está en la build con su variante
// de shader; sin motas en la escena se crean del shader de partículas de URP.

using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace Sonia
{
    /// <summary>Monta los efectos de partículas del escenario y elige cuál se ve.</summary>
    [DisallowMultipleComponent]
    public class StageParticles : MonoBehaviour
    {
        private const string StageName = "SoniaStage";
        private const string ParticleShader = "Universal Render Pipeline/Particles/Unlit";

        private static readonly Color Blue = new Color(0.259f, 0.522f, 0.957f);
        private static readonly Color Red = new Color(0.918f, 0.263f, 0.208f);
        private static readonly Color Yellow = new Color(0.984f, 0.737f, 0.02f);
        private static readonly Color Green = new Color(0.204f, 0.659f, 0.325f);

        [Header("Cambios de efecto")]
        [SerializeField]
        [Range(0.1f, 3f)]
        [Tooltip("Segundos que tarda en aparecer un efecto.")]
        private float fadeInSeconds = 0.6f;

        [SerializeField]
        [Range(0.1f, 3f)]
        [Tooltip("Segundos que tarda en irse.")]
        private float fadeOutSeconds = 1f;

        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("Segundos que se queda la lluvia como mínimo, aunque la búsqueda acabe antes.")]
        private float matrixMinSeconds = 2.5f;

        [Header("Matrix")]
        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Cuánto negro se mezcla en el color del fondo de la marca mientras llueve (1: negro). "
                 + "El posprocesado (ACES y contraste) oscurece más de lo que dice el número: 0,18 lo deja "
                 + "en pantalla un 30 % más oscuro, al 70 % de luminancia (scripts/urp_post.py y captura).")]
        private float matrixBackdropShade = 0.18f;

        [SerializeField]
        [Range(4, 80)]
        [Tooltip("Columnas de lluvia con la cantidad al 100 %.")]
        private int matrixColumns = 24;

        [SerializeField]
        [Range(16, 90)]
        [Tooltip("Glifos que caben de arriba abajo con el tamaño al 100 %.")]
        private int matrixRows = 36;

        [SerializeField]
        [Range(0.5f, 3f)]
        [Tooltip("Brillo de los glifos con el brillo al 100 % (más de 1 enciende el bloom).")]
        private float matrixGlow = 1.4f;

        [Header("Trivia")]
        [SerializeField]
        [Range(0, 300)]
        [Tooltip("Destellos de la explosión de cada acierto, con la cantidad al 100 %.")]
        private int correctBurst = 45;

        [SerializeField]
        [Range(0, 600)]
        [Tooltip("Destellos de la explosión al ganar la trivia.")]
        private int winBurst = 150;

        private static bool s_qualityAllows = true;

        /// <summary>El componente en marcha (uno, el de Sonia).</summary>
        public static StageParticles Instance { get; private set; }

        /// <summary>Falso si la calidad gráfica tiene las partículas apagadas.</summary>
        public static bool QualityAllows
        {
            get { return s_qualityAllows; }
        }

        /// <summary>Lo llama la calidad gráfica: con falso no se ve ningún efecto.</summary>
        public static void SetQualityAllows(bool allowed)
        {
            s_qualityAllows = allowed;
            if (Instance != null)
            {
                Instance.ApplyVisibility();
            }
        }

        /// <summary>Ajustes actuales (los del menú).</summary>
        public ParticleSettings Settings
        {
            get { return _settings; }
        }

        /// <summary>
        /// Efecto que se enseña pase lo que pase, para probarlo desde el menú; null
        /// vuelve a elegir según lo que pasa.
        /// </summary>
        public StageEffect? Preview
        {
            get { return _preview; }
            set
            {
                _preview = value;
                _nextPreviewBurst = Time.time + 1f;
            }
        }

        /// <summary>Efecto que toca ahora (el que está apareciendo o ya se ve).</summary>
        public StageEffect Showing { get; private set; }

        /// <summary>Cierto mientras el orquestador dice que Sonia busca en internet (<c>search</c>).</summary>
        public bool Searching
        {
            get { return _searching; }
        }

        private SoniaClient _client;
        private TriviaController _trivia;
        private StageScreen _screen;
        private AvatarChoreographer _choreographer;
        private Transform _halo;
        private Material _template;
        private Transform _root;
        private bool _built;

        private ParticleSettings _settings;
        private StageEffect? _preview;
        private float _nextPreviewBurst;
        private bool _searching;
        private float _searchSince = -100f;
        private float _matrixUntil = -100f;
        private float _shade = -1f;

        private AmbientLayer _ambient;
        private TriviaLayer _triviaLayer;
        private MatrixLayer _matrix;
        private readonly List<Layer> _layers = new List<Layer>();

        // ------------------------------------------------------------------
        // Ciclo de vida
        // ------------------------------------------------------------------

        private void Awake()
        {
            Instance = this;
            _settings = ParticleSettingsStore.Load();
            _client = GetComponentInChildren<SoniaClient>(true);
            _trivia = GetComponent<TriviaController>();
            _screen = GetComponent<StageScreen>();
            _choreographer = GetComponentInChildren<AvatarChoreographer>(true);
        }

        private void OnEnable()
        {
            if (_client == null)
            {
                return;
            }

            _client.OnActivity += HandleActivity;
            _client.OnTriviaAnswer += HandleTriviaAnswer;
            _client.OnTriviaEnd += HandleTriviaEnd;
            _client.OnDisconnected += HandleDisconnected;
        }

        private void OnDisable()
        {
            if (_client == null)
            {
                return;
            }

            _client.OnActivity -= HandleActivity;
            _client.OnTriviaAnswer -= HandleTriviaAnswer;
            _client.OnTriviaEnd -= HandleTriviaEnd;
            _client.OnDisconnected -= HandleDisconnected;
        }

        private void OnDestroy()
        {
            if (Instance == this)
            {
                Instance = null;
            }

            foreach (Layer layer in _layers)
            {
                layer.Dispose();
            }
        }

        private void Start()
        {
            if (_trivia == null)
            {
                _trivia = GetComponent<TriviaController>();
            }

            if (_screen == null)
            {
                _screen = GetComponent<StageScreen>();
            }

            Build();
        }

        private void Update()
        {
            if (!_built)
            {
                return;
            }

            float dt = Time.deltaTime;
            Showing = Resolve();
            bool allowed = s_qualityAllows;
            foreach (Layer layer in _layers)
            {
                bool wanted = allowed && layer.Effect == Showing && _settings.For(layer.Effect).amount > 0;
                float seconds = wanted ? fadeInSeconds : fadeOutSeconds;
                float before = layer.Weight;
                layer.Wanted = wanted;
                layer.Weight = Mathf.MoveTowards(layer.Weight, wanted ? 1f : 0f, dt / Mathf.Max(0.01f, seconds));
                if (before <= 0f && layer.Weight > 0f)
                {
                    layer.Show();
                }

                layer.Tick(this, dt);
                layer.SetTint(_settings.For(layer.Effect).Brightness, layer.Weight);
                if (before > 0f && layer.Weight <= 0f)
                {
                    layer.Hide();
                }
            }

            UpdateBackdrop();
            if (_preview == StageEffect.Trivia && Time.time >= _nextPreviewBurst)
            {
                // En la vista previa del menú también se ve la explosión de un acierto.
                _nextPreviewBurst = Time.time + 3.5f;
                Burst(correctBurst);
            }
        }

        // ------------------------------------------------------------------
        // API del menú
        // ------------------------------------------------------------------

        /// <summary>Cambia los ajustes, los guarda y los aplica al momento.</summary>
        public void EditSettings(System.Action<ParticleSettings> edit)
        {
            edit(_settings);
            _settings.Sanitize();
            ParticleSettingsStore.Save(_settings);
            ApplyTuning();
        }

        // ------------------------------------------------------------------
        // Qué efecto toca
        // ------------------------------------------------------------------

        private StageEffect Resolve()
        {
            StageEffect effect = StageEffect.Ambient;
            if (_preview.HasValue)
            {
                effect = _preview.Value;
            }
            else if (_settings.contextual)
            {
                if (_trivia != null && _trivia.IsActive)
                {
                    effect = StageEffect.Trivia;
                }
                else if (_searching || Time.time < _matrixUntil)
                {
                    effect = StageEffect.Matrix;
                }
            }

            // Un efecto con la cantidad a 0 está apagado: en su lugar, el ambiente.
            return _settings.For(effect).amount > 0 ? effect : StageEffect.Ambient;
        }

        private void HandleActivity(ActivityMessage message)
        {
            SetSearching(message != null && message.Activity == ActivityNames.Search);
        }

        private void HandleDisconnected()
        {
            SetSearching(false);
        }

        private void SetSearching(bool searching)
        {
            if (searching == _searching)
            {
                return;
            }

            if (searching)
            {
                _searchSince = Time.time;
            }
            else
            {
                _matrixUntil = Mathf.Max(Time.time, _searchSince + matrixMinSeconds);
            }

            _searching = searching;
        }

        private void HandleTriviaAnswer(TriviaAnswerMessage message)
        {
            if (message != null && message.IsCorrect && Showing == StageEffect.Trivia)
            {
                Burst(correctBurst);
            }
        }

        private void HandleTriviaEnd(TriviaEndMessage message)
        {
            if (message != null && message.Won && Showing == StageEffect.Trivia)
            {
                Burst(winBurst);
            }
        }

        private void Burst(int count)
        {
            if (_triviaLayer != null && s_qualityAllows)
            {
                _triviaLayer.Burst(Mathf.RoundToInt(count * _settings.trivia.Amount), HeadPosition(), Forward());
            }
        }

        // ------------------------------------------------------------------
        // Montaje
        // ------------------------------------------------------------------

        private void Build()
        {
            GameObject stage = GameObject.Find(StageName);
            ParticleSystem motes = null;
            if (stage != null)
            {
                _halo = stage.transform.Find("Halo");
                Transform motesTransform = stage.transform.Find("Motes");
                motes = motesTransform != null ? motesTransform.GetComponent<ParticleSystem>() : null;
            }

            ParticleSystemRenderer motesRenderer = motes != null ? motes.GetComponent<ParticleSystemRenderer>() : null;
            _template = motesRenderer != null ? motesRenderer.sharedMaterial : null;

            GameObject root = new GameObject("SoniaParticles");
            _root = root.transform;
            _root.SetParent(transform, false);

            if (motes != null)
            {
                _ambient = new AmbientLayer(motes);
                _layers.Add(_ambient);
            }
            else
            {
                Debug.LogWarning("[Sonia] Sin SoniaStage/Motes en la escena: no hay partículas de ambiente "
                                 + "(Sonia > Iluminación de estudio las monta).", this);
            }

            Texture2D triviaGlyphs = Resources.Load<Texture2D>("Particles/trivia-glyphs");
            Texture2D matrixGlyphs = Resources.Load<Texture2D>("Particles/matrix-glyphs");
            Material triviaMaterial = triviaGlyphs != null ? MakeMaterial(triviaGlyphs, false) : null;
            Material matrixMaterial = matrixGlyphs != null ? MakeMaterial(matrixGlyphs, true) : null;
            if (triviaMaterial != null)
            {
                _triviaLayer = new TriviaLayer(this, triviaMaterial);
                _layers.Add(_triviaLayer);
            }

            if (matrixMaterial != null)
            {
                _matrix = new MatrixLayer(this, matrixMaterial);
                _layers.Add(_matrix);
            }

            if (triviaMaterial == null || matrixMaterial == null)
            {
                Debug.LogWarning("[Sonia] Faltan las texturas de Resources/Particles o el shader de partículas: "
                                 + "sin efectos de trivia o Matrix.", this);
            }

            _built = true;
            ApplyTuning();
            ApplyVisibility();
        }

        /// <summary>
        /// Material de partículas transparente: aditivo (luz que se suma, para las
        /// motas y Matrix) o con alfa (colores que se ven sobre el azul del fondo,
        /// para la trivia).
        /// </summary>
        private Material MakeMaterial(Texture2D texture, bool additive)
        {
            Material material;
            if (_template != null)
            {
                material = new Material(_template);
            }
            else
            {
                Shader shader = Shader.Find(ParticleShader);
                if (shader == null)
                {
                    return null;
                }

                material = new Material(shader);
            }

            material.name = texture.name;
            material.SetFloat("_Surface", 1f);
            material.SetFloat("_Blend", additive ? 2f : 0f); // 0 alpha, 1 premultiply, 2 additive
            material.SetFloat("_ZWrite", 0f);
            material.SetFloat("_Cull", 0f);
            material.SetFloat("_ColorMode", 0f);
            material.SetInt("_SrcBlend", (int)BlendMode.SrcAlpha);
            material.SetInt("_DstBlend", (int)(additive ? BlendMode.One : BlendMode.OneMinusSrcAlpha));
            material.SetInt("_SrcBlendAlpha", (int)BlendMode.One);
            material.SetInt("_DstBlendAlpha", (int)(additive ? BlendMode.One : BlendMode.OneMinusSrcAlpha));
            material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.DisableKeyword("_ALPHAPREMULTIPLY_ON");
            material.DisableKeyword("_ALPHAMODULATE_ON");
            material.DisableKeyword("_ALPHATEST_ON");
            material.SetOverrideTag("RenderType", "Transparent");
            material.renderQueue = (int)RenderQueue.Transparent;
            material.SetTexture("_BaseMap", texture);
            material.mainTexture = texture;
            material.SetColor("_BaseColor", Color.white);
            return material;
        }

        /// <summary>Un sistema de partículas nuevo, parado, en espacio de mundo y sin nada de lo de serie.</summary>
        private ParticleSystem NewSystem(string name, Material material, int tilesX, int tilesY, Vector2 frames)
        {
            GameObject go = new GameObject(name);
            go.SetActive(false);
            go.transform.SetParent(_root, false);
            ParticleSystem system = go.AddComponent<ParticleSystem>();

            ParticleSystem.MainModule main = system.main;
            main.playOnAwake = false;
            main.loop = true;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.scalingMode = ParticleSystemScalingMode.Hierarchy;
            main.startSpeed = 0f;
            main.startRotation = 0f;
            main.gravityModifier = 0f;
            main.startColor = Color.white;

            ParticleSystem.EmissionModule emission = system.emission;
            emission.rateOverTime = 0f;
            ParticleSystem.ShapeModule shape = system.shape;
            shape.enabled = false;

            ParticleSystem.TextureSheetAnimationModule sheet = system.textureSheetAnimation;
            sheet.enabled = true;
            sheet.mode = ParticleSystemAnimationMode.Grid;
            sheet.numTilesX = tilesX;
            sheet.numTilesY = tilesY;
            sheet.animation = ParticleSystemAnimationType.WholeSheet;
            // Dos constantes: cada partícula saca su glifo al nacer y no lo cambia.
            sheet.frameOverTime = new ParticleSystem.MinMaxCurve(frames.x, frames.y);
            sheet.cycleCount = 1;

            ParticleSystemRenderer renderer = go.GetComponent<ParticleSystemRenderer>();
            renderer.renderMode = ParticleSystemRenderMode.Billboard;
            renderer.alignment = ParticleSystemRenderSpace.View;
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            renderer.maxParticleSize = 1f;

            go.SetActive(true);
            system.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            return system;
        }

        private void ApplyTuning()
        {
            if (_ambient != null)
            {
                _ambient.Tune(_settings.ambient);
            }

            if (_triviaLayer != null)
            {
                _triviaLayer.Tune(_settings.trivia);
            }

            if (_matrix != null)
            {
                _matrix.Tune(_settings.matrix, matrixColumns, matrixRows, matrixGlow);
            }
        }

        private void ApplyVisibility()
        {
            foreach (Layer layer in _layers)
            {
                layer.SetVisible(s_qualityAllows);
            }

            if (!s_qualityAllows)
            {
                UpdateBackdrop();
            }
        }

        private void UpdateBackdrop()
        {
            float shade = _matrix != null && s_qualityAllows ? _matrix.Weight * matrixBackdropShade : 0f;
            if (_screen != null && !Mathf.Approximately(shade, _shade))
            {
                _shade = shade;
                _screen.BackdropShade = shade;
            }
        }

        // ------------------------------------------------------------------
        // Dónde está el escenario
        // ------------------------------------------------------------------

        /// <summary>Hacia la cámara desde Sonia, en horizontal.</summary>
        private Vector3 Forward()
        {
            if (_halo != null)
            {
                Vector3 back = -_halo.forward;
                back.y = 0f;
                if (back.sqrMagnitude > 0.001f)
                {
                    return back.normalized;
                }
            }

            Camera main = Camera.main;
            Vector3 toCamera = main != null ? -main.transform.forward : Vector3.back;
            toCamera.y = 0f;
            return toCamera.sqrMagnitude > 0.001f ? toCamera.normalized : Vector3.back;
        }

        /// <summary>El plano detrás de Sonia (el del halo).</summary>
        private Vector3 BackPosition()
        {
            if (_halo != null)
            {
                return _halo.position;
            }

            Camera main = Camera.main;
            return main != null ? main.transform.position + main.transform.forward * 3f : Vector3.zero;
        }

        /// <summary>La cabeza de Sonia (o, sin avatar humano, donde suele estar).</summary>
        private Vector3 HeadPosition()
        {
            Animator animator = _choreographer != null ? _choreographer.MotionPlayerAnimator : null;
            if (animator != null && animator.isHuman)
            {
                Transform head = animator.GetBoneTransform(HumanBodyBones.Head);
                if (head != null)
                {
                    return head.position;
                }
            }

            return BackPosition() + Forward() * 0.9f + Vector3.up * 0.35f;
        }

        // ------------------------------------------------------------------
        // Efectos
        // ------------------------------------------------------------------

        /// <summary>Un efecto: sus sistemas, su material y cuánto se ve (Weight, de 0 a 1).</summary>
        private abstract class Layer
        {
            public readonly StageEffect Effect;
            public float Weight;
            public bool Wanted;
            protected readonly List<ParticleSystem> Systems = new List<ParticleSystem>();
            private readonly Material _material;
            private readonly Color _baseTint;
            private readonly bool _ownsMaterial;

            protected Layer(StageEffect effect, Material material, bool ownsMaterial)
            {
                Effect = effect;
                _material = material;
                _ownsMaterial = ownsMaterial;
                _baseTint = material != null && material.HasProperty("_BaseColor") ? material.GetColor("_BaseColor") : Color.white;
            }

            /// <summary>Brillo como multiplicador del color; el fundido, en el alfa.</summary>
            public void SetTint(float brightness, float weight)
            {
                if (_material == null || !_material.HasProperty("_BaseColor"))
                {
                    return;
                }

                Color tint = _baseTint * brightness * GlowBoost;
                tint.a = _baseTint.a * weight;
                _material.SetColor("_BaseColor", tint);
            }

            public void SetVisible(bool visible)
            {
                foreach (ParticleSystem system in Systems)
                {
                    if (system != null)
                    {
                        system.GetComponent<ParticleSystemRenderer>().enabled = visible;
                    }
                }
            }

            public void Dispose()
            {
                if (_ownsMaterial && _material != null)
                {
                    Destroy(_material);
                }
            }

            protected virtual float GlowBoost
            {
                get { return 1f; }
            }

            /// <summary>Empieza a verse (el peso sale de 0).</summary>
            public virtual void Show()
            {
            }

            /// <summary>Ya no se ve (el peso llega a 0).</summary>
            public virtual void Hide()
            {
            }

            public virtual void Tick(StageParticles owner, float dt)
            {
            }

            /// <summary>Curva plana para el tamaño a lo largo de la vida (el ajuste va en su multiplicador).</summary>
            protected static ParticleSystem.MinMaxCurve Flat(float value)
            {
                return new ParticleSystem.MinMaxCurve(value, AnimationCurve.Constant(0f, 1f, 1f));
            }

            protected static ParticleSystem.MinMaxCurve Curve(float multiplier, params Keyframe[] keys)
            {
                return new ParticleSystem.MinMaxCurve(multiplier, new AnimationCurve(keys));
            }

            protected static Gradient Fade(float fadeIn, float hold, float peak)
            {
                Gradient gradient = new Gradient();
                gradient.SetKeys(
                    new[] { new GradientColorKey(Color.white, 0f), new GradientColorKey(Color.white, 1f) },
                    new[]
                    {
                        new GradientAlphaKey(0f, 0f), new GradientAlphaKey(peak, fadeIn),
                        new GradientAlphaKey(peak * 0.9f, hold), new GradientAlphaKey(0f, 1f)
                    });
                return gradient;
            }
        }

        /// <summary>Las motas del escenario, tal como las montó la iluminación de estudio.</summary>
        private sealed class AmbientLayer : Layer
        {
            private readonly ParticleSystem _system;
            private readonly float _baseRate;
            private readonly int _baseMax;
            private readonly float _baseSpeed;

            public AmbientLayer(ParticleSystem motes)
                : base(StageEffect.Ambient, motes.GetComponent<ParticleSystemRenderer>().material, true)
            {
                _system = motes;
                Systems.Add(motes);
                _baseRate = motes.emission.rateOverTimeMultiplier;
                _baseMax = motes.main.maxParticles;
                _baseSpeed = motes.main.simulationSpeed;
                ParticleSystem.SizeOverLifetimeModule size = motes.sizeOverLifetime;
                if (!size.enabled)
                {
                    size.enabled = true;
                    size.size = Flat(1f);
                }

                // Empieza visible: es lo que se ve al arrancar.
                Weight = 1f;
            }

            public void Tune(EffectTuning tuning)
            {
                ParticleSystem.EmissionModule emission = _system.emission;
                emission.rateOverTimeMultiplier = _baseRate * tuning.Amount;
                ParticleSystem.MainModule main = _system.main;
                main.maxParticles = Mathf.Max(1, Mathf.CeilToInt(_baseMax * Mathf.Max(0.01f, tuning.Amount)));
                main.simulationSpeed = _baseSpeed * tuning.Speed;
                ParticleSystem.SizeOverLifetimeModule size = _system.sizeOverLifetime;
                size.sizeMultiplier = tuning.Size;
            }
        }

        /// <summary>Destellos, símbolos y explosiones de colores de la trivia.</summary>
        private sealed class TriviaLayer : Layer
        {
            // Celdas del atlas (4 x 2): arriba «?», estrella, «!» y otra «?»; abajo destello, punto, estrella y «+».
            private static readonly Vector2 SymbolFrames = new Vector2(0f, 0.499f);
            private static readonly Vector2 SparkleFrames = new Vector2(0.5f, 0.999f);

            private readonly StageParticles _owner;
            private readonly ParticleSystem _sparkles;
            private readonly ParticleSystem _symbols;
            private readonly ParticleSystem _burst;
            private const float SparkleRate = 16f;
            private const float SymbolRate = 3f;

            public TriviaLayer(StageParticles owner, Material material)
                : base(StageEffect.Trivia, material, true)
            {
                _owner = owner;
                ParticleSystem.MinMaxGradient colors = GoogleColors();

                _sparkles = owner.NewSystem("TriviaDestellos", material, 4, 2, SparkleFrames);
                ParticleSystem.MainModule main = _sparkles.main;
                main.startLifetime = new ParticleSystem.MinMaxCurve(2.5f, 4.5f);
                main.startSize = new ParticleSystem.MinMaxCurve(0.025f, 0.06f);
                main.startRotation = new ParticleSystem.MinMaxCurve(-0.6f, 0.6f);
                main.startColor = colors;
                main.maxParticles = 600;
                main.prewarm = true;
                Box(_sparkles, new Vector3(2.6f, 2.8f, 1.2f));
                Rise(_sparkles, 0.03f, 0.1f);
                Noise(_sparkles, 0.06f);
                ParticleSystem.ColorOverLifetimeModule color = _sparkles.colorOverLifetime;
                color.enabled = true;
                color.color = Fade(0.15f, 0.75f, 1f);
                ParticleSystem.SizeOverLifetimeModule size = _sparkles.sizeOverLifetime;
                size.enabled = true;
                size.size = Curve(1f, new Keyframe(0f, 0.3f), new Keyframe(0.2f, 1f), new Keyframe(0.5f, 0.7f),
                    new Keyframe(0.7f, 1f), new Keyframe(1f, 0f));

                _symbols = owner.NewSystem("TriviaSimbolos", material, 4, 2, SymbolFrames);
                main = _symbols.main;
                main.startLifetime = new ParticleSystem.MinMaxCurve(5f, 8f);
                main.startSize = new ParticleSystem.MinMaxCurve(0.12f, 0.2f);
                main.startRotation = new ParticleSystem.MinMaxCurve(-0.35f, 0.35f);
                main.startColor = colors;
                main.maxParticles = 120;
                main.prewarm = true;
                Box(_symbols, new Vector3(2.8f, 3f, 0.3f));
                Rise(_symbols, 0.06f, 0.14f);
                Noise(_symbols, 0.03f);
                ParticleSystem.RotationOverLifetimeModule spin = _symbols.rotationOverLifetime;
                spin.enabled = true;
                spin.z = new ParticleSystem.MinMaxCurve(-0.3f, 0.3f);
                color = _symbols.colorOverLifetime;
                color.enabled = true;
                color.color = Fade(0.15f, 0.8f, 0.85f);
                size = _symbols.sizeOverLifetime;
                size.enabled = true;
                size.size = Curve(1f, new Keyframe(0f, 0.6f), new Keyframe(0.2f, 1f), new Keyframe(1f, 0.9f));

                _burst = owner.NewSystem("TriviaExplosion", material, 4, 2, SparkleFrames);
                main = _burst.main;
                main.startLifetime = new ParticleSystem.MinMaxCurve(1.2f, 2.2f);
                main.startSize = new ParticleSystem.MinMaxCurve(0.025f, 0.065f);
                main.startSpeed = new ParticleSystem.MinMaxCurve(1f, 2.4f);
                main.startRotation = new ParticleSystem.MinMaxCurve(-3f, 3f);
                main.startColor = colors;
                main.gravityModifier = 0.12f;
                main.maxParticles = 1500;
                ParticleSystem.ShapeModule shape = _burst.shape;
                shape.enabled = true;
                shape.shapeType = ParticleSystemShapeType.Sphere;
                shape.radius = 0.2f;
                ParticleSystem.LimitVelocityOverLifetimeModule drag = _burst.limitVelocityOverLifetime;
                drag.enabled = true;
                drag.limit = 100f;
                drag.drag = 1.6f;
                drag.multiplyDragByParticleSize = false;
                drag.multiplyDragByParticleVelocity = false;
                spin = _burst.rotationOverLifetime;
                spin.enabled = true;
                spin.z = new ParticleSystem.MinMaxCurve(-4f, 4f);
                color = _burst.colorOverLifetime;
                color.enabled = true;
                color.color = Fade(0.02f, 0.6f, 1f);
                size = _burst.sizeOverLifetime;
                size.enabled = true;
                size.size = Curve(1f, new Keyframe(0f, 1f), new Keyframe(1f, 0.4f));

                Systems.Add(_sparkles);
                Systems.Add(_symbols);
                Systems.Add(_burst);
            }

            protected override float GlowBoost
            {
                get { return 1.25f; }
            }

            public void Tune(EffectTuning tuning)
            {
                ParticleSystem.EmissionModule emission = _sparkles.emission;
                emission.rateOverTime = SparkleRate * tuning.Amount;
                emission = _symbols.emission;
                emission.rateOverTime = SymbolRate * tuning.Amount;
                foreach (ParticleSystem system in Systems)
                {
                    ParticleSystem.MainModule main = system.main;
                    main.simulationSpeed = tuning.Speed;
                    ParticleSystem.SizeOverLifetimeModule size = system.sizeOverLifetime;
                    size.sizeMultiplier = tuning.Size;
                }
            }

            public override void Show()
            {
                Place();
                _sparkles.Play();
                _symbols.Play();
                _burst.Play();
            }

            public override void Hide()
            {
                foreach (ParticleSystem system in Systems)
                {
                    system.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
                }
            }

            public override void Tick(StageParticles owner, float dt)
            {
                if (Weight <= 0f)
                {
                    return;
                }

                Place();
                if (!Wanted && _sparkles.isEmitting)
                {
                    _sparkles.Stop(false, ParticleSystemStopBehavior.StopEmitting);
                    _symbols.Stop(false, ParticleSystemStopBehavior.StopEmitting);
                }
                else if (Wanted && !_sparkles.isEmitting)
                {
                    _sparkles.Play();
                    _symbols.Play();
                }
            }

            public void Burst(int count, Vector3 head, Vector3 forward)
            {
                if (count <= 0 || Weight <= 0f)
                {
                    return;
                }

                // Desde el pecho, algo por detrás de Sonia: salen alrededor de ella.
                _burst.transform.position = head + Vector3.down * 0.25f - forward * 0.15f;
                if (!_burst.isPlaying)
                {
                    _burst.Play();
                }

                _burst.Emit(count);
            }

            /// <summary>Destellos entre Sonia y el halo; símbolos detrás de ella, para no taparle la cara.</summary>
            private void Place()
            {
                Vector3 back = _owner.BackPosition();
                Vector3 forward = _owner.Forward();
                Quaternion facing = Quaternion.LookRotation(-forward, Vector3.up);
                _sparkles.transform.SetPositionAndRotation(back + forward * 0.45f + Vector3.up * 0.1f, facing);
                _symbols.transform.SetPositionAndRotation(back + forward * 0.1f + Vector3.up * 0.15f, facing);
            }

            private static ParticleSystem.MinMaxGradient GoogleColors()
            {
                Gradient gradient = new Gradient { mode = GradientMode.Fixed };
                gradient.SetKeys(
                    new[]
                    {
                        new GradientColorKey(Blue, 0.25f), new GradientColorKey(Red, 0.5f),
                        new GradientColorKey(Yellow, 0.75f), new GradientColorKey(Green, 1f)
                    },
                    new[] { new GradientAlphaKey(1f, 0f), new GradientAlphaKey(1f, 1f) });
                ParticleSystem.MinMaxGradient colors = new ParticleSystem.MinMaxGradient(gradient);
                colors.mode = ParticleSystemGradientMode.RandomColor;
                return colors;
            }

            private static void Box(ParticleSystem system, Vector3 size)
            {
                ParticleSystem.ShapeModule shape = system.shape;
                shape.enabled = true;
                shape.shapeType = ParticleSystemShapeType.Box;
                shape.scale = size;
            }

            private static void Rise(ParticleSystem system, float min, float max)
            {
                ParticleSystem.VelocityOverLifetimeModule velocity = system.velocityOverLifetime;
                velocity.enabled = true;
                velocity.space = ParticleSystemSimulationSpace.World;
                velocity.x = new ParticleSystem.MinMaxCurve(0f, 0f);
                velocity.y = new ParticleSystem.MinMaxCurve(min, max);
                velocity.z = new ParticleSystem.MinMaxCurve(0f, 0f);
            }

            private static void Noise(ParticleSystem system, float strength)
            {
                ParticleSystem.NoiseModule noise = system.noise;
                noise.enabled = true;
                noise.strength = strength;
                noise.frequency = 0.3f;
                noise.scrollSpeed = 0.2f;
            }
        }

        /// <summary>
        /// Lluvia estilo Matrix: columnas de glifos que caen detrás de Sonia. Cada
        /// columna lleva hasta dos gotas; la cabeza de cada gota deja un glifo
        /// quieto en cada celda que pisa, que nace casi blanco y se apaga en verde.
        /// La mueve el script (Emit), no la emisión del sistema.
        /// </summary>
        private sealed class MatrixLayer : Layer
        {
            private const int MaxColumns = 240;

            private sealed class Drop
            {
                public bool Alive;
                public float Y;
                public float Speed;
                public float Life;
                public int LastCell;
            }

            private sealed class Column
            {
                public float X;
                public float Scale;
                public float Bright;
                public float NextSpawn;
                public readonly Drop[] Drops = { new Drop(), new Drop() };
            }

            private readonly StageParticles _owner;
            private readonly ParticleSystem _system;
            private readonly List<Column> _columns = new List<Column>();
            private int _count;
            private int _baseColumns = 24;
            private int _rows = 36;
            private float _speed = 1f;
            private float _size = 1f;
            private float _glow = 1.4f;

            public MatrixLayer(StageParticles owner, Material material)
                : base(StageEffect.Matrix, material, true)
            {
                _owner = owner;
                _system = owner.NewSystem("MatrixLluvia", material, 8, 8, new Vector2(0f, 0.999f));
                ParticleSystem.MainModule main = _system.main;
                main.maxParticles = 20000;
                ParticleSystem.EmissionModule emission = _system.emission;
                emission.enabled = false;

                Gradient gradient = new Gradient();
                gradient.SetKeys(
                    new[]
                    {
                        new GradientColorKey(new Color(0.85f, 1f, 0.88f), 0f),
                        new GradientColorKey(new Color(0.35f, 1f, 0.45f), 0.04f),
                        new GradientColorKey(new Color(0.12f, 0.85f, 0.28f), 0.35f),
                        new GradientColorKey(new Color(0.04f, 0.45f, 0.12f), 1f)
                    },
                    new[] { new GradientAlphaKey(1f, 0f), new GradientAlphaKey(0.8f, 0.5f), new GradientAlphaKey(0f, 1f) });
                ParticleSystem.ColorOverLifetimeModule color = _system.colorOverLifetime;
                color.enabled = true;
                color.color = gradient;
                Systems.Add(_system);
            }

            protected override float GlowBoost
            {
                get { return _glow; }
            }

            public void Tune(EffectTuning tuning, int columns, int rows, float glow)
            {
                _baseColumns = columns;
                _rows = rows;
                _glow = glow;
                _speed = tuning.Speed;
                _size = tuning.Size;
                Resize(Mathf.Clamp(Mathf.RoundToInt(columns * tuning.Amount), 0, MaxColumns));
            }

            public override void Show()
            {
                _system.Play();
                // La lluvia empieza ya repartida por la pantalla, no toda desde arriba.
                foreach (Column column in _columns)
                {
                    StartDrop(column, column.Drops[0], Random.Range(-0.3f, 0.5f) * _rows / column.Scale);
                }
            }

            public override void Hide()
            {
                foreach (Column column in _columns)
                {
                    column.Drops[0].Alive = false;
                    column.Drops[1].Alive = false;
                }

                _system.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            }

            public override void Tick(StageParticles owner, float dt)
            {
                if (Weight <= 0f)
                {
                    return;
                }

                Camera camera = Camera.main;
                if (camera == null)
                {
                    return;
                }

                // Plano de la lluvia: a la distancia del halo, del tamaño de lo que ve la cámara.
                Transform view = camera.transform;
                float depth = Mathf.Max(0.5f, Vector3.Dot(_owner.BackPosition() - view.position, view.forward));
                float height = 2f * depth * Mathf.Tan(camera.fieldOfView * 0.5f * Mathf.Deg2Rad);
                float width = height * camera.aspect;
                Vector3 center = view.position + view.forward * depth;
                Vector3 top = center + view.up * (height * 0.5f);
                float baseCell = height / Mathf.Max(8, _rows) * _size;
                float now = Time.time;

                foreach (Column column in _columns)
                {
                    float cell = baseCell * column.Scale;
                    float rowsHere = height / cell;
                    Vector3 columnTop = top + view.right * (column.X * width * 0.54f);
                    for (int i = 0; i < column.Drops.Length; i++)
                    {
                        Drop drop = column.Drops[i];
                        if (!drop.Alive)
                        {
                            continue;
                        }

                        drop.Y += drop.Speed * _speed * dt;
                        int reached = Mathf.FloorToInt(drop.Y);
                        while (drop.LastCell < reached)
                        {
                            drop.LastCell++;
                            if (drop.LastCell >= 0 && drop.LastCell <= rowsHere)
                            {
                                Emit(columnTop - view.up * ((drop.LastCell + 0.5f) * cell), cell, drop.Life, column.Bright);
                            }
                        }

                        if (drop.Y > rowsHere + 1f)
                        {
                            drop.Alive = false;
                        }
                    }

                    if (!Wanted || now < column.NextSpawn)
                    {
                        continue;
                    }

                    Drop first = column.Drops[0];
                    Drop second = column.Drops[1];
                    Drop free = !first.Alive ? first : !second.Alive ? second : null;
                    Drop other = free == first ? second : first;
                    if (free != null && (!other.Alive || other.Y > rowsHere * 0.45f))
                    {
                        StartDrop(column, free, -Random.Range(0f, 4f));
                    }
                }
            }

            private void StartDrop(Column column, Drop drop, float y)
            {
                drop.Alive = true;
                drop.Y = y;
                drop.LastCell = Mathf.FloorToInt(y);
                drop.Speed = Random.Range(9f, 20f);
                drop.Life = Random.Range(1.2f, 3f);
                column.NextSpawn = Time.time + Random.Range(0.3f, 2.5f);
            }

            private void Emit(Vector3 position, float cell, float life, float bright)
            {
                ParticleSystem.EmitParams glyph = new ParticleSystem.EmitParams
                {
                    position = position,
                    applyShapeToPosition = false,
                    velocity = Vector3.zero,
                    startSize = cell * 0.92f,
                    startLifetime = life,
                    startColor = new Color(1f, 1f, 1f, bright)
                };
                _system.Emit(glyph, 1);
            }

            /// <summary>Columnas repartidas a lo ancho con algo de desorden y cada una con su tamaño y brillo.</summary>
            private void Resize(int count)
            {
                if (count == _count)
                {
                    return;
                }

                _count = count;
                _columns.Clear();
                for (int i = 0; i < count; i++)
                {
                    float x = (i + 0.5f + Random.Range(-0.35f, 0.35f)) / count;
                    Column column = new Column
                    {
                        X = x * 2f - 1f,
                        Scale = Random.Range(0.7f, 1.25f),
                        Bright = Random.Range(0.55f, 1f),
                        NextSpawn = 0f
                    };
                    _columns.Add(column);
                    if (Weight > 0f)
                    {
                        StartDrop(column, column.Drops[0], Random.Range(-0.3f, 0.5f) * _rows / column.Scale);
                    }
                }
            }
        }
    }
}
