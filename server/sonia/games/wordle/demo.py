"""La secuencia del Wordle para el orquestador falso (``scripts/juegos_demo.py --juego wordle``).

Pasa por cada estado de la pantalla y pide una captura 9:16 en cada uno (``docs/juegos.md``,
«Probar la pantalla sin Sonia»; ``docs/juegos-unity.md``, «Capturas en batch»):

1. Una partida que se gana al quinto intento: la rejilla vacía, un intento (a medio volteo y
   terminado), dos palabras que no valen (una corta y una repetida), la pista tras el cuarto
   intento, el acierto con confeti y el resultado final.
2. Otra que se pierde: seis intentos con letras repetidas, la palabra y su pista, y el final.
3. Una de ocho filas y sin pista, con intentos que llegan casi a la vez (el volteo de uno no ha
   terminado cuando llega el siguiente) y que se cancela a medias.
4. Una pantalla que se conecta a mitad de partida: el primer `guess` que recibe trae el tablero
   de cuatro intentos (el último, con la pista más larga que cabe) y las filas que no había visto
   salen ya puestas.
5. Tres veces en que lo dejan antes de acabar (`stop_game` por voz o «Terminar juego» del panel):
   con tres intentos hechos (la fila ya pintada no se vuelve a voltear: solo sale la palabra con
   su pista y el rótulo «lo dejamos aquí»), sin ningún intento, y con una pantalla que se
   conecta justo entonces y recibe el tablero entero ya con la palabra.

Los mensajes salen de las mismas reglas que el juego (:func:`~sonia.games.wordle.logic.score_guess`
y :func:`~sonia.games.wordle.logic.used_letters`); un test comprueba que son los que manda
:class:`~sonia.games.wordle.game.WordleGame` de verdad. Nada llama a ninguna API ni usa la cámara.
"""

from __future__ import annotations

from typing import Any

from sonia.games.demo import Capture, GameMsg, Send, Step, Wait
from sonia.games.wordle.logic import GREEN, WORD_LENGTH, score_guess, used_letters
from sonia.ws import protocol as p

__all__ = [
    "GIVE_UP",
    "GIVE_UP_NONE",
    "GIVE_UP_REPLAY",
    "HINT_AFTER",
    "LONG",
    "LOST",
    "MANY",
    "ROWS",
    "WON",
    "guess_data",
    "start_data",
    "steps",
    "stopped_data",
]

ROWS = 6
HINT_AFTER = 4
#: La tercera partida: más filas y sin pista (``hint_after`` 0).
MANY_ROWS = 8

#: Palabra y pista de cada partida (las del banco de la app).
WON = ("REACT", "Biblioteca para hacer interfaces con componentes, creada por Meta.")
LOST = (
    "CACHE",
    "Memoria rápida que guarda lo usado hace poco para no tener que pedirlo otra vez.",
)
MANY = ("TOKEN", "La unidad en que los modelos de lenguaje cuentan el texto, y por la que cobran.")
#: Una pista de las más largas que admite el banco (160 caracteres).
LONG = (
    "SPARK",
    "Motor para procesar datos masivos en un clúster: lo usan los equipos de datos para "
    "limpiar, unir y analizar tablas enormes en paralelo y a gran escala.",
)

#: Los intentos de cada partida. En la segunda están los casos de letras repetidas: CHECK contra
#: CACHE (la C verde y la otra amarilla) y MERGE contra CACHE (la E del final es verde y la
#: segunda, gris: de esa letra solo hay una).
WON_GUESSES = ["CLOUD", "SWIFT", "REDIS", "PIXEL", "REACT"]
LOST_GUESSES = ["LINUX", "CLOUD", "CRASH", "CHECK", "PIXEL", "MERGE"]
MANY_GUESSES = ["LINUX", "CLOUD", "PIXEL"]
LONG_GUESSES = ["LINUX", "CLOUD", "PIXEL", "CRASH"]

#: Lo dejan antes de acabar: con tres intentos hechos, sin ninguno y con una pantalla que se
#: conecta justo entonces (palabras y pistas del banco de la app).
GIVE_UP = (
    "CLASS",
    "El molde con el que se crean objetos en la programación orientada a objetos.",
)
GIVE_UP_GUESSES = ["LINUX", "REACT", "MODEL"]
GIVE_UP_NONE = (
    "FLASK",
    "Microframework web de Python: con pocas líneas ya tienes un servidor.",
)
GIVE_UP_REPLAY = (
    "PROXY",
    "Intermediario que hace las peticiones en tu nombre y esconde de dónde vienen.",
)
GIVE_UP_REPLAY_GUESSES = ["LINUX", "CLOUD", "PIXEL"]

#: Las palabras que no valen de la primera partida: lo que dice el juego en cada caso.
INVALID_SHORT = {"letters": "WEB", "reason": "length", "message": "Tienen que ser 5 letras"}
INVALID_REPEATED = {"letters": "SWIFT", "reason": "repeated", "message": "Esa ya la probaron"}


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
        "stopped": False,
    }


def stopped_data(words: list[str], secret: str, hint: str) -> dict[str, Any]:
    """Lo que manda el juego cuando lo dejan con la partida en marcha (``stop_requested``).

    No es un intento nuevo: es el último estado con la palabra y su pista (``result: lose``,
    ``stopped: true``). ``row`` es el del último intento, o -1 si no hubo ninguno.
    """
    board = [{"letters": w, "marks": score_guess(w, secret)} for w in words]
    last = board[-1] if board else None
    return {
        "row": len(words) - 1,
        "letters": last["letters"] if last else "",
        "marks": last["marks"] if last else "",
        "board": board,
        "used": used_letters([(row["letters"], row["marks"]) for row in board]),
        "hint": hint,
        "result": "lose",
        "word": secret,
        "stopped": True,
    }


def stopped_end(words: list[str], secret: str) -> dict[str, Any]:
    """El ``end`` de lo que dejaron a medias (el que manda el manager tras ``finish``)."""
    return {"word": secret, "attempts": len(words), "stopped": True, "result": "lose"}


def start_data(rows: int = ROWS, hint_after: int = HINT_AFTER) -> dict[str, Any]:
    """El ``start`` de la partida (el título lo pone el orquestador)."""
    return {
        "title": "Wordle de tecnología",
        "rows": rows,
        "cols": WORD_LENGTH,
        "hint_after": hint_after,
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
        GameMsg("invalid", INVALID_SHORT),
        Capture("wordle-3a-invalida", settle_s=0.5),
        Wait(1.8),
        GameMsg("guess", guess_data(won[:2], secret, hint)),
        Wait(2.3),
        # Una palabra ya probada: las cinco letras con el borde en rojo.
        GameMsg("invalid", INVALID_REPEATED),
        Capture("wordle-3b-repetida", settle_s=0.5),
        Wait(1.8),
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
        Wait(5.0),
    ]
    secret, hint = MANY
    many = MANY_GUESSES
    out += [
        GameMsg("start", start_data(MANY_ROWS, 0)),
        Capture("wordle-9a-ocho-filas", settle_s=1.4),
    ]
    # Los intentos casi a la vez: cada uno llega cuando el volteo del anterior no ha acabado.
    for count in range(1, len(many) + 1):
        data = guess_data(many[:count], secret, hint, rows=MANY_ROWS, hint_after=0)
        out += [GameMsg("guess", data), Wait(0.5)]
    out += [
        Capture("wordle-9b-solapados", settle_s=3.2),
        # El grupo se va a mitad: la partida se cancela y la pantalla se retira sin resultado.
        GameMsg("end", {"result": "cancel"}),
        Wait(2.5),
    ]
    # Una pantalla que se conecta a mitad: solo le llega el último estado, con el tablero entero.
    secret, hint = LONG
    out += [
        GameMsg("start", start_data()),
        GameMsg("guess", guess_data(LONG_GUESSES, secret, hint)),
        Capture("wordle-10-reconexion", settle_s=3.0),
        GameMsg("end", {"result": "cancel"}),
        Wait(1.5),
    ]
    # Lo dejan con tres intentos hechos: la fila ya pintada NO se vuelve a voltear (la primera
    # captura va medio segundo después, cuando un volteo repetido se vería a medias).
    secret, hint = GIVE_UP
    words = GIVE_UP_GUESSES
    out += [GameMsg("start", start_data()), Wait(1.0)]
    for count in range(1, len(words) + 1):
        out += [GameMsg("guess", guess_data(words[:count], secret, hint)), Wait(2.2)]
    out += [
        GameMsg("guess", stopped_data(words, secret, hint)),
        Capture("wordle-11a-dejan-sin-volteo", settle_s=0.5),
        Capture("wordle-11b-dejan-palabra", settle_s=1.6),
        GameMsg("end", stopped_end(words, secret)),
        Capture("wordle-11c-dejan-final", settle_s=1.2),
        Wait(5.0),
    ]
    # Lo dejan sin haber probado ninguna palabra: no hay fila que enseñar, solo la palabra.
    secret, hint = GIVE_UP_NONE
    out += [
        GameMsg("start", start_data()),
        Wait(1.0),
        GameMsg("guess", stopped_data([], secret, hint)),
        Capture("wordle-12a-dejan-sin-intentos", settle_s=1.4),
        GameMsg("end", stopped_end([], secret)),
        Capture("wordle-12b-dejan-sin-intentos-final", settle_s=1.2),
        Wait(5.0),
    ]
    # Lo dejan justo cuando una pantalla se acaba de conectar: le llega el tablero entero (que no
    # había visto) ya con la palabra, sin voltear nada.
    secret, hint = GIVE_UP_REPLAY
    out += [
        GameMsg("start", start_data()),
        GameMsg("guess", stopped_data(GIVE_UP_REPLAY_GUESSES, secret, hint)),
        Capture("wordle-13-dejan-reconexion", settle_s=1.5),
        GameMsg("end", stopped_end(GIVE_UP_REPLAY_GUESSES, secret)),
        Wait(5.0),
    ]
    return out
