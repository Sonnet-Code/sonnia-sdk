// Pone y cambia el avatar de Sonia con el Genies Avatar SDK, sin cortes.
//
// En modo edición no hay avatar: la escena guarda un ancla vacía («Avatar») que
// dice dónde y de cara a dónde va. Al entrar en Play se carga del SDK el avatar
// vivo lejos de la cámara (el SDK lo monta colgado de «Genies (cargando)», muy
// por debajo del suelo) y, cuando está completo, AvatarBinder lo pone en el
// sitio del ancla; hasta entonces no se ve a nadie. Al aparecer saluda con la
// mano.
//
// Qué avatar lleva Sonia lo decide el orquestador con set_avatar (mensaje fijo:
// la definición que se guardó en la nube desde el editor de personaje, o null
// para el personaje de la app, SoniaGeniesAvatar.json). Hasta que llega, Sonia
// arranca con el último que llegó en otra sesión (se recuerda en
// persistentDataPath, para arrancar bien sin orquestador) y, si nunca llegó
// ninguno, con el de la app.
//
// Un cambio de avatar se carga mientras Sonia sigue con el que tenía; Bind apaga
// el anterior y engancha el nuevo en el mismo fotograma, y el anterior se libera.
// Las cargas van en fila: si piden dos seguidas, gana la última. Si algo falla
// (sin red, sin credenciales, el SDK no responde) se reintenta con espera
// creciente sin quitar el avatar que hay. Si nunca llegó ninguno, tras unos
// fallos (o un rato) se enseña como último recurso el doble (Sticker) que la
// escena guarda desactivado, y se sigue reintentando; si una carga se abandona
// por tiempo, el avatar que el SDK entregue tarde se suelta (si no, quedaba una
// copia de Sonia en escena). Con el editor de personaje en pantalla
// (AvatarEditorSession.IsOpen) Sonia no se pinta, así que los cambios ni se
// montan hasta que se cierre: montar a la vez que el editor se atascaba.
//
// La cara la escribe FaceRig directamente en las formas FACS. El
// BlendShapeAnimatorBehaviour de Genies, que haría lo mismo desde los parámetros
// de su Animator Controller, se apaga: MotionPlayer sustituye ese controlador y
// sin él esos parámetros no existen.

using System;
using System.IO;
using System.Text;
using System.Threading;
using Cysharp.Threading.Tasks;
using Genies.Sdk;
using UnityEngine;

namespace Sonia
{
    /// <summary>Carga del SDK de Genies el avatar que toca y se lo pasa a AvatarBinder.</summary>
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
        [Tooltip("Poner el avatar al arrancar. Si no, se espera a set_avatar o a Apply.")]
        private bool loadOnStart = true;

        [SerializeField]
        [Tooltip("Recordar en persistentDataPath el último set_avatar para arrancar con él sin orquestador.")]
        private bool rememberLastAvatar = true;

        [SerializeField]
        [Tooltip("Espera entre reintentos (s): la primera y el máximo; se dobla en cada fallo.")]
        private Vector2 retrySeconds = new Vector2(5f, 120f);

        [SerializeField]
        [Tooltip("Tiempo máximo de cada paso (iniciar el SDK, la sesión, la carga) antes de darlo por fallido (s).")]
        private float stepTimeoutSeconds = 90f;

        [Header("Último recurso")]
        [SerializeField]
        [Tooltip("Doble (Sticker) que la escena guarda desactivado. Solo se enseña si el SDK no entrega ningún avatar.")]
        private Transform standIn;

        [SerializeField]
        [Tooltip("Intentos fallidos seguidos sin ningún avatar puesto antes de enseñar el doble.")]
        private int standInAfterFailures = 2;

        [SerializeField]
        [Tooltip("Segundos sin ningún avatar puesto antes de enseñar el doble, aunque la carga siga en marcha.")]
        private float standInAfterSeconds = 60f;

        [SerializeField]
        [Tooltip("Al aparecer el avatar (Sonia), saluda con la mano. No en modo debug.")]
        private bool greetOnAppear = true;

        /// <summary>Archivo de persistentDataPath con la definición del último set_avatar (no existe si fue null).</summary>
        public const string LastAvatarFileName = "sonia-avatar.json";

        /// <summary>Lo mismo para el invitado del Modo Jean (set_guest_avatar).</summary>
        public const string LastGuestAvatarFileName = "sonia-guest-avatar.json";

        /// <summary>Nombre de los avatares que monta el SDK.</summary>
        public const string LiveAvatarName = "Avatar (Genies)";

        /// <summary>
        /// Se lanza cuando un avatar del SDK queda puesto: el cargador y su
        /// definición. El editor de Unity lo usa para que SoniaGeniesAvatar.json
        /// siga al último avatar de Sonia.
        /// </summary>
        public static event Action<GeniesAvatarLoader, string> AvatarShown;

        /// <summary>
        /// Se espera antes de poner en pantalla un avatar ya montado, aún en el
        /// aparcamiento, para retocarlo sin que se vea el cambio: la camiseta de
        /// staff (GeniesStaffShirt). Cada uno tiene BeforeShowTimeoutSeconds; si
        /// falla o tarda, el avatar sale igual.
        /// </summary>
        public static event Func<GeniesAvatarLoader, Transform, UniTask> BeforeShow;

        /// <summary>Tope de cada BeforeShow (s).</summary>
        private const float BeforeShowTimeoutSeconds = 8f;

        /// <summary>Donde espera el avatar mientras carga, lejos de la cámara.</summary>
        private static readonly Vector3 ParkedPosition = new Vector3(0f, -1000f, 0f);

        /// <summary>Resultado de una carga que dejó de hacer falta porque se pidió otra definición.</summary>
        private const string Superseded = "sustituida por otra petición";

        /// <summary>Espera entre que aparece el avatar y el saludo, para que el reproductor ya lo mueva.</summary>
        private const float GreetDelaySeconds = 0.4f;

        // Estado de esta sesión. [NonSerialized] porque al entrar en Play Unity
        // recarga el dominio y, sin él, serializa también los campos privados: un
        // string null volvía como "" y parecía una petición ya hecha.
        [NonSerialized] private CancellationTokenSource _cancel;
        [NonSerialized] private ManagedAvatar _avatar;
        [NonSerialized] private string _shownDefinition;
        [NonSerialized] private string _shownHash = string.Empty;
        [NonSerialized] private string _requested;
        [NonSerialized] private int _requestVersion;
        [NonSerialized] private bool _running;
        [NonSerialized] private bool _started;
        [NonSerialized] private float _startTime;
        [NonSerialized] private int _failures;
        [NonSerialized] private Transform _parking;
        [NonSerialized] private bool _standInShown;
        [NonSerialized] private bool _debugQuiet;

        /// <summary>Cierto cuando hay un avatar del SDK cargado y enganchado.</summary>
        public bool IsLoaded
        {
            get { return _avatar != null && !_avatar.IsDisposed; }
        }

        /// <summary>Cierto mientras hay una carga en marcha o esperando a reintentar.</summary>
        public bool IsBusy
        {
            get { return _running; }
        }

        /// <summary>Cierto si, a falta del avatar del SDK, se está enseñando el doble.</summary>
        public bool ShowingStandIn
        {
            get { return _standInShown && !IsLoaded; }
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

        /// <summary>Definición del avatar del SDK en pantalla (null si aún no hay ninguno).</summary>
        public string ShownDefinition
        {
            get { return _shownDefinition; }
        }

        /// <summary>Huella (GeniesDefinition.Hash) del avatar del SDK en pantalla; vacía si aún no hay ninguno.</summary>
        public string ShownDefinitionHash
        {
            get { return _shownHash; }
        }

        /// <summary>Avatar del SDK en pantalla (null si aún no hay ninguno).</summary>
        public ManagedAvatar LiveAvatar
        {
            get { return IsLoaded ? _avatar : null; }
        }

        /// <summary>Resolución de las texturas con que se cargan los avatares.</summary>
        public AvatarLods Quality
        {
            get { return quality; }
        }

        private string AppDefinition
        {
            get { return definition != null ? definition.text : null; }
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

            // El doble solo aparece como último recurso.
            if (standIn != null && (binder == null || binder.Current != standIn))
            {
                standIn.gameObject.SetActive(false);
            }

            _cancel = new CancellationTokenSource();
        }

        private void OnEnable()
        {
            if (client == null)
            {
                return;
            }

            client.OnSetDebug += HandleSetDebug;
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
                client.OnSetDebug -= HandleSetDebug;
                client.OnSetAvatar -= HandleSetAvatar;
                client.OnSetGuestAvatar -= HandleSetGuestAvatar;
            }
        }

        private void Start()
        {
            // Hasta que llegue el del SDK no hay avatar en pantalla (solo el ancla).
            SetShown(null, string.Empty);
            _startTime = Time.realtimeSinceStartup;
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

        private void Update()
        {
            if (_standInShown || standIn == null || !_started || IsLoaded || AvatarEditorSession.IsOpen)
            {
                return;
            }

            bool tooManyFailures = standInAfterFailures > 0 && _failures >= standInAfterFailures;
            bool tooLong = standInAfterSeconds > 0f && Time.realtimeSinceStartup - _startTime >= standInAfterSeconds;
            if (tooManyFailures || tooLong)
            {
                ShowStandIn(tooManyFailures
                    ? _failures + " intentos fallidos"
                    : "sin avatar tras " + standInAfterSeconds.ToString("F0") + " s");
            }
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

        private void HandleSetDebug(SetDebugMessage message)
        {
            _debugQuiet = message != null && message.Enabled;
        }

        private void HandleDefinition(string definitionJson, string messageName)
        {
            string requested = string.IsNullOrWhiteSpace(definitionJson) ? null : definitionJson;
            RememberAvatar(requested);

            // Es un mensaje fijo: llega tras cada hello aunque no haya cambiado nada.
            string effective = requested ?? AppDefinition;
            if (!string.IsNullOrEmpty(_requested) && GeniesDefinition.Same(effective, _requested))
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
                Debug.LogWarning("[Sonia] GeniesAvatarLoader sin AvatarBinder: no se puede poner el avatar.", this);
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
                    if (IsLoaded && _shownHash == GeniesDefinition.Hash(target))
                    {
                        return;
                    }

                    string failure = await TryLoadAsync(target, version, token);
                    if (failure == null || failure == Superseded)
                    {
                        wait = Mathf.Max(1f, retrySeconds.x);
                        continue;
                    }

                    _failures++;
                    Debug.LogWarning("[Sonia] Avatar de Genies sin cargar (" + failure + "). Reintento en "
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
            // Paso en curso, para decir en qué se quedó si falla o tarda.
            string step = "iniciar el SDK";
            try
            {
                if (!await AvatarSdk.InitializeAsync().Timeout(limit))
                {
                    return "el SDK no se inicializó";
                }

                token.ThrowIfCancellationRequested();
                step = "iniciar sesión";
                string noSession = await GeniesSession.EnsureLoggedInAsync(limit);
                if (noSession != null)
                {
                    return noSession;
                }

                token.ThrowIfCancellationRequested();

                // La precarga solo adelanta descargas; si falla, la carga lo vuelve a intentar.
                step = "precargar las piezas";
                bool cached = await AvatarSdk.PrecacheAvatarAssetsByDefinitionAsync(json).Timeout(limit);
                if (!cached && _failures == 0)
                {
                    Debug.LogWarning("[Sonia] Genies no pudo precargar las piezas del avatar; se intenta montarlo igual.", this);
                }

                token.ThrowIfCancellationRequested();
                if (IsSuperseded(version, json))
                {
                    return Superseded;
                }

                await WaitWhileEditorOpen(token);
                if (IsSuperseded(version, json))
                {
                    return Superseded;
                }

                step = "montar el avatar";
                UniTaskCompletionSource<bool> complete = new UniTaskCompletionSource<bool>();
                UniTask<ManagedAvatar> load = AvatarSdk.LoadAvatarAsync(new LoadAvatarOptions.ByDefinition
                {
                    DefinitionToLoad = json,
                    AvatarName = LiveAvatarName,
                    Parent = ParkingLot(),
                    ShowLoadingSilhouette = false,
                    TargetLods = new[] { quality },
                    OnLoadingComplete = _ => complete.TrySetResult(true)
                }).Preserve();
                try
                {
                    pending = await load.Timeout(limit);
                }
                catch (TimeoutException)
                {
                    if (_failures == 0)
                    {
                        // Qué llegó a construir el SDK, para saber en qué se quedó.
                        Debug.LogWarning("[Sonia] Genies no termina de montar el avatar. En el aparcamiento: "
                                         + DescribeParking(), this);
                    }

                    // El SDK sigue montándolo: el avatar que entregue tarde se suelta.
                    DiscardWhenLoaded(load).Forget();
                    throw;
                }

                if (pending == null || pending.Root == null)
                {
                    return "el SDK no devolvió avatar";
                }

                pending.Root.transform.localPosition = Vector3.zero;
                if (!pending.IsLoadingComplete)
                {
                    step = "terminar de cargar el avatar";
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

                await RunBeforeShow(pending.Root.transform, token);
                if (IsSuperseded(version, json))
                {
                    return Superseded;
                }

                // Cambio en un solo fotograma: Bind apaga el anterior (el ancla, el
                // doble o el avatar de antes) y pone este en su sitio.
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

                _failures = 0;
                SetShown(json, GeniesDefinition.Hash(json));
                Debug.Log("[Sonia] Avatar de Genies del SDK puesto (" + json.Length + " caracteres de definición).", this);
                RaiseShown(json);
                GreetSoon(token).Forget();
                return null;
            }
            catch (TimeoutException)
            {
                return "«" + step + "» tardó más de " + limit.TotalSeconds.ToString("F0") + " s";
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception exception)
            {
                if (_failures == 0)
                {
                    // La traza completa solo la primera vez, para no llenar el registro con reintentos.
                    Debug.LogWarning("[Sonia] Genies falló al " + step + ":\n" + exception, this);
                }

                return "al " + step + ": " + exception.GetType().Name + ": " + exception.Message;
            }
            finally
            {
                if (pending != null && !pending.IsDisposed)
                {
                    pending.Dispose();
                }
            }
        }

        /// <summary>
        /// Donde se monta un avatar nuevo hasta que Bind lo pone en su sitio: muy
        /// por debajo del suelo. El SDK lo construye en su padre y, colgado de
        /// Sonia, se veía de espaldas en su sitio mientras tanto.
        /// </summary>
        private Transform ParkingLot()
        {
            if (_parking == null)
            {
                _parking = new GameObject("Genies (cargando)").transform;
                _parking.SetParent(binder.transform, false);
                _parking.localPosition = ParkedPosition;
            }

            return _parking;
        }

        /// <summary>
        /// Resumen de lo que hay en el aparcamiento (objetos, mallas, materiales y
        /// texturas puestas), para el registro cuando una carga se atasca.
        /// </summary>
        private string DescribeParking()
        {
            if (_parking == null || _parking.childCount == 0)
            {
                return "nada (el SDK no llegó a crear el avatar)";
            }

            StringBuilder sb = new StringBuilder();
            foreach (Transform child in _parking)
            {
                Renderer[] renderers = child.GetComponentsInChildren<Renderer>(true);
                int vertices = 0;
                int materials = 0;
                int textures = 0;
                int emptySlots = 0;
                foreach (Renderer renderer in renderers)
                {
                    SkinnedMeshRenderer skinned = renderer as SkinnedMeshRenderer;
                    if (skinned != null && skinned.sharedMesh != null)
                    {
                        vertices += skinned.sharedMesh.vertexCount;
                    }

                    foreach (Material material in renderer.sharedMaterials)
                    {
                        if (material == null)
                        {
                            continue;
                        }

                        materials++;
                        foreach (string property in material.GetTexturePropertyNames())
                        {
                            if (material.GetTexture(property) != null)
                            {
                                textures++;
                            }
                            else
                            {
                                emptySlots++;
                            }
                        }
                    }
                }

                sb.Append('«').Append(child.name).Append("» ")
                  .Append(child.GetComponentsInChildren<Transform>(true).Length).Append(" objetos, ")
                  .Append(renderers.Length).Append(" renderers, ")
                  .Append(vertices).Append(" vértices, ")
                  .Append(materials).Append(" materiales, ")
                  .Append(textures).Append(" texturas puestas y ")
                  .Append(emptySlots).Append(" huecos sin textura; ");
            }

            return sb.ToString();
        }

        /// <summary>Suelta el avatar de una carga abandonada por tiempo cuando el SDK lo entregue.</summary>
        private static async UniTaskVoid DiscardWhenLoaded(UniTask<ManagedAvatar> load)
        {
            try
            {
                ManagedAvatar late = await load;
                if (late != null && !late.IsDisposed)
                {
                    late.Dispose();
                }
            }
            catch (Exception)
            {
                // La carga abandonada también falló: no hay nada que soltar.
            }
        }

        /// <summary>Último recurso: el SDK no entrega ningún avatar y se enseña el doble que guarda la escena.</summary>
        private void ShowStandIn(string reason)
        {
            _standInShown = true;
            standIn.gameObject.SetActive(true);
            if (!binder.Bind(standIn))
            {
                standIn.gameObject.SetActive(false);
                Debug.LogWarning("[Sonia] No se pudo enseñar el doble del avatar (" + reason + ").", this);
                return;
            }

            Debug.LogWarning("[Sonia] El SDK de Genies no entrega el avatar (" + reason
                             + "): se enseña el doble mientras se sigue intentando.", this);
            if (_cancel != null)
            {
                GreetSoon(_cancel.Token).Forget();
            }
        }

        /// <summary>Al aparecer, Sonia saluda con la mano (si puede: en idle o escuchando, y no en modo debug).</summary>
        private async UniTaskVoid GreetSoon(CancellationToken token)
        {
            if (!greetOnAppear || role != AvatarRole.Sonia)
            {
                return;
            }

            try
            {
                await UniTask.Delay(TimeSpan.FromSeconds(GreetDelaySeconds), ignoreTimeScale: true, cancellationToken: token);
            }
            catch (OperationCanceledException)
            {
                return;
            }

            AvatarChoreographer choreographer = binder != null ? binder.GetComponentInChildren<AvatarChoreographer>(true) : null;
            if (!_debugQuiet && choreographer != null && choreographer.Ready)
            {
                choreographer.PlayGreetingNow();
            }
        }

        /// <summary>Cierto si, mientras se cargaba esta definición, se pidió otra distinta.</summary>
        private bool IsSuperseded(int version, string json)
        {
            return _requestVersion != version && !GeniesDefinition.Same(_requested, json);
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
        /// pantalla y, si aún no hay ninguno, la que se está poniendo o la de la app.
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

        private async UniTask RunBeforeShow(Transform root, CancellationToken token)
        {
            Func<GeniesAvatarLoader, Transform, UniTask> handlers = BeforeShow;
            if (handlers == null)
            {
                return;
            }

            foreach (Delegate handler in handlers.GetInvocationList())
            {
                token.ThrowIfCancellationRequested();
                try
                {
                    await ((Func<GeniesAvatarLoader, Transform, UniTask>)handler)(this, root)
                        .Timeout(TimeSpan.FromSeconds(BeforeShowTimeoutSeconds));
                }
                catch (TimeoutException)
                {
                    Debug.LogWarning("[Sonia] Un retoque del avatar antes de mostrarlo tardó más de "
                                     + BeforeShowTimeoutSeconds + " s; sale sin esperarlo.", this);
                }
                catch (Exception exception) when (!(exception is OperationCanceledException))
                {
                    Debug.LogException(exception, this);
                }
            }
        }

        private void RaiseShown(string json)
        {
            Action<GeniesAvatarLoader, string> handler = AvatarShown;
            if (handler == null)
            {
                return;
            }

            try
            {
                handler(this, json);
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
