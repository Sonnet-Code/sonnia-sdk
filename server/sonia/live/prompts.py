"""Instructions and session configuration for the GPT-Live engine.

GPT-Live separates two prompts (see the Live API prompting guide):

- The session ``instructions`` are for the voice: who Sonnia is, how she
  speaks, when she stays quiet and when she delegates. It is the persona of
  :mod:`sonia.persona` plus the real-time voice rules, the knowledge base and
  the stack.
- The backend ones (``delegation.responses.instructions``) are for the model
  that runs the actions: tools, gallery ids and rules.

That way the persona lives in a single place. Which blocks go in depending on the
settings is decided by this code.
"""

from __future__ import annotations

from typing import Any, Literal

from sonia.actions.registry import ActionRegistry
from sonia.config import Settings
from sonia.persona import SYSTEM_PROMPT, KnowledgeSource, host_of, is_local_host, load_knowledge

__all__ = [
    "CAMERA_NOTE_PREFIX",
    "GALLERY_NOTE_PREFIX",
    "LIVE_RULES",
    "build_backend_instructions",
    "build_live_instructions",
    "build_session_config",
    "camera_mode",
    "describe_live_stack",
    "gallery_note",
]

#: Prefix of the silent notes with what the camera sees.
CAMERA_NOTE_PREFIX = "[Camera]"

#: Prefix of the silent notes with the images added to or removed from the gallery.
GALLERY_NOTE_PREFIX = "[Gallery]"


LIVE_RULES = """\
HOW YOU WORK (real-time voice to voice):
- You hear the user directly and speak with your own voice. Speak English by default; if someone speaks to you in another language, answer in that language.
{setting_rule}
{clock_rule}
- If a name, a date or an important detail was not clear, ask about exactly that part.
{camera_rule}
- If you are told that a user has typed something to you, answer out loud just as if they had said it.
{trivia_rule}
Backchannel policy: Use short acknowledgements ("uh-huh", "sure") sparingly, without talking over the user or competing with your answer.

Interruption policy: If the user interrupts you, stop right away and listen to what they say.

Delegation policy:
Backend tools:
{capabilities}

Delegate to the backend when:
- You want to show or hide an image on your screen. When you change topic, hide it.
{look_when}{moves_when}{trivia_when}{search_when}- The question needs careful reasoning and the answer is not clear in your knowledge base.
- A correction changes what you already asked the backend for.

Do not delegate to the backend when:
{no_delegate_chat}
- You can answer from the conversation or from a backend result that still holds.
- Only a short clarification is needed to understand what they are asking.

Delegate before giving an answer that depends on backend work.
Do not guess the result while waiting. While the backend works, say something short and natural ("let me show you", "let me check")."""

_CAPABILITIES = {
    "show_image": "- Screen: show an image from the gallery next to you.",
    "hide_image": "- Hide the image you are showing.",
    "play_animation": (
        "- Move on the screen: dance, wave hello, make the peace sign, a military salute, "
        "thumbs up, celebrate, a 'so close' gesture or look thoughtful."
    ),
    "look": "- Look: take a new photo with your camera and tell you what is in it.",
    "start_trivia": (
        "- Trivia: start a tech trivia game on your screen, with three options per question."
    ),
    "trivia_answer": (
        "- Trivia: record the option the user picks and tell you whether it is right and how "
        "to explain it."
    ),
    "trivia_next": "- Trivia: put up the next question when the user asks for it.",
    "restart_trivia": "- Restart the trivia: a new game from the first question.",
    "stop_trivia": "- End the running trivia.",
}

#: The capabilities when the backend has no tool at all.
_NO_CAPABILITIES = "- None right now: do not delegate."

#: Web search is not an action of the registry: it is the Responses API ``web_search``
#: tool, run by OpenAI.
_SEARCH_CAPABILITY = (
    "- Search the web: look up online something that is not in your knowledge base."
)

#: When to delegate a move (``play_animation``).
_MOVES_WHEN = (
    '- You are asked to dance, wave or make a gesture ("dance!", "do a little dance", '
    '"do the peace sign"): delegate it in that same turn, without asking or saying first '
    "that you cannot, and go along with a short sentence. "
    "Do not move on your own every now and then: only when asked or when celebrating something."
)

#: How the trivia works (only if the backend has the action). The procedure is dictated
#: by the backend when delegating: with it in the prompt, the realtime model played on its own.
_TRIVIA_RULE = (
    "- Trivia: the questions, their options and the card on the screen come only from the "
    "backend: never make up or say a question it has not given you. If someone does not "
    "know what to ask you, you can suggest the trivia."
)

#: The date and the time, given once when the session opens.
_CLOCK_RULE = (
    '- You know the date: the "DATE AND TIME" section gives it, with the time this '
    "conversation started. Do not mention the date or the time on your own: use them only "
    "if you are asked what day or what time it is. That time is when the conversation "
    "started, so if you are asked the exact time, give it as approximate."
)

#: When to search the web (``web_search`` of the backend).
_SEARCH_WHEN = (
    "- You are asked something that is not in your knowledge base and can be looked up "
    "online (news, the weather, facts about a company, a technology, an event or a public "
    "figure): search for it before saying you do not know. Never look up information about "
    "the people you talk to or about private individuals."
)

#: How Sonnia gets what the camera sees (see :func:`camera_mode`).
CameraMode = Literal["notes", "look", "none"]

_CAMERA_RULE: dict[CameraMode, str] = {
    "notes": (
        f'- Sometimes you get internal notes that start with "{CAMERA_NOTE_PREFIX}" with what '
        "your camera sees at that moment. Use them naturally, for example for the compliment "
        "when greeting, but do not read them out loud or say you get notes. You do not see "
        "images directly: only those notes. If you have no recent note, do not make up what "
        "you see."
    ),
    "look": (
        "- You do not see anything on your own: your camera only looks when you ask your "
        "backend to look. You decide when: for example if someone shows you something, asks "
        "what you see or how many they are, or someone new arrives and you want to greet them "
        "with a detail of what they wear. Never say you see something you have not looked at "
        "and never make up what you see."
    ),
    "none": (
        "- Right now you have no camera: you cannot see anyone. Do not make up what you see "
        "and do not compliment what someone is wearing."
    ),
}

_LOOK_WHEN: dict[CameraMode, str] = {
    "notes": "- You are asked what you see, someone shows you something on camera or you need to look again.",
    "look": (
        "- You want to look through the camera: you are asked what you see or how many they "
        "are, someone shows you something or someone new arrives whom you want to greet with "
        "a detail of what they wear."
    ),
}

_NO_DELEGATE_CHAT: dict[CameraMode, str] = {
    "notes": "- You greet, chat or answer something that is already in your knowledge base.",
    "look": (
        "- You chat or answer something that is already in your knowledge base. When "
        "greeting, delegate only if you want to look at the person who arrives."
    ),
    "none": "- You greet, chat or answer something that is already in your knowledge base.",
}

#: Where Sonnia is: in a public place with people around.
_SETTING_RULE = (
    "- You are in a public place where many people may be around. Answer only when someone "
    "is talking to you; ignore background conversations, coughs, applause and music. If you "
    "hear something stray that is not meant for you, stay quiet."
)


def _eyes(settings: Settings) -> str:
    if settings.vision.source == "unity":
        return "the webcam of the computer that runs your avatar"
    return "a camera next to your screen"


def camera_mode(settings: Settings, action_names: list[str]) -> CameraMode:
    """How Sonnia sees: automatic ``[Camera]`` notes, only when she looks (``look``) or nothing."""
    vision = settings.vision
    if vision.source == "none" or not settings.llm.supports_vision:
        return "none"
    if vision.on_turn_start or vision.interval_seconds > 0:
        return "notes"
    return "look" if "look" in action_names else "none"


BACKEND_PROMPT = """\
You are the backend of Sonia, a virtual assistant who talks with people in person through an animated 3D avatar. Sonia is another model that speaks out loud with the users and delegates tasks to you: you solve them with your tools and give her back the result.

Rules:
- Do what the task asks with the tools you have and answer with one or two short, factual sentences, without markdown or lists, in the language the user is speaking (English by default): Sonia will use them to keep talking.
- Everything you return is said out loud by Sonia: no code, web addresses, tables or lists. If someone asks for a script or a program, explain in two or three sentences how it would be done, without writing it.
- Do not greet or introduce yourself: Sonia is already talking with the user.
- To show images, use only the exact gallery ids.
- If you look through the camera, describe only what is useful for the conversation: how many people there are, clothes and colors, glasses, caps, badges, logos or readable text, and objects they are showing. Never talk about the body, weight, age or skin, and never guess origin, gender or profession.
- Use only the facts in the knowledge base and from your tools. If something is not there, say so; never make up facts, figures or names.
- Do not name brands, companies, products or models of the technology Sonia is made with (her voice, you or her avatar): if asked, answer in general terms.
- If the result of a tool starts with "FOR SONIA:", return everything after it as is, whole and without summarizing: it is Sonia's script (for example, the trivia question with its options, which she does not read out loud)."""


def _action_names(registry: ActionRegistry | None) -> list[str]:
    return list(registry.names()) if registry is not None else []


#: The lines of the stack (:func:`describe_live_stack`). The code puts the dash in front.
_STACK_TITLE = "YOUR STACK RIGHT NOW (generated automatically at startup):"
_STACK_VOICE = (
    "Voice and conversation: a speech-to-speech artificial intelligence model, real-time "
    "and in the cloud: it hears you and speaks directly with its own voice, which is why you "
    "can be interrupted like in a normal conversation."
)
_STACK_BACKEND = (
    "Actions and delegated tasks: your backend, an artificial intelligence agent with "
    "tools that works behind the scenes, also in the cloud."
)
_STACK_EYES_NONE = "Eyes: no camera right now; you cannot see anyone, do not make up what you see."
#: ``{origin}``: where the photos come from (:func:`_eyes`).
_STACK_EYES_LOOK = (
    "Eyes: {origin}; you do not watch all the time: when you decide to, your backend takes "
    "a photo and tells you what is in it. Photos are not stored."
)
#: ``{where}``: "on this same computer" or "in the cloud", depending on the vision server.
_STACK_EYES_NOTES = (
    "Eyes: {origin}; when someone starts talking to you, a vision model ({where}) describes "
    f"the photo and it reaches you as a {CAMERA_NOTE_PREFIX} note. Photos are not stored."
)
_STACK_SEARCH = (
    "Web search: your backend can search the web when you ask it for something you do not know."
)
_STACK_BODY = (
    "Body: a 3D avatar animated in real time right here, on the local computer: gestures, "
    "gaze, blinking, dances and the mouth, which follows the sounds of your voice."
)
#: ``{actions}``: the names of the registry actions, separated by commas.
_STACK_ACTIONS = "Actions available through the backend: {actions}."
_STACK_NO_ACTIONS = "Actions available: none right now."
_STACK_CLOUD = (
    "YOUR VOICE AND YOUR CONVERSATION RUN IN THE CLOUD: if you are asked where you run, say "
    "it naturally. The avatar and the camera are here, on the local computer; the "
    "conversation is processed in real time by a voice model in the cloud. Do not say you "
    "run locally."
)
_STACK_NO_BRANDS = (
    "NO BRANDS: do not name companies, products, models or programs of the technology you "
    "are made with. If you are asked which model you are, which company is behind your voice "
    "or which program you were made with, say that you combine artificial intelligence "
    "models in the cloud with a real-time 3D avatar, and that the people who run you can "
    "share the technical details. Do not deny it or name another brand: you simply do not "
    "talk about brands."
)


def describe_live_stack(settings: Settings, *, action_names: list[str] | None = None) -> str:
    """The components Sonnia uses, told without brands.

    It is generated at startup so that Sonnia can talk about herself accurately, but
    in general terms: neither the voice model, nor the backend one, nor the avatar
    engine are named.
    """
    live = settings.live
    lines = [_STACK_VOICE, _STACK_BACKEND]

    mode = camera_mode(settings, action_names or [])
    if mode == "none":
        lines.append(_STACK_EYES_NONE)
    elif mode == "look":
        lines.append(_STACK_EYES_LOOK.format(origin=_eyes(settings)))
    else:
        host = host_of(settings.llm.base_url)
        where = "on this same computer" if is_local_host(host) else "in the cloud"
        lines.append(_STACK_EYES_NOTES.format(origin=_eyes(settings), where=where))
    if live.backend_web_search:
        lines.append(_STACK_SEARCH)
    lines.append(_STACK_BODY)
    lines.append(
        _STACK_ACTIONS.format(actions=", ".join(action_names))
        if action_names
        else _STACK_NO_ACTIONS
    )
    lines.append(_STACK_CLOUD)
    lines.append(_STACK_NO_BRANDS)
    return "\n".join([_STACK_TITLE] + [f"- {line}" for line in lines])


#: ``{date}``: the spoken date and time when the session opens.
_CLOCK_SECTION = (
    "DATE AND TIME (when this conversation started): {date}. Do not say it unless you are asked."
)


#: Do not make up anyone's looks (without having looked, the model complimented glasses
#: and smiles it had never seen).
_LOOKS_REMINDER: dict[CameraMode, str] = {
    "look": (
        "- You do not know what anyone looks like or what they wear until you look through "
        "the camera (by delegating): do not comment on clothes, glasses, hair, smile or "
        "anything about their appearance without having seen it in this conversation. For a "
        "compliment, look first."
    ),
    "notes": (
        f"- About people's appearance you only know what the recent {CAMERA_NOTE_PREFIX} notes "
        "say: do not comment on anything that is not in them."
    ),
    "none": "- You have no camera: do not comment on anyone's appearance or clothes.",
}

#: What the backend only does if it is delegated, with its name for the reminder.
_BACKEND_DOES = {
    "show_image": "showing or hiding images",
    "look": "looking through the camera",
    "play_animation": "dancing or making a gesture",
    "start_trivia": "the trivia (starting it, recording answers, moving on, restarting and ending it)",
}
_BACKEND_DOES_SEARCH = "searching the web"

_REMINDER_TITLE = "BEFORE EVERY ANSWER, REMEMBER (this overrides everything above):"
#: ``{things}``: what only the backend does (``_BACKEND_DOES``), with commas and an "and".
_REMINDER_DELEGATE = (
    "- These only happen if you delegate them to your backend: {things}. Delegate first and "
    'speak afterwards. Never say you are already doing it, that it is done or "here it '
    'goes" without having delegated it: if you do not delegate, nothing happens on the screen.'
)
_REMINDER_MOVES = (
    "- If you are asked to dance or make a gesture, delegate it in that same turn. If you are "
    "told you did not do it, it is because you did not delegate it: delegate it now."
)
_REMINDER_TRIVIA = (
    "- In the trivia never say questions or options from your own head: start it by "
    "delegating and read the question the backend returns."
)
_REMINDER_SEARCH = (
    "- If you do not know something and it can be looked up online, delegate the search "
    "before saying you do not know."
)


def _reminder_section(names: list[str], *, web_search: bool, mode: CameraMode = "look") -> str:
    """Delegation reminder at the very end, which is what the model reads closest.

    With long instructions (persona, knowledge), the realtime model ended up saying
    "here goes the little dance!" or making up the trivia question without delegating
    anything.
    """
    things = [text for name, text in _BACKEND_DOES.items() if name in names]
    if web_search:
        things.append(_BACKEND_DOES_SEARCH)
    if not things:
        return ""
    listed = ", ".join(things[:-1]) + f" and {things[-1]}" if len(things) > 1 else things[0]
    lines = [_REMINDER_TITLE, _REMINDER_DELEGATE.format(things=listed)]
    if "play_animation" in names:
        lines.append(_REMINDER_MOVES)
    if "start_trivia" in names:
        lines.append(_REMINDER_TRIVIA)
    if web_search:
        lines.append(_REMINDER_SEARCH)
    lines.append(_LOOKS_REMINDER[mode])
    return "\n".join(lines)


#: ``{notes}``: today's notes written by the operator in the panel. Also in the backend.
_NOTES_SECTION = (
    "TODAY'S NOTES FROM THE PEOPLE WHO RUN YOU (they are newer than your knowledge base; "
    "if they clash, these win):\n{notes}"
)


def _notes_section(notes: str) -> str:
    return _NOTES_SECTION.format(notes=notes.strip())


#: ``{knowledge}``: the files of ``assets/knowledge``.
_KNOWLEDGE_SECTION = (
    "KNOWLEDGE BASE (these are your only verified facts; whatever is not here, do not "
    "claim it):\n\n{knowledge}"
)

#: ``{images}``: the gallery ids, separated by commas.
_GALLERY_LINE = "Images the backend can show on your screen: {images}"
_GALLERY_EMPTY = "The image gallery is empty: you have no images to show on your screen."
_GALLERY_WATCH = (
    f'If images are added or removed, you will get an internal note "{GALLERY_NOTE_PREFIX}" '
    "with the new list: that one wins."
)


def build_live_instructions(
    settings: Settings,
    *,
    registry: ActionRegistry | None,
    gallery_ids: list[str],
    knowledge_dir: KnowledgeSource = None,
    notes: str = "",
    clock_text: str = "",
) -> str:
    """Session ``instructions``: persona, rules, knowledge, stack and reminder."""
    names = _action_names(registry)
    mode = camera_mode(settings, names)
    web_search = settings.live.backend_web_search

    capabilities = "\n".join(
        [_CAPABILITIES[n] for n in names if n in _CAPABILITIES]
        + ([_SEARCH_CAPABILITY] if web_search else [])
    )
    look_when = _LOOK_WHEN[mode] + "\n" if mode in _LOOK_WHEN else ""
    trivia = "start_trivia" in names
    rules = LIVE_RULES.format(
        capabilities=capabilities or _NO_CAPABILITIES,
        clock_rule=_CLOCK_RULE,
        setting_rule=_SETTING_RULE,
        camera_rule=_CAMERA_RULE[mode],
        look_when=look_when if "look" in names else "",
        moves_when=_MOVES_WHEN + "\n" if "play_animation" in names else "",
        trivia_rule=_TRIVIA_RULE + "\n" if trivia else "",
        trivia_when=_TRIVIA_WHEN + "\n" if trivia else "",
        search_when=_SEARCH_WHEN + "\n" if web_search else "",
        no_delegate_chat=_NO_DELEGATE_CHAT[mode],
    )
    parts = [SYSTEM_PROMPT.strip(), rules]
    if clock_text:
        parts.append(_CLOCK_SECTION.format(date=clock_text))
    knowledge = load_knowledge(knowledge_dir)
    if knowledge:
        parts.append(_KNOWLEDGE_SECTION.format(knowledge=knowledge))
    if notes.strip():
        parts.append(_notes_section(notes))
    gallery = _GALLERY_LINE.format(images=", ".join(gallery_ids)) if gallery_ids else _GALLERY_EMPTY
    if settings.gallery_watch_seconds > 0:
        gallery += " " + _GALLERY_WATCH
    parts.append(gallery)
    parts.append(describe_live_stack(settings, action_names=names))
    reminder = _reminder_section(names, web_search=web_search, mode=mode)
    if reminder:
        parts.append(reminder)
    return "\n\n".join(parts)


#: When to delegate the trivia.
_TRIVIA_WHEN = (
    "- The user wants to play the trivia: delegate starting it in that same turn, without "
    "asking anything first (pass the level only if they already told you). Also when they "
    'pick an option ("B", "Kotlin"), ask for the next question, want to start a new one '
    "from scratch or want to stop playing."
)

#: Backend rules for searching the web (``web_search``).
_BACKEND_SEARCH_RULE = (
    "- You can search the web when Sonia asks you for something that is not in the knowledge "
    "base (news, the weather, companies, technologies, events, public figures). Search just "
    "enough and answer with the fact in one or two sentences, saying where it comes from "
    '(for example "according to the national weather service"), without reading out web '
    "addresses. For anything about the place where Sonia is, the knowledge base wins. Do not "
    "look up personal information about the people she talks to or about private "
    "individuals: say you do not look that up."
)

#: ``{date}``: the spoken date and time when the session opens.
_BACKEND_CLOCK = (
    "Date and time when the conversation started: {date}. If the task brings a more recent "
    "time, that one wins."
)
#: ``{images}``: the gallery ids, separated by commas (or "none").
_BACKEND_GALLERY = (
    "Gallery images at the start (exact ids): {images}. Images can be added or removed "
    "during the conversation: if the task names one that is not in this list, try it anyway; "
    "show_image tells which ones exist."
)
#: ``{knowledge}``: the files of ``assets/knowledge``.
_BACKEND_KNOWLEDGE = "KNOWLEDGE BASE:\n\n{knowledge}"


def build_backend_instructions(
    *,
    gallery_ids: list[str],
    knowledge_dir: KnowledgeSource = None,
    notes: str = "",
    clock_text: str = "",
    web_search: bool = False,
) -> str:
    """Instructions of the Responses backend: rules, gallery and knowledge."""
    rules = BACKEND_PROMPT
    if web_search:
        rules += "\n" + _BACKEND_SEARCH_RULE
    parts = [rules]
    if clock_text:
        parts.append(_BACKEND_CLOCK.format(date=clock_text))
    parts.append(_BACKEND_GALLERY.format(images=", ".join(gallery_ids) or "none"))
    knowledge = load_knowledge(knowledge_dir)
    if knowledge:
        parts.append(_BACKEND_KNOWLEDGE.format(knowledge=knowledge))
    if notes.strip():
        parts.append(_notes_section(notes))
    return "\n\n".join(parts)


def _web_search_tool(settings: Settings) -> dict[str, Any]:
    """The Responses API ``web_search`` tool, located where Sonnia is (if configured)."""
    live = settings.live
    location: dict[str, Any] = {"type": "approximate"}
    if live.backend_web_search_country.strip():
        location["country"] = live.backend_web_search_country.strip().upper()
    if live.backend_web_search_city.strip():
        location["city"] = live.backend_web_search_city.strip()
    if settings.timezone.strip():
        location["timezone"] = settings.timezone.strip()
    tool: dict[str, Any] = {"type": "web_search"}
    if len(location) > 1:
        tool["user_location"] = location
    if live.backend_web_search_context.strip() in ("low", "medium", "high"):
        tool["search_context_size"] = live.backend_web_search_context.strip()
    return tool


def build_session_config(
    settings: Settings,
    *,
    registry: ActionRegistry | None,
    gallery_ids: list[str],
    knowledge_dir: KnowledgeSource = None,
    notes: str = "",
    clock_text: str = "",
) -> dict[str, Any]:
    """The ``session`` object of ``session.start``.

    The API rejects unknown fields, so only the optional ones that have a value
    are sent.
    """
    live = settings.live
    responses: dict[str, Any] = {
        "model": live.backend_model,
        "instructions": build_backend_instructions(
            gallery_ids=gallery_ids,
            knowledge_dir=knowledge_dir,
            notes=notes,
            clock_text=clock_text,
            web_search=live.backend_web_search,
        ),
        "max_output_tokens": max(16, live.backend_max_output_tokens),
    }
    tools = registry.to_responses_tools() if registry is not None and len(registry) else []
    if live.backend_web_search:
        tools.append(_web_search_tool(settings))
    if tools:
        responses["tools"] = tools
        responses["tool_choice"] = "auto"
        # One at a time: Sonnia shows the image and then talks about it, no races.
        responses["parallel_tool_calls"] = False
    if live.backend_reasoning_effort.strip():
        responses["reasoning"] = {"effort": live.backend_reasoning_effort.strip()}
    if live.backend_service_tier.strip():
        responses["service_tier"] = live.backend_service_tier.strip()

    return {
        "model": live.model,
        "instructions": build_live_instructions(
            settings,
            registry=registry,
            gallery_ids=gallery_ids,
            knowledge_dir=knowledge_dir,
            notes=notes,
            clock_text=clock_text,
        ),
        "audio": {
            "format": {"type": "audio/pcm", "rate": int(live.sample_rate)},
            "output": {"voice": live.voice},
        },
        "delegation": {"type": "responses", "responses": responses},
    }


def gallery_note(added: list[str], removed: list[str], ids: list[str], *, max_chars: int) -> str:
    """``[Gallery]`` note for the open session: what changed and which images are left.

    It goes through ``thinking``, which does not make it speak. If it does not fit
    in ``max_chars`` (the limit of an append), the list is cut with "and N more".
    """

    def listed(items: list[str], budget: int) -> str:
        shown: list[str] = []
        for index, item in enumerate(items):
            rest = len(items) - index - 1
            tail = f" and {rest} more" if rest else ""
            if len(", ".join([*shown, item])) + len(tail) > budget:
                return ", ".join(shown) + f" and {len(items) - index} more"
            shown.append(item)
        return ", ".join(shown)

    budget = max(40, (max_chars - 260) // 3)
    parts = [GALLERY_NOTE_PREFIX]
    if added:
        parts.append(f"New images were added to your gallery: {listed(added, budget)}.")
    if removed:
        parts.append(f"Removed: {listed(removed, budget)}.")
    if ids:
        parts.append(f"Images you can show now (exact ids): {listed(ids, budget)}.")
        parts.append("Do not announce it: show them when they fit the conversation.")
    else:
        parts.append("Your gallery is now empty: you no longer have images to show.")
    return " ".join(parts)[:max_chars]
