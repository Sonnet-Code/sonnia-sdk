// Avatar choreographer: decides which clip plays at each moment.
//
// Replaces the Animator Controller and the old IdleAttentionController and
// SpeakingGestureController. It receives the orchestrator's state (idle,
// listening, thinking, speaking) and the per-utterance signals, and plays clips
// through MotionPlayer with fades chosen case by case:
//
//   idle       base loop; once things are calm (no conversation for
//              attentionQuietDelay) attention gestures (dances, fourth wall)
//              spaced 15 +/- 5 s, like Genies' boredom
//   listening, thinking, speaking
//              with singleConversationLoop (default), one long idle: the same
//              idle loop, without restarting it or changing clip between
//              states and without variations or gestures, like Genies demo
//              characters. Off, each state has its own loop, nods, thinking
//              variations and chained talking clips
//   greeting   wave; it is left to finish unless it is time to speak
//
// Gestures fade in and out over gestureFade (0.8 s) and MotionPlayer blends
// them with a smooth curve, like Genies.
//
// While Sonnia walks out or in (away mode, PresenceController) the
// choreographer is suspended: it records the state it receives but launches no
// clip, neither gestures nor dances, until the body is handed back.
//
// Everything is optional: without MotionPlayer or a clip set it does nothing.

using UnityEngine;

namespace Sonia
{
    /// <summary>Plays the right clip for each state with fades done in code.</summary>
    [DefaultExecutionOrder(-50)]
    [DisallowMultipleComponent]
    public class AvatarChoreographer : MonoBehaviour
    {
        private enum Phase
        {
            Base,
            Variation,
            Attention,
            Greeting,
            // Trivia reaction: plays in full even if the state changes.
            Reaction
        }

        [Header("References")]
        [SerializeField]
        [Tooltip("Clip player. If empty, it is looked up on this object or its children.")]
        private MotionPlayer motionPlayer;

        [SerializeField]
        [Tooltip("Clips grouped by state. Created with Sonnia > Create Motion Set.")]
        private SoniaMotionSet motionSet;

        [Header("Fades (seconds)")]
        [SerializeField]
        [Tooltip("When switching between main states (idle, listening, thinking).")]
        private float stateFade = 0.55f;

        [SerializeField]
        [Tooltip("When starting to speak: shorter so the reply feels immediate.")]
        private float speakFade = 0.35f;

        [SerializeField]
        [Tooltip("Between one gesturing clip and the next while speaking.")]
        private float talkingChainFade = 0.5f;

        [SerializeField]
        [Range(0.1f, 2f)]
        [Tooltip("Fade in and out of gestures (attention, greeting and variations), with MotionPlayer's smooth curve. Genies uses 0.8 s.")]
        private float gestureFade = 0.8f;

        [SerializeField]
        [Range(0.1f, 1.5f)]
        [Tooltip("Fade in and out of the image-presenting gesture (right arm).")]
        private float presentFade = 0.5f;

        [SerializeField]
        [Tooltip("Nods on the torso layer.")]
        private float nodFade = 0.3f;

        [Header("Conversation")]
        [SerializeField]
        [Tooltip("In conversation (listening, thinking, speaking) one long idle plays, the idle one, without changing clip between states and without variations, nods or talking gestures, like Genies demo characters. Off: each state with its own loop and variations.")]
        private bool singleConversationLoop = true;

        [Header("Idle")]
        [SerializeField]
        [Tooltip("Minimum and maximum seconds between idle variations (only when things are calm).")]
        private Vector2 idleVariationInterval = new Vector2(7f, 16f);

        [SerializeField]
        [Tooltip("Seconds in idle without conversation before the first attention gesture: with someone in front (between turns the state is also idle) she does not dance.")]
        private float attentionQuietDelay = 25f;

        [SerializeField]
        [Tooltip("Minimum and maximum seconds between attention gestures when things are calm (15 +/- 5, like Genies' boredom).")]
        private Vector2 attentionSpacing = new Vector2(10f, 20f);

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probability of a fourth-wall gesture: pointing, waving, tapping the screen.")]
        private float fourthWallWeight = 0.45f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probability of a full dance.")]
        private float danceWeight = 0.30f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probability of a soft filler gesture.")]
        private float softWeight = 0.25f;

        [Header("Listening and thinking")]
        [SerializeField]
        [Tooltip("Minimum and maximum seconds between nods while listening.")]
        private Vector2 nodInterval = new Vector2(4f, 8f);

        [SerializeField]
        [Tooltip("Minimum and maximum seconds between variations while thinking.")]
        private Vector2 thinkingVariationInterval = new Vector2(4f, 8f);

        [Header("Speaking")]
        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Minimum progress of the current clip for a new utterance to change gesture.")]
        private float speechChangeThreshold = 0.5f;

        [Header("Greeting")]
        [SerializeField]
        [Tooltip("Seconds in idle needed for the next listening to trigger a greeting.")]
        private float minIdleSecondsForGreeting = 25f;

        [SerializeField]
        [Tooltip("Minimum seconds between two greetings.")]
        private float greetingCooldownSeconds = 20f;

        [Header("Logging")]
        [SerializeField]
        [Tooltip("Write every clip that is launched to the console.")]
        private bool logEvents;

        private const float MaxTrackedSeconds = 3600f;

        private AvatarState _state = AvatarState.Idle;
        private Phase _phase = Phase.Base;
        private MotionPlayer.Handle _body;
        private MotionPlayer.Handle _upper;

        // Present gesture (image): hand up, frozen at the peak.
        private MotionPlayer.Handle _present;
        private bool _presentHolding;
        private bool _presentReleasing;
        private AnimationClip _lastTalking;
        private bool _speechPaused;
        private AnimationClip _lastVariation;
        private int _lastAttention = -1;
        private float _stateSeconds;
        private float _lastIdleSeconds;
        private float _secondsSinceGreeting = MaxTrackedSeconds;
        private float _variationTimer;
        private float _attentionTimer;
        private float _nodTimer;
        private float _wideUntil = -1f;
        private bool _started;
        private bool _suspended;

        // Seconds in idle since the last conversation (listening, thinking or speaking).
        private float _quietSeconds;
        private bool _quietArmed;

        // Speed of the base loops ("Idle movement" setting).
        private float _loopSpeed = 1f;

        /// <summary>State that has been communicated to the choreographer.</summary>
        public AvatarState State
        {
            get { return _state; }
        }

        /// <summary>Seconds Sonnia has been in the current state.</summary>
        public float SecondsInState
        {
            get { return _stateSeconds; }
        }

        /// <summary>
        /// True while a big gesture (dance, fourth wall, greeting) plays and during
        /// its fade out: the camera widens the shot.
        /// </summary>
        public bool IsWideShot
        {
            get
            {
                return !_suspended
                       && (_phase == Phase.Attention || _phase == Phase.Greeting || Time.time < _wideUntil);
            }
        }

        /// <summary>Clip set in use.</summary>
        public SoniaMotionSet MotionSet
        {
            get { return motionSet; }
            set { motionSet = value; }
        }

        /// <summary>Clip player the choreographer uses.</summary>
        public MotionPlayer Player
        {
            get { return motionPlayer; }
        }

        /// <summary>True while another component controls the body (walking out and in).</summary>
        public bool IsSuspended
        {
            get { return _suspended; }
        }

        /// <summary>
        /// True while a play-once clip runs over the body (gesture, greeting,
        /// dance, reaction or variation) instead of the base loop: the hand
        /// gestures while speaking (AvatarStateController) wait for it to end.
        /// </summary>
        public bool IsPlayingOneShot
        {
            get { return !_suspended && _phase != Phase.Base; }
        }

        /// <summary>Seconds in idle since the last conversation: if few, someone is still in front.</summary>
        public float QuietSeconds
        {
            get { return _quietSeconds; }
        }

        /// <summary>
        /// Speed of the base loops (1 = the clip's own). Slower, the idle weight
        /// shift goes more slowly. Set by the "Idle movement" setting.
        /// </summary>
        public void SetLoopSpeed(float speed)
        {
            _loopSpeed = Mathf.Clamp(speed, 0.25f, 3f);
            if (_body != null && _body.IsAlive && _body.Clip != null && _body.Clip.isLooping)
            {
                _body.SetSpeed(_loopSpeed);
            }
        }

        private void Awake()
        {
            if (motionPlayer == null)
            {
                motionPlayer = GetComponentInChildren<MotionPlayer>(true);
            }
        }

        private void Start()
        {
            _started = true;
            _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
            _attentionTimer = RandomSpacing();
            EnterState(_state, stateFade, true);
        }

        /// <summary>True when there is a player with a graph and a clip set: it can now move the avatar.</summary>
        public bool Ready
        {
            get { return motionPlayer != null && motionPlayer.IsReady && motionSet != null; }
        }

        // ------------------------------------------------------------------
        // Inputs
        // ------------------------------------------------------------------

        /// <summary>Receives the orchestrator's state.</summary>
        public void SetState(AvatarState state)
        {
            if (state == _state)
            {
                return;
            }

            if (_state == AvatarState.Idle)
            {
                _lastIdleSeconds = _stateSeconds;
            }

            AvatarState previous = _state;
            _state = state;
            _stateSeconds = 0f;
            _speechPaused = false;
            if (state != AvatarState.Idle)
            {
                // There is a conversation: things are not calm.
                _quietSeconds = 0f;
                _quietArmed = false;
            }

            // Suspended (off screen or walking): the state is recorded and
            // applied when the body is handed back (Resume).
            if (!_started || _suspended)
            {
                return;
            }

            // The greeting is left to finish if the state only switches between
            // idle and listening; thinking or speaking cut it.
            if (_phase == Phase.Greeting && (state == AvatarState.Idle || state == AvatarState.Listening))
            {
                return;
            }

            // A reaction (right answer, wrong answer or end of the trivia) is not
            // cut: the new state is applied when it ends (EndOneShot).
            if (_phase == Phase.Reaction)
            {
                return;
            }

            float fade = state == AvatarState.Speaking ? speakFade : stateFade;
            bool cutting = _phase == Phase.Attention || _phase == Phase.Greeting;
            EnterState(state, cutting ? Mathf.Max(fade, gestureFade * 0.6f) : fade, false);

            if (previous == AvatarState.Listening && state != AvatarState.Listening && motionPlayer != null)
            {
                motionPlayer.FadeOut(MotionPlayer.UpperLayer, nodFade);
                _upper = null;
            }
        }

        /// <summary>
        /// Called on every <c>speech_start</c>: if the current gesture is already
        /// well along, it switches to another so each utterance has its own gesturing.
        /// </summary>
        public void NotifySpeechStart()
        {
            if (!Ready || _suspended || _state != AvatarState.Speaking)
            {
                return;
            }

            if (_speechPaused)
            {
                SetSpeechPaused(false);
                return;
            }

            if (IsPresenting || _phase == Phase.Reaction)
            {
                return;
            }

            if (_body == null || !_body.IsAlive || _body.NormalizedTime >= speechChangeThreshold)
            {
                PlayNextTalking(talkingChainFade);
            }
        }

        /// <summary>True while talking gestures are paused for lack of audio.</summary>
        public bool SpeechPaused
        {
            get { return _speechPaused; }
        }

        /// <summary>
        /// In the middle of a reply the model may take a while to deliver the next
        /// utterance and Sonnia goes silent for a few seconds: gesturing with a
        /// closed mouth looks odd. While paused it moves to the listening loop (an
        /// attentive wait) without leaving "speaking"; when the audio returns the
        /// gesturing resumes.
        /// </summary>
        public void SetSpeechPaused(bool paused)
        {
            if (paused == _speechPaused)
            {
                return;
            }

            _speechPaused = paused;

            if (!Ready || _suspended || _state != AvatarState.Speaking || _phase != Phase.Base)
            {
                return;
            }

            if (singleConversationLoop)
            {
                // One single idle: the pause does not change clip.
                return;
            }

            if (paused)
            {
                PlayLoop(motionSet.listeningLoop != null ? motionSet.listeningLoop : motionSet.idleLoop, speakFade);
                Log("talking gestures paused: no audio");
            }
            else if (!IsPresenting)
            {
                PlayNextTalking(speakFade);
            }
        }

        /// <summary>
        /// Waves if Sonnia is in idle or listening, had been alone for a good while
        /// and has not just greeted. Returns true if it launched the greeting.
        /// </summary>
        public bool PlayGreeting()
        {
            if (GreetingSuppressed || !CanGreet())
            {
                return false;
            }

            float idleSeconds = _state == AvatarState.Idle ? _stateSeconds : _lastIdleSeconds;
            if (idleSeconds < minIdleSecondsForGreeting || _secondsSinceGreeting < greetingCooldownSeconds)
            {
                return false;
            }

            StartGreeting("greeting after " + Mathf.RoundToInt(idleSeconds) + " s in idle");
            return true;
        }

        /// <summary>
        /// Waves right now, without the conditions of the automatic greeting
        /// (time alone, cooldown). The orchestrator requests it with
        /// <c>attention</c> and <c>category: "greeting"</c> (panel button, greeter
        /// mode). Only in idle or listening, with no image showing (the waving arm
        /// is the pointing one) and without repeating one already underway.
        /// </summary>
        public bool PlayGreetingNow()
        {
            if (!CanGreet() || IsPresenting || _phase == Phase.Greeting)
            {
                return false;
            }

            StartGreeting("greeting requested by the orchestrator");
            return true;
        }

        private bool CanGreet()
        {
            return Ready
                   && !_suspended
                   && motionSet.greeting != null
                   && _phase != Phase.Reaction
                   && (_state == AvatarState.Idle || _state == AvatarState.Listening);
        }

        /// <summary>
        /// No automatic greeting when someone approaches (turned off by the trivia:
        /// with a game running, every answer from the user would trigger it).
        /// </summary>
        public bool GreetingSuppressed { get; set; }

        private void StartGreeting(string why)
        {
            _secondsSinceGreeting = 0f;
            _phase = Phase.Greeting;
            _body = motionPlayer.Play(motionSet.greeting, MotionPlayer.BodyLayer, gestureFade);
            _attentionTimer = RandomSpacing();
            _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
            Log(why);
        }

        /// <summary>
        /// Another component takes the body (walking out and in): the image
        /// presentation and nods are cut, and until <see cref="Resume"/> no clip is
        /// launched (no variations, attention gestures, dances or talking
        /// gestures). Any state that arrives in the meantime is recorded.
        /// </summary>
        public void Suspend()
        {
            if (_suspended)
            {
                return;
            }

            _suspended = true;
            _phase = Phase.Base;
            _wideUntil = -1f;
            _speechPaused = false;
            _present = null;
            _presentHolding = false;
            _presentReleasing = false;
            _upper = null;
            if (motionPlayer != null && motionPlayer.IsReady)
            {
                motionPlayer.FadeOut(MotionPlayer.UpperLayer, nodFade);
                motionPlayer.FadeOut(MotionPlayer.RightArmLayer, presentFade);
            }

            Log("choreography suspended");
        }

        /// <summary>
        /// Hands the body back to the choreographer. If <paramref name="body"/> is
        /// already playing the current state's base loop (Sonnia has just arrived
        /// in idle), it is adopted as is so as not to restart it; otherwise the
        /// state is entered with a fade of <paramref name="fade"/> seconds. The
        /// first attention gesture waits as usual, so she does not start dancing
        /// right after returning.
        /// </summary>
        public void Resume(MotionPlayer.Handle body, float fade)
        {
            if (!_suspended)
            {
                return;
            }

            _suspended = false;
            _stateSeconds = 0f;
            _attentionTimer = RandomSpacing();
            if (!Ready)
            {
                return;
            }

            AnimationClip loop = BaseLoopOf(_state);
            if (body != null && body.IsCurrent && loop != null && body.Clip == loop)
            {
                _body = body;
                _phase = Phase.Base;
                _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
                _nodTimer = Random.Range(nodInterval.x, nodInterval.y);
                Log("choreography back, loop continues: " + loop.name);
                return;
            }

            EnterState(_state, Mathf.Max(0.05f, fade), false);
            Log("choreography back in " + _state);
        }

        private AnimationClip BaseLoopOf(AvatarState state)
        {
            if (motionSet == null)
            {
                return null;
            }

            switch (state)
            {
                case AvatarState.Idle:
                    return motionSet.idleLoop;
                case AvatarState.Listening:
                    return ConversationLoop(motionSet.listeningLoop);
                case AvatarState.Thinking:
                    return ConversationLoop(motionSet.thinkingLoop);
                default:
                    return singleConversationLoop ? motionSet.idleLoop : null;
            }
        }

        /// <summary>Loop for a conversation state: the idle one with a single long idle, otherwise its own.</summary>
        private AnimationClip ConversationLoop(AnimationClip own)
        {
            if (singleConversationLoop || own == null)
            {
                return motionSet.idleLoop;
            }

            return own;
        }

        /// <summary>
        /// Starts presenting an image: raises the hand and points with the index
        /// finger (torso layer, so the legs and the rest keep speaking or idling).
        /// The gesture freezes on reaching the top and is held until
        /// <see cref="EndPresent"/>. Returns false if there is no clip.
        /// </summary>
        public bool BeginPresent()
        {
            if (!Ready || _suspended || motionSet.present == null)
            {
                return false;
            }

            _presentHolding = false;
            _presentReleasing = false;
            // Only the right arm: the torso, head and other arm follow the state's
            // base loop, which also goes without variations or gestures while the
            // presentation lasts (see UpdateIdle/UpdateSpeaking).
            _present = motionPlayer.Play(motionSet.present, MotionPlayer.RightArmLayer, presentFade);
            if (_phase != Phase.Base && _phase != Phase.Greeting)
            {
                // A variation or attention gesture in progress is cut: the body
                // returns to the base so she does not dance while pointing.
                EndOneShot();
            }

            Log("presenting an image: " + motionSet.present.name);
            return true;
        }

        /// <summary>Releases the present gesture: the hand finishes lowering and the torso layer turns off.</summary>
        public void EndPresent()
        {
            if (_present == null)
            {
                return;
            }

            if (_present.IsAlive)
            {
                _present.SetSpeed(1f);
                _presentReleasing = true;
            }
            else
            {
                _present = null;
            }

            _presentHolding = false;
        }

        /// <summary>True while the hand is up, frozen pointing.</summary>
        public bool IsPresentHolding
        {
            get { return _presentHolding && _present != null && _present.IsAlive; }
        }

        /// <summary>True while the present gesture lasts (rising, held or lowering).</summary>
        public bool IsPresenting
        {
            get { return _present != null && _present.IsAlive; }
        }

        /// <summary>Humanoid Animator the player drives (for reference bones).</summary>
        public Animator MotionPlayerAnimator
        {
            get { return motionPlayer != null ? motionPlayer.Animator : null; }
        }

        /// <summary>Tip of the index finger of the presenting hand, or null if there is no humanoid Animator.</summary>
        public Transform PresentAnchor
        {
            get
            {
                Animator animator = motionPlayer != null ? motionPlayer.Animator : null;
                if (animator == null || !animator.isHuman)
                {
                    return null;
                }

                Transform tip = animator.GetBoneTransform(HumanBodyBones.RightIndexDistal);
                return tip != null ? tip : animator.GetBoneTransform(HumanBodyBones.RightHand);
            }
        }

        private void UpdatePresent()
        {
            if (_present == null)
            {
                return;
            }

            if (!_present.IsAlive)
            {
                _present = null;
                _presentHolding = false;
                _presentReleasing = false;
                return;
            }

            if (_presentReleasing)
            {
                if (_present.Remaining <= presentFade)
                {
                    motionPlayer.FadeOut(MotionPlayer.RightArmLayer, presentFade);
                    _present = null;
                    _presentReleasing = false;
                }

                return;
            }

            if (!_presentHolding && _present.Time >= SoniaAnimations.PresentHoldTime)
            {
                _present.SetSpeed(0f);
                _presentHolding = true;
            }
        }

        /// <summary>
        /// Reaction gesture (trivia: celebrate a right answer, lament a wrong one,
        /// dance on winning). Like <see cref="Preview"/>, but it plays in full even
        /// if Sonnia moves on to thinking or speaking meanwhile; when it ends, it
        /// returns to the state that applies.
        /// </summary>
        public void PlayReaction(AnimationClip clip)
        {
            if (!Ready || _suspended || clip == null || clip.isLooping)
            {
                return;
            }

            _phase = Phase.Reaction;
            _body = motionPlayer.Play(clip, MotionPlayer.BodyLayer, gestureFade);
            Log("reaction: " + clip.name);
        }

        /// <summary>
        /// Previews a clip of the set (animation panel). A base loop becomes the
        /// active loop; any other clip plays once over the body (or over the torso,
        /// if it is a nod) and then returns to the current state's base.
        /// </summary>
        public void Preview(AnimationClip clip, bool upperBody = false)
        {
            if (!Ready || _suspended || clip == null)
            {
                return;
            }

            if (upperBody)
            {
                _upper = motionPlayer.Play(clip, MotionPlayer.UpperLayer, nodFade);
                return;
            }

            if (clip.isLooping)
            {
                _phase = Phase.Base;
                PlayLoop(clip, stateFade);
                return;
            }

            bool attentionLike = System.Array.Exists(
                motionSet.attention, m => m != null && m.clip == clip) || clip == motionSet.greeting;
            _phase = attentionLike ? Phase.Attention : Phase.Variation;
            _body = motionPlayer.Play(clip, MotionPlayer.BodyLayer, gestureFade);
            Log("preview: " + clip.name);
        }

        /// <summary>Launches a random attention gesture (by weights). Only in idle.</summary>
        public void PlayRandomAttention()
        {
            if (_suspended || _state != AvatarState.Idle)
            {
                return;
            }

            PlayAttention(PickAttention());
        }

        /// <summary>
        /// Launches an attention gesture of a category (or a specific clip by name,
        /// if it exists). The orchestrator uses it for sung dances. Only in idle.
        /// </summary>
        public void PlayAttention(AttentionCategory category, string clipName = null)
        {
            if (!Ready || _suspended || _state != AvatarState.Idle)
            {
                return;
            }

            if (!string.IsNullOrEmpty(clipName))
            {
                for (int i = 0; i < motionSet.attention.Length; i++)
                {
                    AttentionMotion motion = motionSet.attention[i];
                    if (motion != null && motion.clip != null && motion.clip.name == clipName)
                    {
                        PlayAttention(i);
                        return;
                    }
                }
            }

            int count = motionSet.CountInCategory(category);
            if (count == 0)
            {
                PlayAttention(PickAttention());
                return;
            }

            for (int attempt = 0; attempt < 12; attempt++)
            {
                int index = Random.Range(0, motionSet.attention.Length);
                AttentionMotion motion = motionSet.attention[index];
                if (motion == null || motion.clip == null || motion.category != category)
                {
                    continue;
                }

                if (index != _lastAttention || count == 1)
                {
                    PlayAttention(index);
                    return;
                }
            }

            for (int i = 0; i < motionSet.attention.Length; i++)
            {
                if (motionSet.attention[i] != null && motionSet.attention[i].clip != null
                    && motionSet.attention[i].category == category)
                {
                    PlayAttention(i);
                    return;
                }
            }
        }

        /// <summary>Launches the attention gesture with that index in the set. Only in idle.</summary>
        public void PlayAttention(int index)
        {
            if (!Ready || _suspended || _state != AvatarState.Idle || index < 0 || index >= motionSet.attention.Length)
            {
                return;
            }

            AttentionMotion motion = motionSet.attention[index];
            if (motion == null || motion.clip == null)
            {
                return;
            }

            _lastAttention = index;
            _attentionTimer = RandomSpacing();
            _phase = Phase.Attention;
            _body = motionPlayer.Play(motion.clip, MotionPlayer.BodyLayer, gestureFade);
            _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
            Log("attention " + motion.category + ": " + motion.clip.name);
        }

        // ------------------------------------------------------------------
        // Loop
        // ------------------------------------------------------------------

        private void Update()
        {
            float dt = Time.deltaTime;
            _stateSeconds = Mathf.Min(MaxTrackedSeconds, _stateSeconds + dt);
            _secondsSinceGreeting = Mathf.Min(MaxTrackedSeconds, _secondsSinceGreeting + dt);
            if (_state == AvatarState.Idle)
            {
                _quietSeconds = Mathf.Min(MaxTrackedSeconds, _quietSeconds + dt);
            }

            if (!Ready || _suspended)
            {
                return;
            }

            UpdatePresent();

            // A play-once gesture has ended (or nearly): back to the base.
            if (_phase != Phase.Base)
            {
                bool done = _body == null || !_body.IsAlive || _body.Remaining <= FadeForReturn();
                if (done)
                {
                    EndOneShot();
                }

                return;
            }

            switch (_state)
            {
                case AvatarState.Idle:
                    UpdateIdle(dt);
                    break;
                case AvatarState.Listening:
                    UpdateListening(dt);
                    break;
                case AvatarState.Thinking:
                    UpdateThinking(dt);
                    break;
                case AvatarState.Speaking:
                    UpdateSpeaking();
                    break;
            }
        }

        private float FadeForReturn()
        {
            return gestureFade;
        }

        private void EndOneShot()
        {
            bool wasWide = _phase == Phase.Attention || _phase == Phase.Greeting;
            _phase = Phase.Base;
            if (wasWide)
            {
                _wideUntil = Time.time + gestureFade;
            }

            EnterState(_state, gestureFade, false);
        }

        private float RandomSpacing()
        {
            return Random.Range(Mathf.Min(attentionSpacing.x, attentionSpacing.y), Mathf.Max(attentionSpacing.x, attentionSpacing.y));
        }

        private void UpdateIdle(float dt)
        {
            EnsureLoop(motionSet.idleLoop, stateFade);

            if (IsPresenting)
            {
                // Presenting an image: only the base loop, no variations or
                // attention gestures, which look absurd with the arm pointing.
                return;
            }

            // Between turns the state is also idle: until things have been calm for
            // a while there are no gestures or variations (with someone in front,
            // Sonnia does not start dancing). The first one comes shortly after.
            if (_quietSeconds < attentionQuietDelay)
            {
                return;
            }

            if (!_quietArmed)
            {
                _quietArmed = true;
                _attentionTimer = Random.Range(0f, Mathf.Max(0.1f, Mathf.Min(attentionSpacing.x, attentionSpacing.y) * 0.5f));
            }

            _attentionTimer -= dt;
            if (_attentionTimer <= 0f)
            {
                int index = PickAttention();
                if (index >= 0)
                {
                    PlayAttention(index);
                    return;
                }

                _attentionTimer = RandomSpacing();
            }

            _variationTimer -= dt;
            if (_variationTimer <= 0f)
            {
                _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
                AnimationClip clip = PickDifferent(motionSet.idleVariations, _lastVariation);
                if (clip != null)
                {
                    _lastVariation = clip;
                    _phase = Phase.Variation;
                    _body = motionPlayer.Play(clip, MotionPlayer.BodyLayer, gestureFade);
                    Log("idle variation: " + clip.name);
                }
            }
        }

        private void UpdateListening(float dt)
        {
            EnsureLoop(ConversationLoop(motionSet.listeningLoop), stateFade);

            if (IsPresenting || singleConversationLoop)
            {
                // Presenting an image, or with one long idle: no clip nods (the head
                // nods by code in AvatarStateController).
                return;
            }

            if (_upper != null && _upper.IsAlive)
            {
                if (_upper.Remaining <= nodFade)
                {
                    motionPlayer.FadeOut(MotionPlayer.UpperLayer, nodFade);
                    _upper = null;
                }

                return;
            }

            _nodTimer -= dt;
            if (_nodTimer <= 0f)
            {
                _nodTimer = Random.Range(nodInterval.x, nodInterval.y);
                AnimationClip nod = PickDifferent(motionSet.nods, null);
                if (nod != null)
                {
                    _upper = motionPlayer.Play(nod, MotionPlayer.UpperLayer, nodFade);
                    Log("nod: " + nod.name);
                }
            }
        }

        private void UpdateThinking(float dt)
        {
            EnsureLoop(ConversationLoop(motionSet.thinkingLoop), stateFade);
            if (IsPresenting || singleConversationLoop)
            {
                return;
            }

            _variationTimer -= dt;
            if (_variationTimer <= 0f)
            {
                _variationTimer = Random.Range(thinkingVariationInterval.x, thinkingVariationInterval.y);
                AnimationClip clip = PickDifferent(motionSet.thinkingVariations, _lastVariation);
                if (clip != null)
                {
                    _lastVariation = clip;
                    _phase = Phase.Variation;
                    _body = motionPlayer.Play(clip, MotionPlayer.BodyLayer, gestureFade);
                    Log("thinking variation: " + clip.name);
                }
            }
        }

        private void UpdateSpeaking()
        {
            if (singleConversationLoop)
            {
                // One long idle: she speaks from it, without clip gesturing.
                EnsureLoop(motionSet.idleLoop, speakFade);
                return;
            }

            if (_speechPaused || IsPresenting)
            {
                // No audio, or pointing at an image: attentive wait instead of gesturing.
                EnsureLoop(motionSet.listeningLoop != null ? motionSet.listeningLoop : motionSet.idleLoop, speakFade);
                return;
            }

            if (_body == null || !_body.IsAlive || _body.Remaining <= talkingChainFade)
            {
                PlayNextTalking(_body == null || !_body.IsAlive ? speakFade : talkingChainFade);
            }
        }

        // ------------------------------------------------------------------
        // Playback
        // ------------------------------------------------------------------

        /// <summary>
        /// Starts a state's base motion. If the new state's loop is the one already
        /// playing (thinking and speaking share the idle one), it continues where
        /// it was: a fade of the same clip with itself at another point would mix
        /// two phases of the weight shift.
        /// </summary>
        private void EnterState(AvatarState state, float fade, bool initial)
        {
            if (!Ready)
            {
                return;
            }

            _phase = Phase.Base;
            switch (state)
            {
                case AvatarState.Idle:
                    _attentionTimer = initial ? RandomSpacing() : Mathf.Max(_attentionTimer, 0.5f);
                    _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
                    EnsureLoop(motionSet.idleLoop, fade);
                    break;
                case AvatarState.Listening:
                    _nodTimer = Random.Range(nodInterval.x, nodInterval.y);
                    EnsureLoop(ConversationLoop(motionSet.listeningLoop), fade);
                    break;
                case AvatarState.Thinking:
                    _variationTimer = Random.Range(thinkingVariationInterval.x, thinkingVariationInterval.y);
                    EnsureLoop(ConversationLoop(motionSet.thinkingLoop), fade);
                    break;
                case AvatarState.Speaking:
                    PlayNextTalking(fade);
                    break;
            }
        }

        /// <summary>If the base loop is not playing (or another clip is), launches it.</summary>
        private void EnsureLoop(AnimationClip loop, float fade)
        {
            if (loop == null)
            {
                return;
            }

            if (_body != null && _body.IsCurrent && _body.Clip == loop)
            {
                return;
            }

            PlayLoop(loop, fade);
        }

        private void PlayLoop(AnimationClip loop, float fade)
        {
            if (loop == null)
            {
                return;
            }

            // It enters at a random point of the loop so two returns to the same
            // state do not always start with the same pose.
            float start = loop.isLooping ? Random.Range(0f, Mathf.Max(0f, loop.length - 0.5f)) : 0f;
            _body = motionPlayer.Play(loop, MotionPlayer.BodyLayer, fade, loop.isLooping ? _loopSpeed : 1f, start);
        }

        private void PlayNextTalking(float fade)
        {
            AnimationClip clip = singleConversationLoop ? null : PickDifferent(motionSet.talking, _lastTalking);
            if (clip == null)
            {
                EnsureLoop(motionSet.idleLoop, fade);
                return;
            }

            _lastTalking = clip;
            _body = motionPlayer.Play(clip, MotionPlayer.BodyLayer, fade);
            Log("talking gesture: " + clip.name);
        }

        // ------------------------------------------------------------------
        // Selection
        // ------------------------------------------------------------------

        private static AnimationClip PickDifferent(AnimationClip[] clips, AnimationClip last)
        {
            if (clips == null || clips.Length == 0)
            {
                return null;
            }

            int valid = 0;
            for (int i = 0; i < clips.Length; i++)
            {
                if (clips[i] != null)
                {
                    valid++;
                }
            }

            if (valid == 0)
            {
                return null;
            }

            for (int attempt = 0; attempt < 8; attempt++)
            {
                AnimationClip candidate = clips[Random.Range(0, clips.Length)];
                if (candidate != null && (candidate != last || valid == 1))
                {
                    return candidate;
                }
            }

            for (int i = 0; i < clips.Length; i++)
            {
                if (clips[i] != null)
                {
                    return clips[i];
                }
            }

            return null;
        }

        private int PickAttention()
        {
            if (motionSet == null || motionSet.attention.Length == 0)
            {
                return -1;
            }

            AttentionCategory category = PickCategory();
            int count = motionSet.CountInCategory(category);
            if (count == 0)
            {
                // With no clips of that category, any is taken.
                count = 0;
                for (int i = 0; i < motionSet.attention.Length; i++)
                {
                    if (motionSet.attention[i] != null && motionSet.attention[i].clip != null)
                    {
                        count++;
                    }
                }

                if (count == 0)
                {
                    return -1;
                }
            }

            for (int attempt = 0; attempt < 12; attempt++)
            {
                int index = Random.Range(0, motionSet.attention.Length);
                AttentionMotion motion = motionSet.attention[index];
                if (motion == null || motion.clip == null)
                {
                    continue;
                }

                bool categoryOk = motion.category == category || motionSet.CountInCategory(category) == 0;
                if (categoryOk && (index != _lastAttention || count == 1))
                {
                    return index;
                }
            }

            for (int i = 0; i < motionSet.attention.Length; i++)
            {
                if (motionSet.attention[i] != null && motionSet.attention[i].clip != null)
                {
                    return i;
                }
            }

            return -1;
        }

        private AttentionCategory PickCategory()
        {
            float fourth = Mathf.Max(0f, fourthWallWeight);
            float dance = Mathf.Max(0f, danceWeight);
            float soft = Mathf.Max(0f, softWeight);
            float total = fourth + dance + soft;
            if (total <= 0f)
            {
                return AttentionCategory.Soft;
            }

            float roll = Random.value * total;
            if (roll < fourth)
            {
                return AttentionCategory.FourthWall;
            }

            return roll < fourth + dance ? AttentionCategory.Dance : AttentionCategory.Soft;
        }

        private void Log(string message)
        {
            if (logEvents)
            {
                Debug.Log("[Sonnia] " + message, this);
            }
        }
    }
}
