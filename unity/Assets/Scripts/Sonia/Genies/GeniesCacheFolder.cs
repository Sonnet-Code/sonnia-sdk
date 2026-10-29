// Genies cache in a fixed folder on each machine.
//
// NAF stores the avatar pieces (about 135 MB) in "cache", relative to the
// working directory (NafAssetResolverConfig.cachePath). In the macOS app that
// directory is the folder containing Sonnia.app, and on Windows, the one with
// the .exe. So every version unzipped somewhere else downloaded everything
// again and, if that folder is not writable, Genies does not deliver the avatar
// and the fallback avatar is used after 60 s. This happens on macOS with App
// Translocation: downloaded apps that are opened without moving them with the
// Finder run from a read-only copy
// (/private/var/folders/.../AppTranslocation/...).
//
// When the app starts (not in the editor), before anything uses Genies, the
// working directory becomes a folder of its own that is writable:
//   macOS    ~/Library/Application Support/Sonia/genies
//   Windows  %LOCALAPPDATA%\Sonia\genies (not Roaming: it is a cache)
// The first time, if there was a cache next to the app (from another version in
// the same folder), it is copied there to avoid downloading it again. If the
// folder cannot be created, everything works as before.

using System;
using System.IO;
using UnityEngine;

namespace Sonia
{
    /// <summary>Sets the app's working directory to a folder of its own for the NAF cache.</summary>
    public static class GeniesCacheFolder
    {
        /// <summary>Name of the NAF cache (NafAssetResolverConfig.cachePath), relative to the working directory.</summary>
        public const string CacheName = "cache";

        /// <summary>Fixed folder used as the working directory (null in the editor or if it could not be used).</summary>
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
                Debug.LogWarning("[Sonnia] macOS is running the app translocated, from a read-only copy (" + dataPath
                                 + "). It works, but it is better to move it with the Finder to a regular folder.");
            }

            string folder;
            try
            {
                folder = FixedFolder();
                Directory.CreateDirectory(folder);
            }
            catch (Exception exception)
            {
                Debug.LogWarning("[Sonnia] Genies cache without a fixed folder (" + exception.Message
                                 + "): it stays next to the app, in " + SafeCurrentDirectory() + ".");
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
                Debug.LogWarning("[Sonnia] Genies cache without a fixed folder (" + exception.Message
                                 + "): it stays next to the app, in " + previous + ".");
                return;
            }

            Folder = folder;
            Debug.Log("[Sonnia] Genies cache in " + Path.Combine(folder, CacheName)
                      + (migrated != null ? " (copied from " + migrated + ")" : string.Empty) + ".");
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
        /// Copies the cache that was next to the app into the fixed folder, if the
        /// fixed folder does not have one yet. Returns where it was copied from, or null.
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

            // Copy aside and rename at the end: a half copy does not count as a cache.
            string partial = target + ".copying";
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
                Debug.LogWarning("[Sonnia] Could not copy the Genies cache from " + source + " (" + exception.Message
                                 + "): it will be downloaded again.");
                try
                {
                    if (Directory.Exists(partial))
                    {
                        Directory.Delete(partial, true);
                    }
                }
                catch (Exception)
                {
                    // Anything left half-copied is deleted on the next launch.
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
