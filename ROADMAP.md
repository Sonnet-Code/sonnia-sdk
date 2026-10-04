# Roadmap de Sonia

Lo que queda pendiente antes y durante el DevFest Santo Domingo (9 y 10 de octubre de 2026), por orden de urgencia. Se tacha al terminar y se apunta la fecha. El histórico de lo ya hecho está en el README ("Hoja de ruta") y en `git log`.

## 1. Probar GPT-Live con clave (bloqueante)

El motor GPT-Live (ADR 007) ya habló con la API real el 4 de octubre: de esa prueba salieron el corte de frases por nivel de voz (manda audio sin parar a ritmo real), el uso de `session.commentary.append` para los textos escritos y la limpieza de marcas como "[laugh]". Desde ese día es el único motor: el anterior y el silenciado del micro mientras hablaba Sonia se borraron. Queda la prueba completa:

- [ ] Clave en `.env` (`OPENAI_API_KEY` o `LIVE_API_KEY`) y pasar `sonia check` (abre y cierra una sesión).
- [ ] `sonia say "Hola, soy Sonia"` con varias voces (`LIVE_VOICE`: marin, coral, sage, shimmer...) y elegir una.
- [ ] `sonia chat`: comprobar que un texto escrito (ahora por `session.commentary.append`) recibe respuesta hablada.
- [ ] `sonia run` con micrófono, cámara y Unity:
  - [ ] Interrumpirla hablando con los altavoces del stand: que se calle y escuche, y que no se corte sola ni se conteste a sí misma (ya no se silencia el micro mientras habla).
  - [ ] Latencia percibida de la respuesta y de las acciones (`show_image` pasa por el backend `gpt-6-luna`).
  - [ ] Calibrar `LIVE_GATE_RMS` (o "Ruido del pasillo" en el panel) con las voces del pasillo (`docs/stand.md`).
  - [ ] Que diga bien los nombres propios del evento y de Sonnet Code.
- [ ] Ojos: `LLM_*` apunta por defecto a un modelo con visión de OpenAI (`gpt-6-luna`, clave `OPENAI_API_KEY` o `LLM_API_KEY`); si el `.env` sigue apuntando al endpoint del motor anterior, borrar esas líneas. O `LLM_SUPPORTS_VISION=false` para apagar la cámara.
- [ ] Números del stand: comprobar que la frase grabada suena bien y, si no hay grabación, que `session.commentary.append` la dice tal cual y no la parafrasea.

## 2. Panel de control (`docs/panel.md`)

El panel vive en Cloudflare (`https://sonia.sonnetcode.com`, Worker `sonia-panel`, código en `cloud/panel/`) y cada Sonia se conecta a él hacia fuera. Desplegado y probado de punta a punta el 3 de octubre (login, lista de Sonias, acción y conexión de una Sonia real). El panel local (`http://127.0.0.1:8780`) queda de respaldo sin internet. Para volver a desplegar: `cd cloud/panel && npm install && npm run deploy` con la sesión de wrangler.

- [ ] Volver a desplegar el panel (`cd cloud/panel && npm run deploy`): el de `sonia.sonnetcode.com` aún sirve los estáticos de antes del 4 de octubre, con el interruptor "Interrumpirla hablando", que ya no existe.
- [ ] Poner `PANEL_CLOUD_TOKEN` (y un `PANEL_INSTANCE_NAME` reconocible) en el `.env` del equipo del stand. El valor está en `~/.config/sonia/panel-secrets.env` del Mac de Jean, junto con la contraseña del panel.
- [ ] Repartir la contraseña del panel al personal del stand (o cambiarla con `npx wrangler secret put PANEL_PASSWORD` en `cloud/panel/`).
- [ ] Opcional: Cloudflare Access (login con el correo `@sonnetcode.com`) en vez de, o además de, la contraseña. Pasos en `docs/panel.md` ("Acceso"); hace falta una política Bypass para `/agent` y los secretos `ACCESS_TEAM_DOMAIN` y `ACCESS_AUD`. Ningún token disponible tiene permiso de Access: se hace desde el dashboard.
- [ ] "Preparar voces" una vez con la clave puesta y la voz elegida (graba saludos, frases y cantos en `cache/voice` de ese equipo; se repite solo si cambia la voz).
- [ ] Ensayo con alguien del stand que no sea técnico: entrar desde el móvil, cambiar de modo, mandar un aviso, mostrar el logo, subir el volumen y ver si entiende los avisos de salud y de Sonias duplicadas.

## 3. Unity: modo "Fuera", volumen y saludo

El código está escrito y compila contra las DLL de Unity 6000.6.0f1 (0 errores), pero no se ha visto en el editor (lo pidió Jean: probar luego juntos). Detalle en `docs/unity.md`, sección "6c. Modo Fuera".

- [ ] Abrir el proyecto (importa `Assets/Animations/RPM/F_Walk_002.fbx`, caminar femenino de Ready Player Me, 1,4 m/s) y ejecutar **Sonia > Crear set de animaciones**: el clip debe quedar Humanoid, en bucle, y la consola decir "caminar F_Walk_002".
- [ ] Comprobar que el avance del clip (root motion) se lee bien con `MotionPlayer`; si sale el aviso "sin root motion", Sonia sale deslizando.
- [ ] Renders 9:16 en varios instantes de la salida y de la entrada: pie de apoyo sin derivar más de 1-2 cm, giro suave, ojos vivos, plano a cuerpo entero mientras camina, letrero legible con texto largo, tildes y eñes. Ajustar el pie de arranque con `walkStartNormalizedTime`.
- [ ] Con el encuadre actual solo caben unos 0,78 m a cada lado (2 o 3 pasos); para más paseo, retrasar `Presence Shot Position`.
- [ ] Reconexión de Unity estando "Fuera" (se aplica sin animación) y cambios a medias ("Volver" durante la salida y al revés).
- [ ] `set_volume` a 0,3, 1 y 1,5 con Sonia hablando, y el gesto `greeting` (botón "Saludar ahora").
- [ ] Subtítulos parciales de Sonia en el HUD (`SoniaDebugUI`) con la voz de GPT-Live.
- [ ] Recompilar la build (`unity/Build/macOS/Sonia.app`).

## 4. Decisiones pendientes de Jean

- [x] Discurso de "100 % local" (4 de octubre): retirado. `CLAUDE.md`, la documentación, la base de conocimiento (`assets/knowledge/07-como-funciona-sonia.md`) y las frases del stand cuentan que Sonia usa GPT-Live de OpenAI. Si las frases cambiadas ya estaban grabadas, "Preparar voces" graba las nuevas.
- [ ] Coste: unos 3 USD por hora de sesión abierta (0,05 USD/min). En "Solo saludos" y "Fuera" no se gasta nada.

## 5. Equipo del stand

Sonia no tiene por qué correr en el Mac de desarrollo. Guía de instalación para cualquier equipo en `docs/stand.md`, "Instalar Sonia en el equipo del stand".

- [ ] Decidir el equipo (mini PC GMKtec con Windows, otro portátil o el Mac) e instalarlo siguiendo esa guía: claves y `PANEL_CLOUD_TOKEN` en su `.env`.
- [ ] Que no quede otra Sonia con `PANEL_CLOUD_TOKEN` corriendo en otro equipo (el panel avisa de duplicados).
- [ ] Si es Windows: comprobar que el micrófono abre a 24 kHz (si no, `LIVE_SAMPLE_RATE=16000`), compilar la build de Unity para Windows y buscar un equivalente de `scripts/kiosk.sh` (es bash).
- [ ] Internet estable todo el día: sin red Sonia no conversa. Plan B: pasar a "Solo saludos" desde el panel local (sigue funcionando con las frases grabadas).
- [ ] Prueba completa con micrófono, cámara y Unity en el equipo del stand.

## 6. Arrastrado de antes

- [ ] Imágenes de la galería: faltan servicios de Sonnet Code y un diagrama de cómo funciona Sonia.
