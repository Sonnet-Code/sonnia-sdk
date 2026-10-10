"""La ruleta en el orquestador falso (``scripts/juegos_demo.py --juego ruleta``).

Pasa por cada estado de la pantalla y pide una captura 9:16 en cada uno: la ruleta
quieta, girando y parada; la tarjeta de cada reto con sus contadores, la pista y el
«¡Tiempo!»; y los resultados (acierto, fallo, nota con estrellas, predicción con su
barra y reto cumplido). Los datos salen de las mismas funciones que usa el juego
(``segment_data``, ``spin_data``, ``challenge_data`` y ``result_data``), así que la
pantalla se prueba con lo que manda de verdad. El contenido es de muestra.
"""

from __future__ import annotations

from dataclasses import replace

from sonia.games.demo import Capture, GameMsg, Step, Wait, WaitEvent
from sonia.games.ruleta.game import (
    FUTURE_PROMPT,
    SPIN_SECONDS,
    Round,
    RuletaGame,
    build_segments,
    challenge_data,
    result_data,
    segment_data,
    spin_data,
)

SEGMENTS = build_segments(20.0)

#: Tras ``wheel_stopped``, el destello de la casilla antes de la tarjeta del reto.
LANDED_S = 0.8


def _round(spin: int, kind_index: int, **fields: object) -> Round:
    return Round(spin, kind_index, SEGMENTS[kind_index].kind, **fields)  # type: ignore[arg-type]


def _spin_steps(round_: Round, wins: int, capture: str = "") -> list[Step]:
    """Gira hasta la casilla del reto y espera a que Unity diga que paró."""
    steps: list[Step] = [GameMsg("spin", spin_data(round_, wins))]
    if capture:
        steps += [Wait(1.4), Capture(capture, settle_s=0.0)]
    steps.append(WaitEvent("wheel_stopped", timeout=SPIN_SECONDS + 6.0))
    return steps


def _challenge(round_: Round, wins: int) -> GameMsg:
    return GameMsg("challenge", challenge_data(round_, SEGMENTS[round_.segment], wins))


def _result(round_: Round, wins: int) -> GameMsg:
    return GameMsg("result", result_data(round_, SEGMENTS[round_.segment], wins))


def steps() -> list[Step]:
    seq: list[Step] = [
        GameMsg(
            "start",
            {"title": RuletaGame.title, "segments": segment_data(SEGMENTS, range(len(SEGMENTS)))},
        ),
        Capture("ruleta-01-empezar", settle_s=1.5),
    ]

    # 1. Trivia relámpago: la ruleta girando y parada, la tarjeta, el contador y el acierto.
    quiz = _round(
        1,
        0,
        prompt="¿Quién organiza el DevFest Santo Domingo?",
        options=("Google, directamente", "GDG Santo Domingo", "La Biblioteca Nacional"),
        correct=1,
        timer_s=20.0,
    )
    seq += _spin_steps(quiz, 0, capture="ruleta-02-girando")
    seq += [
        Capture("ruleta-03-parada", settle_s=0.3),
        Wait(LANDED_S),
        _challenge(quiz, 0),
        Capture("ruleta-04-trivia", settle_s=1.2),
        _challenge(replace(quiz, timer_at=0.0), 0),
        Wait(3.0),
        Capture("ruleta-05-trivia-contador", settle_s=0.0),
        _result(replace(quiz, timer_at=0.0, outcome="win", chosen=1), 1),
        Capture("ruleta-06-trivia-acierto", settle_s=1.2),
        Wait(2.0),
    ]

    # 2. Adivinanza geek: la tarjeta, el primer fallo con la pista y el fallo final.
    riddle = _round(
        2,
        1,
        prompt=(
            "Tengo teclas pero no abro puertas, tengo espacio pero no soy un cuarto, y puedes "
            "entrar pero no salir. ¿Qué soy?"
        ),
        answer="el teclado",
        hint="Lo usas para escribir y tiene una tecla que se llama Enter.",
        tries=3,
    )
    seq += _spin_steps(riddle, 1)
    seq += [
        Wait(LANDED_S),
        _challenge(riddle, 1),
        Capture("ruleta-07-adivinanza", settle_s=1.2),
        _challenge(replace(riddle, misses=1, hint_shown=True), 1),
        Capture("ruleta-08-adivinanza-pista", settle_s=1.0),
        _result(replace(riddle, misses=3, hint_shown=True, outcome="lose"), 1),
        Capture("ruleta-09-adivinanza-fallo", settle_s=1.2),
        Wait(2.0),
    ]

    # 3. Explica en 20 segundos: la tecnología, el contador en marcha, «¡Tiempo!» y la nota.
    explain = _round(3, 2, prompt="Kubernetes", timer_s=20.0)
    seq += _spin_steps(explain, 1)
    seq += [
        Wait(LANDED_S),
        _challenge(explain, 1),
        Capture("ruleta-10-explica", settle_s=1.2),
        _challenge(replace(explain, timer_at=0.0), 1),
        Wait(4.0),
        Capture("ruleta-11-explica-contador", settle_s=0.0),
        _challenge(replace(explain, timer_at=0.0, time_up=True), 1),
        Capture("ruleta-12-explica-tiempo", settle_s=0.8),
        _result(replace(explain, timer_at=0.0, time_up=True, outcome="done", score=8), 2),
        Capture("ruleta-13-explica-nota", settle_s=2.0),
        Wait(1.5),
    ]

    # 4. Predice el futuro de la IA: la tarjeta y la predicción con su barra.
    future = _round(4, 3, prompt=FUTURE_PROMPT)
    seq += _spin_steps(future, 2)
    seq += [
        Wait(LANDED_S),
        _challenge(future, 2),
        Capture("ruleta-14-futuro", settle_s=1.2),
        _result(
            replace(
                future,
                outcome="done",
                prediction=(
                    "En 2030 cada estudiante tendrá un tutor de IA que le explica todo con "
                    "paciencia infinita"
                ),
                probability=73,
            ),
            2,
        ),
        Capture("ruleta-15-futuro-prediccion", settle_s=2.0),
        Wait(1.5),
    ]

    # 5. Reto sorpresa de Sonnet Code: un reto de stand, cumplido.
    sonnet = _round(
        5,
        4,
        prompt="Hazte una foto con Sonnia y súbela a tus redes etiquetando a @sonnetcode.",
        task=True,
    )
    seq += _spin_steps(sonnet, 2)
    seq += [
        Wait(LANDED_S),
        _challenge(sonnet, 2),
        Capture("ruleta-16-sonnet", settle_s=1.2),
        _result(replace(sonnet, outcome="win"), 3),
        Capture("ruleta-17-sonnet-cumplido", settle_s=1.2),
        Wait(2.0),
    ]

    # 6. Otra trivia relámpago, fallada: la elegida en rojo y la buena en verde.
    quiz2 = _round(
        6,
        0,
        prompt="¿Cuántos días dura el DevFest Santo Domingo 2026?",
        options=("Un día", "Dos días", "Una semana"),
        correct=1,
        timer_s=20.0,
    )
    seq += _spin_steps(quiz2, 3)
    seq += [
        Wait(LANDED_S),
        _challenge(replace(quiz2, timer_at=0.0), 3),
        Wait(1.0),
        _result(replace(quiz2, timer_at=0.0, outcome="lose", chosen=0), 3),
        Capture("ruleta-18-trivia-fallo", settle_s=1.2),
        Wait(1.5),
        # 7. Terminar («stop_game»): la pantalla se retira.
        GameMsg("end", {"result": "cancel"}),
        Capture("ruleta-19-final", settle_s=1.5),
    ]
    return seq
