# Fecha, hora, agenda en vivo y búsqueda en internet

Sonnia sabe qué día y qué hora es en Santo Domingo, lee la agenda del DevFest de su web oficial y puede buscar en internet lo que no está en su base de conocimiento. Todo lo que es comparar, calcular o decidir si algo cambió lo hace el código, no el modelo.

## Fecha y hora (`server/sonia/clock.py`)

- La hora es la del stand (`TIMEZONE`, por defecto `America/Santo_Domingo`), no la del equipo: el Mac de desarrollo está en España y la app puede correr en cualquier sitio.
- Al abrir cada sesión, las instrucciones llevan una sección «FECHA Y HORA» (`martes 6 de octubre de 2026, 19:25 (las 7:25 de la noche), hora de Santo Domingo`).
- Entre turnos, cuando Sonnia está en reposo (`_between_turns` en el ciclo del motor), si cambió el minuto, el motor manda una nota silenciosa `[Reloj]` por `session.thinking.append` con la hora y, si cambió, qué hay ahora y qué viene (o cuánto falta para el DevFest). Como mucho una por minuto. Nunca mientras alguien habla: al principio iba al empezar cada turno y una de esas notas coincidió con una respuesta de la trivia que GPT-Live no registró (un append puede cambiar lo que el modelo está decidiendo). Los cambios de agenda esperan igual a un momento de calma.
- Windows no trae la base de zonas horarias de `zoneinfo`: Santo Domingo es UTC-4 todo el año y `resolve_timezone` lo resuelve sin ella. Otra zona que falte cae en la del sistema con un aviso.

## Agenda en vivo (`server/sonia/agenda`)

La web (`AGENDA_URL`, https://devfest.gdgsantodomingo.org/schedule) es de Next.js y trae los datos dentro del HTML, en el flujo de React Server Components: `talkRows` (cada sesión, con horas UTC, ponente, temas y track) y `trackRows` (las salas). `source.py` junta los trozos `self.__next_f.push([1, "..."])` y saca esas dos listas. No se lee el HTML pintado ni se usa ningún modelo.

- **Arranque.** `AgendaBook.load()` carga la última agenda descargada (`AGENDA_CACHE_FILE`, por defecto `cache/agenda.json`) o, si no hay, la copia que trae la app (`assets/agenda/agenda.json`). Así Sonnia sabe la agenda aunque no haya red. Después `watch()` la baja de la web al arrancar y cada `AGENDA_REFRESH_MINUTES` (10).
- **Texto para Sonnia.** `render_agenda` la escribe por días y salas, en horas de 12 (como se dicen), con el cargo del ponente recortado y sin emojis. Va en las instrucciones de GPT-Live y del backend en vez del antiguo `assets/knowledge/08-agenda-devfest-2026.md`.
- **Cambios.** Cada versión nueva se compara con la anterior en `diff_agenda`: por id de sesión (y, si la web la vuelve a crear con otro id, por título), solo lo que le importa al visitante (título, ponente, día, hora y sala). Cada cambio sale ya escrito en una frase (««Charla uno» de Ana Pérez cambia de hora: era … y ahora es …»). Si hay sesión abierta, el motor se los pasa por `session.instructions.append` (cabe en los 1200 caracteres de un append; si hay más, le dice que consulte). Las sesiones nuevas ya llevan la agenda nueva entera.
- **Qué hay ahora.** `happening` calcula qué sesiones están en curso y cuáles vienen después (o cuánto falta para el evento, o que ya terminó). Va en la nota `[Reloj]` y en el resultado de `check_agenda`.
- **Acción `check_agenda`.** GPT-Live la delega cuando preguntan si cambió algo, quieren confirmar una charla, hora o sala, o no tiene claro qué toca. Baja la web en ese momento, compara con la agenda que tenía la sesión al empezar (`ctx.extra["agenda_baseline"]`) y devuelve los cambios y qué hay ahora. Si la web no responde, lo dice y Sonnia sigue con lo que sabía.
- **Robustez.** Una descarga fallida no borra nada. Una página que de repente trae menos de la mitad de las sesiones se toma por rota y se ignora. Nada de esto tumba el orquestador.
- **Actualizar la copia de la app.** Antes de una build, si la agenda cambió, basta con copiar `cache/agenda.json` (lo escribe cualquier `sonia run` con red) sobre `assets/agenda/agenda.json`.

## Búsqueda en internet

El backend Responses en el que delega GPT-Live lleva la herramienta integrada `web_search` (la ejecuta OpenAI, no hay handler propio), situada en Santo Domingo (`LIVE_BACKEND_WEB_SEARCH_COUNTRY`, `LIVE_BACKEND_WEB_SEARCH_CITY`, `TIMEZONE`) y con poco contexto para que sea rápida (`LIVE_BACKEND_WEB_SEARCH_CONTEXT=low`). GPT-Live la delega cuando le preguntan algo que no está en su base de conocimiento y se puede buscar (el tiempo, una noticia, una empresa, una tecnología, una persona pública). El backend responde en una o dos frases diciendo de dónde sale el dato y no busca datos de visitantes ni de particulares. `LIVE_BACKEND_WEB_SEARCH=false` la quita. Cada búsqueda cobra aparte.

## Delegación: lo que se probó el 7 de octubre de 2026

Por voz en el stand, GPT-Live decía «¡ahí va el bailecito!» o se inventaba la pregunta de la trivia sin delegar nada: las instrucciones habían crecido a 36 000 caracteres y la política de delegación quedaba enterrada en medio. Se arregló así (`server/sonia/live/prompts.py`):

- Las reglas usan los encabezados de la plantilla oficial de GPT-Live tal cual, en inglés (`Backchannel policy`, `Interruption policy`, `Delegation policy` con `Backend tools`, `Delegate to the backend when`, `Do not delegate to the backend when` y las dos frases finales), con el contenido en español.
- El procedimiento de la trivia (requisito de seguir a Sonnet Code y nivel) va aparte; en la delegación solo queda el disparador.
- Al final de todo va un recordatorio: lo que solo pasa si se delega, nunca decir «ahí va» sin delegar, nunca preguntas de trivia de su cabeza y buscar antes de decir que no se sabe.

Probado con la API real metiendo voz sintetizada como micrófono: el baile, la trivia (con su tarjeta) y la búsqueda se delegan en el mismo turno. Con texto escrito (`sonia chat`, que entra por `session.commentary.append`) la delegación llega un turno tarde: es una vía de desarrollo, no la del stand.
