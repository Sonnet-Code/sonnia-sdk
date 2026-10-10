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
    #: sirve para quitarlo: en el ``.env`` equivale a no poner la variable y vuelve ``none``.
    #: ``none`` porque con ``low`` luna tardaba el doble (medido el 7-oct-2026, 18 fotos:
    #: mediana 4,5 s y hasta 14 s con ``low``; 2,1 s y 3,6 s como mucho con ``none``).
    reasoning_effort: str = "none"
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


#: Servidor de la API de Gemini y su endpoint compatible con OpenAI (Chat Completions).
GEMINI_HOST = "generativelanguage.googleapis.com"
GEMINI_OPENAI_URL = f"https://{GEMINI_HOST}/v1beta/openai/"


def is_gemini_url(url: str) -> bool:
    """¿Es ``url`` la API de Gemini (su endpoint compatible con OpenAI, por HTTPS)?"""
    parsed = urlparse(url.strip())
    return parsed.scheme == "https" and (parsed.hostname or "") == GEMINI_HOST


#: Tope de respuesta de los gestos: sin razonar bastan unos 10 tokens; si el
#: modelo razona (Gemini 3 no deja apagarlo), lo que razona cuenta en el tope.
GESTURE_TOKENS_PLAIN = 64
#: Modelo de gestos con Gemini si no se dice otro: el ligero que usa Genies para
#: sus prompts auxiliares. Medido el 6-oct-2026 con razonamiento minimal: 1,1-1,5 s
#: por petición, frente a 3,8-4,5 s de gpt-6-luna sin razonar.
GESTURE_GEMINI_MODEL = "gemini-3.1-flash-lite"
GESTURE_TOKENS_THINKING = 512


class GestureSettings(BaseSettings):
    """Director de gestos (``sonia/gestures``, ``docs/gestos.md``).

    Un modelo de texto ligero lee lo que dice Sonia y elige el gesto de cada
    frase del catálogo que manda Unity. Con ``GEMINI_API_KEY`` y sin
    ``GESTURE_BASE_URL`` ni ``GESTURE_MODEL`` va por Gemini
    (:data:`GESTURE_GEMINI_MODEL`, por su endpoint compatible con OpenAI): luna
    tarda demasiado para gesticular frase a frase. Sin ella, lo que se deja vacío
    sale del modelo de visión (``LLM_*``): mismo servidor, modelo y clave.
    """

    model_config = SettingsConfigDict(
        env_prefix="GESTURE_", extra="ignore", env_ignore_empty=True, populate_by_name=True
    )

    #: ``GESTURES_ENABLED``: con ``false`` Sonia habla sin gestos elegidos por el modelo.
    enabled: bool = Field(
        default=True, validation_alias=AliasChoices("GESTURES_ENABLED", "GESTURE_ENABLED")
    )
    #: Vacíos: Gemini (:data:`GESTURE_GEMINI_MODEL`) si hay ``GEMINI_API_KEY``; si no, los de ``LLM_*``.
    model: str = ""
    base_url: str = ""
    api_key: str = Field(default="", repr=False)
    #: ``GEMINI_API_KEY``: la clave de Gemini, que se usa si ``base_url`` es la
    #: API de Gemini y no hay ``GESTURE_API_KEY``. Nunca sale hacia otro servidor.
    gemini_api_key: str = Field(
        default="", validation_alias=AliasChoices("GEMINI_API_KEY"), repr=False
    )
    #: Vacío: el más bajo que acepta cada servidor (ver :meth:`effective_reasoning_effort`).
    #: ``off`` no lo envía.
    reasoning_effort: str = ""
    #: Tope de una petición. Con la frase ya sonando, además, lo que le quede hasta ``max_delay_s``.
    timeout_s: float = 3.0
    #: Tope de la respuesta. 0: 64 sin razonar (``none``) y 512 si el modelo
    #: razona, porque lo que razona cuenta en el tope.
    max_tokens: int = 0
    #: Vacío: ``max_tokens`` con Gemini y otros servidores, ``max_completion_tokens``
    #: con OpenAI, o el de ``LLM_MAX_TOKENS_PARAM`` si es el mismo servidor.
    max_tokens_param: Literal["", "max_tokens", "max_completion_tokens"] = ""
    #: Campos extra del cuerpo, en JSON (como ``LLM_EXTRA_BODY``). Vacío: los de
    #: ``LLM_EXTRA_BODY`` si es el mismo servidor; si no, ninguno.
    extra_body: dict[str, Any] = Field(default_factory=dict)
    #: Se pide el gesto de una frase en cuanto su texto llega a tantos caracteres...
    trigger_chars: int = 20
    #: ... o pasan estos segundos desde que empezó, lo primero.
    trigger_s: float = 0.5
    #: Un gesto no empieza hasta que acaba el núcleo del anterior más esto.
    min_gap_s: float = 0.5
    #: Un gesto que llegaría más tarde que esto desde el principio de su frase se descarta.
    max_delay_s: float = 2.5
    #: El mismo gesto no se repite antes de esto.
    repeat_s: float = 90.0
    #: Como mucho un gesto ``Uncommon`` cada tanto y uno ``Rare`` cada tanto.
    uncommon_s: float = 45.0
    rare_s: float = 300.0
    #: Si el modelo falla o no contesta a tiempo, un gesto de relleno neutro
    #: (lista ``Utility_NoImpact``). No se usa cuando el modelo dice «ninguno».
    fallback: bool = True

    def effective_reasoning_effort(self, base: LLMSettings) -> str:
        """El esfuerzo de razonamiento que se manda: el más bajo que acepta cada servidor.

        - OpenAI: ``none`` (sin razonar).
        - Gemini: ``none`` en los 2.5; ``minimal`` en los 3, que no dejan
          apagar el razonamiento (``none`` no les vale).
        - El mismo servidor que ``LLM_*``: su ``LLM_REASONING_EFFORT``.
        - Otro servidor: ``off`` (no se envía).
        """
        if self.reasoning_effort.strip():
            return self.reasoning_effort.strip()
        base_url = self._base_url(base)
        if is_openai_url(base_url):
            return "none"
        if is_gemini_url(base_url):
            model = self._model(base).lower().removeprefix("models/")
            return "none" if model.startswith("gemini-2") else "minimal"
        return base.reasoning_effort if self._same_server(base) else "off"

    def llm_settings(self, base: LLMSettings) -> LLMSettings:
        """Ajustes del cliente del modelo de gestos, heredando lo que falte de ``base`` (``LLM_*``).

        Con otro servidor que el de ``base`` no se heredan su clave, su
        temperatura ni sus campos extra (son de ese servidor). La clave de
        OpenAI solo se usa contra la API de OpenAI (``LLMSettings.key``) y la de
        Gemini solo contra la de Gemini.
        """
        base_url = self._base_url(base)
        same_server = self._same_server(base)
        gemini = is_gemini_url(base_url)
        effort = self.effective_reasoning_effort(base)
        max_tokens = self.max_tokens
        if max_tokens <= 0:
            plain = effort.lower() == "none"
            max_tokens = GESTURE_TOKENS_PLAIN if plain else GESTURE_TOKENS_THINKING
        tokens_param = self.max_tokens_param or (
            base.max_tokens_param
            if same_server
            else "max_completion_tokens"
            if is_openai_url(base_url)
            else "max_tokens"
        )
        return base.model_copy(
            update={
                "base_url": base_url,
                "model": self._model(base),
                "api_key": (
                    self.api_key
                    or (self.gemini_api_key if gemini else "")
                    or (base.api_key if same_server else "")
                ),
                "reasoning_effort": effort,
                "temperature": base.temperature if same_server else None,
                "extra_body": dict(self.extra_body)
                if self.extra_body
                else (dict(base.extra_body) if same_server else {}),
                "max_tokens": max_tokens,
                "max_tokens_param": tokens_param,
                "request_timeout": max(0.5, self.timeout_s),
            }
        )

    def _prefers_gemini(self) -> bool:
        """Con clave de Gemini y nada más dicho, los gestos van por Gemini."""
        return bool(self.gemini_api_key) and not self.base_url.strip() and not self.model.strip()

    def _base_url(self, base: LLMSettings) -> str:
        if self.base_url.strip():
            return self.base_url.strip()
        return GEMINI_OPENAI_URL if self._prefers_gemini() else base.base_url

    def _model(self, base: LLMSettings) -> str:
        if self.model.strip():
            return self.model.strip()
        if is_gemini_url(self._base_url(base)) and not is_gemini_url(base.base_url):
            # Gemini sin modelo: el de visión sería de otro servidor.
            return GESTURE_GEMINI_MODEL
        return base.model

    def _same_server(self, base: LLMSettings) -> bool:
        return self._base_url(base).rstrip("/") == base.base_url.rstrip("/")


class AudioSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUDIO_", extra="ignore", env_ignore_empty=True)

    #: Índice o nombre del dispositivo de entrada de sounddevice ("" = por defecto).
    input_device: str = ""
    #: Tamaño de los bloques del micrófono que se mandan a GPT-Live, en milisegundos.
    block_ms: int = 32


class VisionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VISION_", extra="ignore", env_ignore_empty=True)

    #: opencv = captura desde Python; unity = Unity envía frames por WS; obs = una fuente
    #: de OBS (modo reunión: Sonia ve la ventana de la videollamada, docs/reunion.md);
    #: screen = la pantalla del equipo (plan B del modo reunión sin OBS); none.
    source: Literal["opencv", "unity", "obs", "screen", "none"] = "opencv"
    camera_index: int = 0
    #: Con ``source=obs``: servidor WebSocket de OBS (Herramientas > Ajustes del
    #: servidor WebSocket), su contraseña (vacía si se desactiva la autenticación) y
    #: el nombre de la fuente o escena que captura la ventana de la reunión.
    obs_url: str = "ws://127.0.0.1:4455"
    obs_password: str = ""
    obs_source: str = "Reunión"
    #: Con ``source=screen``, qué pantalla se captura: 1 = la principal, 2, 3… las
    #: demás y 0 = todas juntas (numeración de mss).
    screen_monitor: int = 1
    #: Resolución que se le pide a la cámara USB si abre por debajo (muchas webcams abren a
    #: 640x480 en Windows aunque den 1080p). Las caras se buscan a esa resolución (docs/caras.md).
    #: Si no da imagen así, se queda con la suya. 0 = la que dé la cámara.
    capture_width: int = 1920
    capture_height: int = 1080
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
    #: Tope de tokens de cada respuesta del backend, razonamiento y búsquedas incluidos. Con
    #: 400 se cortaban las búsquedas en internet y GPT-Live daba «Responses handoff
    #: incomplete»; solo se cobra lo que escribe, y sus respuestas siguen siendo cortas.
    backend_max_output_tokens: int = 2000
    #: Rondas de acciones que se le permiten al backend por tarea delegada.
    backend_max_tool_rounds: int = 3
    #: ``LIVE_BACKEND_WEB_SEARCH``: el backend puede buscar en internet (herramienta
    #: ``web_search`` de la API Responses, la ejecuta OpenAI) para responder lo que no
    #: está en la base de conocimiento. Cada búsqueda cobra aparte.
    backend_web_search: bool = True
    #: Cuánto contexto de la web lee cada búsqueda: ``low`` (más rápido), ``medium`` o ``high``.
    backend_web_search_context: str = "low"
    #: Dónde está Sonia, para que la búsqueda dé resultados locales (país ISO y ciudad).
    backend_web_search_country: str = "DO"
    backend_web_search_city: str = "Santo Domingo"
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
    #: Puerta de la cámara, parte de la misma puerta del micro (``MicGate`` en
    #: ``sonia/live/audio.py``): OpenCV busca caras cada ``presence_scan_seconds``,
    #: en este equipo y sin guardar nada, con el modelo YuNet que baja el
    #: reconocimiento de caras (``FACES_DIR``). Solo con ``VISION_SOURCE=opencv``.
    #: Apagada al arrancar: con la API real GPT-Live ya ignora solo las voces del
    #: pasillo (docs/stand.md, «Voces del pasillo»). Se enciende en caliente con
    #: el interruptor del panel, que manda sobre esto.
    presence_gate: bool = False
    #: Sin una cara cerca ni conversación en este tiempo, GPT-Live deja de oír el
    #: micro. Muy generoso a propósito: dejarla sorda con alguien delante es mucho
    #: peor que oír el pasillo un rato.
    presence_hold_seconds: float = 600.0
    presence_scan_seconds: float = 0.5
    #: Ancho mínimo de la cara en una foto de 640 px (unos 1,8 m con una webcam
    #: normal): quien pasa por el pasillo no cuenta.
    presence_min_face_px: int = 38
    #: Con alguien delante de la cámara ahora mismo, la puerta de ruido se abre con
    #: este tanto de ``gate_rms``: quien habla bajito delante de Sonia también
    #: pasa. 1 = no cambia.
    presence_near_gate_scale: float = 0.5
    #: Ruido muy suave (RMS 0..1) que oye GPT-Live cuando no se le manda el
    #: micrófono (puerta cerrada, nadie delante, micro silenciado, frase grabada,
    #: ``--no-mic``). Con ceros absolutos entendía al visitante con 7 a 40 s de
    #: retraso y no decía lo que le devolvía el backend hasta volver a oír algo.
    #: 0 = ceros.
    comfort_noise_rms: float = 0.003
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
    #: De lo que no es baile, qué parte son momentos: una invitación a acercarse
    #: que improvisa GPT-Live con lo que pasa ahora (la charla que toca, lo que ve
    #: la cámara o algo que se puede probar) en vez de una frase fija. 0 = solo
    #: frases fijas.
    moment_chance: float = 0.6
    #: Que los momentos tiren también de lo que ve la cámara (una foto y su
    #: descripción con el modelo de visión cada pocos momentos; no se guarda).
    moment_camera: bool = True


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
    #: Tras la última respuesta, mínimo que se ve el resultado antes de la pantalla final.
    #: Entre preguntas no hay tiempo: la siguiente sale cuando el visitante la pide.
    reveal_seconds: float = 4.0
    #: Tope de espera a que Sonia termine de contar el resultado final antes de la pantalla final.
    final_wait_seconds: float = 20.0
    #: Nivel si el visitante no elige: fácil, intermedio o difícil.
    default_level: str = "intermedio"
    #: Con quién del stand manda Sonia a hablar a quien gana (vacío: a nadie). Sonia no sabe
    #: qué premios hay: los da el equipo (decisión de Jean del 8 de octubre de 2026).
    win_contact: str = "Brian o Mariel"


class RuletaSettings(BaseSettings):
    """La ruleta de Sonnia (``GAME_RULETA_*``, docs/juegos/ruleta.md)."""

    model_config = SettingsConfigDict(
        env_prefix="GAME_RULETA_", extra="ignore", env_ignore_empty=True
    )

    enabled: bool = True
    #: Pesos de las cinco casillas, en orden: trivia relámpago, adivinanza geek, explica en
    #: 20 segundos, predice el futuro de la IA y reto sorpresa de Sonnet Code.
    weights: str = "1,1,1,1,1"
    #: Contador (solo visual) de la trivia relámpago.
    quiz_seconds: float = 20.0
    #: La pista de la adivinanza sale a estos segundos.
    hint_seconds: float = 30.0
    #: Tiempo para explicar una tecnología.
    explain_seconds: float = 20.0
    #: Sin voz ni nadie delante durante esto, la partida se cancela (0: ``GAMES_ABANDON_SECONDS``).
    abandon_seconds: float = 60.0


class PosesSettings(BaseSettings):
    """Simón dice con poses (``GAME_POSES_*``, docs/juegos/poses.md)."""

    model_config = SettingsConfigDict(
        env_prefix="GAME_POSES_", extra="ignore", env_ignore_empty=True
    )

    enabled: bool = True
    #: Rondas por partida, de las que ``tricks`` son trampa (nunca la primera).
    rounds: int = 6
    tricks: int = 1
    #: Ventana tras la orden en la que se cuenta quién hace la pose (cuenta el mejor frame).
    window_seconds: float = 1.8
    #: Altura mínima de una persona en la imagen (fracción) para contar como jugador.
    min_person: float = 0.25
    #: Detecciones por segundo.
    fps: float = 8.0
    #: Variante del modelo de poses: ``n`` (ligero, la mitad de CPU con Unity en marcha) o
    #: ``s`` (algo más preciso con gente tapada). Por defecto ``n`` (10 de octubre de 2026).
    model: str = "n"
    #: 0: ``GAMES_ABANDON_SECONDS``.
    abandon_seconds: float = 0.0


class AkinatorSettings(BaseSettings):
    """Akinator dev (``GAME_AKINATOR_*``, docs/juegos/akinator.md)."""

    model_config = SettingsConfigDict(
        env_prefix="GAME_AKINATOR_", extra="ignore", env_ignore_empty=True
    )

    enabled: bool = True
    #: Preguntas de sí o no como mucho antes de pedir la respuesta.
    max_questions: int = 20
    #: No intenta adivinar antes de esta pregunta.
    min_questions: int = 5
    abandon_seconds: float = 60.0


class PptSettings(BaseSettings):
    """Piedra, papel o tijera (``GAME_PPT_*``, docs/juegos/piedra_papel_tijera.md)."""

    model_config = SettingsConfigDict(env_prefix="GAME_PPT_", extra="ignore", env_ignore_empty=True)

    enabled: bool = True
    #: Al mejor de estas rondas.
    rounds: int = 3
    #: Tiempo de lectura de la mano tras el «¡ya!» (se queda con la lectura estable).
    read_seconds: float = 0.8
    #: Detecciones por segundo mientras se juega.
    fps: float = 8.0
    #: Veces que se repite una ronda si no se ve la mano.
    retries: int = 1
    #: 0: ``GAMES_ABANDON_SECONDS``.
    abandon_seconds: float = 0.0


class WordleSettings(BaseSettings):
    """Wordle de tecnología (``GAME_WORDLE_*``, docs/juegos/wordle.md)."""

    model_config = SettingsConfigDict(
        env_prefix="GAME_WORDLE_", extra="ignore", env_ignore_empty=True
    )

    enabled: bool = True
    #: Intentos.
    rows: int = 6
    #: La pista sale tras estos intentos fallidos.
    hint_after: int = 4
    abandon_seconds: float = 90.0


class BusquedaSettings(BaseSettings):
    """Búsqueda relámpago (``GAME_BUSQUEDA_*``, docs/juegos/busqueda.md)."""

    model_config = SettingsConfigDict(
        env_prefix="GAME_BUSQUEDA_", extra="ignore", env_ignore_empty=True
    )

    enabled: bool = True
    rounds: int = 3
    #: Duración de cada ronda.
    round_seconds: float = 25.0
    #: Cada cuánto va una foto reducida al modelo de visión.
    check_seconds: float = 2.5
    #: Tope de fotos al modelo de visión por ronda.
    max_checks: int = 10
    #: 0: ``GAMES_ABANDON_SECONDS``.
    abandon_seconds: float = 0.0


class GamesSettings(BaseSettings):
    """Los juegos del stand (``sonia/games``, docs/juegos.md).

    Cada juego tiene además su bloque (``GAME_<JUEGO>_*``). Un juego solo se ofrece si
    está encendido aquí y en ``games/registry.py``, no está apagado desde el panel
    (``games_off``) y la Unity conectada lo anuncia (``client_hello.games``).
    """

    model_config = SettingsConfigDict(env_prefix="GAMES_", extra="ignore", env_ignore_empty=True)

    #: ``GAMES_ENABLED``: con ``false`` no se ofrece ningún juego.
    enabled: bool = True
    #: Sin voz ni nadie delante durante esto, la partida se cancela (el visitante se fue).
    abandon_seconds: float = 60.0
    #: Si el visitante habla en plena partida y en este tiempo no se delega nada, se le
    #: recuerda a Sonia que delegue la jugada (solo los juegos que lo piden).
    nudge_seconds: float = 3.0
    #: Al terminar, el resultado se queda al menos esto en pantalla...
    result_seconds: float = 4.0
    #: ...y como mucho esto esperando a que Sonia termine de contarlo.
    final_wait_seconds: float = 20.0
    #: Modelos de visión de los juegos (poses, manos), como los de caras.
    models_dir: str = str(_HOME / "cache" / "games" / "modelos")
    #: ``GAMES_JUDGE``: quién decide las rondas de cámara. ``gemini`` (por defecto, 10 de octubre
    #: de 2026): una foto reducida por ronda de Simón dice y de piedra, papel o tijera a Gemini
    #: (con ``GEMINI_API_KEY``), y la búsqueda relámpago también; la detección local sigue para
    #: la vista en vivo y decide si Gemini no contesta a tiempo. ``local``: como antes, todo en
    #: este equipo (y la búsqueda con el modelo de visión, ``LLM_*``). Es el de arranque: el
    #: panel lo cambia en caliente con el ajuste compartido ``games_judge``.
    judge: Literal["gemini", "local"] = "gemini"
    #: Plazo del juez de Gemini en Simón dice y en piedra, papel o tijera (la búsqueda usa el
    #: suyo). Medido el 10 de octubre de 2026: mediana 1,25 s, p90 1,7 s, máximo 2,8 s.
    judge_timeout_seconds: float = 4.0

    ruleta: RuletaSettings = Field(default_factory=RuletaSettings)
    poses: PosesSettings = Field(default_factory=PosesSettings)
    akinator: AkinatorSettings = Field(default_factory=AkinatorSettings)
    ppt: PptSettings = Field(default_factory=PptSettings)
    wordle: WordleSettings = Field(default_factory=WordleSettings)
    busqueda: BusquedaSettings = Field(default_factory=BusquedaSettings)


class AgendaSettings(BaseSettings):
    """Agenda del DevFest leída de su web (``sonia/agenda``, docs/agenda.md).

    Se descarga al arrancar y cada ``refresh_minutes``; el código compara cada
    versión con la anterior y le pasa a Sonia solo lo que cambió. Sin red se usa
    la última que se bajó (``cache/agenda.json``) o la copia que trae la app.
    """

    model_config = SettingsConfigDict(env_prefix="AGENDA_", extra="ignore", env_ignore_empty=True)

    #: Página de la agenda. ``AGENDA_URL=off`` no la consulta (solo caché y copia de la app).
    url: str = "https://devfest.gdgsantodomingo.org/schedule"
    #: Cada cuánto se vuelve a mirar si cambió (0 = solo al arrancar y cuando Sonia lo pide).
    refresh_minutes: float = 10.0
    #: Minutos antes de cada charla en que se le pasa a Sonia la hora y lo que empieza
    #: (nota ``[Reloj]``). Es la única nota de hora: con una por minuto la decía sin
    #: venir a cuento. 0 = nunca.
    notice_minutes: float = 5.0
    #: Tope de cada descarga: Sonia espera esto como mucho cuando la consulta ella.
    timeout_seconds: float = 6.0
    #: Última agenda descargada, para arrancar sin red.
    cache_file: str = str(_HOME / "cache" / "agenda.json")

    @property
    def enabled(self) -> bool:
        return self.url.strip().lower() not in ("", "off", "false", "0", "no")


class FaceSettings(BaseSettings):
    """Reconocer al equipo de Sonnet Code y a los ponentes delante de la cámara (``sonia/faces``, docs/caras.md).

    Corre entero en este equipo (OpenCV) y solo conoce a quien sale en la lista
    del equipo (``assets/faces/staff.json``) y en la agenda: de los visitantes no
    se guarda nada. Los umbrales salen de medir las 38 fotos reales el 7-oct-2026:
    dos personas distintas llegaron a 0,46 de similitud y la misma persona en
    fotos distintas, a 0,60-0,65.
    """

    model_config = SettingsConfigDict(env_prefix="FACES_", extra="ignore", env_ignore_empty=True)

    #: ``FACES_ENABLED``: con ``false`` Sonia no reconoce a nadie.
    enabled: bool = True
    #: Reconocer también a los ponentes de la agenda (con su foto de la web del DevFest).
    speakers: bool = True
    #: Modelos, huellas y fotos locales del equipo (``modelos/``, ``huellas/``, ``fotos/``).
    dir: str = str(_HOME / "cache" / "faces")
    #: Lista del equipo; vacío = ``assets/faces/staff.json``.
    staff_file: str = ""
    #: Personas conocidas que no son del equipo ni ponentes; vacío = ``assets/faces/invitados.json``.
    guests_file: str = ""
    #: Contexto para saludar (por persona y por grupo); vacío = ``assets/faces/saludos.json``.
    greetings_file: str = ""
    #: ``FACES_MODEL``: qué modelo saca las huellas. ``arcface`` (ArcFace R50 de InsightFace,
    #: 174 MB) reconoce el doble que ``sface`` (el de OpenCV, el de antes del 8-oct-2026) de
    #: lado, lejos y a oscuras con las mismas falsas alarmas (docs/caras.md). Cada uno tiene
    #: sus huellas y su umbral: volver a SFace no rehace nada.
    model: Literal["arcface", "sface"] = "arcface"
    #: Similitud mínima con ArcFace para dar a alguien por reconocido (medida con CPLFW: unas
    #: 7 falsas alarmas por cada 100 000 fotos de desconocidos con 41 personas conocidas).
    arcface_threshold: float = 0.40
    #: Similitud mínima con SFace (``FACES_MODEL=sface``).
    threshold: float = 0.52
    #: Ventaja mínima sobre la segunda persona más parecida; si no, no se arriesga.
    margin: float = 0.06
    #: Ancho mínimo de la cara, en píxeles de la foto en la que se buscan (la de la cámara,
    #: hasta ``analysis_width``). Hasta 40 px el tamaño apenas quita parecido (medido con las
    #: fotos de referencia: 0,84 de media frente a 0,92); por debajo cae deprisa. A 1920 px son
    #: unos cuatro metros con una webcam normal.
    min_face_px: int = 40
    #: Ancho máximo de la foto en la que se buscan caras (0 = la de la cámara): no la de 768 px
    #: de la visión, que dejaba fuera a quien estaba a más de un metro (docs/caras.md).
    analysis_width: int = 1920
    #: Cada cuánto mira la cámara por su cuenta, con sesión abierta (0 = solo cuando Sonia mira).
    #: Cada segundo: con una sola foto de referencia, solo pasa el umbral quien mira de frente
    #: a la cámara, y cuanto más se mira, antes se le pilla así (docs/caras.md, 8-oct-2026).
    scan_seconds: float = 1.0
    #: Revisiones en que tiene que salir alguien antes de avisar a Sonia, seguidas o no...
    confirm_scans: int = 2
    #: ...dentro de estos segundos (nunca menos de dos revisiones seguidas).
    confirm_seconds: float = 4.0
    #: Minutos sin volver a avisar de la misma persona, salvo que Sonia use la cámara.
    cooldown_minutes: float = 20.0
    #: Tope de la descarga de cada foto de referencia y de los modelos.
    download_timeout_seconds: float = 60.0


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
    #: ``PANEL_CAMERA_STREAM``: mandar la cámara (y el micrófono en el Modo Jean) a la
    #: sala de vídeo del panel de Cloudflare, para «Ver cámara» y el Modo Jean. Las
    #: builds de prueba lo traen apagado (``build.env``): así nadie del panel puede ver
    #: ni oír a quien la está probando.
    camera_stream: bool = True
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
    gestures: GestureSettings = Field(default_factory=GestureSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    vision: VisionSettings = Field(default_factory=VisionSettings)
    ws: WSSettings = Field(default_factory=WSSettings)
    showcase: ShowcaseSettings = Field(default_factory=ShowcaseSettings)
    trivia: TriviaSettings = Field(default_factory=TriviaSettings)
    games: GamesSettings = Field(default_factory=GamesSettings)
    panel: PanelSettings = Field(default_factory=PanelSettings)
    agenda: AgendaSettings = Field(default_factory=AgendaSettings)
    faces: FaceSettings = Field(default_factory=FaceSettings)

    assets_dir: str = str(BUNDLE_ROOT / "assets")
    log_level: str = "INFO"
    #: ``DEVICES_FILE``: micrófono y cámara elegidos en el menú de opciones (sonia/devices.py).
    devices_file: str = str(_HOME / "cache" / "devices.json")
    #: ``TIMEZONE``: la hora que Sonia sabe y dice (la del stand, no la del equipo).
    timezone: str = "America/Santo_Domingo"
    #: Reiniciar la conversación tras N segundos sin actividad (modo kiosco).
    idle_reset_seconds: float = 120.0
    #: Retirar sola una imagen mostrada tras N segundos (0 = nunca). El modelo
    #: la retira al cambiar de tema, pero si se olvida no se queda ahí.
    image_auto_hide_seconds: float = 30.0
    #: ``GALLERY_WATCH_SECONDS``: cada cuánto se mira ``assets/gallery``; lo que el
    #: equipo añade o quita se le cuenta a la sesión abierta con una nota silenciosa
    #: ``[Galería]`` (0 = no mirar: la lista nueva llega con la siguiente sesión).
    gallery_watch_seconds: float = 5.0
    #: ``GALLERY_UPLOAD_DIR``: dónde se guardan las imágenes que se suben desde el
    #: panel. Escribible y fuera de ``assets``: en la ``.app`` de macOS ``assets`` va
    #: dentro del paquete y escribir ahí rompe la firma.
    gallery_upload_dir: str = str(_HOME / "cache" / "gallery")
    #: ``MEETING``: Sonia está en una videollamada (Google Meet), no en el stand.
    #: Lo pone ``sonia reunion``; cambia sus instrucciones (``live/prompts.py``) y
    #: quita la animación de stand (docs/reunion.md).
    meeting: bool = False
    #: ``TRIAL_LIMIT_MINUTES``: minutos de conversación (sesión de GPT-Live abierta)
    #: que tiene esta Sonia en total, sumando todos sus arranques. Al llegar, se
    #: queda en «Fuera» con un letrero y ya no conversa. Lo ponen las builds de
    #: prueba del equipo (``build.env``); 0 (por defecto) es sin límite.
    trial_limit_minutes: float = 0.0
    #: ``KNOWLEDGE_EXTRA_DIR``: otra carpeta de conocimiento que se lee después de la
    #: del stand, para pruebas con datos que no deben llegar al stand. Vacía por defecto.
    knowledge_extra_dir: str = ""
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
    def knowledge_dirs(self) -> list[Path]:
        """La del stand y, si se pide, la extra (``KNOWLEDGE_EXTRA_DIR``)."""
        extra = [Path(self.knowledge_extra_dir)] if self.knowledge_extra_dir.strip() else []
        return [self.knowledge_dir, *extra]

    @property
    def faces_staff_file(self) -> Path:
        """Lista del equipo de Sonnet Code que Sonia reconoce (``FACES_STAFF_FILE``)."""
        custom = self.faces.staff_file.strip()
        return Path(custom) if custom else Path(self.assets_dir) / "faces" / "staff.json"

    @property
    def faces_guests_file(self) -> Path:
        """Personas conocidas que Sonia reconoce además del equipo y los ponentes (``FACES_GUESTS_FILE``)."""
        custom = self.faces.guests_file.strip()
        return Path(custom) if custom else Path(self.assets_dir) / "faces" / "invitados.json"

    @property
    def faces_greetings_file(self) -> Path:
        """Contexto propio para saludar a algunas personas conocidas (``FACES_GREETINGS_FILE``)."""
        custom = self.faces.greetings_file.strip()
        return Path(custom) if custom else Path(self.assets_dir) / "faces" / "saludos.json"

    @property
    def agenda_fallback_file(self) -> Path:
        """Copia de la agenda que trae la app, para cuando no hay red ni caché."""
        return Path(self.assets_dir) / "agenda" / "agenda.json"

    @property
    def trivia_file(self) -> Path:
        return Path(self.assets_dir) / "trivia" / "preguntas.md"

    @property
    def games_dir(self) -> Path:
        """Bancos de los juegos que trae la app: ``assets/games/<juego>/*.md``."""
        return Path(self.assets_dir) / "games"


def load_settings() -> Settings:
    """Carga las variables (`overrides.env`, el `.env` del repo o de la app, y el del cwd) y construye la configuración."""
    from dotenv import load_dotenv

    # Sin override: el primero que define una variable gana.
    for candidate in (*env_files(), Path(".env")):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
    return Settings()
