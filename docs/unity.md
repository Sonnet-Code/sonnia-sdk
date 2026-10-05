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

### Compilar la app

**Sonia > Build macOS** (o **Build Windows**) aplica los ajustes de arriba,
añade la descripción de uso de cámara y micrófono que exige macOS (sin ella el
build falla porque `WebcamFrameSender` usa `WebCamTexture`) y deja el
resultado en `unity/Build/<plataforma>/` (ignorado por git) junto a un
`build-report.txt` con el resumen. Sin abrir el editor:

```bash
/Applications/Unity/Hub/Editor/6000.6.0f1/Unity.app/Contents/MacOS/Unity \
  -batchmode -quit -projectPath unity \
  -executeMethod Sonia.EditorTools.SoniaBuild.BuildMac -logFile build.log
```

El primer build compila todas las variantes de shaders de URP (unos 7 minutos
en un MacBook Pro M-series); los siguientes salen de la caché en 2 minutos.
Batch mode necesita que el editor esté cerrado sobre ese proyecto.

Para probarla en ventana y no a pantalla completa, y para verificarla sin
editor, la app admite estos argumentos:

```bash
unity/Build/macOS/Sonia.app/Contents/MacOS/Sonia \
  -screen-fullscreen 0 -screen-width 540 -screen-height 960 \
  -capture-dir /tmp/capturas -capture-every 5 -logFile player.log
```

`-capture-dir` guarda un PNG de la pantalla cada `-capture-every` segundos
(`ScreenshotService`); sin ese argumento no se instala y no cuesta nada.
Pendiente: el log del build avisa de que el shader de post-procesado
(`PaniniProjection`) se recorta y URP desactiva entonces todos los pases de
post-procesado en la app, así que el Volume (ACES, bloom) solo se ve en el editor.

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
- **Colores.** El fondo de la escena ya usa el color corporativo (cámara en `#1B1F2A`, telón con degradado de `#2A3142` a `#12151C`), puesto por **Sonia > Recalcular encuadre (con el doble)** (sección 6b, "Fondo y luz"). Para cambiar el tono, editar `CameraBackground`, `BackdropTop` y `BackdropBottom` en `Editor/SoniaAvatarSetup.cs` y volver a ejecutar ese menú.

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
`Assets/Avatar/Yae.vrm` y `Snb.vrm`. De dónde salió, qué otros personajes se
evaluaron y hasta dónde se puede personalizar la ropa: `docs/avatares.md`.
Las animaciones son la biblioteca de
Ready Player Me (`Assets/Animations/RPM/`, hecha para este esqueleto: 10 idles
femeninos, 6 clips de hablar femeninos y 10 masculinos, 1 baile) más los FBX de
Mixamo (`Assets/Animations/Mixamo/`) para bailes, pensar, asentir y gestos de
atención. Para hablar solo se usan los de Ready Player Me: ver "Manos y dedos".
Todo el montaje está automatizado en menús pensados para poder ejecutarse las
veces que haga falta sin acumular basura:

| Menú | Qué hace |
|---|---|
| **Sonia > Elegir avatar (VRM o GLB)** | Recuerda qué modelo (`.vrm`, `.glb`, `.gltf` o `.fbx`) se va a colocar (se guarda en EditorPrefs) |
| **Sonia > Crear set de animaciones** | Reimporta los FBX de `RPM/` y `Mixamo/` (Humanoid, sin compresión, bucle solo en los bucles base, centrados), rellena `Assets/Animations/SoniaMotionSet.asset` desde `SoniaAnimations.cs`, genera la máscara de torso y cablea `MotionPlayer` y `AvatarChoreographer` |
| **Sonia > Regenerar Avatar Humanoid** | Reconstruye `Assets/Avatar/Generated/<modelo>_Humanoid.asset` desde el modelo colocado (tras cambiar el mapeo o los límites de `SoniaHumanoidRig`) y lo reasigna al Animator |
| **Sonia > Iluminación de estudio** | Monta o actualiza key, fill, rim y hair light, el halo, las motas, el Volume (ACES, bloom, viñeta, color, profundidad de campo) y SMAA |
| **Sonia > Iluminación estilo Genies** | Opcional: la luz de la demo Mia de genies.com (key frontal cálida, ambiente SH del HDR de Mia, rims en espacio de vista, reflejos del HDR, LUT con Tonemapping None y sombra en el suelo). No es la de por defecto: con la piel de Sonia sale naranja (ver `Assets/Sonia/Lighting/LEEME.md`). Se deshace con **Iluminación de estudio** |
| **Sonia > Actualizar componentes** | Añade al objeto `Sonia` de una escena ya creada los componentes que le falten y recablea `SoniaBootstrap` |
| **Sonia > Colocar avatar** | Rehace el sitio del avatar de Sonia, sin ningún avatar a la vista: el ancla vacía «Avatar» (donde se pone en Play el avatar del SDK) y el doble Sticker desactivado (último recurso), y recablea el pipeline. No toca la cámara, el panel ni la luz (ver "El avatar de Genies en Play") |
| **Sonia > Captura vertical 9:16** | Guarda un PNG 1080x1920 de la cámara principal en `unity/Temp`, con el HUD compuesto encima (`SoniaCapture.Render` renderiza aparte la cámara superpuesta del HUD, porque fuera del bucle de juego URP no dibuja la pila) |
| **Sonia > Montar invitado (Modo Jean)** | Monta (o pone al día) la raíz `Invitado` de la escena del stand: la misma pila de Sonia para el avatar de Jean (voz y lip-sync con el perfil masculino de uLipSync, cara, cabeza, clips, presencia sin letrero que sale por la izquierda, cargador de Genies con el rol `Guest`), más `HandshakeRig`, `ChoreographerBody` y `GuestPresenter`. Su posición es la marca de Jean, 0,45 m a la izquierda de Sonia. En modo edición no lleva avatar, solo un ancla vacía: el de Jean se carga vivo del SDK al entrar en Play (ver `docs/modo-jean.md`) |
| **Sonia > Comprobar Modo Jean (en Play)** | Recorre la entrada, el apretón de manos, la voz de prueba (`Temp/guestcheck/voz.wav`) y la salida a paso fijo, y deja capturas 9:16, vistas de las manos e informe en `Temp/guestcheck/` |
| **Sonia > Recalcular encuadre (con el doble)** | Mide el doble Sticker (encendido solo mientras mide) y rehace cámara, planos abierto y de panel, panel de imágenes, telón e iluminación de estudio |

El HUD (`SoniaHUD`, Screen Space - Camera) se dibuja con `HudCamera`, una
cámara superpuesta hija de la principal (URP camera stacking) que solo ve la
capa UI y no lleva postprocesado: con la principal, el tonemapping, la viñeta y
la profundidad de campo oscurecían el logo de la esquina y lavaban el texto. Los
subtítulos son dos burbujas apiladas sobre la fila de texto (`Debug/Subtitles`):
la del visitante, pequeña y gris con la etiqueta "TÚ", y la de Sonia, grande y
blanca con "SONIA" en el azul de la marca; cada una crece con su texto y se
oculta vacía. El texto de Sonia aparece con su primer chunk de audio, no con
`speech_start`.

**Imágenes** (`show_image`): el panel es un elemento de pantalla, no un objeto
que siga al personaje. Al llegar la imagen, Sonia levanta la mano y señala con
el índice (`Point_ThisGuy` en una capa solo del brazo derecho,
`MotionPlayer.RightArmLayer`, congelado en su punto álgido con
`Handle.SetSpeed(0)` mientras dura la imagen; el torso, la cabeza y el otro
brazo siguen el bucle base del estado, y mientras presenta no hay variaciones
de reposo, gestos de atención, asentimientos ni gestos de habla: quieta y
atenta); la imagen aparece cuando la mano
llega arriba (señal real del coreógrafo, `IsPresentHolding`), en una franja fija
de la parte alta de la pantalla (`ImagePanelController.PlaceOnScreen`: margen
superior del 12 % para no chocar con el logo ni con los botones, hasta el 70 %
del ancho y el 22 % del alto), y la cámara se echa un poco atrás y sube
(`CameraFramingController.panelShotOffset`, 0,13 m y 0,45 m) para que no la
tape; el panel se recoloca cada frame durante ese movimiento. Está en la capa
UI: lo dibuja la cámara del HUD, sin postprocesado, con el pie dentro del panel.
El orquestador retira la imagen sola a los `IMAGE_AUTO_HIDE_SECONDS` (30) si el
modelo no lo hace antes.

Un montaje desde cero se hace en ese orden. Cualquier comprobación de encuadre
se mira con la captura vertical: las capturas normales del editor salen en 16:9
y engañan, porque en 9:16 se ve mucho menos a lo ancho.

### El avatar de Genies en Play

El SDK de Genies solo monta el avatar en Play (sesión, descargas y montaje
nativo), así que **en modo edición no se ve ningún avatar**. La escena guarda
bajo el objeto `Sonia` un ancla vacía («Avatar», sin malla ni Animator, girada
180 grados) que dice dónde y de cara a dónde va. Al entrar en Play,
`GeniesAvatarLoader` carga del SDK el avatar vivo lejos de la cámara y, cuando
está completo, `AvatarBinder` lo pone en el sitio del ancla y la apaga; hasta
entonces se ve el escenario sin nadie. Tarda poco si el avatar ya está en la
caché del SDK; la primera vez, lo que tarden las descargas. Al aparecer, y tras
cada cambio de avatar, Sonia saluda con la mano si está en reposo o escuchando
(`greetOnAppear`; no en modo debug ni con el saludo desactivado en el panel).

**Qué avatar lleva Sonia.** Lo decide el orquestador con el mensaje fijo
`set_avatar` (`{"definition": "<json>"}` con el personaje guardado en la nube
desde el editor de personaje, o `null` para el de la app,
`SoniaGeniesAvatar.json`). Hasta que llega, Sonia arranca con el último que
llegó en otra sesión, que se recuerda en `persistentDataPath/sonia-avatar.json`
(`null` borra el archivo), y si nunca llegó ninguno, con el de la app. Un cambio
se carga mientras Sonia sigue con el que tenía; `AvatarBinder` lo cambia en un
solo fotograma y se libera el anterior. Las cargas van en fila: si llegan dos
`set_avatar` seguidos, gana el último. Con el editor de personaje en pantalla
(`AvatarEditorSession.IsOpen`) el cambio espera a que se cierre.
`AvatarEditorSession.CurrentDefinition` siempre tiene la definición que lleva
Sonia (o, antes de que llegue, la que se está poniendo), y el editor de
personaje arranca con ella. Las definiciones se comparan por huella
(`GeniesDefinition.Hash`, FNV-1a de 64 bits) sin contar espacios ni saltos de
línea fuera de las cadenas: da igual que el JSON venga sangrado, compacto o con
CRLF.

**Último recurso: el doble.** Fuera de la jerarquía de Sonia, la escena guarda
desactivado el doble Sticker (objeto raíz «Sonia (doble)», del Genies Avatar
Starter Pack, mismo esqueleto y misma cara FACS). Si el SDK todavía no ha
entregado ningún avatar tras dos intentos fallidos (`standInAfterFailures`) o a
los 60 s de arrancar (`standInAfterSeconds`), el cargador lo engancha en el sitio
del ancla y sigue reintentando; cuando llega el avatar del SDK, lo sustituye.
Con el editor de personaje abierto no se pone. Es lo que se verá sin red si el
SDK no consigue montar el avatar desde su caché (sin probar sin red: la sesión de
Genies la necesita). Va fuera de la jerarquía de Sonia a propósito: varios
componentes buscan un Animator o mallas entre sus hijos si no tienen uno
asignado, y no deben quedarse con el doble apagado.

**En el editor de Unity, `SoniaGeniesAvatar.json` sigue al último avatar de
Sonia** (`Editor/SoniaGeniesDefinitionSync.cs`). Cuando en Play se pone un avatar
del SDK, su definición se escribe en el archivo de definición del cargador,
sangrada para leer bien los cambios en git. Consecuencia: en el editor, el
personaje de la app (el de `set_avatar null` y el de las builds) es siempre el
último que llevó Sonia, y `reset_avatar` no vuelve a uno anterior. El invitado
del Modo Jean no se toca. En una build no se escribe nada.

**Menús.** **Sonia > Colocar avatar** rehace el ancla y el doble desactivado y
recablea el pipeline sin avatar (Animator, cabeza, ojos y cara vacíos hasta
Play); no toca la cámara, el panel ni la luz. **Sonia > Recalcular encuadre (con
el doble)** enciende el doble un momento, lo mide y rehace cámara, planos
abierto y de panel, panel de imágenes, telón y luz. El encuadre guardado
(cámara en (0; 1,201; −1,363), FOV 40) se ajustó con el avatar del SDK; el doble
mide algo distinto, así que recalcularlo cambia un poco el plano.

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

**Excepción: los bucles de reposo** (`SoniaAnimations.KeepsHorizontalMotionInPose`:
reposo, escuchar y pensar) llevan el avance XZ **dentro de la pose**. En un
reposo ese avance es el traspaso de peso de un pie a otro; extraído y
descartado, la cadera se quedaba clavada y en su lugar patinaban los pies
(`DefaultIdle`: 0,6 cm de vaivén con los pies resbalando 1,8 cm, frente a
3,2 cm con los pies quietos). El paseo del modo Fuera (`Walk`) sigue
extrayéndolo, porque `PresenceController` lee ese avance. Hoy suenan
`DefaultIdle` en reposo, al hablar y al pensar, e `idles-0024-basicIdle` (más
contenido) al escuchar; `StillPose`, la pose congelada, ya no se usa. La
comparación de reposos, y por qué no se usa el motor de comportamiento nativo
de Genies, está en `docs/informe-reposo-genies.md`; la herramienta para medir
y fotografiar reposos es `SoniaIdleCheck` (en Play y en pausa, desde el MCP).

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
| idle | bucle base; con el stand en calma (`attentionQuietDelay`, 25 s en idle sin conversación: entre turnos el estado también es idle) un gesto de atención (baile, cuarta pared o suave) cada 10-20 s, repartidos 45/30/25 % sin repetir, y las variaciones de reposo |
| listening, thinking, speaking | con `singleConversationLoop` (por defecto) un solo reposo largo: el bucle de idle sigue sin reiniciarse ni cambiar de clip, sin variaciones, asentimientos de clip ni gesticulación, como Mia en genies.com. Apagado: cada estado con su bucle, asentimientos (fundido 0,3 s), variaciones de pensar y clips de habla encadenados |
| saludo | `PlayGreeting()` al primer listening tras 25 s sola (y 20 s entre saludos); se deja terminar salvo que toque pensar o hablar |

Los gestos (atención, saludo, variaciones) entran y salen en `gestureFade`
(0,8 s) y `MotionPlayer` pasa el peso de cada fundido por una curva suave
(smoothstep, `smoothFades`), como Genies; el de presentar imagen va en
`presentFade` (0,5 s). `AvatarStateController.SetIdleTuning(respiración,
acentos, velocidad)` cambia en vivo la respiración, los acentos al hablar y la
velocidad del reposo (`AvatarChoreographer.SetLoopSpeed`), 1 = tal cual.

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
agachada, queda mal en plano medio), `IdleLooking2` como idle (gira el cuerpo
de perfil demasiado tiempo; se usa como gesto suave de atención, una sola vez),
`Wave2` (el FBX trae 16 fotogramas, medio segundo: un tic; el saludo con la
mano es `Greeting`) y `Point_Forward` (la mano tapa la cara casi todo el clip
en el plano de la demo).

### Manos y dedos

Los clips de habla de Mixamo (`Talking1-5`, `Speaking`, `Speaking2`,
`Speaking3`) se retiraron del set tras revisarlos mano a mano con primeros
planos: ponían los dedos en garra (hiperextendidos hacia atrás) y, como están
hechos para un cuerpo más estrecho, hundían las manos en la cintura y en los
muslos de Babe. Para hablar solo se usan clips de Ready Player Me:
`F_Talking_Variations_001, 002, 003, 005, 006` y `M_Talking_Variations_006,
007, 009, 010`. Los masculinos están hechos para el mismo esqueleto y
retargetean limpios sobre Babe. Se descartan `F_004` (las manos atraviesan el
suéter al posarse en el pecho), `M_001-004, 008` (manos caídas casi todo el
clip, rozando las caderas) y `M_005` (gira el cuerpo 34° y la cabeza 52°, como
si hablara con otra persona).

Se probó y se descartó recortar el "estirado" positivo de los dedos en los
límites musculares del Avatar (`SoniaHumanoidRig.LimitFor`): Unity no recorta
sino que reescala el valor normalizado del clip al rango del destino, así que
con el rango reducido las manos abiertas de Mixamo (saludar, señalar, pulgar
arriba) salían medio cerradas. Los límites se quedan en los de Unity. Si en el
futuro hiciera falta un tope de verdad, sería un `HumanPoseHandler` en
`LateUpdate` que recorte los músculos de los dedos, no los límites del Avatar.
El menú **Sonia > Regenerar Avatar Humanoid** reconstruye el Avatar cuando se
toca `SoniaHumanoidRig`.

**Pose de exportación del GLB.** `SoniaHumanoidRig` construye el Avatar
Humanoid a partir de la pose de los nodos tal como vienen en el archivo. Babe
se exporta en T-pose y todo cuadra; un modelo exportado en A-pose (brazos a
unos 55° hacia abajo, como Zoe 1) hace que el retargeting de los clips de Ready
Player Me pliegue los brazos dentro del torso hasta desaparecer. Se nota en los
bounds del `SkinnedMeshRenderer` (unos 0,23 m de ancho plegado frente a 0,52 m
con los brazos extendidos). Antes de culpar a los clips, comprobar la pose de
reposo del GLB; `scripts/injerto_glb.py` iguala la del receptor a la del
donante al injertar cabezas.

Queda una limitación conocida: con los brazos caídos, los dedos rozan las
caderas de Babe en cualquier clip. En el encuadre de cintura para arriba no se
ve; si algún día se abre el plano, habría que añadir una separación de brazos
por script o cambiar el cuerpo del avatar.

Para revisar manos, las capturas en modo edición con un `PlayableGraph` tienen
una trampa: el `SkinnedMeshRenderer` renderiza con las matrices del tick
anterior, así que la imagen va una pose por detrás de los huesos. Con
`forceMatrixRecalculationPerRender = true` durante la captura la malla sigue a
los huesos en el mismo comando.

### Cara: lip-sync, ojos, parpadeo y cabeza

- **Lip-sync** (`LipSyncController`): tres fuentes por orden de preferencia.
  Primero **fonemas en tiempo real** con uLipSync (MIT, MFCC) a través de
  `PhonemeLipSyncBridge`, que le pasa cada bloque de audio de
  `AudioStreamPlayer` (evento `OnAudioFrame`) y traduce A/I/U/E/O a
  `viseme_aa/I/U/E/O` escalados por el volumen con una curva suave (abre un
  poco con voz floja, nunca del todo); si no hay analizador
  (`preferRealtimePhonemes` apagado o sin perfil), los visemas con timestamp
  del mensaje `visemes`, que el orquestador ya no envía (con GPT-Live no hay
  tiempos por fonema); y si tampoco, envolvente o RMS del audio. Suavizado con
  ataque 28/s y caída 11/s, peso máximo 65 %. Con el motor en cascada anterior
  los visemas del orquestador (una estimación por texto) tuvieron prioridad y,
  como llegaban al terminar la síntesis, la boca se desincronizaba, sobre todo
  en la cola: seguía moviéndose unos 400 ms después de la voz.
- **Sincronía boca-voz** (`AudioStreamPlayer.lipSyncLeadMs`, 60 ms): el
  análisis de fonemas ve el audio fresco y la salida real sale por una línea
  de retardo de 60 ms. Medido con la voz del motor anterior: la boca iba 75 ms por
  detrás del bloque generado (ventana de 64 ms de uLipSync, un frame de espera
  del job y el suavizado), unos 40-50 ms tarde respecto al altavoz, que es
  justo el rango en que el oído nota que el audio va por delante. Con el
  adelanto la boca cae a la par o unos milisegundos antes, que pasa
  desapercibido. Importante: el componente uLipSync vive en el objeto hijo
  `Fonemas`, sin AudioSource; en el raíz Unity le pasaría además por su propio
  `OnAudioFilterRead` la salida ya retardada y analizaría una mezcla.
- **Arranque de "hablando"** (`SoniaBootstrap.waitAudioBeforeSpeaking`): Sonia
  se queda en "pensando" y aplica el estado `speaking` y la gesticulación con
  el primer chunk de audio de esa frase (tope de 2,5 s por si el audio no
  llega). Con GPT-Live el orquestador ya manda `speech_start` y `speaking` con
  el primer audio con voz, así que la espera es casi nula; con el motor en
  cascada anterior la voz tardaba entre 0,3 y 1,5 s en llegar tras
  `speech_start`. Las frases ambientales del stand no cambian de estado y no
  pasan por aquí.
- **Escala de blendshapes**: los GLB de glTFast definen los blendshapes de 0 a 1
  y los FBX/VRM de 0 a 100. `LipSyncController.BlendShapeScale` lee el peso del
  frame y se escribe siempre en la escala de la malla; sin esto la cara de Babe
  se estiraba hasta el pecho.
- **Ojos** (`EyeGazeController`): los huesos `LeftEye`/`RightEye` no van en el
  rig humanoide (el retargeting los dejaba bizcos). Cada ojo apunta al
  visitante (o al panel, o a donde mande una mirada impuesta) desde su
  posición, con el punto de enfoque alejado a 2,5 m como mínimo y **ganancia
  0,65** (con ojos grandes estilizados, compensar toda la rotación de la cabeza
  lee como mirar de reojo). Sobre eso, **fijaciones por estado** con las
  plantillas de atención de Genies medidas en Mia (`docs/informe-mia.md`):
  hablando, fija en el visitante con microsacadas; escuchando, al visitante
  unos 6 s y un vistazo de 1,5-3 s hasta ±11° a un lado (medido: 83 % del
  tiempo al visitante; Mia mira menos, el 37 %, pero en el stand se leía como
  no hacer caso a quien habla);
  pensando, unos 20 por minuto arriba y a un lado; con el stand en calma, unos
  17 por minuto, amplios y a menudo abajo. Un cambio de fijación de más de 4°
  parpadea el 70 % de las veces. Límites de 16° de guiñada y 11° de cabeceo
  por ojo, aplicados a los dos por igual (si uno toca el tope, el otro se
  corrige lo mismo y no cambia la vergencia), desvío total acotado a 14°,
  microsacadas de hasta 2,5° y microtemblor. Durante bailes y gestos grandes
  las microsacadas son un 60 % más vivas.
- **Cabeza** (`AvatarStateController`): sigue al visitante solo en parte
  (`headFollow` 0,3 en reposo y al pensar; 0,5 al escuchar y al hablar; 0,3 en
  bailes): la mueve sobre todo el reposo y los ojos hacen el resto, como Mia.
  `DefaultIdle` gira bastante la cabeza (unos 18° de lado a lado con 0,3;
  12,6° con 0,5), por eso en conversación sigue más. Hasta 40°, con vaivén lento de
  1,4° (ruido Perlin, escalado por el seguimiento). Escuchando, ladeada 6°,
  el torso 2° hacia delante y asentimientos lentos (muelle de 1,4 Hz) cada 4-8
  s; pensando, sube 4° y se ladea mientras los ojos van arriba y a un lado. El
  desvío se calcula y suaviza **en el espacio local de la cabeza**: si se
  suavizara en el mundo, al girar el cuerpo deprisa la cabeza se quedaría
  clavada mirando al sitio antiguo (pasó con un baile).
- **Cuerpo vivo** (`AvatarStateController`): **respiración aditiva** continua,
  también al hablar (una inspiración cada 5 s con un 12 % de azar para que no
  case con el bucle del reposo, pecho ±1,1° y hombros 0,6°, valores de Mia) y
  **acentos al hablar** como el énfasis de Genies: en las sílabas tónicas, una
  cascada de 0,85 s (preparación hacia atrás; columna, pecho, cuello, cabeza y
  brazos, cada uno un poco después) con `accentScale` 0,6 de los grados de
  Genies. Se escriben en los huesos humanoides después del Animator; si el
  Animator no escribe un fotograma, se parte de la pose guardada y el giro no
  se acumula.
- **Parpadeo** (`AvatarStateController`): 0,38 s (cierra en un tercio, rápido,
  y abre en dos, despacio), cada 3-5 s más los de la voz y los cambios de
  mirada (unos 20 por minuto), dobles en un 18 %, los ojos desfasados unos
  milisegundos y las cejas que bajan un poco. Antes, 0,14 s cada 2,5-6 s.
- **Expresiones** (`FacialExpressionController`): sobre los blendshapes ARKit,
  una **sonrisa de base constante** (`baseSmile` 0,35, media al pensar; Mia
  lleva siempre su emoción "Happy") con cejas algo arriba, cejas que suben en
  cada acento de la voz (el mismo instante que la cascada del cuerpo,
  `AvatarStateController.OnEmphasis`) y un levantamiento breve al empezar a
  escuchar o hablar, ceño al pensar, mejillas, párpados que se entornan al
  sonreír y al hablar fuerte y se abren en los énfasis, y un vaivén aleatorio
  permanente. No toca visemas, mandíbula ni parpadeo, así que no se pisa con el
  lip-sync; con la boca redonda la sonrisa baja sola.
- **Boca al callarse** (`LipSyncController.closeSeconds`): si ya no hay voz
  ahora ni en los 60 ms siguientes, lo que queda abierto se cierra en 1 s con
  una curva que frena al final (casi todo el cierre en los primeros 0,4 s), el
  MouthCloser de Genies; en una interrupción, igual en 0,25 s. **Ganancias de
  lip-sync de Genies** (`FaceRig.lipShapeGains`): en los visemas, embudo ×0,5,
  pucker ×0,75, `LIPS_TOWARD` ×0,4 y `CHIN_RAISER_T` ×0,3, que Genies aplica a
  su propio lip-sync porque las o, las u y los cierres salían exagerados.
- **Panel de ajuste** (`SoniaTuningUI`): el botón **Ajustes** arriba a la
  derecha (o F2) abre en la mitad inferior de la pantalla deslizadores para los
  parámetros de ojos, cabeza, expresiones, boca y fonemas, leídos de los
  componentes en vivo. **Guardar** escribe `sonia-tuning.json` en
  `Application.persistentDataPath` y se aplica al arrancar; **Imprimir** saca
  los valores por consola para pasarlos a la escena; **Restablecer** vuelve a
  los valores de la escena y borra el archivo. Sobrevive a recompilaciones en
  Play (reconstruye el panel si pierde las referencias). El cursor del ratón
  está visible (`showCursor` en `SoniaBootstrap`).
- **Clips que giran el cuerpo**: se midió el giro máximo de caderas de cada
  clip evaluándolo con un `PlayableGraph` en edición; los bailes de Ready
  Player Me 001/004/005/007 y `Dance_House` giran de 87° a 179° (dan la espalda
  al visitante) y la variación de reposo 005 mira 117° hacia atrás: fuera del
  catálogo.

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

## 6c. Modo Fuera: salida y entrada caminando

El panel del stand tiene un modo "Fuera" (`docs/panel.md`). El orquestador lo
manda como `presence` y Unity lo resuelve con `PresenceController` y
`AwaySignController`, que `SoniaBootstrap` añade por código al objeto `Sonia`
si la escena no los trae (no hay que tocar la escena).

**`present: false`.** Se corta la voz y la boca (como `stop_speaking`), se
retira la imagen y el coreógrafo queda suspendido (apunta el estado pero no
lanza variaciones, gestos, bailes ni gestos de habla). Sonia vuelve al reposo y
mira hacia la salida (ojos con parpadeo y cabeza primero); a los 0,5 s gira
hacia ese lado con una curva suave mientras el ciclo de caminar entra fundido,
así los primeros pasos se dan girando y no pivota sobre los pies. Camina hasta
que ningún hueso (más 0,3 m de margen) se ve en ningún encuadre de la cámara;
entonces se apagan sus renderers y aparece el letrero con un fundido.

**`present: true`.** El letrero se va, Sonia entra caminando desde el mismo
lado mirando hacia dónde va, vuelve a mirar al visitante un poco antes de
llegar, frena hasta su marca y se gira hacia la cámara; al terminar, el
coreógrafo recupera el cuerpo (si estaba en reposo, sigue el mismo bucle sin
reiniciarlo) y el primer gesto de atención espera lo de siempre.

**Sin animación.** Un `presence: false` que llega en los 2 s siguientes al
`hello` (el orquestador lo repite a cada cliente nuevo) se aplica de golpe:
Sonia oculta, letrero puesto y cámara ya abierta
(`SoniaBootstrap.presenceInstantWindowSeconds`). Otro `presence` con el mismo
`present` solo cambia el texto. Si cambia de idea a medias (vuelve mientras
sale o se va mientras entra), se da la vuelta desde donde está; el giro pasa
siempre por mirar a cámara, nunca de espaldas.

**Pies.** El ciclo es `F_Walk_002` de la biblioteca de Ready Player Me
(`feminine/fbx/locomotion`, misma licencia que el resto de `RPM/`): trae root
motion hacia delante, 4,40 m en 3,13 s (1,40 m/s), seis pasos de 0,52 s, en
bucle limpio. Mientras camina se enciende `applyRootMotion`, se lee
`Animator.deltaPosition` cada frame y Sonia se desplaza exactamente su
proyección sobre el eje lateral de la cámara; lo que avanza hacia la cámara se
descarta (sigue en su línea, y ese deslizamiento en profundidad no se ve de
frente). Como la proyección depende del giro, la arrancada crece sola. Para
frenar en su marca se sustituye el root motion por una curva de Hermite que
parte de la velocidad medida y llega parada, en el mismo tiempo en que el
caminar se funde al reposo: la velocidad baja lineal a la vez que los pasos se
acortan. Sin clip de caminar (set sin regenerar) o con un clip sin root motion,
se desplaza a una velocidad estimada: desliza, pero no se rompe.

**Cámara.** En el plano medio no se ven las piernas y Sonia sale de cuadro en
un paso, así que mientras sale, está fuera y vuelve, `CameraFramingController`
abre al plano de cuerpo entero (`Wide Shot Position`, o `Presence Shot
Position` si se rellena) con un travelling SmoothDamp que arranca y frena suave
(`presenceSmoothTime` 0,75 s). Empieza a cerrar cuando Sonia empieza a frenar.
Con el plano abierto actual caben 0,78 m a cada lado: el paseo es corto; para
alargarlo, `Presence Shot Position` más atrás.

**Letrero.** En el Canvas del HUD (sale en las capturas y F1 no lo esconde):
tarjeta navy de 900 px con borde y halo en el azul de la marca, "SONIA"
espaciado, el mensaje en blanco y negrita a 80 px (baja hasta 54 px con textos
largos), tres puntos que laten y "Asistente virtual de Sonnet Code". El logo
del HUD ya está arriba a la izquierda y no se repite. Entra subiendo con un
fundido de 0,7 s y sale en 0,45 s.

Todos los parámetros son campos serializados: en `PresenceController` el lado
(`exitSide`, por defecto la derecha de la pantalla), la pausa antes de girar,
la duración del giro, el fundido al caminar, el pie de arranque
(`walkStartNormalizedTime`), la frenada, el margen de fuera de cuadro y la
mirada; en `AwaySignController` textos, tamaños, colores y fundidos; en
`CameraFramingController` el plano de salida.

En la misma tanda: `set_volume` (`AudioStreamPlayer.SetVolume`, 0 a 1,5, en
rampa de un bloque para que no chasquee y con limitador suave por encima de 1;
el lip-sync analiza el audio antes de la ganancia, así que la boca se mueve
igual a cualquier volumen) y `attention` con `category: "greeting"`
(`AvatarChoreographer.PlayGreetingNow`: saludo con la mano ya, en idle o
escuchando y sin imagen puesta).

### Pendiente en el editor (nada de esto se ha probado aún)

1. Abrir el proyecto: Unity importa `Assets/Animations/RPM/F_Walk_002.fbx` y
   crea su `.meta` (subirlo con el FBX).
2. **Sonia > Crear set de animaciones**: lo deja como Humanoid (Create From
   This Model, como el resto de `RPM/`), en bucle, sin compresión, con rotación
   y altura dentro de la pose y la traslación XZ fuera (Center of Mass), y
   rellena `SoniaMotionSet.walk`. La consola debe decir "caminar F_Walk_002".
   En el inspector del clip, Average Velocity con z ≈ 1,4 y los indicadores de
   bucle en verde. Si el retargeting sobre Babe sale raro, probar Avatar
   Definition "Copy From Other Avatar" con
   `Assets/Avatar/Generated/Babe_Humanoid.asset`.
3. Play con la Game view en 9:16. Sin orquestador: panel **Animaciones** >
   **Salir/Volver**, o en un `RunCommand`
   `Object.FindAnyObjectByType<Sonia.PresenceController>().TogglePresence()`
   (`PhaseName` y `Offset` dicen dónde va). Con orquestador: modo "Fuera" del
   panel.
4. Verificación visual, con renders 1080x1920 (**Sonia > Captura vertical 9:16**
   o render a `RenderTexture` desde un `RunCommand`, conduciendo los frames
   con `EditorApplication.Step()`):
   - Salida: al empezar (mira a un lado, cámara abriéndose), a mitad del giro
     (pasos girando, sin pivotar sobre pies plantados), caminando de perfil,
     con el hombro en el borde y con el escenario ya vacío y el letrero
     entrando.
   - Pies sin patinar: durante el apoyo, la posición en mundo de `LeftFoot` o
     `RightFoot` entre frames seguidos debe quedarse quieta (deriva lateral de
     1 o 2 cm como mucho). Si patina, mirar la consola: el aviso "El clip de
     caminar no trae root motion" indica que la importación dejó la traslación
     dentro de la pose.
   - Entrada: letrero yéndose, Sonia entrando por el mismo lado, frenada con
     pasos cada vez más cortos, mirada al visitante antes que el giro del
     cuerpo, giro a cámara y vuelta al idle sin salto; cámara cerrando al plano
     medio.
   - Ojos: sacadas y parpadeos durante el paseo; nada de mirada fija ni
     bizca al girar.
   - Letrero: legible y sin cortes en la captura; probar un mensaje de unos 150
     caracteres y otro con tildes y eñes.
   - Reconexión: con el orquestador en "Fuera", parar y volver a dar a Play:
     Sonia ya oculta, letrero puesto y cámara abierta, sin animación.
   - Cambios de planes: "Volver" a mitad de la salida y "Fuera" a mitad de la
     entrada.
   - `set_volume` 0,3, 1 y 1,5 con Sonia hablando: la boca se mueve igual y no
     hay chasquidos al cambiar. `attention` `greeting` en idle: saluda.
5. Ajustar a ojo si hace falta: `walkStartNormalizedTime` (con qué pie da el
   primer paso), `turnSecondsPer90`, `arriveSeconds`, `exitSide` y la posición
   del plano de salida.

## 7. Mapeo de visemas

El protocolo usa los identificadores del conjunto Oculus (ver
`docs/protocolo.md`). El orquestador ya no envía `visemes`, pero el mapa sigue
en uso: los fonemas de uLipSync se traducen a `aa`, `E`, `ih`, `oh`, `ou` y
`nn` y pasan por él. El mapa por defecto de `LipSyncController` es editable en
el inspector. La columna Oculus sirve para
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

   `sonia chat` no necesita micrófono ni cámara: se escribe en la consola y
   GPT-Live contesta con su voz (abre una sesión y gasta). Para la demo
   completa, `uv run sonia run`.
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
   | Escape | Abre el menú de calidad gráfica (siempre, también sin `-dev-ui`); para callar a Sonia, el botón **Interrumpir** |
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
7. **Calidad gráfica**: Esc en la ventana de Sonia abre un menú con Alta, Media,
   Baja y Personalizada, los FPS medidos y cada opción (resolución con
   reescalado FSR, suavizado, sombras, oclusión ambiental, desenfoque del fondo,
   bloom, partículas y 60 o 30 FPS). Ratón o teclado: ↑↓ fila, ←→ valor, 1-4
   niveles. Alta es la escena tal como está montada; Media y Baja recortan desde
   ahí (`Assets/Scripts/Sonia/Graphics`, ensamblado `Sonia.Graphics`, se crea solo
   al arrancar). Se guarda en PlayerPrefs de cada equipo y se fuerza al arrancar
   con `-quality alta|media|baja|personalizada`. No toca assets en disco: el URP
   asset y el SSAO vuelven a como estaban al salir.

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
| `CameraFramingController.cs` | Abre el plano de la cámara durante los bailes y el saludo, y vuelve al plano medio; travelling a cuerpo entero en el modo Fuera |
| `PresenceController.cs` | Modo Fuera (`presence`): sale caminando con el root motion del ciclo de caminar, se oculta, y vuelve frenando hasta su marca (sección 6c) |
| `AwaySignController.cs` | Letrero del modo Fuera en el Canvas del HUD, construido por código, con fundidos |
| `ImagePanelController.cs` | Decodifica el base64 de `show_image` y lo muestra con animación de escala |
| `WebcamFrameSender.cs` | Captura de `WebCamTexture` y envío en JPEG cuando llega `request_frame` |
| `SoniaDebugUI.cs` | HUD de conexión, subtítulos, entrada de texto y botón de interrumpir |
| `Graphics/GraphicsQuality*.cs` | Calidad gráfica: niveles y opciones, el controlador que los aplica sobre lo montado y el menú de Esc |
| `SoniaBootstrap.cs` | Enlaza todo y aplica los ajustes de kiosco |
| `Editor/SoniaSceneSetup.cs` | Menús **Sonia > Crear escena base**, **Configurar build 9:16** y **Actualizar componentes** |
| `Editor/SoniaMotionSetBuilder.cs` | Menú **Sonia > Crear set de animaciones**: importa los FBX, rellena el set, genera la máscara y cablea la escena |
| `Editor/SoniaStageLighting.cs` | Menú **Sonia > Iluminación de estudio**: tres puntos de luz, halo, motas, Volume y SMAA; también deshace la iluminación estilo Genies |
| `Editor/SoniaGeniesLighting.cs` | Menú **Sonia > Iluminación estilo Genies** (opcional) y su `Remove` |
| `SoniaGeniesLook.cs` | Ambiente SH en modo Custom y rims que giran con la cámara de la iluminación estilo Genies |
| `Editor/SoniaAvatarSetup.cs` | Menús **Sonia > Colocar avatar** (ancla vacía, doble desactivado y cableado sin avatar) y **Recalcular encuadre (con el doble)** (mide el doble y ajusta cámara, panel, telón y luz) |
| `Editor/SoniaGeniesDefinitionSync.cs` | En el editor, escribe en `SoniaGeniesAvatar.json` el último avatar del SDK que lleva Sonia en Play |
| `GeniesDefinition.cs` | Huella de una definición de avatar de Genies, para comparar definiciones sin depender del formato |
| `Editor/SoniaHumanoidRig.cs` | Construye y guarda un Avatar Humanoid para modelos con esqueleto de Mixamo que llegan sin él (GLB de Ready Player Me) |
| `Editor/SoniaCapture.cs` | Menú **Sonia > Captura vertical 9:16**: PNG 1080x1920 de la cámara principal |
| `Editor/SoniaBrandAssets.cs` | Rutas y ajustes de importación de los assets de marca de Sonnet Code |
