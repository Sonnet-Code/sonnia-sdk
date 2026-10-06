// Capturas de pantalla de la app compilada, para verificarla sin editor.
//
// Se activa solo por línea de comandos:
//
//   Sonnia.app/Contents/MacOS/Sonnia -capture-dir /ruta -capture-every 5
//
// Guarda un PNG numerado en la carpeta cada N segundos (por defecto 5). Sin
// -capture-dir no hace nada, así que en el stand no cuesta ni un frame.

using System;
using System.Globalization;
using System.IO;
using UnityEngine;

namespace Sonia
{
    public sealed class ScreenshotService : MonoBehaviour
    {
        private string _directory;
        private float _every = 5f;
        private float _next;
        private int _index;

        /// <summary>Crea el servicio si la línea de comandos lo pide.</summary>
        public static void InstallFromCommandLine(GameObject host)
        {
            string[] args = Environment.GetCommandLineArgs();
            string dir = null;
            float every = 5f;
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == "-capture-dir")
                {
                    dir = args[i + 1];
                }
                else if (args[i] == "-capture-every"
                    && float.TryParse(args[i + 1], NumberStyles.Float, CultureInfo.InvariantCulture, out float seconds)
                    && seconds > 0f)
                {
                    every = seconds;
                }
            }
            if (string.IsNullOrEmpty(dir))
            {
                return;
            }
            ScreenshotService service = host.AddComponent<ScreenshotService>();
            service._directory = dir;
            service._every = every;
            Directory.CreateDirectory(dir);
            Debug.Log("[Sonia] Capturas cada " + every + " s en " + dir);
        }

        private void Update()
        {
            if (Time.unscaledTime < _next)
            {
                return;
            }
            _next = Time.unscaledTime + _every;
            string path = Path.Combine(_directory, "captura-" + _index.ToString("D3") + ".png");
            _index++;
            ScreenCapture.CaptureScreenshot(path);
        }
    }
}
