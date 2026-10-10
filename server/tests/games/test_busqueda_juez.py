"""La búsqueda relámpago con el juez de verdad (``ModelJudge``) sobre un servidor HTTP falso.

Nunca el modelo de visión de verdad: ``httpx.MockTransport`` contesta lo que diga el test. Sirve para
comprobar el juego contra la implementación real del juez: la cuenta de fotos por ronda
(``start_round``), la pregunta que llega al modelo y lo que vuelve en JSON (``objeto``) por el
filtro ``clean_what`` antes de llegar a Sonia o a la pantalla.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from sonia.games.busqueda.bank import OBJECTS, parse_objects
from sonia.games.busqueda.game import BusquedaGame
from sonia.vision.judge import JUDGE_PROMPT, ModelJudge
from tests.games.fakes import FakeVision, make_game
from tests.games.test_busqueda import current, go, pump, sent
from tests.test_vision_judge import FakeCamera, completion_response, make_client


def reply(seen: bool, what: str = "") -> httpx.Response:
    return completion_response(json.dumps({"visto": seen, "objeto": what if seen else ""}))


async def test_el_juez_de_verdad_recibe_la_pregunta_del_objeto_y_gana_la_ronda() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return reply(len(bodies) == 3, "botella azul")

    camera = FakeCamera()
    async with make_client(handler) as client:
        judge = ModelJudge(client, camera)
        game, host = make_game(BusquedaGame, vision=FakeVision(judge=judge))  # type: ignore[arg-type]
        await game.start("voice", {})
        assert judge.remaining == 10  # el juego abrió la cuenta de la ronda con su tope
        await go(game, host)
        name = current(game)
        await pump(game, host, 7.7)
        assert judge.calls == 3 and len(bodies) == 3
        assert sent(host, "found") and host.last("found")["what"] == "botella azul"
        # Al modelo le llegan el prompt del juez y la pregunta cerrada del objeto, con la foto.
        first = bodies[0]["messages"]
        assert first[0] == {"role": "system", "content": JUDGE_PROMPT}
        bank = host.settings.games_dir / "busqueda" / OBJECTS.file
        entry = {e.name: e for e in parse_objects(bank.read_text(encoding="utf-8")).entries}[name]
        assert first[1]["content"][0] == {"type": "text", "text": entry.question}
        assert first[1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert camera.requests == [(640, 75)] * 3
        await game.stop("panel")


async def test_las_fotos_del_juego_y_las_del_juez_llevan_la_misma_cuenta_y_el_mismo_tope() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return reply(False)

    async with make_client(handler) as client:
        judge = ModelJudge(client, FakeCamera())
        game, host = make_game(BusquedaGame, vision=FakeVision(judge=judge))  # type: ignore[arg-type]
        await game.start("voice", {})
        await go(game, host)
        await pump(game, host, 26.0)
        # Se acabó el tiempo: nueve o diez fotos, nunca más que el tope, y las dos cuentas coinciden.
        assert 9 <= calls <= 10
        assert judge.calls == calls == game.snapshot()["checks"]
        assert sent(host, "timeout") and not sent(host, "found")
        # La ronda siguiente empieza la cuenta de cero.
        host.quiet = 0.0
        await pump(game, host, 0.5)
        host.quiet = 5.0
        await pump(game, host, 0.1)
        assert judge.calls == 0 and judge.remaining == 10
        await game.stop("panel")


async def test_un_objeto_del_modelo_que_habla_de_la_persona_no_llega_a_sonia() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return reply(True, "un hombre con gafas sosteniendo una botella")

    async with make_client(handler) as client:
        judge = ModelJudge(client, FakeCamera())
        game, host = make_game(BusquedaGame, vision=FakeVision(judge=judge))  # type: ignore[arg-type]
        await game.start("voice", {})
        await go(game, host)
        name = current(game)
        await pump(game, host, 2.7)
        assert host.last("found")["what"] == name
        assert "hombre" not in host.spoken[-1] and "gafas" not in host.spoken[-1]
        await game.stop("panel")


async def test_si_el_servidor_falla_la_ronda_sigue_y_se_avisa_de_que_la_camara_no_contesta() -> (
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="caído")

    async with make_client(handler) as client:
        judge = ModelJudge(client, FakeCamera())
        game, host = make_game(BusquedaGame, vision=FakeVision(judge=judge))  # type: ignore[arg-type]
        await game.start("voice", {})
        await go(game, host)
        await pump(game, host, 26.0)
        assert host.last("timeout")["silent"] is True
        assert game.snapshot()["phase"] == "between"
        await game.stop("panel")


async def test_sin_foto_de_la_camara_no_se_llama_al_modelo_y_la_ronda_acaba_sin_respuesta() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no debía llamar al modelo")

    async with make_client(handler) as client:
        judge = ModelJudge(client, FakeCamera(ok=False))
        game, host = make_game(BusquedaGame, vision=FakeVision(judge=judge))  # type: ignore[arg-type]
        await game.start("voice", {})
        await go(game, host)
        await pump(game, host, 26.0)
        assert judge.calls == 0 and host.last("timeout")["silent"] is True
        await game.stop("panel")
