<!--
  BORRADOR pendiente de revisión de Jean (10 de octubre de 2026). Escrito por el agente de
  «Simón dice con poses»; se cambia desde el panel (Bancos de los juegos) sin instalar nada.

  Formato de cada pose:

  - Una línea «## » con su id. Solo valen las seis que sabe detectar la cámara:
    brazos_arriba, un_brazo, pose_t, manos_cabeza, biceps y barbilla. Una pose nueva
    necesita su regla en el código (server/sonia/games/poses/rules.py).
  - «- orden:» la frase del meme, sin «Simón dice» (se añade sola). Hasta 60 caracteres.
  - «- pose:» la instrucción clara que va detrás, en minúsculas. Hasta 32 caracteres.
    Sale también en la pantalla, debajo del monigote.
  - «- demo:» (opcional) cómo la enseña Sonnia. Vacío: la pose hecha por código. El nombre
    de un clip de su set (como touchBeard): ese clip. «ninguna»: sin demostración.
  - «- activa:» (opcional) «sí» por defecto; «no» la deja fuera de las partidas.

  Sonia dice la orden así: «¡Simón dice: pasaron todos los tests, brazos arriba!». En las
  rondas trampa, sin «Simón dice»: «¡Pasaron todos los tests, brazos arriba!». Las dos
  versiones se graban con la voz de Sonia en «Preparar voces»: si cambias una frase, vuelve
  a prepararlas (si no, la dice en directo y tarda un poco más).

  Hacen falta al menos 3 poses activas. Una pose mal escrita se salta con un aviso.
-->

# Poses de «Simón dice»

## brazos_arriba
- orden: Pasaron todos los tests
- pose: brazos arriba
- demo:
- activa: sí

## un_brazo
- orden: Subiendo a producción
- pose: un brazo arriba
- demo:
- activa: sí

## pose_t
- orden: Pose T, la del avatar sin animar
- pose: brazos en cruz
- demo:
- activa: sí

## manos_cabeza
- orden: Deploy un viernes
- pose: manos a la cabeza
- demo:
- activa: sí

## biceps
- orden: Compiló a la primera
- pose: saquen bíceps
- demo:
- activa: sí

## barbilla
- orden: Revisando el PR
- pose: mano en la barbilla
- demo:
- activa: sí
