// Copia local del avatar del SDK de Genies: la captura (ver SoniaGeniesSnapshot.cs
// para cuándo se hace).
//
// Qué se guarda y por qué:
//
//  * Mallas: copia exacta de las que montó el SDK, con las 84 formas FACS de la
//    cara. Son legibles en CPU, así que basta con clonarlas.
//  * Materiales: los mismos shaders del SDK (MegaSkin, MegaHair, MegaEyes,
//    MegaFlair, URP/Lit) con todas sus propiedades. Las texturas que ya son
//    assets del paquete se referencian tal cual; las que el SDK descargó o
//    generó en tiempo de ejecución (ASTC sin mipmaps, el RenderTexture de los
//    tatuajes) se leen por GPU respetando sRGB o lineal y se guardan en PNG, de
//    modo que el shader recibe los mismos valores.
//  * Esqueleto: la pose de reposo tal cual la dejó el SDK, con las medidas de
//    la cara (SkeletonModifierBehaviour escala y gira huesos de nariz, boca,
//    mandíbula y cuencas en cada fotograma) ya aplicadas. Nada anima esos
//    huesos, así que se hornean y el componente sobra. Los ojos vuelven al
//    reposo que guardó EyeGazeController y el pelo a la pose de casa de sus
//    partículas.
//  * Físicas del pelo: las DynamicsStructure de Genies se copian tal cual (son
//    componentes serializables) y siguen funcionando sin el SDK.
//  * Avatar Humanoid: copia del que construyó el SDK (mismo HumanDescription).
//  * Definición: GeniesAvatarSnapshot guarda el JSON del que salió.
//  * Fuera: los componentes nativos del SDK (NativeGenie, ManagedAvatar...),
//    que solo sirven para montar y descargar.

#if UNITY_EDITOR

using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEditor;
using UnityEngine;
using UnityEngine.Experimental.Rendering;
using Object = UnityEngine.Object;

namespace Sonia.EditorTools
{
    public static partial class SoniaGeniesSnapshot
    {
        /// <summary>Paquete embebido del SDK, para anotar su versión.</summary>
        private const string SdkPackagePath = "Packages/com.genies.avatar-sdk.client";

        /// <summary>Componentes del SDK que solo sirven para montar y descargar el avatar. El orden importa: NativeGenieBuilder depende de NativeGenie.</summary>
        private static readonly string[] SdkOnlyComponents =
        {
            "SkinnedNativeMeshRenderer",
            "NativeMultiMeshBuilder",
            "BlendShapeAnimatorBehaviour",
            "ManagedAvatarComponent",
            "GenieReference",
            "NativeGenieBuilder",
            "NativeGenie"
        };

        private const string SkeletonModifierType = "SkeletonModifierBehaviour";
        private const string RigBuilderType = "RigBuilder";
        private const string SkeletonModifierRigName = "SkeletonModifierRig";
        private const string ParticleType = "DynamicsParticle";

        /// <summary>Ajustes de importación de cada PNG que se está escribiendo (los aplica el postprocesador).</summary>
        private static readonly Dictionary<string, TextureSettings> PendingTextures = new Dictionary<string, TextureSettings>();

        // ------------------------------------------------------------------
        // Copia
        // ------------------------------------------------------------------

        /// <summary>
        /// Guarda como prefab el avatar del SDK que está enganchado ahora (en Play).
        /// Devuelve la ruta del prefab, o null si no hay avatar del SDK.
        /// </summary>
        public static string Capture(GeniesAvatarLoader loader)
        {
            if (!EditorApplication.isPlaying || loader == null || !loader.IsLoaded)
            {
                Debug.LogError("[Sonia] La copia se hace en Play, con el avatar del SDK ya cargado.");
                return null;
            }

            AvatarBinder binder = loader.GetComponent<AvatarBinder>();
            if (binder == null)
            {
                binder = loader.GetComponentInParent<AvatarBinder>();
            }

            Transform live = binder != null ? binder.Current : null;
            Animator liveAnimator = live != null ? live.GetComponent<Animator>() : null;
            if (live == null || live.GetComponent<GeniesAvatarSnapshot>() != null || liveAnimator == null
                || liveAnimator.avatar == null || !liveAnimator.avatar.isHuman)
            {
                Debug.LogError("[Sonia] El avatar enganchado no es el del SDK con un Humanoid válido; no se copia.");
                return null;
            }

            // La definición que lleva Sonia (la de set_avatar o la de la app).
            TextAsset definition = loader.Definition;
            string json = !string.IsNullOrEmpty(loader.ShownDefinition)
                ? loader.ShownDefinition
                : (definition != null ? definition.text : string.Empty);
            System.Diagnostics.Stopwatch clock = System.Diagnostics.Stopwatch.StartNew();
            string folder = SnapshotFolder;
            string prefabPath = SnapshotPrefabPath;
            EnsureFolder(folder);
            EnsureFolder(folder + "/Meshes");
            EnsureFolder(folder + "/Materials");
            EnsureFolder(folder + "/Textures");

            // La copia se monta bajo un padre inactivo: así no corre el Awake de
            // nada (ni de los componentes del SDK, que tocarían su parte nativa).
            GameObject holder = new GameObject("Copia del avatar (temporal)");
            holder.SetActive(false);
            HashSet<string> written = new HashSet<string>();
            try
            {
                GameObject copy = Object.Instantiate(live.gameObject, holder.transform, false);
                copy.name = Path.GetFileName(folder);
                copy.transform.localPosition = Vector3.zero;
                copy.transform.localRotation = Quaternion.identity;
                copy.transform.localScale = Vector3.one;

                Dictionary<string, Transform> bones = IndexByName(copy.transform);
                HashSet<string> humanBones = new HashSet<string>();
                foreach (HumanBone bone in liveAnimator.avatar.humanDescription.human)
                {
                    humanBones.Add(bone.boneName);
                }

                RestoreEyes(live, bones);
                RestoreHair(copy);
                BakeSkeletonModifier(copy, humanBones);
                RemoveSdkComponents(copy);

                Animator animator = copy.GetComponent<Animator>();
                animator.avatar = SaveAvatar(liveAnimator.avatar, copy, folder + "/" + copy.name + "Avatar.asset", written);
                animator.runtimeAnimatorController = null;
                animator.applyRootMotion = false;
                animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;

                SaveRenderers(copy, folder, written);

                GeniesAvatarSnapshot marker = copy.AddComponent<GeniesAvatarSnapshot>();
                marker.Describe(json,
                                definition != null ? definition.name : string.Empty,
                                SdkVersion(),
                                LoaderQuality(loader));

                bool saved;
                PrefabUtility.SaveAsPrefabAsset(copy, prefabPath, out saved);
                if (!saved)
                {
                    Debug.LogError("[Sonia] No se pudo guardar " + prefabPath + ".");
                    return null;
                }

                written.Add(prefabPath);
            }
            finally
            {
                Object.DestroyImmediate(holder);
            }

            RemoveStale(folder, written);
            AssetDatabase.SaveAssets();
            Debug.Log("[Sonia] Copia del avatar del SDK guardada en " + prefabPath + " (" + written.Count + " assets, SDK "
                      + SdkVersion() + ", " + (clock.ElapsedMilliseconds / 1000f).ToString("F1") + " s).");
            return prefabPath;
        }

        /// <summary>Los ojos los mueve la mirada: vuelven al reposo que guardó EyeGazeController al engancharlos.</summary>
        private static void RestoreEyes(Transform live, Dictionary<string, Transform> bones)
        {
            EyeGazeController gaze = Object.FindAnyObjectByType<EyeGazeController>();
            if (gaze == null)
            {
                return;
            }

            const BindingFlags Flags = BindingFlags.Instance | BindingFlags.NonPublic;
            Type type = typeof(EyeGazeController);
            RestoreEye(live, bones, type.GetField("leftEye", Flags), type.GetField("_leftRest", Flags), gaze);
            RestoreEye(live, bones, type.GetField("rightEye", Flags), type.GetField("_rightRest", Flags), gaze);
        }

        private static void RestoreEye(Transform live, Dictionary<string, Transform> bones, FieldInfo eyeField,
                                       FieldInfo restField, EyeGazeController gaze)
        {
            Transform eye = eyeField != null ? eyeField.GetValue(gaze) as Transform : null;
            Transform target;
            if (eye == null || !eye.IsChildOf(live) || restField == null || !bones.TryGetValue(eye.name, out target))
            {
                Debug.LogWarning("[Sonia] No se encontró el reposo de un ojo; se queda la rotación que tenía.");
                return;
            }

            target.localRotation = (Quaternion)restField.GetValue(gaze);
        }

        /// <summary>El pelo con físicas vuelve a la pose de casa de cada partícula (la del montaje, sin simular).</summary>
        private static void RestoreHair(GameObject copy)
        {
            foreach (MonoBehaviour behaviour in copy.GetComponentsInChildren<MonoBehaviour>(true))
            {
                if (behaviour == null || behaviour.GetType().Name != ParticleType)
                {
                    continue;
                }

                SerializedObject particle = new SerializedObject(behaviour);
                SerializedProperty position = particle.FindProperty("LocalHomePosition");
                SerializedProperty rotation = particle.FindProperty("LocalHomeRotation");
                if (position == null || rotation == null)
                {
                    continue;
                }

                behaviour.transform.localPosition = position.vector3Value;
                behaviour.transform.localRotation = rotation.quaternionValue;
            }
        }

        /// <summary>
        /// Las medidas de la cara que aplica SkeletonModifierBehaviour ya están en
        /// los huesos copiados. Si alguna fuese de un hueso humanoide (el Animator
        /// lo pisaría), se deja el componente solo con esas y se avisa.
        /// </summary>
        private static void BakeSkeletonModifier(GameObject copy, HashSet<string> humanBones)
        {
            Component modifier = FindComponent(copy, SkeletonModifierType);
            Transform rig = copy.transform.Find(SkeletonModifierRigName);
            if (rig != null)
            {
                // Lleva una restricción anidada que no se puede guardar; si hace
                // falta, el componente la vuelve a crear en su Awake.
                Object.DestroyImmediate(rig.gameObject);
            }

            if (modifier == null)
            {
                return;
            }

            SerializedObject serialized = new SerializedObject(modifier);
            SerializedProperty list = serialized.FindProperty("modifiers");
            int kept = 0;
            for (int i = list.arraySize - 1; i >= 0; i--)
            {
                Transform joint = list.GetArrayElementAtIndex(i).FindPropertyRelative("targetJoint").objectReferenceValue as Transform;
                if (joint != null && humanBones.Contains(joint.name))
                {
                    kept++;
                    continue;
                }

                list.DeleteArrayElementAtIndex(i);
            }

            if (kept == 0)
            {
                Object.DestroyImmediate(modifier);
                Component rigBuilder = FindComponent(copy, RigBuilderType);
                if (rigBuilder != null)
                {
                    Object.DestroyImmediate(rigBuilder);
                }

                return;
            }

            serialized.ApplyModifiedPropertiesWithoutUndo();
            Component builder = FindComponent(copy, RigBuilderType);
            if (builder != null)
            {
                SerializedObject builderObject = new SerializedObject(builder);
                SerializedProperty layers = builderObject.FindProperty("m_RigLayers");
                if (layers != null)
                {
                    layers.ClearArray();
                    builderObject.ApplyModifiedPropertiesWithoutUndo();
                }
            }

            Debug.LogWarning("[Sonia] El avatar tiene " + kept + " medidas sobre huesos humanoides: se mantiene el "
                             + "SkeletonModifierBehaviour de Genies para ellas. Revisa la copia en Play.");
        }

        private static void RemoveSdkComponents(GameObject copy)
        {
            foreach (string typeName in SdkOnlyComponents)
            {
                foreach (Component component in copy.GetComponentsInChildren<Component>(true))
                {
                    if (component != null && component.GetType().Name == typeName)
                    {
                        Object.DestroyImmediate(component);
                    }
                }
            }
        }

        private static Avatar SaveAvatar(Avatar live, GameObject copy, string path, HashSet<string> written)
        {
            Avatar avatar = null;
            try
            {
                avatar = Object.Instantiate(live);
            }
            catch (Exception)
            {
                avatar = null;
            }

            if (avatar == null || !avatar.isValid || !avatar.isHuman)
            {
                avatar = AvatarBuilder.BuildHumanAvatar(copy, live.humanDescription);
            }

            avatar.name = Path.GetFileNameWithoutExtension(path);
            written.Add(path);
            return SaveAsset(avatar, path);
        }

        /// <summary>Mallas, materiales y texturas de cada renderer, como assets del proyecto.</summary>
        private static void SaveRenderers(GameObject copy, string folder, HashSet<string> written)
        {
            Dictionary<Material, Material> materials = new Dictionary<Material, Material>();
            Dictionary<Texture, Texture> textures = new Dictionary<Texture, Texture>();
            HashSet<string> textureNames = new HashSet<string>();

            foreach (SkinnedMeshRenderer renderer in copy.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                Mesh live = renderer.sharedMesh;
                if (live != null)
                {
                    Mesh mesh = Object.Instantiate(live);
                    mesh.name = live.name;
                    string meshPath = folder + "/Meshes/" + SafeName(renderer.name) + ".asset";
                    written.Add(meshPath);
                    renderer.sharedMesh = SaveAsset(mesh, meshPath);
                    for (int i = 0; i < renderer.sharedMesh.blendShapeCount; i++)
                    {
                        renderer.SetBlendShapeWeight(i, 0f);
                    }
                }

                Material[] slots = renderer.sharedMaterials;
                for (int i = 0; i < slots.Length; i++)
                {
                    Material source = slots[i];
                    if (source == null || EditorUtility.IsPersistent(source))
                    {
                        continue;
                    }

                    Material saved;
                    if (!materials.TryGetValue(source, out saved))
                    {
                        string materialPath = folder + "/Materials/" + SafeName(renderer.name) + "_" + i + "_"
                                              + SafeName(source.name) + ".mat";
                        saved = SaveMaterial(source, materialPath, folder, textures, textureNames, written);
                        written.Add(materialPath);
                        materials.Add(source, saved);
                    }

                    slots[i] = saved;
                }

                renderer.sharedMaterials = slots;
            }
        }

        private static Material SaveMaterial(Material source, string path, string folder, Dictionary<Texture, Texture> textures,
                                             HashSet<string> textureNames, HashSet<string> written)
        {
            Material material = new Material(source);
            material.name = Path.GetFileNameWithoutExtension(path);
            foreach (string property in source.GetTexturePropertyNames())
            {
                Texture texture = source.GetTexture(property);
                if (texture == null || EditorUtility.IsPersistent(texture))
                {
                    continue;
                }

                Texture saved;
                if (!textures.TryGetValue(texture, out saved))
                {
                    saved = SaveTexture(texture, source.name + property, folder, textureNames, written);
                    textures.Add(texture, saved);
                }

                material.SetTexture(property, saved);
            }

            return SaveAsset(material, path);
        }

        /// <summary>
        /// Lee la textura por GPU (sirve para las comprimidas y los RenderTexture)
        /// y la guarda en PNG con la misma codificación: si era sRGB, se copia
        /// por un destino sRGB y se importa como sRGB; si era lineal, lineal.
        /// Los arrays de texturas (los tatuajes de la piel) se guardan como una
        /// tira vertical de capas, la primera arriba, y se importan como
        /// Texture2DArray.
        /// </summary>
        private static Texture SaveTexture(Texture source, string fallbackName, string folder, HashSet<string> names,
                                           HashSet<string> written)
        {
            Texture2D source2D = source as Texture2D;
            RenderTexture sourceRT = source as RenderTexture;
            Texture2DArray sourceArray = source as Texture2DArray;
            bool srgb = source2D != null ? source2D.isDataSRGB
                : sourceRT != null ? sourceRT.sRGB
                : sourceArray != null && GraphicsFormatUtility.IsSRGBFormat(sourceArray.graphicsFormat);
            bool mips = source2D != null ? source2D.mipmapCount > 1
                : sourceRT != null ? sourceRT.useMipMap
                : sourceArray != null && sourceArray.mipmapCount > 1;
            int layers = source.dimension == UnityEngine.Rendering.TextureDimension.Tex2DArray
                ? (sourceRT != null ? sourceRT.volumeDepth : sourceArray != null ? sourceArray.depth : 1)
                : 0;

            string name = TextureName(source.name, fallbackName);
            string unique = name;
            for (int n = 2; !names.Add(unique); n++)
            {
                unique = name + "_" + n;
            }

            string path = folder + "/Textures/" + unique + ".png";
            Texture2D pixels = Readback(source, srgb, Mathf.Max(1, layers));
            try
            {
                File.WriteAllBytes(FullPath(path), pixels.EncodeToPNG());
            }
            finally
            {
                Object.DestroyImmediate(pixels);
            }

            PendingTextures[path] = new TextureSettings
            {
                Srgb = srgb,
                Mips = mips,
                Wrap = source.wrapMode,
                Filter = source.filterMode,
                Aniso = source.anisoLevel,
                MaxSize = Mathf.Max(source.width, source.height * Mathf.Max(1, layers)),
                Layers = layers
            };
            try
            {
                AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate | ImportAssetOptions.ForceSynchronousImport);
            }
            finally
            {
                PendingTextures.Remove(path);
            }

            written.Add(path);
            Texture saved = layers > 0
                ? (Texture)AssetDatabase.LoadAssetAtPath<Texture2DArray>(path)
                : AssetDatabase.LoadAssetAtPath<Texture2D>(path);
            if (layers > 0)
            {
                CheckLayers(source, saved, layers, srgb);
            }

            return saved;
        }

        /// <summary>
        /// Copia la textura (o cada capa de un array, apiladas de arriba abajo) a
        /// una textura RGBA32 legible, sin cambiar los valores de los texels.
        /// </summary>
        private static Texture2D Readback(Texture source, bool srgb, int layers)
        {
            int width = source.width;
            int height = source.height;
            RenderTextureDescriptor descriptor = new RenderTextureDescriptor(
                width, height, srgb ? GraphicsFormat.R8G8B8A8_SRGB : GraphicsFormat.R8G8B8A8_UNorm, 0);
            descriptor.useMipMap = false;
            descriptor.autoGenerateMips = false;
            RenderTexture target = RenderTexture.GetTemporary(descriptor);
            RenderTexture previous = RenderTexture.active;
            bool isArray = source.dimension == UnityEngine.Rendering.TextureDimension.Tex2DArray;
            try
            {
                Texture2D pixels = new Texture2D(width, height * layers, TextureFormat.RGBA32, false, !srgb);
                for (int layer = 0; layer < layers; layer++)
                {
                    if (isArray)
                    {
                        Graphics.Blit(source, target, layer, 0);
                    }
                    else
                    {
                        Graphics.Blit(source, target);
                    }

                    RenderTexture.active = target;
                    pixels.ReadPixels(new Rect(0, 0, width, height), 0, (layers - 1 - layer) * height, false);
                }

                pixels.Apply(false, false);
                return pixels;
            }
            finally
            {
                RenderTexture.active = previous;
                RenderTexture.ReleaseTemporary(target);
            }
        }

        /// <summary>Comprueba que cada capa del array importado es la misma que la del original (color medio).</summary>
        private static void CheckLayers(Texture source, Texture saved, int layers, bool srgb)
        {
            if (saved == null)
            {
                Debug.LogError("[Sonia] El array de texturas " + source.name + " no se importó como Texture2DArray.");
                return;
            }

            Texture2D original = Readback(source, srgb, layers);
            Texture2D copy = Readback(saved, srgb, layers);
            try
            {
                int height = source.height;
                for (int layer = 0; layer < layers; layer++)
                {
                    Color a = Mean(original, (layers - 1 - layer) * height, height);
                    Color b = Mean(copy, (layers - 1 - layer) * height, height);
                    float difference = Mathf.Max(Mathf.Abs(a.r - b.r), Mathf.Abs(a.g - b.g), Mathf.Abs(a.b - b.b), Mathf.Abs(a.a - b.a));
                    if (difference > 0.02f)
                    {
                        Debug.LogWarning("[Sonia] La capa " + layer + " del array " + saved.name + " no coincide con la original (diferencia media "
                                         + difference.ToString("F3") + ").");
                    }
                }
            }
            finally
            {
                Object.DestroyImmediate(original);
                Object.DestroyImmediate(copy);
            }
        }

        private static Color Mean(Texture2D pixels, int y, int height)
        {
            Color32[] data = pixels.GetPixels32();
            int width = pixels.width;
            double r = 0, g = 0, b = 0, a = 0;
            int count = 0;
            for (int row = y; row < y + height; row += 4)
            {
                for (int column = 0; column < width; column += 4)
                {
                    Color32 c = data[row * width + column];
                    r += c.r;
                    g += c.g;
                    b += c.b;
                    a += c.a;
                    count++;
                }
            }

            float scale = 1f / (255f * Mathf.Max(1, count));
            return new Color((float)(r * scale), (float)(g * scale), (float)(b * scale), (float)(a * scale));
        }

        /// <summary>Aplica los ajustes de importación de un PNG de la copia (lo llama el postprocesador).</summary>
        internal static void ApplyPendingSettings(string path, TextureImporter importer)
        {
            TextureSettings settings;
            if (importer == null || !PendingTextures.TryGetValue(path, out settings))
            {
                return;
            }

            importer.textureType = TextureImporterType.Default;
            if (settings.Layers > 0)
            {
                TextureImporterSettings shape = new TextureImporterSettings();
                importer.ReadTextureSettings(shape);
                shape.textureShape = TextureImporterShape.Texture2DArray;
                shape.flipbookColumns = 1;
                shape.flipbookRows = settings.Layers;
                importer.SetTextureSettings(shape);
            }
            else
            {
                importer.textureShape = TextureImporterShape.Texture2D;
            }

            importer.sRGBTexture = settings.Srgb;
            importer.alphaSource = TextureImporterAlphaSource.FromInput;
            importer.alphaIsTransparency = false;
            importer.mipmapEnabled = settings.Mips;
            importer.streamingMipmaps = false;
            importer.isReadable = false;
            importer.npotScale = TextureImporterNPOTScale.None;
            importer.wrapMode = settings.Wrap;
            importer.filterMode = settings.Filter;
            importer.anisoLevel = settings.Aniso;
            importer.maxTextureSize = Mathf.Clamp(Mathf.NextPowerOfTwo(settings.MaxSize), 32, 16384);
            importer.textureCompression = TextureImporterCompression.CompressedHQ;
            importer.crunchedCompression = false;
        }

        // ------------------------------------------------------------------
        // Utilidades
        // ------------------------------------------------------------------

        /// <summary>Guarda el objeto en la ruta. Si ya existe, lo sobrescribe conservando su GUID (diffs limpios en git).</summary>
        private static T SaveAsset<T>(T asset, string path) where T : Object
        {
            T existing = AssetDatabase.LoadAssetAtPath<T>(path);
            if (existing != null)
            {
                EditorUtility.CopySerialized(asset, existing);
                EditorUtility.SetDirty(existing);
                Object.DestroyImmediate(asset);
                return existing;
            }

            AssetDatabase.CreateAsset(asset, path);
            return asset;
        }

        /// <summary>Borra de la carpeta de la copia lo que no se escribió esta vez (piezas de un avatar anterior).</summary>
        private static void RemoveStale(string folder, HashSet<string> written)
        {
            foreach (string guid in AssetDatabase.FindAssets(string.Empty, new[] { folder }))
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                if (!path.StartsWith(folder + "/", StringComparison.Ordinal) || AssetDatabase.IsValidFolder(path)
                    || written.Contains(path))
                {
                    continue;
                }

                AssetDatabase.DeleteAsset(path);
            }
        }

        private static Dictionary<string, Transform> IndexByName(Transform root)
        {
            Dictionary<string, Transform> bones = new Dictionary<string, Transform>();
            foreach (Transform child in root.GetComponentsInChildren<Transform>(true))
            {
                if (!bones.ContainsKey(child.name))
                {
                    bones.Add(child.name, child);
                }
            }

            return bones;
        }

        private static Component FindComponent(GameObject root, string typeName)
        {
            foreach (Component component in root.GetComponents<Component>())
            {
                if (component != null && component.GetType().Name == typeName)
                {
                    return component;
                }
            }

            return null;
        }

        /// <summary>
        /// Nombre del PNG: el de la textura del SDK sin su prefijo de caché
        /// ("48b7bb061e0f5d73.hair-0128-..._AlbedoTransparency.png") ni extensión.
        /// </summary>
        private static string TextureName(string sdkName, string fallback)
        {
            string name = string.IsNullOrEmpty(sdkName) ? fallback : sdkName;
            int dot = name.IndexOf('.');
            if (dot == 16)
            {
                name = name.Substring(dot + 1);
            }

            if (name.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
            {
                name = name.Substring(0, name.Length - 4);
            }

            return SafeName(name);
        }

        private static string SafeName(string name)
        {
            char[] invalid = Path.GetInvalidFileNameChars();
            char[] chars = name.ToCharArray();
            for (int i = 0; i < chars.Length; i++)
            {
                if (Array.IndexOf(invalid, chars[i]) >= 0 || chars[i] == ' ')
                {
                    chars[i] = '_';
                }
            }

            return new string(chars);
        }

        private static string FullPath(string assetPath)
        {
            return Path.Combine(Path.GetDirectoryName(Application.dataPath), assetPath);
        }

        private static void EnsureFolder(string folder)
        {
            if (AssetDatabase.IsValidFolder(folder))
            {
                return;
            }

            string parent = Path.GetDirectoryName(folder).Replace('\\', '/');
            EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, Path.GetFileName(folder));
        }

        private static string SdkVersion()
        {
            UnityEditor.PackageManager.PackageInfo package = UnityEditor.PackageManager.PackageInfo.FindForAssetPath(SdkPackagePath);
            return package != null ? package.version : "desconocida";
        }

        private static string LoaderQuality(GeniesAvatarLoader loader)
        {
            SerializedProperty quality = new SerializedObject(loader).FindProperty("quality");
            if (quality == null || quality.propertyType != SerializedPropertyType.Enum)
            {
                return string.Empty;
            }

            int index = quality.enumValueIndex;
            return index >= 0 && index < quality.enumDisplayNames.Length ? quality.enumDisplayNames[index] : string.Empty;
        }

        private sealed class TextureSettings
        {
            public bool Srgb;
            public bool Mips;
            public TextureWrapMode Wrap;
            public FilterMode Filter;
            public int Aniso;
            public int MaxSize;

            /// <summary>Capas si es un array de texturas (tira vertical); 0 si es una textura 2D normal.</summary>
            public int Layers;
        }
    }

    /// <summary>Da a los PNG de la copia del avatar sus ajustes de importación la primera vez que se importan.</summary>
    internal sealed class SoniaGeniesSnapshotTextures : AssetPostprocessor
    {
        private void OnPreprocessTexture()
        {
            SoniaGeniesSnapshot.ApplyPendingSettings(assetPath, assetImporter as TextureImporter);
        }
    }
}

#endif
