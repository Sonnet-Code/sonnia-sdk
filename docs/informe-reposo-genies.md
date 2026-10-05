# Reposo natural del avatar de Genies: investigación

Investigación del 5 de octubre de 2026, cuatro días antes del DevFest. Jean probó
los personajes de `genies.com/chat` (Mia) y, cuando están quietos, se balancean
de un lado a otro muy sutilmente; Sonia, en cambio, se veía tiesa en reposo. Aquí
está por qué no se usa el motor de comportamiento nativo de Genies en Unity y
qué se hizo en su lugar.

## Cómo lo hace la web

`genies.com/chat` monta el avatar con NAF compilado a WebAssembly (three.js) y
un motor de comportamiento con capas: reposo, aburrimiento, gestos, respiración,
emoción base, cuatro emotes y habla. El balanceo es el clip de reposo del
personaje más la capa de respiración, mezclados por ese motor.

El comportamiento de cada personaje sale de la API nueva de Genies (CAMP):

1. El catálogo público (`/chat/api/catalog?resource=genies`) da el
   `smartAvatarId` de cada personaje (`bm_smart-avatar_…`).
2. El smart avatar se resuelve por CAMP (`campResolveItem`) y trae
   `behavior.id`, un id `behavior-config`.
3. Ese config se resuelve también por CAMP y se carga con
   `loadSmartAvatarBehaviorFromConfig(config, useRH, idle, talking, breathing,
   emotion, onComplete)`, con ids `bm_anim-asset_…` fijos para la respiración, el
   habla y la emoción.
4. Antes, el JavaScript le pasa al nativo la URL del servicio, un token bearer
   del visitante y la versión del SDK (`setServiceBaseUrl`,
   `setServiceBearerToken`, `setServiceSdkVersion`).

## Qué trae el SDK de Unity (3.8.6)

El SDK de Unity incluye el mismo tipo de controlador en los bindings SWIG
(`GnWrappers.AvatarController`, ensamblado `Genies.NafPlugin`), pero el código C#
del SDK no lo usa en ningún sitio: el avatar se anima con el Animator. La API es
más antigua que la de la web:

- `LoadSmartAvatarBehavior(slug, useRH, idleAssetId, talkingAssetId,
  onComplete)`. No hay `FromConfig` ni manera de pasar un token. El nativo usa su
  propio cliente REST (`GnUtils::RestService`, configuración embebida con
  `api.genies.com`): se autentica con credenciales de cliente embebidas en la
  librería (y, si fallan, como invitado), pide la lista `GET /smart-avatars` y
  busca el **slug** en ella. El id del catálogo web no vale.
- El controlador también acepta clips directamente: `SetIdle`, `SetBreath`,
  `SetTalking`, `PlayBoredom`, `PlayGesture` y `SetEmotion` con un
  `GnWrappers.AnimationClip`. Pero ese clip es formato nativo (OZZ,
  `AnimationClip.Load(datos, tamaño)`), y el SDK no ofrece desde C# ninguna forma
  de conseguir los clips de Genies en ese formato
  (`ContainerApi.LoadAnimation` devuelve un búfer opaco).
- La pose se lee con `GetPose()` (locales del esqueleto: 10 floats por hueso) y
  la `PoseContext` del avatar vivo está en `NativeGenie.PoseContext` (interno,
  por reflexión).

## Qué se probó

Un componente de prueba (`GeniesBehaviorDriver`, ya retirado) creaba el
controlador sobre el avatar vivo del SDK, cargaba el comportamiento, lo avanzaba
con `Update` y volcaba su pose en los huesos después del Animator.

- Con el id del catálogo (`bm_smart-avatar_…`) o con el slug `mia`, el peso del
  reposo (`GetIdleWeight`) se queda en 0. Con `mia` el aviso de fin llega (se
  despacha desde `Update`, no desde el hilo de red), pero sin reposo. Con un
  slug inventado no llega en 60 fotogramas.
- El log nativo no dice nada: el proyecto tiene NAF con `logging: 0`, y ni
  engancharle un callback al `GnUtils::Logger` (el mismo que usa el módulo de
  comportamiento) ni el log a archivo reciben siquiera un `Info` lanzado a mano.
  Si algo falla, falla en silencio.
- **Se cae Unity** si se libera el controlador mientras la autenticación está
  en curso: el hilo del `ThreadManager` vuelve de la petición de credenciales,
  pasa a la de invitado y usa el `DefaultAuthProvider` ya destruido (segfault en
  `DefaultAuthProvider::FetchGuestAuth`, `libgnBehaviourWrapper`). En el stand
  pasaría al cambiar de avatar, al entrar en el modo Jean o al recargar.

## Decisión

El motor nativo no entra antes del 9 de octubre: la API de Unity no es la de la
web, falla sin decir por qué y puede tumbar la app. Si algún día se retoma, hace
falta un SDK de Unity con la API nueva (config por CAMP y token), o al menos que
el controlador viva todo el proceso y nunca se libere con una carga a medias.

En su lugar (plan B), todo con recursos oficiales de Genies y sin red:

1. Reposos oficiales de Genies con balanceo, comparados con fotogramas frente a
   `DefaultIdle`.
2. Reposos naturales también al escuchar y al pensar, en lugar de `StillPose`
   (la pose congelada), que era lo que más tiesa la dejaba en conversación.
3. Una capa procedural suave encima: respiración y traspaso de peso lento con
   los pies fijos, ajustable.
