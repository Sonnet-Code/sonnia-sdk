// View the stage particle effects in the editor, without an orchestrator.
//
// Menu Sonnia > Particles: enters Play if needed and forces an effect
// (StageParticles.Preview), or a demo that alternates Matrix and trivia every
// few seconds until Play is exited. "Automatic" goes back to choosing based on
// what is happening. Meanwhile, Esc > Particles changes amount, speed, size
// and brightness; with that menu open it takes over, and when it closes the
// forced effect comes back.
//
// Also when opening the editor from the command line:
//
//   Unity -projectPath unity -executeMethod Sonia.EditorTools.SoniaParticlePreview.DemoFromCommandLine
//
// Nothing is saved: the forced effect is forgotten on leaving Play.

#if UNITY_EDITOR

using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine.SceneManagement;

namespace Sonia.EditorTools
{
    /// <summary>Forces the StageParticles effects in Play from the editor menu.</summary>
    [InitializeOnLoad]
    public static class SoniaParticlePreview
    {
        private const string ScenePath = "Assets/Scenes/SampleScene.unity";

        // The request survives the domain reload when entering Play.
        private const string RequestKey = "Sonia.ParticlePreview";
        private const string Demo = "demo";
        private const double DemoSeconds = 10.0;

        private static string s_mode;
        private static StageEffect? s_lastSet;
        private static double s_nextSwitch;
        private static bool s_demoOnMatrix;

        static SoniaParticlePreview()
        {
            string saved = SessionState.GetString(RequestKey, string.Empty);
            s_mode = saved.Length > 0 ? saved : null;
            EditorApplication.playModeStateChanged += OnPlayModeChanged;
            EditorApplication.update += Tick;
        }

        [MenuItem("Sonnia/Particles/Demo (Matrix and trivia)")]
        private static void DemoMenu()
        {
            Request(Demo);
        }

        [MenuItem("Sonnia/Particles/Show Matrix")]
        private static void MatrixMenu()
        {
            Request("matrix");
        }

        [MenuItem("Sonnia/Particles/Show Trivia")]
        private static void TriviaMenu()
        {
            Request("trivia");
        }

        [MenuItem("Sonnia/Particles/Show Ambient")]
        private static void AmbientMenu()
        {
            Request("ambient");
        }

        [MenuItem("Sonnia/Particles/Automatic (follows what is happening)")]
        private static void AutomaticMenu()
        {
            Request(null);
        }

        /// <summary>Command-line entry point: opens the main scene and starts the demo.</summary>
        public static void DemoFromCommandLine()
        {
            if (SceneManager.GetActiveScene().path != ScenePath)
            {
                EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            }

            // Once the editor has finished starting.
            EditorApplication.delayCall += () => Request(Demo);
        }

        private static void Request(string mode)
        {
            s_mode = mode;
            s_lastSet = null;
            s_nextSwitch = 0.0;
            s_demoOnMatrix = false;
            SessionState.SetString(RequestKey, mode ?? string.Empty);
            if (mode == null)
            {
                if (StageParticles.Instance != null)
                {
                    StageParticles.Instance.Preview = null;
                }

                return;
            }

            if (!EditorApplication.isPlaying && !EditorApplication.isPlayingOrWillChangePlaymode)
            {
                EditorApplication.EnterPlaymode();
            }
        }

        private static void OnPlayModeChanged(PlayModeStateChange change)
        {
            if (change == PlayModeStateChange.ExitingPlayMode)
            {
                s_mode = null;
                s_lastSet = null;
                SessionState.EraseString(RequestKey);
            }
        }

        private static void Tick()
        {
            StageParticles particles = StageParticles.Instance;
            if (s_mode == null || !EditorApplication.isPlaying || particles == null)
            {
                return;
            }

            // The Esc > Particles menu is showing another effect: it takes over until it closes.
            if (particles.Preview.HasValue && particles.Preview != s_lastSet)
            {
                return;
            }

            StageEffect wanted;
            if (s_mode == Demo)
            {
                if (EditorApplication.timeSinceStartup >= s_nextSwitch)
                {
                    s_demoOnMatrix = !s_demoOnMatrix;
                    s_nextSwitch = EditorApplication.timeSinceStartup + DemoSeconds;
                }

                wanted = s_demoOnMatrix ? StageEffect.Matrix : StageEffect.Trivia;
            }
            else
            {
                wanted = s_mode == "matrix" ? StageEffect.Matrix
                    : s_mode == "trivia" ? StageEffect.Trivia
                    : StageEffect.Ambient;
            }

            if (particles.Preview != wanted)
            {
                particles.Preview = wanted;
            }

            s_lastSet = wanted;
        }
    }
}

#endif
