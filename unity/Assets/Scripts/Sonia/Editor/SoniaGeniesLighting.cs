// "Sonia > Iluminación estilo Genies": la luz de la demo Mia de genies.com
// (genies.com/chat/mia) trasladada de su runtime web (three.js) a URP.
//
// Mia descarga https://d344oyp4d2jz0e.cloudfront.net/naf/scene.json, su LUT y su
// HDR (ver Assets/Sonia/Lighting/LEEME.md); el "ArtHub Visual Runtime" pone sus
// valores por defecto a lo que falta. Lo que de verdad se ve en Mia y cómo queda
// aquí:
//
//   three.js (Mia)                            URP (Sonia)
//   Direccional #ffd8b8 × 2, rotación         Direccional principal #ffd8b8 × 2/π × 0,85,
//     x 12,44 e y 10,78 (casi de frente,        Euler (12,44; 10,78; 0), sombra suave entera.
//     algo a la izquierda y baja)
//   AmbientLight #b5b5b5 × 1 (hemisferio      Ambiente SH (SoniaGeniesLook):
//     apagado) + HDR × 0,5 de entorno           0,85 × (#b5b5b5 / π + 0,5 × HDR) + 0,15.
//   megaStylizer flatness 0,15                (el 0,85 y el 0,15 de arriba: menos difuso
//                                              y un 15 % de albedo sin sombrear)
//   megaStylizer LightA #ffb189, α 0,33       Rim cálido: direccional sin sombra que gira
//     (vista: arriba a la derecha, detrás)      con la cámara.
//   megaStylizer LightB #a9d2ff, α 0,45       Rim frío: abajo a la izquierda, detrás.
//   Reflejos del HDR × 0,5                    Reflejo por defecto: cubemap del HDR × 0,5.
//   toneMapping Linear, exposición 1          Tonemapping None (el grading LDR recorta a 1).
//   LUT CCNeutralTonemapFilmic tras la        Color Lookup con el mismo LUT en tira 32³
//     salida sRGB                               (URP también lo aplica en sRGB).
//   Sin bloom, viñeta ni SSAO                 Bloom y ajustes de color fuera. La viñeta navy
//                                              y el desenfoque del telón se quedan (marca).
//   ShadowMaterial negro al 40 % en y = 0     Sonia/Shadow Catcher, con borde desvanecido.
//
// ÷π: three.js usa luces físicas (difuso = albedo / π × irradiancia) y URP mete
// la π en la intensidad (difuso = albedo × intensidad). Ejes: en Mia el avatar
// mira a +Z con la cámara en +Z; aquí mira a −Z con la cámara en −Z, así que una
// dirección (x, y, z) de three.js es (x, y, −z) en Unity.
//
// El telón, el halo, las motas y el logo no cambian. Los focos del estudio se
// apagan (no se borran) y todo vuelve con "Sonia > Iluminación de estudio".

#if UNITY_EDITOR

using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.SceneManagement;

namespace Sonia.EditorTools
{
    /// <summary>Monta y quita la iluminación estilo Genies (demo Mia).</summary>
    public static class SoniaGeniesLighting
    {
        /// <summary>Objeto raíz con todo lo que añade esta iluminación.</summary>
        public const string RigName = "SoniaGeniesLight";

        private const string StageName = "SoniaStage";
        private const string WarmRimName = "RimCalido";
        private const string CoolRimName = "RimFrio";
        private const string CatcherName = "ShadowCatcher";
        private const string Folder = "Assets/Sonia/Lighting";
        private const string LutPath = Folder + "/GeniesLut_CCNeutralTonemapFilmicLUT_09_SP_32.png";
        private const string EnvironmentPath = Folder + "/GeniesEnv_composer_hdr_v02_cube_90_3JS_07_512_unity.exr";
        private const string CatcherMaterialPath = Folder + "/SoniaShadowCatcher.mat";
        private const string CatcherShaderName = "Sonia/Shadow Catcher";
        private const string UndoName = "Iluminación estilo Genies";

        /// <summary>megaStylizer.flatness: parte del albedo que va sin sombrear.</summary>
        private const float Flatness = 0.15f;

        // Direccional de scene.json: #ffd8b8 × 2.
        private static readonly Color KeyColor = new Color(1f, 216f / 255f, 184f / 255f);
        private const float KeyIntensity = 2f / Mathf.PI * (1f - Flatness);
        private static readonly Vector3 KeyEuler = new Vector3(12.44f, 10.78f, 0f);

        // Rims (megaStylizer LightA y LightB). Dirección hacia la luz en el espacio
        // de la cámara de Unity, sacada del ecuador y la altura de cada luz: en vista
        // de three.js (cos p·cos(270−e), sin p, cos p·sin(270−e)), con z invertida.
        // La intensidad es el ajuste por mínimos cuadrados de un Lambert a la rampa
        // del estilizador sobre las normales que miran a cámara, algo rebajado.
        private static readonly Color WarmRimColor = new Color(1f, 177f / 255f, 137f / 255f);
        private static readonly Color CoolRimColor = new Color(169f / 255f, 210f / 255f, 1f);
        private static readonly Vector3 WarmRimView = new Vector3(0.5906f, 0.5f, 0.6334f);
        private static readonly Vector3 CoolRimView = new Vector3(-0.5090f, -0.5f, 0.7006f);
        private const float WarmRimIntensity = 0.6f;
        private const float CoolRimIntensity = 0.75f;

        // Ambiente: 0,85 × (0,5 × HDR convolucionado + #b5b5b5 / π) + 0,15, en el
        // formato de SphericalHarmonicsL2 (9 rojos, 9 verdes, 9 azules), calculado
        // con scripts/iluminacion_genies/env_to_sh.py a partir del EXR de Mia (ver LEEME.md).
        private static readonly float[] AmbientCoefficients =
        {
            0.589957f, 0.106199f, 0.030030f, -0.055000f, -0.023375f, -0.078945f, 0.000214f, -0.073328f, 0.103216f,
            0.611013f, 0.084198f, 0.118732f, -0.051366f, -0.022542f, -0.039475f, -0.021248f, -0.081282f, 0.136471f,
            0.700396f, 0.076729f, 0.215254f, -0.045807f, -0.021915f, -0.020275f, -0.044566f, -0.093653f, 0.196985f,
        };

        private const float ReflectionIntensity = 0.5f;
        private const float CatcherOpacity = 0.4f;
        private const float CatcherFadeStart = 0.8f;
        private const float CatcherFadeEnd = 1.6f;

        [MenuItem("Sonia/Iluminación estilo Genies")]
        public static void ApplyMenu()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
            {
                EditorUtility.DisplayDialog("Sonia", "Sal de Play: la iluminación se guarda con la escena.", "Vale");
                return;
            }

            Scene scene = SceneManager.GetActiveScene();
            Camera camera = Camera.main;
            if (camera == null)
            {
                EditorUtility.DisplayDialog("Sonia", "Hace falta una cámara principal.", "Vale");
                return;
            }

            if (!Apply(scene, camera))
            {
                EditorUtility.DisplayDialog(
                    "Sonia", "Faltan recursos en " + Folder + " (LUT, HDR o shader). Mira la consola.", "Vale");
                return;
            }

            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
        }

        /// <summary>Monta o actualiza la iluminación estilo Genies. Falso si falta algún recurso.</summary>
        public static bool Apply(Scene scene, Camera camera)
        {
            Texture2D lut = EnsureLut();
            Cubemap environment = EnsureEnvironment();
            Material catcherMaterial = EnsureCatcherMaterial();
            if (lut == null || environment == null || catcherMaterial == null)
            {
                Debug.LogError("[Sonia] Iluminación estilo Genies: falta el LUT, el HDR o el shader en " + Folder + ".");
                return false;
            }

            SetStageLightsEnabled(false);
            Light key = SetUpKeyLight(scene);

            GameObject rig = EnsureRig(scene);
            Light warm = SetUpRim(rig, WarmRimName, WarmRimColor, WarmRimIntensity);
            Light cool = SetUpRim(rig, CoolRimName, CoolRimColor, CoolRimIntensity);
            SetUpCatcher(rig, catcherMaterial);

            SoniaGeniesLook look = rig.GetComponent<SoniaGeniesLook>();
            if (look == null)
            {
                look = Undo.AddComponent<SoniaGeniesLook>(rig);
            }

            Undo.RecordObject(look, UndoName);
            look.Configure(
                camera, new[] { warm, cool }, new[] { WarmRimView, CoolRimView }, (float[])AmbientCoefficients.Clone());
            EditorUtility.SetDirty(look);

            SetUpEnvironment(environment, key);
            SetUpVolume(scene, lut);

            Debug.Log("[Sonia] Iluminación estilo Genies aplicada (key, ambiente SH, rims, reflejos, LUT, sombra).", rig);
            return true;
        }

        /// <summary>
        /// Quita lo que añade esta iluminación: el objeto raíz, el reflejo del HDR,
        /// el sol y el Color Lookup. No vuelve a montar el estudio (eso lo hace
        /// SoniaStageLighting, que llama aquí). Cierto si había algo que quitar.
        /// </summary>
        public static bool Remove(Scene scene)
        {
            bool found = false;
            GameObject[] roots = scene.GetRootGameObjects();
            for (int i = 0; i < roots.Length; i++)
            {
                if (roots[i].name == RigName)
                {
                    Undo.DestroyObjectImmediate(roots[i]);
                    found = true;
                }
            }

            Texture environment = AssetDatabase.LoadAssetAtPath<Texture>(EnvironmentPath);
            if (RenderSettings.customReflectionTexture != null && RenderSettings.customReflectionTexture == environment)
            {
                RenderSettings.defaultReflectionMode = DefaultReflectionMode.Skybox;
                RenderSettings.customReflectionTexture = null;
                RenderSettings.reflectionIntensity = 1f;
                found = true;
            }

            if (found)
            {
                RenderSettings.sun = null;
            }

            VolumeProfile profile = FindProfile(scene);
            ColorLookup lookup;
            if (profile != null && profile.TryGet(out lookup) && lookup != null && lookup.active)
            {
                Undo.RecordObject(lookup, UndoName);
                lookup.active = false;
                EditorUtility.SetDirty(lookup);
                AssetDatabase.SaveAssets();
                found = true;
            }

            return found;
        }

        // ------------------------------------------------------------------
        // Luces
        // ------------------------------------------------------------------

        /// <summary>Enciende o apaga los focos del estudio. El halo y las motas no son luces y siguen.</summary>
        public static void SetStageLightsEnabled(bool enabled)
        {
            GameObject stage = GameObject.Find(StageName);
            if (stage == null)
            {
                return;
            }

            Light[] lights = stage.GetComponentsInChildren<Light>(true);
            for (int i = 0; i < lights.Length; i++)
            {
                if (lights[i].enabled != enabled)
                {
                    Undo.RecordObject(lights[i], UndoName);
                    lights[i].enabled = enabled;
                    EditorUtility.SetDirty(lights[i]);
                }
            }
        }

        private static Light SetUpKeyLight(Scene scene)
        {
            Light key = FindKeyLight(scene);
            if (key == null)
            {
                GameObject go = new GameObject("Directional Light");
                Undo.RegisterCreatedObjectUndo(go, UndoName);
                key = go.AddComponent<Light>();
                go.AddComponent<UniversalAdditionalLightData>();
            }

            Undo.RecordObject(key, UndoName);
            Undo.RecordObject(key.transform, UndoName);
            key.enabled = true;
            key.type = LightType.Directional;
            key.color = KeyColor;
            key.intensity = KeyIntensity;
            key.transform.rotation = Quaternion.Euler(KeyEuler);
            key.shadows = LightShadows.Soft;
            key.shadowStrength = 1f;
            EditorUtility.SetDirty(key);
            return key;
        }

        /// <summary>La direccional de la escena que no es de este montaje ni del estudio.</summary>
        private static Light FindKeyLight(Scene scene)
        {
            GameObject[] roots = scene.GetRootGameObjects();
            for (int i = 0; i < roots.Length; i++)
            {
                if (roots[i].name == RigName || roots[i].name == StageName)
                {
                    continue;
                }

                Light[] lights = roots[i].GetComponentsInChildren<Light>(true);
                for (int j = 0; j < lights.Length; j++)
                {
                    if (lights[j].type == LightType.Directional)
                    {
                        return lights[j];
                    }
                }
            }

            return null;
        }

        private static GameObject EnsureRig(Scene scene)
        {
            GameObject[] roots = scene.GetRootGameObjects();
            for (int i = 0; i < roots.Length; i++)
            {
                if (roots[i].name == RigName)
                {
                    return roots[i];
                }
            }

            GameObject rig = new GameObject(RigName);
            Undo.RegisterCreatedObjectUndo(rig, UndoName);
            if (rig.scene != scene)
            {
                SceneManager.MoveGameObjectToScene(rig, scene);
            }

            return rig;
        }

        private static Light SetUpRim(GameObject rig, string name, Color color, float intensity)
        {
            Transform child = rig.transform.Find(name);
            GameObject go = child != null ? child.gameObject : new GameObject(name);
            if (child == null)
            {
                Undo.RegisterCreatedObjectUndo(go, UndoName);
                go.transform.SetParent(rig.transform, false);
            }

            Light light = go.GetComponent<Light>();
            if (light == null)
            {
                light = Undo.AddComponent<Light>(go);
            }

            Undo.RecordObject(light, UndoName);
            light.enabled = true;
            light.type = LightType.Directional;
            light.color = color;
            light.intensity = intensity;
            light.shadows = LightShadows.None;
            EditorUtility.SetDirty(light);
            return light;
        }

        private static void SetUpCatcher(GameObject rig, Material material)
        {
            Transform child = rig.transform.Find(CatcherName);
            GameObject go;
            if (child == null)
            {
                go = GameObject.CreatePrimitive(PrimitiveType.Quad);
                go.name = CatcherName;
                Undo.RegisterCreatedObjectUndo(go, UndoName);
                go.transform.SetParent(rig.transform, false);
                Collider collider = go.GetComponent<Collider>();
                if (collider != null)
                {
                    Object.DestroyImmediate(collider);
                }
            }
            else
            {
                go = child.gameObject;
            }

            // El suelo de Mia está en y = 0, donde apoya el avatar. El Quad mira a
            // −Z; girado 90° en X queda tumbado mirando hacia arriba.
            Undo.RecordObject(go.transform, UndoName);
            go.transform.localPosition = Vector3.zero;
            go.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
            float size = CatcherFadeEnd * 2f + 0.2f;
            go.transform.localScale = new Vector3(size, size, 1f);

            MeshRenderer renderer = go.GetComponent<MeshRenderer>();
            Undo.RecordObject(renderer, UndoName);
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = true;
            renderer.lightProbeUsage = LightProbeUsage.Off;
            renderer.reflectionProbeUsage = ReflectionProbeUsage.Off;
            EditorUtility.SetDirty(renderer);
        }

        // ------------------------------------------------------------------
        // Entorno y postprocesado
        // ------------------------------------------------------------------

        private static void SetUpEnvironment(Cubemap environment, Light key)
        {
            // En Custom Unity respeta el SH que pone SoniaGeniesLook (en Trilight lo rehace).
            RenderSettings.ambientMode = AmbientMode.Custom;
            RenderSettings.defaultReflectionMode = DefaultReflectionMode.Custom;
            RenderSettings.customReflectionTexture = environment;
            RenderSettings.reflectionIntensity = ReflectionIntensity;

            // URP toma como luz principal el sol o, si no hay, la direccional más
            // intensa: sin esto ganaría el rim frío y se llevaría las sombras.
            RenderSettings.sun = key;
        }

        private static void SetUpVolume(Scene scene, Texture2D lut)
        {
            VolumeProfile profile = FindProfile(scene);
            if (profile == null)
            {
                GameObject go = new GameObject("Global Volume");
                Undo.RegisterCreatedObjectUndo(go, UndoName);
                Volume volume = go.AddComponent<Volume>();
                volume.isGlobal = true;
                profile = ScriptableObject.CreateInstance<VolumeProfile>();
                AssetDatabase.CreateAsset(profile, "Assets/Settings/SoniaVolumeProfile.asset");
                volume.sharedProfile = profile;
            }

            profile.components.RemoveAll(component => component == null);

            Tonemapping tonemapping = GetOrAdd<Tonemapping>(profile);
            tonemapping.active = true;
            tonemapping.mode.overrideState = true;
            tonemapping.mode.value = TonemappingMode.None;

            ColorLookup lookup = GetOrAdd<ColorLookup>(profile);
            lookup.active = true;
            lookup.texture.overrideState = true;
            lookup.texture.value = lut;
            lookup.contribution.overrideState = true;
            lookup.contribution.value = 1f;

            // Mia no tiene bloom ni corrección de color aparte del LUT.
            Bloom bloom;
            if (profile.TryGet(out bloom) && bloom != null)
            {
                bloom.active = false;
            }

            ColorAdjustments color;
            if (profile.TryGet(out color) && color != null)
            {
                color.active = false;
            }

            EditorUtility.SetDirty(profile);
            foreach (VolumeComponent component in profile.components)
            {
                if (component != null)
                {
                    EditorUtility.SetDirty(component);
                }
            }

            AssetDatabase.SaveAssets();
        }

        private static VolumeProfile FindProfile(Scene scene)
        {
            GameObject[] roots = scene.GetRootGameObjects();
            for (int i = 0; i < roots.Length; i++)
            {
                Volume[] volumes = roots[i].GetComponentsInChildren<Volume>(true);
                if (volumes.Length > 0)
                {
                    return volumes[0].sharedProfile;
                }
            }

            return null;
        }

        /// <summary>Como en SoniaStageLighting: un componente nuevo se guarda como sub-asset del perfil.</summary>
        private static T GetOrAdd<T>(VolumeProfile profile) where T : VolumeComponent
        {
            T component;
            if (profile.TryGet(out component) && component != null)
            {
                return component;
            }

            component = profile.Add<T>(true);
            if (AssetDatabase.Contains(profile) && !AssetDatabase.Contains(component))
            {
                component.name = typeof(T).Name;
                AssetDatabase.AddObjectToAsset(component, profile);
            }

            return component;
        }

        // ------------------------------------------------------------------
        // Recursos
        // ------------------------------------------------------------------

        /// <summary>El LUT como lo pide el Color Lookup de URP: lineal, sin mipmaps ni compresión.</summary>
        private static Texture2D EnsureLut()
        {
            TextureImporter importer = AssetImporter.GetAtPath(LutPath) as TextureImporter;
            if (importer == null)
            {
                return null;
            }

            bool changed = false;
            if (importer.textureType != TextureImporterType.Default)
            {
                importer.textureType = TextureImporterType.Default;
                changed = true;
            }

            if (importer.sRGBTexture)
            {
                importer.sRGBTexture = false;
                changed = true;
            }

            if (importer.mipmapEnabled)
            {
                importer.mipmapEnabled = false;
                changed = true;
            }

            if (importer.textureCompression != TextureImporterCompression.Uncompressed)
            {
                importer.textureCompression = TextureImporterCompression.Uncompressed;
                changed = true;
            }

            if (importer.wrapMode != TextureWrapMode.Clamp)
            {
                importer.wrapMode = TextureWrapMode.Clamp;
                changed = true;
            }

            if (importer.filterMode != FilterMode.Bilinear)
            {
                importer.filterMode = FilterMode.Bilinear;
                changed = true;
            }

            if (importer.npotScale != TextureImporterNPOTScale.None)
            {
                importer.npotScale = TextureImporterNPOTScale.None;
                changed = true;
            }

            if (importer.maxTextureSize < 1024)
            {
                importer.maxTextureSize = 2048;
                changed = true;
            }

            if (changed)
            {
                importer.SaveAndReimport();
            }

            return AssetDatabase.LoadAssetAtPath<Texture2D>(LutPath);
        }

        /// <summary>El HDR de Mia como cubemap latitud-longitud con mipmaps de reflejo (GGX).</summary>
        private static Cubemap EnsureEnvironment()
        {
            TextureImporter importer = AssetImporter.GetAtPath(EnvironmentPath) as TextureImporter;
            if (importer == null)
            {
                return null;
            }

            TextureImporterSettings settings = new TextureImporterSettings();
            importer.ReadTextureSettings(settings);
            bool changed = false;
            if (settings.textureShape != TextureImporterShape.TextureCube)
            {
                settings.textureShape = TextureImporterShape.TextureCube;
                changed = true;
            }

            if (settings.generateCubemap != TextureImporterGenerateCubemap.Cylindrical)
            {
                settings.generateCubemap = TextureImporterGenerateCubemap.Cylindrical;
                changed = true;
            }

            if (settings.cubemapConvolution != TextureImporterCubemapConvolution.Specular)
            {
                settings.cubemapConvolution = TextureImporterCubemapConvolution.Specular;
                changed = true;
            }

            if (!settings.seamlessCubemap)
            {
                settings.seamlessCubemap = true;
                changed = true;
            }

            if (!settings.mipmapEnabled)
            {
                settings.mipmapEnabled = true;
                changed = true;
            }

            if (settings.wrapMode != TextureWrapMode.Clamp)
            {
                settings.wrapMode = TextureWrapMode.Clamp;
                changed = true;
            }

            if (changed)
            {
                importer.SetTextureSettings(settings);
            }

            if (importer.textureCompression != TextureImporterCompression.Uncompressed)
            {
                importer.textureCompression = TextureImporterCompression.Uncompressed;
                changed = true;
            }

            if (changed)
            {
                importer.SaveAndReimport();
            }

            return AssetDatabase.LoadAssetAtPath<Cubemap>(EnvironmentPath);
        }

        private static Material EnsureCatcherMaterial()
        {
            Shader shader = Shader.Find(CatcherShaderName);
            if (shader == null)
            {
                return null;
            }

            Material material = AssetDatabase.LoadAssetAtPath<Material>(CatcherMaterialPath);
            if (material == null)
            {
                material = new Material(shader);
                AssetDatabase.CreateAsset(material, CatcherMaterialPath);
            }

            material.shader = shader;
            material.SetColor("_ShadowColor", Color.black);
            material.SetFloat("_Opacity", CatcherOpacity);
            material.SetFloat("_FadeStart", CatcherFadeStart);
            material.SetFloat("_FadeEnd", CatcherFadeEnd);
            EditorUtility.SetDirty(material);
            return material;
        }
    }
}

#endif
