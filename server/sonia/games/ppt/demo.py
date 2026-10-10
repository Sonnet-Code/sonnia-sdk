"""La secuencia de piedra, papel o tijera para el orquestador falso (``scripts/juegos_demo.py``).

Pasa por cada estado de la pantalla con una captura en cada uno: empezar (con la vista
en vivo y el jugador resaltado), la cuenta (Sonnia agitando el puño), el «¡ya!» (su mano
fuera), una ronda ganada por el visitante, una ganada por Sonnia, una sin mano que se
repite y el final. La vista en vivo es sintética, con las marcas que pinta el juego
(:mod:`sonia.games.ppt.overlay`): nunca la cámara de nadie.

La primera ronda va fotograma a fotograma para revisar la mano de Sonnia: el puño arriba,
la cuenta, el «¡ya!» y 0,5, 1 y 3 s después, con el juez tardando 1,9 s y Sonnia hablando
en el resultado (voz sintética y un gesto al hablar del catálogo), que no tiene que mover
la mano hasta que baja sola.

    uv run --no-sync python ../scripts/juegos_demo.py --juego piedra_papel_tijera --puerto 8795
"""

from __future__ import annotations

from typing import Any

import numpy as np

from sonia.busy import TEXT_HAND
from sonia.games.demo import Audio, Capture, GameMsg, Preview, Send, Step, Wait
from sonia.games.ppt.overlay import OverlayState, draw_state
from sonia.ws import protocol as p

__all__ = ["steps"]

ROUNDS = 3
TARGET = 2
#: Del principio de la frase grabada al «¡ya!» en la demo (una grabación típica).
GO_S = 1.8
#: La tasa del ``hello`` del orquestador falso (``scripts/juegos_demo.py``).
SAMPLE_RATE = 24_000
#: Lo que dice el visitante con la cuenta: larga, para ver que su pastilla no tapa la mano.
SAID = "Piedra, papel o tijera… ¡una, dos y tres, piedra!"

#: Como el motor de verdad: Sonia escucha antes de cada tirada y habla para reaccionar al
#: resultado (sin esto, Sonnia se quedaría en reposo y haría gestos de llamar la atención).
LISTENING = Send(p.msg_state("listening"))
SPEAKING = Send(p.msg_state("speaking"))

#: Lo que pinta el juego en la vista en vivo: el jugador y, en la lectura, su mano.
WITH_HAND = OverlayState(
    player=(0.33, 0.12, 0.34, 0.86), hand=(0.44, 0.42, 0.1, 0.17), hand_ok=True
)


def _voice(utterance_id: int, seconds: float) -> Audio:
    """Voz sintética de ``seconds``: un tono con armónicos y sílabas a 4 Hz, en trozos de 100 ms."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    tone = sum(np.sin(2 * np.pi * 170 * k * t) / k for k in range(1, 8))
    syllables = 0.5 - 0.5 * np.cos(2 * np.pi * 4 * t)
    pcm = (tone * syllables * 6000).astype("<i2").tobytes()
    chunk = SAMPLE_RATE // 10 * 2
    frames = [
        p.encode_audio_frame(utterance_id, pcm[i : i + chunk], False)
        for i in range(0, len(pcm), chunk)
    ]
    frames.append(p.encode_audio_frame(utterance_id, b"", True))
    return Audio(tuple(frames))


def _talk(utterance_id: int, text: str, gesture: str, seconds: float) -> list[Step]:
    """Sonia habla ``seconds`` con un gesto al hablar (``gesture``, del catálogo de Sage)."""
    return [
        SPEAKING,
        Send(p.msg_gesture(gesture, None)),
        Send(p.msg_speech_start(utterance_id, text)),
        _voice(utterance_id, seconds),
        Send(p.msg_speech_end(utterance_id)),
    ]


def _count_voice(utterance_id: int) -> list[Step]:
    """La frase de la cuenta con voz (sintética) y subtítulo, y el visitante repitiéndola.

    Con los dos subtítulos a la vez, la pastilla del visitante sube: es el caso más justo para
    el puño en lo más bajo de cada golpe. La voz es también el reloj de la cuenta en Unity.
    """
    phrase = "¡Piedra, papel o tijera… ya!"
    return [
        Send(p.msg_speech_start(utterance_id, phrase)),
        _voice(utterance_id, GO_S + 0.4),
        Send(p.msg_speech_end(utterance_id)),
        Send(p.msg_transcript("assistant", phrase, False)),
        Send(p.msg_transcript("user", SAID, False)),
    ]


def _draw(image: np.ndarray, mirrored: bool) -> None:
    draw_state(image, WITH_HAND, mirrored)


def _score(sonnia: int, player: int) -> dict[str, int]:
    return {"sonnia": sonnia, "player": player}


def _base(number: int, sonnia: int, player: int) -> dict[str, Any]:
    return {"round": number, "rounds": ROUNDS, "target": TARGET, "score": _score(sonnia, player)}


def _throw(number: int, move: str, sonnia: int, player: int, *, retry: bool = False) -> list[Step]:
    """Una tirada hasta el «¡ya!»: ``round``, ``ready``, ``countdown`` y ``go``."""
    return [
        LISTENING,
        GameMsg("round", {**_base(number, sonnia, player), "retry": retry}),
        GameMsg("ready", {"round": number}),
        Wait(0.8),
        GameMsg("countdown", {"round": number, "sonnia": move, "go_s": GO_S, "beats": 3}),
    ]


def _result(
    number: int,
    move: str,
    shown: str | None,
    winner: str,
    sonnia: int,
    player: int,
    *,
    reason: str = "",
    retry: bool = False,
) -> GameMsg:
    return GameMsg(
        "result",
        {
            **_base(number, sonnia, player),
            "sonnia": move,
            "player": shown,
            "winner": winner,
            "reason": reason,
            "retry": retry,
        },
    )


def steps() -> list[Step]:
    return [
        GameMsg("start", {"title": "Piedra, papel o tijera", **_base(1, 0, 0)}),
        Preview(100.0, draw=_draw, off=True),
        Capture("ppt-1-empezar", settle_s=2.0),
        # Ronda 1, fotograma a fotograma (cada captura deja 0,5 s detrás; los tiempos, desde
        # el countdown): el puño arriba, la cuenta, el «¡ya!» con la tijera a 1,8 s, el juez
        # que tarda 1,9 s y gana el visitante, con Sonia hablando y gesticulando.
        LISTENING,
        GameMsg("round", {**_base(1, 0, 0), "retry": False}),
        GameMsg("ready", {"round": 1}),
        Capture("ppt-2a-puno-arriba", settle_s=0.6),
        GameMsg("countdown", {"round": 1, "sonnia": "tijera", "go_s": GO_S, "beats": 3}),
        Capture("ppt-2b-cuenta", settle_s=0.25),  # 0,25 s
        Capture("ppt-2c-cuenta", settle_s=0.0),  # 0,75 s
        Capture("ppt-2d-cuenta", settle_s=0.0),  # 1,25 s
        GameMsg("go", {"round": 1, "sonnia": "tijera"}),  # 1,75 s
        Send(p.msg_transcript("user", SAID, False)),
        Capture("ppt-3a-ya-tijera", settle_s=0.15),  # 1,9 s: el «¡ya!»
        Send(p.msg_busy(True, "judge", TEXT_HAND)),  # juzga Gemini
        Capture("ppt-3b-ya-0.5s", settle_s=0.0),  # «¡ya!» + 0,5 s
        Capture("ppt-3c-ya-1s", settle_s=0.0),  # «¡ya!» + 1 s
        Wait(0.3),
        Send(p.msg_busy(False)),
        Send(p.msg_transcript("user", SAID, True)),
        _result(1, "tijera", "piedra", "player", 0, 1),  # «¡ya!» + 1,9 s
        *_talk(101, "¡Me ganaste con piedra! Muy bien.", "openClarify", 4.5),
        Capture("ppt-3d-ya-3s-hablando", settle_s=1.1),  # «¡ya!» + 3 s
        Capture("ppt-4-acierto", settle_s=0.35),  # resultado + 2 s
        Capture("ppt-4b-bajando", settle_s=0.0),  # resultado + 2,5 s: ya baja
        Capture("ppt-4c-bajada-hablando", settle_s=0.6),  # gestos de vuelta
        Wait(1.0),
        # Ronda 2: el papel de Sonnia y gana ella, otra vez hablando con un gesto. La cuenta va
        # con la voz de la frase y los dos subtítulos (el puño, por encima de la pastilla «TÚ»).
        *_throw(2, "papel", 0, 1),
        *_count_voice(201),
        Capture("ppt-5-cuenta-con-voz-a", settle_s=0.9),
        Capture("ppt-5-cuenta-con-voz-b", settle_s=0.2),
        GameMsg("go", {"round": 2, "sonnia": "papel"}),
        Capture("ppt-5a-ya-papel", settle_s=0.2),
        Wait(0.5),
        _result(2, "papel", "piedra", "sonnia", 1, 1),
        *_talk(102, "¡Te gané! Papel envuelve piedra.", "emphasizeShort", 3.0),
        Capture("ppt-5-fallo", settle_s=1.2),
        Wait(1.5),
        # Ronda 3: la piedra de Sonnia; no se ve la mano del visitante y se repite.
        *_throw(3, "piedra", 1, 1),
        Wait(GO_S + 0.15),
        GameMsg("go", {"round": 3, "sonnia": "piedra"}),
        Capture("ppt-6a-ya-piedra", settle_s=0.4),
        Wait(0.5),
        _result(3, "piedra", None, "none", 1, 1, reason="no_hand", retry=True),
        SPEAKING,
        Capture("ppt-6-sin-mano", settle_s=1.2),
        Wait(1.5),
        # La repetición: gana el visitante y con eso la partida.
        *_throw(3, "piedra", 1, 1, retry=True),
        Wait(GO_S + 0.15),
        GameMsg("go", {"round": 3, "sonnia": "piedra"}),
        Wait(1.0),
        _result(3, "piedra", "papel", "player", 1, 2),
        GameMsg(
            "final",
            {
                "winner": "player",
                "score": _score(1, 2),
                "rounds": ROUNDS,
                "target": TARGET,
                "sonnia": "piedra",
                "player": "papel",
                "contact": "Brian o Mariel",
            },
        ),
        Capture("ppt-7-final", settle_s=3.0),
        GameMsg("end", {"result": "win", "winner": "player", "score": _score(1, 2)}),
        Wait(1.5),
    ]
