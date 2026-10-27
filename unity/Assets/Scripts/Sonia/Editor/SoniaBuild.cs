// Build standalone de la demo para macOS (y, cuando llegue el mini PC, Windows).
//
// Se lanza desde el menú Sonia > Build macOS o en batch mode, sin editor abierto:
//
//   Unity -batchmode -quit -projectPath unity \
//         -executeMethod Sonia.EditorTools.SoniaBuild.BuildMac -logFile build.log
//
// El resultado va a unity/Build/<plataforma>/Sonnia.app, carpeta ignorada por git.
// SoniaPlayerBuildFixes la retoca (en macOS: NAF sin precarga y sin llavero; en
// las dos: el orquestador empaquetado con su .env). En macOS se compila con
// Mono: Genies pide IL2CPP, pero este Mac no tiene el módulo IL2CPP de macOS y
// con Mono funciona igual que en el editor. Windows va con IL2CPP si se compila
// en Windows y con Mono si se compila desde un Mac (IL2CPP de Windows solo se
// puede compilar en Windows); en las dos, con Vulkan como única API gráfica,
// porque las texturas de NAF (Genies) llegan en formatos de Vulkan.
// El resumen del BuildReport se escribe en unity/Build/<plataforma>/build-report.txt
// para poder leerlo sin rebuscar en el log de Unity.
//
// Cada build lleva versión (ResolveVersion: «1.0.<commits del repo>»): sale en el menú
// de Esc de la app (Application.version) y en el nombre del zip que se deja en
// unity/Build, p. ej. Sonnia-pruebas-macOS-1.0.179.zip. Los zips anteriores del mismo
// tipo se borran.

using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;
using UnityEngine.Rendering;
using Debug = UnityEngine.Debug;

namespace Sonia.EditorTools
{
    public static class SoniaBuild
    {
        private const string ScenePath = "Assets/Scenes/SampleScene.unity";
        private const string BuildRoot = "Build";

        /// <summary>Identificador de la app (antes salía el de la plantilla de URP).</summary>
        public const string BundleId = "com.sonnetcode.sonia";

        /// <summary>
        /// Primera parte de la versión de las builds; la última es el número de commits del
        /// repo (ResolveVersion). Se sube a mano para marcar un salto grande.
        /// </summary>
        public const string MajorMinor = "1.0";

        /// <summary>Variable de entorno que fuerza la versión (p. ej. en un equipo sin git).</summary>
        public const string VersionVariable = "SONIA_VERSION";

        /// <summary>
        /// Escenas de la build: la de Sonia primero (es la que arranca) y la del
        /// editor de personaje, que AvatarEditorLauncher carga por nombre encima.
        /// </summary>
        public static readonly string[] Scenes =
        {
            ScenePath,
            "Assets/Sonia/AvatarEditor/Scenes/" + AvatarEditorLauncher.DefaultSceneName + ".unity"
        };

        /// <summary>Deja las escenas de la build en Build Settings (también las usa Play en el editor).</summary>
        [MenuItem("Sonia/Escenas de la build")]
        public static void ConfigureScenes()
        {
            EditorBuildSettingsScene[] scenes = new EditorBuildSettingsScene[Scenes.Length];
            for (int i = 0; i < Scenes.Length; i++)
            {
                scenes[i] = new EditorBuildSettingsScene(Scenes[i], true);
            }

            EditorBuildSettings.scenes = scenes;
        }

        [MenuItem("Sonia/Build macOS")]
        public static void BuildMac()
        {
            Build(BuildTarget.StandaloneOSX, "macOS", "Sonnia.app", "Sonnia-macOS");
        }

        /// <summary>
        /// Build de desarrollo de macOS con el registro interno de Genies (FORCE_LOGS)
        /// y trazas completas, para ver en el Player.log en qué se atasca el SDK.
        /// </summary>
        [MenuItem("Sonia/Build macOS (desarrollo, registro de Genies)")]
        public static void BuildMacDevelopment()
        {
            Build(BuildTarget.StandaloneOSX, "macOS-dev", "Sonnia.app", "Sonnia-desarrollo-macOS",
                BuildOptions.Development, "FORCE_LOGS");
        }

        /// <summary>Nombre de la app de vídeo para redes (y de su ejecutable).</summary>
        public const string VideoProductName = "Sonnia Video";

        /// <summary>Identificador de la app de vídeo: distinto del de la del stand para que convivan.</summary>
        public const string VideoBundleId = "com.sonnetcode.sonnia.video";

        /// <summary>
        /// App de macOS para hacer vídeos de Sonnia para redes (docs/video.md): la misma escena
        /// con SONNIA_VIDEO_APP, que no conversa sino que renderiza los trabajos de sonnia-video,
        /// y con sonnia-video congelado dentro en lugar del orquestador. Sale en
        /// Build/macOS-video/Sonnia Video.app.
        /// </summary>
        [MenuItem("Sonia/Build macOS (vídeo para redes)")]
        public static void BuildMacVideo()
        {
            string savedName = PlayerSettings.productName;
            SoniaPlayerBuildFixes.VideoBuild = true;
            s_bundleId = VideoBundleId;
            try
            {
                PlayerSettings.productName = VideoProductName;
                Build(BuildTarget.StandaloneOSX, "macOS-video", VideoProductName + ".app", "Sonnia-Video-macOS",
                    BuildOptions.None, "SONNIA_VIDEO_APP");
            }
            finally
            {
                PlayerSettings.productName = savedName;
                SoniaPlayerBuildFixes.VideoBuild = false;
                s_bundleId = BundleId;
                PlayerSettings.SetApplicationIdentifier(NamedBuildTarget.Standalone, BundleId);
                // Build() guarda los ajustes con el nombre de la de vídeo: se vuelven a guardar.
                AssetDatabase.SaveAssets();
            }
        }

        private static string s_bundleId = BundleId;

        [MenuItem("Sonia/Build Windows")]
        public static void BuildWindows()
        {
            Build(BuildTarget.StandaloneWindows64, "Windows-x64", "Sonnia.exe", "Sonnia-Windows-x64");
        }

        /// <summary>
        /// Build de macOS para que el equipo pruebe a Sonnia en su casa: sin mandar la
        /// cámara ni el micrófono al panel (PANEL_CAMERA_STREAM=false en su build.env),
        /// así nadie del panel ve ni oye a quien la prueba. Sale en Build/macOS-pruebas.
        /// </summary>
        [MenuItem("Sonia/Build macOS (pruebas, sin cámara en el panel)")]
        public static void BuildMacTesters()
        {
            BuildForTesters(() => Build(BuildTarget.StandaloneOSX, "macOS-pruebas", "Sonnia.app", "Sonnia-pruebas-macOS"));
        }

        /// <summary>Como BuildMacTesters, para Windows (Build/Windows-pruebas-x64).</summary>
        [MenuItem("Sonia/Build Windows (pruebas, sin cámara en el panel)")]
        public static void BuildWindowsTesters()
        {
            BuildForTesters(() => Build(BuildTarget.StandaloneWindows64, "Windows-pruebas-x64", "Sonnia.exe",
                "Sonnia-pruebas-Windows-x64"));
        }

        /// <summary>
        /// Como la de prueba de Windows, pero de desarrollo y con el registro interno de
        /// Genies (FORCE_LOGS): para ver en el Player.log de un PC por qué el SDK no monta
        /// el avatar (7 de octubre de 2026: «NativeGenie» sin mallas en un portátil con AMD
        /// Ryzen). Sale en Build/Windows-dev-x64.
        /// </summary>
        [MenuItem("Sonia/Build Windows (diagnóstico, registro de Genies)")]
        public static void BuildWindowsDiagnostics()
        {
            BuildForTesters(() => Build(BuildTarget.StandaloneWindows64, "Windows-dev-x64", "Sonnia.exe",
                "Sonnia-diagnostico-Windows-x64", BuildOptions.Development, "FORCE_LOGS"));
        }

        private static void BuildForTesters(System.Action build)
        {
            SoniaPlayerBuildFixes.BuildEnv = SoniaPlayerBuildFixes.TesterBuildEnv;
            try
            {
                build();
            }
            finally
            {
                SoniaPlayerBuildFixes.BuildEnv = null;
            }
        }

        private static void Build(BuildTarget target, string folder, string fileName, string zipName,
                                  BuildOptions extraOptions = BuildOptions.None, params string[] defines)
        {
            string version = ResolveVersion();
            SoniaSceneSetup.ConfigureVerticalBuild();
            PlayerSettings.SetApplicationIdentifier(NamedBuildTarget.Standalone, s_bundleId);
            // macOS exige explicar para qué se usan la cámara y el micrófono; sin
            // el texto de la cámara el build falla porque WebcamFrameSender usa WebCamTexture.
            PlayerSettings.macOS.cameraUsageDescription =
                "Sonia mira por la cámara para saludar a quien se acerca al stand.";
            PlayerSettings.macOS.microphoneUsageDescription =
                "Sonia escucha por el micrófono para conversar.";
            ConfigureScenes();

            string outputDir = Path.Combine(BuildRoot, folder);
            Directory.CreateDirectory(outputDir);
            string output = Path.Combine(outputDir, fileName);

            BuildPlayerOptions options = new BuildPlayerOptions
            {
                scenes = Scenes,
                locationPathName = output,
                target = target,
                targetGroup = BuildPipeline.GetBuildTargetGroup(target),
                options = extraOptions,
                extraScriptingDefines = defines
            };

            if (target == BuildTarget.StandaloneWindows64)
            {
                PlayerSettings.SetUseDefaultGraphicsAPIs(target, false);
                PlayerSettings.SetGraphicsAPIs(target, new[] { GraphicsDeviceType.Vulkan });
                // Siempre x64: desde un Mac con Apple Silicon el ajuste estaba en ARM64 y esa
                // app no abre en los PC normales («This app can't run on your PC» en un AMD
                // Ryzen, 7 de octubre de 2026). Los Windows ARM la abren igual, emulando x64.
                EditorUserBuildSettings.SetPlatformSettings(
                    BuildPipeline.GetBuildTargetName(target), WindowsArchitectureSetting, "x64");
            }

            // Mono solo durante esta build (ver la cabecera).
            ScriptingImplementation backend = PlayerSettings.GetScriptingBackend(NamedBuildTarget.Standalone);
            bool mono = target == BuildTarget.StandaloneOSX;
#if !UNITY_EDITOR_WIN
            mono |= target == BuildTarget.StandaloneWindows64;
#endif
            if (mono)
            {
                PlayerSettings.SetScriptingBackend(NamedBuildTarget.Standalone, ScriptingImplementation.Mono2x);
            }

            // La versión solo durante la build, para no tocar ProjectSettings en cada una.
            string savedVersion = PlayerSettings.bundleVersion;
            PlayerSettings.bundleVersion = version;

            BuildReport report;
            try
            {
                report = BuildPipeline.BuildPlayer(options);
            }
            finally
            {
                PlayerSettings.bundleVersion = savedVersion;
                // Y a disco: la build guarda los ajustes con Mono y, si no, se quedaba así.
                PlayerSettings.SetScriptingBackend(NamedBuildTarget.Standalone, backend);
                AssetDatabase.SaveAssets();
                // Sin esto el editor puede no volver a abrir el proyecto (ver el método).
                SoniaPlayerBuildFixes.RestoreEditorNafPreload();
            }

            string summary = "Versión: " + version + "\n" + Summarize(report);
            bool wrongArchitecture = false;
            if (target == BuildTarget.StandaloneWindows64 && report.summary.result == BuildResult.Succeeded)
            {
                string machine = WindowsMachine(output);
                summary += "Arquitectura: " + machine + "\n";
                wrongArchitecture = machine != "x64";
                if (wrongArchitecture)
                {
                    Debug.LogError("[Sonia] La build de Windows salió para " + machine
                                   + ", no x64: no abriría en los PC normales.");
                }

                // Sin el runtime de Visual C++ al lado, Genies no monta el avatar en un PC que no
                // lo tenga instalado (SoniaPlayerBuildFixes.AddVisualCppRuntime).
                string[] runtime = { "msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll" };
                string missing = string.Join(", ", System.Array.FindAll(
                    runtime, dll => !File.Exists(Path.Combine(outputDir, dll))));
                summary += "Runtime de Visual C++: " + (missing.Length == 0 ? "sí" : "falta " + missing) + "\n";
                wrongArchitecture |= missing.Length > 0;
            }

            File.WriteAllText(Path.Combine(outputDir, "build-report.txt"), summary);
            Debug.Log("[Sonia] Build " + folder + ": " + report.summary.result + "\n" + summary);

            bool zipped = true;
            if (report.summary.result == BuildResult.Succeeded && !wrongArchitecture)
            {
                zipped = Zip(target, outputDir, fileName, zipName, version);
            }

            if (Application.isBatchMode && (report.summary.result != BuildResult.Succeeded || wrongArchitecture || !zipped))
            {
                EditorApplication.Exit(1);
            }
        }

        /// <summary>
        /// Versión de esta build: «MajorMinor.<commits del repo>», así que todas las builds de un
        /// mismo commit llevan la misma. SONIA_VERSION la fuerza; sin git, la última parte es 0.
        /// </summary>
        public static string ResolveVersion()
        {
            string forced = System.Environment.GetEnvironmentVariable(VersionVariable);
            if (!string.IsNullOrWhiteSpace(forced))
            {
                return forced.Trim();
            }

            string count = RunTool("git", new[] { "rev-list", "--count", "HEAD" }, RepoRoot, out string output) ? output.Trim() : string.Empty;
            if (!int.TryParse(count, out int commits))
            {
                Debug.LogWarning("[Sonia] No se pudo contar los commits con git: la build sale con la versión "
                                 + MajorMinor + ".0. Para fijarla, " + VersionVariable + ".");
                commits = 0;
            }

            return MajorMinor + "." + commits;
        }

        private static string RepoRoot => Path.GetFullPath(Path.Combine(Application.dataPath, "..", ".."));

        /// <summary>
        /// Deja la build en Build/&lt;zipName&gt;-&lt;versión&gt;.zip y borra los zips anteriores del
        /// mismo tipo. La app de macOS va con ditto (enlaces, permisos y firma tal cual); la de
        /// Windows, con tar (bsdtar, que viene en macOS y en Windows 10+), sin la carpeta
        /// _BackUpThisFolder_ButDontShipItWithYourGame.
        /// </summary>
        private static bool Zip(BuildTarget target, string outputDir, string fileName, string zipName, string version)
        {
            string root = Path.GetFullPath(BuildRoot);
            string zip = Path.Combine(root, zipName + "-" + version + ".zip");
            List<string> old = new List<string>(Directory.GetFiles(root, zipName + "-*.zip"));
            if (File.Exists(Path.Combine(root, zipName + ".zip")))
            {
                old.Add(Path.Combine(root, zipName + ".zip"));
            }

            foreach (string path in old)
            {
                File.Delete(path);
            }

            string folder = Path.GetFullPath(outputDir);
            bool ok;
            string output;
            if (target == BuildTarget.StandaloneOSX)
            {
                ok = RunTool("/usr/bin/ditto", new[] { "-c", "-k", "--keepParent", Path.Combine(folder, fileName), zip }, root, out output);
            }
            else
            {
                List<string> args = new List<string> { "-a", "-c", "-f", zip, "--exclude", ".DS_Store", "-C", folder };
                foreach (string entry in Directory.GetFileSystemEntries(folder))
                {
                    string name = Path.GetFileName(entry);
                    if (!name.EndsWith("_BackUpThisFolder_ButDontShipItWithYourGame") && name != ".DS_Store")
                    {
                        args.Add(name);
                    }
                }

                ok = RunTool("tar", args.ToArray(), root, out output);
            }

            if (!ok || !File.Exists(zip))
            {
                Debug.LogError("[Sonia] No se pudo crear " + zip + ": " + output);
                return false;
            }

            Debug.Log("[Sonia] Zip de la build: " + zip + " (" + (new FileInfo(zip).Length / (1024 * 1024)) + " MB)");
            return true;
        }

        /// <summary>Un argumento entre comillas si hace falta (ProcessStartInfo no tiene ArgumentList aquí).</summary>
        private static string Quote(string arg)
        {
            if (arg.Length > 0 && arg.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
            {
                return arg;
            }

            return "\"" + arg.Replace("\"", "\\\"") + "\"";
        }

        /// <summary>Lanza una herramienta y espera a que acabe. Cierto si sale con 0.</summary>
        private static bool RunTool(string tool, string[] args, string workingDirectory, out string output)
        {
            ProcessStartInfo info = new ProcessStartInfo(tool, string.Join(" ", System.Array.ConvertAll(args, Quote)))
            {
                WorkingDirectory = workingDirectory,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };
            // Sin los «._» de los atributos de macOS dentro del zip de Windows.
            info.EnvironmentVariables["COPYFILE_DISABLE"] = "1";
            try
            {
                using (Process process = Process.Start(info))
                {
                    System.Threading.Tasks.Task<string> stderr = process.StandardError.ReadToEndAsync();
                    output = process.StandardOutput.ReadToEnd();
                    process.WaitForExit();
                    output += stderr.Result;
                    return process.ExitCode == 0;
                }
            }
            catch (System.Exception ex)
            {
                output = ex.Message;
                return false;
            }
        }

        /// <summary>Ajuste de plataforma con la arquitectura de la build de Windows (x64 o ARM64).</summary>
        private const string WindowsArchitectureSetting = "Architecture";

        /// <summary>Para qué procesador es un .exe de Windows, leído de su cabecera PE.</summary>
        private static string WindowsMachine(string exe)
        {
            try
            {
                using (BinaryReader reader = new BinaryReader(File.OpenRead(exe)))
                {
                    reader.BaseStream.Seek(0x3C, SeekOrigin.Begin);
                    int header = reader.ReadInt32();
                    reader.BaseStream.Seek(header + 4, SeekOrigin.Begin);
                    ushort machine = reader.ReadUInt16();
                    switch (machine)
                    {
                        case 0x8664:
                            return "x64";
                        case 0xAA64:
                            return "ARM64";
                        case 0x014C:
                            return "x86";
                        default:
                            return "0x" + machine.ToString("X4");
                    }
                }
            }
            catch (IOException ex)
            {
                return "desconocida (" + ex.Message + ")";
            }
        }

        private static string Summarize(BuildReport report)
        {
            StringBuilder sb = new StringBuilder();
            sb.AppendLine("Resultado: " + report.summary.result);
            sb.AppendLine("Salida: " + report.summary.outputPath);
            sb.AppendLine("Tamaño: " + (report.summary.totalSize / (1024 * 1024)) + " MB");
            sb.AppendLine("Duración: " + report.summary.totalTime);
            sb.AppendLine("Errores: " + report.summary.totalErrors + ", avisos: " + report.summary.totalWarnings);
            foreach (BuildStep step in report.steps)
            {
                foreach (BuildStepMessage message in step.messages)
                {
                    if (message.type == LogType.Error || message.type == LogType.Exception)
                    {
                        sb.AppendLine("  [" + step.name + "] " + message.content);
                    }
                }
            }
            return sb.ToString();
        }
    }
}
