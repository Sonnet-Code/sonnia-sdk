// Aplica la calidad gráfica elegida (GraphicsQuality.cs) sobre lo que haya
// montado en la escena.
//
// Al arrancar (y al cargar otra escena) apunta lo montado: el URP asset activo
// (resolución, reescalado, sombras), el SSAO de sus renderers, las sombras de
// cada luz, el suavizado de cada cámara, la profundidad de campo y el bloom de
// cada volumen, y las partículas. «Alta» es eso tal cual; Media y Baja
// recortan desde ahí. Tonemapping, LUT, viñeta, reflejos y halo no se tocan.
//
// Nada se guarda en disco: los volúmenes se tocan en su copia de ejecución
// (Volume.profile), y lo que vive en assets (URP asset y SSAO) se devuelve a
// como estaba al salir. Se crea solo al arrancar, sin estar en la escena.

using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.SceneManagement;

namespace Sonia
{
    /// <summary>Aplica la calidad gráfica y mide los fotogramas por segundo.</summary>
    [DisallowMultipleComponent]
    public class GraphicsQualityController : MonoBehaviour
    {
        // Topes de Media y Baja sobre lo montado.
        private const int MediumShadowResolution = 1024;
        private const int MediumShadowCascades = 2;
        private const float MediumShadowDistance = 8f;
        private const int LowShadowResolution = 1024;
        private const float LowShadowDistance = 5f;

        // Desenfoque suave (gaussiano): empieza algo detrás del foco montado.
        private const float SoftBlurStartBehindFocus = 0.6f;
        private const float SoftBlurLength = 4f;

        private const float FpsWindowSeconds = 0.5f;

        private struct LightEntry
        {
            public Light Light;
            public LightShadows Shadows;
        }

        private struct CameraEntry
        {
            public UniversalAdditionalCameraData Data;
            public AntialiasingMode Mode;
            public AntialiasingQuality Quality;
        }

        private struct VolumeEntry
        {
            public DepthOfField Dof;
            public bool DofModeOverride;
            public DepthOfFieldMode DofMode;
            public float GaussianStart;
            public float GaussianEnd;
            public float FocusDistance;
            public Bloom Bloom;
            public bool BloomActive;
            public bool BloomHighQualityOverride;
            public bool BloomHighQuality;
        }

        private struct ParticleEntry
        {
            public ParticleSystemRenderer Renderer;
            public bool Enabled;
        }

        private struct FeatureEntry
        {
            public ScriptableRendererFeature Feature;
            public bool Active;
        }

        /// <summary>El controlador en marcha (uno por aplicación).</summary>
        public static GraphicsQualityController Instance { get; private set; }

        /// <summary>Nivel y opciones actuales.</summary>
        public GraphicsQualityState State { get; private set; }

        /// <summary>Fotogramas por segundo medidos (media de medio segundo).</summary>
        public float Fps { get; private set; }

        /// <summary>Cierto si el renderer montado tiene oclusión ambiental (SSAO).</summary>
        public bool HasAmbientOcclusion
        {
            get { return _ssao.Count > 0; }
        }

        /// <summary>Cambió el nivel o alguna opción.</summary>
        public event Action Changed;

        // Lo montado en el URP asset.
        private UniversalRenderPipelineAsset _asset;
        private float _assetRenderScale = 1f;
        private UpscalingFilterSelection _assetUpscaling;
        private float _assetShadowDistance;
        private int _assetShadowCascades;
        private int _assetMainShadowResolution;
        private int _assetAdditionalShadowResolution;
        private readonly List<FeatureEntry> _ssao = new List<FeatureEntry>();

        // Lo montado en las escenas cargadas.
        private readonly HashSet<UnityEngine.Object> _captured = new HashSet<UnityEngine.Object>();
        private readonly List<LightEntry> _lights = new List<LightEntry>();
        private readonly List<CameraEntry> _cameras = new List<CameraEntry>();
        private readonly List<VolumeEntry> _volumes = new List<VolumeEntry>();
        private readonly List<ParticleEntry> _particles = new List<ParticleEntry>();

        private int _fpsFrames;
        private float _fpsTime;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void CreateOnStart()
        {
            if (Instance != null)
            {
                return;
            }

            GameObject go = new GameObject("SoniaGraphicsQuality");
            DontDestroyOnLoad(go);
            go.AddComponent<GraphicsQualityController>();
            go.AddComponent<GraphicsQualityMenu>();
            go.AddComponent<SoniaOptionsMenu>();
        }

        private void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Destroy(this);
                return;
            }

            Instance = this;
            State = GraphicsQualityStore.Load();
            GraphicsPreset? forced = GraphicsQualityStore.CommandLinePreset();
            if (forced.HasValue)
            {
                State.preset = forced.Value;
            }

            CaptureAsset();
            CaptureScenes();
            SceneManager.sceneLoaded += HandleSceneLoaded;
            Apply();
        }

        private void OnDestroy()
        {
            SceneManager.sceneLoaded -= HandleSceneLoaded;
            RestoreAssets();
            if (Instance == this)
            {
                Instance = null;
            }
        }

        private void OnApplicationQuit()
        {
            RestoreAssets();
        }

        private void Update()
        {
            _fpsFrames++;
            _fpsTime += Time.unscaledDeltaTime;
            if (_fpsTime >= FpsWindowSeconds)
            {
                Fps = _fpsFrames / _fpsTime;
                _fpsFrames = 0;
                _fpsTime = 0f;
            }
        }

        // ------------------------------------------------------------------
        // Cambios desde el menú
        // ------------------------------------------------------------------

        /// <summary>Pasa a un nivel. Al entrar en Personalizada se parte de lo que se ve ahora.</summary>
        public void SetPreset(GraphicsPreset preset)
        {
            if (preset == GraphicsPreset.Custom && State.preset != GraphicsPreset.Custom)
            {
                State.custom = State.Effective.Clone();
            }

            State.preset = preset;
            Commit();
        }

        /// <summary>Cambia una opción: pasa a Personalizada partiendo de lo que se ve ahora.</summary>
        public void EditCustom(Action<GraphicsOptions> edit)
        {
            if (State.preset != GraphicsPreset.Custom)
            {
                State.custom = State.Effective.Clone();
                State.preset = GraphicsPreset.Custom;
            }

            edit(State.custom);
            State.custom.Sanitize();
            Commit();
        }

        private void Commit()
        {
            GraphicsQualityStore.Save(State);
            Apply();
            if (Changed != null)
            {
                Changed();
            }
        }

        // ------------------------------------------------------------------
        // Captura de lo montado
        // ------------------------------------------------------------------

        private void CaptureAsset()
        {
            _asset = GraphicsSettings.currentRenderPipeline as UniversalRenderPipelineAsset;
            if (_asset == null)
            {
                Debug.LogWarning("[Sonia] Calidad gráfica: no hay URP asset activo; solo se ajusta la escena.");
                return;
            }

            _assetRenderScale = _asset.renderScale;
            _assetUpscaling = _asset.upscalingFilter;
            _assetShadowDistance = _asset.shadowDistance;
            _assetShadowCascades = _asset.shadowCascadeCount;
            _assetMainShadowResolution = _asset.mainLightShadowmapResolution;
            _assetAdditionalShadowResolution = _asset.additionalLightsShadowmapResolution;

            foreach (ScriptableRendererData data in _asset.rendererDataList)
            {
                if (data == null)
                {
                    continue;
                }

                foreach (ScriptableRendererFeature feature in data.rendererFeatures)
                {
                    if (feature != null && feature.GetType().Name == "ScreenSpaceAmbientOcclusion")
                    {
                        _ssao.Add(new FeatureEntry { Feature = feature, Active = feature.isActive });
                    }
                }
            }
        }

        private void HandleSceneLoaded(Scene scene, LoadSceneMode mode)
        {
            CaptureScenes();
            Apply();
        }

        /// <summary>Apunta lo montado en los objetos que aún no se conocían.</summary>
        private void CaptureScenes()
        {
            _lights.RemoveAll(e => e.Light == null);
            _cameras.RemoveAll(e => e.Data == null);
            _volumes.RemoveAll(e => e.Dof == null && e.Bloom == null);
            _particles.RemoveAll(e => e.Renderer == null);

            foreach (Light light in FindObjectsByType<Light>(FindObjectsInactive.Include))
            {
                if (_captured.Add(light))
                {
                    _lights.Add(new LightEntry { Light = light, Shadows = light.shadows });
                }
            }

            foreach (UniversalAdditionalCameraData data in
                     FindObjectsByType<UniversalAdditionalCameraData>(FindObjectsInactive.Include))
            {
                // Las cámaras sin suavizado (interfaz, capturas) se dejan como están.
                if (_captured.Add(data) && data.antialiasing != AntialiasingMode.None)
                {
                    _cameras.Add(new CameraEntry { Data = data, Mode = data.antialiasing, Quality = data.antialiasingQuality });
                }
            }

            foreach (Volume volume in FindObjectsByType<Volume>(FindObjectsInactive.Include))
            {
                if (!_captured.Add(volume) || (volume.sharedProfile == null && !volume.HasInstantiatedProfile()))
                {
                    continue;
                }

                // Copia de ejecución: lo que se toque aquí no llega al asset del perfil.
                VolumeProfile profile = volume.profile;
                VolumeEntry entry = new VolumeEntry();
                DepthOfField dof;
                if (profile.TryGet(out dof))
                {
                    entry.Dof = dof;
                    entry.DofModeOverride = dof.mode.overrideState;
                    entry.DofMode = dof.mode.value;
                    entry.GaussianStart = dof.gaussianStart.value;
                    entry.GaussianEnd = dof.gaussianEnd.value;
                    entry.FocusDistance = dof.focusDistance.value;
                }

                Bloom bloom;
                if (profile.TryGet(out bloom))
                {
                    entry.Bloom = bloom;
                    entry.BloomActive = bloom.active;
                    entry.BloomHighQualityOverride = bloom.highQualityFiltering.overrideState;
                    entry.BloomHighQuality = bloom.highQualityFiltering.value;
                }

                if (entry.Dof != null || entry.Bloom != null)
                {
                    _volumes.Add(entry);
                }
            }

            foreach (ParticleSystemRenderer particles in
                     FindObjectsByType<ParticleSystemRenderer>(FindObjectsInactive.Include))
            {
                if (_captured.Add(particles))
                {
                    _particles.Add(new ParticleEntry { Renderer = particles, Enabled = particles.enabled });
                }
            }
        }

        // ------------------------------------------------------------------
        // Aplicar
        // ------------------------------------------------------------------

        private void Apply()
        {
            GraphicsOptions options = State.Effective;
            ApplyAsset(options);
            ApplyLights(options.shadows);
            ApplyCameras(options.antialiasing);
            ApplyVolumes(options);
            foreach (ParticleEntry entry in _particles)
            {
                if (entry.Renderer != null)
                {
                    entry.Renderer.enabled = options.particles && entry.Enabled;
                }
            }

            Application.targetFrameRate = options.targetFrameRate;
            Debug.Log(
                "[Sonia] Calidad gráfica " + GraphicsQualityStore.Label(State.preset) + ": render "
                + options.renderScalePercent + " %, sombras " + options.shadows + ", suavizado "
                + options.antialiasing + ", SSAO " + (options.ambientOcclusion ? "sí" : "no") + ", desenfoque "
                + options.backgroundBlur + ", bloom " + options.bloom + ", partículas "
                + (options.particles ? "sí" : "no") + ", " + options.targetFrameRate + " FPS",
                this);
        }

        private void ApplyAsset(GraphicsOptions options)
        {
            if (_asset == null)
            {
                return;
            }

            _asset.renderScale = _assetRenderScale * options.renderScalePercent / 100f;
            _asset.upscalingFilter = options.renderScalePercent < 100
                ? (options.sharpUpscaling ? UpscalingFilterSelection.FSR : UpscalingFilterSelection.Linear)
                : _assetUpscaling;

            float distance = _assetShadowDistance;
            int cascades = _assetShadowCascades;
            int mainResolution = _assetMainShadowResolution;
            int additionalResolution = _assetAdditionalShadowResolution;
            if (options.shadows == ShadowLevel.Medium)
            {
                distance = Mathf.Min(distance, MediumShadowDistance);
                cascades = Mathf.Min(cascades, MediumShadowCascades);
                mainResolution = Mathf.Min(mainResolution, MediumShadowResolution);
                additionalResolution = Mathf.Min(additionalResolution, MediumShadowResolution);
            }
            else if (options.shadows == ShadowLevel.Low)
            {
                distance = Mathf.Min(distance, LowShadowDistance);
                cascades = 1;
                mainResolution = Mathf.Min(mainResolution, LowShadowResolution);
                additionalResolution = Mathf.Min(additionalResolution, LowShadowResolution);
            }

            _asset.shadowDistance = distance;
            _asset.shadowCascadeCount = cascades;
            _asset.mainLightShadowmapResolution = mainResolution;
            _asset.additionalLightsShadowmapResolution = additionalResolution;

            foreach (FeatureEntry entry in _ssao)
            {
                if (entry.Feature != null)
                {
                    entry.Feature.SetActive(entry.Active && options.ambientOcclusion);
                }
            }
        }

        private void ApplyLights(ShadowLevel level)
        {
            // En Baja solo da sombra la luz que más sombra daba, con su tipo montado:
            // una sombra dura del pelo cruza la cara con una línea dentada.
            Light strongest = null;
            float strongestStrength = -1f;
            foreach (LightEntry entry in _lights)
            {
                if (entry.Light != null && entry.Shadows != LightShadows.None
                    && entry.Light.shadowStrength > strongestStrength)
                {
                    strongest = entry.Light;
                    strongestStrength = entry.Light.shadowStrength;
                }
            }

            foreach (LightEntry entry in _lights)
            {
                if (entry.Light == null)
                {
                    continue;
                }

                LightShadows shadows = entry.Shadows;
                if (level == ShadowLevel.Off)
                {
                    shadows = LightShadows.None;
                }
                else if (level == ShadowLevel.Low)
                {
                    shadows = entry.Light == strongest ? entry.Shadows : LightShadows.None;
                }

                entry.Light.shadows = shadows;
            }
        }

        private void ApplyCameras(AntialiasLevel level)
        {
            foreach (CameraEntry entry in _cameras)
            {
                if (entry.Data == null)
                {
                    continue;
                }

                switch (level)
                {
                    case AntialiasLevel.Off:
                        entry.Data.antialiasing = AntialiasingMode.None;
                        break;
                    case AntialiasLevel.Fxaa:
                        entry.Data.antialiasing = AntialiasingMode.FastApproximateAntialiasing;
                        break;
                    case AntialiasLevel.Smaa:
                        entry.Data.antialiasing = AntialiasingMode.SubpixelMorphologicalAntiAliasing;
                        entry.Data.antialiasingQuality = AntialiasingQuality.Medium;
                        break;
                    default:
                        entry.Data.antialiasing = entry.Mode;
                        entry.Data.antialiasingQuality = entry.Quality;
                        break;
                }
            }
        }

        private void ApplyVolumes(GraphicsOptions options)
        {
            foreach (VolumeEntry entry in _volumes)
            {
                DepthOfField dof = entry.Dof;
                if (dof != null && entry.DofMode != DepthOfFieldMode.Off)
                {
                    // Siempre se fija el modo: lo que sale de aquí manda sobre el perfil.
                    dof.mode.overrideState = entry.DofModeOverride || options.backgroundBlur != BlurLevel.Full;
                    dof.gaussianStart.value = entry.GaussianStart;
                    dof.gaussianEnd.value = entry.GaussianEnd;
                    switch (options.backgroundBlur)
                    {
                        case BlurLevel.Off:
                            dof.mode.value = DepthOfFieldMode.Off;
                            break;
                        case BlurLevel.Soft:
                            dof.mode.value = DepthOfFieldMode.Gaussian;
                            if (entry.DofMode != DepthOfFieldMode.Gaussian)
                            {
                                // El bokeh enfoca a una distancia; el gaussiano empieza detrás de ella.
                                dof.gaussianStart.overrideState = true;
                                dof.gaussianEnd.overrideState = true;
                                dof.gaussianStart.value = entry.FocusDistance + SoftBlurStartBehindFocus;
                                dof.gaussianEnd.value = entry.FocusDistance + SoftBlurStartBehindFocus + SoftBlurLength;
                            }

                            break;
                        default:
                            dof.mode.value = entry.DofMode;
                            break;
                    }
                }

                Bloom bloom = entry.Bloom;
                if (bloom != null && entry.BloomActive)
                {
                    bloom.active = options.bloom != BloomLevel.Off;
                    if (options.bloom == BloomLevel.Normal)
                    {
                        bloom.highQualityFiltering.overrideState = true;
                        bloom.highQualityFiltering.value = false;
                    }
                    else
                    {
                        bloom.highQualityFiltering.overrideState = entry.BloomHighQualityOverride;
                        bloom.highQualityFiltering.value = entry.BloomHighQuality;
                    }
                }
            }
        }

        /// <summary>Devuelve el URP asset y el SSAO a como estaban montados.</summary>
        private void RestoreAssets()
        {
            if (_asset != null)
            {
                _asset.renderScale = _assetRenderScale;
                _asset.upscalingFilter = _assetUpscaling;
                _asset.shadowDistance = _assetShadowDistance;
                _asset.shadowCascadeCount = _assetShadowCascades;
                _asset.mainLightShadowmapResolution = _assetMainShadowResolution;
                _asset.additionalLightsShadowmapResolution = _assetAdditionalShadowResolution;
            }

            foreach (FeatureEntry entry in _ssao)
            {
                if (entry.Feature != null)
                {
                    entry.Feature.SetActive(entry.Active);
                }
            }
        }
    }
}
