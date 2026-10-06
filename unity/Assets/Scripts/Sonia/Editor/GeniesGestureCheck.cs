// Hojas de contactos de los gestos de Genies sobre el avatar vivo (en Play).
//
// Para revisar a ojo los gestos del set (manos que atraviesan el cuerpo o la
// camiseta, dedos raros, giros imposibles): cada fila es un gesto y cada
// columna un instante (por defecto al 20, 40, 60 y 80 % del clip), con una
// cámara propia que encuadra torso y brazos de frente. La pose se pone con
// GeniesGestureLayer.ApplyPose, sin reproducir el clip, así que salen todos en
// segundos. Las imágenes van a Temp/gestos-genies/ con un .txt que dice qué
// gesto es cada fila.
//
// Uso: Play, esperar al avatar de Genies y Sonia > Gestos de Genies > Hojas de
// contactos (en Play). Desde código: GeniesGestureCheck.RenderSheets(...).

using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Comprobación visual de los gestos de Genies.</summary>
    public static class GeniesGestureCheck
    {
        private const string OutputFolder = "Temp/gestos-genies";

        [MenuItem("Sonia/Gestos de Genies/Hojas de contactos (en Play)")]
        public static void RenderAllMenu()
        {
            string log = RenderSheets(null, new[] { 0.2f, 0.4f, 0.6f, 0.8f }, 8, OutputFolder, 270, 360);
            Debug.Log("[Sonia] " + log);
        }

        [MenuItem("Sonia/Gestos de Genies/Hojas de contactos de cuerpo entero (en Play)")]
        public static void RenderAllFullBodyMenu()
        {
            string log = RenderSheets(null, new[] { 0.2f, 0.4f, 0.6f, 0.8f }, 8, OutputFolder + "-cuerpo", 200, 400, true);
            Debug.Log("[Sonia] " + log);
        }

        /// <summary>
        /// Hojas de <paramref name="rowsPerSheet"/> gestos por imagen. Con
        /// <paramref name="gestures"/> null, todos los del set. Devuelve un resumen.
        /// </summary>
        public static string RenderSheets(string[] gestures, float[] fractions, int rowsPerSheet, string folder, int frameWidth, int frameHeight, bool fullBody = false)
        {
            if (!Application.isPlaying)
            {
                return "hace falta Play con el avatar de Genies cargado";
            }

            GeniesGestureLayer layer = FindLayer();
            if (layer == null || !layer.IsReady)
            {
                return "sin GeniesGestureLayer lista (¿avatar cargado?)";
            }

            List<string> names = new List<string>();
            if (gestures != null)
            {
                names.AddRange(gestures);
            }
            else
            {
                foreach (GeniesGestureSet.Gesture g in layer.Set.gestures)
                {
                    if (g != null && g.clip != null)
                    {
                        names.Add(g.name);
                    }
                }
            }

            Animator animator = layer.GetComponent<MotionPlayer>() != null ? layer.GetComponent<MotionPlayer>().Animator : null;
            if (animator == null)
            {
                return "sin Animator";
            }

            Directory.CreateDirectory(folder);
            Camera camera = MakeCamera(animator, fullBody);
            SkinnedMeshRenderer[] skins = animator.GetComponentsInChildren<SkinnedMeshRenderer>();
            bool[] force = new bool[skins.Length];
            for (int i = 0; i < skins.Length; i++)
            {
                force[i] = skins[i].forceMatrixRecalculationPerRender;
                skins[i].forceMatrixRecalculationPerRender = true;
            }

            // Pose de partida (la del Animator) para devolverla al acabar.
            List<KeyValuePair<Transform, Quaternion>> saved = new List<KeyValuePair<Transform, Quaternion>>();
            Transform hips = FindDeep(animator.transform, "Hips");
            Vector3 hipsPosition = hips != null ? hips.localPosition : Vector3.zero;
            List<string> boneNames = new List<string>(GeniesGestureLayer.LowerBoneNames);
            boneNames.AddRange(GeniesGestureLayer.BoneNames);
            foreach (string boneName in boneNames)
            {
                Transform t = FindDeep(animator.transform, boneName);
                if (t != null)
                {
                    saved.Add(new KeyValuePair<Transform, Quaternion>(t, t.localRotation));
                }
            }

            StringBuilder index = new StringBuilder();
            int sheets = 0;
            try
            {
                for (int start = 0; start < names.Count; start += rowsPerSheet)
                {
                    int rows = Mathf.Min(rowsPerSheet, names.Count - start);
                    Texture2D sheet = new Texture2D(frameWidth * fractions.Length, frameHeight * rows, TextureFormat.RGB24, false);
                    string file = Path.Combine(folder, "hoja-" + (sheets + 1).ToString("00") + ".png");
                    index.AppendLine(Path.GetFileName(file));
                    for (int r = 0; r < rows; r++)
                    {
                        string gesture = names[start + r];
                        float duration = layer.DurationOf(gesture);
                        index.AppendLine("  fila " + (r + 1) + ": " + gesture + " (" + duration.ToString("0.0") + " s)");
                        for (int c = 0; c < fractions.Length; c++)
                        {
                            layer.ApplyPose(gesture, fractions[c] * duration, fullBody);
                            Texture2D frame = SoniaCapture.Render(camera, frameWidth, frameHeight);
                            // Las filas van de arriba abajo (la textura empieza abajo).
                            sheet.SetPixels(c * frameWidth, (rows - 1 - r) * frameHeight, frameWidth, frameHeight, frame.GetPixels());
                            Object.DestroyImmediate(frame);
                        }
                    }

                    File.WriteAllBytes(file, sheet.EncodeToPNG());
                    Object.DestroyImmediate(sheet);
                    sheets++;
                }
            }
            finally
            {
                foreach (KeyValuePair<Transform, Quaternion> pair in saved)
                {
                    pair.Key.localRotation = pair.Value;
                }

                if (hips != null)
                {
                    hips.localPosition = hipsPosition;
                }

                for (int i = 0; i < skins.Length; i++)
                {
                    skins[i].forceMatrixRecalculationPerRender = force[i];
                }

                Object.DestroyImmediate(camera.gameObject);
            }

            File.WriteAllText(Path.Combine(folder, "indice.txt"), index.ToString());
            return names.Count + " gestos en " + sheets + " hojas en " + Path.GetFullPath(folder);
        }

        private static GeniesGestureLayer FindLayer()
        {
            foreach (GeniesGestureLayer layer in Object.FindObjectsByType<GeniesGestureLayer>(FindObjectsInactive.Exclude))
            {
                if (layer.gameObject.name == "Sonia")
                {
                    return layer;
                }
            }

            return null;
        }

        // Cámara de frente que encuadra de la cadera a la cabeza con los brazos
        // abiertos, o de los pies a la cabeza (cuerpo entero, para ver los pies).
        private static Camera MakeCamera(Animator animator, bool fullBody)
        {
            Transform head = animator.GetBoneTransform(HumanBodyBones.Head);
            Transform hips = animator.GetBoneTransform(fullBody ? HumanBodyBones.LeftFoot : HumanBodyBones.Hips);
            Vector3 center = Vector3.Lerp(hips.position, head.position, fullBody ? 0.5f : 0.55f);
            Vector3 toViewer = Camera.main != null ? Camera.main.transform.position - center : -animator.transform.forward;
            toViewer.y = 0f;
            toViewer = toViewer.sqrMagnitude > 1e-4f ? toViewer.normalized : animator.transform.forward;
            float span = (head.position.y - hips.position.y) + (fullBody ? 0.45f : 0.55f);
            GameObject go = new GameObject("GestureCheckCamera");
            go.hideFlags = HideFlags.HideAndDontSave;
            Camera camera = go.AddComponent<Camera>();
            camera.fieldOfView = 30f;
            camera.nearClipPlane = 0.05f;
            camera.farClipPlane = 20f;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.16f, 0.18f, 0.24f);
            float distance = span * 0.5f / Mathf.Tan(camera.fieldOfView * 0.5f * Mathf.Deg2Rad);
            go.transform.position = center + toViewer * distance;
            go.transform.LookAt(center);
            camera.enabled = false;
            return camera;
        }

        private static Transform FindDeep(Transform root, string name)
        {
            if (root.name == name)
            {
                return root;
            }

            for (int i = 0; i < root.childCount; i++)
            {
                Transform found = FindDeep(root.GetChild(i), name);
                if (found != null)
                {
                    return found;
                }
            }

            return null;
        }
    }
}
