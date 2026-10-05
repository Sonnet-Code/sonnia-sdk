// Genera el set de animaciones del avatar desde el catálogo.
//
// "Sonia > Crear set de animaciones" hace tres cosas, en orden:
//   1. Configura cada clip de las carpetas de SoniaAnimations.ClipFolders: en
//      bucle solo si es un bucle base, con la rotación y la altura de la raíz
//      dentro de la pose y el avance XZ fuera (centro de masas), salvo en los
//      reposos, que lo llevan dentro (es su traspaso de peso). Los .anim (los
//      oficiales de Genies) se ajustan en sus propios ajustes de clip; los FBX,
//      en el importador (Humanoid, sin compresión de fotogramas, que aplana
//      dedos y muñecas).
//   2. Rellena el asset SoniaMotionSet con los clips que nombra SoniaAnimations.
//   3. Genera la máscara de torso y deja MotionPlayer y AvatarChoreographer de
//      la escena apuntando a todo ello.
//
// Es idempotente: se puede ejecutar cuantas veces haga falta.

#if UNITY_EDITOR

using System.Collections.Generic;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Sonia.EditorTools
{
    /// <summary>Construye <c>Assets/Animations/SoniaMotionSet.asset</c> y lo cablea en la escena.</summary>
    public static class SoniaMotionSetBuilder
    {
        [MenuItem("Sonia/Crear set de animaciones")]
        public static void CreateMotionSetMenu()
        {
            ConfigureClips();
            SoniaMotionSet set = BuildMotionSet();
            AvatarMask mask = BuildUpperBodyMask();
            AssignToScene(set, mask);
            Selection.activeObject = set;
            EditorGUIUtility.PingObject(set);
        }

        // ------------------------------------------------------------------
        // Importación de los FBX
        // ------------------------------------------------------------------

        /// <summary>Configura todos los FBX de las carpetas de clips. Devuelve cuántos reimportó.</summary>
        public static int ConfigureClips()
        {
            int changed = 0;
            int total = 0;
            for (int f = 0; f < SoniaAnimations.ClipFolders.Length; f++)
            {
                string folder = SoniaAnimations.ClipFolders[f];
                if (!AssetDatabase.IsValidFolder(folder))
                {
                    continue;
                }

                string[] guids = AssetDatabase.FindAssets("t:Model", new[] { folder });
                total += guids.Length;
                for (int i = 0; i < guids.Length; i++)
                {
                    if (ConfigureClip(AssetDatabase.GUIDToAssetPath(guids[i])))
                    {
                        changed++;
                    }
                }
            }

            for (int f = 0; f < SoniaAnimations.ClipFolders.Length; f++)
            {
                string folder = SoniaAnimations.ClipFolders[f];
                if (!AssetDatabase.IsValidFolder(folder))
                {
                    continue;
                }

                string[] guids = AssetDatabase.FindAssets("t:AnimationClip", new[] { folder });
                for (int i = 0; i < guids.Length; i++)
                {
                    string path = AssetDatabase.GUIDToAssetPath(guids[i]);
                    if (!path.EndsWith(".anim"))
                    {
                        continue;
                    }

                    total++;
                    if (ConfigureAnimAsset(path))
                    {
                        changed++;
                    }
                }
            }

            Debug.Log("[Sonia] Clips configurados: " + changed + " de " + total + " cambiados.");
            return changed;
        }

        /// <summary>
        /// Configura un clip .anim con los mismos criterios que los FBX: bucle
        /// solo en los bucles base, rotación y altura de la raíz dentro de la pose
        /// y avance XZ fuera de ella. Devuelve verdadero si hubo que cambiarlo.
        /// </summary>
        public static bool ConfigureAnimAsset(string path)
        {
            AnimationClip clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(path);
            if (clip == null)
            {
                return false;
            }

            bool loop = SoniaAnimations.IsLoopingClip(clip.name);
            AnimationClipSettings settings = AnimationUtility.GetAnimationClipSettings(clip);
            bool touched = false;
            if (settings.loopTime != loop)
            {
                settings.loopTime = loop;
                touched = true;
            }

            if (!settings.loopBlendOrientation || !settings.keepOriginalOrientation)
            {
                settings.loopBlendOrientation = true;
                settings.keepOriginalOrientation = true;
                touched = true;
            }

            if (!settings.loopBlendPositionY || !settings.keepOriginalPositionY)
            {
                settings.loopBlendPositionY = true;
                settings.keepOriginalPositionY = true;
                touched = true;
            }

            // Avance XZ fuera de la pose (centro de masas), salvo en los reposos:
            // ahí ese avance es el traspaso de peso (ver KeepsHorizontalMotionInPose).
            bool keepXZ = SoniaAnimations.KeepsHorizontalMotionInPose(clip.name);
            if (settings.loopBlendPositionXZ != keepXZ || settings.keepOriginalPositionXZ)
            {
                settings.loopBlendPositionXZ = keepXZ;
                settings.keepOriginalPositionXZ = false;
                touched = true;
            }

            // Los clips de Genies traen eventos para su controlador de tercera
            // persona (OnFootstep en la caminata). Aquí nadie los recibe y cada
            // uno sería un error en la consola: fuera.
            if (AnimationUtility.GetAnimationEvents(clip).Length > 0)
            {
                AnimationUtility.SetAnimationEvents(clip, new AnimationEvent[0]);
                touched = true;
            }

            if (!touched)
            {
                return false;
            }

            AnimationUtility.SetAnimationClipSettings(clip, settings);
            EditorUtility.SetDirty(clip);
            AssetDatabase.SaveAssetIfDirty(clip);
            return true;
        }

        /// <summary>Configura un FBX. Devuelve verdadero si hubo que reimportarlo.</summary>
        public static bool ConfigureClip(string path)
        {
            ModelImporter importer = AssetImporter.GetAtPath(path) as ModelImporter;
            if (importer == null)
            {
                return false;
            }

            string clipName = System.IO.Path.GetFileNameWithoutExtension(path);
            bool touched = false;

            if (importer.animationType != ModelImporterAnimationType.Human)
            {
                importer.animationType = ModelImporterAnimationType.Human;
                importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
                touched = true;
            }

            if (!importer.importAnimation)
            {
                importer.importAnimation = true;
                touched = true;
            }

            if (importer.animationCompression != ModelImporterAnimationCompression.Off)
            {
                importer.animationCompression = ModelImporterAnimationCompression.Off;
                touched = true;
            }

            // Los FBX de animación no necesitan malla ni materiales.
            if (importer.materialImportMode != ModelImporterMaterialImportMode.None)
            {
                importer.materialImportMode = ModelImporterMaterialImportMode.None;
                touched = true;
            }

            ModelImporterClipAnimation[] clips = importer.clipAnimations;
            if (clips == null || clips.Length == 0)
            {
                clips = importer.defaultClipAnimations;
                touched = clips.Length > 0 || touched;
            }

            bool loop = SoniaAnimations.IsLoopingClip(clipName);
            for (int c = 0; c < clips.Length; c++)
            {
                ModelImporterClipAnimation clip = clips[c];
                if (clips.Length == 1 && clip.name != clipName)
                {
                    clip.name = clipName;
                    touched = true;
                }

                if (clip.loopTime != loop || clip.loopPose != loop)
                {
                    clip.loopTime = loop;
                    clip.loopPose = loop;
                    touched = true;
                }

                if (!clip.lockRootRotation || !clip.keepOriginalOrientation)
                {
                    clip.lockRootRotation = true;
                    clip.keepOriginalOrientation = true;
                    touched = true;
                }

                if (!clip.lockRootHeightY || !clip.keepOriginalPositionY)
                {
                    clip.lockRootHeightY = true;
                    clip.keepOriginalPositionY = true;
                    touched = true;
                }

                // Center of Mass: el desplazamiento del clip se extrae como root
                // motion y, con applyRootMotion apagado, se descarta. Sonia se
                // queda en el sitio. Los reposos lo dejan en la pose: es su
                // traspaso de peso (ver KeepsHorizontalMotionInPose).
                bool keepXZ = SoniaAnimations.KeepsHorizontalMotionInPose(clipName);
                if (clip.keepOriginalPositionXZ || clip.lockRootPositionXZ != keepXZ)
                {
                    clip.keepOriginalPositionXZ = false;
                    clip.lockRootPositionXZ = keepXZ;
                    touched = true;
                }
            }

            if (!touched)
            {
                return false;
            }

            importer.clipAnimations = clips;
            importer.SaveAndReimport();
            return true;
        }

        // ------------------------------------------------------------------
        // Set de clips
        // ------------------------------------------------------------------

        /// <summary>Crea o actualiza el asset del set con los clips del catálogo.</summary>
        public static SoniaMotionSet BuildMotionSet()
        {
            SoniaMotionSet set = AssetDatabase.LoadAssetAtPath<SoniaMotionSet>(SoniaAnimations.MotionSetPath);
            if (set == null)
            {
                set = ScriptableObject.CreateInstance<SoniaMotionSet>();
                EnsureFolder(System.IO.Path.GetDirectoryName(SoniaAnimations.MotionSetPath).Replace('\\', '/'));
                AssetDatabase.CreateAsset(set, SoniaAnimations.MotionSetPath);
            }

            List<string> missing = new List<string>();

            set.idleLoop = LoadClip(SoniaAnimations.IdleLoopClip, missing);
            set.idleVariations = LoadClips(SoniaAnimations.IdleVariationClips, missing);
            set.listeningLoop = LoadClip(SoniaAnimations.ListeningLoopClip, missing);
            set.nods = LoadClips(SoniaAnimations.NodClips, missing);
            set.thinkingLoop = LoadClip(SoniaAnimations.ThinkingLoopClip, missing);
            set.thinkingVariations = LoadClips(SoniaAnimations.ThinkingVariationClips, missing);
            set.talking = LoadClips(SoniaAnimations.TalkingClips, missing);
            set.greeting = LoadClip(SoniaAnimations.GreetingClip, missing);
            set.present = LoadClip(SoniaAnimations.PresentClip, missing);
            set.walk = LoadClip(SoniaAnimations.WalkClip, missing);

            List<AttentionMotion> attention = new List<AttentionMotion>();
            for (int i = 0; i < SoniaAnimations.AttentionClips.Length; i++)
            {
                AttentionClip entry = SoniaAnimations.AttentionClips[i];
                AnimationClip clip = LoadClip(entry.Name, missing);
                if (clip != null)
                {
                    attention.Add(new AttentionMotion { clip = clip, category = entry.Category });
                }
            }

            set.attention = attention.ToArray();

            EditorUtility.SetDirty(set);
            AssetDatabase.SaveAssets();

            Debug.Log(
                "[Sonia] Set de animaciones en " + SoniaAnimations.MotionSetPath + ": "
                + set.idleVariations.Length + " variaciones de reposo, " + set.talking.Length
                + " de habla, " + set.nods.Length + " asentimientos, " + set.attention.Length
                + " de atención, caminar " + (set.walk != null ? set.walk.name : "(falta)")
                + (missing.Count > 0 ? ". Sin encontrar: " + string.Join(", ", missing.ToArray()) : ".") ,
                set);

            return set;
        }

        private static AnimationClip[] LoadClips(string[] names, List<string> missing)
        {
            List<AnimationClip> clips = new List<AnimationClip>();
            for (int i = 0; i < names.Length; i++)
            {
                AnimationClip clip = LoadClip(names[i], missing);
                if (clip != null)
                {
                    clips.Add(clip);
                }
            }

            return clips.ToArray();
        }

        private static AnimationClip LoadClip(string name, List<string> missing)
        {
            // Un nombre vacío es un hueco a propósito (Genies no publica ese clip).
            if (string.IsNullOrEmpty(name))
            {
                return null;
            }

            for (int f = 0; f < SoniaAnimations.ClipFolders.Length; f++)
            {
                AnimationClip anim = AssetDatabase.LoadAssetAtPath<AnimationClip>(SoniaAnimations.ClipFolders[f] + "/" + name + ".anim");
                if (anim != null)
                {
                    return anim;
                }

                string path = SoniaAnimations.ClipFolders[f] + "/" + name + ".fbx";
                Object[] assets = AssetDatabase.LoadAllAssetRepresentationsAtPath(path);
                AnimationClip fallback = null;
                for (int i = 0; i < assets.Length; i++)
                {
                    AnimationClip clip = assets[i] as AnimationClip;
                    if (clip == null || clip.name.StartsWith("__preview__"))
                    {
                        continue;
                    }

                    if (clip.name == name)
                    {
                        return clip;
                    }

                    if (fallback == null)
                    {
                        fallback = clip;
                    }
                }

                if (fallback != null)
                {
                    return fallback;
                }
            }

            missing.Add(name);
            return null;
        }

        // ------------------------------------------------------------------
        // Máscara y escena
        // ------------------------------------------------------------------

        /// <summary>Crea o actualiza la máscara de torso.</summary>
        public static AvatarMask BuildUpperBodyMask()
        {
            AvatarMask mask = AssetDatabase.LoadAssetAtPath<AvatarMask>(SoniaAnimations.UpperBodyMaskPath);
            AvatarMask fresh = MotionPlayer.CreateUpperBodyMask();
            if (mask == null)
            {
                AssetDatabase.CreateAsset(fresh, SoniaAnimations.UpperBodyMaskPath);
                mask = fresh;
            }
            else
            {
                for (int i = 0; i < (int)AvatarMaskBodyPart.LastBodyPart; i++)
                {
                    AvatarMaskBodyPart part = (AvatarMaskBodyPart)i;
                    mask.SetHumanoidBodyPartActive(part, fresh.GetHumanoidBodyPartActive(part));
                }

                EditorUtility.SetDirty(mask);
                Object.DestroyImmediate(fresh);
            }

            AssetDatabase.SaveAssets();
            return mask;
        }

        /// <summary>
        /// Deja MotionPlayer y AvatarChoreographer en el objeto Sonia de la escena
        /// abierta, apuntando al Animator del avatar, al set y a la máscara.
        /// </summary>
        public static void AssignToScene(SoniaMotionSet set, AvatarMask mask)
        {
            Scene scene = SceneManager.GetActiveScene();
            if (!scene.IsValid() || !scene.isLoaded)
            {
                return;
            }

            SoniaBootstrap bootstrap = null;
            GameObject[] roots = scene.GetRootGameObjects();
            for (int i = 0; i < roots.Length && bootstrap == null; i++)
            {
                bootstrap = roots[i].GetComponentInChildren<SoniaBootstrap>(true);
            }

            if (bootstrap == null)
            {
                return;
            }

            GameObject root = bootstrap.gameObject;
            Animator animator = root.GetComponentInChildren<Animator>(true);
            Wire(root, animator, set, mask);
            EditorSceneManager.MarkSceneDirty(scene);
        }

        /// <summary>Añade (si faltan) y cablea los componentes de animación en el objeto raíz.</summary>
        public static void Wire(GameObject root, Animator animator, SoniaMotionSet set, AvatarMask mask)
        {
            MotionPlayer player = root.GetComponent<MotionPlayer>();
            if (player == null)
            {
                player = Undo.AddComponent<MotionPlayer>(root);
            }

            AvatarChoreographer choreographer = root.GetComponent<AvatarChoreographer>();
            if (choreographer == null)
            {
                choreographer = Undo.AddComponent<AvatarChoreographer>(root);
            }

            SerializedObject playerObject = new SerializedObject(player);
            playerObject.FindProperty("animator").objectReferenceValue = animator;
            playerObject.FindProperty("upperBodyMask").objectReferenceValue = mask;
            playerObject.ApplyModifiedPropertiesWithoutUndo();

            SerializedObject choreoObject = new SerializedObject(choreographer);
            choreoObject.FindProperty("motionPlayer").objectReferenceValue = player;
            choreoObject.FindProperty("motionSet").objectReferenceValue = set;
            choreoObject.ApplyModifiedPropertiesWithoutUndo();

            if (animator != null)
            {
                Undo.RecordObject(animator, "Configurar Animator de Sonia");
                animator.runtimeAnimatorController = null;
                animator.applyRootMotion = false;
                animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
                EditorUtility.SetDirty(animator);
            }
        }

        /// <summary>Set ya generado, o lo genera si no existe.</summary>
        public static SoniaMotionSet LoadOrBuildMotionSet()
        {
            SoniaMotionSet set = AssetDatabase.LoadAssetAtPath<SoniaMotionSet>(SoniaAnimations.MotionSetPath);
            if (set == null)
            {
                ConfigureClips();
                set = BuildMotionSet();
            }

            return set;
        }

        /// <summary>Máscara ya generada, o la genera si no existe.</summary>
        public static AvatarMask LoadOrBuildMask()
        {
            AvatarMask mask = AssetDatabase.LoadAssetAtPath<AvatarMask>(SoniaAnimations.UpperBodyMaskPath);
            return mask != null ? mask : BuildUpperBodyMask();
        }

        private static void EnsureFolder(string folder)
        {
            if (string.IsNullOrEmpty(folder) || AssetDatabase.IsValidFolder(folder))
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
