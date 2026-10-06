// Gestos de un personaje del chat de Genies (de momento, Sage) con su ficha.
//
// Se crea con Sonia > Gestos de Genies > Crear set de Sage a partir de
// Assets/Animations/GeniesSage/manifest.json (lo escribe
// scripts/gestos_genies/descarga_ozz.py desde el behavior del personaje) y de
// los .ozz de esa carpeta. Cada gesto lleva la ficha que Genies le da a su LLM
// (llmMetadata: descripción física, intención, frecuencia y momento de uso,
// impacto, intensidad, tiempos del núcleo y del golpe). Unity la manda al
// orquestador en el mensaje gesture_catalog para que el director de gestos
// elija (docs/gestos.md); aquí solo se reproducen.

using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace Sonia
{
    /// <summary>Catálogo de gestos de un personaje de Genies, con su clip OZZ y su ficha.</summary>
    [CreateAssetMenu(fileName = "GestureSet", menuName = "Sonia/Gestos de Genies")]
    public sealed class GeniesGestureSet : ScriptableObject
    {
        /// <summary>Lista de Genies con los gestos de relleno casi neutros.</summary>
        public const string FillerList = "Utility_NoImpact";

        /// <summary>Un gesto con su clip y su ficha.</summary>
        [Serializable]
        public sealed class Gesture
        {
            [Tooltip("Nombre del gesto en Genies (displayName); es el que usan el director y el panel.")]
            public string name;

            [Tooltip("Clip OZZ del gesto.")]
            public GeniesOzzAsset clip;

            [Tooltip("Listas del behavior de Genies en las que está (Utility_NoImpact, Sage(IDset)...).")]
            public string[] lists = new string[0];

            [Tooltip("Duración del clip en segundos (la del OZZ).")]
            public float duration;

            [Tooltip("Inicio y fin del núcleo del gesto (llmMetadata.core_start_time/core_stop_time).")]
            public float coreStart;

            public float coreStop;

            [Tooltip("Instante del golpe (critical_beat_timestamp), o -1 si no tiene.")]
            public float criticalBeat = -1f;

            [Tooltip("Duración mínima que Genies le da (min_duration), o -1.")]
            public float minDuration = -1f;

            [Tooltip("Gesto que se sostiene (is_gesture_held).")]
            public bool held;

            [Tooltip("Gesto especial del behavior (isSpecialGesture).")]
            public bool special;

            [Tooltip("Standard, Uncommon o Rare.")]
            public string frequency = "Standard";

            [Tooltip("Instant, Short o Long.")]
            public string timing = "Short";

            [Tooltip("NoImpact, LowImpact o HighImpact (vacío si no lo trae).")]
            public string impact = "";

            [Tooltip("De 1 a 3.")]
            public int intensity = 1;

            [TextArea]
            [Tooltip("physical_description: qué hace el cuerpo.")]
            public string description = "";

            [Tooltip("Intenciones (llmMetadata.intent y etiquetas intent).")]
            public string[] intents = new string[0];

            [TextArea]
            [Tooltip("intent_description: cuándo usarlo y cuándo no (USE / DO NOT USE).")]
            public string intentDescription = "";

            [Tooltip("Etiquetas del behavior como tipo:valor (descriptor:Neutral, personality:Poised...).")]
            public string[] tags = new string[0];

            /// <summary>Cierto si es de relleno (lista Utility_NoImpact).</summary>
            public bool IsFiller
            {
                get { return Array.IndexOf(lists, FillerList) >= 0; }
            }
        }

        [Tooltip("Personaje de Genies del que salen los gestos.")]
        public string character = "Sage";

        [Tooltip("Fundido de entrada y salida de cada gesto (TransitionToClip_Duration del demeanor del personaje).")]
        public float transitionSeconds = 0.8f;

        [Tooltip("Gestos del personaje.")]
        public Gesture[] gestures = new Gesture[0];

        [NonSerialized]
        private Dictionary<string, Gesture> _byName;

        /// <summary>Gesto con ese nombre, o null.</summary>
        public Gesture Find(string gestureName)
        {
            if (string.IsNullOrEmpty(gestureName))
            {
                return null;
            }

            if (_byName == null || _byName.Count != gestures.Length)
            {
                _byName = new Dictionary<string, Gesture>(StringComparer.Ordinal);
                foreach (Gesture g in gestures)
                {
                    if (g != null && !string.IsNullOrEmpty(g.name) && g.clip != null)
                    {
                        _byName[g.name] = g;
                    }
                }
            }

            Gesture found;
            return _byName.TryGetValue(gestureName, out found) ? found : null;
        }

        private void OnValidate()
        {
            _byName = null;
        }

        // ------------------------------------------------------------------
        // Manifiesto (lo usa el editor al crear el set)
        // ------------------------------------------------------------------

        /// <summary>
        /// Lee las fichas del manifest.json de descarga_ozz.py. Devuelve los gestos
        /// (animType "gesture") sin clip ni duración, con la ruta del .ozz relativa
        /// a la carpeta del manifiesto en <paramref name="files"/>.
        /// </summary>
        public static List<Gesture> ParseManifest(string json, out string characterName, out float transition, out List<string> files)
        {
            JObject root = JObject.Parse(json);
            characterName = (string)root["character"] ?? "Genies";
            transition = 0.8f;
            JObject demeanor = root["demeanor"] as JObject;
            if (demeanor != null)
            {
                transition = ToFloat(demeanor["TransitionToClip_Duration"], transition);
            }

            List<Gesture> result = new List<Gesture>();
            files = new List<string>();
            JArray clips = root["clips"] as JArray;
            if (clips == null)
            {
                return result;
            }

            foreach (JToken item in clips)
            {
                if ((string)item["animType"] != "gesture")
                {
                    continue;
                }

                JObject llm = item["llm"] as JObject ?? new JObject();
                Gesture g = new Gesture
                {
                    name = (string)item["name"],
                    lists = ToStrings(item["lists"]),
                    coreStart = ToFloat(llm["core_start_time"], 0f),
                    coreStop = ToFloat(llm["core_stop_time"], 0f),
                    criticalBeat = ToFloat(llm["critical_beat_timestamp"], -1f),
                    minDuration = ToFloat(llm["min_duration"], -1f),
                    held = ToBool(llm["is_gesture_held"]),
                    special = ToBool(item["special"]),
                    frequency = (string)llm["usage_frequency"] ?? "Standard",
                    timing = (string)llm["usage_timing"] ?? "Short",
                    impact = (string)llm["impact"] ?? "",
                    intensity = Mathf.RoundToInt(ToFloat(llm["intensity"], 1f)),
                    description = ((string)llm["physical_description"] ?? "").Trim(),
                    intentDescription = ((string)llm["intent_description"] ?? "").Trim(),
                    tags = ToStrings(item["tags"])
                };
                g.intents = Intents(llm["intent"], g.tags);
                result.Add(g);
                files.Add((string)item["file"]);
            }

            return result;
        }

        private static string[] Intents(JToken intent, string[] tags)
        {
            List<string> found = new List<string>();
            string raw = intent != null && intent.Type != JTokenType.Null ? intent.ToString() : "";
            // Viene como "To Convey" o como lista de Python en texto: "['To Convey', 'To Agree']".
            foreach (string part in raw.Trim('[', ']').Split(','))
            {
                string clean = part.Trim().Trim('\'', '"').Trim();
                if (clean.Length > 0 && !found.Contains(clean))
                {
                    found.Add(clean);
                }
            }

            foreach (string tag in tags)
            {
                if (tag.StartsWith("intent:", StringComparison.Ordinal))
                {
                    string value = tag.Substring("intent:".Length);
                    if (!found.Contains(value))
                    {
                        found.Add(value);
                    }
                }
            }

            return found.ToArray();
        }

        private static string[] ToStrings(JToken token)
        {
            JArray array = token as JArray;
            if (array == null)
            {
                return new string[0];
            }

            List<string> items = new List<string>(array.Count);
            foreach (JToken t in array)
            {
                if (t.Type != JTokenType.Null)
                {
                    items.Add(t.ToString());
                }
            }

            return items.ToArray();
        }

        private static float ToFloat(JToken token, float fallback)
        {
            if (token == null || token.Type == JTokenType.Null)
            {
                return fallback;
            }

            if (token.Type == JTokenType.Float || token.Type == JTokenType.Integer)
            {
                return (float)token;
            }

            float value;
            return float.TryParse(token.ToString(), System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out value)
                ? value
                : fallback;
        }

        private static bool ToBool(JToken token)
        {
            if (token == null || token.Type == JTokenType.Null)
            {
                return false;
            }

            if (token.Type == JTokenType.Boolean)
            {
                return (bool)token;
            }

            return string.Equals(token.ToString(), "true", StringComparison.OrdinalIgnoreCase);
        }
    }
}
