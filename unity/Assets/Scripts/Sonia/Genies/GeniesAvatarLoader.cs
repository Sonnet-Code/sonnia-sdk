// Sets and swaps the avatar with the Genies Avatar SDK, without cuts.
//
// In edit mode there is no avatar: the scene keeps an empty anchor ("Avatar")
// that says where it goes and which way it faces. On entering Play the live
// avatar is loaded from the SDK far from the camera (the SDK builds it hanging
// from "Genies (loading)", far below the floor) and, when it is complete,
// AvatarBinder puts it at the anchor's place; until then nobody is visible. On
// appearing it waves hello.
//
// Which avatar is shown is decided by the orchestrator with set_avatar (a
// persistent message: the definition to use, or null for the app's character,
// SoniaGeniesAvatar.json). Until it arrives, the app starts with the last one
// received in another session (remembered in persistentDataPath, so it starts
// correctly without an orchestrator) and, if none ever arrived, with the app's.
//
// An avatar change is loaded while the current one stays; Bind turns the
// previous one off and attaches the new one in the same frame, and the previous
// one is released. Loads are queued: if two arrive in a row, the last wins. If
// something fails (no network, no credentials, the SDK does not respond) it
// retries with growing backoff without removing the avatar that is there. If
// none ever arrived, after a few failures (or a while) the fallback avatar
// (Sticker) that the scene keeps disabled is shown as a last resort, and
// retrying continues; if a load is abandoned on timeout, the avatar the SDK
// delivers late is released (otherwise a copy of the avatar was left in the
// scene). While no SDK avatar is shown yet (the first load on each machine,
// which downloads about 90 MB), the load is not abandoned at stepTimeoutSeconds:
// it waits up to FirstLoadMinutes. Abandoning it and requesting another every
// 90 s left the first run on the fallback avatar until the app was reopened.
//
// The face is written by FaceRig directly into the FACS shapes. Genies'
// BlendShapeAnimatorBehaviour, which would do the same from the parameters of
// its Animator Controller, is turned off: MotionPlayer replaces that controller
// and without it those parameters do not exist.

using System;
using System.IO;
using System.Text;
using System.Threading;
using Cysharp.Threading.Tasks;
using Genies.Sdk;
using UnityEngine;

namespace Sonia
{
    /// <summary>Loads the right avatar from the Genies SDK and hands it to AvatarBinder.</summary>
    [DisallowMultipleComponent]
    public class GeniesAvatarLoader : MonoBehaviour
    {
        [SerializeField]
        [Tooltip("App character (SDK JSON): the one for set_avatar null and the startup one if no other ever arrived.")]
        private TextAsset definition;

        [SerializeField]
        [Tooltip("Who attaches the avatar to the pipeline. Empty: the one on the parent object.")]
        private AvatarBinder binder;

        [SerializeField]
        [Tooltip("Connection with the orchestrator, which sends set_avatar. Empty: the one on the parent object.")]
        private SoniaClient client;

        [SerializeField]
        [Tooltip("Avatar texture resolution.")]
        private AvatarLods quality = AvatarLods.High;

        [SerializeField]
        [Tooltip("Set the avatar at startup. Otherwise wait for set_avatar or Apply.")]
        private bool loadOnStart = true;

        [SerializeField]
        [Tooltip("Remember the last set_avatar in persistentDataPath to start with it without an orchestrator.")]
        private bool rememberLastAvatar = true;

        [SerializeField]
        [Tooltip("Wait between retries (s): the first and the maximum; it doubles on each failure.")]
        private Vector2 retrySeconds = new Vector2(5f, 120f);

        [SerializeField]
        [Tooltip("Maximum time of each step (starting the SDK, the session, the load) before counting it as failed (s).")]
        private float stepTimeoutSeconds = 90f;

        [Header("Last resort")]
        [SerializeField]
        [Tooltip("Fallback avatar (Sticker) that the scene keeps disabled. Only shown if the SDK delivers no avatar.")]
        private Transform standIn;

        [SerializeField]
        [Tooltip("Consecutive failed attempts with no avatar set before showing the fallback avatar.")]
        private int standInAfterFailures = 2;

        [SerializeField]
        [Tooltip("Seconds with no avatar set before showing the fallback avatar, even if the load is still running.")]
        private float standInAfterSeconds = 60f;

        [SerializeField]
        [Tooltip("When the avatar appears, it waves hello. Not in debug mode.")]
        private bool greetOnAppear = true;

        /// <summary>File in persistentDataPath with the definition of the last set_avatar (absent if it was null).</summary>
        public const string LastAvatarFileName = "sonia-avatar.json";

        /// <summary>Name of the avatars the SDK builds.</summary>
        public const string LiveAvatarName = "Avatar (Genies)";

        /// <summary>
        /// How long the load is awaited while no SDK avatar is set (the first one on
        /// each machine). It downloads about 90 MB of pieces and, with a normal
        /// connection, does not fit in stepTimeoutSeconds. Abandoning it and
        /// requesting another every 90 s left it on the fallback avatar forever: on
        /// reopening, with the pieces already cached, it built in seconds. One hour:
        /// the network speed is unknown and retrying does not help; meanwhile the
        /// fallback avatar is shown.
        /// </summary>
        private const float FirstLoadMinutes = 60f;

        /// <summary>Where the avatar waits while loading, far from the camera.</summary>
        private static readonly Vector3 ParkedPosition = new Vector3(0f, -1000f, 0f);

        /// <summary>Result of a load that is no longer needed because another definition was requested.</summary>
        private const string Superseded = "superseded by another request";

        /// <summary>Wait between the avatar appearing and the greeting, so the player is already moving it.</summary>
        private const float GreetDelaySeconds = 0.4f;

        // State of this session. [NonSerialized] because on entering Play Unity
        // reloads the domain and, without it, also serializes private fields: a
        // null string came back as "" and looked like a request already made.
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

        /// <summary>True when an SDK avatar is loaded and attached.</summary>
        public bool IsLoaded
        {
            get { return _avatar != null && !_avatar.IsDisposed; }
        }

        /// <summary>True while a load is running or waiting to retry.</summary>
        public bool IsBusy
        {
            get { return _running; }
        }

        /// <summary>True if, for lack of the SDK avatar, the fallback avatar is being shown.</summary>
        public bool ShowingStandIn
        {
            get { return _standInShown && !IsLoaded; }
        }

        /// <summary>App character (SDK JSON).</summary>
        public TextAsset Definition
        {
            get { return definition; }
        }

        /// <summary>Definition of the SDK avatar on screen (null if there is none yet).</summary>
        public string ShownDefinition
        {
            get { return _shownDefinition; }
        }

        /// <summary>Fingerprint (GeniesDefinition.Hash) of the SDK avatar on screen; empty if there is none yet.</summary>
        public string ShownDefinitionHash
        {
            get { return _shownHash; }
        }

        /// <summary>SDK avatar on screen (null if there is none yet).</summary>
        public ManagedAvatar LiveAvatar
        {
            get { return IsLoaded ? _avatar : null; }
        }

        /// <summary>Texture resolution avatars are loaded with.</summary>
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
                return Path.Combine(Application.persistentDataPath, LastAvatarFileName);
            }
        }

        private void Awake()
        {
            if (binder == null)
            {
                binder = GetComponentInParent<AvatarBinder>();
            }

            // Added from code (GeniesAvatarSource): the definition and the fallback
            // avatar are kept by the scene's AvatarBinder.
            if (binder != null)
            {
                if (definition == null)
                {
                    definition = binder.GeniesDefinition;
                }

                if (standIn == null)
                {
                    standIn = binder.StandIn;
                }
            }

            if (client == null)
            {
                client = GetComponentInParent<SoniaClient>();
            }

            if (client == null)
            {
                client = FindAnyObjectByType<SoniaClient>();
            }

            // The fallback avatar only appears as a last resort.
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
            client.OnSetAvatar += HandleSetAvatar;
        }

        private void OnDisable()
        {
            if (client != null)
            {
                client.OnSetDebug -= HandleSetDebug;
                client.OnSetAvatar -= HandleSetAvatar;
            }
        }

        private void Start()
        {
            // Until the SDK one arrives there is no avatar on screen (only the anchor).
            SetShown(null, string.Empty);
            _startTime = Time.realtimeSinceStartup;
            _started = true;
            if (!string.IsNullOrEmpty(_requested))
            {
                // set_avatar arrived before starting.
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
                Debug.Log("[Sonnia] Starting with the last avatar the orchestrator sent (" + remembered.Length
                          + " characters).", this);
            }

            Request(remembered);
        }

        private void Update()
        {
            if (_standInShown || standIn == null || !_started || IsLoaded)
            {
                return;
            }

            bool tooManyFailures = standInAfterFailures > 0 && _failures >= standInAfterFailures;
            bool tooLong = standInAfterSeconds > 0f && Time.realtimeSinceStartup - _startTime >= standInAfterSeconds;
            if (tooManyFailures || tooLong)
            {
                ShowStandIn(tooManyFailures
                    ? _failures + " failed attempts"
                    : "no avatar after " + standInAfterSeconds.ToString("F0") + " s");
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

        /// <summary>Requests that the avatar use this definition (null: the app's character).</summary>
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

        private void HandleSetDebug(SetDebugMessage message)
        {
            _debugQuiet = message != null && message.Enabled;
        }

        private void HandleDefinition(string definitionJson, string messageName)
        {
            string requested = string.IsNullOrWhiteSpace(definitionJson) ? null : definitionJson;
            RememberAvatar(requested);

            // It is a persistent message: it arrives after every hello even if nothing changed.
            string effective = requested ?? AppDefinition;
            if (!string.IsNullOrEmpty(_requested) && GeniesDefinition.Same(effective, _requested))
            {
                return;
            }

            Debug.Log("[Sonnia] " + messageName + ": " + (requested == null
                ? "the app's character"
                : "definition of " + requested.Length + " characters") + ".", this);
            Request(requested);
        }

        private void Request(string definitionJson)
        {
            string effective = string.IsNullOrWhiteSpace(definitionJson) ? AppDefinition : definitionJson;
            if (string.IsNullOrWhiteSpace(effective))
            {
                Debug.LogWarning("[Sonnia] GeniesAvatarLoader has no definition: keeping the current avatar.", this);
                return;
            }

            _requested = effective;
            _requestVersion++;
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
                Debug.LogWarning("[Sonnia] GeniesAvatarLoader has no AvatarBinder: cannot set the avatar.", this);
                return;
            }

            RunAsync(_cancel.Token).Forget();
        }

        /// <summary>Sets the last requested definition and stops when the one on screen is that one.</summary>
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
                    Debug.LogWarning("[Sonnia] Genies avatar not loaded (" + failure + "). Retrying in "
                                     + wait.ToString("F0") + " s.", this);
                    await WaitForRetry(wait, version, token);
                    wait = Mathf.Min(wait * 2f, Mathf.Max(wait, retrySeconds.y));
                }
            }
            catch (OperationCanceledException)
            {
                // The loader was destroyed (end of Play or scene change).
            }
            finally
            {
                _running = false;
            }
        }

        /// <summary>One full attempt. Returns null if the avatar was set; otherwise, why not.</summary>
        private async UniTask<string> TryLoadAsync(string json, int version, CancellationToken token)
        {
            TimeSpan limit = TimeSpan.FromSeconds(Mathf.Max(5f, stepTimeoutSeconds));
            // With no SDK avatar set yet, the download and the build are awaited longer (see FirstLoadMinutes).
            bool first = _avatar == null;
            TimeSpan patient = first ? TimeSpan.FromMinutes(Mathf.Max(FirstLoadMinutes, (float)limit.TotalMinutes)) : limit;
            TimeSpan stepLimit = limit;
            ManagedAvatar pending = null;
            // Current step, to say where it got stuck if it fails or is slow.
            string step = "start the SDK";
            try
            {
                if (!await AvatarSdk.InitializeAsync().Timeout(limit))
                {
                    return "the SDK did not initialize";
                }

                token.ThrowIfCancellationRequested();
                step = "sign in";
                string noSession = await GeniesSession.EnsureLoggedInAsync(limit);
                if (noSession != null)
                {
                    return noSession;
                }

                token.ThrowIfCancellationRequested();

                // Precaching only gets downloads ahead; if it fails, the load tries again.
                step = "precache the pieces";
                stepLimit = patient;
                bool cached = await AvatarSdk.PrecacheAvatarAssetsByDefinitionAsync(json).Timeout(patient);
                if (!cached && _failures == 0)
                {
                    Debug.LogWarning("[Sonnia] Genies could not precache the avatar pieces; trying to build it anyway.", this);
                }

                token.ThrowIfCancellationRequested();
                if (IsSuperseded(version, json))
                {
                    return Superseded;
                }

                step = "build the avatar";
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
                UniTask<ManagedAvatar> watched = Watch(load);
                try
                {
                    stepLimit = patient;
                    pending = await AwaitLoad(watched, limit, patient);
                }
                catch (TimeoutException)
                {
                    if (_failures == 0)
                    {
                        // What the SDK got to build, to know where it got stuck.
                        Debug.LogWarning("[Sonnia] Genies is not finishing building the avatar. In the parking area: "
                                         + DescribeParking(), this);
                    }

                    // The SDK is still building it: the avatar it delivers late is released.
                    DiscardWhenLoaded(watched).Forget();
                    throw;
                }

                if (pending == null || pending.Root == null)
                {
                    return "the SDK returned no avatar";
                }

                pending.Root.transform.localPosition = Vector3.zero;
                if (!pending.IsLoadingComplete)
                {
                    step = "finish loading the avatar";
                    stepLimit = limit;
                    await complete.Task.Timeout(limit);
                }

                token.ThrowIfCancellationRequested();
                if (IsSuperseded(version, json))
                {
                    return Superseded;
                }

                DisableGeniesFaceDriver(pending.Root);
                if (IsSuperseded(version, json))
                {
                    return Superseded;
                }

                // Swap in a single frame: Bind turns off the previous one (the anchor,
                // the fallback avatar or the earlier avatar) and puts this one in place.
                if (!binder.Bind(pending.Root.transform))
                {
                    return "could not attach";
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
                Debug.Log("[Sonnia] Genies SDK avatar set (" + json.Length + " definition characters).", this);
                GreetSoon(token).Forget();
                return null;
            }
            catch (TimeoutException)
            {
                return "\"" + step + "\" took more than " + stepLimit.TotalSeconds.ToString("F0") + " s";
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception exception)
            {
                if (_failures == 0)
                {
                    // The full trace only the first time, to avoid filling the log with retries.
                    Debug.LogWarning("[Sonnia] Genies failed to " + step + ":\n" + exception, this);
                }

                return "while trying to " + step + ": " + exception.GetType().Name + ": " + exception.Message;
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
        /// The SDK load, to await it several times while it keeps running. A UniTask,
        /// even with Preserve, only supports one registered await until it completes:
        /// awaiting it in stretches (AwaitLoad) or again to release it
        /// (DiscardWhenLoaded) gave "Already continuation registered". The first load
        /// was thrown away at 90 s and another was requested instead of waiting up to
        /// FirstLoadMinutes. A UniTaskCompletionSource does support several awaits at once.
        /// </summary>
        internal static UniTask<ManagedAvatar> Watch(UniTask<ManagedAvatar> load)
        {
            UniTaskCompletionSource<ManagedAvatar> source = new UniTaskCompletionSource<ManagedAvatar>();
            Forward(load, source).Forget();
            return source.Task;
        }

        private static async UniTaskVoid Forward(UniTask<ManagedAvatar> load, UniTaskCompletionSource<ManagedAvatar> source)
        {
            try
            {
                source.TrySetResult(await load);
            }
            catch (OperationCanceledException)
            {
                source.TrySetCanceled();
            }
            catch (Exception exception)
            {
                source.TrySetException(exception);
            }
        }

        /// <summary>
        /// Waits for the SDK to deliver the avatar up to <paramref name="total"/>,
        /// without abandoning the load or requesting another; every <paramref name="step"/>
        /// logs how it is going. Throws TimeoutException when <paramref name="total"/> runs
        /// out. The load has to support several awaits (Watch).
        /// </summary>
        private async UniTask<ManagedAvatar> AwaitLoad(UniTask<ManagedAvatar> load, TimeSpan step, TimeSpan total)
        {
            DateTime until = DateTime.UtcNow + total;
            while (true)
            {
                TimeSpan left = until - DateTime.UtcNow;
                if (left <= TimeSpan.Zero)
                {
                    throw new TimeoutException();
                }

                try
                {
                    return await load.Timeout(left < step ? left : step);
                }
                catch (TimeoutException)
                {
                    if (DateTime.UtcNow >= until - TimeSpan.FromSeconds(1))
                    {
                        throw;
                    }

                    Debug.Log("[Sonnia] Genies is still building the avatar (the first time on this machine it downloads "
                              + "the pieces; waiting up to " + total.TotalMinutes.ToString("F0")
                              + " min). In the parking area: " + DescribeParking(), this);
                }
            }
        }

        /// <summary>
        /// Where a new avatar is built until Bind puts it in place: far below the
        /// floor. The SDK builds it under its parent and, hung from the avatar root,
        /// it was seen from behind in place meanwhile.
        /// </summary>
        private Transform ParkingLot()
        {
            if (_parking == null)
            {
                _parking = new GameObject("Genies (loading)").transform;
                _parking.SetParent(binder.transform, false);
                _parking.localPosition = ParkedPosition;
            }

            return _parking;
        }

        /// <summary>
        /// Summary of what is in the parking area (objects, meshes, materials and
        /// textures set), for the log when a load gets stuck.
        /// </summary>
        private string DescribeParking()
        {
            if (_parking == null || _parking.childCount == 0)
            {
                return "nothing (the SDK never created the avatar)";
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

                sb.Append('"').Append(child.name).Append("\" ")
                  .Append(child.GetComponentsInChildren<Transform>(true).Length).Append(" objects, ")
                  .Append(renderers.Length).Append(" renderers, ")
                  .Append(vertices).Append(" vertices, ")
                  .Append(materials).Append(" materials, ")
                  .Append(textures).Append(" textures set and ")
                  .Append(emptySlots).Append(" empty texture slots; ");
            }

            return sb.ToString();
        }

        /// <summary>
        /// Releases the avatar of a load abandoned on timeout when the SDK delivers it.
        /// The load has to support another await (Watch).
        /// </summary>
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
                // The abandoned load failed too: nothing to release.
            }
        }

        /// <summary>Last resort: the SDK delivers no avatar and the fallback avatar kept by the scene is shown.</summary>
        private void ShowStandIn(string reason)
        {
            _standInShown = true;
            standIn.gameObject.SetActive(true);
            if (!binder.Bind(standIn))
            {
                standIn.gameObject.SetActive(false);
                Debug.LogWarning("[Sonnia] Could not show the fallback avatar (" + reason + ").", this);
                return;
            }

            Debug.LogWarning("[Sonnia] The Genies SDK is not delivering the avatar (" + reason
                             + "): showing the fallback avatar while retrying.", this);
            if (_cancel != null)
            {
                GreetSoon(_cancel.Token).Forget();
            }
        }

        /// <summary>On appearing, the avatar waves hello (if it can: idle or listening, and not in debug mode).</summary>
        private async UniTaskVoid GreetSoon(CancellationToken token)
        {
            if (!greetOnAppear)
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

        /// <summary>True if, while this definition was loading, a different one was requested.</summary>
        private bool IsSuperseded(int version, string json)
        {
            return _requestVersion != version && !GeniesDefinition.Same(_requested, json);
        }

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
                Debug.LogWarning("[Sonnia] Could not read the last remembered avatar: " + exception.Message, this);
                return null;
            }
        }

        /// <summary>Remembers the definition of the last set_avatar; null (the app's character) deletes the file.</summary>
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

                // Write aside and rename: an interruption midway does not leave a broken file.
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
                Debug.LogWarning("[Sonnia] Could not remember the avatar: " + exception.Message, this);
            }
        }

        /// <summary>Turns off the Genies bridge between Animator parameters and face shapes (internal to the SDK).</summary>
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
