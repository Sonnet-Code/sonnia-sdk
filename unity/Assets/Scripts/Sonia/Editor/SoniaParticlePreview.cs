// Ver los efectos de partículas del escenario en el editor, sin orquestador.
//
// Menú Sonia > Partículas: entra en Play si hace falta y fuerza un efecto
// (StageParticles.Preview), o una demostración que alterna Matrix y la trivia
// cada pocos segundos hasta salir de Play. «Automático» vuelve a elegir según lo
// que pasa. Mientras tanto, Esc > Partículas cambia cantidad, velocidad, tamaño
// y brillo; con ese menú abierto manda él, y al cerrarlo vuelve lo forzado.
//
// También al abrir el editor desde la línea de comandos:
//
//   Unity -projectPath unity -executeMethod Sonia.EditorTools.SoniaParticlePreview.DemoFromCommandLine
//
// No se guarda nada: lo forzado se olvida al salir de Play.

#if UNITY_EDITOR

using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine.SceneManagement;

namespace Sonia.EditorTools
{
    /// <summary>Fuerza los efectos de StageParticles en Play desde el menú del editor.</summary>
    [InitializeOnLoad]
    public static class SoniaParticlePreview
    {
        private const string ScenePath = "Assets/Scenes/SampleScene.unity";

        // Lo pedido sobrevive a la recarga de dominio al entrar en Play.
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

        [MenuItem("Sonia/Partículas/Demostración (Matrix y trivia)")]
        private static void DemoMenu()
        {
            Request(Demo);
        }

        [MenuItem("Sonia/Partículas/Ver Matrix")]
        private static void MatrixMenu()
        {
            Request("matrix");
        }

        [MenuItem("Sonia/Partículas/Ver trivia")]
        private static void TriviaMenu()
        {
            Request("trivia");
        }

        [MenuItem("Sonia/Partículas/Ver ambiente")]
        private static void AmbientMenu()
        {
            Request("ambient");
        }

        [MenuItem("Sonia/Partículas/Automático (según lo que pasa)")]
        private static void AutomaticMenu()
        {
            Request(null);
        }

        /// <summary>Entrada por línea de comandos: abre la escena del stand y arranca la demostración.</summary>
        public static void DemoFromCommandLine()
        {
            if (SceneManager.GetActiveScene().path != ScenePath)
            {
                EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            }

            // Cuando el editor termine de arrancar.
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

            // El menú Esc > Partículas está enseñando otro efecto: manda él hasta que se cierre.
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
