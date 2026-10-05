// En el editor de Unity, SoniaGeniesAvatar.json sigue al último avatar de Sonia.
//
// Cuando en Play Sonia se pone un avatar del SDK (el que mandó el orquestador
// con set_avatar tras guardarlo en el editor de personaje, o el último
// recordado), su definición se escribe en el archivo de definición de su
// cargador (SoniaGeniesAvatar.json): así el personaje de la app, el de
// set_avatar null y el de las builds, es siempre el último que llevó Sonia. Solo
// el de Sonia: el invitado del Modo Jean tiene su propio archivo y no se toca.
// En una build no se escribe nada.

#if UNITY_EDITOR

using System;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Reescribe la definición del personaje de la app con el avatar que lleva Sonia en Play.</summary>
    [InitializeOnLoad]
    public static class SoniaGeniesDefinitionSync
    {
        static SoniaGeniesDefinitionSync()
        {
            GeniesAvatarLoader.AvatarShown += OnAvatarShown;
        }

        private static void OnAvatarShown(GeniesAvatarLoader loader, string json)
        {
            if (!EditorApplication.isPlaying || loader == null || loader.Role != AvatarRole.Sonia || string.IsNullOrEmpty(json))
            {
                return;
            }

            string path = loader.Definition != null
                ? AssetDatabase.GetAssetPath(loader.Definition)
                : SoniaAvatarSetup.GeniesDefinitionPath;
            if (string.IsNullOrEmpty(path))
            {
                return;
            }

            TextAsset current = AssetDatabase.LoadAssetAtPath<TextAsset>(path);
            if (current != null && GeniesDefinition.Same(current.text, json))
            {
                return;
            }

            try
            {
                // Sangrado, para que los cambios se lean bien en git.
                File.WriteAllText(FullPath(path), IndentJson(json) + "\n", new UTF8Encoding(false));
            }
            catch (Exception exception)
            {
                Debug.LogWarning("[Sonia] No se pudo escribir " + path + ": " + exception.Message);
                return;
            }

            AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate | ImportAssetOptions.ForceSynchronousImport);
            Debug.Log("[Sonia] " + path + " ahora es el avatar que lleva Sonia (" + json.Length + " caracteres de definición).");
        }

        /// <summary>
        /// Sangra un JSON con dos espacios. Solo quita y pone espacios fuera de las
        /// cadenas, así que el valor no cambia (ni su huella).
        /// </summary>
        private static string IndentJson(string json)
        {
            StringBuilder builder = new StringBuilder(json.Length * 2);
            int depth = 0;
            bool inString = false;
            bool escaped = false;
            for (int i = 0; i < json.Length; i++)
            {
                char c = json[i];
                if (inString)
                {
                    builder.Append(c);
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

                    continue;
                }

                if (char.IsWhiteSpace(c) || c == '﻿')
                {
                    continue;
                }

                switch (c)
                {
                    case '"':
                        inString = true;
                        builder.Append(c);
                        break;
                    case '{':
                    case '[':
                        builder.Append(c);
                        int next = NextSignificant(json, i + 1);
                        if (next < json.Length && (json[next] == '}' || json[next] == ']'))
                        {
                            // Vacío: "{}" o "[]" en la misma línea.
                            builder.Append(json[next]);
                            i = next;
                            break;
                        }

                        depth++;
                        NewLine(builder, depth);
                        break;
                    case '}':
                    case ']':
                        depth = Math.Max(0, depth - 1);
                        NewLine(builder, depth);
                        builder.Append(c);
                        break;
                    case ',':
                        builder.Append(c);
                        NewLine(builder, depth);
                        break;
                    case ':':
                        builder.Append(": ");
                        break;
                    default:
                        builder.Append(c);
                        break;
                }
            }

            return builder.ToString();
        }

        private static int NextSignificant(string json, int start)
        {
            int i = start;
            while (i < json.Length && (char.IsWhiteSpace(json[i]) || json[i] == '﻿'))
            {
                i++;
            }

            return i;
        }

        private static void NewLine(StringBuilder builder, int depth)
        {
            builder.Append('\n');
            builder.Append(' ', depth * 2);
        }

        private static string FullPath(string assetPath)
        {
            return Path.Combine(Path.GetDirectoryName(Application.dataPath), assetPath);
        }
    }
}

#endif
