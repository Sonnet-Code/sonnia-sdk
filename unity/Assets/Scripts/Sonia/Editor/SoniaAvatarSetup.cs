// Coloca un avatar VRM en la escena, lo cablea y ajusta el encuadre del stand.
//
// El menú vale para cualquier VRM o GLB: la ruta se elige con "Sonia/Elegir avatar (VRM o GLB)"
// y la convención de blendshapes de la cara se detecta sola (VRM estándar,
// VRoid, Seed-san u Oculus / Ready Player Me).
//
// Un par de cosas que no son obvias:
//
//  * Los VRM miran hacia +Z, y la cámara del stand está en Z negativo mirando
//    hacia +Z, así que el avatar se gira 180 grados en Y para quedar de frente.
//  * Vrm10Instance aplica cada frame los pesos de sus expresiones (todas a cero)
//    sobre los mismos blendshapes que usa el lip-sync, y la mirada sobre los
//    huesos de los ojos. Los ojos están mapeados en el Humanoid, así que el
//    Animator los reinicia en cada pasada de animación: la mirada solo se ve si
//    se aplica DESPUÉS, en LateUpdate. Por eso Vrm10Instance queda en LateUpdate
//    (orden 11000) y LipSyncController y AvatarStateController llevan
//    [DefaultExecutionOrder(12000)] para escribir boca y parpadeo después.
//  * El encuadre del stand es un plano medio en vertical 9:16: de un poco por
//    debajo de las caderas a justo por encima de la cabeza, con muy poco aire.
//    Se calcula con los huesos reales del avatar, no con los bounds de los
//    renderers, porque los accesorios (mochilas, brazos robóticos, armas)
//    ensanchan los bounds muchísimo y estropean el cálculo.

#if UNITY_EDITOR

using TMPro;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Sonia.EditorTools
{
    /// <summary>Menús que montan el avatar y dejan la cámara y el panel en su sitio.</summary>
    public static class SoniaAvatarSetup
    {
        /// <summary>Avatar por defecto si nadie ha elegido otro.</summary>
        private const string DefaultAvatarPath = "Assets/Avatar/Babe.glb";

        /// <summary>Clave de EditorPrefs donde se recuerda el avatar elegido.</summary>
        private const string AvatarPathKey = "Sonia.AvatarPath";

        private const string AvatarObjectName = "Avatar";
        private const string RootName = "Sonia";
        private const string PanelName = "ImagePanel";
        private const string UndoName = "Colocar avatar de Sonia";

        // ------------------------------------------------------------------
        // Encuadre del stand
        // ------------------------------------------------------------------

        /// <summary>Campo de visión vertical de la cámara, en grados.</summary>
        private const float CameraFieldOfView = 40f;

        /// <summary>Metros que se dejan por encima de la cabeza. Muy poco aire a propósito.</summary>
        private const string TopMarginKey = "Sonia.FramingTopMargin";

        private const float DefaultTopMargin = 0.12f;

        /// <summary>Metros que se ven por debajo de las caderas.</summary>
        private const float HipMargin = 0.05f;

        /// <summary>
        /// Profundidad del panel de imágenes. Va detrás del avatar; el tamaño se
        /// calcula luego para que quepa en el hueco libre de la pantalla.
        /// </summary>
        private const float PanelDepth = 2.6f;

        /// <summary>
        /// Borde derecho del panel en coordenadas de pantalla, donde 1 es el borde
        /// de la imagen. Se deja un poco de aire para que no toque el marco.
        /// </summary>
        private const float PanelScreenRightEdge = 0.97f;

        /// <summary>
        /// Aire entre la silueta de la cabeza y el borde izquierdo del panel, en
        /// las mismas unidades de pantalla.
        /// </summary>
        private const float PanelHeadGap = 0.015f;

        /// <summary>Borde superior del bloque del panel en coordenadas de pantalla.</summary>
        private const float PanelScreenTopEdge = 0.93f;

        /// <summary>
        /// Fracción del ancho de pantalla que ocupa la imagen en el encuadre de
        /// panel. Con menos no se lee desde el pasillo del stand.
        /// </summary>
        private const float PanelShotScreenWidth = 0.76f;

        /// <summary>
        /// Metros por debajo de los hombros donde queda el borde inferior de la
        /// pantalla en el encuadre de panel: se ve a Sonia del pecho hacia arriba.
        /// </summary>
        private const float PanelShotChestDrop = 0.1f;

        /// <summary>
        /// Altura en pantalla a la que queda la coronilla en el encuadre de panel.
        /// Negativa: justo por debajo del centro, para dejar libre la mitad de
        /// arriba.
        /// </summary>
        private const float PanelShotHeadTopV = -0.13f;

        /// <summary>Proporción del panel. Las imágenes de la galería son 16:9.</summary>
        private const float PanelAspect = 16f / 9f;

        /// <summary>Separación entre el borde inferior de la imagen y el pie de foto, en metros.</summary>
        private const float CaptionGap = 0.025f;

        /// <summary>Alto de la caja del pie de foto, como fracción del alto del panel.</summary>
        private const float CaptionHeightFactor = 0.3f;

        /// <summary>Proporción de la pantalla del stand, para calcular el ancho visible.</summary>
        private const float StandAspect = (float)SoniaCapture.Width / SoniaCapture.Height;

        // ------------------------------------------------------------------
        // Plano abierto para bailes y saludos
        // ------------------------------------------------------------------

        /// <summary>Metros que se ven por debajo de los pies en plano abierto.</summary>
        private const float WideFootMargin = 0.05f;

        /// <summary>Metros de aire por encima de la cabeza en plano abierto.</summary>
        private const float WideHeadMargin = 0.15f;

        /// <summary>
        /// Envergadura que tiene que caber a lo ancho. En 9:16 el ancho es el que
        /// manda, no el alto: medido sobre Dance_HipHop y Blow_Kiss con Yae, los
        /// brazos llegan a 1,49 m de punta a punta, así que con 1,55 sobra un poco.
        /// </summary>
        private const float WideArmSpan = 1.55f;

        // ------------------------------------------------------------------
        // Fondo y luz
        // ------------------------------------------------------------------

        private const string BackdropName = "Backdrop";
        private const string TextureFolder = "Assets/Sonia/Textures";
        private const string MaterialFolder = "Assets/Sonia/Materials";
        private const string BackdropMaterialPath = MaterialFolder + "/SoniaBackdrop.mat";
        private const string BackdropTexturePath = TextureFolder + "/SoniaBackdrop.asset";

        /// <summary>
        /// Detrás del panel de imágenes. Tiene que quedar POR DETRÁS de verdad: si
        /// se pone delante, el telón tapa el panel y la imagen no se ve.
        /// </summary>
        private const float BackdropZ = PanelDepth + 0.6f;

        /// <summary>Margen del telón sobre lo que ve la cámara más abierta.</summary>
        private const float BackdropMargin = 1.2f;

        private static readonly Color CameraBackground = new Color32(0x0E, 0x1B, 0x33, 0xFF);
        private static readonly Color BackdropTop = new Color32(0x2A, 0x31, 0x42, 0xFF);
        private static readonly Color BackdropBottom = new Color32(0x12, 0x15, 0x1C, 0xFF);

        /// <summary>
        /// Recorte del fondo corporativo sobre el telón. La textura es 16:9 y el
        /// telón es vertical, así que se toma una franja estrecha y alta.
        ///
        /// La franja se coge de la IZQUIERDA, que es donde está la S de marca de
        /// agua, y se corta por arriba para dejar fuera el logo de la esquina: en
        /// el HUD ya hay uno y no puede salir dos veces.
        /// </summary>
        private static readonly Vector2 BackdropTiling = new Vector2(0.221f, 0.7f);

        private static readonly Vector2 BackdropOffset = new Vector2(0.02f, 0f);

        /// <summary>Luz principal: cálida, suave y de frente, para que la cara no se queme.</summary>
        private static readonly Color KeyLightColor = new Color32(0xFF, 0xF4, 0xE6, 0xFF);

        private const float KeyLightIntensity = 1f;

        /// <summary>
        /// Frontal y desde arriba. La Y ronda 0 grados porque el avatar mira hacia
        /// -Z: con la luz apuntando a -Z quedaría a contraluz y la cara a oscuras.
        /// </summary>
        private static readonly Vector3 KeyLightRotation = new Vector3(25f, 340f, 0f);

        // ------------------------------------------------------------------
        // Convenciones de blendshapes
        // ------------------------------------------------------------------

        /// <summary>
        /// Una forma de nombrar los blendshapes de la cara. Se elige la primera
        /// cuyo blendshape de prueba exista en la malla.
        /// </summary>
        private sealed class BlendShapeConvention
        {
            public string Name;
            public string Probe;
            public string BlinkLeft;
            public string BlinkRight;
            public string BlinkBoth;
            public string MouthOpen;
            public string[,] Visemes;
        }

        /// <summary>
        /// Convenciones conocidas, en orden de prueba. El mapa de visemas usa los
        /// identificadores del protocolo; una cadena vacía significa "este visema
        /// no mueve ningún blendshape" y la boca se cierra sola.
        /// </summary>
        private static readonly BlendShapeConvention[] Conventions =
        {
            // VRM estándar (Yae, Snb y la mayoría de modelos exportados a VRM).
            new BlendShapeConvention
            {
                Name = "VRM (Aa/Ih/Ou/Ee/Oh)",
                Probe = "Aa",
                BlinkLeft = "Blink_L",
                BlinkRight = "Blink_R",
                BlinkBoth = "Blink",
                MouthOpen = "Aa",
                Visemes = new[,]
                {
                    { VisemeIds.Sil, string.Empty },
                    { VisemeIds.PP, string.Empty },
                    { VisemeIds.FF, "Ih" },
                    { VisemeIds.TH, "Ih" },
                    { VisemeIds.DD, "Ih" },
                    { VisemeIds.KK, "Ee" },
                    { VisemeIds.CH, "Ih" },
                    { VisemeIds.SS, "Ih" },
                    { VisemeIds.NN, "Ee" },
                    { VisemeIds.RR, "Ee" },
                    { VisemeIds.AA, "Aa" },
                    { VisemeIds.E, "Ee" },
                    { VisemeIds.IH, "Ih" },
                    { VisemeIds.OH, "Oh" },
                    { VisemeIds.OU, "Ou" }
                }
            },

            // VRoid Studio.
            new BlendShapeConvention
            {
                Name = "VRoid (Fcl_MTH_*)",
                Probe = "Fcl_MTH_A",
                BlinkLeft = "Fcl_EYE_Close_L",
                BlinkRight = "Fcl_EYE_Close_R",
                BlinkBoth = "Fcl_EYE_Close",
                MouthOpen = "Fcl_MTH_A",
                Visemes = new[,]
                {
                    { VisemeIds.Sil, string.Empty },
                    { VisemeIds.PP, string.Empty },
                    { VisemeIds.FF, "Fcl_MTH_I" },
                    { VisemeIds.TH, "Fcl_MTH_I" },
                    { VisemeIds.DD, "Fcl_MTH_I" },
                    { VisemeIds.KK, "Fcl_MTH_E" },
                    { VisemeIds.CH, "Fcl_MTH_I" },
                    { VisemeIds.SS, "Fcl_MTH_I" },
                    { VisemeIds.NN, "Fcl_MTH_E" },
                    { VisemeIds.RR, "Fcl_MTH_E" },
                    { VisemeIds.AA, "Fcl_MTH_A" },
                    { VisemeIds.E, "Fcl_MTH_E" },
                    { VisemeIds.IH, "Fcl_MTH_I" },
                    { VisemeIds.OH, "Fcl_MTH_O" },
                    { VisemeIds.OU, "Fcl_MTH_U" }
                }
            },

            // Seed-san y modelos de la misma familia.
            new BlendShapeConvention
            {
                Name = "Seed-san (lip_*)",
                Probe = "lip_a",
                BlinkLeft = "blink_L",
                BlinkRight = "blink_R",
                BlinkBoth = "eye_close",
                MouthOpen = "mouse_open",
                Visemes = new[,]
                {
                    { VisemeIds.Sil, string.Empty },
                    { VisemeIds.PP, string.Empty },
                    { VisemeIds.FF, "lip_u" },
                    { VisemeIds.TH, "lip_i" },
                    { VisemeIds.DD, "lip_i" },
                    { VisemeIds.KK, "lip_e" },
                    { VisemeIds.CH, "lip_i" },
                    { VisemeIds.SS, "lip_i" },
                    { VisemeIds.NN, "lip_e" },
                    { VisemeIds.RR, "lip_e" },
                    { VisemeIds.AA, "lip_a" },
                    { VisemeIds.E, "lip_e" },
                    { VisemeIds.IH, "lip_i" },
                    { VisemeIds.OH, "lip_o" },
                    { VisemeIds.OU, "lip_u" }
                }
            },

            // Oculus / Ready Player Me.
            new BlendShapeConvention
            {
                Name = "Oculus (viseme_*)",
                Probe = "viseme_aa",
                BlinkLeft = "eyeBlinkLeft",
                BlinkRight = "eyeBlinkRight",
                BlinkBoth = "eyesClosed",
                MouthOpen = "jawOpen",
                Visemes = new[,]
                {
                    { VisemeIds.Sil, "viseme_sil" },
                    { VisemeIds.PP, "viseme_PP" },
                    { VisemeIds.FF, "viseme_FF" },
                    { VisemeIds.TH, "viseme_TH" },
                    { VisemeIds.DD, "viseme_DD" },
                    { VisemeIds.KK, "viseme_kk" },
                    { VisemeIds.CH, "viseme_CH" },
                    { VisemeIds.SS, "viseme_SS" },
                    { VisemeIds.NN, "viseme_nn" },
                    { VisemeIds.RR, "viseme_RR" },
                    { VisemeIds.AA, "viseme_aa" },
                    { VisemeIds.E, "viseme_E" },
                    { VisemeIds.IH, "viseme_I" },
                    { VisemeIds.OH, "viseme_O" },
                    { VisemeIds.OU, "viseme_U" }
                }
            }
        };

        /// <summary>Ruta del VRM que se va a colocar.</summary>
        public static string AvatarPath
        {
            get { return EditorPrefs.GetString(AvatarPathKey, DefaultAvatarPath); }
            set { EditorPrefs.SetString(AvatarPathKey, value); }
        }

        /// <summary>Metros de aire por encima de la cabeza en el encuadre.</summary>
        public static float TopMargin
        {
            get { return EditorPrefs.GetFloat(TopMarginKey, DefaultTopMargin); }
            set { EditorPrefs.SetFloat(TopMarginKey, value); }
        }

        // ------------------------------------------------------------------
        // Menús
        // ------------------------------------------------------------------

        [MenuItem("Sonia/Elegir avatar (VRM o GLB)")]
        public static void ChooseAvatar()
        {
            string absolute = EditorUtility.OpenFilePanelWithFilters(
                "Elegir avatar", Application.dataPath + "/Avatar",
                new[] { "Avatares", "vrm,glb,gltf,fbx", "Todos", "*" });
            if (string.IsNullOrEmpty(absolute))
            {
                return;
            }

            string projectRoot = System.IO.Path.GetDirectoryName(Application.dataPath);
            if (!absolute.StartsWith(projectRoot))
            {
                EditorUtility.DisplayDialog(
                    "Sonia", "El avatar tiene que estar dentro del proyecto, en Assets/.", "Vale");
                return;
            }

            AvatarPath = absolute.Substring(projectRoot.Length + 1).Replace('\\', '/');
            Debug.Log("[Sonia] Avatar elegido: " + AvatarPath + ". Ejecuta Sonia > Colocar avatar.");
        }

        [MenuItem("Sonia/Colocar avatar")]
        public static void PlaceAvatarMenu()
        {
            PlaceAvatar(AvatarPath);
        }

        /// <summary>
        /// Instancia el VRM bajo el objeto "Sonia", lo cablea con los componentes
        /// de la escena y deja la cámara y el panel de imágenes en su sitio.
        /// </summary>
        public static GameObject PlaceAvatar(string assetPath)
        {
            Scene scene = SceneManager.GetActiveScene();
            if (!scene.IsValid() || !scene.isLoaded)
            {
                EditorUtility.DisplayDialog("Sonia", "No hay ninguna escena abierta.", "Vale");
                return null;
            }

            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
            if (prefab == null)
            {
                EditorUtility.DisplayDialog(
                    "Sonia",
                    "No se encontró " + assetPath + ". Importa el VRM o elige otro con "
                    + "Sonia > Elegir avatar (VRM o GLB).",
                    "Vale");
                return null;
            }

            SoniaBootstrap bootstrap = FindInScene<SoniaBootstrap>(scene);
            Transform root = bootstrap != null ? bootstrap.transform : FindRootByName(scene);
            if (root == null)
            {
                EditorUtility.DisplayDialog(
                    "Sonia",
                    "No hay ningún objeto \"" + RootName + "\" en la escena. Ejecuta antes Sonia > Crear escena base.",
                    "Vale");
                return null;
            }

            int undoGroup = Undo.GetCurrentGroup();

            // Se rehace desde cero para que el menú se pueda ejecutar las veces
            // que haga falta sin acumular avatares.
            Transform previous = root.Find(AvatarObjectName);
            if (previous != null)
            {
                Undo.DestroyObjectImmediate(previous.gameObject);
            }

            GameObject avatar = (GameObject)PrefabUtility.InstantiatePrefab(prefab, root);
            if (avatar == null)
            {
                Debug.LogError("[Sonia] No se pudo instanciar " + assetPath + ".");
                return null;
            }

            Undo.RegisterCreatedObjectUndo(avatar, UndoName);
            avatar.name = AvatarObjectName;
            avatar.transform.SetParent(root, false);
            avatar.transform.localPosition = Vector3.zero;

            // Los VRM miran hacia +Z; la cámara también, así que hay que darle
            // media vuelta para que quede de frente.
            avatar.transform.localRotation = Quaternion.Euler(0f, 180f, 0f);
            avatar.transform.localScale = Vector3.one;

            // Los VRM y los FBX Humanoid ya traen Animator con Avatar; a los GLB
            // (Ready Player Me y similares) se les construye uno a partir del
            // esqueleto de Mixamo.
            Animator animator = SoniaHumanoidRig.EnsureHumanoidAnimator(avatar, assetPath);
            if (animator == null)
            {
                animator = avatar.GetComponentInChildren<Animator>(true);
            }

            ConfigureAnimator(animator);
            ConfigureVrm10Instance(avatar);

            BlendShapeConvention convention;
            SkinnedMeshRenderer face = FindFaceRenderer(avatar, out convention);
            Transform head = animator != null ? animator.GetBoneTransform(HumanBodyBones.Head) : null;

            WireAvatarState(root, animator, head, face, convention);
            WireLipSync(root, face, convention);
            WireChoreography(root, animator);
            SoniaSceneSetup.EnsurePhonemeLipSync(root.gameObject, root.GetComponentInChildren<AvatarStateController>(true));
            SoniaSceneSetup.EnsureEyeGaze(
                root.gameObject,
                root.GetComponentInChildren<AvatarStateController>(true),
                root.GetComponentInChildren<AvatarChoreographer>(true),
                animator);
            SoniaSceneSetup.EnsureFacialExpressions(
                root.gameObject, root.GetComponentInChildren<AvatarStateController>(true));

            float headTop;
            float hipsY;
            float shouldersY;
            MeasureAvatar(avatar, animator, out hipsY, out headTop, out shouldersY);

            Vector3 widePosition;
            Vector3 panelPosition;
            Camera camera = SetUpFraming(
                scene, hipsY, headTop, shouldersY, out widePosition, out panelPosition);
            SetUpImagePanel(root, avatar, animator, camera, panelPosition);
            SetUpBackdrop(root, camera, widePosition, panelPosition);
            SetUpLighting(scene);
            if (head != null && camera != null)
            {
                SoniaStageLighting.Apply(scene, head.position, camera);
            }

            WireCameraFraming(root, animator, camera, widePosition, panelPosition);

            Selection.activeGameObject = avatar;
            Undo.SetCurrentGroupName(UndoName);
            Undo.CollapseUndoOperations(undoGroup);
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);

            Debug.Log(
                "[Sonia] Avatar " + System.IO.Path.GetFileName(assetPath) + " colocado. "
                + "Convención de blendshapes: " + (convention != null ? convention.Name : "ninguna reconocida")
                + ". Cara: " + (face != null ? face.name : "sin malla")
                + ". Cabeza: " + (head != null ? head.name : "sin hueso")
                + ". Caderas y=" + hipsY.ToString("F2")
                + ", hombros y=" + shouldersY.ToString("F2")
                + ", alto de cabeza y=" + headTop.ToString("F2") + ".",
                avatar);

            return avatar;
        }

        // ------------------------------------------------------------------
        // Avatar
        // ------------------------------------------------------------------

        private static void ConfigureAnimator(Animator animator)
        {
            if (animator == null)
            {
                Debug.LogWarning("[Sonia] El avatar no tiene Animator; no habrá animaciones.");
                return;
            }

            Undo.RecordObject(animator, UndoName);

            // Los clips los reproduce MotionPlayer con la Playables API; el
            // Animator solo aporta el retargeting humanoide y no lleva controlador.
            animator.runtimeAnimatorController = null;

            // Las animaciones de Mixamo se reproducen en el sitio: el avatar no se
            // mueve del origen de la escena.
            animator.applyRootMotion = false;

            // En el stand la cámara siempre lo ve, pero con culling por defecto un
            // frame fuera de pantalla congela la pose y el lip-sync.
            animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            EditorUtility.SetDirty(animator);
        }

        /// <summary>
        /// Ajusta el componente de UniVRM sin depender de su ensamblado: se busca
        /// por nombre de tipo y se escriben sus campos con SerializedObject. Si el
        /// avatar no fuera un VRM 1.0, simplemente no hace nada.
        /// </summary>
        private static void ConfigureVrm10Instance(GameObject avatar)
        {
            MonoBehaviour instance = null;
            MonoBehaviour[] components = avatar.GetComponents<MonoBehaviour>();
            for (int i = 0; i < components.Length; i++)
            {
                if (components[i] != null && components[i].GetType().Name == "Vrm10Instance")
                {
                    instance = components[i];
                    break;
                }
            }

            if (instance == null)
            {
                return;
            }

            SerializedObject serialized = new SerializedObject(instance);

            // UniVRM se queda en LateUpdate para que su LookAt corra después del
            // Animator y los ojos giren de verdad. Quien se aparta es lo nuestro:
            // LipSyncController y AvatarStateController llevan orden de ejecución
            // 12000, así que escriben la boca y la cabeza después de UniVRM.
            SetEnumByName(serialized, "UpdateType", "LateUpdate");

            Camera main = Camera.main;
            if (main != null)
            {
                SetEnumByName(serialized, "LookAtTargetType", "SpecifiedTransform");
                SerializedProperty target = serialized.FindProperty("LookAtTarget");
                if (target != null)
                {
                    target.objectReferenceValue = main.transform;
                }
            }

            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        /// <summary>
        /// Busca la malla de la cara probando las convenciones conocidas. Devuelve
        /// también cuál encajó, que es la que da el mapa de visemas y el parpadeo.
        /// </summary>
        private static SkinnedMeshRenderer FindFaceRenderer(
            GameObject avatar,
            out BlendShapeConvention convention)
        {
            SkinnedMeshRenderer[] renderers = avatar.GetComponentsInChildren<SkinnedMeshRenderer>(true);
            SkinnedMeshRenderer withShapes = null;

            for (int i = 0; i < renderers.Length; i++)
            {
                Mesh mesh = renderers[i].sharedMesh;
                if (mesh == null || mesh.blendShapeCount == 0)
                {
                    continue;
                }

                if (withShapes == null)
                {
                    withShapes = renderers[i];
                }

                for (int c = 0; c < Conventions.Length; c++)
                {
                    if (HasBlendShape(mesh, Conventions[c].Probe))
                    {
                        convention = Conventions[c];
                        return renderers[i];
                    }
                }
            }

            convention = null;
            if (withShapes == null)
            {
                Debug.LogWarning(
                    "[Sonia] El avatar no tiene ninguna malla con blendshapes; no habrá lip-sync ni parpadeo.");
            }
            else
            {
                Debug.LogWarning(
                    "[Sonia] La malla \"" + withShapes.name + "\" no usa ninguna convención conocida de "
                    + "blendshapes; hay que rellenar los visemas a mano en LipSyncController.");
            }

            return withShapes;
        }

        /// <summary>
        /// Mide el avatar con los huesos del rig humanoide. No se usan los bounds
        /// de los renderers porque los accesorios (mochilas, armas, brazos
        /// robóticos) los ensanchan y darían un encuadre absurdo.
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
                Debug.LogWarning("[Sonia] El avatar no tiene rig humanoide; se usan medidas por defecto.");
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

            // El alto real de la cabeza sale del renderer, que incluye el pelo,
            // pero acotado al hueso: así un accesorio alto no dispara el encuadre.
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
        // Encuadre y panel
        // ------------------------------------------------------------------

        /// <summary>
        /// Deja la cámara en un plano medio vertical: de un poco por debajo de las
        /// caderas a justo por encima de la cabeza, con muy poco aire arriba.
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
                Debug.LogWarning("[Sonia] No hay cámara en la escena; no se puede ajustar el encuadre.");
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

            // Sin cielo: el horizonte de la plantilla cruzaba el pecho del avatar.
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = CameraBackground;
            EditorUtility.SetDirty(camera);

            // Plano abierto para los bailes: de los pies a por encima de la cabeza,
            // y con hueco a los lados para los brazos. En 9:16 casi siempre manda
            // el ancho, no el alto.
            float wideBottom = -WideFootMargin;
            float wideTop = headTop + WideHeadMargin;
            float wideDistance = Mathf.Max(
                ((wideTop - wideBottom) * 0.5f) / tangentHalf,
                (WideArmSpan * 0.5f) / (tangentHalf * StandAspect));
            widePosition = new Vector3(0f, (wideTop + wideBottom) * 0.5f, -wideDistance);

            // Encuadre de panel: Sonia del pecho hacia arriba en la mitad de abajo
            // y la mitad de arriba libre para la imagen. Se resuelve pidiendo que
            // el borde inferior caiga en el pecho y la coronilla quede justo por
            // debajo del centro de la pantalla.
            float chestY = shouldersY - PanelShotChestDrop;
            float panelCameraY = (headTop + (PanelShotHeadTopV * chestY)) / (1f + PanelShotHeadTopV);
            float panelHalfHeight = Mathf.Max(0.2f, panelCameraY - chestY);
            panelPosition = new Vector3(0f, panelCameraY, -(panelHalfHeight / tangentHalf));

            Debug.Log(
                "[Sonia] Encuadre 9:16: se ve de y=" + bottom.ToString("F2") + " a y=" + top.ToString("F2")
                + " (" + visibleHeight.ToString("F2") + " m). Cámara en (0, "
                + ((top + bottom) * 0.5f).ToString("F2") + ", " + (-distance).ToString("F2")
                + ") con FOV " + CameraFieldOfView + ". Plano abierto en "
                + widePosition.ToString("F2") + ", plano de panel en "
                + panelPosition.ToString("F2") + ".",
                camera);

            return camera;
        }

        /// <summary>Media anchura visible, en metros, a esa Z del mundo y en 9:16.</summary>
        private static float VisibleHalfWidthAt(Camera camera, float worldZ)
        {
            return VisibleHalfWidthAt(camera.transform.position.z, worldZ);
        }

        /// <summary>Lo mismo, pero para una pose de cámara que todavía no existe en la escena.</summary>
        private static float VisibleHalfWidthAt(float cameraZ, float worldZ)
        {
            float distance = Mathf.Max(0.1f, worldZ - cameraZ);
            return distance * Mathf.Tan(CameraFieldOfView * 0.5f * Mathf.Deg2Rad) * StandAspect;
        }

        /// <summary>
        /// Coloca el panel de imágenes grande y centrado por encima de la cabeza.
        ///
        /// El tamaño se calcula sobre el ENCUADRE DE PANEL, no sobre el plano
        /// medio: cuando aparece una imagen la cámara se echa atrás y sube, la
        /// mitad de arriba de la pantalla queda libre y ahí cabe una imagen que se
        /// lee desde el pasillo. Todo en coordenadas de pantalla, donde 1 es el
        /// borde de la imagen.
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

            // Banda libre por encima de la coronilla. El bloque es la imagen más
            // el pie, y se centra en esa banda.
            float bandBottom = headTopV + PanelHeadGap;
            float bandHeight = Mathf.Max(0.2f, PanelScreenTopEdge - bandBottom) * halfHeight;
            float blockHeight = height * (1f + CaptionHeightFactor) + CaptionGap;

            // Si el bloque no cabe de alto, manda el alto y la imagen se encoge.
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

            // El tamaño de verdad lo recalcula el componente al mostrar la imagen,
            // así que hay que ajustarlo también ahí o volvería al panel viejo.
            ImagePanelController controller = panel.GetComponent<ImagePanelController>();
            if (controller != null)
            {
                SerializedObject serialized = new SerializedObject(controller);
                SetFloat(serialized, "panelHeight", height);
                SetFloat(serialized, "panelMaxWidth", width);
                serialized.ApplyModifiedPropertiesWithoutUndo();
            }

            Debug.Log(
                "[Sonia] Panel de imágenes en " + panel.localPosition.ToString("F2") + ", "
                + width.ToString("F2") + " x " + height.ToString("F2")
                + " m. Con el encuadre de panel ocupa "
                + Mathf.RoundToInt(width / halfWidth * SoniaCapture.Width * 0.5f)
                + " px de ancho, o sea el " + Mathf.RoundToInt(width / (halfWidth * 2f) * 100f)
                + " % de la pantalla; la coronilla queda en y=" + headTopV.ToString("F2") + ".",
                panel);
        }

        /// <summary>
        /// Pie de foto debajo de la imagen, centrado y con ajuste automático de
        /// tamaño para que nunca se salga del ancho del panel.
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

                // El texto se encoge solo hasta caber en la caja: un pie largo
                // reduce la letra en vez de salirse por el borde de la pantalla.
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
        /// Proyecta la cabeza sobre la pantalla y devuelve dónde caen su borde
        /// derecho y su coronilla, en unidades donde 1 es el borde de la imagen.
        /// Solo cuentan las mallas que empiezan a la altura del cuello o por
        /// encima: el cuerpo, con los brazos en cruz, taparía toda la pantalla.
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

            // Se proyecta desde el centro en Z de la caja: usar la cara delantera
            // exagera el ancho de una cabeza casi redonda y el panel se quedaría
            // en nada.
            float depth = Mathf.Max(0.1f, headBounds.center.z - cameraPosition.z);
            rightEdge = headBounds.max.x / (depth * tangent * StandAspect);
            topEdge = (headBounds.max.y - cameraPosition.y) / (depth * tangent);
        }

        // ------------------------------------------------------------------
        // Fondo y luz
        // ------------------------------------------------------------------

        /// <summary>
        /// Pone un telón detrás del avatar con un degradado vertical suave. Sin él
        /// se ve el color plano de la cámara, que queda muerto; con él la silueta
        /// clara de Sonia se recorta contra un fondo oscuro.
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

            // Tiene que tapar la pantalla en los TRES encuadres, y cada uno ve una
            // franja distinta del plano del telón: se cubre la unión de todas.
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
        /// Material sin iluminar del telón. Usa el fondo corporativo si está en el
        /// proyecto y, si no, el degradado navy generado por código.
        /// </summary>
        private static Material LoadOrCreateBackdropMaterial()
        {
            Material material = AssetDatabase.LoadAssetAtPath<Material>(BackdropMaterialPath);
            Texture2D corporate = SoniaBrandAssets.LoadBackgroundTexture();
            Texture2D gradient = corporate != null
                ? corporate
                : AssetDatabase.LoadAssetAtPath<Texture2D>(BackdropTexturePath);

            if (gradient == null)
            {
                EnsureFolder(TextureFolder);

                // Cuatro píxeles de ancho bastan: el degradado solo cambia en vertical.
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

            // El degradado generado por código ya tiene la proporción del telón;
            // el fondo corporativo es 16:9 y hay que recortarlo.
            Vector2 tiling = corporate != null ? BackdropTiling : Vector2.one;
            Vector2 offset = corporate != null ? BackdropOffset : Vector2.zero;
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
        /// Suaviza la luz de la plantilla. Venía a intensidad 2 y muy cenital, que
        /// quemaba la cara y la camiseta blanca.
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
                Debug.LogWarning("[Sonia] No hay luz direccional en la escena.");
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
        /// Baja el bloom y pone un tonemapping neutro. El perfil de la plantilla
        /// trae un bloom alegre que, con una camiseta blanca a plena luz, se come
        /// todo el detalle.
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
        // Cableado
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
                    "[Sonia] No hay CameraFramingController en la escena. "
                    + "Ejecuta Sonia > Actualizar componentes.");
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

        private static void WireAvatarState(
            Transform root,
            Animator animator,
            Transform head,
            SkinnedMeshRenderer face,
            BlendShapeConvention convention)
        {
            AvatarStateController state = root.GetComponentInChildren<AvatarStateController>(true);
            if (state == null)
            {
                Debug.LogWarning("[Sonia] No hay AvatarStateController en la escena.");
                return;
            }

            SerializedObject serialized = new SerializedObject(state);
            SetReference(serialized, "headBone", head);
            SetReference(serialized, "faceRenderer", face);

            if (convention != null)
            {
                Mesh mesh = face != null ? face.sharedMesh : null;
                string left = convention.BlinkLeft;
                string right = convention.BlinkRight;

                // Algunos modelos solo traen un blendshape para los dos ojos.
                if (mesh != null && !HasBlendShape(mesh, left) && HasBlendShape(mesh, convention.BlinkBoth))
                {
                    left = convention.BlinkBoth;
                    right = convention.BlinkBoth;
                }

                SetString(serialized, "blinkLeftBlendShape", left);
                SetString(serialized, "blinkRightBlendShape", right);
            }

            Camera main = Camera.main;
            if (main != null)
            {
                SetReference(serialized, "lookTarget", main.transform);
            }

            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void WireLipSync(
            Transform root,
            SkinnedMeshRenderer face,
            BlendShapeConvention convention)
        {
            LipSyncController lipSync = root.GetComponentInChildren<LipSyncController>(true);
            if (lipSync == null)
            {
                Debug.LogWarning("[Sonia] No hay LipSyncController en la escena.");
                return;
            }

            SerializedObject serialized = new SerializedObject(lipSync);
            SetReference(serialized, "faceRenderer", face);

            if (convention != null)
            {
                SetString(serialized, "jawOpenBlendShape", convention.MouthOpen);
                SetString(serialized, "mouthOpenBlendShape", convention.MouthOpen);

                SerializedProperty bindings = serialized.FindProperty("visemeBindings");
                if (bindings == null || !bindings.isArray)
                {
                    Debug.LogWarning(
                        "[Sonia] No se encontró el array \"visemeBindings\" en LipSyncController; "
                        + "hay que rellenarlo a mano.");
                }
                else
                {
                    int count = convention.Visemes.GetLength(0);
                    bindings.arraySize = count;
                    for (int i = 0; i < count; i++)
                    {
                        SerializedProperty element = bindings.GetArrayElementAtIndex(i);
                        SerializedProperty viseme = element.FindPropertyRelative("viseme");
                        SerializedProperty shape = element.FindPropertyRelative("blendShape");
                        if (viseme != null)
                        {
                            viseme.stringValue = convention.Visemes[i, 0];
                        }

                        if (shape != null)
                        {
                            shape.stringValue = convention.Visemes[i, 1];
                        }
                    }
                }
            }

            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void WireChoreography(Transform root, Animator animator)
        {
            SoniaMotionSet set = SoniaMotionSetBuilder.LoadOrBuildMotionSet();
            AvatarMask mask = SoniaMotionSetBuilder.LoadOrBuildMask();
            SoniaMotionSetBuilder.Wire(root.gameObject, animator, set, mask);
        }

        // ------------------------------------------------------------------
        // Utilidades
        // ------------------------------------------------------------------

        /// <summary>Busca un blendshape aceptando diferencias de mayúsculas.</summary>
        private static bool HasBlendShape(Mesh mesh, string name)
        {
            if (mesh == null || string.IsNullOrEmpty(name))
            {
                return false;
            }

            if (mesh.GetBlendShapeIndex(name) >= 0)
            {
                return true;
            }

            int total = mesh.blendShapeCount;
            for (int i = 0; i < total; i++)
            {
                string candidate = mesh.GetBlendShapeName(i);
                if (string.IsNullOrEmpty(candidate))
                {
                    continue;
                }

                if (string.Equals(candidate, name, System.StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }

                int dot = candidate.LastIndexOf('.');
                if (dot >= 0 && dot + 1 < candidate.Length
                    && string.Equals(
                        candidate.Substring(dot + 1), name, System.StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }
            }

            return false;
        }

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

        private static void SetString(SerializedObject target, string path, string value)
        {
            SerializedProperty property = target.FindProperty(path);
            if (property == null)
            {
                Debug.LogWarning(
                    "[Sonia] El campo \"" + path + "\" no existe en " + target.targetObject.GetType().Name
                    + "; hay que asignarlo a mano en el inspector.");
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
                    "[Sonia] El campo \"" + path + "\" no existe en " + target.targetObject.GetType().Name
                    + "; hay que asignarlo a mano en el inspector.");
                return;
            }

            property.floatValue = value;
        }

        /// <summary>Asigna un enum por el nombre del valor, sin conocer su tipo en tiempo de compilación.</summary>
        private static void SetEnumByName(SerializedObject target, string path, string valueName)
        {
            SerializedProperty property = target.FindProperty(path);
            if (property == null || property.propertyType != SerializedPropertyType.Enum)
            {
                Debug.LogWarning(
                    "[Sonia] El campo \"" + path + "\" no existe o no es un enum en "
                    + target.targetObject.GetType().Name + "; hay que ajustarlo a mano.");
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
                "[Sonia] El enum \"" + path + "\" no tiene el valor \"" + valueName + "\"; se deja como estaba.");
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
