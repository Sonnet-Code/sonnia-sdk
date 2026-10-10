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
    starting_soon,
    today_now_and_next,
)
from sonia.clock import place_of, resolve_timezone, spoken_now, spoken_time
from sonia.config import AgendaSettings, ShowcaseSettings
from sonia.live.prompts import build_session_config
from sonia.showcase import Showcase
from sonia.types import ActionContext
from tests.test_live import make_rig, make_settings

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


def test_lo_de_hoy_para_los_momentos_del_stand() -> None:
    # Sonia solo está en el DevFest: fuera de sus días (o con el día ya acabado) no anuncia nada.
    schedule = parse_schedule_page(page(base_rows()))
    assert today_now_and_next(schedule, local(7, 19, 0), TZ) == ""
    assert today_now_and_next(schedule, local(9, 8, 30), TZ) == (
        "Lo siguiente, a las 9:15 de la mañana: Apertura, para todos."
    )
    now = today_now_and_next(schedule, local(9, 10, 45), TZ)
    assert now.startswith("Ahora mismo: Salón Principal: «Charla uno» de Ana Pérez; ")
    assert now.endswith("Lo siguiente, a las 12:05 del mediodía: Descanso con café, para todos.")
    assert today_now_and_next(schedule, local(9, 18, 0), TZ) == ""
    assert today_now_and_next(schedule, local(10, 16, 30), TZ) == "Ahora mismo: Cierre, para todos."
    assert today_now_and_next(schedule, local(11, 10, 0), TZ) == ""


def test_lo_que_empieza_en_cinco_minutos_sin_contar_descansos() -> None:
    schedule = parse_schedule_page(page(base_rows()))
    lead = timedelta(minutes=5)
    assert starting_soon(schedule, local(9, 10, 30), TZ, lead) is None
    soon = starting_soon(schedule, local(9, 10, 35), TZ, lead)
    assert soon is not None and soon[0] == local(9, 10, 40)
    assert soon[1] == (
        "A las 10:40 de la mañana (dentro de 5 min) empieza: Salón Principal: «Charla uno» de "
        "Ana Pérez; Salón B: «Charla dos» de Luis Gómez; Workshop en el Laboratorio: «Taller "
        "práctico» de Eva Ruiz."
    )
    # La apertura y el cierre sí se avisan; el descanso con café no.
    assert starting_soon(schedule, local(9, 9, 12), TZ, lead) is not None
    assert starting_soon(schedule, local(9, 12, 2), TZ, lead) is None


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
    # Trae la hora de ahora: GPT-Live solo tiene la de cuando empezó la conversación.
    assert "Hora de ahora: viernes 9 de octubre de 2026, 10:45 (las 10:45 de la mañana)." in (
        result.text
    )
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

        # Pasan los minutos sin charla a la vista: ninguna nota de hora (la decía sin venir
        # a cuento cuando llegaba una por minuto).
        now[0] = local(9, 10, 47)
        await asyncio.sleep(0.1)
        now[0] = local(9, 11, 30)
        await asyncio.sleep(0.1)
        assert conn.of_type("session.thinking.append") == []

        # Cinco minutos antes de la siguiente charla (no del descanso de las 12:05), una nota.
        now[0] = local(9, 12, 1)
        await asyncio.sleep(0.1)
        assert conn.of_type("session.thinking.append") == []
        rows = base_rows()
        rows.append(row("g", "Charla tres", "16:20", "17:00", track="t1", speaker={"name": "Zoe"}))
        web.html = page(rows)
        await book.refresh()
        now[0] = local(9, 12, 16)
        await conn.wait_type("session.thinking.append")
        note = conn.of_type("session.thinking.append")[0]["content"]
        assert note == (
            "[Reloj] Son las 12:16 (las 12:16 del mediodía). A las 12:20 del mediodía (dentro "
            "de 4 min) empieza: Salón Principal: «Charla tres» de Zoe."
        )
        # Una sola por tanda.
        now[0] = local(9, 12, 18)
        await asyncio.sleep(0.1)
        assert len(conn.of_type("session.thinking.append")) == 1
        await conn.wait_type("session.instructions.append")

        # La web cambió (la charla nueva): el código lo detecta y se lo pasa a la sesión.
        appended = conn.of_type("session.instructions.append")[-1]["content"]
        assert appended.startswith("La agenda oficial del DevFest acaba de cambiar")
        assert "Nueva en la agenda: «Charla tres» de Zoe" in appended

        # Con alguien hablando no se le pasa nada: ni la hora ni los cambios.
        await conn.hear("Hola")
        await rig.rec.wait_state("listening")
        rows[1]["track_id"] = "t2"
        rows.append(row("h", "Charla cuatro", "16:40", "17:20", track="t2"))
        web.html = page(rows)
        await book.refresh()
        now[0] = local(9, 12, 37)
        await asyncio.sleep(0.15)
        assert len(conn.of_type("session.thinking.append")) == 1
        assert len(conn.of_type("session.instructions.append")) == 1


# -- tarjetas de charlas (show_talk) --------------------------------------------------


class FakeAvatar:
    """Lo que las acciones piden a Unity: aquí solo se apunta."""

    def __init__(self) -> None:
        self.shown: list[dict[str, Any]] = []

    async def show_image(
        self, *, image_id: str, source: str, mime: str, data: bytes, caption: str | None
    ) -> None:
        self.shown.append({"image_id": image_id, "source": source, "mime": mime, "data": data})

    async def hide_image(self) -> None:
        pass


def test_busca_la_charla_por_titulo_o_ponente() -> None:
    from sonia.agenda.card import find_talk

    schedule = parse_schedule_page(page(base_rows()))
    assert (find_talk(schedule, "charla uno") or base_rows()).id == "b"  # type: ignore[union-attr]
    assert (find_talk(schedule, "la de Luis Gomez") or base_rows()).id == "c"  # type: ignore[union-attr]
    assert (find_talk(schedule, "taller practico") or base_rows()).id == "d"  # type: ignore[union-attr]
    assert find_talk(schedule, "cocina medieval") is None
    # También lo que no tiene ponente: la apertura, un descanso o el cierre.
    assert (find_talk(schedule, "Apertura") or base_rows()).id == "a"  # type: ignore[union-attr]
    assert (find_talk(schedule, "el cierre") or base_rows()).id == "f"  # type: ignore[union-attr]
    # Igual gana a «contiene»: «Cierre» y no una charla que lleve esa palabra.
    rows = base_rows()
    rows[2]["title"] = "Del código al cierre de negocios"
    other = parse_schedule_page(page(rows))
    assert (find_talk(other, "cierre") or base_rows()).id == "f"  # type: ignore[union-attr]


def test_entre_varias_iguales_elige_la_proxima() -> None:
    from sonia.agenda.card import find_talk

    rows = base_rows()
    rows.append(row("e2", "BREAK", "18:00", "18:15", kind="break", plenary=True, icon="☕"))
    schedule = parse_schedule_page(page(rows))
    assert find_talk(schedule, "descanso con café", now=local(9, 9, 0)).id == "e"  # type: ignore[union-attr]
    assert find_talk(schedule, "descanso con café", now=local(9, 13, 0)).id == "e2"  # type: ignore[union-attr]
    assert find_talk(schedule, "descanso con café", now=local(11, 9, 0)).id == "e"  # type: ignore[union-attr]


def test_la_tarjeta_es_un_png_de_1600x900() -> None:
    import io

    from PIL import Image

    from sonia.agenda.card import HEIGHT, WIDTH, render_talk_card

    schedule = parse_schedule_page(page(base_rows()))
    talk = next(t for t in schedule.talks if t.id == "b")
    image = Image.open(io.BytesIO(render_talk_card(talk, TZ, photo=b"no es una foto")))
    assert image.format == "PNG" and image.size == (WIDTH, HEIGHT)


async def test_show_talk_ensena_la_tarjeta_y_dice_cuando_y_donde(tmp_path: Path) -> None:
    from sonia.actions.agenda import show_talk

    rows = base_rows()
    rows[1]["speakers"]["photo_url"] = "https://fotos.test/ana.webp"
    web = FakeWeb(page(rows))
    book = make_book(tmp_path, web, fallback_rows=rows)
    await book.load()
    avatar = FakeAvatar()
    ctx = ActionContext(camera=None, avatar=avatar, gallery_dir="", extra={"agenda": book})
    result = await show_talk(ctx, {"charla": "Charla uno"})
    assert result.text.startswith(
        "Mostrando ya en tu pantalla la tarjeta de la charla «Charla uno»"
    )
    assert "Ya se ve: no ofrezcas enseñarla." in result.text
    assert "de 10:40 a 11:20 de la mañana en el Salón Principal" in result.text
    assert avatar.shown[0]["source"] == "agenda" and avatar.shown[0]["mime"] == "image/png"
    assert avatar.shown[0]["data"].startswith(b"\x89PNG")
    # La foto se pidió (la web falsa no la tiene, y aun así sale la tarjeta) una sola vez.
    await show_talk(ctx, {"charla": "Charla uno"})
    assert web.requests == 1

    result = await show_talk(ctx, {"charla": "cocina medieval"})
    assert result.text.startswith("No encuentro en la agenda")
    assert len(avatar.shown) == 2


async def test_show_talk_con_un_juego_en_pantalla_no_ensena_nada(tmp_path: Path) -> None:
    """Con un juego en la franja alta la tarjeta no se vería (pasó con GPT-Live real: contestó
    una pregunta del pasillo con show_talk en pleno Wordle): ni se dibuja ni se manda."""
    from types import SimpleNamespace

    from sonia.actions.agenda import show_talk

    rows = base_rows()
    web = FakeWeb(page(rows))
    book = make_book(tmp_path, web, fallback_rows=rows)
    await book.load()
    requests = web.requests
    avatar = FakeAvatar()
    games = SimpleNamespace(active=True, current=SimpleNamespace(spoken="el Wordle de tecnología"))
    ctx = ActionContext(
        camera=None, avatar=avatar, gallery_dir="", extra={"agenda": book, "games": games}
    )
    result = await show_talk(ctx, {"charla": "Charla uno"})
    assert avatar.shown == [] and web.requests == requests
    assert "el Wordle de tecnología" in result.text
    assert "la tarjeta de la charla" in result.text and "con palabras" in result.text


def test_las_descripciones_largas_se_leen_de_su_trozo() -> None:
    from sonia.agenda.source import _text_chunks

    uno, dos = "Primera descripción: ñandú.", "Segunda, justo detrás"
    largo = len(uno.encode("utf-8"))
    payload = (
        f'5:["$","x",null,{{}}]\n18:T{largo:x},{uno}19:T{len(dos.encode()):x},{dos}20:["fin"]\n'
    )
    assert _text_chunks(payload) == {"18": uno, "19": dos}

    rows = base_rows()
    rows[1]["description"] = "$18"
    rows[2]["description"] = "Inline"
    rows[3]["description"] = None
    data = {"talkRows": rows, "trackRows": TRACKS}
    flight = f"5:{json.dumps(data, ensure_ascii=False)}\n18:T{largo:x},{uno}"
    html = f"<script>self.__next_f.push([1,{json.dumps(flight)}])</script>"
    talks = {t.id: t for t in parse_schedule_page(html).talks}
    assert talks["b"].description == uno
    assert talks["c"].description == "Inline"
    assert talks["d"].description == ""


async def test_un_momento_del_stand_cuenta_lo_que_pasa_en_la_agenda(tmp_path: Path) -> None:
    book = make_book(tmp_path, None, fallback_rows=base_rows())
    showcase = Showcase(phrases=[], songs=[], gesture_chance=0, moment_chance=1.0)
    settings = ShowcaseSettings(
        enabled=True, first_delay_seconds=0.0, interval_min_seconds=60, interval_max_seconds=60
    )
    async with make_rig(
        tmp_path,
        agenda=book,
        showcase=showcase,
        showcase_settings=settings,
        clock=lambda: local(9, 10, 45),
    ) as rig:
        conn = await rig.conn()
        await conn.wait_type("session.commentary.append")
        content = conn.of_type("session.commentary.append")[0]["content"]
        assert book.today() in content and "Ahora mismo:" in content
        assert "sin cambiar títulos, salas ni horas" in content
        assert "ya está aquí, en el DevFest" in content


async def test_antes_del_devfest_los_momentos_no_anuncian_el_evento(tmp_path: Path) -> None:
    # 7-oct: decía «¿Ya tienes tu entrada? Arranca este viernes…» a gente que ya está en él.
    book = make_book(tmp_path, None, fallback_rows=base_rows(), clock=lambda: local(7, 19, 0))
    showcase = Showcase(phrases=[], songs=[], gesture_chance=0, moment_chance=1.0)
    settings = ShowcaseSettings(
        enabled=True, first_delay_seconds=0.0, interval_min_seconds=60, interval_max_seconds=60
    )
    async with make_rig(
        tmp_path,
        agenda=book,
        showcase=showcase,
        showcase_settings=settings,
        clock=lambda: local(7, 19, 0),
    ) as rig:
        conn = await rig.conn()
        await conn.wait_type("session.commentary.append")
        content = conn.of_type("session.commentary.append")[0]["content"]
        assert "empieza" not in content and "viernes" not in content
        assert "trivia" in content
