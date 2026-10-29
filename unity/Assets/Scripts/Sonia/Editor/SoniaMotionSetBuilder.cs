// Builds the avatar's motion set from the catalog.
//
// "Sonnia > Create Motion Set" does, in order:
//   0. Generates the own idle loop (SonniaIdle) if missing and, only with the
//      Genies Avatar SDK installed, copies the SDK's common animations
//      (DefaultIdle and Walk) to SoniaAnimations.SdkClipFolder
//      (Assets/Animations/GeniesSdk), which is not committed to the repo.
//   1. Configures each clip in the SoniaAnimations.ClipFolders folders: looping
//      only if it is a base loop, with root rotation and height baked into the
//      pose and XZ travel left out (center of mass), except for idles, which
//      keep it in (it is their weight shift). The .anim files (the
//      redistributable Genies clips) are adjusted in their own clip settings;
//      FBX files in the importer (Humanoid, no keyframe compression, which
//      flattens fingers and wrists).
//   2. Fills the SoniaMotionSet asset with the clips named in SoniaAnimations.
//   3. Generates the torso mask and points the scene's MotionPlayer and
//      AvatarChoreographer at all of it.
//
// It is idempotent: it can be run as many times as needed.

#if UNITY_EDITOR

using System.Collections.Generic;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Sonia.EditorTools
{
    /// <summary>Builds <c>Assets/Animations/SoniaMotionSet.asset</c> and wires it into the scene.</summary>
    public static class SoniaMotionSetBuilder
    {
        [MenuItem("Sonnia/Create Motion Set")]
        public static void CreateMotionSetMenu()
        {
            CopySdkClips();
            GenerateIdleClip(false);
            ConfigureClips();
            SoniaMotionSet set = BuildMotionSet();
            AvatarMask mask = BuildUpperBodyMask();
            AssignToScene(set, mask);
            Selection.activeObject = set;
            EditorGUIUtility.PingObject(set);
        }

        // ------------------------------------------------------------------
        // FBX import
        // ------------------------------------------------------------------

        /// <summary>Configures all FBX files in the clip folders. Returns how many it reimported.</summary>
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

            Debug.Log("[Sonnia] Clips configured: " + changed + " of " + total + " changed.");
            return changed;
        }

        /// <summary>
        /// Configures a .anim clip with the same criteria as the FBX files: loop
        /// only in the base loops, root rotation and height baked into the pose
        /// and XZ travel left out of it. Returns true if it had to be changed.
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

            // XZ travel outside the pose (center of mass), except in idles:
            // there that travel is the weight shift (see KeepsHorizontalMotionInPose).
            bool keepXZ = SoniaAnimations.KeepsHorizontalMotionInPose(clip.name);
            if (settings.loopBlendPositionXZ != keepXZ || settings.keepOriginalPositionXZ)
            {
                settings.loopBlendPositionXZ = keepXZ;
                settings.keepOriginalPositionXZ = false;
                touched = true;
            }

            // Genies clips carry events for their third-person controller
            // (OnFootstep in the walk). Nobody receives them here and each one
            // would be a console error: remove them.
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

        /// <summary>Configures an FBX. Returns true if it had to be reimported.</summary>
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

            // Animation FBX files do not need a mesh or materials.
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

                // Center of Mass: the clip's displacement is extracted as root
                // motion and, with applyRootMotion off, discarded. Sonnia stays
                // in place. Idles leave it in the pose: it is their weight
                // shift (see KeepsHorizontalMotionInPose).
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
        // Clip set
        // ------------------------------------------------------------------

        /// <summary>Creates or updates the set asset with the catalog clips.</summary>
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

            set.idleLoop = LoadFirstClip(SoniaAnimations.IdleLoopClips, missing);
            set.idleVariations = LoadClips(SoniaAnimations.IdleVariationClips, missing);
            set.listeningLoop = LoadFirstClip(SoniaAnimations.ListeningLoopClips, missing);
            set.nods = LoadClips(SoniaAnimations.NodClips, missing);
            set.thinkingLoop = LoadFirstClip(SoniaAnimations.ThinkingLoopClips, missing);
            set.thinkingVariations = LoadClips(SoniaAnimations.ThinkingVariationClips, missing);
            set.talking = LoadClips(SoniaAnimations.TalkingClips, missing);
            set.greeting = LoadClip(SoniaAnimations.GreetingClip, missing);
            set.present = LoadClip(SoniaAnimations.PresentClip, missing);
            // Only with the Genies SDK: without it nothing is missing, Sonnia just slides away.
            set.walk = LoadClip(SoniaAnimations.WalkClip, new List<string>());

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
            set.trivia = LoadClips(SoniaAnimations.TriviaClips, missing);

            EditorUtility.SetDirty(set);
            AssetDatabase.SaveAssets();

            Debug.Log(
                "[Sonnia] Motion set at " + SoniaAnimations.MotionSetPath + ": "
                + set.idleVariations.Length + " idle variations, " + set.talking.Length
                + " talking, " + set.nods.Length + " nods, " + set.attention.Length
                + " attention, " + set.trivia.Length + " trivia, walk " + (set.walk != null ? set.walk.name : "(missing)")
                + (missing.Count > 0 ? ". Not found: " + string.Join(", ", missing.ToArray()) : ".") ,
                set);

            return set;
        }

        /// <summary>The first of <paramref name="names"/> that exists (in order of preference).</summary>
        private static AnimationClip LoadFirstClip(string[] names, List<string> missing)
        {
            List<string> notFound = new List<string>();
            for (int i = 0; i < names.Length; i++)
            {
                AnimationClip clip = LoadClip(names[i], notFound);
                if (clip != null)
                {
                    return clip;
                }
            }

            missing.Add(string.Join(" / ", names));
            return null;
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
            // An empty name is an intentional gap (no clip is published for it).
            if (string.IsNullOrEmpty(name))
            {
                return null;
            }

            for (int f = 0; f < SoniaAnimations.ClipFolders.Length; f++)
            {
                if (!AssetDatabase.IsValidFolder(SoniaAnimations.ClipFolders[f]))
                {
                    continue;
                }

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
        // Generated idle and Genies SDK clips
        // ------------------------------------------------------------------

        /// <summary>Length of the generated idle loop, in seconds (one weight shift back and forth).</summary>
        private const float IdleLoopSeconds = 10f;

        /// <summary>Key spacing of the generated idle curves, in seconds.</summary>
        private const float IdleKeyStep = 0.25f;

        /// <summary>
        /// Copies the Genies Avatar SDK common animations (DefaultIdle, Walk) to
        /// <see cref="SoniaAnimations.SdkClipFolder"/> when the SDK is installed.
        /// The copies are configured like any other clip and are not committed.
        /// Returns how many were copied.
        /// </summary>
        public static int CopySdkClips()
        {
#if SONNIA_GENIES
            int copied = 0;
            foreach (string name in SoniaAnimations.SdkClips)
            {
                string source = SoniaAnimations.SdkCommonAnimationsFolder + "/" + name + ".anim";
                string target = SoniaAnimations.SdkClipFolder + "/" + name + ".anim";
                if (AssetDatabase.LoadAssetAtPath<AnimationClip>(target) != null)
                {
                    continue;
                }

                if (AssetDatabase.LoadAssetAtPath<AnimationClip>(source) == null)
                {
                    Debug.LogWarning("[Sonnia] Genies SDK clip not found: " + source);
                    continue;
                }

                EnsureFolder(SoniaAnimations.SdkClipFolder);
                if (AssetDatabase.CopyAsset(source, target))
                {
                    copied++;
                }
            }

            if (copied > 0)
            {
                Debug.Log("[Sonnia] Copied " + copied + " Genies SDK clip(s) to " + SoniaAnimations.SdkClipFolder
                          + " (not committed: Genies SDK license).");
            }

            return copied;
#else
            return 0;
#endif
        }

        /// <summary>
        /// Generates the idle loop <see cref="SoniaAnimations.GeneratedIdleClip"/>:
        /// the humanoid pose of <see cref="SoniaAnimations.GeneratedIdleSourceClip"/>
        /// at <see cref="SoniaAnimations.GeneratedIdleSourceTime"/>, held still,
        /// with a slow weight shift from one foot to the other (the feet stay
        /// planted through foot IK) and a little spine and arm drift. Breathing,
        /// head, face and eyes are added procedurally at runtime. With
        /// <paramref name="overwrite"/> false an existing clip is kept.
        /// </summary>
        [MenuItem("Sonnia/Regenerate Idle Clip")]
        public static void RegenerateIdleClipMenu()
        {
            GenerateIdleClip(true);
        }

        public static AnimationClip GenerateIdleClip(bool overwrite)
        {
            string path = SoniaAnimations.GeneratedClipFolder + "/" + SoniaAnimations.GeneratedIdleClip + ".anim";
            AnimationClip existing = AssetDatabase.LoadAssetAtPath<AnimationClip>(path);
            if (existing != null && !overwrite)
            {
                return existing;
            }

            AnimationClip source = LoadClip(SoniaAnimations.GeneratedIdleSourceClip, new List<string>());
            if (source == null)
            {
                Debug.LogWarning("[Sonnia] Cannot generate the idle loop: " + SoniaAnimations.GeneratedIdleSourceClip + " is missing.");
                return existing;
            }

            HashSet<string> muscles = new HashSet<string>(HumanTrait.MuscleName);
            AnimationClip clip = new AnimationClip { name = SoniaAnimations.GeneratedIdleClip, frameRate = 30f };
            float t0 = Mathf.Clamp(SoniaAnimations.GeneratedIdleSourceTime, 0f, source.length);
            foreach (EditorCurveBinding binding in AnimationUtility.GetCurveBindings(source))
            {
                if (binding.type != typeof(Animator) || !string.IsNullOrEmpty(binding.path) || !IsHumanoidCurve(binding.propertyName, muscles))
                {
                    continue;
                }

                AnimationCurve curve = AnimationUtility.GetEditorCurve(source, binding);
                if (curve == null)
                {
                    continue;
                }

                float value = curve.Evaluate(t0);
                AnimationUtility.SetEditorCurve(clip, binding, IdleCurve(binding.propertyName, value));
            }

            AnimationClipSettings settings = AnimationUtility.GetAnimationClipSettings(clip);
            settings.loopTime = true;
            settings.loopBlendOrientation = true;
            settings.keepOriginalOrientation = true;
            settings.loopBlendPositionY = true;
            settings.keepOriginalPositionY = true;
            settings.loopBlendPositionXZ = true;
            settings.keepOriginalPositionXZ = false;
            AnimationUtility.SetAnimationClipSettings(clip, settings);

            EnsureFolder(SoniaAnimations.GeneratedClipFolder);
            if (existing != null)
            {
                EditorUtility.CopySerialized(clip, existing);
                existing.name = SoniaAnimations.GeneratedIdleClip;
                EditorUtility.SetDirty(existing);
                AssetDatabase.SaveAssetIfDirty(existing);
                Object.DestroyImmediate(clip);
                clip = existing;
            }
            else
            {
                AssetDatabase.CreateAsset(clip, path);
            }

            AssetDatabase.SaveAssets();
            Debug.Log("[Sonnia] Idle loop generated: " + path + " (pose of " + source.name + " at " + t0.ToString("F2") + " s).", clip);
            return clip;
        }

        /// <summary>Muscles, root and IK goals of a humanoid clip; not the face or rig controls.</summary>
        private static bool IsHumanoidCurve(string property, HashSet<string> muscles)
        {
            if (muscles.Contains(property))
            {
                return true;
            }

            return property.StartsWith("RootT.") || property.StartsWith("RootQ.")
                || property.StartsWith("LeftFootT.") || property.StartsWith("LeftFootQ.")
                || property.StartsWith("RightFootT.") || property.StartsWith("RightFootQ.")
                || property.StartsWith("LeftHandT.") || property.StartsWith("LeftHandQ.")
                || property.StartsWith("RightHandT.") || property.StartsWith("RightHandQ.");
        }

        /// <summary>
        /// Loop curve for one property: constant at <paramref name="value"/>, plus a
        /// slow sine on the few properties that make the weight shift.
        /// </summary>
        private static AnimationCurve IdleCurve(string property, float value)
        {
            float amplitude;
            float phase;
            switch (property)
            {
                // Hips sway sideways (center of mass, metres); the feet stay planted.
                case "RootT.x": amplitude = 0.012f; phase = 0f; break;
                // The spine and chest lean against the hips so the head stays centred.
                case "Spine Left-Right": amplitude = -0.025f; phase = 0f; break;
                case "Chest Left-Right": amplitude = -0.015f; phase = 0.05f; break;
                case "Spine Front-Back": amplitude = 0.01f; phase = 0.25f; break;
                // Arms hang and drift a little with the body.
                case "Left Arm Down-Up": amplitude = 0.012f; phase = 0.1f; break;
                case "Right Arm Down-Up": amplitude = -0.012f; phase = 0.1f; break;
                case "Left Forearm Stretch": amplitude = 0.01f; phase = 0.3f; break;
                case "Right Forearm Stretch": amplitude = -0.01f; phase = 0.3f; break;
                default: amplitude = 0f; phase = 0f; break;
            }

            if (Mathf.Approximately(amplitude, 0f))
            {
                return AnimationCurve.Constant(0f, IdleLoopSeconds, value);
            }

            int steps = Mathf.RoundToInt(IdleLoopSeconds / IdleKeyStep);
            Keyframe[] keys = new Keyframe[steps + 1];
            for (int i = 0; i <= steps; i++)
            {
                float t = i * IdleKeyStep;
                float angle = 2f * Mathf.PI * (t / IdleLoopSeconds + phase);
                float slope = amplitude * 2f * Mathf.PI / IdleLoopSeconds * Mathf.Cos(angle);
                keys[i] = new Keyframe(t, value + amplitude * Mathf.Sin(angle), slope, slope);
            }

            return new AnimationCurve(keys);
        }

        // ------------------------------------------------------------------
        // Mask and scene
        // ------------------------------------------------------------------

        /// <summary>Creates or updates the torso mask.</summary>
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
        /// Puts MotionPlayer and AvatarChoreographer on the Sonia object of the
        /// open scene, pointing at the avatar's Animator, the set and the mask.
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

        /// <summary>Adds (if missing) and wires the animation components on the root object.</summary>
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
                Undo.RecordObject(animator, "Configure Sonnia Animator");
                animator.runtimeAnimatorController = null;
                animator.applyRootMotion = false;
                animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
                EditorUtility.SetDirty(animator);
            }
        }

        /// <summary>The already generated set, or generates it if missing.</summary>
        public static SoniaMotionSet LoadOrBuildMotionSet()
        {
            SoniaMotionSet set = AssetDatabase.LoadAssetAtPath<SoniaMotionSet>(SoniaAnimations.MotionSetPath);
            if (set == null)
            {
                CopySdkClips();
                GenerateIdleClip(false);
                ConfigureClips();
                set = BuildMotionSet();
            }

            return set;
        }

        /// <summary>The already generated mask, or generates it if missing.</summary>
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
