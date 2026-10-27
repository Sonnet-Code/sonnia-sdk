# Sonnia Video

`sonnia-video` hace vídeos y fotos de Sonnia para redes sociales (Instagram, TikTok, YouTube Shorts) y para los reels de `media/` del repo de Sonnet Code, sin abrir Unity ni recompilar nada: se escribe un guion, se elige la voz (Gemini, ElevenLabs o un audio grabado) y sale un MP4 listo para subir (o un MOV con alfa y los cuadros PNG para montar a Sonnia encima de otra cosa) con sus subtítulos en SRT.

Por dentro, Sonnia es la misma del stand: el avatar de Genies con la camiseta del staff (o lisa), el lip-sync por fonemas y los gestos de Sage elegidos por el modelo de gestos. Un renderizador de Unity («Sonnia Video.app», sin ventana) reproduce los mismos mensajes que manda el orquestador en el stand, pero a paso fijo y cuadro a cuadro, así que el vídeo sale limpio aunque el equipo vaya lento. Los vídeos salen **sin el HUD del stand** (ni logo, ni QR, ni subtítulos en pantalla, decisión de Jean del 27 de octubre de 2026): los subtítulos van solo en el `.srt`.

## Instalación

Desde el repo (todo desde `server/`):

```bash
uv sync --group dev --extra audio --extra camera --extra panel --extra video
uv run --no-sync sonnia-video --help
```

- El extra `video` trae `imageio-ffmpeg`, un ffmpeg con H.264 (libx264), ProRes, PNG y AAC ya compilado (comprobado en macOS arm64 el 27 de octubre de 2026). Sin él vale el de Homebrew (`brew install ffmpeg`) o cualquiera que diga `SONNIA_FFMPEG`.
- El renderizador es una build de Unity: `unity/Build/macOS-video/Sonnia Video.app`, `/Applications/Sonnia Video.app` o la ruta de `SONNIA_VIDEO_APP`.

Congelado (sin Python instalado): `scripts/build_sonnia_video.sh` deja `unity/Build/sonnia-video/<plataforma>/sonnia-video/` con el ejecutable, su Python y el ffmpeg de imageio. Para que «Sonnia Video.app» lo lleve, esa carpeta se copia en `Sonnia Video.app/Contents/Resources/sonnia-video/`; desde ahí encuentra su app sola. No lleva claves. Todo es por terminal: no hay interfaz gráfica.

### Claves

| Clave | Para qué |
|---|---|
| `GEMINI_API_KEY` | Voz de Gemini, tiempos por palabra (transcripción) y gestos. Sin ella no hay voz de Gemini; con otro motor, los tiempos salen del respaldo local y los gestos del modelo de `LLM_*` si tiene clave. |
| `ELEVENLABS_API_KEY` | Voz de ElevenLabs y su lista de voces. |

Se leen del entorno o de un `.env`, por este orden (manda el primero que la tiene): el entorno, `<carpeta de datos>/.env`, el `.env` junto al ejecutable congelado y, al ejecutarlo desde el repo, el `.env` del repo. Nunca se imprimen.

### Carpeta de datos

`~/Library/Application Support/Sonnia Video` en macOS y `%APPDATA%/Sonnia Video` en Windows (`SONNIA_VIDEO_HOME` la cambia). Dentro:

| Carpeta | Qué hay |
|---|---|
| `videos/` | Los vídeos y sus SRT (si no se dice otra con `--out`). Con fondo transparente, también `<titulo>/sonnia/`, el paquete para reels. |
| `fotos/` | Las fotos de `sonnia-video foto`. |
| `cache/voz/`, `cache/tiempos/` | Las tomas de voz y las transcripciones ya pagadas. |
| `trabajos/<id>/` | Lo de cada trabajo de Unity: los WAV de cada frase, `registro.json`, `heard.wav` y `voz_final.wav`. Se guardan los 10 últimos. |
| `unity.log` | El registro del renderizador. |

## Uso

```bash
sonnia-video ejemplo > guion.toml          # un guion con todas las opciones comentadas
sonnia-video render guion.toml             # → <datos>/videos/<titulo>.mp4 y .srt
sonnia-video render guion.toml --formato cuadrado --luz dramatica --out ~/Desktop
sonnia-video decir "¡Hola! Soy Sonnia. Nos vemos en el DevFest." --voz gemini:es-419-commercial-6
sonnia-video render guion.toml --reel ~/Documents/git/sonnet-code/media/reels/mi-reel   # MOV con alfa + paquete en el reel
sonnia-video foto --gesto waveCalm --rafaga 6 --fondo transparente --formato 4k-vertical
sonnia-video vista guion.toml --encuadre primer-plano   # PNG rápido de la escena, sin voz
```

Repetir un vídeo cambiando solo la escena (luz, fondo, encuadre...) no vuelve a pagar la voz: sale de la caché.

### Órdenes

| Orden | Qué hace |
|---|---|
| `render guion.toml` | El vídeo de un guion. |
| `decir "texto"` | Lo mismo con el texto en la línea de órdenes: cada oración (cortada tras `.`, `!`, `?` o `…`) es una frase del guion. |
| `foto [guion.toml]` | Fotos de Sonnia en PNG (con alfa si el fondo es transparente), con supermuestreo ×3. Ver «Fotos». |
| `vista [guion.toml]` | Una imagen rápida de la escena con la calidad del guion (`--png ruta`). |
| `ejemplo` | Imprime un guion de ejemplo con todas las opciones. |
| `voces [gemini\|elevenlabs]` | Las voces: las conocidas de Gemini y las de la cuenta de ElevenLabs (nombre e id). |
| `gestos` | Los gestos del catálogo (abre el renderizador si hace falta). |
| `estado` | Carpeta de datos, ffmpeg y estado del renderizador (versión, avatar, camiseta, trabajo). |
| `cerrar` | Cierra el renderizador. Se cierra solo tras 45 minutos sin peticiones (`SONNIA_VIDEO_IDLE_MIN` lo cambia). |

`-v` da más detalle. Ctrl+C durante el render cancela el trabajo en Unity.

### Opciones de la línea de órdenes

Pisan lo del guion.

- Escena (en `render`, `decir`, `foto` y `vista`): `--out DIR`, `--titulo`, `--formato` (`vertical`, `cuadrado`, `horizontal`, `4k-vertical` o `ANCHOxALTO`), `--luz`, `--fondo` (un modo, `transparente`, un color como `#000000` o la ruta de una imagen), `--encuadre` y `--emocion` (`alegre`, `neutra`).
- Vídeo (en `render` y `decir`): `--voz motor:voz` (`gemini:Leda`, `elevenlabs:Rachel`, `archivo:voz.wav`; sin `motor:` cambia solo la voz), `--fps`, `--calidad` (`borrador`, `normal`, `alta`), `--sin-gestos`, `--reel RUTA` (fondo transparente y el paquete en `<reel>/assets/sonnia/`) y `--forzar` (reemplaza los cuadros que ya haya en ese reel).
- Fotos (en `foto`): `--gesto NOMBRE`, `--espejo`, `--momento S` y `--rafaga N`.

## El guion

TOML con las claves en español. Solo las frases son obligatorias. Los errores salen en español y dicen dónde («escena → luz: valor no válido; vale stand, estudio...»).

**El nombre.** Se escribe «Sonnia» y se dice «Sonia» (CLAUDE.md, principio 6): en el SRT, en `palabras.json` y en los mensajes siempre sale «Sonnia» (aunque se escriba «Sonia») y al TTS le llega «Sonia».

| Tabla | Clave | Por defecto | Qué es |
|---|---|---|---|
| | `titulo` | las primeras palabras | Nombre de los archivos (`<titulo>.mp4`). |
| `[voz]` | `motor` | `gemini` | `gemini`, `elevenlabs` o `archivo`. |
| | `voz` | la de cada motor | Gemini: el nombre (`es-es-techagent-5`). ElevenLabs: el nombre o el `voice_id` (obligatoria). |
| | `modelo` | la de cada motor | `gemini-3.8-flash-tts`; `eleven_v4`. |
| | `estilo` | | Gemini: cómo habla, en texto (vacío: acento latinoamericano, cercana y alegre; `ninguno`: sin indicación). ElevenLabs: exageración del estilo, de 0 a 1. |
| | `estabilidad`, `similitud`, `velocidad` | los de la voz | Ajustes de ElevenLabs (0 a 1; velocidad de 0,7 a 1,2). |
| | `idioma` | | ElevenLabs: `language_code` (`es`). También el idioma de la transcripción (`es-419` si no). |
| | `archivo` | | Motor `archivo`: el WAV o MP3 (o lo que lea ffmpeg), relativo al guion. |
| `[pronunciacion]` | `"se ve" = "se dice"` | | Cambia lo que se dice sin cambiar lo que se ve: `"sonnetcode.com" = "sónet code punto com"`. Sin distinguir mayúsculas, solo palabras enteras. |
| `[video]` | `formato` | `vertical` | `vertical` (1080×1920), `cuadrado` (1080×1080), `horizontal` (1920×1080), `4k-vertical` (2160×3840) o `ANCHOxALTO` (pares). |
| | `fps` | 30 | Cuadros por segundo. |
| | `calidad` | `normal` | `borrador` (sin supermuestreo, CRF 23, rápido), `normal` (supermuestreo ×2, CRF 18) o `alta` (×2, desenfoque de movimiento con 4 subcuadros, CRF 14, `slow`). |
| | `antes`, `despues` | 0,6 y 1,5 | Segundos de reposo antes de la primera frase y después de la última. |
| | `reel` | | Carpeta de un reel de `media/reels/<id>`: el paquete va a `<reel>/assets/sonnia/`. Necesita `fondo = "transparente"`. |
| `[escena]` | `fondo` | `stand` | `stand` (el azul royal del stand), `color`, `degradado` (de `color` arriba a `color2` abajo), `imagen` o `transparente` (ver «Fondo transparente y reels»). |
| | `color`, `color2` | `#142752`, `#0B1322` | Colores del fondo. |
| | `imagen` | | PNG o JPG que cubre el cuadro (con `fondo = "imagen"`). |
| | `particulas` | `true` | Motas del escenario. |
| | `luz` | `stand` | `stand`, `estudio`, `suave`, `calida`, `fria` o `dramatica`. |
| | `luz_intensidad`, `luz_ambiente` | 1 | Multiplican la luz principal y la ambiente. |
| | `contraluz`, `contraluz_intensidad` | vacío, 1,5 | Color de un contraluz extra (vacío: ninguno) y su fuerza. |
| | `exposicion` | 0 | En pasos (EV). |
| | `encuadre` | `stand` | `stand`, `primer-plano`, `medio` (cintura), `americano` (medio muslo) o `cuerpo` (entero). |
| | `zoom`, `desplazar_x`, `desplazar_y` | 1, 0, 0 | Zoom (> 1 acerca) y desplazamiento en fracción del cuadro (positivo: a la derecha y abajo). |
| | `camiseta` | `staff` | `staff` (la del DevFest) o `lisa`. Se pone al cargar el avatar: si el renderizador abierto lleva la otra, se cierra y se vuelve a abrir (unos segundos más). |
| | `gorra` | `false` | La gorra de la trivia. |
| | `emocion` | `alegre` | `alegre` o `neutra`. |
| `[gestos]` | `modo` | `auto` | `auto` (los elige el modelo; los escritos mandan), `manual` (solo los escritos) o `ninguno`. |
| `[[frase]]` | `texto` | | Lo que dice. |
| | `gesto` | | Un gesto del catálogo (`sonnia-video gestos`), sin mirar mayúsculas. |
| | `pausa` | 0 | Silencio extra después de la frase. |
| `[[accion]]` | `gesto`, `en`, `espejo` | | Un gesto suelto en el segundo `en` del vídeo, fuera de las frases, para coreografiar como en los reels (`gesto = "knockKnock"`, `en = 0.0`, `espejo = true`: con la otra mano). |

Las tildes y mayúsculas de los valores dan igual (`cálida`, `Primer plano`). `logo`, `qr` y `subtitulos` ya no existen: un guion que los lleve da un error que lo explica.

## Fondo transparente y reels

Con `fondo = "transparente"` Unity entrega los cuadros RGBA con alfa (sin premultiplicar) y, en la misma pasada de ffmpeg, salen:

- `<salida>/<titulo>.mov`: ProRes 4444 con alfa (`prores_ks`, `yuva444p10le`, `alpha_bits 16`, `vendor apl0`) con la voz dentro (AAC 192k, −14 LUFS), para edición.
- El paquete `sonnia/` (en `<salida>/<titulo>/sonnia/`, o en `<reel>/assets/sonnia/` con `--reel`), con el formato que consume `secuencia()` de `media/framework/render/secuencia.js` (`media/README.md`, «Secuencias de imágenes» y «Línea de tiempo fija»), el mismo de `reels/devfest-sd-sede/assets/sonnia/`:

| Archivo | Qué es |
|---|---|
| `frames/sonnia_0000.png`... | RGBA del tamaño del cuadro, desde 0000. |
| `proxy/sonnia_0000.png`... | Lo mismo a la mitad, para el reproductor. |
| `prueba.png` | El primer cuadro (el `fallback`). |
| `voz.wav` | La voz final colocada desde el segundo 0 del vídeo, mono a 48 kHz, a −14 LUFS. |
| `palabras.json` | `[{"texto", "inicio", "fin"}]`: lo que se ve («Sonnia») con su tiempo en el vídeo. |
| `voz.json` | `archivo`, `duracion`, `frecuencia`, `origen`, `proceso`, `frases: [{texto, voz: [inicio, fin]}]` y los datos del TTS (`voz_gemini` o `voz_elevenlabs`). |
| `localizador.json` | `fps`, `ancho`, `alto`, `notas` y `cuadros: [{"cuadro": i, "cara": {"x", "y"}, "mano_der": {"x", "y", "z"}, ...}]`: `cabeza`, `cuello`, `pecho`, `cadera`, `mano_der`, `mano_izq`, `indice_*`, `nudillos_*`, `ojo_*` y `cara` (entre los ojos), en píxeles del cuadro (y hacia abajo); `z`, en metros a la cámara, solo en las manos. `_der` es la mano derecha de Sonnia, que sale a la izquierda de la pantalla. |

Con `--reel` se comprueba antes de gastar nada que la carpeta es un reel (tiene `reel.config.js`) y, si ya tiene cuadros, solo se reemplazan con `--forzar` (se borran `frames/`, `proxy/` y los archivos del paquete, nada más). Fuera de un reel, la carpeta de cada título se reemplaza sin preguntar. Al acabar se imprime lo que hay que pegar en el reel:

```js
// reel.config.js
timeline: { duration: 8.367, words: 'assets/sonnia/palabras.json', voice: 'assets/sonnia/voz.wav' },

// en la escena (scenes/<id>.js)
import { secuencia } from '../../../framework/render/secuencia.js';
const sonnia = secuencia(C, root, {
  dir: 'sonnia/frames/', name: (i) => `sonnia_${String(i).padStart(4, '0')}.png`, count: 251,
  proxy: { dir: 'sonnia/proxy/', name: (i) => `sonnia_${String(i).padStart(4, '0')}.png` },
  fallback: 'sonnia/prueba.png',
});
// en update(t): sonnia.update(t)
```

## Fotos

`sonnia-video foto [guion.toml]` hace PNG de Sonnia sin voz, con la escena del guion (o la de por defecto) y supermuestreo ×3. Con `--fondo transparente`, con alfa.

- `--gesto NOMBRE` lanza ese gesto en el segundo 0 (`--espejo`: con la otra mano) y la foto sale en `--momento S` segundos o, si no se dice, en el golpe del gesto (`critical_beat` de su ficha) o el medio de su núcleo.
- `--rafaga N` reparte N fotos por la duración del gesto (la de su ficha del catálogo), cada una en el medio de su tramo; sin gesto, por 3 segundos de reposo.
- Salen en `<datos>/fotos/` (o `--out`) como `<titulo>.png` o `<titulo>_01.png`... El título es el del guion, `--titulo` o `foto-<gesto>`.

## Voces

- **Gemini** (`GEMINI_API_KEY`): por defecto `es-es-techagent-5` (Tech Advisor 5) con un estilo de acento latinoamericano, la que eligió Jean para el comercial del DevFest del 9 de octubre de 2026 (sin el estilo sale castellana). `sonnia-video voces gemini` lista las del casting del repo de Sonnet Code (`es-419-assistant-1`, `es-419-commercial-6`...) y algunas globales (Leda, Kore, Aoede, Puck...). La API no las lista: vale cualquier otra que acepte Gemini.
- **ElevenLabs** (`ELEVENLABS_API_KEY`): las de la cuenta (`sonnia-video voces elevenlabs`), por nombre (vale el principio: «Rachel» encuentra «Rachel - calm») o por `voice_id`. Modelo por defecto `eleven_v4`, el de más calidad y multilingüe de su lista de modelos (consultada el 27 de octubre de 2026). Su documentación no dice si `eleven_v4` acepta tiempos por carácter y ajustes de voz: si lo rechaza, `sonnia-video` repite una vez con `eleven_multilingual_v2` y lo avisa. Límite por toma: 10 000 caracteres (`eleven_v3`, 5 000).
- **Archivo**: una locución grabada. Las frases tienen que ser lo que se oye: sirven para los subtítulos, los gestos y para cortar el audio.

## Gestos

Con `modo = "auto"`, una sola petición al modelo de gestos del stand (`GESTURE_*` de `sonia/config.py`: con `GEMINI_API_KEY`, `gemini-3.1-flash-lite` por su endpoint compatible con OpenAI) con el catálogo que da el renderizador y el guion entero. Como mucho un gesto por frase y sin repetir. Las reglas de frecuencia de Genies se aplican también en código, con los tiempos reales de cada frase (`sonia/video/gestures.py`, `schedule`):

- Un gesto no empieza hasta que acaba el núcleo del anterior más `GESTURE_MIN_GAP_S`; si para eso tendría que esperar más de `GESTURE_MAX_DELAY_S` desde que empieza su frase (o su frase ya ha acabado), se quita.
- Un `Uncommon` cada `GESTURE_UNCOMMON_S` y un `Rare` cada `GESTURE_RARE_S` como mucho.

Los escritos en `gesto` van siempre, y los `[[accion]]` a su hora. Si el modelo falla, el vídeo sale sin gestos elegidos y se avisa.

## Costes

Gasta solo lo que llama a las APIs; los tests no llaman a ninguna. El renderizador no gasta: solo baja el avatar de Genies.

| Qué | Cuándo |
|---|---|
| Voz (Gemini o ElevenLabs) | Una toma por guion distinto. Cambiar la escena, el formato o los gestos no la repite (caché). ElevenLabs descuenta caracteres del plan de la cuenta. |
| Transcripción (Gemini) | Una por toma nueva (también se guarda). No se usa con ElevenLabs, que da los tiempos. |
| Gestos (Gemini flash-lite) | Una petición corta por vídeo con `modo = "auto"`. |
| Fotos y vista previa | Nada. |

Para el precio, la tarifa vigente de cada proveedor.

## Velocidad

Medido por la sesión de Unity con la app 1.0.505: opaco a 1080×1920 con supermuestreo ×2 y sin desenfoque, unos 35 cuadros por segundo; transparente con 2 subcuadros y los PNG, unos 11. En el Mac de desarrollo, en `borrador`, 48 cuadros por segundo opaco y 22 a 25 transparente. El avatar tarda unos 10 s en cargar con la caché de Genies ya bajada.

## Cómo funciona

1. **Guion** (`sonia/video/script.py`): se valida con pydantic y cada frase se parte en trozos de lo que se ve, cada uno con las palabras que se dicen por él (`Unit`: «sonnetcode.com» → «sónet code punto com»).
2. **Voz** (`voice.py`, `gemini.py`, `elevenlabs.py`): una sola toma con todo el guion (más natural que frases sueltas). Gemini por su API «interactions» (como `media/framework/voice/gemini.mjs` del repo de Sonnet Code), ElevenLabs por `text-to-speech/{voice_id}/with-timestamps` en PCM de 24 kHz. Reintentos con espera creciente en 429 y 5xx.
3. **Tiempos por palabra** (`align.py`): de la alineación por caracteres de ElevenLabs o de `gemini-3.5-transcribe`, alineados con las palabras del guion con programación dinámica tolerante (números en cifra o en letra, signos, tildes, palabras partidas o juntas). Si casan menos de la mitad o no hay transcripción, el respaldo local reparte las palabras por los tramos con voz según su longitud, buscando antes las pausas entre frases.
4. **Plan** (`plan.py`): la toma se corta en frases por el medio del silencio entre la última palabra de una y la primera de la siguiente; se recortan los silencios de los extremos y se añade la `pausa` de cada frase. A Unity le llega cada frase en un WAV al nivel de GPT-Live (RMS mediano de las ventanas de 20 ms con voz ≈ 0,059, una sola ganancia para todo el guion y un limitador que no recorta): más fuerte, la boca iría siempre abierta.
5. **Línea de tiempo**: lo que manda el orquestador en el stand, con hora. `stage_mode` sin conversación y `state idle`; tras `antes` segundos, `state speaking`; por frase su `gesture`, `speech_start` y el audio; los `transcript` acumulados palabra a palabra (Unity ya no los pinta, pero no estorban); los `[[accion]]`; y `state idle` al acabar la voz.
6. **Unity** renderiza a paso fijo sin ventana, codifica con ffmpeg (opaco: H.264 en BT.709; transparente: ProRes 4444 y los PNG) y devuelve `registro.json` y `heard.wav`.
7. **Mezcla** (`ffmpeg.py`): la voz original (no la de Unity) se coloca donde sonó en Unity, comparando su envolvente con la de `heard.wav` (cada 5 ms, de −0,5 a +0,5 s); si no casa, con la mediana de `heard_t − t` del registro. Después se mide la sincronía boca-voz (correlación entre la apertura de la boca de cada cuadro y la envolvente de la voz, de −6 a +6 cuadros) y, si pasa de dos cuadros, se mueve la voz y se avisa: es una red, con `heard.wav` el desfase medido sale 0. Por qué no basta `heard_t`: con la app 1.0.505, `heard_t` ≈ `first_audio_t` (−9 y +2 ms), pero en `heard.wav` cada frase suena 91 y 102 ms después de `first_audio_t` más donde empieza la voz dentro de su propio WAV (`u001.wav`...): el retraso está en el reproductor de Unity, no en los cortes de la toma (la boca lo confirma: va 3 cuadros detrás de `heard_t`). Después `loudnorm` en dos pasadas a −14 LUFS (pico −1,5 dBTP) y AAC 192k estéreo a 48 kHz con `+faststart`, en el MP4 y en el MOV; el vídeo no se recodifica.
8. **SRT** (`srt.py`): con los tiempos de las palabras ya colocadas, líneas de 42 caracteres como mucho, dos líneas por subtítulo y sin mezclar frases. Dentro de una frase se elige el reparto de menos coste: mejor tras un punto, una coma o dos puntos; luego antes de un nexo («que», «en», «para»...); nunca tras un artículo o una preposición sueltos, nunca dentro de un nombre propio («Sonnet Code», «Santo Domingo», «Plaza de la Cultura») ni con una palabra sola en un subtítulo o en una línea, y con las dos líneas equilibradas. Entre subtítulos el corte pesa el doble que entre líneas: los subtítulos se cortan por frases y cláusulas. Un nombre que no cabe en una línea (más de 42 caracteres) se parte por donde menos desequilibra.

## Contrato con Unity

El renderizador se arranca siempre sin ventana ni icono en el Dock:

```
"<app>/Contents/MacOS/<ejecutable>" -batchmode -sonnia-video -sonnia-video-port 8795 [-sonnia-video-idle-min <min>] [-sin-camiseta-staff] -logFile <datos>/unity.log
```

El ejecutable es el único archivo de `Contents/MacOS/`. Va en un proceso aparte que sigue abierto para el siguiente vídeo y se cierra solo tras 45 minutos sin peticiones. Carga el avatar de Genies (de 10 s a varios minutos la primera vez; necesita red) y escucha en `127.0.0.1:<puerto>` (`SONNIA_VIDEO_PORT`, 8795). La camiseta se pone al cargar el avatar, así que va por argumento (`-sin-camiseta-staff` para la lisa): si la abierta lleva otra, `sonnia-video` la cierra (`/quit`, espera a que no conteste) y la vuelve a abrir.

| HTTP | Qué hace |
|---|---|
| `GET /status` | `{"app", "version", "avatar": "loading"\|"ready", "outfit": "staff"\|"plain", "busy", "job": null\|{"id", "kind", "state": "preparing"\|"rendering"\|"encoding"\|"done"\|"error"\|"cancelled", "frame", "frames", "render_fps", "error"}}`. No hay doble de respaldo: si Genies no entrega, sigue en `loading` hasta el tope de 15 minutos de `sonnia-video` y entonces da un error. |
| `GET /catalog` | El mismo JSON que el mensaje `gesture_catalog` del stand. 503 sin avatar. |
| `POST /job` | Un trabajo (abajo). 202 `{"ok": true, "id"}`; 409 si ya hay uno; 400 si no valida. |
| `POST /cancel` | Corta el trabajo en curso (`cancelled`). |
| `POST /quit` | Cierra la app. |

Trabajo:

```json
{
  "id": "gracias-devfest-20261027-153012",
  "kind": "video",
  "output_dir": "/…/trabajos/gracias-devfest-20261027-153012",
  "width": 1080, "height": 1920, "fps": 30,
  "supersample": 2, "subframes": 1, "shutter": 0.5,
  "duration_s": 24.0, "warmup_s": 2.0, "audio_sample_rate": 24000,
  "timeline": [
    {"t": 0.0, "message": {"type": "stage_mode", "mode": "greeter", "talk": false}},
    {"t": 0.0, "message": {"type": "state", "state": "idle"}},
    {"t": 0.0, "action": {"name": "knockKnock", "mirror": true}},
    {"t": 0.6, "message": {"type": "state", "state": "speaking"}},
    {"t": 0.6, "message": {"type": "gesture", "name": "waveCalm", "utterance_id": 1}},
    {"t": 0.6, "message": {"type": "speech_start", "utterance_id": 1, "text": ""}},
    {"t": 0.6, "audio": {"utterance_id": 1, "wav": "/…/u001.wav"}},
    {"t": 0.8, "message": {"type": "transcript", "role": "assistant", "text": "¡Hola!", "final": false}},
    {"t": 22.9, "message": {"type": "state", "state": "idle"}}
  ],
  "scene": {
    "background": {"mode": "stand", "color": "#142752", "color2": "#0B1322", "image": ""},
    "particles": true,
    "lighting": {"preset": "stand", "key": 1.0, "ambient": 1.0, "rim_color": "", "rim_intensity": 0.0, "exposure": 0.0},
    "framing": {"preset": "stand", "zoom": 1.0, "offset_x": 0.0, "offset_y": 0.0},
    "outfit": "staff", "cap": false, "emotion": "joy"
  },
  "encoder": {"ffmpeg": "/…/ffmpeg", "args": ["-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-c:v", "libx264", "…"], "path": "/…/video_mudo.mp4"}
}
```

- `timeline` va ordenada por `t` (segundos desde el cuadro 0); a igual `t`, en el orden de la lista. `message` es un mensaje del protocolo del stand (`docs/protocolo.md`) que Unity despacha como si llegara del orquestador. `audio`: Unity lee el WAV (PCM 16 bit mono a `audio_sample_rate`) y lo manda al reproductor en trozos de 100 ms a ritmo real desde `t`, como GPT-Live; con el último manda él solo el `speech_end`. `action`: un gesto de Sage por el canal de acciones, entero.
- Un gesto que tiene que esperar al núcleo del anterior llega más tarde que su `speech_start`, con su `utterance_id`, como en el stand.
- `scene.background.mode`: `stand`, `color`, `gradient`, `image` (los compone Unity con colores exactos) o `transparent` (alfa). `scene.outfit` va también en el trabajo, pero Unity lo ignora (manda el argumento de arranque). Sin HUD: no se mandan ni `logo`, ni `qr`, ni `set_subtitles`.
- Unity ejecuta `ffmpeg -hide_banner -loglevel error -y -f rawvideo -pix_fmt rgba -s WxH -r fps -i - <args> <path>` y le escribe los cuadros (RGBA sRGB, alfa sin premultiplicar) por stdin. Opaco: los argumentos del H.264 con las etiquetas BT.709. Transparente: tres salidas en la misma pasada, el `.mov` ProRes 4444 (`-map 0:v -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le -alpha_bits 16 -vendor apl0 video_mudo.mov`, sin el `-vf` de color del H.264), los PNG (`-map 0:v -c:v png -pix_fmt rgba -start_number 0 frames/sonnia_%04d.png`) y la copia a la mitad (`-map 0:v -vf scale=iw/2:ih/2 -c:v png … -start_number 0`, con `path` = `proxy/sonnia_%04d.png`).
- `kind: "still"`: fotos. Con `stills: [{"t": 1.2, "path": "/…/foto_01.png"}, …]`, Unity reproduce la línea de tiempo desde 0 y guarda un PNG en cada `t` (el último marca la duración); sin `stills`, una foto en `t = 0` en `still_path`. Las fotos van con `supersample: 3`.
- Al acabar deja en `output_dir` el `registro.json` (`kind`, `width`, `height`, `fps`, `frames`, `skipped`, `utterances` con `utterance_id`, `first_audio_t` y `heard_t`, y `frames_log` con `i`, `rms`, `mouth`, `utterance` y `bones: {nombre: [x, y, z]}` por cuadro, también en los `still`) y, en los vídeos, `heard.wav` (lo que sonó, 48 kHz mono).

## Problemas frecuentes

- **«No encuentro Sonnia Video»**: `SONNIA_VIDEO_APP` con la ruta de la app (o de su ejecutable).
- **Tarda mucho la primera vez**: el renderizador baja el avatar de Genies (hasta 15 minutos de espera). Se queda abierto: los siguientes vídeos empiezan enseguida. `sonnia-video cerrar` lo cierra.
- **«Relanzo el renderizador una vez»**: si el avatar no llega en 2 minutos, `sonnia-video` cierra la app y la abre otra vez (`STALL_RESTART_S`). Pasa a veces en el primer arranque de una app recién compilada o copiada a `/Applications` (27 de octubre de 2026): Genies monta las mallas pero se queda con texturas sin bajar («Genies sigue montando el avatar… huecos sin textura» en `unity.log`) y en ese proceso ya no se recupera; el segundo arranque carga en unos 8 s.
- **«El avatar de Genies no cargó»**: sin red, o Genies no entregó. Mirar `<datos>/unity.log`, cerrar y repetir.
- **Ocupado**: el renderizador hace un trabajo a la vez (`sonnia-video estado`).
- **«Ya hay N cuadros de Sonnia en …»**: el reel ya tiene un render; `--forzar` lo reemplaza.
- **La boca no va con la voz**: el informe del render dice dónde colocó la voz, de dónde lo sacó y el desfase que midió (y si lo corrigió). `heard.wav` y `registro.json` del trabajo permiten mirarlo a mano.
