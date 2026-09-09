"""Historial de la conversación, acotado y sin imágenes viejas."""

from __future__ import annotations

from sonia.llm.messages import has_image, strip_images, system
from sonia.types import Message

__all__ = ["Conversation"]


class Conversation:
    """Guarda el historial y lo prepara para enviarlo al modelo.

    Dos reglas gobiernan lo que sale de :meth:`messages`:

    - Solo se conservan los últimos ``history_turns`` turnos del usuario. El
      corte cae siempre en el inicio de un turno, así que un mensaje del
      asistente con ``tool_calls`` nunca se separa de sus resultados.
    - Solo el último mensaje de usuario del turno actual conserva sus imágenes.
      Reenviar capturas antiguas dispara el prefill del modelo y añade latencia.
    """

    def __init__(self, system_prompt: str, history_turns: int) -> None:
        self._system_prompt = system_prompt
        self._history_turns = max(1, history_turns)
        self._history: list[Message] = []

    # -- estado ------------------------------------------------------------

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    def set_system_prompt(self, text: str) -> None:
        """Cambia el prompt de sistema sin tocar el historial."""
        self._system_prompt = text

    def reset(self) -> None:
        """Olvida la conversación (modo kiosco: nadie hereda el turno anterior)."""
        self._history.clear()

    def __len__(self) -> int:
        return len(self._history)

    # -- escritura ---------------------------------------------------------

    def add(self, message: Message) -> None:
        """Añade un mensaje ya construido y recorta el historial si hace falta."""
        self._history.append(message)
        self._truncate()

    def _turn_starts(self) -> list[int]:
        """Índices de los mensajes de usuario que abren un turno.

        Un mensaje de usuario que viene detrás de resultados de acciones (o de
        un asistente con ``tool_calls``) no abre turno: es la imagen que
        devolvió una acción dentro del turno en curso.
        """
        starts: list[int] = []
        for index, message in enumerate(self._history):
            if message.get("role") != "user":
                continue
            if index > 0:
                previous = self._history[index - 1]
                if previous.get("role") == "tool":
                    continue
                if previous.get("role") == "assistant" and previous.get("tool_calls"):
                    continue
            starts.append(index)
        return starts

    def _truncate(self) -> None:
        starts = self._turn_starts()
        if len(starts) <= self._history_turns:
            return
        cut = starts[len(starts) - self._history_turns]
        del self._history[:cut]

    # -- lectura -----------------------------------------------------------

    def messages(self) -> list[Message]:
        """Historial listo para el modelo, con el prompt de sistema delante."""
        keep_index = self._image_message_index()
        out: list[Message] = [system(self._system_prompt)]
        for index, message in enumerate(self._history):
            if index != keep_index and message.get("role") == "user" and has_image(message):
                out.append(strip_images(message))
            else:
                out.append(dict(message))
        return out

    def _image_message_index(self) -> int:
        """Índice del único mensaje de usuario que conserva sus imágenes.

        Es el último que las lleva, y solo si pertenece al turno en curso.
        """
        starts = self._turn_starts()
        last_start = starts[-1] if starts else 0
        for index in range(len(self._history) - 1, last_start - 1, -1):
            message = self._history[index]
            if message.get("role") == "user" and has_image(message):
                return index
        return -1
