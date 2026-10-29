// Post-processing of macOS player builds that include the Genies Avatar SDK.
//
// Only compiled when the SDK is installed (SONNIA_GENIES). Genies does not
// officially support macOS players; two things break without these fixes:
//   1. NAF preload (before the build). Genies' own preprocess marks its NAF
//      libraries as "Load on Startup" on macOS. Preloaded, the UnityPluginLoad of
//      libgnUnityPlugin runs before there is a Metal device and crashes the app
//      ("Failed to create Metal command queue"), and the libraries load in list
//      order instead of dependency order, so NAF returned empty meshes. Our
//      OnPreprocessBuild, which runs after Genies', clears the preload: they load
//      on first use, as in the editor. After the build the editor importers are
//      restored to "no preload" as well.
//   2. libGeniesAuthAPI and libGeniesTelemetryBridge look for libCommonDeps at an
//      absolute path of a Genies developer machine: an rpath inside the app is
//      added, and the app is signed ad hoc again because install_name_tool
//      invalidates signatures.
//
// Windows players with Genies need the Visual C++ runtime installed on the
// target machine (msvcp140, vcruntime140...): without it the SDK does not
// mount the avatar and the fallback avatar shows instead.

#if SONNIA_GENIES

using System;
using System.Diagnostics;
using System.IO;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using Debug = UnityEngine.Debug;

namespace Sonia.EditorTools
{
    public class SoniaPlayerBuildFixes : IPreprocessBuildWithReport, IPostprocessBuildWithReport
    {
        /// <summary>Folder of the macOS NAF libraries inside the Genies SDK.</summary>
        private const string NafMacPlugins = "/NAF Plugin/Runtime/Plugins/macOS/";

        /// <summary>After Genies' own callbacks (theirs, XcodePostProcess, is 0).</summary>
        public int callbackOrder => 1000;

        public void OnPreprocessBuild(BuildReport report)
        {
            if (report.summary.platform == BuildTarget.StandaloneOSX)
            {
                WithoutNafPreload();
            }
        }

        public void OnPostprocessBuild(BuildReport report)
        {
            if (report.summary.platform != BuildTarget.StandaloneOSX)
            {
                return;
            }

            RestoreEditorNafPreload();
            if (report.summary.result != BuildResult.Failed && report.summary.result != BuildResult.Cancelled)
            {
                FixMac(report.summary.outputPath);
            }
        }

        /// <summary>
        /// Clears the preload ("Load on Startup") that Genies' preprocess sets on its
        /// macOS NAF libraries (see the header).
        /// </summary>
        private static void WithoutNafPreload()
        {
            int changed = 0;
            foreach (PluginImporter importer in PluginImporter.GetAllImporters())
            {
                if (!importer.isPreloaded || !importer.assetPath.Replace('\\', '/').Contains(NafMacPlugins))
                {
                    continue;
                }

                importer.isPreloaded = false;
                importer.SaveAndReimport();
                changed++;
            }

            Debug.Log("[Sonnia] macOS build: " + changed + " NAF library(ies) without preload; they load on first use, as in the editor.");
        }

        /// <summary>
        /// Leaves the macOS NAF libraries without preload on disk. A preloaded NAF
        /// makes the editor load it at startup, before there is Metal, and crash
        /// when opening the project ("Failed to create Metal command queue"). The
        /// .meta text is checked too: importers have reported "no preload" while
        /// the file still said "isPreloaded: 1".
        /// </summary>
        public static void RestoreEditorNafPreload()
        {
            int fixedCount = 0;
            foreach (PluginImporter importer in PluginImporter.GetAllImporters())
            {
                string path = importer.assetPath.Replace('\\', '/');
                if (!path.Contains(NafMacPlugins))
                {
                    continue;
                }

                if (importer.isPreloaded)
                {
                    importer.isPreloaded = false;
                    importer.SaveAndReimport();
                    fixedCount++;
                }

                string meta = Path.GetFullPath(path) + ".meta";
                if (File.Exists(meta))
                {
                    string text = File.ReadAllText(meta);
                    if (text.Contains("isPreloaded: 1"))
                    {
                        File.WriteAllText(meta, text.Replace("isPreloaded: 1", "isPreloaded: 0"));
                        AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate);
                        fixedCount++;
                    }
                }
            }

            if (fixedCount > 0)
            {
                Debug.Log("[Sonnia] macOS NAF libraries back to no preload in the editor (" + fixedCount + " change(s)).");
            }
        }

        private static void FixMac(string app)
        {
            string plugins = Path.Combine(app, "Contents", "PlugIns");
            if (!Directory.Exists(plugins))
            {
                return;
            }

            // Let the Genies libraries find libCommonDeps inside the app.
            string[] commonDeps = Directory.GetFiles(plugins, "libCommonDeps.dylib", SearchOption.AllDirectories);
            if (commonDeps.Length > 0)
            {
                string depsFolder = Path.GetDirectoryName(commonDeps[0]);
                foreach (string name in new[] { "libGeniesAuthAPI.dylib", "libGeniesTelemetryBridge.dylib" })
                {
                    foreach (string lib in Directory.GetFiles(plugins, name, SearchOption.AllDirectories))
                    {
                        string rpath = "@loader_path" + RelativeSuffix(Path.GetDirectoryName(lib), depsFolder);
                        Run("install_name_tool", "-add_rpath " + rpath + " \"" + lib + "\"", allowFailure: true);
                    }
                }
            }

            // Ad hoc signature again: install_name_tool invalidates signatures.
            Run("codesign", "--force --deep --sign - \"" + app + "\"");
            Debug.Log("[Sonnia] macOS build fixed: Genies library paths and ad hoc signature.");
        }

        /// <summary>"/.." or "/sub" to go from one PlugIns folder to another (one level only, which is what Genies uses).</summary>
        private static string RelativeSuffix(string from, string to)
        {
            if (string.Equals(Path.GetFullPath(from), Path.GetFullPath(to), StringComparison.Ordinal))
            {
                return string.Empty;
            }

            string parent = Path.GetDirectoryName(Path.GetFullPath(from));
            if (string.Equals(parent, Path.GetFullPath(to), StringComparison.Ordinal))
            {
                return "/..";
            }

            return "/../" + Path.GetFileName(to);
        }

        private static void Run(string tool, string arguments, bool allowFailure = false)
        {
            ProcessStartInfo info = new ProcessStartInfo(tool, arguments)
            {
                UseShellExecute = false,
                RedirectStandardError = true,
                RedirectStandardOutput = true,
                CreateNoWindow = true
            };
            using (Process process = Process.Start(info))
            {
                string error = process.StandardError.ReadToEnd();
                process.StandardOutput.ReadToEnd();
                process.WaitForExit();
                if (process.ExitCode != 0 && !allowFailure)
                {
                    throw new BuildFailedException(tool + " " + arguments + " failed (" + process.ExitCode + "): " + error);
                }
            }
        }
    }
}

#endif
