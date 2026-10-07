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

using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;
using UnityEngine.Rendering;

namespace Sonia.EditorTools
{
    public static class SoniaBuild
    {
        private const string ScenePath = "Assets/Scenes/SampleScene.unity";
        private const string BuildRoot = "Build";

        /// <summary>Identificador de la app (antes salía el de la plantilla de URP).</summary>
        public const string BundleId = "com.sonnetcode.sonia";

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
            Build(BuildTarget.StandaloneOSX, "macOS", "Sonnia.app");
        }

        /// <summary>
        /// Build de desarrollo de macOS con el registro interno de Genies (FORCE_LOGS)
        /// y trazas completas, para ver en el Player.log en qué se atasca el SDK.
        /// </summary>
        [MenuItem("Sonia/Build macOS (desarrollo, registro de Genies)")]
        public static void BuildMacDevelopment()
        {
            Build(BuildTarget.StandaloneOSX, "macOS-dev", "Sonnia.app", BuildOptions.Development, "FORCE_LOGS");
        }

        [MenuItem("Sonia/Build Windows")]
        public static void BuildWindows()
        {
            Build(BuildTarget.StandaloneWindows64, "Windows-x64", "Sonnia.exe");
        }

        /// <summary>
        /// Build de macOS para que el equipo pruebe a Sonnia en su casa: sin mandar la
        /// cámara ni el micrófono al panel (PANEL_CAMERA_STREAM=false en su build.env),
        /// así nadie del panel ve ni oye a quien la prueba. Sale en Build/macOS-pruebas.
        /// </summary>
        [MenuItem("Sonia/Build macOS (pruebas, sin cámara en el panel)")]
        public static void BuildMacTesters()
        {
            BuildForTesters(() => Build(BuildTarget.StandaloneOSX, "macOS-pruebas", "Sonnia.app"));
        }

        /// <summary>Como BuildMacTesters, para Windows (Build/Windows-pruebas-x64).</summary>
        [MenuItem("Sonia/Build Windows (pruebas, sin cámara en el panel)")]
        public static void BuildWindowsTesters()
        {
            BuildForTesters(() => Build(BuildTarget.StandaloneWindows64, "Windows-pruebas-x64", "Sonnia.exe"));
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
                BuildOptions.Development, "FORCE_LOGS"));
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

        private static void Build(BuildTarget target, string folder, string fileName,
                                  BuildOptions extraOptions = BuildOptions.None, params string[] defines)
        {
            SoniaSceneSetup.ConfigureVerticalBuild();
            PlayerSettings.SetApplicationIdentifier(NamedBuildTarget.Standalone, BundleId);
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

            BuildReport report;
            try
            {
                report = BuildPipeline.BuildPlayer(options);
            }
            finally
            {
                // Y a disco: la build guarda los ajustes con Mono y, si no, se quedaba así.
                PlayerSettings.SetScriptingBackend(NamedBuildTarget.Standalone, backend);
                AssetDatabase.SaveAssets();
                // Sin esto el editor puede no volver a abrir el proyecto (ver el método).
                SoniaPlayerBuildFixes.RestoreEditorNafPreload();
            }

            string summary = Summarize(report);
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

            if (Application.isBatchMode && (report.summary.result != BuildResult.Succeeded || wrongArchitecture))
            {
                EditorApplication.Exit(1);
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
