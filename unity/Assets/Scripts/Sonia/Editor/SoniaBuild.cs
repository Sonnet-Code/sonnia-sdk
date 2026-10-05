// Build standalone de la demo para macOS (y, cuando llegue el mini PC, Windows).
//
// Se lanza desde el menú Sonia > Build macOS o en batch mode, sin editor abierto:
//
//   Unity -batchmode -quit -projectPath unity \
//         -executeMethod Sonia.EditorTools.SoniaBuild.BuildMac -logFile build.log
//
// El resultado va a unity/Build/<plataforma>/Sonia.app, carpeta ignorada por git.
// SoniaPlayerBuildFixes la retoca (en macOS: NAF sin precarga y sin llavero; en
// las dos: el orquestador empaquetado con su .env). En macOS se compila con
// Mono: Genies pide IL2CPP, pero este Mac no tiene el módulo IL2CPP de macOS y
// con Mono funciona igual que en el editor. Windows sigue con IL2CPP.
// El resumen del BuildReport se escribe en unity/Build/<plataforma>/build-report.txt
// para poder leerlo sin rebuscar en el log de Unity.

using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;

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
            Build(BuildTarget.StandaloneOSX, "macOS", "Sonia.app");
        }

        /// <summary>
        /// Build de desarrollo de macOS con el registro interno de Genies (FORCE_LOGS)
        /// y trazas completas, para ver en el Player.log en qué se atasca el SDK.
        /// </summary>
        [MenuItem("Sonia/Build macOS (desarrollo, registro de Genies)")]
        public static void BuildMacDevelopment()
        {
            Build(BuildTarget.StandaloneOSX, "macOS-dev", "Sonia.app", BuildOptions.Development, "FORCE_LOGS");
        }

        [MenuItem("Sonia/Build Windows")]
        public static void BuildWindows()
        {
            Build(BuildTarget.StandaloneWindows64, "Windows", "Sonia.exe");
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

            // macOS con Mono solo durante esta build (ver la cabecera).
            ScriptingImplementation backend = PlayerSettings.GetScriptingBackend(NamedBuildTarget.Standalone);
            if (target == BuildTarget.StandaloneOSX)
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
                PlayerSettings.SetScriptingBackend(NamedBuildTarget.Standalone, backend);
            }

            string summary = Summarize(report);
            File.WriteAllText(Path.Combine(outputDir, "build-report.txt"), summary);
            Debug.Log("[Sonia] Build " + folder + ": " + report.summary.result + "\n" + summary);

            if (Application.isBatchMode && report.summary.result != BuildResult.Succeeded)
            {
                EditorApplication.Exit(1);
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
