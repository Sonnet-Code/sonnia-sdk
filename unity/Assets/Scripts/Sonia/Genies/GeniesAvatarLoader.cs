// Carga el avatar de Sonia con el Genies Avatar SDK y lo pone en el sitio del doble.
//
// Al arrancar: sesión (la guardada o como invitado), precarga de sus piezas y
// carga desde la definición JSON del repo, directamente en la calidad pedida (sin
// silueta ni pasos intermedios). Mientras carga se queda lejos de la cámara;
// cuando el SDK avisa de que está completo, AvatarBinder lo coloca y apaga el
// doble. Si algo falla (sin red, sin credenciales, el SDK no responde) se
// reintenta con espera creciente y el doble sigue en pantalla mientras tanto:
// Sonia nunca se queda sin avatar.
//
// La cara la escribe FaceRig directamente en las formas FACS. El
// BlendShapeAnimatorBehaviour de Genies, que haría lo mismo desde los parámetros
// de su Animator Controller, se apaga: MotionPlayer sustituye ese controlador y
// sin él esos parámetros no existen.

using System;
using System.Threading;
using Cysharp.Threading.Tasks;
using Genies.Sdk;
using UnityEngine;

namespace Sonia
{
    /// <summary>Carga el avatar del SDK de Genies y se lo pasa a AvatarBinder.</summary>
    [DisallowMultipleComponent]
    public class GeniesAvatarLoader : MonoBehaviour
    {
        [SerializeField]
        [Tooltip("Definición del avatar (JSON del SDK: piezas, colores y medidas).")]
        private TextAsset definition;

        [SerializeField]
        [Tooltip("Quién engancha el avatar al pipeline de Sonia. Vacío: el del objeto padre.")]
        private AvatarBinder binder;

        [SerializeField]
        [Tooltip("Resolución de las texturas del avatar.")]
        private AvatarLods quality = AvatarLods.High;

        [SerializeField]
        [Tooltip("Cargar al arrancar. Si no, hay que llamar a Load.")]
        private bool loadOnStart = true;

        [SerializeField]
        [Tooltip("Espera entre reintentos (s): la primera y el máximo; se dobla en cada fallo.")]
        private Vector2 retrySeconds = new Vector2(5f, 120f);

        [SerializeField]
        [Tooltip("Tiempo máximo de cada paso (iniciar el SDK, la sesión, la carga) antes de darlo por fallido (s).")]
        private float stepTimeoutSeconds = 90f;

        /// <summary>Donde espera el avatar mientras carga, lejos de la cámara.</summary>
        private static readonly Vector3 ParkedPosition = new Vector3(0f, -1000f, 0f);

        private CancellationTokenSource _cancel;
        private ManagedAvatar _avatar;
        private bool _running;

        /// <summary>Cierto cuando el avatar del SDK está cargado y enganchado.</summary>
        public bool IsLoaded
        {
            get { return _avatar != null && !_avatar.IsDisposed; }
        }

        private void Awake()
        {
            if (binder == null)
            {
                binder = GetComponentInParent<AvatarBinder>();
            }
        }

        private void Start()
        {
            if (loadOnStart)
            {
                Load();
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

            if (_avatar != null && !_avatar.IsDisposed)
            {
                _avatar.Dispose();
            }

            _avatar = null;
        }

        /// <summary>Empieza la carga si no hay una en marcha ni un avatar ya cargado.</summary>
        public void Load()
        {
            if (_running || IsLoaded)
            {
                return;
            }

            if (definition == null || binder == null)
            {
                Debug.LogWarning("[Sonia] GeniesAvatarLoader sin definición o sin AvatarBinder: sigue el doble.", this);
                return;
            }

            if (_cancel != null)
            {
                _cancel.Dispose();
            }

            _cancel = new CancellationTokenSource();
            RunAsync(_cancel.Token).Forget();
        }

        private async UniTaskVoid RunAsync(CancellationToken token)
        {
            _running = true;
            float wait = Mathf.Max(1f, retrySeconds.x);
            try
            {
                while (!token.IsCancellationRequested)
                {
                    string failure = await TryLoadAsync(token);
                    if (failure == null)
                    {
                        return;
                    }

                    Debug.LogWarning("[Sonia] Avatar de Genies sin cargar (" + failure + "); sigue el doble. Reintento en "
                                     + wait.ToString("F0") + " s.", this);
                    await UniTask.Delay(TimeSpan.FromSeconds(wait), cancellationToken: token);
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

        /// <summary>Un intento completo. Devuelve null si el avatar quedó enganchado; si no, por qué falló.</summary>
        private async UniTask<string> TryLoadAsync(CancellationToken token)
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
                string json = definition.text;

                // La precarga solo adelanta descargas; si falla, la carga lo vuelve a intentar.
                await AvatarSdk.PrecacheAvatarAssetsByDefinitionAsync(json).Timeout(limit);
                token.ThrowIfCancellationRequested();

                UniTaskCompletionSource<bool> complete = new UniTaskCompletionSource<bool>();
                pending = await AvatarSdk.LoadAvatarAsync(new LoadAvatarOptions.ByDefinition
                {
                    DefinitionToLoad = json,
                    AvatarName = "Avatar (Genies)",
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
                DisableGeniesFaceDriver(pending.Root);
                if (!binder.Bind(pending.Root.transform))
                {
                    return "no se pudo enganchar";
                }

                _avatar = pending;
                pending = null;
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
