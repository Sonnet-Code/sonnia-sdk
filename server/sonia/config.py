"""Configuración de Sonia. Todo viene de variables de entorno o de `.env`.

Ningún módulo debe leer `os.environ` directamente: recibe un `Settings` (o la
parte que necesita) por parámetro. Así los tests pueden construir la
configuración a mano.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from sonia.paths import BUNDLE_ROOT, env_files, home

#: Raíz de `cache/` y `overrides.env`: el repo, o fuera de la app empaquetada (`sonia/paths.py`).
_HOME = home()


class LLMSettings(BaseSettings):
    """Modelo con visión que describe la cámara (GPT-Live no acepta imágenes).

    Cualquier endpoint compatible con OpenAI (Chat Completions). Por defecto la
    API de OpenAI; si falta ``LLM_API_KEY`` se usa la clave de OpenAI
    (``OPENAI_API_KEY`` o, si no está, ``LIVE_API_KEY``), pero solo contra la
    propia OpenAI (ver :attr:`key`).
    """

    model_config = SettingsConfigDict(
        env_prefix="LLM_", extra="ignore", env_ignore_empty=True, populate_by_name=True
    )

    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-6-luna"
    #: ``LLM_API_KEY``: la clave del servidor del modelo.
    api_key: str = Field(default="", repr=False)
    #: Clave de OpenAI (``OPENAI_API_KEY`` o, si no está, la de GPT-Live,
    #: ``LIVE_API_KEY``), que solo vale si ``base_url`` es la API de OpenAI.
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "LIVE_API_KEY"),
        repr=False,
    )
    #: Si es False, Sonia no mira la cámara (sin notas de la cámara ni ``look``).
    supports_vision: bool = True
    #: Se envía como ``reasoning_effort`` salvo que valga ``off``. Un valor vacío no
    #: sirve para quitarlo: en el ``.env`` equivale a no poner la variable y vuelve ``low``.
    reasoning_effort: str = "low"
    #: Se envía solo si no es None (algunos modelos solo admiten su valor por defecto).
    temperature: float | None = None
    max_tokens: int = 400
    #: Nombre del campo con el que se envía ``max_tokens``: la API de OpenAI pide
    #: ``max_completion_tokens`` en sus modelos de razonamiento; otros servidores,
    #: ``max_tokens``.
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = "max_completion_tokens"
    #: ``detail`` con el que se manda cada imagen (low, high, auto). ``off`` no lo
    #: envía: fuera de OpenAI el campo no está documentado y un servidor estricto puede
    #: rechazar la petición.
    image_detail: str = "low"
    #: Campos extra del cuerpo de la petición, como JSON en ``LLM_EXTRA_BODY``, para
    #: lo propio de cada servidor. Kimi K2.6 razona por defecto y se le apaga con
    #: ``{"thinking": {"type": "disabled"}}``.
    extra_body: dict[str, Any] = Field(default_factory=dict)
    request_timeout: float = 60.0

    @property
    def key(self) -> str:
        """Clave que se manda: ``LLM_API_KEY`` o, contra la API de OpenAI, la de OpenAI.

        Con otro proveedor (Kimi, un servidor propio...) y sin ``LLM_API_KEY``
        queda vacía: la clave de OpenAI nunca sale hacia otro servidor.
        """
        if self.api_key:
            return self.api_key
        return self.openai_api_key if is_openai_url(self.base_url) else ""


def is_openai_url(url: str) -> bool:
    """¿Es ``url`` la API de OpenAI (``api.openai.com`` por HTTPS)?"""
    parsed = urlparse(url.strip())
    return parsed.scheme == "https" and (parsed.hostname or "") == "api.openai.com"


class AudioSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUDIO_", extra="ignore", env_ignore_empty=True)

    #: Índice o nombre del dispositivo de entrada de sounddevice ("" = por defecto).
    input_device: str = ""
    #: Tamaño de los bloques del micrófono que se mandan a GPT-Live, en milisegundos.
    block_ms: int = 32


class VisionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VISION_", extra="ignore", env_ignore_empty=True)

    #: opencv = captura desde Python; unity = Unity envía frames por WS; none.
    source: Literal["opencv", "unity", "none"] = "opencv"
    camera_index: int = 0
    max_width: int = 768
    jpeg_quality: int = 80
    #: Describir la cámara cuando el visitante empieza a hablar (nota [Cámara]).
    #: Por defecto no: Sonia solo mira cuando ella lo decide, con la acción ``look``.
    on_turn_start: bool = False
    #: Adjuntar además una captura cada N segundos aunque no la pida el modelo (0 = nunca).
    interval_seconds: float = 0.0
    #: Guardar capturas en disco (solo depuración; nunca en el stand).
    debug_save_frames: bool = False
    debug_dir: str = str(_HOME / "debug_frames")


class WSSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WS_", extra="ignore", env_ignore_empty=True)

    host: str = "127.0.0.1"
    port: int = 8765


class LiveSettings(BaseSettings):
    """Motor de voz a voz con GPT-Live (ver ADR 007).

    GPT-Live oye el micrófono y habla con su propia voz por un único WebSocket:
    sustituye al detector de voz, al reconocedor, al modelo de texto y al TTS.
    Las acciones las ejecuta un backend de la API Responses al que GPT-Live
    delega (``backend_*``).
    """

    model_config = SettingsConfigDict(
        env_prefix="LIVE_", extra="ignore", env_ignore_empty=True, populate_by_name=True
    )

    url: str = "wss://api.openai.com/v1/live/sessions"
    #: Clave de la API. Si ``LIVE_API_KEY`` no está, se usa ``OPENAI_API_KEY``.
    api_key: str = Field(
        default="", validation_alias=AliasChoices("LIVE_API_KEY", "OPENAI_API_KEY")
    )
    model: str = "gpt-live-1"
    #: Voz integrada (marin, cedar, coral, sage, shimmer...). Fija durante la sesión.
    voice: str = "marin"
    #: Tasa del PCM en los dos sentidos. La API acepta 16000 o 24000. Es un
    #: ``int`` validado y no un ``Literal``: desde ``.env`` llega como texto y
    #: pydantic no convierte texto a un ``Literal`` de enteros.
    sample_rate: int = 24_000
    #: Modelo de la API Responses que ejecuta las tareas delegadas y las acciones.
    backend_model: str = "gpt-6-luna"
    #: ``reasoning.effort`` del backend (vacío = el del modelo).
    backend_reasoning_effort: str = "low"
    #: ``service_tier`` del backend (vacío = no se envía; ``priority`` = más rápido).
    backend_service_tier: str = ""
    backend_max_output_tokens: int = 400
    #: Rondas de acciones que se le permiten al backend por tarea delegada.
    backend_max_tool_rounds: int = 3
    #: Silencio en la voz de Sonia que cierra una frase hacia Unity.
    segment_gap_ms: int = 800
    #: Silencio en lo que transcribe del visitante que da su turno por cerrado.
    user_turn_gap_ms: int = 1_200
    #: Puerta de ruido: nivel RMS (0..1) por debajo del cual se envía silencio
    #: en lugar del micrófono. 0 la desactiva. Sirve para que GPT-Live no oiga
    #: las conversaciones de fondo del pasillo; se calibra en el stand.
    gate_rms: float = 0.0
    #: Tiempo que la puerta sigue abierta después de la última voz por encima del umbral.
    gate_hold_ms: int = 900
    #: Mínimo entre dos descripciones de la cámara (cada una es una petición al modelo de visión).
    vision_min_interval_seconds: float = 10.0
    #: Reiniciar la sesión en el siguiente momento de calma si el contexto pasa de esta fracción.
    context_restart_ratio: float = 0.85
    connect_timeout: float = 15.0
    #: Esperas entre reconexiones (crecen del mínimo al máximo).
    reconnect_min_seconds: float = 1.0
    reconnect_max_seconds: float = 15.0

    @field_validator("sample_rate")
    @classmethod
    def _check_sample_rate(cls, value: int) -> int:
        if value not in (16_000, 24_000):
            raise ValueError("LIVE_SAMPLE_RATE debe ser 16000 o 24000")
        return value


class ShowcaseSettings(BaseSettings):
    """Animación de stand: frases y bailes cantados cuando no hay nadie."""

    model_config = SettingsConfigDict(env_prefix="SHOWCASE_", extra="ignore", env_ignore_empty=True)

    enabled: bool = True
    #: Segundos en idle antes del primer número.
    first_delay_seconds: float = 25.0
    #: Segundos mínimo y máximo entre números.
    interval_min_seconds: float = 40.0
    interval_max_seconds: float = 90.0
    #: Probabilidad de que el número sea un baile cantado en vez de una frase.
    dance_chance: float = 0.3
    #: Probabilidad de que una frase vaya acompañada de un gesto de cuarta pared.
    gesture_chance: float = 0.5


class TriviaSettings(BaseSettings):
    """Modo trivia: preguntas de opción múltiple en la pantalla de Unity.

    GPT-Live entiende lo que contesta el visitante y lo registra con la acción
    ``trivia_answer``; el orquestador guarda la clave y lleva la pantalla.
    """

    model_config = SettingsConfigDict(env_prefix="TRIVIA_", extra="ignore", env_ignore_empty=True)

    enabled: bool = True
    #: Preguntas por partida (salen al azar de ``assets/trivia/preguntas.md``).
    questions: int = 5
    #: Aciertos para ganar la partida.
    win_threshold: int = 3
    #: Sin respuesta durante esto, Sonia repite las opciones una vez.
    remind_seconds: float = 25.0
    #: Sin oír al visitante durante esto, la partida se cancela (se ha ido).
    abandon_seconds: float = 60.0
    #: Segundos que la pantalla enseña el acierto o el fallo antes de la siguiente.
    reveal_seconds: float = 4.0


class PanelSettings(BaseSettings):
    """Panel de control web para el personal del stand (``docs/panel.md``)."""

    model_config = SettingsConfigDict(env_prefix="PANEL_", extra="ignore", env_ignore_empty=True)

    enabled: bool = True
    #: Solo en local: desde internet se entra por el Cloudflare Tunnel.
    host: str = "127.0.0.1"
    port: int = 8780
    #: Equipo de Cloudflare Zero Trust (``<equipo>.cloudflareaccess.com``) y
    #: AUD de la aplicación de Access. Sin los dos, se rechaza todo acceso
    #: que llegue por Cloudflare.
    access_team_domain: str = ""
    access_aud: str = ""
    #: Dónde se guarda el estado del panel (modo, avisos, volumen...).
    state_file: str = str(_HOME / "cache" / "panel_state.json")
    #: Caché de frases fijas grabadas con la voz de GPT-Live.
    voice_cache_dir: str = str(_HOME / "cache" / "voice")
    #: Modo "Solo saludos": segundos entre saludos (mínimo y máximo).
    greeter_interval_min_seconds: float = 25.0
    greeter_interval_max_seconds: float = 55.0
    #: Precio de GPT-Live por minuto de sesión, para estimar el gasto.
    live_price_per_minute: float = 0.05
    #: Panel en Cloudflare: cada Sonia se conecta hacia fuera a este Worker.
    #: Sin ``cloud_token`` no se conecta (solo queda el panel local).
    cloud_url: str = "wss://sonia.sonnetcode.com/agent"
    cloud_token: str = ""
    #: Nombre con el que esta Sonia sale en el panel (vacío = nombre del equipo).
    instance_name: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # En pydantic-settings el último archivo manda: al revés que env_files().
        env_file=(".env", *reversed(env_files())),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    live: LiveSettings = Field(default_factory=LiveSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    vision: VisionSettings = Field(default_factory=VisionSettings)
    ws: WSSettings = Field(default_factory=WSSettings)
    showcase: ShowcaseSettings = Field(default_factory=ShowcaseSettings)
    trivia: TriviaSettings = Field(default_factory=TriviaSettings)
    panel: PanelSettings = Field(default_factory=PanelSettings)

    assets_dir: str = str(BUNDLE_ROOT / "assets")
    log_level: str = "INFO"
    #: Reiniciar la conversación tras N segundos sin actividad (modo kiosco).
    idle_reset_seconds: float = 120.0
    #: Retirar sola una imagen mostrada tras N segundos (0 = nunca). El modelo
    #: la retira al cambiar de tema, pero si se olvida no se queda ahí.
    image_auto_hide_seconds: float = 30.0
    #: ``SONIA_PARENT_PID``: el PID de la app que lanzó el orquestador (lo pone
    #: Unity en la app todo en uno). Si esa app muere, el orquestador se cierra
    #: solo (``sonia/parent.py``). Vacío al lanzarlo a mano.
    sonia_parent_pid: int | None = None

    @field_validator("sonia_parent_pid", mode="before")
    @classmethod
    def _check_parent_pid(cls, value: Any) -> int | None:
        # Un valor raro no puede impedir que arranque Sonia: sin vigilancia.
        try:
            pid = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return pid if pid > 0 else None

    @property
    def gallery_dir(self) -> Path:
        return Path(self.assets_dir) / "gallery"

    @property
    def showcase_dir(self) -> Path:
        return Path(self.assets_dir) / "showcase"

    @property
    def knowledge_dir(self) -> Path:
        return Path(self.assets_dir) / "knowledge"

    @property
    def trivia_file(self) -> Path:
        return Path(self.assets_dir) / "trivia" / "preguntas.md"


def load_settings() -> Settings:
    """Carga las variables (`overrides.env`, el `.env` del repo o de la app, y el del cwd) y construye la configuración."""
    from dotenv import load_dotenv

    # Sin override: el primero que define una variable gana.
    for candidate in (*env_files(), Path(".env")):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
    return Settings()
