// Post-proceso de las builds de Sonia (macOS y Windows), haga quien haga la build.
//
// macOS (Genies no la soporta oficialmente; ver docs/unity.md, "Build de macOS"):
//   1. NAF: Unity precarga libgnUnityPlugin antes de crear el dispositivo Metal y su
//      UnityPluginLoad tumba la app ("Failed to create Metal command queue"). Se
//      renombra a libgnUnityPluginReal.dylib y en su lugar va el puente
//      (unity/NativeSource/SoniaNafShim), que reexporta sus símbolos y lo
//      inicializa cuando ya hay MTLDevice.
//   2. libGeniesAuthAPI y libGeniesTelemetryBridge buscan libCommonDeps en una ruta
//      absoluta del equipo de un desarrollador de Genies: se les añade la de la app.
//   3. Se vuelve a firmar la app (firma ad hoc) tras tocar sus binarios.
//
// macOS y Windows:
//   4. El orquestador congelado (scripts/build_orquestador.sh) entra en la app con el
//      .env del repo a su lado, copiado como archivo (nunca se lee). Jean: «los envs
//      deben inyectarse en el build». Las builds están en .gitignore, así que la
//      clave no llega a git. Si falta el orquestador congelado, la app sale sin él
//      (avisa) y espera uno externo, como antes.

using System;
using System.Diagnostics;
using System.IO;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using Debug = UnityEngine.Debug;

namespace Sonia.EditorTools
{
    public class SoniaPlayerBuildFixes : IPostprocessBuildWithReport
    {
        private const string RealNafName = "libgnUnityPluginReal.dylib";
        private const string NafName = "libgnUnityPlugin.dylib";

        public int callbackOrder => 1000;

        private static string UnityRoot => Path.GetFullPath(Path.Combine(UnityEngine.Application.dataPath, ".."));

        private static string RepoRoot => Path.GetFullPath(Path.Combine(UnityRoot, ".."));

        /// <summary>Puente de NAF compilado (unity/NativeSource/SoniaNafShim/build.sh).</summary>
        private static string ShimPath => Path.Combine(UnityRoot, "NativeSource", "SoniaNafShim", "libSoniaNafShim.dylib");

        /// <summary>Orquestador congelado de una plataforma (scripts/build_orquestador.sh).</summary>
        private static string FrozenOrchestrator(string platform) =>
            Path.Combine(UnityRoot, "Build", "orquestador", platform, "sonia-orquestador");

        public void OnPostprocessBuild(BuildReport report)
        {
            if (report.summary.result == BuildResult.Failed || report.summary.result == BuildResult.Cancelled)
            {
                return;
            }

            string output = report.summary.outputPath;
            switch (report.summary.platform)
            {
                case BuildTarget.StandaloneOSX:
                    FixMac(output);
                    break;
                case BuildTarget.StandaloneWindows64:
                    string data = Path.Combine(Path.GetDirectoryName(output), Path.GetFileNameWithoutExtension(output) + "_Data");
                    AddOrchestrator("Windows", Path.Combine(data, "orquestador"));
                    break;
            }
        }

        // ------------------------------------------------------------------
        // macOS
        // ------------------------------------------------------------------

        private static void FixMac(string app)
        {
            string plugins = Path.Combine(app, "Contents", "PlugIns");
            if (!File.Exists(ShimPath))
            {
                throw new BuildFailedException("Falta el puente de NAF (" + ShimPath + "): ejecuta unity/NativeSource/SoniaNafShim/build.sh.");
            }

            int bridged = 0;
            foreach (string naf in Directory.GetFiles(plugins, NafName, SearchOption.AllDirectories))
            {
                string folder = Path.GetDirectoryName(naf);
                string real = Path.Combine(folder, RealNafName);
                if (File.Exists(real))
                {
                    File.Delete(real);
                }

                File.Move(naf, real);
                Run("install_name_tool", "-id @rpath/" + RealNafName + " \"" + real + "\"");
                File.Copy(ShimPath, naf);
                bridged++;
            }

            if (bridged == 0)
            {
                throw new BuildFailedException("No se encontró " + NafName + " en la build: el puente de NAF no se pudo poner.");
            }

            // Que las librerías de Genies encuentren libCommonDeps dentro de la app.
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

            AddOrchestrator("macOS", Path.Combine(app, "Contents", "Resources", "orquestador"));

            // Firma ad hoc de todo de nuevo: install_name_tool invalida las firmas.
            Run("codesign", "--force --deep --sign - \"" + app + "\"");
            Debug.Log("[Sonia] Build de macOS arreglada: puente de NAF en " + bridged + " sitio(s), rutas de Genies y firma ad hoc.");
        }

        /// <summary>"/.." o "/sub" para ir de una carpeta de PlugIns a otra (solo un nivel, lo que usa Genies).</summary>
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

        // ------------------------------------------------------------------
        // Orquestador empaquetado
        // ------------------------------------------------------------------

        private static void AddOrchestrator(string platform, string destination)
        {
            string frozen = FrozenOrchestrator(platform);
            if (!Directory.Exists(frozen))
            {
                Debug.LogWarning("[Sonia] Build sin orquestador empaquetado: falta " + frozen
                                 + " (scripts/build_orquestador.sh en " + platform + "). La app esperará uno externo.");
                return;
            }

            string target = Path.Combine(destination, "sonia-orquestador");
            if (Directory.Exists(target))
            {
                Directory.Delete(target, true);
            }

            Directory.CreateDirectory(destination);
#if UNITY_EDITOR_OSX
            // ditto conserva los enlaces simbólicos y los permisos de PyInstaller.
            Run("ditto", "\"" + frozen + "\" \"" + target + "\"");
#else
            CopyDirectory(frozen, target);
#endif

            string env = Path.Combine(RepoRoot, ".env");
            if (File.Exists(env))
            {
                // Se copia como archivo: nunca se lee ni se escribe en ningún registro.
                File.Copy(env, Path.Combine(target, ".env"), true);
                Debug.Log("[Sonia] Orquestador empaquetado con el .env del repo (" + platform + ").");
            }
            else
            {
                Debug.LogWarning("[Sonia] Orquestador empaquetado sin .env: no hay " + env + ". Sin claves no conversa.");
            }
        }

        private static void CopyDirectory(string from, string to)
        {
            Directory.CreateDirectory(to);
            foreach (string file in Directory.GetFiles(from))
            {
                File.Copy(file, Path.Combine(to, Path.GetFileName(file)), true);
            }

            foreach (string folder in Directory.GetDirectories(from))
            {
                CopyDirectory(folder, Path.Combine(to, Path.GetFileName(folder)));
            }
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
                    throw new BuildFailedException(tool + " " + arguments + " falló (" + process.ExitCode + "): " + error);
                }
            }
        }
    }
}
