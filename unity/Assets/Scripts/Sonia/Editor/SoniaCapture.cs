// Renders de la cámara principal en la resolución real del stand.
//
// La pantalla es vertical 1080x1920 y las capturas del editor salen en 16:9, que
// engaña: en 9:16 se ve mucho menos a lo ancho y bastante más a lo alto. Todo lo
// que sea comprobar encuadre hay que mirarlo con esto.

#if UNITY_EDITOR

using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Sonia.EditorTools
{
    /// <summary>Guarda un PNG 1080x1920 de lo que ve la cámara principal.</summary>
    public static class SoniaCapture
    {
        /// <summary>Resolución de la pantalla del stand.</summary>
        public const int Width = 1080;

        public const int Height = 1920;

        /// <summary>Carpeta por defecto: Temp no se sube al repositorio.</summary>
        private const string DefaultFolder = "Temp";

        [MenuItem("Sonia/Captura vertical 9:16")]
        public static void CaptureMenu()
        {
            string path = Capture(null);
            if (!string.IsNullOrEmpty(path))
            {
                EditorUtility.RevealInFinder(path);
            }
        }

        /// <summary>
        /// Renderiza la cámara principal a 1080x1920 y lo guarda en PNG. Devuelve
        /// la ruta absoluta, o cadena vacía si no se pudo.
        /// </summary>
        public static string Capture(string relativePath)
        {
            Camera camera = Camera.main;
            if (camera == null)
            {
                Scene scene = SceneManager.GetActiveScene();
                GameObject[] roots = scene.GetRootGameObjects();
                for (int i = 0; i < roots.Length && camera == null; i++)
                {
                    camera = roots[i].GetComponentInChildren<Camera>(true);
                }
            }

            if (camera == null)
            {
                Debug.LogWarning("[Sonia] No hay cámara en la escena; no se puede capturar.");
                return string.Empty;
            }

            if (string.IsNullOrEmpty(relativePath))
            {
                relativePath = DefaultFolder + "/sonia_"
                               + System.DateTime.Now.ToString("HHmmss") + ".png";
            }

            string projectRoot = Path.GetDirectoryName(Application.dataPath);
            string absolute = Path.Combine(projectRoot, relativePath);
            string folder = Path.GetDirectoryName(absolute);
            if (!string.IsNullOrEmpty(folder) && !Directory.Exists(folder))
            {
                Directory.CreateDirectory(folder);
            }

            RenderTexture target = new RenderTexture(Width, Height, 24, RenderTextureFormat.ARGB32);
            target.antiAliasing = 4;

            RenderTexture previousActive = RenderTexture.active;
            RenderTexture previousTarget = camera.targetTexture;
            Texture2D image = new Texture2D(Width, Height, TextureFormat.RGB24, false);

            try
            {
                camera.targetTexture = target;
                camera.Render();

                RenderTexture.active = target;
                image.ReadPixels(new Rect(0f, 0f, Width, Height), 0, 0);
                image.Apply();

                File.WriteAllBytes(absolute, image.EncodeToPNG());
            }
            finally
            {
                camera.targetTexture = previousTarget;
                RenderTexture.active = previousActive;
                Object.DestroyImmediate(image);
                target.Release();
                Object.DestroyImmediate(target);
            }

            Debug.Log("[Sonia] Captura 1080x1920 guardada en " + absolute);
            return absolute;
        }
    }
}

#endif
