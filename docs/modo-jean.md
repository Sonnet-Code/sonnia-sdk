# Modo Jean: invitado sorpresa desde España

Petición de Jean (CTO de Sonnet Code), el 5 de octubre de 2026:

- En «Developer» del backoffice hay una opción que abre un modal y activa el «Modo Jean».
- Sonia dice que acaba de llegar un invitado sorpresa y entra el avatar de Jean.
- Se dan la mano y Sonia se va, dejando a Jean hablando.
- Desde el modal, Jean ve la cámara del stand en vivo, estable aunque haya que bajar la calidad.
- Jean habla desde España por su micrófono y se le oye en el DevFest.
- Su avatar mueve la boca con su voz y hace gestos al hablar.
- Jean tiene botones para lanzar animaciones a mano.

## 1. Cómo se ve en el stand

1. Jean pulsa «Activar Modo Jean» en el modal.
2. GPT-Live se cierra y el modo saludos se pausa: nada más habla por los altavoces del stand.
3. Sonia dice una frase grabada (`cache/voice`, sin gastar): «¡Atención! Acaba de llegar un invitado sorpresa…».
4. El avatar de Jean entra caminando por la derecha. Se paran uno frente al otro y se dan la mano.
5. Sonia sale caminando por la izquierda, sin letrero, y Jean se coloca en el centro mirando a cámara. El encuadre es el plano medio de siempre.
6. A partir de ahí, lo que Jean dice por su micrófono suena en el stand y mueve su boca. La cabeza, las cejas y los ojos siguen su voz, y él lanza gestos desde el modal.
7. «Terminar Modo Jean»: Jean se despide y sale, Sonia vuelve caminando y todo regresa al modo de antes.

## 2. Arquitectura

```
Jean (navegador, España)                   Cloudflare                          Stand (Santo Domingo)
  modal Modo Jean ──WS /api/guest──►  Worker ──► Durable Object  ◄──WS /guest/agent── orquestador
   · micro → PCM 24 kHz ─────────────────────────► GuestRoom ─────────────────────────► hub → Unity (avatar de Jean)
   · ◄── JPEG cámara + PCM 16 kHz micro del stand ◄────────────────────────────────── cámara + micro del stand
   · acciones (activar, animaciones) ──POST /api/action──► ControlRoom ──► StandControl ──► Unity
```

- **`GuestRoom`** es un Durable Object nuevo, uno por Sonia (`idFromName(<id de la Sonia>)`, con `locationHint: "enam"` para que viva cerca del stand). Solo reenvía: los frames del stand van a los navegadores y el audio de Jean va al orquestador. No guarda nada y no toca a `ControlRoom`, así que los mensajes de estado y las acciones van por un canal distinto del de la media.
- **El orquestador** abre `/guest/agent` (mismo `PANEL_CLOUD_TOKEN`) solo mientras la sala hace falta: con el Modo Jean activo o con alguien en «Ver cámara» (`docs/panel.md`). Manda vídeo solo si alguien mira, y el micro del stand solo con el Modo Jean y a su modal.
- **Las acciones** (activar, terminar, animaciones) van por la API de siempre (`POST /api/action`) y llegan a `StandControl` como cualquier otra.

### 2.1 Por qué un relé por WebSocket y no WebRTC con Cloudflare Realtime

| | Relé por el Durable Object (elegido) | Cloudflare Realtime (SFU, WebRTC) |
|---|---|---|
| Cámara del stand hacia Jean | JPEG por WebSocket, con fps y calidad adaptables | Hace falta publicar con WebRTC desde el orquestador (`aiortc` y FFmpeg en el equipo del stand). El adaptador WebSocket de Realtime no admite vídeo de entrada (solo saca JPEG a 1 fps) |
| Audio | PCM con colchón antisaltos propio | Opus, FEC y colchón de WebRTC (mejor con pérdidas) |
| Latencia de boca a oído | 300-450 ms (estimada) | 200-300 ms (estimada) |
| Piezas nuevas | Un Durable Object y código propio | App de Realtime (App ID y secreto), firma en el Worker, `aiortc` en Windows y Mac, adaptador WebSocket para el audio del stand |
| Coste | Gratis dentro del plan free (ver 2.3) | Gratis hasta 1 000 GB al mes |
| Riesgo a 4 días del evento | Bajo: reutiliza el panel, el token y la sesión que ya funcionan | Alto: dependencia nativa pesada y otra integración nueva |

Con un control de flujo que adapte el bitrate (sección 3), la cámara se ve fluida en una red normal y, si la red del recinto flojea, baja de calidad sin cortarse. Si el resultado no convence, WebRTC sigue siendo la mejora natural para después del DevFest.

### 2.2 Latencia estimada (Madrid ↔ Santo Domingo)

El ping entre Europa y el Caribe ronda los 110-140 ms de ida y vuelta. El Durable Object, con `locationHint: "enam"` (este de Norteamérica), queda casi de camino: España ↔ Cloudflare ↔ DO, unos 80-100 ms, y DO ↔ stand, unos 30-50 ms.

- **Voz de Jean al stand:** 60 ms de bloque en el navegador, 60-75 ms de red de ida, 150 ms de colchón en el orquestador y 60-100 ms de salida de Unity. En total, unos 350-400 ms, el retardo de una llamada internacional.
- **Imagen del stand a Jean:** de 250 a 400 ms, más la cola de envío si la red va justa (el control de flujo la mantiene corta).

### 2.3 Cuota del plan free de Cloudflare

Los mensajes de WebSocket entrantes al Durable Object cuentan 1 de cada 20 como petición; los salientes son gratis. El límite es de 100 000 peticiones al día. Por segundo de Modo Jean:

| Flujo | Mensajes/s |
|---|---|
| Vídeo del stand (hasta 12 fps) | 12 |
| Micro del stand (bloques de 100 ms) | 10 |
| Micro de Jean (bloques de 60 ms) | 17 |
| Confirmaciones de vídeo de Jean | 12 |
| **Total** | **unos 51** |

Eso son unas 184 000 al día por hora, que cuentan como unas 9 200 peticiones por hora. Caben más de 9 horas de Modo Jean al día además del resto del panel. La duración del Durable Object (128 MB) entra de sobra en los 13 000 GB-s diarios. Los mensajes caben en el máximo de 32 MiB.

## 3. Vídeo: bitrate adaptable con control de flujo

Cada fotograma JPEG lleva su número y la hora de envío del stand. El navegador lo pinta y contesta con un `ack` (número y hora de envío de vuelta). En el orquestador, `VideoRateController`:

- **Ventana:** como mucho 2 fotogramas sin confirmar. Si la red se atasca, no se apilan fotogramas: los fps bajan solos al ritmo que la red aguanta, como la ventana de TCP. La imagen siempre es reciente.
- **RTT:** media móvil de la hora devuelta en el `ack` (mismo reloj, sin desfase).
- **Bitrate medido:** bytes confirmados por segundo.
- **Escalones** de tamaño y calidad: 854×480 q70, 640×360 q65, 640×360 q50, 480×270 q50, 320×180 q45.
  - Cada segundo baja un escalón si el RTT pasa de 700 ms o si la ventana ha ido llena más de la mitad del tiempo con menos de 5 fps.
  - Sube un escalón tras 3 s seguidos con RTT bajo 350 ms y la ventana casi siempre libre.
  - Un fotograma sin confirmar en 2 s se da por perdido y baja un escalón.
- **Tope de fps:** 12. Arranca en 640×360 q65 a unos 2 Mbit/s y en el peor escalón ronda los 200 kbit/s.
- **Estadísticas:** el modal muestra cada segundo fps, kbit/s, escalón y RTT.

**El audio manda.** Si el búfer de envío del orquestador pasa de 256 KB, se saltan fotogramas de vídeo. El audio del stand nunca se encola más de 300 ms: lo más viejo se descarta.

## 4. Audio

- **Jean al stand:** el navegador pide el micro con cancelación de eco, supresión de ruido y control de ganancia. Un AudioWorklet lo baja a 24 kHz mono PCM de 16 bits en bloques de 60 ms (384 kbit/s).
  - En el navegador, si `ws.bufferedAmount` pasa de 64 KB, los bloques se tiran: mejor un hueco que un retraso creciente.
  - El orquestador junta 150 ms antes de empezar cada racha de voz y la pasa a Unity como frames `SNGU`. Una racha nueva empieza tras 500 ms de silencio, con `FLAG_LAST` al cerrar la anterior.
- **El stand a Jean:** el micro del stand (el que usa GPT-Live, ahora cerrada) baja a 16 kHz en bloques de 100 ms (256 kbit/s). En el navegador otro AudioWorklet lo reproduce con un colchón de unos 200 ms, recorta si pasa de 600 ms y tiene su propio volumen.
- **Eco:**
  - Jean debe usar auriculares; el modal lo avisa. Si no, la voz del stand vuelve al stand. En el stand, GPT-Live está cerrada durante todo el modo, así que nadie contesta solo.
  - La voz de Jean suena por los altavoces del stand y el micro del stand la recoge. Para que no se oiga a sí mismo con retraso, mientras habla y 0,7 s después (`GUEST_ECHO_TAIL_S`), el micro del stand le llega en silencio (se manda silencio para no vaciar su colchón). Es medio dúplex: si un visitante le habla mientras él habla, no lo oye hasta que calla.

## 5. Orquestador (`server/sonia/guest/`)

| Módulo | Qué hace |
|---|---|
| `media.py` | Formato binario de los frames de la sala, `VideoRateController` y remuestreo y paso a int16 del micro. Sin dependencias de red; con tests. |
| `link.py` | `GuestLink`: WebSocket a `/guest/agent` con reconexión de espera creciente (0,5 a 10 s). Manda la cámara según el controlador y el micro del stand. Recibe el audio de Jean, lo segmenta en rachas y lo pasa al hub (`SNGU`). Calcula las estadísticas. |
| `mode.py` | `GuestMode`: la máquina de estados `off → intro → entering → live → leaving → off`. Coordina la frase de Sonia, los mensajes a Unity, la sala y la vuelta al modo de antes. Nada de esto tumba el proceso: cada paso tiene tiempo límite y, si Unity no contesta, se sigue. |
| `room.py` | `RoomSupervisor`: abre `GuestLink` mientras lo necesiten el Modo Jean (con micro del stand y voz de Jean) o «Ver cámara» (solo vídeo, hasta que no quede nadie mirando). Lo comparten los dos: el visor se suma a la sala del Modo Jean y al revés. |

Integración en `StandControl`, cuando el principal confirme la base:

- **Acciones:**
  - `set_guest_mode` {`active`: bool}.
  - `guest_animation` {`clip`}.
- **Estado:** `guest` {`phase`, `link`, `viewers`, `stats`, `animations`}.
- **Capacidad:** `guest_mode`.
- Mientras el modo está activo no se abre GPT-Live, aunque el modo sea «Conversando», y el modo saludos no saluda solo.
- **Micro:** con el modo activo, `RoomSupervisor.hold_guest` engancha `GuestLink.push_mic` al motor (`LiveEngine.add_mic_listener`). El enlace solo lo manda si en la sala hay alguien que lo oye (`listeners`).
- **Frase de entrada:** va en `assets/showcase/invitado.md` para que «Preparar voces» la grabe con la voz de Sonia. Sin grabar, el modo entra igual pero sin frase y lo registra en el log.

## 6. Unity

- **El avatar de Jean** es una segunda definición de Genies:
  - Es un ajuste compartido aparte, `guest_avatar` (mensaje fijo `set_guest_avatar`), que pone su propio `GeniesAvatarLoader` con el rol `Guest`. Recuerda el último en su propio archivo (`sonia-guest-avatar.json`), igual que Sonia. No lleva copia local: en modo edición no hay ningún avatar (la raíz «Invitado» solo tiene un ancla vacía que marca dónde va) y al entrar en Play se carga vivo del SDK, en unos segundos y con Jean fuera de cuadro.
  - Se edita con el mismo editor de personaje: «Editar personaje de Jean» en «Developer» o «Editar mi personaje» en el modal mandan `open_avatar_editor` con `target` `guest`. El editor parte del aspecto actual de Jean y, al guardar, `avatar_saved` lleva el mismo `target` y el orquestador lo guarda en `guest_avatar`, sin tocar a Sonia. Mientras Jean no guarde uno, se usa su avatar de prueba, `Assets/Sonia/Avatar/JeanGeniesAvatar.json`.
- **La raíz «Invitado»** la monta *Sonia > Montar invitado (Modo Jean)* (`Editor/SoniaGuestSetup.cs`) en la escena del stand. Su posición es la marca de Jean: 0,45 m a la izquierda de Sonia en pantalla. Los avatares de Genies son pequeños (unos 41 cm de brazo) y más lejos no llegan a darse la mano. Lleva la misma pila de Sonia, otra vez:
  - voz: `AudioSource`, `AudioStreamPlayer` (frames `SNGU`), `LipSyncController` y `PhonemeLipSyncBridge` con uLipSync, con el perfil de muestra masculino;
  - cara, cabeza y ojos: `FaceRig`, `AvatarStateController`, `FacialExpressionController` y `EyeGazeController`;
  - cuerpo: `MotionPlayer` y `AvatarChoreographer` con el set de Sonia, sin bailes por su cuenta;
  - caminar: `PresenceController` (sale por la izquierda, sin letrero);
  - avatar: `AvatarBinder` y `GeniesAvatarLoader` (rol `Guest`);
  - Modo Jean: `HandshakeRig`, `ChoreographerBody` y `GuestPresenter`.
- **`GuestPresenter`** (`Scripts/Sonia/Guest/`) lleva la secuencia. Escucha `guest_mode`, `guest_animation`, la voz `SNGU`, `set_volume` y `set_tuning` (la boca de Jean lleva los mismos ajustes que la de Sonia) y avisa con `guest_state`.
- **Entrada** (`entering`):
  1. Plano entero de los dos (el de salida caminando, centrado entre los dos y más atrás si no caben).
  2. Jean entra caminando desde la izquierda con su presencia; Sonia le mira llegar.
  3. Apretón de manos (`HandshakeRig`). Genies no trae clip, así que el brazo derecho de cada uno va con IK de dos huesos a un punto entre los dos, encima del reposo. Las palmas quedan juntas, con el pulgar arriba y los dedos algo cerrados, y suben y bajan un par de veces. Se giran el uno hacia el otro lo justo: 20° la raíz de Sonia, que tiene la mano derecha del lado de Jean, y 45° la de Jean, que la tiene del lado de fuera, más 12° de tronco cada uno. Las manos se encuentran delante de los hombros derechos, a un 30 % del brazo hacia delante y un 55 % hacia abajo. Se miran a la cara. Las medidas de la mano salen de los huesos de cada avatar.
  4. Sonia sale por la derecha sin letrero (`PresenceController.HoldForGuest`). Mientras dure el modo, los `presence` del orquestador se apuntan y no la traen de vuelta, aunque llegue un hello.
  5. Plano medio de Jean: el de Sonia, llevado a su cabeza (con los ajustes de «Developer»). Unity avisa con `guest_state` `live`.
- **En directo:** la voz de Jean suena por su reproductor, con su lip-sync, cabeza y cejas con la prosodia. Cada frase nueva puede estrenar gesto; callado, escucha (bucle atento y asentimientos).
- **Animaciones a mano:** `guest_animation` lanza cualquier clip de una sola vez del catálogo, el mismo que el de Sonia.
- **Salida** (`leaving`): Jean se despide con la mano y sale por la izquierda mientras Sonia vuelve por la derecha. Plano entero de los dos y, al acabar, el de siempre. Unity avisa con `guest_state` `off`.
- **Robustez:**
  - Un `guest_mode` justo tras el hello (reconexión) se aplica sin animación.
  - Si tras un hello no llega ninguno y Jean estaba dentro (el orquestador se reinició), se despide.
  - Una secuencia que se queda a medias se completa sin animación (40 s entrando, 30 s saliendo).
- **El cuerpo es intercambiable:** `GuestPresenter` solo habla con `IAvatarBody`: hablar o callar, a quién atiende, un gesto por nombre y saludar. Hoy lo da `ChoreographerBody` (el coreógrafo y la cabeza de siempre). El motor de comportamiento de Genies entrará con su propio adaptador de `IAvatarBody` en la raíz «Invitado», y el presentador lo prefiere al de respaldo sin cambiar nada más. Caminar, la mano, la voz y la cámara no son del cuerpo.
- **La cámara** la impone `CameraFramingController.SetOverride` por encima de todos los planos, con el mismo travelling. El plano impuesto entra en `CollectShotPoses`, así que las presencias saben cuándo alguien está de verdad fuera de cuadro.
- **Verificación:** *Sonia > Comprobar Modo Jean (en Play)* (`Editor/SoniaGuestCheck.cs`) recorre la secuencia sin orquestador, a paso fijo y con el audio a mano. Le hace hablar con una voz de verdad (`Temp/guestcheck/voz.wav`) y guarda capturas 9:16 de cada paso, más dos vistas de las manos (de detrás y de cerca) y las distancias entre palmas. En la última pasada las palmas quedaron a unos 5 cm, piel con piel.

## 7. Protocolo nuevo

**Orquestador → Unity:**

| Mensaje | Qué hace |
|---|---|
| `guest_mode` {`phase`: `enter` \| `leave`, `name`: "Jean", `sample_rate`: 24000} | Arranca la entrada o la salida. |
| `guest_animation` {`clip`} | Un clip de una sola vez en el avatar de Jean. |
| `set_guest_avatar` {`definition`} | Fijo; como `set_avatar`, pero para Jean. |
| Frames binarios `SNGU` | Misma cabecera que `SNIA` (marca, `utterance_id`, flags) y PCM s16le mono a `sample_rate`. Los Unity antiguos los ignoran porque la marca no coincide. |

**Unity → orquestador:**

| Mensaje | Qué indica |
|---|---|
| `guest_state` {`phase`: `entering` \| `live` \| `leaving` \| `off`} | Cuándo Jean ya está, para el panel y para empezar a pasar su voz. |

**Sala de Cloudflare (`/guest/agent` y `/api/guest`):** frames binarios con una cabecera de 16 bytes, little-endian:

| Bytes | Campo |
|---|---|
| 0-1 | `"SG"` |
| 2 | versión (1) |
| 3 | tipo: 1 = JPEG del stand, 2 = PCM del micro del stand, 3 = PCM de Jean |
| 4-7 | número de frame |
| 8-11 | hora de envío en ms (reloj de quien envía; vuelve en el `ack`) |
| 12-13 | tasa de muestreo en Hz (0 en el vídeo) |
| 14-15 | reservado |

Mensajes JSON de la sala:
- **Del navegador:** `ack` {`seq`, `t`}.
- **Del orquestador:** `stats` {`fps`, `kbps`, `width`, `height`, `quality`, `rtt_ms`}.
- **Del Durable Object:**
  - `viewers` {`count`, `listeners`}, al orquestador: cuántos miran y cuántos oyen el micro del stand. Los de «Ver cámara» (`role=watch`) no lo oyen y lo que manden en binario se descarta.
  - `agent` {`connected`}, a los navegadores.

## 8. Panel

- En «Developer», un bloque «Modo Jean» con el botón «Abrir Modo Jean». Lo inyecta `static/jean.js`, que también monta el modal; `index.html` solo añade su `<script>` y su hoja de estilos. El modal tiene:
  - Fase actual y botones «Activar Modo Jean» y «Terminar».
  - La cámara en vivo (canvas 16:9) con fps, kbit/s, calidad y RTT.
  - Micro con medidor: micro abierto o pulsar para hablar (botón o barra espaciadora), con el aviso de auriculares.
  - Volumen del sonido del stand y silencio.
  - Botones de animaciones del avatar de Jean.
  - Estado de la conexión (conectando, en directo, sin Sonia, reconectando).
- Al abrirlo, el modal pide la sala con `watch_camera` y la renueva mientras está abierto: Jean ve el stand antes de entrar. El visor (conexión, vídeo, `ack` y estadísticas) es `static/room.js`, el mismo de «Ver cámara».
- **Solo en la nube:** en el panel local (`127.0.0.1`), el modal dice que el Modo Jean es desde `sonia.sonnetcode.com`. Las acciones sí funcionan en local para probar la entrada.

## 9. Fases

1. **MVP de streaming en local:**
   - Sala de Cloudflare.
   - `GuestLink` con cámara y micro falsos.
   - Modal con micro (o tono de prueba), cámara y estadísticas.
   - Pruebas: `wrangler dev`, Chrome y tests sin red.
2. **Integración en el panel y en `StandControl`:** acciones, estado, mic tap y frase grabada.
3. **Unity:** `GuestPresenter`, entrada y salida, lip-sync del invitado, animaciones y avatar de Jean. Se verifica con capturas 9:16.
4. **Prueba completa** con el Worker desplegado y un orquestador de prueba, y luego con Jean desde fuera de casa (4G) para medir la latencia real.

## 10. Lo que tiene que hacer Jean

- Usar **auriculares** con micro.
- Pulsar «Preparar voces» una vez con internet, para grabar la frase de entrada con la voz de Sonia.
- Crear su avatar con «Editar personaje de Jean» (en «Developer» o en el modal), con el Modo Jean apagado. Se edita en la pantalla de Sonia, con su ratón: lo más cómodo es hacerlo antes del evento con Sonia corriendo en su Mac. Queda en la nube para todas las Sonias.
- Probar desde España antes del día 9. Conviene probar la red del recinto: si filtra WebSockets largos, también caería el panel.
