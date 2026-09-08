# CLAUDE.md

Guía para trabajar en este repositorio con Claude Code.

## Qué es este proyecto

Sonia es un asistente de IA por voz en tiempo real con avatar 3D, similar a los avatares de Grok, que corre completamente en local. Ve a través de una cámara (capturas puntuales, no vídeo) y puede mostrar imágenes dentro de su escena 3D. Se construye para el stand de Sonnet Code en DevFest Santo Domingo 2026 (9 y 10 de octubre de 2026). El público serán visitantes de un evento de desarrolladores, así que la demo tiene que ser robusta, rápida y funcionar sin conexión a internet.

## Principios que no se negocian

1. **Todo corre local.** Ningún componente puede depender de una API en la nube. No añadas SDKs de OpenAI, Anthropic, Google, ElevenLabs ni similares como dependencia de ejecución. Si un módulo necesita red para funcionar, está mal diseñado.
2. **Agnóstico al modelo.** El orquestador habla con un endpoint compatible con OpenAI configurado por variables de entorno (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`). Kimi K3 es el modelo por defecto, pero ningún archivo de código debe mencionarlo por nombre. Nada de prompts, parsers ni ajustes específicos de un modelo. La visión y las acciones usan los formatos estándar de la API (contenido de imagen en `image_url` y tool calling), y deben degradar limpiamente si el modelo configurado no soporta imágenes o herramientas.
3. **Latencia primero.** Todo el pipeline es streaming. Meta: menos de dos segundos entre que el usuario termina de hablar y Sonia empieza a responder. Cualquier cambio que añada latencia perceptible necesita justificación.
4. **Demo de stand, no producto.** Prioriza que funcione de forma fiable durante ocho horas seguidas sobre la elegancia arquitectónica. Reinicios automáticos, timeouts y degradación controlada valen más que abstracciones.

## Stack

- **Orquestador:** Python 3.12, gestionado con `uv`. Formateo y lint con `ruff`. Tipado con anotaciones y `mypy` en modo estricto donde sea razonable.
- **Detección de voz:** Silero VAD.
- **Reconocimiento de voz:** faster-whisper, español.
- **Modelo de lenguaje:** cualquier servidor con API compatible con OpenAI (llama.cpp, vLLM, Ollama). Por defecto Kimi K3, que es multimodal.
- **Visión:** cámara USB leída con OpenCV. Solo capturas puntuales, reducidas antes de enviarlas al modelo. Nunca streaming de vídeo al LLM.
- **Acciones del modelo:** tool calling estándar de OpenAI como vía principal. Las mismas acciones se exponen también como servidor MCP local (`server/mcp`) para modelos o servidores sin tool calling nativo. Una única definición de acciones alimenta ambas vías.
- **Síntesis de voz:** OmniVoice, detrás de una interfaz `TextToSpeech` sustituible.
- **Avatar:** Unity (LTS más reciente), C#, assets gratuitos. Personaje femenino. Lip-sync por visemas a partir del audio o de los timestamps que envíe el orquestador. Incluye un panel de imágenes integrado en la escena hacia el que el avatar puede orientarse.
- **Comunicación:** WebSocket local entre orquestador y Unity. Mensajes JSON para eventos y binario para audio PCM.

## Estructura

```
server/     Orquestador Python. Un módulo por etapa: vad, stt, vision, llm, actions, tts, ws, mcp.
unity/      Proyecto Unity. Scripts en unity/Assets/Scripts.
assets/     Galería local de imágenes que Sonia puede mostrar (logos, diagramas, material del stand).
scripts/    Arranque de servicios locales, descarga de modelos, checks del stand.
docs/       Decisiones de diseño (ADR cortos), protocolo WebSocket, licencias de assets.
```

## Acciones del modelo

Definidas una sola vez en `server/actions` y expuestas por tool calling y por MCP.

| Acción | Qué hace |
|---|---|
| `look` | Toma una captura fresca de la cámara y la devuelve al modelo como imagen. |
| `show_image` | Muestra una imagen en el panel de la escena de Unity. Acepta un id de la galería local o `camera` para la última captura. Opcionalmente un pie de texto. |
| `hide_image` | Retira el panel de imágenes. |

Además de la acción `look`, el orquestador adjunta automáticamente una captura al turno cuando detecta que alguien empieza a hablar, y opcionalmente cada cierto tiempo mientras hay presencia. Esa política vive en `server/vision` y se controla por variables de entorno (`VISION_ON_TURN_START`, `VISION_INTERVAL_SECONDS`). Si `LLM_SUPPORTS_VISION=false`, la capa de visión se desactiva entera y `look` deja de anunciarse al modelo.

Al añadir una acción nueva: definirla en `server/actions`, escribir su handler, añadir el mensaje correspondiente al protocolo WebSocket si afecta a Unity, e implementar el lado de Unity en el mismo commit.

## Protocolo entre orquestador y Unity

Documentado en `docs/protocolo.md` cuando exista. Mientras tanto, la idea:

- El orquestador envía eventos de estado: `listening`, `thinking`, `speaking`, `idle`.
- El audio viaja en chunks PCM 16 bit mono con la tasa de muestreo que produzca OmniVoice.
- Junto a cada chunk van los visemas con su timestamp para el lip-sync.
- El orquestador envía `show_image` con la imagen en base64 o una ruta de la galería, más el pie de texto opcional, y `hide_image` para retirarla. Unity decide cómo integrarlo con el avatar (panel, giro de cabeza, gesto).
- Unity envía `interrupt` cuando detecta que el usuario ha empezado a hablar mientras Sonia habla. El orquestador cancela la generación y la síntesis en curso.

Si cambias el protocolo, actualiza ambos lados y el documento en el mismo commit.

## Convenciones

- Idioma del código y los comentarios: español para comentarios y documentación, inglés para identificadores (nombres de variables, funciones, clases).
- Commits cortos en español, en imperativo: "Añade interrupción por VAD".
- Configuración solo por variables de entorno y `.env`. Nunca hardcodear rutas de modelos, puertos ni claves.
- Los modelos pesados (pesos de LLM, STT, TTS) no se suben al repo. Van en `.gitignore` y se descargan con `scripts/`.
- Las capturas de cámara no se guardan en disco salvo en modo debug explícito. Es una demo pública con visitantes reales: nada de persistir imágenes de personas.
- Los assets de Unity de terceros se documentan en `docs/licencias.md` con nombre, autor, licencia y enlace.

## Comandos

Se completarán cuando exista el código. Formato esperado:

```bash
uv sync                          # instalar dependencias del orquestador
uv run sonia                     # arrancar el orquestador
uv run ruff check . && uv run ruff format .
uv run pytest
```

## Cosas que no hay que hacer

- No introducir dependencias de red en tiempo de ejecución.
- No acoplar el código a Kimi K3 ni a ningún modelo concreto.
- No bloquear el hilo de audio con llamadas síncronas al LLM o al TTS.
- No enviar vídeo continuo ni capturas en cada frame al modelo. Solo fotos puntuales, reducidas, cuando aporten.
- No guardar en disco capturas de la cámara fuera del modo debug.
- No implementar una acción solo en tool calling o solo en MCP. Siempre ambas desde la misma definición.
- No subir pesos de modelos ni builds de Unity al repositorio.
- No añadir funcionalidades que no aporten a la demo del stand sin discutirlo antes.

## Contexto del evento

- Evento: DevFest Santo Domingo 2026, organizado por GDG Santo Domingo.
- Fecha: 9 y 10 de octubre de 2026.
- Lugar: Biblioteca Nacional Pedro Henríquez Ureña, Santo Domingo, República Dominicana.
- Stand: Sonnet Code (https://www.sonnetcode.com/es).
- Sonia debe poder presentarse, explicar qué es Sonnet Code brevemente si se lo preguntan y mantener una conversación casual en español con acento y registro naturales para el Caribe.
- Debe usar la cámara con naturalidad: saludar a quien se acerca, notar si hay varias personas, comentar algo que le enseñen. Sin describir a la gente de forma invasiva ni hacer comentarios sobre aspecto físico.
- Debe apoyarse en el panel de imágenes cuando ayude a explicar algo, por ejemplo mostrar el logo o un diagrama de Sonnet Code, y retirarlo cuando cambie de tema.
