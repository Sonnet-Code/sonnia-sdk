// Ajuste de calidad gráfica: niveles Alta, Media y Baja, y uno Personalizado
// que se configura opción a opción.
//
// No sabemos en qué equipo correrá Sonia en el stand, así que la calidad se
// elige allí mismo: Esc en la ventana de Sonia abre el menú
// (GraphicsQualityMenu) y GraphicsQualityController lo aplica.
//
// «Alta» no son valores fijos: es la escena tal como está montada (URP asset,
// luces, volúmenes, cámaras y partículas). Media y Baja recortan desde ahí, de
// modo que si cambia la iluminación los niveles la siguen sin tocar este
// archivo. La elección se guarda en PlayerPrefs y se puede forzar al arrancar
// con -quality alta|media|baja|personalizada.

using System;
using UnityEngine;

namespace Sonia
{
    /// <summary>Nivel elegido en el menú.</summary>
    public enum GraphicsPreset
    {
        High = 0,
        Medium = 1,
        Low = 2,
        Custom = 3
    }

    /// <summary>Sombras: como están montadas, recortadas, solo la de la luz principal, o ninguna.</summary>
    public enum ShadowLevel
    {
        Off = 0,
        Low = 1,
        Medium = 2,
        High = 3
    }

    /// <summary>Suavizado de bordes: como está montado (High), SMAA medio, FXAA o nada.</summary>
    public enum AntialiasLevel
    {
        Off = 0,
        Fxaa = 1,
        Smaa = 2,
        High = 3
    }

    /// <summary>Desenfoque del fondo (profundidad de campo): como está montado, gaussiano barato o nada.</summary>
    public enum BlurLevel
    {
        Off = 0,
        Soft = 1,
        Full = 2
    }

    /// <summary>Brillo (bloom): como está montado, sin filtrado de alta calidad, o nada.</summary>
    public enum BloomLevel
    {
        Off = 0,
        Normal = 1,
        High = 2
    }

    /// <summary>Un juego completo de opciones. Los niveles fijos salen de <see cref="For"/>.</summary>
    [Serializable]
    public class GraphicsOptions
    {
        /// <summary>Resoluciones que ofrece el menú, en % de la montada.</summary>
        public static readonly int[] RenderScaleSteps = { 100, 90, 85, 80, 70, 60, 50 };

        /// <summary>FPS que ofrece el menú.</summary>
        public static readonly int[] FrameRateSteps = { 60, 30 };

        [Tooltip("Resolución de render en % de la del URP asset montado.")]
        public int renderScalePercent = 100;

        [Tooltip("Por debajo del 100 %, reescalado nítido (FSR) en vez de bilineal.")]
        public bool sharpUpscaling = true;

        public AntialiasLevel antialiasing = AntialiasLevel.High;
        public ShadowLevel shadows = ShadowLevel.High;

        [Tooltip("Oclusión ambiental (SSAO) del renderer, si la tiene.")]
        public bool ambientOcclusion = true;

        public BlurLevel backgroundBlur = BlurLevel.Full;
        public BloomLevel bloom = BloomLevel.High;

        [Tooltip("Partículas del escenario: las motas y los efectos de la trivia y de Matrix (StageParticles).")]
        public bool particles = true;

        public int targetFrameRate = 60;

        public GraphicsOptions Clone()
        {
            return (GraphicsOptions)MemberwiseClone();
        }

        /// <summary>Las opciones de un nivel fijo (para Custom, las de Alta).</summary>
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

        /// <summary>Corrige valores que no ofrece el menú (por ejemplo, de un PlayerPrefs viejo).</summary>
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

    /// <summary>Lo que se guarda: el nivel elegido y las opciones del Personalizado.</summary>
    [Serializable]
    public class GraphicsQualityState
    {
        public GraphicsPreset preset = GraphicsPreset.High;
        public GraphicsOptions custom = new GraphicsOptions();

        /// <summary>Las opciones que se aplican ahora.</summary>
        public GraphicsOptions Effective
        {
            get { return preset == GraphicsPreset.Custom ? custom : GraphicsOptions.For(preset); }
        }
    }

    /// <summary>Guardado en PlayerPrefs y lectura de -quality.</summary>
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
                Debug.LogWarning("[Sonia] Calidad gráfica guardada ilegible; se usa Alta: " + ex.Message);
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

        /// <summary>Nivel pedido con -quality en la línea de comandos, o null.</summary>
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

        /// <summary>Nombre del nivel en el menú.</summary>
        public static string Label(GraphicsPreset preset)
        {
            switch (preset)
            {
                case GraphicsPreset.Medium:
                    return "Media";
                case GraphicsPreset.Low:
                    return "Baja";
                case GraphicsPreset.Custom:
                    return "Personalizada";
                default:
                    return "Alta";
            }
        }
    }
}
