# Gestos de hablar de Genies: progreso (6 de octubre de 2026)

Jean pidió que Sonnia gesticule al hablar como los personajes del chat de Genies
(`https://genies.com/chat/existentialcheerleader`). Autorizó descargar esos gestos
para este proyecto (sin ánimo de lucro, uso personal). Se paró a mitad por
petición de Jean. Aquí queda lo averiguado, lo que funciona, lo que no y cómo
retomarlo.

## Resumen

- **Los gestos se pueden sacar de la página.** El motor nativo de Genies (el WASM
  de NAF) los muestrea hueso a hueso desde la propia página. Hay 48 candidatos
  identificados y 12 ya capturados a 30 fps (`gestos-genies-1.json`).
- **Pasarlos a Sonnia funciona a medias.** El horneador
  (`SoniaGeniesGestureBaker.cs`) genera clips humanoides. El primero
  (`chat-noImpact02`) tiene bien el torso, los brazos y las manos, pero salió con
  las piernas rotas: le faltaban las curvas de IK de los pies.
  - La causa está entendida y medida. El arreglo (calcular esas curvas) está
    escrito y compila, pero no se llegó a probar.
- **No hay nada integrado en la coreografía.** `TalkingClips` sigue vacío y los
  gestos de manos por código (5fdd48f) siguen como están.

## 1. Lo averiguado

### Dónde están los gestos

- **La lista de gestos del personaje** va en el `__NEXT_DATA__` de
  `/chat/existentialcheerleader` (se baja con `curl`):
  - `props.pageProps.smartAvatar.behavior` (`bm_behavior-config_59d2e7d8…`, "Cheerleader") trae dos listas:
    - `Utility_NoImpact`, con 10 clips de relleno (`noImpact01/02/03`, "lightly nods while gesturing with hands subtly at the side", entre otros);
    - `Cheerleader(IDset)`, con 146 clips.
  - Cada clip trae:
    - `_id`: `bm_anim-asset_…`;
    - `displayName`;
    - `llmMetadata`: descripción, duración, `core_start_time` y `core_stop_time`;
    - `libraryMetadata`: animador, `polish_level` y `assetName`, como `rnd-noImpact02-5f487c028aa1191c`.
  - La lista de etiquetas que Jean sacó de la consola (`Gesture tag not found: think. Available: […]`) es la misma: son los `displayName` en minúsculas.
- **Los clips son OZZ** (formato propio "genies-animation-clip") en el CDN de Genies.
  - La URL no está en la página: la resuelve CAMP dentro del WASM (`campResolveItem` → `loadAnimationAsync`).
  - Por eso no se bajaron "directos del S3": habría que imitar la resolución CAMP con el token de invitado de la página, y después decodificar OZZ fuera del motor.
  - No se intentó. Leerlos con el propio motor de la página resultó más seguro.
- **SDK web en la página:** está dentro de los chunks de webpack.
  - Se llega a él con `webpackChunk_N_E.push(...)` y se busca el módulo que exporta `loadAnimation` y `getLoadedAvatars`.
  - `avatar.controller` es un `AvatarAnimationController`, con `_module` (el módulo WASM), `_poseContext` y `_poseDefJS.joints`.
- **Muestrear un clip:**
  - Así funciona:
    1. `new M.AvatarController()` y `setPoseContext(ctx)`.
    2. Mirada, parpadeo, respiración, físicas, FBIK e IK de pies a cero o apagados.
    3. `setIdle(clip)`.
    4. Por cada fotograma, `setIdleTime(t)` + `update(0)` + `getPoseWrapper().getSkeletonLocalsAsFloat32Array()`. Son 10 floats por hueso: posición, cuaternión y escala.
  - El resultado es exacto y repetible: coincide con reproducir el clip de seguido.
  - `createClipSampler` + `Animator` sueltos no sirven: devuelven la pose de enlace.
  - El retarget nativo (`setAllRetargetEnabled`) no cambia nada.

### Esqueleto y coordenadas

- **Huesos:** el esqueleto de la página tiene 156 huesos con los mismos nombres que el avatar de Genies en Unity:
  - `Root`, `Hips`, `Spine`, `Spine1`, `Spine2`, `Neck`, `Head`, `LeftShoulder`, `LeftArm`, `LeftForeArm`, `LeftHand`, dedos `LeftHandIndex1..3`, etc.;
  - más huesos `…Bind` y `…TwistNBind`.
  - El clip trae 39 pistas SoA de 4 huesos (156) y 152 canales float (FACS), y `coordSpace` "RH".
- **Coordenadas:** la pose sale en mano derecha (three.js). A Unity se pasa con posición `(-x, y, z)` y cuaternión `(x, -y, -z, w)`.
  - Comprobado con la pose de enlace: `LeftArm` (0,1836, 0,0105, 0,0485, 0,9817) en la web frente a (0,1886, -0,0063, -0,0431, 0,9811) en Sonnia.
- **Pose de enlace distinta:** la animadora (`SubSpecies/ee3624e5ed509900`) no tiene la misma pose de enlace que Sonnia.
  - Cuello: +26,6° frente a -1,4°.
  - `Spine2`: -11° frente a 0°.
  - Los clips guardan rotaciones locales absolutas para ese cuerpo, así que copiarlas tal cual encorvaría a Sonnia.
  - **Solución usada:** para cada hueso humanoide se pasa el giro en el mundo respecto al enlace, delta = mundo_anim · mundo_enlace⁻¹, y se aplica sobre el enlace de Sonnia. La cadera se desplaza escalada por la altura de cada una (0,7785 m en la web).
- **Huesos `…Bind` en Unity:**
  - Los que no pesan en la malla (antebrazo, mano, dedos) toman su pose de enlace del hijo `…Bind`, que en Unity cuelga sin giro.
  - En Unity los `…Bind` están quietos (rotación local identidad). En la web se mueven los de giro del antebrazo y del brazo. Al humanoide no le afecta.

### IK de pies en Unity (la causa de las piernas rotas)

- MotionPlayer reproduce el cuerpo con IK de pies (`SetApplyFootIK(true)`). Sin curvas `LeftFootT/Q` y `RightFootT/Q`, los objetivos valen cero y los pies se van al centro del cuerpo: la rodilla sube al pecho.
- Se midió con `QuickAction_vibe` cómo construye Unity esos objetivos en este avatar. En todos los instantes y en los dos pies sale:
  - `goalQ = inv(bodyQ) · footRot · Q`, con Q ≈ (0,690, 0,151, -0,691, -0,152), constante;
  - `goalT = inv(bodyQ) · (footPos/humanScale - bodyT) + goalQ · (≈0,119, 0, 0)`;
  - 0,119 en unidades normalizadas son los 0,098 m de `leftFeetBottomHeight`.
- El horneador ya calibra Q y el desplazamiento con el reposo oficial (`DefaultIdle`) antes de hornear, y escribe las curvas. **Sin probar.**

## 2. Qué funciona y qué no

| Pieza | Estado |
|---|---|
| Captura en la página (`captura.js`) | Funciona. 12 gestos capturados en `gestos-genies-1.json`, más la prueba con `noImpact02`. |
| Descargas | El primer archivo por carga de página baja a `~/Downloads`. Chrome bloquea los siguientes sin preguntar, y el JSON de 36 gestos (17 MB) no llegó: hay que recargar la página antes de cada descarga. |
| Pestaña de Genies | Se colgó y desapareció dos veces. La primera vez fue tras muchas pruebas, probablemente por controladores nativos que no se liberaron. Las capturas en tandas de 12, liberando cada controlador, fueron bien. |
| Horneado (pasar el movimiento + músculos) | Torso, brazos, manos y dedos con buena pinta en `chat-noImpact02`: manos a los lados con un gesto suave, sin atravesar el cuerpo (vistas de frente, lado y tres cuartos a t = 0 y 1 s). |
| Piernas | Rotas en el clip horneado por la falta de curvas de IK. El arreglo está escrito, compila y está sin probar. |
| Hoja de contactos en conversación | El gesto es sutil: con el bocadillo de la invitación y el encuadre de cerca, las manos apenas entran en cuadro. Hay que mirar gestos más amplios (manos a la altura del pecho). |
| Integración (coreógrafo, gestos por código) | Sin empezar. |

**Nota sobre el MCP de Unity:** en este subagente no estaban las herramientas `mcp__unity-mcp__*`.
- Se usó el relay directamente: `scratchpad/herramientas/umcp.py` lanza `relay_mac_arm64 --mcp` y habla JSON-RPC.
- No pidió aprobación y cada llamada cierra su proceso.
- Los avisos `JobTempAlloc` de `Step()` hacen que el MCP marque el comando como fallido aunque haya terminado bien.

## 3. Archivos

**En el repositorio, sin commitear** (sin verificar del todo; compilan sin errores):

- `unity/Assets/Scripts/Sonia/Editor/SoniaGeniesGestureBaker.cs`: menú **Sonia > Gestos de Genies > Hornear capturas (en Play)**.
  - Lee la captura, calibra la IK de los pies con `DefaultIdle`, pasa el movimiento al esqueleto de Sonnia y escribe `Assets/Animations/GeniesChat/chat-<gesto>.anim`.
  - Necesita Play en pausa (la primera llamada solo pausa).
  - Se llama con reflexión: `Sonia.EditorTools.SoniaGeniesGestureBaker.BakeFile(rutaJson, "gesto1,gesto2" | null)`.
- `unity/Assets/Scripts/Sonia/Editor/SoniaGeniesGesturePreview.cs`: menú **Sonia > Gestos de Genies > Fotogramas de los gestos (en Play)**.
  - Pone a Sonnia en "hablando", aparta al coreógrafo y reproduce reposo → gesto (fundido de 0,8 s) → reposo.
  - Guarda fotogramas 1080x1920 en `unity/Temp/gestos/<clip>/`.
  - `PreviewFolder(solo, cadaSegundos)`.
- `unity/Assets/Animations/GeniesChat/chat-noImpact02.anim` (+ `.meta` de la carpeta): el primer horneado, **con las piernas rotas**. Hay que rehornearlo o borrarlo; no está en el set.

**En el repositorio, commiteado con este informe:**
- `scripts/gestos_genies/captura.js`: script de captura para la consola de la página. Es la misma lógica que se ejecutó; la lista de gestos va en `window.__gestosGenies`.

**En el scratchpad** (`/private/tmp/claude-501/-Users-jeanc-calderon-Documents-git-sonia/ec28b4d1-06d5-4c08-95e5-fc8360f58eb3/scratchpad/`, temporal, se pierde al cerrar la sesión):

| Ruta | Contenido |
|---|---|
| `gestos/capturas/gestos-genies-1.json` (3,9 MB) | `noImpact01`, `noImpact02`, `noImpact03`, `affirmationYamada`, `holdHandNodCute`, `subtleExplaination`, `refAbstract01Quick`, `refOpenHandsCute`, `refRaisedHandsCute`, `softEmphasis`, `ofCourse`, `emphasizeShort`. |
| `gestos/capturas/gestos-genies-prueba.json` | Solo `noImpact02`. |
| `gestos/pagina/ec.html`, `ec_next.json` | La página y su `__NEXT_DATA__` (lista completa con fichas). También `sage.html`, movida desde la raíz del repo. |
| `gestos/bundles/*.js`, `gestos/wasm/NAFWebGL.wasm`, `strings.txt` | Bundles del SDK web y el WASM, para consulta. |
| `gestos/hojas/` y `gestos/poses/` | Hoja de contactos y vistas de la primera prueba (piernas rotas). |
| `herramientas/umcp.py`, `runlog.sh` y los `.cs` de `RunCommand` | `bind.cs`, `hd.cs`, `binds.cs`, `units.cs`, `bake.cs`, `preview.cs`, `pose.cs`, `ikmeasure*.cs`. |

**Candidatos sin capturar** (36, de la lista `Cheerleader(IDset)`):
- **Habla y referencias:** `emphasize`, `3rdPersonPoised02/04/05`, `3rdPersonHandPoised03`, `3rdPrsnHandPoised01/04`, `3rdPrsnHandCute01/03/04`, `2ndPersonPoised04`, `refUser03Quick`, `refUser04Quick`, `1stPersonGesture03`, `1stPersonGesture01Quick`, `refSelf02Quick`, `refFuture`, `refFuture02`, `referenceThere01`, `refOptions02Quick`, `uncertainOptions`, `listingGesture02`.
- **Hombros y énfasis:** `subtleShrug`, `shrugging`, `noBigDeal`, `eccentricHands`, `handsWavingUpDown`, `envisionNagi`, `affirmPoised`, `agreeHipHopM`, `thumbsUpCalm`, `clappingCalm`, `2ndPersonCute02_1`, `gesturingAway02`, `referenceThis02`, `slowDown`.

Jean mencionó `cheerleader.html` en la raíz del repo, pero no estaba al cerrar (puede que sea la `sage.html` movida al scratchpad). No se revisó.

## 4. Cómo retomarlo

1. **Volver a capturar** si el scratchpad ya no está:
   1. Abrir `/chat/existentialcheerleader` en una pestaña propia.
   2. Poner la lista en `window.__gestosGenies` (tandas de 12) y ejecutar `captura.js`.
   3. **Recargar la página antes de cada tanda**: Chrome solo deja pasar la primera descarga por carga.
   4. Mover los JSON de `~/Downloads` a una carpeta del scratchpad.
2. **Probar el arreglo de la IK:**
   1. Entrar en Play y esperar al avatar.
   2. Llamar a `BakeFile` dos veces: la primera pausa, la segunda hornea.
   3. Mirar las piernas con `pose.cs`, de frente, de lado y en tres cuartos.
   - Si siguen mal, la alternativa es reproducir estos clips sin IK de pies (opción nueva en `MotionPlayer.Play`) o en la capa de torso (`UpperLayer`, que no toca piernas ni raíz). Las piernas no se ven en el encuadre de conversación.
3. **Hornear todos y elegir 10-15** con hojas de contactos en el encuadre de conversación (`PreviewFolder`):
   - que las manos no atraviesen el cuerpo ni la camiseta y los dedos se vean naturales;
   - que no haya giros raros;
   - descartar los muy de personaje (sarcasmo, coqueteo).
   - Cada `.anim` ocupa unos 2,7 MB por 2 s (YAML): conviene quedarse con pocos o reducir claves.
4. **Integrar:**
   1. Carpeta `Assets/Animations/GeniesChat` en `SoniaAnimations.ClipFolders`, con su `LICENSE.md` y una entrada en `docs/licencias.md`.
   2. Los elegidos en `TalkingClips`, y en `KeepsHorizontalMotionInPose` para conservar el traspaso de peso.
   3. En `AvatarChoreographer`, con el reposo único de conversación: un gesto suelto en el cuerpo (fundido de 0,8 s, como Genies) al empezar una frase o cada pocos segundos de voz, nunca seguidos, y vuelta al reposo.
   4. En `AvatarStateController`, `handGestures` solo como respaldo cuando el set no tenga clips de hablar.
   5. Documentarlo en `docs/unity.md` y marcar el punto de `PENDIENTES.md`.
5. **Verificar en silencio** con `hub_manos.py` (volumen 0) y hojas de contactos 9:16 mientras habla.
