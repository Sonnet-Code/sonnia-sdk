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

Fuentes exploradas sin resultado: CDN de Ready Player Me (muerto), Union
Avatars y MetaPerson (sin muestras públicas sin cuenta), Sketchfab CC0
(descarga con login), Kenney y Quaternius (personajes sin cara), Mozilla Hubs
(solo medio cuerpo), Blender Studio (solo `.blend`).

## Las dos VRM que siguen en el repo

`unity/Assets/Avatar/Yae.vrm` y `Snb.vrm` son de otra familia: modelos anime de
**VRoid**, del autor `tacochan`, con licencia de
[VRoid Hub](https://hub.vroid.com) que permite uso personal y modificación pero
**prohíbe uso comercial**. Títulos internos `yaechan_rwp` y `snbchan_rwb`.
Visemas VRM estándar (`Aa`/`Ih`/`Ou`/`Ee`/`Oh`, cinco formas en vez de quince),
así que el lip-sync es más tosco. Siguen funcionando (`Sonia > Elegir avatar`),
pero el registro visual es anime, no el estilo Apple/Meta que se buscaba.

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
