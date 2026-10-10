"""Lo que lee GPT-Live en la búsqueda relámpago: reglas, guiones y avisos.

Todo con «Sonia» (lo que oye y lee el modelo; en pantalla va «Sonnia») y sin nombrar el
stack. Las reglas (``RULES_TEXT``) entran por ``instruct`` y no pueden pasar de 1200
caracteres; lo demás son guiones (``speak`` o el resultado de una acción, que sale con
``PARA SONIA:``).
"""

from __future__ import annotations

__all__ = [
    "ALL_FOUND_TEXT",
    "ALREADY_TEXT",
    "BACK_TO_TALK_TEXT",
    "CANCEL_TEXT",
    "FINAL_TEXT",
    "FOUND_PHRASE",
    "FOUND_TEXT",
    "GO_PHRASE",
    "LOST_TEXT",
    "NEXT_TEXT",
    "NOT_YET_TEXT",
    "NO_ANSWER_TEXT",
    "NO_MORE_TEXT",
    "NOT_STARTED_TEXT",
    "RESUME_TEXT",
    "ROUND_TEXT",
    "RULES_TEXT",
    "SILENT_TEXT",
    "START_TEXT",
    "STILL_LOOKING_TEXT",
    "TIMEOUT_PHRASE",
    "TIMEOUT_TEXT",
    "WIN_CONTACT_TEXT",
    "WON_TEXT",
]

#: Las frases fijas con tiempo exacto: suenan grabadas (``cache/voice``) en el momento justo.
GO_PHRASE = "¡Ya!"
FOUND_PHRASE = "¡Lo veo!"
TIMEOUT_PHRASE = "¡Tiempo!"

#: Las reglas del juego, al empezar (``GameHost.instruct``: 1200 caracteres como mucho).
RULES_TEXT = """\
JUEGO EN MARCHA: búsqueda relámpago, {total} rondas de {seconds} segundos. En cada ronda hay un objeto que el grupo tiene que enseñar a la cámara (se ve en tu pantalla) y gana la ronda quien lo enseñe antes de que se acabe el tiempo.
- Tú no ves nada: el sistema mira la cámara y te avisa. No digas que lo ves ni que lo han encontrado hasta que te lo avise o lo diga el resultado de busqueda_check.
- Anuncia cada ronda con ganas, diciendo el objeto tal cual, y calla. El «¡Ya!» y el «¡Tiempo!» los pone el sistema: no los digas ni cuentes el tiempo. No preguntes si están listos.
- En plena ronda calla o anima con pocas palabras. Si alguien grita «¡aquí!», «¡ya lo tengo!» o te enseña algo, delega busqueda_check (sin argumentos) antes de decir nada: en la pantalla nada cambia si no lo delegas.
- No uses look en este juego. Al celebrar habla del objeto, nunca de la persona ni de su ropa, ni digas quién fue.
- Si quieren dejar de jugar, delega terminarlo."""

#: El guion de arranque (resultado de ``start_game``, o lo que se le pasa si empieza desde el panel).
START_TEXT = (
    "La búsqueda relámpago ya está en tu pantalla: {total} rondas de {seconds} segundos, y la "
    "cámara en vivo para que sepan dónde enseñar el objeto. Explícalo en una frase corta (el "
    "primero que te enseñe lo que pidas gana la ronda) y anuncia ya la ronda 1 de {total} con "
    "ganas: «¡El primero que me enseñe {name}!». No digas «¡ya!» ni preguntes si están listos: "
    "el sistema da la salida. Después calla."
)

#: Cada ronda nueva (a partir de la segunda), por ``speak``.
ROUND_TEXT = (
    "BÚSQUEDA, ronda {number} de {total}: anuncia con ganas, en una sola frase, «¡El primero "
    "que me enseñe {name}!». No digas «¡ya!» (lo pone el sistema) ni preguntes si están listos. "
    "Después calla."
)

#: Se ve el objeto de la ronda (``what`` ya filtrado: nada de la persona).
FOUND_TEXT = (
    "BÚSQUEDA: ¡lo han encontrado! En la cámara se ve «{what}». Ya ha sonado «¡Lo veo!» y ha "
    "salido el confeti: no lo repitas. Celébralo en una frase corta, hablando solo del objeto; "
    "nunca de la persona ni de su ropa, ni digas quién fue."
)

#: Se acabó el tiempo sin verlo.
TIMEOUT_TEXT = (
    "BÚSQUEDA: se acabó el tiempo y nadie enseñó {name}. Ya ha sonado «¡Tiempo!»: no lo "
    "repitas. Díselo con humor en una frase corta, sin culpar a nadie."
)

#: Se acabó el tiempo y la cámara no contestó a ninguna mirada: algo falla, no que nadie lo trajera.
SILENT_TEXT = (
    "BÚSQUEDA: se acabó el tiempo, pero en esta ronda la cámara no contestó a ninguna mirada: "
    "algo falla con ella. Ya ha sonado «¡Tiempo!»: no lo repitas. Dilo con humor en una frase "
    "corta, sin culpar a nadie, y di que lo seguís intentando."
)

#: La cámara no contestó en dos rondas seguidas: se cancela el juego.
CANCEL_TEXT = (
    "BÚSQUEDA: la cámara no responde y no se puede seguir jugando. Discúlpate con humor en una "
    "frase corta, di que el juego queda para otro momento y sigue conversando con normalidad."
)

#: Tras celebrar o lamentar una ronda que no es la última.
NEXT_TEXT = " Después calla: el sistema anuncia la siguiente ronda."

#: Tras la última ronda: cómo ha quedado la partida.
FINAL_TEXT = " Con esto termina el juego: han encontrado {found} de {total}."
ALL_FOUND_TEXT = " ¡Las {total} de {total}! Felicítalos a lo grande."
WON_TEXT = " Han llegado a la mitad o más: felicítalos con ganas."
LOST_TEXT = " No han llegado a la mitad: anímalos con cariño a intentarlo otra vez cuando quieran."
#: Sonia no sabe qué premios hay: a quien gana lo manda con el equipo del stand (como la trivia).
WIN_CONTACT_TEXT = (
    " Diles que pasen a hablar con {contact} aquí en el stand. No sabes qué premios hay: no "
    "prometas ninguno y, si preguntan, que se lo cuenten ellos."
)
BACK_TO_TALK_TEXT = " Luego sigue conversando con normalidad."

#: ``busqueda_check`` mientras la ronda aún no ha empezado (falta el «¡Ya!»).
NOT_STARTED_TEXT = (
    "Todavía no se ha dado la salida de la ronda. Dile con humor que espere al «¡Ya!» para "
    "enseñarlo. No digas que lo ves."
)

#: ``busqueda_check`` cuando la ronda ya terminó (o la está contando el sistema).
ALREADY_TEXT = (
    "Esta ronda ya terminó y su resultado ya se ha contado: no lo repitas ni digas que lo ves "
    "ahora. Espera a que el sistema anuncie la siguiente."
)

#: ``busqueda_check`` y no se ve el objeto.
NOT_YET_TEXT = (
    "Con la cámara no se ve todavía {name}. Dile en una frase corta que lo acerque, bien a la "
    "vista y quieto, y que siga buscando: quedan unos {left} segundos. No digas que lo ves."
)

#: ``busqueda_check`` y el modelo de visión no contestó.
NO_ANSWER_TEXT = (
    "La cámara no ha contestado esta vez. Pídele que lo intente otra vez, bien a la vista y "
    "quieto; el sistema sigue mirando. No digas que lo ves."
)

#: ``busqueda_check`` y ya no quedan miradas en esta ronda.
NO_MORE_TEXT = (
    "En esta ronda ya no se puede mirar más la cámara: solo queda esperar a que se acabe el "
    "tiempo. Dilo en una frase corta. No digas que lo ves."
)

#: ``busqueda_check`` mientras otra mirada tarda en contestar.
STILL_LOOKING_TEXT = (
    "La cámara está mirando justo ahora. Dile en una frase corta que aguante un momento "
    "enseñándolo; el sistema te avisa si lo ve. No digas que lo ves."
)

#: GPT-Live vuelve a delegar empezar el juego en marcha.
RESUME_TEXT = (
    "Ya estáis jugando a la búsqueda relámpago: ronda {number} de {total}, el objeto es "
    "{name}. No hace falta empezarla otra vez: sigue con la ronda."
)
