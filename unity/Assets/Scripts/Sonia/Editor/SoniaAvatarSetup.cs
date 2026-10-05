// Deja en la escena el sitio del avatar de Sonia, lo cablea y ajusta el encuadre del stand.
//
// Sonia usa avatares de Genies, que el SDK solo monta en Play, así que en modo
// edición no se ve ningún avatar. La escena guarda bajo el objeto Sonia un ancla
// vacía («Avatar», sin malla ni Animator) que dice dónde y de cara a dónde va;
// al entrar en Play GeniesAvatarLoader carga el avatar del SDK y AvatarBinder lo
// pone en el sitio del ancla. Fuera de la jerarquía de Sonia queda desactivado
// el doble Sticker, del Genies Avatar Starter Pack (mismo esqueleto y misma cara
// FACS): solo se enseña si el SDK no entrega ningún avatar, y sirve para medir
// el encuadre con Sonia > Recalcular encuadre (con el doble).
//
// Un par de cosas que no son obvias:
//
//  * Los avatares de Genies miran hacia +Z, y la cámara del stand está en Z
//    negativo mirando hacia +Z, así que el ancla se gira 180 grados en Y.
//  * El doble va fuera de la jerarquía de Sonia a propósito: varios componentes
//    buscan un Animator o mallas entre sus hijos si no tienen uno asignado, y
//    no deben quedarse con el doble apagado.
//  * El Humanoid de Sticker se alinea con el de los avatares del SDK: cabeza en
//    el hueso Head (Genies lo mapeó a Face) y ojos fuera del Humanoid, porque
//    la mirada mueve los globos (LeftEye, RightEye) y no las cuencas, que
//    arrastran las pestañas.
//  * La cara la escribe FaceRig (en el objeto Sonia): traduce los canales del
//    lip-sync, el parpadeo y las expresiones a las formas FACS de Genies.
//  * El encuadre del stand es un plano medio en vertical 9:16: de un poco por
//    debajo de las caderas a justo por encima de la cabeza, con muy poco aire.
//    Se calcula con los huesos reales del avatar, no con los bounds de los
//    renderers, porque los accesorios los ensanchan y estropean el cálculo.

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
        /// <summary>Doble del avatar del SDK: respaldo si el SDK no entrega el avatar y medida del encuadre.</summary>
        public const string StandInAvatarPath = "Assets/Avatar/Genies/Sticker/Sticker.fbx";

        /// <summary>Definición (JSON del SDK de Genies) del avatar que se carga en Play.</summary>
        public const string GeniesDefinitionPath = "Assets/Sonia/Avatar/SoniaGeniesAvatar.json";

        /// <summary>Avatar de prueba de Jean (invitado del Modo Jean) mientras no guarde el suyo en el editor.</summary>
        public const string GuestDefinitionPath = "Assets/Sonia/Avatar/JeanGeniesAvatar.json";

        /// <summary>Ancla vacía bajo Sonia: donde AvatarBinder pone el avatar del SDK.</summary>
        private const string AvatarObjectName = "Avatar";

        /// <summary>Objeto raíz con el doble Sticker, desactivado.</summary>
        public const string StandInObjectName = "Sonia (doble)";
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
        /// manda, no el alto: con los gestos más abiertos los brazos llegaron a
        /// 1,49 m de punta a punta, así que con 1,55 sobra un poco.
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

        /// <summary>Metros de aire por encima de la cabeza en el encuadre.</summary>
        public static float TopMargin
        {
            get { return EditorPrefs.GetFloat(TopMarginKey, DefaultTopMargin); }
            set { EditorPrefs.SetFloat(TopMarginKey, value); }
        }

        // ------------------------------------------------------------------
        // Menús
        // ------------------------------------------------------------------

        [MenuItem("Sonia/Colocar avatar")]
        public static void PlaceAvatarMenu()
        {
            PlaceAvatar(true);
        }

        [MenuItem("Sonia/Recalcular encuadre (con el doble)")]
        public static void ReframeMenu()
        {
            Reframe(true);
        }

        /// <summary>
        /// Deja el sitio del avatar en la escena activa y lo cablea, sin ningún
        /// avatar a la vista: bajo el objeto "Sonia", el ancla vacía «Avatar»
        /// (donde AvatarBinder pondrá en Play el avatar del SDK) y, fuera de su
        /// jerarquía, el doble Sticker desactivado (último recurso del cargador).
        /// No toca la cámara, el panel ni la luz: eso lo hace <see cref="Reframe"/>.
        /// Guarda la escena. Con <paramref name="interactive"/> en falso no abre
        /// diálogos. Devuelve el ancla, o null si no se pudo.
        /// </summary>
        public static Transform PlaceAvatar(bool interactive = true)
        {
            Scene scene = SceneManager.GetActiveScene();
            if (!scene.IsValid() || !scene.isLoaded)
            {
                Report(interactive, "No hay ninguna escena abierta.");
                return null;
            }

            SoniaBootstrap bootstrap = FindInScene<SoniaBootstrap>(scene);
            Transform root = bootstrap != null ? bootstrap.transform : FindRootByName(scene);
            if (root == null)
            {
                Report(interactive, "No hay ningún objeto \"" + RootName + "\" en la escena " + scene.name
                                    + ". Ejecuta antes Sonia > Crear escena base.");
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

            GameObject anchorObject = new GameObject(AvatarObjectName);
            Undo.RegisterCreatedObjectUndo(anchorObject, UndoName);
            Transform anchor = anchorObject.transform;
            anchor.SetParent(root, false);
            anchor.localPosition = Vector3.zero;

            // Los avatares de Genies miran hacia +Z; la cámara también, así que hay
            // que darle media vuelta para que quede de frente.
            anchor.localRotation = Quaternion.Euler(0f, 180f, 0f);
            anchor.localScale = Vector3.one;

            Transform standIn = PlaceStandIn(scene, anchor);

            // Sin avatar hasta Play: el Animator, la cabeza, los ojos y la cara los
            // engancha AvatarBinder.Bind cuando llega el del SDK.
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
                "[Sonia] Sitio del avatar listo: ancla «" + AvatarObjectName + "» (en Play se pone ahí el avatar del SDK)"
                + (standIn != null ? " y doble «" + StandInObjectName + "» desactivado" : ", sin doble")
                + ". La cámara, el panel y la luz no se tocan.",
                anchorObject);
            return anchor;
        }

        /// <summary>
        /// Recalcula el encuadre del stand (cámara, planos abierto y de panel,
        /// panel de imágenes, telón y luz) con las medidas del doble, que se
        /// enciende solo mientras se mide. El encuadre guardado se ajustó con el
        /// avatar del SDK, y el doble tiene otras medidas: el plano cambia un poco.
        /// Guarda la escena. Devuelve si se pudo.
        /// </summary>
        public static bool Reframe(bool interactive = true)
        {
            Scene scene = SceneManager.GetActiveScene();
            SoniaBootstrap bootstrap = scene.IsValid() ? FindInScene<SoniaBootstrap>(scene) : null;
            Transform root = bootstrap != null ? bootstrap.transform : (scene.IsValid() ? FindRootByName(scene) : null);
            GameObject standIn = root != null ? FindRootObject(scene, StandInObjectName) : null;
            if (root == null || standIn == null)
            {
                Report(interactive, "No hay doble con el que medir. Ejecuta antes Sonia > Colocar avatar en la escena del stand.");
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
                    "[Sonia] Encuadre recalculado con el doble: caderas y=" + hipsY.ToString("F2")
                    + ", hombros y=" + shouldersY.ToString("F2") + ", alto de cabeza y=" + headTop.ToString("F2") + ".",
                    camera);
            }
            finally
            {
                standIn.SetActive(wasActive);
            }

            Undo.SetCurrentGroupName("Recalcular encuadre de Sonia");
            Undo.CollapseUndoOperations(undoGroup);
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
            return true;
        }

        /// <summary>
        /// El doble Sticker, desactivado y fuera de la jerarquía de Sonia, en el
        /// sitio del ancla. Null si falta el FBX (entonces no hay respaldo).
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
                Debug.LogWarning("[Sonia] No se encontró el doble " + StandInAvatarPath + " (Genies Avatar Starter Pack, "
                                 + "ver Assets/Avatar/Genies/LICENSE.md): si el SDK no entrega el avatar, no habrá respaldo.");
                return null;
            }

            GameObject standIn = (GameObject)PrefabUtility.InstantiatePrefab(prefab, scene);
            if (standIn == null)
            {
                Debug.LogError("[Sonia] No se pudo instanciar " + StandInAvatarPath + ".");
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

        /// <summary>Deja FaceRig en el objeto Sonia apuntando al avatar.</summary>
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
        /// Deja en el objeto Sonia el AvatarBinder (con el ancla como avatar
        /// actual) y el cargador del SDK de Genies con la definición del repo y el
        /// doble de último recurso.
        /// </summary>
        private static void WireAvatarLoading(Transform root, Transform anchor, Transform standIn)
        {
            AvatarBinder binder = root.GetComponent<AvatarBinder>();
            if (binder == null)
            {
                binder = Undo.AddComponent<AvatarBinder>(root.gameObject);
            }

            SerializedObject binderObject = new SerializedObject(binder);
            SetReference(binderObject, "current", anchor);
            binderObject.ApplyModifiedPropertiesWithoutUndo();

            GeniesAvatarLoader loader = root.GetComponent<GeniesAvatarLoader>();
            if (loader == null)
            {
                loader = Undo.AddComponent<GeniesAvatarLoader>(root.gameObject);
            }

            TextAsset definition = AssetDatabase.LoadAssetAtPath<TextAsset>(GeniesDefinitionPath);
            if (definition == null)
            {
                Debug.LogWarning("[Sonia] No se encontró " + GeniesDefinitionPath + ": en Play no habrá avatar hasta que llegue set_avatar.");
            }

            SerializedObject loaderObject = new SerializedObject(loader);
            SetReference(loaderObject, "definition", definition);
            SetReference(loaderObject, "binder", binder);
            SetReference(loaderObject, "client", root.GetComponentInChildren<SoniaClient>(true));
            SetReference(loaderObject, "standIn", standIn);
            loaderObject.ApplyModifiedPropertiesWithoutUndo();
        }

        /// <summary>Un problema de Colocar avatar: diálogo si lo pidió alguien en el menú; si no, a la consola.</summary>
        private static void Report(bool interactive, string message)
        {
            if (interactive)
            {
                EditorUtility.DisplayDialog("Sonia", message, "Vale");
            }
            else
            {
                Debug.LogWarning("[Sonia] Colocar avatar: " + message);
            }
        }

        private static void WireAvatarState(Transform root, Transform head, FaceRig faceRig)
        {
            AvatarStateController state = root.GetComponentInChildren<AvatarStateController>(true);
            if (state == null)
            {
                Debug.LogWarning("[Sonia] No hay AvatarStateController en la escena.");
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
                Debug.LogWarning("[Sonia] No hay LipSyncController en la escena.");
                return;
            }

            SerializedObject serialized = new SerializedObject(lipSync);
            SetReference(serialized, "faceRig", faceRig);
            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        /// <summary>
        /// Deja el Humanoid de un FBX de Genies como el de los avatares del SDK:
        /// cabeza en el hueso Head y sin ojos ni mandíbula. Solo reimporta si hace falta.
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
            Debug.Log("[Sonia] Humanoid de " + System.IO.Path.GetFileName(assetPath)
                      + " alineado con el de los avatares del SDK (cabeza en Head, sin ojos ni mandíbula).");
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
