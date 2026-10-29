// Renders of the main camera at the real screen resolution.
//
// The screen is vertical 1080x1920 and editor captures come out 16:9, which is
// misleading: in 9:16 much less is visible horizontally and quite a bit more
// vertically. Anything that checks framing should be judged with this.

#if UNITY_EDITOR

using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering.Universal;
using UnityEngine.SceneManagement;

namespace Sonia.EditorTools
{
    /// <summary>Saves a 1080x1920 PNG of what the main camera sees.</summary>
    public static class SoniaCapture
    {
        /// <summary>Resolution of the vertical screen.</summary>
        public const int Width = 1080;

        public const int Height = 1920;

        /// <summary>Default folder: Temp is not committed to the repository.</summary>
        private const string DefaultFolder = "Temp";

        [MenuItem("Sonnia/Vertical 9:16 Capture")]
        public static void CaptureMenu()
        {
            string path = Capture(null);
            if (!string.IsNullOrEmpty(path))
            {
                EditorUtility.RevealInFinder(path);
            }
        }

        /// <summary>
        /// Renders the main camera at 1080x1920 and saves it as PNG. Returns the
        /// absolute path, or an empty string on failure.
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
                Debug.LogWarning("[Sonnia] There is no camera in the scene; cannot capture.");
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

            Texture2D image = Render(camera, Width, Height);
            if (image == null)
            {
                return string.Empty;
            }

            try
            {
                File.WriteAllBytes(absolute, image.EncodeToPNG());
            }
            finally
            {
                Object.DestroyImmediate(image);
            }

            Debug.Log("[Sonnia] 1080x1920 capture saved to " + absolute);
            return absolute;
        }

        /// <summary>
        /// Renders the camera with its stack of overlay cameras (the HUD) to a
        /// texture. The caller destroys the texture.
        ///
        /// Outside the player loop, <c>Camera.Render()</c> on a URP base camera
        /// does not draw the overlays of its stack, and an overlay cannot be
        /// rendered on its own. So each overlay is rendered separately, as a
        /// temporary base over a transparent background, and composited on top.
        /// </summary>
        public static Texture2D Render(Camera camera, int width, int height)
        {
            if (camera == null)
            {
                return null;
            }

            RenderTexture previousActive = RenderTexture.active;
            RenderTexture previousTarget = camera.targetTexture;
            RenderTexture target = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32);
            target.antiAliasing = 4;
            Texture2D image = new Texture2D(width, height, TextureFormat.RGBA32, false);

            try
            {
                camera.targetTexture = target;
                camera.Render();
                camera.targetTexture = previousTarget;
                RenderTexture.active = target;
                image.ReadPixels(new Rect(0f, 0f, width, height), 0, 0);
                image.Apply();
                RenderTexture.active = previousActive;

                List<Camera> overlays = OverlaysOf(camera);
                for (int i = 0; i < overlays.Count; i++)
                {
                    Texture2D layer = RenderOverlay(overlays[i], width, height);
                    if (layer == null)
                    {
                        continue;
                    }

                    Composite(image, layer);
                    Object.DestroyImmediate(layer);
                }

                return image;
            }
            catch
            {
                Object.DestroyImmediate(image);
                throw;
            }
            finally
            {
                camera.targetTexture = previousTarget;
                RenderTexture.active = previousActive;
                target.Release();
                Object.DestroyImmediate(target);
            }
        }

        private static List<Camera> OverlaysOf(Camera camera)
        {
            List<Camera> overlays = new List<Camera>();
            UniversalAdditionalCameraData data = camera.GetUniversalAdditionalCameraData();
            if (data == null || data.renderType != CameraRenderType.Base || data.cameraStack == null)
            {
                return overlays;
            }

            for (int i = 0; i < data.cameraStack.Count; i++)
            {
                Camera overlay = data.cameraStack[i];
                if (overlay != null && overlay.isActiveAndEnabled)
                {
                    overlays.Add(overlay);
                }
            }

            return overlays;
        }

        /// <summary>Renders an overlay camera on its own, over transparent.</summary>
        private static Texture2D RenderOverlay(Camera overlay, int width, int height)
        {
            UniversalAdditionalCameraData data = overlay.GetUniversalAdditionalCameraData();
            CameraRenderType savedType = data.renderType;
            CameraClearFlags savedClear = overlay.clearFlags;
            Color savedBackground = overlay.backgroundColor;
            RenderTexture savedTarget = overlay.targetTexture;
            RenderTexture layerTarget = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32);
            layerTarget.antiAliasing = 4;
            Texture2D layer = new Texture2D(width, height, TextureFormat.RGBA32, false);
            try
            {
                data.renderType = CameraRenderType.Base;
                overlay.clearFlags = CameraClearFlags.SolidColor;
                overlay.backgroundColor = new Color(0f, 0f, 0f, 0f);
                overlay.targetTexture = layerTarget;
                overlay.Render();
                RenderTexture.active = layerTarget;
                layer.ReadPixels(new Rect(0f, 0f, width, height), 0, 0);
                layer.Apply();
                return layer;
            }
            catch
            {
                Object.DestroyImmediate(layer);
                return null;
            }
            finally
            {
                RenderTexture.active = null;
                overlay.targetTexture = savedTarget;
                overlay.clearFlags = savedClear;
                overlay.backgroundColor = savedBackground;
                data.renderType = savedType;
                layerTarget.Release();
                Object.DestroyImmediate(layerTarget);
            }
        }

        /// <summary>Alpha-blends ``layer`` over ``image`` (in-place write).</summary>
        private static void Composite(Texture2D image, Texture2D layer)
        {
            Color32[] basePixels = image.GetPixels32();
            Color32[] top = layer.GetPixels32();
            int count = Mathf.Min(basePixels.Length, top.Length);
            for (int i = 0; i < count; i++)
            {
                int a = top[i].a;
                if (a == 0)
                {
                    continue;
                }

                int inv = 255 - a;
                basePixels[i] = new Color32(
                    (byte)((top[i].r * a + basePixels[i].r * inv) / 255),
                    (byte)((top[i].g * a + basePixels[i].g * inv) / 255),
                    (byte)((top[i].b * a + basePixels[i].b * inv) / 255),
                    255);
            }

            image.SetPixels32(basePixels);
            image.Apply();
        }
    }
}

#endif
