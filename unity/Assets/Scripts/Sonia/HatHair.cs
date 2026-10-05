// Pelo aplastado bajo un gorro que no es de Genies (el de la trivia), para
// cualquier pelo de Genies.
//
// Genies no aplasta el pelo en tiempo real: cuando el avatar lleva una gorra
// oficial, NAF hornea en la malla la forma de bajo el gorro que trae cada pelo
// (sus blendshapes «hair_geo_blendShape…») y la malla final ya no tiene
// blendshapes. Así que GeniesHatHair monta a escondidas una gemela del avatar
// con una gorra oficial y aquí se compara su pelo con el del avatar (Build): sale
// una copia de la malla del avatar con un blendshape más, «sonia_hat_hair», que
// lleva cada vértice del pelo de su sitio al de la gemela. TriviaHat pone esa
// copia mientras lleva el gorro y sube el blendshape según encaja (y lo baja al
// quitárselo); el resto del tiempo el avatar lleva su malla de siempre.
//
// La forma la saca Genies del pelo que lleve el avatar, así que vale para
// cualquier pelo: al cambiar de avatar se vuelve a sacar. Las dos mallas casan
// vértice a vértice (el mismo pelo, montado igual, con los mismos huesos); si no
// casan, no se publica nada y el gorro se pone sin aplastar el pelo.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Pelo bajo gorra de los avatares de Genies: lo publica GeniesHatHair y lo usa TriviaHat.</summary>
    public static class HatHair
    {
        /// <summary>Blendshape que se añade a la copia de la malla (100: el pelo como bajo la gorra oficial).</summary>
        public const string ShapeName = "sonia_hat_hair";

        /// <summary>Shader del pelo de Genies (MegaHair).</summary>
        private const string HairShader = "MegaHair";

        /// <summary>Lo que se mueve un vértice para contar como aplastado (m).</summary>
        private const float MovedThreshold = 0.0005f;

        /// <summary>Más que esto (m) no es aplastar el pelo: las mallas no casan.</summary>
        private const float MaxMove = 0.1f;

        private static readonly List<Flat> Flats = new List<Flat>();

        /// <summary>El pelo aplastado de un avatar: su malla de siempre y la copia con el blendshape.</summary>
        public sealed class Flat
        {
            /// <summary>Raíz del avatar.</summary>
            public Transform Avatar;

            /// <summary>Renderer con el pelo (en NAF, «Default»: cuerpo, pelo, ropa y gorro).</summary>
            public SkinnedMeshRenderer Renderer;

            /// <summary>Su malla de siempre, la de Genies.</summary>
            public Mesh Source;

            /// <summary>Copia de Source con el blendshape del pelo aplastado.</summary>
            public Mesh Mesh;

            /// <summary>Índice de ese blendshape en la copia.</summary>
            public int Shape;
        }

        /// <summary>Se lanza al publicar el pelo aplastado de un avatar (su raíz).</summary>
        public static event Action<Transform> Published;

        /// <summary>Alguien necesita el pelo aplastado de un avatar que aún no lo tiene (su raíz).</summary>
        public static event Action<Transform> Requested;

        /// <summary>El pelo aplastado publicado para ese avatar, o null.</summary>
        public static Flat Find(Transform avatar)
        {
            Prune();
            if (avatar == null)
            {
                return null;
            }

            foreach (Flat flat in Flats)
            {
                if (flat.Avatar == avatar)
                {
                    return flat;
                }
            }

            return null;
        }

        /// <summary>Pide el pelo aplastado de un avatar si aún no está (por si falló al ponerse el avatar).</summary>
        public static void Request(Transform avatar)
        {
            if (avatar == null || Find(avatar) != null)
            {
                return;
            }

            Action<Transform> handler = Requested;
            if (handler != null)
            {
                handler(avatar);
            }
        }

        /// <summary>Publica el pelo aplastado de un avatar (sustituye al que tuviera).</summary>
        public static void Publish(Flat flat)
        {
            if (flat == null || flat.Avatar == null || flat.Renderer == null || flat.Source == null || flat.Mesh == null)
            {
                return;
            }

            Prune();
            for (int i = Flats.Count - 1; i >= 0; i--)
            {
                if (Flats[i].Avatar == flat.Avatar)
                {
                    Release(Flats[i]);
                    Flats.RemoveAt(i);
                }
            }

            Flats.Add(flat);
            Action<Transform> handler = Published;
            if (handler != null)
            {
                handler(flat.Avatar);
            }
        }

        /// <summary>El renderer del avatar que lleva el pelo de Genies, o null si no lleva.</summary>
        public static SkinnedMeshRenderer HairRenderer(Transform avatar)
        {
            if (avatar == null)
            {
                return null;
            }

            foreach (SkinnedMeshRenderer renderer in avatar.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                if (renderer.sharedMesh != null && HairSubMeshes(renderer).Count > 0)
                {
                    return renderer;
                }
            }

            return null;
        }

        /// <summary>
        /// Copia de la malla de <paramref name="live"/> con el blendshape ShapeName,
        /// que lleva su pelo a la forma que tiene en <paramref name="flattened"/> (el
        /// mismo avatar con una gorra oficial puesta). Null si no casan; en
        /// <paramref name="report"/>, cuánto pelo se mueve o por qué no casan.
        /// </summary>
        public static Mesh Build(SkinnedMeshRenderer live, SkinnedMeshRenderer flattened, out string report)
        {
            Mesh a = live != null ? live.sharedMesh : null;
            Mesh b = flattened != null ? flattened.sharedMesh : null;
            if (a == null || b == null || !a.isReadable || !b.isReadable)
            {
                report = "no se pueden leer las mallas";
                return null;
            }

            List<int> hairA = HairSubMeshes(live);
            List<int> hairB = HairSubMeshes(flattened);
            if (hairA.Count == 0)
            {
                report = "el avatar no lleva pelo";
                return null;
            }

            if (hairA.Count != hairB.Count)
            {
                report = "la gemela lleva otro pelo (" + hairB.Count + " submallas de pelo; el avatar, " + hairA.Count + ")";
                return null;
            }

            // Mismos huesos y mismas poses de enlace: las dos mallas están en el
            // mismo espacio y los vértices se comparan tal cual.
            if (!SameSkeleton(live, a, flattened, b))
            {
                report = "la gemela tiene otro esqueleto";
                return null;
            }

            Vector3[] va = a.vertices;
            Vector3[] vb = b.vertices;
            Vector3[] na = a.normals;
            Vector3[] nb = b.normals;
            Vector4[] ta = a.tangents;
            Vector4[] tb = b.tangents;
            Vector2[] ua = a.uv;
            Vector2[] ub = b.uv;
            bool normals = na.Length == va.Length && nb.Length == vb.Length;
            bool tangents = ta.Length == va.Length && tb.Length == vb.Length;
            bool uvs = ua.Length == va.Length && ub.Length == vb.Length;
            var deltaVertices = new Vector3[va.Length];
            Vector3[] deltaNormals = normals ? new Vector3[va.Length] : null;
            Vector3[] deltaTangents = tangents ? new Vector3[va.Length] : null;
            int moved = 0;
            float farthest = 0f;
            for (int h = 0; h < hairA.Count; h++)
            {
                int[] indicesA = a.GetIndices(hairA[h]);
                int[] indicesB = b.GetIndices(hairB[h]);
                int[] usedA = Used(indicesA);
                int[] usedB = Used(indicesB);
                if (usedA.Length != usedB.Length || !SameTopology(indicesA, usedA, indicesB, usedB, Mathf.Max(va.Length, vb.Length)))
                {
                    report = "el pelo de la gemela tiene otra topología";
                    return null;
                }

                // Los vértices de cada submalla, en orden: Genies monta el mismo pelo
                // igual, con o sin gorra (comprobado con la topología y las UV).
                for (int j = 0; j < usedA.Length; j++)
                {
                    int x = usedA[j];
                    int y = usedB[j];
                    if (uvs && (ua[x] - ub[y]).sqrMagnitude > 1e-8f)
                    {
                        report = "el pelo de la gemela tiene otras UV";
                        return null;
                    }

                    Vector3 delta = vb[y] - va[x];
                    float distance = delta.magnitude;
                    if (distance > MaxMove)
                    {
                        report = "el pelo de la gemela se separa " + (distance * 100f).ToString("F0") + " cm";
                        return null;
                    }

                    if (distance > MovedThreshold)
                    {
                        moved++;
                    }

                    farthest = Mathf.Max(farthest, distance);
                    deltaVertices[x] = delta;
                    if (normals)
                    {
                        deltaNormals[x] = nb[y] - na[x];
                    }

                    if (tangents)
                    {
                        deltaTangents[x] = (Vector3)tb[y] - (Vector3)ta[x];
                    }
                }
            }

            if (moved == 0)
            {
                report = "el pelo no cambia bajo la gorra";
                return null;
            }

            Mesh copy = UnityEngine.Object.Instantiate(a);
            copy.name = a.name + " (pelo bajo gorra)";
            copy.AddBlendShapeFrame(ShapeName, 100f, deltaVertices, deltaNormals, deltaTangents);
            report = moved + " vértices de pelo, hasta " + (farthest * 100f).ToString("F1") + " cm";
            return copy;
        }

        /// <summary>Submallas de pelo de Genies (shader MegaHair), en orden.</summary>
        private static List<int> HairSubMeshes(SkinnedMeshRenderer renderer)
        {
            var result = new List<int>();
            Mesh mesh = renderer.sharedMesh;
            Material[] materials = renderer.sharedMaterials;
            for (int s = 0; mesh != null && s < mesh.subMeshCount && s < materials.Length; s++)
            {
                Material material = materials[s];
                if (material != null && material.shader != null
                    && material.shader.name.IndexOf(HairShader, StringComparison.Ordinal) >= 0)
                {
                    result.Add(s);
                }
            }

            return result;
        }

        private static bool SameSkeleton(SkinnedMeshRenderer live, Mesh a, SkinnedMeshRenderer flattened, Mesh b)
        {
            Transform[] bonesA = live.bones;
            Transform[] bonesB = flattened.bones;
            Matrix4x4[] posesA = a.bindposes;
            Matrix4x4[] posesB = b.bindposes;
            if (bonesA.Length != bonesB.Length || posesA.Length != posesB.Length)
            {
                return false;
            }

            for (int i = 0; i < bonesA.Length; i++)
            {
                if (bonesA[i] == null || bonesB[i] == null || bonesA[i].name != bonesB[i].name)
                {
                    return false;
                }
            }

            for (int i = 0; i < posesA.Length; i++)
            {
                for (int c = 0; c < 16; c++)
                {
                    if (Mathf.Abs(posesA[i][c] - posesB[i][c]) > 1e-4f)
                    {
                        return false;
                    }
                }
            }

            return true;
        }

        /// <summary>Vértices que usan unos índices, sin repetir y en orden.</summary>
        private static int[] Used(int[] indices)
        {
            var set = new HashSet<int>(indices);
            var used = new int[set.Count];
            set.CopyTo(used);
            Array.Sort(used);
            return used;
        }

        /// <summary>Cierto si los dos índices dibujan los mismos triángulos con los vértices en el mismo orden.</summary>
        private static bool SameTopology(int[] indicesA, int[] usedA, int[] indicesB, int[] usedB, int vertexCount)
        {
            if (indicesA.Length != indicesB.Length)
            {
                return false;
            }

            var rankA = new int[vertexCount];
            var rankB = new int[vertexCount];
            for (int j = 0; j < usedA.Length; j++)
            {
                rankA[usedA[j]] = j;
                rankB[usedB[j]] = j;
            }

            for (int k = 0; k < indicesA.Length; k++)
            {
                if (rankA[indicesA[k]] != rankB[indicesB[k]])
                {
                    return false;
                }
            }

            return true;
        }

        /// <summary>Quita los publicados de avatares que ya no existen.</summary>
        private static void Prune()
        {
            for (int i = Flats.Count - 1; i >= 0; i--)
            {
                Flat flat = Flats[i];
                if (flat.Avatar == null || flat.Renderer == null || flat.Mesh == null)
                {
                    Release(flat);
                    Flats.RemoveAt(i);
                }
            }
        }

        /// <summary>Devuelve al renderer su malla de siempre y destruye la copia.</summary>
        private static void Release(Flat flat)
        {
            if (flat.Renderer != null && flat.Mesh != null && flat.Renderer.sharedMesh == flat.Mesh && flat.Source != null)
            {
                flat.Renderer.sharedMesh = flat.Source;
            }

            if (flat.Mesh == null)
            {
                return;
            }

            if (Application.isPlaying)
            {
                UnityEngine.Object.Destroy(flat.Mesh);
            }
            else
            {
                UnityEngine.Object.DestroyImmediate(flat.Mesh);
            }
        }
    }
}
