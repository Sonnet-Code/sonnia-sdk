// Genera el Animator Controller del avatar desde código.
//
// Montar a mano un grafo con casi treinta estados y más de cien transiciones es
// un suplicio y no se puede revisar en un diff. Este menú lo regenera entero a
// partir del catálogo de Sonia.SoniaAnimations, así que añadir un baile nuevo es
// añadir una línea allí y volver a ejecutarlo.
//
// Estructura de la capa base:
//
//   Idle  <->  IdleAlt          bucles de reposo, se alternan cada dos vueltas
//   Listening -> ListeningNod   asentimiento puntual con el trigger Gesture
//   Thinking                    bucle de pensar
//   Speaking0/1/2               tres formas de gesticular al hablar
//   Greeting                    saludo con la mano (trigger Greet)
//   Attention/<clip>            submáquina con los bailes y gestos del idle
//
// El parámetro State manda sobre todo lo demás: cualquier estado sale hacia el
// que toque en cuanto cambia, sin tiempo de salida, así que un baile se corta
// solo en cuanto alguien empieza a hablar.

#if UNITY_EDITOR

using System.Collections.Generic;
using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Sonia.EditorTools
{
    /// <summary>Construye <c>Assets/Animations/SoniaAnimator.controller</c>.</summary>
    public static class SoniaAnimatorBuilder
    {
        /// <summary>Duración estándar de las mezclas entre estados principales.</summary>
        private const float MainDuration = 0.3f;

        /// <summary>Mezcla más corta al entrar en una animación de atención.</summary>
        private const float AttentionDuration = 0.25f;

        /// <summary>Mezcla entre variantes de gesticulación al hablar.</summary>
        private const float GestureDuration = 0.35f;

        /// <summary>Mezcla larga entre los dos idles: no debe notarse el corte.</summary>
        private const float IdleSwapDuration = 0.5f;

        /// <summary>Vueltas completas de un idle antes de cambiar al otro.</summary>
        private const float IdleSwapCycles = 2f;

        /// <summary>Momento del saludo en el que ya se puede volver al estado que toque.</summary>
        private const float GreetingExitTime = 0.9f;

        [MenuItem("Sonia/Crear Animator Controller")]
        public static void CreateAnimatorControllerMenu()
        {
            AnimatorController controller = Build();
            if (controller == null)
            {
                return;
            }

            AssignToSceneAvatar(controller);
            Selection.activeObject = controller;
            EditorGUIUtility.PingObject(controller);
        }

        /// <summary>
        /// Deja los FBX de Mixamo centrados en el avatar.
        ///
        /// Por defecto llegan con "Root Transform Position (XZ) > Based Upon:
        /// Original", y como cada clip trae al personaje desplazado unos
        /// centímetros de su propio origen, el avatar se iba del centro del
        /// encuadre en cuanto empezaba a animarse. Con "Center of Mass" el
        /// desplazamiento se extrae como root motion y, al estar
        /// applyRootMotion desactivado, se descarta: Sonia se queda quieta en el
        /// sitio, que es justo lo que hace falta en un plano fijo.
        /// </summary>
        [MenuItem("Sonia/Centrar animaciones de Mixamo")]
        public static void CenterMixamoClips()
        {
            string[] guids = AssetDatabase.FindAssets("t:Model", new[] { SoniaAnimations.ClipFolder });
            int changed = 0;

            for (int i = 0; i < guids.Length; i++)
            {
                string path = AssetDatabase.GUIDToAssetPath(guids[i]);
                ModelImporter importer = AssetImporter.GetAtPath(path) as ModelImporter;
                if (importer == null)
                {
                    continue;
                }

                ModelImporterClipAnimation[] clips = importer.clipAnimations;
                if (clips == null || clips.Length == 0)
                {
                    clips = importer.defaultClipAnimations;
                }

                bool touched = false;
                for (int c = 0; c < clips.Length; c++)
                {
                    if (clips[c].keepOriginalPositionXZ || clips[c].lockRootPositionXZ)
                    {
                        clips[c].keepOriginalPositionXZ = false;
                        clips[c].lockRootPositionXZ = false;
                        touched = true;
                    }
                }

                if (touched)
                {
                    importer.clipAnimations = clips;
                    importer.SaveAndReimport();
                    changed++;
                }
            }

            Debug.Log(
                "[Sonia] Animaciones de Mixamo centradas: " + changed + " de " + guids.Length
                + " FBX reimportados con Root Transform Position (XZ) en Center of Mass.");
        }

        /// <summary>
        /// Regenera el controlador desde cero y lo devuelve. Si ya existía se borra
        /// primero, así que cualquier retoque hecho a mano en la ventana del
        /// Animator se pierde.
        /// </summary>
        public static AnimatorController Build()
        {
            Dictionary<string, AnimationClip> clips = LoadClips();

            string folder = System.IO.Path.GetDirectoryName(SoniaAnimations.ControllerPath);
            if (!AssetDatabase.IsValidFolder(folder))
            {
                Debug.LogError(
                    "[Sonia] No existe la carpeta " + folder + "; importa primero las animaciones de Mixamo.");
                return null;
            }

            if (AssetDatabase.LoadAssetAtPath<AnimatorController>(SoniaAnimations.ControllerPath) != null)
            {
                AssetDatabase.DeleteAsset(SoniaAnimations.ControllerPath);
            }

            AnimatorController controller =
                AnimatorController.CreateAnimatorControllerAtPath(SoniaAnimations.ControllerPath);

            controller.AddParameter(SoniaAnimations.StateParameter, AnimatorControllerParameterType.Int);
            controller.AddParameter(SoniaAnimations.IdleVariantParameter, AnimatorControllerParameterType.Int);
            controller.AddParameter(SoniaAnimations.AttentionTrigger, AnimatorControllerParameterType.Trigger);
            controller.AddParameter(
                SoniaAnimations.GestureVariantParameter, AnimatorControllerParameterType.Int);
            controller.AddParameter(SoniaAnimations.GestureTrigger, AnimatorControllerParameterType.Trigger);
            controller.AddParameter(SoniaAnimations.GreetTrigger, AnimatorControllerParameterType.Trigger);

            AnimatorStateMachine root = controller.layers[0].stateMachine;
            root.entryPosition = new Vector3(-260f, -60f, 0f);
            root.exitPosition = new Vector3(-260f, 80f, 0f);
            root.anyStatePosition = new Vector3(-260f, 220f, 0f);

            MainStates main = CreateMainStates(root, clips);
            AnimatorState[] attention = CreateAttentionStates(root, clips);

            root.defaultState = main.Idle;

            WireMainStates(main);
            WireAttention(main, attention);

            // El relevo entre los dos idles va el último a propósito: al tener
            // tiempo de salida debe ser la transición de menor prioridad de Idle.
            WireIdleSwap(main);

            EditorUtility.SetDirty(controller);
            AssetDatabase.SaveAssets();

            int missing = 0;
            foreach (KeyValuePair<string, AnimationClip> entry in clips)
            {
                if (entry.Value == null)
                {
                    missing++;
                }
            }

            Debug.Log(
                "[Sonia] Animator Controller generado en " + SoniaAnimations.ControllerPath + ": "
                + (9 + attention.Length) + " estados, " + SoniaAnimations.AttentionClips.Length
                + " animaciones de atención"
                + (missing > 0 ? ", " + missing + " clip(s) sin encontrar (ver avisos)" : "") + ".",
                controller);

            return controller;
        }

        // ------------------------------------------------------------------
        // Estados
        // ------------------------------------------------------------------

        /// <summary>Los estados principales de la capa base, para pasarlos de una pieza.</summary>
        private sealed class MainStates
        {
            public AnimatorState Idle;
            public AnimatorState IdleAlt;
            public AnimatorState Listening;
            public AnimatorState ListeningNod;
            public AnimatorState Thinking;
            public AnimatorState Greeting;
            public AnimatorState[] Speaking;
        }

        private static MainStates CreateMainStates(
            AnimatorStateMachine root,
            Dictionary<string, AnimationClip> clips)
        {
            MainStates main = new MainStates();

            main.Idle = AddState(root, SoniaAnimations.IdleState, clips, SoniaAnimations.IdleClip,
                new Vector3(60f, -60f, 0f));
            main.IdleAlt = AddState(root, SoniaAnimations.IdleAltState, clips, SoniaAnimations.IdleAltClip,
                new Vector3(60f, 40f, 0f));
            main.Greeting = AddState(root, SoniaAnimations.GreetingState, clips, SoniaAnimations.GreetingClip,
                new Vector3(60f, -180f, 0f));

            // El saludo levanta el brazo por encima de la cabeza: pide plano abierto.
            main.Greeting.tag = SoniaAnimations.WideShotTag;

            main.Listening = AddState(root, SoniaAnimations.ListeningState, clips,
                SoniaAnimations.ListeningClip, new Vector3(400f, -180f, 0f));
            main.ListeningNod = AddState(root, SoniaAnimations.ListeningNodState, clips,
                SoniaAnimations.ListeningNodClip, new Vector3(660f, -180f, 0f));
            main.Thinking = AddState(root, SoniaAnimations.ThinkingState, clips, SoniaAnimations.ThinkingClip,
                new Vector3(400f, -80f, 0f));

            main.Speaking = new AnimatorState[SoniaAnimations.SpeakingClips.Length];
            for (int i = 0; i < main.Speaking.Length; i++)
            {
                main.Speaking[i] = AddState(
                    root,
                    SoniaAnimations.SpeakingStatePrefix + i,
                    clips,
                    SoniaAnimations.SpeakingClips[i],
                    new Vector3(400f, 20f + (i * 70f), 0f));
            }

            return main;
        }

        private static AnimatorState[] CreateAttentionStates(
            AnimatorStateMachine root,
            Dictionary<string, AnimationClip> clips)
        {
            AnimatorStateMachine machine = root.AddStateMachine(
                SoniaAnimations.AttentionStateMachine, new Vector3(60f, 180f, 0f));
            machine.entryPosition = new Vector3(-260f, 0f, 0f);
            machine.exitPosition = new Vector3(-260f, 120f, 0f);
            machine.anyStatePosition = new Vector3(-260f, 240f, 0f);

            AttentionClip[] catalogue = SoniaAnimations.AttentionClips;
            AnimatorState[] states = new AnimatorState[catalogue.Length];
            for (int i = 0; i < catalogue.Length; i++)
            {
                Vector3 position = new Vector3(60f + ((i / 9) * 320f), -160f + ((i % 9) * 60f), 0f);
                states[i] = AddState(machine, catalogue[i].Name, clips, catalogue[i].Name, position);

                // Bailes y gestos ocupan mucho más que el plano medio: la cámara
                // se abre mientras dure el estado.
                states[i].tag = SoniaAnimations.WideShotTag;
            }

            return states;
        }

        private static AnimatorState AddState(
            AnimatorStateMachine machine,
            string stateName,
            Dictionary<string, AnimationClip> clips,
            string clipName,
            Vector3 position)
        {
            AnimatorState state = machine.AddState(stateName, position);

            AnimationClip clip;
            if (clips.TryGetValue(clipName, out clip) && clip != null)
            {
                state.motion = clip;
            }

            return state;
        }

        // ------------------------------------------------------------------
        // Transiciones
        // ------------------------------------------------------------------

        private static void WireMainStates(MainStates main)
        {
            // Idle: cambios de estado, saludo, atención y, por último, el relevo
            // con el idle alternativo. El orden importa: Unity coge la primera
            // transición cuyas condiciones se cumplen.
            AddStateChanges(main, main.Idle, AvatarState.Idle);
            AddGreetEntry(main, main.Idle);

            AddStateChanges(main, main.IdleAlt, AvatarState.Idle);
            AddGreetEntry(main, main.IdleAlt);

            // Escuchar: asentimiento ocasional y vuelta por tiempo de salida.
            AddStateChanges(main, main.Listening, AvatarState.Listening);
            AddGreetEntry(main, main.Listening);
            AnimatorStateTransition toNod = Connect(main.Listening, main.ListeningNod, MainDuration, false, 0f);
            Trigger(toNod, SoniaAnimations.GestureTrigger);

            AddStateChanges(main, main.ListeningNod, AvatarState.Listening);
            Connect(main.ListeningNod, main.Listening, MainDuration, true, 1f);

            AddStateChanges(main, main.Thinking, AvatarState.Thinking);

            // Hablar: se entra por GestureVariant y se salta entre las tres
            // variantes con el trigger Gesture en cada frase nueva.
            for (int i = 0; i < main.Speaking.Length; i++)
            {
                AddStateChanges(main, main.Speaking[i], AvatarState.Speaking);

                for (int j = 0; j < main.Speaking.Length; j++)
                {
                    if (i == j)
                    {
                        continue;
                    }

                    AnimatorStateTransition swap =
                        Connect(main.Speaking[i], main.Speaking[j], GestureDuration, false, 0f);
                    Trigger(swap, SoniaAnimations.GestureTrigger);
                    IntEquals(swap, SoniaAnimations.GestureVariantParameter, j);
                }
            }

            // Saludo: se corta en seco si toca pensar o hablar, y se deja terminar
            // si solo hay que volver al idle o a escuchar.
            AnimatorStateTransition greetToThinking =
                Connect(main.Greeting, main.Thinking, MainDuration, false, 0f);
            IntEquals(greetToThinking, SoniaAnimations.StateParameter, (int)AvatarState.Thinking);

            for (int i = 0; i < main.Speaking.Length; i++)
            {
                AnimatorStateTransition greetToSpeaking =
                    Connect(main.Greeting, main.Speaking[i], MainDuration, false, 0f);
                IntEquals(greetToSpeaking, SoniaAnimations.StateParameter, (int)AvatarState.Speaking);
                IntEquals(greetToSpeaking, SoniaAnimations.GestureVariantParameter, i);
            }

            AnimatorStateTransition greetToListening =
                Connect(main.Greeting, main.Listening, MainDuration, true, GreetingExitTime);
            IntEquals(greetToListening, SoniaAnimations.StateParameter, (int)AvatarState.Listening);

            AnimatorStateTransition greetToIdle =
                Connect(main.Greeting, main.Idle, MainDuration, true, GreetingExitTime);
            IntEquals(greetToIdle, SoniaAnimations.StateParameter, (int)AvatarState.Idle);
        }

        /// <summary>
        /// Alterna los dos bucles de reposo cada dos vueltas para que no se note
        /// que es siempre la misma animación.
        /// </summary>
        private static void WireIdleSwap(MainStates main)
        {
            AnimatorStateTransition toAlt =
                Connect(main.Idle, main.IdleAlt, IdleSwapDuration, true, IdleSwapCycles);
            IntEquals(toAlt, SoniaAnimations.StateParameter, (int)AvatarState.Idle);

            AnimatorStateTransition toIdle =
                Connect(main.IdleAlt, main.Idle, IdleSwapDuration, true, IdleSwapCycles);
            IntEquals(toIdle, SoniaAnimations.StateParameter, (int)AvatarState.Idle);
        }

        private static void WireAttention(MainStates main, AnimatorState[] attention)
        {
            AttentionClip[] catalogue = SoniaAnimations.AttentionClips;

            for (int i = 0; i < attention.Length; i++)
            {
                // Entrada desde los dos idles con el trigger Attention y el índice.
                AnimatorStateTransition fromIdle =
                    Connect(main.Idle, attention[i], AttentionDuration, false, 0f);
                Trigger(fromIdle, SoniaAnimations.AttentionTrigger);
                IntEquals(fromIdle, SoniaAnimations.IdleVariantParameter, catalogue[i].Index);

                AnimatorStateTransition fromIdleAlt =
                    Connect(main.IdleAlt, attention[i], AttentionDuration, false, 0f);
                Trigger(fromIdleAlt, SoniaAnimations.AttentionTrigger);
                IntEquals(fromIdleAlt, SoniaAnimations.IdleVariantParameter, catalogue[i].Index);

                // Salida inmediata si alguien habla: los bailes son bucles y no se
                // pueden dejar a su aire.
                AddStateChanges(main, attention[i], AvatarState.Idle);

                // Y, si nadie interrumpe, vuelta al idle tras una vuelta completa.
                // Sin condiciones: es la salida de seguridad de los bucles.
                Connect(attention[i], main.Idle, MainDuration, true, 1f);
            }
        }

        /// <summary>
        /// Añade las transiciones que reaccionan al parámetro State. Se omite la
        /// familia a la que ya pertenece el estado de origen para no reentrar en
        /// bucle en la misma animación.
        /// </summary>
        private static void AddStateChanges(MainStates main, AnimatorState from, AvatarState own)
        {
            if (own != AvatarState.Idle)
            {
                AnimatorStateTransition toIdle = Connect(from, main.Idle, MainDuration, false, 0f);
                IntEquals(toIdle, SoniaAnimations.StateParameter, (int)AvatarState.Idle);
            }

            if (own != AvatarState.Listening)
            {
                AnimatorStateTransition toListening = Connect(from, main.Listening, MainDuration, false, 0f);
                IntEquals(toListening, SoniaAnimations.StateParameter, (int)AvatarState.Listening);
            }

            if (own != AvatarState.Thinking)
            {
                AnimatorStateTransition toThinking = Connect(from, main.Thinking, MainDuration, false, 0f);
                IntEquals(toThinking, SoniaAnimations.StateParameter, (int)AvatarState.Thinking);
            }

            if (own != AvatarState.Speaking)
            {
                for (int i = 0; i < main.Speaking.Length; i++)
                {
                    AnimatorStateTransition toSpeaking =
                        Connect(from, main.Speaking[i], MainDuration, false, 0f);
                    IntEquals(toSpeaking, SoniaAnimations.StateParameter, (int)AvatarState.Speaking);
                    IntEquals(toSpeaking, SoniaAnimations.GestureVariantParameter, i);
                }
            }
        }

        private static void AddGreetEntry(MainStates main, AnimatorState from)
        {
            AnimatorStateTransition transition = Connect(from, main.Greeting, MainDuration, false, 0f);
            Trigger(transition, SoniaAnimations.GreetTrigger);
        }

        private static AnimatorStateTransition Connect(
            AnimatorState from,
            AnimatorState to,
            float duration,
            bool hasExitTime,
            float exitTime)
        {
            AnimatorStateTransition transition = from.AddTransition(to);
            transition.hasExitTime = hasExitTime;
            transition.exitTime = exitTime;
            transition.hasFixedDuration = true;
            transition.duration = duration;
            transition.offset = 0f;
            transition.canTransitionToSelf = false;

            // "Next State": una transición en curso se puede cortar por otra del
            // estado de destino, que es lo que hace que los cambios de estado
            // encadenados se sientan inmediatos.
            transition.interruptionSource = TransitionInterruptionSource.Destination;
            transition.orderedInterruption = true;
            return transition;
        }

        private static void IntEquals(AnimatorStateTransition transition, string parameter, int value)
        {
            transition.AddCondition(AnimatorConditionMode.Equals, value, parameter);
        }

        private static void Trigger(AnimatorStateTransition transition, string parameter)
        {
            transition.AddCondition(AnimatorConditionMode.If, 0f, parameter);
        }

        // ------------------------------------------------------------------
        // Clips
        // ------------------------------------------------------------------

        /// <summary>
        /// Carga todos los clips que hacen falta desde los FBX de Mixamo. Cada FBX
        /// contiene un clip con el mismo nombre que el archivo.
        /// </summary>
        private static Dictionary<string, AnimationClip> LoadClips()
        {
            List<string> names = new List<string>
            {
                SoniaAnimations.IdleClip,
                SoniaAnimations.IdleAltClip,
                SoniaAnimations.ListeningClip,
                SoniaAnimations.ListeningNodClip,
                SoniaAnimations.ThinkingClip,
                SoniaAnimations.GreetingClip
            };
            names.AddRange(SoniaAnimations.SpeakingClips);
            for (int i = 0; i < SoniaAnimations.AttentionClips.Length; i++)
            {
                names.Add(SoniaAnimations.AttentionClips[i].Name);
            }

            Dictionary<string, AnimationClip> clips = new Dictionary<string, AnimationClip>();
            for (int i = 0; i < names.Count; i++)
            {
                string name = names[i];
                if (clips.ContainsKey(name))
                {
                    continue;
                }

                AnimationClip clip = LoadClip(name);
                if (clip == null)
                {
                    Debug.LogWarning(
                        "[Sonia] No se encontró el clip \"" + name + "\" en "
                        + SoniaAnimations.ClipFolder + "/" + name + ".fbx; su estado quedará vacío.");
                }

                clips[name] = clip;
            }

            return clips;
        }

        private static AnimationClip LoadClip(string name)
        {
            string path = SoniaAnimations.ClipFolder + "/" + name + ".fbx";
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

            return fallback;
        }

        // ------------------------------------------------------------------
        // Escena
        // ------------------------------------------------------------------

        /// <summary>
        /// Vuelve a asignar el controlador al avatar de la escena abierta. Hace
        /// falta porque regenerar el asset lo borra y deja el Animator vacío.
        /// </summary>
        public static void AssignToSceneAvatar(AnimatorController controller)
        {
            Scene scene = SceneManager.GetActiveScene();
            if (!scene.IsValid() || !scene.isLoaded)
            {
                return;
            }

            GameObject[] roots = scene.GetRootGameObjects();
            bool changed = false;
            for (int i = 0; i < roots.Length; i++)
            {
                SoniaBootstrap bootstrap = roots[i].GetComponentInChildren<SoniaBootstrap>(true);
                if (bootstrap == null)
                {
                    continue;
                }

                Animator[] animators = bootstrap.GetComponentsInChildren<Animator>(true);
                for (int j = 0; j < animators.Length; j++)
                {
                    if (animators[j].runtimeAnimatorController == controller)
                    {
                        continue;
                    }

                    Undo.RecordObject(animators[j], "Asignar Animator Controller de Sonia");
                    animators[j].runtimeAnimatorController = controller;
                    EditorUtility.SetDirty(animators[j]);
                    changed = true;
                }
            }

            if (changed)
            {
                EditorSceneManager.MarkSceneDirty(scene);
            }
        }
    }
}

#endif
