// Editor menu that builds the base Sonnia scene.
//
// Creates the "Sonia" object with all its components, the image panel, the
// debug HUD and, if missing, an EventSystem with the new Input System module.
// The avatar fields (SkinnedMeshRenderer, Animator, head bone) are left empty:
// whoever imports the model fills them in.
//
// Everything is designed for a vertical screen: a 1080x1920 (9:16) monitor in
// portrait. That is why the image panel sits above the avatar and not to one
// side, and the camera frames the character full body leaving room above.
// The avatar is assumed to be placed at the origin of the "Sonia" object,
// standing and facing +Z, which is where the camera looks from.

#if UNITY_EDITOR

using TMPro;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem.UI;
using UnityEngine.Rendering.Universal;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace Sonia.EditorTools
{
    /// <summary>Editor tools to build the demo scene.</summary>
    public static class SoniaSceneSetup
    {
        private const string RootName = "Sonia";
        private const string PanelName = "ImagePanel";
        private const string HudName = "SoniaHUD";

        /// <summary>Group that F1 hides.</summary>
        private const string HudDebugName = "Debug";

        /// <summary>
        /// Distance from the Canvas to the camera. With Screen Space - Camera the
        /// HUD shows up in RenderTexture renders; in Overlay it does not.
        /// </summary>
        private const float HudPlaneDistance = 0.3f;

        /// <summary>Where the debug labels start: top left.</summary>
        private static readonly Vector2 HudConnectionPosition = new Vector2(48f, -48f);

        private static readonly Vector2 HudStatePosition =
            new Vector2(HudConnectionPosition.x, HudConnectionPosition.y - 52f);
        private const string MaterialFolder = "Assets/Sonia/Materials";
        private const string MaterialPath = MaterialFolder + "/SoniaImagePanel.mat";
        private const string UndoName = "Create Sonnia base scene";

        /// <summary>Screen resolution: vertical 9:16 monitor.</summary>
        private const int ScreenWidth = 1080;

        private const int ScreenHeight = 1920;

        /// <summary>Camera position to frame the avatar full body in portrait.</summary>
        private static readonly Vector3 CameraPosition = new Vector3(0f, 1.3f, -2.7f);

        /// <summary>Vertical field of view of the camera, in degrees.</summary>
        private const float CameraFieldOfView = 52f;

        /// <summary>
        /// Center of the image panel: behind the avatar, peeking over the
        /// shoulder. It does not fit above the head, because the screen framing
        /// is a medium shot. The final position is recomputed by Sonnia > Place
        /// Avatar with the model's real bones.
        /// </summary>
        private static readonly Vector3 PanelPosition = new Vector3(0.35f, 1.35f, 0.6f);

        /// <summary>Panel size in meters: max width and height.</summary>
        private static readonly Vector2 PanelSize = new Vector2(0.55f, 0.31f);

        [MenuItem("Sonnia/Create Base Scene")]
        public static void CreateBaseScene()
        {
            Scene scene = SceneManager.GetActiveScene();
            if (!scene.IsValid())
            {
                EditorUtility.DisplayDialog("Sonnia", "No scene is open.", "OK");
                return;
            }

            if (FindInScene<SoniaBootstrap>(scene) != null)
            {
                EditorUtility.DisplayDialog(
                    "Sonnia",
                    "This scene already has a Sonia object with SoniaBootstrap. Delete it before creating it again.",
                    "OK");
                return;
            }

            // TMP_Settings.defaultFontAsset throws NullReferenceException if the
            // "TMP Essential Resources" are not imported. They are imported
            // right here (no dialog) so the HUD has a font and shader.
            if (TMP_Settings.instance == null)
            {
                Debug.Log("[Sonnia] Importing the TextMeshPro essential resources...");
                TMP_PackageResourceImporter.ImportResources(true, false, false);
                AssetDatabase.Refresh();
            }

            if (TMP_Settings.instance == null || TMP_Settings.defaultFontAsset == null)
            {
                Debug.LogWarning(
                    "[Sonnia] There are no TextMeshPro resources in the project. Import "
                    + "Window > TextMeshPro > Import TMP Essential Resources so the HUD is visible.");
            }

            int undoGroup = Undo.GetCurrentGroup();

            GameObject root = new GameObject(RootName);
            Undo.RegisterCreatedObjectUndo(root, UndoName);

            SoniaClient client = root.AddComponent<SoniaClient>();
            AudioSource audioSource = root.AddComponent<AudioSource>();
            audioSource.playOnAwake = false;
            audioSource.spatialBlend = 0f;
            AudioStreamPlayer audioPlayer = root.AddComponent<AudioStreamPlayer>();
            LipSyncController lipSync = root.AddComponent<LipSyncController>();
            AvatarStateController avatarState = root.AddComponent<AvatarStateController>();
            MotionPlayer motionPlayer = root.AddComponent<MotionPlayer>();
            AvatarChoreographer choreographer = root.AddComponent<AvatarChoreographer>();
            CameraFramingController cameraFraming = root.AddComponent<CameraFramingController>();
            WebcamFrameSender webcam = root.AddComponent<WebcamFrameSender>();
            SoniaDebugUI debugUI = root.AddComponent<SoniaDebugUI>();
            SoniaBootstrap bootstrap = root.AddComponent<SoniaBootstrap>();

            // The camera is usually better disabled while VISION_SOURCE=opencv.
            webcam.enabled = false;

            ImagePanelController panel = CreateImagePanel(root.transform);
            GameObject hud = CreateHud(root.transform, out SoniaDebugUiRefs hudRefs);

            EnsureEventSystem(scene);
            SetUpVerticalCamera(scene);

            WireUp(
                client,
                audioPlayer,
                lipSync,
                avatarState,
                motionPlayer,
                choreographer,
                cameraFraming,
                panel,
                webcam,
                debugUI,
                bootstrap,
                hud,
                hudRefs);

            Selection.activeGameObject = root;
            Undo.SetCurrentGroupName(UndoName);
            Undo.CollapseUndoOperations(undoGroup);
            EditorSceneManager.MarkSceneDirty(scene);

            ApplyVerticalPlayerSettings();

            Debug.Log(
                "[Sonnia] Base scene created for a vertical 9:16 screen (1080x1920). Still to do: place the "
                + "avatar at the origin of the Sonia object, facing +Z, and assign its face "
                + "SkinnedMeshRenderer, its Animator and the head bone. "
                + "In the Game view, choose the \"9:16 Portrait\" aspect or add a fixed "
                + "1080x1920 resolution.",
                root);
        }

        /// <summary>
        /// Sets the build settings for the vertical monitor.
        /// It can be run on its own if someone changes them by accident.
        /// </summary>
        [MenuItem("Sonnia/Configure 9:16 Build")]
        public static void ConfigureVerticalBuild()
        {
            ApplyVerticalPlayerSettings();
            Debug.Log(
                "[Sonnia] Vertical build settings: " + ScreenWidth + "x" + ScreenHeight
                + ", borderless fullscreen, not resizable and running in the background.");
        }

        /// <summary>
        /// Adds the missing components to the Sonia object of an existing scene
        /// and rewires the SoniaBootstrap references. Used after adding new
        /// components to the project, to avoid rebuilding the whole scene.
        /// </summary>
        [MenuItem("Sonnia/Update Components")]
        public static void UpdateComponents()
        {
            Scene scene = SceneManager.GetActiveScene();
            SoniaBootstrap bootstrap = scene.IsValid() ? FindInScene<SoniaBootstrap>(scene) : null;
            if (bootstrap == null)
            {
                EditorUtility.DisplayDialog(
                    "Sonia",
                    "This scene has no object with SoniaBootstrap. Run Sonnia > Create Base Scene first.",
                    "OK");
                return;
            }

            GameObject root = bootstrap.gameObject;
            int undoGroup = Undo.GetCurrentGroup();

            MotionPlayer motionPlayer = EnsureComponent<MotionPlayer>(root);
            AvatarChoreographer choreographer = EnsureComponent<AvatarChoreographer>(root);
            CameraFramingController cameraFraming = EnsureComponent<CameraFramingController>(root);
            AvatarStateController avatarState = root.GetComponentInChildren<AvatarStateController>(true);
            LipSyncController lipSync = root.GetComponentInChildren<LipSyncController>(true);
            ImagePanelController panel = root.GetComponentInChildren<ImagePanelController>(true);

            // The Animator only exists if the avatar is already placed; if not,
            // AvatarBinder fills it in when the avatar loads.
            Animator animator = avatarState != null
                ? avatarState.GetComponentInChildren<Animator>(true)
                : root.GetComponentInChildren<Animator>(true);

            // Player and choreographer: already generated clip set and torso mask.
            SoniaMotionSetBuilder.Wire(
                root, animator, SoniaMotionSetBuilder.LoadOrBuildMotionSet(), SoniaMotionSetBuilder.LoadOrBuildMask());

            // Real-time phonemes (uLipSync), eye gaze, expressions and the tuning panel.
            EnsurePhonemeLipSync(root, avatarState);
            EnsureEyeGaze(root, avatarState, choreographer, animator);
            EnsureFacialExpressions(root, avatarState);
            EnsureComponent<SoniaTuningUI>(root);
            EnsureComponent<SoniaAnimationPreviewUI>(root);

            SerializedObject framingObject = new SerializedObject(cameraFraming);
            SetReference(framingObject, "choreographer", choreographer);
            SetReference(framingObject, "targetCamera", Camera.main);
            SetReference(framingObject, "imagePanel", panel);
            framingObject.ApplyModifiedPropertiesWithoutUndo();

            SerializedObject bootstrapObject = new SerializedObject(bootstrap);
            SetReference(bootstrapObject, "choreographer", choreographer);
            SetReference(bootstrapObject, "cameraFraming", cameraFraming);
            SetReference(bootstrapObject, "avatarState", avatarState);
            SetReference(bootstrapObject, "lipSync", lipSync);
            SetReference(bootstrapObject, "imagePanel", panel);
            bootstrapObject.ApplyModifiedPropertiesWithoutUndo();

            UpgradeHud(root);

            Undo.SetCurrentGroupName("Update Sonnia components");
            Undo.CollapseUndoOperations(undoGroup);
            EditorSceneManager.MarkSceneDirty(scene);

            Debug.Log(
                "[Sonnia] Components updated on \"" + root.name + "\". Animator: "
                + (animator != null ? animator.name : "unassigned, place the avatar first") + ".",
                root);
        }

        /// <summary>uLipSync phoneme profile used until one calibrated with Sonnia's voice exists.</summary>
        private const string DefaultPhonemeProfilePath =
            "Packages/com.hecomi.ulipsync/Assets/Profiles/uLipSync-Profile-Sample-Female.asset";

        /// <summary>Name of the child object that holds the phoneme analyzer.</summary>
        public const string PhonemeAnalyzerObjectName = "Phonemes";

        /// <summary>
        /// Puts the phoneme analyzer on a child object with no AudioSource and
        /// its bridge to the lip-sync on the root. The analyzer receives the audio
        /// from AudioStreamPlayer (the block that will sound within
        /// lipSyncLeadMs); if it were on the same object as the AudioSource, Unity
        /// would also feed it the already delayed output through its own
        /// OnAudioFilterRead and it would analyze a mix of the two.
        /// </summary>
        public static void EnsurePhonemeLipSync(GameObject root, AvatarStateController avatarState)
        {
            uLipSync.uLipSync stray = root.GetComponent<uLipSync.uLipSync>();
            uLipSync.Profile keepProfile = stray != null ? stray.profile : null;
            if (stray != null)
            {
                Undo.DestroyObjectImmediate(stray);
            }

            Transform holder = root.transform.Find(PhonemeAnalyzerObjectName);
            if (holder == null)
            {
                GameObject holderObject = new GameObject(PhonemeAnalyzerObjectName);
                Undo.RegisterCreatedObjectUndo(holderObject, "Create phoneme analyzer");
                holderObject.transform.SetParent(root.transform, false);
                holder = holderObject.transform;
            }

            uLipSync.uLipSync analyzer = EnsureComponent<uLipSync.uLipSync>(holder.gameObject);
            if (analyzer.profile == null)
            {
                analyzer.profile = keepProfile != null
                    ? keepProfile
                    : AssetDatabase.LoadAssetAtPath<uLipSync.Profile>(DefaultPhonemeProfilePath);
                EditorUtility.SetDirty(analyzer);
            }

            PhonemeLipSyncBridge bridge = EnsureComponent<PhonemeLipSyncBridge>(root);
            SerializedObject bridgeObject = new SerializedObject(bridge);
            SetReference(bridgeObject, "audioPlayer", root.GetComponent<AudioStreamPlayer>());
            SetReference(bridgeObject, "analyzer", analyzer);
            SetReference(bridgeObject, "lipSync", root.GetComponent<LipSyncController>());
            bridgeObject.ApplyModifiedPropertiesWithoutUndo();

            if (avatarState != null)
            {
                SerializedObject stateObject = new SerializedObject(avatarState);
                SetReference(stateObject, "lipSync", root.GetComponent<LipSyncController>());
                stateObject.ApplyModifiedPropertiesWithoutUndo();
            }
        }

        /// <summary>Puts the brow, eyelid and smile controller on the root object, writing to the face (FaceRig).</summary>
        public static void EnsureFacialExpressions(GameObject root, AvatarStateController avatarState)
        {
            FacialExpressionController expressions = EnsureComponent<FacialExpressionController>(root);
            LipSyncController lipSync = root.GetComponent<LipSyncController>();
            SerializedObject expressionObject = new SerializedObject(expressions);
            SetReference(expressionObject, "faceRig", root.GetComponent<FaceRig>());
            SetReference(expressionObject, "stateController", avatarState);
            SetReference(expressionObject, "lipSync", lipSync);
            expressionObject.ApplyModifiedPropertiesWithoutUndo();

            if (avatarState != null)
            {
                SerializedObject stateObject = new SerializedObject(avatarState);
                SetReference(stateObject, "choreographer", root.GetComponent<AvatarChoreographer>());
                stateObject.ApplyModifiedPropertiesWithoutUndo();
            }
        }

        /// <summary>Puts the eye gaze on the root object, pointing at the avatar's head.</summary>
        public static void EnsureEyeGaze(
            GameObject root, AvatarStateController avatarState, AvatarChoreographer choreographer, Animator animator)
        {
            EyeGazeController gaze = EnsureComponent<EyeGazeController>(root);
            SerializedObject gazeObject = new SerializedObject(gaze);
            SetReference(gazeObject, "stateController", avatarState);
            SetReference(gazeObject, "choreographer", choreographer);
            Transform head = animator != null && animator.isHuman
                ? animator.GetBoneTransform(HumanBodyBones.Head)
                : null;
            SetReference(gazeObject, "headBone", head);
            SetReference(gazeObject, "leftEye", FindEye(head, "LeftEye"));
            SetReference(gazeObject, "rightEye", FindEye(head, "RightEye"));
            gazeObject.ApplyModifiedPropertiesWithoutUndo();
        }

        private static Transform FindEye(Transform head, string name)
        {
            if (head == null)
            {
                return null;
            }

            Transform[] all = head.GetComponentsInChildren<Transform>(true);
            for (int i = 0; i < all.Length; i++)
            {
                if (all[i].name == name || all[i].name.EndsWith(":" + name))
                {
                    return all[i];
                }
            }

            return null;
        }

        /// <summary>
        /// Updates the HUD of an existing scene: Canvas in Screen Space - Camera
        /// and debug widgets inside a group that F1 hides.
        /// </summary>
        private static void UpgradeHud(GameObject root)
        {
            Transform hud = root.transform.Find(HudName);
            if (hud == null)
            {
                Debug.LogWarning("[Sonnia] There is no \"" + HudName + "\" object; the HUD cannot be updated.");
                return;
            }

            Undo.RecordObject(hud.gameObject, "Update Sonnia components");
            ConfigureHudCanvas(hud.GetComponent<Canvas>());

            Transform debugGroup = hud.Find(HudDebugName);
            if (debugGroup == null)
            {
                GameObject group = new GameObject(HudDebugName, typeof(RectTransform));
                group.transform.SetParent(hud, false);
                group.layer = hud.gameObject.layer;
                StretchFull(group.GetComponent<RectTransform>());
                Undo.RegisterCreatedObjectUndo(group, "Update Sonnia components");
                debugGroup = group.transform;

                // Everything that already hung from the Canvas goes into the group.
                // With worldPositionStays false the anchors are respected.
                Transform[] children = new Transform[hud.childCount];
                for (int i = 0; i < hud.childCount; i++)
                {
                    children[i] = hud.GetChild(i);
                }

                for (int i = 0; i < children.Length; i++)
                {
                    if (children[i] == debugGroup)
                    {
                        continue;
                    }

                    Undo.SetTransformParent(children[i], debugGroup, "Update Sonnia components");
                    children[i].SetParent(debugGroup, false);
                }
            }

            MoveHudLabel(debugGroup, "Connection", HudConnectionPosition);
            MoveHudLabel(debugGroup, "State", HudStatePosition);

            SoniaDebugUiRefs subtitleRefs = default(SoniaDebugUiRefs);
            EnsureSubtitles(debugGroup, ref subtitleRefs);

            // The image panel is drawn by the HUD camera, without post-processing
            // and above the avatar: the image shows as it is.
            Transform panel = root.transform.Find(PanelName);
            if (panel != null)
            {
                Undo.RecordObject(panel.gameObject, "Update Sonnia components");
                SetLayerRecursively(panel.gameObject, LayerMask.NameToLayer("UI"));
            }

            SoniaDebugUI debugUI = root.GetComponentInChildren<SoniaDebugUI>(true);
            if (debugUI != null)
            {
                SerializedObject serialized = new SerializedObject(debugUI);
                SetReference(serialized, "hudRoot", debugGroup.gameObject);
                SetNestedReference(serialized, "userLabel", "tmp", subtitleRefs.User);
                SetNestedReference(serialized, "userLabel", "container", subtitleRefs.UserBubble);
                SetNestedReference(serialized, "assistantLabel", "tmp", subtitleRefs.Assistant);
                SetNestedReference(serialized, "assistantLabel", "container", subtitleRefs.AssistantBubble);
                serialized.ApplyModifiedPropertiesWithoutUndo();
            }

            EditorUtility.SetDirty(hud.gameObject);
        }

        /// <summary>Repositions a HUD label that already exists in the scene.</summary>
        private static void MoveHudLabel(Transform debugGroup, string name, Vector2 position)
        {
            Transform label = debugGroup != null ? debugGroup.Find(name) : null;
            RectTransform rect = label != null ? label.GetComponent<RectTransform>() : null;
            if (rect == null)
            {
                return;
            }

            Undo.RecordObject(rect, "Update Sonnia components");
            rect.anchoredPosition = position;
            EditorUtility.SetDirty(rect);
        }

        /// <summary>Returns the object's component, adding it if missing.</summary>
        private static T EnsureComponent<T>(GameObject target) where T : Component
        {
            T component = target.GetComponent<T>();
            if (component == null)
            {
                component = Undo.AddComponent<T>(target);
            }

            return component;
        }

        private static void ApplyVerticalPlayerSettings()
        {
            PlayerSettings.defaultScreenWidth = ScreenWidth;
            PlayerSettings.defaultScreenHeight = ScreenHeight;
            PlayerSettings.defaultIsNativeResolution = false;
            PlayerSettings.fullScreenMode = FullScreenMode.FullScreenWindow;
            PlayerSettings.runInBackground = true;
            PlayerSettings.resizableWindow = false;
            PlayerSettings.visibleInBackground = true;
            AssetDatabase.SaveAssets();
        }

        /// <summary>
        /// Places the camera for the vertical framing: full-body avatar at the
        /// bottom and room above for the image panel.
        /// </summary>
        private static void SetUpVerticalCamera(Scene scene)
        {
            Camera camera = Camera.main;
            if (camera == null)
            {
                camera = FindInScene<Camera>(scene);
            }

            if (camera == null)
            {
                Debug.LogWarning("[Sonnia] There is no camera in the scene; place it by hand.");
                return;
            }

            Undo.RecordObject(camera.transform, UndoName);
            Undo.RecordObject(camera, UndoName);
            camera.transform.position = CameraPosition;
            camera.transform.rotation = Quaternion.identity;
            camera.fieldOfView = CameraFieldOfView;
            camera.nearClipPlane = 0.1f;
        }

        // ------------------------------------------------------------------
        // Image panel
        // ------------------------------------------------------------------

        private static ImagePanelController CreateImagePanel(Transform parent)
        {
            GameObject panelRoot = new GameObject(PanelName);
            panelRoot.transform.SetParent(parent, false);

            panelRoot.transform.localPosition = PanelPosition;

            GameObject quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
            quad.name = "Quad";
            quad.transform.SetParent(panelRoot.transform, false);
            quad.transform.localScale = new Vector3(PanelSize.x, PanelSize.y, 1f);

            Collider quadCollider = quad.GetComponent<Collider>();
            if (quadCollider != null)
            {
                Object.DestroyImmediate(quadCollider);
            }

            MeshRenderer meshRenderer = quad.GetComponent<MeshRenderer>();
            Material material = LoadOrCreatePanelMaterial();
            if (material != null && meshRenderer != null)
            {
                meshRenderer.sharedMaterial = material;
            }

            // The component turns the Transform into a RectTransform, so it is
            // added before positioning the object.
            // The caption goes ABOVE the image: below it would collide with the
            // avatar's head, which sits right under the panel.
            GameObject captionObject = new GameObject("Caption");
            TextMeshPro caption = captionObject.AddComponent<TextMeshPro>();
            captionObject.transform.SetParent(panelRoot.transform, false);
            captionObject.transform.localPosition = new Vector3(0f, PanelSize.y * 0.78f, 0f);
            caption.text = string.Empty;
            caption.fontSize = 0.7f;
            caption.alignment = TextAlignmentOptions.Center;
            caption.color = Color.white;

            RectTransform captionRect = captionObject.GetComponent<RectTransform>();
            if (captionRect != null)
            {
                captionRect.sizeDelta = new Vector2(PanelSize.x * 1.4f, 0.16f);
            }

            captionObject.SetActive(false);

            SetLayerRecursively(panelRoot, LayerMask.NameToLayer("UI"));

            ImagePanelController controller = panelRoot.AddComponent<ImagePanelController>();
            SerializedObject serialized = new SerializedObject(controller);
            SetReference(serialized, "panelRoot", quad.transform);
            SetReference(serialized, "targetRenderer", meshRenderer);
            SetReference(serialized, "captionLabel", caption);
            SetReference(serialized, "captionRoot", captionObject);

            // The component recomputes the size when showing each image, so
            // these two fields are the ones that really count.
            SerializedProperty height = serialized.FindProperty("panelHeight");
            if (height != null)
            {
                height.floatValue = PanelSize.y;
            }

            SerializedProperty maxWidth = serialized.FindProperty("panelMaxWidth");
            if (maxWidth != null)
            {
                maxWidth.floatValue = PanelSize.x;
            }

            serialized.ApplyModifiedPropertiesWithoutUndo();

            return controller;
        }

        private static Material LoadOrCreatePanelMaterial()
        {
            Material existing = AssetDatabase.LoadAssetAtPath<Material>(MaterialPath);
            if (existing != null)
            {
                return existing;
            }

            Shader shader = Shader.Find("Universal Render Pipeline/Unlit");
            if (shader == null)
            {
                shader = Shader.Find("Unlit/Texture");
            }

            if (shader == null)
            {
                Debug.LogWarning(
                    "[Sonnia] No unlit shader found; the panel will use the Quad's default material.");
                return null;
            }

            if (!AssetDatabase.IsValidFolder("Assets/Sonia"))
            {
                AssetDatabase.CreateFolder("Assets", "Sonia");
            }

            if (!AssetDatabase.IsValidFolder(MaterialFolder))
            {
                AssetDatabase.CreateFolder("Assets/Sonia", "Materials");
            }

            if (!AssetDatabase.IsValidFolder(MaterialFolder))
            {
                Debug.LogWarning(
                    "[Sonnia] Could not create " + MaterialFolder
                    + "; the panel will use the Quad's default material.");
                return null;
            }

            Material material = new Material(shader);
            material.name = "SoniaImagePanel";
            AssetDatabase.CreateAsset(material, MaterialPath);
            AssetDatabase.SaveAssets();
            return material;
        }

        // ------------------------------------------------------------------
        // HUD
        // ------------------------------------------------------------------

        private struct SoniaDebugUiRefs
        {
            public TextMeshProUGUI Connection;
            public TextMeshProUGUI State;
            public TextMeshProUGUI User;
            public TextMeshProUGUI Assistant;
            public GameObject UserBubble;
            public GameObject AssistantBubble;
            public TMP_InputField Input;
            public Button Interrupt;
            public GameObject DebugGroup;
        }

        /// <summary>Name of the overlay camera that draws the HUD.</summary>
        private const string HudCameraName = "HudCamera";

        /// <summary>
        /// Puts the HUD Canvas in Screen Space - Camera on an overlay camera
        /// (URP camera stacking) with no post-processing. With the main camera,
        /// the HUD went through ACES tonemapping, bloom, vignette and depth of
        /// field: colors came out dark and text washed out. In Overlay it would
        /// go through nothing, but it would not show in the 1080x1920 captures
        /// either; the stacked camera is rendered along with the main one.
        /// </summary>
        private static void ConfigureHudCanvas(Canvas canvas)
        {
            if (canvas == null)
            {
                return;
            }

            Camera main = Camera.main;
            if (main == null)
            {
                canvas.renderMode = RenderMode.ScreenSpaceOverlay;
                canvas.sortingOrder = 100;
                Debug.LogWarning(
                    "[Sonnia] There is no main camera; the HUD stays in Overlay and will not show "
                    + "in captures.");
                return;
            }

            Camera hudCamera = EnsureHudCamera(main);
            canvas.renderMode = RenderMode.ScreenSpaceCamera;
            canvas.worldCamera = hudCamera != null ? hudCamera : main;
            canvas.planeDistance = HudPlaneDistance;
            canvas.sortingOrder = 100;
        }

        /// <summary>
        /// Overlay camera, child of the main one: UI layer only and no
        /// post-processing. The main camera stops drawing the UI layer.
        /// </summary>
        private static Camera EnsureHudCamera(Camera main)
        {
            int uiLayer = LayerMask.NameToLayer("UI");
            if (uiLayer < 0)
            {
                Debug.LogWarning("[Sonnia] The UI layer does not exist; the HUD is drawn with the main camera.");
                return null;
            }

            Transform existing = main.transform.Find(HudCameraName);
            GameObject cameraObject;
            if (existing != null)
            {
                cameraObject = existing.gameObject;
            }
            else
            {
                cameraObject = new GameObject(HudCameraName, typeof(Camera));
                cameraObject.transform.SetParent(main.transform, false);
                Undo.RegisterCreatedObjectUndo(cameraObject, "Create HUD camera");
            }

            cameraObject.transform.localPosition = Vector3.zero;
            cameraObject.transform.localRotation = Quaternion.identity;
            cameraObject.transform.localScale = Vector3.one;

            Camera hudCamera = cameraObject.GetComponent<Camera>();
            hudCamera.cullingMask = 1 << uiLayer;
            hudCamera.orthographic = main.orthographic;
            hudCamera.fieldOfView = main.fieldOfView;
            hudCamera.nearClipPlane = 0.05f;
            hudCamera.farClipPlane = 5f;
            hudCamera.depth = main.depth + 1;
            AudioListener listener = cameraObject.GetComponent<AudioListener>();
            if (listener != null)
            {
                Object.DestroyImmediate(listener);
            }

            UniversalAdditionalCameraData hudData = hudCamera.GetUniversalAdditionalCameraData();
            hudData.renderType = CameraRenderType.Overlay;
            hudData.renderPostProcessing = false;
            hudData.renderShadows = false;
            hudData.requiresColorOption = CameraOverrideOption.Off;
            hudData.requiresDepthOption = CameraOverrideOption.Off;

            UniversalAdditionalCameraData mainData = main.GetUniversalAdditionalCameraData();
            if (mainData.renderType != CameraRenderType.Base)
            {
                mainData.renderType = CameraRenderType.Base;
            }

            if (!mainData.cameraStack.Contains(hudCamera))
            {
                mainData.cameraStack.Add(hudCamera);
            }

            // Overlay canvases (tuning and animation panels) do not use a
            // camera; the rest of the UI is this HUD, which the main camera no longer draws.
            main.cullingMask &= ~(1 << uiLayer);
            EditorUtility.SetDirty(main);
            EditorUtility.SetDirty(hudCamera);
            return hudCamera;
        }

        /// <summary>Name of the subtitles container inside the debug group.</summary>
        private const string SubtitlesName = "Subtitles";

        /// <summary>
        /// Subtitles as two bubbles stacked above the text row: the user's
        /// (small, gray, "YOU" tag) and Sonnia's (large, white, "SONNIA" tag in
        /// blue). Each bubble grows with its text and hides when empty, so they
        /// never overlap.
        /// </summary>
        private static void EnsureSubtitles(Transform debugGroup, ref SoniaDebugUiRefs refs)
        {
            // Loose labels from earlier versions are no longer needed.
            foreach (string stale in new[] { "UserSubtitle", "AssistantSubtitle" })
            {
                Transform old = debugGroup.Find(stale);
                if (old != null)
                {
                    Undo.DestroyObjectImmediate(old.gameObject);
                }
            }

            Transform existing = debugGroup.Find(SubtitlesName);
            if (existing != null)
            {
                Undo.DestroyObjectImmediate(existing.gameObject);
            }

            GameObject container = new GameObject(SubtitlesName, typeof(RectTransform));
            container.transform.SetParent(debugGroup, false);
            container.layer = debugGroup.gameObject.layer;
            Undo.RegisterCreatedObjectUndo(container, "Create subtitles");
            RectTransform containerRect = container.GetComponent<RectTransform>();
            containerRect.anchorMin = new Vector2(0.5f, 0f);
            containerRect.anchorMax = new Vector2(0.5f, 0f);
            containerRect.pivot = new Vector2(0.5f, 0f);
            containerRect.anchoredPosition = new Vector2(0f, 150f);
            containerRect.sizeDelta = new Vector2(980f, 0f);
            VerticalLayoutGroup stack = container.AddComponent<VerticalLayoutGroup>();
            stack.spacing = 14f;
            stack.childAlignment = TextAnchor.LowerCenter;
            stack.childControlWidth = true;
            stack.childControlHeight = true;
            stack.childForceExpandWidth = true;
            stack.childForceExpandHeight = false;
            container.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            refs.UserBubble = CreateSubtitleBubble(
                container.transform,
                "UserBubble",
                "YOU",
                new Color(0.62f, 0.70f, 0.82f, 1f),
                new Color(0.04f, 0.07f, 0.14f, 0.55f),
                26f,
                new Color(0.86f, 0.89f, 0.95f, 1f),
                out refs.User);
            refs.AssistantBubble = CreateSubtitleBubble(
                container.transform,
                "AssistantBubble",
                "SONNIA",
                new Color(0.44f, 0.66f, 1f, 1f),
                new Color(0.02f, 0.05f, 0.12f, 0.72f),
                36f,
                Color.white,
                out refs.Assistant);

            // They start empty and hidden; SoniaDebugUI shows them with the text.
            refs.UserBubble.SetActive(false);
            refs.AssistantBubble.SetActive(false);
        }

        private static GameObject CreateSubtitleBubble(
            Transform parent,
            string name,
            string tag,
            Color tagColor,
            Color background,
            float fontSize,
            Color textColor,
            out TextMeshProUGUI text)
        {
            GameObject bubble = new GameObject(name, typeof(RectTransform));
            bubble.transform.SetParent(parent, false);
            bubble.layer = parent.gameObject.layer;
            Image image = bubble.AddComponent<Image>();
            image.color = background;
            image.raycastTarget = false;
            VerticalLayoutGroup layout = bubble.AddComponent<VerticalLayoutGroup>();
            layout.padding = new RectOffset(28, 28, 12, 14);
            layout.spacing = 2f;
            layout.childAlignment = TextAnchor.UpperCenter;
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = false;
            bubble.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            GameObject tagObject = new GameObject("Tag", typeof(RectTransform));
            tagObject.transform.SetParent(bubble.transform, false);
            tagObject.layer = bubble.layer;
            TextMeshProUGUI tagText = tagObject.AddComponent<TextMeshProUGUI>();
            tagText.text = tag;
            tagText.fontSize = 19f;
            tagText.characterSpacing = 6f;
            tagText.fontStyle = FontStyles.Bold;
            tagText.color = tagColor;
            tagText.alignment = TextAlignmentOptions.Center;
            tagText.raycastTarget = false;

            GameObject textObject = new GameObject("Text", typeof(RectTransform));
            textObject.transform.SetParent(bubble.transform, false);
            textObject.layer = bubble.layer;
            text = textObject.AddComponent<TextMeshProUGUI>();
            text.text = string.Empty;
            text.fontSize = fontSize;
            text.color = textColor;
            text.alignment = TextAlignmentOptions.Center;
            text.textWrappingMode = TextWrappingModes.Normal;
            text.raycastTarget = false;
            return bubble;
        }

        /// <summary>Sets the layer on an object and all its children (if the layer exists).</summary>
        private static void SetLayerRecursively(GameObject root, int layer)
        {
            if (root == null || layer < 0)
            {
                return;
            }

            root.layer = layer;
            for (int i = 0; i < root.transform.childCount; i++)
            {
                SetLayerRecursively(root.transform.GetChild(i).gameObject, layer);
            }
        }

        /// <summary>Makes a RectTransform fill its whole parent.</summary>
        private static void StretchFull(RectTransform rect)
        {
            if (rect == null)
            {
                return;
            }

            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
        }

        private static GameObject CreateHud(Transform parent, out SoniaDebugUiRefs refs)
        {
            refs = new SoniaDebugUiRefs();

            GameObject canvasObject = new GameObject(HudName);
            canvasObject.transform.SetParent(parent, false);
            canvasObject.layer = LayerMask.NameToLayer("UI");

            Canvas canvas = canvasObject.AddComponent<Canvas>();
            ConfigureHudCanvas(canvas);

            CanvasScaler scaler = canvasObject.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(ScreenWidth, ScreenHeight);
            scaler.matchWidthOrHeight = 0.5f;

            canvasObject.AddComponent<GraphicRaycaster>();

            GameObject debugGroup = new GameObject(HudDebugName, typeof(RectTransform));
            debugGroup.transform.SetParent(canvasObject.transform, false);
            debugGroup.layer = canvasObject.layer;
            StretchFull(debugGroup.GetComponent<RectTransform>());
            refs.DebugGroup = debugGroup;

            // Connection and assistant state: at the very top.
            refs.Connection = CreateLabel(
                debugGroup.transform,
                "Connection",
                new Vector2(0f, 1f),
                new Vector2(0f, 1f),
                new Vector2(0f, 1f),
                HudConnectionPosition,
                new Vector2(700f, 44f),
                28f,
                TextAlignmentOptions.Left,
                "Not connected");

            refs.State = CreateLabel(
                debugGroup.transform,
                "State",
                new Vector2(0f, 1f),
                new Vector2(0f, 1f),
                new Vector2(0f, 1f),
                HudStatePosition,
                new Vector2(700f, 44f),
                28f,
                TextAlignmentOptions.Left,
                "idle");

            // Subtitles at the bottom, above the text input row.
            EnsureSubtitles(debugGroup.transform, ref refs);

            TMP_DefaultControls.Resources resources = BuildResources();

            GameObject inputObject = TMP_DefaultControls.CreateInputField(resources);
            inputObject.name = "TextInput";
            inputObject.transform.SetParent(debugGroup.transform, false);
            RectTransform inputRect = inputObject.GetComponent<RectTransform>();
            // At 1080 wide, the field and the button sit together in a single row
            // at the bottom, with 40 px of margin on each side.
            inputRect.anchorMin = new Vector2(0.5f, 0f);
            inputRect.anchorMax = new Vector2(0.5f, 0f);
            inputRect.pivot = new Vector2(0.5f, 0f);
            inputRect.anchoredPosition = new Vector2(-145f, 50f);
            inputRect.sizeDelta = new Vector2(730f, 60f);
            refs.Input = inputObject.GetComponent<TMP_InputField>();
            if (refs.Input != null)
            {
                refs.Input.lineType = TMP_InputField.LineType.SingleLine;
                if (refs.Input.textComponent != null)
                {
                    refs.Input.textComponent.fontSize = 26f;
                }

                if (refs.Input.placeholder is TMP_Text placeholder)
                {
                    placeholder.text = "Type and press Enter...";
                    placeholder.fontSize = 26f;
                }

                refs.Input.pointSize = 26f;
            }

            GameObject buttonObject = TMP_DefaultControls.CreateButton(resources);
            buttonObject.name = "InterruptButton";
            buttonObject.transform.SetParent(debugGroup.transform, false);
            RectTransform buttonRect = buttonObject.GetComponent<RectTransform>();
            buttonRect.anchorMin = new Vector2(0.5f, 0f);
            buttonRect.anchorMax = new Vector2(0.5f, 0f);
            buttonRect.pivot = new Vector2(0.5f, 0f);
            buttonRect.anchoredPosition = new Vector2(370f, 50f);
            buttonRect.sizeDelta = new Vector2(260f, 60f);
            refs.Interrupt = buttonObject.GetComponent<Button>();
            TextMeshProUGUI buttonLabel = buttonObject.GetComponentInChildren<TextMeshProUGUI>();
            if (buttonLabel != null)
            {
                buttonLabel.text = "Interrupt";
                buttonLabel.fontSize = 26f;
            }

            return canvasObject;
        }

        private static TMP_DefaultControls.Resources BuildResources()
        {
            TMP_DefaultControls.Resources resources = new TMP_DefaultControls.Resources();
            resources.standard = AssetDatabase.GetBuiltinExtraResource<Sprite>("UI/Skin/UISprite.psd");
            resources.background = AssetDatabase.GetBuiltinExtraResource<Sprite>("UI/Skin/Background.psd");
            resources.inputField = AssetDatabase.GetBuiltinExtraResource<Sprite>("UI/Skin/InputFieldBackground.psd");
            resources.knob = AssetDatabase.GetBuiltinExtraResource<Sprite>("UI/Skin/Knob.psd");
            resources.checkmark = AssetDatabase.GetBuiltinExtraResource<Sprite>("UI/Skin/Checkmark.psd");
            resources.dropdown = AssetDatabase.GetBuiltinExtraResource<Sprite>("UI/Skin/DropdownArrow.psd");
            resources.mask = AssetDatabase.GetBuiltinExtraResource<Sprite>("UI/Skin/UIMask.psd");
            return resources;
        }

        private static TextMeshProUGUI CreateLabel(
            Transform parent,
            string name,
            Vector2 anchorMin,
            Vector2 anchorMax,
            Vector2 pivot,
            Vector2 anchoredPosition,
            Vector2 size,
            float fontSize,
            TextAlignmentOptions alignment,
            string text)
        {
            GameObject labelObject = new GameObject(name, typeof(RectTransform));
            labelObject.transform.SetParent(parent, false);
            labelObject.layer = parent.gameObject.layer;

            RectTransform rect = labelObject.GetComponent<RectTransform>();
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.pivot = pivot;
            rect.anchoredPosition = anchoredPosition;
            rect.sizeDelta = size;

            TextMeshProUGUI label = labelObject.AddComponent<TextMeshProUGUI>();
            label.text = text;
            label.fontSize = fontSize;
            label.alignment = alignment;
            label.color = Color.white;
            label.raycastTarget = false;
            return label;
        }

        // ------------------------------------------------------------------
        // EventSystem
        // ------------------------------------------------------------------

        private static void EnsureEventSystem(Scene scene)
        {
            EventSystem existing = FindInScene<EventSystem>(scene);
            if (existing != null)
            {
                // With activeInputHandler = 1 the new Input System module is required.
                if (existing.GetComponent<InputSystemUIInputModule>() == null)
                {
                    BaseInputModule legacy = existing.GetComponent<BaseInputModule>();
                    if (legacy != null)
                    {
                        Object.DestroyImmediate(legacy);
                    }

                    existing.gameObject.AddComponent<InputSystemUIInputModule>();
                }

                return;
            }

            GameObject eventSystem = new GameObject("EventSystem");
            eventSystem.AddComponent<EventSystem>();
            eventSystem.AddComponent<InputSystemUIInputModule>();
            Undo.RegisterCreatedObjectUndo(eventSystem, UndoName);
        }

        // ------------------------------------------------------------------
        // Wiring
        // ------------------------------------------------------------------

        private static void WireUp(
            SoniaClient client,
            AudioStreamPlayer audioPlayer,
            LipSyncController lipSync,
            AvatarStateController avatarState,
            MotionPlayer motionPlayer,
            AvatarChoreographer choreographer,
            CameraFramingController cameraFraming,
            ImagePanelController panel,
            WebcamFrameSender webcam,
            SoniaDebugUI debugUI,
            SoniaBootstrap bootstrap,
            GameObject hud,
            SoniaDebugUiRefs refs)
        {
            SerializedObject lipSyncObject = new SerializedObject(lipSync);
            SetReference(lipSyncObject, "audioPlayer", audioPlayer);
            lipSyncObject.ApplyModifiedPropertiesWithoutUndo();

            SerializedObject avatarObject = new SerializedObject(avatarState);
            SetReference(avatarObject, "avatarRoot", avatarState.transform);
            Camera main = Camera.main;
            if (main != null)
            {
                SetReference(avatarObject, "lookTarget", main.transform);
            }

            SetReference(avatarObject, "imageLookTarget", panel.PanelTransform);
            avatarObject.ApplyModifiedPropertiesWithoutUndo();

            SerializedObject webcamObject = new SerializedObject(webcam);
            SetReference(webcamObject, "client", client);
            webcamObject.ApplyModifiedPropertiesWithoutUndo();

            SerializedObject debugObject = new SerializedObject(debugUI);
            SetReference(debugObject, "client", client);
            SetReference(debugObject, "hudRoot", refs.DebugGroup != null ? refs.DebugGroup : hud);
            SetNestedReference(debugObject, "connectionLabel", "tmp", refs.Connection);
            SetNestedReference(debugObject, "stateLabel", "tmp", refs.State);
            SetNestedReference(debugObject, "userLabel", "tmp", refs.User);
            SetNestedReference(debugObject, "userLabel", "container", refs.UserBubble);
            SetNestedReference(debugObject, "assistantLabel", "tmp", refs.Assistant);
            SetNestedReference(debugObject, "assistantLabel", "container", refs.AssistantBubble);
            SetReference(debugObject, "inputField", refs.Input);
            SetReference(debugObject, "interruptButton", refs.Interrupt);
            debugObject.ApplyModifiedPropertiesWithoutUndo();

            SerializedObject choreoObject = new SerializedObject(choreographer);
            SetReference(choreoObject, "motionPlayer", motionPlayer);
            choreoObject.ApplyModifiedPropertiesWithoutUndo();

            SerializedObject framingObject = new SerializedObject(cameraFraming);
            SetReference(framingObject, "imagePanel", panel);
            SetReference(framingObject, "choreographer", choreographer);
            Camera mainCamera = Camera.main;
            if (mainCamera != null)
            {
                SetReference(framingObject, "targetCamera", mainCamera);
            }

            framingObject.ApplyModifiedPropertiesWithoutUndo();

            SerializedObject bootstrapObject = new SerializedObject(bootstrap);
            SetReference(bootstrapObject, "client", client);
            SetReference(bootstrapObject, "audioPlayer", audioPlayer);
            SetReference(bootstrapObject, "lipSync", lipSync);
            SetReference(bootstrapObject, "avatarState", avatarState);
            SetReference(bootstrapObject, "choreographer", choreographer);
            SetReference(bootstrapObject, "cameraFraming", cameraFraming);
            SetReference(bootstrapObject, "imagePanel", panel);
            SetReference(bootstrapObject, "webcam", webcam);
            SetReference(bootstrapObject, "debugUI", debugUI);
            bootstrapObject.ApplyModifiedPropertiesWithoutUndo();
        }

        // ------------------------------------------------------------------
        // Utilities
        // ------------------------------------------------------------------

        /// <summary>
        /// Assigns a reference by field name. Warns instead of blowing up if the
        /// field was renamed and this script was left behind.
        /// </summary>
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

        private static void SetNestedReference(
            SerializedObject target,
            string path,
            string relativePath,
            Object value)
        {
            SerializedProperty property = target.FindProperty(path);
            SerializedProperty nested = property != null ? property.FindPropertyRelative(relativePath) : null;
            if (nested == null)
            {
                Debug.LogWarning(
                    "[Sonnia] Field \"" + path + "." + relativePath + "\" does not exist on "
                    + target.targetObject.GetType().Name + "; assign it by hand in the inspector.");
                return;
            }

            nested.objectReferenceValue = value;
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
