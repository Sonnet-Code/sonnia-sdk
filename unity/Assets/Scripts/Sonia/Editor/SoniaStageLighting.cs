// Iluminación de estudio y efectos del stand, sin assets de pago.
//
// "Sonia > Iluminación de estudio" monta (o actualiza) un retrato de tres
// puntos alrededor del avatar y el pulido de imagen:
//
//   Key    foco cálido a la izquierda de cámara, 25° por encima de los ojos,
//          con sombras suaves: modela la cara.
//   Fill   luz fría y débil al otro lado, casi en el eje de cámara: levanta
//          las sombras sin borrarlas.
//   Rim    foco frío detrás y arriba, estrecho: recorta pelo y hombros contra
//          el telón oscuro (el efecto que más "premium" se ve en vertical).
//   Halo   plano con degradado radial detrás del avatar, aditivo y en el azul
//          de marca: simula el haz de un foco sobre el telón.
//   Motas  partículas lentas y tenues, aditivas, entre el avatar y el telón.
//   Volume tonemapping ACES, bloom sutil, viñeta, un punto de contraste y
//          saturación; SMAA en la cámara.
//
// Todo cuelga de un objeto "SoniaStage" para poder borrarlo de un golpe. Las
// posiciones se calculan a partir de la cabeza del avatar y de la cámara, así
// que vale para cualquier modelo.

#if UNITY_EDITOR

using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.SceneManagement;

namespace Sonia.EditorTools
{
    /// <summary>Monta las luces, el halo, las motas y el postprocesado del stand.</summary>
    public static class SoniaStageLighting
    {
        private const string StageName = "SoniaStage";
        private const string TextureFolder = "Assets/UI/Generated";
        private const string UndoName = "Iluminación de estudio de Sonia";

        // Colores en Kelvin aproximados: key 5300 K, fill 6500 K, rim 8000 K con tinte de marca.
        private static readonly Color KeyColor = new Color(1.00f, 0.95f, 0.88f);
        private static readonly Color FillColor = new Color(0.82f, 0.88f, 1.00f);
        private static readonly Color RimColor = new Color(0.62f, 0.78f, 1.00f);
        private static readonly Color HaloColor = new Color(0.30f, 0.50f, 1.00f);
        private static readonly Color AmbientSky = new Color(0.22f, 0.28f, 0.42f);
        private static readonly Color AmbientEquator = new Color(0.16f, 0.19f, 0.27f);
        private static readonly Color AmbientGround = new Color(0.06f, 0.07f, 0.10f);

        [MenuItem("Sonia/Iluminación de estudio")]
        public static void ApplyMenu()
        {
            Scene scene = SceneManager.GetActiveScene();
            Transform head = FindHead(scene);
            Camera camera = Camera.main;
            if (head == null || camera == null)
            {
                EditorUtility.DisplayDialog(
                    "Sonia", "Hace falta un avatar colocado (con cabeza humanoide) y una cámara principal.", "Vale");
                return;
            }

            Apply(scene, head.position, camera);
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
        }

        /// <summary>Monta o actualiza todo el escenario alrededor de la cabeza dada.</summary>
        public static void Apply(Scene scene, Vector3 headPosition, Camera camera)
        {
            GameObject stage = GameObject.Find(StageName);
            if (stage == null)
            {
                stage = new GameObject(StageName);
                Undo.RegisterCreatedObjectUndo(stage, UndoName);
            }

            // El avatar mira hacia la cámara; "delante" es hacia ella.
            Vector3 toCamera = camera.transform.position - headPosition;
            toCamera.y = 0f;
            Vector3 forward = toCamera.sqrMagnitude > 0.001f ? toCamera.normalized : Vector3.back;
            Vector3 right = Vector3.Cross(Vector3.up, forward).normalized; // derecha de cámara vista desde el avatar
            Vector3 chest = headPosition + Vector3.down * 0.35f;

            SetUpLight(stage, "KeyLight", LightType.Spot,
                headPosition + (-right * 1.1f) + forward * 1.5f + Vector3.up * 0.75f, chest + Vector3.up * 0.15f,
                KeyColor, 6f, 62f, LightShadows.Soft, 0.7f);
            SetUpLight(stage, "FillLight", LightType.Spot,
                headPosition + (right * 1.3f) + forward * 1.4f + Vector3.up * 0.05f, chest,
                FillColor, 2.2f, 80f, LightShadows.None, 0f);
            SetUpLight(stage, "RimLight", LightType.Spot,
                headPosition + (right * 0.5f) - forward * 1.3f + Vector3.up * 1.0f, headPosition + Vector3.down * 0.1f,
                RimColor, 9f, 48f, LightShadows.None, 0f);
            SetUpLight(stage, "HairLight", LightType.Spot,
                headPosition + (-right * 0.7f) - forward * 1.1f + Vector3.up * 1.1f, headPosition,
                RimColor, 5f, 40f, LightShadows.None, 0f);

            TameDirectional(scene);
            SetUpAmbient();
            SetUpHalo(stage, headPosition, forward);
            SetUpMotes(stage, headPosition, forward);
            SetUpCamera(camera);
            SetUpVolume(scene, camera, headPosition);

            Debug.Log("[Sonia] Iluminación de estudio aplicada (key, fill, rim, hair, halo, motas, ACES, SMAA).", stage);
        }

        // ------------------------------------------------------------------
        // Luces
        // ------------------------------------------------------------------

        private static void SetUpLight(
            GameObject stage, string name, LightType type, Vector3 position, Vector3 target,
            Color color, float intensity, float spotAngle, LightShadows shadows, float shadowStrength)
        {
            Transform child = stage.transform.Find(name);
            GameObject go = child != null ? child.gameObject : new GameObject(name);
            if (child == null)
            {
                Undo.RegisterCreatedObjectUndo(go, UndoName);
                go.transform.SetParent(stage.transform, false);
            }

            Light light = go.GetComponent<Light>();
            if (light == null)
            {
                light = Undo.AddComponent<Light>(go);
            }

            Undo.RecordObject(light, UndoName);
            Undo.RecordObject(go.transform, UndoName);
            go.transform.position = position;
            go.transform.rotation = Quaternion.LookRotation((target - position).normalized, Vector3.up);
            light.type = type;
            light.color = color;
            light.intensity = intensity;
            light.range = 8f;
            light.spotAngle = spotAngle;
            light.innerSpotAngle = spotAngle * 0.55f;
            light.shadows = shadows;
            light.shadowStrength = shadowStrength;
            light.shadowBias = 0.02f;
            light.shadowNormalBias = 0.4f;
            light.shadowNearPlane = 0.1f;

            UniversalAdditionalLightData data = go.GetComponent<UniversalAdditionalLightData>();
            if (data == null)
            {
                data = Undo.AddComponent<UniversalAdditionalLightData>(go);
            }

            Undo.RecordObject(data, UndoName);
            data.usePipelineSettings = true;
            data.softShadowQuality = SoftShadowQuality.High;
            EditorUtility.SetDirty(light);
            EditorUtility.SetDirty(data);
        }

        /// <summary>La direccional de la plantilla queda como luz de ambiente muy tenue, sin sombras duras.</summary>
        private static void TameDirectional(Scene scene)
        {
            GameObject[] roots = scene.GetRootGameObjects();
            for (int i = 0; i < roots.Length; i++)
            {
                Light[] lights = roots[i].GetComponentsInChildren<Light>(true);
                for (int j = 0; j < lights.Length; j++)
                {
                    if (lights[j].type != LightType.Directional)
                    {
                        continue;
                    }

                    Undo.RecordObject(lights[j], UndoName);
                    lights[j].intensity = 0.25f;
                    lights[j].color = new Color(0.85f, 0.9f, 1f);
                    lights[j].shadows = LightShadows.Soft;
                    lights[j].shadowStrength = 0.35f;
                    lights[j].transform.rotation = Quaternion.Euler(55f, 200f, 0f);
                    EditorUtility.SetDirty(lights[j]);
                }
            }
        }

        private static void SetUpAmbient()
        {
            RenderSettings.ambientMode = AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = AmbientSky;
            RenderSettings.ambientEquatorColor = AmbientEquator;
            RenderSettings.ambientGroundColor = AmbientGround;
        }

        // ------------------------------------------------------------------
        // Halo y motas
        // ------------------------------------------------------------------

        private static void SetUpHalo(GameObject stage, Vector3 headPosition, Vector3 forward)
        {
            Texture2D radial = EnsureRadialTexture("halo", 256, 3.2f);
            Transform child = stage.transform.Find("Halo");
            GameObject go = child != null ? child.gameObject : GameObject.CreatePrimitive(PrimitiveType.Quad);
            if (child == null)
            {
                go.name = "Halo";
                Undo.RegisterCreatedObjectUndo(go, UndoName);
                go.transform.SetParent(stage.transform, false);
                Object.DestroyImmediate(go.GetComponent<Collider>());
            }

            Material material = EnsureAdditiveMaterial("SoniaHalo", radial, HaloColor * 0.22f);
            MeshRenderer renderer = go.GetComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;

            // Entre el avatar y el telón, algo por detrás de los hombros.
            go.transform.position = headPosition - forward * 0.9f + Vector3.down * 0.35f;
            go.transform.rotation = Quaternion.LookRotation(-forward, Vector3.up);
            go.transform.localScale = new Vector3(2.2f, 2.8f, 1f);
        }

        private static void SetUpMotes(GameObject stage, Vector3 headPosition, Vector3 forward)
        {
            Texture2D dot = EnsureRadialTexture("mote", 64, 2.2f);
            Transform child = stage.transform.Find("Motes");
            GameObject go = child != null ? child.gameObject : new GameObject("Motes");
            if (child == null)
            {
                Undo.RegisterCreatedObjectUndo(go, UndoName);
                go.transform.SetParent(stage.transform, false);
            }

            ParticleSystem system = go.GetComponent<ParticleSystem>();
            if (system == null)
            {
                system = Undo.AddComponent<ParticleSystem>(go);
            }

            go.transform.position = headPosition - forward * 0.3f + Vector3.down * 0.6f;
            go.transform.rotation = Quaternion.identity;

            ParticleSystem.MainModule main = system.main;
            main.loop = true;
            main.prewarm = true;
            main.startLifetime = new ParticleSystem.MinMaxCurve(9f, 16f);
            main.startSpeed = new ParticleSystem.MinMaxCurve(0.01f, 0.04f);
            main.startSize = new ParticleSystem.MinMaxCurve(0.008f, 0.022f);
            main.startColor = new ParticleSystem.MinMaxGradient(new Color(1f, 1f, 1f, 0.10f), new Color(0.75f, 0.85f, 1f, 0.22f));
            main.maxParticles = 70;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.gravityModifier = -0.002f;

            ParticleSystem.EmissionModule emission = system.emission;
            emission.rateOverTime = 4.5f;

            ParticleSystem.ShapeModule shape = system.shape;
            shape.shapeType = ParticleSystemShapeType.Box;
            shape.scale = new Vector3(2.4f, 2.6f, 1.2f);

            ParticleSystem.NoiseModule noise = system.noise;
            noise.enabled = true;
            noise.strength = 0.08f;
            noise.frequency = 0.25f;
            noise.scrollSpeed = 0.15f;

            ParticleSystem.ColorOverLifetimeModule color = system.colorOverLifetime;
            color.enabled = true;
            Gradient gradient = new Gradient();
            gradient.SetKeys(
                new[] { new GradientColorKey(Color.white, 0f), new GradientColorKey(Color.white, 1f) },
                new[]
                {
                    new GradientAlphaKey(0f, 0f), new GradientAlphaKey(1f, 0.2f),
                    new GradientAlphaKey(1f, 0.8f), new GradientAlphaKey(0f, 1f)
                });
            color.color = gradient;

            ParticleSystemRenderer renderer = go.GetComponent<ParticleSystemRenderer>();
            renderer.sharedMaterial = EnsureAdditiveMaterial("SoniaMote", dot, Color.white);
            renderer.renderMode = ParticleSystemRenderMode.Billboard;
            renderer.sortingFudge = 0f;
            EditorUtility.SetDirty(system);
        }

        private static Texture2D EnsureRadialTexture(string name, int size, float falloff)
        {
            string path = TextureFolder + "/" + name + "_" + falloff.ToString("F1").Replace('.', '_') + ".png";
            Texture2D existing = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
            if (existing != null)
            {
                return existing;
            }

            EnsureFolder(TextureFolder);
            Texture2D texture = new Texture2D(size, size, TextureFormat.RGBA32, false);
            Color[] pixels = new Color[size * size];
            float half = size * 0.5f;
            for (int y = 0; y < size; y++)
            {
                for (int x = 0; x < size; x++)
                {
                    float dx = (x + 0.5f - half) / half;
                    float dy = (y + 0.5f - half) / half;
                    float d = Mathf.Sqrt(dx * dx + dy * dy);
                    float a = Mathf.Clamp01(1f - d);
                    a = Mathf.Pow(a, falloff);
                    pixels[y * size + x] = new Color(1f, 1f, 1f, a);
                }
            }

            texture.SetPixels(pixels);
            texture.Apply();
            System.IO.File.WriteAllBytes(path, texture.EncodeToPNG());
            Object.DestroyImmediate(texture);
            AssetDatabase.ImportAsset(path);

            TextureImporter importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer != null)
            {
                importer.textureType = TextureImporterType.Default;
                importer.alphaIsTransparency = true;
                importer.mipmapEnabled = true;
                importer.wrapMode = TextureWrapMode.Clamp;
                importer.SaveAndReimport();
            }

            return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
        }

        private static Material EnsureAdditiveMaterial(string name, Texture2D texture, Color tint)
        {
            string path = TextureFolder + "/" + name + ".mat";
            Material material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
            {
                Shader shader = Shader.Find("Universal Render Pipeline/Particles/Unlit");
                if (shader == null)
                {
                    shader = Shader.Find("Universal Render Pipeline/Unlit");
                }

                material = new Material(shader);
                EnsureFolder(TextureFolder);
                AssetDatabase.CreateAsset(material, path);
            }

            // Particles/Unlit en modo transparente aditivo (SrcAlpha, One): el alfa
            // radial de la textura decide cuánto suma cada píxel. Sin premultiplicado,
            // que con una textura blanca pintaría cuadrados.
            material.SetFloat("_Surface", 1f);
            material.SetFloat("_Blend", 2f); // 0 alpha, 1 premultiply, 2 additive, 3 multiply
            material.SetFloat("_ZWrite", 0f);
            material.SetFloat("_Cull", 0f);
            material.SetFloat("_ColorMode", 0f);
            material.SetInt("_SrcBlend", (int)BlendMode.SrcAlpha);
            material.SetInt("_DstBlend", (int)BlendMode.One);
            material.SetInt("_SrcBlendAlpha", (int)BlendMode.One);
            material.SetInt("_DstBlendAlpha", (int)BlendMode.One);
            material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.DisableKeyword("_ALPHAPREMULTIPLY_ON");
            material.DisableKeyword("_ALPHAMODULATE_ON");
            material.DisableKeyword("_ALPHATEST_ON");
            material.SetOverrideTag("RenderType", "Transparent");
            material.renderQueue = (int)RenderQueue.Transparent;
            material.SetTexture("_BaseMap", texture);
            material.SetColor("_BaseColor", tint);
            material.mainTexture = texture;
            material.color = tint;
            EditorUtility.SetDirty(material);
            return material;
        }

        // ------------------------------------------------------------------
        // Cámara y postprocesado
        // ------------------------------------------------------------------

        private static void SetUpCamera(Camera camera)
        {
            UniversalAdditionalCameraData data = camera.GetUniversalAdditionalCameraData();
            if (data == null)
            {
                return;
            }

            Undo.RecordObject(data, UndoName);
            data.renderPostProcessing = true;
            data.antialiasing = AntialiasingMode.SubpixelMorphologicalAntiAliasing;
            data.antialiasingQuality = AntialiasingQuality.High;
            data.renderShadows = true;
            EditorUtility.SetDirty(data);
        }

        private static void SetUpVolume(Scene scene, Camera camera, Vector3 headPosition)
        {
            Volume volume = null;
            GameObject[] roots = scene.GetRootGameObjects();
            for (int i = 0; i < roots.Length && volume == null; i++)
            {
                Volume[] volumes = roots[i].GetComponentsInChildren<Volume>(true);
                if (volumes.Length > 0)
                {
                    volume = volumes[0];
                }
            }

            if (volume == null)
            {
                GameObject go = new GameObject("Global Volume");
                Undo.RegisterCreatedObjectUndo(go, UndoName);
                volume = go.AddComponent<Volume>();
                volume.isGlobal = true;
            }

            VolumeProfile profile = volume.sharedProfile;
            if (profile == null)
            {
                profile = ScriptableObject.CreateInstance<VolumeProfile>();
                AssetDatabase.CreateAsset(profile, "Assets/Settings/SoniaVolumeProfile.asset");
                volume.sharedProfile = profile;
            }

            Tonemapping tonemapping = GetOrAdd<Tonemapping>(profile);
            tonemapping.active = true;
            tonemapping.mode.overrideState = true;
            tonemapping.mode.value = TonemappingMode.ACES;

            Bloom bloom = GetOrAdd<Bloom>(profile);
            bloom.active = true;
            bloom.intensity.overrideState = true;
            bloom.intensity.value = 0.22f;
            bloom.threshold.overrideState = true;
            bloom.threshold.value = 1.0f;
            bloom.scatter.overrideState = true;
            bloom.scatter.value = 0.65f;

            Vignette vignette = GetOrAdd<Vignette>(profile);
            vignette.active = true;
            vignette.intensity.overrideState = true;
            vignette.intensity.value = 0.28f;
            vignette.smoothness.overrideState = true;
            vignette.smoothness.value = 0.45f;
            vignette.color.overrideState = true;
            vignette.color.value = new Color(0.02f, 0.03f, 0.08f);

            ColorAdjustments color = GetOrAdd<ColorAdjustments>(profile);
            color.active = true;
            color.postExposure.overrideState = true;
            color.postExposure.value = 0f;
            color.contrast.overrideState = true;
            color.contrast.value = 10f;
            color.saturation.overrideState = true;
            color.saturation.value = 8f;

            DepthOfField dof = GetOrAdd<DepthOfField>(profile);
            dof.active = true;
            dof.mode.overrideState = true;
            dof.mode.value = DepthOfFieldMode.Bokeh;
            dof.focusDistance.overrideState = true;
            dof.focusDistance.value = Mathf.Max(0.5f, Vector3.Distance(camera.transform.position, headPosition));
            dof.aperture.overrideState = true;
            dof.aperture.value = 9f;
            dof.focalLength.overrideState = true;
            dof.focalLength.value = 45f;

            EditorUtility.SetDirty(profile);
            foreach (VolumeComponent component in profile.components)
            {
                EditorUtility.SetDirty(component);
            }

            AssetDatabase.SaveAssets();
        }

        private static T GetOrAdd<T>(VolumeProfile profile) where T : VolumeComponent
        {
            T component;
            if (profile.TryGet(out component))
            {
                return component;
            }

            return profile.Add<T>(true);
        }

        // ------------------------------------------------------------------
        // Utilidades
        // ------------------------------------------------------------------

        private static Transform FindHead(Scene scene)
        {
            GameObject[] roots = scene.GetRootGameObjects();
            for (int i = 0; i < roots.Length; i++)
            {
                Animator[] animators = roots[i].GetComponentsInChildren<Animator>(true);
                for (int j = 0; j < animators.Length; j++)
                {
                    if (animators[j].isHuman)
                    {
                        Transform head = animators[j].GetBoneTransform(HumanBodyBones.Head);
                        if (head != null)
                        {
                            return head;
                        }
                    }
                }
            }

            return null;
        }

        private static void EnsureFolder(string folder)
        {
            if (AssetDatabase.IsValidFolder(folder))
            {
                return;
            }

            string parent = System.IO.Path.GetDirectoryName(folder).Replace('\\', '/');
            EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, System.IO.Path.GetFileName(folder));
        }
    }
}

#endif
