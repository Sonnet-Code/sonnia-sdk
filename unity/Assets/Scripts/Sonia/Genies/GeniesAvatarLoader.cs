// Pone y cambia el avatar de Sonia con el Genies Avatar SDK, sin cortes.
//
// Qué avatar lleva Sonia lo decide el orquestador con set_avatar (mensaje fijo:
// la definición que se guardó en la nube desde el editor de personaje, o null
// para el personaje de la app, SoniaGeniesAvatar.json). Hasta que llega, Sonia
// arranca con el último que llegó en otra sesión (se recuerda en
// persistentDataPath, para arrancar bien sin red ni orquestador) y, si nunca
// llegó ninguno, con el de la app.
//
// La escena trae la copia local de un avatar (GeniesAvatarSnapshot, Sonia >
// Actualizar copia del avatar del SDK). Si es la definición que toca, no se carga
// nada: sale al instante y no hace falta red. Si no, el avatar se carga del SDK
// lejos de la cámara mientras Sonia sigue con el que tenía; cuando está completo,
// AvatarBinder lo pone en su sitio en el mismo fotograma en que apaga el
// anterior, y el anterior se libera. Las cargas van en fila: si piden dos
// seguidas, gana la última. Si algo falla (sin red, sin credenciales, el SDK no
// responde) se reintenta con espera creciente sin quitar el avatar que hay: Sonia
// nunca se queda sin avatar. Con el editor de personaje en pantalla
// (AvatarEditorSession.IsOpen) Sonia no se pinta, así que el cambio espera a que
// se cierre.
//
// La cara la escribe FaceRig directamente en las formas FACS. El
// BlendShapeAnimatorBehaviour de Genies, que haría lo mismo desde los parámetros
// de su Animator Controller, se apaga: MotionPlayer sustituye ese controlador y
// sin él esos parámetros no existen.

using System;
using System.IO;
using System.Threading;
using Cysharp.Threading.Tasks;
using Genies.Sdk;
using UnityEngine;

namespace Sonia
{
    /// <summary>Pone el avatar que toca (copia local o del SDK de Genies) y se lo pasa a AvatarBinder.</summary>
    [DisallowMultipleComponent]
    public class GeniesAvatarLoader : MonoBehaviour
    {
        [SerializeField]
        [Tooltip("De quién es el avatar: Sonia (set_avatar) o el invitado del Modo Jean (set_guest_avatar).")]
        private AvatarRole role = AvatarRole.Sonia;

        [SerializeField]
        [Tooltip("Personaje de la app (JSON del SDK): el de set_avatar null y el de arranque si nunca llegó otro.")]
        private TextAsset definition;

        [SerializeField]
        [Tooltip("Quién engancha el avatar al pipeline de Sonia. Vacío: el del objeto padre.")]
        private AvatarBinder binder;

        [SerializeField]
        [Tooltip("Conexión con el orquestador, que manda set_avatar. Vacío: la del objeto padre.")]
        private SoniaClient client;

        [SerializeField]
        [Tooltip("Resolución de las texturas del avatar.")]
        private AvatarLods quality = AvatarLods.High;

        [SerializeField]
        [Tooltip("Poner el avatar al arrancar. Si no, se espera a set_avatar o a Load.")]
        private bool loadOnStart = true;

        [SerializeField]
        [Tooltip("Cargar del SDK aunque la escena tenga la copia local de la definición que toca.")]
        private bool alwaysLoadLive;

        [SerializeField]
        [Tooltip("Recordar en persistentDataPath el último set_avatar para arrancar con él sin red ni orquestador.")]
        private bool rememberLastAvatar = true;

        [SerializeField]
        [Tooltip("Espera entre reintentos (s): la primera y el máximo; se dobla en cada fallo.")]
        private Vector2 retrySeconds = new Vector2(5f, 120f);

        [SerializeField]
        [Tooltip("Tiempo máximo de cada paso (iniciar el SDK, la sesión, la carga) antes de darlo por fallido (s).")]
        private float stepTimeoutSeconds = 90f;

        /// <summary>
        /// Clave de SessionState con la que el editor pide cargar del SDK aunque
        /// haya copia local (la usa Sonia > Actualizar copia del avatar del SDK).
        /// </summary>
        public const string ForceLiveSessionKey = "Sonia.Genies.ForceLiveLoad";

        /// <summary>Archivo de persistentDataPath con la definición del último set_avatar (no existe si fue null).</summary>
        public const string LastAvatarFileName = "sonia-avatar.json";

        /// <summary>Lo mismo para el invitado del Modo Jean (set_guest_avatar).</summary>
        public const string LastGuestAvatarFileName = "sonia-guest-avatar.json";

        /// <summary>Nombre de los avatares que monta el SDK.</summary>
        public const string LiveAvatarName = "Avatar (Genies)";

        /// <summary>
        /// Se lanza cuando una petición cambia el avatar en pantalla: el cargador, la
        /// definición que lleva y si es un avatar del SDK (true) o la copia local
        /// (false). El editor de Unity lo usa para rehacer la copia.
        /// </summary>
        public static event Action<GeniesAvatarLoader, string, bool> AvatarShown;

        /// <summary>Donde espera el avatar mientras carga, lejos de la cámara.</summary>
        private static readonly Vector3 ParkedPosition = new Vector3(0f, -1000f, 0f);

        /// <summary>Resultado de una carga que dejó de hacer falta porque se pidió otra definición.</summary>
        private const string Superseded = "sustituida por otra petición";

        // Estado de esta sesión. [NonSerialized] porque al entrar en Play Unity
        // recarga el dominio y, sin él, serializa también los campos privados: un
        // string null volvía como "" y parecía una petición ya hecha.
        [NonSerialized] private CancellationTokenSource _cancel;
        [NonSerialized] private ManagedAvatar _avatar;
        [NonSerialized] private GeniesAvatarSnapshot _snapshot;
        [NonSerialized] private string _shownDefinition;
        [NonSerialized] private string _shownHash = string.Empty;
        [NonSerialized] private string _requested;
        [NonSerialized] private int _requestVersion;
        [NonSerialized] private bool _forceLive;
        [NonSerialized] private bool _running;
        [NonSerialized] private bool _started;
        [NonSerialized] private bool _announcedSnapshot;
        [NonSerialized] private bool _warnedStaleSnapshot;

        /// <summary>Cierto cuando hay un avatar del SDK cargado y enganchado.</summary>
        public bool IsLoaded
        {
            get { return _avatar != null && !_avatar.IsDisposed; }
        }

        /// <summary>Cierto si Sonia lleva ahora la copia local del avatar.</summary>
        public bool UsingSnapshot
        {
            get { return _snapshot != null && binder != null && binder.Current == _snapshot.transform; }
        }

        /// <summary>Cierto mientras hay una carga en marcha o esperando a reintentar.</summary>
        public bool IsBusy
        {
            get { return _running; }
        }

        /// <summary>Personaje de la app (JSON del SDK).</summary>
        public TextAsset Definition
        {
            get { return definition; }
        }

        /// <summary>De quién es el avatar que pone este cargador.</summary>
        public AvatarRole Role
        {
            get { return role; }
        }

        /// <summary>Definición del avatar en pantalla (null si es el doble del editor).</summary>
        public string ShownDefinition
        {
            get { return _shownDefinition; }
        }

        /// <summary>Huella (GeniesAvatarSnapshot.HashDefinition) del avatar en pantalla; vacía si es el doble.</summary>
        public string ShownDefinitionHash
        {
            get { return _shownHash; }
        }

        private string AppDefinition
        {
            get { return definition != null ? definition.text : null; }
        }

        private bool ForceLive
        {
            get
            {
#if UNITY_EDITOR
                if (UnityEditor.SessionState.GetBool(ForceLiveSessionKey, false))
                {
                    return true;
                }
#endif
                return alwaysLoadLive;
            }
        }

        private string RememberedAvatarPath
        {
            get
            {
                string file = role == AvatarRole.Guest ? LastGuestAvatarFileName : LastAvatarFileName;
                return Path.Combine(Application.persistentDataPath, file);
            }
        }

        private void Awake()
        {
            if (binder == null)
            {
                binder = GetComponentInParent<AvatarBinder>();
            }

            if (client == null)
            {
                client = GetComponentInParent<SoniaClient>();
            }

            if (client == null)
            {
                client = FindAnyObjectByType<SoniaClient>();
            }

            _cancel = new CancellationTokenSource();
        }

        private void OnEnable()
        {
            if (client == null)
            {
                return;
            }

            if (role == AvatarRole.Guest)
            {
                client.OnSetGuestAvatar += HandleSetGuestAvatar;
            }
            else
            {
                client.OnSetAvatar += HandleSetAvatar;
            }
        }

        private void OnDisable()
        {
            if (client != null)
            {
                client.OnSetAvatar -= HandleSetAvatar;
                client.OnSetGuestAvatar -= HandleSetGuestAvatar;
            }
        }

        private void Start()
        {
            _forceLive = ForceLive;

            // Lo que hay en escena al arrancar: la copia local o el doble del editor.
            Transform current = binder != null ? binder.Current : null;
            _snapshot = current != null ? current.GetComponent<GeniesAvatarSnapshot>() : null;
            if (_snapshot != null)
            {
                SetShown(_snapshot.DefinitionJson, _snapshot.DefinitionHash);
            }
            else
            {
                SetShown(null, string.Empty);
            }

            _started = true;
            if (!string.IsNullOrEmpty(_requested))
            {
                // set_avatar llegó antes de arrancar.
                StartWorker();
                return;
            }

            if (!loadOnStart)
            {
                return;
            }

            string remembered = ReadRememberedAvatar();
            if (remembered != null)
            {
                Debug.Log("[Sonia] Se arranca con el último avatar que mandó el orquestador (" + remembered.Length
                          + " caracteres).", this);
            }

            Request(remembered);
        }

        private void OnDestroy()
        {
            if (_cancel != null)
            {
                _cancel.Cancel();
                _cancel.Dispose();
                _cancel = null;
            }

            ReleaseLiveAvatar();
        }

        /// <summary>Pide que Sonia lleve esta definición (null: el personaje de la app).</summary>
        public void Apply(string definitionJson)
        {
            Request(definitionJson);
        }

        /// <summary>Carga del SDK la definición que toca aunque la copia local valga (para rehacer la copia).</summary>
        public void Load()
        {
            _forceLive = true;
            Request(_requested);
        }

        /// <summary>
        /// La copia de la escena dejó de valer en esta sesión (el editor de Unity la
        /// acaba de rehacer con otro avatar): ya no se vuelve a poner.
        /// </summary>
        public void ForgetSnapshot()
        {
            if (_snapshot != null && !UsingSnapshot)
            {
                _snapshot = null;
            }
        }

        private void HandleSetAvatar(SetAvatarMessage message)
        {
            if (message != null)
            {
                HandleDefinition(message.Definition, "set_avatar");
            }
        }

        private void HandleSetGuestAvatar(SetGuestAvatarMessage message)
        {
            if (message != null)
            {
                HandleDefinition(message.Definition, "set_guest_avatar");
            }
        }

        private void HandleDefinition(string definitionJson, string messageName)
        {
            string requested = string.IsNullOrWhiteSpace(definitionJson) ? null : definitionJson;
            RememberAvatar(requested);

            // Es un mensaje fijo: llega tras cada hello aunque no haya cambiado nada.
            string effective = requested ?? AppDefinition;
            if (!string.IsNullOrEmpty(_requested)
                && GeniesAvatarSnapshot.HashDefinition(effective) == GeniesAvatarSnapshot.HashDefinition(_requested))
            {
                return;
            }

            Debug.Log("[Sonia] " + messageName + ": " + (requested == null
                ? "el personaje de la app"
                : "definición de " + requested.Length + " caracteres") + ".", this);
            Request(requested);
        }

        private void Request(string definitionJson)
        {
            string effective = string.IsNullOrWhiteSpace(definitionJson) ? AppDefinition : definitionJson;
            if (string.IsNullOrWhiteSpace(effective))
            {
                Debug.LogWarning("[Sonia] GeniesAvatarLoader sin definición: sigue el avatar que hay.", this);
                return;
            }

            _requested = effective;
            _requestVersion++;
            PublishCurrentDefinition();
            if (_started)
            {
                StartWorker();
            }
        }

        private void StartWorker()
        {
            if (_running || _cancel == null || string.IsNullOrWhiteSpace(_requested))
            {
                return;
            }

            if (binder == null)
            {
                Debug.LogWarning("[Sonia] GeniesAvatarLoader sin AvatarBinder: sigue el avatar que hay.", this);
                return;
            }

            RunAsync(_cancel.Token).Forget();
        }

        /// <summary>Pone la última definición pedida y para cuando la que hay en pantalla es esa.</summary>
        private async UniTaskVoid RunAsync(CancellationToken token)
        {
            _running = true;
            float wait = Mathf.Max(1f, retrySeconds.x);
            try
            {
                while (!token.IsCancellationRequested)
                {
                    string target = _requested;
                    int version = _requestVersion;
                    string hash = GeniesAvatarSnapshot.HashDefinition(target);
                    if (hash == _shownHash && (!_forceLive || IsLoaded))
                    {
                        AnnounceSnapshot();
                        return;
                    }

                    if (!_forceLive && _snapshot != null && _snapshot.Matches(target))
                    {
                        await WaitWhileEditorOpen(token);
                        if (_requestVersion != version)
                        {
                            continue;
                        }

                        if (ShowSnapshot(target, hash))
                        {
                            continue;
                        }
                    }
                    else if (_snapshot != null && !_forceLive && !_warnedStaleSnapshot)
                    {
                        _warnedStaleSnapshot = true;
                        Debug.Log("[Sonia] La copia local del avatar es de otra definición: se carga del SDK"
                                  + " (en el editor de Unity la copia se rehace sola).", this);
                    }

                    string failure = await TryLoadAsync(target, version, token);
                    if (failure == null || failure == Superseded)
                    {
                        wait = Mathf.Max(1f, retrySeconds.x);
                        continue;
                    }

                    Debug.LogWarning("[Sonia] Avatar de Genies sin cargar (" + failure + "); sigue el que hay. Reintento en "
                                     + wait.ToString("F0") + " s.", this);
                    await WaitForRetry(wait, version, token);
                    wait = Mathf.Min(wait * 2f, Mathf.Max(wait, retrySeconds.y));
                }
            }
            catch (OperationCanceledException)
            {
                // Se destruyó el cargador (fin de Play o cambio de escena).
            }
            finally
            {
                _running = false;
            }
        }

        /// <summary>Un intento completo. Devuelve null si el avatar quedó puesto; si no, por qué no.</summary>
        private async UniTask<string> TryLoadAsync(string json, int version, CancellationToken token)
        {
            TimeSpan limit = TimeSpan.FromSeconds(Mathf.Max(5f, stepTimeoutSeconds));
            ManagedAvatar pending = null;
            try
            {
                if (!await AvatarSdk.InitializeAsync().Timeout(limit))
                {
                    return "el SDK no se inicializó";
                }

                token.ThrowIfCancellationRequested();
                if (!AvatarSdk.IsLoggedIn)
                {
                    var instant = await AvatarSdk.TryInstantLoginAsync().Timeout(limit);
                    if (!instant.isLoggedIn)
                    {
                        var guest = await AvatarSdk.StartLoginAnonymousAsync().Timeout(limit);
                        if (!guest.succeeded)
                        {
                            return "sin sesión: " + guest.failReason;
                        }
                    }
                }

                token.ThrowIfCancellationRequested();

                // La precarga solo adelanta descargas; si falla, la carga lo vuelve a intentar.
                await AvatarSdk.PrecacheAvatarAssetsByDefinitionAsync(json).Timeout(limit);
                token.ThrowIfCancellationRequested();
                if (IsSuperseded(version, json))
                {
                    return Superseded;
                }

                UniTaskCompletionSource<bool> complete = new UniTaskCompletionSource<bool>();
                pending = await AvatarSdk.LoadAvatarAsync(new LoadAvatarOptions.ByDefinition
                {
                    DefinitionToLoad = json,
                    AvatarName = LiveAvatarName,
                    Parent = binder.transform,
                    ShowLoadingSilhouette = false,
                    TargetLods = new[] { quality },
                    OnLoadingComplete = _ => complete.TrySetResult(true)
                }).Timeout(limit);

                if (pending == null || pending.Root == null)
                {
                    return "el SDK no devolvió avatar";
                }

                pending.Root.transform.localPosition = ParkedPosition;
                if (!pending.IsLoadingComplete)
                {
                    await complete.Task.Timeout(limit);
                }

                token.ThrowIfCancellationRequested();
                if (IsSuperseded(version, json))
                {
                    return Superseded;
                }

                DisableGeniesFaceDriver(pending.Root);
                await WaitWhileEditorOpen(token);
                if (IsSuperseded(version, json))
                {
                    return Superseded;
                }

                // Cambio en un solo fotograma: Bind apaga el anterior y engancha este.
                if (!binder.Bind(pending.Root.transform))
                {
                    return "no se pudo enganchar";
                }

                ManagedAvatar previous = _avatar;
                _avatar = pending;
                pending = null;
                if (previous != null && !previous.IsDisposed)
                {
                    previous.Dispose();
                }

                SetShown(json, GeniesAvatarSnapshot.HashDefinition(json));
                Debug.Log("[Sonia] Avatar de Genies del SDK puesto (" + json.Length + " caracteres de definición).", this);
                RaiseShown(json, true);
                return null;
            }
            catch (TimeoutException)
            {
                return "un paso tardó más de " + limit.TotalSeconds.ToString("F0") + " s";
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception exception)
            {
                return exception.GetType().Name + ": " + exception.Message;
            }
            finally
            {
                if (pending != null && !pending.IsDisposed)
                {
                    pending.Dispose();
                }
            }
        }

        /// <summary>Vuelve a poner la copia local de la escena y libera el avatar del SDK que hubiera.</summary>
        private bool ShowSnapshot(string json, string hash)
        {
            Transform copy = _snapshot.transform;
            if (binder.Current != copy)
            {
                copy.gameObject.SetActive(true);
                if (!binder.Bind(copy))
                {
                    copy.gameObject.SetActive(false);
                    return false;
                }
            }

            ReleaseLiveAvatar();
            SetShown(json, hash);
            AnnounceSnapshot();
            RaiseShown(json, false);
            return true;
        }

        /// <summary>Cierto si, mientras se cargaba esta definición, se pidió otra distinta.</summary>
        private bool IsSuperseded(int version, string json)
        {
            return _requestVersion != version
                   && GeniesAvatarSnapshot.HashDefinition(_requested) != GeniesAvatarSnapshot.HashDefinition(json);
        }

        private static async UniTask WaitWhileEditorOpen(CancellationToken token)
        {
            if (AvatarEditorSession.IsOpen)
            {
                await UniTask.WaitWhile(() => AvatarEditorSession.IsOpen, cancellationToken: token);
            }
        }

        /// <summary>Espera antes de reintentar, salvo que entretanto se pida otra definición.</summary>
        private async UniTask WaitForRetry(float seconds, int version, CancellationToken token)
        {
            float end = Time.realtimeSinceStartup + seconds;
            while (Time.realtimeSinceStartup < end && _requestVersion == version)
            {
                await UniTask.Delay(TimeSpan.FromSeconds(0.25), ignoreTimeScale: true, cancellationToken: token);
            }
        }

        private void SetShown(string json, string hash)
        {
            _shownDefinition = string.IsNullOrEmpty(json) ? null : json;
            _shownHash = hash ?? string.Empty;
            PublishCurrentDefinition();
        }

        /// <summary>
        /// El editor de personaje arranca con AvatarEditorSession.CurrentDefinition
        /// y, si estuviera vacía, con el avatar base de Genies: guardar eso
        /// sustituiría a Sonia. Así que nunca se deja vacía: la del avatar en
        /// pantalla y, si no se sabe (el doble del editor o una copia antigua sin su
        /// JSON), la que se está poniendo o la de la app.
        /// </summary>
        private void PublishCurrentDefinition()
        {
            string current = _shownDefinition;
            if (string.IsNullOrEmpty(current))
            {
                current = !string.IsNullOrEmpty(_requested) ? _requested : AppDefinition;
            }

            AvatarEditorSession.SetDefinitionFor(role, string.IsNullOrEmpty(current) ? null : current);
        }

        private void AnnounceSnapshot()
        {
            if (_announcedSnapshot || !UsingSnapshot)
            {
                return;
            }

            _announcedSnapshot = true;
            Debug.Log("[Sonia] Avatar de Genies desde la copia local (SDK " + _snapshot.SdkVersion + ", "
                      + _snapshot.CreatedUtc + "): no hace falta cargarlo.", this);
        }

        private void RaiseShown(string json, bool live)
        {
            Action<GeniesAvatarLoader, string, bool> handler = AvatarShown;
            if (handler == null)
            {
                return;
            }

            try
            {
                handler(this, json, live);
            }
            catch (Exception exception)
            {
                Debug.LogException(exception, this);
            }
        }

        private void ReleaseLiveAvatar()
        {
            if (_avatar != null && !_avatar.IsDisposed)
            {
                _avatar.Dispose();
            }

            _avatar = null;
        }

        private string ReadRememberedAvatar()
        {
            if (!rememberLastAvatar)
            {
                return null;
            }

            try
            {
                string path = RememberedAvatarPath;
                if (!File.Exists(path))
                {
                    return null;
                }

                string json = File.ReadAllText(path);
                return string.IsNullOrWhiteSpace(json) ? null : json;
            }
            catch (Exception exception)
            {
                Debug.LogWarning("[Sonia] No se pudo leer el último avatar recordado: " + exception.Message, this);
                return null;
            }
        }

        /// <summary>Recuerda la definición del último set_avatar; null (el personaje de la app) borra el archivo.</summary>
        private void RememberAvatar(string json)
        {
            if (!rememberLastAvatar)
            {
                return;
            }

            string path = RememberedAvatarPath;
            try
            {
                if (json == null)
                {
                    if (File.Exists(path))
                    {
                        File.Delete(path);
                    }

                    return;
                }

                if (File.Exists(path) && File.ReadAllText(path) == json)
                {
                    return;
                }

                // Se escribe aparte y se cambia de nombre: un corte a medias no deja el archivo roto.
                string temporary = path + ".tmp";
                File.WriteAllText(temporary, json);
                if (File.Exists(path))
                {
                    File.Delete(path);
                }

                File.Move(temporary, path);
            }
            catch (Exception exception)
            {
                Debug.LogWarning("[Sonia] No se pudo recordar el avatar: " + exception.Message, this);
            }
        }

        /// <summary>Apaga el puente de Genies entre parámetros del Animator y formas de la cara (es interno del SDK).</summary>
        private static void DisableGeniesFaceDriver(GameObject root)
        {
            MonoBehaviour[] behaviours = root.GetComponentsInChildren<MonoBehaviour>(true);
            for (int i = 0; i < behaviours.Length; i++)
            {
                if (behaviours[i] != null && behaviours[i].GetType().Name == "BlendShapeAnimatorBehaviour")
                {
                    behaviours[i].enabled = false;
                }
            }
        }
    }
}
