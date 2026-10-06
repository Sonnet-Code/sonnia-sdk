# Base de conocimiento de Sonia

Cada archivo `.md` de esta carpeta se añade, en orden alfabético, a las instrucciones de la sesión de GPT-Live. Sirve para darle datos del evento, del GDG, del lugar y de Sonnet Code sin tocar código.

Reglas:

- Solo datos verificados. Si algo no se sabe con certeza, escribirlo como "por confirmar" para que Sonia lo diga así y no lo invente.
- Frases cortas y concretas. Todo lo que está aquí cuenta como tokens en cada turno, así que conviene no pasar de unas 1500 palabras en total.
- Se puede editar durante el evento: Sonia relee estos archivos cada vez que abre una sesión nueva (al reiniciar por inactividad, `IDLE_RESET_SECONDS`, o con «Reiniciar» en el panel). Para un dato de última hora sin tocar archivos, mejor «Avisos de hoy» en el panel.
- Los nombres con prefijo numérico (`01-`, `02-`...) controlan el orden.
- La agenda del DevFest no va aquí: se lee de la web oficial (`AGENDA_URL`) y el orquestador avisa a Sonia de los cambios (docs/agenda.md).
- `00-glosario.md` lista los nombres propios que Sonia puede oír mal con el ruido, para que reconozca el parecido ("Begasov" es Vegazo).
