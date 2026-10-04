// Marca un avatar de la escena como copia local de un avatar del SDK de Genies.
//
// El SDK solo compone el avatar en Play (sesión, descargas y montaje nativo): en
// modo edición no existe y al arrancar tarda unos segundos en aparecer. "Sonia >
// Actualizar copia del avatar del SDK" guarda ese avatar ya montado como un
// prefab normal (mallas con sus formas FACS, materiales, texturas, esqueleto con
// las medidas de la cara aplicadas, físicas del pelo y Avatar Humanoid), y este
// componente guarda la definición de la que salió. Mientras Sonia tenga que
// llevar esa misma definición, GeniesAvatarLoader no vuelve a cargar el avatar del
// SDK: sale al instante, igual en modo edición que en Play, y también sin red.

using UnityEngine;

namespace Sonia
{
    /// <summary>Copia local de un avatar del SDK de Genies y de qué definición salió.</summary>
    [DisallowMultipleComponent]
    public class GeniesAvatarSnapshot : MonoBehaviour
    {
        [SerializeField]
        [TextArea(2, 8)]
        [Tooltip("Definición JSON del SDK de la que salió la copia.")]
        private string definitionJson;

        [SerializeField]
        [Tooltip("Huella de la definición (HashDefinition). Solo informativa si está definitionJson.")]
        private string definitionHash;

        [SerializeField]
        [Tooltip("Nombre de la definición (TextAsset) de la que salió la copia.")]
        private string definitionName;

        [SerializeField]
        [Tooltip("Versión del Genies Avatar SDK que montó el avatar.")]
        private string sdkVersion;

        [SerializeField]
        [Tooltip("Calidad de las texturas (AvatarLods) con la que se cargó.")]
        private string quality;

        [SerializeField]
        [Tooltip("Cuándo se hizo la copia (UTC, ISO 8601).")]
        private string createdUtc;

        /// <summary>Definición JSON de la que salió la copia (vacía en copias antiguas).</summary>
        public string DefinitionJson
        {
            get { return definitionJson; }
        }

        /// <summary>Huella de la definición de la que salió la copia.</summary>
        public string DefinitionHash
        {
            get { return string.IsNullOrEmpty(definitionJson) ? definitionHash : HashDefinition(definitionJson); }
        }

        /// <summary>Nombre de la definición de la que salió la copia.</summary>
        public string DefinitionName
        {
            get { return definitionName; }
        }

        /// <summary>Versión del SDK que montó el avatar.</summary>
        public string SdkVersion
        {
            get { return sdkVersion; }
        }

        /// <summary>Cuándo se hizo la copia (UTC, ISO 8601).</summary>
        public string CreatedUtc
        {
            get { return createdUtc; }
        }

        /// <summary>Cierto si la copia salió de esta misma definición (sin contar espacios ni saltos de línea).</summary>
        public bool Matches(string json)
        {
            string hash = DefinitionHash;
            return !string.IsNullOrEmpty(hash) && hash == HashDefinition(json);
        }

        /// <summary>
        /// Huella de una definición JSON. No cuenta los espacios, tabuladores ni
        /// saltos de línea de fuera de las cadenas (ni la marca BOM), para que la
        /// misma definición dé la misma huella venga del editor de personaje, de la
        /// nube o del archivo del repo, con o sin sangría y en cualquier sistema.
        /// Es FNV-1a de 64 bits: solo sirve para saber si la definición cambió, no
        /// es criptográfica. Vacía si no hay definición.
        /// </summary>
        public static string HashDefinition(string json)
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

#if UNITY_EDITOR
        /// <summary>Anota de dónde sale la copia. Solo lo usa la herramienta del editor que la crea.</summary>
        public void Describe(string json, string definitionAssetName, string sdk, string lods)
        {
            definitionJson = json;
            definitionHash = HashDefinition(json);
            definitionName = definitionAssetName;
            sdkVersion = sdk;
            quality = lods;
            createdUtc = System.DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ");
        }
#endif
    }
}
