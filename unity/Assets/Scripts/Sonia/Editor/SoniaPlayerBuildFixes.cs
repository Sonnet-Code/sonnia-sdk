// Post-proceso de las builds de Sonia (macOS y Windows), haga quien haga la build.
//
// macOS (Genies no la soporta oficialmente; ver docs/unity.md, "Build de macOS"):
//   1. Sin precarga de NAF (antes de la build). El preproceso de Genies
//      (XcodePostProcess) marca sus librerías NAF como «Load on Startup» en macOS.
//      Precargadas, el UnityPluginLoad de libgnUnityPlugin corre antes de que haya
//      dispositivo Metal y tumba la app («Failed to create Metal command queue»), y
//      además se cargan en el orden de esa lista y no en el de sus dependencias:
//      NAF devolvía vacías las piezas con malla (cuerpo, ropa, pelo) y Sonia no
//      salía. OnPreprocessBuild, que va después del de Genies, les quita la
//      precarga: se cargan al primer uso, como en el editor.
//   2. libGeniesAuthAPI y libGeniesTelemetryBridge buscan libCommonDeps en una ruta
//      absoluta del equipo de un desarrollador de Genies: se les añade la de la app.
//   3. Cero llavero: esas dos librerías guardan sus tokens en el llavero de macOS y,
//      con la firma ad hoc, macOS pedía la contraseña una y otra vez. Su dependencia
//      de Security.framework pasa a ser el puente del llavero
//      (unity/NativeSource/SoniaKeychainShim), que guarda en memoria. Jean: «debe
//      ser totalmente portable, 0 keychain».
//   4. Se vuelve a firmar la app (firma ad hoc) tras tocar sus binarios.
//
// macOS y Windows:
//   5. El orquestador congelado (scripts/build_orquestador.sh) entra en la app con el
//      .env del repo a su lado, copiado como archivo. Jean: «los envs deben
//      inyectarse en el build». Las builds están en .gitignore, así que la clave no
//      llega a git. Si falta el orquestador congelado, la app sale sin él (avisa) y
//      espera uno externo, como antes.
//   6. Todas las apps salen en el panel de Cloudflare (Jean: «necesito que todas
//      las builds la tengan»): sin PANEL_CLOUD_TOKEN en ese .env la build no
//      empieza. Solo se mira si la variable tiene valor; nunca se escribe el valor.
//   7. Lo que fija el tipo de build va en build.env, junto al .env, y manda sobre
//      él (sonia/paths.py). Las builds de prueba (SoniaBuild.BuildMacTesters y
//      BuildWindowsTesters) llevan PANEL_CAMERA_STREAM=false: el equipo prueba a
//      Sonnia en casa sin que el panel pueda ver ni oír su cámara y su micrófono.
//      Las del stand no llevan build.env.

using System;
using System.Diagnostics;
using System.IO;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using Debug = UnityEngine.Debug;

namespace Sonia.EditorTools
{
    public class SoniaPlayerBuildFixes : IPreprocessBuildWithReport, IPostprocessBuildWithReport
    {
        /// <summary>Variable del .env con la que cada Sonia entra en el panel de Cloudflare.</summary>
        private const string PanelTokenVariable = "PANEL_CLOUD_TOKEN";

        /// <summary>Carpeta de las librerías NAF de macOS dentro del SDK de Genies.</summary>
        private const string NafMacPlugins = "/NAF Plugin/Runtime/Plugins/macOS/";

        private const string KeychainShimName = "libSoniaKeychainShim.dylib";
        private const string SecurityFramework = "/System/Library/Frameworks/Security.framework/Versions/A/Security";

        /// <summary>Librerías de Genies que usan el llavero de macOS.</summary>
        private static readonly string[] KeychainUsers = { "libGeniesAuthAPI.dylib", "libGeniesTelemetryBridge.dylib" };

        /// <summary>Contenido del build.env de la build en curso; null: sin build.env (las del stand).</summary>
        public static string BuildEnv;

        /// <summary>build.env de las builds de prueba (ver la cabecera).</summary>
        public const string TesterBuildEnv =
            "# Build de prueba: la cámara y el micrófono no se mandan al panel de Cloudflare.\n"
            + "PANEL_CAMERA_STREAM=false\n"
            + "# Cuatro horas de conversación en total; después Sonnia se queda fuera con un letrero.\n"
            + "TRIAL_LIMIT_MINUTES=240\n";

        /// <summary>Después de los de Genies (el suyo, XcodePostProcess, es el 0).</summary>
        public int callbackOrder => 1000;

        private static string UnityRoot => Path.GetFullPath(Path.Combine(UnityEngine.Application.dataPath, ".."));

        private static string RepoRoot => Path.GetFullPath(Path.Combine(UnityRoot, ".."));

        /// <summary>Puente del llavero compilado (unity/NativeSource/SoniaKeychainShim/build.sh).</summary>
        private static string KeychainShimPath => Path.Combine(UnityRoot, "NativeSource", "SoniaKeychainShim", KeychainShimName);

        /// <summary>Orquestador congelado de una plataforma (scripts/build_orquestador.sh).</summary>
        private static string FrozenOrchestrator(string platform) =>
            Path.Combine(UnityRoot, "Build", "orquestador", platform, "sonia-orquestador");

        public void OnPreprocessBuild(BuildReport report)
        {
            BuildTarget platform = report.summary.platform;
            if (platform == BuildTarget.StandaloneOSX || platform == BuildTarget.StandaloneWindows64)
            {
                RequirePanelToken();
            }

            if (platform == BuildTarget.StandaloneOSX)
            {
                WithoutNafPreload();
            }
        }

        /// <summary>Sin PANEL_CLOUD_TOKEN en el .env del repo, la build no empieza (ver la cabecera).</summary>
        private static void RequirePanelToken()
        {
            string env = Path.Combine(RepoRoot, ".env");
            if (File.Exists(env) && HasValue(env, PanelTokenVariable))
            {
                return;
            }

            throw new BuildFailedException("Falta " + PanelTokenVariable + " en " + env
                                           + ": todas las apps tienen que salir en el panel de Cloudflare."
                                           + " Ponlo (es el AGENT_TOKEN del Worker sonia-panel, ver docs/panel.md)"
                                           + " y vuelve a lanzar la build.");
        }

        /// <summary>
        /// Si un .env da valor a <paramref name="name"/>, leyéndolo como python-dotenv:
        /// manda la última línea, vale «export », las comillas encierran el valor y,
        /// sin comillas, lo que va tras « #» es comentario.
        /// </summary>
        private static bool HasValue(string envFile, string name)
        {
            string value = null;
            foreach (string raw in File.ReadAllLines(envFile))
            {
                string line = raw.Trim();
                if (line.StartsWith("export ", StringComparison.Ordinal))
                {
                    line = line.Substring("export ".Length).TrimStart();
                }

                int equals = line.IndexOf('=');
                if (line.StartsWith("#", StringComparison.Ordinal) || equals <= 0
                    || line.Substring(0, equals).Trim() != name)
                {
                    continue;
                }

                string rest = line.Substring(equals + 1).Trim();
                if (rest.Length > 0 && (rest[0] == '"' || rest[0] == '\''))
                {
                    int close = rest.IndexOf(rest[0], 1);
                    value = close > 0 ? rest.Substring(1, close - 1) : rest.Substring(1);
                }
                else
                {
                    Match comment = Regex.Match(rest, @"(^|\s)#");
                    value = (comment.Success ? rest.Substring(0, comment.Index) : rest).Trim();
                }
            }

            return !string.IsNullOrWhiteSpace(value);
        }

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
                    AddVisualCppRuntime(Path.GetDirectoryName(output), data);
                    break;
            }
        }

        /// <summary>
        /// El runtime de Visual C++ (msvcp140, vcruntime140, concrt140...) junto a Sonnia.exe y
        /// a los plugins de 64 bits: lo necesitan las DLL nativas de Genies y Windows no lo trae
        /// de serie (7 de octubre de 2026: sin él, Genies no montaba el avatar y salía el doble).
        /// Sale del orquestador congelado en Windows (scripts/build_orquestador.sh, vcredist/).
        /// </summary>
        private static void AddVisualCppRuntime(string root, string data)
        {
            string source = Path.Combine(FrozenOrchestrator("Windows"), "vcredist");
            string[] dlls = Directory.Exists(source) ? Directory.GetFiles(source, "*.dll") : new string[0];
            if (dlls.Length == 0)
            {
                Debug.LogError("[Sonia] Build de Windows sin el runtime de Visual C++ (falta " + source
                               + "): en un PC sin él Genies no monta el avatar. Hay que volver a congelar "
                               + "el orquestador de Windows (scripts/build_orquestador.sh en Windows o el workflow).");
                return;
            }

            string plugins = Path.Combine(data, "Plugins", "x86_64");
            var names = new System.Collections.Generic.List<string>();
            foreach (string dll in dlls)
            {
                string name = Path.GetFileName(dll);
                File.Copy(dll, Path.Combine(root, name), true);
                if (Directory.Exists(plugins))
                {
                    File.Copy(dll, Path.Combine(plugins, name), true);
                }

                names.Add(name);
            }

            Debug.Log("[Sonia] Runtime de Visual C++ en la build de Windows: " + string.Join(", ", names));
        }

        // ------------------------------------------------------------------
        // macOS
        // ------------------------------------------------------------------

        /// <summary>
        /// Quita la precarga («Load on Startup») que el preproceso de Genies pone a
        /// sus librerías NAF en macOS (ver la cabecera). Genies la devuelve a su valor
        /// del editor, sin precarga, al acabar la build.
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

            Debug.Log("[Sonia] Build de macOS: " + changed + " librería(s) NAF sin precarga; se cargan al primer uso, como en el editor.");
        }

        /// <summary>
        /// Deja las librerías NAF de macOS sin precarga en disco. Se llama al acabar
        /// cada build, salga bien o mal (SoniaBuild). El 6 de octubre los .meta
        /// quedaron con «isPreloaded: 1» tras una build buena aunque los
        /// importadores decían que no, y así el editor carga NAF al arrancar,
        /// antes de tener Metal, y se cae al abrir el proyecto («Failed to create
        /// Metal command queue»). Por eso se mira también el texto del .meta.
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
                Debug.Log("[Sonia] Librerías NAF de macOS otra vez sin precarga en el editor (" + fixedCount + " cambio(s)).");
            }
        }

        private static void FixMac(string app)
        {
            string plugins = Path.Combine(app, "Contents", "PlugIns");

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

            int unlocked = WithoutKeychain(plugins);

            AddOrchestrator("macOS", Path.Combine(app, "Contents", "Resources", "orquestador"));

            // Firma ad hoc de todo de nuevo: install_name_tool invalida las firmas.
            Run("codesign", "--force --deep --sign - \"" + app + "\"");
            Debug.Log("[Sonia] Build de macOS arreglada: " + unlocked
                      + " librería(s) de Genies sin llavero, rutas de Genies y firma ad hoc.");
        }

        /// <summary>
        /// Las librerías de Genies que usan el llavero pasan a usar el puente (en
        /// memoria): se copia a su lado y su dependencia de Security.framework
        /// apunta a él. Devuelve cuántas se cambiaron.
        /// </summary>
        private static int WithoutKeychain(string plugins)
        {
            if (!File.Exists(KeychainShimPath))
            {
                throw new BuildFailedException("Falta el puente del llavero (" + KeychainShimPath
                                               + "): ejecuta unity/NativeSource/SoniaKeychainShim/build.sh.");
            }

            int changed = 0;
            foreach (string name in KeychainUsers)
            {
                foreach (string lib in Directory.GetFiles(plugins, name, SearchOption.AllDirectories))
                {
                    File.Copy(KeychainShimPath, Path.Combine(Path.GetDirectoryName(lib), KeychainShimName), true);
                    Run("install_name_tool", "-change " + SecurityFramework + " @loader_path/" + KeychainShimName
                                             + " \"" + lib + "\"");
                    changed++;
                }
            }

            if (changed == 0)
            {
                Debug.LogWarning("[Sonia] No se encontraron las librerías de Genies que usan el llavero: revisa si cambiaron de nombre.");
            }

            return changed;
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

            WarnIfStale(frozen, platform);
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

            // Frases grabadas y modelos y huellas de caras de este equipo si el orquestador
            // congelado no los trae (el del runner de GitHub para Windows no los tiene:
            // cache/ no está en git). Sin las huellas, la app no reconocería a quien se dio
            // de alta con fotos locales, como las personas conocidas (docs/caras.md).
            string[][] seeded = { new[] { "voice" }, new[] { "faces", "modelos" }, new[] { "faces", "huellas" } };
            foreach (string[] part in seeded)
            {
                string source = Path.Combine(RepoRoot, "cache", Path.Combine(part));
                string bundled = Path.Combine(target, "_internal", "cache", Path.Combine(part));
                if (Directory.Exists(source) && !Directory.Exists(bundled))
                {
                    CopyDirectory(source, bundled);
                    Debug.Log("[Sonia] cache/" + string.Join("/", part) + " de este equipo añadido al orquestador ("
                              + platform + ").");
                }
            }

            string buildEnv = Path.Combine(target, "build.env");
            if (BuildEnv != null)
            {
                File.WriteAllText(buildEnv, BuildEnv);
                Debug.Log("[Sonia] build.env de la build (" + platform + "): " + BuildEnv.Replace("\n", " | "));
            }
            else if (File.Exists(buildEnv))
            {
                File.Delete(buildEnv);
            }

            string env = Path.Combine(RepoRoot, ".env");
            if (File.Exists(env))
            {
                // Se copia como archivo; su contenido no se escribe en ningún registro.
                File.Copy(env, Path.Combine(target, ".env"), true);
                Debug.Log("[Sonia] Orquestador empaquetado con el .env del repo (" + platform + ").");
            }
            else
            {
                Debug.LogWarning("[Sonia] Orquestador empaquetado sin .env: no hay " + env + ". Sin claves no conversa.");
            }
        }

        /// <summary>
        /// Avisa si el orquestador congelado es más viejo que el último cambio de
        /// server/sonia o assets/: la app llevaría un orquestador desfasado. Se
        /// arregla volviendo a ejecutar scripts/build_orquestador.sh.
        /// </summary>
        private static void WarnIfStale(string frozen, string platform)
        {
            DateTime builtAt = Directory.GetLastWriteTimeUtc(frozen);
            DateTime newest = DateTime.MinValue;
            string newestFile = null;
            foreach (string folder in new[] { Path.Combine(RepoRoot, "server", "sonia"), Path.Combine(RepoRoot, "assets") })
            {
                if (!Directory.Exists(folder))
                {
                    continue;
                }

                foreach (string file in Directory.GetFiles(folder, "*", SearchOption.AllDirectories))
                {
                    if (file.Contains("__pycache__"))
                    {
                        continue;
                    }

                    DateTime changed = File.GetLastWriteTimeUtc(file);
                    if (changed > newest)
                    {
                        newest = changed;
                        newestFile = file;
                    }
                }
            }

            if (newest > builtAt)
            {
                Debug.LogWarning("[Sonia] El orquestador congelado de " + platform + " es anterior a "
                                 + Path.GetFileName(newestFile) + ": vuelve a ejecutar scripts/build_orquestador.sh"
                                 + " para que la app lleve el código y los assets de ahora.");
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
