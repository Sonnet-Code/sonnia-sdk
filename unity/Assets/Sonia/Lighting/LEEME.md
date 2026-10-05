# Iluminación estilo Genies

Recursos de **Sonia > Iluminación estilo Genies** (`Assets/Scripts/Sonia/Editor/SoniaGeniesLighting.cs`). Es la iluminación de la demo Mia de Genies (https://genies.com/chat/mia) pasada de su runtime web (three.js) a URP. Se deshace con **Sonia > Iluminación de estudio**.

## Resultado con Sonia (5 de octubre de 2026)

No es la iluminación por defecto: la escena se queda con la de estudio. Se probó en Play con el avatar vivo, en el mismo frame y la misma pose, y la traslación fiel deja la cara de Sonia naranja.

- **Mejilla (sRGB):** Mia en genies.com (236, 152, 105); Sonia con la luz de estudio (177, 111, 91); Sonia con esta (235, 94, 43).
- **Causa:** la piel de Sonia (morena, con colorete) es mucho más saturada que la de Mia. Con solo la key, la mejilla da (173, 49, 19); con un ambiente gris neutro, (170, 81, 53). La key cálida, el HDR (cálido de frente) y el LUT sin la desaturación de ACES la empujan al naranja. Pasar la key a casi blanca (#fff0e4) apenas cambia nada: (235, 104, 56).
- **Comprobaciones:**
  - el Color Lookup de URP aplica el LUT igual que el `.cube`, con un error medio de 1,4/255;
  - volver con **Iluminación de estudio** deja la imagen idéntica píxel a píxel.
- **Cuándo volver a probarla:** con un avatar de piel más clara o menos saturada, como la de Mia.

## De dónde sale cada archivo

El 5 de octubre de 2026 se registraron las peticiones de red de genies.com/chat/mia en un Chrome sin ventana. La página solo descarga estos ajustes de escena:

| Archivo | Origen |
|---|---|
| `GeniesEnv_composer_hdr_v02_cube_90_3JS_07_512_unity.exr` | https://dbpochrf0zukx.cloudfront.net/hdr/composer_hdr_v02_cube_90_3JS_07_512.exr: un EXR equirectangular de 512x256, girado un cuarto de vuelta con `env_to_unity.py` (ver «Ejes» más abajo). Se importa como cubemap latitud-longitud con convolución especular y hace de reflejo por defecto al 0,5. |
| `GeniesLut_CCNeutralTonemapFilmicLUT_09_SP_32.png` | https://dbpochrf0zukx.cloudfront.net/luts/CCNeutralTonemapFilmicLUT_09_SP.cube: un LUT 3D de 25³ hecho con lutCreator.js. Se remuestrea por interpolación trilineal a la tira de 32³ (1024x32) que pide el Color Lookup de URP. |
| `SoniaShadowCatcher.shader` | Es propio. Hace lo del `ShadowMaterial` del shadow catcher de Mia y le añade un borde desvanecido. |
| `SoniaShadowCatcher.mat` | Lo crea el menú. |

Los valores salen de https://d344oyp4d2jz0e.cloudfront.net/naf/scene.json. Mia no es una genie «self-serve», así que usa los ajustes de escena por defecto. Su fondo marrón viene de `sceneBackgroundColor` (#633B00) y aquí no se usa. El archivo `naf/studio-scene.json`, con la luz hemisférica #ffd48b y la direccional #d7a67d ×4, es de las genies de estudio: Mia no lo carga.

En la tira del LUT, el azul elige el bloque, el rojo avanza a la derecha dentro del bloque y el verde va hacia arriba (fila de abajo = verde 0). La textura se importa lineal, sin mipmaps ni compresión.

## Conversión (three.js → URP)

| Mia (scene.json y valores por defecto del runtime) | Sonia |
|---|---|
| Direccional #ffd8b8 ×2, rotación x 12,44 y 10,78: casi de frente, algo a la izquierda de la pantalla y baja | Direccional principal #ffd8b8 a 2/π × 0,85 = 0,54, Euler (12,44; 10,78; 0), sombra suave al 100 %. También es `RenderSettings.sun`. |
| `AmbientLight` #b5b5b5 ×1; la hemisférica está apagada por defecto | Ambiente SH en modo Custom (`SoniaGeniesLook`): 0,85 × (#b5b5b5 lineal / π + 0,5 × HDR convolucionado con el coseno) + 0,15 |
| Entorno: el HDR ×0,5 | El mismo SH para el difuso y el cubemap ×0,5 para los reflejos |
| megaStylizer `flatness` 0,15: el difuso queda al 85 % y se suma un 15 % del albedo sin sombrear | El 0,85 y el +0,15 de las filas anteriores |
| megaStylizer `LightA` #ffb189, α 0,33 (ecuador 317°, polar 30°, en espacio de vista: arriba a la derecha y detrás) | Rim cálido: direccional sin sombra a 0,6 que gira con la cámara |
| megaStylizer `LightB` #a9d2ff, α 0,45 (ecuador 36°, polar −30°: abajo a la izquierda y detrás) | Rim frío: direccional sin sombra a 0,75 que gira con la cámara |
| `toneMapping` Linear, exposición 1 | Tonemapping None: el grading LDR de URP recorta a 1 igual |
| LUT tras el `OutputPass`, sobre color sRGB | Color Lookup a contribución 1: URP también lo aplica en sRGB (`ApplyColorGrading`, modo LDR) |
| Bloom, viñeta y SSAO apagados (sin `enabled`, o con radio 0) | Sin bloom ni ajustes de color. Se quedan la viñeta navy y el desenfoque del telón, que son de la marca. |
| Shadow catcher negro al 40 % en y = 0 | `Sonia/Shadow Catcher` al 40 %, desvanecido entre 0,8 y 1,6 m del centro |

- **Por qué ÷π:** three.js usa luces físicas (difuso = albedo/π × irradiancia) y URP mete la π en la intensidad (difuso = albedo × intensidad). La luz ambiente plana se divide igual. El HDR no, porque su difuso en three.js ya es la radiancia media ponderada por el coseno.
- **Ejes:** en Mia el avatar mira a +Z con la cámara en +Z; en Sonia mira a −Z con la cámara en −Z. Una dirección (x, y, z) de three.js es (x, y, −z) en Unity.
- **El HDR girado:** three.js pone el centro del equirectangular (u = 0,5) en +X, y el «Latitude-Longitude» de Unity lo pone en +Z. Por eso la imagen va desplazada un cuarto de ancho a la derecha. Está comprobado en Unity: se renderizó el cubemap en diez direcciones y el error frente a lo esperado fue de un 2 %; sin el giro salía el entorno rotado 90°. El SH se calcula con el EXR original de la CDN, no con el girado.
- **Ambiente SH:** solo funciona en los modos Custom y Skybox; en Trilight y Flat, Unity rehace el SH a partir de los colores e ignora el asignado. Unity guarda `RenderSettings.ambientProbe` ya convolucionado y dividido entre π. El shader evalúa c0 + c1·y + c2·z + c3·x + c4·xy + c5·yz + c6·(3z²−1) + c7·xz + c8·(x²−y²) (ver `SHCoefficients` en `com.unity.render-pipelines.core`). Los 27 coeficientes de `SoniaGeniesLighting.cs` salen del EXR con esa convención. Comparado con la convolución exacta, el error es del 3 % al 5 %. Comprobado en Unity: una esfera Lit blanca solo con este ambiente da el valor previsto × 0,96, que es el difuso dieléctrico de URP, en las seis direcciones.
- **Rims:** el megaStylizer de la web añade `color × mezcla(1, albedo) × α × rampa(N·L)` con la normal en espacio de vista. Una direccional de URP da `albedo × color × I × N·L`. I sale del ajuste por mínimos cuadrados de las dos curvas sobre las normales que miran a cámara (0,74 y 0,86), un poco rebajado. Los shaders Mega del SDK de Unity no traen el estilizador: solo aparece por nombre en una herramienta interna de Genies (`MegaStylizerPropertyTransfer`).

## Scripts de conversión

Están en `scripts/iluminacion_genies/`. Se ejecutan desde `server/`, con las dependencias de la cámara (`--extra camera`, que trae numpy y OpenCV):

```bash
uv run --no-sync python ../scripts/iluminacion_genies/lut_to_unity.py CCNeutralTonemapFilmicLUT_09_SP.cube GeniesLut_CCNeutralTonemapFilmicLUT_09_SP_32.png 32
uv run --no-sync python ../scripts/iluminacion_genies/env_to_unity.py composer_hdr_v02_cube_90_3JS_07_512.exr GeniesEnv_composer_hdr_v02_cube_90_3JS_07_512_unity.exr
uv run --no-sync python ../scripts/iluminacion_genies/env_to_sh.py composer_hdr_v02_cube_90_3JS_07_512.exr 0.425 0.275021
```

`env_to_sh.py` imprime los 27 coeficientes de `AmbientCoefficients` de `SoniaGeniesLighting.cs` (y un Trilight aproximado, solo como referencia).
