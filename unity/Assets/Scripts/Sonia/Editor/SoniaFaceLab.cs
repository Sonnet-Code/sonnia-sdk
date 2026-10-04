// Laboratorio de cara: render fotograma a fotograma de Sonia hablando.
//
// Monta en la escena del stand un guion (SoniaFaceLabDriver) que hace de
// orquestador sin red, entra en Play y guarda cada fotograma del plano del stand
// y de un primer plano de la cara, más un TSV con los blendshapes, el fonema y
// la pose de cabeza y ojos de cada fotograma, y el audio que sonó. Con eso se
// revisa el lip-sync, las expresiones y los gestos con datos y con imágenes, y
// se monta un vídeo con sonido (scripts/facelab.sh).
//
// Se lanza sin abrir el editor, sobre una copia del proyecto o con el editor
// cerrado (Unity no abre dos veces el mismo proyecto):
//
//   Unity -batchmode -projectPath unity -executeMethod Sonia.EditorTools.SoniaFaceLab.RunFromCommandLine \
//         -facelab-config /ruta/guion.json -logFile /ruta/unity.log
//
// El guion es un JSON con los campos de Config (abajo). "overrides" cambia
// campos de los componentes antes de entrar en Play (mismo formato que
// sonia-tuning.json), para comparar ajustes sin tocar la escena.

#if UNITY_EDITOR

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering.Universal;
using Object = UnityEngine.Object;

namespace Sonia.EditorTools
{
    /// <summary>Prepara la escena con el guion de prueba de la cara y entra en Play.</summary>
    public static class SoniaFaceLab
    {
        private const string ScenePath = "Assets/Scenes/SampleScene.unity";

        /// <summary>Guion de la prueba, tal cual se lee del JSON.</summary>
        [Serializable]
        public class Config
        {
            public string outputDir = "Temp/facelab";
            public int fps = 60;
            public int captureEvery = 1;
            public int standWidth = 540;
            public int standHeight = 960;
            public int closeupSize = 640;
            public float closeupFov = 9f;
            public bool captureStand = true;
            public bool captureCloseup = true;
            public bool loadTuning = true;
            public bool exitWhenDone = true;
            public float audioLatency = 0.35f;
            public float audioLead = 0.1f;
            public float chunkSeconds = 0.1f;
            public float idleAfterPlayback = 0.3f;
            public List<SoniaFaceLabDriver.Step> steps = new List<SoniaFaceLabDriver.Step>();
            public List<Override> overrides = new List<Override>();
        }

        /// <summary>Cambio de un campo de un componente antes de entrar en Play.</summary>
        [Serializable]
        public class Override
        {
            public string component;
            public string field;
            public float value;
        }

        /// <summary>Lanza un guion JSON desde el editor abierto (sin salir al terminar).</summary>
        public static void RunConfigFile(string path)
        {
            if (string.IsNullOrEmpty(path) || !File.Exists(path))
            {
                Debug.LogError("[FaceLab] no existe el guion " + path);
                return;
            }

            Config config = JsonUtility.FromJson<Config>(File.ReadAllText(path));
            config.exitWhenDone = false;
            Run(config);
        }

        /// <summary>Entrada por línea de comandos: -facelab-config guion.json.</summary>
        public static void RunFromCommandLine()
        {
            string[] args = Environment.GetCommandLineArgs();
            string configPath = null;
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == "-facelab-config")
                {
                    configPath = args[i + 1];
                }
            }

            if (string.IsNullOrEmpty(configPath) || !File.Exists(configPath))
            {
                Debug.LogError("[FaceLab] falta -facelab-config con un JSON válido");
                EditorApplication.Exit(2);
                return;
            }

            Config config = JsonUtility.FromJson<Config>(File.ReadAllText(configPath));
            Run(config);
        }

        [MenuItem("Sonia/Laboratorio de cara (Temp/facelab)")]
        private static void RunMenu()
        {
            Config config = new Config { exitWhenDone = false };
            config.steps.Add(new SoniaFaceLabDriver.Step { kind = "state", value = "idle", seconds = 1.5f });
            config.steps.Add(new SoniaFaceLabDriver.Step { kind = "state", value = "listening", seconds = 1.5f });
            config.steps.Add(new SoniaFaceLabDriver.Step { kind = "state", value = "thinking", seconds = 1f });
            Run(config);
        }

        /// <summary>Abre la escena, la prepara con el guion y entra en Play.</summary>
        public static void Run(Config config)
        {
            if (EditorApplication.isPlaying)
            {
                Debug.LogError("[FaceLab] sal de Play antes de lanzar el laboratorio");
                return;
            }

            EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);

            // Sin red: el guion hace de orquestador. Ni cliente ni webcam.
            foreach (SoniaClient client in Object.FindObjectsByType<SoniaClient>(FindObjectsInactive.Include))
            {
                SerializedObject so = new SerializedObject(client);
                so.FindProperty("autoConnect").boolValue = false;
                so.FindProperty("serverUrl").stringValue = "ws://127.0.0.1:9";
                so.ApplyModifiedPropertiesWithoutUndo();
                client.enabled = false;
            }

            foreach (WebcamFrameSender webcam in Object.FindObjectsByType<WebcamFrameSender>(FindObjectsInactive.Include))
            {
                webcam.enabled = false;
            }

            if (!config.loadTuning)
            {
                foreach (SoniaTuningUI tuning in Object.FindObjectsByType<SoniaTuningUI>(FindObjectsInactive.Include))
                {
                    SerializedObject so = new SerializedObject(tuning);
                    SerializedProperty load = so.FindProperty("loadOnStart");
                    if (load != null)
                    {
                        load.boolValue = false;
                        so.ApplyModifiedPropertiesWithoutUndo();
                    }
                }
            }

            ApplyOverrides(config.overrides);

            Camera main = Camera.main;
            Camera closeup = config.captureCloseup && main != null ? CreateCloseupCamera(main) : null;

            GameObject host = new GameObject("FaceLab");
            SoniaFaceLabDriver driver = host.AddComponent<SoniaFaceLabDriver>();
            driver.outputDir = config.outputDir;
            driver.fps = config.fps;
            driver.captureEvery = config.captureEvery;
            driver.standSize = new Vector2Int(config.standWidth, config.standHeight);
            driver.closeupSize = config.closeupSize;
            driver.closeupFov = config.closeupFov;
            driver.captureStand = config.captureStand;
            driver.captureCloseup = config.captureCloseup;
            driver.exitWhenDone = config.exitWhenDone;
            driver.audioLatency = config.audioLatency;
            driver.audioLead = config.audioLead;
            driver.chunkSeconds = config.chunkSeconds;
            driver.idleAfterPlayback = config.idleAfterPlayback;
            driver.steps = config.steps;
            driver.standCamera = main;
            driver.closeupCamera = closeup;

            Debug.Log("[FaceLab] escena preparada, entrando en Play");
            EditorApplication.EnterPlaymode();
        }

        /// <summary>
        /// Copia de la cámara del stand para el primer plano: mismos ajustes de
        /// URP y postprocesado, sin scripts, sin HUD y apagada (se renderiza a
        /// mano).
        /// </summary>
        private static Camera CreateCloseupCamera(Camera main)
        {
            GameObject copy = Object.Instantiate(main.gameObject);
            copy.name = "FaceLabCloseup";
            copy.tag = "Untagged";
            for (int i = copy.transform.childCount - 1; i >= 0; i--)
            {
                Object.DestroyImmediate(copy.transform.GetChild(i).gameObject);
            }

            foreach (MonoBehaviour behaviour in copy.GetComponents<MonoBehaviour>())
            {
                if (!(behaviour is UniversalAdditionalCameraData))
                {
                    Object.DestroyImmediate(behaviour);
                }
            }

            AudioListener listener = copy.GetComponent<AudioListener>();
            if (listener != null)
            {
                Object.DestroyImmediate(listener);
            }

            Camera camera = copy.GetComponent<Camera>();
            UniversalAdditionalCameraData data = camera.GetUniversalAdditionalCameraData();
            if (data != null)
            {
                data.renderType = CameraRenderType.Base;
                data.cameraStack.Clear();
            }

            camera.enabled = false;
            return camera;
        }

        /// <summary>Aplica los cambios de campos (formato de sonia-tuning.json; "campo.x" para vectores).</summary>
        private static void ApplyOverrides(List<Override> overrides)
        {
            if (overrides == null)
            {
                return;
            }

            const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
            foreach (Override change in overrides)
            {
                Type type = Type.GetType("Sonia." + change.component + ", Sonia");
                if (type == null)
                {
                    Debug.LogWarning("[FaceLab] componente desconocido: " + change.component);
                    continue;
                }

                foreach (Object found in Object.FindObjectsByType(type, FindObjectsInactive.Include))
                {
                    string[] parts = change.field.Split('.');
                    FieldInfo field = type.GetField(parts[0], flags);
                    if (field == null)
                    {
                        Debug.LogWarning("[FaceLab] campo desconocido: " + change.component + "." + change.field);
                        break;
                    }

                    object value = field.GetValue(found);
                    if (parts.Length == 1)
                    {
                        if (field.FieldType == typeof(float))
                        {
                            field.SetValue(found, change.value);
                        }
                        else if (field.FieldType == typeof(int))
                        {
                            field.SetValue(found, Mathf.RoundToInt(change.value));
                        }
                        else if (field.FieldType == typeof(bool))
                        {
                            field.SetValue(found, change.value != 0f);
                        }
                    }
                    else if (value is Vector2 v2)
                    {
                        if (parts[1] == "x") { v2.x = change.value; } else { v2.y = change.value; }
                        field.SetValue(found, v2);
                    }
                    else if (value is Vector3 v3)
                    {
                        if (parts[1] == "x") { v3.x = change.value; } else if (parts[1] == "y") { v3.y = change.value; } else { v3.z = change.value; }
                        field.SetValue(found, v3);
                    }

                    Debug.Log("[FaceLab] " + change.component + "." + change.field + " = "
                              + change.value.ToString(CultureInfo.InvariantCulture));
                }
            }
        }
    }
}

#endif
