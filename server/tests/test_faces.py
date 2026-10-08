"""Reconocer al equipo de Sonnet Code y a los ponentes (docs/caras.md).

Sin OpenCV ni red: un analizador falso convierte cada «foto» (unos bytes) en las
caras que se le dicen, y las fotos de referencia salen de archivos locales o de
``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from sonia import cli
from sonia.actions import build_default_registry
from sonia.agenda.schedule import Schedule, Talk
from sonia.config import FaceSettings, Settings, VisionSettings
from sonia.faces import (
    Face,
    FaceBook,
    FaceModelError,
    FaceWatcher,
    Greetings,
    Match,
    Person,
    Sighting,
    VisitLog,
    arrival_text,
    ensure_models,
    known_people,
    known_text,
    load_greetings,
    load_staff,
    speakers_from,
)
from sonia.faces.book import book_path, enroll
from sonia.faces.model import ARCFACE, RECOGNIZER, model_files
from sonia.faces.watcher import RECENT_S, most_different
from sonia.live.prompts import build_session_config
from sonia.paths import REPO_ROOT, SEEDED
from sonia.types import Frame
from sonia.vision.camera import OpenCVCamera
from tests.helpers import FakeCamera
from tests.test_cli import make_settings as cli_make_settings
from tests.test_live import make_rig, make_settings, tool_names, wait_until

#: Lo que devuelve la cámara falsa en estos tests: el analizador falso la reconoce por sus bytes.
CAMERA_FRAME = Frame(data=b"camara")

SANTO_DOMINGO = timezone(timedelta(hours=-4))
#: Primer día del DevFest, 10:32 de la mañana en el stand.
MORNING = datetime(2026, 10, 9, 10, 32, tzinfo=SANTO_DOMINGO)


class FakeClock:
    """Hora de pared que el test mueve a mano."""

    def __init__(self, now: datetime = MORNING) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


# ---------------------------------------------------------------------------
# Huellas de prueba y analizador falso
# ---------------------------------------------------------------------------


def axis(i: int) -> np.ndarray[Any, Any]:
    vector = np.zeros(128, dtype=np.float32)
    vector[i] = 1.0
    return vector


def near(i: int, similarity: float, other: int = 127) -> np.ndarray[Any, Any]:
    """Una huella con similitud ``similarity`` con ``axis(i)`` (el resto hacia ``axis(other)``)."""
    return axis(i) * similarity + axis(other) * float(np.sqrt(1 - similarity**2))


class FakeAnalyzer:
    """Cada foto es una clave (sus bytes) con las caras que se le hayan dicho."""

    def __init__(self, photos: dict[bytes, list[Face]] | None = None) -> None:
        self.photos = photos or {}
        self.calls = 0

    def decode(self, data: bytes, max_side: int = 0) -> Any | None:
        return data if data in self.photos else None

    def faces(self, image: Any, *, min_width: int = 0, limit: int = 0) -> list[Face]:
        self.calls += 1
        found = [f for f in self.photos.get(image, []) if f.width >= min_width]
        found.sort(key=lambda f: f.width, reverse=True)
        return found[:limit] if limit > 0 else found


def face(vector: np.ndarray[Any, Any], width: int = 150) -> Face:
    return Face(width=width, score=0.95, embedding=vector / np.linalg.norm(vector))


def staff_file(tmp_path: Path, people: list[dict[str, Any]]) -> Path:
    path = tmp_path / "staff.json"
    path.write_text(json.dumps({"people": people}), encoding="utf-8")
    return path


def local_photos(folder: Path, names: list[str]) -> None:
    (folder / "fotos").mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / "fotos" / f"{name}.jpg").write_bytes(f"foto-{name}".encode())


BRIAN = {"name": "Brian James", "role": "gerente de Operaciones", "photos": ["fotos/brian.jpg"]}
JEAN = {"name": "Jean Calderon", "role": "CTO", "photos": ["fotos/jean.jpg"]}


def reference_analyzer(**extra: list[Face]) -> FakeAnalyzer:
    """Brian es el eje 0 y Jean el 1; ``extra`` añade fotos de la cámara."""
    photos = {b"foto-brian": [face(axis(0))], b"foto-jean": [face(axis(1))]}
    photos.update({key.encode(): faces for key, faces in extra.items()})
    return FakeAnalyzer(photos)


def watcher(
    tmp_path: Path,
    analyzer: FakeAnalyzer,
    *,
    clock: FakeClock | None = None,
    greetings: list[dict[str, Any]] | None = None,
    groups: dict[str, str] | None = None,
    guests: list[dict[str, Any]] | None = None,
    bundled_book: Path | None = None,
    **overrides: Any,
) -> FaceWatcher:
    folder = tmp_path / "faces"
    local_photos(folder, ["brian", "jean"])
    values: dict[str, Any] = {"dir": str(folder), "confirm_scans": 2, "cooldown_minutes": 20.0}
    values.update(overrides)
    greetings_file = tmp_path / "saludos.json"
    if greetings is not None or groups is not None:
        data = {"people": greetings or [], "groups": groups or {}}
        greetings_file.write_text(json.dumps(data), encoding="utf-8")
    guests_file = tmp_path / "invitados.json"
    if guests is not None:
        guests_file.write_text(json.dumps({"people": guests}), encoding="utf-8")
    return FaceWatcher(
        FaceSettings(**values),
        staff_file=staff_file(tmp_path, [BRIAN, JEAN]),
        analyzer_factory=lambda folder: analyzer,
        models=False,
        greetings_file=greetings_file,
        guests_file=guests_file,
        bundled_book=bundled_book,
        clock=clock or FakeClock(),
    )


def talk(title: str, speaker: str, photo: str = "", kind: str = "talk") -> Talk:
    start = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
    return Talk(
        id=title,
        title=title,
        starts_at=start,
        ends_at=start,
        kind=kind,
        speaker=speaker,
        photo_url=photo,
    )


# ---------------------------------------------------------------------------
# Quién es conocido
# ---------------------------------------------------------------------------


def test_el_staff_json_del_repo_trae_al_equipo_con_las_fotos_de_la_web() -> None:
    people = load_staff(REPO_ROOT / "assets" / "faces" / "staff.json")
    assert [p.name for p in people] == [
        "Jean Calderon",
        "Alexander Vegazo",
        "Brian James",
        "Lissette Pimentel",
        "Elieser Grullon",
    ]
    assert all(p.kind == "staff" and p.role for p in people)
    assert all(
        photo.startswith("https://www.sonnetcode.com/photos/leaders/")
        for p in people
        for photo in p.photos
    )


def test_load_staff_salta_las_entradas_sin_nombre_o_sin_fotos(tmp_path: Path) -> None:
    path = staff_file(
        tmp_path,
        [BRIAN, {"name": "Sin fotos"}, {"photos": ["x.jpg"]}, "basura"],  # type: ignore[list-item]
    )
    people = load_staff(path)
    assert [(p.id, p.name, p.photos) for p in people] == [
        ("staff:brian-james", "Brian James", ("fotos/brian.jpg",))
    ]
    assert load_staff(tmp_path / "no-existe.json") == []
    (tmp_path / "roto.json").write_text("{", encoding="utf-8")
    assert load_staff(tmp_path / "roto.json") == []


def test_los_ponentes_salen_de_la_agenda_con_su_charla() -> None:
    schedule = Schedule(
        (
            talk("IA en producción", "Lowell Abbott", "https://fotos.test/lowell.webp"),
            talk("Taller de IA", "Lowell Abbott", "https://fotos.test/lowell.webp"),
            talk("Panel", "Ana y Luis", "https://fotos.test/ana.webp"),
            talk("Sin foto", "Carmen"),
            talk("APERTURA", "", kind="break"),
        )
    )
    speakers = speakers_from(schedule)
    assert len(speakers) == 1
    lowell = speakers[0]
    assert (lowell.id, lowell.kind, lowell.photos) == (
        "speaker:lowell-abbott",
        "speaker",
        ("https://fotos.test/lowell.webp",),
    )
    assert lowell.role == "«IA en producción» y «Taller de IA»"
    assert (
        lowell.label == "Lowell Abbott (ponente del DevFest: «IA en producción» y «Taller de IA»)"
    )
    assert speakers_from(None) == []


def test_alguien_del_equipo_que_da_charla_es_una_sola_persona() -> None:
    staff = [Person("staff:jean-calderon", "Jean Calderon", "staff", "CTO", ("a.jpg",))]
    speaker = Person("speaker:jean-calderon", "Jean Calderón", "speaker", "«Sonia»", ("b.jpg",))
    people = known_people(staff, [speaker])
    assert len(people) == 1
    assert people[0].kind == "staff"
    assert people[0].photos == ("a.jpg", "b.jpg")
    assert people[0].label == "Jean Calderon (del equipo de Sonnet Code, CTO; ponente: «Sonia»)"


# ---------------------------------------------------------------------------
# Huellas: umbral, margen y disco
# ---------------------------------------------------------------------------


def make_book(tmp_path: Path) -> FaceBook:
    book = FaceBook(tmp_path / "caras.json")
    book.add_print(Person("staff:brian", "Brian", "staff"), "a", axis(0))
    book.add_print(Person("staff:jean", "Jean", "staff"), "b", axis(1))
    return book


def test_match_exige_umbral_y_ventaja_sobre_el_segundo(tmp_path: Path) -> None:
    book = make_book(tmp_path)
    found = book.match(near(0, 0.7), threshold=0.52, margin=0.06)
    assert found is not None and found.person.name == "Brian"
    assert found.score == pytest.approx(0.7, abs=1e-5)
    # Por debajo del umbral, nadie.
    assert book.match(near(0, 0.45), threshold=0.52, margin=0.06) is None
    # Se parece a los dos casi igual: no se arriesga.
    both = axis(0) * 0.62 + axis(1) * 0.6
    assert book.match(both / np.linalg.norm(both), threshold=0.4, margin=0.06) is None


def test_las_huellas_se_guardan_y_se_cargan_sin_fotos(tmp_path: Path) -> None:
    book = make_book(tmp_path)
    book.save()
    data = json.loads((tmp_path / "caras.json").read_text(encoding="utf-8"))
    assert data["model"] == "face_recognition_sface_2021dec.onnx"
    assert {p["name"] for p in data["people"]} == {"Brian", "Jean"}
    assert all(len(v) == 128 for p in data["people"] for v in p["prints"].values())

    again = FaceBook(tmp_path / "caras.json")
    again.load()
    assert len(again) == 2
    found = again.match(near(1, 0.8), threshold=0.52, margin=0.06)
    assert found is not None and found.person.name == "Jean"

    # Huellas de otro modelo: se ignoran (se rehacen).
    data["model"] = "otro.onnx"
    (tmp_path / "caras.json").write_text(json.dumps(data), encoding="utf-8")
    other = FaceBook(tmp_path / "caras.json")
    other.load()
    assert len(other) == 0


async def test_enroll_solo_descarga_lo_nuevo_y_quita_a_quien_sobra(tmp_path: Path) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/falta.jpg":
            return httpx.Response(404)
        return httpx.Response(200, content=b"foto-" + request.url.path.strip("/").encode())

    transport = httpx.MockTransport(handler)
    analyzer = FakeAnalyzer(
        {
            b"foto-lowell.webp": [face(axis(2))],
            b"foto-logo.png": [],
            b"foto-brian": [face(axis(0))],
        }
    )
    folder = tmp_path / "faces"
    local_photos(folder, ["brian"])
    people = [
        Person("staff:brian", "Brian", "staff", photos=("fotos/brian.jpg",)),
        Person("speaker:lowell", "Lowell", "speaker", photos=("https://w.test/lowell.webp",)),
        Person("speaker:sin-cara", "Logo", "speaker", photos=("https://w.test/logo.png",)),
        Person("speaker:falta", "Falta", "speaker", photos=("https://w.test/falta.jpg",)),
    ]
    book = FaceBook(folder / "huellas" / "caras.json")
    book.add_print(Person("staff:antiguo", "Antiguo", "staff"), "x", axis(5))

    report = await enroll(book, people, analyzer, base_dir=folder, transport=transport)
    assert report.added == 2
    assert report.removed == ["Antiguo"]
    assert sorted(name for name, _ in report.failed) == ["Falta", "Logo"]
    assert {p.name for p in book.people} == {"Brian", "Lowell"}
    assert len(requests) == 3

    # Con todo hecho no se toca la red ni se vuelven a analizar las fotos.
    requests.clear()
    calls = analyzer.calls
    again = await enroll(book, people[:2], analyzer, base_dir=folder, transport=transport)
    assert (again.added, again.failed, requests, analyzer.calls) == (0, [], [], calls)


async def test_una_foto_local_que_ya_no_esta_conserva_su_huella(tmp_path: Path) -> None:
    folder = tmp_path / "faces"
    book = FaceBook(folder / "huellas" / "caras.json")
    mariel = Person("staff:mariel", "Mariel", "staff", photos=("fotos/mariel.jpg",))
    book.add_print(mariel, "fotos/mariel.jpg", axis(3))
    report = await enroll(book, [mariel], FakeAnalyzer(), base_dir=folder)
    assert report.failed == [] and len(book) == 1


async def test_ensure_models_rechaza_una_descarga_con_otra_huella(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"no-es-onnx"))
    with pytest.raises(FaceModelError, match="SHA-256"):
        await ensure_models(tmp_path / "modelos", transport=transport)
    assert not list((tmp_path / "modelos").glob("*.onnx"))


# ---------------------------------------------------------------------------
# Cuándo se avisa a Sonia
# ---------------------------------------------------------------------------


async def test_prepare_da_de_alta_y_reconoce_solo_caras_grandes_y_conocidas(
    tmp_path: Path,
) -> None:
    analyzer = reference_analyzer(
        camara=[
            face(near(0, 0.66), width=180),  # Brian, delante
            face(near(1, 0.9), width=30),  # Jean, a más de cuatro metros: no cuenta
            face(axis(9), width=200),  # un visitante
        ]
    )
    faces = watcher(tmp_path, analyzer)
    assert not faces.ready
    report = await faces.prepare(None)
    assert report.added == 2 and faces.ready
    assert faces.book.path == tmp_path / "faces" / "huellas" / "caras-arcface.json"
    assert faces.book.path.is_file()

    seen = await faces.identify(CAMERA_FRAME)
    assert [s.match.person.name for s in seen] == ["Brian James"]
    assert faces.snapshot() == {
        "ready": True,
        "people": 2,
        "staff": 2,
        "speakers": 0,
        "guests": 0,
    }


async def test_avisa_tras_dos_revisiones_y_calla_veinte_minutos(tmp_path: Path) -> None:
    faces = watcher(tmp_path, reference_analyzer(camara=[face(axis(0))]))
    await faces.prepare(None)
    brian = await faces.identify(CAMERA_FRAME)

    assert faces.due(brian, now=0.0) == []  # primera vez: aún sin confirmar
    assert [s.label for s in faces.due(brian, now=3.0)] == [
        "Brian James (del equipo de Sonnet Code, gerente de Operaciones)"
    ]
    assert faces.due(brian, now=6.0) == []
    # Sigue delante (confirmado otra vez): en su plazo no se repite.
    assert faces.due(brian, now=19 * 60) == []
    assert faces.due(brian, now=19 * 60 + 1) == []
    # Se fue y volvió: hace falta confirmar otra vez, y el plazo sigue mandando.
    assert faces.due([], now=19.5 * 60) == []
    assert faces.due(brian, now=3.0 + 20 * 60 - 1) == []
    assert len(faces.due(brian, now=3.0 + 20 * 60)) == 1


async def test_confirma_con_revisiones_salteadas_dentro_de_la_ventana(tmp_path: Path) -> None:
    # Quien habla moviendo la cabeza pasa el umbral a ratos (registro del 8 de octubre).
    faces = watcher(tmp_path, reference_analyzer(camara=[face(axis(0))]))
    await faces.prepare(None)
    brian = await faces.identify(CAMERA_FRAME)

    assert faces.due(brian, now=0.0) == []
    assert faces.due([], now=1.0) == []
    assert faces.due([], now=2.0) == []
    assert len(faces.due(brian, now=3.0)) == 1


async def test_dos_aciertos_lejanos_no_confirman(tmp_path: Path) -> None:
    faces = watcher(tmp_path, reference_analyzer(camara=[face(axis(0))]))
    await faces.prepare(None)
    brian = await faces.identify(CAMERA_FRAME)

    assert faces.confirm_window_s == 4.0
    assert faces.due(brian, now=0.0) == []
    for second in range(1, 5):
        assert faces.due([], now=float(second)) == []
    assert faces.due(brian, now=4.5) == []  # el primero ya quedó fuera de la ventana
    assert len(faces.due(brian, now=5.5)) == 1


async def test_mirando_despacio_dos_revisiones_seguidas_siempre_confirman(tmp_path: Path) -> None:
    faces = watcher(tmp_path, reference_analyzer(camara=[face(axis(0))]), scan_seconds=5.0)
    await faces.prepare(None)
    brian = await faces.identify(CAMERA_FRAME)

    assert faces.confirm_window_s == 10.0
    assert faces.due(brian, now=0.0) == []
    assert len(faces.due(brian, now=5.3)) == 1  # la revisión siguiente, con su retraso


def test_cada_modelo_tiene_sus_huellas_y_su_umbral(tmp_path: Path) -> None:
    # ArcFace por defecto; con FACES_MODEL=sface se vuelve a lo de antes sin rehacer nada.
    arcface = watcher(tmp_path, reference_analyzer())
    assert arcface.book.path.name == "caras-arcface.json"
    assert arcface.book.model == "w600k_r50.onnx" and arcface.threshold == 0.40
    sface = watcher(tmp_path, reference_analyzer(), model="sface")
    assert sface.book.path.name == "caras.json"
    assert sface.book.model == RECOGNIZER.name and sface.threshold == 0.52
    assert ARCFACE in model_files("arcface") and ARCFACE not in model_files("sface")
    assert book_path(tmp_path, "arcface") != book_path(tmp_path, "sface")


async def test_las_huellas_de_otro_modelo_no_se_mezclan(tmp_path: Path) -> None:
    sface_book = FaceBook(tmp_path / "caras.json")
    sface_book.add_print(Person("staff:brian", "Brian James", "staff"), "foto", axis(0))
    sface_book.save()
    arcface_book = FaceBook(tmp_path / "caras.json", "w600k_r50.onnx")
    arcface_book.load()  # el archivo es de SFace: no se usa
    assert len(arcface_book) == 0


# ---------------------------------------------------------------------------
# Alta con la cámara (sonia caras --alta)
# ---------------------------------------------------------------------------


def camera_sources(faces: FaceWatcher, person_id: str) -> list[str]:
    saved = json.loads(faces.book.path.read_text(encoding="utf-8"))
    prints = next(p["prints"] for p in saved["people"] if p["id"] == person_id)
    return sorted(s for s in prints if s.startswith("camara:"))


async def test_alta_con_la_camara_guarda_las_huellas_mas_distintas_y_ninguna_foto(
    tmp_path: Path,
) -> None:
    # Jean sale de seis maneras distintas, una repetida, y hay fotos que no valen.
    poses = [face(near(1, 0.70, other=10 + k)) for k in range(6)]
    analyzer = reference_analyzer(
        **{f"toma{k}": [pose] for k, pose in enumerate(poses)},
        repetida=[poses[0]],
        brian=[face(axis(0))],  # otra persona conocida delante
        nadie=[],
        otro=[face(near(1, 0.10))],  # no se parece a sus fotos
    )
    faces = watcher(tmp_path, analyzer)
    await faces.prepare(None)
    jean = faces.find("jean CALDERÓN")
    assert jean is not None
    names = [f"toma{k}" for k in range(6)] + ["repetida", "brian", "nadie", "otro"]
    report = await faces.enroll_from_camera(
        jean, [Frame(data=n.encode()) for n in names], stamp="20261008-1500", keep=4
    )

    assert (report.frames, report.faces, report.others, report.unlike) == (10, 9, 1, 1)
    assert report.kept == 4 and report.similar == pytest.approx((0.70, 0.70), abs=1e-4)
    assert camera_sources(faces, jean.id) == [f"camara:20261008-1500-{k}" for k in range(1, 5)]
    # Ninguna foto de la cámara en disco: solo huellas.
    written = [p for p in (tmp_path / "faces").rglob("*") if p.is_file() and "fotos" not in p.parts]
    assert {p.suffix for p in written} <= {".json"}


async def test_si_no_se_parece_a_sus_fotos_no_se_guarda_nada(tmp_path: Path) -> None:
    faces = watcher(tmp_path, reference_analyzer(otro=[face(near(1, 0.10))]))
    await faces.prepare(None)
    jean = faces.find("Jean Calderon")
    assert jean is not None
    before = faces.book.path.read_text(encoding="utf-8")
    report = await faces.enroll_from_camera(jean, [Frame(data=b"otro")] * 3, stamp="s")
    assert (report.unlike, report.kept) == (3, 0)
    assert faces.book.path.read_text(encoding="utf-8") == before


async def test_las_huellas_de_la_camara_se_quedan_y_viajan_en_la_app(tmp_path: Path) -> None:
    analyzer = reference_analyzer(toma=[face(near(1, 0.70, other=20))])
    dev = tmp_path / "desarrollo"
    faces = watcher(dev, analyzer)
    await faces.prepare(None)
    jean = faces.find("Jean Calderon")
    assert jean is not None
    assert (await faces.enroll_from_camera(jean, [Frame(data=b"toma")], stamp="mac")).kept == 1

    # Otra vez sonia caras: no se borran aunque no estén en staff.json.
    again = watcher(dev, analyzer)
    await again.prepare(None)
    assert camera_sources(again, jean.id) == ["camara:mac-1"]
    # En el equipo del stand, sin huellas de la cámara, la app trae las del Mac...
    stand = tmp_path / "stand"
    there = watcher(stand, analyzer, bundled_book=faces.book.path)
    await there.prepare(None)
    assert camera_sources(there, jean.id) == ["camara:mac-1"]
    # ...y si allí se da de alta con su cámara, las suyas mandan.
    await there.enroll_from_camera(jean, [Frame(data=b"toma")], stamp="stand")
    later = watcher(stand, analyzer, bundled_book=faces.book.path)
    await later.prepare(None)
    assert camera_sources(later, jean.id) == ["camara:stand-1"]


async def test_a_un_ponente_no_se_le_da_de_alta_con_la_camara(tmp_path: Path) -> None:
    # A los ponentes se les reconoce solo por su foto pública (CLAUDE.md).
    analyzer = reference_analyzer(toma=[face(axis(2))])
    analyzer.photos[b"foto-lowell.webp"] = [face(axis(2))]
    folder = tmp_path / "faces"
    local_photos(folder, ["brian", "jean"])
    faces = FaceWatcher(
        FaceSettings(dir=str(folder)),
        staff_file=staff_file(tmp_path, [BRIAN, JEAN]),
        analyzer_factory=lambda folder: analyzer,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"foto-lowell.webp")),
        models=False,
    )
    await faces.prepare(Schedule((talk("IA", "Lowell Abbott", "https://fotos.test/l.webp"),)))
    lowell = faces.find("Lowell Abbott")
    assert lowell is not None and lowell.kind == "speaker"
    report = await faces.enroll_from_camera(lowell, [Frame(data=b"toma")], stamp="s")
    assert report.kept == 0 and faces.book.camera_prints(lowell.id) == 0


def test_most_different_elige_poses_distintas_y_salta_las_repetidas() -> None:
    a, b = near(1, 0.70, other=10), near(1, 0.70, other=11)
    chosen = most_different([a, a.copy(), b, a.copy()], keep=5)
    assert len(chosen) == 2
    assert most_different([], keep=3) == [] and most_different([a], keep=0) == []


def test_parser_caras_alta() -> None:
    args = cli.build_parser().parse_args(["caras", "--alta", "Jean Calderon", "--fotos", "3"])
    assert (args.alta, args.fotos) == ("Jean Calderon", 3)
    assert cli.build_parser().parse_args(["caras"]).alta is None


async def test_quien_se_queda_cerca_del_umbral_queda_en_el_registro(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Sin esto, el registro no decía por qué no reconocía a Jean (8 de octubre).
    a, b = 0.60, 0.57
    both = axis(0) * a + axis(1) * b + axis(127) * float(np.sqrt(1 - a * a - b * b))
    analyzer = reference_analyzer(
        cerca=[face(near(1, 0.33), width=98)],
        lejos=[face(near(1, 0.20))],
        dudosa=[face(both)],
    )
    faces = watcher(tmp_path, analyzer)
    await faces.prepare(None)
    caplog.set_level(logging.INFO, logger="sonia.faces.watcher")

    assert await faces.identify(Frame(data=b"cerca")) == []
    assert await faces.identify(Frame(data=b"cerca")) == []  # una vez por minuto como mucho
    assert await faces.identify(Frame(data=b"lejos")) == []  # ni se parece: no se apunta
    assert await faces.identify(Frame(data=b"dudosa")) == []
    assert [r.getMessage() for r in caplog.records if "se parece" in r.getMessage()] == [
        "Caras: se parece a Jean Calderon pero no llega (0.33 de 0.40; cara de 98 px)",
        "Caras: se parece a Brian James pero también a otra persona (0.60 frente a 0.57; "
        "cara de 150 px)",
    ]


async def test_look_cuenta_a_quien_vio_la_revision_hace_un_momento(tmp_path: Path) -> None:
    # La revisión sola mira a resolución completa y ve más lejos que la foto de look.
    analyzer = reference_analyzer(camara=[face(axis(0))], look=[])
    faces = watcher(tmp_path, analyzer)
    await faces.prepare(None)
    faces.due(await faces.identify(CAMERA_FRAME))

    seen = await faces.seen_in(Frame(data=b"look"))
    assert [s.match.person.name for s in seen] == ["Brian James"]
    assert faces.recent(now=time.monotonic() + RECENT_S + 1) == []


async def test_las_caras_se_buscan_a_la_resolucion_de_la_camara(tmp_path: Path) -> None:
    class Usb(OpenCVCamera):
        def __init__(self) -> None:
            super().__init__(VisionSettings(source="opencv"))
            self.asked: list[tuple[int | None, int | None]] = []

        async def capture(
            self, *, max_width: int | None = None, quality: int | None = None
        ) -> Frame | None:
            self.asked.append((max_width, quality))
            return CAMERA_FRAME

    faces = watcher(tmp_path, reference_analyzer())
    usb = Usb()
    assert await faces.capture(usb) is CAMERA_FRAME
    assert usb.asked == [(1920, 90)]  # no la de 768 px de la visión
    unity = FakeCamera(data=b"camara")
    assert await faces.capture(unity) is not None and unity.captures == 1


async def test_si_sonia_usa_la_camara_se_le_dice_igual_y_el_plazo_empieza_de_nuevo(
    tmp_path: Path,
) -> None:
    faces = watcher(tmp_path, reference_analyzer(camara=[face(axis(0))]))
    await faces.prepare(None)
    brian = await faces.identify(CAMERA_FRAME)
    faces.due(brian, now=0.0)
    assert len(faces.due(brian, now=3.0)) == 1
    # Sonia mira a los 10 minutos: se le dice aunque esté en su plazo...
    assert len(faces.used(brian, now=600.0)) == 1
    # ...y los 20 minutos cuentan desde ahí.
    assert faces.due(brian, now=3.0 + 20 * 60) == []
    assert faces.due(brian, now=3.0 + 20 * 60 + 1) == []  # confirmado, pero en su plazo
    assert faces.due(brian, now=600.0 + 20 * 60 - 1) == []
    assert len(faces.due(brian, now=600.0 + 20 * 60)) == 1


async def test_un_aviso_que_no_llega_se_puede_repetir(tmp_path: Path) -> None:
    faces = watcher(tmp_path, reference_analyzer(camara=[face(axis(0))]), confirm_scans=1)
    await faces.prepare(None)
    brian = await faces.identify(CAMERA_FRAME)
    sent = faces.due(brian, now=0.0)
    faces.retract(sent)
    assert len(faces.due(brian, now=3.0)) == 1


# ---------------------------------------------------------------------------
# Quién ya pasó por el stand y saludos propios
# ---------------------------------------------------------------------------

BRIAN_LABEL = "Brian James (del equipo de Sonnet Code, gerente de Operaciones)"
JEAN_LABEL = "Jean Calderon (del equipo de Sonnet Code, CTO)"
BRIAN_GREETING = {"name": "brian JAMES", "greeting": "Pregúntale si ya montó todo el stand"}


async def test_la_primera_nota_del_dia_trae_su_saludo_y_luego_dice_que_ya_paso(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    faces = watcher(
        tmp_path,
        reference_analyzer(camara=[face(axis(0))]),
        clock=clock,
        greetings=[BRIAN_GREETING],
    )
    await faces.prepare(None)
    brian = await faces.identify(CAMERA_FRAME)
    first = (
        f"Acaba de ponerse delante de la cámara {BRIAN_LABEL}. "
        "Para saludar a Brian James: Pregúntale si ya montó todo el stand."
    )
    assert faces.arrival_note(brian) == first
    # Componer la nota no apunta nada: solo cuenta cuando llega a Sonia.
    assert faces.arrival_note(brian) == first and len(faces.visits) == 0

    await faces.remember(brian)
    clock.now = MORNING + timedelta(minutes=25)
    assert faces.arrival_note(brian) == (
        f"Está delante de la cámara {BRIAN_LABEL}, que ya pasó hoy por el stand (la primera vez, "
        "a las 10:32 de la mañana): no le saludes como si fuera la primera vez."
    )


async def test_las_visitas_sobreviven_a_reiniciar_y_al_dia_siguiente_vuelve_a_saludar(
    tmp_path: Path,
) -> None:
    analyzer = reference_analyzer(camara=[face(axis(0))])
    faces = watcher(tmp_path, analyzer, greetings=[BRIAN_GREETING])
    await faces.prepare(None)
    await faces.remember(await faces.identify(CAMERA_FRAME))
    assert (tmp_path / "faces" / "visitas.json").is_file()

    # Se reinicia el orquestador a media tarde: sigue sabiendo que vino.
    later = watcher(tmp_path, analyzer, clock=FakeClock(MORNING + timedelta(hours=5)))
    await later.prepare(None)
    assert "ya pasó hoy por el stand (la primera vez, a las 10:32 de la mañana)" in (
        later.arrival_note(await later.identify(CAMERA_FRAME))
    )

    # La memoria es por días, no por conversaciones: al día siguiente se le saluda como la
    # primera vez, con su saludo.
    tomorrow = watcher(
        tmp_path, analyzer, clock=FakeClock(MORNING + timedelta(days=1)), greetings=[BRIAN_GREETING]
    )
    await tomorrow.prepare(None)
    assert tomorrow.arrival_note(await tomorrow.identify(CAMERA_FRAME)) == (
        f"Acaba de ponerse delante de la cámara {BRIAN_LABEL}. "
        "Para saludar a Brian James: Pregúntale si ya montó todo el stand."
    )


async def test_varias_personas_unas_nuevas_y_otras_que_ya_pasaron(tmp_path: Path) -> None:
    clock = FakeClock()
    analyzer = reference_analyzer(
        camara=[face(axis(0)), face(axis(1), width=120)], brian=[face(axis(0))]
    )
    greetings = [{"name": "Jean Calderón", "greeting": "Es el CTO: ni lo presentes."}]
    faces = watcher(tmp_path, analyzer, clock=clock, greetings=greetings)
    await faces.prepare(None)
    await faces.remember(await faces.identify(Frame(data=b"brian")))
    clock.now = MORNING + timedelta(hours=1)
    both = await faces.identify(CAMERA_FRAME)
    assert faces.arrival_note(both) == (
        f"Acaba de ponerse delante de la cámara {JEAN_LABEL}. Para saludar a Jean Calderon: Es "
        f"el CTO: ni lo presentes. Está delante de la cámara {BRIAN_LABEL}, que ya pasó hoy por "
        "el stand (la primera vez, a las 10:32 de la mañana): no le saludes como si fuera la "
        "primera vez."
    )
    assert faces.known_note(both) == (
        f"Personas conocidas en la foto: {BRIAN_LABEL} y {JEAN_LABEL}. Brian James ya pasó hoy "
        "por el stand (la primera vez, a las 10:32 de la mañana): no le saludes como si fuera la "
        "primera vez. Para saludar a Jean Calderon: Es el CTO: ni lo presentes."
    )
    await faces.remember(both)
    clock.now = MORNING + timedelta(hours=2)
    assert faces.arrival_note(both) == (
        f"Están delante de la cámara {BRIAN_LABEL} y {JEAN_LABEL}, que ya pasaron hoy por el "
        "stand: no les saludes como si fuera la primera vez."
    )


async def test_un_saludo_para_alguien_que_no_conoce_se_avisa_y_no_cuenta(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    greetings = [
        {"name": "Nadie Conocido", "greeting": "hola"},
        {"name": "Jean Calderon", "greeting": "   "},  # vacío: no cuenta
        BRIAN_GREETING,
    ]
    faces = watcher(tmp_path, reference_analyzer(), greetings=greetings)
    with caplog.at_level("WARNING"):
        await faces.prepare(None)
    assert faces.greetings == {"staff:brian-james": "Pregúntale si ya montó todo el stand"}
    assert faces.own_greetings == {"staff:brian-james"}
    assert "nadie-conocido" in caplog.text
    assert load_greetings(tmp_path / "no-existe.json") == Greetings()


LOWELL = Person(
    "speaker:lowell-abbott", "Lowell Abbott", "speaker", "«Blockchain sin perder la cabeza»"
)
LOWELL_LABEL = "Lowell Abbott (ponente del DevFest: «Blockchain sin perder la cabeza»)"
#: Su charla de verdad: viernes 9 de octubre de 10:40 a 11:20 de la mañana.
LOWELL_TALK = datetime(2026, 10, 9, 10, 40, tzinfo=SANTO_DOMINGO)


def lowell_schedule(*extra: Talk) -> Schedule:
    talk = Talk(
        id="blockchain",
        title="Blockchain sin perder la cabeza",
        starts_at=LOWELL_TALK,
        ends_at=LOWELL_TALK + timedelta(minutes=40),
        speaker="Lowell Abbott",
    )
    return Schedule((talk, *extra))


def test_la_nota_de_un_ponente_dice_si_ya_dio_su_charla() -> None:
    seen = [Sighting(Match(LOWELL, 0.8), 150)]
    schedule = lowell_schedule()
    # La prueba real del 7 de octubre: dos días antes. Sonia le preguntó «¿qué tal te fue?».
    wednesday = datetime(2026, 10, 7, 14, 55, tzinfo=SANTO_DOMINGO)
    assert arrival_text(seen, now=wednesday, schedule=schedule) == (
        f"Acaba de ponerse delante de la cámara {LOWELL_LABEL}. La charla de Lowell Abbott es "
        "pasado mañana (el viernes 9 de octubre) a las 10:40 de la mañana: todavía no la ha dado."
    )
    # El día relativo va ya hecho: con solo «el viernes 9», GPT-Live dijo «mañana».
    assert "es dentro de 3 días (el viernes 9 de octubre)" in arrival_text(
        seen, now=wednesday - timedelta(days=1), schedule=schedule
    )
    assert "ya dio su charla hace 4 días (el viernes 9 de octubre)" in arrival_text(
        seen, now=LOWELL_TALK + timedelta(days=4), schedule=schedule
    )
    hour = timedelta(hours=1)
    assert "es mañana a las 10:40 de la mañana: todavía no la ha dado." in arrival_text(
        seen, now=LOWELL_TALK - 20 * hour, schedule=schedule
    )
    assert "es hoy a las 10:40 de la mañana: todavía no la ha dado." in arrival_text(
        seen, now=LOWELL_TALK - hour, schedule=schedule
    )
    assert "es ahora mismo, hasta las 11:20 de la mañana." in arrival_text(
        seen, now=LOWELL_TALK + hour / 6, schedule=schedule
    )
    assert "Lowell Abbott ya dio su charla hoy a las 10:40 de la mañana." in arrival_text(
        seen, now=LOWELL_TALK + 2 * hour, schedule=schedule
    )
    # También cuando Sonia mira con la cámara, y al día siguiente.
    assert "Lowell Abbott ya dio su charla ayer a las 10:40 de la mañana." in known_text(
        seen, now=LOWELL_TALK + 24 * hour, schedule=schedule
    )
    # Sin agenda, la nota de siempre.
    assert arrival_text(seen, now=wednesday) == (
        f"Acaba de ponerse delante de la cámara {LOWELL_LABEL}."
    )


def test_un_ponente_con_varias_charlas_o_compartidas() -> None:
    seen = [Sighting(Match(LOWELL, 0.8), 150)]
    panel = Talk(
        id="panel",
        title="Panel de Web3",
        starts_at=LOWELL_TALK + timedelta(days=1),
        ends_at=LOWELL_TALK + timedelta(days=1, hours=1),
        speaker="Ana Pérez y Lowell Abbott",
    )
    note = arrival_text(seen, now=LOWELL_TALK + timedelta(hours=2), schedule=lowell_schedule(panel))
    assert "Lowell Abbott ya dio su charla «Blockchain sin perder la cabeza» hoy" in note
    assert (
        "La charla «Panel de Web3» de Lowell Abbott es mañana a las 10:40 de la mañana: "
        "todavía no la ha dado." in note
    )


async def test_la_nota_usa_la_agenda_de_ahora(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 10, 9, 9, 0, tzinfo=SANTO_DOMINGO))
    faces = watcher(tmp_path, reference_analyzer(camara=[face(axis(0))]), clock=clock)
    await faces.prepare(None)
    brian = await faces.identify(CAMERA_FRAME)
    assert "charla" not in faces.arrival_note(brian)
    # Alguien del equipo que también da una charla, con la agenda que lleva el motor.
    talk = Talk(
        id="ops",
        title="Operaciones",
        starts_at=datetime(2026, 10, 9, 15, 0, tzinfo=SANTO_DOMINGO),
        ends_at=datetime(2026, 10, 9, 15, 40, tzinfo=SANTO_DOMINGO),
        speaker="Brian James",
    )
    faces.follow_agenda(lambda: Schedule((talk,)))
    assert faces.arrival_note(brian).endswith(
        "La charla de Brian James es hoy a las 3:00 de la tarde: todavía no la ha dado."
    )


def test_visit_log_guarda_el_primero_de_cada_dia(tmp_path: Path) -> None:
    log = VisitLog(tmp_path / "visitas.json")
    log.record("staff:brian-james", "Brian James", MORNING)
    log.record("staff:brian-james", "Brian James", MORNING + timedelta(hours=2))
    log.save()
    again = VisitLog(tmp_path / "visitas.json")
    again.load()
    visit = again.get("staff:brian-james")
    assert visit is not None and (visit.day_first, visit.count) == (MORNING, 2)
    again.record("staff:brian-james", "Brian James", MORNING + timedelta(days=1))
    visit = again.get("staff:brian-james")
    assert visit is not None and visit.day_first == MORNING + timedelta(days=1)

    (tmp_path / "visitas.json").write_text("{roto", encoding="utf-8")
    broken = VisitLog(tmp_path / "visitas.json")
    broken.load()
    assert len(broken) == 0


async def test_olvidar_visitas(tmp_path: Path) -> None:
    faces = watcher(tmp_path, reference_analyzer(camara=[face(axis(0))]))
    await faces.prepare(None)
    await faces.remember(await faces.identify(CAMERA_FRAME))
    assert await faces.forget_visits() == 1
    again = VisitLog(tmp_path / "faces" / "visitas.json")
    again.load()
    assert len(again) == 0


def test_los_saludos_e_invitados_del_repo_se_leen() -> None:
    greetings = load_greetings(REPO_ROOT / "assets" / "faces" / "saludos.json")
    assert {"staff", "speaker"} <= set(greetings.groups)
    assert "charla" in greetings.groups["speaker"]
    assert {"victor-duran", "wanda-custodio"} <= set(greetings.people)
    assert "moto" in greetings.people["victor-duran"]
    assert "laboratorio de innovación" in greetings.people["wanda-custodio"]
    guests = load_staff(REPO_ROOT / "assets" / "faces" / "invitados.json", kind="guest")
    assert {"guest:victor-duran", "guest:wanda-custodio"} <= {p.id for p in guests}
    assert all(p.kind == "guest" for p in guests)
    # Toda persona conocida con saludo propio tiene que casar con alguien de la lista.
    assert set(greetings.people) <= {p.id.removeprefix("guest:") for p in guests}
    assert all(photo.startswith("fotos/") for p in guests for photo in p.photos)


async def test_saludo_de_grupo_para_quien_no_tiene_uno_propio(tmp_path: Path) -> None:
    analyzer = reference_analyzer(camara=[face(axis(0)), face(axis(1), width=120)])
    groups = {"staff": "Pregúntale algo sobre lo que hace en Sonnet Code."}
    faces = watcher(tmp_path, analyzer, greetings=[BRIAN_GREETING], groups=groups)
    await faces.prepare(None)
    both = await faces.identify(CAMERA_FRAME)
    assert faces.arrival_note(both) == (
        f"Acaban de ponerse delante de la cámara {BRIAN_LABEL} y {JEAN_LABEL}. Para saludar a "
        "Brian James: Pregúntale si ya montó todo el stand. Para saludar a Jean Calderon: "
        "Pregúntale algo sobre lo que hace en Sonnet Code."
    )
    assert faces.own_greetings == {"staff:brian-james"}


async def test_una_persona_conocida_se_presenta_como_tal(tmp_path: Path) -> None:
    folder = tmp_path / "faces"
    local_photos(folder, ["victor"])
    analyzer = reference_analyzer(camara=[face(axis(5))], **{"foto-victor": [face(axis(5))]})
    guests = [{"name": "Victor Duran", "photos": ["fotos/victor.jpg"]}]
    greetings = [{"name": "Víctor Durán", "greeting": "Pregúntale si vino en la moto."}]
    faces = watcher(tmp_path, analyzer, guests=guests, greetings=greetings)
    await faces.prepare(None)
    assert faces.snapshot()["guests"] == 1
    victor = await faces.identify(CAMERA_FRAME)
    assert faces.arrival_note(victor) == (
        "Acaba de ponerse delante de la cámara Victor Duran (persona conocida del equipo de "
        "Sonnet Code). Para saludar a Victor Duran: Pregúntale si vino en la moto."
    )


async def test_la_app_trae_las_huellas_de_quien_se_dio_de_alta_con_fotos_locales(
    tmp_path: Path,
) -> None:
    # En el Mac de desarrollo: Victor se da de alta con su foto local.
    dev = tmp_path / "desarrollo"
    local_photos(dev / "faces", ["victor"])
    analyzer = reference_analyzer(camara=[face(axis(5))], **{"foto-victor": [face(axis(5))]})
    guests = [{"name": "Victor Duran", "photos": ["fotos/victor.jpg"]}]
    built = watcher(dev, analyzer, guests=guests)
    await built.prepare(None)
    bundled = built.book.path
    assert "guest:victor-duran" in {p.id for p in built.book.people}

    # En el equipo del stand ya había huellas de antes (la app no las pisa) y no está su foto.
    stand = tmp_path / "stand"
    old = watcher(stand, reference_analyzer())
    await old.prepare(None)
    (stand / "faces" / "fotos" / "victor.jpg").unlink(missing_ok=True)
    faces = watcher(stand, analyzer, guests=guests, bundled_book=bundled)
    await faces.prepare(None)
    assert [s.match.person.name for s in await faces.identify(CAMERA_FRAME)] == ["Victor Duran"]


# ---------------------------------------------------------------------------
# Con el motor GPT-Live
# ---------------------------------------------------------------------------


async def test_el_motor_avisa_una_vez_de_quien_llega(tmp_path: Path) -> None:
    analyzer = reference_analyzer(camara=[face(axis(0)), face(axis(1), width=120)])
    faces = watcher(tmp_path, analyzer, scan_seconds=0.02)
    camera = FakeCamera(data=b"camara")
    async with make_rig(
        tmp_path, camera=camera, faces=faces, vision_source="opencv", on_turn_start=False
    ) as rig:
        conn = await rig.conn()
        instructions = conn.start["session"]["instructions"]
        assert "Tu cámara reconoce sola a las personas del equipo de Sonnet Code" in instructions
        await conn.wait_type("session.thinking.append")
        await wait_until(lambda: camera.captures >= 8)
        notes = [m["content"] for m in conn.of_type("session.thinking.append")]
        assert notes == [
            "[Cámara] Acaban de ponerse delante de la cámara Brian James (del equipo de "
            "Sonnet Code, gerente de Operaciones) y Jean Calderon (del equipo de Sonnet Code, "
            "CTO)."
        ]
        # La nota llegó: quedan apuntados para no saludarles otra vez como nuevos.
        await wait_until(lambda: len(faces.visits) == 2)
        assert (tmp_path / "faces" / "visitas.json").is_file()


async def test_look_dice_quien_sale_en_la_foto_aunque_ya_se_avisara(tmp_path: Path) -> None:
    analyzer = reference_analyzer(camara=[face(axis(0))])
    faces = watcher(tmp_path, analyzer, scan_seconds=0.02, confirm_scans=1)
    camera = FakeCamera(data=b"camara")
    async with make_rig(
        tmp_path, camera=camera, faces=faces, vision_source="opencv", on_turn_start=False
    ) as rig:
        conn = await rig.conn()
        assert "look" in tool_names(conn.start["session"]["delegation"]["responses"]["tools"])
        await conn.wait_type("session.thinking.append")
        await conn.response_event(
            {
                "type": "response.output_item.done",
                "item": {"type": "function_call", "call_id": "c", "name": "look", "arguments": ""},
            }
        )
        await conn.response_event({"type": "response.completed"})
        await conn.wait_type("response.create")
        output = conn.of_type("response.item.create")[0]["item"]["output"]
        # La revisión sola ya le avisó: la foto lo dice para que no le salude otra vez.
        assert output == (
            "Captura tomada. Personas conocidas en la foto: Brian James (del equipo de Sonnet "
            "Code, gerente de Operaciones). Brian James ya pasó hoy por el stand (la primera "
            "vez, a las 10:32 de la mañana): no le saludes como si fuera la primera vez."
        )


async def test_sin_sesion_no_se_mira_la_camara(tmp_path: Path) -> None:
    faces = watcher(tmp_path, reference_analyzer(camara=[face(axis(0))]), scan_seconds=0.02)
    camera = FakeCamera(data=b"camara")
    async with make_rig(
        tmp_path, camera=camera, faces=faces, vision_source="opencv", on_turn_start=False
    ) as rig:
        await rig.conn()
        await wait_until(lambda: camera.captures > 0)
        await rig.engine.set_active(False)
        await wait_until(lambda: not rig.engine.connected)
        await asyncio.sleep(0.1)  # una revisión que ya estuviera en marcha
        before = camera.captures
        await asyncio.sleep(0.2)  # unas diez revisiones
        assert camera.captures == before


# ---------------------------------------------------------------------------
# Instrucciones, CLI y app
# ---------------------------------------------------------------------------


def test_las_reglas_de_caras_solo_van_si_reconoce_y_sin_marcas(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, vision_source="opencv", on_turn_start=False)
    with_faces = build_session_config(settings, registry=None, gallery_ids=[], faces=True)
    without = build_session_config(settings, registry=None, gallery_ids=[])
    backend = with_faces["delegation"]["responses"]["instructions"]
    assert "Personas conocidas en la foto" in backend
    assert "reconoce al equipo de Sonnet Code y a los ponentes" in with_faces["instructions"]
    assert "Tu cámara reconoce sola" not in without["instructions"]
    # «¿Me reconoces?» sin nota: mira antes de contestar (8 de octubre: «no sé quién eres»).
    registry = build_default_registry(include_look=True)
    with_look = build_session_config(settings, registry=registry, gallery_ids=[], faces=True)
    delegate = with_look["instructions"].split("Delegate to the backend when:")[1]
    assert "Te pregunten si les reconoces" in delegate.split("Do not delegate")[0]
    plain = build_session_config(settings, registry=registry, gallery_ids=[])
    assert "Te pregunten si les reconoces" not in plain["instructions"]
    # Quién ya pasó por el stand y el saludo propio.
    assert "ya pasó hoy por el stand" in with_faces["instructions"]
    assert "Para saludar a" in with_faces["instructions"]
    assert "ya pasaron hoy por el stand" in backend
    assert "Personas conocidas en la foto" not in without["delegation"]["responses"]["instructions"]
    for brand in ("OpenCV", "YuNet", "SFace", "ONNX"):
        assert brand not in with_faces["instructions"] and brand not in backend


def cli_settings(tmp_path: Path, **faces: Any) -> Settings:
    values: dict[str, Any] = {"dir": str(tmp_path / "faces")}
    values.update(faces)
    return cli_make_settings(
        tmp_path, vision=VisionSettings(source="opencv"), faces=FaceSettings(**values)
    )


async def test_check_dice_si_faltan_los_modelos_o_esta_apagado(tmp_path: Path) -> None:
    off = await cli.check_faces(cli_settings(tmp_path, enabled=False))
    assert (off.ok, off.critical) == (True, False) and "FACES_ENABLED=false" in off.detail
    missing = await cli.check_faces(cli_settings(tmp_path))
    assert (missing.ok, missing.critical) == (False, False)
    assert "sonia caras" in missing.detail


def test_build_faces_respeta_el_interruptor_y_la_camara(tmp_path: Path) -> None:
    assert cli.build_faces(cli_settings(tmp_path)) is not None
    assert cli.build_faces(cli_settings(tmp_path, enabled=False)) is None
    assert cli.build_faces(cli_make_settings(tmp_path)) is None  # VISION_SOURCE=none


def test_parser_caras() -> None:
    args = cli.build_parser().parse_args(["caras"])
    assert (args.command, args.probar, args.olvidar_visitas) == ("caras", False, False)
    assert cli.build_parser().parse_args(["caras", "--probar"]).probar is True
    assert cli.build_parser().parse_args(["caras", "--olvidar-visitas"]).olvidar_visitas is True


def test_la_app_lleva_modelos_y_huellas_pero_no_fotos() -> None:
    assert "cache/faces/modelos" in SEEDED and "cache/faces/huellas" in SEEDED
    assert not any("fotos" in folder for folder in SEEDED)


async def test_sin_agenda_se_conservan_los_ponentes_que_ya_estaban(tmp_path: Path) -> None:
    analyzer = reference_analyzer()
    analyzer.photos[b"foto-lowell.webp"] = [face(axis(2))]
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"foto-lowell.webp")
    )
    folder = tmp_path / "faces"
    local_photos(folder, ["brian", "jean"])
    faces = FaceWatcher(
        FaceSettings(dir=str(folder)),
        staff_file=staff_file(tmp_path, [BRIAN, JEAN]),
        analyzer_factory=lambda folder: analyzer,
        transport=transport,
        models=False,
    )
    schedule = Schedule((talk("IA", "Lowell Abbott", "https://fotos.test/lowell.webp"),))
    await faces.prepare(schedule)
    assert len(faces.book) == 3

    again = FaceWatcher(
        FaceSettings(dir=str(folder)),
        staff_file=staff_file(tmp_path, [BRIAN, JEAN]),
        analyzer_factory=lambda folder: analyzer,
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        models=False,
    )
    report = await again.prepare(None)
    assert (report.removed, report.failed) == ([], [])
    assert {p.name for p in again.book.people} == {"Brian James", "Jean Calderon", "Lowell Abbott"}


def test_los_titulos_largos_se_recortan_en_la_nota() -> None:
    title = "EL CÓDIGO YA NO ES EL CUELLO DE BOTELLA Spec-Driven Development: el próximo salto"
    speaker = speakers_from(Schedule((talk(title, "Carlos Paulino", "https://f.test/c.webp"),)))[0]
    assert speaker.role.startswith("«EL CÓDIGO YA NO ES") and speaker.role.endswith("…»")
    assert len(speaker.role) <= 72


async def test_en_una_videollamada_no_mira_sola(tmp_path: Path) -> None:
    faces = watcher(tmp_path, reference_analyzer(camara=[face(axis(0))]), scan_seconds=0.02)
    camera = FakeCamera(data=b"camara")
    async with make_rig(
        tmp_path, camera=camera, faces=faces, vision_source="obs", on_turn_start=False
    ) as rig:
        await rig.conn()
        await wait_until(lambda: faces.ready)
        await asyncio.sleep(0.2)
        assert camera.captures == 0
