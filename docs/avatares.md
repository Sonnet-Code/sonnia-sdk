# Catálogo de avatares

De dónde salió el avatar de Sonia, qué otros personajes se evaluaron y hasta
dónde se pueden personalizar (ropa, pelo, cara). Investigación de septiembre de
2026. Los detalles de montaje en Unity están en `docs/unity.md`, sección 4 y 6b.

## El avatar actual

`unity/Assets/Avatar/Babe.glb` es una copia de **`xr_babe.glb`**, del repo
[XRCupid/hub](https://github.com/XRCupid/hub/tree/main/public/avatars)
(carpeta `public/avatars`, ficheros en Git LFS). Es un avatar de **Ready Player
Me** exportado como malla única: 8,8 MB, 14 041 triángulos, un solo
`SkinnedMeshRenderer` (`Wolf3D_Avatar`) con un material y tres texturas de
1024x1024 (base color, normal, metallic-roughness). Trae **67 blendshapes**: los
15 visemas de Oculus (`viseme_*`) más los 52 de ARKit. Look: top corto naranja,
vaqueros, zapatillas blancas, pelo corto burdeos.

## Por qué no se puede generar uno nuevo

**Ready Player Me cerró en enero de 2026.** El editor web y el CDN
(`https://models.readyplayer.me/<id>.glb`) están muertos, comprobado con `curl`.
No se puede crear un avatar nuevo, ni elegirle la ropa en su editor, ni
descargar por ID. Lo único que queda son los GLB que ya estaban exportados y
viven en repos públicos de GitHub, que es exactamente de donde salen todos los
personajes de este catálogo.

Todos los avatares de Ready Player Me comparten esqueleto (Mixamo,
`mixamorig`), nombres de malla y juego de morph targets, así que **son
intercambiables entre sí**: animaciones, rig Humanoid generado y lip-sync
funcionan igual con cualquiera de ellos.

## Los diez finalistas

![Bustos de las candidatas](img/avatares-candidatas.jpg)

![Caras de las candidatas](img/avatares-candidatas-caras.jpg)

| Archivo | Repo | Tamaño | Blendshapes de boca | Triángulos | Ropa y pelo | Licencia |
|---|---|---|---|---|---|---|
| `hc_dlm_zoe1.glb` | [rorosaga/holo-cierge](https://github.com/rorosaga/holo-cierge/tree/main/concierge-frontend/public/models/zoe) | 2,7 MB | 67 (15 visemas + ARKit) | 13 967 | Camisa blanca, falda negra con leggings, bob castaño con flequillo | Repo sin licencia |
| `hc_dlm_zoe6.glb` | [rorosaga/holo-cierge](https://github.com/rorosaga/holo-cierge/tree/main/concierge-frontend/public/models/zoe) | 2,6 MB | 67 | 13 646 | Camisa blanca con logo, chinos beige, melena castaña | Repo sin licencia |
| `hc_dlm_zoe7.glb` | [rorosaga/holo-cierge](https://github.com/rorosaga/holo-cierge/tree/main/concierge-frontend/public/models/zoe) | 4,9 MB | 67 | 13 646 | Igual que zoe6, **más 12 animaciones dentro del GLB** | Repo sin licencia |
| `xr_coach_grace.glb` | [XRCupid/hub](https://github.com/XRCupid/hub/tree/main/public/avatars) | 13,4 MB | 67 | 18 075 | Vestido de fantasía con alas y armadura dorada, pelirroja con pecas | Repo sin licencia |
| `xr_coach_rizzo.glb` | [XRCupid/hub](https://github.com/XRCupid/hub/tree/main/public/avatars) | 13,9 MB | 67 | 19 493 | Mismo vestido de fantasía, piel oscura, melena negra | Repo sin licencia |
| **`xr_babe.glb`** (el elegido) | [XRCupid/hub](https://github.com/XRCupid/hub/tree/main/public/avatars) | 8,8 MB | 67 | 14 041 | Top corto naranja, vaqueros, pelo corto burdeos | Repo sin licencia |
| `xr_chickie.glb` | [XRCupid/hub](https://github.com/XRCupid/hub/tree/main/public/avatars) | 8,7 MB | 67 | 13 009 | Camisa y pantalón negros, piel oscura, bob negro | Repo sin licencia |
| `xr_Ciri1.glb` | [XRCupid/hub](https://github.com/XRCupid/hub/tree/main/public/avatars) | 11,0 MB | 52 (solo ARKit) | 21 885 | Chaqueta verde militar, vaqueros negros, bob rubio | Repo sin licencia |
| `rv_avatar1_f.glb` | [carlosfranzreb/ravas](https://github.com/carlosfranzreb/ravas/tree/main/rpm/public) | 10,0 MB | 52 (solo ARKit) | 19 390 | Polo azul claro, moño castaño alto | MIT (el repo) |
| `rv_avatar3_f.glb` | [carlosfranzreb/ravas](https://github.com/carlosfranzreb/ravas/tree/main/rpm/public) | 9,1 MB | 52 (solo ARKit) | 17 673 | Polo azul claro, melena negra larga | MIT (el repo) |

Los `hc_dlm_zoe*` vienen en **multi-malla** (9 mallas, texturas por prenda: los
blendshapes están repartidos entre `Wolf3D_Head`, `Wolf3D_Teeth`, `EyeLeft` y
`EyeRight`, y hay que escribir el mismo peso en los cuatro). Los `xr_*` y `rv_*`
vienen en **malla única con atlas**, que es lo que usa Sonia: un solo renderer,
una sola llamada de dibujo y un solo sitio donde escribir los visemas.

Los que solo traen 52 blendshapes de ARKit no tienen `viseme_*`: el lip-sync
tendría que salir de `jawOpen` + `mouthFunnel` + `mouthPucker` + `mouthClose`.
Se puede, pero es peor que mapear visemas uno a uno.

### Descartados del mismo barrido

| Archivo | Motivo |
|---|---|
| `bp_avatar.glb`, `w3d_test.glb`, `rts_model.glb`, `xr_coach_posie.glb` | Hombres |
| `xr_Erika.glb`, `xr_Mindy.glb`, `pa_femalephysician.glb` | Solo 2 morph targets, insuficiente para lip-sync |
| `hc_zoeSingleMesh.glb` | Sin texturas embebidas, se renderiza gris |
| `visage_halfbody.glb` | Medio cuerpo con casco, sin piernas |
| `hc_dlm_zoe3.glb`, `hc_dlm_zoe5.glb` | Duplicados de `zoe6` |
| `hc_Zoe.glb` | Igual que `zoe6` pero con `KHR_draco_mesh_compression`: obligaría a añadir el paquete Draco en Unity sin ganar nada |
| `rpm_feminine000.glb` | Atuendo táctico militar, inadecuado para el stand |

Fuentes exploradas sin resultado en aquel barrido: CDN de Ready Player Me
(muerto; ver "La mina" más abajo), Union
Avatars y MetaPerson (sin muestras públicas sin cuenta), Sketchfab CC0
(descarga con login), Kenney y Quaternius (personajes sin cara), Mozilla Hubs
(solo medio cuerpo), Blender Studio (solo `.blend`).

## Segunda búsqueda (9 de septiembre de 2026)

Barrido de GitHub por repos que contengan GLB de Ready Player Me: 33 proyectos
inspeccionados, **55 modelos descargados y renderizados**. De ahí salen catorce
mujeres nuevas con blendshapes suficientes:

| Archivo | Repo | Blendshapes | Triángulos | Look |
|---|---|---|---|---|
| `brunette.glb` | [met4citizen/TalkingHead](https://github.com/met4citizen/TalkingHead/tree/main/avatars) | 72 (15 visemas + 57 ARKit) | 13 317 | Gafas, flequillo, top deportivo azul y burdeos. **Licencia CC BY-NC 4.0 documentada**, la más limpia del barrido. Repetida en DialogLab como `avatar1.glb` |
| `female-avatar1.glb` | [ecruhue/DialogLab](https://github.com/ecruhue/DialogLab/tree/main/client/public/assets) | 72 | 21 182 | Sudadera beige con estampado, moño alto |
| `female-avatar2.glb` | ecruhue/DialogLab | 72 | 17 518 | Pelo rizado, gafas, jersey gris de cuello alto |
| `female-avatar3.glb` | ecruhue/DialogLab | 72 | 14 320 | Rubia con coleta y **sudadera amarilla lisa**: el mejor lienzo del lote para el logo del DevFest |
| `female-avatar4.glb` | ecruhue/DialogLab | 72 | 12 634 | Melena negra, top corto verde azulado con logo al pecho, vaqueros |
| `female-avatar5.glb` | ecruhue/DialogLab | 72 | 13 546 | Rubia con gafas, vestido amarillo con cinturón, botas altas |
| `63ba9de7….glb` | [itskhagendra/V-Tubing-APP](https://github.com/itskhagendra/V-Tubing-APP/tree/master/Assets/Avatars) | 72 | 15 050 | Gafas de sol, vestido verde, chaqueta blanca. Malla única con atlas |
| `69b1976b….glb` | [Kshitijm7/digital-persona](https://github.com/Kshitijm7/digital-persona/tree/main/public/avatars) | 67 | 12 020 | Chaleco de rombos, pantalón corto |
| `69b19dfb….glb` | Kshitijm7/digital-persona | 67 | 14 710 | Abrigo negro largo, guantes, pelo recogido |
| `dlm_zoe2.glb` | [rorosaga/holo-cierge](https://github.com/rorosaga/holo-cierge/tree/main/concierge-frontend/public/models/zoe) | 67 | 13 967 | Otra Zoe que se nos pasó: camisa blanca, vaqueros negros |
| `29689621….glb` | [DiegoTovar/RealidadVirtual2022](https://github.com/DiegoTovar/RealidadVirtual2022-ARKit-ReadyPlayerMe) | 63 | 15 044 | Camisa tostada, pantalón de cuadros |
| `c47ba0a6….glb` | DiegoTovar/RealidadVirtual2022 | 63 | 14 818 | Camisa blanca, vaqueros negros, bob, gafas |
| `avatar2.glb` | [nagarajpandith/aido](https://github.com/nagarajpandith/aido/tree/master/public/assets/models) | 15 (solo visemas) | 14 301 | Cárdigan largo crema y botas. Sin blendshape de parpadeo |
| `women.avatar.glb` | [gitchaell/ngx-profile-avatar](https://github.com/gitchaell/ngx-profile-avatar) | 72 | 11 598 | Medio cuerpo: solo cabeza y cuello |

Los otros 41 son hombres, duplicados (`user_avatar.glb` de XRCupid **es Babe**),
medios cuerpos o modelos con dos blendshapes.

Aparecen tres exportaciones nuevas que no había en la primera tanda: la de **72
blendshapes** (los 15 visemas de Oculus más los 57 de ARKit, una vuelta de tuerca
sobre los 67 de Babe), la de **63** y la de **15** (solo visemas, sin parpadeo).

### La mina: 1 075 avatares en la Wayback Machine

El CDN de Ready Player Me está muerto, pero el archivo de internet guardó copias.
La API CDX los lista:

```bash
curl "http://web.archive.org/cdx/search/cdx?url=models.readyplayer.me*&fl=original,timestamp,length,statuscode&filter=original:.*\.glb.*&filter=statuscode:200&collapse=urlkey&page=0"
```

Salen **1 213 identificadores distintos**, 1 075 con tamaño de avatar completo
(1,5 a 14 MB). Cada uno se descarga con el prefijo `id_` para saltarse el visor
del archivo:

```bash
curl -sSL -o avatar.glb "https://web.archive.org/web/<timestamp>id_/https://models.readyplayer.me/<id>.glb"
```

El pero: la exportación por defecto de RPM traía los **57 blendshapes de ARKit
sin los 15 visemas de Oculus**, que había que pedir con `?morphTargets=Oculus
Visemes`. Solo 18 de las copias archivadas lo llevan. Los otros sirven igual para
el lip-sync por fonemas de uLipSync (con un mapa a ARKit: `jawOpen`,
`mouthFunnel`, `mouthPucker`, `mouthClose`, `mouthSmile*`) y traen
`eyeBlinkLeft/Right`, así que el parpadeo está cubierto.

El archivo también se corta si se le piden muchas descargas a la vez: va bien
secuencial con dos segundos de pausa.

### Trasplantar ropa entre avatares

Todos los avatares de Ready Player Me comparten cuerpo base, topología y
esqueleto. Eso abre la vía que RPM cerró: **coger la prenda de un avatar y
ponérsela a otro en Blender**. La sudadera lisa de `female-avatar3` sobre el
cuerpo de Babe, por ejemplo, da una superficie grande y plana donde el logo del
DevFest se pinta sin pelear con el atlas del top corto. Es más trabajo que
repintar una textura, pero mucho menos que modelar una prenda desde cero.

## Las dos VRM que siguen en el repo

`unity/Assets/Avatar/Yae.vrm` y `Snb.vrm` son de otra familia: modelos anime de
**VRoid**, del autor `tacochan`, con licencia de
[VRoid Hub](https://hub.vroid.com) que permite uso personal y modificación pero
**prohíbe uso comercial**. Títulos internos `yaechan_rwp` y `snbchan_rwb`.
Visemas VRM estándar (`Aa`/`Ih`/`Ou`/`Ee`/`Oh`, cinco formas en vez de quince),
así que el lip-sync es más tosco. Siguen funcionando (`Sonia > Elegir avatar`),
pero el registro visual es anime, no el estilo Apple/Meta que se buscaba.

## Diferencias de calidad entre modelos

Medido sobre los ficheros, no a ojo. El script está en el scratchpad
(`calidad.py`): abre cada GLB, mide las texturas y calcula el **área UV de la
cabeza** (los vértices que mueven los blendshapes de cara) multiplicada por el
tamaño de su textura. Eso da los píxeles reales que le tocan a la cara, que es
lo que se ve en un plano medio de 1080x1920.

![Nitidez de cara: Babe frente a dos multi-malla](img/avatares-nitidez-cara.jpg)

| Tipo de exportación | Píxeles de cara (lado equivalente) | Ejemplos |
|---|---|---|
| Medio cuerpo (la cabeza se queda casi todo el atlas) | **901** | `women.avatar.glb` |
| **Multi-malla**: `Wolf3D_Head` con textura propia de 1024 | **768** | Zoe 1/2/6/7, las cinco de DialogLab, Brunette, digital-persona |
| **Atlas de malla única**, reparto normal | **681** | Chickie, Ciri, Grace, Rizzo, ravas, fool |
| Reexportado por Blender con la cabeza a 512 | **482** | los seis de DiegoTovar, `aido_2` |
| **Atlas de malla única con reparto malo** | **325** | **Babe** |

**Babe es la peor del catálogo en resolución de cara.** Su atlas mete la cabeza
en el 10 % de una textura de 1024, así que la cara vive en unos 325x325 píxeles
reales; una Zoe tiene 768x768, es decir **5,6 veces más área de textura**. En la
comparación de arriba se nota en cejas, pestañas y el borde de los labios.

Otros ejes, por orden de importancia:

- **Juego de blendshapes** (marca la generación del exportador): **72** (los 15
  visemas de Oculus + los 57 de ARKit) > **67** (visemas + 52) > **63** > **57**
  (solo ARKit; es lo que devolvía el CDN por defecto) > **52** > **15** (solo
  visemas, sin parpadeo) > 5 / 2 / 0. Babe tiene 67; las de DialogLab,
  TalkingHead y V-Tubing tienen 72.
- **Quién exportó el fichero.** `generator: Ready Player Me` es la exportación
  original y fiel. `Khronos glTF Blender I/O` significa que alguien lo pasó por
  Blender, y ahí se pierden cosas: los de DiegoTovar bajaron la cabeza a 512 y
  uno tiene el anillo del cuello desplazado 9,15 mm. `glTF-Transform` es una
  pasada de optimización que a veces se lleva por delante los morph targets
  (`readyplayer2.glb` se quedó con dos).
- **Tamaño de textura.** Casi todos, 1024. Algún reexportado tiene 2048 en la
  ropa pero 512 en la cara, que es lo contrario de lo que interesa.
- **Formato.** PNG (sin pérdida) o JPEG (más ligero, con artefactos). A 1024
  apenas se nota.
- **La antigüedad no predice nada.** Los nombres que son ObjectId de MongoDB
  llevan la fecha dentro: el catálogo va de **noviembre de 2022 a marzo de
  2026** y no hay correlación entre fecha y calidad. Lo que manda son los
  parámetros con los que se pidió el fichero, no cuándo se creó el avatar.
- **El peso del fichero tampoco.** `fool.glb` pesa 15,3 MB y tiene 681 px de
  cara; Zoe 6 pesa 2,6 MB y tiene 768. El peso lo mandan los triángulos y el
  número de texturas.

## Trasplantar cabezas entre avatares

Comprobado sobre la geometría, no supuesto:

- La cabeza de Babe es una pieza suelta de **3 838 triángulos y 1 979
  vértices**. El `Wolf3D_Head` de Zoe 1 tiene **exactamente los mismos** 3 838 y
  1 979. Todos los avatares de RPM usan la misma malla de cabeza; lo que cambia
  son las posiciones de los vértices de la cara y la textura.
- El **anillo del cuello son 17 vértices** y coincide **al 0,00 mm** entre Babe,
  Zoe 1, Zoe 6, Chickie, Female 3, Brunette y las de digital-persona. RPM dejaba
  el cuello fijo a propósito para poder intercambiar cabezas y cuerpos. La única
  excepción medida es `c47ba0a6` (DiegoTovar), desplazado 9,15 mm en bloque por
  el reexportado de Blender: se arregla moviendo la pieza.
- En una exportación de **malla única** como la de Babe las piezas siguen siendo
  componentes desconectados: en Blender, `P > By Loose Parts` recupera cabeza,
  dientes, ojos, cuerpo, top, pantalón, zapatillas y pelo por separado.

Receta, en Blender:

1. Importar los dos GLB. Separar el `Wolf3D_Avatar` del de malla única por
   piezas sueltas.
2. Borrar del receptor la cabeza, los dientes y los dos ojos.
3. Emparentar las piezas del donante al armature del receptor (`Ctrl+P > With
   Empty Groups` no; hay que conservar los grupos de vértices, que ya vienen con
   los mismos nombres de hueso de Mixamo).
4. Exportar como GLB y pasarlo por **Sonia > Elegir avatar** y **Colocar
   avatar**.

Dos avisos:

- **El cuello canta si los tonos de piel no coinciden.** La cabeza se lleva su
  textura y el cuerpo la suya. La forma de no tener ese problema es trasplantar
  **cabeza y cuerpo juntos** y quedarse solo con la ropa del otro avatar.
- **Cambiar de cuerpo no arregla la cara.** Si se pone la cabeza de Babe sobre
  otro cuerpo, la cara sigue teniendo sus 325 píxeles. Para ganar nitidez hay
  que ir al revés: quedarse con una cabeza multi-malla (Zoe 1, Brunette,
  Female 3) y vestirla como haga falta.

### Hecho: la cabeza de Babe sobre el cuerpo de Zoe 1

`scripts/injerto_glb.py` hace la operación sin Blender, con numpy y nada más.
El resultado está en `unity/Assets/Avatar/BabeCamisa.glb` (11,5 MB): cara, pelo,
ojos y dientes de Babe sobre el cuerpo, la camisa blanca, la falda y los zapatos
de Zoe 1. Conserva los **67 blendshapes** (comprobado: `viseme_aa` mueve 1 349
vértices de la boca, `eyeBlinkLeft` 283 del párpado).

![Cabeza de Babe sobre el cuerpo de Zoe 1](img/avatar-injerto-cabeza.jpg)

```bash
python3 scripts/injerto_glb.py cabeza cuerpo.glb cabeza.glb salida.glb
```

Cómo funciona, por si hay que repetirlo con otro par:

1. Del cuerpo se borran los **nodos** de `Wolf3D_Head`, `Wolf3D_Teeth`,
   `EyeLeft`, `EyeRight` y `Wolf3D_Hair`. Las mallas se quedan en el fichero
   pero, sin nodo, no se instancian.
2. Del donante de atlas se conservan solo los triángulos cuyas piezas sueltas
   tienen el techo por encima de y = 1,52, que son exactamente cabeza, pelo,
   ojos y dientes. **No se borran vértices**: solo se reescribe el búfer de
   índices, así que los 67 morph targets siguen apuntando a donde apuntaban.
3. Los accessors del donante (atributos y blendshapes, incluidos los dispersos)
   se copian **byte a byte** a base de duplicar sus bufferViews. Nada se
   recodifica.
4. El nodo nuevo cuelga del mismo padre y reutiliza el `skin` del cuerpo, que es
   legítimo porque los dos esqueletos son el mismo.

### Lo que no funcionó: injertar solo la prenda

![Babe con la camisa de Zoe injertada](img/avatar-injerto-prenda.jpg)

Primero se probó lo contrario: dejar a Babe entera y traerle solo la camisa
(`injerto_glb.py prenda`). La camisa entra y se dobla bien con el esqueleto,
pero salen dos costuras, y las dos son culpa de la misma decisión de RPM: **borra
la geometría que queda oculta bajo la ropa**.

- A Babe le falta la piel del torso y del antebrazo, porque su top corto las
  tapaba. Con otra prenda encima el problema no se ve, pero en las muñecas sí:
  la manga de Zoe termina en otro sitio y deja un hueco.
- La camisa de Zoe viene cortada por la cintura, donde su falda la tapaba. Sobre
  los vaqueros de tiro bajo de Babe, ese corte queda a la vista.

Se puede arreglar trayendo también el `Wolf3D_Body` del donante y ajustando el
tono de piel, pero el trasplante de cabeza da el mismo resultado con una pieza
menos y sin retoques de textura.

## Personalización

### Cambiar de personaje

Directo: copiar el `.glb` a `unity/Assets/Avatar/`, ejecutar **Sonia > Elegir
avatar (VRM o GLB)** y luego **Sonia > Colocar avatar**. El menú genera el
Avatar Humanoid, cablea lip-sync, parpadeo, mirada y coreógrafo, y recoloca
cámara, panel y luces. Las animaciones se heredan por retargeting.

### Cambiar la ropa

**No hay editor de ropa.** El avatar viene con la geometría de las prendas ya
fusionada en la malla única, así que no se puede cambiar de prenda desde Unity;
lo que sí se puede es **repintar la textura**, y eso alcanza para la camiseta
del staff.

El `BASE_COLOR` de Babe es un atlas de 1024x1024 con las zonas bien separadas:

| Zona del atlas | Qué contiene |
|---|---|
| Cuadrante superior izquierdo | Cara y piel, arriba; dientes y encías, abajo |
| Franja central superior | Vaqueros (con marca Calvin Klein horneada en la etiqueta) |
| Esquina superior derecha | Pelo burdeos y los ojos |
| Cuadrante inferior izquierdo | Zapatillas blancas (también con marca Calvin Klein) |
| **Cuadrante inferior derecho** | **El top naranja** |

Recetas, de menos a más trabajo:

1. **Recolorear el top**: extraer el PNG del GLB, pintar de otro color el
   cuadrante inferior derecho, volver a empaquetar (o, más simple en Unity,
   duplicar el material y sustituir solo el `Base Map` por el PNG editado).
2. **Logo del DevFest en el pecho**: sobre ese mismo cuadrante, el pecho es la
   isla UV grande de la derecha; pintar ahí el logo. Es prueba y error con una
   textura de comprobación, pero se hace en una tarde.
3. **Sin tocar texturas**: un `Quad` pequeño con el logo, hijo del hueso
   `chest` del rig y separado un par de milímetros del cuerpo. Funciona con
   cualquier avatar y se ve bien de frente, que es el único ángulo del stand.
4. **Cambiar de prenda de verdad** (mangas largas, otra silueta): abrir el GLB
   en Blender y sustituir la geometría. Es trabajo real y rompe los pesos de
   skinning si no se hace con cuidado.

Ojo con las marcas: los vaqueros y las zapatillas llevan el logotipo de Calvin
Klein horneado en la textura (era ropa de marca licenciada dentro de Ready
Player Me). En plano medio no se ve, pero si algún encuadre baja de la cintura
conviene borrarlo del atlas.

### Cambiar cara, pelo o cuerpo

No se puede desde Unity: la cara es geometría, no parámetros. Las opciones
reales son elegir otro personaje del catálogo o irse a un generador vivo:

- **[VRoid Studio](https://vroid.com/en/studio)** (gratis, Pixiv): editor
  completo de cara, pelo y **ropa**, exporta VRM. Estilo anime.
- **[MetaPerson Creator](https://avatarsdk.com)** (Avatar SDK): el sucesor
  natural de Ready Player Me, primer avatar gratis, exporta GLB con
  blendshapes.
- **[Avaturn](https://avaturn.me)**: descartado en su día por el usuario.

## Dónde están los archivos

Los diez GLB finalistas, los renders individuales y las hojas de contacto
completas quedaron en el scratchpad de la sesión del 9 de septiembre de 2026:

```
/private/tmp/claude-501/-Users-jeanc-calderon-Documents-git-sonia/404d413a-4239-493d-9eb2-0b30ea0980ca/scratchpad/hunt/stylized/
```

Es un directorio temporal y se borrará. Los enlaces de la tabla permiten volver
a descargarlos; si se quiere conservar el lote (unos 100 MB), hay que moverlo
fuera de `/tmp`. En el repo solo vive el elegido, `unity/Assets/Avatar/Babe.glb`.

## Licencias

Ninguno de estos avatares tiene licencia limpia de asset: son exportaciones que
usuarios subieron a sus repos. Dos repos fuente no llevan licencia
(`holo-cierge`, `XRCupid/hub`) y uno es MIT (`ravas`), pero el MIT cubre el
código, no necesariamente el avatar. Las VRM de `tacochan` prohíben
explícitamente el uso comercial. Como el proyecto es sin ánimo de lucro y de uso
personal, se asume el riesgo (ver `docs/licencias.md` y el principio 8 de
`CLAUDE.md`); si algún día hubiera uso comercial, habría que rehacer el avatar
en MetaPerson o VRoid con licencia propia.
