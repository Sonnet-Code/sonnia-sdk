// "Sonia > Crear gorro Noogler": monta el gorro de la trivia a partir de lo que
// sale de scripts/gorro_noogler (Assets/Sonia/Trivia/NooglerCap): el FBX, las
// tres texturas, NooglerCap.json con las medidas de la boca y el eje de la
// hélice, y NooglerCap_fit.json con su sitio en la cabeza de Sonia (encajado con
// la gorra oficial de Genies).
//
//   1. Importa el FBX con la conversión de ejes horneada y sin materiales. En el
//      prefab el origen es el centro de la boca, la visera mira a +Z (con media
//      vuelta al modelo si el FBX la deja hacia -Z) y la copa sube por +Y.
//   2. Normal map como normal map y metálico/suavidad en lineal.
//   3. Material URP Lit con las tres texturas, a dos caras como el original.
//   4. Prefab en Resources (Trivia/NooglerCap) con TriviaCapRig: la hélice y su
//      eje, las medidas de la boca (TriviaHat lo coge por el ala) y el encaje en
//      la cabeza.
//
// Es idempotente: se puede ejecutar cuantas veces haga falta.
//
// "Sonia > Medir gorra oficial (gorro Noogler)", en Play con la gorra oficial
// puesta: la hornea en el espacio del hueso de la cabeza y la guarda en
// scripts/gorro_noogler/trabajo/gorra_oficial.json para que encajar.py coloque el
// gorro Noogler en su sitio. La gorra es la submalla que encuentra
// TriviaHat.FindHatParts, la misma que el gorro esconde mientras está puesto.

#if UNITY_EDITOR

using System;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Monta el prefab del gorro Noogler de la trivia.</summary>
    public static class SoniaNooglerCapBuilder
    {
        private const string Folder = "Assets/Sonia/Trivia/NooglerCap";
        private const string ModelPath = Folder + "/NooglerCap.fbx";
        private const string AlbedoPath = Folder + "/NooglerCap_Albedo.jpg";
        private const string NormalPath = Folder + "/NooglerCap_Normal.png";
        private const string MaskPath = Folder + "/NooglerCap_MetallicSmoothness.png";
        private const string MetadataPath = Folder + "/NooglerCap.json";
        private const string FitPath = Folder + "/NooglerCap_fit.json";
        private const string MaterialPath = Folder + "/NooglerCap.mat";
        private const string PrefabPath = "Assets/Sonia/Trivia/Resources/Trivia/NooglerCap.prefab";

        /// <summary>Lo que escribe construir.py (coordenadas de Blender: Z arriba, visera hacia -Y).</summary>
        [Serializable]
        private class Metadata
        {
            public float[] apex = new float[3];
            public float opening_width = 0f;
            public float opening_depth = 0f;
            public float[] propeller_axis = new float[0];
            public float[] grip_points = new float[0];
            public float[] grip_normals = new float[0];
        }

        /// <summary>Lo que escribe encajar.py: el gorro en el espacio del hueso de la cabeza (ejes de Unity).</summary>
        [Serializable]
        private class Fit
        {
            public float[] position = new float[0];
            public float[] rotation = new float[0];
            public float scale = 0f;
            public float error_mm = 0f;
        }

        [MenuItem("Sonia/Crear gorro Noogler")]
        public static void Build()
        {
            AssetDatabase.Refresh();
            if (AssetImporter.GetAtPath(ModelPath) is not ModelImporter model)
            {
                Debug.LogError("[Sonia] Falta " + ModelPath + " (sale de scripts/gorro_noogler/construir.py).");
                return;
            }

            ConfigureModel(model);
            ConfigureTexture(AlbedoPath, TextureImporterType.Default, true);
            ConfigureTexture(NormalPath, TextureImporterType.NormalMap, false);
            ConfigureTexture(MaskPath, TextureImporterType.Default, false);
            Material material = BuildMaterial();
            BuildPrefab(material);
        }

        private static void ConfigureModel(ModelImporter model)
        {
            bool dirty = false;
            if (!model.bakeAxisConversion)
            {
                model.bakeAxisConversion = true;
                dirty = true;
            }

            if (model.materialImportMode != ModelImporterMaterialImportMode.None)
            {
                model.materialImportMode = ModelImporterMaterialImportMode.None;
                dirty = true;
            }

            if (model.importAnimation || model.importCameras || model.importLights)
            {
                model.importAnimation = false;
                model.importCameras = false;
                model.importLights = false;
                dirty = true;
            }

            if (model.animationType != ModelImporterAnimationType.None)
            {
                model.animationType = ModelImporterAnimationType.None;
                dirty = true;
            }

            if (dirty)
            {
                model.SaveAndReimport();
            }
        }

        private static void ConfigureTexture(string path, TextureImporterType type, bool srgb)
        {
            if (AssetImporter.GetAtPath(path) is not TextureImporter importer)
            {
                Debug.LogWarning("[Sonia] Falta la textura " + path);
                return;
            }

            if (importer.textureType == type && importer.sRGBTexture == srgb && importer.mipmapEnabled)
            {
                return;
            }

            importer.textureType = type;
            importer.sRGBTexture = srgb;
            importer.mipmapEnabled = true;
            importer.SaveAndReimport();
        }

        private static Material BuildMaterial()
        {
            Material material = AssetDatabase.LoadAssetAtPath<Material>(MaterialPath);
            Shader shader = Shader.Find("Universal Render Pipeline/Lit");
            if (material == null)
            {
                material = new Material(shader);
                AssetDatabase.CreateAsset(material, MaterialPath);
            }
            else if (shader != null && material.shader != shader)
            {
                material.shader = shader;
            }

            material.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(AlbedoPath));
            material.SetColor("_BaseColor", Color.white);
            material.SetTexture("_BumpMap", AssetDatabase.LoadAssetAtPath<Texture2D>(NormalPath));
            material.SetFloat("_BumpScale", 1f);
            material.EnableKeyword("_NORMALMAP");
            material.SetTexture("_MetallicGlossMap", AssetDatabase.LoadAssetAtPath<Texture2D>(MaskPath));
            material.EnableKeyword("_METALLICSPECGLOSSMAP");
            material.SetFloat("_Smoothness", 1f);
            material.SetFloat("_SmoothnessTextureChannel", 0f);
            // A dos caras, como el material original (el ala y las palas son finas).
            material.SetFloat("_Cull", 0f);
            material.doubleSidedGI = true;
            EditorUtility.SetDirty(material);
            AssetDatabase.SaveAssets();
            return material;
        }

        private static void BuildPrefab(Material material)
        {
            GameObject source = AssetDatabase.LoadAssetAtPath<GameObject>(ModelPath);
            GameObject root = new GameObject("NooglerCap");
            try
            {
                GameObject model = UnityEngine.Object.Instantiate(source, root.transform, false);
                model.name = "Modelo";
                foreach (Renderer renderer in model.GetComponentsInChildren<Renderer>(true))
                {
                    Material[] materials = new Material[renderer.sharedMaterials.Length];
                    for (int i = 0; i < materials.Length; i++)
                    {
                        materials[i] = material;
                    }

                    renderer.sharedMaterials = materials;
                }

                // Unity convierte el FBX de Blender como (x, z, y), con la visera hacia
                // -Z; el gorro tiene que mirar a +Z, como el avatar, y todas las medidas
                // (coronilla, hélice y puntos de encajar.py) van en (-x, z, -y): media
                // vuelta en Y. Se mira la visera por si otra versión lo importa ya bien.
                Bounds modelBounds = new Bounds(Vector3.zero, Vector3.zero);
                foreach (Renderer renderer in model.GetComponentsInChildren<Renderer>(true))
                {
                    modelBounds.Encapsulate(renderer.bounds);
                }

                if (modelBounds.center.z < 0f)
                {
                    // Sobre el giro que ya trae el FBX al importarse, no en su lugar.
                    model.transform.localRotation = Quaternion.Euler(0f, 180f, 0f) * model.transform.localRotation;
                }

                TriviaCapRig rig = root.AddComponent<TriviaCapRig>();
                rig.propeller = FindDeep(model.transform, "Propeller");
                Metadata meta = ReadJson<Metadata>(MetadataPath);
                if (meta != null)
                {
                    // Blender (x, y, z) con Z arriba y la visera hacia -Y -> Unity (-x, z, -y).
                    rig.apex = FromBlender(meta.apex);
                    rig.openingWidth = meta.opening_width;
                    rig.openingDepth = meta.opening_depth;
                    if (meta.grip_points != null && meta.grip_points.Length == 6 && meta.grip_normals != null && meta.grip_normals.Length == 6)
                    {
                        rig.gripPoints = new[] { FromBlender(meta.grip_points, 0), FromBlender(meta.grip_points, 3) };
                        rig.gripNormals = new[] { FromBlender(meta.grip_normals, 0).normalized, FromBlender(meta.grip_normals, 3).normalized };
                    }

                    if (rig.propeller != null && meta.propeller_axis != null && meta.propeller_axis.Length == 3)
                    {
                        // Del espacio del gorro al de la hélice: así da igual cómo
                        // haya convertido los ejes el FBX.
                        Vector3 axis = root.transform.TransformDirection(FromBlender(meta.propeller_axis));
                        rig.propellerAxis = rig.propeller.InverseTransformDirection(axis).normalized;
                    }
                }

                Fit fit = ReadJson<Fit>(FitPath);
                rig.fitted = fit != null && fit.position.Length == 3 && fit.rotation.Length == 4 && fit.scale > 0f;
                if (rig.fitted)
                {
                    rig.headPosition = new Vector3(fit.position[0], fit.position[1], fit.position[2]);
                    rig.headRotation = new Quaternion(fit.rotation[0], fit.rotation[1], fit.rotation[2], fit.rotation[3]).normalized;
                    rig.headScale = fit.scale;
                }
                else
                {
                    Debug.LogWarning("[Sonia] Sin " + FitPath + ": el gorro irá en la colocación aproximada de TriviaHat.");
                }

                Directory.CreateDirectory(Path.GetDirectoryName(PrefabPath));
                PrefabUtility.SaveAsPrefabAsset(root, PrefabPath);
                Bounds bounds = new Bounds(Vector3.zero, Vector3.zero);
                foreach (Renderer renderer in model.GetComponentsInChildren<Renderer>(true))
                {
                    bounds.Encapsulate(renderer.bounds);
                }

                Debug.Log("[Sonia] Gorro Noogler en " + PrefabPath + ": hélice " + (rig.propeller != null ? rig.propeller.name + " (eje local " + rig.propellerAxis.ToString("F3") + ")" : "(no encontrada)")
                          + ", boca " + rig.openingWidth.ToString("0.000") + " x " + rig.openingDepth.ToString("0.000")
                          + " m, agarre " + (rig.gripPoints.Length == 2 ? rig.gripPoints[0].ToString("F3") + " y " + rig.gripPoints[1].ToString("F3") : "(sin puntos)")
                          + " m, límites " + bounds.min.ToString("F3") + " .. " + bounds.max.ToString("F3")
                          + (rig.fitted ? ", encajado en la cabeza (escala " + rig.headScale.ToString("0.000") + ", error " + fit.error_mm.ToString("0.0") + " mm)" : ", sin encaje medido"));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(root);
            }
        }

        [MenuItem("Sonia/Medir gorra oficial (gorro Noogler)")]
        public static void MeasureOfficialCap()
        {
            if (!EditorApplication.isPlaying)
            {
                Debug.LogError("[Sonia] Medir la gorra oficial: hace falta Play, con el avatar de Sonia cargado y la gorra puesta.");
                return;
            }

            TriviaHat trivia = UnityEngine.Object.FindFirstObjectByType<TriviaHat>(FindObjectsInactive.Include);
            GameObject sonia = trivia != null ? trivia.gameObject : GameObject.Find("Sonia");
            AvatarBinder binder = sonia != null ? sonia.GetComponentInChildren<AvatarBinder>(true) : null;
            Transform avatar = binder != null ? binder.Current : null;
            Animator animator = avatar != null ? avatar.GetComponentInChildren<Animator>(true) : null;
            Transform head = animator != null && animator.isHuman ? animator.GetBoneTransform(HumanBodyBones.Head) : null;
            if (head == null)
            {
                Debug.LogError("[Sonia] Medir la gorra oficial: no encuentro la cabeza del avatar de Sonia.");
                return;
            }

            var parts = new System.Collections.Generic.List<TriviaHat.HatPart>();
            TriviaHat.FindHatParts(avatar, head, parts);
            if (parts.Count == 0)
            {
                Debug.LogError("[Sonia] Medir la gorra oficial: Sonia no lleva ninguna gorra (ninguna submalla de ropa por encima de la coronilla).");
                return;
            }

            // Los triángulos de las submallas del gorro, con sus vértices horneados en la pose de ahora.
            var vertices = new System.Collections.Generic.List<Vector3>();
            var normals = new System.Collections.Generic.List<Vector3>();
            var triangles = new System.Collections.Generic.List<int>();
            StringBuilder names = new StringBuilder();
            Mesh baked = new Mesh();
            foreach (TriviaHat.HatPart part in parts)
            {
                part.Renderer.BakeMesh(baked, true);
                Vector3[] bakedVertices = baked.vertices;
                Vector3[] bakedNormals = baked.normals;
                Matrix4x4 toWorld = part.Renderer.transform.localToWorldMatrix;
                var remap = new System.Collections.Generic.Dictionary<int, int>();
                foreach (int index in part.Renderer.sharedMesh.GetIndices(part.SubMesh))
                {
                    if (!remap.TryGetValue(index, out int mapped))
                    {
                        mapped = vertices.Count;
                        remap[index] = mapped;
                        vertices.Add(head.InverseTransformPoint(toWorld.MultiplyPoint3x4(bakedVertices[index])));
                        normals.Add(head.InverseTransformDirection(toWorld.MultiplyVector(bakedNormals[index]).normalized));
                    }

                    triangles.Add(mapped);
                }

                names.Append(names.Length > 0 ? ", " : string.Empty).Append(part.Renderer.name).Append(" submalla ").Append(part.SubMesh);
            }

            UnityEngine.Object.DestroyImmediate(baked);
            CultureInfo inv = CultureInfo.InvariantCulture;
            StringBuilder json = new StringBuilder(vertices.Count * 64);
            json.Append("{\"renderer\":\"").Append(names).Append("\",\"vertices\":[");
            for (int i = 0; i < vertices.Count; i++)
            {
                AppendVector(json, vertices[i], i > 0, inv);
            }

            json.Append("],\"normals\":[");
            for (int i = 0; i < normals.Count; i++)
            {
                AppendVector(json, normals[i], i > 0, inv);
            }

            json.Append("],\"triangles\":[");
            for (int i = 0; i < triangles.Count; i++)
            {
                json.Append(i > 0 ? "," : string.Empty).Append(triangles[i].ToString(inv));
            }

            json.Append("],\"up\":");
            AppendVector(json, head.InverseTransformDirection(avatar.up), false, inv);
            json.Append(",\"forward\":");
            AppendVector(json, head.InverseTransformDirection(avatar.forward), false, inv);
            json.Append(",\"head_scale\":").Append(head.lossyScale.y.ToString("R", inv)).Append('}');

            string path = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "scripts", "gorro_noogler", "trabajo", "gorra_oficial.json"));
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllText(path, json.ToString());
            Debug.Log("[Sonia] Gorra oficial medida (" + names + "): " + vertices.Count + " vértices y " + (triangles.Count / 3)
                      + " triángulos en el espacio del hueso de la cabeza. Guardada en " + path);
        }

        private static void AppendVector(StringBuilder json, Vector3 v, bool comma, CultureInfo inv)
        {
            json.Append(comma ? ",[" : "[").Append(v.x.ToString("R", inv)).Append(',').Append(v.y.ToString("R", inv)).Append(',').Append(v.z.ToString("R", inv)).Append(']');
        }

        private static T ReadJson<T>(string path)
            where T : class
        {
            TextAsset text = AssetDatabase.LoadAssetAtPath<TextAsset>(path);
            return text != null ? JsonUtility.FromJson<T>(text.text) : null;
        }

        private static Vector3 FromBlender(float[] v, int start = 0)
        {
            return v != null && v.Length >= start + 3 ? new Vector3(-v[start], v[start + 2], -v[start + 1]) : Vector3.zero;
        }

        private static Transform FindDeep(Transform parent, string name)
        {
            foreach (Transform child in parent.GetComponentsInChildren<Transform>(true))
            {
                if (child.name == name)
                {
                    return child;
                }
            }

            return null;
        }
    }
}

#endif
