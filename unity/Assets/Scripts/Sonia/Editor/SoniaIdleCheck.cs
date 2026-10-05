// Comparación de reposos en Play, a paso fijo.
//
// Pone un clip de reposo en bucle sobre el avatar enganchado (o deja que el
// coreógrafo haga lo suyo en un estado), avanza el juego con
// EditorApplication.Step y mide lo que se nota de un reposo: cuánto se balancea
// la cadera, cuánto se mueve la cabeza, si los pies apoyados patinan y si las
// manos se meten en el cuerpo. Guarda fotogramas con tres cámaras: el plano del
// stand (Camera.main) y dos fijas de cuerpo entero, de frente y de lado. Las
// fijas no siguen a la cadera: así el balanceo se ve contra el encuadre.
//
// Uso desde el MCP con Sonia en Play y en pausa (Step no avanza en el mismo
// comando que pide la pausa): RecordClip(...) o RecordState(...). Salida en
// Temp/idlecheck/<etiqueta>/.

#if UNITY_EDITOR

using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Mide y fotografía reposos en el avatar de verdad.</summary>
    public static class SoniaIdleCheck
    {
        /// <summary>Carpeta de salida, relativa al proyecto (Temp no se sube).</summary>
        public const string OutputFolder = "Temp/idlecheck";

        private const float StepSeconds = 0.02f;
        private const float SampleSeconds = 0.1f;

        // Un pie cuenta como apoyado con el tobillo a menos de esto del suelo.
        private const float GroundedAnkleHeight = 0.13f;

        /// <summary>
        /// Pone <paramref name="clipPath"/> en bucle con el avance XZ dentro de la
        /// pose (<paramref name="bakeXZ"/>) o fuera (como lo dejaba el generador del
        /// set), lo graba <paramref name="seconds"/> segundos y devuelve el informe.
        /// Cambia los ajustes del clip en el asset.
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
                return "No hay clip en " + clipPath + ".";
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

                return Record(choreographer, label, clip.name + (bakeXZ ? " (XZ en la pose)" : " (XZ fuera)"), seconds, frameEvery);
            }
            finally
            {
                choreographer.Resume(playing, 0.3f);
            }
        }

        /// <summary>
        /// Deja al coreógrafo en <paramref name="state"/> (con sus bucles, gestos y
        /// capas) y lo graba: así se ve el resultado final, no un clip suelto.
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
            for (int i = 0; i < 40; i++)
            {
                EditorApplication.Step();
            }

            return Record(choreographer, label, "estado " + state, seconds, frameEvery);
        }

        /// <summary>
        /// Ajustes de bucle de un reposo: rotación y altura de la raíz dentro de la
        /// pose, y el avance XZ dentro o fuera. Sin eventos (nadie los recibe).
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

        /// <summary>El coreógrafo de Sonia (con el invitado del Modo Jean en la escena hay dos).</summary>
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
                return "Hace falta Play.";
            }

            if (!EditorApplication.isPaused)
            {
                EditorApplication.isPaused = true;
                return "Play pausado: vuelve a lanzarlo (Step no avanza en el mismo comando que pausa).";
            }

            AvatarChoreographer choreographer = SoniaChoreographer();
            if (choreographer == null || !choreographer.Ready)
            {
                return "No hay coreógrafo listo.";
            }

            Animator animator = choreographer.Player.Animator;
            return animator != null && animator.isHuman ? null : "Sin Animator Humanoid.";
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

            string folder = Path.Combine(OutputFolder, label);
            Directory.CreateDirectory(folder);
            foreach (string old in Directory.GetFiles(folder, "*.png"))
            {
                File.Delete(old);
            }

            // Cámaras fijas de cuerpo entero, a la altura de la cintura y sin seguir a nadie.
            Vector3 center = root.position + Vector3.up * 0.86f;
            Camera front = MakeCamera("SoniaIdleCheck.Frente", center + root.forward * 3.4f, center);
            Camera side = MakeCamera("SoniaIdleCheck.Lado", center + root.right * 3.4f, center);

            CultureInfo inv = CultureInfo.InvariantCulture;
            StringBuilder csv = new StringBuilder("t,cadera_x,cadera_y,cadera_z,cabeza_x,cabeza_y,cabeza_z,cabeza_giro,cabeza_ladeo,pie_izq_apoyado,pie_der_apoyado,mano_izq_cuerpo,mano_der_cuerpo\n");
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

                    // Pie apoyado: se ancla al apoyarlo y se mide cuánto se aleja en horizontal.
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

                    // Mano respecto al eje del tronco (cadera-pecho), en horizontal: por
                    // debajo de unos 12 cm está pegada o dentro de la cadera.
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
                            .Append(Cm(DistanceToAxis(hands[1].position, hips.position, chest.position))).Append('\n');
                    }

                    if (step % frameStride == 0)
                    {
                        string stamp = step.ToString("D4", inv);
                        Render(Camera.main, Path.Combine(folder, "plano_" + stamp + ".png"));
                        Render(front, Path.Combine(folder, "frente_" + stamp + ".png"));
                        Render(side, Path.Combine(folder, "lado_" + stamp + ".png"));
                    }
                }
            }
            finally
            {
                Object.DestroyImmediate(front.gameObject);
                Object.DestroyImmediate(side.gameObject);
            }

            StringBuilder report = new StringBuilder();
            report.Append(label).Append(": ").Append(title).Append(", ").Append(seconds.ToString("F0", inv)).Append(" s. ")
                .Append("Cadera: ").Append(Cm(hipsRange.size.x)).Append(" cm de lado a lado, ")
                .Append(Cm(hipsRange.size.z)).Append(" cm adelante-atrás, ").Append(Cm(hipsRange.size.y)).Append(" cm de alto. ")
                .Append("Cabeza: ").Append(Cm(headRange.size.x)).Append(" cm de lado, giro ")
                .Append((headYaw.y - headYaw.x).ToString("F1", inv)).Append("°, ladeo ")
                .Append((headRoll.y - headRoll.x).ToString("F1", inv)).Append("°. ")
                .Append("Pies apoyados, lo que más patinan: ").Append(Cm(slide[0])).Append(" / ").Append(Cm(slide[1])).Append(" cm. ")
                .Append("Manos, lo más cerca del eje del tronco: ").Append(Cm(handGap[0])).Append(" / ").Append(Cm(handGap[1])).Append(" cm.");
            File.WriteAllText(Path.Combine(folder, "informe.txt"), report + "\n");
            File.WriteAllText(Path.Combine(folder, "muestras.csv"), csv.ToString());
            return report.ToString();
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
