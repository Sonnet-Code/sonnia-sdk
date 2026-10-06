# Sonia en una reunión (Meet, Zoom, Teams)

Montaje probado el 5 de octubre de 2026 en el Mac de desarrollo con Google
Meet, para que Sonia participe en una videollamada como una persona más: la
reunión la ve por una cámara virtual y la oye por un micrófono virtual, y Sonia
oye la reunión directamente, sin pasar por ningún micrófono de la sala.

Desde el 6 de octubre además **ve la reunión** (modo reunión, `sonia reunion`):
OBS captura la ventana de Chrome con Meet y, cada vez que Sonia decide mirar
(acción `look`), el orquestador le pide a OBS una foto de esa ventana. Puede
decir quién está, cuántos son o qué comparten. Igual que con la cámara del
stand: solo fotos sueltas cuando mira, nunca vídeo, y nada se guarda.

Sonia se queda sola en el Mac; quien la presenta entra a la reunión desde otro
dispositivo.

## Qué hace falta (una sola vez)

```bash
brew install --cask obs           # cámara virtual
brew fetch --cask blackhole-2ch   # dos dispositivos de audio virtuales
brew fetch --cask blackhole-16ch
```

- **BlackHole** se instala abriendo cada `.pkg` descargado (está en
  `$(brew --cache)`) y pide la contraseña del Mac. `brew install --cask` no sirve
  desde una sesión sin terminal, porque `sudo` no puede pedir la contraseña.
- **Sin reiniciar el Mac.** Aunque el instalador lo pida, basta con reiniciar el
  servicio de audio: `sudo killall coreaudiod` (o, sin terminal,
  `osascript -e 'do shell script "killall coreaudiod" with administrator privileges'`).
  Después «BlackHole 2ch» y «BlackHole 16ch» salen en Centro de control > Sonido.
- **Cámara de OBS.** La primera vez que se pulsa «Iniciar cámara virtual», macOS
  bloquea la extensión. Se aprueba en Ajustes del Sistema > General > Ítems de
  inicio y extensiones > Extensiones de cámara (activar OBS Virtual Camera).
  Comprobación: `systemextensionsctl list` debe decir `[activated enabled]`.

## Cómo va el sonido

| Qué | Dispositivo |
|---|---|
| Salida de sonido del Mac (Unity reproduce ahí la voz de Sonia) | BlackHole 2ch |
| Micrófono en la reunión | BlackHole 2ch |
| Altavoz en la reunión | BlackHole 16ch |
| Lo que oye Sonia (orquestador) | BlackHole 16ch |
| Cámara en la reunión | OBS Virtual Camera |

## Cómo va la imagen (todo en OBS)

| Qué | Dónde |
|---|---|
| Lo que la reunión ve de Sonia | La escena en emisión de OBS (la ventana de Unity) → OBS Virtual Camera |
| Lo que Sonia ve de la reunión | La fuente «Reunión» de OBS (la ventana de Chrome con Meet), en la misma escena pero **fuera del lienzo** |

OBS solo da una cámara virtual, y la usa la reunión para ver a Sonia. Sonia no
necesita otra: le pide a OBS fotos de la fuente «Reunión» por su servidor
WebSocket. Esa fuente tiene que estar en la escena en emisión, porque OBS solo
captura las fuentes activas y fuera de ella la foto sale negra (comprobado con
OBS 32.2). Fuera del lienzo la cámara virtual no la enseña. `sonia reunion` lo
deja así solo:

- crea «Reunión» si no existe, elige la ventana con «Meet» (o Zoom o Teams) en
  el título, la coloca fuera del lienzo y la bloquea;
- enciende la cámara virtual y hace una foto de prueba (no se guarda).

La contraseña del servidor WebSocket de OBS no hay que copiarla: Sonia la lee
de la configuración de OBS de ese equipo. Con OBS cerrado, `sonia reunion`
activa el servidor y abre OBS.

Sonia no se oye a sí misma: su voz va a BlackHole 2ch y ella escucha BlackHole
16ch, donde solo suena la reunión. Tampoco oye a nadie de la sala. Quien está en el
Mac no oye nada mientras dure: para seguir la reunión hay que entrar desde otro
dispositivo.

## Pasos para cada reunión

1. **Chrome con la reunión de Meet**, en su propia ventana y con la pestaña de
   Meet delante: el título de la ventana es el de la pestaña activa y así la
   encuentra OBS («Meet - abc-defg-hij»). Mejor en otra pantalla que la de Sonia.
   Micrófono BlackHole 2ch, altavoz BlackHole 16ch y cámara OBS Virtual Camera.
   Si la cámara no sale, recargar la reunión: las apps solo ven las cámaras
   nuevas al arrancar.
2. **Sonia en modo reunión**:

   ```bash
   cd server && uv run --no-sync sonia reunion
   ```

   Abre OBS si hace falta, deja la fuente «Reunión» con la ventana de Meet,
   enciende la cámara virtual y arranca como `sonia run` con:

   | Variable | Valor en modo reunión |
   |---|---|
   | `AUDIO_INPUT_DEVICE` | `BlackHole 16ch` (oye la reunión) |
   | `VISION_SOURCE` | `obs` (ve la ventana de la reunión) |
   | `VISION_MAX_WIDTH` | `1280` (para leer los nombres de los recuadros) |

   Cualquiera se puede cambiar al lanzarlo, por ejemplo
   `VISION_MAX_WIDTH=768 uv run --no-sync sonia reunion`. Mandan sobre el
   `.env`. Al arrancar escribe lo que hizo: tiene que decir «Sonia ve la ventana
   «…Meet…»» y «Foto de prueba de «Reunión»: …, se ve bien». Si dice que no
   encuentra la ventana, se elige a mano en OBS (doble clic en «Reunión» >
   Ventana) o se vuelve a lanzar con Meet ya abierto.
3. **Unity** en Play o la app de Sonia (`Sonnia.app`), en otra pantalla. La app,
   siempre después del paso 2: usa el orquestador que ya esté escuchando y, si
   se abre antes, lanza el suyo sin modo reunión.
4. **OBS**: la escena en emisión tiene que tener la ventana de Unity (la de
   ayer: «macOS Screen Capture»). Si se abrió la app en vez del editor, elegir
   en esa fuente la ventana de Sonia. La primera vez OBS pide permiso de
   grabación de pantalla.
5. **Panel** (local, http://127.0.0.1:8780, o sonia.sonnetcode.com) en modo
   **Conversando**. En «Solo saludos» y «Fuera» no se abre GPT-Live y Sonia no
   contesta.
6. **Salida de sonido del Mac** → BlackHole 2ch.
7. Desde el otro dispositivo, entrar a la reunión y probar: «Sonia, ¿qué ves?»,
   «¿cuántos somos?».

En modo reunión Sonia sabe que está en una videollamada (sus instrucciones
cambian solas) y no hace la animación de stand: en los silencios de la reunión
se pondría a bailar o a decir frases del stand.

### Plan B sin OBS: la pantalla

Si OBS da problemas, `VISION_SOURCE=screen uv run --no-sync sonia reunion` hace
que Sonia vea una pantalla entera del Mac (`VISION_SCREEN_MONITOR`: 1 la
principal, 2 la segunda…), con Meet delante en esa pantalla. La app de terminal
desde la que se lanza necesita permiso de Grabación de pantalla (Ajustes del
Sistema > Privacidad y seguridad); sin él, macOS solo deja ver el fondo de
escritorio y el registro lo avisa.

## Al terminar

- Salida de sonido del Mac → los altavoces de siempre.
- Parar el orquestador (Ctrl+C) y arrancar Sonia como siempre (`sonia run` o la
  app): vuelve al micrófono y a la cámara del `.env`.
- Cerrar OBS. BlackHole, la extensión de OBS y la fuente «Reunión» pueden
  quedarse: no hacen nada si no se usan.

Gasta lo mismo que una conversación normal: la sesión de GPT-Live está abierta
mientras Sonia está en Conversando. Cada vez que mira, la foto va al backend
(unos céntimos).
