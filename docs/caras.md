# Caras conocidas: el equipo de Sonnet Code, los ponentes y personas conocidas

Sonnia reconoce por la cara al equipo de Sonnet Code, a los ponentes del
DevFest y a las personas conocidas que el equipo añade a mano, y a nadie más.
Cuando uno se pone delante de la cámara, se lo dice a GPT-Live con una nota
silenciosa, y así puede saludarle por su nombre o nombrarle su charla. Es una
decisión de Jean del 7 de octubre de 2026: «mejor solo con los speakers y staff
de Sonnet Code, no con gente random». Ese mismo día añadió a dos personas
conocidas con su saludo propio (Victor Duran y Wanda Custodio).

Código en `server/sonia/faces`; integración en `server/sonia/live/engine.py`
(revisión periódica y nota `[Cámara]`) y `server/sonia/actions/builtin.py`
(`look`).

## Qué ve y qué no

- **Todo corre en el equipo del stand**, con OpenCV: YuNet encuentra las caras y
  ArcFace R50 (el `w600k_r50` de InsightFace) saca la huella de cada una (512
  números). SFace, el modelo de antes del 8 de octubre, queda de respaldo
  (`FACES_MODEL=sface`) y es el que alinea la cara para los dos. Ninguna foto
  sale del equipo por esto y no se llama a ningún modelo de pago.
- **Solo hay huellas de las personas conocidas**: el equipo de
  `assets/faces/staff.json` (fotos de https://www.sonnetcode.com/es/about), los
  ponentes de la agenda (la foto que publica la web del DevFest) y las personas
  de `assets/faces/invitados.json` (fotos locales). Se guardan en
  `cache/faces/huellas/caras-arcface.json` (las de SFace, en `caras.json`),
  sin las fotos.
- **De los visitantes no se guarda nada**: su cara se compara en memoria y se
  olvida. Nunca se da de alta a nadie desde la cámara.
- Las sesiones con varios ponentes no dan de alta a nadie: la web trae la foto
  de uno solo y no se sabe de cuál.

Si preguntan cómo les reconoce, Sonnia dice que reconoce al equipo de Sonnet
Code y a los ponentes por sus fotos públicas y que la cara de los demás no la
guarda. No nombra OpenCV ni ningún modelo, igual que con el resto de su stack.

## Cuándo se avisa a Sonnia (sin agobiarla)

Hay dos caminos (`FaceWatcher` en `server/sonia/faces/watcher.py`):

1. **Revisión sola.** Con una sesión de GPT-Live abierta, el motor mira la
   cámara cada `FACES_SCAN_SECONDS` (1 s), a la resolución de la cámara (hasta
   `FACES_ANALYSIS_WIDTH`, 1920 px), no a la de 768 px de la visión. Quien sale
   en `FACES_CONFIRM_SCANS` revisiones (2) de los últimos `FACES_CONFIRM_SECONDS`
   (4 s), seguidas o no, genera una nota:
   `[Cámara] Acaba de ponerse delante de la cámara Brian James (del equipo de Sonnet Code, gerente de Operaciones y Servicios).`
   De esa persona no se vuelve a avisar en `FACES_COOLDOWN_MINUTES` (20). Así
   Brian o Mariel pueden pasar el día en el stand sin llenar la conversación
   de notas.
2. **Sonnia usa la cámara**, con `look` o con la nota automática `[Cámara]` si
   está activada. Al resultado se le añade
   `Personas conocidas en la foto: ...` aunque ya se le dijera hace poco, y el
   plazo de 20 minutos de esas personas empieza de nuevo. Cuenta también quien
   reconoció la revisión sola en los últimos 3 s: esa mira a resolución
   completa y ve más lejos que la foto de `look`.

Otros detalles:
- En «Solo saludos» y «Fuera» no hay sesión, así que no se mira.
- En el modo reunión (`sonia reunion`, ojos por OBS o la pantalla) no hay revisión sola: cada foto abre una conexión con OBS y los nombres ya salen en los recuadros. Solo cuenta cuando Sonnia mira con `look`.
- El plazo vale entre sesiones: si la conversación se reinicia (dos minutos
  sin nadie), Sonnia olvida la nota, pero no se repite hasta que pase el plazo
  o ella mire.
- La nota es silenciosa (`session.thinking.append`): Sonnia no habla por
  recibirla.
- Sus instrucciones le dicen que la nota cuenta quién se vio en ese momento,
  no quién le habla después. Si no encaja, no da por hecho que es esa
  persona, y si le dicen que no son quien cree, se disculpa y sigue.
- Si le preguntan «¿me reconoces?» o «¿sabes quién soy?» y no le ha llegado la
  nota, mira con `look` antes de contestar (es una de sus reglas de delegación).
  El 8 de octubre contestó «no sé quién eres» sin mirar, y la nota llegó diez
  segundos después.
- Quien se parece a alguien conocido sin llegar al umbral queda en el registro,
  una vez por minuto y persona como mucho:
  `Caras: se parece a Jean Calderon pero no llega (0.47 de 0.52; cara de 98 px)`
  o `... pero también a otra persona (0.55 frente a 0.51; ...)`. Antes el
  registro no decía por qué no se reconocía a alguien.

## Preparar

Desde `server/`:

```bash
uv run --no-sync sonia caras            # baja los modelos (210 MB) y da de alta a todos
uv run --no-sync sonia caras --probar   # además, cada segundo dice a quién ve la cámara
```

- No gasta: solo descarga los modelos (YuNet y SFace del OpenCV Model Zoo y
  ArcFace de InsightFace, de Hugging Face, comprobados por SHA-256) y las fotos
  públicas.
- Solo baja lo nuevo: con todo hecho, no toca la red.
- `sonia run` hace lo mismo solo al arrancar, en segundo plano. Hasta que
  termina, no reconoce a nadie.
- La build (`scripts/build_orquestador.sh`) se lleva `cache/faces/modelos` y
  `cache/faces/huellas`, pero no las fotos. La app los copia a su carpeta de
  datos y reconoce sin descargar nada.
- `sonia check` tiene una línea «Caras» que dice a cuántas personas reconoce.
  No usa la red.

Con 38 personas (5 del equipo y 33 ponentes), la primera vez tarda unos
7 segundos.

## Quién ya pasó por el stand

La memoria de personas es **por días, no por conversaciones** (decisión de Jean
del 7 de octubre de 2026). Por persona conocida se apunta cuándo se le dijo a
Sonnia que estaba delante: el primer aviso de cada día, el último y cuántos
(`cache/faces/visitas.json`, de cada equipo, no viaja en la build). Sobrevive a
que la conversación se reinicie (dos minutos sin nadie) y a reiniciar el
orquestador. Con eso la nota cambia:

- **La primera vez:** `Acaba de ponerse delante de la cámara Brian James (...). Para saludar a Brian James: ...`
- **Más tarde ese día** (cada 20 minutos si sigue ahí, o si vuelve): `Está delante de la cámara Brian James (...), que ya pasó hoy por el stand (la primera vez, a las 10:32 de la mañana): no le saludes como si fuera la primera vez.`
  No dice «ha vuelto», porque puede que no se haya ido.
- **Otro día** se empieza de cero: se le saluda como la primera vez, con su
  saludo.

De un ponente (o de alguien del equipo que también da charla), la nota dice
además cuándo es su charla, calculado con la hora del stand y la agenda de ese
momento:
- **Antes:** «La charla de Lowell Abbott es pasado mañana (el viernes 9 de octubre) a las 10:40 de la mañana: todavía no la ha dado».
- **Durante:** «es ahora mismo, hasta las 11:20».
- **Después:** «Lowell Abbott ya dio su charla hoy a las 10:40 de la mañana».

En la prueba real del 7 de octubre, con solo el título, Sonnia le preguntó a
Lowell «¿qué tal te fue?» dos días antes de su charla. Tenía la fecha y la
agenda en sus instrucciones, pero no las cruzó: por eso ahora lo calcula el
código, como el resto de la agenda. El día relativo también va ya hecho
(«hoy», «mañana», «pasado mañana», «dentro de 3 días»): con solo «el viernes 9
de octubre», un miércoles 7 dijo «mañana».

Con `look`, la foto dice lo mismo («Brian James ya pasó hoy por el stand...»).
La visita se apunta cuando la nota llega a Sonnia, no al componerla: si la
sesión cae justo entonces, la próxima vez se le vuelve a presentar.

Si se prueba en el equipo del stand el mismo día del evento antes de abrir,
`uv run --no-sync sonia caras --olvidar-visitas` para que nadie cuente como ya
visto. Las pruebas de días anteriores no cuentan.

Se probó el 7 de octubre de 2026 con GPT-Live de verdad, con las fotos como
cámara y saludos por texto. Victor, Wanda, Ivana, Brian (saludo del equipo) y
un ponente (saludo de ponente) recibieron su saludo. Tras reiniciarse la
conversación, Victor volvió y Sonnia le dijo «qué bueno tenerte por aquí de
nuevo», sin repetir lo de la moto.

## Saludos

`assets/faces/saludos.json` dice cómo saludar a alguien **la primera vez que
Sonnia le ve cada día** (`Para saludar a ...:` en la nota). Se escribe como una
instrucción a Sonnia, en una o dos frases:

- `groups`: uno por grupo para quien no tiene uno propio. Ahora, al equipo
  (`staff`) le pregunta por lo que hace en Sonnet Code y a los ponentes
  (`speaker`), por su charla; a las personas conocidas (`guest`), nada genérico.
- `people`: el propio de algunas personas, que manda sobre el de su grupo. El
  nombre, como sale en `staff.json`, `invitados.json` o la agenda; da igual
  acentos y mayúsculas. Si no casa con nadie, `sonia caras` y el registro lo
  avisan.

`sonia caras` marca con `[saludo propio]` a quien lo tiene, y `sonia check`
cuenta cuántos hay. Se lee al arrancar: tras cambiarlo, reiniciar el
orquestador.

## Añadir a alguien

- **Del equipo, si no está en la web (por ejemplo, Mariel):** en
  `assets/faces/staff.json`, con su cargo:
  `{"name": "Mariel ...", "role": "su cargo", "photos": ["fotos/mariel.jpg"]}`.
- **Una persona conocida, que no es del equipo ni ponente (como Victor y
  Wanda):** en `assets/faces/invitados.json`, con el mismo formato (`role` es
  opcional). Sonnia la presenta como «persona conocida del equipo de Sonnet
  Code».

En los dos casos:
1. Pon sus fotos, de frente y con buena luz, en `cache/faces/fotos/` (no van al
   repo). Mejor varias: una huella por foto reconoce mejor con distinta luz o
   ángulo.
2. **Que en cada foto salga solo su cara.** De cada foto se usa la cara más
   grande, así que de una foto de grupo hay que recortar la suya. Las de Victor
   y Wanda se recortaron el 7 de octubre de 2026 con YuNet y SFace. Su foto
   individual sirvió de referencia: en las de grupo se eligió la cara que más se
   le parecía (0,62 y 0,71 frente a 0,05 y 0,11 la del acompañante). El recorte
   se estrechó hasta que no quedó otra cara.
3. Su saludo, si lo tiene, en `saludos.json`.
4. `uv run --no-sync sonia caras`.

La huella viaja en la build (`cache/faces/huellas`), las fotos no. Si el equipo
del stand ya tenía huellas de antes, la app no las pisa. Pero a quien allí no
tiene ni huella ni fotos le pone la que trae la build, así que basta con
compilar después de `sonia caras`.

## Calibrar en el stand

Usa `sonia caras --probar` con la cámara ya colocada. Por cada cara imprime
algo así:

```
  (foto de 1920x1080)
  cara de 212 px -> Brian James: 0.58 (segunda 0.12) SÍ
  cara de  31 px -> Jean Calderon: 0.44 (segunda 0.10) no (pequeña)
```

| Variable | Por defecto | Qué hace |
|---|---|---|
| `FACES_ENABLED` | `true` | `false` apaga el reconocimiento. |
| `FACES_MODEL` | `arcface` | `sface` vuelve al modelo de antes, con sus huellas y su umbral, sin rehacer nada. |
| `FACES_ARCFACE_THRESHOLD` | `0.40` | Similitud mínima con ArcFace. Súbela si confunde a gente; bájala (no de 0,35) si no reconoce al equipo. |
| `FACES_THRESHOLD` | `0.52` | Similitud mínima con SFace. |
| `FACES_MARGIN` | `0.06` | Ventaja mínima sobre la segunda persona más parecida. |
| `FACES_MIN_FACE_PX` | `40` | Ancho mínimo de la cara en la foto de la cámara. A 1920 px son unos cuatro metros con una webcam normal; a 640 px, metro y medio. |
| `FACES_ANALYSIS_WIDTH` | `1920` | Ancho máximo de la foto en la que se buscan caras (0 = la de la cámara). |
| `FACES_SCAN_SECONDS` | `1` | Cada cuánto mira sola (0 = solo cuando Sonnia usa la cámara). |
| `FACES_CONFIRM_SCANS` | `2` | Revisiones en que tiene que salir antes de avisar, seguidas o no... |
| `FACES_CONFIRM_SECONDS` | `4` | ...dentro de estos segundos (nunca menos de dos revisiones seguidas). |
| `VISION_CAPTURE_WIDTH` y `_HEIGHT` | `1920` y `1080` | Resolución que se le pide a la cámara USB si abre por debajo (en Windows muchas webcams abren a 640x480). Si así no da imagen, se queda con la suya. 0 = no pedir. |
| `FACES_COOLDOWN_MINUTES` | `20` | Minutos sin repetir el aviso de la misma persona. |
| `FACES_SPEAKERS` | `true` | `false` reconoce solo al equipo. |
| `FACES_STAFF_FILE` | `assets/faces/staff.json` | Otra lista del equipo. |
| `FACES_DIR` | `cache/faces` | Modelos, huellas y fotos locales. |

Además, sin cámara (`VISION_SOURCE=none`), con `LLM_SUPPORTS_VISION=false` o
sin OpenCV, el reconocimiento se apaga solo con un aviso en el registro.

### De dónde salen los umbrales

Se midieron el 7 de octubre de 2026 con las 38 fotos reales y fotos libres de
eventos (gente de espaldas, un grupo, un stand, una sala vacía):

- **Personas distintas:** dos personas distintas del equipo y de los ponentes
  llegan a 0,46 de similitud (Alexander Vegazo con Wagner Luciano). Con el
  umbral de los ejemplos de OpenCV (0,363) se habrían confundido.
- **Desconocidos:** ninguna cara de desconocido pasó de 0,35, y las que más se
  acercaban eran pequeñas, del fondo.
- **La misma persona en fotos distintas:** dio entre 0,60 y 0,65.
- **Tiempo:** cada revisión tarda entre 8 y 24 ms en el Mac de desarrollo. Va
  en un hilo y no toca el bucle de audio.

Con la cámara real las similitudes de la misma persona suelen bajar (otra
luz, otro ángulo), así que el umbral se confirma en el stand con
`--probar`.

### ArcFace en vez de SFace (8 de octubre)

Medido con fotos que no son de nadie del stand: CPLFW, el banco público de
caras con pose cruzada (las mismas personas de frente y de perfil; 1776 fotos
de 683 personas, la copia de Hugging Face `marcelohaps/cplfw`). A la foto de
«la cámara» se le aplicó lo del stand: cara de 40 px en JPEG (lejos) y gamma
2,2 con ruido (contraluz). La referencia quedó como está, igual que las fotos
de la web.

Un stand simulado: 200 sorteos de 41 personas conocidas con una foto cada una,
y las fotos de todas las demás como desconocidos:

| Modelo y umbral | Conocidos reconocidos (normal / lejos y oscuro) | Desconocidos tomados por otro, por foto |
|---|---|---|
| SFace 0,52 (el de antes) | 38 % / 23 % | 0,004 % / 0,003 % |
| ArcFace R50 0,40 | 74 % / 57 % | 0,007 % / 0,011 % |
| ArcFace R50 0,35 | 82 % / 70 % | 0,014 % / 0,018 % |
| ArcFace MobileFaceNet 0,40 | 46 % / 30 % | 0,011 % / 0,007 % |

Cada foto suelta; además hacen falta dos aciertos en 4 s. Con nuestras 46 fotos
de referencia, las dos personas distintas más parecidas dan 0,27 con ArcFace
(José Aquino Cepeda y Jose Elias) y 0,46 con SFace (Wagner Luciano y Alexander
Vegazo, casi en su umbral). Reducidas a 24 px, ArcFace acepta el 100 % con 0,69
de media y nadie más pasa de 0,28; SFace, el 87 %.

ArcFace tarda 34 ms por cara en el Mac de desarrollo (SFace, 6 ms): con una
revisión por segundo y como mucho seis caras, va de sobra. El modelo pesa
174 MB y su licencia es solo para uso no comercial, como esta demo.

También se probó a «entrenar» mejor a cada persona, con R50 y umbral 0,40
(427 personas de CPLFW con tres fotos o más):

| Cómo se da de alta | Normal | Lejos y oscuro |
|---|---|---|
| 1 foto (los ponentes) | 74 % | 62 % |
| 1 foto + variaciones (espejo, más oscura, más pequeña) | 75 % | 65 % |
| 1 foto + variaciones, huella media | 71 % | 63 % |
| 2 fotos reales | 89 % | 77 % |

Las variaciones sintéticas apenas ayudan; una segunda foto real, distinta de
la primera, sube unos 15 puntos. Normalizar la luz de la cara (CLAHE o gamma)
tampoco ayudó con la webcam del Mac. Para el equipo, lo que funciona es tener
varias fotos suyas en `cache/faces/fotos` (ver «Añadir a alguien»).

### Por qué tardó 75 segundos en reconocer a Jean (8 de octubre)

En la app del Mac, la cámara dio imagen a las 13:10:57 y el aviso de Jean llegó
a las 13:12:12, con 0,55 de parecido. Entre medias Sonnia miró con `look` y
tampoco le reconoció, y a «¿sabes quién soy?» contestó que no. No se perdió
ninguna nota: ninguna revisión le dio por encima del umbral dos veces seguidas.
Las causas:

- **La foto se reducía a 768 px.** La cámara del Mac da 1920x1080, pero las
  caras se buscaban en la foto de la visión (768x432). Con el mínimo de 64 px,
  quien estaba a más de un metro ni se comparaba.
- **Revisiones seguidas cada 3 s.** Sentado delante del Mac y mirando a otras
  pantallas, Jean daba entre 0,26 y 0,43 (lo que da un desconocido). Solo
  pasaba de 0,52 en alguna foto suelta mirando a la cámara, y hacían falta dos
  seguidas, con 3 s entre ellas.
- **Una sola foto de referencia** (la de la web): con otra luz y de lado, se
  parece poco a la de la cámara.

Cuánto quita el tamaño se midió con las 46 fotos de referencia, reducidas hasta
que la cara mide N px y pasadas por JPEG como la cámara:

| Cara | Parecido con su huella (media, peor 10 %) | Pasa el umbral | Impostor más alto |
|---|---|---|---|
| 140 px | 0,95, 0,90 | 100 % | 0,43 |
| 48 px | 0,88, 0,79 | 100 % | 0,45 |
| 40 px | 0,84, 0,70 | 98 % | 0,43 |
| 32 px | 0,76, 0,51 | 89 % | 0,41 |
| 24 px | 0,65, 0,44 | 87 % | 0,43 |

Hasta 40 px el tamaño apenas quita parecido, y los impostores no suben al
encoger la cara. Por eso las caras se buscan a resolución completa con un
mínimo de 40 px. Además, YuNet detecta desde 0,6 de confianza en vez de 0,8:
con 0,8, ocho de cada veinte fotos de Jean sentado delante, algo girado, salían
sin cara. Una «cara» que no lo es no se parece a nadie: el umbral de parecido
manda.

## Si algo falla

Nada de esto tumba a Sonnia. Pase lo que pase, sigue conversando, aunque no
reconozca a nadie:
- Sin red la primera vez, sin modelos o con una descarga que no cuadra: aviso
  en el registro.
- Una foto que no baja o sin cara: aviso con el nombre, y el resto sigue.
- Una revisión fallida: se ignora y la siguiente lo intenta otra vez.
