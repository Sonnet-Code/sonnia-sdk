// Graphics quality setting: High, Medium and Low levels, plus a Custom one
// that is configured option by option.
//
// We don't know what machine Sonnia will run on, so quality is chosen on the
// spot: Esc in the Sonnia window opens the menu (GraphicsQualityMenu) and
// GraphicsQualityController applies it.
//
// "High" is not a set of fixed values: it is the scene as built (URP asset,
// lights, volumes, cameras and particles). Medium and Low trim down from
// there, so if the lighting changes the levels follow it without touching this
// file. The choice is saved in PlayerPrefs and can be forced at startup
// with -quality high|medium|low|custom.

using System;
using UnityEngine;

namespace Sonia
{
    /// <summary>Level chosen in the menu.</summary>
    public enum GraphicsPreset
    {
        High = 0,
        Medium = 1,
        Low = 2,
        Custom = 3
    }

    /// <summary>Shadows: as built, trimmed, only the main light's, or none.</summary>
    public enum ShadowLevel
    {
        Off = 0,
        Low = 1,
        Medium = 2,
        High = 3
    }

    /// <summary>Edge smoothing: as built (High), medium SMAA, FXAA or none.</summary>
    public enum AntialiasLevel
    {
        Off = 0,
        Fxaa = 1,
        Smaa = 2,
        High = 3
    }

    /// <summary>Background blur (depth of field): as built, cheap Gaussian or none.</summary>
    public enum BlurLevel
    {
        Off = 0,
        Soft = 1,
        Full = 2
    }

    /// <summary>Glow (bloom): as built, without high-quality filtering, or none.</summary>
    public enum BloomLevel
    {
        Off = 0,
        Normal = 1,
        High = 2
    }

    /// <summary>A full set of options. The fixed levels come from <see cref="For"/>.</summary>
    [Serializable]
    public class GraphicsOptions
    {
        /// <summary>Resolutions offered by the menu, as a % of the built one.</summary>
        public static readonly int[] RenderScaleSteps = { 100, 90, 85, 80, 70, 60, 50 };

        /// <summary>FPS offered by the menu.</summary>
        public static readonly int[] FrameRateSteps = { 60, 30 };

        [Tooltip("Render resolution as a % of the built URP asset's.")]
        public int renderScalePercent = 100;

        [Tooltip("Below 100 %, sharp upscaling (FSR) instead of bilinear.")]
        public bool sharpUpscaling = true;

        public AntialiasLevel antialiasing = AntialiasLevel.High;
        public ShadowLevel shadows = ShadowLevel.High;

        [Tooltip("Ambient occlusion (SSAO) of the renderer, if it has one.")]
        public bool ambientOcclusion = true;

        public BlurLevel backgroundBlur = BlurLevel.Full;
        public BloomLevel bloom = BloomLevel.High;

        [Tooltip("Stage particles: the motes and the effects (StageParticles).")]
        public bool particles = true;

        public int targetFrameRate = 60;

        public GraphicsOptions Clone()
        {
            return (GraphicsOptions)MemberwiseClone();
        }

        /// <summary>The options of a fixed level (for Custom, those of High).</summary>
        public static GraphicsOptions For(GraphicsPreset preset)
        {
            switch (preset)
            {
                case GraphicsPreset.Medium:
                    return new GraphicsOptions
                    {
                        renderScalePercent = 85,
                        sharpUpscaling = true,
                        antialiasing = AntialiasLevel.Smaa,
                        shadows = ShadowLevel.Medium,
                        ambientOcclusion = false,
                        backgroundBlur = BlurLevel.Soft,
                        bloom = BloomLevel.Normal,
                        particles = true,
                        targetFrameRate = 60
                    };
                case GraphicsPreset.Low:
                    return new GraphicsOptions
                    {
                        renderScalePercent = 70,
                        sharpUpscaling = true,
                        antialiasing = AntialiasLevel.Fxaa,
                        shadows = ShadowLevel.Low,
                        ambientOcclusion = false,
                        backgroundBlur = BlurLevel.Off,
                        bloom = BloomLevel.Normal,
                        particles = false,
                        targetFrameRate = 30
                    };
                default:
                    return new GraphicsOptions();
            }
        }

        /// <summary>Fixes values the menu doesn't offer (for example, from an old PlayerPrefs).</summary>
        public void Sanitize()
        {
            renderScalePercent = Mathf.Clamp(renderScalePercent, 50, 100);
            targetFrameRate = targetFrameRate <= 30 ? 30 : 60;
            antialiasing = (AntialiasLevel)Mathf.Clamp((int)antialiasing, 0, 3);
            shadows = (ShadowLevel)Mathf.Clamp((int)shadows, 0, 3);
            backgroundBlur = (BlurLevel)Mathf.Clamp((int)backgroundBlur, 0, 2);
            bloom = (BloomLevel)Mathf.Clamp((int)bloom, 0, 2);
        }
    }

    /// <summary>What is saved: the chosen level and the Custom options.</summary>
    [Serializable]
    public class GraphicsQualityState
    {
        public GraphicsPreset preset = GraphicsPreset.High;
        public GraphicsOptions custom = new GraphicsOptions();

        /// <summary>The options being applied now.</summary>
        public GraphicsOptions Effective
        {
            get { return preset == GraphicsPreset.Custom ? custom : GraphicsOptions.For(preset); }
        }
    }

    /// <summary>Saving to PlayerPrefs and reading -quality.</summary>
    public static class GraphicsQualityStore
    {
        private const string Key = "Sonia.GraphicsQuality";

        public static GraphicsQualityState Load()
        {
            GraphicsQualityState state = null;
            try
            {
                string json = PlayerPrefs.GetString(Key, string.Empty);
                if (!string.IsNullOrEmpty(json))
                {
                    state = JsonUtility.FromJson<GraphicsQualityState>(json);
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[Sonnia] Saved graphics quality unreadable; using High: " + ex.Message);
            }

            if (state == null)
            {
                state = new GraphicsQualityState();
            }

            if (state.custom == null)
            {
                state.custom = new GraphicsOptions();
            }

            state.preset = (GraphicsPreset)Mathf.Clamp((int)state.preset, 0, 3);
            state.custom.Sanitize();
            return state;
        }

        public static void Save(GraphicsQualityState state)
        {
            PlayerPrefs.SetString(Key, JsonUtility.ToJson(state));
            PlayerPrefs.Save();
        }

        /// <summary>Level requested with -quality on the command line, or null.</summary>
        public static GraphicsPreset? CommandLinePreset()
        {
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] != "-quality")
                {
                    continue;
                }

                switch (args[i + 1].ToLowerInvariant())
                {
                    case "alta":
                    case "high":
                        return GraphicsPreset.High;
                    case "media":
                    case "medium":
                        return GraphicsPreset.Medium;
                    case "baja":
                    case "low":
                        return GraphicsPreset.Low;
                    case "personalizada":
                    case "custom":
                        return GraphicsPreset.Custom;
                }
            }

            return null;
        }

        /// <summary>Level name in the menu.</summary>
        public static string Label(GraphicsPreset preset)
        {
            switch (preset)
            {
                case GraphicsPreset.Medium:
                    return "Medium";
                case GraphicsPreset.Low:
                    return "Low";
                case GraphicsPreset.Custom:
                    return "Custom";
                default:
                    return "High";
            }
        }
    }
}
