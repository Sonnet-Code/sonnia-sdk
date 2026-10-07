"""Reloj y agenda en vivo: lectura de la web, texto, cambios, caché, acción y motor.

Sin red: la página de la agenda es un HTML sintético con el mismo formato que
la web del DevFest (flujo RSC de Next.js) servido con ``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from sonia.actions.agenda import NO_AGENDA, check_agenda
from sonia.actions.builtin import build_default_registry
from sonia.agenda import (
    AgendaBook,
    AgendaError,
    Schedule,
    diff_agenda,
    happening,
    parse_schedule_page,
    render_agenda,
)
from sonia.clock import place_of, resolve_timezone, spoken_now, spoken_time
from sonia.config import AgendaSettings
from sonia.live.prompts import build_session_config
from sonia.types import ActionContext
from tests.test_live import make_rig, make_settings, wait_until

TZ = timezone(timedelta(hours=-4), "America/Santo_Domingo")

TRACKS: list[dict[str, Any]] = [
    {"id": "t1", "name": "Track 1", "kind": "talks", "room": "Salón Principal", "display_order": 1},
    {"id": "t2", "name": "Track 2", "kind": "talks", "room": "Salón B", "display_order": 2},
    {
        "id": "t3",
        "name": "Workshops",
        "kind": "workshops",
        "room": "Laboratorio",
        "display_order": 3,
    },
]


def row(
    talk_id: str,
    title: str,
    start: str,
    end: str,
    *,
    day: int = 9,
    track: str | None = None,
    kind: str = "talk",
    plenary: bool = False,
    speaker: dict[str, str] | None = None,
    topics: list[str] | None = None,
    icon: str | None = None,
    language: str = "es",
) -> dict[str, Any]:
    """Una fila de ``talkRows`` (horas UTC, como la web)."""
    return {
        "id": talk_id,
        "title": title,
        "description": "$18",
        "track_id": track,
        "topics": topics,
        "is_plenary": plenary,
        "icon": icon,
        "room": None,
        "starts_at": f"2026-10-{day:02d}T{start}:00+00:00",
        "ends_at": f"2026-10-{day:02d}T{end}:00+00:00",
        "talk_type": kind,
        "level": None,
        "language": language,
        "speakers": speaker,
    }


def base_rows() -> list[dict[str, Any]]:
    return [
        row("a", "APERTURA", "13:15", "13:35", kind="break", plenary=True),
        row(
            "b",
            "Charla uno",
            "14:40",
            "15:20",
            track="t1",
            speaker={"name": "Ana Pérez", "title": "CTO 🚀 | GDE | Otra cosa"},
            topics=["AI/ML", "Cloud"],
        ),
        row("c", "Charla dos", "14:40", "15:20", track="t2", speaker={"name": "Luis Gómez"}),
        row("d", "Taller práctico", "14:40", "16:05", track="t3", speaker={"name": "Eva Ruiz"}),
        row("e", "BREAK", "16:05", "16:20", kind="break", plenary=True, icon="☕"),
        row("f", "CIERRE", "20:00", "21:00", day=10, kind="break", plenary=True),
    ]


def page(rows: list[dict[str, Any]], tracks: list[dict[str, Any]] | None = None) -> str:
    """HTML con los datos repartidos en varios ``self.__next_f.push`` (como Next.js)."""
    data = {"talkRows": rows, "trackRows": TRACKS if tracks is None else tracks, "topicRows": []}
    payload = '5:["$","$L17",null,' + json.dumps(data, ensure_ascii=False) + "]\n"
    size = len(payload) // 3 + 1
    chunks = [payload[i : i + size] for i in range(0, len(payload), size)]
    pushes = "".join(
        f"<script>self.__next_f.push([1,{json.dumps(chunk)}])</script>" for chunk in chunks
    )
    return f"<html><body><script>self.__next_f.push([0])</script>{pushes}</body></html>"


def local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


# -- reloj -----------------------------------------------------------------------


def test_la_hora_se_dice_como_en_el_caribe() -> None:
    assert spoken_time(local(6, 19, 5)) == "19:05 (las 7:05 de la noche)"
    assert spoken_time(local(7, 1, 4)) == "01:04 (la 1:04 de la madrugada)"
    assert spoken_time(local(9, 12, 30)) == "12:30 (las 12:30 del mediodía)"
    assert spoken_time(local(9, 9, 15)) == "09:15 (las 9:15 de la mañana)"
    assert spoken_now(local(9, 15, 0), place_of("America/Santo_Domingo")) == (
        "viernes 9 de octubre de 2026, 15:00 (las 3:00 de la tarde), hora de Santo Domingo"
    )


def test_santo_domingo_sin_base_de_zonas_es_utc_menos_4(monkeypatch: pytest.MonkeyPatch) -> None:
    import zoneinfo

    def broken(name: str) -> None:
        raise zoneinfo.ZoneInfoNotFoundError(name)

    monkeypatch.setattr(zoneinfo, "ZoneInfo", broken)
    tz = resolve_timezone("America/Santo_Domingo")
    assert datetime(2026, 10, 9, 12, tzinfo=tz).utcoffset() == timedelta(hours=-4)
    # Una zona desconocida no tumba nada: cae en la del sistema.
    assert resolve_timezone("Nada/Inventada") is not None


# -- lectura de la página ----------------------------------------------------------


def test_lee_la_agenda_de_la_pagina() -> None:
    schedule = parse_schedule_page(page(base_rows()))
    assert len(schedule) == 6
    assert [r.name for r in schedule.rooms] == ["Salón Principal", "Salón B", "Laboratorio"]
    talks = {t.id: t for t in schedule.talks}
    assert talks["b"].room == "Salón Principal"
    assert talks["b"].speaker == "Ana Pérez"
    assert talks["b"].starts_at == local(9, 10, 40)
    # Una charla del track de workshops es un workshop.
    assert talks["d"].kind == "workshop"
    assert talks["a"].room == ""


def test_una_pagina_sin_agenda_lanza() -> None:
    with pytest.raises(AgendaError):
        parse_schedule_page("<html><body>Mantenimiento</body></html>")
    with pytest.raises(AgendaError):
        parse_schedule_page(page([]))


def test_el_texto_de_la_agenda_va_por_dias_y_salas() -> None:
    text = render_agenda(parse_schedule_page(page(base_rows())), TZ, consulted="hoy")
    assert "consultada el hoy" in text
    assert "Salas: Salón Principal (Track 1), Salón B (Track 2) y Laboratorio (Workshops)." in text
    assert "## Viernes 9 de octubre\n- 9:15-9:35 Apertura, para todos." in text
    # Cargo recortado al primero y sin emojis.
    assert "- 10:40-11:20 Salón Principal: «Charla uno» — Ana Pérez (CTO). AI/ML, Cloud." in text
    assert "- 10:40-12:05 Workshop en el Laboratorio: «Taller práctico» — Eva Ruiz." in text
    assert "- 12:05-12:20 Descanso con café, para todos." in text
    assert "## Sábado 10 de octubre\n- 4:00-5:00 Cierre, para todos." in text


# -- cambios ---------------------------------------------------------------------


def test_los_cambios_se_detectan_en_codigo() -> None:
    old = parse_schedule_page(page(base_rows()))
    rows = base_rows()
    rows[0]["id"] = "a-nuevo"  # la web la volvió a crear: mismo título, nada que contar
    rows[1]["starts_at"], rows[1]["ends_at"] = (
        "2026-10-09T15:25:00+00:00",
        "2026-10-09T16:05:00+00:00",
    )
    rows[2]["track_id"] = "t1"
    rows[3]["speakers"] = {"name": "Otro Ponente"}
    del rows[4]
    rows.append(row("g", "Charla sorpresa", "18:00", "18:40", track="t2", speaker={"name": "Zoe"}))
    changes = diff_agenda(old, parse_schedule_page(page(rows)), TZ)
    assert changes == [
        "«Charla dos» de Luis Gómez cambia de sala: del Salón B al Salón Principal.",
        "«Taller práctico»: el ponente era Eva Ruiz y ahora es Otro Ponente.",
        "«Charla uno» de Ana Pérez cambia de hora: era el viernes 9 de octubre, de 10:40 a "
        "11:20 de la mañana y ahora es el viernes 9 de octubre, de 11:25 de la mañana a 12:05 "
        "del mediodía.",
        "«Descanso con café» ya no está en la agenda (era el viernes 9 de octubre, de 12:05 a "
        "12:20 del mediodía).",
        "Nueva en la agenda: «Charla sorpresa» de Zoe, el viernes 9 de octubre, de 2:00 a 2:40 "
        "de la tarde en el Salón B.",
    ]


def test_sin_cambios_no_hay_nada_que_contar() -> None:
    old = parse_schedule_page(page(base_rows()))
    new = parse_schedule_page(page(list(reversed(base_rows()))))
    assert diff_agenda(old, new, TZ) == []


def test_que_hay_ahora_y_que_viene() -> None:
    schedule = parse_schedule_page(page(base_rows()))
    assert happening(schedule, local(7, 19, 0), TZ) == (
        "El DevFest empieza dentro de 2 días, el viernes 9 de octubre a las 9:15 de la mañana."
    )
    now = happening(schedule, local(9, 10, 45), TZ)
    assert now.startswith("Ahora mismo: Salón Principal: «Charla uno» de Ana Pérez; ")
    assert "Lo siguiente, a las 12:05 del mediodía: Descanso con café, para todos." in now
    assert happening(schedule, local(9, 18, 0), TZ) == (
        "Ahora mismo no hay ninguna sesión. Lo siguiente, el sábado 10 de octubre a las 4:00 "
        "de la tarde: Cierre, para todos."
    )
    assert happening(schedule, local(11, 10, 0), TZ) == "El DevFest ya terminó."


# -- caché, web y oyentes ------------------------------------------------------------


class FakeWeb:
    """La web de la agenda: sirve ``html`` o un error."""

    def __init__(self, html: str) -> None:
        self.html = html
        self.status = 200
        self.requests = 0

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests += 1
            assert request.headers["user-agent"].startswith("Sonnia/")
            return httpx.Response(self.status, text=self.html)

        return httpx.MockTransport(handle)


def make_book(
    tmp_path: Path,
    web: FakeWeb | None,
    *,
    fallback_rows: list[dict[str, Any]] | None = None,
    clock: Any = None,
) -> AgendaBook:
    fallback = tmp_path / "agenda.json"
    if fallback_rows is not None:
        schedule = parse_schedule_page(page(fallback_rows))
        data = {"fetched_at": "2026-10-06T19:05:00-04:00", **schedule.to_json()}
        fallback.write_text(json.dumps(data), encoding="utf-8")
    settings = AgendaSettings(
        url="http://agenda.test/schedule" if web is not None else "off",
        refresh_minutes=0,
        timeout_seconds=1,
        cache_file=str(tmp_path / "cache" / "agenda.json"),
    )
    return AgendaBook(
        settings,
        tz=TZ,
        fallback_file=fallback,
        transport=web.transport() if web is not None else None,
        clock=clock or (lambda: local(9, 10, 45)),
    )


async def test_arranca_con_la_copia_y_avisa_de_lo_que_cambia_en_la_web(tmp_path: Path) -> None:
    rows = base_rows()
    rows[2]["track_id"] = "t1"
    web = FakeWeb(page(rows))
    book = make_book(tmp_path, web, fallback_rows=base_rows())
    heard: list[list[str]] = []

    async def listener(changes: list[str]) -> None:
        heard.append(changes)

    book.on_change(listener)
    await book.load()
    assert book.source == "copia de la app"
    assert "consultada el martes 6 de octubre de 2026 a las 19:05" in book.text()

    update = await book.refresh("prueba")
    assert update.ok and update.changes == heard[0]
    assert heard == [["«Charla dos» de Luis Gómez cambia de sala: del Salón B al Salón Principal."]]
    assert book.source == "web"

    # La siguiente vez arranca de la caché, ya con el cambio.
    again = make_book(tmp_path, None)
    await again.load()
    assert again.source == "caché"
    assert "Salón Principal: «Charla dos»" in again.text()

    # Sin cambios, nadie se entera.
    assert (await book.refresh()).changes == []
    assert len(heard) == 1


async def test_si_la_web_falla_se_queda_con_lo_que_sabia(tmp_path: Path) -> None:
    web = FakeWeb(page(base_rows()))
    web.status = 503
    book = make_book(tmp_path, web, fallback_rows=base_rows())
    update = await book.refresh()
    assert not update.ok and "503" in update.error
    assert book.source == "copia de la app" and len(book.schedule or ()) == 6
    assert not (tmp_path / "cache" / "agenda.json").exists()


async def test_una_pagina_casi_vacia_no_borra_la_agenda(tmp_path: Path) -> None:
    web = FakeWeb(page(base_rows()[:2]))
    book = make_book(tmp_path, web, fallback_rows=base_rows())
    update = await book.refresh()
    assert not update.ok
    assert len(book.schedule or ()) == 6


async def test_sin_url_no_se_consulta_la_web(tmp_path: Path) -> None:
    book = make_book(tmp_path, None, fallback_rows=base_rows())
    update = await book.refresh()
    assert not update.ok
    assert book.schedule is not None


# -- acción check_agenda ---------------------------------------------------------------


def ctx_with(book: AgendaBook | None, baseline: Schedule | None) -> ActionContext:
    return ActionContext(
        camera=None,
        avatar=None,
        gallery_dir="",
        extra={"agenda": book, "agenda_baseline": baseline},
    )


async def test_check_agenda_cuenta_los_cambios_y_que_hay_ahora(tmp_path: Path) -> None:
    rows = base_rows()
    rows[3]["speakers"] = {"name": "Otro Ponente"}
    web = FakeWeb(page(base_rows()))
    book = make_book(tmp_path, web, fallback_rows=base_rows())
    await book.load()
    baseline = book.schedule

    result = await check_agenda(ctx_with(book, baseline), {})
    assert result.text.startswith("Consultada ahora la agenda oficial: no ha cambiado nada")
    assert "Ahora mismo: Salón Principal: «Charla uno»" in result.text

    web.html = page(rows)
    result = await check_agenda(ctx_with(book, baseline), {})
    assert "Cambios respecto a la que conocías: «Taller práctico»: el ponente era Eva Ruiz" in (
        result.text
    )

    web.status = 500
    result = await check_agenda(ctx_with(book, baseline), {})
    assert result.text.startswith("No se pudo consultar la web de la agenda ahora mismo")
    assert (await check_agenda(ctx_with(None, None), {})).text == NO_AGENDA


# -- instrucciones -------------------------------------------------------------------


def test_las_instrucciones_traen_hora_agenda_busqueda_y_recordatorio(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    config = build_session_config(
        settings,
        registry=build_default_registry(
            include_look=False, include_trivia=True, include_agenda=True
        ),
        gallery_ids=[],
        knowledge_dir=tmp_path,
        agenda="AGENDA DEL DEVFEST (prueba)",
        clock_text="viernes 9 de octubre de 2026, 10:45",
    )
    instructions = config["instructions"]
    assert "FECHA Y HORA (al empezar esta conversación): viernes 9 de octubre" in instructions
    assert "AGENDA DEL DEVFEST (prueba)" in instructions
    assert "- Agenda: consultar ahora la agenda oficial" in instructions
    assert "- Buscar en internet:" in instructions
    # El recordatorio de delegar va lo último, que es lo que más pesa.
    reminder = instructions.rsplit("\n\n", 1)[1]
    assert reminder.startswith("ANTES DE CADA RESPUESTA, RECUERDA")
    assert "bailar o hacer un gesto" in reminder and "buscar en internet" in reminder
    assert "nunca digas preguntas ni opciones de tu cabeza" in reminder
    # Sin cámara no se habla del aspecto de nadie (se inventaba «esas gafas»).
    assert "No tienes cámara: no comentes el aspecto" in reminder

    backend = config["delegation"]["responses"]
    assert "AGENDA DEL DEVFEST (prueba)" in backend["instructions"]
    assert "Puedes buscar en internet" in backend["instructions"]
    search = [t for t in backend["tools"] if t["type"] == "web_search"]
    assert search == [
        {
            "type": "web_search",
            "user_location": {
                "type": "approximate",
                "country": "DO",
                "city": "Santo Domingo",
                "timezone": "America/Santo_Domingo",
            },
            "search_context_size": "low",
        }
    ]


def test_sin_busqueda_web_no_se_anuncia(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, backend_web_search=False)
    config = build_session_config(
        settings, registry=build_default_registry(include_look=False), gallery_ids=[]
    )
    assert all(t["type"] == "function" for t in config["delegation"]["responses"]["tools"])
    assert "Buscar en internet" not in config["instructions"]
    assert "Puedes buscar en internet" not in config["delegation"]["responses"]["instructions"]


# -- motor -------------------------------------------------------------------------


async def test_el_motor_da_la_hora_y_pasa_los_cambios_de_agenda(tmp_path: Path) -> None:
    web = FakeWeb(page(base_rows()))
    now = [local(9, 10, 45)]
    book = make_book(tmp_path, web, fallback_rows=base_rows(), clock=lambda: now[0])
    async with make_rig(tmp_path, agenda=book, clock=lambda: now[0]) as rig:
        conn = await rig.conn()
        session = conn.start["session"]
        assert (
            "viernes 9 de octubre de 2026, 10:45 (las 10:45 de la mañana)"
            in (session["instructions"])
        )
        assert "## Viernes 9 de octubre" in session["instructions"]
        assert "check_agenda" in [
            t.get("name") for t in session["delegation"]["responses"]["tools"]
        ]

        # Mismo minuto que al abrir la sesión: no hace falta nota.
        await asyncio.sleep(0.1)
        assert conn.of_type("session.thinking.append") == []

        # Cambia el minuto: la nota va en calma, no al empezar a hablar alguien.
        now[0] = local(9, 10, 47)
        await conn.wait_type("session.thinking.append")
        note = conn.of_type("session.thinking.append")[0]["content"]
        assert note.startswith("[Reloj] Ahora: viernes 9 de octubre de 2026, 10:47")
        assert "Ahora mismo: Salón Principal: «Charla uno»" in note
        await asyncio.sleep(0.1)
        assert len(conn.of_type("session.thinking.append")) == 1
        # Al minuto siguiente, solo la hora: lo de la agenda no ha cambiado.
        now[0] = local(9, 10, 48)
        await conn.wait_type("session.thinking.append", 2)
        assert "Ahora mismo" not in conn.of_type("session.thinking.append")[1]["content"]

        # La web cambia: el código lo detecta y se lo pasa a la sesión abierta.
        await wait_until(lambda: web.requests >= 1)
        rows = base_rows()
        rows[1]["track_id"] = "t2"
        web.html = page(rows)
        await book.refresh()
        await conn.wait_type("session.instructions.append")
        appended = conn.of_type("session.instructions.append")[-1]["content"]
        assert appended.startswith("La agenda oficial del DevFest acaba de cambiar")
        assert (
            "«Charla uno» de Ana Pérez cambia de sala: del Salón Principal al Salón B." in appended
        )

        # Con alguien hablando no se le pasa nada: ni la hora ni los cambios.
        await conn.hear("Hola")
        await rig.rec.wait_state("listening")
        now[0] = local(9, 10, 49)
        rows[2]["track_id"] = "t1"
        web.html = page(rows)
        await book.refresh()
        await asyncio.sleep(0.15)
        assert len(conn.of_type("session.thinking.append")) == 2
        assert len(conn.of_type("session.instructions.append")) == 1
