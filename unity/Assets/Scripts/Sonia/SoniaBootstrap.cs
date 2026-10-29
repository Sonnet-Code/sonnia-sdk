// Root of the Sonnia scene: wires the WebSocket client to the audio, the
// lip-sync, the avatar state, the image panel and the camera, and applies the
// display settings (keep running in background, no screen sleep...).

using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>
    /// The single place where the components are wired together. If one is
    /// missing, the rest keep working.
    /// </summary>
    [DisallowMultipleComponent]
    public class SoniaBootstrap : MonoBehaviour
    {
        [Header("Components")]
        [SerializeField]
        [Tooltip("WebSocket client toward the orchestrator.")]
        private SoniaClient client;

        [SerializeField]
        [Tooltip("Streaming audio player.")]
        private AudioStreamPlayer audioPlayer;

        [SerializeField]
        [Tooltip("Lip-sync by visemes or by envelope.")]
        private LipSyncController lipSync;

        [SerializeField]
        [Tooltip("Avatar animations, gaze and blinking.")]
        private AvatarStateController avatarState;

        [SerializeField]
        [Tooltip("Choreographer: picks the clip for each state, the idle gestures and the greeting. Optional.")]
        private AvatarChoreographer choreographer;

        [SerializeField]
        [Tooltip("Widens the camera shot during dances and the greeting. Optional.")]
        private CameraFramingController cameraFraming;

        [SerializeField]
        [Tooltip("The scene's image panel.")]
        private ImagePanelController imagePanel;

        [SerializeField]
        [Tooltip("Webcam capture sender. Only with VISION_SOURCE=unity.")]
        private WebcamFrameSender webcam;

        [SerializeField]
        [Tooltip("Debug HUD. Optional.")]
        private SoniaDebugUI debugUI;

        [SerializeField]
        [Tooltip("Walking out and back in (away mode) with its away sign. If the scene lacks it, it is added by code on this object.")]
        private PresenceController presence;

        [Header("Away mode")]
        [SerializeField]
        [Range(0f, 10f)]
        [Tooltip("An 'away' presence that arrives within this many seconds after the hello (the orchestrator re-sends it to each new client) is applied without animation: Sonnia is already hidden and the away sign is up.")]
        private float presenceInstantWindowSeconds = 2f;

        [Header("Display")]
        [SerializeField]
        [Tooltip("Keep running even when the window loses focus. Essential for an unattended installation.")]
        private bool runInBackground = true;

        [SerializeField]
        [Tooltip("Prevent the screen from sleeping.")]
        private bool preventScreenSleep = true;

        [SerializeField]
        [Tooltip("Show the mouse cursor.")]
        private bool showCursor = true;

        [SerializeField]
        [Tooltip("Target frames per second. 0 keeps the platform default.")]
        private int targetFrameRate = 60;

        [Header("Sync")]
        [SerializeField]
        [Tooltip("Delay the 'speaking' state (gestures, brows) until the first audio of the utterance arrives. The orchestrator sends speech_start and the state when synthesis begins, and the voice takes 0.3 to 1.5 s to arrive: without this Sonnia gestures with her mouth closed.")]
        private bool waitAudioBeforeSpeaking = true;

        [SerializeField]
        [Range(0.5f, 10f)]
        [Tooltip("Seconds to wait for audio before applying the 'speaking' state anyway (in case speech synthesis fails silently). Talking gestures stay paused until real audio arrives.")]
        private float speakingAudioTimeout = 4f;

        [SerializeField]
        [Range(0f, 3f)]
        [Tooltip("If the audio runs out mid-reply and no more arrives within this many seconds, talking gestures pause (attentive wait) until the voice returns. 0 disables it.")]
        private float speechGapPauseSeconds = 0.4f;


        [Header("Logging")]
        [SerializeField]
        [Tooltip("Write the important protocol events to the console.")]
        private bool logEvents = true;

        // Utterance announced by speech_start whose audio has not arrived yet.
        private int _pendingUtteranceId = -1;
        private bool _pendingSpeechStart;
        private bool _pendingSpeakingState;
        private float _pendingSince;
        private int _lastAudioUtteranceId = -1;
        // Moment the audio ran out in the middle of 'speaking' (-1 if playing).
        private float _audioDrainedAt = -1f;
        // Announced image waiting for the hand to reach the top. [NonSerialized]:
        // the domain reload on entering Play also serializes private fields and
        // brought it back as an empty image, not as null.
        [System.NonSerialized]
        private ShowImageMessage _pendingImage;
        // Time of the last hello (to apply the presence that follows it without animation).
        private float _helloAt = -999f;

        // Full animation set (the asset) and the copy without what the panel
        // disabled, which is the one the choreographer uses for what it does on its own.
        private SoniaMotionSet _fullMotionSet;
        private SoniaMotionSet _filteredMotionSet;
        private readonly HashSet<string> _disabledClips = new HashSet<string>();
        private bool _debugQuiet;

        // Last clip reported with animation_playing (to send only the changes).
        private string _reportedClip;
        private bool _clipReported;

        private void Awake()
        {
            ResolveReferences();
            ApplyDisplaySettings();
            ScreenshotService.InstallFromCommandLine(gameObject);
        }

        private void OnEnable()
        {
            if (client != null)
            {
                client.OnConnected += HandleConnected;
                client.OnDisconnected += HandleDisconnected;
                client.OnHello += HandleHello;
                client.OnState += HandleState;
                client.OnTranscript += HandleTranscript;
                client.OnSpeechStart += HandleSpeechStart;
                client.OnAudioFrame += HandleAudioFrame;
                client.OnSpeechEnd += HandleSpeechEnd;
                client.OnStopSpeaking += HandleStopSpeaking;
                client.OnShowImage += HandleShowImage;
                client.OnHideImage += HandleHideImage;
                client.OnAttention += HandleAttention;
                client.OnPlayAnimation += HandlePlayAnimation;
                client.OnSetDisabledAnimations += HandleSetDisabledAnimations;
                client.OnSetDebug += HandleSetDebug;
                client.OnSetTuning += HandleSetTuning;
                client.OnPresence += HandlePresence;
                client.OnSetVolume += HandleSetVolume;
                client.OnError += HandleError;
                client.OnRequestFrame += HandleRequestFrame;
            }

            if (audioPlayer != null)
            {
                audioPlayer.OnUtterancePlaybackDone += HandlePlaybackDone;
            }
        }

        private void OnDisable()
        {
            if (client != null)
            {
                client.OnConnected -= HandleConnected;
                client.OnDisconnected -= HandleDisconnected;
                client.OnHello -= HandleHello;
                client.OnState -= HandleState;
                client.OnTranscript -= HandleTranscript;
                client.OnSpeechStart -= HandleSpeechStart;
                client.OnAudioFrame -= HandleAudioFrame;
                client.OnSpeechEnd -= HandleSpeechEnd;
                client.OnStopSpeaking -= HandleStopSpeaking;
                client.OnShowImage -= HandleShowImage;
                client.OnHideImage -= HandleHideImage;
                client.OnAttention -= HandleAttention;
                client.OnPlayAnimation -= HandlePlayAnimation;
                client.OnSetDisabledAnimations -= HandleSetDisabledAnimations;
                client.OnSetDebug -= HandleSetDebug;
                client.OnSetTuning -= HandleSetTuning;
                client.OnPresence -= HandlePresence;
                client.OnSetVolume -= HandleSetVolume;
                client.OnError -= HandleError;
                client.OnRequestFrame -= HandleRequestFrame;
            }

            if (audioPlayer != null)
            {
                audioPlayer.OnUtterancePlaybackDone -= HandlePlaybackDone;
            }
        }

        private void ResolveReferences()
        {
            if (client == null)
            {
                client = GetComponentInChildren<SoniaClient>(true);
            }

            if (audioPlayer == null)
            {
                audioPlayer = GetComponentInChildren<AudioStreamPlayer>(true);
            }

            if (lipSync == null)
            {
                lipSync = GetComponentInChildren<LipSyncController>(true);
            }

            if (avatarState == null)
            {
                avatarState = GetComponentInChildren<AvatarStateController>(true);
            }

            if (choreographer == null)
            {
                choreographer = GetComponentInChildren<AvatarChoreographer>(true);
            }

            if (cameraFraming == null)
            {
                cameraFraming = GetComponentInChildren<CameraFramingController>(true);
            }

            if (imagePanel == null)
            {
                // Only children are searched: if the panel lives elsewhere in the
                // scene it must be assigned by hand in the inspector.
                imagePanel = GetComponentInChildren<ImagePanelController>(true);
            }

            if (webcam == null)
            {
                webcam = GetComponentInChildren<WebcamFrameSender>(true);
            }

            if (debugUI == null)
            {
                debugUI = GetComponentInChildren<SoniaDebugUI>(true);
            }

            if (presence == null)
            {
                presence = GetComponentInChildren<PresenceController>(true);
            }

            if (presence == null)
            {
                // By code, to leave the scene untouched: it assembles itself from
                // what it finds (choreographer, gaze, camera) and creates its away sign.
                presence = gameObject.AddComponent<PresenceController>();
            }

            if (cameraFraming != null)
            {
                cameraFraming.Presence = presence;
            }

            if (GetComponent<TriviaController>() == null)
            {
                // Also by code: draws the trivia on the HUD (card, confetti) when
                // the orchestrator sends it.
                gameObject.AddComponent<TriviaController>();
            }

            if (GetComponent<StageScreen>() == null)
            {
                // Also by code: the stage screen (backdrop, logo, QR, invitation to
                // talk and subtitles).
                gameObject.AddComponent<StageScreen>();
            }

            if (GetComponent<BusyIndicator>() == null)
            {
                // Also by code: the busy indicator, a pill on top of everything
                // while Sonnia thinks, searches or looks at the photo.
                gameObject.AddComponent<BusyIndicator>();
            }

            if (GetComponent<StageParticles>() == null)
            {
                // Also by code: the stage particles (motes, trivia and the
                // Matrix-style rain when searching or taking long).
                gameObject.AddComponent<StageParticles>();
            }

        }

        private void ApplyDisplaySettings()
        {
            Application.runInBackground = runInBackground;

            if (preventScreenSleep)
            {
                Screen.sleepTimeout = SleepTimeout.NeverSleep;
            }

            Cursor.visible = showCursor;

            if (targetFrameRate > 0)
            {
                Application.targetFrameRate = targetFrameRate;
            }
        }

        // ------------------------------------------------------------------
        // Protocol events
        // ------------------------------------------------------------------

        private void HandleConnected()
        {
            if (logEvents)
            {
                Debug.Log("[Sonnia] Connected to the orchestrator.", this);
            }
        }

        private void HandleDisconnected()
        {
            _pendingSpeakingState = false;
            _pendingSpeechStart = false;
            _pendingUtteranceId = -1;
            if (logEvents)
            {
                Debug.Log("[Sonnia] Connection lost; the client will retry.", this);
            }

            if (audioPlayer != null)
            {
                audioPlayer.Flush();
            }

            if (lipSync != null)
            {
                lipSync.StopAndClose();
            }

            ApplyAvatarState(AvatarState.Idle);

            // If the connection drops in the middle of a dance, the camera stays
            // wide until the clip ends. Better to return to the medium shot now.
            // Not when away (or leaving): Sonnia stays away until the orchestrator
            // says otherwise on reconnect, and the camera keeps its shot.
            if (cameraFraming != null && (presence == null || presence.IsPresent))
            {
                cameraFraming.ResetToBase();
            }
        }

        /// <summary>
        /// Distributes the state among all the components that animate the avatar.
        /// Any that is not assigned is simply skipped.
        /// </summary>
        private void ApplyAvatarState(AvatarState state)
        {
            _audioDrainedAt = -1f;
            if (avatarState != null)
            {
                avatarState.SetState(state);
            }

            if (choreographer != null)
            {
                choreographer.SetState(state);
            }
        }

        private void HandleHello(HelloMessage message)
        {
            if (message == null)
            {
                return;
            }

            _helloAt = Time.unscaledTime;
            if (audioPlayer != null)
            {
                audioPlayer.SetSourceSampleRate(message.SampleRate);
            }

            if (logEvents)
            {
                Debug.Log(
                    "[Sonnia] hello: version " + message.Version + ", " + message.SampleRate + " Hz, "
                    + message.Channels + " channel(s), format " + message.Format,
                    this);
            }

            SendAnimationCatalog();
            _clipReported = false;
        }

        /// <summary>
        /// The full set, as the scene assigned it. It is recorded the first time
        /// because the choreographer later receives the filtered copy.
        /// </summary>
        private SoniaMotionSet FullMotionSet
        {
            get
            {
                if (_fullMotionSet == null && choreographer != null)
                {
                    _fullMotionSet = choreographer.MotionSet;
                }

                return _fullMotionSet;
            }
        }

        /// <summary>Tells the orchestrator which animations the panel can trigger one by one.</summary>
        private void SendAnimationCatalog()
        {
            if (client == null || FullMotionSet == null)
            {
                return;
            }

            List<KeyValuePair<string, string>> pairs = AnimationCatalog.ToPairs(AnimationCatalog.Build(FullMotionSet));
            client.SendAnimations(pairs);
        }

        private void HandleSetDisabledAnimations(SetDisabledAnimationsMessage message)
        {
            if (message == null)
            {
                return;
            }

            _disabledClips.Clear();
            if (message.Clips != null)
            {
                foreach (string clip in message.Clips)
                {
                    if (!string.IsNullOrEmpty(clip))
                    {
                        _disabledClips.Add(clip);
                    }
                }
            }

            ApplyMotionFilter();
            if (logEvents)
            {
                Debug.Log("[Sonnia] animations it does not use on its own: " + _disabledClips.Count, this);
            }
        }

        private void HandleSetDebug(SetDebugMessage message)
        {
            if (message == null)
            {
                return;
            }

            _debugQuiet = message.Enabled;
            ApplyMotionFilter();
            if (logEvents)
            {
                Debug.Log("[Sonnia] debug mode " + (_debugQuiet ? "on: nothing automatic" : "off"), this);
            }
        }

        /// <summary>Panel "Developer" settings: mouth (lip-sync) and camera framing.</summary>
        private void HandleSetTuning(SetTuningMessage message)
        {
            if (message == null)
            {
                return;
            }

            MouthTuning mouth = message.Mouth ?? new MouthTuning();
            CameraTuning view = message.Camera ?? new CameraTuning();
            IdleTuning idle = message.Idle ?? new IdleTuning();
            if (lipSync != null)
            {
                lipSync.ApplyTuning(mouth.Open, mouth.Jaw, mouth.Closure, mouth.Speed);
            }

            if (avatarState != null)
            {
                avatarState.SetIdleTuning(idle.Breath, idle.Accents, idle.Speed);
            }

            if (cameraFraming != null)
            {
                cameraFraming.SetTuning(new Vector3(view.Side, view.Height, view.Distance), view.Zoom, view.Tilt);
            }

            if (logEvents)
            {
                Debug.Log("[Sonnia] Developer: mouth x" + mouth.Open.ToString("F2") + ", zoom x" + view.Zoom.ToString("F2"), this);
            }
        }

        /// <summary>
        /// Gives the choreographer the set without what it must not do on its own:
        /// the animations disabled in the panel and, in debug mode, all attention
        /// gestures, dances, variations and nods. The base loops, walking and the
        /// image-presenting gesture stay. Whatever is triggered from the panel
        /// (play_animation) comes from the full set and plays all the same.
        /// </summary>
        private void ApplyMotionFilter()
        {
            SoniaMotionSet full = FullMotionSet;
            if (choreographer == null || full == null)
            {
                return;
            }

            if (_filteredMotionSet != null)
            {
                Destroy(_filteredMotionSet);
                _filteredMotionSet = null;
            }

            if (_disabledClips.Count == 0 && !_debugQuiet)
            {
                choreographer.MotionSet = full;
                return;
            }

            SoniaMotionSet copy = Instantiate(full);
            copy.name = full.name + " (filtered)";
            copy.talking = KeepEnabled(full.talking);
            copy.greeting = full.greeting != null && _disabledClips.Contains(full.greeting.name) ? null : full.greeting;
            copy.idleVariations = _debugQuiet ? new AnimationClip[0] : KeepEnabled(full.idleVariations);
            copy.thinkingVariations = _debugQuiet ? new AnimationClip[0] : KeepEnabled(full.thinkingVariations);
            copy.nods = _debugQuiet ? new AnimationClip[0] : KeepEnabled(full.nods);

            List<AttentionMotion> attention = new List<AttentionMotion>();
            if (!_debugQuiet && full.attention != null)
            {
                foreach (AttentionMotion motion in full.attention)
                {
                    if (motion != null && motion.clip != null && !_disabledClips.Contains(motion.clip.name))
                    {
                        attention.Add(motion);
                    }
                }
            }

            copy.attention = attention.ToArray();
            _filteredMotionSet = copy;
            choreographer.MotionSet = copy;
        }

        private AnimationClip[] KeepEnabled(AnimationClip[] clips)
        {
            List<AnimationClip> kept = new List<AnimationClip>();
            if (clips != null)
            {
                foreach (AnimationClip clip in clips)
                {
                    if (clip != null && !_disabledClips.Contains(clip.name))
                    {
                        kept.Add(clip);
                    }
                }
            }

            return kept.ToArray();
        }

        /// <summary>
        /// Tells the panel which catalog clip is playing (to highlight its button),
        /// only when it changes. Base loops do not count: no gesture, null.
        /// </summary>
        private void ReportPlayingAnimation()
        {
            if (client == null || !client.IsConnected || choreographer == null || choreographer.Player == null
                || !choreographer.Player.IsReady)
            {
                return;
            }

            MotionPlayer player = choreographer.Player;
            string playing = OneShotName(player.CurrentClip(MotionPlayer.BodyLayer))
                             ?? OneShotName(player.CurrentClip(MotionPlayer.UpperLayer))
                             ?? OneShotName(player.CurrentClip(MotionPlayer.RightArmLayer));
            if (_clipReported && playing == _reportedClip)
            {
                return;
            }

            _clipReported = true;
            _reportedClip = playing;
            client.SendAnimationPlaying(playing);
        }

        private static string OneShotName(AnimationClip clip)
        {
            return clip != null && !clip.isLooping ? clip.name : null;
        }

        /// <summary>
        /// The panel asks for a specific animation: it plays once over the body
        /// and the choreographer returns to what the current state calls for.
        /// </summary>
        private void HandlePlayAnimation(PlayAnimationMessage message)
        {
            if (choreographer == null || message == null)
            {
                return;
            }

            AnimationCatalog.Entry entry;
            if (!AnimationCatalog.TryFind(FullMotionSet, message.Clip, out entry))
            {
                Debug.LogWarning("[Sonnia] an animation was requested that is not in the set: " + message.Clip, this);
                return;
            }

            if (message.Whole)
            {
                choreographer.PlayReaction(entry.Clip);
            }
            else
            {
                choreographer.Preview(entry.Clip);
            }

            if (logEvents)
            {
                Debug.Log("[Sonnia] animation requested (" + (message.Whole ? "by voice" : "panel") + "): "
                    + entry.Clip.name, this);
            }
        }

        private void HandleState(StateMessage message)
        {
            if (message == null)
            {
                return;
            }

            AvatarState state = AvatarStateController.ParseState(message.State);
            if (state == AvatarState.Speaking && waitAudioBeforeSpeaking && _pendingUtteranceId >= 0
                && _lastAudioUtteranceId < _pendingUtteranceId)
            {
                // The voice has not arrived yet: the previous state (thinking) is
                // kept and 'speaking' is applied with the first audio chunk.
                _pendingSpeakingState = true;
            }
            else
            {
                _pendingSpeakingState = false;
                ApplyAvatarState(state);
            }

            // If someone approaches after a good while with nobody around, Sonnia
            // waves. The component itself decides whether it is due or just happened.
            if (state == AvatarState.Listening && choreographer != null)
            {
                choreographer.PlayGreeting();
            }

            if (logEvents)
            {
                Debug.Log("[Sonnia] state: " + message.State, this);
            }
        }

        private void HandleTranscript(TranscriptMessage message)
        {
            if (logEvents && message != null && message.Final)
            {
                Debug.Log("[Sonnia] " + message.Role + ": " + message.Text, this);
            }
        }

        private void HandleSpeechStart(SpeechStartMessage message)
        {
            // An idle line (ambient) does not touch the body: if she is dancing, she
            // keeps dancing while she "sings". Each utterance of a real reply gets
            // a different way of gesturing.
            bool ambient = message != null && message.Ambient;
            if (!ambient && message != null)
            {
                _pendingUtteranceId = message.UtteranceId;
                _pendingSince = Time.time;
                if (waitAudioBeforeSpeaking && _lastAudioUtteranceId < message.UtteranceId)
                {
                    _pendingSpeechStart = true;
                }
                else
                {
                    _pendingSpeechStart = false;
                    if (choreographer != null)
                    {
                        choreographer.NotifySpeechStart();
                    }

                }
            }

            if (logEvents && message != null)
            {
                Debug.Log("[Sonnia] utterance " + message.UtteranceId + ": " + message.Text, this);
            }
        }

        /// <summary>Applies what was waiting for the audio: 'speaking' state and the start of gesturing.</summary>
        private void ReleasePendingSpeech(string why)
        {
            if (_pendingSpeakingState)
            {
                _pendingSpeakingState = false;
                ApplyAvatarState(AvatarState.Speaking);
            }

            if (_pendingSpeechStart)
            {
                _pendingSpeechStart = false;
                if (choreographer != null)
                {
                    choreographer.NotifySpeechStart();
                }

            }

            if (logEvents && why != null)
            {
                Debug.Log("[Sonnia] 'speaking' applied " + why, this);
            }
        }

        private void Update()
        {
            ReportPlayingAnimation();

            if (_pendingSpeakingState && Time.time - _pendingSince > speakingAudioTimeout)
            {
                // Speech is taking too long: the state (brows, head) is applied but
                // without gesturing; gestures wait for the first audio chunk.
                _pendingSpeakingState = false;
                ApplyAvatarState(AvatarState.Speaking);
                if (choreographer != null)
                {
                    choreographer.SetSpeechPaused(true);
                }

                if (logEvents)
                {
                    Debug.Log("[Sonnia] 'speaking' without audio after " + speakingAudioTimeout + " s: gestures paused", this);
                }
            }

            if (_pendingImage != null && choreographer != null)
            {
                if (choreographer.IsPresentHolding)
                {
                    ShowImageMessage message = _pendingImage;
                    _pendingImage = null;
                    ShowImageNow(message);
                }
                else if (!choreographer.IsPresenting)
                {
                    // The gesture was cut (another state, another clip): the image shows anyway.
                    ShowImageMessage message = _pendingImage;
                    _pendingImage = null;
                    ShowImageNow(message);
                }
            }

            if (_audioDrainedAt >= 0f && speechGapPauseSeconds > 0f && choreographer != null
                && !choreographer.SpeechPaused && Time.time - _audioDrainedAt > speechGapPauseSeconds
                && avatarState != null && avatarState.State == AvatarState.Speaking)
            {
                choreographer.SetSpeechPaused(true);
            }
        }

        /// <summary>The orchestrator asks for an attention gesture (for example a dance to sing over).</summary>
        private void HandleAttention(AttentionMessage message)
        {
            if (choreographer == null || message == null)
            {
                return;
            }

            AttentionCategory category = AttentionCategory.Soft;
            string name = (message.Category ?? string.Empty).ToLowerInvariant();
            if (name == "greeting" || name == "wave")
            {
                // Wave right now (panel button, greeter mode), without the
                // conditions of the automatic greeting. In idle or listening.
                bool waved = choreographer.PlayGreetingNow();
                if (logEvents)
                {
                    Debug.Log("[Sonnia] greeting requested by the orchestrator" + (waved ? string.Empty : " (not now)"), this);
                }

                return;
            }

            if (name == "dance")
            {
                category = AttentionCategory.Dance;
            }
            else if (name == "fourth_wall" || name == "fourthwall")
            {
                category = AttentionCategory.FourthWall;
            }

            choreographer.PlayAttention(category, message.Clip);

            if (logEvents)
            {
                Debug.Log("[Sonnia] attention requested by the orchestrator: " + message.Category, this);
            }
        }

        private void HandleAudioFrame(AudioFrame frame)
        {
            if (audioPlayer != null)
            {
                audioPlayer.Enqueue(frame);
            }

            if (frame.UtteranceId > _lastAudioUtteranceId)
            {
                _lastAudioUtteranceId = frame.UtteranceId;
            }

            if ((_pendingSpeakingState || _pendingSpeechStart) && frame.UtteranceId >= _pendingUtteranceId)
            {
                ReleasePendingSpeech(null);
            }

            // The voice is back: gestures resume if they were paused.
            _audioDrainedAt = -1f;
            if (choreographer != null && choreographer.SpeechPaused)
            {
                choreographer.SetSpeechPaused(false);
            }
        }

        private void HandleSpeechEnd(SpeechEndMessage message)
        {
            if (message == null)
            {
                return;
            }

            // Safety net in case the last-chunk bit never arrived.
            if (audioPlayer != null)
            {
                audioPlayer.MarkUtteranceComplete(message.UtteranceId);
            }
        }

        private void HandleStopSpeaking(StopSpeakingMessage message)
        {
            StopSpeechNow();

            if (logEvents)
            {
                Debug.Log("[Sonnia] stop_speaking: " + (message != null ? message.Reason : "?"), this);
            }
        }

        /// <summary>Discards the queued audio and closes the mouth (stop_speaking and leaving for away mode).</summary>
        private void StopSpeechNow()
        {
            _pendingSpeakingState = false;
            _pendingSpeechStart = false;
            _audioDrainedAt = -1f;
            if (audioPlayer != null)
            {
                audioPlayer.Flush();
            }

            if (lipSync != null)
            {
                lipSync.StopAndClose();
            }
        }

        /// <summary>
        /// The panel's away mode. On leaving it cuts the voice and mouth (like
        /// stop_speaking) and hides the image; the walk out, the away sign and the
        /// return are handled by PresenceController. The presence the orchestrator
        /// re-sends right after the hello is applied without animation.
        /// </summary>
        private void HandlePresence(PresenceMessage message)
        {
            if (message == null || presence == null)
            {
                return;
            }

            bool leaving = !message.Present && presence.TargetPresent;
            if (leaving)
            {
                StopSpeechNow();
                HideImageNow();
            }

            bool instant = !message.Present && Time.unscaledTime - _helloAt <= presenceInstantWindowSeconds;
            presence.SetPresent(message.Present, message.Message, instant);

            if (logEvents)
            {
                Debug.Log(
                    "[Sonnia] presence: " + (message.Present ? "on screen" : "away")
                    + (instant ? " (no animation)" : string.Empty)
                    + (string.IsNullOrEmpty(message.Message) ? string.Empty : ", \"" + message.Message + "\""),
                    this);
            }
        }

        /// <summary>Voice volume (0 to 1.5).</summary>
        private void HandleSetVolume(SetVolumeMessage message)
        {
            if (message == null || audioPlayer == null)
            {
                return;
            }

            audioPlayer.SetVolume(message.Value);
            if (logEvents)
            {
                Debug.Log("[Sonnia] set_volume: " + audioPlayer.Volume.ToString("F2"), this);
            }
        }

        private void HandleShowImage(ShowImageMessage message)
        {
            if (imagePanel == null || message == null)
            {
                return;
            }

            // With the trivia in the top strip, the image would not be visible:
            // Sonnia does not point at anything (safety net in case the
            // orchestrator sends it anyway).
            TriviaController trivia = GetComponent<TriviaController>();
            bool stripTaken = trivia != null && trivia.IsActive;

            // Sonnia raises her hand and points; the image appears above the finger
            // when the hand reaches the top (see Update), not before.
            if (!stripTaken && choreographer != null && choreographer.BeginPresent())
            {
                _pendingImage = message;
            }
            else
            {
                _pendingImage = null;
                ShowImageNow(message);
            }

            if (logEvents)
            {
                Debug.Log("[Sonnia] show_image: " + message.ImageId + " (" + message.Source + ")", this);
            }
        }

        private void ShowImageNow(ShowImageMessage message)
        {
            // Screen element: the panel is placed in its fixed spot when shown.
            imagePanel.Show(message);

            if (avatarState != null)
            {
                avatarState.SetImagePanel(imagePanel.PanelTransform, imagePanel.IsVisible);
            }
        }

        private void HandleHideImage(HideImageMessage message)
        {
            if (imagePanel == null)
            {
                return;
            }

            HideImageNow();

            if (logEvents)
            {
                Debug.Log("[Sonnia] hide_image", this);
            }
        }

        /// <summary>Hides the image (and the one waiting for the hand) and releases the pointing gesture.</summary>
        private void HideImageNow()
        {
            _pendingImage = null;
            if (imagePanel == null)
            {
                return;
            }

            imagePanel.Hide();
            if (choreographer != null)
            {
                choreographer.EndPresent();
            }

            if (avatarState != null)
            {
                avatarState.SetImagePanel(imagePanel.PanelTransform, false);
            }
        }

        private void HandleError(ErrorMessage message)
        {
            if (message != null)
            {
                Debug.LogWarning("[Sonnia] orchestrator error: " + message.Message, this);
            }
        }

        private void HandleRequestFrame(RequestFrameMessage message)
        {
            if (webcam != null)
            {
                webcam.RequestFrameNow();
            }
            else if (logEvents)
            {
                Debug.Log("[Sonnia] request_frame but there is no active WebcamFrameSender.", this);
            }
        }

        private void HandlePlaybackDone(int utteranceId)
        {
            if (client != null)
            {
                client.SendPlaybackDone(utteranceId);
            }

            // What there was ran out: if the orchestrator is still in 'speaking' and
            // sends no more audio soon, gestures pause (see Update).
            if (_lastAudioUtteranceId <= utteranceId)
            {
                _audioDrainedAt = Time.time;
            }

            if (lipSync != null)
            {
                lipSync.NotifyUtteranceFinished(utteranceId);
            }

            if (logEvents)
            {
                Debug.Log("[Sonnia] playback_done: " + utteranceId, this);
            }
        }
    }
}
