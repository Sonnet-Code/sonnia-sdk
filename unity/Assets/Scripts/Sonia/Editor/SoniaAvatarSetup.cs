// Places the Sonnia avatar spot in the scene, wires it and sets up the screen framing.
//
// Sonnia uses Genies avatars, which the SDK only builds in Play, so no avatar
// is visible in edit mode. The scene keeps an empty anchor ("Avatar", no mesh
// or Animator) under the Sonia object that says where the avatar goes and
// which way it faces; on entering Play GeniesAvatarLoader loads the SDK avatar
// and AvatarBinder puts it at the anchor. Outside the Sonia hierarchy, a
// disabled fallback Sticker avatar from the Genies Avatar Starter Pack (same
// skeleton and same FACS face) is kept: it is only shown if the SDK delivers
// no avatar (without the SDK it is the avatar; with it, the last resort), and
// it is used to measure the framing with Sonnia > Recompute Framing (fallback
// avatar).
//
// A few things that are not obvious:
//
//  * Genies avatars face +Z, and the screen camera sits at negative Z looking
//    toward +Z, so the anchor is rotated 180 degrees on Y.
//  * The fallback avatar lives outside the Sonia hierarchy on purpose: several
//    components look for an Animator or meshes among their children if none is
//    assigned, and must not end up with the disabled fallback.
//  * Sticker's Humanoid is aligned with that of the SDK avatars: head on the
//    Head bone (Genies mapped it to Face) and eyes outside the Humanoid,
//    because gaze moves the eyeballs (LeftEye, RightEye) and not the sockets,
//    which would drag the eyelashes along.
//  * The face is written by FaceRig (on the Sonia object): it translates the
//    lip-sync, blink and expression channels to Genies FACS shapes.
//  * The screen framing is a vertical 9:16 medium shot: from a little below
//    the hips to just above the head, with very little headroom. It is
//    computed from the avatar's real bones, not from renderer bounds, because
//    accessories widen them and spoil the calculation.

#if UNITY_EDITOR

using TMPro;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Sonia.EditorTools
{
    /// <summary>Menus that set up the avatar and put the camera and panel in place.</summary>
    public static class SoniaAvatarSetup
    {
        /// <summary>Fallback avatar: the avatar without the SDK, the last resort if the SDK delivers none, and the reference for measuring the framing.</summary>
        public const string StandInAvatarPath = "Assets/Avatar/Genies/Sticker/Sticker.fbx";

        /// <summary>Definition (Genies SDK JSON) of the avatar loaded in Play.</summary>
        public const string GeniesDefinitionPath = "Assets/Sonia/Avatar/SoniaGeniesAvatar.json";

        /// <summary>Empty anchor under Sonia: where AvatarBinder puts the SDK avatar.</summary>
        private const string AvatarObjectName = "Avatar";

        /// <summary>Root object with the fallback Sticker avatar, disabled.</summary>
        public const string StandInObjectName = "Sonia (fallback)";
        private const string RootName = "Sonia";
        private const string PanelName = "ImagePanel";
        private const string UndoName = "Place Sonnia avatar";

        // ------------------------------------------------------------------
        // Screen framing
        // ------------------------------------------------------------------

        /// <summary>Vertical field of view of the camera, in degrees.</summary>
        private const float CameraFieldOfView = 40f;

        /// <summary>Meters left above the head. Very little headroom on purpose.</summary>
        private const string TopMarginKey = "Sonia.FramingTopMargin";

        private const float DefaultTopMargin = 0.12f;

        /// <summary>Meters visible below the hips.</summary>
        private const float HipMargin = 0.05f;

        /// <summary>
        /// Depth of the image panel. It goes behind the avatar; the size is
        /// computed later so it fits in the free area of the screen.
        /// </summary>
        private const float PanelDepth = 2.6f;

        /// <summary>
        /// Right edge of the panel in screen coordinates, where 1 is the edge of
        /// the image. A little space is left so it does not touch the frame.
        /// </summary>
        private const float PanelScreenRightEdge = 0.97f;

        /// <summary>
        /// Space between the head silhouette and the left edge of the panel, in
        /// the same screen units.
        /// </summary>
        private const float PanelHeadGap = 0.015f;

        /// <summary>Top edge of the panel block in screen coordinates.</summary>
        private const float PanelScreenTopEdge = 0.93f;

        /// <summary>
        /// Fraction of the screen width the image takes in the panel shot.
        /// Any less and it is hard to read from a distance.
        /// </summary>
        private const float PanelShotScreenWidth = 0.76f;

        /// <summary>
        /// Meters below the shoulders where the bottom edge of the screen falls
        /// in the panel shot: Sonnia is seen from the chest up.
        /// </summary>
        private const float PanelShotChestDrop = 0.1f;

        /// <summary>
        /// Screen height at which the top of the head falls in the panel shot.
        /// Negative: just below the center, to leave the top half free.
        /// </summary>
        private const float PanelShotHeadTopV = -0.13f;

        /// <summary>Panel aspect ratio. Gallery images are 16:9.</summary>
        private const float PanelAspect = 16f / 9f;

        /// <summary>Gap between the bottom edge of the image and the caption, in meters.</summary>
        private const float CaptionGap = 0.025f;

        /// <summary>Height of the caption box, as a fraction of the panel height.</summary>
        private const float CaptionHeightFactor = 0.3f;

        /// <summary>Aspect ratio of the screen, to compute the visible width.</summary>
        private const float StandAspect = (float)SoniaCapture.Width / SoniaCapture.Height;

        // ------------------------------------------------------------------
        // Wide shot for dances and greetings
        // ------------------------------------------------------------------

        /// <summary>Meters visible below the feet in the wide shot.</summary>
        private const float WideFootMargin = 0.05f;

        /// <summary>Meters of headroom above the head in the wide shot.</summary>
        private const float WideHeadMargin = 0.15f;

        /// <summary>
        /// Arm span that has to fit across. In 9:16 the width is what limits,
        /// not the height: with the widest gestures the arms reached 1.49 m
        /// tip to tip, so 1.55 leaves a little to spare.
        /// </summary>
        private const float WideArmSpan = 1.55f;

        // ------------------------------------------------------------------
        // Backdrop and light
        // ------------------------------------------------------------------

        private const string BackdropName = "Backdrop";
        private const string TextureFolder = "Assets/Sonia/Textures";
        private const string MaterialFolder = "Assets/Sonia/Materials";
        private const string BackdropMaterialPath = MaterialFolder + "/SoniaBackdrop.mat";
        private const string BackdropTexturePath = TextureFolder + "/SoniaBackdrop.asset";

        /// <summary>
        /// Behind the image panel. It must really be BEHIND: if it is in front,
        /// the backdrop covers the panel and the image is not visible.
        /// </summary>
        private const float BackdropZ = PanelDepth + 0.6f;

        /// <summary>Backdrop margin over what the widest camera sees.</summary>
        private const float BackdropMargin = 1.2f;

        private static readonly Color CameraBackground = new Color32(0x0E, 0x1B, 0x33, 0xFF);
        private static readonly Color BackdropTop = new Color32(0x2A, 0x31, 0x42, 0xFF);
        private static readonly Color BackdropBottom = new Color32(0x12, 0x15, 0x1C, 0xFF);

        /// <summary>Key light: warm, soft and frontal, so the face does not burn out.</summary>
        private static readonly Color KeyLightColor = new Color32(0xFF, 0xF4, 0xE6, 0xFF);

        private const float KeyLightIntensity = 1f;

        /// <summary>
        /// Frontal and from above. Y is near 0 degrees because the avatar faces
        /// -Z: with the light pointing at -Z it would be backlit and the face dark.
        /// </summary>
        private static readonly Vector3 KeyLightRotation = new Vector3(25f, 340f, 0f);

        /// <summary>Meters of headroom above the head in the framing.</summary>
        public static float TopMargin
        {
            get { return EditorPrefs.GetFloat(TopMarginKey, DefaultTopMargin); }
            set { EditorPrefs.SetFloat(TopMarginKey, value); }
        }

        // ------------------------------------------------------------------
        // Menus
        // ------------------------------------------------------------------

        [MenuItem("Sonnia/Place Avatar")]
        public static void PlaceAvatarMenu()
        {
            PlaceAvatar(true);
        }

        [MenuItem("Sonnia/Recompute Framing (fallback avatar)")]
        public static void ReframeMenu()
        {
            Reframe(true);
        }

        /// <summary>
        /// Sets up the avatar spot in the active scene and wires it, with no
        /// avatar in sight: under the "Sonia" object, the empty "Avatar" anchor
        /// (where AvatarBinder will put the SDK avatar in Play) and, outside its
        /// hierarchy, the disabled fallback Sticker avatar (the loader's last
        /// resort). It does not touch the camera, panel or light: <see cref="Reframe"/> does.
        /// Saves the scene. With <paramref name="interactive"/> false it opens no
        /// dialogs. Returns the anchor, or null if it could not be done.
        /// </summary>
        public static Transform PlaceAvatar(bool interactive = true)
        {
            Scene scene = SceneManager.GetActiveScene();
            if (!scene.IsValid() || !scene.isLoaded)
            {
                Report(interactive, "No scene is open.");
                return null;
            }

            SoniaBootstrap bootstrap = FindInScene<SoniaBootstrap>(scene);
            Transform root = bootstrap != null ? bootstrap.transform : FindRootByName(scene);
            if (root == null)
            {
                Report(interactive, "There is no \"" + RootName + "\" object in scene " + scene.name
                                    + ". Run Sonnia > Create Base Scene first.");
                return null;
            }

            int undoGroup = Undo.GetCurrentGroup();

            // It is rebuilt from scratch so the menu can be run as many times
            // as needed without piling up avatars.
            Transform previous = root.Find(AvatarObjectName);
            if (previous != null)
            {
                Undo.DestroyObjectImmediate(previous.gameObject);
            }

            GameObject anchorObject = new GameObject(AvatarObjectName);
            Undo.RegisterCreatedObjectUndo(anchorObject, UndoName);
            Transform anchor = anchorObject.transform;
            anchor.SetParent(root, false);
            anchor.localPosition = Vector3.zero;

            // Genies avatars face +Z; the camera looks toward +Z too, so the
            // anchor must be turned around to face it.
            anchor.localRotation = Quaternion.Euler(0f, 180f, 0f);
            anchor.localScale = Vector3.one;

            Transform standIn = PlaceStandIn(scene, anchor);

            // No avatar until Play: the Animator, head, eyes and face are hooked
            // up by AvatarBinder.Bind when the SDK avatar arrives.
            FaceRig faceRig = WireFaceRig(root, null);
            WireAvatarState(root, null, faceRig);
            WireLipSync(root, faceRig);
            WireAvatarLoading(root, anchor, standIn);
            WireChoreography(root, null);
            SoniaSceneSetup.EnsurePhonemeLipSync(root.gameObject, root.GetComponentInChildren<AvatarStateController>(true));
            SoniaSceneSetup.EnsureEyeGaze(
                root.gameObject,
                root.GetComponentInChildren<AvatarStateController>(true),
                root.GetComponentInChildren<AvatarChoreographer>(true),
                null);
            SoniaSceneSetup.EnsureFacialExpressions(
                root.gameObject, root.GetComponentInChildren<AvatarStateController>(true));

            if (interactive)
            {
                Selection.activeGameObject = anchorObject;
            }

            Undo.SetCurrentGroupName(UndoName);
            Undo.CollapseUndoOperations(undoGroup);
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);

            Debug.Log(
                "[Sonnia] Avatar spot ready: anchor \"" + AvatarObjectName + "\" (the SDK avatar is placed there in Play)"
                + (standIn != null ? " and disabled fallback \"" + StandInObjectName + "\"" : ", no fallback")
                + ". The camera, panel and light are not touched.",
                anchorObject);
            return anchor;
        }

        /// <summary>
        /// Recomputes the screen framing (camera, wide and panel shots, image
        /// panel, backdrop and light) with the fallback avatar's measurements; it
        /// is switched on only while measuring. The saved framing was tuned with
        /// the SDK avatar, and the fallback has other measurements: the shot
        /// changes a little. Saves the scene. Returns whether it worked.
        /// </summary>
        public static bool Reframe(bool interactive = true)
        {
            Scene scene = SceneManager.GetActiveScene();
            SoniaBootstrap bootstrap = scene.IsValid() ? FindInScene<SoniaBootstrap>(scene) : null;
            Transform root = bootstrap != null ? bootstrap.transform : (scene.IsValid() ? FindRootByName(scene) : null);
            GameObject standIn = root != null ? FindRootObject(scene, StandInObjectName) : null;
            if (root == null || standIn == null)
            {
                Report(interactive, "There is no fallback avatar to measure with. Run Sonnia > Place Avatar in the screen scene first.");
                return false;
            }

            int undoGroup = Undo.GetCurrentGroup();
            bool wasActive = standIn.activeSelf;
            standIn.SetActive(true);
            try
            {
                Animator animator = standIn.GetComponentInChildren<Animator>(true);
                float headTop;
                float hipsY;
                float shouldersY;
                MeasureAvatar(standIn, animator, out hipsY, out headTop, out shouldersY);

                Vector3 widePosition;
                Vector3 panelPosition;
                Camera camera = SetUpFraming(
                    scene, hipsY, headTop, shouldersY, out widePosition, out panelPosition);
                SetUpImagePanel(root, standIn, animator, camera, panelPosition);
                SetUpBackdrop(root, camera, widePosition, panelPosition);
                SetUpLighting(scene);
                Transform head = animator != null && animator.isHuman ? animator.GetBoneTransform(HumanBodyBones.Head) : null;
                if (head != null && camera != null)
                {
                    SoniaStageLighting.Apply(scene, head.position, camera);
                }

                WireCameraFraming(root, animator, camera, widePosition, panelPosition);
                Debug.Log(
                    "[Sonnia] Framing recomputed with the fallback avatar: hips y=" + hipsY.ToString("F2")
                    + ", shoulders y=" + shouldersY.ToString("F2") + ", head top y=" + headTop.ToString("F2") + ".",
                    camera);
            }
            finally
            {
                standIn.SetActive(wasActive);
            }

            Undo.SetCurrentGroupName("Recompute Sonnia framing");
            Undo.CollapseUndoOperations(undoGroup);
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
            return true;
        }

        /// <summary>
        /// The fallback Sticker avatar, disabled and outside the Sonia hierarchy,
        /// at the anchor's spot. Null if the FBX is missing (then there is no fallback).
        /// </summary>
        private static Transform PlaceStandIn(Scene scene, Transform anchor)
        {
            GameObject old = FindRootObject(scene, StandInObjectName);
            if (old != null)
            {
                Undo.DestroyObjectImmediate(old);
            }

            AlignGeniesHumanoid(StandInAvatarPath);
            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(StandInAvatarPath);
            if (prefab == null)
            {
                Debug.LogWarning("[Sonnia] Fallback avatar not found at " + StandInAvatarPath + " (Genies Avatar Starter Pack, "
                                 + "see Assets/Avatar/Genies/LICENSE.md): if the SDK delivers no avatar, there will be no fallback.");
                return null;
            }

            GameObject standIn = (GameObject)PrefabUtility.InstantiatePrefab(prefab, scene);
            if (standIn == null)
            {
                Debug.LogError("[Sonnia] Could not instantiate " + StandInAvatarPath + ".");
                return null;
            }

            Undo.RegisterCreatedObjectUndo(standIn, UndoName);
            standIn.name = StandInObjectName;
            standIn.transform.SetPositionAndRotation(anchor.position, anchor.rotation);
            standIn.transform.localScale = Vector3.one;
            ConfigureAnimator(standIn.GetComponentInChildren<Animator>(true));
            standIn.SetActive(false);
            return standIn.transform;
        }

        // ------------------------------------------------------------------
        // Avatar
        // ------------------------------------------------------------------

        private static void ConfigureAnimator(Animator animator)
        {
            if (animator == null)
            {
                Debug.LogWarning("[Sonnia] The avatar has no Animator; there will be no animations.");
                return;
            }

            Undo.RecordObject(animator, UndoName);

            // MotionPlayer plays the clips with the Playables API; the Animator
            // only provides humanoid retargeting and has no controller.
            animator.runtimeAnimatorController = null;

            // Animations play in place: the avatar does not move from the
            // scene origin.
            animator.applyRootMotion = false;

            // The camera always sees it, but with default culling a frame
            // off screen freezes the pose and the lip-sync.
            animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            EditorUtility.SetDirty(animator);
        }

        /// <summary>
        /// Measures the avatar with the humanoid rig bones. Renderer bounds are
        /// not used because accessories (backpacks, weapons, robotic arms)
        /// widen them and would give an absurd framing.
        /// </summary>
        private static void MeasureAvatar(
            GameObject avatar,
            Animator animator,
            out float hipsY,
            out float headTop,
            out float shouldersY)
        {
            hipsY = 0.79f;
            headTop = 1.55f;
            shouldersY = 1.25f;

            if (animator == null || !animator.isHuman)
            {
                Debug.LogWarning("[Sonnia] The avatar has no humanoid rig; default measurements are used.");
                return;
            }

            Transform hips = animator.GetBoneTransform(HumanBodyBones.Hips);
            Transform head = animator.GetBoneTransform(HumanBodyBones.Head);
            Transform leftShoulder = animator.GetBoneTransform(HumanBodyBones.LeftUpperArm);
            Transform rightShoulder = animator.GetBoneTransform(HumanBodyBones.RightUpperArm);

            if (hips != null)
            {
                hipsY = hips.position.y;
            }

            if (leftShoulder != null && rightShoulder != null)
            {
                shouldersY = (leftShoulder.position.y + rightShoulder.position.y) * 0.5f;
            }
            else if (head != null)
            {
                shouldersY = head.position.y - 0.15f;
            }

            if (head == null)
            {
                return;
            }

            // The real head height comes from the renderer, which includes the
            // hair, but clamped to the bone: a tall accessory then cannot
            // blow up the framing.
            float headBoneY = head.position.y;
            float measured = headBoneY;
            Renderer[] renderers = avatar.GetComponentsInChildren<Renderer>(true);
            for (int i = 0; i < renderers.Length; i++)
            {
                measured = Mathf.Max(measured, renderers[i].bounds.max.y);
            }

            headTop = Mathf.Clamp(measured, headBoneY + 0.10f, headBoneY + 0.35f);
        }

        // ------------------------------------------------------------------
        // Framing and panel
        // ------------------------------------------------------------------

        /// <summary>
        /// Sets the camera to a vertical medium shot: from a little below the
        /// hips to just above the head, with very little headroom.
        /// </summary>
        private static Camera SetUpFraming(
            Scene scene,
            float hipsY,
            float headTop,
            float shouldersY,
            out Vector3 widePosition,
            out Vector3 panelPosition)
        {
            widePosition = new Vector3(0f, 0.83f, -2.7f);
            panelPosition = new Vector3(0f, 1.62f, -1.42f);

            Camera camera = Camera.main;
            if (camera == null)
            {
                camera = FindInScene<Camera>(scene);
            }

            if (camera == null)
            {
                Debug.LogWarning("[Sonnia] There is no camera in the scene; the framing cannot be adjusted.");
                return null;
            }

            float tangentHalf = Mathf.Tan(CameraFieldOfView * 0.5f * Mathf.Deg2Rad);

            float bottom = hipsY - HipMargin;
            float top = headTop + TopMargin;
            float visibleHeight = Mathf.Max(0.2f, top - bottom);
            float distance = (visibleHeight * 0.5f)
                             / Mathf.Tan(CameraFieldOfView * 0.5f * Mathf.Deg2Rad);

            Undo.RecordObject(camera.transform, UndoName);
            Undo.RecordObject(camera, UndoName);
            camera.transform.position = new Vector3(0f, (top + bottom) * 0.5f, -distance);
            camera.transform.rotation = Quaternion.identity;
            camera.fieldOfView = CameraFieldOfView;
            camera.nearClipPlane = 0.05f;

            // No sky: the template horizon crossed the avatar's chest.
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = CameraBackground;
            EditorUtility.SetDirty(camera);

            // Wide shot for dances: from the feet to above the head, with room
            // at the sides for the arms. In 9:16 the width almost always limits,
            // not the height.
            float wideBottom = -WideFootMargin;
            float wideTop = headTop + WideHeadMargin;
            float wideDistance = Mathf.Max(
                ((wideTop - wideBottom) * 0.5f) / tangentHalf,
                (WideArmSpan * 0.5f) / (tangentHalf * StandAspect));
            widePosition = new Vector3(0f, (wideTop + wideBottom) * 0.5f, -wideDistance);

            // Panel shot: Sonnia from the chest up in the bottom half and the
            // top half free for the image. It is solved by asking for the
            // bottom edge to fall at the chest and the top of the head just
            // below the center of the screen.
            float chestY = shouldersY - PanelShotChestDrop;
            float panelCameraY = (headTop + (PanelShotHeadTopV * chestY)) / (1f + PanelShotHeadTopV);
            float panelHalfHeight = Mathf.Max(0.2f, panelCameraY - chestY);
            panelPosition = new Vector3(0f, panelCameraY, -(panelHalfHeight / tangentHalf));

            Debug.Log(
                "[Sonnia] 9:16 framing: visible from y=" + bottom.ToString("F2") + " to y=" + top.ToString("F2")
                + " (" + visibleHeight.ToString("F2") + " m). Camera at (0, "
                + ((top + bottom) * 0.5f).ToString("F2") + ", " + (-distance).ToString("F2")
                + ") with FOV " + CameraFieldOfView + ". Wide shot at "
                + widePosition.ToString("F2") + ", panel shot at "
                + panelPosition.ToString("F2") + ".",
                camera);

            return camera;
        }

        /// <summary>Half the visible width, in meters, at that world Z and in 9:16.</summary>
        private static float VisibleHalfWidthAt(Camera camera, float worldZ)
        {
            return VisibleHalfWidthAt(camera.transform.position.z, worldZ);
        }

        /// <summary>The same, but for a camera pose that does not exist in the scene yet.</summary>
        private static float VisibleHalfWidthAt(float cameraZ, float worldZ)
        {
            float distance = Mathf.Max(0.1f, worldZ - cameraZ);
            return distance * Mathf.Tan(CameraFieldOfView * 0.5f * Mathf.Deg2Rad) * StandAspect;
        }

        /// <summary>
        /// Places the image panel large and centered above the head.
        ///
        /// The size is computed on the PANEL SHOT, not on the medium shot: when
        /// an image appears the camera pulls back and rises, the top half of the
        /// screen is free and an image that can be read from a distance fits
        /// there. All in screen coordinates, where 1 is the edge of the image.
        /// </summary>
        private static void SetUpImagePanel(
            Transform root,
            GameObject avatar,
            Animator animator,
            Camera camera,
            Vector3 panelCameraPosition)
        {
            Transform panel = root.Find(PanelName);
            if (panel == null || camera == null)
            {
                return;
            }

            float headEdgeU;
            float headTopV;
            MeasureHeadOnScreen(avatar, animator, panelCameraPosition, out headEdgeU, out headTopV);

            float halfWidth = VisibleHalfWidthAt(panelCameraPosition.z, PanelDepth);
            float halfHeight = halfWidth / StandAspect;

            float width = PanelShotScreenWidth * 2f * halfWidth;
            float height = width / PanelAspect;

            // Free band above the top of the head. The block is the image plus
            // the caption, centered in that band.
            float bandBottom = headTopV + PanelHeadGap;
            float bandHeight = Mathf.Max(0.2f, PanelScreenTopEdge - bandBottom) * halfHeight;
            float blockHeight = height * (1f + CaptionHeightFactor) + CaptionGap;

            // If the block does not fit in height, height wins and the image shrinks.
            if (blockHeight > bandHeight)
            {
                height = (bandHeight - CaptionGap) / (1f + CaptionHeightFactor);
                width = height * PanelAspect;
                blockHeight = bandHeight;
            }

            float blockCenterY = panelCameraPosition.y
                                 + ((bandBottom + PanelScreenTopEdge) * 0.5f * halfHeight);
            float y = blockCenterY + (blockHeight * 0.5f) - (height * 0.5f);

            Undo.RecordObject(panel, UndoName);
            panel.localPosition = new Vector3(0f, y, PanelDepth);
            panel.localRotation = Quaternion.identity;
            EditorUtility.SetDirty(panel);

            Transform quad = panel.Find("Quad");
            if (quad != null)
            {
                Undo.RecordObject(quad, UndoName);
                quad.localScale = new Vector3(width, height, 1f);
                EditorUtility.SetDirty(quad);
            }

            SetUpCaption(panel, width, height);

            // The component recomputes the real size when showing the image, so
            // it has to be adjusted there too or it would go back to the old panel.
            ImagePanelController controller = panel.GetComponent<ImagePanelController>();
            if (controller != null)
            {
                SerializedObject serialized = new SerializedObject(controller);
                SetFloat(serialized, "panelHeight", height);
                SetFloat(serialized, "panelMaxWidth", width);
                serialized.ApplyModifiedPropertiesWithoutUndo();
            }

            Debug.Log(
                "[Sonnia] Image panel at " + panel.localPosition.ToString("F2") + ", "
                + width.ToString("F2") + " x " + height.ToString("F2")
                + " m. In the panel shot it is "
                + Mathf.RoundToInt(width / halfWidth * SoniaCapture.Width * 0.5f)
                + " px wide, i.e. " + Mathf.RoundToInt(width / (halfWidth * 2f) * 100f)
                + " % of the screen; the top of the head is at y=" + headTopV.ToString("F2") + ".",
                panel);
        }

        /// <summary>
        /// Caption below the image, centered and auto-sized so it never
        /// exceeds the panel width.
        /// </summary>
        private static void SetUpCaption(Transform panel, float width, float height)
        {
            Transform caption = panel.Find("Caption");
            if (caption == null)
            {
                return;
            }

            Undo.RecordObject(caption, UndoName);
            float captionHeight = height * CaptionHeightFactor;
            caption.localPosition = new Vector3(0f, -((height * 0.5f) + CaptionGap + (captionHeight * 0.5f)), 0f);
            caption.localRotation = Quaternion.identity;
            caption.localScale = Vector3.one;

            RectTransform rect = caption.GetComponent<RectTransform>();
            if (rect != null)
            {
                rect.sizeDelta = new Vector2(width, captionHeight);
            }

            TMP_Text label = caption.GetComponent<TMP_Text>();
            if (label != null)
            {
                Undo.RecordObject(label, UndoName);
                label.alignment = TextAlignmentOptions.Center;

                // The text shrinks until it fits the box: a long caption
                // reduces the font instead of running off the screen edge.
                label.enableAutoSizing = true;
                label.fontSizeMin = width * 0.08f;
                label.fontSizeMax = width * 2f;
                label.fontSize = label.fontSizeMax;
                label.margin = Vector4.zero;
                EditorUtility.SetDirty(label);
            }

            EditorUtility.SetDirty(caption);
        }

        /// <summary>
        /// Projects the head onto the screen and returns where its right edge
        /// and top fall, in units where 1 is the edge of the image. Only meshes
        /// that start at neck height or above count: the body, with arms out,
        /// would cover the whole screen.
        /// </summary>
        private static void MeasureHeadOnScreen(
            GameObject avatar,
            Animator animator,
            Vector3 cameraPosition,
            out float rightEdge,
            out float topEdge)
        {
            rightEdge = 0.35f;
            topEdge = 0.72f;

            Transform head = animator != null ? animator.GetBoneTransform(HumanBodyBones.Head) : null;
            if (head == null)
            {
                return;
            }

            float neckY = head.position.y - 0.15f;
            bool found = false;
            Bounds headBounds = new Bounds();

            Renderer[] renderers = avatar.GetComponentsInChildren<Renderer>(true);
            for (int i = 0; i < renderers.Length; i++)
            {
                Bounds bounds = renderers[i].bounds;
                if (bounds.min.y < neckY)
                {
                    continue;
                }

                if (!found)
                {
                    headBounds = bounds;
                    found = true;
                }
                else
                {
                    headBounds.Encapsulate(bounds);
                }
            }

            if (!found)
            {
                return;
            }

            float tangent = Mathf.Tan(CameraFieldOfView * 0.5f * Mathf.Deg2Rad);

            // Projected from the box's Z center: using the front face
            // exaggerates the width of a nearly round head and the panel would
            // end up tiny.
            float depth = Mathf.Max(0.1f, headBounds.center.z - cameraPosition.z);
            rightEdge = headBounds.max.x / (depth * tangent * StandAspect);
            topEdge = (headBounds.max.y - cameraPosition.y) / (depth * tangent);
        }

        // ------------------------------------------------------------------
        // Backdrop and light
        // ------------------------------------------------------------------

        /// <summary>
        /// Puts a backdrop behind the avatar with a soft vertical gradient. Without
        /// it the flat camera color shows, which looks dead; with it Sonnia's
        /// light silhouette stands out against a dark background.
        /// </summary>
        private static void SetUpBackdrop(
            Transform root,
            Camera camera,
            Vector3 widePosition,
            Vector3 panelPosition)
        {
            if (camera == null)
            {
                return;
            }

            Transform backdrop = root.Find(BackdropName);
            GameObject backdropObject;
            if (backdrop == null)
            {
                backdropObject = GameObject.CreatePrimitive(PrimitiveType.Quad);
                backdropObject.name = BackdropName;
                backdropObject.transform.SetParent(root, false);
                Undo.RegisterCreatedObjectUndo(backdropObject, UndoName);

                Collider collider = backdropObject.GetComponent<Collider>();
                if (collider != null)
                {
                    Object.DestroyImmediate(collider);
                }
            }
            else
            {
                backdropObject = backdrop.gameObject;
            }

            // It must cover the screen in all THREE shots, and each one sees a
            // different strip of the backdrop plane: the union of all is covered.
            float tangent = Mathf.Tan(CameraFieldOfView * 0.5f * Mathf.Deg2Rad);
            float bottom = float.MaxValue;
            float top = float.MinValue;
            float halfWidth = 0f;

            Vector3[] poses = { camera.transform.position, widePosition, panelPosition };
            for (int i = 0; i < poses.Length; i++)
            {
                float halfHeight = (BackdropZ - poses[i].z) * tangent;
                bottom = Mathf.Min(bottom, poses[i].y - halfHeight);
                top = Mathf.Max(top, poses[i].y + halfHeight);
                halfWidth = Mathf.Max(halfWidth, halfHeight * StandAspect);
            }

            Undo.RecordObject(backdropObject.transform, UndoName);
            backdropObject.transform.localPosition = new Vector3(0f, (top + bottom) * 0.5f, BackdropZ);
            backdropObject.transform.localRotation = Quaternion.identity;
            backdropObject.transform.localScale = new Vector3(
                halfWidth * 2f * BackdropMargin, (top - bottom) * BackdropMargin, 1f);

            MeshRenderer renderer = backdropObject.GetComponent<MeshRenderer>();
            if (renderer != null)
            {
                Undo.RecordObject(renderer, UndoName);
                renderer.sharedMaterial = LoadOrCreateBackdropMaterial();
                renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
                renderer.receiveShadows = false;
                EditorUtility.SetDirty(renderer);
            }

            EditorUtility.SetDirty(backdropObject);
        }

        /// <summary>
        /// Unlit backdrop material, with the navy gradient generated in code.
        /// </summary>
        private static Material LoadOrCreateBackdropMaterial()
        {
            Material material = AssetDatabase.LoadAssetAtPath<Material>(BackdropMaterialPath);
            Texture2D gradient = AssetDatabase.LoadAssetAtPath<Texture2D>(BackdropTexturePath);

            if (gradient == null)
            {
                EnsureFolder(TextureFolder);

                // Four pixels wide are enough: the gradient only changes vertically.
                gradient = new Texture2D(4, 256, TextureFormat.RGBA32, false, false);
                gradient.name = "SoniaBackdrop";
                gradient.wrapMode = TextureWrapMode.Clamp;
                gradient.filterMode = FilterMode.Bilinear;

                for (int y = 0; y < gradient.height; y++)
                {
                    float t = y / (float)(gradient.height - 1);
                    Color row = Color.Lerp(BackdropBottom, BackdropTop, t);
                    for (int x = 0; x < gradient.width; x++)
                    {
                        gradient.SetPixel(x, y, row);
                    }
                }

                gradient.Apply(false, false);
                AssetDatabase.CreateAsset(gradient, BackdropTexturePath);
            }

            if (material == null)
            {
                EnsureFolder(MaterialFolder);

                Shader shader = Shader.Find("Universal Render Pipeline/Unlit");
                if (shader == null)
                {
                    shader = Shader.Find("Unlit/Texture");
                }

                material = new Material(shader);
                material.name = "SoniaBackdrop";
                AssetDatabase.CreateAsset(material, BackdropMaterialPath);
            }

            if (material.HasProperty("_BaseMap"))
            {
                material.SetTexture("_BaseMap", gradient);
            }

            if (material.HasProperty("_BaseColor"))
            {
                material.SetColor("_BaseColor", Color.white);
            }

            material.mainTexture = gradient;

            // The generated gradient already has the backdrop's proportions.
            Vector2 tiling = Vector2.one;
            Vector2 offset = Vector2.zero;
            material.mainTextureScale = tiling;
            material.mainTextureOffset = offset;
            if (material.HasProperty("_BaseMap"))
            {
                material.SetTextureScale("_BaseMap", tiling);
                material.SetTextureOffset("_BaseMap", offset);
            }
            EditorUtility.SetDirty(material);
            AssetDatabase.SaveAssets();
            return material;
        }

        /// <summary>
        /// Softens the template light. It came at intensity 2 and very overhead,
        /// which burned out the face and any white clothing.
        /// </summary>
        private static void SetUpLighting(Scene scene)
        {
            Light key = null;
            GameObject[] roots = scene.GetRootGameObjects();
            for (int i = 0; i < roots.Length && key == null; i++)
            {
                Light[] lights = roots[i].GetComponentsInChildren<Light>(true);
                for (int j = 0; j < lights.Length; j++)
                {
                    if (lights[j].type == LightType.Directional)
                    {
                        key = lights[j];
                        break;
                    }
                }
            }

            if (key == null)
            {
                Debug.LogWarning("[Sonnia] There is no directional light in the scene.");
                return;
            }

            Undo.RecordObject(key, UndoName);
            Undo.RecordObject(key.transform, UndoName);
            key.intensity = KeyLightIntensity;
            key.color = KeyLightColor;
            key.transform.rotation = Quaternion.Euler(KeyLightRotation);
            EditorUtility.SetDirty(key);

            AdjustPostProcessing(scene);
        }

        /// <summary>
        /// Lowers the bloom and sets a neutral tonemapping. The template profile
        /// has a generous bloom that, with white clothing in full light, eats
        /// all the detail.
        /// </summary>
        private static void AdjustPostProcessing(Scene scene)
        {
            GameObject[] roots = scene.GetRootGameObjects();
            for (int i = 0; i < roots.Length; i++)
            {
                UnityEngine.Rendering.Volume[] volumes =
                    roots[i].GetComponentsInChildren<UnityEngine.Rendering.Volume>(true);
                for (int j = 0; j < volumes.Length; j++)
                {
                    UnityEngine.Rendering.VolumeProfile profile = volumes[j].sharedProfile;
                    if (profile == null)
                    {
                        continue;
                    }

                    UnityEngine.Rendering.Universal.Tonemapping tonemapping;
                    if (profile.TryGet(out tonemapping))
                    {
                        Undo.RecordObject(tonemapping, UndoName);
                        tonemapping.active = true;
                        tonemapping.mode.overrideState = true;
                        tonemapping.mode.value = UnityEngine.Rendering.Universal.TonemappingMode.Neutral;
                        EditorUtility.SetDirty(tonemapping);
                    }

                    UnityEngine.Rendering.Universal.Bloom bloom;
                    if (profile.TryGet(out bloom))
                    {
                        Undo.RecordObject(bloom, UndoName);
                        bloom.active = true;
                        bloom.intensity.overrideState = true;
                        bloom.intensity.value = 0.25f;
                        bloom.threshold.overrideState = true;
                        bloom.threshold.value = 1.1f;
                        EditorUtility.SetDirty(bloom);
                    }

                    EditorUtility.SetDirty(profile);
                }
            }

            AssetDatabase.SaveAssets();
        }

        private static void EnsureFolder(string folder)
        {
            if (AssetDatabase.IsValidFolder(folder))
            {
                return;
            }

            string parent = System.IO.Path.GetDirectoryName(folder).Replace('\\', '/');
            string leaf = System.IO.Path.GetFileName(folder);
            if (!AssetDatabase.IsValidFolder(parent))
            {
                EnsureFolder(parent);
            }

            AssetDatabase.CreateFolder(parent, leaf);
        }

        // ------------------------------------------------------------------
        // Wiring
        // ------------------------------------------------------------------

        private static void WireCameraFraming(
            Transform root,
            Animator animator,
            Camera camera,
            Vector3 widePosition,
            Vector3 panelPosition)
        {
            CameraFramingController framing = root.GetComponentInChildren<CameraFramingController>(true);
            if (framing == null)
            {
                Debug.LogWarning(
                    "[Sonnia] There is no CameraFramingController in the scene. "
                    + "Run Sonnia > Update Components.");
                return;
            }

            SerializedObject serialized = new SerializedObject(framing);
            SetReference(serialized, "choreographer", root.GetComponentInChildren<AvatarChoreographer>(true));
            SetReference(serialized, "targetCamera", camera);

            SerializedProperty position = serialized.FindProperty("wideShotPosition");
            if (position != null)
            {
                position.vector3Value = widePosition;
            }

            SerializedProperty panelShot = serialized.FindProperty("panelShotPosition");
            if (panelShot != null)
            {
                panelShot.vector3Value = panelPosition;
            }

            SetReference(serialized, "imagePanel", root.GetComponentInChildren<ImagePanelController>(true));
            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        /// <summary>Puts FaceRig on the Sonia object pointing at the avatar.</summary>
        private static FaceRig WireFaceRig(Transform root, Transform avatarRoot)
        {
            FaceRig rig = root.GetComponent<FaceRig>();
            if (rig == null)
            {
                rig = Undo.AddComponent<FaceRig>(root.gameObject);
            }

            SerializedObject serialized = new SerializedObject(rig);
            SetReference(serialized, "avatarRoot", avatarRoot);
            serialized.ApplyModifiedPropertiesWithoutUndo();
            rig.Rebuild();
            return rig;
        }

        /// <summary>
        /// Puts the AvatarBinder on the Sonia object with the anchor as the current
        /// avatar, the fallback avatar and the repo's Genies definition (only used
        /// with the Genies Avatar SDK installed).
        /// </summary>
        private static void WireAvatarLoading(Transform root, Transform anchor, Transform standIn)
        {
            AvatarBinder binder = root.GetComponent<AvatarBinder>();
            if (binder == null)
            {
                binder = Undo.AddComponent<AvatarBinder>(root.gameObject);
            }

            TextAsset definition = AssetDatabase.LoadAssetAtPath<TextAsset>(GeniesDefinitionPath);
            SerializedObject binderObject = new SerializedObject(binder);
            SetReference(binderObject, "current", anchor);
            SetReference(binderObject, "standIn", standIn);
            SetReference(binderObject, "geniesDefinition", definition);
            binderObject.ApplyModifiedPropertiesWithoutUndo();
        }

        /// <summary>A Place Avatar problem: a dialog if someone asked from the menu; otherwise the console.</summary>
        private static void Report(bool interactive, string message)
        {
            if (interactive)
            {
                EditorUtility.DisplayDialog("Sonnia", message, "OK");
            }
            else
            {
                Debug.LogWarning("[Sonnia] Place Avatar: " + message);
            }
        }

        private static void WireAvatarState(Transform root, Transform head, FaceRig faceRig)
        {
            AvatarStateController state = root.GetComponentInChildren<AvatarStateController>(true);
            if (state == null)
            {
                Debug.LogWarning("[Sonnia] There is no AvatarStateController in the scene.");
                return;
            }

            SerializedObject serialized = new SerializedObject(state);
            SetReference(serialized, "headBone", head);
            SetReference(serialized, "faceRig", faceRig);

            Camera main = Camera.main;
            if (main != null)
            {
                SetReference(serialized, "lookTarget", main.transform);
            }

            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void WireLipSync(Transform root, FaceRig faceRig)
        {
            LipSyncController lipSync = root.GetComponentInChildren<LipSyncController>(true);
            if (lipSync == null)
            {
                Debug.LogWarning("[Sonnia] There is no LipSyncController in the scene.");
                return;
            }

            SerializedObject serialized = new SerializedObject(lipSync);
            SetReference(serialized, "faceRig", faceRig);
            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        /// <summary>
        /// Makes the Humanoid of a Genies FBX like that of the SDK avatars:
        /// head on the Head bone and no eyes or jaw. Only reimports if needed.
        /// </summary>
        private static void AlignGeniesHumanoid(string assetPath)
        {
            ModelImporter importer = AssetImporter.GetAtPath(assetPath) as ModelImporter;
            if (importer == null || importer.animationType != ModelImporterAnimationType.Human)
            {
                return;
            }

            HumanDescription description = importer.humanDescription;
            HumanBone[] bones = description.human;
            if (bones == null || bones.Length == 0)
            {
                return;
            }

            bool changed = false;
            System.Collections.Generic.List<HumanBone> kept = new System.Collections.Generic.List<HumanBone>(bones.Length);
            for (int i = 0; i < bones.Length; i++)
            {
                HumanBone bone = bones[i];
                if (bone.humanName == "LeftEye" || bone.humanName == "RightEye" || bone.humanName == "Jaw")
                {
                    changed = true;
                    continue;
                }

                if (bone.humanName == "Head" && bone.boneName != "Head")
                {
                    bone.boneName = "Head";
                    changed = true;
                }

                kept.Add(bone);
            }

            if (!changed)
            {
                return;
            }

            description.human = kept.ToArray();
            importer.humanDescription = description;
            importer.SaveAndReimport();
            Debug.Log("[Sonnia] Humanoid of " + System.IO.Path.GetFileName(assetPath)
                      + " aligned with that of the SDK avatars (head on Head, no eyes or jaw).");
        }

        private static void WireChoreography(Transform root, Animator animator)
        {
            SoniaMotionSet set = SoniaMotionSetBuilder.LoadOrBuildMotionSet();
            AvatarMask mask = SoniaMotionSetBuilder.LoadOrBuildMask();
            SoniaMotionSetBuilder.Wire(root.gameObject, animator, set, mask);
        }

        // ------------------------------------------------------------------
        // Utilities
        // ------------------------------------------------------------------

        private static void SetReference(SerializedObject target, string path, Object value)
        {
            SerializedProperty property = target.FindProperty(path);
            if (property == null)
            {
                Debug.LogWarning(
                    "[Sonnia] Field \"" + path + "\" does not exist on " + target.targetObject.GetType().Name
                    + "; assign it by hand in the inspector.");
                return;
            }

            property.objectReferenceValue = value;
        }

        private static void SetString(SerializedObject target, string path, string value)
        {
            SerializedProperty property = target.FindProperty(path);
            if (property == null)
            {
                Debug.LogWarning(
                    "[Sonnia] Field \"" + path + "\" does not exist on " + target.targetObject.GetType().Name
                    + "; assign it by hand in the inspector.");
                return;
            }

            property.stringValue = value;
        }

        private static void SetFloat(SerializedObject target, string path, float value)
        {
            SerializedProperty property = target.FindProperty(path);
            if (property == null)
            {
                Debug.LogWarning(
                    "[Sonnia] Field \"" + path + "\" does not exist on " + target.targetObject.GetType().Name
                    + "; assign it by hand in the inspector.");
                return;
            }

            property.floatValue = value;
        }

        /// <summary>Assigns an enum by value name, without knowing its type at compile time.</summary>
        private static void SetEnumByName(SerializedObject target, string path, string valueName)
        {
            SerializedProperty property = target.FindProperty(path);
            if (property == null || property.propertyType != SerializedPropertyType.Enum)
            {
                Debug.LogWarning(
                    "[Sonnia] Field \"" + path + "\" does not exist or is not an enum on "
                    + target.targetObject.GetType().Name + "; set it by hand.");
                return;
            }

            string[] names = property.enumNames;
            for (int i = 0; i < names.Length; i++)
            {
                if (names[i] == valueName)
                {
                    property.enumValueIndex = i;
                    return;
                }
            }

            Debug.LogWarning(
                "[Sonnia] Enum \"" + path + "\" has no value \"" + valueName + "\"; left as it was.");
        }

        private static GameObject FindRootObject(Scene scene, string name)
        {
            GameObject[] roots = scene.GetRootGameObjects();
            for (int i = 0; i < roots.Length; i++)
            {
                if (roots[i].name == name)
                {
                    return roots[i];
                }
            }

            return null;
        }

        private static Transform FindRootByName(Scene scene)
        {
            GameObject[] roots = scene.GetRootGameObjects();
            for (int i = 0; i < roots.Length; i++)
            {
                if (roots[i].name == RootName)
                {
                    return roots[i].transform;
                }
            }

            return null;
        }

        private static T FindInScene<T>(Scene scene) where T : Component
        {
            GameObject[] roots = scene.GetRootGameObjects();
            for (int i = 0; i < roots.Length; i++)
            {
                T found = roots[i].GetComponentInChildren<T>(true);
                if (found != null)
                {
                    return found;
                }
            }

            return null;
        }
    }
}

#endif
