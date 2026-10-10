// Caché de Genies en una carpeta fija de cada equipo (docs/unity.md, «La caché
// de Genies»).
//
// NAF guarda las piezas de los avatares (unos 135 MB) en «cache», relativo al
// directorio de trabajo (NafAssetResolverConfig.cachePath). En la app de macOS
// ese directorio es la carpeta que contiene Sonnia.app, y en Windows, la del
// .exe. Así, cada versión descomprimida en otro sitio volvía a bajarlo todo y,
// si esa carpeta no se puede escribir, Genies no entrega el avatar y a los 60 s
// sale el doble. Pasó en el stand el 10 de octubre de 2026: macOS abría la app
// «traslocada». Las apps descargadas que se abren sin moverlas con el Finder se
// ejecutan desde una copia de solo lectura
// (/private/var/folders/.../AppTranslocation/...).
//
// Al arrancar la app (en el editor no), antes de que nada use Genies, el
// directorio de trabajo pasa a ser una carpeta propia que se puede escribir:
//   macOS    ~/Library/Application Support/Sonia/genies
//   Windows  %LOCALAPPDATA%\Sonia\genies (no la de Roaming: es una caché)
// La primera vez, si junto a la app había una caché (la de otra versión en la
// misma carpeta), se copia ahí para no bajarla otra vez. Si la carpeta no se
// puede crear, todo sigue como antes.

using System;
using System.IO;
using UnityEngine;

namespace Sonia
{
    /// <summary>Fija el directorio de trabajo de la app en una carpeta propia para la caché de NAF.</summary>
    public static class GeniesCacheFolder
    {
        /// <summary>Nombre de la caché de NAF (NafAssetResolverConfig.cachePath), relativo al directorio de trabajo.</summary>
        public const string CacheName = "cache";

        /// <summary>Carpeta fija que hace de directorio de trabajo (null en el editor o si no se pudo usar).</summary>
        public static string Folder { get; private set; }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void Install()
        {
            if (Application.isEditor || !string.IsNullOrEmpty(Folder))
            {
                return;
            }

            string dataPath = Application.dataPath ?? string.Empty;
            if (dataPath.IndexOf("/AppTranslocation/", StringComparison.Ordinal) >= 0)
            {
                Debug.LogWarning("[Sonia] macOS ejecuta la app traslocada, desde una copia de solo lectura (" + dataPath
                                 + "). Funciona, pero conviene moverla con el Finder a una carpeta normal.");
            }

            string folder;
            try
            {
                folder = FixedFolder();
                Directory.CreateDirectory(folder);
            }
            catch (Exception exception)
            {
                Debug.LogWarning("[Sonia] Caché de Genies sin carpeta fija (" + exception.Message
                                 + "): sigue junto a la app, en " + SafeCurrentDirectory() + ".");
                return;
            }

            string previous = SafeCurrentDirectory();
            string migrated = AdoptPreviousCache(previous, folder);
            try
            {
                Directory.SetCurrentDirectory(folder);
            }
            catch (Exception exception)
            {
                Debug.LogWarning("[Sonia] Caché de Genies sin carpeta fija (" + exception.Message
                                 + "): sigue junto a la app, en " + previous + ".");
                return;
            }

            Folder = folder;
            Debug.Log("[Sonia] Caché de Genies en " + Path.Combine(folder, CacheName)
                      + (migrated != null ? " (copiada de " + migrated + ")" : string.Empty) + ".");
        }

        private static string FixedFolder()
        {
#if UNITY_STANDALONE_WIN
            string root = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            return Path.Combine(root, "Sonia", "genies");
#else
            string home = Environment.GetFolderPath(Environment.SpecialFolder.Personal);
            return Path.Combine(home, "Library", "Application Support", "Sonia", "genies");
#endif
        }

        /// <summary>
        /// Copia en la carpeta fija la caché que había junto a la app, si la fija aún
        /// no tiene. Devuelve de dónde la copió, o null.
        /// </summary>
        private static string AdoptPreviousCache(string previous, string folder)
        {
            string target = Path.Combine(folder, CacheName);
            if (string.IsNullOrEmpty(previous) || Directory.Exists(target))
            {
                return null;
            }

            string source = Path.Combine(previous, CacheName);
            if (!Directory.Exists(source) || SamePath(source, target))
            {
                return null;
            }

            // Se copia aparte y se renombra al final: una copia a medias no cuenta como caché.
            string partial = target + ".copiando";
            try
            {
                if (Directory.Exists(partial))
                {
                    Directory.Delete(partial, true);
                }

                CopyFolder(source, partial);
                Directory.Move(partial, target);
                return source;
            }
            catch (Exception exception)
            {
                Debug.LogWarning("[Sonia] No se pudo copiar la caché de Genies de " + source + " (" + exception.Message
                                 + "): se bajará otra vez.");
                try
                {
                    if (Directory.Exists(partial))
                    {
                        Directory.Delete(partial, true);
                    }
                }
                catch (Exception)
                {
                    // Lo que quede a medias se borra en el próximo arranque.
                }

                return null;
            }
        }

        private static void CopyFolder(string from, string to)
        {
            Directory.CreateDirectory(to);
            foreach (string file in Directory.GetFiles(from))
            {
                File.Copy(file, Path.Combine(to, Path.GetFileName(file)), true);
            }

            foreach (string directory in Directory.GetDirectories(from))
            {
                CopyFolder(directory, Path.Combine(to, Path.GetFileName(directory)));
            }
        }

        private static bool SamePath(string a, string b)
        {
            try
            {
                return string.Equals(Path.GetFullPath(a).TrimEnd(Path.DirectorySeparatorChar),
                    Path.GetFullPath(b).TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase);
            }
            catch (Exception)
            {
                return false;
            }
        }

        private static string SafeCurrentDirectory()
        {
            try
            {
                return Directory.GetCurrentDirectory();
            }
            catch (Exception)
            {
                return null;
            }
        }
    }
}
