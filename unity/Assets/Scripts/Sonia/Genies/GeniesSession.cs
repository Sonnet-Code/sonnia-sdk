// Genies session shared by everything that needs it (the avatar loader and
// anything else that talks to the Genies SDK).
//
// AvatarSdk.StartLoginAnonymousAsync does not tolerate two simultaneous calls:
// the second one discards the flow of the first (CoreSdk.LoginAnonymous) and the
// first ends in a NullReferenceException even though the sign-in went fine. In
// the editor this goes unnoticed because the session is restored from the
// keychain at startup; in a built app there is no keychain (every launch does a
// new anonymous sign-in), so concurrent callers would collide. Here they all
// wait for the same attempt.

using System;
using Cysharp.Threading.Tasks;
using Genies.Sdk;
using UnityEngine;

namespace Sonia
{
    /// <summary>One Genies sign-in at a time (instant if possible, anonymous otherwise).</summary>
    public static class GeniesSession
    {
        // Attempt in progress. It is a UniTaskCompletionSource because it supports
        // several simultaneous awaiters; a UniTask with Preserve() supports only
        // one until it completes ("Already continuation registered").
        private static UniTaskCompletionSource<string> _pending;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void ResetState()
        {
            // Without domain reload on entering Play, statics survive.
            _pending = null;
        }

        /// <summary>
        /// Signs in if needed. Returns null if there is a session and, if not, the
        /// reason. If an attempt is already running, it waits for that one. SDK
        /// failures (and the TimeoutException from <paramref name="limit"/>) arrive
        /// as an exception.
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

            var login = await AvatarSdk.StartLoginAnonymousAsync().Timeout(limit);
            return login.succeeded ? null : "no session: " + login.failReason;
        }

        /// <summary>The next caller to ask for a session starts a new attempt.</summary>
        private static void Finish(UniTaskCompletionSource<string> attempt)
        {
            if (_pending == attempt)
            {
                _pending = null;
            }
        }
    }
}
