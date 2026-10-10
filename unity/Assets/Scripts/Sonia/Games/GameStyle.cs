// Colores, curvas y utilidades de las pantallas de los juegos: los mismos de la
// trivia (TriviaController) y de la pantalla del stand (StageScreen, diseño F),
// para que todos los juegos se vean de la misma familia.

using System.Text;
using UnityEngine;

namespace Sonia
{
    /// <summary>Colores de los juegos: los de Google (DevFest), las tarjetas de la trivia y la marca.</summary>
    public static class GameColors
    {
        // Colores de Google, los del DevFest y de la trivia.
        public static readonly Color Blue = new Color(0.259f, 0.522f, 0.957f);
        public static readonly Color Red = new Color(0.918f, 0.263f, 0.208f);
        public static readonly Color Yellow = new Color(0.984f, 0.737f, 0.02f);
        public static readonly Color Green = new Color(0.204f, 0.659f, 0.325f);

        /// <summary>Azul, rojo, amarillo y verde, en ese orden (como las letras de la trivia).</summary>
        public static readonly Color[] Google = { Blue, Red, Yellow, Green };

        // Tarjetas, como las de la trivia.
        public static readonly Color CardFill = new Color(0.035f, 0.07f, 0.15f, 0.93f);

        /// <summary>
        /// Lo que se ve de <see cref="CardFill"/> sobre el escenario (medido en las
        /// capturas), pero opaco: la tarjeta de los juegos lo usa para que lo que vaya
        /// detrás (los destellos) no se transparente.
        /// </summary>
        public static readonly Color CardFillOpaque = new Color32(27, 44, 74, 255);
        public static readonly Color CardBorder = new Color(0.44f, 0.66f, 1f, 0.55f);
        public static readonly Color OptionFill = new Color(0.1f, 0.16f, 0.3f, 0.96f);
        public static readonly Color RightFill = new Color(0.12f, 0.56f, 0.27f, 1f);
        public static readonly Color WrongFill = new Color(0.8f, 0.2f, 0.17f, 1f);

        /// <summary>Texto secundario sobre las tarjetas oscuras (contadores, frases).</summary>
        public static readonly Color Muted = new Color(0.68f, 0.75f, 0.88f, 1f);

        // Marca de Sonnet Code (diseño F de la pantalla).
        public static readonly Color Navy = new Color32(20, 39, 82, 255);
        public static readonly Color Brand = new Color32(3, 113, 245, 255);
        public static readonly Color Dark = new Color32(11, 19, 34, 255);

        /// <summary>El punto rojo de «En vivo».</summary>
        public static readonly Color Live = new Color(0.96f, 0.22f, 0.2f, 1f);

        /// <summary>Dorado del resultado ganador.</summary>
        public static readonly Color Gold = new Color(1f, 0.93f, 0.55f, 1f);
    }

    /// <summary>Utilidades de UI y curvas de animación para los juegos.</summary>
    public static class GameUi
    {
        /// <summary>Ocupa todo el padre.</summary>
        public static void Stretch(RectTransform rect)
        {
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
        }

        /// <summary>
        /// Centrado en horizontal, con su borde de arriba a <paramref name="topFraction"/>
        /// del alto de la pantalla (0 arriba), del tamaño dado (píxeles de la referencia).
        /// </summary>
        public static void PlaceTop(RectTransform rect, float topFraction, Vector2 size)
        {
            rect.anchorMin = new Vector2(0.5f, 1f - topFraction);
            rect.anchorMax = rect.anchorMin;
            rect.pivot = new Vector2(0.5f, 1f);
            rect.anchoredPosition = Vector2.zero;
            rect.sizeDelta = size;
        }

        /// <summary>Centrado en su padre, del tamaño dado.</summary>
        public static void PlaceCenter(RectTransform rect, Vector2 position, Vector2 size)
        {
            rect.anchorMin = new Vector2(0.5f, 0.5f);
            rect.anchorMax = rect.anchorMin;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = position;
            rect.sizeDelta = size;
        }

        public static Color WithAlpha(Color color, float alpha)
        {
            color.a = alpha;
            return color;
        }

        /// <summary>Texto con cada letra en un color de Google (los espacios no gastan color), en texto enriquecido.</summary>
        public static string ColoredWord(string word)
        {
            if (string.IsNullOrEmpty(word))
            {
                return string.Empty;
            }

            StringBuilder builder = new StringBuilder(word.Length * 24);
            int index = 0;
            for (int i = 0; i < word.Length; i++)
            {
                char c = word[i];
                if (char.IsWhiteSpace(c))
                {
                    builder.Append(c);
                    continue;
                }

                Color color = GameColors.Google[index % GameColors.Google.Length];
                index++;
                builder.Append("<color=#").Append(ColorUtility.ToHtmlStringRGB(color)).Append('>')
                       .Append(Escape(c)).Append("</color>");
            }

            return builder.ToString();
        }

        /// <summary>Quita lo que TextMeshPro leería como etiquetas (texto que llega del orquestador).</summary>
        public static string Plain(string text)
        {
            return string.IsNullOrEmpty(text) ? string.Empty : text.Replace('<', '‹').Replace('>', '›');
        }

        private static string Escape(char c)
        {
            return c == '<' ? "‹" : c == '>' ? "›" : c.ToString();
        }

        public static float EaseOutBack(float t)
        {
            const float c1 = 1.70158f;
            const float c3 = c1 + 1f;
            float p = t - 1f;
            return 1f + (c3 * p * p * p) + (c1 * p * p);
        }

        public static float EaseOutCubic(float t)
        {
            float p = 1f - t;
            return 1f - (p * p * p);
        }

        public static float EaseInCubic(float t)
        {
            return t * t * t;
        }

        public static float EaseInOutSine(float t)
        {
            return -(Mathf.Cos(Mathf.PI * t) - 1f) * 0.5f;
        }
    }
}
