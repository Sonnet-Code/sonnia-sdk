"""Piedra, papel o tijera (``sonia/games/ppt``) sin red, sin cámara y sin Unity.

1. Lo que decide el juego, con personas y manos inventadas: quién juega (y si otra
   persona se pone delante), qué mano cuenta (la levantada; dos manos), la lectura
   estable (estable, cambiante, sin mano, cambio tardío), quién gana y el «¡ya!» de la
   frase grabada.
2. Partidas enteras con ``FakeGameHost``: ganar, perder, empates, sin mano (repetir y
   ronda nula), la cuenta que no suena, el «¡ya!» medido y el de la transcripción, sin
   nadie delante y parar a media partida.
3. De punta a punta con ``GameManager`` y las acciones que delega GPT-Live.
"""

from __future__ import annotations

import asyncio
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sonia.actions import build_default_registry
from sonia.games import SCRIPT_PREFIX, GameError
from sonia.games.base import INSTRUCT_MAX_CHARS
from sonia.games.demo import Capture, GameMsg, load_demo
from sonia.games.ppt import game as ppt_game
from sonia.games.ppt.game import (
    AUDIO_LAG_S,
    CANT_SEE_TEXT,
    GO_TIMEOUT_S,
    HINT_NO_PLAYER,
    NO_PLAYER_CANCEL_TEXT,
    NO_PLAYER_TEXT,
    PHRASE,
    RETRY_NO_HAND,
    RETRY_UNCLEAR,
    PptGame,
    phrase_go_seconds,
)
from sonia.games.ppt.logic import (
    NO_HAND,
    contradicted,
    pick_player,
    read_sample,
    says_ya,
    settle,
    winner_of,
    ya_onset,
)
from sonia.games.ppt.overlay import GREEN, RED, YELLOW, OverlayState, draw_state
from sonia.types import ActionContext
from sonia.vision.contracts import (
    L_HIP,
    L_SHOULDER,
    NOSE,
    R_HIP,
    R_SHOULDER,
    HandReading,
    HandShape,
    Person,
    PoseFrame,
)
from sonia.ws import protocol as p
from tests.games.fakes import (
    FakeGameHost,
    FakeHands,
    FakePoses,
    FakeVision,
    brands_in,
    game_settings,
    make_manager,
    person,
    pose_frame,
)

ROCK, PAPER, SCISSORS, UNKNOWN = (
    HandShape.ROCK,
    HandShape.PAPER,
    HandShape.SCISSORS,
    HandShape.UNKNOWN,
)

#: La jugada que gana a cada una y la que pierde.
BEATS_IT = {ROCK: PAPER, PAPER: SCISSORS, SCISSORS: ROCK}
LOSES_TO = {ROCK: SCISSORS, PAPER: ROCK, SCISSORS: PAPER}


@pytest.fixture(autouse=True)
def _sin_frase_grabada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Por defecto la frase no está medida: el «¡ya!» sale de la transcripción o del tope.

    (Sin esto se leería la caché de voces de verdad del equipo, si la hubiera.)
    """
    monkeypatch.setattr(ppt_game, "phrase_go_seconds", lambda settings: None)


# ---------------------------------------------------------------------------
# Personas y manos inventadas
# ---------------------------------------------------------------------------


def body(
    cx: float = 0.5,
    width: float = 0.3,
    top: float = 0.1,
    height: float = 0.85,
    *,
    score: float = 0.9,
    hips: bool = True,
) -> Person:
    """Una persona de pie: caja, nariz, hombros y (si ``hips``) caderas a media altura."""
    points = {
        NOSE: (cx, top + 0.05),
        L_SHOULDER: (cx + width * 0.3, top + 0.2),
        R_SHOULDER: (cx - width * 0.3, top + 0.2),
    }
    if hips:
        points[L_HIP] = (cx + 0.06, top + 0.55)
        points[R_HIP] = (cx - 0.06, top + 0.55)
    return person(points, box=(cx - width / 2, top, width, height), score=score)


def hand(
    shape: HandShape, *, y: float = 0.4, x: float = 0.5, side: str = "derecha", size: float = 0.1
) -> HandReading:
    """Una mano leída con su centro en ``(x, y)``."""
    return HandReading(
        side="derecha" if side == "derecha" else "izquierda",
        shape=shape,
        score=0.9,
        box=(x - size / 2, y - size / 2, size, size),
    )


class PlayerHands(FakeHands):
    """Manos que contestan según la partida (``plan(juego)``) y apuntan a quién se leyó."""

    def __init__(self, plan: Callable[[PptGame], list[HandReading]]) -> None:
        super().__init__()
        self.plan = plan
        self.game: Callable[[], PptGame | None] = lambda: None
        self.persons: list[Person] = []

    async def read(self, frame_bgr: np.ndarray, person: Person) -> list[HandReading]:
        self.reads += 1
        self.persons.append(person)
        game = self.game()
        assert game is not None, "lectura sin partida"
        return self.plan(game)


class PlanPoses(FakePoses):
    """Poses según la partida (``plan(juego)``): para cambiar de gente entre tiradas."""

    def __init__(self, plan: Callable[[PptGame], PoseFrame]) -> None:
        super().__init__()
        self.plan = plan
        self.game: Callable[[], PptGame | None] = lambda: None

    def _frame(self) -> PoseFrame | None:
        game = self.game()
        return self.plan(game) if game is not None else None

    def latest(self, max_age_s: float = 0.5) -> PoseFrame | None:
        return self._frame()

    async def detect(self, frame_bgr: np.ndarray, at: float) -> PoseFrame:
        return self._frame() or pose_frame()


def wins(game: PptGame) -> list[HandReading]:
    """El jugador saca lo que gana a Sonia."""
    assert game.move is not None
    return [hand(BEATS_IT[game.move])]


def loses(game: PptGame) -> list[HandReading]:
    assert game.move is not None
    return [hand(LOSES_TO[game.move])]


def by_throw(
    *plans: Callable[[PptGame], list[HandReading]],
) -> Callable[[PptGame], list[HandReading]]:
    """Un plan por tirada (la última se repite)."""

    def plan(game: PptGame) -> list[HandReading]:
        return plans[min(game.throws, len(plans) - 1)](game)

    return plan


def tie(game: PptGame) -> list[HandReading]:
    assert game.move is not None
    return [hand(game.move)]


def nothing(game: PptGame) -> list[HandReading]:
    return []


def make_ppt(
    plan: Callable[[PptGame], list[HandReading]],
    *,
    poses: FakePoses | None = None,
    host_cls: type[FakeGameHost] = FakeGameHost,
    **kwargs: Any,
) -> tuple[PptGame, FakeGameHost, PlayerHands]:
    hands = PlayerHands(plan)
    vision = FakeVision(poses=poses or FakePoses([pose_frame(body())]), hands=hands)
    host = host_cls(PptGame.id, vision=vision, **kwargs)
    game = PptGame(host)
    hands.game = lambda: game
    if isinstance(poses, PlanPoses):
        poses.game = lambda: game
    return game, host, hands


async def play(game: PptGame, host: FakeGameHost) -> str:
    script = await game.start("voice", {})
    await host.run_tasks()
    return script


def events(host: FakeGameHost) -> list[str]:
    return [m["event"] for m in host.sent]


# ---------------------------------------------------------------------------
# 1. Lo que decide el juego
# ---------------------------------------------------------------------------


def test_juega_la_persona_mas_grande_y_centrada() -> None:
    small_left = body(cx=0.15, width=0.12, height=0.4)
    big_center = body(cx=0.5, width=0.3, height=0.85)
    medium_right = body(cx=0.85, width=0.2, height=0.6)
    chosen = pick_player(pose_frame(small_left, big_center, medium_right))
    assert chosen is big_center


def test_centrada_gana_a_una_algo_mas_grande_en_el_borde() -> None:
    center = body(cx=0.5, width=0.25, height=0.8)  # área 0,2
    edge = body(cx=0.88, width=0.24, height=0.95)  # área 0,23, casi en el borde
    assert pick_player(pose_frame(edge, center)) is center


def test_no_cuentan_las_dudosas_ni_las_lejanas() -> None:
    weak = body(score=0.2)
    tiny = body(width=0.05, height=0.1)
    assert pick_player(pose_frame(weak, tiny)) is None
    assert pick_player(pose_frame()) is None
    assert pick_player(None) is None
    ok = body(cx=0.3, width=0.15, height=0.5)
    assert pick_player(pose_frame(weak, tiny, ok)) is ok


def test_sigue_con_el_mismo_jugador_si_otro_es_parecido() -> None:
    player = body(cx=0.45, width=0.3, height=0.8)
    other = body(cx=0.55, width=0.3, height=0.95)  # algo más grande y centrada
    assert pick_player(pose_frame(player, other)) is other
    # Con el jugador de antes, se sigue con él: no salta entre dos parecidos.
    assert pick_player(pose_frame(player, other), previous=player.box) is player


def test_otra_persona_delante_pasa_a_jugar() -> None:
    player = body(cx=0.5, width=0.2, height=0.6)
    closer = body(cx=0.48, width=0.45, height=0.95)  # mucho más grande: está delante
    assert pick_player(pose_frame(player, closer), previous=player.box) is closer


def test_cuenta_la_mano_levantada_no_la_que_cuelga() -> None:
    player = body()  # caderas a 0,65
    raised = hand(SCISSORS, y=0.4)
    hanging = hand(ROCK, y=0.8, x=0.3, side="izquierda")
    sample = read_sample([hanging, raised], player)
    assert sample.shape is SCISSORS and sample.seen and sample.box == raised.box
    # Solo la que cuelga: no está enseñando nada.
    assert read_sample([hanging], player) == NO_HAND
    assert read_sample([], player) == NO_HAND


def test_dos_manos_a_la_vez_con_jugadas_distintas_no_valen() -> None:
    player = body()
    left = hand(PAPER, y=0.4, x=0.4, side="izquierda")
    right = hand(SCISSORS, y=0.42, x=0.6)
    sample = read_sample([left, right], player)
    assert sample.shape is None and sample.seen
    # Las dos con la misma jugada: vale.
    assert read_sample([left, hand(PAPER, y=0.42, x=0.6)], player).shape is PAPER
    # Una a la vista que no se entiende y la otra sí, a la misma altura: vale la otra.
    blurry = hand(UNKNOWN, y=0.39, x=0.6)
    assert read_sample([blurry, left], player).shape is PAPER


def test_de_dos_manos_levantadas_cuenta_la_mas_alta() -> None:
    player = body()
    high = hand(ROCK, y=0.3)
    lower = hand(PAPER, y=0.5, x=0.35, side="izquierda")
    assert read_sample([lower, high], player).shape is ROCK


def test_mano_que_no_se_entiende_y_sin_caderas() -> None:
    player = body(hips=False)
    sample = read_sample([hand(UNKNOWN, y=0.85)], player)
    # Sin caderas a la vista (muy cerca), toda mano cuenta como levantada.
    assert sample.shape is None and sample.seen
    assert read_sample([hand(PAPER, y=0.9)], player).shape is PAPER
    # Una caja vacía no es una mano.
    empty = HandReading(side="derecha", shape=ROCK, score=0.9, box=(0.5, 0.5, 0.0, 0.0))
    assert read_sample([empty], player) == NO_HAND


def test_lectura_estable() -> None:
    assert settle([PAPER, PAPER, PAPER, PAPER]) is PAPER
    # Una sola lectura (o varias iguales con huecos) también vale.
    assert settle([None, SCISSORS, None]) is SCISSORS
    assert settle([PAPER, None, PAPER, None]) is PAPER


def test_lectura_cambiante_no_vale() -> None:
    assert settle([PAPER, SCISSORS, PAPER, SCISSORS]) is None
    assert settle([ROCK, PAPER]) is None


def test_lectura_sin_mano() -> None:
    assert settle([None, None, None]) is None
    assert settle([]) is None


def test_el_puno_de_la_cuenta_no_tapa_la_jugada_que_viene_despues() -> None:
    # Agitaba el puño (piedra) y abrió la mano: manda el último tramo estable.
    assert settle([ROCK, ROCK, ROCK, PAPER, PAPER]) is PAPER
    # Si aún solo hay una lectura de papel, la estable es la piedra... pero la
    # contradice la última: el juego alarga la lectura.
    shapes = [ROCK, ROCK, ROCK, PAPER]
    assert settle(shapes) is ROCK and contradicted(shapes, ROCK)
    assert not contradicted([ROCK, ROCK, None], ROCK)
    assert not contradicted([], ROCK) and not contradicted([PAPER], None)


@pytest.mark.parametrize(
    ("sonnia", "player", "expected"),
    [
        (ROCK, ROCK, "tie"),
        (ROCK, PAPER, "player"),
        (ROCK, SCISSORS, "sonnia"),
        (PAPER, ROCK, "sonnia"),
        (PAPER, PAPER, "tie"),
        (PAPER, SCISSORS, "player"),
        (SCISSORS, ROCK, "player"),
        (SCISSORS, PAPER, "sonnia"),
        (SCISSORS, SCISSORS, "tie"),
    ],
)
def test_quien_gana(sonnia: HandShape, player: HandShape, expected: str) -> None:
    assert winner_of(sonnia, player) == expected


def test_el_ya_de_la_transcripcion_de_sonia() -> None:
    assert says_ya("¡Piedra, papel o tijera… ya!")
    assert says_ya("piedra papel o tijeras... ¡YA!")
    assert says_ya("¡Ya!")
    assert not says_ya("¡Piedra, papel o tijera…")
    assert not says_ya("Ya está, piedra, papel o tijera")
    assert not says_ya("")


SR = 24_000


def _tone(seconds: float, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return amplitude * np.sin(2 * np.pi * 220 * t)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SR * seconds))


def _pcm(*parts: np.ndarray) -> bytes:
    audio = np.concatenate(parts)
    return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()


def _phrase(with_click: bool = False) -> bytes:
    parts = [
        _silence(0.05),
        _tone(0.4),  # piedra
        _silence(0.1),
        _tone(0.4),  # papel
        _silence(0.1),
        _tone(0.5),  # o tijera
        _silence(0.3),  # …
        _tone(0.35),  # ¡ya!
        _silence(0.3),
    ]
    if with_click:
        parts += [_tone(0.02), _silence(0.1)]
    return _pcm(*parts)


def test_el_ya_de_la_frase_grabada() -> None:
    onset = ya_onset(_phrase(), SR)
    assert onset == pytest.approx(1.85, abs=0.03)
    # Un clic suelto al final no es una palabra.
    assert ya_onset(_phrase(with_click=True), SR) == pytest.approx(1.85, abs=0.03)


def test_el_ya_pegado_a_tijera_y_sin_voz() -> None:
    glued = _pcm(_silence(0.05), _tone(0.4), _silence(0.1), _tone(1.3), _silence(0.3))
    # Último tramo de 1,3 s: el «ya» son sus últimos 0,45 s.
    assert ya_onset(glued, SR) == pytest.approx(0.55 + 1.3 - 0.45, abs=0.03)
    assert ya_onset(_pcm(_silence(1.0)), SR) is None
    assert ya_onset(b"", SR) is None
    assert ya_onset(_phrase(), 0) is None


def test_mide_la_frase_en_la_cache_de_voces(tmp_path: Path) -> None:
    from sonia.live.voicecache import VoiceCache

    settings = game_settings()
    settings = settings.model_copy(
        update={"panel": settings.panel.model_copy(update={"voice_cache_dir": str(tmp_path)})}
    )
    # Sin grabación, no se sabe.
    assert phrase_go_seconds(settings) is None
    path = VoiceCache(tmp_path, settings.live).path_for(PHRASE)
    path.parent.mkdir(parents=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(settings.live.sample_rate)
        wav.writeframes(_phrase() if settings.live.sample_rate == SR else b"")
    assert phrase_go_seconds(settings) == pytest.approx(1.85, abs=0.03)


def test_la_vista_en_vivo_resalta_al_jugador_y_su_mano() -> None:
    image = np.zeros((360, 640, 3), dtype=np.uint8)
    state = OverlayState(player=(0.1, 0.1, 0.3, 0.8), hand=(0.6, 0.4, 0.1, 0.2), hand_ok=True)
    draw_state(image, state, mirrored=False)
    assert tuple(image[36, 64]) == YELLOW  # esquina de arriba a la izquierda del jugador
    assert tuple(image[144, 384]) == GREEN  # esquina de la caja de la mano
    assert not image[180, 160].any()  # el centro del jugador no se toca
    # En espejo, la esquina pasa al otro lado (x → 1 - x).
    mirrored = np.zeros_like(image)
    draw_state(mirrored, state, mirrored=True)
    assert tuple(mirrored[36, 640 - 64 - 192]) == YELLOW
    assert not mirrored[36, 64].any()
    red = np.zeros_like(image)
    draw_state(red, OverlayState(hand=(0.6, 0.4, 0.1, 0.2)), mirrored=False)
    assert tuple(red[144, 384]) == RED
    # Cajas fuera de la imagen no rompen nada.
    draw_state(red, OverlayState(player=(1.2, 1.3, 0.2, 0.2), hand=(-0.5, 0.0, 0.1, 0.1)), False)


# ---------------------------------------------------------------------------
# 2. Partidas enteras con FakeGameHost
# ---------------------------------------------------------------------------


async def test_el_jugador_gana_la_partida() -> None:
    game, host, hands = make_ppt(wins)
    script = await play(game, host)
    assert "mejor de 3" in script and "«¡ya!»" in script
    # Reglas por instruct, dentro del tope y sin marcas (FakeGameHost lo comprueba).
    assert host.instructions == [game.rules()]
    assert len(game.rules()) <= INSTRUCT_MAX_CHARS
    # La cámara, las poses y la vista en vivo a su nombre.
    assert host.stream.owners == {PptGame.id}
    assert PptGame.id in host.poses.owners
    assert host.preview.starts == [(PptGame.id, True)]
    # Dos tiradas, dos frases grabadas y gana el jugador.
    assert host.fixed == [(PHRASE, False), (PHRASE, False)]
    assert host.finished == [("win", {"winner": "player", "score": {"sonnia": 0, "player": 2}})]
    assert events(host) == [
        "start",
        *(["round", "ready", "countdown", "go", "result"] * 2),
        "final",
    ]
    start = host.last("start")
    assert start == {"round": 1, "rounds": 3, "target": 2, "score": {"sonnia": 0, "player": 0}}
    countdown = host.events("countdown")[0]
    assert countdown["sonnia"] in ("piedra", "papel", "tijera")
    assert countdown["go_s"] is None and countdown["beats"] == 3
    first = host.events("result")[0]
    assert first["winner"] == "player" and first["round"] == 1 and not first["retry"]
    assert first["score"] == {"sonnia": 0, "player": 1}
    assert first["sonnia"] == countdown["sonnia"]
    assert first["player"] == BEATS_IT[HandShape(countdown["sonnia"])].value
    final = host.last("final")
    assert final["winner"] == "player" and final["contact"] == "Brian o Mariel"
    assert final["score"] == {"sonnia": 0, "player": 2}
    # Sonia reacciona a cada ronda y, al final, manda al ganador con el equipo del stand.
    assert "gana el jugador" in host.spoken[0] and "Marcador: Sonia 0, jugador 1" in host.spoken[0]
    assert "GANA LA PARTIDA 2 a 0" in host.spoken[-1] and "Brian o Mariel" in host.spoken[-1]
    # Se sigue al jugador para que la partida no se dé por abandonada.
    assert host.touches > 0
    assert hands.reads >= 4


async def test_sonia_gana_la_partida() -> None:
    game, host, _ = make_ppt(loses, seed=5)
    await play(game, host)
    assert host.finished == [("lose", {"winner": "sonnia", "score": {"sonnia": 2, "player": 0}})]
    assert "ganas tú" in host.spoken[0]
    assert "GANAS TÚ LA PARTIDA 2 a 0" in host.spoken[-1]
    assert "Brian o Mariel" not in host.spoken[-1]
    assert host.last("final")["winner"] == "sonnia"


async def test_un_empate_se_repite_sin_contar() -> None:
    game, host, _ = make_ppt(by_throw(tie, wins, loses, wins))
    await play(game, host)
    results = host.events("result")
    assert [r["winner"] for r in results] == ["tie", "player", "sonnia", "player"]
    assert [r["round"] for r in results] == [1, 1, 2, 3]
    assert results[0]["score"] == {"sonnia": 0, "player": 0}
    # La ronda del empate se repite (round con retry) y no cuenta.
    rounds = host.events("round")
    assert [(r["round"], r["retry"]) for r in rounds] == [
        (1, False),
        (1, True),
        (2, False),
        (3, False),
    ]
    assert "empate" in host.spoken[0] and "se repite" in host.spoken[0]
    assert host.finished[0][0] == "win"


async def test_sin_mano_se_repite_una_vez_y_luego_no_cuenta() -> None:
    game, host, _ = make_ppt(by_throw(nothing, nothing, wins, wins))
    await play(game, host)
    results = host.events("result")
    assert [(r["round"], r["winner"], r["reason"], r["retry"]) for r in results] == [
        (1, "none", "no_hand", True),
        (1, "none", "no_hand", False),
        (2, "player", "", False),
        (3, "player", "", False),
    ]
    assert results[0]["player"] is None
    assert host.spoken[0] == RETRY_NO_HAND
    assert "no cuenta" in host.spoken[1]
    assert host.finished == [("win", {"winner": "player", "score": {"sonnia": 0, "player": 2}})]


async def test_mano_que_no_se_entiende() -> None:
    def blurry(game: PptGame) -> list[HandReading]:
        return [hand(UNKNOWN)]

    game, host, _ = make_ppt(by_throw(blurry, wins, wins))
    await play(game, host)
    first = host.events("result")[0]
    assert first["winner"] == "none" and first["reason"] == "unclear" and first["retry"]
    assert host.spoken[0] == RETRY_UNCLEAR


async def test_lectura_cambiante_es_que_no_se_entiende() -> None:
    def flicker(game: PptGame) -> list[HandReading]:
        return [hand(PAPER if hands.reads % 2 else SCISSORS)]

    game, host, hands = make_ppt(by_throw(flicker, wins, wins))
    await play(game, host)
    first = host.events("result")[0]
    assert first["reason"] == "unclear" and first["retry"]
    # Se alargó la lectura buscando una jugada estable.
    assert game.throws == 3


async def test_dos_rondas_seguidas_sin_mano_cancelan() -> None:
    game, host, _ = make_ppt(nothing)
    await play(game, host)
    assert [r["retry"] for r in host.events("result")] == [True, False, True, False]
    assert host.spoken[-1] == CANT_SEE_TEXT
    assert host.finished == [("cancel", {"score": {"sonnia": 0, "player": 0}, "reason": "no_hand"})]
    assert "final" not in events(host)


async def test_si_la_cuenta_no_suena_se_retira_el_puno_y_se_repite() -> None:
    class Flaky(FakeGameHost):
        fails = 1

        async def say_fixed(self, text: str) -> bool:
            await super().say_fixed(text)
            if self.fails > 0:
                self.fails -= 1
                return False
            return True

    game, host, _ = make_ppt(wins, host_cls=Flaky)
    await play(game, host)
    assert events(host)[:6] == ["start", "round", "ready", "countdown", "abort", "round"]
    assert host.events("abort") == [{"round": 1}]
    assert host.finished[0][0] == "win"
    assert len(host.fixed) == 3


async def test_si_la_cuenta_nunca_suena_se_deja() -> None:
    game, host, _ = make_ppt(wins, connected=False)
    await play(game, host)
    assert len(host.events("abort")) == ppt_game.MAX_SAY_FAILURES
    assert host.finished == [
        ("cancel", {"score": {"sonnia": 0, "player": 0}, "reason": "countdown"})
    ]


class TimedHost(FakeGameHost):
    """Apunta en cada mensaje la hora del reloj del juego."""

    async def send(
        self, event: str, data: dict[str, Any] | None = None, *, sticky: bool = True
    ) -> None:
        await super().send(event, data, sticky=sticky)
        self.sent[-1]["at"] = self.now()

    def at(self, event: str, index: int = 0) -> float:
        return float([m for m in self.sent if m["event"] == event][index]["at"])


async def test_el_ya_cae_donde_dice_la_frase_grabada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ppt_game, "phrase_go_seconds", lambda settings: 1.5)
    game, host, _ = make_ppt(wins, host_cls=TimedHost, recorded=[PHRASE])
    await play(game, host)
    assert isinstance(host, TimedHost)
    assert host.events("countdown")[0]["go_s"] == 1.5
    assert host.at("go") - host.at("countdown") == pytest.approx(1.5 + AUDIO_LAG_S, abs=0.01)
    assert host.fixed[0] == (PHRASE, True)
    # La lectura empieza tras el «ya» y el resultado llega poco después.
    assert 0.8 < host.at("result") - host.at("go") < 2.5


async def test_sin_grabacion_el_ya_sale_de_la_transcripcion() -> None:
    class Speaking(TimedHost):
        game: PptGame | None = None
        said_at: float | None = None

        async def say_fixed(self, text: str) -> bool:
            self.said_at = self.now()
            return await super().say_fixed(text)

        async def sleep(self, seconds: float) -> None:
            await super().sleep(seconds)
            if self.said_at is not None and self.now() - self.said_at >= 1.2:
                self.said_at = None
                assert self.game is not None
                await self.game.on_assistant_text("¡Piedra, papel o tijera…", False)
                await self.game.on_assistant_text("¡Piedra, papel o tijera… ya!", False)

    game, host, _ = make_ppt(wins, host_cls=Speaking)
    assert isinstance(host, Speaking)
    host.game = game
    await play(game, host)
    assert 1.2 <= host.at("go") - host.at("countdown") < 1.4


async def test_sin_grabacion_ni_transcripcion_el_ya_llega_por_tiempo() -> None:
    game, host, _ = make_ppt(wins, host_cls=TimedHost)
    await play(game, host)
    assert isinstance(host, TimedHost)
    assert host.at("go") - host.at("countdown") == pytest.approx(GO_TIMEOUT_S, abs=0.06)
    # Fuera de la cuenta, lo que dice Sonia no cuenta como «ya».
    await game.on_assistant_text("¡ya!", True)


async def test_sin_nadie_delante_avisa_y_luego_lo_deja() -> None:
    game, host, hands = make_ppt(wins, poses=FakePoses([pose_frame()]))
    await play(game, host)
    assert host.events("hint") == [{"text": HINT_NO_PLAYER}]
    assert host.spoken == [NO_PLAYER_TEXT, NO_PLAYER_CANCEL_TEXT]
    assert host.finished == [
        ("cancel", {"score": {"sonnia": 0, "player": 0}, "reason": "no_player"})
    ]
    assert hands.reads == 0 and host.touches == 0
    assert "countdown" not in events(host)


async def test_otra_persona_delante_sigue_la_partida() -> None:
    first = body(cx=0.5, width=0.2, height=0.6)
    closer = body(cx=0.45, width=0.45, height=0.9)

    def people(game: PptGame) -> PoseFrame:
        return pose_frame(first) if game.throws == 0 else pose_frame(first, closer)

    poses = PlanPoses(people)
    game, host, hands = make_ppt(wins, poses=poses)
    await play(game, host)
    assert host.finished[0][0] == "win"
    boxes = {pp.box for pp in hands.persons}
    assert boxes == {first.box, closer.box}
    # La primera tirada se leyó al primero y la segunda, al que se puso delante.
    assert hands.persons[0].box == first.box and hands.persons[-1].box == closer.box


async def test_parar_a_media_partida() -> None:
    game, host, _ = make_ppt(wins)
    await game.start("voice", {})
    for _ in range(300):
        await asyncio.sleep(0)
    assert game.phase != "off"
    await game.stop("voice")
    # El manager cancela las tareas del juego al terminar la partida.
    for task in host.tasks:
        task.cancel()
    await asyncio.gather(*host.tasks, return_exceptions=True)
    assert all(t.cancelled() or t.exception() is None for t in host.tasks)
    assert game.snapshot()["phase"] == "off"
    assert game._overlay == OverlayState()
    assert host.finished == []


async def test_no_empieza_sin_camara_ni_poses() -> None:
    game, host, _ = make_ppt(wins)
    host.vision.stream.available = False
    with pytest.raises(GameError):
        await game.start("voice", {})
    game, host, _ = make_ppt(wins)
    host.vision.poses.available_flag = False
    with pytest.raises(GameError):
        await game.start("voice", {})


async def test_sin_vista_en_vivo_se_juega_igual() -> None:
    game, host, _ = make_ppt(wins)
    host.vision.preview.available = False
    await play(game, host)
    assert host.finished[0][0] == "win"


async def test_seguir_la_partida_y_estado_del_panel() -> None:
    game, host, _ = make_ppt(wins)
    await game.start("voice", {})
    text = await game.resume()
    assert "Ya estáis jugando" in text and not brands_in(text)
    snap = game.snapshot()
    assert (
        snap["rounds"] == 3 and snap["target"] == 2 and snap["score"] == {"sonnia": 0, "player": 0}
    )
    # La línea corta de la tarjeta «Juegos» del panel (en pantalla, «Sonnia»).
    assert snap["summary"] == "Ronda 1 (al mejor de 3), Sonnia 0 - 0 Tú"
    for task in host.tasks:
        task.cancel()
    await asyncio.gather(*host.tasks, return_exceptions=True)


def test_reglas_cortas_y_sin_marcas() -> None:
    for rounds in (1, 3, 5, 15, 99):
        settings = game_settings(
            ppt=game_settings().games.ppt.model_copy(update={"rounds": rounds})
        )
        game = PptGame(FakeGameHost(PptGame.id, settings=settings))
        rules = game.rules()
        assert len(rules) <= INSTRUCT_MAX_CHARS
        assert not brands_in(rules) and "Sonnia" not in rules
        assert game.target == game.rounds // 2 + 1
    for text in (
        ppt_game.START_SCRIPT,
        ppt_game.RESUME_SCRIPT,
        ppt_game.RETRY_NO_HAND,
        ppt_game.RETRY_UNCLEAR,
        ppt_game.FINAL_PLAYER,
        ppt_game.FINAL_SONNIA,
        ppt_game.FINAL_TIE,
        ppt_game.NO_PLAYER_TEXT,
        ppt_game.NO_PLAYER_CANCEL_TEXT,
        ppt_game.CANT_SEE_TEXT,
        ppt_game.SAY_FAILED_TEXT,
        PHRASE,
    ):
        assert not brands_in(text) and "Sonnia" not in text


def test_la_frase_grabada_se_declara() -> None:
    game = PptGame(FakeGameHost(PptGame.id))
    assert game.phrases() == [PHRASE]
    assert PptGame.banks() == [] and PptGame.actions() == []


def test_la_secuencia_del_orquestador_falso() -> None:
    steps = load_demo(PptGame.id)
    names = [s.name for s in steps if isinstance(s, Capture)]
    # Una captura por estado (empezar, cuenta, «ya», acierto, fallo, sin mano y final), más
    # fotogramas seguidos del puño y de cada forma de la mano de Sonnia; en orden y sin repetir.
    for state in (
        "ppt-1-empezar",
        "ppt-2a-puno-arriba",
        "ppt-2b-cuenta",
        "ppt-3a-ya-tijera",
        "ppt-4-acierto",
        "ppt-5a-ya-papel",
        "ppt-5-fallo",
        "ppt-6a-ya-piedra",
        "ppt-6-sin-mano",
        "ppt-7-final",
    ):
        assert state in names, state
    assert len(names) == len(set(names))
    states = [int(n.split("-")[1][0]) for n in names]
    assert states == sorted(states)
    msgs = [s for s in steps if isinstance(s, GameMsg)]
    assert msgs[0].event == "start" and msgs[-1].event == "end"
    assert msgs[-1].data["result"] == "win"
    assert all(p.is_game_name(m.event) for m in msgs)
    assert {m.event for m in msgs} >= {"round", "ready", "countdown", "go", "result", "final"}


# ---------------------------------------------------------------------------
# 3. De punta a punta con GameManager
# ---------------------------------------------------------------------------


async def run_until(condition: Callable[[], bool], limit: int = 100_000) -> None:
    for _ in range(limit):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("la partida no llegó a donde se esperaba")


async def _managed(plan: Callable[[PptGame], list[HandReading]]) -> Any:
    hands = PlayerHands(plan)
    vision = FakeVision(poses=FakePoses([pose_frame(body())]), hands=hands)
    manager, engine, screen, clock = await make_manager([PptGame], vision=vision)
    current = manager.current

    def game() -> PptGame | None:
        found = manager.current or current
        return found if isinstance(found, PptGame) else None

    hands.game = game
    registry = build_default_registry(include_look=False, games=[PptGame])
    ctx = ActionContext(camera=None, avatar=None, gallery_dir="", extra={"games": manager})
    return manager, engine, screen, registry, ctx, hands


async def test_partida_entera_por_voz() -> None:
    manager, engine, screen, registry, ctx, _ = await _managed(wins)
    result = await registry.execute("start_game", {"juego": PptGame.id}, ctx)
    assert result.text.startswith(SCRIPT_PREFIX) and "piedra, papel o tijera" in result.text
    assert manager.active and manager.phase == "playing"
    await run_until(lambda: not manager.active)
    end = screen.game_msgs("end")[-1]
    assert end["data"] == {
        "winner": "player",
        "score": {"sonnia": 0, "player": 2},
        "result": "win",
    }
    assert engine.instructions[0].startswith("JUEGO EN MARCHA: piedra, papel o tijera")
    assert "vuelve a conversar con normalidad" in engine.instructions[-1]
    assert any("Brian o Mariel" in text for text in engine.spoken)
    first = screen.game_msgs()[0]
    assert first["event"] == "start" and first["data"]["title"] == "Piedra, papel o tijera"
    seqs = [m["seq"] for m in screen.game_msgs()]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    # Sin partida, nada queda fijo.
    assert screen.replay() == []


async def test_stop_game_a_media_partida() -> None:
    manager, _, screen, registry, ctx, _ = await _managed(wins)
    await registry.execute("start_game", {"juego": PptGame.id}, ctx)
    await run_until(lambda: bool(screen.game_msgs("countdown")))
    result = await registry.execute("stop_game", {}, ctx)
    assert "terminado" in result.text
    assert screen.game_msgs("end")[-1]["data"]["result"] == "cancel"
    assert not manager.active
    for _ in range(200):
        await asyncio.sleep(0)
    # Tras parar, la partida ya no manda nada más.
    assert screen.game_msgs()[-1]["event"] == "end"


async def test_unity_que_se_reconecta_vuelve_a_pintar_la_partida() -> None:
    manager, _, screen, registry, ctx, _ = await _managed(by_throw(wins, nothing))
    await registry.execute("start_game", {"juego": PptGame.id}, ctx)
    await run_until(lambda: bool(screen.game_msgs("result")))
    replay = screen.replay()
    assert replay[0]["event"] == "start"
    assert replay[-1]["event"] == "result"
    assert replay[-1]["data"]["score"] == {"sonnia": 0, "player": 1}
    # Lo pasajero (el puño, la cuenta, el «ya») no se repite.
    assert not {m["event"] for m in replay} & {"ready", "countdown", "go", "abort", "hint"}
    await manager.stop("panel")


async def test_una_jugada_de_piedra_papel_o_tijera_no_es_una_accion() -> None:
    registry = build_default_registry(include_look=False, games=[PptGame])
    names = set(registry.names())
    assert {"start_game", "stop_game"} <= names
    assert not any(name.startswith(("ppt_", "piedra_papel_tijera_")) for name in names)
