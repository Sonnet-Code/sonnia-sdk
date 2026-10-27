// Cuadros del renderizador de vídeos: la cámara principal (con su pila, el HUD)
// pinta a una RenderTexture N veces más grande que el vídeo; cada subfotograma
// expuesto se reduce con un promedio de caja y se suma a un acumulador (desenfoque
// de movimiento con obturador); al cerrar el cuadro se lee de la GPU y se le pasa a
// ffmpeg por stdin (vídeo sin audio) o se guarda en PNG (vista previa).
//
// Todo en la GPU salvo la lectura final: a 1080x1920 con supermuestreo 2 el CPU de
// Mono tardaba cientos de milisegundos por cuadro en hacer lo mismo.

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using UnityEngine;
using UnityEngine.Rendering;
using Debug = UnityEngine.Debug;

namespace Sonia.Video
{
    /// <summary>Acumula, lee y entrega los cuadros de un trabajo.</summary>
    public sealed class VideoFrameRecorder : IDisposable
    {
        private const string ShaderName = "Hidden/Sonia/VideoResolve";
        private const int QueuedFrames = 6;

        private readonly int _width;
        private readonly int _height;
        private readonly int _scale;
        private readonly Material _material;
        private readonly RenderTexture _accum;
        private readonly RenderTexture _output;
        private readonly bool _transparent;
        private RenderTexture _black;
        private RenderTexture _bgBlack;
        private RenderTexture _bgWhite;
        private Texture _background;
        private Vector4 _backgroundST = new Vector4(1f, 1f, 0f, 0f);
        private int _exposures;

        private Process _ffmpeg;
        private Thread _writer;
        private BlockingCollection<byte[]> _frames;
        private readonly Queue<string> _ffmpegLog = new Queue<string>();
        private volatile string _writeError;

        /// <param name="transparent">
        /// Fondo transparente: cada exposición se pinta dos veces, sobre negro y sobre blanco, y
        /// el alfa sale de la diferencia (ver el shader). La cámara solo ve a Sonnia.
        /// </param>
        public VideoFrameRecorder(int width, int height, int supersample, bool transparent = false)
        {
            _width = width;
            _height = height;
            _transparent = transparent;
            _scale = Mathf.Clamp(supersample, 1, 3);
            Shader shader = Shader.Find(ShaderName);
            if (shader == null)
            {
                throw new InvalidOperationException("Falta el shader " + ShaderName + " en la build.");
            }

            _material = new Material(shader) { hideFlags = HideFlags.HideAndDontSave };
            Target = new RenderTexture(new RenderTextureDescriptor(width * _scale, height * _scale, RenderTextureFormat.ARGB32, 24)
            {
                sRGB = true,
                msaaSamples = 1
            }) { name = "SonniaVideoRender" };
            Target.Create();
            _accum = new RenderTexture(new RenderTextureDescriptor(width, height, RenderTextureFormat.ARGBHalf, 0)
            {
                sRGB = false
            }) { name = "SonniaVideoAccum" };
            _accum.Create();
            _output = new RenderTexture(new RenderTextureDescriptor(width, height, RenderTextureFormat.ARGB32, 0)
            {
                sRGB = true
            }) { name = "SonniaVideoFrame" };
            _output.Create();
            if (transparent)
            {
                _black = NewLike(Target, "SonniaVideoNegro");
                _bgBlack = NewLike(Target, "SonniaVideoFondoNegro");
                _bgWhite = NewLike(Target, "SonniaVideoFondoBlanco");
            }
        }

        private static RenderTexture NewLike(RenderTexture source, string name)
        {
            var texture = new RenderTexture(new RenderTextureDescriptor(source.width, source.height, RenderTextureFormat.ARGB32, 0)
            {
                sRGB = true
            }) { name = name };
            texture.Create();
            return texture;
        }

        /// <summary>
        /// Fondo transparente: pinta el fondo vacío (sin nada en la máscara) sobre negro y sobre
        /// blanco, una vez por trabajo; la viñeta y el tonemapping cambian el blanco de cada píxel.
        /// </summary>
        public void Calibrate(Camera camera)
        {
            if (!_transparent)
            {
                return;
            }

            int mask = camera.cullingMask;
            camera.cullingMask = 0;
            camera.backgroundColor = Color.black;
            Render(camera);
            Graphics.Blit(Target, _bgBlack);
            camera.backgroundColor = Color.white;
            Render(camera);
            Graphics.Blit(Target, _bgWhite);
            camera.cullingMask = mask;
        }

        /// <summary>
        /// Fondo con sus colores exactos detrás de Sonnia aislada (con <c>transparent</c>): el
        /// cuadro sale opaco. <paramref name="st"/> = escala y desplazamiento de sus UV (recorte).
        /// </summary>
        public void SetBackground(Texture texture, Vector4 st)
        {
            _background = texture;
            _backgroundST = st;
        }

        /// <summary>Donde pinta la cámara principal mientras dura el trabajo.</summary>
        public RenderTexture Target { get; }

        /// <summary>Último cuadro cerrado (para la ventana de la app).</summary>
        public RenderTexture Preview
        {
            get { return _output; }
        }

        /// <summary>Últimas líneas de ffmpeg (para los errores).</summary>
        public string FfmpegLog
        {
            get
            {
                lock (_ffmpegLog)
                {
                    return string.Join("\n", _ffmpegLog);
                }
            }
        }

        /// <summary>Lanza ffmpeg: <c>-f rawvideo -pix_fmt rgba -s WxH -r fps -i - args path</c>.</summary>
        public void StartEncoder(VideoEncoder encoder, int fps)
        {
            var args = new List<string>
            {
                "-hide_banner", "-loglevel", "error", "-y",
                "-f", "rawvideo", "-pix_fmt", "rgba", "-s", _width + "x" + _height, "-r", fps.ToString(),
                "-i", "-"
            };
            if (encoder.Args != null)
            {
                args.AddRange(encoder.Args);
            }

            args.Add(encoder.Path);
            var info = new ProcessStartInfo(encoder.Ffmpeg, string.Join(" ", args.ConvertAll(Quote)))
            {
                UseShellExecute = false,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };
            _ffmpeg = new Process { StartInfo = info, EnableRaisingEvents = true };
            _ffmpeg.ErrorDataReceived += (_, e) => Remember(e.Data);
            _ffmpeg.OutputDataReceived += (_, e) => Remember(e.Data);
            _ffmpeg.Start();
            _ffmpeg.BeginErrorReadLine();
            _ffmpeg.BeginOutputReadLine();
            _frames = new BlockingCollection<byte[]>(QueuedFrames);
            _writer = new Thread(WriteLoop) { IsBackground = true, Name = "SonniaVideoFfmpeg" };
            _writer.Start();
            Debug.Log("[Vídeo] ffmpeg: " + info.FileName + " " + info.Arguments);
        }

        /// <summary>
        /// Pinta la cámara (con las superpuestas de su pila: el HUD) en <see cref="Target"/>.
        /// A mano y no en el bucle de juego: en modo batch (sin ventana) Unity no pinta las
        /// cámaras solo, y así se pinta una vez por subfotograma también con ventana (la
        /// cámara principal está apagada mientras dura el trabajo).
        /// </summary>
        public void Render(Camera camera)
        {
            camera.targetTexture = Target;
            var request = new RenderPipeline.StandardRequest { destination = Target };
            if (RenderPipeline.SupportsRenderRequest(camera, request))
            {
                RenderPipeline.SubmitRenderRequest(camera, request);
            }
            else
            {
                camera.Render();
            }
        }

        /// <summary>Empieza un cuadro nuevo: acumulador a cero.</summary>
        public void BeginFrame()
        {
            RenderTexture previous = RenderTexture.active;
            RenderTexture.active = _accum;
            GL.Clear(false, true, Color.clear);
            RenderTexture.active = previous;
            _exposures = 0;
        }

        /// <summary>
        /// Pinta este subfotograma y lo suma al cuadro (peso 1/<paramref name="exposures"/>). Con
        /// fondo transparente lo pinta sobre negro y sobre blanco y suma color premultiplicado y alfa.
        /// </summary>
        public void Expose(Camera camera, int exposures)
        {
            _material.SetFloat("_Scale", _scale);
            _material.SetFloat("_Weight", 1f / Mathf.Max(1, exposures));
            if (!_transparent)
            {
                Render(camera);
                Graphics.Blit(Target, _accum, _material, 0);
            }
            else
            {
                camera.backgroundColor = Color.black;
                Render(camera);
                Graphics.Blit(Target, _black);
                camera.backgroundColor = Color.white;
                Render(camera);
                _material.SetTexture("_BlackTex", _black);
                _material.SetTexture("_BgBlack", _bgBlack);
                _material.SetTexture("_BgWhite", _bgWhite);
                Graphics.Blit(Target, _accum, _material, 2);
            }

            _exposures++;
        }

        /// <summary>Cierra el cuadro: lo copia a la salida y lo lee de la GPU (filas de arriba abajo si <paramref name="topDown"/>).</summary>
        public byte[] ReadFrame(bool topDown)
        {
            _material.SetFloat("_FlipY", topDown ? 1f : 0f);
            _material.SetFloat("_Transparent", _transparent ? 1f : 0f);
            _material.SetFloat("_HasBackground", _transparent && _background != null ? 1f : 0f);
            if (_background != null)
            {
                _material.SetTexture("_Background", _background);
                _material.SetVector("_BgST", _backgroundST);
            }

            Graphics.Blit(_accum, _output, _material, 1);
            AsyncGPUReadbackRequest request = AsyncGPUReadback.Request(_output, 0, TextureFormat.RGBA32);
            request.WaitForCompletion();
            if (request.hasError)
            {
                throw new InvalidOperationException("No se pudo leer el cuadro de la GPU.");
            }

            return request.GetData<byte>().ToArray();
        }

        /// <summary>Manda un cuadro a ffmpeg (espera si lleva varios por delante).</summary>
        public void Encode(byte[] frame)
        {
            if (_writeError != null)
            {
                throw new IOException("ffmpeg dejó de aceptar cuadros: " + _writeError + "\n" + FfmpegLog);
            }

            if (_ffmpeg != null && _ffmpeg.HasExited)
            {
                throw new IOException("ffmpeg terminó antes de tiempo (" + _ffmpeg.ExitCode + "):\n" + FfmpegLog);
            }

            _frames.Add(frame);
        }

        /// <summary>Guarda el último cuadro leído (filas de abajo arriba) en PNG.</summary>
        public void SavePng(byte[] frame, string path)
        {
            byte[] png = ImageConversion.EncodeArrayToPNG(frame, UnityEngine.Experimental.Rendering.GraphicsFormat.R8G8B8A8_SRGB,
                (uint)_width, (uint)_height);
            Directory.CreateDirectory(Path.GetDirectoryName(path) ?? ".");
            File.WriteAllBytes(path, png);
        }

        /// <summary>Deja de mandar cuadros. Hay que esperar a <see cref="EncoderFinished"/>.</summary>
        public void CloseEncoder()
        {
            _frames?.CompleteAdding();
        }

        /// <summary>Cierto cuando ffmpeg ya terminó (o no había).</summary>
        public bool EncoderFinished
        {
            get
            {
                if (_ffmpeg == null)
                {
                    return true;
                }

                return (_writer == null || !_writer.IsAlive) && _ffmpeg.HasExited;
            }
        }

        /// <summary>Código de salida de ffmpeg (0 si no había).</summary>
        public int EncoderExitCode
        {
            get { return _ffmpeg != null && _ffmpeg.HasExited ? _ffmpeg.ExitCode : 0; }
        }

        private void WriteLoop()
        {
            Stream stdin = _ffmpeg.StandardInput.BaseStream;
            try
            {
                foreach (byte[] frame in _frames.GetConsumingEnumerable())
                {
                    stdin.Write(frame, 0, frame.Length);
                }

                stdin.Flush();
            }
            catch (Exception ex)
            {
                _writeError = ex.Message;
                // Si ffmpeg murió, que nadie se quede esperando hueco en la cola.
                while (_frames.TryTake(out _))
                {
                }
            }
            finally
            {
                try
                {
                    stdin.Close();
                }
                catch (Exception)
                {
                    // Ya estaba cerrado.
                }
            }
        }

        private void Remember(string line)
        {
            if (string.IsNullOrEmpty(line))
            {
                return;
            }

            lock (_ffmpegLog)
            {
                _ffmpegLog.Enqueue(line);
                while (_ffmpegLog.Count > 30)
                {
                    _ffmpegLog.Dequeue();
                }
            }
        }

        private static string Quote(string arg)
        {
            if (arg.Length > 0 && arg.IndexOfAny(new[] { ' ', '\t', '"', '\'' }) < 0)
            {
                return arg;
            }

            return "\"" + arg.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
        }

        /// <summary>Corta ffmpeg si sigue vivo (trabajo cancelado o fallido).</summary>
        public void Abort()
        {
            try
            {
                _frames?.CompleteAdding();
                if (_ffmpeg != null && !_ffmpeg.HasExited)
                {
                    _ffmpeg.Kill();
                }
            }
            catch (Exception)
            {
                // Ya había terminado.
            }
        }

        public void Dispose()
        {
            Abort();
            Target.Release();
            UnityEngine.Object.Destroy(Target);
            _accum.Release();
            UnityEngine.Object.Destroy(_accum);
            _output.Release();
            UnityEngine.Object.Destroy(_output);
            foreach (RenderTexture extra in new[] { _black, _bgBlack, _bgWhite })
            {
                if (extra != null)
                {
                    extra.Release();
                    UnityEngine.Object.Destroy(extra);
                }
            }

            UnityEngine.Object.Destroy(_material);
            _ffmpeg?.Dispose();
        }

        /// <summary>Describe el acumulador (para el registro).</summary>
        public override string ToString()
        {
            var sb = new StringBuilder();
            sb.Append(_width).Append('x').Append(_height).Append(" ×").Append(_scale);
            return sb.ToString();
        }
    }
}
