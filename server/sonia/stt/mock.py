"""STT falso para tests y para `sonia chat` (sin micrófono ni modelos)."""

from __future__ import annotations

from collections.abc import Iterable

from sonia.stt.base import Utterance


class MockSTT:
    """Devuelve textos predefinidos en orden; el último se repite indefinidamente.

    >>> stt = MockSTT(["hola", "adiós"])
    """

    def __init__(self, texts: Iterable[str] | str = "hola sonia") -> None:
        if isinstance(texts, str):
            self._texts: list[str] = [texts]
        else:
            self._texts = list(texts)
        self._index = 0
        #: Turnos recibidos, por si un test quiere inspeccionarlos.
        self.calls: list[Utterance] = []

    @property
    def texts(self) -> list[str]:
        return list(self._texts)

    async def transcribe(self, utterance: Utterance) -> str:
        self.calls.append(utterance)
        return self.next_text()

    def next_text(self) -> str:
        """Siguiente texto de la cola; al agotarse repite el último (o cadena vacía)."""
        if not self._texts:
            return ""
        index = min(self._index, len(self._texts) - 1)
        self._index += 1
        return self._texts[index]

    def reset(self) -> None:
        self._index = 0
        self.calls.clear()
