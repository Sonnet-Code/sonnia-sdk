"""Reconocer al equipo de Sonnet Code y a los ponentes del DevFest delante de la cámara (docs/caras.md).

Todo en este equipo, con OpenCV: ninguna foto sale ni se guarda, y de los
visitantes no queda nada. ``cv2`` se importa solo al cargar los modelos.
"""

from __future__ import annotations

from sonia.faces.book import (
    FaceBook,
    Greetings,
    Match,
    Person,
    known_people,
    load_greetings,
    load_staff,
    name_key,
    speakers_from,
)
from sonia.faces.model import Face, FaceModel, FaceModelError, ensure_models, models_ready
from sonia.faces.visits import Visit, VisitLog
from sonia.faces.watcher import (
    FaceWatcher,
    Probe,
    Sighting,
    arrival_text,
    join_labels,
    known_text,
)

__all__ = [
    "Face",
    "FaceBook",
    "FaceModel",
    "FaceModelError",
    "FaceWatcher",
    "Greetings",
    "Match",
    "Person",
    "Probe",
    "Sighting",
    "Visit",
    "VisitLog",
    "arrival_text",
    "ensure_models",
    "join_labels",
    "known_people",
    "known_text",
    "load_greetings",
    "load_staff",
    "models_ready",
    "name_key",
    "speakers_from",
]
