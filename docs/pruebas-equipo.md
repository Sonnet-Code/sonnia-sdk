# Probar Sonnia: builds de prueba para el equipo

Son `Sonnia-pruebas-macOS.zip`, para un Mac con Apple Silicon (M1 o posterior), y
`Sonnia-pruebas-Windows-x64.zip`, para un PC con Windows de 64 bits (Intel o AMD).
Hace falta internet:
Sonnia habla de verdad con GPT-Live, que cuesta unos 3 USD por hora mientras la
app está abierta. **Ciérrala cuando acabes de probar.**

Cada copia tiene **una hora de conversación en total**, sumando todas las veces que
la abras. Cuando se acaba, Sonnia se va de la pantalla y deja un letrero: «La prueba
de Sonnia ha terminado». A partir de ahí ya no conversa.

Estas builds no mandan tu cámara ni tu micrófono al panel: nadie del equipo te
puede ver ni oír desde `sonia.sonnetcode.com`. Sí sales en el panel con el nombre
de tu equipo, y desde ahí Jean puede cambiarle el modo a tu Sonnia.

## Mac (solo con Apple Silicon: M1 o posterior)

1. Descomprime el zip y mueve `Sonnia.app` a una carpeta tuya, por ejemplo
   `~/Sonnia/`. Que no sea una carpeta de solo lectura: la primera vez Sonnia
   guarda ahí unos 90 MB de piezas de su avatar.
2. La app no está firmada por Apple y macOS la bloquea la primera vez. Quita el
   bloqueo una sola vez, en Terminal:

   ```bash
   xattr -dr com.apple.quarantine ~/Sonnia/Sonnia.app
   ```

   Otra forma, sin Terminal: intenta abrirla. Cuando macOS la bloquee, ve a
   Ajustes del Sistema > Privacidad y seguridad, pulsa «Abrir igualmente» y
   confirma.
3. Doble clic en `Sonnia.app` y acepta los permisos de micrófono y cámara.

En un Mac con Intel no funciona: el avatar de Genies solo existe para Apple
Silicon. Usa la de Windows en un PC.

## Windows

1. Clic derecho en el zip > «Extraer todo», a una carpeta tuya, por ejemplo
   `C:\Sonnia\`. No la abras desde dentro del zip.
2. Doble clic en `Sonnia.exe`.
   - Si sale «Windows protegió tu PC», pulsa «Más información» y luego
     «Ejecutar de todas formas».
   - Si el firewall pregunta, permite el acceso.
3. Si Windows pide permiso para el micrófono o la cámara, acéptalo
   (Configuración > Privacidad y seguridad).

## Al usarla

- La primera vez tarda un poco en aparecer Sonnia: se descarga su avatar.
- Sale a pantalla completa y en vertical. En una pantalla horizontal se ve con
  bandas negras a los lados: es normal.
- Háblale con normalidad: te oye por el micrófono y contesta con voz. Puedes
  interrumpirla hablando. Prueba la trivia, que te diga la agenda del DevFest o
  que baile.
- Esc abre el menú de opciones. Si va lenta, baja ahí la calidad gráfica.
- Para cerrarla: Cmd+Q en Mac y Alt+F4 en Windows.

## Si algo falla

Mándale a Jean la hora aproximada y los registros:

- **Mac:** `~/Library/Application Support/Sonia/logs/` y
  `~/Library/Logs/DefaultCompany/Sonnia/Player.log`.
- **Windows:** `%APPDATA%\Sonia\logs\` y
  `%USERPROFILE%\AppData\LocalLow\DefaultCompany\Sonnia\Player.log`.
