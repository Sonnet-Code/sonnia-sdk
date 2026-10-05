# Sonia en una reunión (Meet, Zoom, Teams)

Montaje rápido, probado el 5 de octubre de 2026 en el Mac de desarrollo con
Google Meet, para que Sonia participe en una videollamada como una persona más:
la reunión la ve por una cámara virtual y la oye por un micrófono virtual, y
Sonia oye la reunión directamente, sin pasar por ningún micrófono de la sala.
No hay código nuevo: todo es configuración del sistema.

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

Sonia no se oye a sí misma: su voz va a BlackHole 2ch y ella escucha BlackHole
16ch, donde solo suena la reunión. Tampoco oye a nadie de la sala. Quien está en el
Mac no oye nada mientras dure: para seguir la reunión hay que entrar desde otro
dispositivo.

## Pasos para cada reunión

1. **Orquestador escuchando BlackHole 16ch**, sin tocar el `.env` (la variable de
   entorno manda sobre el `.env`):

   ```bash
   cd server && AUDIO_INPUT_DEVICE="BlackHole 16ch" uv run --no-sync sonia run
   ```

   En el registro debe salir `Micrófono abierto (dispositivo=N…)` con el número de
   BlackHole 16ch.
2. **Unity en Play** (o la build), conectado al orquestador.
3. **Panel local** (http://127.0.0.1:8780) en modo **Conversando**. En «Solo
   saludos» y «Fuera» no se abre GPT-Live y Sonia no contesta.
4. **Salida de sonido del Mac** → BlackHole 2ch.
5. **OBS** → Fuentes → «+» → Captura de ventana → la ventana de Unity →
   **Iniciar cámara virtual**. OBS pide permiso de grabación de pantalla la primera
   vez. La escena es vertical (9:16) y la reunión 16:9: sale con barras a los lados.
6. **En la reunión:** micrófono BlackHole 2ch, altavoz BlackHole 16ch y cámara OBS
   Virtual Camera. Si la cámara no sale, recargar la reunión: las apps solo ven las
   cámaras nuevas al arrancar. Comprobar que el micrófono de la reunión no está
   silenciado.

## Al terminar

- Salida de sonido del Mac → los altavoces de siempre.
- Parar el orquestador y arrancarlo de nuevo sin la variable (vuelve al micrófono
  del `.env`).
- Cerrar OBS. BlackHole y la extensión de OBS pueden quedarse instalados: no hacen
  nada si no se eligen.

Gasta lo mismo que una conversación normal: la sesión de GPT-Live está abierta
mientras Sonia está en Conversando.
