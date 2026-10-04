// Menú del editor que monta la escena base de Sonia.
//
// Crea el objeto "Sonia" con todos los componentes, el panel de imágenes, el HUD
// de depuración y, si falta, un EventSystem con el módulo del Input System nuevo.
// Los campos del avatar (SkinnedMeshRenderer, Animator, hueso de cabeza) se dejan
// vacíos: los rellena la persona que importe el modelo.
//
// Todo está pensado para la pantalla del stand: un monitor en VERTICAL de
// 1080x1920 (9:16). Por eso el panel de imágenes va encima del avatar y no a un
// lado, y la cámara encuadra al personaje de cuerpo entero dejando hueco arriba.
// Se da por hecho que el avatar se coloca en el origen del objeto "Sonia",
// de pie y mirando hacia +Z, que es de donde mira la cámara.

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
    /// <summary>Herramientas de editor para montar la escena de la demo.</summary>
    public static class SoniaSceneSetup
    {
        private const string RootName = "Sonia";
        private const string PanelName = "ImagePanel";
        private const string HudName = "SoniaHUD";

        /// <summary>Grupo que F1 esconde. El logo de marca queda FUERA, siempre visible.</summary>
        private const string HudDebugName = "Debug";

        private const string BrandLogoName = "BrandLogo";

        /// <summary>
        /// Distancia del Canvas a la cámara. Con Screen Space - Camera el HUD sale
        /// en los renders a RenderTexture; en Overlay no sale.
        /// </summary>
        private const float HudPlaneDistance = 0.3f;

        /// <summary>Ancho del logo del HUD en píxeles de la resolución de referencia.</summary>
        private const float BrandLogoWidth = 300f;

        /// <summary>Proporción del PNG del logo: 1200 x 500.</summary>
        private const float BrandLogoAspect = 1200f / 500f;

        /// <summary>Margen del logo a las esquinas, en píxeles.</summary>
        private const float BrandLogoMargin = 48f;

        /// <summary>
        /// Dónde empiezan las etiquetas de depuración: por debajo del logo, que
        /// ocupa la esquina de arriba a la izquierda y no se esconde con F1.
        /// </summary>
        private static readonly Vector2 HudConnectionPosition =
            new Vector2(BrandLogoMargin, -(BrandLogoMargin + (BrandLogoWidth / BrandLogoAspect) + 24f));

        private static readonly Vector2 HudStatePosition =
            new Vector2(HudConnectionPosition.x, HudConnectionPosition.y - 52f);
        private const string MaterialFolder = "Assets/Sonia/Materials";
        private const string MaterialPath = MaterialFolder + "/SoniaImagePanel.mat";
        private const string UndoName = "Crear escena base de Sonia";

        /// <summary>Resolución de la pantalla del stand: monitor vertical 9:16.</summary>
        private const int ScreenWidth = 1080;

        private const int ScreenHeight = 1920;

        /// <summary>Posición de la cámara para encuadrar al avatar de cuerpo entero en vertical.</summary>
        private static readonly Vector3 CameraPosition = new Vector3(0f, 1.3f, -2.7f);

        /// <summary>Campo de visión vertical de la cámara, en grados.</summary>
        private const float CameraFieldOfView = 52f;

        /// <summary>
        /// Centro del panel de imágenes: detrás del avatar, asomando por encima del
        /// hombro. Encima de la cabeza no cabe, porque el encuadre del stand es un
        /// plano medio. La posición definitiva la recalcula Sonia > Colocar avatar
        /// con los huesos reales del modelo.
        /// </summary>
        private static readonly Vector3 PanelPosition = new Vector3(0.35f, 1.35f, 0.6f);

        /// <summary>Tamaño del panel en metros: ancho máximo y alto.</summary>
        private static readonly Vector2 PanelSize = new Vector2(0.55f, 0.31f);

        [MenuItem("Sonia/Crear escena base")]
        public static void CreateBaseScene()
        {
            Scene scene = SceneManager.GetActiveScene();
            if (!scene.IsValid())
            {
                EditorUtility.DisplayDialog("Sonia", "No hay ninguna escena abierta.", "Vale");
                return;
            }

            if (FindInScene<SoniaBootstrap>(scene) != null)
            {
                EditorUtility.DisplayDialog(
                    "Sonia",
                    "Esta escena ya tiene un objeto Sonia con SoniaBootstrap. Bórralo antes de volver a crearlo.",
                    "Vale");
                return;
            }

            // TMP_Settings.defaultFontAsset lanza NullReferenceException si los
            // "TMP Essential Resources" no están importados. Se importan aquí
            // mismo (sin diálogo) para que el HUD tenga fuente y shader.
            if (TMP_Settings.instance == null)
            {
                Debug.Log("[Sonia] Importando los recursos esenciales de TextMeshPro...");
                TMP_PackageResourceImporter.ImportResources(true, false, false);
                AssetDatabase.Refresh();
            }

            if (TMP_Settings.instance == null || TMP_Settings.defaultFontAsset == null)
            {
                Debug.LogWarning(
                    "[Sonia] No hay recursos de TextMeshPro en el proyecto. Importa "
                    + "Window > TextMeshPro > Import TMP Essential Resources para que el HUD se vea.");
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

            // La cámara suele quedar mejor desactivada mientras VISION_SOURCE=opencv.
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
                "[Sonia] Escena base creada para pantalla vertical 9:16 (1080x1920). Falta colocar el "
                + "avatar en el origen del objeto Sonia, mirando hacia +Z, y asignar su "
                + "SkinnedMeshRenderer de la cara, su Animator y el hueso de la cabeza. "
                + "En la Game view, elige el aspecto \"9:16 Portrait\" o añade una resolución "
                + "fija de 1080x1920. Ver docs/unity.md.",
                root);
        }

        /// <summary>
        /// Deja los ajustes de build listos para el monitor vertical del stand.
        /// Se puede lanzar por separado si alguien los toca sin querer.
        /// </summary>
        [MenuItem("Sonia/Configurar build 9:16")]
        public static void ConfigureVerticalBuild()
        {
            ApplyVerticalPlayerSettings();
            Debug.Log(
                "[Sonia] Ajustes de build en vertical: " + ScreenWidth + "x" + ScreenHeight
                + ", pantalla completa sin bordes, sin redimensionar y corriendo en segundo plano.");
        }

        /// <summary>
        /// Añade al objeto Sonia de una escena que ya existe los componentes que le
        /// falten y vuelve a cablear las referencias de SoniaBootstrap. Se usa
        /// después de añadir componentes nuevos al proyecto, para no tener que
        /// rehacer la escena entera.
        /// </summary>
        [MenuItem("Sonia/Actualizar componentes")]
        public static void UpdateComponents()
        {
            Scene scene = SceneManager.GetActiveScene();
            SoniaBootstrap bootstrap = scene.IsValid() ? FindInScene<SoniaBootstrap>(scene) : null;
            if (bootstrap == null)
            {
                EditorUtility.DisplayDialog(
                    "Sonia",
                    "Esta escena no tiene ningún objeto con SoniaBootstrap. Ejecuta antes Sonia > Crear escena base.",
                    "Vale");
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

            // El Animator solo existe si el avatar ya está colocado; si no, lo
            // rellena Sonia > Colocar avatar Seed-san.
            Animator animator = avatarState != null
                ? avatarState.GetComponentInChildren<Animator>(true)
                : root.GetComponentInChildren<Animator>(true);

            // Reproductor y coreógrafo: set de clips y máscara de torso ya generados.
            SoniaMotionSetBuilder.Wire(
                root, animator, SoniaMotionSetBuilder.LoadOrBuildMotionSet(), SoniaMotionSetBuilder.LoadOrBuildMask());

            // Fonemas en tiempo real (uLipSync), mirada de los ojos, expresiones y panel de ajuste.
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

            Undo.SetCurrentGroupName("Actualizar componentes de Sonia");
            Undo.CollapseUndoOperations(undoGroup);
            EditorSceneManager.MarkSceneDirty(scene);

            Debug.Log(
                "[Sonia] Componentes actualizados en \"" + root.name + "\". Animator: "
                + (animator != null ? animator.name : "sin asignar, coloca antes el avatar") + ".",
                root);
        }

        /// <summary>Perfil de fonemas de uLipSync que se usa mientras no haya uno calibrado con la voz de Sonia.</summary>
        private const string DefaultPhonemeProfilePath =
            "Packages/com.hecomi.ulipsync/Assets/Profiles/uLipSync-Profile-Sample-Female.asset";

        /// <summary>Nombre del objeto hijo que aloja el analizador de fonemas.</summary>
        public const string PhonemeAnalyzerObjectName = "Fonemas";

        /// <summary>
        /// Deja el analizador de fonemas en un objeto hijo sin AudioSource y su
        /// puente al lip-sync en el raíz. El analizador recibe el audio desde
        /// AudioStreamPlayer (el bloque que sonará dentro de lipSyncLeadMs); si
        /// estuviera en el mismo objeto que el AudioSource, Unity le pasaría
        /// además por su propio OnAudioFilterRead la salida ya retardada y
        /// analizaría una mezcla de las dos.
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
                Undo.RegisterCreatedObjectUndo(holderObject, "Crear analizador de fonemas");
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

        /// <summary>Deja en el objeto raíz el controlador de cejas, párpados y sonrisa, escribiendo en la cara (FaceRig).</summary>
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

        /// <summary>Deja en el objeto raíz la mirada de los ojos apuntando a la cabeza del avatar.</summary>
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
        /// Pone al día el HUD de una escena que ya existe: Canvas en Screen Space -
        /// Camera, widgets de depuración dentro de un grupo que F1 esconde y logo
        /// de marca fuera de ese grupo.
        /// </summary>
        private static void UpgradeHud(GameObject root)
        {
            Transform hud = root.transform.Find(HudName);
            if (hud == null)
            {
                Debug.LogWarning("[Sonia] No hay objeto \"" + HudName + "\"; no se puede poner al día el HUD.");
                return;
            }

            Undo.RecordObject(hud.gameObject, "Actualizar componentes de Sonia");
            ConfigureHudCanvas(hud.GetComponent<Canvas>());

            Transform debugGroup = hud.Find(HudDebugName);
            if (debugGroup == null)
            {
                GameObject group = new GameObject(HudDebugName, typeof(RectTransform));
                group.transform.SetParent(hud, false);
                group.layer = hud.gameObject.layer;
                StretchFull(group.GetComponent<RectTransform>());
                Undo.RegisterCreatedObjectUndo(group, "Actualizar componentes de Sonia");
                debugGroup = group.transform;

                // Todo lo que ya colgaba del Canvas se mete en el grupo, menos el
                // logo. Con worldPositionStays en falso los anclajes se respetan.
                Transform[] hijos = new Transform[hud.childCount];
                for (int i = 0; i < hud.childCount; i++)
                {
                    hijos[i] = hud.GetChild(i);
                }

                for (int i = 0; i < hijos.Length; i++)
                {
                    if (hijos[i] == debugGroup || hijos[i].name == BrandLogoName)
                    {
                        continue;
                    }

                    Undo.SetTransformParent(hijos[i], debugGroup, "Actualizar componentes de Sonia");
                    hijos[i].SetParent(debugGroup, false);
                }
            }

            EnsureBrandLogo(hud);
            MoveHudLabel(debugGroup, "Connection", HudConnectionPosition);
            MoveHudLabel(debugGroup, "State", HudStatePosition);

            SoniaDebugUiRefs subtitleRefs = default(SoniaDebugUiRefs);
            EnsureSubtitles(debugGroup, ref subtitleRefs);

            // El panel de imágenes lo dibuja la cámara del HUD, sin postprocesado
            // y por encima del avatar: la imagen se ve tal cual es.
            Transform panel = root.transform.Find(PanelName);
            if (panel != null)
            {
                Undo.RecordObject(panel.gameObject, "Actualizar componentes de Sonia");
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

        /// <summary>Recoloca una etiqueta del HUD que ya existe en la escena.</summary>
        private static void MoveHudLabel(Transform debugGroup, string name, Vector2 position)
        {
            Transform label = debugGroup != null ? debugGroup.Find(name) : null;
            RectTransform rect = label != null ? label.GetComponent<RectTransform>() : null;
            if (rect == null)
            {
                return;
            }

            Undo.RecordObject(rect, "Actualizar componentes de Sonia");
            rect.anchoredPosition = position;
            EditorUtility.SetDirty(rect);
        }

        /// <summary>Devuelve el componente del objeto, añadiéndolo si no estaba.</summary>
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
        /// Coloca la cámara para el encuadre vertical: avatar de cuerpo entero
        /// abajo y hueco arriba para el panel de imágenes.
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
                Debug.LogWarning("[Sonia] No hay cámara en la escena; colócala a mano según docs/unity.md.");
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
        // Panel de imágenes
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

            // El componente convierte el Transform en RectTransform, así que se
            // añade antes de colocar el objeto.
            // El pie va ENCIMA de la imagen: debajo chocaría con la cabeza del
            // avatar, que queda justo bajo el panel.
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

            // El componente recalcula el tamaño al mostrar cada imagen, así que
            // estos dos campos son los que mandan de verdad.
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
                    "[Sonia] No se encontró un shader unlit; el panel usará el material por defecto del Quad.");
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
                    "[Sonia] No se pudo crear " + MaterialFolder
                    + "; el panel usará el material por defecto del Quad.");
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

        /// <summary>Nombre de la cámara superpuesta que dibuja el HUD.</summary>
        private const string HudCameraName = "HudCamera";

        /// <summary>
        /// Deja el Canvas del HUD en Screen Space - Camera sobre una cámara
        /// superpuesta (URP camera stacking) sin postprocesado. Con la cámara
        /// principal, el HUD pasaba por el tonemapping ACES, el bloom, la viñeta
        /// y la profundidad de campo: el logo de la esquina salía oscuro y el
        /// texto, lavado. En Overlay no pasaría por nada, pero tampoco saldría en
        /// las capturas 1080x1920 con las que se verifica todo; la cámara apilada
        /// sí se renderiza con la principal.
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
                    "[Sonia] No hay cámara principal; el HUD se queda en Overlay y no saldrá "
                    + "en las capturas.");
                return;
            }

            Camera hudCamera = EnsureHudCamera(main);
            canvas.renderMode = RenderMode.ScreenSpaceCamera;
            canvas.worldCamera = hudCamera != null ? hudCamera : main;
            canvas.planeDistance = HudPlaneDistance;
            canvas.sortingOrder = 100;
        }

        /// <summary>
        /// Cámara superpuesta hija de la principal: solo la capa UI y sin
        /// postprocesado. La principal deja de dibujar la capa UI.
        /// </summary>
        private static Camera EnsureHudCamera(Camera main)
        {
            int uiLayer = LayerMask.NameToLayer("UI");
            if (uiLayer < 0)
            {
                Debug.LogWarning("[Sonia] No existe la capa UI; el HUD se dibuja con la cámara principal.");
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
                Undo.RegisterCreatedObjectUndo(cameraObject, "Crear cámara del HUD");
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

            // Los canvas en Overlay (paneles de ajustes y animaciones) no usan
            // cámara; el resto de la UI es este HUD, que ya no dibuja la principal.
            main.cullingMask &= ~(1 << uiLayer);
            EditorUtility.SetDirty(main);
            EditorUtility.SetDirty(hudCamera);
            return hudCamera;
        }

        /// <summary>Crea o actualiza el logo de Sonnet Code, arriba a la izquierda del HUD.</summary>
        private static Image EnsureBrandLogo(Transform canvasTransform)
        {
            Transform existing = canvasTransform.Find(BrandLogoName);
            GameObject logoObject;
            if (existing != null)
            {
                logoObject = existing.gameObject;
            }
            else
            {
                logoObject = new GameObject(BrandLogoName, typeof(RectTransform));
                logoObject.transform.SetParent(canvasTransform, false);
                logoObject.layer = canvasTransform.gameObject.layer;
            }

            RectTransform rect = logoObject.GetComponent<RectTransform>();
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(0f, 1f);
            rect.pivot = new Vector2(0f, 1f);
            rect.anchoredPosition = new Vector2(BrandLogoMargin, -BrandLogoMargin);
            rect.sizeDelta = new Vector2(BrandLogoWidth, BrandLogoWidth / BrandLogoAspect);

            Image image = logoObject.GetComponent<Image>();
            if (image == null)
            {
                image = logoObject.AddComponent<Image>();
            }

            image.sprite = SoniaBrandAssets.LoadLogoSprite();
            image.preserveAspect = true;
            image.raycastTarget = false;
            image.color = Color.white;

            // El logo va el primero para que el resto del HUD se dibuje encima si
            // alguna vez se solapan.
            logoObject.transform.SetAsFirstSibling();
            EditorUtility.SetDirty(logoObject);
            return image;
        }

        /// <summary>Nombre del contenedor de subtítulos dentro del grupo de depuración.</summary>
        private const string SubtitlesName = "Subtitles";

        /// <summary>
        /// Subtítulos como dos burbujas apiladas sobre la fila de texto: la del
        /// visitante (pequeña, gris, etiqueta "TÚ") y la de Sonia (grande, blanca,
        /// etiqueta "SONIA" en el azul de la marca). Cada burbuja crece con su
        /// texto y se oculta cuando está vacía, así nunca se pisan.
        /// </summary>
        private static void EnsureSubtitles(Transform debugGroup, ref SoniaDebugUiRefs refs)
        {
            // Las etiquetas sueltas de versiones anteriores sobran.
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
            Undo.RegisterCreatedObjectUndo(container, "Crear subtítulos");
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
                "TÚ",
                new Color(0.62f, 0.70f, 0.82f, 1f),
                new Color(0.04f, 0.07f, 0.14f, 0.55f),
                26f,
                new Color(0.86f, 0.89f, 0.95f, 1f),
                out refs.User);
            refs.AssistantBubble = CreateSubtitleBubble(
                container.transform,
                "AssistantBubble",
                "SONIA",
                new Color(0.44f, 0.66f, 1f, 1f),
                new Color(0.02f, 0.05f, 0.12f, 0.72f),
                36f,
                Color.white,
                out refs.Assistant);

            // Empiezan vacías y ocultas; SoniaDebugUI las enciende con el texto.
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

        /// <summary>Pone la capa a un objeto y a todos sus hijos (si la capa existe).</summary>
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

        /// <summary>Deja un RectTransform ocupando todo su padre.</summary>
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

            // El logo de marca va directo en el Canvas: F1 esconde el grupo de
            // depuración, no la marca.
            EnsureBrandLogo(canvasObject.transform);

            GameObject debugGroup = new GameObject(HudDebugName, typeof(RectTransform));
            debugGroup.transform.SetParent(canvasObject.transform, false);
            debugGroup.layer = canvasObject.layer;
            StretchFull(debugGroup.GetComponent<RectTransform>());
            refs.DebugGroup = debugGroup;

            // Estado de la conexión y del asistente: arriba del todo.
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
                "Sin conexión");

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

            // Subtítulos abajo, encima de la fila de entrada de texto.
            EnsureSubtitles(debugGroup.transform, ref refs);

            TMP_DefaultControls.Resources resources = BuildResources();

            GameObject inputObject = TMP_DefaultControls.CreateInputField(resources);
            inputObject.name = "TextInput";
            inputObject.transform.SetParent(debugGroup.transform, false);
            RectTransform inputRect = inputObject.GetComponent<RectTransform>();
            // En 1080 de ancho, el campo y el botón van juntos en una sola fila
            // abajo, con 40 px de margen a cada lado.
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
                    placeholder.text = "Escribe y pulsa Enter…";
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
                buttonLabel.text = "Interrumpir";
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
                // Con activeInputHandler = 1 hace falta el módulo del Input System nuevo.
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
        // Cableado
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
        // Utilidades
        // ------------------------------------------------------------------

        /// <summary>
        /// Asigna una referencia por nombre de campo. Avisa en lugar de reventar si
        /// el campo se renombró y este script se quedó atrás.
        /// </summary>
        private static void SetReference(SerializedObject target, string path, Object value)
        {
            SerializedProperty property = target.FindProperty(path);
            if (property == null)
            {
                Debug.LogWarning(
                    "[Sonia] El campo \"" + path + "\" no existe en " + target.targetObject.GetType().Name
                    + "; hay que asignarlo a mano en el inspector.");
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
                    "[Sonia] El campo \"" + path + "." + relativePath + "\" no existe en "
                    + target.targetObject.GetType().Name + "; hay que asignarlo a mano en el inspector.");
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
