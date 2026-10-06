// Crea el set de gestos de Sage (GeniesGestureSet) a partir de
// Assets/Animations/GeniesSage/manifest.json y sus .ozz, y lo engancha en la
// escena: añade GeniesGestureLayer al objeto Sonia (el del coreógrafo) si no lo
// tiene y le asigna el set.
//
// El manifiesto y los .ozz salen de scripts/gestos_genies/descarga_ozz.py (ver
// gestos-genies/README.md). Volver a ejecutar el menú tras bajar clips nuevos:
// el asset se actualiza en su sitio, sin cambiar de GUID.

using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Sonia.EditorTools
{
    /// <summary>Menú Sonia > Gestos de Genies > Crear set de Sage.</summary>
    public static class GeniesGestureSetBuilder
    {
        /// <summary>Carpeta del personaje (manifiesto y .ozz).</summary>
        public const string SageFolder = "Assets/Animations/GeniesSage";

        /// <summary>Asset del set de Sage.</summary>
        public const string SageSetPath = SageFolder + "/SageGestureSet.asset";

        // Papeles de cuerpo entero de Sage, elegidos con su ficha (descripción,
        // frecuencia, etiqueta Deep Idle) y las listas de Genies de Veyra (bored,
        // listen, think; docs/informe-mia.md, 3.4). Se quedan fuera los de mal
        // humor, dormirse o coqueteo, que no pegan en el stand.
        private static readonly string[] SageRestIdle = { "baseIdle03", "baseIdle04", "baseIdle05" };
        private static readonly string[] SageRestListen = { "listeningNod", "listeningTildedNod", "listeningLeaningIn" };
        private static readonly string[] SageRestThink = { "subtleThinkGeneric", "subtleThinkChaotic" };

        private static readonly string[] SageBored =
        {
            "idleCalm", "idleCheckHairOneHand", "idleGeneralMirrored", "handsBehindBack",
            "armsBehindBack", "idleCheckingOutfit", "gentleKeyPose"
        };

        private static readonly string[] SageGreeting = { "waveCalm", "wave02Paris", "goodbyeGeneric" };

        private static readonly string[] SageFourthWall =
        {
            "knockKnock", "waveCalm", "wave02Paris", "peaceSignClip", "thumbsUpCalm"
        };

        // Relleno al hablar: los de relleno de Genies (noImpact) y sus gestos neutros
        // de explicar con las manos a la altura del pecho o la cintura (Standard o
        // Uncommon, LowImpact, sin estilo marcado).
        private static readonly string[] SageTalk =
        {
            "noImpact01", "noImpact02", "noImpact03",
            "3rdPersonHands01", "3rdPersonHands05", "3rdPersonHands08",
            "2ndPersonPoised02_1", "refAbstract01Quick", "refUser03Quick", "subtleExplaination",
            "ofCourse", "openClarify", "smallElaboration02", "3rdPersonPoised02", "3rdPersonPoised04",
            "3rdPrsnHandPoised04", "3rdPersonHandPoised03", "referenceThere01", "RefOpenHandCute",
            "emphasizeShort", "Comprehensive", "listingGesture02"
        };

        [MenuItem("Sonia/Gestos de Genies/Crear set de Sage")]
        public static void BuildSageMenu()
        {
            GeniesGestureSet set = Build(SageFolder, SageSetPath);
            if (set != null)
            {
                AttachToScene(set);
            }
        }

        /// <summary>Crea o actualiza el set de una carpeta con manifest.json y .ozz.</summary>
        public static GeniesGestureSet Build(string folder, string assetPath)
        {
            string manifestPath = folder + "/manifest.json";
            if (!File.Exists(manifestPath))
            {
                Debug.LogError("[Sonia] no está " + manifestPath + " (scripts/gestos_genies/descarga_ozz.py)");
                return null;
            }

            AssetDatabase.Refresh();
            string characterName;
            float transition;
            List<string> files;
            List<GeniesGestureSet.Gesture> gestures = GeniesGestureSet.ParseManifest(
                File.ReadAllText(manifestPath), out characterName, out transition, out files);

            List<GeniesGestureSet.Gesture> ok = new List<GeniesGestureSet.Gesture>();
            List<string> failed = new List<string>();
            int faceTracks = 0;
            for (int i = 0; i < gestures.Count; i++)
            {
                GeniesGestureSet.Gesture g = gestures[i];
                GeniesOzzAsset clip = AssetDatabase.LoadAssetAtPath<GeniesOzzAsset>(folder + "/" + files[i]);
                if (clip == null)
                {
                    failed.Add(g.name + " (sin " + files[i] + ")");
                    continue;
                }

                try
                {
                    GeniesOzzClip decoded = clip.Decode();
                    g.clip = clip;
                    g.duration = decoded.Duration;
                    foreach (GeniesOzzClip.FloatTrack track in decoded.FloatTracks)
                    {
                        if (track.IsAnimated)
                        {
                            faceTracks++;
                        }
                    }

                    ok.Add(g);
                }
                catch (System.FormatException e)
                {
                    failed.Add(g.name + " (" + e.Message + ")");
                }
            }

            GeniesGestureSet set = AssetDatabase.LoadAssetAtPath<GeniesGestureSet>(assetPath);
            bool created = set == null;
            if (created)
            {
                set = ScriptableObject.CreateInstance<GeniesGestureSet>();
            }

            set.character = characterName;
            set.transitionSeconds = transition;
            set.gestures = ok.ToArray();
            // Los papeles solo se rellenan si están vacíos: lo retocado a mano se queda.
            set.restIdle = Roles(set.restIdle, SageRestIdle, set);
            set.restListen = Roles(set.restListen, SageRestListen, set);
            set.restThink = Roles(set.restThink, SageRestThink, set);
            set.bored = Roles(set.bored, SageBored, set);
            set.greeting = Roles(set.greeting, SageGreeting, set);
            set.fourthWall = Roles(set.fourthWall, SageFourthWall, set);
            set.talk = Roles(set.talk, SageTalk, set);
            if (created)
            {
                AssetDatabase.CreateAsset(set, assetPath);
            }

            EditorUtility.SetDirty(set);
            AssetDatabase.SaveAssets();

            Debug.Log("[Sonia] set de gestos de " + characterName + ": " + ok.Count + " gestos (" + faceTracks
                + " curvas de cara animadas), fundido " + transition + " s"
                + (failed.Count > 0 ? "; sin leer: " + string.Join(", ", failed.ToArray()) : ""));
            return set;
        }

        private static string[] Roles(string[] current, string[] defaults, GeniesGestureSet set)
        {
            if (current != null && current.Length > 0)
            {
                return current;
            }

            List<string> found = new List<string>();
            foreach (string name in defaults)
            {
                if (set.Find(name) != null)
                {
                    found.Add(name);
                }
            }

            return found.ToArray();
        }

        /// <summary>Pone GeniesGestureLayer con el set en el objeto Sonia de la escena abierta y la guarda.</summary>
        public static bool AttachToScene(GeniesGestureSet set)
        {
            AvatarChoreographer target = null;
            foreach (AvatarChoreographer choreographer in Object.FindObjectsByType<AvatarChoreographer>(FindObjectsInactive.Include))
            {
                if (choreographer.gameObject.name == "Sonia")
                {
                    target = choreographer;
                    break;
                }
            }

            if (target == null)
            {
                Debug.LogWarning("[Sonia] no encuentro el objeto Sonia con AvatarChoreographer en la escena abierta: añade GeniesGestureLayer a mano.");
                return false;
            }

            GeniesGestureLayer layer = target.GetComponent<GeniesGestureLayer>();
            if (layer == null)
            {
                layer = Undo.AddComponent<GeniesGestureLayer>(target.gameObject);
            }

            SerializedObject so = new SerializedObject(layer);
            so.FindProperty("gestureSet").objectReferenceValue = set;
            so.ApplyModifiedProperties();

            Scene scene = target.gameObject.scene;
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
            Debug.Log("[Sonia] GeniesGestureLayer con " + set.name + " en " + target.name + " (" + scene.path + ")");
            return true;
        }
    }
}
