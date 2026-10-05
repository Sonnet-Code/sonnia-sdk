// Monta en la escena del stand la raíz «Invitado» del Modo Jean.
//
// Es la misma pila de Sonia, otra vez, para el avatar de Jean: su voz (frames
// SNGU) con su reproductor y su lip-sync por fonemas (perfil masculino de
// uLipSync), cara, cabeza y ojos, reproductor de clips y coreógrafo (sin bailes
// por su cuenta), presencia para entrar y salir caminando (sin letrero, por la
// izquierda), el cargador de Genies con el rol de invitado y, encima,
// HandshakeRig, ChoreographerBody y GuestPresenter.
//
// La posición de la raíz es la marca del invitado: a la izquierda de Sonia en
// pantalla, a GuestSpacing metros. En modo edición no hay avatar: solo un ancla
// vacía («Avatar», sin malla ni Animator) que dice dónde y de cara a dónde se
// pone. Al entrar en Play, el cargador trae vivo del SDK el avatar de Jean (el
// último set_guest_avatar o el de prueba, JeanGeniesAvatar.json) y AvatarBinder
// lo coloca en el sitio del ancla; hasta entonces, nada se ve. Se puede volver a
// ejecutar: rehace lo que haga falta sin duplicar nada.

#if UNITY_EDITOR

using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Sonia.EditorTools
{
    /// <summary>Menú que monta (o pone al día) el invitado del Modo Jean en la escena del stand.</summary>
    public static class SoniaGuestSetup
    {
        /// <summary>Nombre de la raíz del invitado.</summary>
        public const string RootName = "Invitado";

        /// <summary>
        /// Metros entre Sonia y la marca del invitado (de centro a centro). Los
        /// avatares de Genies tienen el brazo corto (unos 40 cm): más lejos, las
        /// manos no se encuentran.
        /// </summary>
        public const float GuestSpacing = 0.45f;

        private const string AvatarObjectName = "Avatar";
        private const string MaleProfilePath =
            "Packages/com.hecomi.ulipsync/Assets/Profiles/uLipSync-Profile-Sample-Male.asset";

        [MenuItem("Sonia/Montar invitado (Modo Jean)")]
        public static void BuildMenu()
        {
            GameObject root = Build(true);
            if (root != null)
            {
                Selection.activeGameObject = root;
            }
        }

        /// <summary>Monta o pone al día la raíz «Invitado». Devuelve la raíz, o null si no se pudo.</summary>
        public static GameObject Build(bool interactive)
        {
            Scene scene = SceneManager.GetActiveScene();
            SoniaBootstrap sonia = scene.IsValid() ? FindInScene<SoniaBootstrap>(scene) : null;
            if (sonia == null)
            {
                Report(interactive, "Esta escena no tiene a Sonia (SoniaBootstrap). Abre la escena del stand.");
                return null;
            }

            Camera camera = Camera.main;
            CameraFramingController framing = sonia.GetComponentInChildren<CameraFramingController>(true);
            SoniaClient client = sonia.GetComponentInChildren<SoniaClient>(true);

            // La marca: a la izquierda de Sonia en pantalla.
            Vector3 left = camera != null ? -camera.transform.right : Vector3.left;
            left.y = 0f;
            left = left.sqrMagnitude > 0.0001f ? left.normalized : Vector3.left;
            GameObject root = FindRoot(scene);
            if (root == null)
            {
                root = new GameObject(RootName);
                SceneManager.MoveGameObjectToScene(root, scene);
                Undo.RegisterCreatedObjectUndo(root, "Montar invitado");
            }

            root.transform.SetPositionAndRotation(sonia.transform.position + (left * GuestSpacing), sonia.transform.rotation);
            root.transform.localScale = Vector3.one;

            // Voz.
            AudioSource source = Ensure<AudioSource>(root);
            source.playOnAwake = false;
            source.spatialBlend = 0f;
            AudioStreamPlayer player = Ensure<AudioStreamPlayer>(root);
            LipSyncController lipSync = Ensure<LipSyncController>(root);
            AvatarStateController state = Ensure<AvatarStateController>(root);
            FaceRig face = Ensure<FaceRig>(root);
            AvatarBinder binder = Ensure<AvatarBinder>(root);

            // Sin avatar en modo edición: el ancla de donde se pondrá el de Jean.
            Transform anchor = EnsureAnchor(root.transform);

            // El Animator, la cabeza y la cara llegan con el avatar del SDK (AvatarBinder.Bind).
            Animator animator = null;

            // Clips y coreógrafo (el set y la máscara de Sonia).
            SoniaMotionSetBuilder.Wire(
                root, animator, SoniaMotionSetBuilder.LoadOrBuildMotionSet(), SoniaMotionSetBuilder.LoadOrBuildMask());
            AvatarChoreographer choreographer = root.GetComponent<AvatarChoreographer>();
            SerializedObject choreoObject = new SerializedObject(choreographer);
            SetFloat(choreoObject, "danceWeight", 0f);
            SetFloat(choreoObject, "fourthWallWeight", 0f);
            SetFloat(choreoObject, "softWeight", 1f);
            SetFloat(choreoObject, "firstAttentionDelay", 30f);
            SetVector2(choreoObject, "attentionInterval", new Vector2(30f, 60f));
            choreoObject.ApplyModifiedPropertiesWithoutUndo();

            // Cara, cabeza y boca.
            SerializedObject faceObject = new SerializedObject(face);
            SetReference(faceObject, "avatarRoot", null);
            faceObject.ApplyModifiedPropertiesWithoutUndo();

            SerializedObject stateObject = new SerializedObject(state);
            SetReference(stateObject, "headBone", null);
            SetReference(stateObject, "faceRig", face);
            SetReference(stateObject, "lookTarget", camera != null ? camera.transform : null);
            stateObject.ApplyModifiedPropertiesWithoutUndo();

            SerializedObject lipObject = new SerializedObject(lipSync);
            SetReference(lipObject, "faceRig", face);
            SetReference(lipObject, "audioPlayer", player);
            lipObject.ApplyModifiedPropertiesWithoutUndo();

            SoniaSceneSetup.EnsurePhonemeLipSync(root, state);
            uLipSync.uLipSync analyzer = root.GetComponentInChildren<uLipSync.uLipSync>(true);
            uLipSync.Profile male = AssetDatabase.LoadAssetAtPath<uLipSync.Profile>(MaleProfilePath);
            if (analyzer != null && male != null)
            {
                // Jean es un hombre: el perfil de muestra masculino reconoce mejor sus vocales.
                analyzer.profile = male;
                EditorUtility.SetDirty(analyzer);
            }

            SoniaSceneSetup.EnsureEyeGaze(root, state, choreographer, animator);
            SoniaSceneSetup.EnsureFacialExpressions(root, state);

            // El ancla hace de avatar actual: Bind pone el del SDK en su sitio y la apaga.
            SerializedObject binderObject = new SerializedObject(binder);
            SetReference(binderObject, "current", anchor);
            binderObject.ApplyModifiedPropertiesWithoutUndo();

            GeniesAvatarLoader loader = Ensure<GeniesAvatarLoader>(root);
            SerializedObject loaderObject = new SerializedObject(loader);
            SetEnum(loaderObject, "role", (int)AvatarRole.Guest);
            SetReference(loaderObject, "definition", AssetDatabase.LoadAssetAtPath<TextAsset>(SoniaAvatarSetup.GuestDefinitionPath));
            SetReference(loaderObject, "binder", binder);
            SetReference(loaderObject, "client", client);
            loaderObject.ApplyModifiedPropertiesWithoutUndo();

            // Entrar y salir caminando: sin letrero y por la izquierda.
            PresenceController presence = Ensure<PresenceController>(root);
            SerializedObject presenceObject = new SerializedObject(presence);
            SetReference(presenceObject, "choreographer", choreographer);
            SetReference(presenceObject, "motionPlayer", root.GetComponent<MotionPlayer>());
            SetReference(presenceObject, "animator", animator);
            SetReference(presenceObject, "stateController", state);
            SetReference(presenceObject, "cameraFraming", framing);
            SetEnum(presenceObject, "exitSide", (int)ScreenSide.Left);
            SetBool(presenceObject, "useSign", false);
            presenceObject.ApplyModifiedPropertiesWithoutUndo();

            // Cuerpo, mano y secuencia.
            Ensure<ChoreographerBody>(root);
            Ensure<HandshakeRig>(root);
            GuestPresenter presenter = Ensure<GuestPresenter>(root);
            SerializedObject presenterObject = new SerializedObject(presenter);
            SetReference(presenterObject, "sonia", sonia);
            SetReference(presenterObject, "client", client);
            SetReference(presenterObject, "guestPresence", presence);
            SetReference(presenterObject, "guestPlayer", player);
            SetReference(presenterObject, "guestLipSync", lipSync);
            SetReference(presenterObject, "guestState", state);
            SetReference(presenterObject, "guestMotion", root.GetComponent<MotionPlayer>());
            SetReference(presenterObject, "handshake", root.GetComponent<HandshakeRig>());
            presenterObject.ApplyModifiedPropertiesWithoutUndo();

            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
            Debug.Log("[Sonia] Invitado del Modo Jean montado en " + scene.path + ": marca a " + GuestSpacing.ToString("F2")
                      + " m a la izquierda de Sonia, sin avatar en modo edición; en Play se carga del SDK ("
                      + SoniaAvatarSetup.GuestDefinitionPath + " si Jean no tiene uno guardado).", root);
            return root;
        }

        /// <summary>
        /// El ancla «Avatar» bajo la raíz: vacía (sin malla ni Animator), en la
        /// marca y de cara a la cámara. Un avatar que hubiera de un montaje
        /// anterior (el doble) se quita: en modo edición no se ve ninguno.
        /// </summary>
        private static Transform EnsureAnchor(Transform root)
        {
            Transform anchor = root.Find(AvatarObjectName);
            if (anchor != null && (anchor.GetComponentInChildren<Renderer>(true) != null
                                   || anchor.GetComponentInChildren<Animator>(true) != null))
            {
                Undo.DestroyObjectImmediate(anchor.gameObject);
                anchor = null;
            }

            if (anchor == null)
            {
                GameObject empty = new GameObject(AvatarObjectName);
                Undo.RegisterCreatedObjectUndo(empty, "Montar invitado");
                anchor = empty.transform;
                anchor.SetParent(root, false);
            }

            // Los avatares de Genies miran hacia +Z, igual que la cámara: media vuelta.
            anchor.localPosition = Vector3.zero;
            anchor.localRotation = Quaternion.Euler(0f, 180f, 0f);
            anchor.localScale = Vector3.one;
            return anchor;
        }

        // ------------------------------------------------------------------
        // Utilidades
        // ------------------------------------------------------------------

        private static GameObject FindRoot(Scene scene)
        {
            foreach (GameObject candidate in scene.GetRootGameObjects())
            {
                if (candidate.name == RootName)
                {
                    return candidate;
                }
            }

            return null;
        }

        private static T FindInScene<T>(Scene scene) where T : Component
        {
            foreach (GameObject candidate in scene.GetRootGameObjects())
            {
                T found = candidate.GetComponentInChildren<T>(true);
                if (found != null)
                {
                    return found;
                }
            }

            return null;
        }

        private static T Ensure<T>(GameObject target) where T : Component
        {
            T component = target.GetComponent<T>();
            return component != null ? component : Undo.AddComponent<T>(target);
        }

        private static SerializedProperty Property(SerializedObject target, string path)
        {
            SerializedProperty property = target.FindProperty(path);
            if (property == null)
            {
                Debug.LogWarning("[Sonia] El campo «" + path + "» no existe en " + target.targetObject.GetType().Name
                                 + "; hay que ajustarlo a mano en el inspector.");
            }

            return property;
        }

        private static void SetReference(SerializedObject target, string path, Object value)
        {
            SerializedProperty property = Property(target, path);
            if (property != null)
            {
                property.objectReferenceValue = value;
            }
        }

        private static void SetFloat(SerializedObject target, string path, float value)
        {
            SerializedProperty property = Property(target, path);
            if (property != null)
            {
                property.floatValue = value;
            }
        }

        private static void SetBool(SerializedObject target, string path, bool value)
        {
            SerializedProperty property = Property(target, path);
            if (property != null)
            {
                property.boolValue = value;
            }
        }

        private static void SetVector2(SerializedObject target, string path, Vector2 value)
        {
            SerializedProperty property = Property(target, path);
            if (property != null)
            {
                property.vector2Value = value;
            }
        }

        private static void SetEnum(SerializedObject target, string path, int value)
        {
            SerializedProperty property = Property(target, path);
            if (property != null)
            {
                property.enumValueIndex = value;
            }
        }

        private static void Report(bool interactive, string message)
        {
            if (interactive)
            {
                EditorUtility.DisplayDialog("Sonia", message, "Vale");
            }
            else
            {
                Debug.LogWarning("[Sonia] Montar invitado: " + message);
            }
        }
    }
}

#endif
