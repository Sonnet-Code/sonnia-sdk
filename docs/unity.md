# Guía del avatar en Unity

Cómo montar, configurar y construir el lado de Unity de Sonia: el avatar 3D que
reproduce la voz del orquestador, sincroniza los labios, cambia de animación
según el estado y muestra imágenes en su escena.

El proyecto ya existe en `unity/`. Esta guía va desde abrirlo hasta dejar una
build de kiosco lista para el stand.

## 1. Abrir el proyecto

1. Instalar **Unity 6000.6.0f1** (Unity 6.6) desde Unity Hub. La versión exacta
   está en `unity/ProjectSettings/ProjectVersion.txt`; abrir con otra versión
   fuerza una migración que no hace falta.
2. Añadir la carpeta `unity/` en Unity Hub y abrirla.
3. La primera vez el editor resolverá los paquetes. Entre ellos está
   `com.unity.nuget.newtonsoft-json` (3.2.2), que es el que usan los scripts
   para el JSON del protocolo. Si el editor estaba abierto cuando se añadió al
   manifiesto, usar **Window > Package Manager** y esperar a que termine, o
   cerrar y volver a abrir el proyecto.
4. Abrir `Assets/Scenes/SampleScene.unity`.

Si la consola se queja de que no encuentra `Newtonsoft.Json`, el paquete no se
ha resuelto: revisar `unity/Packages/manifest.json` y la conexión al registro de
Unity (la resolución de paquetes sí necesita internet la primera vez; después
queda en caché).

### Input System

`ProjectSettings/ProjectSettings.asset` tiene `activeInputHandler: 1`, es decir
**solo el Input System nuevo**. El API clásico `UnityEngine.Input`
(`Input.GetKey`, `Input.GetKeyDown`) lanza una excepción en tiempo de ejecución.
Todo el código de Sonia usa `UnityEngine.InputSystem` y el `EventSystem` de la
escena necesita un `InputSystemUIInputModule`, no un `StandaloneInputModule`. El
menú de creación de escena lo arregla si hace falta.

## 2. Crear la escena base

Menú **Sonia > Crear escena base**. Crea en la escena activa:

```
Sonia                       SoniaClient, AudioSource, AudioStreamPlayer,
│                           LipSyncController, AvatarStateController,
│                           WebcamFrameSender (desactivado), SoniaDebugUI,
│                           SoniaBootstrap
├── ImagePanel              ImagePanelController, encima de la cabeza del avatar
│   ├── Quad                MeshRenderer con Assets/Sonia/Materials/SoniaImagePanel.mat
│   └── Caption             TextMeshPro (3D), sobre la imagen, oculto hasta que
│                           llega un pie de foto
└── SoniaHUD                Canvas overlay 1080x1920: estado arriba, subtítulos
                            abajo, campo de texto y botón Interrumpir
EventSystem                 Con InputSystemUIInputModule (se crea si falta)
```

Además coloca la cámara para el encuadre vertical y deja los ajustes de build en
1080x1920. Todo eso se explica en la sección 3.

El menú deja a propósito **vacíos** los campos del avatar. Se rellenan en el
paso 5. La acción se puede deshacer con Ctrl+Z / Cmd+Z, salvo los ajustes de
build, que se vuelven a aplicar con **Sonia > Configurar build 9:16**.

Si el HUD sale sin texto, faltan los recursos de TextMeshPro: **Window >
TextMeshPro > Import TMP Essential Resources**.

## 3. Pantalla vertical 9:16

La pantalla del stand es un monitor en **vertical, 1080x1920**. Toda la escena
está pensada para ese formato: sobra alto y falta ancho, así que el panel de
imágenes va **encima** del avatar en lugar de a un lado.

### Cámara y encuadre

**Sonia > Crear escena base** deja la cámara principal con un encuadre
provisional, antes de que exista ningún avatar:

| Ajuste | Valor |
|---|---|
| Posición | `(0, 1.3, -2.7)` |
| Rotación | `(0, 0, 0)` |
| Field of View | 52 (vertical) |
| Near Clip | 0.1 |

Son solo un punto de partida. En cuanto hay un avatar en la escena, **Sonia >
Colocar avatar** recalcula la cámara de verdad a partir de los huesos del rig
(caderas y cabeza), con FOV 40 y muy poco aire por encima de la cabeza, y deja
preparado además un plano más abierto para los bailes y un tercer plano para
cuando hay una imagen puesta. El cálculo completo y los valores concretos con
el avatar actual están en la sección 6b, "Encuadre del stand".

Esto **da por hecho que el avatar está en el origen del objeto `Sonia`, de pie
y orientado hacia la cámara**. **Sonia > Colocar avatar** ya deja cualquier VRM
así (ver "Detalles del VRM que no son obvios" en la sección 6b); si mueves el
avatar a mano, ajusta la cámara en la misma proporción.

### Panel de imágenes

**Sonia > Crear escena base** deja el objeto `ImagePanel` en una posición
provisional, `(0.35, 1.35, 0.6)`, con un `Quad` de 0,55 × 0,31 m: sirve solo
para que el objeto exista antes de colocar el avatar.

**Sonia > Colocar avatar** recalcula su posición y su tamaño de verdad,
proyectando la silueta de la cabeza del avatar sobre la pantalla y encajando
el panel en el hueco libre que queda arriba a la derecha. El cálculo completo
y los valores con el avatar actual están en la sección 6b, "Panel de
imágenes".

En `ImagePanelController`, el tamaño se recalcula con cada imagen respetando
dos límites: `Panel Height` y `Panel Max Width`, que son los que deja puestos
el menú.

### HUD

El `Canvas Scaler` está en `Scale With Screen Size` con referencia
**1080 × 1920** y `Match` 0,5, así que todo escala con la pantalla. La
distribución, en coordenadas de esa referencia:

| Elemento | Posición |
|---|---|
| Conexión y estado | Esquina superior izquierda, a 40 px del borde |
| Subtítulo del usuario | Abajo centrado, a 290 px del borde inferior |
| Subtítulo de Sonia | Abajo centrado, a 160 px del borde inferior |
| Campo de texto y botón | Fila inferior, a 50 px del borde |

### Ajustes de build

**Sonia > Configurar build 9:16** deja los Player Settings así:

| Ajuste | Valor |
|---|---|
| Default Screen Width | 1080 |
| Default Screen Height | 1920 |
| Default Is Native Resolution | desactivado |
| Fullscreen Mode | Fullscreen Window |
| Run In Background | activado |
| Resizable Window | desactivado |
| Visible In Background | activado |

El menú **Crear escena base** ya los aplica; el ítem separado sirve para volver
a ponerlos si alguien los toca.

### Probar en el editor

La Game view no se configura desde el script, así que se elige a mano una vez:

1. En la Game view, abre el desplegable de aspecto (arriba a la izquierda, suele
   poner `Free Aspect`).
2. Elige **9:16 Portrait** si aparece en la lista.
3. Si no aparece, pulsa el **+** del final del desplegable y añade una entrada
   con Type `Fixed Resolution`, Width 1080, Height 1920 y el nombre que quieras.

Queda guardado por proyecto, así que solo hay que hacerlo la primera vez.

## 4. Conseguir un avatar femenino con visemas

El avatar de la demo, `Assets/Avatar/Yae.vrm`, ya está en el proyecto y trae
sus blendshapes de boca. La vía rápida es no tener que conseguir nada:

1. Con la escena base creada (sección 2), ejecutar **Sonia > Colocar avatar**.
   Con Yae elegido por defecto, esto instancia el VRM, detecta sus
   blendshapes, cablea el lip-sync y el parpadeo, y ajusta cámara, panel y
   fondo (todo el detalle está en la sección 6b).
2. Si se prefiere el otro modelo incluido, `Assets/Avatar/Snb.vrm`, elegirlo
   antes con **Sonia > Elegir avatar (VRM o GLB)** y volver a ejecutar **Colocar
   avatar**.

El requisito real es que la malla de la cara tenga **blendshapes de boca**;
sin ellos el lip-sync cae al modo de envolvente, que abre y cierra la boca
pero no articula. **Sonia > Colocar avatar** reconoce solo cuatro
convenciones de nombres (ver la sección 6b, "Cambiar de avatar"): VRM
estándar (`Aa`/`Ih`/`Ou`/`Ee`/`Oh`, como Yae y Snb), VRoid Studio
(`Fcl_MTH_*`), Seed-san (`lip_*`) y Oculus / Ready Player Me (`viseme_*`, ya
descontinuado). Si un avatar no encaja en ninguna, el menú avisa en la
consola y hay que rellenar `LipSyncController` a mano (sección 7).

### Conseguir otro avatar femenino gratuito

> Ready Player Me cerró en enero de 2026; los pasos antiguos ya no funcionan.

- **VRoid Studio** (gratuito, de Pixiv, para macOS y Windows, en
  [vroid.com/en/studio](https://vroid.com/en/studio)): elegir un preset
  femenino, ajustar la ropa (una camiseta lisa del color del staff sirve para
  la sección 4b) y exportar como **VRM**. El proyecto ya trae instalado
  **UniVRM** por git URL (ver `unity/Packages/manifest.json`):

  ```
  com.vrmc.gltf: https://github.com/vrm-c/UniVRM.git?path=/Packages/UniGLTF#v0.131.2
  com.vrmc.vrm: https://github.com/vrm-c/UniVRM.git?path=/Packages/VRM10#v0.131.2
  ```

  Arrastrar el `.vrm` exportado a `Assets/Avatar`, elegirlo con **Sonia >
  Elegir avatar VRM** y ejecutar **Sonia > Colocar avatar**.
- **Modelos VRM de muestra** con licencia libre, para probar sin modelar nada:
  AliciaSolid (el VRM de muestra oficial de UniVRM/Dwango, en la sección de
  *samples* de [github.com/vrm-c/UniVRM](https://github.com/vrm-c/UniVRM)) o
  modelos de [hub.vroid.com](https://hub.vroid.com) filtrados por
  condiciones de uso libres. Se importan igual que cualquier VRM.
- **GLB con morph targets**: cualquier `.glb`/`.gltf` con blendshapes de boca
  (un VRoid exportado como GLB en vez de VRM, o un avatar de MetaPerson
  Creator de Avatar SDK, que da el primer avatar gratis) se arrastra
  directamente a `Assets/Avatar`. El proyecto tiene instalado
  `com.unity.cloud.gltfast` (6.20.0), que importa GLB/glTF con morph targets
  sin paquetes adicionales. **Sonia > Elegir avatar (VRM o GLB)** acepta
  también `.glb`, `.gltf` y `.fbx`, y **Colocar avatar** hace el resto: si el
  modelo llega sin Animator Humanoid (glTFast no lo crea), `SoniaHumanoidRig`
  construye un Avatar a partir de los nombres de hueso de Mixamo (`Hips`,
  `Spine1`, `LeftArm`, `LeftForeArm`..., con o sin prefijo `mixamorig:`), lo
  guarda en `Assets/Avatar/Generated/<modelo>_Humanoid.asset` y añade el
  Animator. Los avatares de Ready Player Me usan exactamente ese esqueleto.
  Los blendshapes se detectan con la convención Oculus (`viseme_*`,
  `eyeBlinkLeft/Right`, `jawOpen`) cuando existen.

Las animaciones son las de Mixamo de `Assets/Animations/Mixamo/`, que ya
están en el proyecto (sección 6b). Un avatar nuevo con rig Humanoid las
hereda directamente en cuanto se le asigna el `Animator Controller`, por el
retargeting habitual de Unity: no hace falta volver a exportarlas de Mixamo.

## 4b. Camiseta del staff y logo de Sonnet Code

Sonia se presenta como parte del staff del DevFest, así que el avatar debe llevar la misma camiseta que el staff y la pantalla debe dejar claro que es de Sonnet Code:

- **Camiseta.** Yae ya lleva una camiseta blanca lisa, horneada en la textura del material `body` del `SkinnedMeshRenderer` `yaechan_rwp_body`. Para cambiar el color o poner el logo del DevFest, la vía directa es editar esa textura (o el `.vrm` abierto en Blender) y sustituirla por una del mismo tamaño. Si se genera el avatar desde cero en VRoid Studio es más simple: elegir la camiseta y su color en el editor de ropa antes de exportar, y para el logo exacto exportar como GLB, abrirlo en Blender, y sustituir la textura de la prenda superior por una con el logo del DevFest (basta con pintar el logo sobre la zona del pecho en el UV). Alternativa rápida sin Blender, válida para cualquier avatar: un `Quad` pequeño con el logo del DevFest colocado sobre el pecho como hijo del hueso `chest` del rig, ligeramente separado del cuerpo para que no atraviese la malla.
- **Logo de Sonnet Code en pantalla.** Añadir en el Canvas del HUD (`SoniaHUD`) una `Image` con el logo (`Assets/UI/logo-sonnet.png`, importado como Sprite) anclada arriba a la derecha, de unos 220 px de ancho para 1080x1920, siempre visible aunque el HUD de depuración esté oculto (F1 solo oculta el grupo de depuración, así que el logo va fuera de ese grupo). Un segundo logo más discreto puede ir abajo, junto a los subtítulos.
- **Colores.** El fondo de la escena ya usa el color corporativo (cámara en `#1B1F2A`, telón con degradado de `#2A3142` a `#12151C`), puesto por **Sonia > Colocar avatar** (sección 6b, "Fondo y luz"). Para cambiar el tono, editar `CameraBackground`, `BackdropTop` y `BackdropBottom` en `Editor/SoniaAvatarSetup.cs` y volver a ejecutar el menú.

## 5. Asignar los campos en el inspector

Hoy casi todo lo cablea el propio menú. Con la escena creada (sección 2) y el
avatar colocado (sección 4), no queda prácticamente nada por asignar a mano.
Esta sección sirve de referencia para cuando algo no se ha rellenado (un
componente falta en la escena, un campo se renombró en el script) o para
ajustar el resultado a ojo.

| Menú | Qué cablea |
|---|---|
| **Sonia > Crear escena base** | `LipSyncController.Audio Player`; en `AvatarStateController`: `Avatar Root`, `Look Target` (cámara principal), `Image Look Target` (panel); `WebcamFrameSender.Client`; todas las referencias del HUD y de `SoniaBootstrap` |
| **Sonia > Colocar avatar** | El `Animator` del avatar (sin controlador; Avatar Humanoid generado si hace falta); en `AvatarStateController`: `Head Bone`, `Face Renderer`, `Blink Left/Right Blend Shape`, `Lip Sync`; en `LipSyncController`: `Face Renderer`, `Jaw Open/Mouth Open Blend Shape` y las 15 `Viseme Bindings`; `MotionPlayer` (Animator y máscara) y `AvatarChoreographer` (reproductor y set); uLipSync y `PhonemeLipSyncBridge`; `EyeGazeController` (cabeza y ojos); `Choreographer`, `Target Camera` y `Wide Shot Position` en `CameraFramingController`; y la posición de cámara, panel, telón e iluminación |
| **Sonia > Actualizar componentes** | Añade los componentes de gesticulación que falten en el objeto `Sonia` y vuelve a cablear `SoniaBootstrap` |

Lo único que ningún menú toca:

- **`CameraFramingController` → `Panel Shot Position` / `Panel Shot Field Of
  View`**: el plano de cámara mientras hay una imagen puesta se queda en el
  valor por defecto del script, `(0, 1.62, -1.42)`. Si con el avatar actual
  queda mal encuadrado, ajustarlo a mano en el inspector.
- **`LipSyncController` → `Jaw Bone`**: solo hace falta si el avatar no tiene
  ningún blendshape de boca; ninguno de los avatares de la demo lo necesita.
- **`AvatarStateController` → `Head Rotation Offset`**: por defecto es
  `(0, 0, 0)`. Solo hay que tocarlo si la cabeza mira torcida, con un rig cuyo
  hueso de cabeza no tiene el eje Z hacia delante; probar `(0, 90, 0)` y
  `(-90, 0, 0)`.
- **`SoniaClient` → `Server Url`**: el campo ya trae por defecto
  `ws://127.0.0.1:8765`; solo hace falta tocarlo si se cambia `WS_PORT`.

Si algo sale vacío que debería estar cableado, revisar la consola: tanto
**Sonia > Colocar avatar** como **Sonia > Crear escena base** avisan con
`[Sonia]` de cualquier campo o componente que no hayan podido rellenar.

## 6. Animaciones: cómo funcionan ahora

No hay Animator Controller. Los clips los reproduce `MotionPlayer` con la
Playables API de Unity (fundidos por código, dos capas: cuerpo entero y torso
con máscara) y `AvatarChoreographer` decide qué clip suena en cada momento.
Ver [6b. Avatar y animaciones](#6b-avatar-y-animaciones). El `Animator` del
avatar sigue existiendo porque es la salida del grafo y quien hace el
retargeting humanoide, pero no lleva controlador.

## 6b. Avatar y animaciones

El avatar de la demo es `Assets/Avatar/Babe.glb` (Ready Player Me, importado
con glTFast: malla única `Wolf3D_Avatar` con 15 visemas Oculus y 52 blendshapes
ARKit, huesos de ojos, esqueleto Mixamo). Quedan como alternativa los VRM
`Assets/Avatar/Yae.vrm` y `Snb.vrm`. Las animaciones son la biblioteca femenina
de Ready Player Me (`Assets/Animations/RPM/`, hecha para este esqueleto: 10
idles, 6 de hablar, 5 bailes) más los FBX de Mixamo (`Assets/Animations/Mixamo/`).
Todo el montaje está automatizado en menús pensados para poder ejecutarse las
veces que haga falta sin acumular basura:

| Menú | Qué hace |
|---|---|
| **Sonia > Elegir avatar (VRM o GLB)** | Recuerda qué modelo (`.vrm`, `.glb`, `.gltf` o `.fbx`) se va a colocar (se guarda en EditorPrefs) |
| **Sonia > Crear set de animaciones** | Reimporta los FBX de `RPM/` y `Mixamo/` (Humanoid, sin compresión, bucle solo en los bucles base, centrados), rellena `Assets/Animations/SoniaMotionSet.asset` desde `SoniaAnimations.cs`, genera la máscara de torso y cablea `MotionPlayer` y `AvatarChoreographer` |
| **Sonia > Iluminación de estudio** | Monta o actualiza key, fill, rim y hair light, el halo, las motas, el Volume (ACES, bloom, viñeta, color, profundidad de campo) y SMAA |
| **Sonia > Actualizar componentes** | Añade al objeto `Sonia` de una escena ya creada los componentes que le falten y recablea `SoniaBootstrap` |
| **Sonia > Colocar avatar** | Instancia el modelo (VRM o GLB), le construye Avatar Humanoid si no lo trae, lo cablea (lip-sync, fonemas, parpadeo, mirada de ojos, coreógrafo) y deja cámara, panel, telón e iluminación de estudio en su sitio |
| **Sonia > Captura vertical 9:16** | Guarda un PNG 1080x1920 de la cámara principal en `unity/Temp` |

Un montaje desde cero se hace en ese orden. Cualquier comprobación de encuadre
se mira con la captura vertical: las capturas normales del editor salen en 16:9
y engañan, porque en 9:16 se ve mucho menos a lo ancho.

### Cambiar de avatar

**Sonia > Colocar avatar** vale para cualquier VRM. Detecta solo la convención
de blendshapes de la malla de la cara y rellena el mapa de visemas y el
parpadeo. Reconoce cuatro familias, por este orden:

| Convención | Se reconoce por | Visemas | Parpadeo |
|---|---|---|---|
| VRM estándar | `Aa` | `Aa`, `Ih`, `Ou`, `Ee`, `Oh` | `Blink_L` / `Blink_R` |
| VRoid Studio | `Fcl_MTH_A` | `Fcl_MTH_A/I/U/E/O` | `Fcl_EYE_Close_L` / `_R` |
| Seed-san | `lip_a` | `lip_a/i/u/e/o` | `blink_L` / `blink_R` |
| Oculus, Ready Player Me | `viseme_aa` | `viseme_*` | `eyeBlinkLeft` / `Right` |

Si el modelo solo trae un blendshape para los dos ojos, se usa ese para ambos.
Si no encaja ninguna convención, avisa en la consola y hay que rellenar
`LipSyncController` a mano.

### Encuadre del stand

La pantalla es vertical 1080x1920 y el usuario quiere a Sonia ocupando casi
toda la pantalla, en plano medio, con la boca grande y clara. **Sonia > Colocar
avatar** calcula la cámara a partir de los huesos del avatar:

- Se ve desde `caderas - 0,05` hasta `alto de la cabeza + 0,12` metros.
- FOV vertical 40, rotación cero, X = 0.
- La Y es el centro de esa franja y la Z sale de la trigonometría del FOV.

Con Yae sale una franja de 0,95 m y la cámara queda en `(0, 1.20, -1.31)`.

Ese plano es perfecto para hablar y escuchar, pero se queda corto en dos casos:
cuando Sonia baila se sale por los lados, y cuando enseña una imagen no hay
sitio para ponerla. De eso se encarga `CameraFramingController`, que maneja
**tres encuadres** y va al que toque con una interpolación suave:

| Encuadre | Cuándo | Cámara con Yae |
|---|---|---|
| Abierto | El Animator está en un estado con la etiqueta `wide`: bailes, gestos de atención y saludo | `(0, 0.83, -3.79)` |
| Panel | `ImagePanelController.IsVisible` es cierto | `(0, 1.62, -1.51)` |
| Base | El resto del tiempo | `(0, 1.20, -1.31)` |

La prioridad es esa: si Sonia baila mientras hay una imagen puesta, manda el
baile. Medido en Play, la transición tarda algo menos de un segundo y es
monótona, sin saltos: de `y=1.27` a `y=1.57` en diez muestras al ir, y de
`y=1.54` a `y=1.25` al volver.

El plano abierto se calcula igual que el medio, pero cabiendo el cuerpo entero:
de los pies menos 5 cm a la cabeza más 15 cm, **y con 1,55 m de ancho para los
brazos**. En 9:16 casi siempre manda el ancho: con Yae el alto pedía 2,40 m de
distancia y los brazos 3,79 m, así que gana el ancho. La cámara acaba en
`(0, 0.83, -3.79)`.

Esa envergadura de 1,55 m no es un número al azar: midiendo los bounds de los
renderers durante `Dance_HipHop` y `Blow_Kiss`, los brazos de Yae llegan a 1,49 m
de punta a punta. El precio de que quepa todo es que durante el baile Sonia ocupa
poco más de la mitad de la pantalla; es la aritmética del 9:16 y no hay forma de
esquivarla salvo aceptar que se salga una mano. Si se prefiere lo segundo, se
baja `WideArmSpan` en `Editor/SoniaAvatarSetup.cs`.

### Marca de Sonnet Code

El HUD lleva el logo arriba a la izquierda y el telón usa el fondo corporativo.
Los assets están en `unity/Assets/UI/`: `logo-sonnet.png` (texto blanco, para
fondo oscuro), `logo-sonnet-color.png` (texto navy, por si el fondo fuera claro)
y `sonnet-bg-navy-4k.png` (fondo 16:9 con degradado, la S de marca de agua y el
logo). Los ajustes de importación los fuerza `Editor/SoniaBrandAssets.cs`: los
logos como Sprite sin mipmaps y con compresión de alta calidad, el fondo como
textura normal con mipmaps.

| Elemento | Valor |
|---|---|
| Logo del HUD | 300 x 125 px, esquina de arriba a la izquierda, margen 48 px, `preserveAspect` |
| Canvas del HUD | Screen Space - Camera, Main Camera, plano 0,3, orden 100 |
| Escala del Canvas | Referencia 1080x1920 |
| Etiquetas de depuración | Debajo del logo, en (48, -197) y (48, -249) |
| Telón | Textura `sonnet-bg-navy-4k`, tiling (0,221, 0,70), offset (0,02, 0) |
| Fondo de cámara | `#0E1B33`, a juego con el navy |

Dos decisiones que no son obvias:

**El Canvas va en Screen Space - Camera, no en Overlay.** Un Canvas en Overlay no
aparece cuando se renderiza a una RenderTexture, y todas las verificaciones se
hacen con **Sonia > Captura vertical 9:16**, que es exactamente eso. En Overlay
las capturas salían sin HUD y no había forma de comprobarlo.

**El logo cuelga del Canvas, no del grupo que esconde F1.** El HUD de depuración
vive ahora en un hijo llamado `Debug` y es ese el que apaga y enciende F1; la
marca se queda siempre puesta. En una escena que ya existía, **Sonia > Actualizar
componentes** crea el grupo, mete dentro los widgets que ya había y reapunta
`hudRoot`.

Del fondo corporativo se toma una franja estrecha y alta, porque la textura es
16:9 y el telón es vertical. La franja sale de la **izquierda**, que es donde
está la S de marca de agua, y se corta por arriba (tiling y = 0,70) para dejar
fuera el logo de la esquina: con el del HUD ya hay uno y no puede salir dos
veces. Las proporciones cuadran, así que la textura no se deforma: 0,221 x 3840
por 0,70 x 2160 da una relación de 0,561 y el telón tiene 0,562.

### Fondo y luz

La cámara usa fondo sólido `#1B1F2A` sin skybox y un telón (`Backdrop`) con
degradado vertical `#2A3142` a `#12151C` detrás del avatar, escalado para tapar
los encuadres. Encima de eso, **Sonia > Iluminación de estudio** (que también
ejecuta **Colocar avatar**) monta un retrato de tres puntos bajo el objeto
`SoniaStage`, con posiciones calculadas a partir de la cabeza y la cámara:

| Luz | Tipo | Dónde | Color | Intensidad | Sombras |
|---|---|---|---|---|---|
| `KeyLight` | Spot 62° | 1,1 m a la izquierda de cámara, 0,75 m sobre los ojos | cálida `#FFF2E0` | 6 | suaves, fuerza 0,7 |
| `FillLight` | Spot 80° | al otro lado, casi en el eje de cámara | fría `#D1E0FF` | 2,2 | no |
| `RimLight` | Spot 48° | detrás y arriba, a la derecha | azul `#9EC7FF` | 9 | no |
| `HairLight` | Spot 40° | detrás y arriba, a la izquierda | azul | 5 | no |
| direccional de la plantilla | | queda como ambiente tenue (0,25) | | | suaves, 0,35 |

Ambiente en modo Trilight (cielo azul marino, ecuador gris azulado, suelo casi
negro). Las intensidades de foco en URP no están en lux: con 22 en la key la
cara salía quemada, con 6 queda modelada. Ajustar a ojo con la captura 9:16.

Efectos gratuitos, todos bajo `SoniaStage`:

- `Halo`: quad de 2,2 x 2,8 m entre el avatar y el telón, material aditivo con
  degradado radial (`Assets/UI/Generated/halo_3_2.png`) y tinte azul de marca al
  22 %. Simula el haz de un foco sobre el telón.
- `Motes`: sistema de partículas de 70 motas aditivas de 0,8 a 2,2 cm, vida de
  9 a 16 s, ruido lento, entre el avatar y el telón. Apenas se ven, que es la
  idea.
- Volume: tonemapping ACES, bloom 0,22 con umbral 1,0, viñeta 0,28, contraste
  +10, saturación +8, profundidad de campo Bokeh enfocada a la cabeza con
  apertura 9 (desenfoca un poco el telón, no el panel).
- Cámara: SMAA alta, postprocesado activado.

Los materiales aditivos de halo y motas usan `Particles/Unlit` en modo
**Additive** (`_Blend = 2`, SrcAlpha/One). Con premultiplicado se pintaban
cuadrados blancos porque la textura es blanca y solo lleva la forma en el alfa.

Las medidas salen del rig humanoide, **nunca de los bounds de los renderers**:
los accesorios (mochilas, armas, el brazo robótico de Seed-san) los ensanchan
un metro largo y darían un encuadre absurdo.

### Panel de imágenes

En el plano medio no cabe una imagen que se lea: a los lados de la cabeza quedan
unos 160 px y encima de ella unos 265, y con eso no se ve nada desde el pasillo
del stand. Por eso la imagen tiene su propio encuadre. Cuando aparece, la cámara
se echa atrás y sube, Sonia baja a la mitad de abajo de la pantalla del pecho
hacia arriba y la mitad de arriba queda libre para el panel.

El panel se dimensiona sobre ese encuadre, no sobre el plano medio:

| Parámetro | Valor |
|---|---|
| Profundidad | z 2,6 |
| Ancho en pantalla | 76 % |
| Proporción | 16:9 |
| Borde superior | 0,93 |
| Aire sobre la coronilla | 0,015 |
| Alto de la caja del pie | 30 % del alto de la imagen |
| Coronilla en pantalla | -0,13, justo bajo el centro |
| Borde inferior de la pantalla | 10 cm por debajo de los hombros |

Con Yae sale una imagen de 1,28 x 0,72 m centrada en `(0, 2.35, 2.60)`, que son
821 px de ancho en la pantalla del stand. Los mismos valores se copian a
`panelHeight` y `panelMaxWidth` de `ImagePanelController`, que es quien recalcula
el tamaño real al mostrar cada imagen.

El pie va centrado debajo, con la caja del ancho del panel y **auto-ajuste de
tamaño de TextMeshPro**: un pie largo se encoge y parte en líneas en lugar de
salirse. Probado con "Sonnet Code" en una línea y con "Sonnet Code, equipos de
ingeniería que entregan" en dos.

Un detalle que costó un rato: el telón de fondo tiene que quedar **por detrás**
del panel. Estaba en z 2,5 con el panel en z 2,6 y tapaba la imagen entera sin
dar ningún error. Ahora su Z se calcula a partir de la del panel y el telón se
escala para cubrir los tres encuadres.

### Cómo se importan los clips

Los FBX llegan como **Generic**, con un clip llamado `mixamo.com` y con **Root
Transform Position (XZ) > Based Upon: Original**; cada clip trae al personaje
unos centímetros desplazado de su origen y Sonia se iba del encuadre.
**Sonia > Crear set de animaciones** deja cada FBX de `Assets/Animations/RPM/`
y `Assets/Animations/Mixamo/` como **Humanoid** (avatar del propio modelo), con
el clip llamado como el archivo, **sin compresión de fotogramas** (la
compresión aplana dedos y muñecas, que es donde se lee la gesticulación), con
`Loop Time` solo en los tres bucles base (`F_Standing_Idle_001`, `Listening`,
`Thinking`) y con el root motion en **Center of Mass** (se extrae y, con
`applyRootMotion` apagado, se descarta). Todo lo demás se reproduce una sola
vez: así el coreógrafo sabe cuándo termina un gesto y encadena el siguiente en
lugar de cortarlo a mitad, que era lo que hacía el Animator Controller antiguo
(478 transiciones sin tiempo de salida y clips de habla forzados a bucle).

### MotionPlayer y AvatarChoreographer

`MotionPlayer` construye un `PlayableGraph`: un `AnimationClipPlayable` por clip
vivo, un `AnimationMixerPlayable` por capa (fundidos cruzados con pesos
normalizados, así nunca pasa por una pose hundida) y un
`AnimationLayerMixerPlayable` con dos capas: cuerpo entero y torso con la
máscara `Assets/Animations/SoniaUpperBody.mask` (todo menos raíz, piernas y sus
IK). `Play(clip, capa, fundido)` devuelve un handle con progreso, tiempo
restante y si terminó.

`AvatarChoreographer` recibe el estado del orquestador y las señales de cada
frase y decide qué suena, con fundidos elegidos caso por caso (campos
serializados, ajustables en el inspector):

| Estado | Qué hace |
|---|---|
| idle | bucle base + una variación de reposo (una sola vez, fundido 0,6 s) cada 7-16 s + un gesto de atención (baile, cuarta pared o suave; entrada 0,4 s, salida 0,7 s) a los 6 s y luego cada 12-30 s, repartidos 45/30/25 % sin repetir |
| listening | bucle de escucha + un asentimiento en la capa de torso (fundido 0,3 s) cada 4-8 s |
| thinking | bucle de pensar + una variación cada 4-8 s |
| speaking | clips de gesticulación encadenados sin bucle (fundido 0,5 s entre ellos); cada `speech_start` cambia de gesto solo si el actual va por más de la mitad |
| saludo | `PlayGreeting()` al primer listening tras 25 s sola (y 20 s entre saludos); se deja terminar salvo que toque pensar o hablar |

Mientras suena un gesto grande (atención o saludo) `IsWideShot` es cierto y
`CameraFramingController` abre el plano. Las listas de clips viven en
`SoniaAnimations.cs` y el asset `SoniaMotionSet` las materializa.

### Añadir una animación nueva

1. Dejar el FBX en `Assets/Animations/Mixamo/` (o `RPM/`) con el nombre del
   clip.
2. Añadir el nombre a la lista que toque en `Assets/Scripts/Sonia/SoniaAnimations.cs`
   (`IdleVariationClips`, `TalkingClips`, `NodClips`, `AttentionClips` con su
   categoría...).
3. Ejecutar **Sonia > Crear set de animaciones**.

Se probaron y descartaron: `Counting` (habla mirándose las manos con la cabeza
agachada, queda mal en plano medio) e `IdleLooking2` como idle (gira el cuerpo
de perfil demasiado tiempo; se usa como gesto suave de atención, una sola vez).

### Cara: lip-sync, ojos, parpadeo y cabeza

- **Lip-sync** (`LipSyncController`): tres fuentes por orden de preferencia.
  Visemas con timestamp del orquestador si llegan; si no, **fonemas en tiempo
  real** con uLipSync (MIT, MFCC) a través de `PhonemeLipSyncBridge`, que le
  pasa cada bloque de audio de `AudioStreamPlayer` (evento `OnAudioFrame`) y
  traduce A/I/U/E/O a `viseme_aa/I/U/E/O` escalados por el volumen con una
  curva suave (abre un poco con voz floja, nunca del todo); si no, envolvente o
  RMS. Suavizado con ataque 20/s y caída 10/s, peso máximo 65 %. Con Gemini en
  streaming los visemas del servidor no llegan a tiempo (se calculan con la
  frase entera), así que en la práctica manda el modo de fonemas.
- **Escala de blendshapes**: los GLB de glTFast definen los blendshapes de 0 a 1
  y los FBX/VRM de 0 a 100. `LipSyncController.BlendShapeScale` lee el peso del
  frame y se escribe siempre en la escala de la malla; sin esto la cara de Babe
  se estiraba hasta el pecho.
- **Ojos** (`EyeGazeController`): los huesos `LeftEye`/`RightEye` no van en el
  rig humanoide (el retargeting los dejaba bizcos). Cada ojo apunta al objetivo
  de `AvatarStateController` (cámara, panel o punto de pensar) desde su
  posición, con el punto de enfoque alejado a 2,5 m como mínimo, **ganancia
  0,65** (con ojos grandes estilizados, compensar toda la rotación de la cabeza
  lee como mirar de reojo), límites de 10° de guiñada y 8° de cabeceo, sacadas
  de hasta 2,5°, vistazos de 5° cada 4-9 s, desviación total acotada a 7°,
  microtemblor y parpadeo en los saltos grandes. Durante bailes y gestos grandes
  es un 60 % más vivo.
- **Cabeza** (`AvatarStateController`): mira al objetivo con peso 0,7 y hasta
  40°, con vaivén lento de 1,4° (ruido Perlin) y un asentimiento de hasta 2,5°
  en las sílabas fuertes (según `LipSyncController.MouthOpen`). Parpadeo cada
  2,5-6 s.

### Detalles del VRM que no son obvios

- Los VRM miran hacia +Z y la cámara del stand también, así que el avatar va con
  rotación Y = 180 para quedar de frente.
- `Vrm10Instance.UpdateType` se pone en `Update` (por defecto es `LateUpdate`).
  Si no, sus expresiones, todas a peso cero, pisarían los visemas que
  `LipSyncController` escribe en `LateUpdate` y la boca no se movería.
- El `LookAt` del `Vrm10Instance` apunta a la cámara (`SpecifiedTransform`), así
  que en un VRM los ojos siguen al visitante además de la cabeza. Con un GLB
  (Babe) no hay `Vrm10Instance` y de los ojos se ocupa `EyeGazeController`.
- Seed-san lleva un brazo robótico (`robo_arm`) colgado de la mochila, movido por
  spring bones y ajeno al rig humanoide. Cuenta para los bounds del avatar, que
  llegan hasta x ≈ 1,5.

## 7. Mapeo de visemas

El orquestador envía los identificadores del conjunto Oculus (ver
`docs/protocolo.md` y `server/sonia/visemes.py`). El mapa por defecto de
`LipSyncController` es editable en el inspector. La columna Oculus sirve para
avatares GLB que usen esa convención de nombres (por ejemplo Ready Player Me,
ya descontinuado, o algunos exportados desde MetaPerson Creator); la columna
VRoid/VRM es la que aplica a los avatares de la sección 4.

| Protocolo | Sonidos en español | Oculus (`viseme_*`) | VRoid/VRM (`Fcl_MTH_*`) |
|---|---|---|---|
| `sil` | silencio, puntuación | `viseme_sil` | (sin blendshape / boca cerrada) |
| `PP` | p, b, m | `viseme_PP` | (cerrada) |
| `FF` | f, v | `viseme_FF` | (cerrada) |
| `TH` | th | `viseme_TH` | (cerrada) |
| `DD` | d, t | `viseme_DD` | (cerrada) |
| `kk` | k, c, g, q, j | `viseme_kk` | (cerrada) |
| `CH` | ch, ñ, y, ll | `viseme_CH` | `Fcl_MTH_I` |
| `SS` | s, z, ce/ci, x | `viseme_SS` | `Fcl_MTH_I` |
| `nn` | n, l | `viseme_nn` | (cerrada) |
| `RR` | r, rr | `viseme_RR` | (cerrada) |
| `aa` | a | `viseme_aa` | `Fcl_MTH_A` |
| `E` | e | `viseme_E` | `Fcl_MTH_E` |
| `ih` | i | `viseme_I` | `Fcl_MTH_I` |
| `oh` | o | `viseme_O` | `Fcl_MTH_O` |
| `ou` | u | `viseme_U` | `Fcl_MTH_U` |

Los nombres se buscan sin distinguir mayúsculas y aceptando el prefijo con punto
que añaden algunos importadores (`Head.viseme_aa` encuentra `viseme_aa`). Un
nombre vacío es válido y significa "este visema no mueve ningún blendshape".

### El mapa que usa el avatar de la demo

Ninguno de los avatares que se han probado sigue las dos convenciones de arriba,
así que el mapa lo rellena **Sonia > Colocar avatar** al detectar la familia de
blendshapes del modelo (ver la sección 6b). Con Yae, que usa la convención VRM
estándar sobre el `SkinnedMeshRenderer` `yaechan_rwp_face`, queda así:

| Protocolo | Blendshape | | Protocolo | Blendshape |
|---|---|---|---|---|
| `aa` | `Aa` | | `CH`, `SS`, `TH`, `DD`, `FF` | `Ih` |
| `E` | `Ee` | | `kk`, `nn`, `RR` | `Ee` |
| `ih` | `Ih` | | `sil`, `PP` | (ninguno: boca cerrada) |
| `oh` | `Oh` | | | |
| `ou` | `Ou` | | | |

La apertura de boca del respaldo por envolvente usa `Aa`, y el parpadeo `Blink_L`
y `Blink_R`.

### Cómo se sincronizan con el audio

`AudioStreamPlayer` lleva la cuenta de cuántas muestras de cada frase se han
reproducido de verdad. `CurrentUtteranceTime` es ese número dividido entre la
tasa de salida, así que es el tiempo real de la frase que suena, no el tiempo
del reloj. Si el buffer se queda corto y hay que rellenar con silencio, el
tiempo **no** avanza y los visemas se esperan con el audio. `LipSyncController`
usa ese par (frase, tiempo) para elegir el visema activo.

Si la boca va adelantada o atrasada respecto a la voz, ajustar **Time Offset
Seconds** en `LipSyncController`. Valores negativos adelantan la boca.

## 8. Ajustes de audio

En **Edit > Project Settings > Audio**:

- **DSP Buffer Size**: `Best latency`. Ahora mismo el proyecto tiene 1024
  muestras (`Best performance`), que añade unos 21 ms de retardo a 48 kHz.
  Bajarlo a `Best latency` (256) recorta ese retardo, que se nota al interrumpir
  a Sonia. Si aparecen cortes en el audio en la máquina del stand, subir un
  escalón.
- **Sample Rate**: dejar en automático. El reproductor remuestrea desde los
  24 kHz que anuncia el orquestador en `hello` hasta la tasa de salida.
- **Default Speaker Mode**: `Stereo` va bien; el audio de Sonia es mono y se
  escribe en todos los canales.

## 9. Probar

1. Levantar el orquestador desde `server/`:

   ```bash
   uv run sonia chat
   ```

   `sonia chat` no necesita micrófono ni cámara: se escribe en la consola y el
   pipeline hace el resto. Para la demo completa, `uv run sonia run`.
2. Poner la Game view en **9:16 Portrait** (ver la sección 3). Sin eso el
   encuadre se ve mal y los subtítulos quedan fuera de sitio.
3. Darle a **Play** en Unity. El HUD de arriba a la izquierda debe pasar de
   "Sin conexión" a "Conectado a ws://127.0.0.1:8765".
4. Escribir en el campo de texto del HUD y pulsar **Enter**: eso envía un
   `text_input`, que el orquestador procesa igual que un turno hablado.
5. Teclas del HUD:

   | Tecla | Qué hace |
   |---|---|
   | F1 | Muestra y esconde el HUD |
   | Escape | Envía `interrupt`: Sonia se calla |
   | Enter | Envía el texto escrito |

6. Para ver el detalle de cada mensaje, marcar **Verbose Log** en `SoniaClient`
   o **Log Events** en `SoniaBootstrap`.

Si Unity no conecta, comprobar que el orquestador está escuchando en el puerto
(`WS_HOST` y `WS_PORT` del `.env`). El cliente reintenta solo, con una espera
que va de 1 a 10 segundos, así que se puede arrancar en cualquier orden.

## 10. Cámara desde Unity

Solo hace falta con `VISION_SOURCE=unity` en el `.env`. Por defecto
(`VISION_SOURCE=opencv`) el orquestador abre la cámara él mismo y el componente
`WebcamFrameSender` se queda desactivado.

Para usarlo: activar el componente en el objeto `Sonia`, opcionalmente escribir
el nombre del dispositivo, y dejar `Periodic Send Seconds` en 0 para enviar solo
cuando el orquestador lo pida con `request_frame`.

## 11. Build para el stand

1. Ejecutar **Sonia > Configurar build 9:16** si no se hizo ya al crear la
   escena. Deja resolución, pantalla completa y segundo plano como toca.
2. **File > Build Profiles** (o Build Settings), plataforma Windows/macOS/Linux
   según la máquina del stand. Añadir la escena a la lista.
3. **Quality**: perfil con VSync activado para no quemar GPU con frames de más.
   `SoniaBootstrap` fija `Application.targetFrameRate = 60`.
4. En `SoniaBootstrap`, dejar `Show Cursor` desmarcado para el stand.
5. Girar el monitor a vertical en el sistema operativo antes de lanzar la build.
   Si el escritorio está en horizontal, la ventana en pantalla completa saldrá
   apaisada y con bandas negras.
6. Construir fuera del repositorio: las builds no se suben (ver `.gitignore`).

Los detalles de montaje físico, arranque automático y checklist del día están en
[`stand.md`](stand.md).

## 12. Licencias de los assets

El proyecto es sin ánimo de lucro y de uso personal, así que de momento no se
lleva un registro detallado. Mixamo, VRoid Studio, UniVRM y los modelos de
muestra como AliciaSolid son gratuitos para este uso personal y sin ánimo de
lucro. Si algún día la demo se distribuye o se usa comercialmente, hay que
releer sus condiciones y anotarlas en [`licencias.md`](licencias.md).

## 13. Unity MCP

El proyecto incluye `com.unity.ai.assistant`, que trae el servidor MCP de Unity.
Sirve para que Claude Code lea la consola del editor, inspeccione la escena y
ejecute menús sin salir de la terminal.

Para autorizarlo:

1. Con el editor abierto: **Edit > Project Settings > AI > Unity MCP Server**.
2. En la lista de clientes aparece Claude Code. Pulsar **Configure** o
   **Approve** para que el editor escriba la entrada del servidor en la
   configuración MCP del cliente.
3. En Claude Code, recargar los plugins o reiniciar la sesión para que aparezcan
   las herramientas `mcp__unity-mcp__*`.
4. El editor tiene que estar abierto y con el proyecto cargado: el servidor MCP
   vive dentro del editor.

Con eso, un error de compilación se puede leer y corregir sin copiar y pegar la
consola a mano.

## Resumen de los scripts

Todos en `unity/Assets/Scripts/Sonia/`, namespace `Sonia`.

| Script | Qué hace |
|---|---|
| `Protocol.cs` | Espejo en C# de `docs/protocolo.md`: constantes, clases de mensaje, decodificador del frame binario y constructores de los mensajes salientes |
| `SoniaClient.cs` | WebSocket con reconexión automática. Recibe en un hilo de fondo, despacha eventos en el hilo principal |
| `AudioStreamPlayer.cs` | Buffer circular de PCM, remuestreo lineal, contabilidad por frase y aviso de `playback_done` |
| `LipSyncController.cs` | Visemas sobre blendshapes: del orquestador, de los fonemas en tiempo real o de la envolvente/RMS; escala 0-1 o 0-100 según la malla |
| `PhonemeLipSyncBridge.cs` | Alimenta uLipSync con el audio en streaming y traduce sus fonemas (A/I/U/E/O) a visemas |
| `AvatarStateController.cs` | Estado, mirada de la cabeza (con vaivén y asentimientos al hablar) y parpadeo |
| `EyeGazeController.cs` | Huesos de los ojos: fijación, sacadas, vistazos, microtemblor; más vivo en bailes |
| `SoniaAnimations.cs` | Catálogo de clips por estado y gestos de atención con su categoría; carpetas y rutas |
| `SoniaMotionSet.cs` | ScriptableObject con los clips ya resueltos, generado por el menú |
| `MotionPlayer.cs` | Reproductor de clips con la Playables API: fundidos por código, capa de cuerpo y capa de torso con máscara |
| `AvatarChoreographer.cs` | Decide qué clip suena en cada estado: idle con variaciones y atención, escuchar con asentimientos, pensar, hablar encadenando gestos, saludo |
| `CameraFramingController.cs` | Abre el plano de la cámara durante los bailes y el saludo, y vuelve al plano medio |
| `ImagePanelController.cs` | Decodifica el base64 de `show_image` y lo muestra con animación de escala |
| `WebcamFrameSender.cs` | Captura de `WebCamTexture` y envío en JPEG cuando llega `request_frame` |
| `SoniaDebugUI.cs` | HUD de conexión, subtítulos, entrada de texto y botón de interrumpir |
| `SoniaBootstrap.cs` | Enlaza todo y aplica los ajustes de kiosco |
| `Editor/SoniaSceneSetup.cs` | Menús **Sonia > Crear escena base**, **Configurar build 9:16** y **Actualizar componentes** |
| `Editor/SoniaMotionSetBuilder.cs` | Menú **Sonia > Crear set de animaciones**: importa los FBX, rellena el set, genera la máscara y cablea la escena |
| `Editor/SoniaStageLighting.cs` | Menú **Sonia > Iluminación de estudio**: tres puntos de luz, halo, motas, Volume y SMAA |
| `Editor/SoniaAvatarSetup.cs` | Menús **Sonia > Colocar avatar** y **Elegir avatar (VRM o GLB)**: instancia el modelo, detecta sus blendshapes, rellena las referencias y ajusta cámara y panel |
| `Editor/SoniaHumanoidRig.cs` | Construye y guarda un Avatar Humanoid para modelos con esqueleto de Mixamo que llegan sin él (GLB de Ready Player Me) |
| `Editor/SoniaCapture.cs` | Menú **Sonia > Captura vertical 9:16**: PNG 1080x1920 de la cámara principal |
| `Editor/SoniaBrandAssets.cs` | Rutas y ajustes de importación de los assets de marca de Sonnet Code |
