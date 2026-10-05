// Comprobación de la pantalla del stand (diseño F) en Play, sin orquestador y a
// paso fijo.
//
// Recorre los momentos del diseño: reposo con la invitación, el visitante
// preguntando, la respuesta de Sonia creciendo con la voz (karaoke), una frase
// grabada que llega entera y la vuelta al reposo. Simula los mensajes en
// StageScreen y el estado en AvatarStateController (la cámara pasa al plano de
// conversación y vuelve al de reposo), avanza el juego con EditorApplication.Step
// y guarda capturas 9:16 de la cámara del stand con el HUD. Si hay un orquestador
// conectado, sus mensajes pueden colarse: mejor sin él.
//
// Uso, con la escena del stand en Play y el avatar ya puesto: Sonia > Comprobar
// pantalla (en Play). La primera vez solo pausa (EditorApplication.Step no avanza
// en el mismo comando que pide la pausa); la segunda hace la comprobación. Salida
// en Temp/stagecheck/.

#if UNITY_EDITOR

using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Recorre la pantalla del stand en Play y deja capturas e informe.</summary>
    public static class SoniaStageCheck
    {
        /// <summary>Carpeta de salida, relativa al proyecto.</summary>
        public const string OutputFolder = "Temp/stagecheck";

        private const float StepSeconds = 0.02f;

        private const string Question = "¿Y qué hace Sonnet Code?";
        private const string Answer =
            "Aporta ingenieros senior a empresas de producto, integrados en su equipo en días, no en meses.";
        private const string Recorded = "¡Claro! Mira: tienen oficinas en Santo Domingo, Albuquerque y Madrid.";

        [MenuItem("Sonia/Comprobar pantalla (en Play)")]
        public static void CheckMenu()
        {
            Debug.Log(Run());
        }

        /// <summary>Hace la comprobación entera. Devuelve el informe.</summary>
        public static string Run()
        {
            if (!EditorApplication.isPlaying)
            {
                return "[Sonia] Comprobar pantalla solo funciona en Play.";
            }

            SoniaBootstrap sonia = Object.FindAnyObjectByType<SoniaBootstrap>();
            StageScreen screen = sonia != null ? sonia.GetComponent<StageScreen>() : null;
            if (screen == null || !screen.IsBuilt)
            {
                return "[Sonia] La pantalla del stand aún no está montada: espera a que arranque.";
            }

            AvatarStateController state = sonia.GetComponentInChildren<AvatarStateController>(true);
            CameraFramingController framing = sonia.GetComponentInChildren<CameraFramingController>(true);
            if (!EditorApplication.isPaused)
            {
                EditorApplication.isPaused = true;
                return "[Sonia] Play pausado. Vuelve a lanzar la comprobación (Step no avanza en el mismo comando que pausa).";
            }

            Directory.CreateDirectory(OutputFolder);
            foreach (string old in Directory.GetFiles(OutputFolder, "*.png"))
            {
                File.Delete(old);
            }

            Session session = new Session(screen, state, framing);
            StringBuilder report = new StringBuilder();
            report.AppendLine("[Sonia] Comprobación de la pantalla. Capturas en " + Path.GetFullPath(OutputFolder) + ".");

            // 1. Reposo: nadie habla. Plano de reposo e invitación.
            screen.SimulateStageMode(true);
            session.Hold(AvatarState.Idle, "idle");
            report.Append(session.Run(9.5f));
            session.Capture("01_reposo", report);

            // 2. El visitante pregunta.
            session.Hold(AvatarState.Listening, "listening");
            screen.SimulateTranscript("user", "¿Y qué hace", false);
            report.Append(session.Run(0.5f));
            screen.SimulateTranscript("user", Question, true);
            report.Append(session.Run(1.8f));
            session.Capture("02_escucha", report);

            // 3. Sonia contesta: la transcripción llega a trozos detrás de la voz.
            session.Hold(AvatarState.Speaking, "speaking");
            screen.SimulateSpeechStart(9001, string.Empty);
            string[] words = Answer.Split(' ');
            StringBuilder said = new StringBuilder();
            for (int i = 0; i < words.Length; i++)
            {
                if (said.Length > 0)
                {
                    said.Append(' ');
                }

                said.Append(words[i]);
                if (i % 3 == 2 || i == words.Length - 1)
                {
                    screen.SimulateAudio(9001);
                    screen.SimulateTranscript("assistant", said.ToString(), false);
                    report.Append(session.Run(0.45f));
                    if (i == 8)
                    {
                        session.Capture("03_habla_a_medias", report);
                    }
                }
            }

            screen.SimulateTranscript("assistant", Answer, true);
            report.Append(session.Run(0.3f));
            session.Capture("04_habla_fin_de_frase", report);
            screen.SimulateSpeechEnd(9001);

            // 4. Frase grabada: llega entera y se enciende al ritmo de la voz.
            screen.SimulateSpeechStart(9002, Recorded);
            screen.SimulateAudio(9002);
            report.Append(session.Run(1.6f));
            session.Capture("05_frase_grabada_karaoke", report);
            report.Append(session.Run(3.6f));
            screen.SimulateSpeechEnd(9002);

            // 5. Fin de la conversación: los subtítulos se van y vuelve la invitación.
            session.Hold(AvatarState.Idle, "idle");
            report.Append(session.Run(4f));
            session.Capture("06_subtitulos_quedandose", report);
            report.Append(session.Run(10f));
            session.Capture("07_vuelta_al_reposo", report);

            string text = report.ToString();
            File.WriteAllText(Path.Combine(OutputFolder, "informe.txt"), text);
            return text;
        }

        /// <summary>Lleva el reloj de la prueba y mantiene el estado simulado frente a lo que llegue.</summary>
        private sealed class Session
        {
            private readonly StageScreen _screen;
            private readonly AvatarStateController _state;
            private readonly CameraFramingController _framing;
            private AvatarState _held = AvatarState.Idle;
            private string _heldName = "idle";
            private float _time;

            public Session(StageScreen screen, AvatarStateController state, CameraFramingController framing)
            {
                _screen = screen;
                _state = state;
                _framing = framing;
            }

            public void Hold(AvatarState state, string name)
            {
                _held = state;
                _heldName = name;
                Apply();
            }

            public string Run(float seconds)
            {
                int steps = Mathf.Max(1, Mathf.RoundToInt(seconds / StepSeconds));
                for (int i = 0; i < steps; i++)
                {
                    Apply();
                    EditorApplication.Step();
                    _time += StepSeconds;
                }

                return string.Empty;
            }

            public void Capture(string name, StringBuilder report)
            {
                Camera camera = Camera.main;
                if (camera == null)
                {
                    report.AppendLine("- " + name + ": sin cámara principal.");
                    return;
                }

                Texture2D image = SoniaCapture.Render(camera, SoniaCapture.Width, SoniaCapture.Height);
                if (image == null)
                {
                    report.AppendLine("- " + name + ": no se pudo renderizar.");
                    return;
                }

                try
                {
                    File.WriteAllBytes(Path.Combine(OutputFolder, name + ".png"), image.EncodeToPNG());
                }
                finally
                {
                    Object.DestroyImmediate(image);
                }

                string shot = _framing == null ? "?" : _framing.IsIdleShot ? "reposo" : _framing.IsPanelShot ? "panel" : "conversación";
                report.AppendLine(
                    "- " + name + " (t=" + _time.ToString("F1", CultureInfo.InvariantCulture) + " s, estado " + _heldName
                    + ", plano de " + shot + ", cámara " + camera.transform.position.ToString("F2") + ")");
            }

            private void Apply()
            {
                if (_state != null && _state.State != _held)
                {
                    _state.SetState(_held);
                }

                _screen.SimulateState(_heldName);
            }
        }
    }
}

#endif
