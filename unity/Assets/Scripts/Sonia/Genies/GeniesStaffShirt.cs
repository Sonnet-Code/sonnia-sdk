// Camiseta de staff del DevFest Santo Domingo para Sonnia (docs/unity.md,
// «Camiseta de staff»).
//
// Cada vez que se va a poner un avatar de Sonnia, aún en el aparcamiento
// (GeniesAvatarLoader.BeforeShow, así nunca se la ve sin ella), su prenda de
// arriba pasa a ser la camiseta de staff:
//   - el color de la tela se multiplica por el de la camiseta. Genies pinta la
//     tela de blanco y saca los pliegues y el tejido del mapa de normales, que no
//     se toca, así que la prenda se queda con su textura y su sombreado;
//   - los estampados (Resources/StaffShirt/<variante>, los genera
//     scripts/camiseta_staff/genera.py con su staff-shirt.json) se proyectan de
//     frente o de espaldas sobre la malla y se hornean en la textura de la
//     prenda: cada texel sabe en qué punto del cuerpo está y coge el color del
//     estampado que cae ahí. Es lo que hacen las prendas de MegaShader con
//     estampado con su mapa _DecalUVProjection; esta camiseta (URP Lit, sin ese
//     mapa) no lo trae, así que se calcula aquí, una vez por avatar y en un hilo
//     aparte. Como el estampado va en la textura, se pliega y se ilumina con la tela.
// Al destruirse el avatar se devuelve la textura original al material (NAF puede
// reutilizarlo) y se suelta la horneada.
//
// Variantes: azul (la de por defecto, DefaultVariant), negra y blanca; se elige
// con -camiseta <variante>. -sin-camiseta-staff lo desactiva.

using System;
using System.Collections.Generic;
using Cysharp.Threading.Tasks;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Sonia
{
    /// <summary>Viste a Sonnia con la camiseta de staff (ver la cabecera).</summary>
    public static class GeniesStaffShirt
    {
        public const string DisableArgument = "-sin-camiseta-staff";

        /// <summary>Argumento que elige la variante: -camiseta azul|negra|blanca.</summary>
        public const string VariantArgument = "-camiseta";

        /// <summary>La que se pone sin -camiseta.</summary>
        public const string DefaultVariant = "azul";

        /// <summary>Nombre de la textura horneada (la sonda la reconoce).</summary>
        public const string BakedTextureName = "staff-shirt";

        private const string ResourceFolder = "StaffShirt/";

        /// <summary>Propiedades del color de la tela según el shader (URP Lit, MegaShader, Built-in).</summary>
        private static readonly string[] AlbedoProperties = { "_BaseMap", "_AlbedoTransparency", "_MainTex" };

        /// <summary>Texturas originales de los materiales retocados (NAF puede reutilizar un material).</summary>
        private static readonly Dictionary<Material, Texture> Originals = new Dictionary<Material, Texture>();

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void Install()
        {
            GeniesAvatarLoader.BeforeShow -= Dress;
            Originals.Clear();
            if (Array.IndexOf(Environment.GetCommandLineArgs(), DisableArgument) < 0)
            {
                GeniesAvatarLoader.BeforeShow += Dress;
            }
        }

        private static async UniTask Dress(GeniesAvatarLoader loader, Transform root)
        {
            if (loader == null || loader.Role != AvatarRole.Sonia || root == null)
            {
                return;
            }

            float started = Time.realtimeSinceStartup;
            Design design = Design.Load(Variant());
            if (design == null)
            {
                return;
            }

            Animator animator = root.GetComponentInChildren<Animator>();
            Transform chest = animator != null && animator.isHuman
                ? animator.GetBoneTransform(HumanBodyBones.UpperChest) ?? animator.GetBoneTransform(HumanBodyBones.Chest)
                : null;
            if (chest == null)
            {
                Debug.LogWarning("[Sonia] Camiseta de staff: el avatar no tiene pecho humanoide; se queda con su ropa.");
                return;
            }

            Garment garment = Garment.FindTop(root, chest);
            if (garment == null)
            {
                Debug.LogWarning("[Sonia] Camiseta de staff: no encuentro la prenda de arriba; se queda con su ropa.");
                return;
            }

            if (!Originals.TryGetValue(garment.Material, out Texture source))
            {
                source = garment.Material.GetTexture(garment.AlbedoProperty);
            }

            int width = source != null ? source.width : 2048;
            int height = source != null ? source.height : 2048;
            Color32[] basePixels = source != null ? Readback(source) : null;
            var job = new BakeJob(design, garment, chest.position, root, width, height, basePixels);
            Color32[] pixels = await UniTask.RunOnThreadPool(job.Run);
            if (root == null || garment.Material == null)
            {
                return;
            }

            var texture = new Texture2D(width, height, TextureFormat.RGBA32, true, false)
            {
                name = BakedTextureName,
                wrapMode = source != null ? source.wrapMode : TextureWrapMode.Clamp,
                filterMode = FilterMode.Trilinear,
                anisoLevel = 4
            };
            texture.SetPixels32(pixels);
            texture.Apply(true, true);
            if (!Originals.ContainsKey(garment.Material))
            {
                Originals[garment.Material] = source;
            }

            garment.Material.SetTexture(garment.AlbedoProperty, texture);
            Owner owner = root.gameObject.AddComponent<Owner>();
            owner.Material = garment.Material;
            owner.Property = garment.AlbedoProperty;
            owner.Texture = texture;
            Debug.Log("[Sonia] Camiseta de staff (" + design.Name + ") puesta en «" + garment.Material.name + "» ("
                      + width + "x" + height + ", " + job.PrintedTexels + " texeles estampados, "
                      + ((Time.realtimeSinceStartup - started) * 1000f).ToString("F0") + " ms).");
        }

        /// <summary>La variante de la línea de comandos (-camiseta) o la de por defecto.</summary>
        private static string Variant()
        {
            string[] args = Environment.GetCommandLineArgs();
            int index = Array.IndexOf(args, VariantArgument);
            return index >= 0 && index + 1 < args.Length ? args[index + 1].Trim().ToLowerInvariant() : DefaultVariant;
        }

        /// <summary>Píxeles de una textura aunque no sea legible (copia por la GPU, en sRGB).</summary>
        private static Color32[] Readback(Texture texture)
        {
            RenderTexture rt = RenderTexture.GetTemporary(texture.width, texture.height, 0, RenderTextureFormat.ARGB32,
                                                          RenderTextureReadWrite.sRGB);
            Graphics.Blit(texture, rt);
            RenderTexture previous = RenderTexture.active;
            RenderTexture.active = rt;
            var copy = new Texture2D(texture.width, texture.height, TextureFormat.RGBA32, false, false);
            copy.ReadPixels(new Rect(0, 0, texture.width, texture.height), 0, 0);
            copy.Apply(false);
            RenderTexture.active = previous;
            RenderTexture.ReleaseTemporary(rt);
            Color32[] pixels = copy.GetPixels32();
            Object.Destroy(copy);
            return pixels;
        }

        // ------------------------------------------------------------------
        // Diseño (staff-shirt.json + PNG)
        // ------------------------------------------------------------------

        [Serializable]
        private class DesignFile
        {
            public string color = "#FFFFFF";
            public PrintFile[] prints = Array.Empty<PrintFile>();
        }

        [Serializable]
        private class PrintFile
        {
            public string texture;
            public string face;
            public float[] rect;
        }

        private sealed class Print
        {
            public bool Back;
            public Rect Area;
            public int Width;
            public int Height;
            public Color32[] Pixels;
        }

        private sealed class Design
        {
            public string Name;
            public Color32 Color;
            public List<Print> Prints = new List<Print>();

            public static Design Load(string variant)
            {
                string folder = ResourceFolder + variant + "/";
                TextAsset json = Resources.Load<TextAsset>(folder + "staff-shirt");
                if (json == null && variant != DefaultVariant)
                {
                    Debug.LogWarning("[Sonia] Camiseta de staff: no hay variante «" + variant + "»; uso la " + DefaultVariant + ".");
                    folder = ResourceFolder + DefaultVariant + "/";
                    json = Resources.Load<TextAsset>(folder + "staff-shirt");
                }

                if (json == null)
                {
                    Debug.LogWarning("[Sonia] Camiseta de staff: falta Resources/" + folder + "staff-shirt.json.");
                    return null;
                }

                DesignFile file = JsonUtility.FromJson<DesignFile>(json.text);
                var design = new Design
                {
                    Name = folder.TrimEnd('/').Substring(ResourceFolder.Length),
                    Color = ColorUtility.TryParseHtmlString(file.color, out Color color) ? (Color32)color : new Color32(255, 255, 255, 255)
                };
                foreach (PrintFile entry in file.prints ?? Array.Empty<PrintFile>())
                {
                    Texture2D image = Resources.Load<Texture2D>(folder + entry.texture);
                    if (image == null || !image.isReadable || entry.rect == null || entry.rect.Length != 4)
                    {
                        Debug.LogWarning("[Sonia] Camiseta de staff: estampado «" + entry.texture + "» ausente, no legible o sin rect.");
                        continue;
                    }

                    design.Prints.Add(new Print
                    {
                        Back = entry.face == "back",
                        Area = Rect.MinMaxRect(entry.rect[0], entry.rect[1], entry.rect[2], entry.rect[3]),
                        Width = image.width,
                        Height = image.height,
                        Pixels = image.GetPixels32()
                    });
                }

                return design;
            }
        }

        // ------------------------------------------------------------------
        // La prenda de arriba
        // ------------------------------------------------------------------

        private sealed class Garment
        {
            public Material Material;
            public string AlbedoProperty;
            public Vector2[] Uvs;
            public Vector3[] Positions;
            public Vector3[] Normals;
            public int[] Triangles;

            /// <summary>
            /// La prenda que cubre el pecho: una submalla que no es piel ni pelo de
            /// Genies (MegaSkin, Shader Graphs/Mega*) y que pasa por encima y por
            /// debajo del pecho. Si hay varias, la de más triángulos.
            /// </summary>
            public static Garment FindTop(Transform root, Transform chest)
            {
                Garment best = null;
                int bestTriangles = 0;
                float chestY = chest.position.y;
                foreach (SkinnedMeshRenderer renderer in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
                {
                    Mesh mesh = renderer.sharedMesh;
                    if (mesh == null || !mesh.isReadable)
                    {
                        continue;
                    }

                    Material[] materials = renderer.sharedMaterials;
                    Mesh baked = null;
                    for (int s = 0; s < mesh.subMeshCount && s < materials.Length; s++)
                    {
                        Material material = materials[s];
                        string shader = material != null && material.shader != null ? material.shader.name : string.Empty;
                        string property = material != null ? Array.Find(AlbedoProperties, material.HasProperty) : null;
                        if (property == null || shader.StartsWith("Shader Graphs/Mega", StringComparison.Ordinal)
                            || shader.IndexOf("MegaSkin", StringComparison.Ordinal) >= 0)
                        {
                            continue;
                        }

                        int[] triangles = mesh.GetTriangles(s);
                        if (triangles.Length / 3 <= bestTriangles)
                        {
                            continue;
                        }

                        if (baked == null)
                        {
                            baked = new Mesh();
                            renderer.BakeMesh(baked, true);
                        }

                        Vector3[] vertices = baked.vertices;
                        Matrix4x4 toWorld = renderer.transform.localToWorldMatrix;
                        float min = float.PositiveInfinity;
                        float max = float.NegativeInfinity;
                        foreach (int index in triangles)
                        {
                            float y = toWorld.MultiplyPoint3x4(vertices[index]).y;
                            min = Mathf.Min(min, y);
                            max = Mathf.Max(max, y);
                        }

                        if (min > chestY - 0.05f || max < chestY + 0.05f)
                        {
                            continue;
                        }

                        Vector3[] normals = baked.normals;
                        var positions = new Vector3[vertices.Length];
                        var worldNormals = new Vector3[vertices.Length];
                        for (int i = 0; i < vertices.Length; i++)
                        {
                            positions[i] = toWorld.MultiplyPoint3x4(vertices[i]);
                            worldNormals[i] = i < normals.Length ? toWorld.MultiplyVector(normals[i]).normalized : Vector3.zero;
                        }

                        best = new Garment
                        {
                            Material = material,
                            AlbedoProperty = property,
                            Uvs = mesh.uv,
                            Positions = positions,
                            Normals = worldNormals,
                            Triangles = triangles
                        };
                        bestTriangles = triangles.Length / 3;
                    }

                    if (baked != null)
                    {
                        Object.Destroy(baked);
                    }
                }

                return best != null && best.Uvs.Length == best.Positions.Length ? best : null;
            }
        }

        // ------------------------------------------------------------------
        // Horneado (en un hilo aparte: solo datos, nada de la API de Unity)
        // ------------------------------------------------------------------

        private sealed class BakeJob
        {
            /// <summary>Cuánto tiene que mirar la tela hacia el estampado: de lado se estira, así que se desvanece.</summary>
            private const float FacingStart = 0.15f;
            private const float FacingFull = 0.45f;

            private readonly Design _design;
            private readonly Garment _garment;
            private readonly Vector3 _anchor;
            private readonly Vector3 _forward;
            private readonly Vector3 _up;
            private readonly Vector3 _viewerRight;
            private readonly int _width;
            private readonly int _height;
            private readonly Color32[] _base;

            public int PrintedTexels;

            public BakeJob(Design design, Garment garment, Vector3 anchor, Transform root, int width, int height, Color32[] basePixels)
            {
                _design = design;
                _garment = garment;
                _anchor = anchor;
                _forward = root.forward;
                _up = root.up;
                // Quien mira a Sonnia de frente tiene su derecha a la izquierda de ella.
                _viewerRight = -root.right;
                _width = width;
                _height = height;
                _base = basePixels;
            }

            public Color32[] Run()
            {
                int count = _width * _height;
                var ink = new Color[count];
                int[] tris = _garment.Triangles;
                for (int t = 0; t + 2 < tris.Length; t += 3)
                {
                    RasterizeTriangle(tris[t], tris[t + 1], tris[t + 2], ink);
                }

                var result = new Color32[count];
                Color32 shirt = _design.Color;
                for (int i = 0; i < count; i++)
                {
                    Color32 b = _base != null ? _base[i] : new Color32(255, 255, 255, 255);
                    // La tela: su textura por el color de la camiseta.
                    float r = b.r * shirt.r / 255f;
                    float g = b.g * shirt.g / 255f;
                    float bl = b.b * shirt.b / 255f;
                    Color c = ink[i];
                    if (c.a > 0f)
                    {
                        // La tinta, también por la textura de la tela (premultiplicada).
                        r = r * (1f - c.a) + b.r * c.r;
                        g = g * (1f - c.a) + b.g * c.g;
                        bl = bl * (1f - c.a) + b.b * c.b;
                        PrintedTexels++;
                    }

                    result[i] = new Color32((byte)Mathf.Clamp(Mathf.RoundToInt(r), 0, 255),
                                            (byte)Mathf.Clamp(Mathf.RoundToInt(g), 0, 255),
                                            (byte)Mathf.Clamp(Mathf.RoundToInt(bl), 0, 255), b.a);
                }

                return result;
            }

            private void RasterizeTriangle(int i0, int i1, int i2, Color[] ink)
            {
                Vector2 a = Pixel(_garment.Uvs[i0]);
                Vector2 b = Pixel(_garment.Uvs[i1]);
                Vector2 c = Pixel(_garment.Uvs[i2]);
                float area = Edge(a, b, c);
                if (Mathf.Abs(area) < 1e-6f)
                {
                    return;
                }

                // Un triángulo que no mira a ningún estampado no hace falta recorrerlo.
                Vector3 n = _garment.Normals[i0] + _garment.Normals[i1] + _garment.Normals[i2];
                float facing = Vector3.Dot(n.normalized, _forward);
                if (Mathf.Abs(facing) < FacingStart * 0.5f)
                {
                    return;
                }

                int x0 = Mathf.Max(0, Mathf.FloorToInt(Mathf.Min(a.x, Mathf.Min(b.x, c.x))));
                int x1 = Mathf.Min(_width - 1, Mathf.CeilToInt(Mathf.Max(a.x, Mathf.Max(b.x, c.x))));
                int y0 = Mathf.Max(0, Mathf.FloorToInt(Mathf.Min(a.y, Mathf.Min(b.y, c.y))));
                int y1 = Mathf.Min(_height - 1, Mathf.CeilToInt(Mathf.Max(a.y, Mathf.Max(b.y, c.y))));
                Vector3 p0 = _garment.Positions[i0], p1 = _garment.Positions[i1], p2 = _garment.Positions[i2];
                Vector3 n0 = _garment.Normals[i0], n1 = _garment.Normals[i1], n2 = _garment.Normals[i2];
                for (int y = y0; y <= y1; y++)
                {
                    for (int x = x0; x <= x1; x++)
                    {
                        var center = new Vector2(x + 0.5f, y + 0.5f);
                        float w0 = Edge(b, c, center) / area;
                        float w1 = Edge(c, a, center) / area;
                        float w2 = 1f - w0 - w1;
                        if (w0 < -1e-4f || w1 < -1e-4f || w2 < -1e-4f)
                        {
                            continue;
                        }

                        Vector3 normal = (n0 * w0 + n1 * w1 + n2 * w2).normalized;
                        if (!NearAnyPrint(p0 * w0 + p1 * w1 + p2 * w2, normal))
                        {
                            continue;
                        }

                        Color sum = Color.clear;
                        // 2x2 muestras por texel: los bordes de las letras sin dientes.
                        for (int sy = 0; sy < 2; sy++)
                        {
                            for (int sx = 0; sx < 2; sx++)
                            {
                                var sample = new Vector2(x + 0.25f + 0.5f * sx, y + 0.25f + 0.5f * sy);
                                float v0 = Edge(b, c, sample) / area;
                                float v1 = Edge(c, a, sample) / area;
                                Vector3 point = p0 * v0 + p1 * v1 + p2 * (1f - v0 - v1);
                                sum += InkAt(point, normal);
                            }
                        }

                        sum *= 0.25f;
                        if (sum.a > 0f)
                        {
                            int index = y * _width + x;
                            if (sum.a > ink[index].a)
                            {
                                ink[index] = sum;
                            }
                        }
                    }
                }
            }

            /// <summary>Descarte rápido: el texel no mira a ningún estampado o cae lejos de todos.</summary>
            private bool NearAnyPrint(Vector3 point, Vector3 normal)
            {
                Vector3 local = point - _anchor;
                const float margin = 0.004f;
                foreach (Print print in _design.Prints)
                {
                    if (Vector3.Dot(normal, print.Back ? -_forward : _forward) <= FacingStart)
                    {
                        continue;
                    }

                    float x = Vector3.Dot(local, print.Back ? -_viewerRight : _viewerRight);
                    float y = Vector3.Dot(local, _up);
                    if (x > print.Area.xMin - margin && x < print.Area.xMax + margin
                        && y > print.Area.yMin - margin && y < print.Area.yMax + margin)
                    {
                        return true;
                    }
                }

                return false;
            }

            /// <summary>Tinta (premultiplicada) que cae en un punto del cuerpo con esa normal.</summary>
            private Color InkAt(Vector3 point, Vector3 normal)
            {
                Color total = Color.clear;
                Vector3 local = point - _anchor;
                foreach (Print print in _design.Prints)
                {
                    float facing = Vector3.Dot(normal, print.Back ? -_forward : _forward);
                    float weight = Mathf.InverseLerp(FacingStart, FacingFull, facing);
                    if (weight <= 0f)
                    {
                        continue;
                    }

                    // De espaldas, la derecha de quien mira es la de Sonnia.
                    float x = Vector3.Dot(local, print.Back ? -_viewerRight : _viewerRight);
                    float y = Vector3.Dot(local, _up);
                    if (!print.Area.Contains(new Vector2(x, y)))
                    {
                        continue;
                    }

                    Color c = Sample(print, (x - print.Area.xMin) / print.Area.width, (y - print.Area.yMin) / print.Area.height);
                    c.a *= weight;
                    total = new Color(total.r * (1f - c.a) + c.r * c.a, total.g * (1f - c.a) + c.g * c.a,
                                      total.b * (1f - c.a) + c.b * c.a, total.a + c.a * (1f - total.a));
                }

                return total;
            }

            /// <summary>Muestra bilineal del estampado (u, v de 0 a 1, v hacia arriba).</summary>
            private static Color Sample(Print print, float u, float v)
            {
                float fx = u * print.Width - 0.5f;
                float fy = v * print.Height - 0.5f;
                int x = Mathf.FloorToInt(fx);
                int y = Mathf.FloorToInt(fy);
                float tx = fx - x;
                float ty = fy - y;
                Color c00 = Texel(print, x, y), c10 = Texel(print, x + 1, y);
                Color c01 = Texel(print, x, y + 1), c11 = Texel(print, x + 1, y + 1);
                return Color.Lerp(Color.Lerp(c00, c10, tx), Color.Lerp(c01, c11, tx), ty);
            }

            private static Color Texel(Print print, int x, int y)
            {
                if (x < 0 || y < 0 || x >= print.Width || y >= print.Height)
                {
                    return Color.clear;
                }

                Color32 c = print.Pixels[y * print.Width + x];
                return new Color(c.r / 255f, c.g / 255f, c.b / 255f, c.a / 255f);
            }

            private Vector2 Pixel(Vector2 uv)
            {
                return new Vector2(uv.x * _width, uv.y * _height);
            }

            private static float Edge(Vector2 a, Vector2 b, Vector2 p)
            {
                return (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x);
            }
        }

        /// <summary>Devuelve la textura original al material y suelta la horneada al destruirse el avatar.</summary>
        private sealed class Owner : MonoBehaviour
        {
            public Material Material;
            public string Property;
            public Texture2D Texture;

            private void OnDestroy()
            {
                if (Material != null && Material.GetTexture(Property) == Texture
                    && Originals.TryGetValue(Material, out Texture original))
                {
                    Material.SetTexture(Property, original);
                }

                if (Material != null)
                {
                    Originals.Remove(Material);
                }

                if (Texture != null)
                {
                    Destroy(Texture);
                }
            }
        }
    }
}
