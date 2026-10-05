// Saca de Genies el pelo aplastado bajo gorra del avatar de Sonia, para el gorro
// de la trivia (HatHair, TriviaHat).
//
// NAF solo aplasta el pelo cuando el avatar lleva una gorra oficial, y lo hornea
// en la malla. Así que, cada vez que se pone un avatar de Sonia
// (GeniesAvatarLoader.AvatarShown), al rato se monta a escondidas una gemela: la
// misma definición más la gorra de referencia (ReferenceHat, la oficial con la
// que se midió el encaje de la gorra Noogler), muy por debajo del suelo y sin
// silueta. De ella se copia la forma del pelo (HatHair.Build) y se suelta. Vale
// para cualquier pelo, porque lo aplasta Genies, y al cambiar de avatar se
// vuelve a sacar.
//
// No hace nada si Sonia no lleva pelo o ya lleva una gorra oficial (su pelo ya
// va aplastado y el gorro de la trivia la esconde). Si falla por la red o por
// tiempo, se vuelve a intentar cuando el gorro lo pide (HatHair.Request, al
// ponérselo); si las mallas no casan, se avisa y el gorro se pone sin aplastar
// el pelo.

using System;
using System.Collections.Generic;
using System.Threading;
using Cysharp.Threading.Tasks;
using Genies.Sdk;
using UnityEngine;

namespace Sonia
{
    /// <summary>Saca con Genies el pelo bajo gorra del avatar de Sonia (ver HatHair).</summary>
    public static class GeniesHatHair
    {
        /// <summary>Gorra oficial de referencia: la naranja de llamas con la que se encajó la gorra Noogler.</summary>
        public const string ReferenceHat = "WardrobeGear/recRecBCofFMJ5Hox";

        /// <summary>Espera tras ponerse el avatar antes de montar la gemela (que no coincida con el saludo).</summary>
        private const float DelaySeconds = 3f;

        /// <summary>Tiempo máximo de cada paso (precargar, montar) antes de darlo por fallido (s).</summary>
        private const float StepTimeoutSeconds = 90f;

        /// <summary>Donde se monta la gemela: lejos de la cámara y del aparcamiento del cargador.</summary>
        private static readonly Vector3 TwinPosition = new Vector3(0f, -2000f, 0f);

        // Último avatar de Sonia y cómo fue con él.
        private static GeniesAvatarLoader _loader;
        private static ManagedAvatar _live;
        private static string _definition;
        private static bool _baking;
        private static bool _settled;
        private static CancellationTokenSource _cancel;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void Install()
        {
            // Sin recarga de dominio al entrar en Play, lo estático sigue ahí.
            GeniesAvatarLoader.AvatarShown -= HandleAvatarShown;
            GeniesAvatarLoader.AvatarShown += HandleAvatarShown;
            HatHair.Requested -= HandleRequested;
            HatHair.Requested += HandleRequested;
            Application.quitting -= Stop;
            Application.quitting += Stop;
            Stop();
            _loader = null;
            _live = null;
            _definition = null;
        }

        private static void HandleAvatarShown(GeniesAvatarLoader loader, string json)
        {
            if (loader == null || loader.Role != AvatarRole.Sonia)
            {
                return;
            }

            Stop();
            _loader = loader;
            _live = loader.LiveAvatar;
            _definition = json;
            Start(DelaySeconds);
        }

        private static void HandleRequested(Transform avatar)
        {
            // Solo si la primera vez falló por la red o por tiempo.
            if (_baking || _settled || _live == null || _live.IsDisposed || _live.Root == null
                || _live.Root.transform != avatar)
            {
                return;
            }

            Start(0f);
        }

        private static void Start(float delay)
        {
            if (_live == null || string.IsNullOrWhiteSpace(_definition))
            {
                return;
            }

            if (_cancel != null)
            {
                _cancel.Dispose();
            }

            _cancel = new CancellationTokenSource();
            BakeAsync(_loader, _live, _definition, delay, _cancel.Token).Forget();
        }

        private static void Stop()
        {
            if (_cancel != null)
            {
                _cancel.Cancel();
                _cancel.Dispose();
                _cancel = null;
            }

            _baking = false;
            _settled = false;
        }

        private static async UniTaskVoid BakeAsync(GeniesAvatarLoader loader, ManagedAvatar live, string json, float delay, CancellationToken token)
        {
            _baking = true;
            TimeSpan limit = TimeSpan.FromSeconds(StepTimeoutSeconds);
            ManagedAvatar twin = null;
            GameObject spot = null;
            string step = "esperar al avatar";
            try
            {
                if (delay > 0f)
                {
                    await UniTask.Delay(TimeSpan.FromSeconds(delay), ignoreTimeScale: true, cancellationToken: token);
                }

                if (live.IsDisposed || live.Root == null)
                {
                    return;
                }

                Transform avatar = live.Root.transform;
                SkinnedMeshRenderer renderer = HatHair.HairRenderer(avatar);
                if (renderer == null)
                {
                    _settled = true;
                    return;
                }

                if (WearsOfficialHat(avatar))
                {
                    _settled = true;
                    Debug.Log("[Sonia] Pelo bajo gorra: Sonia ya lleva una gorra oficial, así que su pelo ya va aplastado.");
                    return;
                }

                string definition = GeniesDefinition.WithAsset(json, ReferenceHat);
                if (definition == null)
                {
                    _settled = true;
                    Debug.LogWarning("[Sonia] Pelo bajo gorra sin sacar: la definición del avatar no se entiende.");
                    return;
                }

                float start = Time.realtimeSinceStartup;
                step = "precargar la gorra de referencia";
                await AvatarSdk.PrecacheAvatarAssetsByDefinitionAsync(definition).Timeout(limit);
                token.ThrowIfCancellationRequested();

                // Montar con el editor de personaje en pantalla se atascaba (GeniesAvatarLoader).
                await UniTask.WaitWhile(() => AvatarEditorSession.IsOpen, cancellationToken: token);
                step = "montar la gemela";
                spot = new GameObject("Genies (pelo bajo gorra)");
                spot.transform.position = TwinPosition;
                UniTask<ManagedAvatar> load = AvatarSdk.LoadAvatarAsync(new LoadAvatarOptions.ByDefinition
                {
                    DefinitionToLoad = definition,
                    AvatarName = "Gemela con gorra",
                    Parent = spot.transform,
                    ShowLoadingSilhouette = false,
                    TargetLods = new[] { loader != null ? loader.Quality : AvatarLods.High }
                }).Preserve();
                try
                {
                    twin = await load.Timeout(limit);
                }
                catch (TimeoutException)
                {
                    DiscardWhenLoaded(load).Forget();
                    throw;
                }

                if (twin == null || twin.Root == null)
                {
                    Debug.LogWarning("[Sonia] Pelo bajo gorra sin sacar: el SDK no devolvió la gemela.");
                    return;
                }

                ManagedAvatar loading = twin;
                await UniTask.WaitUntil(() => loading.IsDisposed || loading.IsLoadingComplete, cancellationToken: token)
                    .Timeout(limit);
                token.ThrowIfCancellationRequested();
                if (twin.IsDisposed || live.IsDisposed || live.Root == null || renderer == null)
                {
                    return;
                }

                step = "comparar el pelo";
                Mesh mesh = HatHair.Build(renderer, HatHair.HairRenderer(twin.Root.transform), out string report);
                _settled = true;
                if (mesh == null)
                {
                    Debug.LogWarning("[Sonia] Pelo bajo gorra sin sacar: " + report + ".");
                    return;
                }

                HatHair.Publish(new HatHair.Flat
                {
                    Avatar = avatar,
                    Renderer = renderer,
                    Source = renderer.sharedMesh,
                    Mesh = mesh,
                    Shape = mesh.GetBlendShapeIndex(HatHair.ShapeName)
                });
                Debug.Log("[Sonia] Pelo bajo gorra listo para la trivia (" + report + "; gemela en "
                          + (Time.realtimeSinceStartup - start).ToString("F1") + " s).");
            }
            catch (OperationCanceledException)
            {
                // Otro avatar o fin de Play.
            }
            catch (TimeoutException)
            {
                Debug.LogWarning("[Sonia] Pelo bajo gorra sin sacar: «" + step + "» tardó más de "
                                 + limit.TotalSeconds.ToString("F0") + " s. Se reintenta al ponerse el gorro.");
            }
            catch (Exception exception)
            {
                Debug.LogWarning("[Sonia] Pelo bajo gorra sin sacar (al " + step + "): " + exception.Message
                                 + ". Se reintenta al ponerse el gorro.");
            }
            finally
            {
                if (twin != null && !twin.IsDisposed)
                {
                    twin.Dispose();
                }

                if (spot != null)
                {
                    UnityEngine.Object.Destroy(spot);
                }

                if (live == _live)
                {
                    _baking = false;
                }
            }
        }

        /// <summary>Cierto si el avatar lleva una gorra oficial (la que el gorro de la trivia esconde).</summary>
        private static bool WearsOfficialHat(Transform avatar)
        {
            Animator animator = avatar.GetComponentInChildren<Animator>(true);
            Transform head = animator != null && animator.isHuman ? animator.GetBoneTransform(HumanBodyBones.Head) : null;
            if (head == null)
            {
                return false;
            }

            var parts = new List<TriviaHat.HatPart>();
            TriviaHat.FindHatParts(avatar, head, parts);
            return parts.Count > 0;
        }

        /// <summary>Suelta la gemela de una carga abandonada por tiempo cuando el SDK la entregue.</summary>
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
    }
}
