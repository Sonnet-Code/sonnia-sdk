"""La secuencia del Wordle para el orquestador falso (``scripts/juegos_demo.py --juego wordle``).

Pasa por cada estado de la pantalla y pide una captura 9:16 en cada uno (``docs/juegos.md``,
«Probar la pantalla sin Sonia»; ``docs/juegos-unity.md``, «Capturas en batch»):

1. Una partida que se gana al quinto intento: la rejilla vacía, un intento (a medio volteo y
   terminado, con letras repetidas), una palabra que no vale, la pista tras el cuarto intento,
   el acierto con confeti y el resultado final.
2. Otra que se pierde: seis intentos con letras repetidas, la palabra y su pista, y el final.

Los mensajes salen de las mismas reglas que el juego (:func:`~sonia.games.wordle.logic.score_guess`
y :func:`~sonia.games.wordle.logic.used_letters`); un test comprueba que son los que manda
:class:`~sonia.games.wordle.game.WordleGame` de verdad. Nada llama a ninguna API ni usa la cámara.
"""

from __future__ import annotations

from typing import Any

from sonia.games.demo import Capture, GameMsg, Send, Step, Wait
from sonia.games.wordle.logic import GREEN, WORD_LENGTH, score_guess, used_letters
from sonia.ws import protocol as p

__all__ = ["HINT_AFTER", "ROWS", "WON", "LOST", "guess_data", "steps"]

ROWS = 6
HINT_AFTER = 4

#: Palabra y pista de cada partida (las del banco de la app).
WON = ("REACT", "Biblioteca para hacer interfaces con componentes, creada por Meta.")
LOST = (
    "CACHE",
    "Memoria rápida que guarda lo usado hace poco para no tener que pedirlo otra vez.",
)

#: Los intentos de cada partida. En la segunda están los casos de letras repetidas: CHECK contra
#: CACHE (la C verde y la otra amarilla) y MERGE contra CACHE (la E del final es verde y la
#: segunda, gris: de esa letra solo hay una).
WON_GUESSES = ["CLOUD", "SWIFT", "REDIS", "PIXEL", "REACT"]
LOST_GUESSES = ["LINUX", "CLOUD", "CRASH", "CHECK", "PIXEL", "MERGE"]


def guess_data(
    words: list[str], secret: str, hint: str, *, rows: int = ROWS, hint_after: int = HINT_AFTER
) -> dict[str, Any]:
    """Lo que manda el juego tras el último intento de ``words`` (las mismas claves que ``_state``).

    ``hint`` es la pista de la palabra: sale desde el intento ``hint_after`` si la partida sigue,
    y al perder.
    """
    board = [{"letters": w, "marks": score_guess(w, secret)} for w in words]
    last = board[-1]
    count = len(words)
    won = last["marks"] == GREEN * WORD_LENGTH
    lost = not won and count >= rows
    result = "win" if won else "lose" if lost else ""
    show_hint = lost or (hint_after >= 1 and count >= hint_after)
    return {
        "row": count - 1,
        "letters": last["letters"],
        "marks": last["marks"],
        "board": board,
        "used": used_letters([(row["letters"], row["marks"]) for row in board]),
        "hint": hint if show_hint else "",
        "result": result,
        "word": secret if result else "",
    }


def start_data() -> dict[str, Any]:
    """El ``start`` de la partida (el título lo pone el orquestador)."""
    return {
        "title": "Wordle de tecnología",
        "rows": ROWS,
        "cols": WORD_LENGTH,
        "hint_after": HINT_AFTER,
    }


def steps() -> list[Step]:
    secret, hint = WON
    won = WON_GUESSES
    out: list[Step] = [
        GameMsg("start", start_data()),
        Capture("wordle-1-empezar", settle_s=1.4),
        # El primer intento, a medio volteo y terminado.
        GameMsg("guess", guess_data(won[:1], secret, hint)),
        Capture("wordle-2a-volteo", settle_s=0.95),
        Capture("wordle-2b-jugada", settle_s=1.4),
        # Una palabra que no vale: la fila se sacude y un rótulo dice por qué.
        Send(p.msg_transcript("assistant", "¡Esa no vale! Tienen que ser cinco letras.", True)),
        GameMsg(
            "invalid",
            {"letters": "WEB", "reason": "length", "message": "Tienen que ser 5 letras"},
        ),
        Capture("wordle-3-invalida", settle_s=0.5),
        Wait(1.8),
        GameMsg("guess", guess_data(won[:2], secret, hint)),
        Wait(2.3),
        GameMsg("guess", guess_data(won[:3], secret, hint)),
        Wait(2.3),
        # El cuarto intento fallido: sale la pista.
        GameMsg("guess", guess_data(won[:4], secret, hint)),
        Capture("wordle-4-pista", settle_s=2.6),
        # El acierto: la fila baila, confeti y la palabra con su pista.
        GameMsg("guess", guess_data(won[:5], secret, hint)),
        Capture("wordle-5a-acierto", settle_s=2.2),
        Capture("wordle-5b-confeti", settle_s=1.2),
        Wait(1.0),
        GameMsg("end", {"word": secret, "attempts": len(won), "result": "win"}),
        Capture("wordle-6-final-acierto", settle_s=1.6),
        Wait(5.0),
    ]
    secret, hint = LOST
    lost = LOST_GUESSES
    out += [
        GameMsg("start", start_data()),
        Wait(1.0),
    ]
    for count in range(1, len(lost)):
        out += [GameMsg("guess", guess_data(lost[:count], secret, hint)), Wait(2.2)]
    out += [
        # El último intento sin acertar: la palabra y su pista.
        GameMsg("guess", guess_data(lost, secret, hint)),
        Capture("wordle-7-derrota", settle_s=2.6),
        Wait(1.0),
        GameMsg("end", {"word": secret, "attempts": len(lost), "result": "lose"}),
        Capture("wordle-8-final-derrota", settle_s=1.6),
        Wait(1.0),
    ]
    return out
