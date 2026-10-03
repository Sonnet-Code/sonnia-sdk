"""Configuración del orquestador. Todo viene de variables de entorno o de `.env`.

Ningún módulo debe leer `os.environ` directamente: recibe un `Settings` (o la
parte que necesita) por parámetro. Así los tests pueden construir la
configuración a mano.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_", extra="ignore", env_ignore_empty=True)

    base_url: str = "http://localhost:8000/v1"
    model: str = "kimi-k3"
    api_key: str = "local"
    #: Si el modelo acepta imágenes. Si es False, la capa de visión se apaga.
    supports_vision: bool = True
    #: native = tool calling de la API; prompt = acciones descritas en el
    #: system prompt y parseadas del texto; none = sin acciones.
    tool_mode: Literal["native", "prompt", "none"] = "native"
    #: Se envía como ``reasoning_effort`` si no está vacío (Kimi K3: low/high/max).
    reasoning_effort: str = "low"
    #: Se envía solo si no es None. Algunos modelos (Kimi K3) solo admiten 1 y
    #: rechazan cualquier otro valor; los servidores locales tienen su propio
    #: valor por defecto.
    temperature: float | None = None
    max_tokens: int = 400
    #: Nombre del campo con el que se envía ``max_tokens``. La API de OpenAI
    #: rechaza ``max_tokens`` en sus modelos de razonamiento y pide
    #: ``max_completion_tokens``; los servidores locales usan ``max_tokens``.
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    #: Máximo de rondas de tool calls por turno del usuario.
    max_tool_rounds: int = 3
    #: Turnos de conversación que se conservan en el historial.
    history_turns: int = 12
    request_timeout: float = 60.0


class STTSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STT_", extra="ignore", env_ignore_empty=True)

    backend: Literal["faster_whisper", "mock"] = "faster_whisper"
    model: str = "small"
    device: str = "auto"
    compute_type: str = "auto"
    language: str = "es"
    beam_size: int = 1


class TTSSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TTS_", extra="ignore", env_ignore_empty=True)

    #: omnivoice = en proceso; http = servidor compatible con /v1/audio/speech;
    #: gemini = API Live de Gemini (provisional, sin GPU; ver ADR 006);
    #: system = voz del sistema operativo (say en macOS, SAPI en Windows,
    #: espeak-ng en Linux): bajo consumo, sin red, para ensayos;
    #: mock = silencio con la duración del texto, solo para tests.
    backend: Literal["omnivoice", "http", "gemini", "system", "mock"] = "omnivoice"
    base_url: str = "http://127.0.0.1:8880/v1"
    api_key: str = "local"
    http_model: str = "omnivoice"
    #: Descripción de la voz (voice design de OmniVoice).
    voice_instruct: str = "female, young adult, warm, natural, latin american spanish accent"
    #: Ruta a un audio de referencia para clonar la voz. Si se define, tiene
    #: prioridad sobre ``voice_instruct``.
    ref_audio: str = ""
    ref_text: str = ""
    language: str = "es"
    device: str = "auto"
    speed: float = 1.0
    num_step: int = 16
    sample_rate: int = 24_000
    #: Backend system: nombre de la voz ("" = mejor voz en español disponible).
    system_voice: str = ""
    #: Backend system: palabras por minuto (0 = la del sistema).
    system_rate: int = 0


class AudioSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUDIO_", extra="ignore", env_ignore_empty=True)

    #: Índice o nombre del dispositivo de entrada de sounddevice ("" = por defecto).
    input_device: str = ""
    #: Tamaño del bloque que entra al VAD, en milisegundos (Silero usa 32 ms).
    block_ms: int = 32
    vad_threshold: float = 0.5
    #: Umbral más exigente mientras Sonia habla, para reducir falsos positivos
    #: por eco del altavoz.
    vad_threshold_while_speaking: float = 0.8
    #: Silencio necesario para dar por terminado el turno del usuario.
    end_silence_ms: int = 600
    #: Habla mínima para considerar que hay un turno (descarta ruidos).
    min_speech_ms: int = 250
    #: Habla mínima para interrumpir a Sonia mientras habla.
    barge_in_min_speech_ms: int = 400
    #: Factor por el que la voz del visitante debe superar el eco de Sonia en el
    #: micrófono (nivel RMS medio) para contar como interrupción. 2,5 son unos
    #: 8 dB. Un micrófono de condensador con altavoces cerca capta la voz de
    #: Sonia como si fuera una persona; esto la distingue por nivel.
    barge_in_over_echo: float = 2.5
    #: Nivel RMS mínimo absoluto (0..1) para interrumpir; 0 lo desactiva. Se
    #: calibra en el stand si el factor sobre el eco no basta.
    barge_in_min_rms: float = 0.0
    #: Nivel RMS medio (0..1) que debe alcanzar la voz de un turno para que
    #: cuente; por debajo se descarta como conversación de fondo. 0 lo
    #: desactiva. Cada turno deja su nivel en el log ("nivel 0.031") para
    #: calibrarlo en el sitio: la gente a un metro del micro suele quedar
    #: bastante por encima de las voces del pasillo.
    min_turn_rms: float = 0.0
    #: Eco con voz que hay que haber oído desde que suena Sonia antes de
    #: admitir interrupciones: evita disparos al arrancar, cuando aún no hay
    #: referencia de nivel.
    barge_in_warmup_ms: int = 500
    #: Constante de tiempo de la media móvil del nivel de eco.
    echo_level_tau_ms: int = 1500
    max_utterance_s: float = 20.0
    #: Audio previo al inicio del habla que se conserva (evita cortar la primera sílaba).
    pre_roll_ms: int = 300
    barge_in: bool = True


class VisionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VISION_", extra="ignore", env_ignore_empty=True)

    #: opencv = captura desde Python; unity = Unity envía frames por WS; none.
    source: Literal["opencv", "unity", "none"] = "opencv"
    camera_index: int = 0
    max_width: int = 768
    jpeg_quality: int = 80
    #: Adjuntar una captura al turno cuando el usuario empieza a hablar.
    on_turn_start: bool = True
    #: Adjuntar además una captura cada N segundos aunque no la pida el modelo (0 = nunca).
    interval_seconds: float = 0.0
    #: Guardar capturas en disco (solo depuración; nunca en el stand).
    debug_save_frames: bool = False
    debug_dir: str = str(_REPO_ROOT / "debug_frames")


class WSSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WS_", extra="ignore", env_ignore_empty=True)

    host: str = "127.0.0.1"
    port: int = 8765
    #: Tamaño de los chunks de audio hacia Unity, en milisegundos.
    chunk_ms: int = 100


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_", extra="ignore", env_ignore_empty=True)

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8766


class LiveSettings(BaseSettings):
    """Motor de voz a voz con GPT-Live (``VOICE_ENGINE=live``, ver ADR 007).

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
    #: Con ``AUDIO_BARGE_IN=false`` el micrófono sigue mudo este tiempo después
    #: de que Sonia termine, para que no se oiga la cola de su propia voz.
    echo_tail_ms: int = 400
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
    state_file: str = str(_REPO_ROOT / "cache" / "panel_state.json")
    #: Caché de frases fijas grabadas con la voz de GPT-Live.
    voice_cache_dir: str = str(_REPO_ROOT / "cache" / "voice")
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
        env_file=(_REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    #: live = GPT-Live voz a voz (ADR 007); pipeline = VAD + STT + LLM + TTS.
    voice_engine: Literal["live", "pipeline"] = "live"
    live: LiveSettings = Field(default_factory=LiveSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    stt: STTSettings = Field(default_factory=STTSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    vision: VisionSettings = Field(default_factory=VisionSettings)
    ws: WSSettings = Field(default_factory=WSSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)
    showcase: ShowcaseSettings = Field(default_factory=ShowcaseSettings)
    panel: PanelSettings = Field(default_factory=PanelSettings)

    assets_dir: str = str(_REPO_ROOT / "assets")
    log_level: str = "INFO"
    #: Reiniciar la conversación tras N segundos sin actividad (modo kiosco).
    idle_reset_seconds: float = 120.0
    #: Retirar sola una imagen mostrada tras N segundos (0 = nunca). El modelo
    #: la retira al cambiar de tema, pero si se olvida no se queda ahí.
    image_auto_hide_seconds: float = 30.0

    @property
    def gallery_dir(self) -> Path:
        return Path(self.assets_dir) / "gallery"

    @property
    def showcase_dir(self) -> Path:
        return Path(self.assets_dir) / "showcase"


def load_settings() -> Settings:
    """Carga `.env` (raíz del repo o cwd) y construye la configuración."""
    from dotenv import load_dotenv

    for candidate in (_REPO_ROOT / ".env", Path(".env")):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
    return Settings()
