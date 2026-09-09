// Construye un Avatar Humanoid para modelos que llegan sin él.
//
// Los VRM traen su Avatar de UniVRM y los FBX de Mixamo lo generan al
// importarlos como Humanoid, pero los GLB (Ready Player Me y similares) los
// importa glTFast como jerarquía de huesos sin Animator. Sin Avatar Humanoid
// el Animator Controller de Sonia no puede retargetear los clips de Mixamo.
//
// Estos modelos usan el esqueleto de Mixamo (Hips, Spine, Spine1, Spine2,
// Neck, Head, LeftArm, LeftForeArm...), a veces con el prefijo "mixamorig:".
// Aquí se mapean esos nombres a los huesos humanos de Unity, se construye el
// Avatar con AvatarBuilder y se guarda como asset junto al modelo para no
// repetirlo en cada colocación.

#if UNITY_EDITOR

using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Genera y asigna Avatares Humanoid a modelos con esqueleto de Mixamo.</summary>
    public static class SoniaHumanoidRig
    {
        /// <summary>Carpeta donde se guardan los Avatares generados.</summary>
        public const string GeneratedFolder = "Assets/Avatar/Generated";

        /// <summary>Hueso de Mixamo (sin prefijo) -> hueso humano de Unity.</summary>
        private static readonly string[,] MixamoToHuman =
        {
            { "Hips", "Hips" },
            { "Spine", "Spine" },
            { "Spine1", "Chest" },
            { "Spine2", "UpperChest" },
            { "Neck", "Neck" },
            { "Head", "Head" },
            // Los ojos se dejan fuera a propósito: los clips de Mixamo no traen
            // curvas de ojos y el retargeting humanoide los dejaba bizcos. Los
            // mueve la mirada por script (o el módulo de ojos del lip-sync).
            { "LeftShoulder", "LeftShoulder" },
            { "LeftArm", "LeftUpperArm" },
            { "LeftForeArm", "LeftLowerArm" },
            { "LeftHand", "LeftHand" },
            { "RightShoulder", "RightShoulder" },
            { "RightArm", "RightUpperArm" },
            { "RightForeArm", "RightLowerArm" },
            { "RightHand", "RightHand" },
            { "LeftUpLeg", "LeftUpperLeg" },
            { "LeftLeg", "LeftLowerLeg" },
            { "LeftFoot", "LeftFoot" },
            { "LeftToeBase", "LeftToes" },
            { "RightUpLeg", "RightUpperLeg" },
            { "RightLeg", "RightLowerLeg" },
            { "RightFoot", "RightFoot" },
            { "RightToeBase", "RightToes" },
            { "LeftHandThumb1", "Left Thumb Proximal" },
            { "LeftHandThumb2", "Left Thumb Intermediate" },
            { "LeftHandThumb3", "Left Thumb Distal" },
            { "LeftHandIndex1", "Left Index Proximal" },
            { "LeftHandIndex2", "Left Index Intermediate" },
            { "LeftHandIndex3", "Left Index Distal" },
            { "LeftHandMiddle1", "Left Middle Proximal" },
            { "LeftHandMiddle2", "Left Middle Intermediate" },
            { "LeftHandMiddle3", "Left Middle Distal" },
            { "LeftHandRing1", "Left Ring Proximal" },
            { "LeftHandRing2", "Left Ring Intermediate" },
            { "LeftHandRing3", "Left Ring Distal" },
            { "LeftHandPinky1", "Left Little Proximal" },
            { "LeftHandPinky2", "Left Little Intermediate" },
            { "LeftHandPinky3", "Left Little Distal" },
            { "RightHandThumb1", "Right Thumb Proximal" },
            { "RightHandThumb2", "Right Thumb Intermediate" },
            { "RightHandThumb3", "Right Thumb Distal" },
            { "RightHandIndex1", "Right Index Proximal" },
            { "RightHandIndex2", "Right Index Intermediate" },
            { "RightHandIndex3", "Right Index Distal" },
            { "RightHandMiddle1", "Right Middle Proximal" },
            { "RightHandMiddle2", "Right Middle Intermediate" },
            { "RightHandMiddle3", "Right Middle Distal" },
            { "RightHandRing1", "Right Ring Proximal" },
            { "RightHandRing2", "Right Ring Intermediate" },
            { "RightHandRing3", "Right Ring Distal" },
            { "RightHandPinky1", "Right Little Proximal" },
            { "RightHandPinky2", "Right Little Intermediate" },
            { "RightHandPinky3", "Right Little Distal" }
        };

        /// <summary>Huesos sin los que Unity no acepta el Avatar.</summary>
        private static readonly string[] RequiredHuman =
        {
            "Hips", "Spine", "Head",
            "LeftUpperArm", "LeftLowerArm", "LeftHand",
            "RightUpperArm", "RightLowerArm", "RightHand",
            "LeftUpperLeg", "LeftLowerLeg", "LeftFoot",
            "RightUpperLeg", "RightLowerLeg", "RightFoot"
        };

        /// <summary>
        /// Devuelve un Animator Humanoid para la instancia. Si el modelo ya lo
        /// trae (VRM, FBX Humanoid) se devuelve tal cual; si no, se construye un
        /// Avatar a partir de los nombres de hueso de Mixamo, se guarda en
        /// <see cref="GeneratedFolder"/> y se añade un Animator que lo use.
        /// Devuelve null si el esqueleto no se reconoce.
        /// </summary>
        /// <param name="instance">Instancia del modelo en la escena, en T-pose y sin rotar.</param>
        /// <param name="modelAssetPath">Ruta del asset del modelo; da nombre al Avatar generado.</param>
        public static Animator EnsureHumanoidAnimator(GameObject instance, string modelAssetPath)
        {
            if (instance == null)
            {
                return null;
            }

            Animator existing = instance.GetComponentInChildren<Animator>(true);
            if (existing != null && existing.avatar != null && existing.avatar.isHuman)
            {
                return existing;
            }

            string avatarPath = GeneratedFolder + "/"
                + System.IO.Path.GetFileNameWithoutExtension(modelAssetPath) + "_Humanoid.asset";
            Avatar avatar = AssetDatabase.LoadAssetAtPath<Avatar>(avatarPath);
            if (avatar == null || !avatar.isValid || !avatar.isHuman)
            {
                avatar = BuildAndSave(instance, avatarPath);
                if (avatar == null)
                {
                    return null;
                }
            }

            Animator animator = existing != null ? existing : instance.GetComponent<Animator>();
            if (animator == null)
            {
                animator = Undo.AddComponent<Animator>(instance);
            }
            else
            {
                Undo.RecordObject(animator, "Asignar Avatar Humanoid");
            }

            animator.avatar = avatar;
            animator.applyRootMotion = false;
            EditorUtility.SetDirty(animator);
            return animator;
        }

        /// <summary>
        /// Vuelve a construir el Avatar del personaje colocado en la escena (por
        /// ejemplo tras cambiar los límites musculares) y lo reasigna al Animator.
        /// </summary>
        [MenuItem("Sonia/Regenerar Avatar Humanoid")]
        public static void RebuildSceneAvatar()
        {
            GameObject instance = GameObject.Find("Sonia/Avatar");
            Animator animator = instance != null ? instance.GetComponentInChildren<Animator>(true) : null;
            if (animator == null)
            {
                Debug.LogWarning("[Sonia] No hay un avatar con Animator en la escena (Sonia/Avatar).");
                return;
            }

            string modelPath = PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(animator.gameObject);
            if (string.IsNullOrEmpty(modelPath))
            {
                modelPath = animator.avatar != null ? animator.avatar.name.Replace("_Humanoid", "") : instance.name;
            }

            string avatarPath = GeneratedFolder + "/"
                + System.IO.Path.GetFileNameWithoutExtension(modelPath) + "_Humanoid.asset";
            Avatar avatar = BuildAndSave(animator.gameObject, avatarPath);
            if (avatar == null)
            {
                return;
            }

            Undo.RecordObject(animator, "Regenerar Avatar Humanoid");
            animator.avatar = avatar;
            EditorUtility.SetDirty(animator);
            Debug.Log("[Sonia] Avatar Humanoid regenerado y reasignado: " + avatarPath, avatar);
        }

        /// <summary>
        /// Construye el Avatar sobre una copia limpia del modelo en el origen (el
        /// constructor de Unity toma la pose actual como T-pose y la jerarquía
        /// no debe estar rotada) y lo guarda como asset.
        /// </summary>
        private static Avatar BuildAndSave(GameObject instance, string avatarPath)
        {
            GameObject source = PrefabUtility.GetCorrespondingObjectFromSource(instance);
            GameObject temp = Object.Instantiate(source != null ? source : instance);
            temp.name = instance.name;
            temp.hideFlags = HideFlags.HideAndDontSave;
            temp.transform.SetParent(null, false);
            temp.transform.position = Vector3.zero;
            temp.transform.rotation = Quaternion.identity;
            temp.transform.localScale = Vector3.one;

            try
            {
                Animator stray = temp.GetComponent<Animator>();
                if (stray != null)
                {
                    Object.DestroyImmediate(stray);
                }

                HumanDescription description;
                string missing;
                if (!TryBuildDescription(temp, out description, out missing))
                {
                    Debug.LogWarning(
                        "[Sonia] No se pudo construir un Avatar Humanoid para " + instance.name
                        + ": faltan los huesos " + missing + ". Solo se reconoce el esqueleto de Mixamo.");
                    return null;
                }

                Avatar avatar = AvatarBuilder.BuildHumanAvatar(temp, description);
                if (avatar == null || !avatar.isValid || !avatar.isHuman)
                {
                    Debug.LogWarning(
                        "[Sonia] Unity rechazó el Avatar Humanoid de " + instance.name
                        + " (isValid=" + (avatar != null && avatar.isValid) + "). ¿Está el modelo en T-pose?");
                    return null;
                }

                avatar.name = System.IO.Path.GetFileNameWithoutExtension(avatarPath);
                EnsureFolder(GeneratedFolder);
                AssetDatabase.CreateAsset(avatar, avatarPath);
                AssetDatabase.SaveAssets();
                Debug.Log("[Sonia] Avatar Humanoid generado en " + avatarPath + ".", avatar);
                return AssetDatabase.LoadAssetAtPath<Avatar>(avatarPath);
            }
            finally
            {
                Object.DestroyImmediate(temp);
            }
        }

        private static bool TryBuildDescription(
            GameObject root, out HumanDescription description, out string missing)
        {
            Dictionary<string, Transform> byName = new Dictionary<string, Transform>();
            Transform[] all = root.GetComponentsInChildren<Transform>(true);
            for (int i = 0; i < all.Length; i++)
            {
                string bare = StripPrefix(all[i].name);
                if (!byName.ContainsKey(bare))
                {
                    byName[bare] = all[i];
                }
            }

            List<HumanBone> human = new List<HumanBone>();
            HashSet<string> mapped = new HashSet<string>();
            for (int i = 0; i < MixamoToHuman.GetLength(0); i++)
            {
                Transform bone;
                if (!byName.TryGetValue(MixamoToHuman[i, 0], out bone))
                {
                    continue;
                }

                HumanBone entry = new HumanBone();
                entry.humanName = MixamoToHuman[i, 1];
                entry.boneName = bone.name;
                entry.limit = LimitFor(entry.humanName);
                human.Add(entry);
                mapped.Add(entry.humanName);
            }

            List<string> absent = new List<string>();
            for (int i = 0; i < RequiredHuman.Length; i++)
            {
                if (!mapped.Contains(RequiredHuman[i]))
                {
                    absent.Add(RequiredHuman[i]);
                }
            }

            missing = string.Join(", ", absent.ToArray());
            if (absent.Count > 0)
            {
                description = new HumanDescription();
                return false;
            }

            SkeletonBone[] skeleton = new SkeletonBone[all.Length];
            for (int i = 0; i < all.Length; i++)
            {
                skeleton[i].name = all[i].name;
                skeleton[i].position = all[i].localPosition;
                skeleton[i].rotation = all[i].localRotation;
                skeleton[i].scale = all[i].localScale;
            }

            description = new HumanDescription();
            description.human = human.ToArray();
            description.skeleton = skeleton;
            description.armStretch = 0.05f;
            description.legStretch = 0.05f;
            description.upperArmTwist = 0.5f;
            description.lowerArmTwist = 0.5f;
            description.upperLegTwist = 0.5f;
            description.lowerLegTwist = 0.5f;
            description.feetSpacing = 0f;
            description.hasTranslationDoF = false;
            return true;
        }

        /// <summary>
        /// Límites musculares por hueso. Los dedos son el caso importante: la
        /// T-pose de estos modelos ya tiene los dedos rectos, así que cualquier
        /// "estirado" positivo del retargeting es hiperextensión (dedos doblados
        /// hacia atrás, manos en garra en los clips de Mixamo). Aquí se recorta
        /// ese lado a unos pocos grados y se deja el cierre completo; como
        /// Unity reescala el valor normalizado del clip al rango del destino, el
        /// resultado es suave y no un tope brusco.
        /// </summary>
        private static HumanLimit LimitFor(string humanName)
        {
            HumanLimit limit = new HumanLimit();
            limit.useDefaultValues = true;
            bool finger = humanName.Contains("Thumb") || humanName.Contains("Index")
                || humanName.Contains("Middle") || humanName.Contains("Ring") || humanName.Contains("Little");
            if (!finger)
            {
                return limit;
            }

            // Ejes: y = separación (solo proximal), z = estirado.
            limit.useDefaultValues = false;
            limit.center = Vector3.zero;
            if (humanName.Contains("Thumb"))
            {
                // El pulgar sí se extiende de forma natural hacia fuera.
                limit.min = new Vector3(0f, -25f, humanName.Contains("Proximal") ? -20f : -40f);
                limit.max = new Vector3(0f, 25f, 15f);
            }
            else if (humanName.Contains("Proximal"))
            {
                limit.min = new Vector3(0f, -15f, -50f);
                limit.max = new Vector3(0f, 15f, 8f);
            }
            else
            {
                limit.min = new Vector3(0f, 0f, -45f);
                limit.max = new Vector3(0f, 0f, 3f);
            }

            return limit;
        }

        private static string StripPrefix(string name)
        {
            const string prefix = "mixamorig";
            if (name.StartsWith(prefix))
            {
                string rest = name.Substring(prefix.Length);
                if (rest.Length > 0 && (rest[0] == ':' || rest[0] == '_'))
                {
                    return rest.Substring(1);
                }

                // Algunos exportadores dejan "mixamorig9:Hips" o similares.
                int colon = rest.IndexOf(':');
                if (colon >= 0)
                {
                    return rest.Substring(colon + 1);
                }
            }

            return name;
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
    }
}

#endif
