// Comprobación del Modo Jean en Play, sin orquestador y fotograma a fotograma.
//
// Lanza la secuencia en GuestPresenter (entra el invitado, se dan la mano, Sonia
// sale), le hace hablar con una voz de verdad (un WAV) y le hace despedirse.
// Avanza el juego a paso fijo con EditorApplication.Step y guarda capturas
// 9:16 de la cámara del stand y, durante el apretón de manos, otras dos: de
// detrás (las manos se ven sin el cuerpo delante) y de cerca. El audio no lo
// consume el hilo de audio sino esta herramienta (OnAudioFilterRead a mano,
// como el laboratorio de la cara), así que la boca va al mismo paso que los
// fotogramas.
//
// Uso, con la escena del stand en Play y los dos avatares ya puestos:
// Sonia > Comprobar Modo Jean (en Play). La primera vez solo pausa
// (EditorApplication.Step no avanza en el mismo comando que pide la pausa); la
// segunda hace la comprobación. La voz es Temp/guestcheck/voz.wav (PCM de 16
// bits) si existe; si no, el invitado no habla. Salida en Temp/guestcheck/.

#if UNITY_EDITOR

using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Recorre el Modo Jean en Play y deja capturas e informe.</summary>
    public static class SoniaGuestCheck
    {
        /// <summary>Carpeta de salida, relativa al proyecto.</summary>
        public const string OutputFolder = "Temp/guestcheck";

        /// <summary>Voz del invitado para la prueba.</summary>
        public const string VoicePath = OutputFolder + "/voz.wav";

        private const float StepSeconds = 0.02f;
        private const float CaptureEverySeconds = 0.25f;

        [MenuItem("Sonia/Comprobar Modo Jean (en Play)")]
        public static void CheckMenu()
        {
            Debug.Log(Run(VoicePath));
        }

        /// <summary>Hace la comprobación entera. Devuelve el informe.</summary>
        public static string Run(string voicePath)
        {
            if (!EditorApplication.isPlaying)
            {
                return "[Sonia] Comprobar Modo Jean solo funciona en Play.";
            }

            GuestPresenter presenter = Object.FindAnyObjectByType<GuestPresenter>();
            if (presenter == null)
            {
                return "[Sonia] No hay GuestPresenter en la escena: usa Sonia > Montar invitado (Modo Jean).";
            }

            // Los dos avatares llegan vivos del SDK unos segundos después de entrar en Play.
            MotionPlayer guestMotion = presenter.GetComponent<MotionPlayer>();
            SoniaBootstrap sonia = Object.FindAnyObjectByType<SoniaBootstrap>();
            MotionPlayer soniaMotion = sonia != null ? sonia.GetComponentInChildren<MotionPlayer>(true) : null;
            if (guestMotion == null || guestMotion.Animator == null || soniaMotion == null || soniaMotion.Animator == null)
            {
                return "[Sonia] Aún no han llegado los dos avatares del SDK: vuelve a probar en unos segundos.";
            }

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

            Session session = new Session(presenter);
            StringBuilder report = new StringBuilder();
            try
            {
                session.Begin();
                report.AppendLine("[Sonia] Comprobación del Modo Jean. Capturas en " + Path.GetFullPath(OutputFolder) + ".");

                // Entrada, mano y salida de Sonia.
                presenter.Enter(false);
                report.Append(session.RunUntil("entrada", () => presenter.StageName == "live", 45f));
                report.Append(session.HandshakeSummary());

                // Habla con la voz de prueba.
                float[] voice;
                int rate;
                if (ReadWav(voicePath, out voice, out rate))
                {
                    presenter.DebugPlayVoice(voice, rate, 1);
                    float seconds = (voice.Length / (float)rate) + 1.2f;
                    report.Append(session.RunFor("habla", seconds, 0.1f));
                }
                else
                {
                    report.AppendLine("Sin voz de prueba en " + voicePath + ": el invitado no habla.");
                    report.Append(session.RunFor("en directo", 2f, CaptureEverySeconds));
                }

                // Despedida y vuelta de Sonia.
                presenter.Leave(false);
                report.Append(session.RunUntil("salida", () => presenter.StageName == "off", 40f));
                report.Append(session.RunFor("de vuelta", 1.5f, 0.5f));
            }
            finally
            {
                session.End();
            }

            string text = report.ToString();
            File.WriteAllText(Path.Combine(OutputFolder, "informe.txt"), text);
            return text;
        }

        /// <summary>Lee un WAV PCM de 16 bits (mono o estéreo, que se mezcla a mono).</summary>
        private static bool ReadWav(string path, out float[] samples, out int rate)
        {
            samples = null;
            rate = 0;
            if (string.IsNullOrEmpty(path) || !File.Exists(path))
            {
                return false;
            }

            byte[] data = File.ReadAllBytes(path);
            if (data.Length < 44 || Encoding.ASCII.GetString(data, 0, 4) != "RIFF" || Encoding.ASCII.GetString(data, 8, 4) != "WAVE")
            {
                return false;
            }

            int channels = 1;
            int bits = 16;
            int pos = 12;
            while (pos + 8 <= data.Length)
            {
                string id = Encoding.ASCII.GetString(data, pos, 4);
                int size = System.BitConverter.ToInt32(data, pos + 4);
                int body = pos + 8;
                if (id == "fmt ")
                {
                    channels = System.BitConverter.ToInt16(data, body + 2);
                    rate = System.BitConverter.ToInt32(data, body + 4);
                    bits = System.BitConverter.ToInt16(data, body + 14);
                }
                else if (id == "data" && bits == 16 && channels > 0)
                {
                    int frames = Mathf.Min(size, data.Length - body) / (2 * channels);
                    samples = new float[frames];
                    for (int i = 0; i < frames; i++)
                    {
                        float sum = 0f;
                        for (int c = 0; c < channels; c++)
                        {
                            sum += System.BitConverter.ToInt16(data, body + (((i * channels) + c) * 2)) / 32768f;
                        }

                        samples[i] = sum / channels;
                    }

                    return rate > 0;
                }

                pos = body + size + (size & 1);
            }

            return false;
        }

        // ------------------------------------------------------------------
        // Sesión: pasos, audio a mano y capturas
        // ------------------------------------------------------------------

        private sealed class Session
        {
            private readonly GuestPresenter _presenter;
            private readonly AudioStreamPlayer _guestPlayer;
            private readonly HandshakeRig _handshake;
            private readonly MethodInfo _filterRead;
            private AudioSource _guestSource;
            private bool _guestSourceWasEnabled;
            private bool _guestSourceWasPlaying;
            private float[] _block = new float[0];
            private double _owed;
            private int _outputRate = 48000;
            private float _time;
            private int _shot;
            private Camera _side;
            private float _closestPalms = float.MaxValue;
            private float _closestWrists = float.MaxValue;
            private int _handshakeShots;

            public Session(GuestPresenter presenter)
            {
                _presenter = presenter;
                _guestPlayer = presenter.GetComponent<AudioStreamPlayer>();
                _handshake = presenter.GetComponent<HandshakeRig>();
                _filterRead = typeof(AudioStreamPlayer).GetMethod(
                    "OnAudioFilterRead", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
            }

            public void Begin()
            {
                // El audio del invitado lo consume esta herramienta, al paso de los fotogramas.
                _guestSource = _guestPlayer != null ? _guestPlayer.GetComponent<AudioSource>() : null;
                if (_guestSource != null)
                {
                    _guestSourceWasEnabled = _guestSource.enabled;
                    _guestSourceWasPlaying = _guestSource.isPlaying;
                    _guestSource.enabled = false;
                }

                _outputRate = _guestPlayer != null && _guestPlayer.OutputSampleRate > 0 ? _guestPlayer.OutputSampleRate : 48000;
                _block = new float[1024 * 2];
                foreach (SkinnedMeshRenderer smr in Object.FindObjectsByType<SkinnedMeshRenderer>(FindObjectsInactive.Exclude))
                {
                    // La malla tiene que seguir a los huesos en cada captura.
                    smr.forceMatrixRecalculationPerRender = true;
                }

                _side = new GameObject("SoniaGuestCheck.Lateral").AddComponent<Camera>();
                _side.fieldOfView = 30f;
                _side.enabled = false;
            }

            public void End()
            {
                if (_guestSource != null)
                {
                    // Apagar una fuente la para: hay que volver a ponerla a sonar.
                    _guestSource.enabled = _guestSourceWasEnabled;
                    if (_guestSourceWasPlaying && _guestSource.enabled)
                    {
                        _guestSource.Play();
                    }
                }

                if (_side != null)
                {
                    Object.DestroyImmediate(_side.gameObject);
                }
            }

            /// <summary>Avanza hasta que se cumpla la condición (o se acabe el tiempo).</summary>
            public string RunUntil(string label, System.Func<bool> done, float timeoutSeconds)
            {
                float start = _time;
                float nextShot = 0f;
                string lastStage = _presenter.StageName;
                StringBuilder lines = new StringBuilder();
                lines.AppendLine("- " + label + ": empieza en " + F(start) + " s (paso " + lastStage + ").");
                while (!done() && _time - start < timeoutSeconds)
                {
                    Step();
                    if (_presenter.StageName != lastStage)
                    {
                        lastStage = _presenter.StageName;
                        lines.AppendLine("  " + F(_time) + " s: paso " + lastStage + ".");
                    }

                    if (_time - start >= nextShot)
                    {
                        nextShot += CaptureEverySeconds;
                        Capture(label);
                    }

                    MeasureHandshake();
                }

                bool ok = done();
                lines.AppendLine("  " + (ok ? "terminó" : "NO terminó") + " en " + F(_time - start) + " s.");
                return lines.ToString();
            }

            /// <summary>Avanza un tiempo fijo con capturas cada tanto.</summary>
            public string RunFor(string label, float seconds, float every)
            {
                float start = _time;
                float nextShot = 0f;
                while (_time - start < seconds)
                {
                    Step();
                    if (_time - start >= nextShot)
                    {
                        nextShot += every;
                        Capture(label);
                    }
                }

                return "- " + label + ": " + F(seconds) + " s; hablando: " + (_presenter.GuestTalking ? "sí" : "no")
                       + " al final.\n";
            }

            public string HandshakeSummary()
            {
                if (_closestWrists == float.MaxValue)
                {
                    return "- apretón de manos: no se midió (¿faltan huesos o no estaba Sonia?).\n";
                }

                return "- apretón de manos: muñecas a " + F(_closestWrists * 100f) + " cm como mucho de cerca, centros de las palmas a "
                       + F(_closestPalms * 100f) + " cm (lo normal, unos 3 cm: las palmas juntas). Capturas de detrás y de cerca: "
                       + _handshakeShots + ".\n";
            }

            private void Step()
            {
                FeedAudio(_guestPlayer);
                EditorApplication.Step();
                _time += StepSeconds;
            }

            /// <summary>El audio que tocaría en este paso, sacado del reproductor a mano.</summary>
            private void FeedAudio(AudioStreamPlayer player)
            {
                if (player == null || _filterRead == null)
                {
                    return;
                }

                _owed += _outputRate * (double)StepSeconds;
                while (_owed >= _block.Length / 2)
                {
                    System.Array.Clear(_block, 0, _block.Length);
                    _filterRead.Invoke(player, new object[] { _block, 2 });
                    _owed -= _block.Length / 2;
                }
            }

            private void Capture(string label)
            {
                Camera camera = Camera.main;
                if (camera == null)
                {
                    return;
                }

                string name = (++_shot).ToString("D4", CultureInfo.InvariantCulture) + "_" + label.Replace(' ', '_');
                Save(SoniaCapture.Render(camera, SoniaCapture.Width, SoniaCapture.Height), name);
            }

            /// <summary>Con las manos juntas: distancias, y capturas de detrás y de cerca.</summary>
            private void MeasureHandshake()
            {
                if (_handshake == null || !_handshake.HandsJoined)
                {
                    return;
                }

                SoniaBootstrap sonia = Object.FindAnyObjectByType<SoniaBootstrap>();
                MotionPlayer soniaMotion = sonia != null ? sonia.GetComponentInChildren<MotionPlayer>(true) : null;
                MotionPlayer guestMotion = _presenter.GetComponent<MotionPlayer>();
                Animator a = soniaMotion != null ? soniaMotion.Animator : null;
                Animator b = guestMotion != null ? guestMotion.Animator : null;
                if (a == null || b == null || !a.isHuman || !b.isHuman)
                {
                    return;
                }

                Transform wristA = a.GetBoneTransform(HumanBodyBones.RightHand);
                Transform wristB = b.GetBoneTransform(HumanBodyBones.RightHand);
                Transform middleA = a.GetBoneTransform(HumanBodyBones.RightMiddleProximal);
                Transform middleB = b.GetBoneTransform(HumanBodyBones.RightMiddleProximal);
                if (wristA == null || wristB == null)
                {
                    return;
                }

                _closestWrists = Mathf.Min(_closestWrists, Vector3.Distance(wristA.position, wristB.position));
                if (middleA != null && middleB != null)
                {
                    Vector3 palmA = Vector3.Lerp(wristA.position, middleA.position, 0.5f);
                    Vector3 palmB = Vector3.Lerp(wristB.position, middleB.position, 0.5f);
                    _closestPalms = Mathf.Min(_closestPalms, Vector3.Distance(palmA, palmB));
                }

                // Dos vistas por cada medio segundo con las manos juntas.
                if (_handshakeShots >= 8 || Mathf.Repeat(_time, 0.5f) >= StepSeconds)
                {
                    return;
                }

                Vector3 meet = (wristA.position + wristB.position) * 0.5f;
                Camera stand = Camera.main;
                Vector3 toCamera = stand != null ? stand.transform.position - meet : Vector3.back;
                toCamera.y = 0f;
                toCamera = toCamera.sqrMagnitude > 0.0001f ? toCamera.normalized : Vector3.back;

                // De detrás: las manos sin los cuerpos delante.
                _side.transform.position = meet - (toCamera * 1.3f) + (Vector3.up * 0.25f);
                _side.transform.LookAt(meet);
                Save(SoniaCapture.Render(_side, SoniaCapture.Width, SoniaCapture.Height),
                     (++_shot).ToString("D4", CultureInfo.InvariantCulture) + "_mano_detras");

                // De cerca, desde el público.
                _side.transform.position = meet + (toCamera * 0.7f) + (Vector3.up * 0.1f);
                _side.transform.LookAt(meet);
                Save(SoniaCapture.Render(_side, SoniaCapture.Width, SoniaCapture.Height),
                     (++_shot).ToString("D4", CultureInfo.InvariantCulture) + "_mano_cerca");
                _handshakeShots += 2;
            }

            private static void Save(Texture2D image, string name)
            {
                if (image == null)
                {
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
            }

            private static string F(float value)
            {
                return value.ToString("F2", CultureInfo.InvariantCulture);
            }
        }
    }
}

#endif
