// Aspecto de la escena para un vídeo: fondo, logo y QR, partículas, luz, exposición,
// encuadre, emoción y gorra. Se aplica al empezar cada trabajo y se deshace al acabar
// (la ventana de la app vuelve a enseñar el stand tal cual).
//
// Luz: los presets escalan y tiñen por nombre las luces de la escena (las de
// Sonia > Iluminación de estudio: KeyLight, FillLight, RimLight, HairLight y la
// direccional), la luz ambiente, y pueden añadir un contraluz direccional desde
// detrás (como el del vídeo del DevFest). La exposición va con un Volume global
// propio (Color Adjustments) por encima de los de la escena.
//
// Encuadre: "stand" es el plano de conversación del stand, quieto (sin el plano de
// reposo que se abre entre turnos); los demás se calculan con los huesos del
// Humanoid (nunca con los bounds: los accesorios los deforman) y se imponen con
// CameraFramingController.SetOverride.

using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using Object = UnityEngine.Object;

namespace Sonia.Video
{
    /// <summary>Aplica y deshace el aspecto de un trabajo.</summary>
    public sealed class VideoLook
    {
        private const BindingFlags Any = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

        /// <summary>
        /// Del hueso de la cabeza (en la base del cráneo) a lo alto del pelo del avatar de Genies,
        /// en metros: medido en el alfa de una foto de cuerpo entero (0,27 m).
        /// </summary>
        private const float CrownAboveHead = 0.28f;

        private struct LightState
        {
            public Light Light;
            public float Intensity;
            public Color Color;
        }

        private readonly List<LightState> _lights = new List<LightState>();
        private readonly List<Object> _created = new List<Object>();
        private float _ambientIntensity;
        private Color _ambientLight;
        private Color _ambientSky;
        private Color _ambientEquator;
        private Color _ambientGround;
        private bool _captured;
        private Volume _volume;

        // ------------------------------------------------------------------
        // Fondo, HUD, partículas y emoción
        // ------------------------------------------------------------------

        /// <summary>Fondo, partículas y emoción. El HUD del stand no sale en los vídeos.</summary>
        public void ApplyStage(VideoJob job, StageScreen screen, SoniaClient client, FacialExpressionController face)
        {
            VideoScene scene = job.Scene;
            if (screen != null)
            {
                screen.SetBackdrop(BackdropSprite(scene.Background, job.Width, job.Height, out Color tint), tint);
            }

            if (client != null)
            {
                // Sin la invitación a hablar del stand.
                client.InjectMessage("{\"type\":\"stage_mode\",\"talk\":false}");
            }

            StageParticles.SetQualityAllows(scene.Particles);
            if (face != null)
            {
                face.ShowEmotion(scene.Emotion == "neutral" ? FacialExpressionController.Emotion.None
                    : FacialExpressionController.Emotion.Joy, scene.Emotion == "neutral" ? 0.3f : 100000f);
            }
        }

        private Sprite BackdropSprite(VideoBackground background, int width, int height, out Color tint)
        {
            tint = Color.white;
            string mode = (background.Mode ?? "stand").ToLowerInvariant();
            if (mode == "color")
            {
                tint = ParseColor(background.Color, new Color32(20, 39, 82, 255));
                return MakeSprite(Texture2D.whiteTexture, new Rect(0, 0, 4, 4));
            }

            if (mode == "gradient")
            {
                Color top = ParseColor(background.Color, new Color32(20, 39, 82, 255));
                Color bottom = ParseColor(background.Color2, new Color32(11, 19, 34, 255));
                var texture = new Texture2D(1, 256, TextureFormat.RGBA32, false) { wrapMode = TextureWrapMode.Clamp };
                for (int y = 0; y < 256; y++)
                {
                    texture.SetPixel(0, y, Color.Lerp(bottom, top, y / 255f));
                }

                texture.Apply(false);
                _created.Add(texture);
                return MakeSprite(texture, new Rect(0, 0, 1, 256));
            }

            if (mode == "image" && !string.IsNullOrEmpty(background.Image) && File.Exists(background.Image))
            {
                var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
                if (!texture.LoadImage(File.ReadAllBytes(background.Image)))
                {
                    Debug.LogWarning("[Vídeo] No se pudo leer la imagen de fondo " + background.Image);
                    Object.Destroy(texture);
                    return null;
                }

                texture.wrapMode = TextureWrapMode.Clamp;
                _created.Add(texture);
                // Cubre el cuadro: se recorta lo que sobra de la imagen, centrado.
                float frame = width / (float)height;
                float image = texture.width / (float)texture.height;
                Rect rect = image > frame
                    ? new Rect((texture.width - texture.height * frame) * 0.5f, 0, texture.height * frame, texture.height)
                    : new Rect(0, (texture.height - texture.width / frame) * 0.5f, texture.width, texture.width / frame);
                return MakeSprite(texture, rect);
            }

            if (mode == "image")
            {
                Debug.LogWarning("[Vídeo] Falta la imagen de fondo: " + background.Image);
            }

            return null;
        }

        private Sprite MakeSprite(Texture2D texture, Rect rect)
        {
            Sprite sprite = Sprite.Create(texture, rect, new Vector2(0.5f, 0.5f), 100f, 0, SpriteMeshType.FullRect);
            _created.Add(sprite);
            return sprite;
        }

        // ------------------------------------------------------------------
        // Luz
        // ------------------------------------------------------------------

        /// <summary>Preset de luz, ganancias, contraluz y exposición.</summary>
        public void ApplyLighting(VideoLighting lighting, Transform avatar)
        {
            Capture();
            RestoreLights();
            string preset = (lighting.Preset ?? "stand").ToLowerInvariant();
            Preset p = PresetOf(preset);
            float key = Mathf.Clamp(lighting.Key, 0f, 4f);
            foreach (LightState state in _lights)
            {
                if (state.Light == null)
                {
                    continue;
                }

                string name = state.Light.name.ToLowerInvariant();
                float gain = key * (name.Contains("key") ? p.Key
                    : name.Contains("fill") ? p.Fill
                    : name.Contains("rim") || name.Contains("hair") ? p.Rim
                    : p.Other);
                state.Light.intensity = state.Intensity * gain;
                state.Light.color = state.Color * p.Tint;
            }

            float ambient = Mathf.Clamp(lighting.Ambient, 0f, 4f) * p.Ambient;
            RenderSettings.ambientIntensity = _ambientIntensity * ambient;
            RenderSettings.ambientLight = _ambientLight * ambient;
            RenderSettings.ambientSkyColor = _ambientSky * ambient;
            RenderSettings.ambientEquatorColor = _ambientEquator * ambient;
            RenderSettings.ambientGroundColor = _ambientGround * ambient;

            Color rim = p.RimColor;
            float rimIntensity = p.ExtraRim;
            if (!string.IsNullOrEmpty(lighting.RimColor))
            {
                rim = ParseColor(lighting.RimColor, rim);
                rimIntensity = lighting.RimIntensity > 0f ? lighting.RimIntensity : Mathf.Max(rimIntensity, 1.5f);
            }
            else if (lighting.RimIntensity > 0f)
            {
                rimIntensity = lighting.RimIntensity;
            }

            if (rimIntensity > 0f && avatar != null)
            {
                AddRim("Contraluz vídeo (izquierda)", rim, rimIntensity, 55f, 20f, avatar, true);
                AddRim("Contraluz vídeo (derecha)", rim, rimIntensity * 0.5f, 55f, 20f, avatar, false);
            }

            SetExposure(lighting.Exposure + p.Exposure);
        }

        private struct Preset
        {
            public float Key;
            public float Fill;
            public float Rim;
            public float Other;
            public float Ambient;
            public Color Tint;
            public Color RimColor;
            public float ExtraRim;
            public float Exposure;
        }

        private static Preset PresetOf(string name)
        {
            var p = new Preset
            {
                Key = 1f, Fill = 1f, Rim = 1f, Other = 1f, Ambient = 1f, Tint = Color.white,
                RimColor = new Color32(0x71, 0xBF, 0xFF, 255), ExtraRim = 0f, Exposure = 0f
            };
            switch (name)
            {
                case "studio":
                    p.Key = 1.1f;
                    p.Fill = 1.3f;
                    p.Ambient = 1.15f;
                    p.ExtraRim = 1.2f;
                    p.RimColor = new Color32(0xE8, 0xF2, 0xFF, 255);
                    break;
                case "soft":
                    p.Key = 0.85f;
                    p.Fill = 1.6f;
                    p.Rim = 0.6f;
                    p.Ambient = 1.3f;
                    break;
                case "warm":
                    p.Tint = new Color(1f, 0.93f, 0.84f);
                    p.Fill = 1.1f;
                    p.ExtraRim = 1.0f;
                    p.RimColor = new Color32(0xFF, 0xC8, 0x8A, 255);
                    break;
                case "cool":
                    p.Tint = new Color(0.88f, 0.94f, 1f);
                    p.ExtraRim = 1.6f;
                    p.RimColor = new Color32(0x71, 0xBF, 0xFF, 255);
                    break;
                case "dramatic":
                    p.Key = 1.25f;
                    p.Fill = 0.35f;
                    p.Other = 0.6f;
                    p.Ambient = 0.55f;
                    p.ExtraRim = 2.6f;
                    p.RimColor = new Color32(0x71, 0xBF, 0xFF, 255);
                    break;
            }

            return p;
        }

        private void AddRim(string name, Color color, float intensity, float sideDeg, float pitchDeg, Transform avatar, bool fromScreenLeft)
        {
            var holder = new GameObject(name);
            Light light = holder.AddComponent<Light>();
            light.type = LightType.Directional;
            light.color = color;
            light.intensity = intensity;
            light.shadows = LightShadows.None;
            light.renderMode = LightRenderMode.ForcePixel;
            // Sonnia mira a cámara: su izquierda es la derecha de la pantalla.
            Vector3 screenRight = -avatar.right;
            Vector3 travel = fromScreenLeft ? screenRight : -screenRight;
            float a = sideDeg * Mathf.Deg2Rad;
            float p = pitchDeg * Mathf.Deg2Rad;
            Vector3 dir = (avatar.forward * Mathf.Cos(a) + travel * Mathf.Sin(a)).normalized;
            dir = (dir * Mathf.Cos(p) - avatar.up * Mathf.Sin(p)).normalized;
            holder.transform.rotation = Quaternion.LookRotation(dir, avatar.up);
            _created.Add(holder);
        }

        private void SetExposure(float exposure)
        {
            if (Mathf.Abs(exposure) < 0.001f)
            {
                if (_volume != null)
                {
                    _volume.weight = 0f;
                }

                return;
            }

            if (_volume == null)
            {
                var holder = new GameObject("Exposición vídeo");
                _volume = holder.AddComponent<Volume>();
                _volume.isGlobal = true;
                _volume.priority = 1000f;
                _volume.profile = ScriptableObject.CreateInstance<VolumeProfile>();
                _volume.profile.Add<ColorAdjustments>(true);
                _created.Add(_volume.profile);
                _created.Add(holder);
            }

            if (_volume.profile.TryGet(out ColorAdjustments adjustments))
            {
                adjustments.postExposure.overrideState = true;
                adjustments.postExposure.value = Mathf.Clamp(exposure, -4f, 4f);
            }

            _volume.weight = 1f;
        }

        private void Capture()
        {
            if (_captured)
            {
                return;
            }

            _captured = true;
            foreach (Light light in Object.FindObjectsByType<Light>(FindObjectsInactive.Include))
            {
                _lights.Add(new LightState { Light = light, Intensity = light.intensity, Color = light.color });
            }

            _ambientIntensity = RenderSettings.ambientIntensity;
            _ambientLight = RenderSettings.ambientLight;
            _ambientSky = RenderSettings.ambientSkyColor;
            _ambientEquator = RenderSettings.ambientEquatorColor;
            _ambientGround = RenderSettings.ambientGroundColor;
        }

        private void RestoreLights()
        {
            foreach (LightState state in _lights)
            {
                if (state.Light != null)
                {
                    state.Light.intensity = state.Intensity;
                    state.Light.color = state.Color;
                }
            }

            if (_captured)
            {
                RenderSettings.ambientIntensity = _ambientIntensity;
                RenderSettings.ambientLight = _ambientLight;
                RenderSettings.ambientSkyColor = _ambientSky;
                RenderSettings.ambientEquatorColor = _ambientEquator;
                RenderSettings.ambientGroundColor = _ambientGround;
            }

            for (int i = _created.Count - 1; i >= 0; i--)
            {
                if (_created[i] is GameObject go && go.GetComponent<Light>() != null)
                {
                    Object.Destroy(go);
                    _created.RemoveAt(i);
                }
            }
        }

        // ------------------------------------------------------------------
        // Encuadre
        // ------------------------------------------------------------------

        /// <summary>
        /// Encuadre del trabajo, quieto durante todo el vídeo. Devuelve la pose impuesta
        /// (la cámara salta a ella en el siguiente LateUpdate).
        /// </summary>
        public ShotPose ApplyFraming(VideoFraming framing, CameraFramingController controller, Camera camera,
                                     Animator animator, Transform avatar, float aspect)
        {
            string preset = (framing.Preset ?? "stand").ToLowerInvariant();
            ShotPose pose;
            if (preset == "stand" || animator == null || avatar == null)
            {
                pose = controller != null ? controller.BaseShot
                    : new ShotPose(camera.transform.position, camera.transform.rotation, camera.fieldOfView);
                pose = Adjust(pose, framing, avatar, aspect);
            }
            else
            {
                pose = Compute(preset, framing, camera.fieldOfView, animator, avatar, aspect);
            }

            if (controller != null)
            {
                controller.SetOverride(pose);
                controller.SnapNextFrame();
            }
            else
            {
                camera.transform.SetPositionAndRotation(pose.Position, pose.Rotation);
                camera.fieldOfView = pose.FieldOfView;
            }

            return pose;
        }

        /// <summary>Zoom y desplazamiento sobre una pose dada (el plano del stand).</summary>
        private static ShotPose Adjust(ShotPose pose, VideoFraming framing, Transform avatar, float aspect)
        {
            float zoom = Mathf.Clamp(framing.Zoom <= 0f ? 1f : framing.Zoom, 0.3f, 4f);
            Vector3 forward = pose.Rotation * Vector3.forward;
            float distance = avatar != null ? Mathf.Max(0.3f, Vector3.Dot(avatar.position - pose.Position, forward)) : 2f;
            float halfHeight = distance * Mathf.Tan(pose.FieldOfView * 0.5f * Mathf.Deg2Rad);
            float halfTan = Mathf.Tan(pose.FieldOfView * 0.5f * Mathf.Deg2Rad) / zoom;
            float fov = Mathf.Clamp(2f * Mathf.Atan(halfTan) * Mathf.Rad2Deg, 5f, 120f);
            Vector3 right = pose.Rotation * Vector3.right;
            Vector3 up = pose.Rotation * Vector3.up;
            // Positivo: Sonnia a la derecha / abajo del cuadro → la cámara va al revés.
            Vector3 position = pose.Position
                               - right * (framing.OffsetX * 2f * halfHeight * aspect / zoom)
                               + up * (framing.OffsetY * 2f * halfHeight / zoom);
            return new ShotPose(position, pose.Rotation, fov);
        }

        private static ShotPose Compute(string preset, VideoFraming framing, float fieldOfView, Animator animator,
                                        Transform avatar, float aspect)
        {
            Vector3 origin = avatar.position;
            Vector3 up = Vector3.up;
            Vector3 forward = Vector3.ProjectOnPlane(avatar.forward, up).normalized;
            if (forward.sqrMagnitude < 0.5f)
            {
                forward = Vector3.forward;
            }

            float Height(HumanBodyBones bone, float fallback)
            {
                Transform t = animator.GetBoneTransform(bone);
                return t != null ? Vector3.Dot(t.position - origin, up) : fallback;
            }

            float head = Height(HumanBodyBones.Head, 1.45f);
            float crown = head + CrownAboveHead;
            float bottom;
            switch (preset)
            {
                case "close":
                    bottom = Height(HumanBodyBones.UpperChest, Height(HumanBodyBones.Chest, head - 0.35f)) - 0.08f;
                    break;
                case "medium":
                    bottom = Height(HumanBodyBones.Hips, head - 0.6f) - 0.05f;
                    break;
                case "cowboy":
                    bottom = (Height(HumanBodyBones.LeftUpperLeg, head - 0.7f) + Height(HumanBodyBones.LeftLowerLeg, head - 1.1f)) * 0.5f;
                    break;
                default:
                    bottom = Mathf.Min(Height(HumanBodyBones.LeftFoot, 0.08f), Height(HumanBodyBones.RightFoot, 0.08f)) - 0.12f;
                    break;
            }

            float span = Mathf.Max(0.2f, crown - bottom);
            float zoom = Mathf.Clamp(framing.Zoom <= 0f ? 1f : framing.Zoom, 0.3f, 4f);
            // Aire por encima de la cabeza: un 8 % del cuadro. El zoom recorta por abajo.
            float frameHeight = span / 0.9f / zoom;
            // Que quepan los hombros (y en horizontal algo más): en vertical los gestos amplios se
            // salen por los lados, como en el stand.
            float minWidth = (preset == "full" ? 0.7f : preset == "close" ? 0.3f : 0.5f) / zoom;
            if (frameHeight * aspect < minWidth)
            {
                frameHeight = minWidth / Mathf.Max(0.1f, aspect);
            }

            float top = crown + frameHeight * 0.08f;
            float center = top - frameHeight * 0.5f + framing.OffsetY * frameHeight;

            float fov = Mathf.Clamp(fieldOfView, 18f, 50f);
            float distance = frameHeight * 0.5f / Mathf.Tan(fov * 0.5f * Mathf.Deg2Rad);
            Vector3 headPoint = animator.GetBoneTransform(HumanBodyBones.Head) != null
                ? animator.GetBoneTransform(HumanBodyBones.Head).position
                : origin + up * head;
            Vector3 hips = animator.GetBoneTransform(HumanBodyBones.Hips) != null
                ? animator.GetBoneTransform(HumanBodyBones.Hips).position
                : origin;
            Vector3 right = Vector3.Cross(up, forward);
            float lateral = (Vector3.Dot(headPoint - origin, right) + Vector3.Dot(hips - origin, right)) * 0.5f;
            float depth = Vector3.Dot(headPoint - origin, forward);
            Vector3 frameWidthAxis = -right; // derecha de la pantalla (la cámara mira hacia -forward)
            Vector3 position = origin + right * lateral + up * center + forward * (depth + distance)
                               - frameWidthAxis * (framing.OffsetX * frameHeight * aspect);
            return new ShotPose(position, Quaternion.LookRotation(-forward, up), fov);
        }

        // ------------------------------------------------------------------
        // Gorra Noogler
        // ------------------------------------------------------------------

        /// <summary>
        /// Pone o quita la gorra de la trivia. Con gorra espera (como mucho
        /// <paramref name="timeout"/> s) al pelo aplastado de GeniesHatHair, que llega
        /// unos segundos después del avatar.
        /// </summary>
        public IEnumerator SetCap(bool on, GameObject sonia, Transform avatar, float timeout)
        {
            TriviaHat hat = Object.FindAnyObjectByType<TriviaHat>(FindObjectsInactive.Include);
            if (!on)
            {
                if (hat != null)
                {
                    hat.SetOn(false, true);
                }

                yield break;
            }

            if (hat == null)
            {
                TriviaController trivia = Object.FindAnyObjectByType<TriviaController>(FindObjectsInactive.Include);
                hat = (trivia != null ? trivia.gameObject : sonia).AddComponent<TriviaHat>();
            }

            float since = Time.realtimeSinceStartup;
            bool asked = false;
            while (avatar != null && HatHair.Find(avatar) == null)
            {
                float waited = Time.realtimeSinceStartup - since;
                if (!asked && waited > 20f)
                {
                    asked = true;
                    HatHair.Request(avatar);
                }

                if (waited > timeout)
                {
                    Debug.LogWarning("[Vídeo] Sin pelo aplastado para la gorra tras " + timeout + " s: se pone igual.");
                    break;
                }

                yield return null;
            }

            hat.SetOn(true, true);
        }

        // ------------------------------------------------------------------
        // Deshacer
        // ------------------------------------------------------------------

        /// <summary>Todo como estaba: fondo del stand, luces, exposición y partículas.</summary>
        public void Restore(StageScreen screen, CameraFramingController controller)
        {
            RestoreLights();
            SetExposure(0f);
            if (screen != null)
            {
                screen.SetBackdrop(null, Color.white);
            }

            StageParticles.SetQualityAllows(true);
            if (controller != null)
            {
                controller.ClearOverride();
            }

            for (int i = _created.Count - 1; i >= 0; i--)
            {
                if (_created[i] is GameObject go && go.GetComponent<Volume>() != null)
                {
                    continue;
                }

                if (_created[i] is VolumeProfile)
                {
                    continue;
                }

                if (_created[i] != null)
                {
                    Object.Destroy(_created[i]);
                }

                _created.RemoveAt(i);
            }
        }

        private static Color ParseColor(string value, Color fallback)
        {
            return !string.IsNullOrEmpty(value) && ColorUtility.TryParseHtmlString(value, out Color c) ? c : fallback;
        }

        /// <summary>Lee un campo privado (o público) por reflexión; null si no existe.</summary>
        public static object GetField(object target, string name)
        {
            return target?.GetType().GetField(name, Any)?.GetValue(target);
        }

        /// <summary>Pone un campo privado (o público) por reflexión. Falso si no existe.</summary>
        public static bool SetField(object target, string name, object value)
        {
            FieldInfo field = target?.GetType().GetField(name, Any);
            if (field == null)
            {
                Debug.LogWarning("[Vídeo] " + (target != null ? target.GetType().Name : "?") + " no tiene " + name);
                return false;
            }

            field.SetValue(target, value);
            return true;
        }
    }
}
