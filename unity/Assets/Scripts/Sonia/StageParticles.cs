// Stage particles: the usual ambient motes and a different effect depending on
// what is happening, one at a time and cross-fading between them.
//
//  - Ambient: the stage motes (SoniaStage/Motes, built by the studio lighting
//    setup). They are adopted as they are and rescaled.
//  - Trivia: sparkles and symbols ("?", "!", stars) in playful confetti colors
//    while a trivia round is on screen (also the final screen), a burst of
//    sparkles on every correct answer and a bigger one on winning.
//  - Matrix: rain of green glyphs in columns behind Sonnia, with the backdrop
//    darkened, while the orchestrator says it is searching the web (message
//    activity, search). It stays at least matrixMinSeconds. The backdrop
//    darkens by 30 %: it is still visible, just dimmer. When a task merely
//    takes long (think) there is no effect.
//
// If they coincide, trivia wins: its answers go through the backend and must not
// trigger the rain every time. With "Automatic switching" off the ambient
// effect is always shown. Amount, speed, size and brightness of each effect come
// from ParticleSettings (menu Esc > Particles); the "Particles" option of the
// graphics quality turns them all off (SetQualityAllows).
//
// Everything is built in code at Play, like the trivia and the stage screen. The
// glyphs are textures in Resources/Particles. The materials are cloned from the
// motes one, which is already in the build with its shader variant; without
// motes in the scene they are created from the URP particle shader.

using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace Sonia
{
    /// <summary>Builds the stage particle effects and chooses which one is shown.</summary>
    [DisallowMultipleComponent]
    public class StageParticles : MonoBehaviour
    {
        private const string StageName = "SoniaStage";
        private const string ParticleShader = "Universal Render Pipeline/Particles/Unlit";

        private static readonly Color Blue = new Color(0.259f, 0.522f, 0.957f);
        private static readonly Color Red = new Color(0.918f, 0.263f, 0.208f);
        private static readonly Color Yellow = new Color(0.984f, 0.737f, 0.02f);
        private static readonly Color Green = new Color(0.204f, 0.659f, 0.325f);

        [Header("Effect changes")]
        [SerializeField]
        [Range(0.1f, 3f)]
        [Tooltip("Seconds an effect takes to appear.")]
        private float fadeInSeconds = 0.6f;

        [SerializeField]
        [Range(0.1f, 3f)]
        [Tooltip("Seconds it takes to go away.")]
        private float fadeOutSeconds = 1f;

        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("Minimum seconds the rain stays, even if the search ends sooner.")]
        private float matrixMinSeconds = 2.5f;

        [Header("Matrix")]
        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("How much black is mixed into the backdrop color while it rains (1: black). "
                 + "Post-processing (ACES and contrast) darkens more than the number says: 0.18 leaves "
                 + "the screen 30 % darker, at 70 % luminance.")]
        private float matrixBackdropShade = 0.18f;

        [SerializeField]
        [Range(4, 80)]
        [Tooltip("Rain columns with the amount at 100 %.")]
        private int matrixColumns = 24;

        [SerializeField]
        [Range(16, 90)]
        [Tooltip("Glyphs that fit top to bottom with the size at 100 %.")]
        private int matrixRows = 36;

        [SerializeField]
        [Range(0.5f, 3f)]
        [Tooltip("Glyph glow with the brightness at 100 % (above 1 lights the bloom).")]
        private float matrixGlow = 1.4f;

        [Header("Trivia")]
        [SerializeField]
        [Range(0, 300)]
        [Tooltip("Sparkles in the burst for each correct answer, with the amount at 100 %.")]
        private int correctBurst = 45;

        [SerializeField]
        [Range(0, 600)]
        [Tooltip("Sparkles in the burst when winning the trivia.")]
        private int winBurst = 150;

        private static bool s_qualityAllows = true;

        /// <summary>The running component (one, Sonnia's).</summary>
        public static StageParticles Instance { get; private set; }

        /// <summary>False if the graphics quality has particles turned off.</summary>
        public static bool QualityAllows
        {
            get { return s_qualityAllows; }
        }

        /// <summary>Called by the graphics quality: with false no effect is shown.</summary>
        public static void SetQualityAllows(bool allowed)
        {
            s_qualityAllows = allowed;
            if (Instance != null)
            {
                Instance.ApplyVisibility();
            }
        }

        /// <summary>Current settings (the menu's).</summary>
        public ParticleSettings Settings
        {
            get { return _settings; }
        }

        /// <summary>
        /// Effect shown no matter what, to try it from the menu; null goes back
        /// to choosing according to what is happening.
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

        /// <summary>Effect that applies now (the one appearing or already visible).</summary>
        public StageEffect Showing { get; private set; }

        /// <summary>True while the orchestrator says Sonnia is searching the web (<c>search</c>).</summary>
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
        // Lifecycle
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
                // In the menu preview the correct-answer burst is also shown.
                _nextPreviewBurst = Time.time + 3.5f;
                Burst(correctBurst);
            }
        }

        // ------------------------------------------------------------------
        // Menu API
        // ------------------------------------------------------------------

        /// <summary>Changes the settings, saves them and applies them right away.</summary>
        public void EditSettings(System.Action<ParticleSettings> edit)
        {
            edit(_settings);
            _settings.Sanitize();
            ParticleSettingsStore.Save(_settings);
            ApplyTuning();
        }

        // ------------------------------------------------------------------
        // Which effect applies
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

            // An effect with amount 0 is off: the ambient one is shown instead.
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
        // Assembly
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
                Debug.LogWarning("[Sonnia] No SoniaStage/Motes in the scene: no ambient particles "
                                 + "(the studio lighting setup builds them).", this);
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
                Debug.LogWarning("[Sonnia] Missing Resources/Particles textures or the particle shader: "
                                 + "no trivia or Matrix effects.", this);
            }

            _built = true;
            ApplyTuning();
            ApplyVisibility();
        }

        /// <summary>
        /// Transparent particle material: additive (light that adds up, for the
        /// motes and Matrix) or alpha-blended (colors that show over the blue
        /// backdrop, for the trivia).
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

        /// <summary>A new particle system, stopped, in world space and with none of the defaults.</summary>
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
            // Two constants: each particle picks its glyph at birth and never changes it.
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
        // Where the stage is
        // ------------------------------------------------------------------

        /// <summary>Toward the camera from Sonnia, horizontally.</summary>
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

        /// <summary>The plane behind Sonnia (the halo's).</summary>
        private Vector3 BackPosition()
        {
            if (_halo != null)
            {
                return _halo.position;
            }

            Camera main = Camera.main;
            return main != null ? main.transform.position + main.transform.forward * 3f : Vector3.zero;
        }

        /// <summary>Sonnia's head (or, without a humanoid avatar, where it usually is).</summary>
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
        // Effects
        // ------------------------------------------------------------------

        /// <summary>An effect: its systems, its material and how visible it is (Weight, 0 to 1).</summary>
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

            /// <summary>Brightness as a color multiplier; the fade goes in the alpha.</summary>
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

            /// <summary>Starts being visible (the weight leaves 0).</summary>
            public virtual void Show()
            {
            }

            /// <summary>No longer visible (the weight reaches 0).</summary>
            public virtual void Hide()
            {
            }

            public virtual void Tick(StageParticles owner, float dt)
            {
            }

            /// <summary>Flat curve for size over lifetime (the setting goes in its multiplier).</summary>
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

        /// <summary>The stage motes, as built by the studio lighting setup.</summary>
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

                // Starts visible: it is what shows at startup.
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

        /// <summary>Colored sparkles, symbols and bursts of the trivia.</summary>
        private sealed class TriviaLayer : Layer
        {
            // Atlas cells (4 x 2): top "?", star, "!" and another "?"; bottom sparkle, dot, star and "+".
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
                ParticleSystem.MinMaxGradient colors = PartyColors();

                _sparkles = owner.NewSystem("TriviaSparkles", material, 4, 2, SparkleFrames);
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

                _symbols = owner.NewSystem("TriviaSymbols", material, 4, 2, SymbolFrames);
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

                _burst = owner.NewSystem("TriviaBurst", material, 4, 2, SparkleFrames);
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

                // From the chest, slightly behind Sonnia: they come out around her.
                _burst.transform.position = head + Vector3.down * 0.25f - forward * 0.15f;
                if (!_burst.isPlaying)
                {
                    _burst.Play();
                }

                _burst.Emit(count);
            }

            /// <summary>Sparkles between Sonnia and the halo; symbols behind her, so they do not cover her face.</summary>
            private void Place()
            {
                Vector3 back = _owner.BackPosition();
                Vector3 forward = _owner.Forward();
                Quaternion facing = Quaternion.LookRotation(-forward, Vector3.up);
                _sparkles.transform.SetPositionAndRotation(back + forward * 0.45f + Vector3.up * 0.1f, facing);
                _symbols.transform.SetPositionAndRotation(back + forward * 0.1f + Vector3.up * 0.15f, facing);
            }

            private static ParticleSystem.MinMaxGradient PartyColors()
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
        /// Matrix-style rain: columns of glyphs falling behind Sonnia. Each
        /// column carries up to two drops; the head of each drop leaves a still
        /// glyph in every cell it steps on, which is born almost white and fades
        /// to green. The script moves it (Emit), not the system's emission.
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
                _system = owner.NewSystem("MatrixRain", material, 8, 8, new Vector2(0f, 0.999f));
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
                // The rain starts already spread over the screen, not all from the top.
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

                // Rain plane: at the halo's distance, the size of what the camera sees.
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

            /// <summary>Columns spread across the width with some randomness, each with its own size and brightness.</summary>
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
