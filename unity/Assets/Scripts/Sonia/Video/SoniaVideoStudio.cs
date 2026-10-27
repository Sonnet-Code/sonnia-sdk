// Renderizador de vídeos para redes («Sonnia Video», docs/video.md).
//
// Con SoniaVideoMode activo (argumento -sonnia-video o la build de vídeo) la app no
// conversa: carga a Sonnia como en el stand y espera trabajos de sonnia-video por
// HTTP en 127.0.0.1 (-sonnia-video-port, 8795 por defecto). Cada trabajo trae una
// línea de tiempo de mensajes del protocolo del stand (estado, speech_start,
// transcript, gesture...) y las voces de cada frase; este componente hace de
// orquestador grabado: los despacha por SoniaClient a su hora, manda la voz en trozos
// de 100 ms como GPT-Live y, como el laboratorio de cara, hace él de motor de audio
// (llama a OnAudioFilterRead del reproductor con lo que toca en cada paso). Así la
// boca, los gestos, la mirada y los subtítulos salen por el mismo camino que en el
// stand, pero a paso fijo (Time.captureDeltaTime): cada render es exacto y puede ir
// más despacio que el tiempo real.
//
// Los cuadros los pinta la cámara principal (con el HUD) en una RenderTexture que
// VideoFrameRecorder reduce, acumula y le pasa a ffmpeg. Al acabar escribe
// registro.json (cuándo sonó cada frase y la boca por cuadro) y heard.wav (lo que
// sonó), con los que sonnia-video coloca la voz final y comprueba la sincronía.
//
// La app se queda abierta para el siguiente vídeo (el avatar tarda en cargar) y se
// cierra sola tras -sonnia-video-idle-min minutos sin peticiones (45 por defecto).

using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Sonia.Video
{
    /// <summary>Conduce los trabajos del renderizador de vídeos (ver la cabecera).</summary>
    public sealed class SoniaVideoStudio : MonoBehaviour
    {
        private const string PortArgument = "-sonnia-video-port";
        private const string IdleArgument = "-sonnia-video-idle-min";
        private const int DefaultPort = 8795;
        private const float ChunkSeconds = 0.1f;
        private const float CapWaitSeconds = 120f;
        private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        private VideoHttpServer _http;
        private float _idleLimit;
        private float _lastRequest;
        private float _startedAt;

        // Escena
        private GameObject _sonia;
        private SoniaClient _client;
        private AudioStreamPlayer _player;
        private AvatarBinder _binder;
        private GeniesGestureLayer _gestures;
        private AvatarStateController _state;
        private FacialExpressionController _face;
        private LipSyncController _lipSync;
        private CameraFramingController _framing;
        private MethodInfo _filterRead;
        private float[] _block = new float[0];
        private bool _sceneReady;

        // Trabajo en curso
        private readonly VideoLook _look = new VideoLook();
        private VideoJob _job;
        private VideoFrameRecorder _recorder;
        private string _jobState;
        private string _jobError;
        private int _frame;
        private int _frames;
        private float _renderStarted;
        private bool _cancel;
        private bool _capOn;

        // Audio del trabajo
        private sealed class VoiceStream
        {
            public int UtteranceId;
            public float[] Samples;
            public float Start;
            public int Sent;
        }

        private readonly List<VoiceStream> _streams = new List<VoiceStream>();
        private readonly Dictionary<int, float> _firstAudio = new Dictionary<int, float>();
        private readonly Dictionary<int, float> _heard = new Dictionary<int, float>();
        private readonly List<float> _heardSamples = new List<float>();
        private bool _recordingAudio;
        private double _owedSamples;
        private long _outputSamples;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        private static void Create()
        {
            if (!SoniaVideoMode.Active)
            {
                return;
            }

            var go = new GameObject("SonniaVideoStudio");
            DontDestroyOnLoad(go);
            go.AddComponent<SoniaVideoStudio>();
        }

        private void Awake()
        {
            _startedAt = Time.realtimeSinceStartup;
            _lastRequest = _startedAt;
            Application.runInBackground = true;
            Application.targetFrameRate = 30;

            AudioListener.pause = true;
            _idleLimit = 60f * ArgFloat(IdleArgument, 45f);
            int port = Mathf.RoundToInt(ArgFloat(PortArgument, DefaultPort));
            _http = new VideoHttpServer(port, Handle);
            if (_http.Start())
            {
                Debug.Log("[Vídeo] Renderizador escuchando en http://127.0.0.1:" + port);
            }

            SceneManager.sceneLoaded += OnSceneLoaded;

            // Se usa desde la terminal (sonnia-video la lanza sin ventana con -batchmode y el
            // puerto). Abierta con doble clic no tiene nada que hacer: avisa y se cierra.
            if (!HasArgument(PortArgument) && !Application.isBatchMode)
            {
                Debug.Log("[Vídeo] Sonnia Video se usa desde la terminal (sonnia-video): me cierro.");
                Invoke(nameof(Quit), 0.2f);
            }
        }

        private void OnDestroy()
        {
            SceneManager.sceneLoaded -= OnSceneLoaded;
            _http?.Dispose();
            _recorder?.Dispose();
        }

        private void OnApplicationQuit()
        {
            _recorder?.Abort();
            _http?.Dispose();
        }

        private void OnSceneLoaded(Scene scene, LoadSceneMode mode)
        {
            if (_sceneReady)
            {
                return;
            }

            _sonia = GameObject.Find("Sonia");
            if (_sonia == null)
            {
                return;
            }

            _client = _sonia.GetComponentInChildren<SoniaClient>(true);
            _player = _sonia.GetComponentInChildren<AudioStreamPlayer>(true);
            _binder = _sonia.GetComponentInChildren<AvatarBinder>(true);
            _gestures = _sonia.GetComponentInChildren<GeniesGestureLayer>(true);
            _state = _sonia.GetComponentInChildren<AvatarStateController>(true);
            _face = _sonia.GetComponentInChildren<FacialExpressionController>(true);
            _lipSync = _sonia.GetComponentInChildren<LipSyncController>(true);
            _framing = FindAnyObjectByType<CameraFramingController>(FindObjectsInactive.Include);
            _filterRead = typeof(AudioStreamPlayer).GetMethod("OnAudioFilterRead", BindingFlags.Instance | BindingFlags.NonPublic);

            // Solo Sonnia: el invitado del Modo Jean cargaba otro avatar de Genies a la vez y a
            // veces se estorbaban (el de Sonnia no llegaba). Y sin el doble: un vídeo con el doble
            // no sirve; mejor esperar a que Genies entregue el de verdad (el cargador reintenta).
            GameObject guest = GameObject.Find("Invitado");
            if (guest != null)
            {
                guest.SetActive(false);
            }

            Component loader = _sonia.GetComponent("GeniesAvatarLoader");
            VideoLook.SetField(loader, "standInAfterSeconds", 0f);
            VideoLook.SetField(loader, "standInAfterFailures", 0);

            // Nada que no pida el guion: ni saludo al aparecer ni gestos de atención o aburrimiento.
            VideoLook.SetField(loader, "greetOnAppear", false);
            AvatarChoreographer choreographer = _sonia.GetComponentInChildren<AvatarChoreographer>(true);
            VideoLook.SetField(choreographer, "attentionQuietDelay", 1e6f);
            VideoLook.SetField(choreographer, "boredInterval", new Vector2(1e5f, 1e5f + 1f));

            // La voz no suena por los altavoces: el audio lo consume este componente.
            AudioSource source = _player != null ? _player.GetComponent<AudioSource>() : null;
            if (source != null)
            {
                source.Stop();
                source.enabled = false;
            }

            AudioSettings.GetDSPBufferSize(out int dsp, out _);
            _block = new float[Mathf.Clamp(dsp, 256, 4096) * 2];
            _sceneReady = true;
            Debug.Log("[Vídeo] Escena lista: " + (_player != null ? "reproductor ok" : "SIN reproductor")
                      + ", filtro " + (_filterRead != null ? "ok" : "NO") + ", encuadre " + (_framing != null ? "ok" : "NO"));
        }

        private void Update()
        {
            _http?.Pump();
            if (_job == null && _idleLimit > 0f && Time.realtimeSinceStartup - _lastRequest > _idleLimit)
            {
                Debug.Log("[Vídeo] Sin peticiones en " + (_idleLimit / 60f) + " min: cierro.");
                Application.Quit();
            }
        }

        // ------------------------------------------------------------------
        // HTTP
        // ------------------------------------------------------------------

        private HttpReply Handle(string method, string path, string body)
        {
            _lastRequest = Time.realtimeSinceStartup;
            switch (method + " " + path)
            {
                case "GET /status":
                case "GET ":
                    return new HttpReply(200, StatusJson());
                case "GET /catalog":
                    if (AvatarStatus() == "loading" || _gestures == null || _gestures.Set == null)
                    {
                        return new HttpReply(503, VideoHttpServer.Error("el avatar aún no está listo"));
                    }

                    return new HttpReply(200, Protocol.GestureCatalogMessage(_gestures.Set));
                case "POST /job":
                    return StartJob(body);
                case "POST /cancel":
                    if (_job != null)
                    {
                        _cancel = true;
                    }

                    return new HttpReply(200, "{\"ok\":true}");
                case "POST /quit":
                    Invoke(nameof(Quit), 0.2f);
                    return new HttpReply(200, "{\"ok\":true}");
                default:
                    return new HttpReply(404, VideoHttpServer.Error("no existe " + method + " " + path));
            }
        }

        private void Quit()
        {
            Application.Quit();
        }

        /// <summary>"ready" con el avatar de Genies puesto; si no, "loading" (sin doble: se espera al de verdad).</summary>
        private string AvatarStatus()
        {
            Transform current = _binder != null ? _binder.Current : null;
            return current != null && current.name.Contains("(Genies)") ? "ready" : "loading";
        }

        private string StatusJson()
        {
            var status = new JObject
            {
                ["app"] = "sonnia-video",
                ["version"] = Application.version,
                ["avatar"] = _sceneReady ? AvatarStatus() : "loading",
                ["outfit"] = Array.IndexOf(Environment.GetCommandLineArgs(), "-sin-camiseta-staff") >= 0 ? "plain" : "staff",
                ["busy"] = _job != null,
                ["job"] = _job == null && _jobState == null
                    ? null
                    : new JObject
                    {
                        ["id"] = _lastJobId,
                        ["kind"] = _lastJobKind,
                        ["state"] = _jobState,
                        ["frame"] = _frame,
                        ["frames"] = _frames,
                        ["render_fps"] = Math.Round(RenderFps(), 2),
                        ["error"] = _jobError
                    }
            };
            return status.ToString(Formatting.None);
        }

        private string _lastJobId;
        private string _lastJobKind;

        private float RenderFps()
        {
            float elapsed = Time.realtimeSinceStartup - _renderStarted;
            return _jobState == "rendering" && elapsed > 0.5f ? _frame / elapsed : 0f;
        }

        private HttpReply StartJob(string body)
        {
            if (_job != null)
            {
                return new HttpReply(409, VideoHttpServer.Error("ya hay un trabajo en curso: " + _job.Id));
            }

            if (!_sceneReady || AvatarStatus() == "loading")
            {
                return new HttpReply(503, VideoHttpServer.Error("el avatar aún no está listo"));
            }

            VideoJob job;
            try
            {
                job = JsonConvert.DeserializeObject<VideoJob>(body);
            }
            catch (Exception ex)
            {
                return new HttpReply(400, VideoHttpServer.Error("trabajo ilegible: " + ex.Message));
            }

            string problem = Validate(job);
            if (problem != null)
            {
                return new HttpReply(400, VideoHttpServer.Error(problem));
            }

            job.Timeline.Sort((a, b) => a.Time.CompareTo(b.Time));
            _job = job;
            _lastJobId = job.Id;
            _lastJobKind = job.Kind;
            _jobState = "preparing";
            _jobError = null;
            _frame = 0;
            _frames = job.IsStill ? 1 : Mathf.Max(1, Mathf.RoundToInt(job.DurationSeconds * job.Fps));
            _cancel = false;
            StartCoroutine(Run(job));
            return new HttpReply(202, "{\"ok\":true,\"id\":" + JsonConvert.ToString(job.Id) + "}");
        }

        private static string Validate(VideoJob job)
        {
            if (job == null)
            {
                return "trabajo vacío";
            }

            if (job.Width < 16 || job.Height < 16 || job.Width > 4096 || job.Height > 4096 || job.Width % 2 != 0 || job.Height % 2 != 0)
            {
                return "resolución no válida (pares, de 16 a 4096): " + job.Width + "x" + job.Height;
            }

            if (job.Fps < 1 || job.Fps > 120)
            {
                return "fps no válidos: " + job.Fps;
            }

            if (string.IsNullOrEmpty(job.OutputDir))
            {
                return "falta output_dir";
            }

            if (!job.IsStill && (job.Encoder == null || string.IsNullOrEmpty(job.Encoder.Ffmpeg) || string.IsNullOrEmpty(job.Encoder.Path)))
            {
                return "falta encoder (ffmpeg y path)";
            }

            if (!job.IsStill && !File.Exists(job.Encoder.Ffmpeg))
            {
                return "no existe ffmpeg en " + job.Encoder.Ffmpeg;
            }

            foreach (TimelineEntry entry in job.Timeline)
            {
                if (entry.Audio != null && !File.Exists(entry.Audio.Wav))
                {
                    return "no existe la voz " + entry.Audio.Wav;
                }
            }

            return null;
        }

        // ------------------------------------------------------------------
        // Trabajo
        // ------------------------------------------------------------------

        private IEnumerator Run(VideoJob job)
        {
            IEnumerator steps = Steps(job);
            while (true)
            {
                object current;
                try
                {
                    if (!steps.MoveNext())
                    {
                        break;
                    }

                    current = steps.Current;
                }
                catch (Exception ex)
                {
                    if (_cancel)
                    {
                        Debug.Log("[Vídeo] " + job.Id + " cancelado");
                        _jobState = "cancelled";
                    }
                    else
                    {
                        Debug.LogException(ex);
                        _jobError = ex.Message;
                        _jobState = "error";
                    }

                    Cleanup();
                    yield break;
                }

                yield return current;
            }

            Cleanup();
        }

        private IEnumerator Steps(VideoJob job)
        {
            Directory.CreateDirectory(job.OutputDir);
            Transform avatar = _binder != null ? _binder.Current : null;
            Animator animator = avatar != null ? avatar.GetComponentInChildren<Animator>() : null;
            Camera camera = _framing != null && _framing.TargetCamera != null ? _framing.TargetCamera : Camera.main;
            // Con fondo transparente, de color, degradado o imagen, Sonnia se pinta aislada (alfa por
            // diferencia) y el fondo se compone después con sus colores exactos: el posprocesado de
            // la escena (tonemapping y viñeta) los apagaba. El del stand es la escena tal cual.
            string mode = (job.Scene.Background.Mode ?? "stand").ToLowerInvariant();
            bool transparent = mode == "transparent" || mode == "color" || mode == "gradient" || mode == "image";

            // Gorra (en tiempo real: el pelo aplastado lo hace Genies en segundo plano).
            Time.captureDeltaTime = 0f;
            if (job.Scene.Cap || _capOn)
            {
                IEnumerator cap = _look.SetCap(job.Scene.Cap, _sonia, avatar, CapWaitSeconds);
                while (cap.MoveNext())
                {
                    yield return cap.Current;
                }

                _capOn = job.Scene.Cap;
            }

            _look.ApplyStage(job, _client, _face);
            _look.ApplyLighting(job.Scene.Lighting, avatar);
            _client.InjectMessage("{\"type\":\"state\",\"state\":\"idle\"}");
            _player.Flush();
            _player.SetSourceSampleRate(Mathf.Max(8000, job.AudioSampleRate));

            int sub = job.IsStill ? 1 : Mathf.Clamp(job.Subframes, 1, 16);
            int window = Mathf.Clamp(Mathf.RoundToInt(sub * Mathf.Clamp01(job.Shutter)), 1, sub);
            float dt = 1f / (job.Fps * sub);
            _recorder = new VideoFrameRecorder(job.Width, job.Height, job.Supersample, transparent);
            if (mode != "transparent")
            {
                Texture2D background = _look.BackgroundTexture(job.Scene.Background, job.Width, job.Height, out Vector4 st);
                if (background != null)
                {
                    _recorder.SetBackground(background, st);
                }
            }

            _camera = camera;
            _cameraMask = camera.cullingMask;
            _cameraClear = camera.clearFlags;
            _cameraBackground = camera.backgroundColor;
            camera.targetTexture = _recorder.Target;
            // Sin el HUD del stand y pintada a mano (VideoFrameRecorder.Render): con la cámara
            // apagada la pila no pinta la cámara del HUD.
            camera.enabled = false;
            if (transparent)
            {
                // Solo Sonnia (y su gorra): ni fondo, ni halo, ni partículas.
                _layered.Clear();
                MoveToLayer(avatar, _layered);
                if (VideoLook.GetField(FindAnyObjectByType<TriviaHat>(FindObjectsInactive.Include), "_root") is Transform hatRoot)
                {
                    MoveToLayer(hatRoot, _layered);
                }

                camera.cullingMask = 1 << CaptureLayer;
                camera.clearFlags = CameraClearFlags.SolidColor;
            }

            if (avatar != null)
            {
                foreach (SkinnedMeshRenderer skin in avatar.GetComponentsInChildren<SkinnedMeshRenderer>(true))
                {
                    skin.forceMatrixRecalculationPerRender = true;
                }
            }

            _bones = TrackedBones(animator, avatar);
            float savedFixed = Time.fixedDeltaTime;
            int savedVsync = QualitySettings.vSyncCount;
            QualitySettings.vSyncCount = 0;
            Application.targetFrameRate = -1;
            Time.captureDeltaTime = dt;
            Time.fixedDeltaTime = dt;
            _restoreFixed = savedFixed;
            _restoreVsync = savedVsync;
            if (!job.IsStill)
            {
                _recorder.StartEncoder(job.Encoder, job.Fps);
            }

            // Fotos: en qué cuadros se guarda cada una (sin lista, una al acabar el calentamiento).
            var stills = new Dictionary<int, List<string>>();
            if (job.IsStill)
            {
                if (job.Stills != null && job.Stills.Count > 0)
                {
                    foreach (VideoStill still in job.Stills)
                    {
                        int at = Mathf.Max(0, Mathf.RoundToInt(still.Time * job.Fps));
                        if (!stills.TryGetValue(at, out List<string> paths))
                        {
                            stills[at] = paths = new List<string>();
                        }

                        paths.Add(still.Path);
                    }
                }
                else
                {
                    stills[0] = new List<string>
                    {
                        string.IsNullOrEmpty(job.StillPath) ? Path.Combine(job.OutputDir, "still.png") : job.StillPath
                    };
                }

                int last = 0;
                foreach (int at in stills.Keys)
                {
                    last = Mathf.Max(last, at);
                }

                _frames = last + 1;
            }

            // Calentamiento sin grabar: el reposo se asienta, la cámara salta a su sitio y
            // Sonnia mira a cámara.
            ResetAudio(false);
            float aspect = job.Width / (float)job.Height;
            int warm = Mathf.Max(2, Mathf.RoundToInt(job.WarmupSeconds / dt));
            for (int k = 0; k < warm; k++)
            {
                if (k == Mathf.Min(warm - 2, Mathf.RoundToInt(0.5f / dt)))
                {
                    ShotPose pose = _look.ApplyFraming(job.Scene.Framing, _framing, camera, animator, avatar, aspect);
                    _state.SetLookOverride(pose.Position);
                }

                PumpAudio(dt);
                yield return new WaitForEndOfFrame();
                if (_cancel)
                {
                    throw new OperationCanceledException("cancelado");
                }
            }

            _recorder.Calibrate(camera);
            ResetAudio(true);
            _jobState = "rendering";
            _renderStarted = Time.realtimeSinceStartup;
            var frames = new StringBuilder();
            int next = 0;
            for (int i = 0; i < _frames; i++)
            {
                bool wanted = !job.IsStill || stills.ContainsKey(i);
                _recorder.BeginFrame();
                for (int s = 0; s < sub; s++)
                {
                    float t = (i * sub + s) * dt;
                    next = Dispatch(job, t, next);
                    StreamVoices(t);
                    PumpAudio(dt);
                    yield return new WaitForEndOfFrame();
                    if (wanted && s >= sub - window)
                    {
                        _recorder.Expose(camera, window);
                    }
                }

                if (_cancel)
                {
                    throw new OperationCanceledException("cancelado");
                }

                if (job.IsStill)
                {
                    if (wanted)
                    {
                        byte[] photo = _recorder.ReadFrame(false);
                        foreach (string path in stills[i])
                        {
                            _recorder.SavePng(photo, path);
                        }
                    }
                }
                else
                {
                    _recorder.Encode(_recorder.ReadFrame(true));
                }

                if (i > 0)
                {
                    frames.Append(',');
                }

                frames.Append("{\"i\":").Append(i)
                    .Append(",\"rms\":").Append(_player.CurrentRms.ToString("0.0000", Inv))
                    .Append(",\"mouth\":").Append((_lipSync != null ? _lipSync.MouthOpen : 0f).ToString("0.0000", Inv))
                    .Append(",\"utterance\":").Append(_player.CurrentUtteranceId)
                    .Append(",\"bones\":").Append(BonesJson(camera, job.Width, job.Height)).Append('}');
                _frame = i + 1;
                if (i % 60 == 0)
                {
                    Debug.Log(string.Format(Inv, "[Vídeo] {0}: cuadro {1}/{2} ({3:0.0} cuadros/s)", job.Id, i, _frames, RenderFps()));
                }
            }

            if (!job.IsStill)
            {
                _jobState = "encoding";
                _recorder.CloseEncoder();
                float waitStart = Time.realtimeSinceStartup;
                Time.captureDeltaTime = 0f;
                while (!_recorder.EncoderFinished)
                {
                    if (Time.realtimeSinceStartup - waitStart > 600f)
                    {
                        throw new TimeoutException("ffmpeg no terminó en 10 min");
                    }

                    yield return null;
                }

                if (_recorder.EncoderExitCode != 0)
                {
                    throw new IOException("ffmpeg salió con " + _recorder.EncoderExitCode + ":\n" + _recorder.FfmpegLog);
                }
            }

            WriteReport(job, frames.ToString());
            _jobState = "done";
            Debug.Log("[Vídeo] " + job.Id + " listo en " + job.OutputDir);
        }

        // ------------------------------------------------------------------
        // Capa de Sonnia (fondo transparente) y huesos por cuadro (localizador)
        // ------------------------------------------------------------------

        private const int CaptureLayer = 31;
        private readonly List<KeyValuePair<GameObject, int>> _layered = new List<KeyValuePair<GameObject, int>>();
        private int _cameraMask;
        private CameraClearFlags _cameraClear;
        private Color _cameraBackground;
        private List<KeyValuePair<string, Transform>> _bones = new List<KeyValuePair<string, Transform>>();

        private static void MoveToLayer(Transform root, List<KeyValuePair<GameObject, int>> saved)
        {
            if (root == null)
            {
                return;
            }

            foreach (Transform part in root.GetComponentsInChildren<Transform>(true))
            {
                saved.Add(new KeyValuePair<GameObject, int>(part.gameObject, part.gameObject.layer));
                part.gameObject.layer = CaptureLayer;
            }
        }

        private void RestoreLayers()
        {
            foreach (KeyValuePair<GameObject, int> pair in _layered)
            {
                if (pair.Key != null)
                {
                    pair.Key.layer = pair.Value;
                }
            }

            _layered.Clear();
        }

        /// <summary>Puntos que se registran por cuadro: cara (entre los ojos), cabeza, manos, índices, pecho y cadera.</summary>
        private static List<KeyValuePair<string, Transform>> TrackedBones(Animator animator, Transform avatar)
        {
            var bones = new List<KeyValuePair<string, Transform>>();
            if (animator == null)
            {
                return bones;
            }

            void Add(string key, HumanBodyBones bone)
            {
                Transform t = animator.GetBoneTransform(bone);
                if (t != null)
                {
                    bones.Add(new KeyValuePair<string, Transform>(key, t));
                }
            }

            Add("cabeza", HumanBodyBones.Head);
            Add("cuello", HumanBodyBones.Neck);
            Add("pecho", HumanBodyBones.UpperChest);
            Add("cadera", HumanBodyBones.Hips);
            // Sonnia mira a cámara: su mano derecha sale a la izquierda de la pantalla.
            Add("mano_der", HumanBodyBones.RightHand);
            Add("mano_izq", HumanBodyBones.LeftHand);
            Add("indice_der", HumanBodyBones.RightIndexDistal);
            Add("indice_izq", HumanBodyBones.LeftIndexDistal);
            Add("nudillos_der", HumanBodyBones.RightMiddleProximal);
            Add("nudillos_izq", HumanBodyBones.LeftMiddleProximal);
            Transform left = null;
            Transform right = null;
            foreach (Transform part in avatar.GetComponentsInChildren<Transform>(true))
            {
                string n = part.name.ToLowerInvariant();
                if (left == null && (n == "lefteye" || n == "eye_l" || n == "l_eye" || n.EndsWith("lefteye")))
                {
                    left = part;
                }
                else if (right == null && (n == "righteye" || n == "eye_r" || n == "r_eye" || n.EndsWith("righteye")))
                {
                    right = part;
                }
            }

            if (left != null && right != null)
            {
                bones.Add(new KeyValuePair<string, Transform>("ojo_izq", left));
                bones.Add(new KeyValuePair<string, Transform>("ojo_der", right));
            }

            return bones;
        }

        /// <summary>{"cabeza":[x,y,z], ...} en píxeles del cuadro (y hacia abajo) y metros a la cámara.</summary>
        private string BonesJson(Camera camera, int width, int height)
        {
            var sb = new StringBuilder("{");
            Vector3 eyes = Vector3.zero;
            int eyeCount = 0;
            foreach (KeyValuePair<string, Transform> bone in _bones)
            {
                if (bone.Value == null)
                {
                    continue;
                }

                if (bone.Key.StartsWith("ojo_", StringComparison.Ordinal))
                {
                    eyes += bone.Value.position;
                    eyeCount++;
                }

                AppendPoint(sb, bone.Key, camera.WorldToViewportPoint(bone.Value.position), width, height);
            }

            if (eyeCount == 2)
            {
                AppendPoint(sb, "cara", camera.WorldToViewportPoint(eyes * 0.5f), width, height);
            }

            return sb.Append('}').ToString();
        }

        private static void AppendPoint(StringBuilder sb, string key, Vector3 v, int width, int height)
        {
            if (sb.Length > 1)
            {
                sb.Append(',');
            }

            sb.Append('"').Append(key).Append("\":[")
                .Append((v.x * width).ToString("0.0", Inv)).Append(',')
                .Append(((1f - v.y) * height).ToString("0.0", Inv)).Append(',')
                .Append(v.z.ToString("0.000", Inv)).Append(']');
        }

        private float _restoreFixed = 0.02f;
        private int _restoreVsync;
        private Camera _camera;

        private void Cleanup()
        {
            Time.captureDeltaTime = 0f;
            Time.fixedDeltaTime = _restoreFixed;
            QualitySettings.vSyncCount = _restoreVsync;
            Application.targetFrameRate = 30;
            RestoreLayers();
            if (_camera != null)
            {
                _camera.targetTexture = null;
                _camera.enabled = true;
                _camera.cullingMask = _cameraMask;
                _camera.clearFlags = _cameraClear;
                _camera.backgroundColor = _cameraBackground;
                _camera = null;
            }

            _streams.Clear();
            _recordingAudio = false;
            _player.Flush();
            _client.InjectMessage("{\"type\":\"state\",\"state\":\"idle\"}");
            _state.ClearLookOverride();
            _look.Restore(_framing);
            if (_recorder != null)
            {
                _recorder.Abort();
                _recorder.Dispose();
                _recorder = null;
            }

            _job = null;
            _lastRequest = Time.realtimeSinceStartup;
        }

        /// <summary>Despacha lo de la línea de tiempo que toca hasta t; devuelve el índice siguiente.</summary>
        private int Dispatch(VideoJob job, float t, int next)
        {
            // Medio paso de margen: lo que cae entre dos subfotogramas va con el más cercano.
            float limit = t + 0.5f / (job.Fps * Mathf.Max(1, job.Subframes));
            while (next < job.Timeline.Count && job.Timeline[next].Time <= limit)
            {
                TimelineEntry entry = job.Timeline[next++];
                if (entry.Message != null)
                {
                    if (!_client.InjectMessage(entry.Message.ToString(Formatting.None)))
                    {
                        Debug.LogWarning("[Vídeo] Mensaje desconocido: " + entry.Message.ToString(Formatting.None));
                    }
                }

                if (entry.Audio != null)
                {
                    _streams.Add(new VoiceStream
                    {
                        UtteranceId = entry.Audio.UtteranceId,
                        Samples = ReadWav(entry.Audio.Wav),
                        Start = entry.Time
                    });
                    _firstAudio[entry.Audio.UtteranceId] = entry.Time;
                }

                if (entry.Action != null && _gestures != null && !_gestures.PlayAction(entry.Action.Name, -1f, entry.Action.Mirror))
                {
                    Debug.LogWarning("[Vídeo] No se pudo lanzar el gesto " + entry.Action.Name);
                }
            }

            return next;
        }

        /// <summary>Manda los trozos de voz de 100 ms que ya tocan, al ritmo real, como GPT-Live.</summary>
        private void StreamVoices(float t)
        {
            int rate = Mathf.Max(8000, _job.AudioSampleRate);
            int chunk = Mathf.RoundToInt(ChunkSeconds * rate);
            for (int k = _streams.Count - 1; k >= 0; k--)
            {
                VoiceStream stream = _streams[k];
                int due = Mathf.Min(stream.Samples.Length, Mathf.FloorToInt((t - stream.Start + ChunkSeconds) * rate));
                while (stream.Sent < due)
                {
                    int count = Mathf.Min(chunk, stream.Samples.Length - stream.Sent);
                    var part = new float[count];
                    Array.Copy(stream.Samples, stream.Sent, part, 0, count);
                    stream.Sent += count;
                    bool last = stream.Sent >= stream.Samples.Length;
                    _client.InjectAudioFrame(new AudioFrame { UtteranceId = stream.UtteranceId, IsLast = last, Samples = part });
                    if (last)
                    {
                        _client.InjectMessage("{\"type\":\"speech_end\",\"utterance_id\":" + stream.UtteranceId + "}");
                        _streams.RemoveAt(k);
                        break;
                    }
                }
            }
        }

        private void ResetAudio(bool record)
        {
            _owedSamples = 0;
            _outputSamples = 0;
            _heardSamples.Clear();
            _heard.Clear();
            _firstAudio.Clear();
            _recordingAudio = record;
        }

        /// <summary>Hace de motor de audio: pide al reproductor los bloques de este paso.</summary>
        private void PumpAudio(float dt)
        {
            if (_player == null || _filterRead == null)
            {
                return;
            }

            int rate = _player.OutputSampleRate > 0 ? _player.OutputSampleRate : 48000;
            _owedSamples += rate * (double)dt;
            int frames = _block.Length / 2;
            while (_owedSamples >= frames)
            {
                _owedSamples -= frames;
                Array.Clear(_block, 0, _block.Length);
                _filterRead.Invoke(_player, new object[] { _block, 2 });
                if (!_recordingAudio)
                {
                    continue;
                }

                for (int i = 0; i < frames; i++)
                {
                    _heardSamples.Add(_block[i * 2]);
                }

                _outputSamples += frames;
                _player.GetPlaybackPosition(out int utterance, out float seconds, out _);
                if (utterance > 0 && !_heard.ContainsKey(utterance) && seconds > 0f)
                {
                    _heard[utterance] = _outputSamples / (float)rate - seconds;
                }
            }
        }

        private void WriteReport(VideoJob job, string frames)
        {
            var sb = new StringBuilder();
            sb.Append("{\"kind\":\"").Append(job.Kind).Append("\",\"width\":").Append(job.Width).Append(",\"height\":").Append(job.Height)
                .Append(",\"fps\":").Append(job.Fps).Append(",\"frames\":").Append(_frames).Append(",\"skipped\":0,\"utterances\":[");
            bool first = true;
            foreach (KeyValuePair<int, float> pair in _firstAudio)
            {
                if (!first)
                {
                    sb.Append(',');
                }

                first = false;
                sb.Append("{\"utterance_id\":").Append(pair.Key)
                    .Append(",\"first_audio_t\":").Append(pair.Value.ToString("0.0000", Inv))
                    .Append(",\"heard_t\":").Append(_heard.TryGetValue(pair.Key, out float heard) ? heard.ToString("0.0000", Inv) : "null")
                    .Append('}');
            }

            sb.Append("],\"frames_log\":[").Append(frames).Append("]}");
            File.WriteAllText(Path.Combine(job.OutputDir, "registro.json"), sb.ToString());
            if (job.IsStill)
            {
                return;
            }

            int rate = _player.OutputSampleRate > 0 ? _player.OutputSampleRate : 48000;
            WriteWav(Path.Combine(job.OutputDir, "heard.wav"), _heardSamples, rate);
        }

        // ------------------------------------------------------------------
        // Utilidades
        // ------------------------------------------------------------------

        private static bool HasArgument(string name)
        {
            return Array.IndexOf(Environment.GetCommandLineArgs(), name) >= 0;
        }

        private static float ArgFloat(string name, float fallback)
        {
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == name && float.TryParse(args[i + 1], NumberStyles.Float, Inv, out float value))
                {
                    return value;
                }
            }

            return fallback;
        }

        /// <summary>WAV PCM 16 bit (mono o el primer canal) a muestras en coma flotante.</summary>
        private static float[] ReadWav(string path)
        {
            byte[] bytes = File.ReadAllBytes(path);
            int channels = 1;
            int bits = 16;
            int pos = 12;
            while (pos + 8 <= bytes.Length)
            {
                string id = Encoding.ASCII.GetString(bytes, pos, 4);
                int size = BitConverter.ToInt32(bytes, pos + 4);
                if (id == "fmt ")
                {
                    channels = BitConverter.ToInt16(bytes, pos + 10);
                    bits = BitConverter.ToInt16(bytes, pos + 22);
                }
                else if (id == "data")
                {
                    if (bits != 16)
                    {
                        throw new InvalidDataException("La voz tiene que ser PCM de 16 bit: " + path);
                    }

                    int count = Mathf.Min(size, bytes.Length - pos - 8) / (2 * channels);
                    var samples = new float[count];
                    for (int i = 0; i < count; i++)
                    {
                        samples[i] = BitConverter.ToInt16(bytes, pos + 8 + i * 2 * channels) / 32768f;
                    }

                    return samples;
                }

                pos += 8 + size + (size & 1);
            }

            throw new InvalidDataException("WAV sin datos: " + path);
        }

        private static void WriteWav(string path, List<float> samples, int rate)
        {
            using (var stream = new FileStream(path, FileMode.Create))
            using (var writer = new BinaryWriter(stream))
            {
                int bytes = samples.Count * 2;
                writer.Write(Encoding.ASCII.GetBytes("RIFF"));
                writer.Write(36 + bytes);
                writer.Write(Encoding.ASCII.GetBytes("WAVEfmt "));
                writer.Write(16);
                writer.Write((short)1);
                writer.Write((short)1);
                writer.Write(rate);
                writer.Write(rate * 2);
                writer.Write((short)2);
                writer.Write((short)16);
                writer.Write(Encoding.ASCII.GetBytes("data"));
                writer.Write(bytes);
                foreach (float s in samples)
                {
                    writer.Write((short)Mathf.Clamp(Mathf.RoundToInt(s * 32767f), -32768, 32767));
                }
            }
        }
    }
}
