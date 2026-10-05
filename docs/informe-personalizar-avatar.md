# Editor de personaje de Genies dentro de la app de Sonia: investigación

> Nota del 5 de octubre de 2026: la copia local del avatar ya no existe. En modo
> edición no hay avatar y Sonia se carga viva del SDK al entrar en Play (ver «El
> avatar de Genies en Play» en `docs/unity.md`). Lo que aquí se dice de la copia,
> de `GeniesAvatarSnapshot` y del menú **Sonia > Actualizar copia del avatar del
> SDK** es historia.

Investigación del 4 de octubre de 2026, cinco días antes del DevFest. Solo se ha
leído código y documentación: no se ha tocado Unity ni se ha llamado a los
servidores de Genies. SDK: `com.genies.avatar-sdk.client` 3.8.6, embebido en
`unity/Packages/` y parcheado a mano para Unity 6000.6.

Qué se quiere (aclaración de Jean): el personaje no se edita desde el panel web.
Un botón del panel pone la pantalla de Sonia (la app de Unity) en la escena de
editar personaje del sample de Genies. Lo que se guarda ahí acaba en la
configuración en la nube, y todas las Sonias lo cargan.

Mientras se escribía esto ya se estaba montando ese camino (cambios sin commit a
las 23:46):

- La copia del sample en `unity/Assets/Sonia/AvatarEditor/`.
- `unity/Assets/Scripts/Sonia/AvatarEditorLauncher.cs`.
- Los mensajes `open_avatar_editor`, `close_avatar_editor`, `avatar_editor`,
  `avatar_saved` y `set_avatar` en `docs/protocolo.md`,
  `server/sonia/ws/protocol.py` y `Protocol.cs`.
- El ajuste compartido `avatar` en `server/sonia/panel/control.py`.

El informe usa esos nombres y, en el apartado 4, repasa lo que falta o conviene
cambiar.

## Conclusión

- **La escena del sample sirve como escena propia de la app.** Trae el editor
  completo (45 categorías, cámara y miniaturas). Usa el Input System nuevo (su
  `EventSystem` lleva `InputSystemUIInputModule`), funciona con la sesión
  anónima y solo necesita la API pública del SDK.
- **Sacar la definición al guardar.** El avatar que se edita lo carga nuestra
  escena y se lo pasa a `EditorInitializer.Initialize(avatar)`, así que lo
  tenemos a mano. Al pulsar Guardar: `string json = avatar.GetDefinition();`.
  Es exactamente el JSON 2-0-0 que carga `LoadAvatarOptions.ByDefinition` (el
  formato de `SoniaGeniesAvatar.json`), y viaja tal cual en `avatar_saved`. El
  guardado del sample (un perfil local en disco) se sustituye por eso. En la
  copia ya está hecho, en `EditorInitializer.SaveAvatar`.
- **Volver a la escena de Sonia.** Se descarga la escena del editor
  (`SceneManager.UnloadSceneAsync`), que destruye y libera su avatar. Luego se
  vuelve a encender lo que se apagó de Sonia, se le devuelve la escena activa y
  se avisa con `avatar_editor` (`open: false`). El aspecto nuevo no lo pone el
  editor: llega por el `set_avatar` fijo y lo aplica `GeniesAvatarLoader` igual
  que en cualquier Sonia.
- **Escena aditiva, como está montada.** Así no se corta la conexión con el
  orquestador ni hay que recargar el avatar de Sonia. Sustituir la escena
  (`LoadSceneMode.Single`) es más limpio, pero deja la pantalla desconectada
  unos segundos y el orquestador lo toma por un cierre del editor (apartado 3.8).
- **Antes de usarlo en el stand faltan cuatro cosas** (apartado 4):
  - `AvatarEditorSession.CurrentDefinition` no lo rellena nadie. Así, el editor
    arranca con el avatar de la sesión anónima, y al guardar **sustituiría el
    aspecto de Sonia en todas las Sonias** por ese.
  - Con la copia local del avatar, la escena de Sonia no inicia sesión en Genies,
    y el editor se queda esperando un login.
  - El cargador todavía no aplica `set_avatar`: Sonia vuelve del editor con el
    aspecto viejo.
  - El canvas del sample está pensado para una columna a la derecha de una
    pantalla apaisada: en 1080x1920 taparía a Sonia.
- **El editor legacy (v7.1.9) no compensa** (apartado 2).

## 1. Lo que trae el SDK

### 1.1 El sample «Creating an Avatar Editor»

El original está en
`unity/Assets/Samples/Genies Avatar SDK/3.8.6/Sample Starter Scenes/Creating an Avatar Editor/`,
que git ignora. La copia de la app está en `unity/Assets/Sonia/AvatarEditor/`:

- con GUID nuevos y espacio de nombres `Sonia.AvatarEditor`;
- en su propio ensamblado (`Sonia.AvatarEditor.asmdef`);
- con lo que usa de `Common` (sprites, `Loading Spinner`, `Login Canvas`,
  `GeniesLoginUI`, `AvatarLoadedNotifier`, el skybox).

| Archivo | Qué hace |
|---|---|
| `Scripts/Sample Extensions/SampleEditorUsage.cs` | Arranque: espera a que haya sesión (`AvatarSdk.Events.UserLoggedIn`), carga el avatar y llama a `EditorInitializer.Initialize(avatar)`. En el original carga `LoadAvatarOptions.User()`; en la copia, `LoadStartingAvatar()` carga `ByDefinition` con `AvatarEditorSession.CurrentDefinition`. |
| `Scripts/Setup and State/EditorInitializer.cs` | Exige `AvatarSdk.IsLoggedIn` (la sesión anónima cuenta) y precarga todo el catálogo (`PreCacheAssets`). Alinea el «Camera Rig» con el avatar, reparte el avatar a los `UIGeneratorGroup` y gestiona Guardar (`_saveButton` → `SaveAvatar`). |
| `Scripts/Data/AssetInfoDataSource.cs` | Catálogo: `GetDefaultWearablesByCategoryAsync`, `GetDefaultHairAssets`, `GetDefaultAvatarFeaturesByCategory`, `GetDefaultColorsAsync`, `GetDefaultMakeupByCategoryAsync`, `GetDefaultTattoosAsync` y `GetAvatarFeatureStatsAsync`. |
| `Scripts/UI Generation/UIGenerator.cs`, `UIGeneratorGroup.cs` | Una sección por categoría: celdas con icono, muestras de color o deslizadores. Al pulsar llaman a `EquipWearableAsync`, `SetAvatarFeatureAsync`, `SetColorAsync`, `EquipMakeupAsync` o `EquipTattooAsync`, y quitan con `UnEquip…`. |
| `Scripts/UI Generation/UICell.cs` | Celda. Un candado estático (`_isLoading`) impide lanzar otra operación hasta que acaba la anterior. |
| `Scripts/Setup and State/UITransitionManager.cs`, `CameraController.cs` | Navegación y cámara: mueve la cámara (`Camera.main` si no tiene otra asignada) entre los transforms «Camera Pos: …» del «Camera Rig». |
| `Prefabs/Editor Canvas.prefab` | Canvas `ScreenSpaceOverlay` con `CanvasScaler` de 1080x1920 y `matchWidthOrHeight` 0,7. El panel (694x1160) cuelga de un «Anchor» en la esquina superior derecha (escala 2,89). |
| `Scenes/SoniaAvatarEditor.unity` | Copia de `CreatingCustomEditor.unity`, igual al original salvo los GUID. Lleva cámara con `AudioListener`, luz direccional, `Global Volume`, `EventSystem`, paredes y fondo, «Sample Editor Usage», el `Login Canvas` y el `Editor Canvas`. |

Genies presenta este sample como el sustituto del editor integrado que quitó en
3.8.4, y su documentación recomienda usar sus scripts y prefabs para hacer el
editor propio.

### 1.2 API pública que interesa

Todo está en `Genies.Sdk.AvatarSdk`
(`unity/Packages/com.genies.avatar-sdk.client/SDK Avatar/Runtime/Scripts/AvatarSdk.Customization.cs`)
y en `Genies.Sdk.ManagedAvatar` (`SDK Core/Runtime/Scripts/ManagedAvatar.cs`).

```csharp
// Cargar el avatar que se va a editar
UniTask<ManagedAvatar> AvatarSdk.LoadAvatarAsync<T>(T options)    // LoadAvatarOptions.ByDefinition { DefinitionToLoad, ShowLoadingSilhouette, TargetLods }
// Sacar y aplicar definiciones
string ManagedAvatar.GetDefinition()
UniTask ManagedAvatar.SetDefinitionAsync(string definition)
bool ManagedAvatar.IsLoadingComplete;  event Action ManagedAvatar.LoadingComplete
void ManagedAvatar.Dispose()
// Lo que usa el sample por dentro (catálogo y cambios)
UniTask<List<WearableAssetInfo>> GetDefaultWearablesByCategoryAsync(WearablesCategory c, bool forceFetch = false)
UniTask<List<IAvatarColor>> GetDefaultColorsAsync(ColorType colorType)
UniTask EquipWearableAsync(ManagedAvatar avatar, WearableAssetInfo info)
UniTask<bool> SetColorAsync(ManagedAvatar avatar, IAvatarColor color)
UniTask<bool> ModifyAvatarFeatureStatAsync(ManagedAvatar avatar, AvatarFeatureStat stat, float value)
UniTask SetAvatarBodyTypeAsync(ManagedAvatar avatar, GenderType gender, BodySize size)
// Lo que no queremos (apartado 1.4)
UniTask SaveAvatarDefinitionLocallyAsync(ManagedAvatar avatar, string profileId = null)
UniTask SaveUserAvatarDefinitionAsync(ManagedAvatar avatar)       // cuenta de Genies real, no anónima
// Sesión
bool AvatarSdk.IsLoggedIn   // también con la sesión anónima
UniTask<(bool isLoggedIn, string username)> AvatarSdk.TryInstantLoginAsync()
UniTask<(bool succeeded, string failReason)> AvatarSdk.StartLoginAnonymousAsync(string applicationId = "")
```

El editor integrado ya no existe: `AvatarSdk.OpenAvatarEditorAsync`,
`CloseAvatarEditorAsync` y `SetEditorSave*` solo registran un error
(`AvatarSdk.cs`, región «Deprecated»).

### 1.3 De dónde sale el catálogo

- Del API de inventario de Genies
  (`Internal/Inventory/Runtime/Services/DefaultInventoryService.cs`), con el token
  de la sesión. **La sesión anónima vale.**
- **Cada llamada espera a que haya sesión, sin límite de tiempo**
  (`GeniesLoginSdk.WaitUntilLoggedInAsync()`). Si nadie inicia sesión, el editor
  se queda con el spinner para siempre.
- Hay caché en memoria y en disco (24 horas, en `persistentDataPath`). La de
  memoria es estática: sobrevive al cerrar y abrir el editor, así que la segunda
  vez abre mucho más rápido.
- **Si una petición falla, el SDK la apunta como hecha y devuelve lista vacía el
  resto de la sesión** (`FetchWithConfig`: «Mark as fetched even on error»). Una
  pestaña vacía no se arregla hasta reiniciar la app (solo las prendas admiten
  `forceFetch`).
- Las miniaturas bajan por Addressables y se quedan en memoria.
- Al poner una prenda nueva se descarga su asset: editar exige red.

### 1.4 Cómo guarda el sample original

`SaveAvatarDefinitionLocallyAsync` → `LocalAvatarProcessor.SaveOrUpdate`
(`Internal/Avatar Customization/Runtime/Scripts/Core/LocalAvatarProcessor.cs`):

- Hace una foto de la cabeza.
- Escribe `persistentDataPath/AvatarProfiles/<perfil>.json` con un envoltorio
  `{"Definition": {...}, "HeadshotPath": "...", "AvatarGameObject": null}`.
- En el editor de Unity, además, crea un ScriptableObject y la foto dentro de
  `Assets/Genies/AvatarEditor/…`, con `AssetDatabase.Refresh()` en pleno Play.
  Esa carpeta la gestiona el SDK.

No sirve para nuestro flujo. El `Definition` de dentro es el mismo JSON de
`GetDefinition()`, pero en un archivo del equipo en vez de en el orquestador.

### 1.5 La definición como JSON

`ManagedAvatar.GetDefinition()` → `NativeUnifiedGenieController.GetDefinition()`
(`Internal/NAF/Runtime/Scripts/UnifiedGenie/NativeUnifiedGenieController.cs`)
reúne:

- las piezas puestas;
- los atributos de color;
- los atributos de cuerpo distintos de cero;
- los tatuajes.

Lo serializa con Newtonsoft como `Genies.Naf.AvatarDefinition`:

```json
{"JsonVersion":"2-0-0","equippedAssetIds":["AvatarBase/recmdZ4C4enmt630","WardrobeGear/0afd6330787bf2a2"],
 "colors":{"unified-skin":{"r":0.741,"g":0.620,"b":0.490,"a":1.0}},"bodyAttributes":{"JawWidth":0.871},"equippedTattooIds":{}}
```

Es el formato de `SoniaGeniesAvatar.json`. `ByDefinition` lo deserializa a esa
misma clase (`GeniesAvatarsSdk.LoadAvatarControllerByJsonDefinition`). Sale
compacto, sin saltos de línea: no es el mismo texto que el JSON del repo aunque
sea el mismo personaje (importa para la huella de la copia local, en 3.6).

### 1.6 Aplicar una definición a un avatar ya cargado

`ManagedAvatar.SetDefinitionAsync(json)` baja las piezas que falten, vacía el
avatar, pone colores y medidas y lo reconstruye en sitio. Tiene tres trampas
(`NativeUnifiedGenieController.SetDefinitionAsync`):

1. Si ya hay una definición cargándose, la segunda llamada se ignora sin avisar.
2. Si una pieza no baja, no hay error: se queda fuera y el avatar queda a medio
   vestir.
3. No convierte ids antiguos.

Además, ninguna llamada de personalización lanza excepciones: registran el error
y vuelven.

Por eso, para poner un aspecto nuevo en Sonia es mejor **cargar otro avatar
aparcado y cambiarlo con `AvatarBinder.Bind`** (lo que ya hace el cargador al
arrancar) que tocar el que está en pantalla.

Los cambios del editor pasan por una cola en la que gana la última operación
(`latestOpWins`). Una carga con silueta (`ShowLoadingSilhouette = true`) termina
la definición en segundo plano, y un clic durante esa carga la cancelaría. La
copia carga con `ShowLoadingSilhouette = false`, que espera a que el avatar esté
completo antes de devolverlo: hay que dejarlo así.

### 1.7 Por qué conviene que el editor no toque el avatar de Sonia

Cada cambio reconstruye el avatar:

- `NativeMultiMeshBuilder.RebuildRenderers()` crea y destruye
  `SkinnedMeshRenderer`, y los índices de los blendshapes pueden cambiar;
- algunos assets vuelven a poner `BlendShapeAnimatorBehaviour` encendido;
- `NativeGenie.RebuildHumanAvatar()` puede asignar un `Animator.avatar` nuevo.

Editar el avatar de Sonia en sitio obligaría a reenganchar `FaceRig`, volver a
apagar ese componente y reconstruir `MotionPlayer` tras cada cambio.

Con el editor en su escena y con su propio avatar, nuestro pipeline nunca ve
cambios en caliente: solo recibe un avatar completo, cargado y enganchado por el
camino de siempre.

## 2. ¿Mejor el editor legacy v7.1.9?

No. Repositorio: `https://github.com/geniesinc/com.genies.avatareditor-sdk.client.git#v7.1.9`
(revisado en un clon de esa etiqueta, fuera del proyecto).

- Genies lo ha congelado. Su README dice «we will not be updating it… We
  recommend using the prefabs and scripts from the "Creating an Avatar Editor"
  sample».
- Depende de `com.unity.cinemachine` 3.1.5 y de `com.genies.avatar-sdk.client`
  3.8.4.
- En 6000.6 no compila sin parche: `Internal/CreatorTools Utils/Runtime/Tattooenator.cs:461`
  usa `GetInstanceID()` (CS0619). Al ser un paquete git, habría que embeberlo
  para parchearlo.
- `ProjectorNavigation.cs` y `CameraOrbiter.cs` usan `UnityEngine.Input`, que en
  nuestro proyecto lanza excepción.
- La interfaz es de móvil táctil (`CanvasScaler` de 390x844) y trae cámaras de
  Cinemachine propias.
- La licencia es la misma EULA propietaria del SDK
  (https://legal.genies.com/sdk-eula.html).

## 3. Diseño: la escena del sample dentro de la app

### 3.1 Piezas

| Pieza | Dónde | Qué hace |
|---|---|---|
| Copia del sample | `unity/Assets/Sonia/AvatarEditor/` | El editor de Genies: escena, prefabs, scripts y arte. Va en git: unos 4 MB. |
| `AvatarEditorSession` | `unity/Assets/Scripts/Sonia/AvatarEditorLauncher.cs` | Puente estático entre las dos escenas: `CurrentDefinition` (con qué personaje abre el editor), `IsOpen`, `Save(definition)` y `Close()`. |
| `AvatarEditorLauncher` | el mismo archivo; `SoniaBootstrap` lo añade a la raíz «Sonia» | Abre la escena del editor encima de la de Sonia y la cierra. Manda `avatar_editor` y `avatar_saved`. |
| `GeniesAvatarLoader` | `unity/Assets/Scripts/Sonia/Genies/GeniesAvatarLoader.cs` | Tiene que rellenar `CurrentDefinition` y aplicar `set_avatar` (falta; apartado 4). |
| Orquestador | `server/sonia/panel/control.py` | Acciones `open_avatar_editor`, `close_avatar_editor` y `reset_avatar`; maneja `avatar_editor` y `avatar_saved`; ajuste compartido `avatar` con el mensaje fijo `set_avatar`. |
| Nube | `cloud/panel/src/control-room.ts` | Guarda los ajustes compartidos y los reparte a todas las Sonias. |
| Build | `unity/Assets/Scripts/Sonia/Editor/SoniaBuild.cs` | `Scenes` lleva las dos escenas (Sonia primero). En el editor de Unity hay que pasar una vez por **Sonia > Escenas de la build** antes de probar en Play: `LoadSceneAsync` por nombre exige que la escena esté en Build Settings, y ahora mismo `EditorBuildSettings.asset` solo tiene `SampleScene`. |

### 3.2 Flujo

1. El operador pulsa «Editar personaje» en el panel. El orquestador manda
   `open_avatar_editor`.
2. `AvatarEditorLauncher` carga `SoniaAvatarEditor` en modo aditivo.
   - Antes de activarla, apaga las demás raíces de la escena de Sonia (cámara y
     HUD, luces, volumen, escenario y `EventSystem`) y, dentro de la raíz
     «Sonia», sus renderers y lienzos.
   - Después pone el editor como escena activa y manda `avatar_editor`
     (`open: true`).
   - El orquestador cierra GPT-Live y para los saludos mientras dure.
3. En el editor, «Sample Editor Usage» espera a la sesión y carga con
   `ByDefinition` el personaje de `AvatarEditorSession.CurrentDefinition`. Luego
   `EditorInitializer.Initialize` precarga el catálogo y muestra la interfaz.
4. El personal edita con el ratón.
5. Guardar: `EditorInitializer.SaveAvatar` → `avatar.GetDefinition()` →
   `AvatarEditorSession.Save(json)` → el lanzador manda `avatar_saved` y cierra
   el editor.
6. El orquestador valida la definición, la guarda como ajuste compartido
   `avatar` (en `cache/panel_state.json` y en la nube) y manda el fijo
   `set_avatar` a todos sus clientes. La nube la reparte a las demás Sonias, que
   también mandan `set_avatar` a su Unity.
7. En cada Unity, `GeniesAvatarLoader` ve un `set_avatar` distinto del que
   lleva puesto, carga el avatar nuevo aparcado y lo cambia con `Bind`.
8. Salir sin guardar (botón del editor, `close_avatar_editor` desde el panel o
   inactividad) cierra igual, sin `avatar_saved`.

### 3.3 Entrar en la escena del editor

Lo que ya hace `AvatarEditorLauncher.OpenRoutine` está bien resuelto:

- carga con `allowSceneActivation = false` y apaga Sonia justo antes de activar,
  así los `Awake` del editor ya encuentran como `Camera.main` la cámara del
  editor, no la de Sonia;
- pone el editor como escena activa con `SceneManager.SetActiveScene`. El cielo
  y la luz ambiente salen de la escena activa, y los objetos que cree el SDK
  (el avatar del editor, que se carga sin padre) caen dentro del editor y se
  destruyen al descargarlo.

Faltan tres cosas:

- **Con qué personaje abre.** `CurrentDefinition` lo tiene que poner el
  cargador, también en el camino de la copia local:
  - la definición del `TextAsset` mientras Sonia lleva el de la app;
  - la del último `set_avatar` aplicado cuando lleva otro.

  Si aun así llegara vacío, el editor debe usar el JSON de la app, nunca
  `LoadAvatarOptions.User()`.
- **Sesión.** Si Sonia salió de la copia local, el SDK ni siquiera ha iniciado
  sesión. El editor debe iniciarla él con el mismo código que el cargador
  (`TryInstantLoginAsync` y, si no, `StartLoginAnonymousAsync`, con `.Timeout`),
  y cerrarse con un aviso si no lo consigue.
- **El `Login Canvas` del sample sobra.** Sin sesión muestra el formulario de
  Genies (correo o entrar como anónimo). Con sesión muestra un botón «Log out»
  que cerraría la sesión de Genies de toda la app.

### 3.4 Cómo sacar la definición al guardar

Dónde: `unity/Assets/Sonia/AvatarEditor/Scripts/Setup and State/EditorInitializer.cs`,
método `SaveAvatar`, que es lo que hace el botón Guardar del sample
(`_saveButton`). En la copia ya cambia el guardado en disco por esto:

```csharp
await UniTask.Yield();
string definition = _avatar != null ? _avatar.GetDefinition() : null;
// …
global::Sonia.AvatarEditorSession.Save(definition);   // → AvatarEditorLauncher.HandleSave → client.SendAvatarSaved(definition)
```

Es el camino correcto: `_avatar` es el `ManagedAvatar` que editan las celdas, y
`GetDefinition()` da el JSON listo para `ByDefinition`. Tres mejoras:

1. **Esperar a que no haya una operación en curso, no un fotograma.** El botón
   Guardar no es una celda, así que el candado del sample no lo bloquea. Si se
   pulsa justo después de elegir una prenda, la definición sale sin ella, y al
   descargar la escena el avatar se libera con la operación a medias. Se
   arregla con una línea en la copia de `UICell` (`public static bool IsBusy => _isLoading;`),
   y Guardar espera con `UniTask.WaitUntil(() => !UICell.IsBusy)` y un tope de
   unos 30 s.
2. **No mandar nada si no cambió.** Si la definición no cambió respecto a
   `CurrentDefinition`, se cierra sin `avatar_saved`. Comparar como datos, no
   como texto: el formato del JSON del repo es distinto.
3. **Validar antes de que viaje a todas las Sonias.** `JsonVersion` igual a
   `"2-0-0"` y `equippedAssetIds` con al menos una pieza.
   `parse_avatar_definition` (en `protocol.py`) solo comprueba que sea un objeto
   JSON de menos de 64 KB: una definición vacía dejaría sin ropa a todas las
   Sonias.

Que la definición llegue la resuelve ya el lanzador. Guarda la última mandada
(`_pendingDefinition`), la repite al reconectar y la da por recibida cuando le
vuelve el `set_avatar` con el mismo texto. El orquestador la guarda sin
reformatearla, así que la comparación por texto vale.

Alternativa sin tocar `SaveAvatar` (no recomendada): dejar el guardado del
sample y leer el `Definition` de `persistentDataPath/AvatarProfiles/<perfil>.json`.
Escribe en disco, hace una foto de la cabeza y, en el editor de Unity, crea
assets en `Assets/Genies` en pleno Play.

### 3.5 Cómo volver a la escena de Sonia

`AvatarEditorLauncher.CloseRoutine`, igual para «guardado» y «sin guardar»:

1. `SceneManager.UnloadSceneAsync(editor)`. Se destruye todo lo del editor,
   también su avatar. La copia de `SampleEditorUsage` llama a `_avatar.Dispose()`
   en su `OnDestroy`, y `ManagedAvatarComponent` haría lo mismo al destruirse la
   raíz del avatar: no queda nada nativo colgado.
2. `SceneManager.SetActiveScene(<escena de Sonia>)` y `ShowSonia()`, que vuelve a
   encender las raíces, renderers y lienzos que apagó (solo esos).
3. `client.SendAvatarEditor(false)`: el orquestador vuelve al modo que tocaba
   (GPT-Live, saludos…).

Lo que sobrevive al editor:

- la sesión de Genies (es estática);
- las cachés del catálogo y de las miniaturas, así que la siguiente apertura es
  más rápida;
- la conexión con el orquestador, que no se ha cortado.

Lo que tiene que añadirse:

- **Un botón «Salir sin guardar» en el canvas.** El sample no lo trae. Debe
  llamar a `AvatarEditorSession.Close()`.
- **Cierre por inactividad** (por ejemplo, 10 minutos sin tocar nada). Si
  alguien deja el editor abierto, Sonia no vuelve sola y GPT-Live sigue cerrada.
- **Cierre por error.** Si `LoadAvatarAsync` devuelve `null` (sin red) o no hay
  sesión, hoy el sample sigue adelante con `Initialize(null)` y enseña una
  interfaz sin avatar. Debe cerrar el editor y avisar.
- **El aspecto nuevo en Sonia** (3.6). Sin eso, Sonia vuelve con el que tenía
  hasta que se reinicie la app, y ni siquiera entonces si el cargador no mira
  `set_avatar`.

### 3.6 Poner el aspecto nuevo en Sonia (todas las Sonias)

Es trabajo de `GeniesAvatarLoader`, igual en la Sonia que editó que en las demás:

- **Al arrancar.** Esperar unos segundos a la conexión con el orquestador, que
  manda los fijos justo después de `hello`, para saber si hay `set_avatar`.
  - Si no lo hay, o es `null`, o es el de la copia local: como ahora (copia
    local al instante).
  - Si es otro: la copia local hace de doble mientras se carga ese del SDK, y
    luego `Bind`.
- **Con Sonia ya en marcha.** Cargar aparcado el nuevo (el `TryLoadAsync` de
  ahora, con el JSON recibido) y comprobar que `GetEquippedAssetIds().Count`
  cuadra con la definición. Después, `binder.Bind(nuevo)` y `Dispose()` del
  anterior (`Bind` lo desactiva, pero no lo libera). Si falla, se queda el que
  había y se reintenta con espera creciente.
  - Mejor cuando Sonia no esté hablando.
  - **Nunca con el editor abierto** (`AvatarEditorSession.IsOpen`): el avatar
    nuevo de Sonia tiene los renderers encendidos y saldría en la cámara del
    editor, en el mismo sitio que el que se edita. Se aplica al cerrar.
- **Mantener `AvatarEditorSession.CurrentDefinition`** con la definición que
  Sonia lleva puesta.
- **Huella de la copia local.** `GeniesAvatarSnapshot.Matches` compara el texto
  (solo normaliza saltos de línea y espacios de los extremos), y `GetDefinition()`
  sale en otro formato que el JSON del repo. Guardar desde el editor el mismo
  aspecto que trae la app no coincidirá con la copia local y se cargará del SDK.
  No rompe nada, pero tarda. Si molesta, hacer la huella sobre el JSON
  canónico.

### 3.7 Pantalla vertical y ratón

El ratón funciona tal cual: `EventSystem` con `InputSystemUIInputModule` y
botones y celdas de uGUI. Lo que no encaja es la disposición:

- **El panel.** Cuelga de un `Anchor` en la esquina superior derecha. Según sus
  `RectTransform`, en 1080x1920 ocuparía de x ≈ 310 a x ≈ 1004 px y de unos 145 a
  1305 px desde arriba: dos tercios del ancho en el centro de la pantalla. No se
  ha visto en pantalla. En la copia hay que reanclarlo abajo, a todo el ancho
  (unos 800 px de alto). Dentro ya está organizado como pestañas en tira
  horizontal, columna de subcategorías y rejilla, y eso sirve en vertical.
- **La cámara.** Los «Camera Pos: Editing Face» y «Editing Body» del
  `Camera Rig` están pensados para ese panel lateral. Hay que moverlos para que
  el avatar quede en la mitad de arriba (los de tatuajes, si se dejan los
  tatuajes, igual).
- **Las capturas (principio 7).** `Sonia > Captura vertical 9:16` renderiza la
  cámara a una textura y no ve los canvas en Overlay. Pasar el `Editor Canvas`
  de la copia a Screen Space - Camera sobre la cámara del editor, o capturar la
  vista Game a 1080x1920.
- **Categorías que se pueden ocultar** en la escena sin tocar código: tatuajes,
  barba, máscaras. Por decidir con Jean: la camiseta del staff del DevFest
  (principio 6) no está en el catálogo de Genies.

### 3.8 ¿Escena aditiva o sustituyendo la de Sonia?

| | Aditiva (lo montado) | Sustituir (`LoadSceneMode.Single`) |
|---|---|---|
| Conexión con el orquestador | Sigue abierta | Se corta y la abre el `SoniaClient` de la otra escena: 1 a 3 s sin pantalla |
| Regla del orquestador (`_loop`: editor abierto y 0 clientes → cerrado) | No salta | Salta en cada cambio de escena y reabre GPT-Live a destiempo, salvo que se le dé un margen de unos 15 s |
| Volver a Sonia | Instantáneo | Recargar la escena; un aspecto nuevo se carga del SDK |
| Memoria | Dos avatares de Genies a la vez (el de Sonia, oculto, y el del editor) | Uno |
| Aislamiento | Hay que apagar bien lo de Sonia (hecho). Su raíz sigue viva: coreógrafo, lip-sync, audio. En «Solo saludos», «Decir» y «Saludar» del panel mandan una frase grabada (`play_clip`) que sonaría por el `AudioListener` del editor | Total |
| Riesgo | Un objeto del SDK creado por primera vez con el editor como escena activa se destruiría al descargarla. Poco probable, porque el SDK ya está iniciado; vigilar errores tras cerrar | Ninguno de esos |

Recomendación: seguir con la aditiva. Conviene que el panel desactive «Decir»,
«Preguntar» y «Saludar» mientras `editor_open` esté a cierto (o que el
orquestador las rechace).

### 3.9 Verificación

- En Play en el Mac (tras **Sonia > Escenas de la build**):
  1. «Editar personaje» desde el panel local.
  2. El editor abre con el personaje de Sonia, no con otro.
  3. Cambiar pelo y ropa, Guardar.
  4. Vuelve Sonia y, a los pocos segundos, con el aspecto nuevo.
  5. `cache/panel_state.json` y la nube tienen la definición.
  6. Salir sin guardar y `close_avatar_editor` vuelven con el aspecto anterior.
- **Principio 7:** capturas 1080x1920 del editor (con su canvas en Screen
  Space - Camera) y de Sonia tras volver. Lip-sync con varios fotogramas después
  del cambio, con «Solo saludos» y la caché de voces para no gastar.
- **Arrancar Sonia** con un `set_avatar` distinto del de la copia local: sale la
  copia y luego el nuevo.
- **Build de Windows** (IL2CPP, Vulkan) en la red del stand: abrir, editar,
  guardar y volver.
- **Tests de Python** sin red para `avatar_saved` (válido, vacío, sin
  `equippedAssetIds`) y para las acciones de abrir y cerrar.

## 4. Repaso de lo que hay en el árbol (cambios sin commit, 23:46)

1. **`AvatarEditorSession.CurrentDefinition` no se asigna en ningún sitio.**
   Solo lo lee `SampleEditorUsage.LoadStartingAvatar()`, que, vacío, carga
   `LoadAvatarOptions.User()`: el avatar por defecto de la sesión anónima.
   Guardar ahí **cambiaría el aspecto de todas las Sonias por ese**.
   - Arreglo: que el cargador lo rellene en todos los caminos (3.3 y 3.6) y que
     el respaldo sea el JSON de la app.
2. **Sesión de Genies.** Con la copia local, `GeniesAvatarLoader.Start` vuelve
   sin iniciar sesión. El editor esperaría `UserLoggedIn` con el formulario de
   Genies en pantalla, y con sesión enseñaría «Log out».
   - Arreglo: inicio de sesión automático en el editor (o un ayudante común con
     el cargador) y quitar el `Login Canvas` de `SoniaAvatarEditor.unity`.
3. **El cargador no escucha `set_avatar`** (`GeniesAvatarLoader` y
   `SoniaBootstrap` no se suscriben a `OnSetAvatar`). Lo guardado no se ve en
   ninguna Sonia hasta implementarlo (3.6).
4. **Guardar con una operación en curso** (3.4, punto 1). Además, `UICell._isLoading`
   es estático y sobrevive a descargar la escena. Si una operación no termina
   nunca (por ejemplo, el catálogo esperando una sesión), todas las celdas quedan
   bloqueadas hasta reiniciar la app.
   - Arreglo: ponerlo a `false` al abrir el editor.
5. **Validación** de `avatar_saved` en el orquestador (3.4, punto 3).
6. **Sin botón de salir, sin cierre por inactividad y sin cierre por error**
   (3.5).
7. **Disposición 9:16 y cámara sin adaptar**: el prefab y la escena son
   idénticos al sample salvo los GUID (3.7).
8. **`SamplePrefabTracker`.** El `Editor Canvas` lleva este componente del SDK,
   que solo existe en el editor (`#if UNITY_EDITOR`). En el build sale como
   «missing script». Inofensivo; se puede quitar.
9. **Ya resuelto:** las dos escenas en `SoniaBuild.Scenes`; el guardado sin
   perfil local; el reenvío de la definición al reconectar; la carga del editor
   sin silueta.

## 5. Trampas generales

- **Unity 6000.6.** Los parches del SDK no están en git: al reinstalarlo en el
  equipo del stand hay que rehacerlos. La copia del sample compila con API
  pública y no necesita parches.
- **Samples.** `Assets/Samples` está en `.gitignore` y la copia tiene GUID nuevos,
  así que no choca con el original si alguien vuelve a importar los samples.
  Pero ojo: los tipos se llaman igual en dos ensamblados (el sample y
  `Sonia.AvatarEditor`). Nada nuestro debe referenciar el ensamblado del sample.
- **Mac frente a Windows.**
  - No hay build standalone de Mac con el SDK (documentación de Genies, «Common
    issues»). Un build de Mac no tendría editor; los `.meta` de los plugins de
    macOS marcan Standalone OSX ARM64, pero no está soportado ni probado.
  - Todo se prueba en Play en el Mac. El build es de Windows: Vulkan como única
    API gráfica, IL2CPP y .NET Framework. Genies avisa de texturas que faltan en
    los editores de avatar si queda DirectX en la lista.
- **Rendimiento.**
  - La primera apertura precarga todo el catálogo (sin medir: varias peticiones
    y cientos de miniaturas); las siguientes salen de caché.
  - Cada prenda nueva supone una descarga más la reconstrucción nativa.
  - Con la escena aditiva hay dos avatares en memoria mientras se edita.
- **Red.** Sin red no hay catálogo, ni sesión, ni prendas nuevas: el editor
  debe cerrarse con un aviso (3.5). Si la red del recinto filtra dominios,
  Genies no carga: probarlo allí, igual que GPT-Live.
- **EULA.** Prohíbe modificar el SDK. La copia adaptada del sample es lo que
  Genies recomienda en su documentación, y el proyecto no gestiona licencias
  (principio 8).

## 6. Resumen y estimación

El plan:

1. La escena del sample, copiada en `Assets/Sonia/AvatarEditor`, se abre en
   modo aditivo sobre la de Sonia con `open_avatar_editor`.
2. Al Guardar, `avatar.GetDefinition()` viaja en `avatar_saved`.
3. El orquestador la convierte en el ajuste compartido `avatar`, que la nube
   reparte a todas las Sonias.
4. Se vuelve descargando la escena del editor.
5. `GeniesAvatarLoader` pone el aspecto nuevo cargándolo aparcado y
   cambiándolo con `Bind`.

Lo que queda, sobre lo que ya hay en el árbol:

| Trabajo | Estimación |
|---|---|
| `CurrentDefinition` y su respaldo; sesión automática y sin `Login Canvas` | 0,25 días |
| Guardar: esperar operaciones, no mandar si no cambió y validar en Unity y en el orquestador | 0,25 días |
| Salir sin guardar, cierre por inactividad y cierre por error | 0,25 días |
| Cargador: aplicar `set_avatar` al arrancar y en marcha (aparcado, `Bind`, `Dispose`, nunca con el editor abierto) | 0,5 días |
| Disposición 9:16 del canvas y de la cámara del editor, con capturas | 0,5 a 1 día |
| Verificación en Play y build de Windows en la red del stand | 0,5 a 1 día |
| **Total** | **unos 2 a 3 días** |

Si no diera tiempo antes del 9 de octubre: con el editor ya funcionando en Play
en el Mac, se puede fijar el aspecto de Sonia y copiar la definición a
`SoniaGeniesAvatar.json` (y rehacer la copia local con **Sonia > Actualizar
copia del avatar del SDK**). Así se tiene un personaje propio aunque el flujo
desde el panel quede para después.

## Qué está verificado y qué no

Verificado leyendo el código del SDK 3.8.6, del sample, de la copia en
`Assets/Sonia/AvatarEditor`, de los cambios sin commit (a las 23:46) y la
documentación enlazada:

- Que `GetDefinition()` da el formato 2-0-0 de `ByDefinition` y que la copia
  guarda con él.
- Que la sesión anónima basta para el catálogo, y que las llamadas del catálogo
  esperan a la sesión sin límite.
- Que `ShowLoadingSilhouette = false` hace esperar a la definición completa
  (`AvatarControllerFactory.CreateSimpleNafGenie`: `SkipWaitingDefinitionLoad = showLoadingSilhouette`).
- Lo que reconstruye cada cambio y las trampas de `SetDefinitionAsync`.
- Que el `Login Canvas` enseña «Log out» con sesión.
- Que la escena y el prefab copiados son idénticos al original salvo los GUID.
- Los puntos del apartado 4, tal como estaban a esa hora.

Sin verificar (no se ha ejecutado nada):

- Cómo se ve el sample en 1080x1920 (deducido de sus `RectTransform`).
- Tiempos de la primera apertura y de cada prenda.
- Que ningún objeto del SDK se cree por primera vez dentro de la escena del
  editor.
- Que el lip-sync y `FaceRig` funcionen igual con un avatar de aspecto nuevo
  cargado por `Bind` (es el mismo camino que al arrancar, así que debería).
- Que un vestido sustituya a la camiseta y al pantalón (lo hace el código
  nativo).

## Fuentes

- Sample «Creating an Avatar Editor»: https://docs.genies.com/docs/sdk-unity/sdk-avatar/sample-scenes/creating-editor
- API para editores propios: https://docs.genies.com/docs/sdk-unity/sdk-avatar/frameworks/custom-editor
- Editor legacy: https://docs.genies.com/docs/sdk-unity/sdk-avatar/tools/legacy-editor
- Notas de la versión 3.8.4 (retirada del editor integrado y sample nuevo): https://docs.genies.com/docs/sdk-unity/sdk-avatar/release-notes/sdk-avatar-3-8-4
- Plataformas y requisitos de Windows: https://docs.genies.com/docs/sdk-unity/tools/common-issues
- Repositorio del editor legacy (etiqueta v7.1.9): https://github.com/geniesinc/com.genies.avatareditor-sdk.client
- EULA del SDK: https://legal.genies.com/sdk-eula.html
