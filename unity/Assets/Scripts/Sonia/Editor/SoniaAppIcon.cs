// Icono de la app: la cara de Sonia con los colores de la marca, recortada con la
// forma de los iconos de macOS (Sonia > Icono de la app (en Play)).
//
// El avatar de Genies solo existe en Play, así que el icono se saca con el avatar
// ya puesto. Una cámara temporal enfoca la cabeza con el hueso Head del Humanoid
// (los bounds de los renderers no sirven para encuadrar) y ve solo al avatar, que
// pasa un momento a una capa libre. Se renderiza sin posprocesado dos veces, sobre
// negro y sobre blanco: la diferencia da la transparencia de verdad (el alfa del
// render no vale: las capas transparentes de cejas y maquillaje lo rebajan sobre
// la piel y el fondo se colaba). Se compone sobre el navy de la marca con un brillo azul detrás
// de la cabeza, dentro de una «squircle» de 824 px en un lienzo de 1024 con margen
// transparente y sombra suave (la plantilla de iconos de macOS). Queda en
// Assets/UI/SoniaAppIcon.png como icono por defecto del Player, el que usan las
// apps de macOS y Windows; eso se hace al salir de Play, porque lo que se cambia
// del Player en Play se pierde. Si cambia el avatar de Sonia, se vuelve a sacar.

#if UNITY_EDITOR

using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.Build;
using UnityEngine;
using UnityEngine.Rendering.Universal;

namespace Sonia.EditorTools
{
    /// <summary>Saca el icono de la app con la cara de Sonia y lo pone en el Player.</summary>
    public static class SoniaAppIcon
    {
        public const string IconPath = "Assets/UI/SoniaAppIcon.png";

        private const int CanvasSize = 1024;
        private const int BodySize = 824;
        private const int Supersample = 2;

        /// <summary>Exponente de la superelipse: la esquina continua de los iconos de Apple.</summary>
        private const float Squareness = 5f;

        /// <summary>Capa sin usar donde se aísla el avatar mientras se renderiza.</summary>
        private const int FreeLayer = 31;

        private const float ShadowOffset = 10f;
        private const float ShadowSoftness = 22f;
        private const float ShadowOpacity = 0.35f;

        // Colores de la marca (StageScreen).
        private static readonly Color Navy = new Color32(20, 39, 82, 255);
        private static readonly Color Brand = new Color32(3, 113, 245, 255);

        [MenuItem("Sonia/Icono de la app (en Play)")]
        public static void MakeMenu()
        {
            string path = Make();
            if (!string.IsNullOrEmpty(path))
            {
                EditorUtility.RevealInFinder(path);
            }
        }

        /// <summary>
        /// Renderiza, compone, guarda y pone el icono. <paramref name="faceHeight"/>:
        /// metros sobre el hueso Head del centro del encuadre; <paramref name="frameHeight"/>:
        /// alto en metros de lo que se ve a esa distancia. Devuelve la ruta absoluta o
        /// cadena vacía si no se pudo.
        /// </summary>
        public static string Make(float faceHeight = 0.08f, float frameHeight = 0.5f, float fieldOfView = 16f)
        {
            if (!EditorApplication.isPlaying)
            {
                Debug.LogWarning("[Sonia] El icono se saca en Play, con el avatar de Genies puesto.");
                return string.Empty;
            }

            GameObject sonia = GameObject.Find("Sonia");
            AvatarBinder binder = sonia != null ? sonia.GetComponentInChildren<AvatarBinder>(true) : null;
            Transform avatar = binder != null ? binder.Current : null;
            Animator animator = avatar != null ? avatar.GetComponentInChildren<Animator>() : null;
            Transform head = animator != null && animator.isHuman ? animator.GetBoneTransform(HumanBodyBones.Head) : null;
            if (head == null)
            {
                Debug.LogWarning("[Sonia] Sin avatar humanoide en Sonia: espera a que cargue el de Genies.");
                return string.Empty;
            }

            Texture2D icon;
            Texture2D onBlack = null;
            Texture2D onWhite = null;
            try
            {
                RenderHead(avatar, head, faceHeight, frameHeight, fieldOfView, out onBlack, out onWhite);
                if (onBlack == null || onWhite == null)
                {
                    return string.Empty;
                }

                icon = Compose(onBlack, onWhite);
            }
            finally
            {
                if (onBlack != null)
                {
                    Object.DestroyImmediate(onBlack);
                }

                if (onWhite != null)
                {
                    Object.DestroyImmediate(onWhite);
                }
            }

            string absolute = Path.Combine(Path.GetDirectoryName(Application.dataPath), IconPath);
            File.WriteAllBytes(absolute, icon.EncodeToPNG());
            Object.DestroyImmediate(icon);

            EditorApplication.playModeStateChanged -= InstallWhenEditing;
            EditorApplication.playModeStateChanged += InstallWhenEditing;
            Debug.Log("[Sonia] Icono de la app guardado en " + IconPath + "; se pone en el Player al salir de Play.");
            return absolute;
        }

        private static void InstallWhenEditing(PlayModeStateChange state)
        {
            if (state != PlayModeStateChange.EnteredEditMode)
            {
                return;
            }

            EditorApplication.playModeStateChanged -= InstallWhenEditing;
            Install();
            Debug.Log("[Sonia] Icono de la app puesto en el Player.");
        }

        /// <summary>Cabeza de frente, solo el avatar, sobre negro y sobre blanco (cuadrados de BodySize × Supersample).</summary>
        private static void RenderHead(Transform avatar, Transform head, float faceHeight, float frameHeight,
                                       float fieldOfView, out Texture2D onBlack, out Texture2D onWhite)
        {
            var layers = new List<KeyValuePair<GameObject, int>>();
            foreach (Transform part in avatar.GetComponentsInChildren<Transform>(true))
            {
                layers.Add(new KeyValuePair<GameObject, int>(part.gameObject, part.gameObject.layer));
                part.gameObject.layer = FreeLayer;
            }

            GameObject holder = new GameObject("Icono (temporal)");
            try
            {
                Camera camera = holder.AddComponent<Camera>();
                camera.clearFlags = CameraClearFlags.SolidColor;
                camera.cullingMask = 1 << FreeLayer;
                camera.fieldOfView = fieldOfView;
                camera.nearClipPlane = 0.05f;
                camera.farClipPlane = 20f;
                camera.allowHDR = false;
                UniversalAdditionalCameraData data = holder.AddComponent<UniversalAdditionalCameraData>();
                data.renderPostProcessing = false;

                Vector3 target = head.position + avatar.up * faceHeight;
                float distance = frameHeight * 0.5f / Mathf.Tan(fieldOfView * 0.5f * Mathf.Deg2Rad);
                holder.transform.position = target + avatar.forward * distance;
                holder.transform.rotation = Quaternion.LookRotation(-avatar.forward, avatar.up);
                int size = BodySize * Supersample;
                camera.backgroundColor = Color.black;
                onBlack = SoniaCapture.Render(camera, size, size);
                camera.backgroundColor = Color.white;
                onWhite = SoniaCapture.Render(camera, size, size);
            }
            finally
            {
                Object.DestroyImmediate(holder);
                foreach (KeyValuePair<GameObject, int> entry in layers)
                {
                    if (entry.Key != null)
                    {
                        entry.Key.layer = entry.Value;
                    }
                }
            }
        }

        /// <summary>Fondo de la marca, avatar encima, squircle y sombra en el lienzo de 1024.</summary>
        private static Texture2D Compose(Texture2D onBlack, Texture2D onWhite)
        {
            Color[] black = onBlack.GetPixels();
            Color[] white = onWhite.GetPixels();
            int sourceSize = onBlack.width;
            Color[] body = new Color[BodySize * BodySize];
            Vector2 glowCenter = new Vector2(BodySize * 0.5f, BodySize * 0.58f);
            float glowRadius = BodySize * 0.62f;
            for (int y = 0; y < BodySize; y++)
            {
                for (int x = 0; x < BodySize; x++)
                {
                    // Media de los Supersample² píxeles. Sobre negro, el render ya es el
                    // color premultiplicado; lo que cambia entre negro y blanco es el
                    // fondo que deja ver, así que la cobertura es 1 menos esa diferencia.
                    Color sum = Color.clear;
                    for (int sy = 0; sy < Supersample; sy++)
                    {
                        for (int sx = 0; sx < Supersample; sx++)
                        {
                            int i = (y * Supersample + sy) * sourceSize + x * Supersample + sx;
                            Color b = black[i];
                            Color w = white[i];
                            float seen = ((w.r - b.r) + (w.g - b.g) + (w.b - b.b)) / 3f;
                            sum += new Color(b.r, b.g, b.b, Mathf.Clamp01(1f - seen));
                        }
                    }

                    sum /= Supersample * Supersample;
                    float glow = 1f - Mathf.Clamp01(Vector2.Distance(new Vector2(x, y), glowCenter) / glowRadius);
                    Color background = Color.Lerp(Navy, Brand, 0.55f * glow * glow * (3f - 2f * glow));
                    body[y * BodySize + x] = new Color(
                        sum.r + background.r * (1f - sum.a),
                        sum.g + background.g * (1f - sum.a),
                        sum.b + background.b * (1f - sum.a),
                        1f);
                }
            }

            Color[] canvas = new Color[CanvasSize * CanvasSize];
            float half = BodySize * 0.5f;
            float center = CanvasSize * 0.5f;
            int margin = (CanvasSize - BodySize) / 2;
            for (int y = 0; y < CanvasSize; y++)
            {
                for (int x = 0; x < CanvasSize; x++)
                {
                    float inside = InsideDistance(x + 0.5f - center, y + 0.5f - center, half);
                    float coverage = Mathf.Clamp01(inside + 0.5f);
                    // La sombra cae hacia abajo (en la textura, y crece hacia arriba).
                    float shadowInside = InsideDistance(x + 0.5f - center, y + 0.5f - center + ShadowOffset, half);
                    float shadow = ShadowOpacity * Mathf.SmoothStep(0f, 1f, (shadowInside + ShadowSoftness) / (2f * ShadowSoftness));
                    float alpha = coverage + shadow * (1f - coverage);
                    if (alpha <= 0f)
                    {
                        canvas[y * CanvasSize + x] = Color.clear;
                        continue;
                    }

                    int bx = Mathf.Clamp(x - margin, 0, BodySize - 1);
                    int by = Mathf.Clamp(y - margin, 0, BodySize - 1);
                    Color c = body[by * BodySize + bx];
                    canvas[y * CanvasSize + x] = new Color(c.r * coverage / alpha, c.g * coverage / alpha,
                                                           c.b * coverage / alpha, alpha);
                }
            }

            Texture2D icon = new Texture2D(CanvasSize, CanvasSize, TextureFormat.RGBA32, false);
            icon.SetPixels(canvas);
            icon.Apply();
            return icon;
        }

        /// <summary>Píxeles hacia dentro del borde de la squircle (negativo fuera).</summary>
        private static float InsideDistance(float dx, float dy, float half)
        {
            float u = Mathf.Abs(dx) / half;
            float v = Mathf.Abs(dy) / half;
            float radius = Mathf.Pow(Mathf.Pow(u, Squareness) + Mathf.Pow(v, Squareness), 1f / Squareness);
            return (1f - radius) * half;
        }

        /// <summary>Ajustes de importación del PNG y icono por defecto del Player.</summary>
        private static void Install()
        {
            AssetDatabase.ImportAsset(IconPath, ImportAssetOptions.ForceSynchronousImport);
            TextureImporter importer = (TextureImporter)AssetImporter.GetAtPath(IconPath);
            importer.textureType = TextureImporterType.Default;
            importer.alphaIsTransparency = true;
            importer.mipmapEnabled = false;
            importer.npotScale = TextureImporterNPOTScale.None;
            importer.textureCompression = TextureImporterCompression.Uncompressed;
            importer.maxTextureSize = CanvasSize;
            importer.SaveAndReimport();

            Texture2D texture = AssetDatabase.LoadAssetAtPath<Texture2D>(IconPath);
            PlayerSettings.SetIcons(NamedBuildTarget.Unknown, new[] { texture }, IconKind.Any);
            AssetDatabase.SaveAssets();
        }
    }
}

#endif
