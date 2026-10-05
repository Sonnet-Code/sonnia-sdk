// Laboratorio de cara: conduce a Sonia por un guion fijo y guarda cada fotograma.
//
// Solo existe en el editor. Lo monta Editor/SoniaFaceLab.cs (menú o línea de
// comandos) sobre la escena del stand, con el cliente WebSocket desconectado:
// el guion hace de orquestador llamando a los mismos manejadores de
// SoniaBootstrap que el protocolo (estado, speech_start, chunks de audio,
// speech_end), así que se prueba el camino real entero: reproductor, línea de
// retardo, análisis de fonemas, lip-sync, expresiones, ojos y gestos.
//
// El tiempo va a paso fijo (Time.captureDeltaTime) y el audio no lo consume el
// hilo de audio sino el propio guion, que llama a OnAudioFilterRead con los
// bloques que tocan en cada fotograma. Así cada ejecución da exactamente los
// mismos fotogramas, se puede renderizar más despacio que el tiempo real y el
// audio que "sonó" se guarda en un WAV alineado con las imágenes.
//
// Cada fotograma se renderiza al principio del siguiente, antes de que ningún
// script toque nada: huesos, blendshapes y malla ya están en el estado final
// del fotograma anterior (renderizar en LateUpdate daría la malla una pose por
// detrás).

#if UNITY_EDITOR

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using UnityEngine;

namespace Sonia
{
    /// <summary>Guion de prueba de la cara con captura fotograma a fotograma. Solo editor.</summary>
    [DefaultExecutionOrder(-32000)]
    public class SoniaFaceLabDriver : MonoBehaviour
    {
        /// <summary>Un paso del guion.</summary>
        [Serializable]
        public class Step
        {
            /// <summary>
            /// "state", "speak", "attention", "wait", "freeze" (apaga los controladores
            /// de la cara), "shape" (pesos fijos: "nombre:peso,...") o "avatar" (espera
            /// en tiempo real, sin grabar, a que el SDK de Genies entregue su avatar;
            /// <see cref="seconds"/> es el tope).
            /// </summary>
            public string kind = "wait";

            /// <summary>Estado (idle, listening, thinking, speaking) o categoría de atención.</summary>
            public string value = string.Empty;

            /// <summary>WAV para "speak" (PCM 16 bit mono).</summary>
            public string wav = string.Empty;

            /// <summary>Texto de la frase (solo para el registro y los subtítulos).</summary>
            public string text = string.Empty;

            /// <summary>Segundos que dura el paso (para "speak", lo que se espera después de que termine el audio).</summary>
            public float seconds = 1f;

            /// <summary>Frase ambiental (animación de stand): mueve la boca sin cambiar de estado.</summary>
            public bool ambient;
        }

        [Header("Salida")]
        public string outputDir = "Temp/facelab";
        public int fps = 60;

        [Tooltip("Guardar uno de cada N fotogramas.")]
        public int captureEvery = 1;

        public Vector2Int standSize = new Vector2Int(540, 960);
        public int closeupSize = 640;

        [Tooltip("Campo de visión del primer plano, en grados. Se mira desde la cámara del stand, así que el enfoque y la perspectiva son los mismos.")]
        public float closeupFov = 9f;

        public bool captureStand = true;
        public bool captureCloseup = true;

        [Header("Guion")]
        public List<Step> steps = new List<Step>();

        [Tooltip("Retraso entre speech_start y el primer chunk de audio, como el de la voz real.")]
        public float audioLatency = 0.35f;

        [Tooltip("Duración de cada chunk de audio enviado.")]
        public float chunkSeconds = 0.1f;

        [Tooltip("Ventaja con la que llega el audio respecto a lo que suena (GPT-Live manda trozos de 100 ms a ritmo real).")]
        public float audioLead = 0.1f;

        [Tooltip("Tamaño del bloque que pide el motor de audio (DSP buffer).")]
        public int dspBlock = 1024;

        [Tooltip("Pausa entre el fin del audio y el estado idle (lo que tarda el orquestador).")]
        public float idleAfterPlayback = 0.3f;

        [Tooltip("Cerrar el editor al terminar (línea de comandos).")]
        public bool exitWhenDone = true;

        [Header("Referencias (las rellena el montaje)")]
        public Camera standCamera;
        public Camera closeupCamera;

        private SoniaBootstrap _bootstrap;
        private AudioStreamPlayer _player;
        private LipSyncController _lipSync;
        private PhonemeLipSyncBridge _bridge;
        private AvatarStateController _state;
        private AvatarChoreographer _choreographer;
        private FaceRig _faceRig;
        private AvatarBinder _binder;
        private bool _waitingAvatar;
        private float _avatarWaitStart;
        private SkinnedMeshRenderer _face;
        private readonly List<KeyValuePair<int, float>> _posed = new List<KeyValuePair<int, float>>();
        private Transform _head;
        private Transform _leftEye;
        private Transform _rightEye;

        private MethodInfo _handleState;
        private MethodInfo _handleSpeechStart;
        private MethodInfo _handleAudioFrame;
        private MethodInfo _handleSpeechEnd;
        private MethodInfo _handleAttention;
        private MethodInfo _filterRead;

        private int _frame;
        private int _stepIndex = -1;
        private float _stepStart;
        private bool _stepWaitingPlayback;
        private float _playbackDoneAt = -1f;
        private int _utterance;
        private bool _done;

        // Audio de la frase en curso.
        private float[] _speech;
        private int _speechRate = 24000;
        private int _speechSent;
        private float _speechStart;
        private bool _speechEnded;

        private double _owedSamples;
        private float[] _block = new float[0];
        private readonly List<float> _heard = new List<float>();
        private int _outputRate;

        private Texture2D _standTexture;
        private Texture2D _closeupTexture;
        private RenderTexture _standTarget;
        private RenderTexture _closeupTarget;
        private StreamWriter _log;
        private readonly StringBuilder _line = new StringBuilder();
        private string _currentLabel = string.Empty;

        private void Start()
        {
            Time.captureDeltaTime = 1f / Mathf.Max(1, fps);
            // Todo el de Sonia: con el invitado del Modo Jean en la escena hay dos de cada.
            _bootstrap = FindAnyObjectByType<SoniaBootstrap>();
            _player = SoniaComponent<AudioStreamPlayer>();
            _lipSync = SoniaComponent<LipSyncController>();
            _bridge = SoniaComponent<PhonemeLipSyncBridge>();
            _state = SoniaComponent<AvatarStateController>();
            _choreographer = SoniaComponent<AvatarChoreographer>();
            _faceRig = _lipSync != null && _lipSync.FaceRig != null ? _lipSync.FaceRig : SoniaComponent<FaceRig>();
            _face = _faceRig != null ? _faceRig.PrimaryRenderer : null;

            Type bootstrapType = typeof(SoniaBootstrap);
            const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;
            _handleState = bootstrapType.GetMethod("HandleState", flags);
            _handleSpeechStart = bootstrapType.GetMethod("HandleSpeechStart", flags);
            _handleAudioFrame = bootstrapType.GetMethod("HandleAudioFrame", flags);
            _handleSpeechEnd = bootstrapType.GetMethod("HandleSpeechEnd", flags);
            _handleAttention = bootstrapType.GetMethod("HandleAttention", flags);
            _filterRead = typeof(AudioStreamPlayer).GetMethod("OnAudioFilterRead", flags);

            // El motor de audio no consume nada: el guion llama al filtro a mano.
            AudioSource source = _player != null ? _player.GetComponent<AudioSource>() : null;
            if (source != null)
            {
                source.Stop();
                source.enabled = false;
            }

            _outputRate = _player != null && _player.OutputSampleRate > 0 ? _player.OutputSampleRate : 48000;
            _block = new float[Mathf.Max(64, dspBlock) * 2];

            BindAvatar();
            _binder = SoniaComponent<AvatarBinder>();
            if (_binder != null)
            {
                _binder.AvatarChanged += OnAvatarChanged;
            }

            if (_face != null)
            {
                // La captura se hace al principio del fotograma siguiente; aun así
                // se fuerza el recálculo para que la malla siga a los huesos.
                foreach (SkinnedMeshRenderer smr in FindObjectsByType<SkinnedMeshRenderer>(FindObjectsInactive.Exclude))
                {
                    smr.forceMatrixRecalculationPerRender = true;
                }
            }

            Directory.CreateDirectory(outputDir);
            Directory.CreateDirectory(Path.Combine(outputDir, "stand"));
            Directory.CreateDirectory(Path.Combine(outputDir, "closeup"));
            _log = new StreamWriter(Path.Combine(outputDir, "frames.tsv"), false, new UTF8Encoding(false));
            _log.WriteLine("frame\ttime\tlabel\tstate\tclip\tphoneme\tvol\trawVol\tmouthOpen\theadPitch\theadYaw\teyeL\teyeR\tshapes");

            Debug.Log("[FaceLab] listo: " + steps.Count + " pasos, " + fps + " fps, salida " + Path.GetFullPath(outputDir)
                      + ", cara " + (_face != null ? _face.name + " (" + _face.sharedMesh.blendShapeCount + " blendshapes)" : "ninguna")
                      + ", tasa de salida " + _outputRate + " Hz");
            if (_face != null)
            {
                StringBuilder names = new StringBuilder();
                for (int i = 0; i < _face.sharedMesh.blendShapeCount; i++)
                {
                    names.Append(_face.sharedMesh.GetBlendShapeName(i)).Append(' ');
                }

                File.WriteAllText(Path.Combine(outputDir, "blendshapes.txt"), names.ToString());
            }

            NextStep();
        }

        private void Update()
        {
            // La pose fija se vuelve a sumar cada fotograma: FaceRig escribe y
            // vacía sus sumas al final del LateUpdate.
            for (int i = 0; i < _posed.Count; i++)
            {
                _faceRig.Add(_posed[i].Key, _posed[i].Value);
            }

            if (_done)
            {
                return;
            }

            if (_waitingAvatar)
            {
                Step waitStep = steps[_stepIndex];
                bool arrived = _binder != null && _binder.Current != null && _binder.Current.name.Contains("(Genies)");
                if (arrived || Time.realtimeSinceStartup - _avatarWaitStart >= waitStep.seconds)
                {
                    Debug.Log("[FaceLab] " + (arrived ? "avatar del SDK listo" : "sin avatar del SDK: sigue el doble")
                              + " tras " + (Time.realtimeSinceStartup - _avatarWaitStart).ToString("F1") + " s");
                    _waitingAvatar = false;
                    Time.captureDeltaTime = 1f / Mathf.Max(1, fps);
                    NextStep();
                }

                return;
            }

            if (_frame > 0 && (_frame - 1) % Mathf.Max(1, captureEvery) == 0)
            {
                Capture(_frame - 1);
            }

            if (_frame > 0)
            {
                LogFrame(_frame - 1);
            }

            AdvanceScript();
            FeedSpeech();
            PumpAudio();
            _frame++;
        }

        // ------------------------------------------------------------------
        // Guion
        // ------------------------------------------------------------------

        private void NextStep()
        {
            _stepIndex++;
            _stepStart = Time.time;
            _stepWaitingPlayback = false;
            _playbackDoneAt = -1f;
            if (_stepIndex >= steps.Count)
            {
                Finish();
                return;
            }

            Step step = steps[_stepIndex];
            _currentLabel = step.kind + ":" + (string.IsNullOrEmpty(step.value) ? Path.GetFileNameWithoutExtension(step.wav) : step.value);
            Debug.Log("[FaceLab] t=" + Time.time.ToString("F2") + " paso " + _stepIndex + ": " + _currentLabel);
            switch (step.kind)
            {
                case "state":
                    SendState(step.value);
                    break;
                case "attention":
                    _handleAttention.Invoke(_bootstrap, new object[] { new AttentionMessage { Category = step.value } });
                    break;
                case "speak":
                    StartSpeech(step);
                    break;
                case "freeze":
                    Freeze();
                    break;
                case "shape":
                    SetShapes(step.value);
                    break;
                case "avatar":
                    // Tiempo real y sin grabar mientras el SDK descarga y monta el avatar.
                    _waitingAvatar = true;
                    _avatarWaitStart = Time.realtimeSinceStartup;
                    Time.captureDeltaTime = 0f;
                    break;
            }
        }

        /// <summary>Un componente de la raíz de Sonia (o, sin ella, el primero de la escena).</summary>
        private T SoniaComponent<T>() where T : Component
        {
            T found = _bootstrap != null ? _bootstrap.GetComponentInChildren<T>(true) : null;
            return found != null ? found : FindAnyObjectByType<T>();
        }

        /// <summary>Cara, cabeza y ojos del avatar actual (cambian cuando el SDK sustituye al doble).</summary>
        private void BindAvatar()
        {
            _face = _faceRig != null ? _faceRig.PrimaryRenderer : null;
            _head = null;
            _leftEye = null;
            _rightEye = null;
            Animator animator = _choreographer != null ? _choreographer.MotionPlayerAnimator : null;
            if (animator == null)
            {
                animator = FindAnyObjectByType<Animator>();
            }

            if (animator != null && animator.isHuman)
            {
                _head = animator.GetBoneTransform(HumanBodyBones.Head);
            }

            if (_head == null)
            {
                return;
            }

            foreach (Transform t in _head.GetComponentsInChildren<Transform>(true))
            {
                if (t.name == "LeftEye")
                {
                    _leftEye = t;
                }
                else if (t.name == "RightEye")
                {
                    _rightEye = t;
                }
            }
        }

        private void OnAvatarChanged(Transform avatar)
        {
            BindAvatar();
            Debug.Log("[FaceLab] avatar nuevo: " + avatar.name + ", cara " + (_face != null ? _face.name : "ninguna"));
        }

        /// <summary>Apaga todo lo que escribe en la cara, para posar blendshapes a mano.</summary>
        private void Freeze()
        {
            foreach (MonoBehaviour behaviour in FindObjectsByType<MonoBehaviour>(FindObjectsInactive.Exclude))
            {
                string name = behaviour.GetType().Name;
                if (name == "LipSyncController" || name == "FacialExpressionController" || name == "AvatarStateController"
                    || name == "EyeGazeController" || name == "PhonemeLipSyncBridge" || name == "FaceAnimator")
                {
                    behaviour.enabled = false;
                }
            }
        }

        /// <summary>
        /// Pose fija de la cara ("canal:peso,..."): visemas, nombres ARKit o formas
        /// FACS. Sustituye a la anterior y se suma en FaceRig cada fotograma; con
        /// la cara congelada, lo demás queda a cero.
        /// </summary>
        private void SetShapes(string spec)
        {
            _posed.Clear();
            if (_faceRig == null)
            {
                return;
            }

            foreach (string part in (spec ?? string.Empty).Split(','))
            {
                string[] kv = part.Split(':');
                if (kv.Length != 2)
                {
                    continue;
                }

                int channel = _faceRig.Channel(kv[0].Trim());
                float weight;
                if (channel >= 0 && float.TryParse(kv[1], NumberStyles.Float, CultureInfo.InvariantCulture, out weight))
                {
                    _posed.Add(new KeyValuePair<int, float>(channel, weight));
                }
                else
                {
                    Debug.LogWarning("[FaceLab] canal desconocido en la pose: " + part);
                }
            }
        }

        private void AdvanceScript()
        {
            if (_stepIndex < 0 || _stepIndex >= steps.Count)
            {
                return;
            }

            Step step = steps[_stepIndex];
            if (step.kind == "speak")
            {
                // Termina cuando el audio se ha reproducido entero, más la pausa.
                if (_speech != null || _player.IsPlaying || !_speechEnded)
                {
                    return;
                }

                if (_playbackDoneAt < 0f)
                {
                    _playbackDoneAt = Time.time;
                }

                if (!step.ambient && !_stepWaitingPlayback && Time.time - _playbackDoneAt >= idleAfterPlayback)
                {
                    _stepWaitingPlayback = true;
                    SendState(AvatarStateNames.Idle);
                }

                if (Time.time - _playbackDoneAt >= Mathf.Max(idleAfterPlayback, step.seconds))
                {
                    NextStep();
                }

                return;
            }

            if (Time.time - _stepStart >= step.seconds)
            {
                NextStep();
            }
        }

        private void SendState(string state)
        {
            _handleState.Invoke(_bootstrap, new object[] { new StateMessage { State = state } });
        }

        private void StartSpeech(Step step)
        {
            int rate;
            float[] samples = ReadWav(step.wav, out rate);
            if (samples == null)
            {
                Debug.LogError("[FaceLab] no se pudo leer " + step.wav);
                return;
            }

            _utterance++;
            _speech = samples;
            _speechRate = rate;
            _speechSent = 0;
            _speechEnded = false;
            _speechStart = Time.time;
            _player.SetSourceSampleRate(rate);
            _handleSpeechStart.Invoke(
                _bootstrap,
                new object[] { new SpeechStartMessage { UtteranceId = _utterance, Text = step.text, Ambient = step.ambient } });
            if (!step.ambient)
            {
                SendState(AvatarStateNames.Speaking);
            }
        }

        /// <summary>Envía los chunks de la frase al ritmo de la voz, con su retraso y su ventaja.</summary>
        private void FeedSpeech()
        {
            if (_speech == null)
            {
                return;
            }

            float elapsed = Time.time - _speechStart - audioLatency;
            if (elapsed < 0f)
            {
                return;
            }

            int due = Mathf.Min(_speech.Length, Mathf.FloorToInt((elapsed + audioLead) * _speechRate));
            int chunk = Mathf.Max(1, Mathf.RoundToInt(chunkSeconds * _speechRate));
            while (_speechSent < due)
            {
                int count = Mathf.Min(chunk, _speech.Length - _speechSent);
                float[] part = new float[count];
                Array.Copy(_speech, _speechSent, part, 0, count);
                _speechSent += count;
                bool last = _speechSent >= _speech.Length;
                _handleAudioFrame.Invoke(
                    _bootstrap,
                    new object[] { new AudioFrame { UtteranceId = _utterance, IsLast = last, Samples = part } });
                if (last)
                {
                    _handleSpeechEnd.Invoke(_bootstrap, new object[] { new SpeechEndMessage { UtteranceId = _utterance } });
                    _speech = null;
                    _speechEnded = true;
                    break;
                }
            }
        }

        /// <summary>Hace de motor de audio: pide al reproductor los bloques que tocan en este fotograma.</summary>
        private void PumpAudio()
        {
            if (_player == null || _filterRead == null)
            {
                return;
            }

            _owedSamples += _outputRate * (double)Time.captureDeltaTime;
            int frames = _block.Length / 2;
            while (_owedSamples >= frames)
            {
                _owedSamples -= frames;
                Array.Clear(_block, 0, _block.Length);
                _filterRead.Invoke(_player, new object[] { _block, 2 });
                for (int i = 0; i < frames; i++)
                {
                    _heard.Add(_block[i * 2]);
                }
            }
        }

        // ------------------------------------------------------------------
        // Captura y registro
        // ------------------------------------------------------------------

        private void Capture(int frame)
        {
            Camera stand = standCamera != null ? standCamera : Camera.main;
            if (stand == null)
            {
                return;
            }

            if (captureStand)
            {
                Render(stand, standSize.x, standSize.y, ref _standTarget, ref _standTexture,
                    Path.Combine(outputDir, "stand", frame.ToString("D5") + ".jpg"));
            }

            if (captureCloseup && closeupCamera != null && _head != null)
            {
                // Desde la misma posición que la cámara del stand, con teleobjetivo
                // apuntando a la cara: misma perspectiva y mismo enfoque.
                Vector3 target = _head.position + _head.up * 0.075f;
                if (_leftEye != null && _rightEye != null)
                {
                    target = (_leftEye.position + _rightEye.position) * 0.5f - _head.up * 0.02f;
                }

                closeupCamera.transform.position = stand.transform.position;
                closeupCamera.transform.rotation = Quaternion.LookRotation(target - stand.transform.position, Vector3.up);
                closeupCamera.fieldOfView = closeupFov;
                Render(closeupCamera, closeupSize, closeupSize, ref _closeupTarget, ref _closeupTexture,
                    Path.Combine(outputDir, "closeup", frame.ToString("D5") + ".jpg"));
            }
        }

        private static void Render(Camera camera, int width, int height, ref RenderTexture target, ref Texture2D texture, string path)
        {
            if (target == null || target.width != width || target.height != height)
            {
                target = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32);
                target.antiAliasing = 4;
                texture = new Texture2D(width, height, TextureFormat.RGB24, false);
            }

            RenderTexture previousTarget = camera.targetTexture;
            RenderTexture previousActive = RenderTexture.active;
            camera.targetTexture = target;
            camera.Render();
            camera.targetTexture = previousTarget;
            RenderTexture.active = target;
            texture.ReadPixels(new Rect(0, 0, width, height), 0, 0);
            texture.Apply(false);
            RenderTexture.active = previousActive;
            File.WriteAllBytes(path, texture.EncodeToJPG(92));
        }

        private void LogFrame(int frame)
        {
            if (_log == null)
            {
                return;
            }

            _line.Length = 0;
            CultureInfo inv = CultureInfo.InvariantCulture;
            string clip = _choreographer != null && _choreographer.Player != null
                ? (_choreographer.Player.CurrentClip(MotionPlayer.BodyLayer) != null ? _choreographer.Player.CurrentClip(MotionPlayer.BodyLayer).name : "-")
                : "-";
            _line.Append(frame).Append('\t')
                 .Append((frame / (float)Mathf.Max(1, fps)).ToString("F3", inv)).Append('\t')
                 .Append(_currentLabel).Append('\t')
                 .Append(_state != null ? _state.State.ToString() : "-").Append('\t')
                 .Append(clip).Append('\t')
                 .Append(_bridge != null ? _bridge.CurrentPhoneme : "-").Append('\t')
                 .Append(_bridge != null ? _bridge.CurrentVolume.ToString("F3", inv) : "-").Append('\t')
                 .Append(_bridge != null ? _bridge.CurrentRawVolume.ToString("F4", inv) : "-").Append('\t')
                 .Append(_lipSync != null ? _lipSync.MouthOpen.ToString("F3", inv) : "-").Append('\t');
            if (_head != null)
            {
                Vector3 e = _head.localEulerAngles;
                _line.Append(Wrap(e.x).ToString("F1", inv)).Append('\t').Append(Wrap(e.y).ToString("F1", inv)).Append('\t');
            }
            else
            {
                _line.Append("-\t-\t");
            }

            _line.Append(EyeText(_leftEye, inv)).Append('\t').Append(EyeText(_rightEye, inv)).Append('\t');
            if (_face != null)
            {
                Mesh mesh = _face.sharedMesh;
                float scale = LipSyncController.BlendShapeScale(mesh);
                for (int i = 0; i < mesh.blendShapeCount; i++)
                {
                    float w = _face.GetBlendShapeWeight(i) / (100f * scale);
                    if (w > 0.005f)
                    {
                        _line.Append(mesh.GetBlendShapeName(i)).Append('=').Append(w.ToString("F2", inv)).Append(' ');
                    }
                }
            }

            _log.WriteLine(_line.ToString());
        }

        private static string EyeText(Transform eye, CultureInfo inv)
        {
            if (eye == null)
            {
                return "-";
            }

            Vector3 e = eye.localEulerAngles;
            return Wrap(e.x).ToString("F1", inv) + "," + Wrap(e.y).ToString("F1", inv);
        }

        private static float Wrap(float degrees)
        {
            return degrees > 180f ? degrees - 360f : degrees;
        }

        private void Finish()
        {
            _done = true;
            if (_log != null)
            {
                _log.Flush();
                _log.Dispose();
                _log = null;
            }

            // En un equipo de verdad el bloque tarda un búfer en sonar: se
            // reproduce esa latencia en el WAV para que el vídeo cuadre igual.
            int latency = _lipSync != null ? _lipSync.OutputLatencySamples : 0;
            if (latency > 0)
            {
                _heard.InsertRange(0, new float[latency]);
            }

            WriteWav(Path.Combine(outputDir, "heard.wav"), _heard, _outputRate);
            File.WriteAllText(Path.Combine(outputDir, "done.txt"), _frame.ToString(CultureInfo.InvariantCulture));
            Debug.Log("[FaceLab] terminado: " + _frame + " fotogramas en " + Path.GetFullPath(outputDir));
            Time.captureDeltaTime = 0f;
            if (exitWhenDone)
            {
                UnityEditor.EditorApplication.Exit(0);
            }
            else
            {
                UnityEditor.EditorApplication.isPlaying = false;
            }
        }

        // ------------------------------------------------------------------
        // WAV
        // ------------------------------------------------------------------

        /// <summary>Lee un WAV PCM de 16 bits (mono o estéreo, se mezcla a mono).</summary>
        public static float[] ReadWav(string path, out int sampleRate)
        {
            sampleRate = 24000;
            if (string.IsNullOrEmpty(path) || !File.Exists(path))
            {
                return null;
            }

            byte[] bytes = File.ReadAllBytes(path);
            int channels = 1;
            int bits = 16;
            int pos = 12;
            while (pos + 8 <= bytes.Length)
            {
                string id = Encoding.ASCII.GetString(bytes, pos, 4);
                int size = BitConverter.ToInt32(bytes, pos + 4);
                int body = pos + 8;
                if (id == "fmt ")
                {
                    channels = BitConverter.ToInt16(bytes, body + 2);
                    sampleRate = BitConverter.ToInt32(bytes, body + 4);
                    bits = BitConverter.ToInt16(bytes, body + 14);
                }
                else if (id == "data")
                {
                    if (bits != 16)
                    {
                        return null;
                    }

                    size = Mathf.Min(size, bytes.Length - body);
                    int frames = size / (2 * Mathf.Max(1, channels));
                    float[] samples = new float[frames];
                    for (int i = 0; i < frames; i++)
                    {
                        float sum = 0f;
                        for (int c = 0; c < channels; c++)
                        {
                            sum += BitConverter.ToInt16(bytes, body + ((i * channels) + c) * 2) / 32768f;
                        }

                        samples[i] = sum / channels;
                    }

                    return samples;
                }

                pos = body + size + (size & 1);
            }

            return null;
        }

        private static void WriteWav(string path, List<float> samples, int rate)
        {
            using (FileStream stream = new FileStream(path, FileMode.Create))
            using (BinaryWriter writer = new BinaryWriter(stream))
            {
                int dataBytes = samples.Count * 2;
                writer.Write(Encoding.ASCII.GetBytes("RIFF"));
                writer.Write(36 + dataBytes);
                writer.Write(Encoding.ASCII.GetBytes("WAVE"));
                writer.Write(Encoding.ASCII.GetBytes("fmt "));
                writer.Write(16);
                writer.Write((short)1);
                writer.Write((short)1);
                writer.Write(rate);
                writer.Write(rate * 2);
                writer.Write((short)2);
                writer.Write((short)16);
                writer.Write(Encoding.ASCII.GetBytes("data"));
                writer.Write(dataBytes);
                for (int i = 0; i < samples.Count; i++)
                {
                    writer.Write((short)Mathf.Clamp(Mathf.RoundToInt(samples[i] * 32767f), -32768, 32767));
                }
            }
        }

        private void OnDestroy()
        {
            if (_binder != null)
            {
                _binder.AvatarChanged -= OnAvatarChanged;
            }

            if (_log != null)
            {
                _log.Dispose();
                _log = null;
            }
        }
    }
}

#endif
