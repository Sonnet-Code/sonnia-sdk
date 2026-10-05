// Sesión de Genies compartida por todo lo que la necesita: los dos cargadores de
// avatar (Sonia y el invitado del Modo Jean) y el editor de personaje.
//
// AvatarSdk.StartLoginAnonymousAsync no aguanta dos llamadas a la vez: la segunda
// desecha el flujo de la primera (CoreSdk.LoginAnonymous) y la primera acaba en
// NullReferenceException aunque el registro haya ido bien. En el editor no se
// notaba porque la sesión se restaura del llavero al arrancar; en la app no hay
// llavero (cada arranque hace un registro anónimo nuevo) y Sonia y el invitado
// arrancan a la vez. Aquí todos esperan al mismo intento.

using System;
using Cysharp.Threading.Tasks;
using Genies.Sdk;
using UnityEngine;

namespace Sonia
{
    /// <summary>Un solo inicio de sesión en Genies a la vez (instantáneo y, si no, anónimo).</summary>
    public static class GeniesSession
    {
        // Intento en marcha. Es un UniTaskCompletionSource porque admite varias
        // esperas a la vez; un UniTask con Preserve() solo admite una mientras no
        // ha terminado («Already continuation registered»).
        private static UniTaskCompletionSource<string> _pending;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void ResetState()
        {
            // Sin recarga de dominio al entrar en Play, lo estático sigue ahí.
            _pending = null;
        }

        /// <summary>
        /// Inicia sesión si hace falta. Devuelve null si hay sesión y, si no, por
        /// qué. Si ya hay un intento en marcha, espera a ese. Los fallos del SDK
        /// (y el TimeoutException de <paramref name="limit"/>) llegan como excepción.
        /// </summary>
        public static UniTask<string> EnsureLoggedInAsync(TimeSpan limit)
        {
            if (AvatarSdk.IsLoggedIn)
            {
                return UniTask.FromResult<string>(null);
            }

            if (_pending == null)
            {
                _pending = new UniTaskCompletionSource<string>();
                RunAsync(limit, _pending).Forget();
            }

            return _pending.Task;
        }

        private static async UniTaskVoid RunAsync(TimeSpan limit, UniTaskCompletionSource<string> attempt)
        {
            try
            {
                string failure = await LogInAsync(limit);
                Finish(attempt);
                attempt.TrySetResult(failure);
            }
            catch (Exception exception)
            {
                Finish(attempt);
                attempt.TrySetException(exception);
            }
        }

        private static async UniTask<string> LogInAsync(TimeSpan limit)
        {
            var instant = await AvatarSdk.TryInstantLoginAsync().Timeout(limit);
            if (instant.isLoggedIn || AvatarSdk.IsLoggedIn)
            {
                return null;
            }

            var guest = await AvatarSdk.StartLoginAnonymousAsync().Timeout(limit);
            return guest.succeeded ? null : "sin sesión: " + guest.failReason;
        }

        /// <summary>El siguiente que pida sesión ya empieza un intento nuevo.</summary>
        private static void Finish(UniTaskCompletionSource<string> attempt)
        {
            if (_pending == attempt)
            {
                _pending = null;
            }
        }
    }
}
