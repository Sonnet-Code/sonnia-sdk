// Huella de una definición de avatar de Genies (el JSON del SDK).
//
// Sirve para saber si dos definiciones son el mismo personaje sin depender del
// formato: llegan sangradas desde el archivo del repo, compactas desde el editor
// de personaje o desde la nube, y con saltos de línea de Windows o de Mac.
// WithAsset saca otra definición con una pieza más (la gemela con gorra de
// GeniesHatHair).

using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Sonia
{
    /// <summary>Comparación de definiciones de avatar de Genies por su contenido.</summary>
    public static class GeniesDefinition
    {
        /// <summary>
        /// Huella de una definición JSON. No cuenta los espacios, tabuladores ni
        /// saltos de línea de fuera de las cadenas (ni la marca BOM). Es FNV-1a de
        /// 64 bits: solo sirve para saber si la definición cambió, no es
        /// criptográfica. Vacía si no hay definición.
        /// </summary>
        public static string Hash(string json)
        {
            if (string.IsNullOrEmpty(json))
            {
                return string.Empty;
            }

            const ulong Prime = 1099511628211UL;
            ulong hash = 14695981039346656037UL;
            bool inString = false;
            bool escaped = false;
            bool any = false;
            for (int i = 0; i < json.Length; i++)
            {
                char c = json[i];
                if (inString)
                {
                    if (escaped)
                    {
                        escaped = false;
                    }
                    else if (c == '\\')
                    {
                        escaped = true;
                    }
                    else if (c == '"')
                    {
                        inString = false;
                    }
                }
                else if (c == '"')
                {
                    inString = true;
                }
                else if (char.IsWhiteSpace(c) || c == '﻿')
                {
                    continue;
                }

                hash ^= (byte)(c & 0xFF);
                hash *= Prime;
                hash ^= (byte)(c >> 8);
                hash *= Prime;
                any = true;
            }

            return any ? hash.ToString("x16") : string.Empty;
        }

        /// <summary>Cierto si las dos son la misma definición (dos vacías no cuentan como iguales).</summary>
        public static bool Same(string a, string b)
        {
            string hash = Hash(a);
            return hash.Length > 0 && hash == Hash(b);
        }

        /// <summary>
        /// La misma definición (compacta) con una pieza más en equippedAssetIds, o
        /// tal cual si ya la lleva. Null si el JSON no es una definición.
        /// </summary>
        public static string WithAsset(string json, string assetId)
        {
            if (string.IsNullOrWhiteSpace(json) || string.IsNullOrEmpty(assetId))
            {
                return null;
            }

            try
            {
                JObject root = JObject.Parse(json);
                JArray equipped = root["equippedAssetIds"] as JArray;
                if (equipped == null)
                {
                    equipped = new JArray();
                    root["equippedAssetIds"] = equipped;
                }

                foreach (JToken token in equipped)
                {
                    if (token.Type == JTokenType.String && (string)token == assetId)
                    {
                        return root.ToString(Formatting.None);
                    }
                }

                equipped.Add(assetId);
                return root.ToString(Formatting.None);
            }
            catch (JsonException)
            {
                return null;
            }
        }
    }
}
