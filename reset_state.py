"""
reset_state.py — Clear runtime data for a fresh test run.

Removes detection logs, recording sessions, and capture files.
Keeps registered individuals and the LBPH model intact.

Usage:
    python reset_state.py
"""

import shutil
from pathlib import Path

from flask import Flask

from database import Detection, RecordingSession, db, init_db

BASE_DIR = Path(__file__).resolve().parent
CAPTURES_DIR = BASE_DIR / "static" / "captures"
RECORDINGS_DIR = BASE_DIR / "static" / "recordings"
SEED_DIR = BASE_DIR / "static" / "captures" / "seed"


def clear_media_folder(folder: Path, keep_seed: bool = False):
    if not folder.exists():
        return
    for item in folder.iterdir():
        if keep_seed and item == SEED_DIR:
            continue
        if item.name == "seed":
            continue
        if item.is_file():
            item.unlink()
        elif item.is_dir() and item.name != "seed":
            shutil.rmtree(item)


def reset():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DIR / 'surveillance.db'}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    init_db(app)

    with app.app_context():
        deleted_detections = Detection.query.delete()
        deleted_sessions = RecordingSession.query.delete()
        db.session.commit()
        print(f"Deleted {deleted_detections} detection(s) and {deleted_sessions} session(s) from database.")

    clear_media_folder(CAPTURES_DIR)
    clear_media_folder(RECORDINGS_DIR)
    print("Cleared capture and recording files (seed photos kept).")
    print("Done — restart the server with: python app.py")


if __name__ == "__main__":
    reset()
