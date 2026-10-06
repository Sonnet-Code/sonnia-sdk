// Sonda de la ropa de Sonnia: para vestirla de staff (StaffShirt) hay que saber
// qué submalla es la camiseta, qué texturas lleva y dónde cae el pecho en ellas.
//
// Solo con -probe-shirt <carpeta> en la línea de comandos de la app (en el stand
// no hace nada). Al ponerse el avatar de Sonnia escribe en esa carpeta:
//   sonda.txt   cada submalla (material, shader, alturas, UV, texturas) y, para
//               la prenda de arriba, las UV que dan unos rayos en una rejilla
//               delante y detrás del pecho;
//   *.png       las texturas de la prenda de arriba (con la camiseta de staff
//               puesta, la horneada) y vistas de frente, de espaldas y de tres
//               cuartos con una cámara temporal (sin el posprocesado del stand).
// Son texturas de ropa y renders del avatar, no capturas de la cámara.

using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Cysharp.Threading.Tasks;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Sonia
{
    /// <summary>Diagnóstico de la camiseta del avatar de Genies (ver la cabecera).</summary>
    public static class GeniesShirtProbe
    {
        public const string Argument = "-probe-shirt";

        private static string _directory;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void Install()
        {
            GeniesAvatarLoader.AvatarShown -= HandleAvatarShown;
            _directory = null;
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == Argument)
                {
                    _directory = args[i + 1];
                }
            }

            if (_directory != null)
            {
                GeniesAvatarLoader.AvatarShown += HandleAvatarShown;
            }
        }

        private static void HandleAvatarShown(GeniesAvatarLoader loader, string json)
        {
            if (loader == null || loader.Role != AvatarRole.Sonia || loader.LiveAvatar == null
                || loader.LiveAvatar.Root == null)
            {
                return;
            }

            ProbeAsync(loader.LiveAvatar.Root.transform).Forget();
        }

        private static async UniTaskVoid ProbeAsync(Transform root)
        {
            await UniTask.Delay(3000);
            if (root == null)
            {
                return;
            }

            Directory.CreateDirectory(_directory);
            var log = new StringBuilder("[Sonia] Sonda de la camiseta\n");
            Animator animator = root.GetComponentInChildren<Animator>();
            Transform chest = Bone(animator, HumanBodyBones.UpperChest) ?? Bone(animator, HumanBodyBones.Chest);
            Transform hips = Bone(animator, HumanBodyBones.Hips);
            Transform neck = Bone(animator, HumanBodyBones.Neck);
            log.AppendLine("raíz " + root.name + " escala " + root.lossyScale + " forward " + root.forward + " right " + root.right);
            log.AppendLine("pecho " + Where(chest) + " caderas " + Where(hips) + " cuello " + Where(neck));
            if (chest == null)
            {
                Finish(log);
                return;
            }

            int exported = 0;
            foreach (SkinnedMeshRenderer renderer in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                Mesh mesh = renderer.sharedMesh;
                log.AppendLine("renderer " + renderer.name + " submallas " + (mesh != null ? mesh.subMeshCount : 0)
                               + " legible " + (mesh != null && mesh.isReadable));
                if (mesh == null || !mesh.isReadable)
                {
                    continue;
                }

                var baked = new Mesh();
                renderer.BakeMesh(baked, true);
                Vector3[] vertices = baked.vertices;
                Vector2[] uvs = mesh.uv;
                Matrix4x4 toWorld = renderer.transform.localToWorldMatrix;
                Material[] materials = renderer.sharedMaterials;
                for (int s = 0; s < mesh.subMeshCount; s++)
                {
                    Material material = s < materials.Length ? materials[s] : null;
                    int[] indices = mesh.GetIndices(s);
                    float min = float.PositiveInfinity;
                    float max = float.NegativeInfinity;
                    Vector2 uvMin = Vector2.positiveInfinity;
                    Vector2 uvMax = Vector2.negativeInfinity;
                    foreach (int index in indices)
                    {
                        float y = toWorld.MultiplyPoint3x4(vertices[index]).y;
                        min = Mathf.Min(min, y);
                        max = Mathf.Max(max, y);
                        if (index < uvs.Length)
                        {
                            uvMin = Vector2.Min(uvMin, uvs[index]);
                            uvMax = Vector2.Max(uvMax, uvs[index]);
                        }
                    }

                    string shader = material != null && material.shader != null ? material.shader.name : "-";
                    log.AppendLine("  [" + s + "] " + (material != null ? material.name : "-") + " | " + shader
                                   + " | y " + min.ToString("F3") + ".." + max.ToString("F3")
                                   + " | uv " + uvMin.ToString("F3") + ".." + uvMax.ToString("F3")
                                   + " | " + indices.Length / 3 + " triángulos");
                    if (material == null)
                    {
                        continue;
                    }

                    bool top = !shader.StartsWith("Shader Graphs/Mega", StringComparison.Ordinal)
                               && shader.IndexOf("MegaSkin", StringComparison.Ordinal) < 0
                               && min < chest.position.y - 0.05f && max > chest.position.y + 0.05f;
                    if (!top)
                    {
                        continue;
                    }

                    log.AppendLine("    PRENDA DE ARRIBA (candidata)");
                    DescribeMaterial(material, log);
                    foreach (string property in material.GetTexturePropertyNames())
                    {
                        Texture texture = material.GetTexture(property);
                        if (texture == null)
                        {
                            continue;
                        }

                        string file = "s" + s + "_" + property.TrimStart('_') + ".png";
                        Export(texture, Path.Combine(_directory, file));
                        exported++;
                        log.AppendLine("    exportada " + file + " (" + texture.width + "x" + texture.height + ")");
                    }

                    RaycastGrid(root, chest, vertices, uvs, indices, toWorld, log);
                }

                Object.Destroy(baked);
            }

            log.AppendLine(exported + " texturas exportadas en " + _directory);
            RenderViews(root, chest);
            log.AppendLine("vistas: vista-frente.png, vista-espalda.png, vista-tres-cuartos.png");
            Finish(log);
        }

        private static void DescribeMaterial(Material material, StringBuilder log)
        {
            Shader shader = material.shader;
            for (int i = 0; i < shader.GetPropertyCount(); i++)
            {
                string name = shader.GetPropertyName(i);
                string value;
                switch (shader.GetPropertyType(i))
                {
                    case UnityEngine.Rendering.ShaderPropertyType.Color:
                        value = material.GetColor(name).ToString();
                        break;
                    case UnityEngine.Rendering.ShaderPropertyType.Float:
                    case UnityEngine.Rendering.ShaderPropertyType.Range:
                        value = material.GetFloat(name).ToString("F3");
                        break;
                    case UnityEngine.Rendering.ShaderPropertyType.Vector:
                        value = material.GetVector(name).ToString();
                        break;
                    case UnityEngine.Rendering.ShaderPropertyType.Texture:
                        Texture t = material.GetTexture(name);
                        value = t != null ? t.name + " " + t.width + "x" + t.height : "-";
                        break;
                    default:
                        value = "?";
                        break;
                }

                log.AppendLine("      " + name + " = " + value);
            }

            log.AppendLine("      keywords: " + string.Join(" ", material.shaderKeywords));
        }

        /// <summary>UV que dan rayos delante y detrás del pecho, en una rejilla de 5 cm.</summary>
        private static void RaycastGrid(Transform root, Transform chest, Vector3[] vertices, Vector2[] uvs,
                                        int[] indices, Matrix4x4 toWorld, StringBuilder log)
        {
            var mesh = new Mesh { indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 };
            var world = new Vector3[vertices.Length];
            for (int i = 0; i < vertices.Length; i++)
            {
                world[i] = toWorld.MultiplyPoint3x4(vertices[i]);
            }

            mesh.vertices = world;
            mesh.uv = uvs;
            mesh.triangles = indices;
            var go = new GameObject("SondaCamiseta");
            MeshCollider collider = go.AddComponent<MeshCollider>();
            collider.sharedMesh = mesh;
            Physics.SyncTransforms();
            foreach (float side in new[] { 1f, -1f })
            {
                log.AppendLine(side > 0 ? "    rejilla DELANTE (dx, dy en m -> uv)" : "    rejilla DETRÁS (dx, dy en m -> uv)");
                for (float dy = 0.10f; dy >= -0.301f; dy -= 0.05f)
                {
                    var row = new StringBuilder("     ");
                    for (float dx = -0.20f; dx <= 0.201f; dx += 0.05f)
                    {
                        Vector3 origin = chest.position + root.right * dx + Vector3.up * dy + root.forward * (0.6f * side);
                        var ray = new Ray(origin, -root.forward * side);
                        row.Append(collider.Raycast(ray, out RaycastHit hit, 1.2f)
                            ? " (" + dx.ToString("F2") + "," + dy.ToString("F2") + ")=" + hit.textureCoord.ToString("F3")
                            : " (" + dx.ToString("F2") + "," + dy.ToString("F2") + ")=-");
                    }

                    log.AppendLine(row.ToString());
                }
            }

            Object.Destroy(go);
            Object.Destroy(mesh);
        }

        /// <summary>El avatar de frente, de espaldas y de tres cuartos, a la altura del pecho.</summary>
        private static void RenderViews(Transform root, Transform chest)
        {
            var go = new GameObject("SondaCamara");
            Camera camera = go.AddComponent<Camera>();
            camera.enabled = false;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.043f, 0.118f, 0.247f);
            camera.fieldOfView = 30f;
            camera.nearClipPlane = 0.05f;
            camera.farClipPlane = 20f;
            var rt = new RenderTexture(1080, 1350, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB) { antiAliasing = 4 };
            camera.targetTexture = rt;
            Vector3 target = chest.position + Vector3.down * 0.07f;
            var views = new (string Name, Vector3 Direction)[]
            {
                ("vista-frente", root.forward),
                ("vista-espalda", -root.forward),
                ("vista-tres-cuartos", (root.forward - root.right * 0.9f).normalized)
            };
            foreach ((string name, Vector3 direction) in views)
            {
                go.transform.position = target + direction * 1.15f;
                go.transform.LookAt(target, Vector3.up);
                camera.Render();
                Export(rt, Path.Combine(_directory, name + ".png"));
            }

            camera.targetTexture = null;
            Object.Destroy(rt);
            Object.Destroy(go);
        }

        private static void Export(Texture texture, string path)
        {
            RenderTexture rt = RenderTexture.GetTemporary(texture.width, texture.height, 0, RenderTextureFormat.ARGB32,
                                                          RenderTextureReadWrite.sRGB);
            Graphics.Blit(texture, rt);
            RenderTexture previous = RenderTexture.active;
            RenderTexture.active = rt;
            var copy = new Texture2D(texture.width, texture.height, TextureFormat.RGBA32, false);
            copy.ReadPixels(new Rect(0, 0, texture.width, texture.height), 0, 0);
            copy.Apply();
            RenderTexture.active = previous;
            RenderTexture.ReleaseTemporary(rt);
            File.WriteAllBytes(path, copy.EncodeToPNG());
            Object.Destroy(copy);
        }

        private static Transform Bone(Animator animator, HumanBodyBones bone)
        {
            return animator != null && animator.isHuman ? animator.GetBoneTransform(bone) : null;
        }

        private static string Where(Transform t)
        {
            return t != null ? t.position.ToString("F3") : "-";
        }

        private static void Finish(StringBuilder log)
        {
            File.WriteAllText(Path.Combine(_directory, "sonda.txt"), log.ToString());
            Debug.Log(log.ToString());
        }
    }
}
