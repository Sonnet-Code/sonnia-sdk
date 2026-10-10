"""Lo que lee GPT-Live en la búsqueda relámpago: reglas, guiones y avisos.

Todo con «Sonia» (lo que oye y lee el modelo; en pantalla va «Sonnia») y sin nombrar el
stack. Las reglas (``RULES_TEXT``) entran por ``instruct`` y no pueden pasar de 1200
caracteres; lo demás son guiones (``speak`` o el resultado de una acción, que sale con
``PARA SONIA:``).

Las reglas y los guiones se pueden cambiar desde el panel de la nube (``sonia.prompts``,
:func:`prompt_specs`): el juego pide cada pieza con :func:`live_text` al usarla. Las frases
grabadas (``GO_PHRASE``...) y los trozos que se pegan detrás de otra pieza con un espacio
delante (``NEXT_TEXT``, ``FINAL_TEXT``, ``WIN_CONTACT_TEXT``...) siguen en el código.
"""

from __future__ import annotations

from collections.abc import Callable

from sonia.games.base import INSTRUCT_MAX_CHARS
from sonia.prompts import BOOK, PROMPT_MAX_LEN, PromptSpec

__all__ = [
    "ALL_FOUND_TEXT",
    "ALREADY_TEXT",
    "BACK_TO_TALK_TEXT",
    "CANCEL_TEXT",
    "FINAL_TEXT",
    "FOUND_PHRASE",
    "FOUND_TEXT",
    "GO_PHRASE",
    "LOST_TEXT",
    "NEXT_TEXT",
    "NOT_YET_TEXT",
    "NO_ANSWER_TEXT",
    "NO_MORE_TEXT",
    "NOT_STARTED_TEXT",
    "NUDGE_RUNNING",
    "NUDGE_STOP",
    "RESUME_TEXT",
    "ROUND_TEXT",
    "RULES_TEXT",
    "SILENT_TEXT",
    "START_TEXT",
    "STILL_LOOKING_TEXT",
    "TIMEOUT_PHRASE",
    "TIMEOUT_TEXT",
    "WIN_CONTACT_TEXT",
    "WON_TEXT",
    "live_text",
    "prompt_specs",
]

#: Empujones tras un turno del visitante sin delegación (``nudge``): órdenes cortas, y el
#: manager añade al final que es una nota interna. En las pruebas con la API real, «Bueno,
#: paramos» no terminaba el juego.
NUDGE_RUNNING = (
    "BÚSQUEDA: si dijeron que ya lo tienen («¡aquí!», «¡lo tengo!»), delega comprobarlo ya; si "
    "pidieron parar o se despidieron, delega terminar el juego."
)
NUDGE_STOP = "BÚSQUEDA: si pidieron parar o se despidieron, delega terminar el juego."

#: Las frases fijas con tiempo exacto: suenan grabadas (``cache/voice``) en el momento justo.
GO_PHRASE = "¡Ya!"
FOUND_PHRASE = "¡Lo veo!"
TIMEOUT_PHRASE = "¡Tiempo!"

#: Las reglas del juego, al empezar (``GameHost.instruct``: 1200 caracteres como mucho).
RULES_TEXT = """\
JUEGO EN MARCHA: búsqueda relámpago, {total} rondas de {seconds} segundos. En cada ronda hay un objeto que el grupo tiene que enseñar a la cámara (se ve en tu pantalla) y gana la ronda quien lo enseñe antes de que se acabe el tiempo.
- Tú no ves nada: el sistema mira la cámara y te avisa. No digas que lo ves ni que lo han encontrado hasta que te lo avise o lo diga el resultado de busqueda_check.
- Anuncia cada ronda con ganas, diciendo el objeto tal cual, y calla. El «¡Ya!» y el «¡Tiempo!» los pone el sistema: no los digas ni cuentes el tiempo. No preguntes si están listos.
- En plena ronda calla o anima con pocas palabras. Si alguien grita «¡aquí!», «¡ya lo tengo!» o te enseña algo, delega busqueda_check (sin argumentos) antes de decir nada: en la pantalla nada cambia si no lo delegas.
- No uses look en este juego. Al celebrar habla del objeto, nunca de la persona ni de su ropa, ni digas quién fue.
- Si quieren dejar de jugar, delega terminarlo."""

#: El guion de arranque (resultado de ``start_game``, o lo que se le pasa si empieza desde el panel).
START_TEXT = (
    "La búsqueda relámpago ya está en tu pantalla: {total} rondas de {seconds} segundos, y la "
    "cámara en vivo para que sepan dónde enseñar el objeto. Explícalo en una frase corta (el "
    "primero que te enseñe lo que pidas gana la ronda) y anuncia ya la ronda 1 de {total} con "
    "ganas: «¡El primero que me enseñe {name}!». No digas «¡ya!» ni preguntes si están listos: "
    "el sistema da la salida. Después calla."
)

#: Cada ronda nueva (a partir de la segunda), por ``speak``.
ROUND_TEXT = (
    "BÚSQUEDA, ronda {number} de {total}: anuncia con ganas, en una sola frase, «¡El primero "
    "que me enseñe {name}!». No digas «¡ya!» (lo pone el sistema) ni preguntes si están listos. "
    "Después calla."
)

#: Se ve el objeto de la ronda (``what`` ya filtrado: nada de la persona).
FOUND_TEXT = (
    "BÚSQUEDA: ¡lo han encontrado! En la cámara se ve «{what}». Ya ha sonado «¡Lo veo!» y ha "
    "salido el confeti: no lo repitas. Celébralo en una frase corta, hablando solo del objeto; "
    "nunca de la persona ni de su ropa, ni digas quién fue."
)

#: Se acabó el tiempo sin verlo.
TIMEOUT_TEXT = (
    "BÚSQUEDA: se acabó el tiempo y nadie enseñó {name}. Ya ha sonado «¡Tiempo!»: no lo "
    "repitas. Díselo con humor en una frase corta, sin culpar a nadie."
)

#: Se acabó el tiempo y la cámara no contestó a ninguna mirada: algo falla, no que nadie lo trajera.
#: El equipo del stand salta el objeto desde el panel («Saltar objeto»).
SKIP_TEXT = (
    "BÚSQUEDA: se salta {name} y esta ronda no cuenta como encontrada. Ya ha sonado «¡Tiempo!»: "
    "no lo repitas. Dilo con humor en una frase corta, sin culpar a nadie."
)

SILENT_TEXT = (
    "BÚSQUEDA: se acabó el tiempo, pero en esta ronda la cámara no contestó a ninguna mirada: "
    "algo falla con ella. Ya ha sonado «¡Tiempo!»: no lo repitas. Dilo con humor en una frase "
    "corta, sin culpar a nadie, y di que lo seguís intentando."
)

#: La cámara no contestó en dos rondas seguidas: se cancela el juego.
CANCEL_TEXT = (
    "BÚSQUEDA: la cámara no responde y no se puede seguir jugando. Discúlpate con humor en una "
    "frase corta, di que el juego queda para otro momento y sigue conversando con normalidad."
)

#: Tras celebrar o lamentar una ronda que no es la última.
NEXT_TEXT = " Después calla: el sistema anuncia la siguiente ronda."

#: Tras la última ronda: cómo ha quedado la partida.
FINAL_TEXT = " Con esto termina el juego: han encontrado {found} de {total}."
ALL_FOUND_TEXT = " ¡Las {total} de {total}! Felicítalos a lo grande."
WON_TEXT = " Han llegado a la mitad o más: felicítalos con ganas."
LOST_TEXT = " No han llegado a la mitad: anímalos con cariño a intentarlo otra vez cuando quieran."
#: Sonia no sabe qué premios hay: a quien gana lo manda con el equipo del stand (como la trivia).
WIN_CONTACT_TEXT = (
    " Diles que pasen a hablar con {contact} aquí en el stand. No sabes qué premios hay: no "
    "prometas ninguno y, si preguntan, que se lo cuenten ellos."
)
BACK_TO_TALK_TEXT = " Luego sigue conversando con normalidad."

#: ``busqueda_check`` mientras la ronda aún no ha empezado (falta el «¡Ya!»).
NOT_STARTED_TEXT = (
    "Todavía no se ha dado la salida de la ronda. Dile con humor que espere al «¡Ya!» para "
    "enseñarlo. No digas que lo ves."
)

#: ``busqueda_check`` cuando la ronda ya terminó (o la está contando el sistema).
ALREADY_TEXT = (
    "Esta ronda ya terminó y su resultado ya se ha contado: no lo repitas ni digas que lo ves "
    "ahora. Espera a que el sistema anuncie la siguiente."
)

#: ``busqueda_check`` y no se ve el objeto.
NOT_YET_TEXT = (
    "Con la cámara no se ve todavía {name}. Dile en una frase corta que lo acerque, bien a la "
    "vista y quieto, y que siga buscando: quedan unos {left} segundos. No digas que lo ves."
)

#: ``busqueda_check`` y el modelo de visión no contestó.
NO_ANSWER_TEXT = (
    "La cámara no ha contestado esta vez. Pídele que lo intente otra vez, bien a la vista y "
    "quieto; el sistema sigue mirando. No digas que lo ves."
)

#: ``busqueda_check`` y ya no quedan miradas en esta ronda.
NO_MORE_TEXT = (
    "En esta ronda ya no se puede mirar más la cámara: solo queda esperar a que se acabe el "
    "tiempo. Dilo en una frase corta. No digas que lo ves."
)

#: ``busqueda_check`` mientras otra mirada tarda en contestar.
STILL_LOOKING_TEXT = (
    "La cámara está mirando justo ahora. Dile en una frase corta que aguante un momento "
    "enseñándolo; el sistema te avisa si lo ve. No digas que lo ves."
)

#: GPT-Live vuelve a delegar empezar el juego en marcha.
RESUME_TEXT = (
    "Ya estáis jugando a la búsqueda relámpago: ronda {number} de {total}, el objeto es "
    "{name}. No hace falta empezarla otra vez: sigue con la ronda."
)


# -- prompts editables desde la nube (``sonia.prompts``) ---------------------------------

#: Ids de las piezas: ``juegos/busqueda/<pieza>``.
PROMPT_PREFIX = "juegos/busqueda/"
PROMPT_GROUP = "Juego: Búsqueda relámpago"


def live_text(piece: str, app_text: str, **values: object) -> str:
    """El texto en uso de la pieza (el de la nube si lo hay y vale; si no, ``app_text``, el
    de la app), con sus marcadores rellenos con ``values``."""
    return BOOK.render(PROMPT_PREFIX + piece, fallback=app_text, **values)


def _piece(
    piece: str,
    title: str,
    default: Callable[[], str],
    *,
    fields: tuple[str, ...] = (),
    required: tuple[str, ...] = (),
    help: str = "",
    instruct: bool = False,
) -> PromptSpec:
    return PromptSpec(
        id=PROMPT_PREFIX + piece,
        group=PROMPT_GROUP,
        title=title,
        default=default,
        fields=fields,
        required=required,
        applies="ronda",
        help=help,
        max_len=INSTRUCT_MAX_CHARS if instruct else PROMPT_MAX_LEN,
    )


_TOTAL = "{total}: las rondas de la partida (GAME_BUSQUEDA_ROUNDS). "
_SECONDS = "{seconds}: los segundos de cada ronda (GAME_BUSQUEDA_ROUND_SECONDS). "
_NUMBER = "{number}: el número de la ronda. "
_NAME = "{name}: el objeto de la ronda, como se dice («algo azul»). "
_ROUND_END = (
    "El código añade detrás que calle hasta la siguiente ronda o, en la última, cómo ha "
    "quedado la partida. "
)
_CHECK = "Resultado de «busqueda_check» (alguien dice que ya lo tiene). "
_NUDGE = (
    "Empujón tras un turno del visitante sin delegar: una orden corta, sin frases que pueda "
    "repetir (el código añade al final que es una nota interna)."
)


def prompt_specs() -> list[PromptSpec]:
    """Las piezas de la búsqueda relámpago editables desde el panel, en su orden."""
    return [
        _piece(
            "reglas",
            "Reglas del juego (al empezar, sin hablar)",
            lambda: RULES_TEXT,
            fields=("total", "seconds"),
            instruct=True,
            help=_TOTAL
            + _SECONDS
            + "Que siga diciendo que delegue busqueda_check: si no, Sonia no lo comprueba.",
        ),
        _piece(
            "arranque",
            "Guion de arranque: explica el juego y anuncia la primera ronda",
            lambda: START_TEXT,
            fields=("total", "seconds", "name"),
            required=("name",),
            help=_TOTAL + _SECONDS + _NAME,
        ),
        _piece(
            "reanudar",
            "Guion si vuelve a pedir el juego que ya está en marcha",
            lambda: RESUME_TEXT,
            fields=("number", "total", "name"),
            help=_NUMBER + _TOTAL + _NAME,
        ),
        _piece(
            "ronda",
            "Anuncio de cada ronda nueva (de la segunda en adelante)",
            lambda: ROUND_TEXT,
            fields=("number", "total", "name"),
            required=("name",),
            help=_NUMBER + _TOTAL + _NAME,
        ),
        _piece(
            "encontrado",
            "Guion cuando la cámara ve el objeto",
            lambda: FOUND_TEXT,
            fields=("what",),
            help="{what}: lo que se ve, solo el objeto («botella azul»). " + _ROUND_END,
        ),
        _piece(
            "tiempo",
            "Guion cuando se acaba el tiempo sin verlo",
            lambda: TIMEOUT_TEXT,
            fields=("name",),
            help=_NAME + _ROUND_END,
        ),
        _piece(
            "saltado",
            "Guion cuando el equipo salta el objeto desde el panel",
            lambda: SKIP_TEXT,
            fields=("name",),
            help=_NAME + _ROUND_END,
        ),
        _piece(
            "camara_muda",
            "Guion cuando la cámara no contestó en toda la ronda",
            lambda: SILENT_TEXT,
            help=_ROUND_END,
        ),
        _piece(
            "cancelado",
            "Guion cuando la cámara no contesta en dos rondas y se cancela",
            lambda: CANCEL_TEXT,
        ),
        _piece(
            "sin_salida",
            "Comprobar antes del «¡Ya!»",
            lambda: NOT_STARTED_TEXT,
            help=_CHECK,
        ),
        _piece(
            "ya_contada",
            "Comprobar con la ronda ya contada",
            lambda: ALREADY_TEXT,
            help=_CHECK,
        ),
        _piece(
            "aun_no",
            "Comprobar y no se ve el objeto",
            lambda: NOT_YET_TEXT,
            fields=("name", "left"),
            help=_CHECK + _NAME + "{left}: los segundos que quedan.",
        ),
        _piece(
            "sin_respuesta",
            "Comprobar y la cámara no contesta",
            lambda: NO_ANSWER_TEXT,
            help=_CHECK,
        ),
        _piece(
            "sin_miradas",
            "Comprobar sin miradas en la ronda",
            lambda: NO_MORE_TEXT,
            help=_CHECK,
        ),
        _piece(
            "mirando",
            "Comprobar mientras otra mirada tarda",
            lambda: STILL_LOOKING_TEXT,
            help=_CHECK,
        ),
        _piece(
            "empujon_ronda",
            "Empujón en plena ronda",
            lambda: NUDGE_RUNNING,
            help=_NUDGE,
        ),
        _piece(
            "empujon_parar",
            "Empujón entre rondas",
            lambda: NUDGE_STOP,
            help=_NUDGE,
        ),
    ]
