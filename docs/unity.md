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
build falla porque `WebcamFrameSender` usa `WebCamTexture`), pone el bundle id
`com.sonnetcode.sonia` y deja el resultado en `unity/Build/<plataforma>/`
(ignorado por git) junto a un `build-report.txt` con el resumen. Después,
`Editor/SoniaPlayerBuildFixes.cs` retoca la app (ver «La app todo en uno» y
«Build de macOS con Genies», abajo). Sin abrir el editor:

```bash
/Applications/Unity/Hub/Editor/6000.6.0f1/Unity.app/Contents/MacOS/Unity \
  -batchmode -quit -projectPath unity \
  -executeMethod Sonia.EditorTools.SoniaBuild.BuildMac -logFile build.log
```

El primer build compila todas las variantes de shaders de URP (unos 7 minutos
en un MacBook Pro M-series); los siguientes salen de la caché en 2 minutos.
Batch mode necesita que el editor esté cerrado sobre ese proyecto.

El icono de la app (macOS y Windows) es `Assets/UI/SoniaAppIcon.png`, el icono
por defecto del Player: la cara de Sonia sobre el navy de la marca. **No se
actualiza solo**: es una imagen fija que entra tal cual en cada build. El avatar
de Genies solo existe en Play, y el aspecto de Sonia lo recibe la app de la nube
al arrancar (se cambia desde el panel sin recompilar). Si cambia el aspecto y se
quiere el icono al día:

1. En el editor, Play y esperar a que Sonia salga con su aspecto nuevo (y a que
   acabe el saludo con la mano, que puede tapar la cara).
2. **Sonia > Icono de la app (en Play)**. Guarda el PNG nuevo.
3. Salir de Play: en ese momento se pone como icono del Player (lo que se
   cambia del Player en Play se pierde, por eso espera).
4. Hacer la build de nuevo. Si Finder sigue enseñando el icono viejo:
   `/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f unity/Build/macOS/Sonnia.app`.

Encuadre y colores están en `Editor/SoniaAppIcon.cs` (`Make`: altura de la cara
sobre el hueso de la cabeza, alto del encuadre y campo de visión).

Para probarla en ventana y no a pantalla completa, y para verificarla sin
editor, la app admite estos argumentos:

```bash
unity/Build/macOS/Sonnia.app/Contents/MacOS/Sonnia \
  -screen-fullscreen 0 -screen-width 540 -screen-height 960 \
  -capture-dir /tmp/capturas -capture-every 5 -logFile player.log
```

`-capture-dir` guarda un PNG de la pantalla cada `-capture-every` segundos
(`ScreenshotService`); sin ese argumento no se instala y no cuesta nada.
`-sin-orquestador` no lanza el orquestador empaquetado (ver abajo).

### La app todo en uno (orquestador dentro)

La app lleva dentro el orquestador de Python congelado con PyInstaller y lo
arranca sola: un doble clic y ya está Sonia entera.

1. `scripts/build_orquestador.sh` congela el orquestador en
   `unity/Build/orquestador/<plataforma>/sonia-orquestador/` (unos 176 MB en
   macOS: Python, dependencias, `assets/` y los estáticos del panel). Hay que
   rehacerlo cuando cambie algo de `server/` o de `assets/`, y hacerlo en cada
   sistema: en macOS sale para macOS y en Windows para Windows.
2. La build lo copia dentro de la app con el `.env` del repo al lado del
   ejecutable (Jean: «los envs deben inyectarse en el build»). Se copia como
   archivo; las builds están en `.gitignore`, así que la clave no llega a git.
   Todas las apps salen en el panel de Cloudflare (Jean: «necesito que todas
   las builds la tengan»): si ese `.env` no da valor a `PANEL_CLOUD_TOKEN`, la
   build no empieza (solo se mira si tiene valor; el valor no se escribe en
   ningún sitio). Sin orquestador congelado la build avisa y la app espera uno
   externo, como antes.
   - macOS: `Sonnia.app/Contents/Resources/orquestador/sonia-orquestador/`
   - Windows: `Sonnia_Data/orquestador/sonia-orquestador/`
3. Al abrir la app, `OrchestratorProcess` lo lanza si nadie escucha en el
   8765 (si ya hay uno, por ejemplo el de desarrollo, manda ese), lo relanza si
   se cae (2, 4, 8… hasta 30 s) y lo cierra al salir (con SIGINT en macOS, que
   cierra la sesión de GPT-Live). Si la app muere de golpe y no llega a
   cerrarlo, el orquestador se cierra solo en unos segundos: recibe el PID de
   la app en `SONIA_PARENT_PID` y lo vigila (`sonia/parent.py`). En el editor
   no se lanza nunca y `-sin-orquestador` lo desactiva.
4. Lo que es de cada equipo va fuera de la app, en `SONIA_HOME`
   (`~/Library/Application Support/Sonia` en macOS, `%APPDATA%\Sonia` en
   Windows): `cache/` (voces grabadas, estado del panel, id de la instancia),
   `overrides.env` (variables cambiadas desde el backoffice, que mandan sobre
   el `.env` empaquetado) y `logs/orquestador-*.log` (los 10 últimos arranques).
   Para no grabar de nuevo las voces, se puede copiar `cache/voice` del repo a
   `SONIA_HOME/cache/voice`.

### Build de macOS con Genies

Genies solo da soporte oficial a Android, iOS y Windows. En macOS la build se
hace igual; `SoniaPlayerBuildFixes` y `SoniaBuild` aplican estas diferencias:

- **Mono en vez de IL2CPP**, solo durante la build de macOS (este Mac no tiene
  el módulo IL2CPP de macOS; con Mono funciona como en el editor). Windows,
  ver «Build de Windows».
- **NAF sin precarga.** El preproceso de Genies (`XcodePostProcess`) marca sus
  siete librerías NAF como «Load on Startup» en macOS. Precargadas, el
  `UnityPluginLoad` de `libgnUnityPlugin` corre antes de que Unity cree el
  dispositivo Metal y tumba la app («Failed to create Metal command queue»), y
  además se cargan en el orden de esa lista y no en el de sus dependencias: NAF
  devolvía vacías las piezas con malla (cuerpo, ropa, pelo), la composición
  salía sin mallas ni esqueleto humanoide y Sonia no aparecía. El preproceso de
  `SoniaPlayerBuildFixes` va después del de Genies y les quita la precarga; se
  cargan al primer uso, como en el editor. Se encontró el 5 de octubre con
  trazas en la build de desarrollo: con la precarga, el cuerpo y la ropa salían
  nulos aunque tuvieran los mismos archivos que en el editor. (Antes había un
  puente nativo, `SoniaNafShim`, que retrasaba el arranque de NAF; arreglaba el
  cierre pero no las piezas vacías y se quitó.)
  **Ojo con el editor:** la precarga es de la build, nunca del editor. El 6 de
  octubre los `.meta` de esas librerías quedaron con `isPreloaded: 1` tras una
  build buena (los importadores decían que no) y el editor no volvía a abrir el
  proyecto: se caía al arrancar con «Failed to create Metal command queue»,
  también en modo batch. Desde entonces `SoniaBuild` llama al acabar cada build,
  salga bien o mal, a `SoniaPlayerBuildFixes.RestoreEditorNafPreload`, que lo
  deja a 0 también en el texto del `.meta`. Si vuelve a pasar con el editor
  cerrado: `sed -i '' 's/^  isPreloaded: 1$/  isPreloaded: 0/'` en
  `Packages/com.genies.avatar-sdk.client/Internal/NAF Plugin/Runtime/Plugins/macOS/*.dylib.meta`.
- **Rutas de Genies.** `libGeniesAuthAPI` y `libGeniesTelemetryBridge` buscan
  `libCommonDeps` en una ruta absoluta del equipo de un desarrollador de
  Genies: el post-proceso les añade la ruta de la app.
- **Cero llavero.** Esas dos librerías guardan los tokens de Genies en el
  llavero de macOS y, con la firma ad hoc, macOS pedía la contraseña una y otra
  vez. El post-proceso cambia su dependencia de `Security.framework` por el
  puente del llavero (`unity/NativeSource/SoniaKeychainShim`): implementa
  `SecItemAdd`, `SecItemCopyMatching`, `SecItemUpdate` y `SecItemDelete` en
  memoria y reexporta el resto de Security. La app no guarda nada en el equipo
  y cada arranque hace un registro anónimo nuevo en Genies (los avisos «Failed
  to retrieve token … -25300» del registro son normales). El puente compilado
  está en el repo; solo hay que recompilarlo (`build.sh` de esa carpeta) si
  cambia su código.
- **Firma ad hoc** de toda la app al final, porque `install_name_tool`
  invalida las firmas.

El registro anónimo solo se ve en la app: con dos cargadores de avatar (Sonia y
el invitado) pidiendo sesión a la vez, el segundo
`AvatarSdk.StartLoginAnonymousAsync` desechaba el flujo del primero y este
acababa en `NullReferenceException`. `GeniesSession` hace que todos (los
cargadores y el editor de personaje) esperen al mismo intento.

**La caché de Genies.** NAF guarda su caché de piezas en `cache`, relativo a la
carpeta de trabajo (`NafAssetResolverConfig.cachePath`). La primera vez descarga
las piezas de Sonia, del invitado y de la gorra de referencia de la trivia (unos
135 MB con las texturas de alta resolución); después arranca sin descargar.

En la app, la carpeta de trabajo era la que contiene `Sonnia.app` (en Windows, la
del `.exe`). Eso traía dos problemas:
- cada versión descomprimida en otro sitio volvía a bajarlo todo;
- si esa carpeta no se podía escribir, Genies no entregaba el avatar y salía el
  doble.

Lo segundo pasó en el stand el 10 de octubre de 2026. macOS abría la app
«traslocada»: las apps descargadas (zip por internet o AirDrop) que se abren sin
moverlas con el Finder se ejecutan desde una copia de solo lectura, y el
`Player.log` empieza con `/private/var/folders/.../AppTranslocation/...`. Se
reproduce montando la app en una imagen de disco de solo lectura.

Desde entonces `GeniesCacheFolder` fija la carpeta de trabajo de la app (en el
editor no) en una carpeta propia, antes de que nada use Genies:
- macOS: `~/Library/Application Support/Sonia/genies`;
- Windows: `%LOCALAPPDATA%\Sonia\genies`.

La caché vale para todas las versiones, se abra la app desde donde se abra. La
primera vez, si junto a la app había una caché de una versión anterior, la copia
ahí. El registro dice dónde está («Caché de Genies en …») y avisa si macOS ejecuta
la app traslocada.

Las versiones anteriores a esta necesitan su carpeta escribible: hay que mover
`Sonnia.app` con el Finder a una carpeta normal (mejor la de la versión anterior,
que tiene su `cache`) y aceptar los permisos que pida.

Esa primera carga puede pasar de los 90 s de cada paso del cargador. Mientras no
hay ningún avatar del SDK puesto, `GeniesAvatarLoader` la espera hasta una hora
sin abandonarla (no se sabe cómo será la red del DevFest) y deja en el registro
cómo va cada 90 s. Mientras tanto se ve el doble.

Antes la abandonaba a los 90 s y pedía otra que competía con la primera. En el
primer PC con Windows (7 de octubre de 2026) se quedó en el doble hasta que se
reabrió la app, y entonces montó en segundos. Hasta la 1.0.501, la espera larga
tampoco funcionaba: `AwaitLoad` volvía a poner `Timeout` sobre la misma carga y
UniTask, también con `Preserve`, no admite dos esperas mientras sigue en marcha
(«Already continuation registered» en el registro). Así que la daba por fallida
en el primer tramo y pedía otra. Ahora la carga se espera a través de
`GeniesAvatarLoader.Watch`, un `UniTaskCompletionSource` que sí admite varias.

Si NAF empieza una carga sin poder escribir su caché, esa carga se queda colgada
aunque luego haya permiso: solo lo arregla reabrir la app (comprobado el 10 de
octubre de 2026). Aun así, conviene abrir la app una vez en el equipo del stand
antes del evento, con internet.

El post-procesado (Volume con ACES y bloom) se ve también en la app: en
`UniversalRenderPipelineGlobalSettings` está desactivado «Strip Unused Post
Processing Variants», que recortaba el shader `PaniniProjection` y con él todos
los pases de post-procesado.

**Sonia > Build macOS (desarrollo, registro de Genies)** hace una build de
desarrollo en `unity/Build/macOS-dev/` con `FORCE_LOGS`, el símbolo que activa
el registro interno de Genies (sin él no escribe nada fuera del editor). El
registro nativo de NAF va aparte: en `Assets/Genies/NAF/Resources/NafSettings_Project`
(fuera de git) se puede poner Logging en «Editor Or Dev Build Only» y File
Logging, que escribe `cache/logs/naf.log`.

Si el avatar no llega a montarse, el cargador escribe en el registro qué había
construido el SDK cuando se agotó el tiempo («Genies no termina de montar el
avatar. En el aparcamiento: …», con objetos, mallas y texturas).

### Build de Windows

Se puede compilar en Windows o desde un Mac. **Sonia > Build Windows** (o
`SoniaBuild.BuildWindows` en modo batch, ver más abajo) deja la carpeta
`unity/Build/Windows-x64/` (`Sonnia.exe`, `Sonnia_Data`, `UnityPlayer.dll`…), que
se copia entera al equipo.

- **Vulkan como única API gráfica.** Genies lo exige en Windows: NAF entrega las
  texturas del avatar en formatos de Vulkan. `SoniaBuild` lo fija antes de cada
  build de Windows (queda guardado en `ProjectSettings`).
- **IL2CPP en Windows, Mono desde un Mac.** Genies pide IL2CPP, pero IL2CPP para
  Windows solo se compila en Windows (con las herramientas de C++ de Visual
  Studio). Desde un Mac `SoniaBuild` usa Mono durante la build, como en macOS.
  Hace falta el módulo **Windows Build Support (Mono)** de Unity 6000.6.0f1:
  `"/Applications/Unity Hub.app/Contents/MacOS/Unity Hub" -- --headless install-modules --version 6000.6.0f1 --module windows-mono`.
- **El orquestador congelado tiene que ser de Windows.** PyInstaller solo
  congela para el sistema en el que corre, así que la carpeta
  `unity/Build/orquestador/Windows/sonia-orquestador/` sale de una de estas dos:
  - `scripts/build_orquestador.sh` en Windows, desde Git Bash y con `uv`.
  - El workflow **Orquestador para Windows** de GitHub Actions
    (`.github/workflows/orquestador-windows.yml`, se lanza a mano:
    `gh workflow run orquestador-windows.yml` y `gh run download -n sonia-orquestador-windows -D unity/Build/orquestador/Windows/sonia-orquestador`).
    Congela el código que haya en GitHub, así que antes hay que subir los
    cambios.
  - Sin Windows ni Actions (el 9 de octubre de 2026 `gh` daba 404 en las
    Actions del repo), `scripts/parchea_orquestador_windows.py` sobre la
    carpeta de una build de Windows anterior: el bytecode de Python 3.12 es el
    mismo en todos los sistemas, así que cambia dentro del `.exe` solo los
    módulos `sonia.*` por los del repo, recalcula la suma PE y copia los
    `assets/` y estáticos del panel que cambiaron. Desde `server/`:
    `uv run --no-sync python ../scripts/parchea_orquestador_windows.py ../unity/Build/orquestador/Windows/sonia-orquestador`
    (`--probar` escribe el exe al lado sin tocar nada). No sirve si cambian las
    dependencias de terceros: entonces hay que congelar en Windows. Así salió
    la 1.0.197.

  Si desde la última build solo cambiaron `server/` o `assets/` (Unity no), la
  versión nueva se puede montar sobre los zips anteriores sin recompilar: se
  cambia el orquestador de dentro (`Sonnia_Data/orquestador/` en Windows,
  `Sonnia.app/Contents/Resources/orquestador/` en macOS, conservando el `.env` y
  el `cache/` que puso la build), la versión (`1.0.N` sale una vez en
  `Sonnia_Data/globalgamemanagers` como cadena con su longitud delante, así que
  se cambia por otra del mismo largo, y en macOS también en el `Info.plist`),
  se vuelve a firmar la app de macOS (`codesign --force --deep --sign -`) y se
  comprime como `SoniaBuild.Zip` (`ditto -c -k --keepParent` en macOS;
  `COPYFILE_DISABLE=1 tar -a -c -f` sin `.DS_Store` en Windows). Así salió la
  1.0.197 sin cerrar el editor, que tenía abierto otra sesión.

  Sin esa carpeta la build sale igual, pero sin orquestador (lo avisa la
  consola) y la app espera uno externo en el puerto 8765 (`uv run sonia run` en
  ese equipo). La build mete en el orquestador el `.env` del repo y, si no los
  trae, las frases grabadas (`cache/voice`) y los modelos y las huellas de caras
  (`cache/faces/modelos` y `huellas`) del equipo donde se compila: sin las
  huellas, la app de Windows no reconocería a las personas dadas de alta con
  fotos locales (`docs/caras.md`).
- **Siempre x64.** La primera prueba en un Windows de verdad (7 de octubre de
  2026, un portátil con AMD Ryzen) falló con «This app can't run on your PC»:
  desde un Mac con Apple Silicon, el ajuste de arquitectura de Windows estaba en
  ARM64. Ahora `SoniaBuild` lo fija en x64 (los Windows ARM la abren igual,
  emulando x64). La build lee la cabecera de `Sonnia.exe`, lo apunta en
  `build-report.txt` y falla si no es x64. Las carpetas y los zips llevan `x64`
  en el nombre. En `Sonnia_Data/Plugins/ARM64` queda un plugin de App UI: es
  normal, la app x64 carga los de `x86_64`.
- **Runtime de Visual C++ dentro de la app.** Las DLL nativas de Genies
  (`CommonDeps`, `GeniesAuthAPI`, `GeniesTelemetryBridge`) necesitan el de
  Visual C++ 2015-2022 x64 (`msvcp140`, `vcruntime140`, `vcruntime140_1`,
  `concrt140`), y Windows no lo trae de serie. En la prueba del 7 de octubre de
  2026, en un PC sin él, Genies no montó el avatar (`NativeGenie` sin mallas) y
  salió el doble. Ahora la app lo lleva: `scripts/build_orquestador.sh`, al
  congelar en Windows, copia esas DLL de `System32` a `sonia-orquestador/vcredist/`.
  La build las pone junto a `Sonnia.exe` y en `Sonnia_Data/Plugins/x86_64`, y
  falla si faltan (`build-report.txt`, «Runtime de Visual C++»).
- Para diagnosticar en un PC, **Sonia > Build Windows (diagnóstico, registro de
  Genies)** (`Build/Windows-dev-x64`). Es la build de prueba en desarrollo y con
  el registro interno de Genies (`FORCE_LOGS`) en el `Player.log`.
- El lado de Windows de Genies no lleva los arreglos de macOS (llavero y rutas):
  su librería de sesión usa DPAPI y no hace falta tocarla. Si algo falla, mirar
  el `Player.log`
  (`%USERPROFILE%\AppData\LocalLow\DefaultCompany\Sonnia\Player.log`) y
  `%APPDATA%\Sonia\logs`.

Desde un Mac, en modo batch y con el editor cerrado (tarda unos minutos la
primera vez, porque compila los shaders para Vulkan):

```bash
cd unity
/Applications/Unity/Hub/Editor/6000.6.0f1/Unity.app/Contents/MacOS/Unity -batchmode -quit \
  -projectPath "$PWD" -executeMethod Sonia.EditorTools.SoniaBuild.BuildWindows -logFile Build/build-windows.log
cat Build/Windows-x64/build-report.txt
```

La build cambia la plataforma activa del proyecto a Windows. Para seguir con la
de macOS no hay que hacer nada: **Sonia > Build macOS** la vuelve a cambiar.

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
| **Sonia > Comprobar pantalla (en Play)** | Simula, sin orquestador, el reposo con la invitación, la pregunta del visitante, la respuesta de Sonia creciendo (karaoke), una frase grabada y la vuelta al reposo, y deja capturas 9:16 e informe en `Temp/stagecheck/` (la primera vez solo pausa) |
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

### Builds de prueba (para el equipo)

**Sonia > Build macOS (pruebas, sin cámara en el panel)** y **Sonia > Build Windows
(pruebas, sin cámara en el panel)** (o `SoniaBuild.BuildMacTesters` y
`BuildWindowsTesters` en modo batch) hacen la misma app que las del stand, pero:
- salen en `Build/macOS-pruebas` y `Build/Windows-pruebas-x64`, para no confundirlas;
- llevan, junto al orquestador, un `build.env` con `PANEL_CAMERA_STREAM=false`. Manda
  sobre el `.env` copiado (`sonia/paths.py`), así que la app no manda ni la cámara ni
  el micrófono al panel de Cloudflare: quien la prueba en casa no puede ser visto ni
  oído desde el panel (no hay «Ver cámara» ni Modo Jean);
- y `TRIAL_LIMIT_MINUTES=300`: cinco horas de conversación en total, sumando todas las veces
  que se abra.
  - Cuenta el tiempo con la sesión de GPT-Live abierta, que es lo que cuesta.
  - Se guarda en `SONIA_HOME` (`trial_seconds` del estado del panel).
  - Al llegar a las cinco horas, GPT-Live se apaga y Sonnia se va con el letrero «La prueba de
    Sonnia ha terminado». Ni el panel ni volver a abrir la app la devuelven a conversar
    (`server/sonia/panel/control.py`, `trial_over`).
  - Es un candado local: borrando el estado del panel se reinicia, y la clave de OpenAI va
    dentro de la app. Para un tope de verdad, conviene darles una clave aparte con límite
    de gasto y revocarla después.

Las del stand no llevan `build.env`.

### App de vídeo para redes (Sonnia Video)

**Sonia > Build macOS (vídeo para redes)** (o `SoniaBuild.BuildMacVideo` en modo batch) hace
`Build/macOS-video/Sonnia Video.app`: la misma escena compilada con `SONNIA_VIDEO_APP`, que
no conversa sino que renderiza vídeos y fotos de Sonnia para redes (uso en `docs/video.md`).
La incremental tarda menos de un minuto.

- `SoniaVideoMode.Active` (esa build, o cualquier app con `-sonnia-video`): no se lanza el
  orquestador, `SoniaClient` no se conecta y la webcam no se abre.
- Sin ventana: `sonnia-video` la lanza con `-batchmode` (y la app lleva `LSUIElement`: ni icono
  en el Dock ni menú). En modo batch Unity no pinta las cámaras solo, así que cada subfotograma
  se pinta a mano (`RenderPipeline.SubmitRenderRequest` con `StandardRequest`). Con la cámara
  principal apagada esa petición no pinta la cámara del HUD: **los vídeos no llevan HUD** (ni
  logo, ni QR, ni subtítulos; Jean, 27 de octubre de 2026). Con doble clic la app abre el
  estudio web de `sonnia-video`, que lanza su propio renderizador sin ventana, y se cierra.
- `Sonia.Video.SoniaVideoStudio` (ensamblado `Sonia.Video`) espera trabajos por HTTP en
  `127.0.0.1:8795` (`-sonnia-video-port`) y hace de orquestador grabado: despacha la línea de
  tiempo del trabajo por `SoniaClient.InjectMessage` e `InjectAudioFrame` (estado,
  `speech_start`, voz en trozos de 100 ms, `gesture`) y hace él de motor de audio, como el
  laboratorio de cara. Boca, gestos y mirada salen por el camino del stand, a paso fijo
  (`Time.captureDeltaTime`). Medido: boca y voz con 0 cuadros de desfase (correlación 0,87).
- `VideoFrameRecorder` pinta a una RenderTexture N veces más grande y reduce y acumula en la
  GPU (shader `Resources/Video/SoniaVideoResolve`: supermuestreo y desenfoque de movimiento por
  subfotogramas); los cuadros van a ffmpeg por stdin, que puede escribir varias salidas a la vez
  (`.mov`, secuencia PNG y proxies). Con fondo transparente la cámara solo ve la capa 31 (Sonnia
  y su gorra) y cada exposición se pinta sobre negro y sobre blanco: el alfa sale de la
  diferencia, calibrada con el fondo vacío (la viñeta y el tonemapping cambian el blanco de
  cada píxel).
- Al acabar deja `registro.json` (cuándo sonó cada frase, boca por cuadro y los huesos en
  píxeles: cara, manos, índices, pecho...; de ahí sale el `localizador.json` de los reels) y
  `heard.wav`. Las fotos son trabajos `still` con varios instantes (`stills`).
- `VideoLook` aplica el aspecto y lo deshace al acabar: fondo (`StageScreen.SetBackdrop`:
  stand, color, degradado o imagen), presets de luz sobre las luces de la escena por nombre,
  contraluz y exposición (Volume propio), encuadre con los huesos
  (`CameraFramingController.SetOverride`: stand, primer plano, medio, americano y entero),
  emoción y gorra Noogler.
- La camiseta se elige al arrancar (`-sin-camiseta-staff` para la de Genies); la app se queda
  abierta entre trabajos (el avatar tarda en cargar; con la caché de Genies, unos 8 s) y se
  cierra sola tras 45 min sin peticiones (`-sonnia-video-idle-min`).
- Lleva dentro `sonnia-video` congelado (`scripts/build_sonnia_video.sh`, en
  `Contents/Resources/sonnia-video`) con el `.env` del repo, en lugar del orquestador, y no
  pide `PANEL_CLOUD_TOKEN`.

### Camiseta de staff

Sonnia lleva la camiseta de staff del DevFest Santo Domingo 2026 sobre la prenda
de arriba que tenga su personaje de Genies (`Genies/GeniesStaffShirt.cs`, 6 de
octubre de 2026). Se pone siempre: el editor de personaje elige la prenda y la
camiseta la viste. Hay cuatro variantes:
- `marino`: azul marino (#3A3448) con tinta blanca, como la camiseta de staff de 2026. Es la de por defecto (`GeniesStaffShirt.DefaultVariant`).
- `azul`: azul royal con tinta blanca, como las de 2023.
- `negra`: tinta blanca.
- `blanca`: tinta #1E1E1E, anillos oscuros en el emblema, como el oficial para fondo claro, y Sonnet Code a color.

`-camiseta azul` (o `negra` o `blanca`) en la línea de comandos elige otra variante y `-sin-camiseta-staff` la quita.

**Diseño** (`scripts/camiseta_staff/genera.py`, con los logos de origen en
`scripts/camiseta_staff/logos/`):
- Azul marino (#3A3448), como la camiseta de staff de 2026 (foto del 7 de
  octubre: la tela con el balance de blancos corregido con la tinta blanca).
  Antes era azul royal (#1F5FD6), como las de 2023, que contrastaba con el
  fondo navy de la pantalla; con la marino, el fondo pasó al azul royal del
  DevFest (ver «Pantalla del stand»). Todo en blanco, una sola tinta,
  salvo el emblema de GDG, que va a color con sus anillos blancos, como el de la
  web del evento.
- Delante: el arte de la camiseta real de 2026 («DevFest 2026 / # → Santo
  Domingo», fray Antón de Montesinos gritando su sermón, el mapa con el corazón,
  [*] y Google Developer Groups), de
  18 cm de ancho, y debajo Sonnet Code, el patrocinador más visible porque es el
  único delante. El arte está vectorizado en
  `scripts/camiseta_staff/logos/devfest-sd-2026-arte.svg` (sirve también para
  imprimir) y `genera.py` usa el PNG de al lado; en la variante `blanca` lo
  blanco pasa a la tinta oscura. Hasta el 7 de octubre delante iban el lockup
  (emblema de GDG + «DevFest / Santo Domingo») y «— STAFF —».
- Detrás: «STAFF» grande, el lockup y los patrocinadores 2026 de la web oficial
  del evento por niveles. Sonnet Code va el más grande. Después vienen Google y
  Banco Popular (Platino); Heva, Bojote, Caribium y TT Academy (Oro); Thraive y
  Talento Digital (Plata); y Festiva (Aliado). Los logos pensados para fondo
  oscuro se pasan a blanco dejando lo oscuro como tela (el cuadrado del Popular,
  los ojos del panda de Bojote). Los pensados para fondo claro quedan como
  silueta blanca con sus blancos en tela (las letras de «academy»).
- El emblema de GDG se dibuja desde la geometría de su SVG oficial: ImageMagick
  lo rasterizaba mal. «DevFest» va en Avenir Next, la de macOS más parecida a
  Google Sans.

`genera.py` escribe, para cada variante, en `Assets/Resources/StaffShirt/<variante>/`
los dos PNG (legibles, sin comprimir y sin mipmaps; los `.meta` que falten los
escribe él) y `staff-shirt.json`, con el color y
el rectángulo de cada estampado en metros respecto al hueso del pecho
(UpperChest): x hacia la derecha de quien mira e y hacia arriba. Para cambiar el
diseño hay que tocar `build()` en `genera.py`, ejecutar
`python3 scripts/camiseta_staff/genera.py --preview <carpeta>` (vistas sobre la
tela de cada variante) y volver a compilar.

**Cómo se pone.** La camiseta de Genies es un URP Lit (NAF lo convierte en
tiempo de ejecución). Sus texturas son color (blanco puro), normales (pliegues y
tejido) y metal/rugosidad, todas a 2048. No trae el mapa de proyección que usan
las prendas de `MegaShader` con estampado: `_DecalAlbedoTransparency`
proyectado con `_DecalUVProjection`, que es como Genies pone sus estampados
(`MegaMaterial.ApplyProjectedTexturesAsync`). Así que `GeniesStaffShirt` hace
esa proyección:
1. Corre en `GeniesAvatarLoader.BeforeShow`, con el avatar aún en el
   aparcamiento, así que nunca se le ve con la camiseta blanca. Tiene 8 s de
   tope; si falla, sale con su ropa.
2. Busca la prenda de arriba: la submalla que no es piel ni pelo de Genies y que
   pasa por encima y por debajo del pecho.
3. Copia su textura de color por la GPU y, en un hilo aparte, rasteriza los
   triángulos de la malla en el espacio de la textura. Cada texel sabe en qué
   punto del cuerpo está y con qué normal, y coge el color del estampado que cae
   ahí proyectado de frente o de espaldas. Usa 2x2 muestras por texel y se
   desvanece cuando la tela gira hacia el costado.
   Para que la tinta caiga solo donde caería con una prenda de verdad hay tres
   condiciones:
   - **La malla se toma con los brazos en cruz.** En el aparcamiento están a
     76° y la tela de la axila queda plegada detrás de la espalda.
   - **Cada estampado va solo en su pieza de tela:** la isla UV del torso que
     más superficie le aporta. Las mangas quedan fuera.
   - **Solo se tiñe la tela visible desde el estampado:** hay un mapa de
     profundidad de 1,5 mm por estampado y una tolerancia de 1,2 cm.

   Sin esto, Jean vio el 6 de octubre un trozo de la «S» de la espalda en la
   cara interior de la manga izquierda, que se separaba del resto al mover el
   brazo.
4. La tela se multiplica por el azul y la tinta va encima, también por la
   textura. Las normales no se tocan, así que el estampado se pliega y se ilumina
   con la tela.
5. Al destruirse el avatar se devuelve la textura original al material, porque
   NAF puede reutilizarlo.
Unos 2 s en este Mac, mientras el avatar sigue aparcado. El registro dice
«Camiseta de staff puesta en …».

La prenda de Genies es de una sola capa y su material (URP Lit) solo dibuja la cara de fuera (`_Cull` 2): al levantar el brazo, por la boca de la manga se veía el fondo a través de la tela de dentro. `GeniesStaffShirt` pone el material a doble cara (`_Cull` 0) al hornear la camiseta y lo devuelve como estaba al destruirse el avatar (7 de octubre de 2026).

**Para revisarla sin editor** (`Genies/GeniesShirtProbe.cs`):

```bash
unity/Build/macOS/Sonnia.app/Contents/MacOS/Sonnia -sin-orquestador -probe-shirt /tmp/sonda -capture-dir /tmp/capturas
```

Escribe en la carpeta:
- `sonda.txt`, con cada submalla y su shader, sus texturas y una rejilla de
  rayos que da las UV del pecho y de la espalda;
- las texturas de la prenda, ya horneadas;
- `vista-frente.png`, `vista-espalda.png` y `vista-tres-cuartos.png`, con una
  cámara temporal y sin el posprocesado del stand.

Con `-capture-dir`, además, capturas de la pantalla del stand.

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

### Pantalla del stand (diseño F)

Lo que se ve en Play es el diseño F («Navy en vivo») del canvas de diseño
«Pantalla de Sonia 9:16». Lo monta `StageScreen` por código al arrancar (lo
añade `SoniaBootstrap`, como la trivia y el letrero del modo Fuera), así que la
escena no cambia y en modo edición se sigue viendo el HUD antiguo:

| Elemento | Dónde (px de la referencia 1080x1920) | Cuándo |
|---|---|---|
| Fondo azul royal, el del arte del DevFest 2026 (hasta el 7 de octubre, el navy de la marca: con la camiseta marino Sonnia se perdía en él): degradado, dos brillos, puntos, la S de marca de agua y el halo azul de detrás de Sonia | Toda la pantalla, en un Canvas propio que dibuja la cámara principal a 12 m (detrás de Sonia, fijo aunque la cámara se mueva); pasa por el posprocesado de la escena y por eso va precompensado | Siempre |
| Logo de Sonnet Code todo en blanco (variación 14 de la marca; la S en degradado se perdía en el azul royal) con una sombra suave como la del recuadro del QR (`stage-logo-shadow`, negra al 55 %, 12 px más abajo) | Arriba a la izquierda, (56, 64), 250 de ancho | Salvo con el aviso de espera |
| Tarjeta blanca con el QR a sonnetcode.com/es y «¡Conoce más!» en negrita (el logo ya dice Sonnet Code) | Arriba a la derecha, margen 56, 232 x 266 | Salvo con imagen, trivia, juego o el aviso de espera (ocupan esa franja) |
| Aviso de espera (`BusyIndicator`): pastilla azul royal con borde blanco, tres puntos que saltan, «SONNIA» (Geist Mono 22) y el texto de `busy` (Manrope ExtraBold 58, blanco) | Arriba, centrada, a 32 del borde, 136 de alto y hasta 1008 de ancho | Con `busy` encendido, y 0,6 s como mínimo |
| Invitación: bocadillo blanco de Sonia, «SONIA» (Manrope ExtraBold 34, azul de marca) y «¡Acércate y pregúntame lo que quieras!» (Manrope ExtraBold 62, dos líneas), con la colita a la izquierda del centro inclinada hacia ella | Abajo, margen 72 a los lados y 96 abajo; la colita sale a 236 del borde izquierdo del bocadillo | Si Sonia puede conversar (`stage_mode` con `talk`), está en reposo, no hay subtítulos desde hace 7,5 s y no hay imagen, trivia ni modo Fuera |
| Subtítulos de Sonia: Manrope ExtraBold 64, blancos, centrados, sin caja, con lo que acaba de decir atenuado | Abajo, a 96 del borde, 968 de ancho, como mucho unos 110 caracteres (de una frase larga se ve el final) | Mientras habla y 6 s después |
| Lo que dijo el visitante: pastilla navy oscura «TÚ …» (sobre el jersey claro una translúcida no se leía) | Encima del texto de Sonia | Con los subtítulos |
| Sombra navy de abajo (degradado) | Los 760 px de abajo | Apagada de momento (`StageScreen.bottomShade`): tapaba las manos de Sonia |
| Sombra más alta detrás de los subtítulos | Los 1000 px de abajo | Con los subtítulos, si `bottomShade` está encendido |
| Sombra suave pegada a las letras de los subtítulos | En el propio texto | Con los subtítulos |

Detalles que no son obvios:

- **El karaoke va con la voz.** La transcripción de Sonia llega detrás de su
  audio, así que lo nuevo se enciende a partir de que llega (de atenuado a
  blanco en 0,45 s, sin correr más de 28 caracteres por segundo si llega un
  trozo grande de golpe). Si la frase llega entera en `speech_start` (las frases
  grabadas de `cache/voice`), lo que aún no ha dicho se ve atenuado y se va
  encendiendo a 15 caracteres por segundo desde el primer audio; al acabar la
  frase, lo que quede se enciende de golpe.
- **La invitación depende del modo.** Con «Solo saludos», «Fuera», el modo
  debug, el editor de personaje o el Modo Jean, GPT-Live está apagada y Sonia
  no contestaría: el orquestador lo dice con el mensaje fijo `stage_mode`
  (`docs/protocolo.md`) y la invitación no sale.
- **El fondo va precompensado.** Lo dibuja la cámara principal, y su
  posprocesado (ACES, contraste 10, saturación 8 y viñeta 0,28 del perfil
  `SampleSceneProfile`) lo dejaba mucho más oscuro que la maqueta: el azul a
  menos de la mitad, el rojo a cero y las esquinas casi negras.
  `scripts/urp_post.py` simula esa cadena de URP (gradación LDR; contrastada con
  una captura, falla en un nivel sobre 255) y `scripts/stage_assets.py` pinta el
  fondo que, tras ella, se ve como la maqueta, con el halo azul de la maqueta
  centrado a 600 px (90 px por debajo de los ojos del plano de reposo y de los
  del de conversación). Los colores del fondo están arriba del script
  (`BG_STOPS`, `GLOW_TOP`, `GLOW_BOTTOM`, `HALO_COLOR`, `HALO_PEAK`). El script lee el perfil del Volume: si se toca el perfil o el
  modo de gradación del pipeline, basta con volver a generar los recursos. Las
  motas del escenario no influyen: son unos pocos puntos de luz delante del fondo.
- **Lo antiguo se apaga en Play**: el telón 3D (`Sonia/Backdrop`), el logo del
  HUD (`BrandLogo`) y las burbujas de subtítulos (`Debug/Subtitles`).
- **Fuentes**: Manrope (ExtraBold y SemiBold) y Geist Mono (Medium), las de
  sonnetcode.com, con licencia OFL, en `Assets/Resources/Stage/Fonts`.
  `StageScreen` crea sus fuentes dinámicas de TextMeshPro al arrancar, con la de
  TextMeshPro de respaldo para los caracteres que falten.
- **Recursos**: fondo, formas redondeadas (corte en 9), sombra, colita del
  bocadillo, QR y logo están en `Assets/Resources/Stage` y los genera
  `scripts/stage_assets.py` (con `--url` para otro QR y `--brand` para la carpeta
  de assets del repo sonnet-code; el fondo tarda minuto y medio por la
  compensación). `Editor/SoniaStageAssets.cs` los importa como
  sprites sin compresión ni mipmaps; **Sonia > Reimportar recursos de la
  pantalla** los vuelve a importar.
- **Pendiente de autorización de Jean**: el cartel. En el diseño, al mostrar una
  imagen Sonia sujeta un cartel con ella; hasta entonces se queda el panel de
  imágenes de la franja alta (sección "Panel de imágenes"), y mientras está
  puesto el QR se aparta.

### Aviso de espera

«La gente es bruta y se desespera» (Jean, 10 de octubre de 2026): mientras Sonia
espera algo que el visitante no ve, `BusyIndicator` (lo añade `SoniaBootstrap`)
enseña la pastilla del mensaje `busy` (`docs/protocolo.md`; los textos están en
`server/sonia/busy.py`).

- **Dónde.** En la franja de arriba del todo, la del logo y el QR, que
  `StageScreen` aparta mientras se ve y vuelven mientras ella sale. Elegido con
  capturas: la coronilla de Sonnia queda a unos 320-360 px de arriba en los
  planos de conversación y de reposo, y en los juegos la tarjeta, la vista en
  vivo y el panel de imágenes empiezan a 200 px o más, con Sonnia debajo. La
  pastilla (de 32 a 168 px) no tapa la cara ni las manos en ninguno, tampoco con
  los brazos arriba de Simón dice ni en el resultado de piedra, papel o tijera.
  Va en un Canvas anidado en el del HUD con su orden 50 por encima: delante del
  escenario, los juegos, la vista en vivo, el confeti y los subtítulos.
- **Tiempos.** Entra en 0,14 s y sale en 0,2 s con la misma curva y sin rebote
  (fundido, un poco de escala y unos píxeles de caída): sale en cada delegación,
  también en las rápidas, y un `on` que llega mientras sale la devuelve desde
  donde está, sin saltos. Se queda al menos 0,6 s desde cada `on` aunque llegue
  antes el `off`. Si cambia el texto estando encendida («Preparando el juego…»,
  «Encendiendo la cámara…», «Pensando…»), el nuevo se funde en 0,18 s y el ancho
  se acomoda, sin volver a entrar. En las capturas sale entera entre 0,1 y 0,2 s
  después del `on` y, con un `off` inmediato, se retira a los 0,9 s.
- **Robustez.** Se retira sola si se cae el orquestador o llega otro `hello` (el
  orquestador repite el aviso al reconectarse si sigue) y a los 90 s sin `off`.
  Un fallo dentro se registra una vez y la apaga; sin el Canvas del HUD monta uno
  propio. `Show(texto)` y `Hide()` sirven para probarla sin orquestador, y el
  registro apunta cada aviso («Aviso de espera: «Pensando…»» y «Aviso de
  espera retirado tras 0.94 s.»).
- **Cómo probarla.** La secuencia `espera` del orquestador falso
  (`server/sonia/games/espera_demo.py`) la pinta en reposo, conversando, en una
  entrada y salida seguidas, con el texto que cambia y en Simón dice, piedra,
  papel o tijera, la búsqueda y el Wordle (`docs/juegos-unity.md`, «Capturas en
  batch»). `--tras-captura 0.05` deja las capturas a unos 0,15 s unas de otras:

  ```bash
  BUSQUEDA_DEMO_FOTO=<foto pública 16:9> SONIA_UNITY_LOCKS=$SP/unity-locks \
    scripts/juegos_capturas.sh --puerto 8796 --clon $SP/f0unity/clon --salida <scratchpad>/capturas-espera \
      --orquestador "uv run --no-sync python ../scripts/juegos_demo.py --juego espera --puerto 8796 --tras-captura 0.05"
  ```

### Encuadre del stand

**Desde el diseño F** `CameraFramingController` calcula el plano base con los
huesos del avatar enganchado (el doble al arrancar y el del SDK en cuanto llega)
en lugar de usar la pose de la cámara en la escena: de medio muslo para arriba
(1,24 m de alto a la altura de la cabeza) con los ojos al 27 % de la pantalla
desde arriba, para que las manos de los gestos de Sage se vean enteras por
encima de los subtítulos (hasta el 6 de octubre era de cintura para arriba,
1,16 m y ojos al 36,8 %, a la altura de los de un adulto si el borde de abajo
del monitor estaba a unos 0,9 m del suelo; con los ojos más arriba, el monitor
va algo más bajo). Cuando nadie conversa (estado `idle` durante 8 s), se abre
al plano de reposo, de rodillas para arriba (1,42 m, ojos al 26 %), con la
cadera y las manos asomando por encima de la invitación.
Los ojos se toman 11 cm por encima del hueso de la cabeza. Los ajustes de
«Developer» del panel se aplican igual sobre los dos, y los planos de panel,
abierto, de salida y del Modo Jean no cambian. Todo esto se puede apagar con
`stageFraming` e `idleShotEnabled` en el inspector. Lo de abajo describe el
cálculo anterior, que sigue siendo el de la pose de la escena:

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

### Partículas del escenario

`StageParticles` (lo añade `SoniaBootstrap` en Play) enseña un efecto de
partículas a la vez y funde de uno a otro en algo menos de un segundo:

| Efecto | Cuándo | Qué se ve |
|---|---|---|
| Ambiente | Por defecto | Las `Motes` de `SoniaStage`, adoptadas tal cual y reescaladas con los ajustes. |
| Trivia | Mientras hay una trivia en pantalla (también la pantalla final) | Destellos que suben y símbolos («?», «!», estrellas) en los colores de Google, entre Sonia y el halo; una explosión de destellos desde su pecho en cada acierto y otra mayor al ganar. Mezcla con alfa, no aditiva: sobre el azul del fondo se ven los colores. |
| Matrix | Con `activity` `search` del orquestador (busca en internet), al menos 2,5 s | Columnas de glifos verdes que caen detrás de Sonia, a la distancia del halo y del tamaño de lo que ve la cámara; la cabeza de cada gota nace casi blanca y deja un rastro que se apaga en verde. El fondo de la marca se oscurece un 30 % (queda al 70 % de su brillo y se sigue viendo detrás; `StageScreen.BackdropShade`). |

Si coinciden, manda la trivia: sus respuestas pasan por el backend y no deben
encender la lluvia cada vez. Con `activity` `think` (una tarea delegada pasa de
5 s sin buscar en internet) no hay efecto de partículas: Sonia se lleva la mano a
la barbilla (ver la tabla del coreógrafo). Los glifos son dos atlas en
`Assets/Resources/Particles` (katakana en espejo, cifras y símbolos para Matrix;
los símbolos de la trivia), generados con `scripts/particulas_glifos.py` (usa
fuentes de macOS para el katakana). Los materiales se clonan del de las motas,
que ya está en la build con su variante de shader.

**Esc > Partículas** (`Graphics/ParticleSettingsMenu.cs`) elige un efecto y lo
enseña al momento mientras el menú está abierto (en la trivia, con la explosión
de un acierto cada pocos segundos); el panel va abajo y el fondo apenas se
oscurece para verlo. Por efecto: cantidad (de 0 a 400 %; 0 lo apaga y en su
lugar sale el ambiente), velocidad (25 a 300 %), tamaño (50 a 500 %) y brillo
(25 a 300 %). «Cambio automático» en No deja siempre el ambiente. R o
«Restablecer este efecto» lo vuelve a como está montado. Se guarda en
PlayerPrefs de cada equipo (`ParticleSettings`). La opción «Partículas» de la
calidad gráfica las apaga todas, también la lluvia (Baja ya lo hace).

Para verlos en el editor, **Sonia > Partículas** entra en Play y fuerza uno
(Matrix, trivia o ambiente) o una demostración que alterna Matrix y la trivia
cada 10 s hasta salir de Play (`Editor/SoniaParticlePreview.cs`); con el editor
cerrado, `Unity -projectPath unity -executeMethod
Sonia.EditorTools.SoniaParticlePreview.DemoFromCommandLine` lo abre ya con la
demostración. Para grabarlos fotograma a fotograma, el laboratorio de cara (`scripts/facelab/run_lab.sh`)
acepta los pasos `message` (un mensaje del protocolo en `text`, por ejemplo
`{"type": "activity", "activity": "search"}` o los de la trivia), `particles`
(`ambient`, `trivia` o `matrix` a la fuerza), `tuning` y `menu` (ver
[`cara-y-lipsync.md`](cara-y-lipsync.md)).

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
| pensar con la mano en la barbilla | con `activity` `think` (una tarea delegada pasa de 5 s) y en thinking, `touchBeard` de Sage como acción sostenida (`ponderGesture`): entra ya en 1,75 s (antes, la mano del clip le tapa la boca), va y viene despacio entre 1,75 y 3,2 s (`ponderHold`, `ponderSpeed` 0,5) mientras dure la tarea y, al acabar o al cambiar de estado, pasa en 0,35 s al final del tramo y la mano baja con el final del clip (~1,2 s) |

Los gestos (atención, saludo, variaciones) entran y salen en `gestureFade`
(0,8 s) y `MotionPlayer` pasa el peso de cada fundido por una curva suave
(smoothstep, `smoothFades`), como Genies; el de presentar imagen va en
`presentFade` (0,5 s). `AvatarStateController.SetIdleTuning(respiración,
acentos, velocidad)` cambia en vivo la respiración, los acentos al hablar y la
velocidad del reposo (`AvatarChoreographer.SetLoopSpeed`), 1 = tal cual.

Mientras suena un gesto grande (atención o saludo) `IsWideShot` es cierto y
`CameraFramingController` abre el plano. Las listas de clips viven en
`SoniaAnimations.cs` y el asset `SoniaMotionSet` las materializa.

### Gestos de hablar de Genies (Sage)

Al hablar, Sonnia gesticula con los 161 gestos de Sage, un personaje del chat
de genies.com. No son clips de Unity: los `.ozz` de Genies se leen en tiempo
de ejecución.

**Qué hay en el proyecto**

- **Los clips:** `Assets/Animations/GeniesSage/ozz/*.ozz`. Los baja
  `scripts/gestos_genies/descarga_ozz.py` del CDN de Genies y los importa
  `GeniesOzzImporter` como `GeniesOzzAsset` (los bytes tal cual).
- **El lector:** `GeniesOzzClip`, traducción del lector de Python
  (`scripts/gestos_genies/ozz_genies.py`). Coincide al 0,0000° en 972 muestras
  de los 162 clips.
- **El set:** `SageGestureSet.asset`, que crea **Sonia > Gestos de Genies > Crear
  set de Sage** desde `manifest.json`. Lleva la ficha que Genies da a su LLM:
  descripción, intenciones, frecuencia, momento, impacto, intensidad y tiempos
  del núcleo. El mismo menú añade `GeniesGestureLayer` al objeto Sonia y le
  asigna el set.

**Cómo se mueven (`GeniesGestureLayer`)**

- **Regla de Genies:** el OZZ guarda la diferencia con la pose de enlace, así
  que cada hueso del torso queda en `enlace de Sonnia · clip`. Es lo que hace el
  motor de Genies con cada cuerpo (comprobado contra su motor web a 0,65°,
  `gestos-genies/README.md`).
- **De dónde sale el enlace:** de las `bindposes` de las mallas. Los huesos sin
  peso lo toman de su hijo `…Bind`.
- **Qué huesos mueve:** columna, cuello, cabeza, hombros, brazos, manos y 15
  falanges por mano. La cadera y las piernas siguen con `MotionPlayer` (reposo,
  IK de pies).
- **Orden de ejecución:** corre en `LateUpdate` con orden -20, después del
  Animator. Las físicas del pelo de Genies (orden 0) colocan el pelo sobre la
  cabeza ya movida. La cabeza que sigue al visitante, la mirada y la cara suman
  encima.
- **Fundidos:** cada gesto entra y sale con el fundido de Sage
  (`TransitionToClip_Duration`, 0,8 s) en curva suave. Si llega otro, el
  anterior se funde hacia fuera a la vez.
- **Cara:** pasa a `FaceRig` las curvas FACS del gesto, solo párpados, cejas,
  mejillas y comisuras (`faceGain`, 1 como Genies). Boca y mandíbula son del
  lip-sync, y `EYES_LOOK_*` de los ojos.

**Quién decide**

- **El director de gestos del orquestador** (mensaje `gesture`, ver
  `docs/gestos.md`) elige el gesto.
- **`SoniaBootstrap`** lo lanza cuando la voz de su frase ya suena:
  - si la frase ya terminó, lo descarta;
  - el de apertura (`utterance_id` null) espera hasta 4 s a la siguiente frase.
- **`AvatarChoreographer.CanTalkGesture`** pide que esté hablando y con voz, sin
  imagen, saludo, reacción, baile ni salida caminando.
- **Corte:** el coreógrafo funde el gesto hacia fuera al salir de hablar, en una
  pausa de voz, con otro clip de cuerpo y con `stop_speaking`.
- **Gestos de manos por código** (`AvatarStateController.handGestures`): se
  apagan mientras haya set, y los acentos de brazos callan mientras suena uno.
- **Panel:** recibe los 161 en el catálogo `animations` (grupo `sage`) y puede
  lanzar cualquiera por su nombre, en cualquier estado, para probarlo. Los
  clips desactivados en el panel y el modo debug también frenan los
  automáticos.

**Comprobar**

- **Sonia > Gestos de Genies > Hojas de contactos (en Play):** cada gesto en
  cuatro instantes, con una cámara que encuadra torso y brazos. Sale en
  `Temp/gestos-genies/` con un `indice.txt`.
- **Resultado (6-oct):** revisados los 161, todos naturales. Los exagerados
  (`blowingKissTinashe`, los `userTouch…`, `hairFlipTwoRiver`) son así por
  diseño; el director los evita en el stand.

**Lo que no se aplica**

- La cadera y las piernas.
- El reparto del giro de antebrazo y brazo en los huesos `…TwistNBind`, que
  sí hace el motor de Genies.
- La emoción `Happy` de Sage, que está vacía: sin huesos ni curvas animadas.

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
   | Escape | Abre el menú de opciones (siempre, también sin `-dev-ui`): **Calidad gráfica**, **Editar a Sonia**, **Partículas** (sección «Partículas del escenario») y **Micrófono, cámara y pantalla** (`StandSettingsMenu`: micrófono y cámara que usa el orquestador de este equipo, por defecto los del sistema, con `list_devices`/`set_device`; resolución 9:16 de la ventana y ventana o pantalla completa, que Unity recuerda solo). Dentro de cada submenú, Esc vuelve a las opciones. Con el editor de personaje abierto no hace nada. Para callar a Sonia, el botón **Interrumpir** |
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
   **Versiones** (desde el 8 de octubre de 2026): cada build de `SoniaBuild` lleva
   la versión `1.0.<commits del repo>` (`SoniaBuild.ResolveVersion`; todas las de un
   mismo commit llevan la misma, `SONIA_VERSION` la fuerza y `MajorMinor` se sube a
   mano para un salto grande). Va en `Application.version` (solo durante la build:
   `ProjectSettings` no cambia), sale arriba a la derecha del menú de Esc y en
   `build-report.txt`, y al acabar deja el zip en `unity/Build/<tipo>-<versión>.zip`
   (`Sonnia-macOS`, `Sonnia-Windows-x64`, `Sonnia-pruebas-macOS`,
   `Sonnia-pruebas-Windows-x64`, `Sonnia-desarrollo-macOS` y
   `Sonnia-diagnostico-Windows-x64`), borrando los zips anteriores de ese tipo. La
   app de macOS va con `ditto` (conserva enlaces y firma); la de Windows, con `tar`
   y sin `Sonnia_BackUpThisFolder_ButDontShipItWithYourGame`.
7. **Menú de opciones (Esc)**: arriba a la derecha, la versión de la app. Lleva a **Calidad gráfica**, a **Editar a Sonia**,
   a **Micrófono, cámara y pantalla** y a **Partículas** (efectos y ajustes de las
   partículas del escenario, sección «Partículas del escenario»)
   (el editor de personaje de Sonia; el de Jean solo se abre desde el panel). Al
   guardar en el editor, el personaje va al orquestador, que lo guarda como
   ajuste compartido y lo devuelve con `set_avatar`: sin orquestador conectado no
   cambia hasta que se conecte. ↑↓ elige, Intro abre, 1 a 4 son atajos.
   **Calidad gráfica** abre un menú con Alta, Media,
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
| `AvatarChoreographer.cs` | Decide qué clip suena en cada estado: idle con variaciones y atención, escuchar con asentimientos, pensar (con la mano en la barbilla si una tarea tarda), hablar encadenando gestos, saludo |
| `Gestures/GeniesOzzClip.cs` | Lector de los clips OZZ de Genies (huesos y curvas de cara) |
| `Gestures/GeniesOzzAsset.cs` | Bytes de un `.ozz` importado (`Editor/GeniesOzzImporter.cs`) |
| `Gestures/GeniesGestureSet.cs` | Gestos de un personaje de Genies (Sage) con su ficha para el director de gestos |
| `Gestures/GeniesGestureLayer.cs` | Reproduce los gestos de Genies sobre el torso (`enlace · clip`) con fundidos y curvas de cara |
| `CameraFramingController.cs` | Planos del stand calculados con los huesos del avatar (conversación de medio muslo para arriba y reposo de rodillas para arriba), plano de panel, abierto para los bailes y travelling a cuerpo entero en el modo Fuera |
| `StageScreen.cs` | Pantalla del stand (diseño F), construida por código en Play: fondo de la marca, logo, QR, invitación a hablar (bocadillo de Sonia) y subtítulos tipo karaoke |
| `PresenceController.cs` | Modo Fuera (`presence`): sale caminando con el root motion del ciclo de caminar, se oculta, y vuelve frenando hasta su marca (sección 6c) |
| `AwaySignController.cs` | Letrero del modo Fuera en el Canvas del HUD, construido por código, con fundidos |
| `ImagePanelController.cs` | Decodifica el base64 de `show_image` y lo muestra con animación de escala |
| `WebcamFrameSender.cs` | Captura de `WebCamTexture` y envío en JPEG cuando llega `request_frame` |
| `SoniaDebugUI.cs` | HUD de conexión, subtítulos, entrada de texto y botón de interrumpir |
| `Graphics/GraphicsQuality*.cs` | Calidad gráfica: niveles y opciones, el controlador que los aplica sobre lo montado y su menú |
| `Graphics/SoniaOptionsMenu.cs` | Menú de opciones de Esc: calidad gráfica, editor de personaje de Sonia, micrófono, cámara y pantalla, y partículas |
| `Graphics/ParticleSettingsMenu.cs` | Menú **Partículas**: efecto con vista previa, cantidad, velocidad, tamaño y brillo, y si cambian solos |
| `StageParticles.cs` | Partículas del escenario: motas, efecto de la trivia y lluvia estilo Matrix (con `activity` `search`), con fundidos |
| `ParticleSettings.cs` | Ajustes de las partículas por efecto, guardados en PlayerPrefs |
| `Editor/SoniaParticlePreview.cs` | Menú **Sonia > Partículas**: fuerza un efecto en Play o una demostración que alterna Matrix y la trivia |
| `SoniaBootstrap.cs` | Enlaza todo y aplica los ajustes de kiosco |
| `Editor/SoniaSceneSetup.cs` | Menús **Sonia > Crear escena base**, **Configurar build 9:16** y **Actualizar componentes** |
| `Editor/SoniaMotionSetBuilder.cs` | Menú **Sonia > Crear set de animaciones**: importa los FBX, rellena el set, genera la máscara y cablea la escena |
| `Editor/SoniaStageLighting.cs` | Menú **Sonia > Iluminación de estudio**: tres puntos de luz, halo, motas, Volume y SMAA; también deshace la iluminación estilo Genies |
| `Editor/SoniaGeniesLighting.cs` | Menú **Sonia > Iluminación estilo Genies** (opcional) y su `Remove` |
| `SoniaGeniesLook.cs` | Ambiente SH en modo Custom y rims que giran con la cámara de la iluminación estilo Genies |
| `Editor/SoniaAvatarSetup.cs` | Menús **Sonia > Colocar avatar** (ancla vacía, doble desactivado y cableado sin avatar) y **Recalcular encuadre (con el doble)** (mide el doble y ajusta cámara, panel, telón y luz) |
| `Editor/SoniaGeniesDefinitionSync.cs` | En el editor, escribe en `SoniaGeniesAvatar.json` el último avatar del SDK que lleva Sonia en Play |
| `GeniesDefinition.cs` | Huella de una definición de avatar de Genies, para comparar definiciones sin depender del formato |
| `Genies/GeniesSession.cs` | Un solo inicio de sesión en Genies a la vez para los cargadores de avatar y el editor de personaje (dos registros anónimos a la vez se pisaban) |
| `Editor/SoniaHumanoidRig.cs` | Construye y guarda un Avatar Humanoid para modelos con esqueleto de Mixamo que llegan sin él (GLB de Ready Player Me) |
| `Editor/GeniesGestureSetBuilder.cs` | Menú **Sonia > Gestos de Genies > Crear set de Sage**: set desde `manifest.json` y `GeniesGestureLayer` en Sonia |
| `Editor/GeniesGestureCheck.cs` | Menú **Sonia > Gestos de Genies > Hojas de contactos (en Play)**: cada gesto en cuatro instantes, en `Temp/gestos-genies/` |
| `Editor/SoniaCapture.cs` | Menú **Sonia > Captura vertical 9:16**: PNG 1080x1920 de la cámara principal |
| `Editor/SoniaAppIcon.cs` | Menú **Sonia > Icono de la app (en Play)**: saca el icono de las apps (la cara de Sonia sobre el navy de la marca, con la forma de los iconos de macOS) en `Assets/UI/SoniaAppIcon.png` y lo pone en el Player al salir de Play |
| `Editor/SoniaBrandAssets.cs` | Rutas y ajustes de importación de los assets de marca de Sonnet Code |
| `Editor/SoniaStageAssets.cs` | Ajustes de importación de `Resources/Stage` (sprites sin compresión, cortes en 9) y menú **Sonia > Reimportar recursos de la pantalla** |
| `Editor/SoniaStageCheck.cs` | Menú **Sonia > Comprobar pantalla (en Play)**: reposo, conversación, frase grabada y vuelta al reposo a paso fijo, con capturas 9:16 en `Temp/stagecheck/` |
