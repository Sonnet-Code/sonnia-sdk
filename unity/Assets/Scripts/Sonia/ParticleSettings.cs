// Ajustes de las partículas del escenario (StageParticles): cantidad,
// velocidad, tamaño y brillo de cada efecto, y si el efecto cambia solo según
// lo que pasa. Se tocan en el menú de opciones (Esc > Partículas,
// ParticleSettingsMenu) y se guardan en este equipo (PlayerPrefs), como la
// calidad gráfica. Todo va en % de como está montado: 100 % es el diseño.

using System;
using UnityEngine;

namespace Sonia
{
    /// <summary>Los efectos de partículas del escenario, de uno en uno.</summary>
    public enum StageEffect
    {
        /// <summary>Las motas de siempre.</summary>
        Ambient = 0,

        /// <summary>Destellos y símbolos de colores mientras hay una trivia.</summary>
        Trivia = 1,

        /// <summary>Lluvia de glifos verdes mientras Sonia busca en internet o tarda en pensar.</summary>
        Matrix = 2
    }

    /// <summary>Ajustes de un efecto, en % de como está montado.</summary>
    [Serializable]
    public class EffectTuning
    {
        [Tooltip("Cuántas partículas (0 apaga el efecto).")]
        public int amount = 100;

        [Tooltip("Lo rápido que se mueven.")]
        public int speed = 100;

        [Tooltip("Su tamaño.")]
        public int size = 100;

        [Tooltip("Su brillo.")]
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

        /// <summary>Corrige valores que no ofrece el menú (por ejemplo, de un PlayerPrefs viejo).</summary>
        public void Sanitize()
        {
            amount = Mathf.Clamp(amount, 0, 400);
            speed = Mathf.Clamp(speed, 25, 300);
            size = Mathf.Clamp(size, 50, 500);
            brightness = Mathf.Clamp(brightness, 25, 300);
        }
    }

    /// <summary>Lo que se guarda: un <see cref="EffectTuning"/> por efecto y si cambian solos.</summary>
    [Serializable]
    public class ParticleSettings
    {
        /// <summary>Valores que ofrece el menú, en %.</summary>
        public static readonly int[] AmountSteps = { 0, 25, 50, 75, 100, 125, 150, 200, 300, 400 };

        public static readonly int[] SpeedSteps = { 25, 50, 75, 100, 125, 150, 200, 300 };
        public static readonly int[] SizeSteps = { 50, 75, 100, 125, 150, 200, 300, 400, 500 };
        public static readonly int[] BrightnessSteps = { 25, 50, 75, 100, 125, 150, 200, 300 };

        [Tooltip("Cambio automático: el efecto de la trivia durante la trivia y Matrix cuando Sonia busca o tarda.")]
        public bool contextual = true;

        public EffectTuning ambient = new EffectTuning();
        public EffectTuning trivia = new EffectTuning();
        public EffectTuning matrix = new EffectTuning();

        /// <summary>Los ajustes de un efecto.</summary>
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

        /// <summary>Vuelve un efecto a como está montado.</summary>
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

        /// <summary>Nombre del efecto en el menú.</summary>
        public static string Label(StageEffect effect)
        {
            switch (effect)
            {
                case StageEffect.Trivia:
                    return "Trivia";
                case StageEffect.Matrix:
                    return "Matrix";
                default:
                    return "Ambiente";
            }
        }
    }

    /// <summary>Guardado en PlayerPrefs.</summary>
    public static class ParticleSettingsStore
    {
        /// <summary>Clave de PlayerPrefs (el laboratorio de cara la deja como estaba al terminar).</summary>
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
                Debug.LogWarning("[Sonia] Ajustes de partículas ilegibles; se usan los de fábrica: " + ex.Message);
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
