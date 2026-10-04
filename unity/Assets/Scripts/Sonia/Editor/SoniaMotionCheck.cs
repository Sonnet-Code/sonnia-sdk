// Comprobación de animaciones en Play, fotograma a fotograma.
//
// Reproduce clips del set en el avatar enganchado (el del SDK de Genies o el
// doble), avanza el juego a paso fijo con EditorApplication.Step y en cada
// muestra mide piernas y orientación y guarda una captura de frente (la cámara
// del stand) y otra de lado. Sirve para validar cualquier clip contra los
// oficiales de Genies antes de meterlo en SoniaAnimations: una rodilla que
// dobla hacia delante, un pie girado o un cuerpo que da la espalda salen en el
// informe sin mirar los fotogramas uno a uno.
//
// Uso, con Sonia en Play: Sonia > Comprobar animaciones (en Play). La primera
// vez solo pausa (EditorApplication.Step no avanza en el mismo comando que pide
// la pausa); la segunda hace la comprobación. Salida en Temp/motioncheck/.

#if UNITY_EDITOR

using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Mide los clips del set en el avatar de verdad y guarda fotogramas de frente y de lado.</summary>
    public static class SoniaMotionCheck
    {
        /// <summary>Carpeta de salida, relativa al proyecto.</summary>
        public const string OutputFolder = "Temp/motioncheck";

        /// <summary>Segundos entre muestras (EditorApplication.Step avanza 0,02 s).</summary>
        private const float SampleSeconds = 0.1f;

        private const float StepSeconds = 0.02f;

        /// <summary>Una rodilla que dobla (más de 8°) y queda por detrás de la línea cadera-tobillo está al revés.</summary>
        private const float KneeBendDegrees = 8f;

        private const float KneeBackwardCm = 1.5f;

        /// <summary>Pie girado respecto a donde mira el cuerpo.</summary>
        private const float FootTurnDegrees = 60f;

        /// <summary>Cuerpo girado respecto a la cámara (dar la espalda al visitante no sirve en un stand).</summary>
        private const float BodyTurnDegrees = 80f;

        [MenuItem("Sonia/Comprobar animaciones (en Play)")]
        public static void CheckAllMenu()
        {
            Debug.Log(CheckAll());
        }

        /// <summary>Comprueba todos los clips distintos del set. Devuelve el informe.</summary>
        public static string CheckAll()
        {
            string blocked = Precondition();
            if (blocked != null)
            {
                return blocked;
            }

            AvatarChoreographer choreographer = Object.FindAnyObjectByType<AvatarChoreographer>();

            // El set del proyecto, no el del coreógrafo: con el modo debug o con
            // animaciones desactivadas en el panel, el coreógrafo lleva una copia recortada.
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

            string summary = "[Sonia] Comprobación de animaciones: " + clips.Count + " clips, " + failed
                             + " con problemas. Fotogramas e informe en " + Path.GetFullPath(OutputFolder) + ".";
            report.Insert(0, summary + "\n");
            Directory.CreateDirectory(OutputFolder);
            File.WriteAllText(Path.Combine(OutputFolder, "informe.txt"), report.ToString());
            return report.ToString();
        }

        /// <summary>
        /// Comprueba todos los clips de las carpetas de SoniaAnimations.ClipFolders,
        /// estén o no en el set: es como se validan los candidatos antes de usarlos.
        /// </summary>
        public static string CheckFolders()
        {
            string blocked = Precondition();
            if (blocked != null)
            {
                return blocked;
            }

            AvatarChoreographer choreographer = Object.FindAnyObjectByType<AvatarChoreographer>();
            List<AnimationClip> clips = new List<AnimationClip>();
            foreach (string guid in AssetDatabase.FindAssets("t:AnimationClip", SoniaAnimations.ClipFolders))
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

            report.Insert(0, "[Sonia] Comprobación de las carpetas de clips: " + clips.Count + " clips, " + failed
                             + " con problemas. Fotogramas en " + Path.GetFullPath(OutputFolder) + ".\n");
            Directory.CreateDirectory(OutputFolder);
            File.WriteAllText(Path.Combine(OutputFolder, "informe-carpetas.txt"), report.ToString());
            return report.ToString();
        }

        /// <summary>Comprueba un clip del set por su nombre. Devuelve el informe.</summary>
        public static string CheckClip(string clipName)
        {
            string blocked = Precondition();
            if (blocked != null)
            {
                return blocked;
            }

            AvatarChoreographer choreographer = Object.FindAnyObjectByType<AvatarChoreographer>();
            SoniaMotionSet set = AssetDatabase.LoadAssetAtPath<SoniaMotionSet>(SoniaAnimations.MotionSetPath);
            AnimationClip clip = FindInSet(set != null ? set : choreographer.MotionSet, clipName);
            if (clip == null)
            {
                return "[Sonia] El set no tiene ningún clip llamado " + clipName + ".";
            }

            bool ok;
            return Check(choreographer, clip, out ok);
        }

        private static string Precondition()
        {
            if (!EditorApplication.isPlaying)
            {
                return "[Sonia] Comprobar animaciones solo funciona en Play.";
            }

            if (!EditorApplication.isPaused)
            {
                EditorApplication.isPaused = true;
                return "[Sonia] Play pausado. Vuelve a lanzar la comprobación (Step no avanza en el mismo comando que pausa).";
            }

            AvatarChoreographer choreographer = Object.FindAnyObjectByType<AvatarChoreographer>();
            if (choreographer == null || choreographer.MotionSet == null || !choreographer.Ready)
            {
                return "[Sonia] No hay coreógrafo listo en la escena.";
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
                return clip.name + ": sin Animator Humanoid.\n";
            }

            Transform root = animator.transform;
            string folder = Path.Combine(OutputFolder, clip.name);
            Directory.CreateDirectory(folder);
            foreach (string old in Directory.GetFiles(folder, "*.png"))
            {
                File.Delete(old);
            }

            // El coreógrafo se aparta (como cuando la presencia camina) y el clip
            // suena solo en el cuerpo: Preview no sirve para los bucles, porque en
            // reposo el coreógrafo vuelve a poner su bucle base en cada fotograma.
            choreographer.Suspend();
            MotionPlayer.Handle playing = choreographer.Player.Play(clip, MotionPlayer.BodyLayer, 0.1f);

            // Se deja entrar el fundido antes de medir.
            for (int i = 0; i < 15; i++)
            {
                EditorApplication.Step();
            }

            float seconds = clip.isLooping ? clip.length : clip.length + 0.3f;
            int steps = Mathf.CeilToInt(seconds / StepSeconds);
            int every = Mathf.Max(1, Mathf.RoundToInt(SampleSeconds / StepSeconds));
            Camera side = new GameObject("SoniaMotionCheck.Lateral").AddComponent<Camera>();
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
                        .Append("  rodilla izq ").Append(kneeL.ToString("+0.0;-0.0", inv)).Append(" cm (").Append(bendL.ToString("F0", inv)).Append("°)")
                        .Append("  der ").Append(kneeR.ToString("+0.0;-0.0", inv)).Append(" cm (").Append(bendR.ToString("F0", inv)).Append("°)")
                        .Append("  pies ").Append(footL.ToString("F0", inv)).Append("°/").Append(footR.ToString("F0", inv)).Append("°")
                        .Append("  cuerpo ").Append(body.ToString("F0", inv)).Append("°\n");

                    CheckKnee(problems, "izquierda", t, kneeL, bendL);
                    CheckKnee(problems, "derecha", t, kneeR, bendR);
                    if (Mathf.Max(footL, footR) > FootTurnDegrees)
                    {
                        problems.Add("pie girado " + Mathf.Max(footL, footR).ToString("F0", inv) + "° en t=" + t.ToString("F2", inv));
                    }

                    if (body > BodyTurnDegrees)
                    {
                        problems.Add("cuerpo girado " + body.ToString("F0", inv) + "° respecto a la cámara en t=" + t.ToString("F2", inv));
                    }

                    worstKnee = Mathf.Min(worstKnee, Mathf.Min(bendL > KneeBendDegrees ? kneeL : 0f, bendR > KneeBendDegrees ? kneeR : 0f));
                    worstFoot = Mathf.Max(worstFoot, Mathf.Max(footL, footR));
                    worstBody = Mathf.Max(worstBody, body);

                    string stamp = step.ToString("D3", inv);
                    Render(Camera.main, Path.Combine(folder, "frente_" + stamp + ".png"));
                    Vector3 pelvis = hips.position;
                    side.transform.position = pelvis + root.right * 2.4f + Vector3.up * 0.05f;
                    side.transform.LookAt(pelvis + Vector3.down * 0.25f);
                    Render(side, Path.Combine(folder, "lado_" + stamp + ".png"));
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
                .Append(clip.isLooping ? ", bucle" : string.Empty).Append("): ")
                .Append(ok ? "bien" : "PROBLEMAS: " + string.Join("; ", Distinct(problems)))
                .Append(". Peor rodilla ").Append((worstKnee == float.MaxValue ? 0f : worstKnee).ToString("+0.0;-0.0", inv))
                .Append(" cm, peor pie ").Append(worstFoot.ToString("F0", inv)).Append("°, cuerpo hasta ")
                .Append(worstBody.ToString("F0", inv)).Append("°.\n");
            report.Append(lines);
            return report.ToString();
        }

        /// <summary>
        /// Rodilla respecto a la línea cadera-tobillo y giro del pie. El giro solo
        /// cuenta con el pie en el suelo: levantado (una patadita hacia atrás) mira
        /// adonde quiera sin que sea un error.
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
                problems.Add("rodilla " + side + " al revés (" + aheadCm.ToString("F1", CultureInfo.InvariantCulture)
                             + " cm, " + bend.ToString("F0", CultureInfo.InvariantCulture) + "°) en t="
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
                string kind = item.Split(new[] { " en t=" }, System.StringSplitOptions.None)[0];
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
