// Servidor HTTP del renderizador de vídeos (solo 127.0.0.1): por aquí sonnia-video pide
// el estado, el catálogo de gestos y los trabajos.
//
// HttpListener atiende en un hilo propio; cada petición se pasa al hilo principal
// (Pump, desde Update) porque solo ahí se puede tocar la escena, y el hilo del
// servidor espera la respuesta. Nada de lo que pase aquí tumba la app.

using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using UnityEngine;

namespace Sonia.Video
{
    /// <summary>Respuesta a una petición: código HTTP y cuerpo JSON.</summary>
    public struct HttpReply
    {
        public int Status;
        public string Json;

        public HttpReply(int status, string json)
        {
            Status = status;
            Json = json;
        }
    }

    /// <summary>Servidor HTTP mínimo que despacha las peticiones en el hilo principal.</summary>
    public sealed class VideoHttpServer : IDisposable
    {
        private sealed class Pending
        {
            public string Method;
            public string Path;
            public string Body;
            public HttpReply Reply;
            public readonly ManualResetEventSlim Done = new ManualResetEventSlim(false);
        }

        private const int ReplyTimeoutMs = 30000;

        private readonly HttpListener _listener = new HttpListener();
        private readonly ConcurrentQueue<Pending> _queue = new ConcurrentQueue<Pending>();
        private readonly Func<string, string, string, HttpReply> _handler;
        private Thread _thread;
        private volatile bool _stopping;

        /// <param name="handler">(método, ruta, cuerpo) → respuesta; corre en el hilo principal.</param>
        public VideoHttpServer(int port, Func<string, string, string, HttpReply> handler)
        {
            Port = port;
            _handler = handler;
            _listener.Prefixes.Add("http://127.0.0.1:" + port + "/");
        }

        public int Port { get; }

        /// <summary>Empieza a escuchar. Falso si el puerto no se pudo abrir.</summary>
        public bool Start()
        {
            try
            {
                _listener.Start();
            }
            catch (Exception ex)
            {
                Debug.LogError("[Vídeo] No se pudo abrir el puerto " + Port + ": " + ex.Message);
                return false;
            }

            _thread = new Thread(Loop) { IsBackground = true, Name = "SonniaVideoHttp" };
            _thread.Start();
            return true;
        }

        /// <summary>Atiende las peticiones pendientes. Hilo principal.</summary>
        public void Pump()
        {
            while (_queue.TryDequeue(out Pending pending))
            {
                try
                {
                    pending.Reply = _handler(pending.Method, pending.Path, pending.Body);
                }
                catch (Exception ex)
                {
                    Debug.LogException(ex);
                    pending.Reply = new HttpReply(500, Error(ex.Message));
                }
                finally
                {
                    pending.Done.Set();
                }
            }
        }

        /// <summary>{"ok":false,"error":...}</summary>
        public static string Error(string message)
        {
            return "{\"ok\":false,\"error\":" + Newtonsoft.Json.JsonConvert.ToString(message ?? "error") + "}";
        }

        private void Loop()
        {
            while (!_stopping)
            {
                HttpListenerContext context;
                try
                {
                    context = _listener.GetContext();
                }
                catch (Exception)
                {
                    if (_stopping)
                    {
                        return;
                    }

                    Thread.Sleep(50);
                    continue;
                }

                ThreadPool.QueueUserWorkItem(_ => Serve(context));
            }
        }

        private void Serve(HttpListenerContext context)
        {
            HttpReply reply;
            try
            {
                string body = string.Empty;
                if (context.Request.HasEntityBody)
                {
                    using (var reader = new StreamReader(context.Request.InputStream, Encoding.UTF8))
                    {
                        body = reader.ReadToEnd();
                    }
                }

                var pending = new Pending
                {
                    Method = context.Request.HttpMethod,
                    Path = context.Request.Url.AbsolutePath.TrimEnd('/'),
                    Body = body
                };
                _queue.Enqueue(pending);
                reply = pending.Done.Wait(ReplyTimeoutMs)
                    ? pending.Reply
                    : new HttpReply(503, Error("la app no contesta (¿ocupada cargando?)"));
            }
            catch (Exception ex)
            {
                reply = new HttpReply(500, Error(ex.Message));
            }

            try
            {
                byte[] bytes = Encoding.UTF8.GetBytes(reply.Json ?? "{}");
                context.Response.StatusCode = reply.Status;
                context.Response.ContentType = "application/json; charset=utf-8";
                context.Response.ContentLength64 = bytes.Length;
                context.Response.OutputStream.Write(bytes, 0, bytes.Length);
                context.Response.OutputStream.Close();
            }
            catch (Exception)
            {
                // El cliente se fue: no pasa nada.
            }
        }

        public void Dispose()
        {
            _stopping = true;
            try
            {
                _listener.Stop();
                _listener.Close();
            }
            catch (Exception)
            {
                // Al salir da igual.
            }
        }
    }
}
