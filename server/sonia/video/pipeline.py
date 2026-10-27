"""El recorrido entero de un vídeo, de guion a MP4 (o MOV con alfa) y SRT, y las fotos.

Lo usa la línea de órdenes (``cli``).

1. Comprueba el guion y lanza el renderizador si no está abierto, con la camiseta pedida
   (carga el avatar mientras se hace la voz).
2. La toma de voz con sus tiempos (``voice``) y el plan (``plan``).
3. Con el avatar listo, el catálogo de gestos, los gestos de cada frase (``gestures``)
   y la línea de tiempo.
4. El trabajo a Unity (``renderer``), que deja el vídeo mudo y su ``registro.json``. Con
   fondo transparente, en la misma pasada, el ``.mov`` ProRes 4444 y los cuadros PNG del
   paquete ``sonnia/`` para los reels (``reel``).
5. La voz colocada y normalizada (``ffmpeg.finish``), los subtítulos (``srt``) y, con
   fondo transparente, el resto del paquete.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sonia.gestures.catalog import Gesture, GestureCatalog
from sonia.video import ffmpeg as ff
from sonia.video.errors import VideoError
from sonia.video.gemini import style_for
from sonia.video.gestures import (
    ScriptPhrase,
    choose_gestures,
    gesture_llm,
    resolve_names,
    schedule,
)
from sonia.video.home import ELEVENLABS_KEY, GEMINI_KEY, home
from sonia.video.plan import (
    STAGE_MODE,
    GestureCue,
    Plan,
    build_plan,
    build_timeline,
    write_unity_wavs,
)
from sonia.video.reel import Package, locator, package_for, snippet, voice_info, words_json
from sonia.video.renderer import (
    STALL_RESTART_S,
    AvatarTimeout,
    Progress,
    RendererClient,
    ensure_started,
    quit_and_wait,
    run_job,
    wait_ready,
)
from sonia.video.script import (
    OUTFITS,
    Quality,
    Script,
    check_files,
    phrase_texts,
    quality,
    scene_message,
    slug,
    title_of,
    video_size,
)
from sonia.video.srt import SrtWord, build_cues, format_srt
from sonia.video.voice import Take, VoiceCache, VoiceMaker

__all__ = [
    "PHOTO_QUALITY",
    "Pipeline",
    "RenderResult",
    "build_job",
    "job_dir",
    "photo_times",
    "unity_log",
]

logger = logging.getLogger(__name__)

#: Segundos simulados antes del cuadro 0 (el avatar se asienta en su reposo).
WARMUP_S = 2.0
#: Trabajos que se guardan en la carpeta de datos (los más nuevos).
KEEP_JOBS = 10
#: Las fotos: supermuestreo ×3 y sin desenfoque de movimiento.
PHOTO_QUALITY = Quality(supersample=3, subframes=1, shutter=0.5, crf=14, preset="slow")
#: Sin gesto, una ráfaga se reparte por estos segundos de reposo.
IDLE_BURST_S = 3.0


def unity_log() -> Path:
    return home() / "unity.log"


def job_dir(job_id: str) -> Path:
    return home() / "trabajos" / job_id


def default_out() -> Path:
    return home() / "videos"


def outfit_of(script: Script) -> str:
    """La camiseta en los nombres del contrato (``staff`` o ``plain``)."""
    return OUTFITS[script.scene.outfit]


def build_job(
    *,
    job_id: str,
    kind: str,
    output_dir: Path,
    script: Script,
    duration_s: float,
    timeline: list[dict[str, Any]],
    ffmpeg: str,
    still_path: Path | None = None,
    stills: list[dict[str, Any]] | None = None,
    sample_rate: int = 24000,
    encoder: tuple[list[str], str] | None = None,
    render_quality: Quality | None = None,
) -> dict[str, Any]:
    """El trabajo tal como lo pide el contrato con Unity.

    ``encoder``: argumentos y ruta del ffmpeg de Unity (por defecto, el MP4 mudo opaco).
    """
    width, height = video_size(script.video)
    q = render_quality or quality(script.video)
    args, path = encoder or (ff.encoder_args(q), str(output_dir / "video_mudo.mp4"))
    job: dict[str, Any] = {
        "id": job_id,
        "kind": kind,
        "output_dir": str(output_dir),
        "width": width,
        "height": height,
        "fps": script.video.fps,
        "supersample": q.supersample,
        "subframes": q.subframes,
        "shutter": q.shutter,
        "duration_s": round(duration_s, 4),
        "warmup_s": WARMUP_S,
        "audio_sample_rate": sample_rate,
        "timeline": timeline,
        "scene": scene_message(script.scene),
        "encoder": {"ffmpeg": ffmpeg, "args": args, "path": path},
    }
    if still_path is not None:
        job["still_path"] = str(still_path)
    if stills is not None:
        job["stills"] = stills
    return job


def photo_times(
    gesture: Gesture | None, *, moment: float | None = None, burst: int = 1
) -> list[float]:
    """Los segundos de cada foto desde que empieza el gesto (o el reposo).

    Una foto: ``moment``, o el golpe del gesto (``critical_beat``), o el medio de su núcleo,
    o el inicio si no hay gesto. Una ráfaga reparte ``burst`` fotos por la duración del
    gesto (o por unos segundos de reposo), cada una en el medio de su tramo.
    """
    if burst > 1:
        length = gesture.duration if gesture is not None and gesture.duration > 0 else IDLE_BURST_S
        return [round(length * (i + 0.5) / burst, 4) for i in range(burst)]
    if moment is not None:
        return [max(0.0, moment)]
    if gesture is None:
        return [0.0]
    if gesture.critical_beat is not None and gesture.critical_beat > 0:
        return [round(gesture.critical_beat, 4)]
    if gesture.core_stop > gesture.core_start:
        return [round((gesture.core_start + gesture.core_stop) / 2, 4)]
    return [round(gesture.duration / 2, 4)]


@dataclass(slots=True)
class RenderResult:
    video: Path
    srt: Path
    duration_s: float
    take: Take
    gestures: dict[int, GestureCue]
    report: ff.FinishReport
    notes: list[str] = field(default_factory=list)
    #: Con fondo transparente: el paquete ``sonnia/`` y lo que hay que pegar en el reel.
    package: Package | None = None
    snippet: str = ""


class Pipeline:
    """Hace vídeos, fotos y vistas previas. Todo lo externo entra por el constructor."""

    def __init__(
        self,
        *,
        client: RendererClient,
        voice: VoiceMaker,
        ffmpeg: str,
        progress: Progress | None = None,
        llm_factory: Callable[[], Any] = gesture_llm,
        app: Path | None = None,
        stall_restart_s: float = STALL_RESTART_S,
    ) -> None:
        self.client = client
        self.voice = voice
        self.ffmpeg = ffmpeg
        self.progress = progress or Progress()
        self._llm_factory = llm_factory
        self._app = app
        self._stall_restart_s = stall_restart_s

    @classmethod
    def default(cls, *, progress: Progress | None = None) -> Pipeline:
        ffmpeg = ff.find_ffmpeg()
        return cls(
            client=RendererClient(),
            voice=VoiceMaker(VoiceCache(home() / "cache"), ffmpeg=ffmpeg),
            ffmpeg=ffmpeg,
            progress=progress,
        )

    # -- renderizador ---------------------------------------------------------------

    def start(self, outfit: str | None = None) -> Any:
        """Lanza el renderizador si no está abierto (o si lleva otra camiseta que ``outfit``)."""
        return ensure_started(self.client, unity_log(), app=self._app, outfit=outfit)

    def ready(self, process: Any = None, *, outfit: str | None = None) -> dict[str, Any]:
        """Abre el renderizador si hace falta y espera al avatar."""
        if process is None:
            process = self.start(outfit)
        try:
            return wait_ready(
                self.client,
                process=process,
                log_file=unity_log(),
                progress=self.progress,
                timeout_s=self._stall_restart_s,
            )
        except AvatarTimeout:
            status = self.client.status()
            if status is not None and status.get("busy"):
                raise
        # Genies se quedó a medias (ver STALL_RESTART_S): se relanza una vez y se espera entera.
        logger.warning(
            "El avatar no llegó en %.0f s: relanzo el renderizador una vez", self._stall_restart_s
        )
        if self.client.status() is not None:
            quit_and_wait(self.client)
        if process is not None and process.poll() is None:
            process.kill()
        process = self.start(outfit)
        return wait_ready(
            self.client, process=process, log_file=unity_log(), progress=self.progress
        )

    def catalog(self) -> GestureCatalog:
        self.ready()
        return GestureCatalog.from_message(self.client.catalog())

    # -- vídeo ------------------------------------------------------------------------

    def render(
        self, script: Script, out_dir: Path | None = None, *, force: bool = False
    ) -> RenderResult:
        check_files(script)
        texts = phrase_texts(script)
        for index, text in enumerate(texts, 1):
            if not text.spoken_words:
                raise VideoError(f"La frase {index} no tiene palabras que decir.")
        out_dir = out_dir or default_out()
        title = title_of(script)
        transparent = script.scene.background == "transparente"
        package: Package | None = None
        if transparent:
            # Antes de gastar nada: que se pueda escribir el paquete.
            package = package_for(reel=script.video.reel, out_dir=out_dir, title=title)
            # La carpeta propia de cada vídeo se reemplaza sin más; la de un reel, solo con --forzar.
            package.prepare(force=force or not package.in_reel)
        # El avatar carga mientras se hace la voz, salvo que falte la clave de la voz: entonces
        # la voz sale de la caché o falla, y no hace falta haber abierto Unity.
        key = {"gemini": GEMINI_KEY, "elevenlabs": ELEVENLABS_KEY}.get(script.voice.engine)
        early = key is None or bool(os.environ.get(key, "").strip())
        outfit = outfit_of(script)
        process = self.start(outfit) if early else None
        take = asyncio.run(self.voice.take(script, texts))
        logger.info(
            "Voz: %.1f s (%s, %s; tiempos: %s%s)",
            take.duration,
            take.engine,
            take.voice,
            take.timing,
            ", de la caché" if take.cached else "",
        )
        plan = build_plan(
            texts,
            take,
            pauses=[p.pause for p in script.phrases],
            lead_s=script.video.lead_s,
            tail_s=script.video.tail_s,
        )
        notes: list[str] = []
        if take.timing == "local":
            notes.append("Tiempos de las palabras aproximados (sin transcripción)")
        self.ready(process, outfit=outfit)
        cues = self._gestures(script, plan, notes)
        actions = self._actions(script)

        job_id = f"{title}-{datetime.now():%Y%m%d-%H%M%S}"
        work = job_dir(job_id)
        work.mkdir(parents=True, exist_ok=True)
        wavs = write_unity_wavs(plan, work)
        timeline = build_timeline(plan, wavs, gestures=cues, actions=actions, fps=script.video.fps)
        mute = work / ("video_mudo.mov" if transparent else "video_mudo.mp4")
        encoder = (
            ff.transparent_outputs(mute, package.frames, package.proxy)
            if package is not None
            else (ff.encoder_args(quality(script.video)), str(mute))
        )
        job = build_job(
            job_id=job_id,
            kind="video",
            output_dir=work,
            script=script,
            duration_s=plan.duration_s,
            timeline=timeline,
            ffmpeg=self.ffmpeg,
            sample_rate=plan.rate,
            encoder=encoder,
        )
        run_job(self.client, job, progress=self.progress, log_file=unity_log())

        out_dir.mkdir(parents=True, exist_ok=True)
        video = out_dir / f"{title}{'.mov' if transparent else '.mp4'}"
        audio_t = {p.uid: plan.phrase_t(k) for k, p in enumerate(plan.phrases)}
        self.progress.update("Poniendo la voz…")
        report = ff.finish(
            ffmpeg=self.ffmpeg,
            video=mute,
            registro=work / "registro.json",
            master=plan.master,
            rate=plan.rate,
            lead_s=plan.lead_s,
            audio_t=audio_t,
            fps=script.video.fps,
            duration_s=plan.duration_s,
            out=video,
            work=work,
            voice_out=package.root / "voz.wav" if package is not None else None,
        )
        self.progress.done()
        words = srt_words(plan, report.voice_at)
        srt = out_dir / f"{title}.srt"
        srt.write_text(format_srt(build_cues(words)), encoding="utf-8")
        pasted = ""
        if package is not None:
            pasted = self._write_package(package, script, plan, take, words, report, work, notes)
        mute.unlink(missing_ok=True)
        _prune_jobs(work.parent)
        return RenderResult(
            video=video,
            srt=srt,
            duration_s=report.frames / script.video.fps if report.frames else plan.duration_s,
            take=take,
            gestures=cues,
            report=report,
            notes=notes + report.notes,
            package=package,
            snippet=pasted,
        )

    def _write_package(
        self,
        package: Package,
        script: Script,
        plan: Plan,
        take: Take,
        words: list[SrtWord],
        report: ff.FinishReport,
        work: Path,
        notes: list[str],
    ) -> str:
        """El resto del paquete ``sonnia/``: prueba, palabras, voz y localizador."""
        fps = script.video.fps
        width, height = video_size(script.video)
        count = len(package.frame_files())
        if report.frames and count != report.frames:
            notes.append(f"Hay {count} cuadros PNG y el vídeo tiene {report.frames}")
        if package.write_proof() is None:
            notes.append(f"Unity no dejó cuadros PNG en {package.frames}")
        package.write_json("palabras.json", words_json(words))
        duration = (report.frames or round(plan.duration_s * fps)) / fps
        options = script.voice
        settings = {
            k: v
            for k, v in (
                ("estabilidad", options.stability),
                ("similitud", options.similarity),
                ("estilo", options.style if isinstance(options.style, float) else None),
                ("velocidad", options.speed),
            )
            if v is not None
        }
        package.write_json(
            "voz.json",
            voice_info(
                duration_s=duration,
                phrases=[
                    (p.display, report.voice_at + p.voice_start, report.voice_at + p.voice_end)
                    for p in plan.phrases
                ],
                engine=take.engine,
                voice=take.voice,
                model=take.model,
                style=style_for(options.style) if take.engine == "gemini" else "",
                settings=settings,
                voice_at=report.voice_at,
            ),
        )
        reg = ff.read_registro(work / "registro.json")
        if reg is not None and reg.bones:
            package.write_json(
                "localizador.json", locator(reg, fps=fps, width=width, height=height)
            )
        else:
            notes.append("El registro de Unity no trae huesos: sin localizador.json")
        return snippet(duration_s=duration, count=count, in_reel=package.in_reel)

    def _actions(self, script: Script) -> list[Any]:
        """Los ``[[accion]]`` con el nombre exacto de su gesto."""
        actions = list(script.actions)
        if not actions:
            return actions
        catalog = GestureCatalog.from_message(self.client.catalog())
        names = resolve_names([a.gesture for a in actions], catalog, "[[accion]]")
        return [a.model_copy(update={"gesture": n}) for a, n in zip(actions, names, strict=True)]

    def _gestures(self, script: Script, plan: Plan, notes: list[str]) -> dict[int, GestureCue]:
        mode = script.gestures.mode
        manual = {
            k + 1: phrase.gesture.strip()
            for k, phrase in enumerate(script.phrases)
            if phrase.gesture.strip()
        }
        if mode == "ninguno" or (mode == "manual" and not manual):
            return {}
        catalog = GestureCatalog.from_message(self.client.catalog())
        if not len(catalog):
            notes.append("El renderizador no tiene gestos: vídeo sin gestos")
            return {}
        fixed = dict(
            zip(manual, resolve_names(list(manual.values()), catalog, "[[frase]]"), strict=True)
        )
        phrases = [
            ScriptPhrase(
                uid=p.uid,
                text=p.display,
                start=plan.phrase_t(k),
                duration=max(0.0, p.voice_end - p.voice_start),
                end=plan.lead_s + p.voice_end,
            )
            for k, p in enumerate(plan.phrases)
        ]
        chosen: dict[int, str] = {}
        if mode == "auto":
            try:
                chosen = asyncio.run(self._choose(catalog, phrases, fixed))
            except VideoError as exc:
                notes.append(f"Sin gestos elegidos: {exc}")
        cues, dropped = schedule(phrases, chosen, fixed, catalog)
        for note in dropped:
            logger.info("Gesto: %s", note)
        return cues

    async def _choose(
        self, catalog: GestureCatalog, phrases: list[ScriptPhrase], fixed: dict[int, str]
    ) -> dict[int, str]:
        llm = self._llm_factory()
        if llm is None:
            raise VideoError(
                "no hay clave para el modelo de gestos (GEMINI_API_KEY u OPENAI_API_KEY)"
            )
        try:
            return await choose_gestures(llm, catalog, phrases, fixed)
        finally:
            close = getattr(llm, "aclose", None)
            if close is not None:
                await close()

    # -- fotos y vista previa ------------------------------------------------------

    def photos(
        self,
        script: Script,
        out_dir: Path | None = None,
        *,
        gesture: str = "",
        mirror: bool = False,
        moment: float | None = None,
        burst: int = 1,
        title: str = "",
    ) -> list[Path]:
        """Fotos de Sonnia (PNG, con alfa si el fondo es transparente), sin voz.

        Con ``gesture``, el gesto empieza en el segundo 0 y la foto sale en ``moment`` (o en
        su golpe); con ``burst``, varias repartidas por el gesto (``photo_times``).
        """
        check_files(script)
        if burst < 1:
            raise VideoError("La ráfaga tiene que ser de una foto o más.")
        self.ready(outfit=outfit_of(script))
        found: Gesture | None = None
        if gesture.strip():
            catalog = GestureCatalog.from_message(self.client.catalog())
            (name,) = resolve_names([gesture], catalog, "--gesto")
            found = catalog.get(name)
        times = photo_times(found, moment=moment, burst=burst)
        base = slug(title) if title.strip() else ""
        base = base or (
            title_of(script)
            if script.title.strip()
            else f"foto-{slug(found.name) if found else 'sonnia'}"
        )
        job_id = f"{base}-{datetime.now():%Y%m%d-%H%M%S}"
        work = job_dir(job_id)
        work.mkdir(parents=True, exist_ok=True)
        timeline: list[dict[str, Any]] = [
            {"t": 0.0, "message": dict(STAGE_MODE)},
            {"t": 0.0, "message": {"type": "state", "state": "idle"}},
        ]
        if found is not None:
            timeline.append({"t": 0.0, "action": {"name": found.name, "mirror": mirror}})
        stills: list[dict[str, Any]] = [
            {"t": t, "path": str(work / f"foto_{i + 1:02d}.png")} for i, t in enumerate(times)
        ]
        job = build_job(
            job_id=job_id,
            kind="still",
            output_dir=work,
            script=script,
            duration_s=max(times),
            timeline=timeline,
            ffmpeg=self.ffmpeg,
            stills=stills,
            render_quality=PHOTO_QUALITY,
        )
        run_job(self.client, job, progress=self.progress, log_file=unity_log())
        out_dir = out_dir or home() / "fotos"
        out_dir.mkdir(parents=True, exist_ok=True)
        results: list[Path] = []
        for i, still in enumerate(stills):
            source = Path(still["path"])
            if not source.is_file():
                raise VideoError(f"El renderizador no dejó la foto en {source}")
            name = f"{base}.png" if len(stills) == 1 else f"{base}_{i + 1:02d}.png"
            target = out_dir / name
            shutil.copyfile(source, target)
            results.append(target)
        _prune_jobs(work.parent)
        return results

    def still(self, script: Script, out: Path) -> Path:
        """Una imagen rápida de la escena pedida (sin voz), con la calidad del guion."""
        check_files(script)
        self.ready(outfit=outfit_of(script))
        title = title_of(script)
        job_id = f"{title}-vista-{datetime.now():%Y%m%d-%H%M%S}"
        work = job_dir(job_id)
        work.mkdir(parents=True, exist_ok=True)
        fps = script.video.fps
        timeline = [
            {"t": 0.0, "message": dict(STAGE_MODE)},
            {"t": 0.0, "message": {"type": "state", "state": "idle"}},
        ]
        target = work / "vista.png"
        job = build_job(
            job_id=job_id,
            kind="still",
            output_dir=work,
            script=script,
            duration_s=1.0 / fps,
            timeline=timeline,
            ffmpeg=self.ffmpeg,
            still_path=target,
        )
        run_job(self.client, job, progress=self.progress, log_file=unity_log())
        found = target if target.is_file() else work / "still.png"
        if not found.is_file():
            raise VideoError(f"El renderizador no dejó la imagen en {target}")
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(found, out)
        _prune_jobs(work.parent)
        return out


def srt_words(plan: Plan, voice_at: float) -> list[SrtWord]:
    """Los trozos de texto con su tiempo en el vídeo (la voz maestra empieza en ``voice_at``)."""
    return [
        SrtWord(unit.display, voice_at + unit.start, voice_at + unit.end, phrase.uid)
        for phrase in plan.phrases
        for unit in phrase.units
    ]


def _prune_jobs(folder: Path, keep: int = KEEP_JOBS) -> None:
    """Borra los trabajos viejos (se quedan los ``keep`` más nuevos)."""
    try:
        jobs = sorted(
            (p for p in folder.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for old in jobs[keep:]:
        shutil.rmtree(old, ignore_errors=True)
