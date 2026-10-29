// Applies the chosen graphics quality (GraphicsQuality.cs) on top of whatever
// is built in the scene.
//
// At startup (and when another scene loads) it records what is built: the
// active URP asset (resolution, upscaling, shadows), the SSAO of its
// renderers, each light's shadows, each camera's antialiasing, each volume's
// depth of field and bloom, and the particles. "High" is that as is; Medium
// and Low trim down from there. Tonemapping, LUT, vignette, reflections and
// halo are left alone.
//
// Nothing is saved to disk: volumes are modified in their runtime copy
// (Volume.profile), and what lives in assets (URP asset and SSAO) is restored
// on exit. It is created on its own at startup, without being in the scene.

using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.SceneManagement;

namespace Sonia
{
    /// <summary>Applies the graphics quality and measures frames per second.</summary>
    [DisallowMultipleComponent]
    public class GraphicsQualityController : MonoBehaviour
    {
        // Medium and Low caps over what is built.
        private const int MediumShadowResolution = 1024;
        private const int MediumShadowCascades = 2;
        private const float MediumShadowDistance = 8f;
        private const int LowShadowResolution = 1024;
        private const float LowShadowDistance = 5f;

        // Soft blur (Gaussian): starts somewhat behind the built focus.
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

        /// <summary>The running controller (one per application).</summary>
        public static GraphicsQualityController Instance { get; private set; }

        /// <summary>Current level and options.</summary>
        public GraphicsQualityState State { get; private set; }

        /// <summary>Measured frames per second (average over half a second).</summary>
        public float Fps { get; private set; }

        /// <summary>True if the built renderer has ambient occlusion (SSAO).</summary>
        public bool HasAmbientOcclusion
        {
            get { return _ssao.Count > 0; }
        }

        /// <summary>The level or some option changed.</summary>
        public event Action Changed;

        // What is built in the URP asset.
        private UniversalRenderPipelineAsset _asset;
        private float _assetRenderScale = 1f;
        private UpscalingFilterSelection _assetUpscaling;
        private float _assetShadowDistance;
        private int _assetShadowCascades;
        private int _assetMainShadowResolution;
        private int _assetAdditionalShadowResolution;
        private readonly List<FeatureEntry> _ssao = new List<FeatureEntry>();

        // What is built in the loaded scenes.
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
        // Changes from the menu
        // ------------------------------------------------------------------

        /// <summary>Switches to a level. Entering Custom starts from what is shown now.</summary>
        public void SetPreset(GraphicsPreset preset)
        {
            if (preset == GraphicsPreset.Custom && State.preset != GraphicsPreset.Custom)
            {
                State.custom = State.Effective.Clone();
            }

            State.preset = preset;
            Commit();
        }

        /// <summary>Changes an option: switches to Custom starting from what is shown now.</summary>
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
        // Capturing what is built
        // ------------------------------------------------------------------

        private void CaptureAsset()
        {
            _asset = GraphicsSettings.currentRenderPipeline as UniversalRenderPipelineAsset;
            if (_asset == null)
            {
                Debug.LogWarning("[Sonnia] Graphics quality: no active URP asset; only the scene is adjusted.");
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

        /// <summary>Records what is built on objects not yet known.</summary>
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
                // Cameras without antialiasing (UI, captures) are left as they are.
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

                // Runtime copy: whatever is changed here doesn't reach the profile asset.
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
        // Apply
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

            // The stage effects are switched on by StageParticles.
            StageParticles.SetQualityAllows(options.particles);

            Application.targetFrameRate = options.targetFrameRate;
            Debug.Log(
                "[Sonnia] Graphics quality " + GraphicsQualityStore.Label(State.preset) + ": render "
                + options.renderScalePercent + " %, shadows " + options.shadows + ", antialiasing "
                + options.antialiasing + ", SSAO " + (options.ambientOcclusion ? "yes" : "no") + ", blur "
                + options.backgroundBlur + ", bloom " + options.bloom + ", particles "
                + (options.particles ? "yes" : "no") + ", " + options.targetFrameRate + " FPS",
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
            // On Low only the light that cast the strongest shadow keeps casting, with its built type:
            // a hard hair shadow would cross the face with a jagged line.
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
                    // The mode is always set: what comes out of here overrides the profile.
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
                                // Bokeh focuses at a distance; Gaussian starts behind it.
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

        /// <summary>Restores the URP asset and the SSAO to how they were built.</summary>
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
