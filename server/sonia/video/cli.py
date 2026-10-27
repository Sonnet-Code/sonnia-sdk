"""Línea de órdenes de Sonnia Video (``sonnia-video``, ``docs/video.md``).

- ``render guion.toml``: el vídeo de un guion (MP4 y SRT).
- ``decir "texto"``: lo mismo con el texto en la línea de órdenes (una frase por oración).
- ``foto [guion.toml]``: fotos de Sonnia (con un gesto, en un momento o en ráfaga).
- ``vista [guion.toml]``: una imagen rápida de la escena, sin voz.
- ``ejemplo``: un guion de ejemplo con todas las opciones.
- ``voces [gemini|elevenlabs]``, ``gestos``: lo que se puede elegir.
- ``estado``, ``cerrar``: el renderizador (la app de Unity que se queda abierta).

Los flags pisan lo del guion. Nada de esto imprime las claves.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from sonia.video.errors import VideoError
from sonia.video.home import ELEVENLABS_KEY, home, load_env
from sonia.video.renderer import Cancelled, RendererClient
from sonia.video.script import (
    EXAMPLE,
    Overrides,
    Script,
    apply_overrides,
    load_script,
    script_from_text,
    title_of,
)

__all__ = ["build_parser", "main"]

logger = logging.getLogger("sonia.video")


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.levelno >= logging.WARNING:
            return f"aviso: {message}"
        return f"· {message}"


def _setup_logging(verbose: bool) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_Formatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG if verbose else logging.WARNING)
    logging.getLogger("sonia.video").setLevel(logging.DEBUG if verbose else logging.INFO)
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _scene_flags() -> argparse.ArgumentParser:
    flags = argparse.ArgumentParser(add_help=False)
    group = flags.add_argument_group("escena (pisa lo del guion)")
    group.add_argument("--out", type=Path, help="carpeta de salida (por defecto, la de datos)")
    group.add_argument("--titulo", help="nombre de los archivos")
    group.add_argument("--formato", help="vertical, cuadrado, horizontal, 4k-vertical o ANCHOxALTO")
    group.add_argument("--luz", help="stand, estudio, suave, calida, fria o dramatica")
    group.add_argument(
        "--fondo",
        help="stand, color, degradado, imagen, transparente, un color (#000000) o una imagen",
    )
    group.add_argument("--encuadre", help="stand, primer-plano, medio, americano o cuerpo")
    group.add_argument("--emocion", choices=["alegre", "neutra"])
    return flags


def _video_flags() -> argparse.ArgumentParser:
    flags = argparse.ArgumentParser(add_help=False)
    group = flags.add_argument_group("vídeo (pisa lo del guion)")
    group.add_argument(
        "--voz", metavar="MOTOR:VOZ", help="gemini:Leda, elevenlabs:Nombre, archivo:voz.wav"
    )
    group.add_argument("--fps", type=int)
    group.add_argument("--calidad", choices=["borrador", "normal", "alta"])
    group.add_argument("--sin-gestos", action="store_true", help="sin gestos")
    group.add_argument(
        "--reel",
        type=Path,
        help="carpeta de un reel de media/reels/<id>: fondo transparente y el paquete "
        "sonnia/ en <reel>/assets/sonnia/",
    )
    group.add_argument(
        "--forzar", action="store_true", help="reemplaza los cuadros que ya haya en el reel"
    )
    return flags


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sonnia-video",
        description="Vídeos y fotos de Sonnia para redes sociales, sin abrir Unity (docs/video.md).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="más detalle")
    commands = parser.add_subparsers(dest="command", metavar="orden")
    scene = _scene_flags()
    video = _video_flags()

    render = commands.add_parser("render", parents=[scene, video], help="vídeo de un guion TOML")
    render.add_argument("guion", type=Path)
    decir = commands.add_parser("decir", parents=[scene, video], help="vídeo de un texto suelto")
    decir.add_argument("texto")
    foto = commands.add_parser("foto", parents=[scene], help="fotos de Sonnia (PNG), sin voz")
    foto.add_argument("guion", type=Path, nargs="?")
    foto.add_argument("--gesto", default="", help="un gesto del catálogo (sonnia-video gestos)")
    foto.add_argument("--espejo", action="store_true", help="el gesto con la otra mano")
    foto.add_argument(
        "--momento",
        type=float,
        help="segundo del gesto en que sale la foto (por defecto, su golpe)",
    )
    foto.add_argument(
        "--rafaga", type=int, default=1, metavar="N", help="N fotos repartidas por el gesto"
    )
    vista = commands.add_parser("vista", parents=[scene], help="imagen rápida de la escena")
    vista.add_argument("guion", type=Path, nargs="?")
    vista.add_argument("--png", type=Path, help="dónde guardar la imagen")
    commands.add_parser("ejemplo", help="imprime un guion de ejemplo con todas las opciones")
    voces = commands.add_parser("voces", help="voces que se pueden usar")
    voces.add_argument("motor", nargs="?", choices=["gemini", "elevenlabs"])
    commands.add_parser("gestos", help="gestos del catálogo (abre el renderizador)")
    commands.add_parser("estado", help="estado del renderizador")
    commands.add_parser("cerrar", help="cierra el renderizador")
    return parser


def _overrides(args: argparse.Namespace) -> Overrides:
    return Overrides(
        voice=getattr(args, "voz", None),
        format=args.formato,
        fps=getattr(args, "fps", None),
        quality=getattr(args, "calidad", None),
        light=args.luz,
        background=args.fondo,
        framing=args.encuadre,
        emotion=args.emocion,
        no_gestures=getattr(args, "sin_gestos", False),
        title=args.titulo,
        reel=str(args.reel) if getattr(args, "reel", None) else None,
    )


def _seconds(value: float) -> str:
    return f"{value:.1f} s".replace(".", ",")


def _render(script: Script, args: argparse.Namespace) -> int:
    from sonia.video.pipeline import Pipeline

    script = apply_overrides(script, _overrides(args))
    pipeline = Pipeline.default()
    result = pipeline.render(script, args.out, force=bool(getattr(args, "forzar", False)))
    take = result.take
    print(f"Listo: {result.video} ({_seconds(result.duration_s)})")
    print(f"Subtítulos: {result.srt}")
    if result.package is not None:
        frames = len(result.package.frame_files())
        print(f"Paquete para reels: {result.package.root} ({frames} cuadros)")
    origin = "de la caché, sin coste" if take.cached else "nueva"
    print(f"Voz: {take.engine} · {take.voice} ({origin}) · tiempos: {take.timing}")
    if result.gestures:
        listed = ", ".join(f"{uid}: {cue.name}" for uid, cue in sorted(result.gestures.items()))
        print(f"Gestos por frase: {listed}")
    else:
        print("Gestos: ninguno")
    report = result.report
    source = {"heard.wav": "lo que sonó en Unity", "heard_t": "el registro de Unity"}.get(
        report.delay_source, "sin medir"
    )
    print(f"Voz colocada en {_seconds(report.voice_at)} ({source})")
    if report.lag_frames is not None and report.correlation is not None:
        print(
            f"Sincronía boca-voz: desfase {report.lag_frames:+d} cuadros "
            f"(correlación {report.correlation:.2f})".replace(".", ",")
        )
    for note in result.notes:
        logger.warning("%s", note)
    if result.snippet:
        print("\nPara el reel:\n")
        print(result.snippet)
    return 0


def _foto(args: argparse.Namespace) -> int:
    from sonia.video.pipeline import Pipeline

    script = load_script(args.guion) if args.guion else script_from_text("Hola.")
    script = apply_overrides(script, _overrides(args))
    pipeline = Pipeline.default()
    paths = pipeline.photos(
        script,
        args.out,
        gesture=args.gesto,
        mirror=args.espejo,
        moment=args.momento,
        burst=args.rafaga,
        title=args.titulo or "",
    )
    for path in paths:
        print(f"Foto: {path}")
    return 0


def _vista(args: argparse.Namespace) -> int:
    from sonia.video.pipeline import Pipeline, default_out

    script = load_script(args.guion) if args.guion else script_from_text("Hola.")
    script = apply_overrides(script, _overrides(args))
    out = args.png or (args.out or default_out()) / f"{title_of(script)}-vista.png"
    pipeline = Pipeline.default()
    print(f"Vista previa: {pipeline.still(script, out)}")
    return 0


def _voces(motor: str | None) -> int:
    import os

    from sonia.video.gemini import KNOWN_VOICES

    if motor in (None, "gemini"):
        print('Gemini (motor = "gemini"; cualquier otra voz que acepte Gemini vale igual):')
        for name, description in KNOWN_VOICES:
            print(f"  {name:<22} {description}")
    if motor in (None, "elevenlabs"):
        if motor is None and not os.environ.get(ELEVENLABS_KEY, "").strip():
            print(f"\nElevenLabs: pon {ELEVENLABS_KEY} en {home() / '.env'} para ver sus voces.")
            return 0
        from sonia.video.voice import VoiceCache, VoiceMaker

        async def listed() -> list[tuple[str, str, str]]:
            maker = VoiceMaker(VoiceCache(home() / "cache"))
            async with maker.eleven_client() as client:
                return [(v.name, v.voice_id, v.summary) for v in await client.voices()]

        voices = asyncio.run(listed())
        print('\nElevenLabs (motor = "elevenlabs"; voz = nombre o voice_id):')
        for name, voice_id, summary in voices:
            print(f"  {name:<30} {voice_id}  {summary}")
        if not voices:
            print("  (la cuenta no tiene voces)")
    return 0


def _gestos() -> int:
    from sonia.video.pipeline import Pipeline

    catalog = Pipeline.default().catalog()
    if not len(catalog):
        print("El renderizador no tiene gestos.")
        return 0
    print(f'{len(catalog)} gestos de {catalog.character or "Sonnia"} (gesto = "nombre"):')
    for gesture in sorted(catalog, key=lambda g: g.name.lower()):
        meta = [gesture.frequency]
        if gesture.timing:
            meta.append(gesture.timing)
        print(
            f"  {gesture.name:<28} {', '.join(meta):<18} {' '.join(gesture.description.split())[:90]}"
        )
    return 0


def _estado() -> int:
    from sonia.video.ffmpeg import find_ffmpeg

    try:
        ffmpeg = find_ffmpeg()
    except VideoError as exc:
        ffmpeg = str(exc)
    print(f"Carpeta de datos: {home()}")
    print(f"ffmpeg: {ffmpeg}")
    with RendererClient() as client:
        status = client.status()
    if status is None:
        print("El renderizador no está abierto.")
        return 0
    avatar = {"loading": "cargando", "ready": "listo"}
    outfit = {"staff": "camiseta del staff", "plain": "camiseta lisa"}
    print(
        f"Sonnia Video {status.get('version', '?')} · avatar "
        f"{avatar.get(str(status.get('avatar')), status.get('avatar'))}"
        f" · {outfit.get(str(status.get('outfit')), 'camiseta ?')}"
        f" · {'ocupado' if status.get('busy') else 'libre'}"
    )
    job = status.get("job")
    if isinstance(job, dict):
        print(
            f"Último trabajo: {job.get('id')} ({job.get('kind')}) · {job.get('state')} · "
            f"cuadro {job.get('frame', 0)}/{job.get('frames', 0)}"
        )
        if job.get("error"):
            print(f"  error: {job['error']}")
    return 0


def _cerrar() -> int:
    with RendererClient() as client:
        if client.status() is None:
            print("El renderizador no estaba abierto.")
        elif client.quit():
            print("Renderizador cerrado.")
        else:
            print("El renderizador no contestó.")
    return 0


def _run(args: argparse.Namespace) -> int:
    command = args.command
    if command == "ejemplo":
        sys.stdout.write(EXAMPLE)
        return 0
    if command == "render":
        return _render(load_script(args.guion), args)
    if command == "decir":
        return _render(script_from_text(args.texto), args)
    if command == "vista":
        return _vista(args)
    if command == "foto":
        return _foto(args)
    if command == "voces":
        return _voces(args.motor)
    if command == "gestos":
        return _gestos()
    if command == "estado":
        return _estado()
    if command == "cerrar":
        return _cerrar()
    raise AssertionError(command)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    _setup_logging(args.verbose)
    load_env()
    try:
        return _run(args)
    except Cancelled as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 130
    except KeyboardInterrupt:
        print("\nCancelado.", file=sys.stderr)
        return 130
    except VideoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
