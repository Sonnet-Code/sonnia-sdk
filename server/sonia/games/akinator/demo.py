"""La secuencia del Akinator dev para el orquestador falso (``scripts/juegos_demo.py``).

Pasa por cada estado de la pantalla y pide una captura 9:16 en cada uno (``docs/juegos.md``,
«Probar la pantalla sin Sonia»; las capturas, en ``docs/juegos-unity.md``):

1. Una partida que Sonia gana: la tarjeta que pide pensar en algo, las preguntas con el
   contador (una corta, una larga y la última), Sonia pensando, su respuesta, un fallo, su
   segunda respuesta (con un nombre largo) y el acierto con confeti.
2. Una partida que Sonia pierde: las 20 preguntas, «me rindo» y «¡me ganaste!».
3. Una partida con otro máximo de preguntas, para comprobar que los puntos se reparten bien.

Los datos de cada evento salen de :func:`~sonia.games.akinator.game.screen_state`, la misma
función que usa el juego de verdad, así que la pantalla recibe exactamente lo mismo.
"""

from __future__ import annotations

from pathlib import Path

from sonia.config import Settings
from sonia.games.akinator.bank import THEMES, parse_themes, theme_names
from sonia.games.akinator.game import Phase, screen_state
from sonia.games.demo import Capture, GameMsg, Send, Step, Wait
from sonia.ws import protocol as p

TITLE = "Akinator dev"

LONG_QUESTION = (
    "¿Es una herramienta que usan los programadores para escribir código, que tiene "
    "extensiones y que no cuesta nada?"
)

FALLBACK_THEMES = [
    "Lenguajes de programación",
    "Herramientas y frameworks",
    "Empresas tecnológicas",
    "Productos de Google",
    "Inteligencia artificial",
    "Apps y redes sociales",
    "Dispositivos y videojuegos",
    "Personajes de la informática",
]


def _themes() -> list[str]:
    """Los temas del banco de la app (los que verá el visitante), o unos de respaldo."""
    try:
        path = Settings(_env_file=None).games_dir / "akinator" / THEMES.file  # type: ignore[call-arg]
        names = theme_names(parse_themes(Path(path).read_text(encoding="utf-8")).entries)
    except OSError:
        names = []
    return names or FALLBACK_THEMES


def _state(
    phase: Phase,
    asked: int,
    max_questions: int = 20,
    *,
    question: str = "",
    guess: str = "",
    missed: tuple[str, ...] = (),
    outcome: str = "",
    answer: str = "",
) -> dict[str, object]:
    return dict(
        screen_state(
            phase=phase,
            asked=asked,
            max_questions=max_questions,
            question=question,
            guess=guess,
            missed=missed,
            outcome=outcome,
            answer=answer,
        )
    )


def _start(max_questions: int = 20) -> list[Step]:
    return [
        GameMsg("start", {"title": TITLE, "max": max_questions, "themes": _themes()}),
        GameMsg("waiting", _state("waiting", 0, max_questions)),
    ]


def steps() -> list[Step]:
    """La secuencia completa (unos 90 s) con una captura por cada estado de la pantalla."""
    missed = ("Java",)
    return [
        # -- 1. Sonia gana -------------------------------------------------------------
        *_start(),
        Capture("akinator-01-empezar", settle_s=2.0),
        GameMsg("question", _state("asking", 1, question="¿Es un lenguaje de programación?")),
        Capture("akinator-02-pregunta-1", settle_s=1.2),
        GameMsg("question", _state("asking", 8, question=LONG_QUESTION)),
        Capture("akinator-03-pregunta-8-larga", settle_s=1.2),
        Send(p.msg_state("thinking")),
        Wait(2.5),
        Capture("akinator-04-pensando", settle_s=1.0),
        Capture("akinator-04b-pensando", settle_s=1.5),
        Send(p.msg_state("idle")),
        GameMsg("question", _state("asking", 18, question="¿Lo creó una empresa dominicana?")),
        Capture("akinator-05-pregunta-18", settle_s=1.2),
        GameMsg(
            "guess",
            _state("guessing", 18, question="¿Lo creó una empresa dominicana?", guess="Java"),
        ),
        Capture("akinator-06a-adivinanza-entrando", settle_s=0.3),
        Capture("akinator-06-adivinanza", settle_s=1.2),
        GameMsg(
            "miss",
            _state("asking", 18, question="¿Lo creó una empresa dominicana?", missed=missed),
        ),
        Capture("akinator-07-fallo", settle_s=0.8),
        GameMsg("question", _state("asking", 19, question="¿Es de Google?", missed=missed)),
        GameMsg(
            "guess",
            _state(
                "guessing",
                19,
                question="¿Es de Google?",
                guess="Visual Studio Code",
                missed=missed,
            ),
        ),
        Capture("akinator-08-adivinanza-larga", settle_s=1.2),
        GameMsg(
            "reveal",
            _state(
                "revealed",
                19,
                question="¿Es de Google?",
                missed=missed,
                outcome="sonnia",
                answer="Visual Studio Code",
            ),
        ),
        Capture("akinator-09-acierto", settle_s=1.0),
        Capture("akinator-09b-acierto-confeti", settle_s=1.5),
        Wait(2.0),
        GameMsg(
            "end",
            {
                "result": "win",
                "outcome": "sonnia",
                "answer": "Visual Studio Code",
                "asked": 19,
                "tries": 2,
            },
        ),
        Capture("akinator-10-cerrado", settle_s=2.5),
        # -- 2. Sonia pierde ---------------------------------------------------------------
        *_start(),
        GameMsg("question", _state("asking", 20, question="¿Se puede jugar con él?")),
        Capture("akinator-11-pregunta-20", settle_s=2.0),
        GameMsg("giveup", _state("giving_up", 20, question="¿Se puede jugar con él?")),
        Capture("akinator-12-me-rindo", settle_s=1.2),
        GameMsg(
            "reveal",
            _state(
                "revealed",
                20,
                question="¿Se puede jugar con él?",
                outcome="visitor",
                answer="Haskell",
            ),
        ),
        Capture("akinator-13-me-ganaste", settle_s=1.2),
        Capture("akinator-13b-me-ganaste", settle_s=1.5),
        Wait(1.5),
        GameMsg(
            "end",
            {"result": "lose", "outcome": "visitor", "answer": "Haskell", "asked": 20, "tries": 0},
        ),
        Capture("akinator-14-cerrado", settle_s=2.5),
        # -- 3. Otro máximo de preguntas ------------------------------------------------
        *_start(12),
        GameMsg("question", _state("asking", 5, 12, question="¿Es un producto de Google?")),
        Capture("akinator-15-maximo-12", settle_s=2.0),
        GameMsg("end", {"result": "cancel"}),
        Capture("akinator-16-cancelado", settle_s=2.0),
    ]
