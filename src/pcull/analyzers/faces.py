"""Closed-eye detection via MediaPipe FaceLandmarker blendshapes.

The model file (~15 MB) is downloaded once into ~/.pcull_models/. If mediapipe
or the model are unavailable, the analyzer reports itself as disabled and the
pipeline simply skips this dimension.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
              "face_landmarker/float16/1/face_landmarker.task")
_MODEL_PATH = Path.home() / ".pcull_models" / "face_landmarker.task"
_BLINK_THRESHOLD = 0.5  # blendshape score above this counts as a clear blink


def eyes_from_blendshapes(face_blendshapes) -> dict:
    """Parse per-face blink scores.

    mediapipe 1.x returns List[List[Category]] (each face is a flat Category
    list); some builds wrap a face in an object exposing .categories. Handle
    both.
    """
    n = len(face_blendshapes or [])
    if n == 0:
        return {"faces": 0, "eye_open_min": None, "closed_eye": 0}
    worst_open = 1.0
    closed = 0
    for face in face_blendshapes:
        categories = face.categories if hasattr(face, "categories") else face
        blink = {c.category_name: c.score for c in categories}
        blink_l = blink.get("eyeBlinkLeft", 0.0)
        blink_r = blink.get("eyeBlinkRight", 0.0)
        eye_open = 1.0 - max(blink_l, blink_r)
        worst_open = min(worst_open, eye_open)
        if max(blink_l, blink_r) >= _BLINK_THRESHOLD:
            closed = 1
    return {"faces": n, "eye_open_min": round(worst_open, 3), "closed_eye": closed}


class EyeAnalyzer:
    def __init__(self):
        self._lander = None
        self._mp: Any = None
        self.error: str | None = None
        try:
            import mediapipe as mp  # noqa: F401
            self._mp = mp
        except ImportError as e:
            self.error = f"mediapipe not installed: {e}"
            return
        try:
            if not _MODEL_PATH.exists():
                _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
                print(f"downloading face_landmarker model -> {_MODEL_PATH}")
                urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
            from mediapipe.tasks.python import vision as mp_vision

            options = mp_vision.FaceLandmarkerOptions(
                base_options=self._mp.tasks.BaseOptions(model_asset_path=str(_MODEL_PATH)),
                running_mode=mp_vision.RunningMode.IMAGE,
                num_faces=10,
                output_face_blendshapes=True,
            )
            self._lander = mp_vision.FaceLandmarker.create_from_options(options)
        except Exception as e:  # network failure, model corrupt, ...
            self.error = f"face landmarker unavailable: {e}"
            self._lander = None

    @property
    def enabled(self) -> bool:
        return self._lander is not None

    def analyze(self, img_rgb: np.ndarray) -> dict:
        """Return {faces, eye_open_min, closed_eye} — eyes measured per face."""
        if not self.enabled:
            return {"faces": None, "eye_open_min": None, "closed_eye": None}

        rgb = np.ascontiguousarray(img_rgb)
        result = self._lander.detect(
            self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        )
        return eyes_from_blendshapes(result.face_blendshapes)
