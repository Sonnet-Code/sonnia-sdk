// Stage particle settings (StageParticles): amount, speed, size and
// brightness of each effect, and whether the effect switches on its own
// depending on what is happening. They are edited in the options menu
// (Esc > Particles, ParticleSettingsMenu) and saved on this machine
// (PlayerPrefs), like the graphics quality. Everything is a % of the built-in
// look: 100 % is the design.

using System;
using UnityEngine;

namespace Sonia
{
    /// <summary>The stage particle effects, one at a time.</summary>
    public enum StageEffect
    {
        /// <summary>The usual ambient motes.</summary>
        Ambient = 0,

        /// <summary>Colored sparkles and symbols during a trivia round.</summary>
        Trivia = 1,

        /// <summary>Green glyph rain while Sonnia searches the web.</summary>
        Matrix = 2
    }

    /// <summary>Settings of one effect, as a % of the built-in look.</summary>
    [Serializable]
    public class EffectTuning
    {
        [Tooltip("How many particles (0 turns the effect off).")]
        public int amount = 100;

        [Tooltip("How fast they move.")]
        public int speed = 100;

        [Tooltip("Their size.")]
        public int size = 100;

        [Tooltip("Their brightness.")]
        public int brightness = 100;

        public float Amount
        {
            get { return amount / 100f; }
        }

        public float Speed
        {
            get { return speed / 100f; }
        }

        public float Size
        {
            get { return size / 100f; }
        }

        public float Brightness
        {
            get { return brightness / 100f; }
        }

        /// <summary>Fixes values the menu does not offer (for example, from an old PlayerPrefs).</summary>
        public void Sanitize()
        {
            amount = Mathf.Clamp(amount, 0, 400);
            speed = Mathf.Clamp(speed, 25, 300);
            size = Mathf.Clamp(size, 50, 500);
            brightness = Mathf.Clamp(brightness, 25, 300);
        }
    }

    /// <summary>What is saved: one <see cref="EffectTuning"/> per effect and whether they switch on their own.</summary>
    [Serializable]
    public class ParticleSettings
    {
        /// <summary>Values the menu offers, in %.</summary>
        public static readonly int[] AmountSteps = { 0, 25, 50, 75, 100, 125, 150, 200, 300, 400 };

        public static readonly int[] SpeedSteps = { 25, 50, 75, 100, 125, 150, 200, 300 };
        public static readonly int[] SizeSteps = { 50, 75, 100, 125, 150, 200, 300, 400, 500 };
        public static readonly int[] BrightnessSteps = { 25, 50, 75, 100, 125, 150, 200, 300 };

        [Tooltip("Automatic switching: the trivia effect during trivia and Matrix when Sonnia searches the web.")]
        public bool contextual = true;

        public EffectTuning ambient = new EffectTuning();
        public EffectTuning trivia = new EffectTuning();
        public EffectTuning matrix = new EffectTuning();

        /// <summary>The settings of one effect.</summary>
        public EffectTuning For(StageEffect effect)
        {
            switch (effect)
            {
                case StageEffect.Trivia:
                    return trivia;
                case StageEffect.Matrix:
                    return matrix;
                default:
                    return ambient;
            }
        }

        /// <summary>Resets an effect to the built-in look.</summary>
        public void Reset(StageEffect effect)
        {
            switch (effect)
            {
                case StageEffect.Trivia:
                    trivia = new EffectTuning();
                    break;
                case StageEffect.Matrix:
                    matrix = new EffectTuning();
                    break;
                default:
                    ambient = new EffectTuning();
                    break;
            }
        }

        public void Sanitize()
        {
            ambient = ambient ?? new EffectTuning();
            trivia = trivia ?? new EffectTuning();
            matrix = matrix ?? new EffectTuning();
            ambient.Sanitize();
            trivia.Sanitize();
            matrix.Sanitize();
        }

        /// <summary>Effect name in the menu.</summary>
        public static string Label(StageEffect effect)
        {
            switch (effect)
            {
                case StageEffect.Trivia:
                    return "Trivia";
                case StageEffect.Matrix:
                    return "Matrix";
                default:
                    return "Ambient";
            }
        }
    }

    /// <summary>Storage in PlayerPrefs.</summary>
    public static class ParticleSettingsStore
    {
        /// <summary>PlayerPrefs key.</summary>
        public const string Key = "Sonia.Particles";

        public static ParticleSettings Load()
        {
            ParticleSettings settings = null;
            try
            {
                string json = PlayerPrefs.GetString(Key, string.Empty);
                if (!string.IsNullOrEmpty(json))
                {
                    settings = JsonUtility.FromJson<ParticleSettings>(json);
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[Sonnia] Unreadable particle settings; using the defaults: " + ex.Message);
            }

            settings = settings ?? new ParticleSettings();
            settings.Sanitize();
            return settings;
        }

        public static void Save(ParticleSettings settings)
        {
            PlayerPrefs.SetString(Key, JsonUtility.ToJson(settings));
            PlayerPrefs.Save();
        }
    }
}
