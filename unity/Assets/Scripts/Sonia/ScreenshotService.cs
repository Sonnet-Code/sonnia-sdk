// Screenshots of the built app, to verify it without the editor.
//
// Enabled only from the command line:
//
//   Sonnia.app/Contents/MacOS/Sonnia -capture-dir /path -capture-every 5
//
// Saves a numbered PNG in the folder every N seconds (default 5). Without
// -capture-dir it does nothing, so it costs no frame time in normal use.

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

        /// <summary>Creates the service if the command line asks for it.</summary>
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
            Debug.Log("[Sonnia] Screenshots every " + every + " s in " + dir);
        }

        private void Update()
        {
            if (Time.unscaledTime < _next)
            {
                return;
            }
            _next = Time.unscaledTime + _every;
            string path = Path.Combine(_directory, "capture-" + _index.ToString("D3") + ".png");
            _index++;
            ScreenCapture.CaptureScreenshot(path);
        }
    }
}
