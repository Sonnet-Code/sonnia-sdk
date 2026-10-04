// Copia local del avatar del SDK de Genies: se rehace sola cada vez que Sonia
// cambia de avatar en el editor de Unity, y también a mano con "Sonia >
// Actualizar copia del avatar del SDK".
//
// El SDK solo compone el avatar en Play (sesión, descargas, montaje nativo), así
// que sin copia en modo edición se veía el doble (Sticker) y al darle a Play, a
// los pocos segundos, Sonia cambiaba de cara. La copia es el avatar ya montado
// guardado como un prefab normal en Assets/Sonia/Avatar/<definición>/, colocado
// en la escena del stand con Sonia > Colocar avatar: se ve en modo edición y
// GeniesAvatarLoader no vuelve a cargarlo mientras Sonia lleve esa definición.
//
// Cuándo se rehace (siempre en el editor de Unity, nunca en una build):
//
//  * Sola: cuando en Play Sonia se pone un avatar del SDK que no tiene copia (lo
//    mandó el orquestador con set_avatar tras guardarlo en el editor de
//    personaje, o era el último recordado), se escribe su definición en
//    SoniaGeniesAvatar.json y se copia en cuanto es seguro: el avatar lleva un
//    momento puesto, no hay otra carga en marcha, el editor de personaje está
//    cerrado y Sonia está callada (o lleva hablando demasiado). Si se sale de
//    Play antes, se vuelve a entrar un momento para hacerla (una vez por
//    cambio). Al volver a modo edición la copia se coloca en la escena del stand
//    y se guarda la escena, sin diálogos.
//  * A mano: el menú entra en Play pidiendo al cargador el avatar del SDK aunque
//    haya copia, lo copia, sale de Play y lo coloca.
//
// Qué se guarda en la copia y cómo: SoniaGeniesSnapshot.Capture.cs.

#if UNITY_EDITOR

using System;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace Sonia.EditorTools
{
    /// <summary>Guarda el avatar que monta el SDK de Genies como prefab y lo pone en la escena.</summary>
    [InitializeOnLoad]
    public static partial class SoniaGeniesSnapshot
    {
        public const string MenuPath = "Sonia/Actualizar copia del avatar del SDK";

        private const string PhaseKey = "Sonia.Genies.SnapshotPhase";
        private const string StartedKey = "Sonia.Genies.SnapshotStarted";
        private const string HashKey = "Sonia.Genies.SnapshotHash";
        private const string DueKey = "Sonia.Genies.SnapshotDue";
        private const string SceneKey = "Sonia.Genies.SnapshotScene";
        private const string ReplayKey = "Sonia.Genies.SnapshotReplayed";
        private const string PlaceKey = "Sonia.Genies.SnapshotToPlace";
        private const string ReplayPendingKey = "Sonia.Genies.SnapshotReplayPending";

        /// <summary>A mano: esperar al avatar del SDK, copiarlo y salir de Play.</summary>
        private const string PhaseCapture = "capture";

        /// <summary>Sola: Sonia lleva un avatar del SDK sin copia; se copia en cuanto sea seguro, sin salir de Play.</summary>
        private const string PhasePending = "pending";

        /// <summary>Tiempo máximo para que el SDK entregue el avatar (la primera vez descarga todo).</summary>
        private const float LoadTimeoutSeconds = 300f;

        /// <summary>Espera tras poner el avatar para que el rig de la cara y las físicas ya hayan corrido.</summary>
        private const float SettleSeconds = 1f;

        /// <summary>Lo más que se espera a que Sonia se calle antes de copiar igualmente.</summary>
        private const float QuietWaitSeconds = 30f;

        private static string _phase;

        /// <summary>Hay copia sin colocar pero la escena del stand no está abierta y hay escenas sin guardar.</summary>
        private static bool _placeDeferred;

        static SoniaGeniesSnapshot()
        {
            _phase = SessionState.GetString(PhaseKey, string.Empty);
            EditorApplication.update += Tick;
            EditorApplication.playModeStateChanged += OnPlayModeChanged;
            EditorSceneManager.sceneOpened += OnSceneOpened;
            GeniesAvatarLoader.AvatarShown += OnAvatarShown;
        }

        /// <summary>Carpeta de la copia: junto a la definición y con su nombre.</summary>
        public static string SnapshotFolder
        {
            get { return SoniaAvatarSetup.GeniesDefinitionPath.Substring(0, SoniaAvatarSetup.GeniesDefinitionPath.Length - Path.GetExtension(SoniaAvatarSetup.GeniesDefinitionPath).Length); }
        }

        /// <summary>Prefab de la copia.</summary>
        public static string SnapshotPrefabPath
        {
            get { return SnapshotFolder + "/" + Path.GetFileName(SnapshotFolder) + ".prefab"; }
        }

        private static float Now
        {
            get { return (float)EditorApplication.timeSinceStartup; }
        }

        // ------------------------------------------------------------------
        // A mano: menú y flujo de un clic
        // ------------------------------------------------------------------

        [MenuItem(MenuPath, false, 30)]
        private static void UpdateSnapshotMenu()
        {
            if (EditorApplication.isCompiling || EditorApplication.isUpdating)
            {
                EditorUtility.DisplayDialog("Sonia", "Unity está compilando. Vuelve a probar cuando termine.", "Vale");
                return;
            }

            if (AssetDatabase.LoadAssetAtPath<TextAsset>(SoniaAvatarSetup.GeniesDefinitionPath) == null)
            {
                EditorUtility.DisplayDialog("Sonia", "No se encontró la definición " + SoniaAvatarSetup.GeniesDefinitionPath + ".", "Vale");
                return;
            }

            Begin();
        }

        /// <summary>
        /// Empieza la copia del avatar que lleva Sonia. Fuera de Play abre la
        /// escena del stand si hace falta y entra en Play pidiendo al cargador el
        /// avatar del SDK aunque ya haya copia; en Play copia el que hay o lo carga.
        /// </summary>
        public static void Begin()
        {
            Begin(true);
        }

        /// <summary>
        /// Deja pedida la copia: si se está en Play, se hace al volver a modo
        /// edición (entrando un momento en Play); si no, ahora.
        /// </summary>
        public static void RequestAfterPlay()
        {
            if (!EditorApplication.isPlayingOrWillChangePlaymode)
            {
                Begin(false);
                return;
            }

            SessionState.SetString(HashKey, string.Empty);
            SessionState.SetBool(ReplayKey, false);
            SetPhase(PhasePending);
        }

        private static void Begin(bool interactive)
        {
            SessionState.SetFloat(StartedKey, Now);
            SessionState.SetString(HashKey, string.Empty);
            SessionState.SetFloat(DueKey, 0f);
            if (interactive)
            {
                SessionState.SetBool(ReplayKey, false);
            }

            if (EditorApplication.isPlaying)
            {
                SessionState.SetBool(GeniesAvatarLoader.ForceLiveSessionKey, true);
                SetPhase(PhaseCapture);
                GeniesAvatarLoader loader = Object.FindAnyObjectByType<GeniesAvatarLoader>();
                if (loader != null && loader.IsLoaded)
                {
                    // Ya hay un avatar del SDK puesto: se copia ese.
                    SessionState.SetString(HashKey, loader.ShownDefinitionHash);
                    SessionState.SetFloat(DueKey, Now);
                }
                else if (loader != null)
                {
                    loader.Load();
                }

                Debug.Log("[Sonia] Copia del avatar: esperando al avatar del SDK.");
                return;
            }

            if (interactive && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
            {
                Finish("cancelado: la escena tiene cambios sin guardar", false);
                return;
            }

            if (Object.FindAnyObjectByType<GeniesAvatarLoader>() == null && !OpenStandScene())
            {
                Finish("no se pudo abrir " + StandScenePath() + " (hay escenas con cambios sin guardar)", false);
                return;
            }

            SessionState.SetBool(GeniesAvatarLoader.ForceLiveSessionKey, true);
            SetPhase(PhaseCapture);
            Debug.Log("[Sonia] Copia del avatar: entrando en Play para que el SDK monte el avatar.");
            EditorApplication.EnterPlaymode();
        }

        // ------------------------------------------------------------------
        // Sola: cada vez que Sonia cambia de avatar en Play
        // ------------------------------------------------------------------

        /// <summary>Sonia acaba de ponerse un avatar (del SDK o la copia local).</summary>
        private static void OnAvatarShown(GeniesAvatarLoader loader, string json, bool live)
        {
            if (!EditorApplication.isPlaying || loader == null || string.IsNullOrEmpty(json))
            {
                return;
            }

            // Esta copia es la de Sonia: el avatar del invitado del Modo Jean no la toca.
            if (loader.Role != AvatarRole.Sonia)
            {
                return;
            }

            SessionState.SetString(SceneKey, loader.gameObject.scene.path);

            // La app arranca con el avatar que lleva Sonia: su definición pasa a ser
            // SoniaGeniesAvatar.json (la de set_avatar null y la de las builds).
            SyncDefinitionFile(json);

            bool manual = _phase == PhaseCapture;
            GeniesAvatarSnapshot onDisk = SnapshotOnDisk();
            bool upToDate = onDisk != null && onDisk.Matches(json);
            if (!live || (upToDate && !manual))
            {
                // Lleva la copia o un avatar que ya la tiene: no hay nada que rehacer.
                if (_phase == PhasePending)
                {
                    SetPhase(string.Empty);
                }

                return;
            }

            SessionState.SetString(HashKey, GeniesAvatarSnapshot.HashDefinition(json));
            SessionState.SetFloat(DueKey, Now + SettleSeconds);
            if (!manual)
            {
                SessionState.SetBool(ReplayKey, false);
                SetPhase(PhasePending);
                Debug.Log("[Sonia] Copia del avatar: Sonia lleva un avatar sin copia; se copia en cuanto esté quieta.");
            }
        }

        /// <summary>
        /// Cada vuelta del editor. Lo de modo edición (volver a entrar en Play,
        /// colocar la copia) va aquí y no en EditorApplication.delayCall, que con
        /// Unity en segundo plano puede tardar mucho en llegar.
        /// </summary>
        private static void Tick()
        {
            if (_phase == PhaseCapture)
            {
                TickManual();
                return;
            }

            if (_phase == PhasePending)
            {
                TickPending();
                return;
            }

            if (EditorApplication.isPlayingOrWillChangePlaymode || EditorApplication.isCompiling || EditorApplication.isUpdating)
            {
                return;
            }

            if (SessionState.GetBool(ReplayPendingKey, false))
            {
                SessionState.SetBool(ReplayPendingKey, false);
                Begin(false);
                return;
            }

            if (!_placeDeferred && SessionState.GetBool(PlaceKey, false))
            {
                PlacePending();
            }
        }

        private static void TickManual()
        {
            float now = Now;
            float started = SessionState.GetFloat(StartedKey, now);
            if (!EditorApplication.isPlayingOrWillChangePlaymode)
            {
                // No llegó a entrar en Play (errores de compilación, cancelado).
                if (now - started > 20f)
                {
                    Finish("cancelado: no se pudo entrar en Play", false);
                }

                return;
            }

            if (!EditorApplication.isPlaying || EditorApplication.isCompiling)
            {
                return;
            }

            if (now - started > LoadTimeoutSeconds)
            {
                Finish("el SDK no entregó el avatar en " + LoadTimeoutSeconds.ToString("F0") + " s; mira la consola", true);
                return;
            }

            GeniesAvatarLoader loader = ReadyLoader();
            if (loader == null)
            {
                return;
            }

            if (!CaptureNow(loader))
            {
                Finish("no se pudo guardar la copia; mira la consola", true);
                return;
            }

            SetPhase(string.Empty);
            SessionState.SetBool(GeniesAvatarLoader.ForceLiveSessionKey, false);
            EditorApplication.ExitPlaymode();
        }

        private static void TickPending()
        {
            if (!EditorApplication.isPlaying || EditorApplication.isCompiling || AvatarEditorSession.IsOpen)
            {
                return;
            }

            GeniesAvatarLoader loader = ReadyLoader();
            if (loader == null)
            {
                return;
            }

            // Copiar congela el editor unos segundos: mejor con Sonia callada.
            if (IsSoniaSpeaking() && Now < SessionState.GetFloat(DueKey, 0f) + QuietWaitSeconds)
            {
                return;
            }

            if (CaptureNow(loader))
            {
                SetPhase(string.Empty);
                return;
            }

            SetPhase(string.Empty);
            Debug.LogWarning("[Sonia] Copia del avatar: no se pudo rehacer; se intentará la próxima vez que Sonia lleve este avatar en Play.");
        }

        /// <summary>El cargador, si lleva puesto el avatar del SDK que toca copiar y ya se puede copiar.</summary>
        private static GeniesAvatarLoader ReadyLoader()
        {
            GeniesAvatarLoader loader = Object.FindAnyObjectByType<GeniesAvatarLoader>();
            if (loader == null || !loader.IsLoaded || loader.IsBusy)
            {
                return null;
            }

            string hash = SessionState.GetString(HashKey, string.Empty);
            if (string.IsNullOrEmpty(hash) || loader.ShownDefinitionHash != hash)
            {
                return null;
            }

            return Now >= SessionState.GetFloat(DueKey, 0f) ? loader : null;
        }

        private static bool CaptureNow(GeniesAvatarLoader loader)
        {
            string path;
            try
            {
                path = Capture(loader);
            }
            catch (Exception exception)
            {
                Debug.LogException(exception);
                path = null;
            }

            if (string.IsNullOrEmpty(path))
            {
                return false;
            }

            // La copia de la escena en Play ya no es la del disco: el cargador no la vuelve a poner.
            loader.ForgetSnapshot();
            SessionState.SetBool(ReplayKey, false);
            SessionState.SetBool(PlaceKey, true);
            return true;
        }

        private static bool IsSoniaSpeaking()
        {
            AudioStreamPlayer player = Object.FindAnyObjectByType<AudioStreamPlayer>();
            return player != null && player.IsPlaying;
        }

        // ------------------------------------------------------------------
        // Al volver a modo edición
        // ------------------------------------------------------------------

        private static void OnPlayModeChanged(PlayModeStateChange change)
        {
            if (change != PlayModeStateChange.EnteredEditMode)
            {
                return;
            }

            // Al salir de Play el cargador vuelve a preferir la copia. La copia
            // pendiente de colocar la coloca Tick (o, si se vuelve a entrar en Play
            // para copiar, al terminar).
            SessionState.SetBool(GeniesAvatarLoader.ForceLiveSessionKey, false);
            _placeDeferred = false;
            if (_phase == PhaseCapture)
            {
                Finish("cancelado: se salió de Play antes de tener el avatar", false);
            }
            else if (_phase == PhasePending)
            {
                ReplayForPendingCopy();
            }
        }

        /// <summary>
        /// Sonia llevó en Play un avatar sin copia y no dio tiempo a copiarlo: se
        /// vuelve a entrar un momento en Play para hacerlo (lo hace Tick), una sola
        /// vez por cambio.
        /// </summary>
        private static void ReplayForPendingCopy()
        {
            SetPhase(string.Empty);
            if (SessionState.GetBool(ReplayKey, false))
            {
                Debug.LogWarning("[Sonia] Copia del avatar: sigue sin rehacer; se hará la próxima vez que Sonia lleve ese avatar en Play "
                                 + "(o con " + MenuPath + ").");
                return;
            }

            SessionState.SetBool(ReplayKey, true);
            SessionState.SetBool(ReplayPendingKey, true);
            Debug.Log("[Sonia] Copia del avatar: Sonia llevaba un avatar sin copia; se entra un momento en Play para rehacerla.");
        }

        private static void OnSceneOpened(Scene scene, OpenSceneMode mode)
        {
            // Si se esperaba a la escena del stand para colocar la copia, Tick la coloca ya.
            if (scene.path == StandScenePath())
            {
                _placeDeferred = false;
            }
        }

        /// <summary>
        /// Coloca en la escena del stand la copia recién guardada y guarda la
        /// escena, sin diálogos. Si la escena del stand no es la activa, se abre un
        /// momento y se vuelve a lo que había; si hay escenas con cambios sin
        /// guardar, se espera a que se abra la del stand.
        /// </summary>
        private static void PlacePending()
        {
            if (!SessionState.GetBool(PlaceKey, false) || EditorApplication.isPlayingOrWillChangePlaymode
                || EditorApplication.isCompiling || EditorApplication.isUpdating)
            {
                return;
            }

            string scenePath = StandScenePath();
            if (SceneManager.GetActiveScene().path == scenePath)
            {
                PlaceNow();
                return;
            }

            SceneSetup[] setup = EditorSceneManager.GetSceneManagerSetup();
            if (AnySceneDirty() || Array.Exists(setup, item => string.IsNullOrEmpty(item.path)))
            {
                _placeDeferred = true;
                Debug.Log("[Sonia] Copia del avatar guardada; se colocará en " + scenePath
                          + " en cuanto la abras (ahora hay escenas sin guardar).");
                return;
            }

            try
            {
                EditorSceneManager.OpenScene(scenePath, OpenSceneMode.Single);
                PlaceNow();
            }
            finally
            {
                if (setup.Length > 0)
                {
                    EditorSceneManager.RestoreSceneManagerSetup(setup);
                }
            }
        }

        private static void PlaceNow()
        {
            SessionState.SetBool(PlaceKey, false);
            GameObject placed = SoniaAvatarSetup.PlaceAvatar(SnapshotPrefabPath, false);
            if (placed != null)
            {
                Debug.Log("[Sonia] Copia del avatar colocada en " + placed.scene.path
                          + " y escena guardada: ya se ve en modo edición y en Play no se vuelve a cargar del SDK.", placed);
            }
            else
            {
                Debug.LogWarning("[Sonia] No se pudo colocar la copia del avatar: usa Sonia > Colocar avatar en la escena del stand.");
            }
        }

        private static void Finish(string reason, bool exitPlay)
        {
            SetPhase(string.Empty);
            SessionState.SetBool(GeniesAvatarLoader.ForceLiveSessionKey, false);
            Debug.LogWarning("[Sonia] Copia del avatar: " + reason + ".");
            if (exitPlay && EditorApplication.isPlaying)
            {
                EditorApplication.ExitPlaymode();
            }
        }

        private static void SetPhase(string phase)
        {
            _phase = phase;
            SessionState.SetString(PhaseKey, phase);
        }

        /// <summary>Escena del stand: la del último avatar visto en Play o, si no, la de siempre.</summary>
        private static string StandScenePath()
        {
            string path = SessionState.GetString(SceneKey, string.Empty);
            return string.IsNullOrEmpty(path) ? SoniaAvatarSetup.StandScenePath : path;
        }

        /// <summary>Abre la escena del stand si no hay nada sin guardar. Devuelve si quedó abierta.</summary>
        private static bool OpenStandScene()
        {
            if (AnySceneDirty())
            {
                return false;
            }

            Scene scene = EditorSceneManager.OpenScene(StandScenePath(), OpenSceneMode.Single);
            return scene.IsValid() && scene.isLoaded;
        }

        private static bool AnySceneDirty()
        {
            for (int i = 0; i < SceneManager.sceneCount; i++)
            {
                if (SceneManager.GetSceneAt(i).isDirty)
                {
                    return true;
                }
            }

            return false;
        }

        /// <summary>Marcador de la copia guardada en disco (null si aún no hay copia).</summary>
        private static GeniesAvatarSnapshot SnapshotOnDisk()
        {
            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(SnapshotPrefabPath);
            return prefab != null ? prefab.GetComponent<GeniesAvatarSnapshot>() : null;
        }

        /// <summary>
        /// Escribe la definición en SoniaGeniesAvatar.json si es otra (con sangría,
        /// para que los cambios se lean bien en git) y la reimporta.
        /// </summary>
        private static void SyncDefinitionFile(string json)
        {
            string path = SoniaAvatarSetup.GeniesDefinitionPath;
            TextAsset current = AssetDatabase.LoadAssetAtPath<TextAsset>(path);
            if (current != null && GeniesAvatarSnapshot.HashDefinition(current.text) == GeniesAvatarSnapshot.HashDefinition(json))
            {
                return;
            }

            try
            {
                File.WriteAllText(FullPath(path), IndentJson(json) + "\n", new UTF8Encoding(false));
            }
            catch (Exception exception)
            {
                Debug.LogWarning("[Sonia] No se pudo escribir " + path + ": " + exception.Message);
                return;
            }

            AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate | ImportAssetOptions.ForceSynchronousImport);
            Debug.Log("[Sonia] " + path + " ahora es el avatar que lleva Sonia (" + json.Length + " caracteres de definición).");
        }

        /// <summary>
        /// Sangra un JSON con dos espacios. Solo quita y pone espacios fuera de las
        /// cadenas, así que el valor no cambia (ni su huella).
        /// </summary>
        private static string IndentJson(string json)
        {
            StringBuilder builder = new StringBuilder(json.Length * 2);
            int depth = 0;
            bool inString = false;
            bool escaped = false;
            for (int i = 0; i < json.Length; i++)
            {
                char c = json[i];
                if (inString)
                {
                    builder.Append(c);
                    if (escaped)
                    {
                        escaped = false;
                    }
                    else if (c == '\\')
                    {
                        escaped = true;
                    }
                    else if (c == '"')
                    {
                        inString = false;
                    }

                    continue;
                }

                if (char.IsWhiteSpace(c) || c == '﻿')
                {
                    continue;
                }

                switch (c)
                {
                    case '"':
                        inString = true;
                        builder.Append(c);
                        break;
                    case '{':
                    case '[':
                        builder.Append(c);
                        int next = NextSignificant(json, i + 1);
                        if (next < json.Length && (json[next] == '}' || json[next] == ']'))
                        {
                            // Vacío: "{}" o "[]" en la misma línea.
                            builder.Append(json[next]);
                            i = next;
                            break;
                        }

                        depth++;
                        NewLine(builder, depth);
                        break;
                    case '}':
                    case ']':
                        depth = Math.Max(0, depth - 1);
                        NewLine(builder, depth);
                        builder.Append(c);
                        break;
                    case ',':
                        builder.Append(c);
                        NewLine(builder, depth);
                        break;
                    case ':':
                        builder.Append(": ");
                        break;
                    default:
                        builder.Append(c);
                        break;
                }
            }

            return builder.ToString();
        }

        private static int NextSignificant(string json, int start)
        {
            int i = start;
            while (i < json.Length && (char.IsWhiteSpace(json[i]) || json[i] == '﻿'))
            {
                i++;
            }

            return i;
        }

        private static void NewLine(StringBuilder builder, int depth)
        {
            builder.Append('\n');
            builder.Append(' ', depth * 2);
        }
    }
}

#endif
