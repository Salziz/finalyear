"""
seed_individuals.py — Populate DB with sample individuals and build SFace embeddings.

Run once before first launch (or after adding new enrolment folders):
    python seed_individuals.py

For real faces, place 10–30 photos per person in:
    static/captures/seed/<name>_samples/*.jpg

Example:
    static/captures/seed/salim_samples/001.jpg … 030.jpg
"""

from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from flask import Flask

from database import Individual, db, init_db
from recognizer import EMBEDDINGS_PATH, FaceRecognizer

BASE_DIR = Path(__file__).resolve().parent
SEED_PHOTOS_DIR = BASE_DIR / "static" / "captures" / "seed"


def create_placeholder_face(path: Path, label: int, name: str):
    """Generate a synthetic face for demo when no real photos exist."""
    img = np.zeros((240, 240, 3), dtype=np.uint8)
    base = (40 + label * 50) % 200
    img[:, :] = (base, base // 2, 100 + label * 30)
    cv2.ellipse(img, (120, 120), (70, 90), 0, 0, 360, (220, 200, 180), -1)
    cv2.circle(img, (95, 105), 12, (40, 40, 40), -1)
    cv2.circle(img, (145, 105), 12, (40, 40, 40), -1)
    cv2.ellipse(img, (120, 155), (25, 12), 0, 0, 180, (60, 40, 40), 2)
    cv2.putText(img, name[:12], (30, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)


def seed():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DIR / 'surveillance.db'}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    init_db(app)

    samples = [
        {
            "full_name": "Salim Abdulaziz",
            "id_number": "BDR-1001",
            "role": "Border Officer",
            "clearance_status": True,
            "face_encoding_label": 1,
            "file": "salim.jpg",
            "samples_dir": "salim_samples",
        },
        
        
        
    ]

    with app.app_context():
        Individual.query.delete()
        db.session.commit()

        for s in samples:
            samples_dir = SEED_PHOTOS_DIR / s["samples_dir"]
            samples_dir.mkdir(parents=True, exist_ok=True)

            # Placeholder only if folder has no real photos yet
            existing = list(samples_dir.glob("*.jpg")) + list(samples_dir.glob("*.png"))
            if not existing:
                for i in range(1, 6):
                    create_placeholder_face(
                        samples_dir / f"sample_{i:02d}.jpg",
                        s["face_encoding_label"],
                        s["full_name"],
                    )
                print(f"  Created 5 placeholder samples in {s['samples_dir']}/")
                existing = list(samples_dir.glob("*.jpg"))

            photo_abs = SEED_PHOTOS_DIR / s["file"]
            if not photo_abs.exists() and existing:
                photo_abs.write_bytes(existing[0].read_bytes())
            elif not photo_abs.exists():
                create_placeholder_face(photo_abs, s["face_encoding_label"], s["full_name"])

            rel_path = f"static/captures/seed/{s['file']}"
            db.session.add(
                Individual(
                    full_name=s["full_name"],
                    id_number=s["id_number"],
                    role=s["role"],
                    clearance_status=s["clearance_status"],
                    face_encoding_label=s["face_encoding_label"],
                    photo_path=rel_path,
                    registered_at=datetime.now(),
                )
            )

        db.session.commit()
        print("Inserted individuals into database.")

        recognizer = FaceRecognizer()
        if recognizer.train_from_database(app):
            print(f"SFace embeddings saved to {EMBEDDINGS_PATH}")
        else:
            print("Warning: embedding build failed — check sample folders under static/captures/seed/")


if __name__ == "__main__":
    seed()
