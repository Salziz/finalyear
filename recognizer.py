"""
recognizer.py — DeepFace SFace embedding-based face recognition.

Replaces LBPH with lightweight SFace embeddings (~200 MB RAM on Pi).
Enrollment scans sample folders under static/captures/seed/.
Recognition uses cosine distance; threshold 0.35 = match.
"""

from __future__ import annotations

import os
import pickle
import threading
from pathlib import Path

import cv2
import numpy as np

from database import Individual

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "static" / "models"
SEED_DIR = BASE_DIR / "static" / "captures" / "seed"
EMBEDDINGS_PATH = MODELS_DIR / "embeddings.pkl"

# Back-compat alias for app.py imports
LBPH_MODEL_PATH = EMBEDDINGS_PATH

HAAR_CASCADE_PATH = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"

# DeepFace model — SFace only (Pi-friendly)
DEEPFACE_MODEL = "SFace"
DETECTOR_BACKEND = "opencv"
DISTANCE_THRESHOLD = 0.593
MIN_FACE_SIZE = (60, 60)

# Suppress verbose TF logs on headless Pi
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).flatten()
    b = np.asarray(b, dtype=np.float64).flatten()
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 1.0
    return 1.0 - float(np.dot(a, b) / denom)


class FaceRecognizer:
    """Same public API as the former LBPH recognizer for app.py / camera.py."""

    def __init__(self):
        self.cascade = cv2.CascadeClassifier(str(HAAR_CASCADE_PATH))
        self._lock = threading.Lock()
        self._deepface_ready = False
        self._persons: list[dict] = []  # loaded from embeddings.pkl
        self._individual_by_label: dict[int, Individual] = {}
        self._label_map: dict[int, int] = {}
        self._last_overlay: list[dict] = []  # cached boxes between motion snapshots
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        if EMBEDDINGS_PATH.exists():
            self.load_model()

    # ------------------------------------------------------------------ utils
    def _ensure_deepface(self):
        if not self._deepface_ready:
            from deepface import DeepFace  # lazy import — saves RAM until first use

            self._DeepFace = DeepFace
            self._deepface_ready = True

    def detect_faces(self, gray_frame):
        faces = self.cascade.detectMultiScale(
            gray_frame,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=MIN_FACE_SIZE,
        )
        return faces

    def extract_face_roi(self, gray_frame, x, y, w, h):
        roi = gray_frame[y : y + h, x : x + w]
        return cv2.resize(roi, (200, 200))

    def _color_roi(self, frame, x, y, w, h):
        roi = frame[y : y + h, x : x + w]
        if roi.size == 0:
            return None
        return cv2.resize(roi, (200, 200))

    # ---------------------------------------------------------------- persistence
    def load_model(self):
        """Load embedding database from disk."""
        if not EMBEDDINGS_PATH.exists():
            return False
        try:
            with open(EMBEDDINGS_PATH, "rb") as fh:
                data = pickle.load(fh)
            self._persons = data.get("persons", [])
            return bool(self._persons)
        except Exception as exc:
            print(f"[Recognizer] Warning: Failed to load embeddings.pkl ({exc}). Treating as empty.")
            self._persons = []
            return False

    def save_model(self):
        """Persist embedding database."""
        payload = {
            "model_name": DEEPFACE_MODEL,
            "threshold": DISTANCE_THRESHOLD,
            "persons": self._persons,
        }
        with open(EMBEDDINGS_PATH, "wb") as fh:
            pickle.dump(payload, fh)

    def rebuild_label_map(self):
        """Refresh in-memory Individual cache (call inside app context)."""
        self._label_map = {}
        self._individual_by_label = {}
        for person in Individual.query.all():
            self._label_map[person.face_encoding_label] = person.id
            self._individual_by_label[person.face_encoding_label] = person

    # ---------------------------------------------------------------- enrollment
    def train_from_database(self, app):
        """Build embeddings.pkl from seed sample folders + DB individuals."""
        with app.app_context():
            return self._build_embeddings_from_seed()

    def _build_embeddings_from_seed(self) -> bool:
        self._ensure_deepface()
        individuals = Individual.query.all()
        self._persons = []

        if not SEED_DIR.exists():
            print(f"[Recognizer] Seed directory missing: {SEED_DIR}")
            return False

        sample_dirs = sorted(
            p for p in SEED_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")
        )

        for folder in sample_dirs:
            images = sorted(
                list(folder.glob("*.jpg"))
                + list(folder.glob("*.jpeg"))
                + list(folder.glob("*.png"))
            )
            if not images:
                continue

            individual = self._match_folder_to_individual(folder.name, individuals)
            vectors = []
            for img_path in images:
                emb = self._embed_image_file(img_path)
                if emb is not None:
                    vectors.append(emb)

            if not vectors:
                print(f"[Recognizer] No embeddings extracted for {folder.name}")
                continue

            mean_emb = np.mean(vectors, axis=0)
            label = individual.face_encoding_label if individual else len(self._persons) + 1

            self._persons.append(
                {
                    "folder_name": folder.name,
                    "individual_id": individual.id if individual else None,
                    "face_encoding_label": label,
                    "display_name": individual.full_name if individual else folder.name,
                    "embedding": mean_emb.tolist(),
                }
            )
            print(f"[Recognizer] Enrolled {folder.name} ({len(vectors)} samples)")

        if not self._persons:
            return False

        self.save_model()
        self.rebuild_label_map()
        print(f"[Recognizer] Saved {len(self._persons)} person(s) -> {EMBEDDINGS_PATH}")
        return True

    def _match_folder_to_individual(self, folder_name: str, individuals: list) -> Individual | None:
        stem = folder_name.replace("_samples", "").lower()
        for person in individuals:
            photo_stem = Path(person.photo_path).stem.lower()
            name_slug = person.full_name.lower().replace(" ", "_")
            if stem == photo_stem or stem in photo_stem or stem == name_slug:
                return person
            if folder_name.lower().startswith(photo_stem):
                return person
        return None

    def _embed_image_file(self, path: Path) -> np.ndarray | None:
        try:
            with self._lock:
                reps = self._DeepFace.represent(
                    img_path=str(path),
                    model_name=DEEPFACE_MODEL,
                    detector_backend=DETECTOR_BACKEND,
                    enforce_detection=False,
                )
            if reps:
                return np.array(reps[0]["embedding"], dtype=np.float64)
        except Exception as exc:
            print(f"[Recognizer] Embed failed for {path.name}: {exc}")
        return None

    def _embed_bgr_array(self, bgr_image: np.ndarray) -> np.ndarray | None:
        try:
            rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
            with self._lock:
                reps = self._DeepFace.represent(
                    img_path=rgb,
                    model_name=DEEPFACE_MODEL,
                    detector_backend=DETECTOR_BACKEND,
                    enforce_detection=False,
                )
            if reps:
                return np.array(reps[0]["embedding"], dtype=np.float64)
        except Exception as exc:
            print(f"[Recognizer] Snapshot embed failed: {exc}")
        return None

    # ---------------------------------------------------------------- recognition
    def recognize_face(self, face_roi_gray):
        """
        Match a face crop against the embedding database.
        Accepts grayscale ROI for API compatibility; converts internally.
        """
        if not self._persons:
            return self._unknown_result()

        bgr = cv2.cvtColor(face_roi_gray, cv2.COLOR_GRAY2BGR)
        return self._match_embedding(bgr)

    def _match_embedding(self, face_bgr: np.ndarray) -> dict:
        if not self._persons:
            return self._unknown_result()

        self._ensure_deepface()
        query = self._embed_bgr_array(face_bgr)
        if query is None:
            return self._unknown_result()

        best_dist = 999.0
        best_person = None
        for entry in self._persons:
            ref = np.array(entry["embedding"], dtype=np.float64)
            dist = _cosine_distance(query, ref)
            print(f"[DEBUG] {entry['display_name']}: distance={dist:.4f} (threshold={DISTANCE_THRESHOLD})")
            if dist < best_dist:
                best_dist = dist
                best_person = entry

        if best_dist >= DISTANCE_THRESHOLD or best_person is None:
            return self._unknown_result(confidence=float(best_dist))

        label = best_person["face_encoding_label"]
        individual = self._individual_by_label.get(label)

        if individual is None:
            return self._unknown_result(confidence=float(best_dist))

        cleared = "CLEARED" if individual.clearance_status else "NOT CLEARED"
        return {
            "matched": True,
            "individual": individual,
            "label": label,
            "confidence": float(best_dist),
            "clearance_result": cleared,
            "display_name": individual.full_name,
            "box_color": (0, 255, 0) if cleared == "CLEARED" else (0, 0, 255),
        }

    def _unknown_result(self, confidence: float = 999.0) -> dict:
        return {
            "matched": False,
            "individual": None,
            "label": -1,
            "confidence": confidence,
            "clearance_result": "NOT CLEARED",
            "display_name": "UNKNOWN",
            "box_color": (0, 0, 255),
        }

    def process_frame(self, frame, analyze: bool = False):
        """
        Draw face boxes on frame.

        analyze=False  → MJPEG stream only; reuse last overlay (no DeepFace).
        analyze=True   → motion snapshot; run DeepFace on detected faces once.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.detect_faces(gray)
        results = []

        if analyze and faces is not None and len(faces) > 0:
            for (x, y, w, h) in faces:
                color_roi = self._color_roi(frame, x, y, w, h)
                if color_roi is None:
                    continue
                match = self._match_embedding(color_roi)
                gray_roi = self.extract_face_roi(gray, x, y, w, h)
                results.append({"bbox": (x, y, w, h), "match": match, "roi": gray_roi, "color_roi": color_roi})
            self._last_overlay = results
        else:
            results = list(self._last_overlay)

        for det in results:
            x, y, w, h = det["bbox"]
            match = det["match"]
            color = match["box_color"]
            name = match["display_name"]
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.rectangle(frame, (x, y - 25), (x + w, y), color, cv2.FILLED)
            cv2.putText(
                frame,
                name,
                (x + 5, y - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

        # Only return detections for DB logging when we actually analyzed
        return frame, results if analyze else []
