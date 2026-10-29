// Idle comparison in Play, at a fixed step.
//
// Loops an idle clip on the attached avatar (or lets the choreographer do its
// thing in a state), advances the game with EditorApplication.Step and
// measures what is noticeable in an idle: how much the hips sway, how much the
// head moves, whether planted feet slide and whether the hands sink into the
// body. It also measures the life that the face and body components add: chest
// (breathing) and head pitch, eye fixation changes per minute and how much they
// look at the user, eye vergence (cross-eyed look) and blinks (how many and how
// long). It saves frames with four cameras: the main shot (Camera.main), two
// fixed full-body ones, front and side, and a face close-up. The fixed ones do
// not follow the hips, so the sway shows against the framing.
//
// Use from the MCP with the app in Play and paused (Step does not advance in the
// same command that requests the pause): RecordClip(...) or RecordState(...).
// Output in Temp/idlecheck/<label>/.

#if UNITY_EDITOR

using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Measures and photographs idles on the real avatar.</summary>
    public static class SoniaIdleCheck
    {
        /// <summary>Output folder, relative to the project (Temp is not committed).</summary>
        public const string OutputFolder = "Temp/idlecheck";

        private const float StepSeconds = 0.02f;
        private const float SampleSeconds = 0.1f;

        // A foot counts as planted with the ankle below this height from the floor.
        private const float GroundedAnkleHeight = 0.13f;

        /// <summary>
        /// Loops <paramref name="clipPath"/> with the XZ travel baked into the
        /// pose (<paramref name="bakeXZ"/>) or left out (as the set generator left
        /// it), records it for <paramref name="seconds"/> seconds and returns the
        /// report. It changes the clip's settings in the asset.
        /// </summary>
        public static string RecordClip(string clipPath, bool bakeXZ, float seconds, float frameEvery, string label)
        {
            string blocked = Precondition();
            if (blocked != null)
            {
                return blocked;
            }

            AnimationClip clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
            if (clip == null)
            {
                return "No clip at " + clipPath + ".";
            }

            SetLoopSettings(clip, bakeXZ);
            AvatarChoreographer choreographer = SoniaChoreographer();
            choreographer.Suspend();
            MotionPlayer.Handle playing = choreographer.Player.Play(clip, MotionPlayer.BodyLayer, 0.2f);
            try
            {
                for (int i = 0; i < 25; i++)
                {
                    EditorApplication.Step();
                }

                return Record(choreographer, label, clip.name + (bakeXZ ? " (XZ in the pose)" : " (XZ out)"), seconds, frameEvery);
            }
            finally
            {
                choreographer.Resume(playing, 0.3f);
            }
        }

        /// <summary>
        /// Leaves the choreographer in <paramref name="state"/> (with its loops,
        /// gestures and layers) and records it: this shows the final result, not a
        /// loose clip.
        /// </summary>
        public static string RecordState(AvatarState state, float seconds, float frameEvery, string label)
        {
            string blocked = Precondition();
            if (blocked != null)
            {
                return blocked;
            }

            AvatarChoreographer choreographer = SoniaChoreographer();
            choreographer.SetState(state);

            // Head, eyes, face and breathing read the state from AvatarStateController.
            AvatarStateController avatarState = choreographer.GetComponentInChildren<AvatarStateController>(true);
            if (avatarState != null)
            {
                avatarState.SetState(state);
            }

            for (int i = 0; i < 40; i++)
            {
                EditorApplication.Step();
            }

            return Record(choreographer, label, "state " + state, seconds, frameEvery);
        }

        /// <summary>
        /// Loop settings for an idle: root rotation and height baked into the
        /// pose, and the XZ travel in or out. No events (nobody receives them).
        /// </summary>
        public static void SetLoopSettings(AnimationClip clip, bool bakeXZ)
        {
            AnimationClipSettings settings = AnimationUtility.GetAnimationClipSettings(clip);
            settings.loopTime = true;
            settings.loopBlendOrientation = true;
            settings.keepOriginalOrientation = true;
            settings.loopBlendPositionY = true;
            settings.keepOriginalPositionY = true;
            settings.loopBlendPositionXZ = bakeXZ;
            settings.keepOriginalPositionXZ = false;
            AnimationUtility.SetAnimationClipSettings(clip, settings);
            if (AnimationUtility.GetAnimationEvents(clip).Length > 0)
            {
                AnimationUtility.SetAnimationEvents(clip, new AnimationEvent[0]);
            }

            EditorUtility.SetDirty(clip);
            AssetDatabase.SaveAssetIfDirty(clip);
        }

        /// <summary>The assistant's choreographer (the one under the bootstrap, if there are several in the scene).</summary>
        private static AvatarChoreographer SoniaChoreographer()
        {
            SoniaBootstrap sonia = Object.FindAnyObjectByType<SoniaBootstrap>();
            AvatarChoreographer found = sonia != null ? sonia.GetComponentInChildren<AvatarChoreographer>(true) : null;
            return found != null ? found : Object.FindAnyObjectByType<AvatarChoreographer>();
        }

        private static string Precondition()
        {
            if (!EditorApplication.isPlaying)
            {
                return "Play mode is required.";
            }

            if (!EditorApplication.isPaused)
            {
                EditorApplication.isPaused = true;
                return "Play paused: run it again (Step does not advance in the same command that pauses).";
            }

            AvatarChoreographer choreographer = SoniaChoreographer();
            if (choreographer == null || !choreographer.Ready)
            {
                return "No choreographer ready.";
            }

            Animator animator = choreographer.Player.Animator;
            return animator != null && animator.isHuman ? null : "No Humanoid Animator.";
        }

        private static string Record(AvatarChoreographer choreographer, string label, string title, float seconds, float frameEvery)
        {
            Animator animator = choreographer.Player.Animator;
            Transform root = animator.transform;
            Transform hips = animator.GetBoneTransform(HumanBodyBones.Hips);
            Transform chest = animator.GetBoneTransform(HumanBodyBones.Chest);
            Transform head = animator.GetBoneTransform(HumanBodyBones.Head);
            Transform[] feet = { animator.GetBoneTransform(HumanBodyBones.LeftFoot), animator.GetBoneTransform(HumanBodyBones.RightFoot) };
            Transform[] hands = { animator.GetBoneTransform(HumanBodyBones.LeftHand), animator.GetBoneTransform(HumanBodyBones.RightHand) };
            Transform upperChest = animator.GetBoneTransform(HumanBodyBones.UpperChest);
            Transform breathBone = upperChest != null ? upperChest : chest;
            Transform leftEye = FindChild(head, "LeftEye", "Eye_L", "eye_L");
            Transform rightEye = FindChild(head, "RightEye", "Eye_R", "eye_R");
            EyeGazeController gaze = choreographer.GetComponentInChildren<EyeGazeController>(true);
            FaceRig face = choreographer.GetComponentInChildren<FaceRig>(true);
            SkinnedMeshRenderer faceMesh = face != null ? face.PrimaryRenderer : null;
            int blinkShape = faceMesh != null ? LipSyncController.FindBlendShape(faceMesh.sharedMesh, "EYES_CLOSED_L") : -1;
            if (faceMesh != null && blinkShape < 0)
            {
                blinkShape = LipSyncController.FindBlendShape(faceMesh.sharedMesh, "eyeBlinkLeft");
            }

            float blinkScale = faceMesh != null ? LipSyncController.BlendShapeScale(faceMesh.sharedMesh) : 1f;

            string folder = Path.Combine(OutputFolder, label);
            Directory.CreateDirectory(folder);
            foreach (string old in Directory.GetFiles(folder, "*.png"))
            {
                File.Delete(old);
            }

            // Fixed full-body cameras, at waist height, following nobody.
            Vector3 center = root.position + Vector3.up * 0.86f;
            Camera front = MakeCamera("SoniaIdleCheck.Front", center + root.forward * 3.4f, center);
            Camera side = MakeCamera("SoniaIdleCheck.Side", center + root.right * 3.4f, center);
            Camera closeup = MakeCamera("SoniaIdleCheck.Face", head.position + root.forward * 0.9f, head.position);
            closeup.fieldOfView = 22f;

            CultureInfo inv = CultureInfo.InvariantCulture;
            StringBuilder csv = new StringBuilder("t,hips_x,hips_y,hips_z,head_x,head_y,head_z,head_yaw,head_roll,left_foot_planted,right_foot_planted,left_hand_body,right_hand_body,chest_pitch,head_pitch,fixation_yaw,fixation_pitch,vergence,eyelid\n");
            int steps = Mathf.CeilToInt(seconds / StepSeconds);
            int sampleEvery = Mathf.Max(1, Mathf.RoundToInt(SampleSeconds / StepSeconds));
            int frameStride = Mathf.Max(1, Mathf.RoundToInt(frameEvery / StepSeconds));
            Bounds hipsRange = new Bounds(root.InverseTransformPoint(hips.position), Vector3.zero);
            Bounds headRange = new Bounds(root.InverseTransformPoint(head.position), Vector3.zero);
            Vector2 headYaw = new Vector2(float.MaxValue, float.MinValue);
            Vector2 headRoll = new Vector2(float.MaxValue, float.MinValue);
            Vector3[] anchors = new Vector3[2];
            bool[] grounded = new bool[2];
            float[] slide = new float[2];
            float[] handGap = { float.MaxValue, float.MaxValue };
            Vector2 chestPitch = new Vector2(float.MaxValue, float.MinValue);
            Vector2 headPitch = new Vector2(float.MaxValue, float.MinValue);
            Vector2 vergence = new Vector2(float.MaxValue, float.MinValue);
            Vector2 lastFixation = gaze != null ? gaze.CurrentFixation : Vector2.zero;
            int fixationJumps = 0;
            int stepsAtVisitor = 0;
            float widestFixation = 0f;
            int blinks = 0;
            float closedSeconds = 0f;
            bool wasClosed = false;
            try
            {
                for (int step = 0; step <= steps; step++)
                {
                    EditorApplication.Step();
                    Vector3 hipsLocal = root.InverseTransformPoint(hips.position);
                    Vector3 headLocal = root.InverseTransformPoint(head.position);
                    hipsRange.Encapsulate(hipsLocal);
                    headRange.Encapsulate(headLocal);
                    Vector3 headAngles = (Quaternion.Inverse(root.rotation) * head.rotation).eulerAngles;
                    float yaw = Mathf.DeltaAngle(0f, headAngles.y);
                    float roll = Mathf.DeltaAngle(0f, headAngles.z);
                    headYaw = new Vector2(Mathf.Min(headYaw.x, yaw), Mathf.Max(headYaw.y, yaw));
                    headRoll = new Vector2(Mathf.Min(headRoll.x, roll), Mathf.Max(headRoll.y, roll));
                    float headNod = Mathf.DeltaAngle(0f, headAngles.x);
                    headPitch = new Vector2(Mathf.Min(headPitch.x, headNod), Mathf.Max(headPitch.y, headNod));
                    float chestNod = breathBone != null ? Mathf.DeltaAngle(0f, (Quaternion.Inverse(root.rotation) * breathBone.rotation).eulerAngles.x) : 0f;
                    chestPitch = new Vector2(Mathf.Min(chestPitch.x, chestNod), Mathf.Max(chestPitch.y, chestNod));

                    // Vergence: horizontal angle between the gaze of the two eyes
                    // (positive, they converge). With the camera a few meters away,
                    // more than about 4° already reads as cross-eyed.
                    float verge = 0f;
                    if (leftEye != null && rightEye != null)
                    {
                        Vector3 l = Flat(root.InverseTransformDirection(leftEye.forward));
                        Vector3 r = Flat(root.InverseTransformDirection(rightEye.forward));
                        verge = Vector3.SignedAngle(r, l, Vector3.up);
                        vergence = new Vector2(Mathf.Min(vergence.x, verge), Mathf.Max(vergence.y, verge));
                    }

                    Vector2 fixation = gaze != null ? gaze.CurrentFixation : Vector2.zero;
                    if ((fixation - lastFixation).sqrMagnitude > 0.01f)
                    {
                        fixationJumps++;
                    }

                    lastFixation = fixation;
                    stepsAtVisitor += fixation.sqrMagnitude < 0.01f ? 1 : 0;
                    widestFixation = Mathf.Max(widestFixation, fixation.magnitude);

                    float lid = faceMesh != null && blinkShape >= 0 ? faceMesh.GetBlendShapeWeight(blinkShape) / (100f * blinkScale) : 0f;
                    bool closed = lid > 0.5f;
                    blinks += closed && !wasClosed ? 1 : 0;
                    closedSeconds += closed ? StepSeconds : 0f;
                    wasClosed = closed;

                    // Planted foot: anchored when planted, then measure how far it drifts horizontally.
                    for (int f = 0; f < 2; f++)
                    {
                        bool down = feet[f].position.y - root.position.y < GroundedAnkleHeight;
                        if (down && !grounded[f])
                        {
                            anchors[f] = feet[f].position;
                        }
                        else if (down)
                        {
                            slide[f] = Mathf.Max(slide[f], Flat(feet[f].position - anchors[f]).magnitude);
                        }

                        grounded[f] = down;
                    }

                    // Hand relative to the trunk axis (hips-chest), horizontally: below
                    // about 12 cm it is stuck to or inside the hip.
                    for (int h = 0; h < 2; h++)
                    {
                        handGap[h] = Mathf.Min(handGap[h], DistanceToAxis(hands[h].position, hips.position, chest.position));
                    }

                    if (step % sampleEvery == 0)
                    {
                        csv.Append((step * StepSeconds).ToString("F2", inv)).Append(',')
                            .Append(Cm(hipsLocal.x)).Append(',').Append(Cm(hipsLocal.y)).Append(',').Append(Cm(hipsLocal.z)).Append(',')
                            .Append(Cm(headLocal.x)).Append(',').Append(Cm(headLocal.y)).Append(',').Append(Cm(headLocal.z)).Append(',')
                            .Append(yaw.ToString("F1", inv)).Append(',').Append(roll.ToString("F1", inv)).Append(',')
                            .Append(grounded[0] ? 1 : 0).Append(',').Append(grounded[1] ? 1 : 0).Append(',')
                            .Append(Cm(DistanceToAxis(hands[0].position, hips.position, chest.position))).Append(',')
                            .Append(Cm(DistanceToAxis(hands[1].position, hips.position, chest.position))).Append(',')
                            .Append(chestNod.ToString("F2", inv)).Append(',').Append(headNod.ToString("F2", inv)).Append(',')
                            .Append(fixation.x.ToString("F1", inv)).Append(',').Append(fixation.y.ToString("F1", inv)).Append(',')
                            .Append(verge.ToString("F2", inv)).Append(',').Append(lid.ToString("F2", inv)).Append('\n');
                    }

                    if (step % frameStride == 0)
                    {
                        string stamp = step.ToString("D4", inv);
                        Render(Camera.main, Path.Combine(folder, "shot_" + stamp + ".png"));
                        Render(front, Path.Combine(folder, "front_" + stamp + ".png"));
                        Render(side, Path.Combine(folder, "side_" + stamp + ".png"));
                        closeup.transform.position = head.position + root.forward * 0.9f;
                        closeup.transform.LookAt(head.position);
                        Render(closeup, Path.Combine(folder, "face_" + stamp + ".png"));
                    }
                }
            }
            finally
            {
                Object.DestroyImmediate(front.gameObject);
                Object.DestroyImmediate(side.gameObject);
                Object.DestroyImmediate(closeup.gameObject);
            }

            float minutes = Mathf.Max(0.01f, seconds / 60f);
            int totalSteps = steps + 1;

            StringBuilder report = new StringBuilder();
            report.Append(label).Append(": ").Append(title).Append(", ").Append(seconds.ToString("F0", inv)).Append(" s. ")
                .Append("Hips: ").Append(Cm(hipsRange.size.x)).Append(" cm side to side, ")
                .Append(Cm(hipsRange.size.z)).Append(" cm front-back, ").Append(Cm(hipsRange.size.y)).Append(" cm vertical. ")
                .Append("Head: ").Append(Cm(headRange.size.x)).Append(" cm sideways, yaw ")
                .Append((headYaw.y - headYaw.x).ToString("F1", inv)).Append("°, roll ")
                .Append((headRoll.y - headRoll.x).ToString("F1", inv)).Append("°. ")
                .Append("Planted feet, worst slide: ").Append(Cm(slide[0])).Append(" / ").Append(Cm(slide[1])).Append(" cm. ")
                .Append("Hands, closest to the trunk axis: ").Append(Cm(handGap[0])).Append(" / ").Append(Cm(handGap[1])).Append(" cm. ")
                .Append("Chest: pitch ").Append((chestPitch.y - chestPitch.x).ToString("F1", inv)).Append("° range; head: ")
                .Append((headPitch.y - headPitch.x).ToString("F1", inv)).Append("°. ")
                .Append("Eyes: ").Append((fixationJumps / minutes).ToString("F0", inv)).Append(" fixation changes per minute, ")
                .Append((100f * stepsAtVisitor / totalSteps).ToString("F0", inv)).Append(" % of the time at the user, up to ")
                .Append(widestFixation.ToString("F1", inv)).Append("°; vergence from ")
                .Append((vergence.x == float.MaxValue ? 0f : vergence.x).ToString("F1", inv)).Append("° to ")
                .Append((vergence.y == float.MinValue ? 0f : vergence.y).ToString("F1", inv)).Append("°. ")
                .Append("Blinks: ").Append((blinks / minutes).ToString("F0", inv)).Append(" per minute, ")
                .Append((blinks > 0 ? closedSeconds / blinks : 0f).ToString("F2", inv)).Append(" s more than half closed each.");
            File.WriteAllText(Path.Combine(folder, "report.txt"), report + "\n");
            File.WriteAllText(Path.Combine(folder, "samples.csv"), csv.ToString());
            return report.ToString();
        }

        private static Transform FindChild(Transform root, params string[] names)
        {
            if (root == null)
            {
                return null;
            }

            Transform[] all = root.GetComponentsInChildren<Transform>(true);
            for (int n = 0; n < names.Length; n++)
            {
                for (int i = 0; i < all.Length; i++)
                {
                    if (all[i].name == names[n] || all[i].name.EndsWith(":" + names[n]))
                    {
                        return all[i];
                    }
                }
            }

            return null;
        }

        private static Camera MakeCamera(string name, Vector3 position, Vector3 target)
        {
            Camera camera = new GameObject(name).AddComponent<Camera>();
            camera.fieldOfView = 34f;
            camera.nearClipPlane = 0.1f;
            camera.transform.position = position;
            camera.transform.LookAt(target);
            camera.enabled = false;
            return camera;
        }

        private static float DistanceToAxis(Vector3 point, Vector3 a, Vector3 b)
        {
            Vector3 axis = b - a;
            Vector3 onAxis = a + Vector3.Project(point - a, axis);
            Vector3 gap = point - onAxis;
            return gap.magnitude;
        }

        private static string Cm(float meters)
        {
            return (meters * 100f).ToString("F1", CultureInfo.InvariantCulture);
        }

        private static Vector3 Flat(Vector3 v)
        {
            v.y = 0f;
            return v;
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
    }
}

#endif
