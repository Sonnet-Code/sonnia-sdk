# Base de conocimiento de Sonia

Cada archivo `.md` de esta carpeta se añade, en orden alfabético, al system prompt de Sonia. Sirve para darle datos del evento, del GDG, del lugar y de Sonnet Code sin tocar código.

Reglas:

- Solo datos verificados. Si algo no se sabe con certeza, escribirlo como "por confirmar" para que Sonia lo diga así y no lo invente.
- Frases cortas y concretas. Todo lo que está aquí cuenta como tokens en cada turno, así que conviene no pasar de unas 1500 palabras en total.
- Se puede editar durante el evento: Sonia relee estos archivos cada vez que reinicia la conversación por inactividad (`IDLE_RESET_SECONDS`).
- Los nombres con prefijo numérico (`01-`, `02-`...) controlan el orden.
- `00-glosario.md` es especial: además de entrar en el prompt, sus viñetas (el nombre antes de los dos puntos) se pasan al reconocedor de voz como palabras clave y sirven para corregir transcripciones parecidas ("Begasov" pasa a ser "Vegazo") antes de que el modelo las vea.
