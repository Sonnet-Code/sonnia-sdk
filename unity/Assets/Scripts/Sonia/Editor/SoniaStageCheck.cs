// Check of the screen layout in Play, without an orchestrator and at a fixed
// step.
//
// Walks through the moments of the design: idle with the invitation, the user
// asking, the assistant's answer growing with the voice (karaoke), a recorded
// phrase that arrives whole and the return to idle. It simulates the messages in
// StageScreen and the state in AvatarStateController (the camera moves to the
// conversation shot and back to the idle one), advances the game with
// EditorApplication.Step and saves 9:16 captures of the main camera with the
// HUD. If an orchestrator is connected, its messages can sneak in: better
// without it.
//
// Usage, with the main scene in Play and the avatar already in place: Sonnia >
// Check Screen (Play mode). The first time it only pauses (EditorApplication.Step
// does not advance in the same command that requests the pause); the second
// time it runs the check. Output in Temp/stagecheck/.

#if UNITY_EDITOR

using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Walks through the screen in Play and leaves captures and a report.</summary>
    public static class SoniaStageCheck
    {
        /// <summary>Output folder, relative to the project.</summary>
        public const string OutputFolder = "Temp/stagecheck";

        private const float StepSeconds = 0.02f;

        private const string Question = "What can you do?";
        private const string Answer =
            "I can chat, answer questions, look at what you show me and put images on the screen.";
        private const string Recorded = "Sure! Look: I can chat, show images and answer questions.";

        [MenuItem("Sonnia/Check Screen (Play mode)")]
        public static void CheckMenu()
        {
            Debug.Log(Run());
        }

        /// <summary>Runs the whole check. Returns the report.</summary>
        public static string Run()
        {
            if (!EditorApplication.isPlaying)
            {
                return "[Sonnia] Check Screen only works in Play mode.";
            }

            SoniaBootstrap sonia = Object.FindAnyObjectByType<SoniaBootstrap>();
            StageScreen screen = sonia != null ? sonia.GetComponent<StageScreen>() : null;
            if (screen == null || !screen.IsBuilt)
            {
                return "[Sonnia] The screen is not built yet: wait for it to start.";
            }

            AvatarStateController state = sonia.GetComponentInChildren<AvatarStateController>(true);
            CameraFramingController framing = sonia.GetComponentInChildren<CameraFramingController>(true);
            if (!EditorApplication.isPaused)
            {
                EditorApplication.isPaused = true;
                return "[Sonnia] Play paused. Run the check again (Step does not advance in the same command that pauses).";
            }

            Directory.CreateDirectory(OutputFolder);
            foreach (string old in Directory.GetFiles(OutputFolder, "*.png"))
            {
                File.Delete(old);
            }

            Session session = new Session(screen, state, framing);
            StringBuilder report = new StringBuilder();
            report.AppendLine("[Sonnia] Screen check. Captures in " + Path.GetFullPath(OutputFolder) + ".");

            // 1. Idle: nobody talks. Idle shot and invitation.
            screen.SimulateStageMode(true);
            session.Hold(AvatarState.Idle, "idle");
            report.Append(session.Run(9.5f));
            session.Capture("01_idle", report);

            // 2. The user asks.
            session.Hold(AvatarState.Listening, "listening");
            screen.SimulateTranscript("user", "What can", false);
            report.Append(session.Run(0.5f));
            screen.SimulateTranscript("user", Question, true);
            report.Append(session.Run(1.8f));
            session.Capture("02_listening", report);

            // 3. The assistant answers: the transcript arrives in pieces behind the voice.
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
                        session.Capture("03_speaking_midway", report);
                    }
                }
            }

            screen.SimulateTranscript("assistant", Answer, true);
            report.Append(session.Run(0.3f));
            session.Capture("04_speaking_end_of_phrase", report);
            screen.SimulateSpeechEnd(9001);

            // 4. Recorded phrase: arrives whole and lights up at the pace of the voice.
            screen.SimulateSpeechStart(9002, Recorded);
            screen.SimulateAudio(9002);
            report.Append(session.Run(1.6f));
            session.Capture("05_recorded_phrase_karaoke", report);
            report.Append(session.Run(3.6f));
            screen.SimulateSpeechEnd(9002);

            // 5. End of the conversation: subtitles go away and the invitation returns.
            session.Hold(AvatarState.Idle, "idle");
            report.Append(session.Run(4f));
            session.Capture("06_subtitles_lingering", report);
            report.Append(session.Run(10f));
            session.Capture("07_back_to_idle", report);

            string text = report.ToString();
            File.WriteAllText(Path.Combine(OutputFolder, "report.txt"), text);
            return text;
        }

        /// <summary>Keeps the test clock and holds the simulated state against whatever arrives.</summary>
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
                    report.AppendLine("- " + name + ": no main camera.");
                    return;
                }

                Texture2D image = SoniaCapture.Render(camera, SoniaCapture.Width, SoniaCapture.Height);
                if (image == null)
                {
                    report.AppendLine("- " + name + ": could not render.");
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

                string shot = _framing == null ? "?" : _framing.IsIdleShot ? "idle" : _framing.IsPanelShot ? "panel" : "conversation";
                report.AppendLine(
                    "- " + name + " (t=" + _time.ToString("F1", CultureInfo.InvariantCulture) + " s, state " + _heldName
                    + ", " + shot + " shot, camera " + camera.transform.position.ToString("F2") + ")");
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
