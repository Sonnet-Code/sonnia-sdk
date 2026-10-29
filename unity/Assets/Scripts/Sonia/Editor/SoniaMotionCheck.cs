// Animation check in Play, frame by frame.
//
// Plays clips of the set on the attached avatar (the Genies SDK one or the
// fallback), advances the game at a fixed step with EditorApplication.Step and
// at each sample measures legs and orientation and saves a front capture (the
// main camera) and a side one. It validates any clip against the official
// Genies ones before adding it to SoniaAnimations: a knee that bends forward,
// a twisted foot or a body that turns its back show up in the report without
// looking at the frames one by one.
//
// Usage, with the app in Play: Sonnia > Check Animations (Play mode). The first
// time it only pauses (EditorApplication.Step does not advance in the same
// command that requests the pause); the second time it runs the check. Output
// in Temp/motioncheck/.

#if UNITY_EDITOR

using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Measures the set's clips on the real avatar and saves front and side frames.</summary>
    public static class SoniaMotionCheck
    {
        /// <summary>Output folder, relative to the project.</summary>
        public const string OutputFolder = "Temp/motioncheck";

        /// <summary>Seconds between samples (EditorApplication.Step advances 0.02 s).</summary>
        private const float SampleSeconds = 0.1f;

        private const float StepSeconds = 0.02f;

        /// <summary>A knee that bends (more than 8°) and ends up behind the hip-ankle line is backwards.</summary>
        private const float KneeBendDegrees = 8f;

        private const float KneeBackwardCm = 1.5f;

        /// <summary>Foot turned relative to where the body faces.</summary>
        private const float FootTurnDegrees = 60f;

        /// <summary>Body turned relative to the camera (turning its back to the user is not acceptable).</summary>
        private const float BodyTurnDegrees = 80f;

        /// <summary>The assistant's choreographer (the one under the bootstrap, if there are several in the scene).</summary>
        private static AvatarChoreographer SoniaChoreographer()
        {
            SoniaBootstrap sonia = Object.FindAnyObjectByType<SoniaBootstrap>();
            AvatarChoreographer found = sonia != null ? sonia.GetComponentInChildren<AvatarChoreographer>(true) : null;
            return found != null ? found : Object.FindAnyObjectByType<AvatarChoreographer>();
        }

        [MenuItem("Sonnia/Check Animations (Play mode)")]
        public static void CheckAllMenu()
        {
            Debug.Log(CheckAll());
        }

        /// <summary>Checks all distinct clips of the set. Returns the report.</summary>
        public static string CheckAll()
        {
            string blocked = Precondition();
            if (blocked != null)
            {
                return blocked;
            }

            AvatarChoreographer choreographer = SoniaChoreographer();

            // The project's set, not the choreographer's: with debug mode or with
            // animations disabled in the panel, the choreographer carries a trimmed copy.
            SoniaMotionSet set = AssetDatabase.LoadAssetAtPath<SoniaMotionSet>(SoniaAnimations.MotionSetPath);
            if (set == null)
            {
                set = choreographer.MotionSet;
            }

            List<AnimationClip> clips = new List<AnimationClip>();
            AddClip(clips, set.idleLoop);
            AddClip(clips, set.listeningLoop);
            AddClip(clips, set.thinkingLoop);
            AddClip(clips, set.walk);
            AddClip(clips, set.greeting);
            AddClip(clips, set.present);
            AddClips(clips, set.idleVariations);
            AddClips(clips, set.nods);
            AddClips(clips, set.thinkingVariations);
            AddClips(clips, set.talking);
            for (int i = 0; i < set.attention.Length; i++)
            {
                AddClip(clips, set.attention[i] != null ? set.attention[i].clip : null);
            }

            StringBuilder report = new StringBuilder();
            int failed = 0;
            for (int i = 0; i < clips.Count; i++)
            {
                bool ok;
                report.Append(Check(choreographer, clips[i], out ok));
                failed += ok ? 0 : 1;
            }

            string summary = "[Sonnia] Animation check: " + clips.Count + " clips, " + failed
                             + " with problems. Frames and report in " + Path.GetFullPath(OutputFolder) + ".";
            report.Insert(0, summary + "\n");
            Directory.CreateDirectory(OutputFolder);
            File.WriteAllText(Path.Combine(OutputFolder, "report.txt"), report.ToString());
            return report.ToString();
        }

        /// <summary>
        /// Checks all clips in the SoniaAnimations.ClipFolders folders, whether or
        /// not they are in the set: this is how candidates are validated before use.
        /// </summary>
        public static string CheckFolders()
        {
            string blocked = Precondition();
            if (blocked != null)
            {
                return blocked;
            }

            AvatarChoreographer choreographer = SoniaChoreographer();
            List<AnimationClip> clips = new List<AnimationClip>();
            string[] folders = System.Array.FindAll(SoniaAnimations.ClipFolders, AssetDatabase.IsValidFolder);
            foreach (string guid in AssetDatabase.FindAssets("t:AnimationClip", folders))
            {
                AddClip(clips, AssetDatabase.LoadAssetAtPath<AnimationClip>(AssetDatabase.GUIDToAssetPath(guid)));
            }

            StringBuilder report = new StringBuilder();
            int failed = 0;
            for (int i = 0; i < clips.Count; i++)
            {
                bool ok;
                report.Append(Check(choreographer, clips[i], out ok));
                failed += ok ? 0 : 1;
            }

            report.Insert(0, "[Sonnia] Clip folders check: " + clips.Count + " clips, " + failed
                             + " with problems. Frames in " + Path.GetFullPath(OutputFolder) + ".\n");
            Directory.CreateDirectory(OutputFolder);
            File.WriteAllText(Path.Combine(OutputFolder, "report-folders.txt"), report.ToString());
            return report.ToString();
        }

        /// <summary>Checks a clip of the set by name. Returns the report.</summary>
        public static string CheckClip(string clipName)
        {
            string blocked = Precondition();
            if (blocked != null)
            {
                return blocked;
            }

            AvatarChoreographer choreographer = SoniaChoreographer();
            SoniaMotionSet set = AssetDatabase.LoadAssetAtPath<SoniaMotionSet>(SoniaAnimations.MotionSetPath);
            AnimationClip clip = FindInSet(set != null ? set : choreographer.MotionSet, clipName);
            if (clip == null)
            {
                return "[Sonnia] The set has no clip named " + clipName + ".";
            }

            bool ok;
            return Check(choreographer, clip, out ok);
        }

        private static string Precondition()
        {
            if (!EditorApplication.isPlaying)
            {
                return "[Sonnia] Check Animations only works in Play mode.";
            }

            if (!EditorApplication.isPaused)
            {
                EditorApplication.isPaused = true;
                return "[Sonnia] Play paused. Run the check again (Step does not advance in the same command that pauses).";
            }

            AvatarChoreographer choreographer = SoniaChoreographer();
            if (choreographer == null || choreographer.MotionSet == null || !choreographer.Ready)
            {
                return "[Sonnia] There is no choreographer ready in the scene.";
            }

            return null;
        }

        private static string Check(AvatarChoreographer choreographer, AnimationClip clip, out bool ok)
        {
            ok = true;
            Animator animator = choreographer.Player != null ? choreographer.Player.Animator : null;
            if (animator == null || !animator.isHuman)
            {
                ok = false;
                return clip.name + ": no Humanoid Animator.\n";
            }

            Transform root = animator.transform;
            string folder = Path.Combine(OutputFolder, clip.name);
            Directory.CreateDirectory(folder);
            foreach (string old in Directory.GetFiles(folder, "*.png"))
            {
                File.Delete(old);
            }

            // The choreographer steps aside (as when presence walks) and the clip
            // plays alone on the body: Preview is no use for loops, because at
            // idle the choreographer puts its base loop back on every frame.
            choreographer.Suspend();
            MotionPlayer.Handle playing = choreographer.Player.Play(clip, MotionPlayer.BodyLayer, 0.1f);

            // Let the fade in finish before measuring.
            for (int i = 0; i < 15; i++)
            {
                EditorApplication.Step();
            }

            float seconds = clip.isLooping ? clip.length : clip.length + 0.3f;
            int steps = Mathf.CeilToInt(seconds / StepSeconds);
            int every = Mathf.Max(1, Mathf.RoundToInt(SampleSeconds / StepSeconds));
            Camera side = new GameObject("SoniaMotionCheck.Side").AddComponent<Camera>();
            side.fieldOfView = 30f;

            CultureInfo inv = CultureInfo.InvariantCulture;
            StringBuilder lines = new StringBuilder();
            List<string> problems = new List<string>();
            float worstKnee = float.MaxValue;
            float worstFoot = 0f;
            float worstBody = 0f;
            try
            {
                for (int step = 0; step <= steps; step++)
                {
                    EditorApplication.Step();
                    if (step % every != 0)
                    {
                        continue;
                    }

                    float t = step * StepSeconds;
                    Vector3 facing = Flat(root.forward);
                    Vector3 toCamera = Camera.main != null ? Flat(Camera.main.transform.position - root.position) : facing;

                    float kneeL, bendL, kneeR, bendR, footL, footR;
                    MeasureLeg(animator, HumanBodyBones.LeftUpperLeg, HumanBodyBones.LeftLowerLeg, HumanBodyBones.LeftFoot, HumanBodyBones.LeftToes, facing, root.position.y, out kneeL, out bendL, out footL);
                    MeasureLeg(animator, HumanBodyBones.RightUpperLeg, HumanBodyBones.RightLowerLeg, HumanBodyBones.RightFoot, HumanBodyBones.RightToes, facing, root.position.y, out kneeR, out bendR, out footR);
                    Transform hips = animator.GetBoneTransform(HumanBodyBones.Hips);
                    float body = Vector3.Angle(Flat(hips.forward), toCamera);

                    lines.Append("  t=").Append(t.ToString("F2", inv))
                        .Append("  left knee ").Append(kneeL.ToString("+0.0;-0.0", inv)).Append(" cm (").Append(bendL.ToString("F0", inv)).Append("°)")
                        .Append("  right ").Append(kneeR.ToString("+0.0;-0.0", inv)).Append(" cm (").Append(bendR.ToString("F0", inv)).Append("°)")
                        .Append("  feet ").Append(footL.ToString("F0", inv)).Append("°/").Append(footR.ToString("F0", inv)).Append("°")
                        .Append("  body ").Append(body.ToString("F0", inv)).Append("°\n");

                    CheckKnee(problems, "left", t, kneeL, bendL);
                    CheckKnee(problems, "right", t, kneeR, bendR);
                    if (Mathf.Max(footL, footR) > FootTurnDegrees)
                    {
                        problems.Add("foot turned " + Mathf.Max(footL, footR).ToString("F0", inv) + "° at t=" + t.ToString("F2", inv));
                    }

                    if (body > BodyTurnDegrees)
                    {
                        problems.Add("body turned " + body.ToString("F0", inv) + "° relative to the camera at t=" + t.ToString("F2", inv));
                    }

                    worstKnee = Mathf.Min(worstKnee, Mathf.Min(bendL > KneeBendDegrees ? kneeL : 0f, bendR > KneeBendDegrees ? kneeR : 0f));
                    worstFoot = Mathf.Max(worstFoot, Mathf.Max(footL, footR));
                    worstBody = Mathf.Max(worstBody, body);

                    string stamp = step.ToString("D3", inv);
                    Render(Camera.main, Path.Combine(folder, "front_" + stamp + ".png"));
                    Vector3 pelvis = hips.position;
                    side.transform.position = pelvis + root.right * 2.4f + Vector3.up * 0.05f;
                    side.transform.LookAt(pelvis + Vector3.down * 0.25f);
                    Render(side, Path.Combine(folder, "side_" + stamp + ".png"));
                }
            }
            finally
            {
                Object.DestroyImmediate(side.gameObject);
                choreographer.Resume(playing, 0.3f);
            }

            ok = problems.Count == 0;
            StringBuilder report = new StringBuilder();
            report.Append(clip.name).Append(" (").Append(clip.length.ToString("F2", inv)).Append(" s")
                .Append(clip.isLooping ? ", loop" : string.Empty).Append("): ")
                .Append(ok ? "ok" : "PROBLEMS: " + string.Join("; ", Distinct(problems)))
                .Append(". Worst knee ").Append((worstKnee == float.MaxValue ? 0f : worstKnee).ToString("+0.0;-0.0", inv))
                .Append(" cm, worst foot ").Append(worstFoot.ToString("F0", inv)).Append("°, body up to ")
                .Append(worstBody.ToString("F0", inv)).Append("°.\n");
            report.Append(lines);
            return report.ToString();
        }

        /// <summary>
        /// Knee relative to the hip-ankle line and foot turn. The turn only counts
        /// with the foot on the ground: when raised (a little kick backward) it
        /// points wherever it likes without being an error.
        /// </summary>
        private static void MeasureLeg(
            Animator animator, HumanBodyBones upper, HumanBodyBones lower, HumanBodyBones foot, HumanBodyBones toes,
            Vector3 facing, float groundY, out float kneeAheadCm, out float bendDegrees, out float footTurnDegrees)
        {
            Vector3 hip = animator.GetBoneTransform(upper).position;
            Vector3 knee = animator.GetBoneTransform(lower).position;
            Vector3 ankle = animator.GetBoneTransform(foot).position;
            Vector3 onLine = hip + Vector3.Project(knee - hip, ankle - hip);
            kneeAheadCm = Vector3.Dot(knee - onLine, facing) * 100f;
            bendDegrees = Vector3.Angle(knee - hip, ankle - knee);
            Transform toe = animator.GetBoneTransform(toes);
            bool grounded = toe != null && toe.position.y - groundY < 0.08f;
            footTurnDegrees = grounded ? Vector3.Angle(Flat(toe.position - ankle), facing) : 0f;
        }

        private static void CheckKnee(List<string> problems, string side, float t, float aheadCm, float bend)
        {
            if (bend > KneeBendDegrees && aheadCm < -KneeBackwardCm)
            {
                problems.Add(side + " knee backwards (" + aheadCm.ToString("F1", CultureInfo.InvariantCulture)
                             + " cm, " + bend.ToString("F0", CultureInfo.InvariantCulture) + "°) at t="
                             + t.ToString("F2", CultureInfo.InvariantCulture));
            }
        }

        private static Vector3 Flat(Vector3 v)
        {
            v.y = 0f;
            return v.sqrMagnitude > 0.000001f ? v.normalized : Vector3.forward;
        }

        private static void Render(Camera camera, string path)
        {
            if (camera == null)
            {
                return;
            }

            RenderTexture texture = RenderTexture.GetTemporary(540, 960, 24);
            RenderTexture previousTarget = camera.targetTexture;
            RenderTexture previousActive = RenderTexture.active;
            camera.targetTexture = texture;
            camera.Render();
            camera.targetTexture = previousTarget;
            RenderTexture.active = texture;
            Texture2D image = new Texture2D(540, 960, TextureFormat.RGB24, false);
            image.ReadPixels(new Rect(0, 0, 540, 960), 0, 0);
            image.Apply();
            RenderTexture.active = previousActive;
            File.WriteAllBytes(path, image.EncodeToPNG());
            Object.DestroyImmediate(image);
            RenderTexture.ReleaseTemporary(texture);
        }

        private static AnimationClip FindInSet(SoniaMotionSet set, string name)
        {
            List<AnimationClip> all = new List<AnimationClip>();
            AddClip(all, set.idleLoop);
            AddClip(all, set.listeningLoop);
            AddClip(all, set.thinkingLoop);
            AddClip(all, set.walk);
            AddClip(all, set.greeting);
            AddClip(all, set.present);
            AddClips(all, set.idleVariations);
            AddClips(all, set.nods);
            AddClips(all, set.thinkingVariations);
            AddClips(all, set.talking);
            for (int i = 0; i < set.attention.Length; i++)
            {
                AddClip(all, set.attention[i] != null ? set.attention[i].clip : null);
            }

            for (int i = 0; i < all.Count; i++)
            {
                if (all[i].name == name)
                {
                    return all[i];
                }
            }

            return null;
        }

        private static void AddClip(List<AnimationClip> list, AnimationClip clip)
        {
            if (clip != null && !list.Contains(clip))
            {
                list.Add(clip);
            }
        }

        private static void AddClips(List<AnimationClip> list, AnimationClip[] clips)
        {
            if (clips == null)
            {
                return;
            }

            for (int i = 0; i < clips.Length; i++)
            {
                AddClip(list, clips[i]);
            }
        }

        private static IEnumerable<string> Distinct(List<string> items)
        {
            HashSet<string> kinds = new HashSet<string>();
            foreach (string item in items)
            {
                string kind = item.Split(new[] { " at t=" }, System.StringSplitOptions.None)[0];
                kind = kind.Split('(')[0].Trim();
                if (kinds.Add(kind))
                {
                    yield return item;
                }
            }
        }
    }
}

#endif
