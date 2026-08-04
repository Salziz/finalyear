"""
database.py — SQLAlchemy models and SQLite initialization.

Defines three tables (individuals, recording_sessions, detections)
and helper functions to create the database and obtain sessions.
"""

from datetime import datetime
from pathlib import Path

from flask_sqlalchemy import SQLAlchemy

# Flask-SQLAlchemy extension instance (bound to app in app.py)
db = SQLAlchemy()

# Default SQLite file lives next to this module
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "surveillance.db"


class Individual(db.Model):
    """Registered person with LBPH label and clearance metadata."""

    __tablename__ = "individuals"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    id_number = db.Column(db.String(64), nullable=False, unique=True)
    role = db.Column(db.String(120), nullable=False)
    clearance_status = db.Column(db.Boolean, default=True, nullable=False)
    # Integer label used by LBPHFaceRecognizer during training/prediction
    face_encoding_label = db.Column(db.Integer, nullable=False, unique=True)
    photo_path = db.Column(db.String(512), nullable=False)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    detections = db.relationship("Detection", back_populates="individual")

    def to_dict(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "id_number": self.id_number,
            "role": self.role,
            "clearance_status": self.clearance_status,
            "face_encoding_label": self.face_encoding_label,
            "photo_path": self.photo_path,
            "registered_at": self._format_ts(self.registered_at),
        }

    @staticmethod
    def _format_ts(dt):
        if dt is None:
            return None
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class RecordingSession(db.Model):
    """One continuous video recording from Start to Stop."""

    __tablename__ = "recording_sessions"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(256), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    file_path = db.Column(db.String(512), nullable=False)
    detection_count = db.Column(db.Integer, default=0, nullable=False)

    detections = db.relationship("Detection", back_populates="recording_session")

    def to_dict(self):
        duration_sec = 0
        if self.start_time and self.end_time:
            duration_sec = int((self.end_time - self.start_time).total_seconds())
        return {
            "id": self.id,
            "filename": self.filename,
            "start_time": Individual._format_ts(self.start_time),
            "end_time": Individual._format_ts(self.end_time),
            "file_path": self.file_path,
            "detection_count": self.detection_count,
            "duration_seconds": duration_sec,
            "playback_url": f"/recordings/{self.filename}",
        }


class Detection(db.Model):
    """Log entry when a face is recognized or flagged as unknown."""

    __tablename__ = "detections"

    id = db.Column(db.Integer, primary_key=True)
    individual_id = db.Column(db.Integer, db.ForeignKey("individuals.id"), nullable=True)
    captured_image_path = db.Column(db.String(512), nullable=False)
    clearance_result = db.Column(db.String(32), nullable=False)  # CLEARED / NOT CLEARED
    detected_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    recording_session_id = db.Column(
        db.Integer, db.ForeignKey("recording_sessions.id"), nullable=True
    )

    individual = db.relationship("Individual", back_populates="detections")
    recording_session = db.relationship("RecordingSession", back_populates="detections")

    def to_dict(self, include_individual=False):
        data = {
            "id": self.id,
            "individual_id": self.individual_id,
            "captured_image_path": self.captured_image_path,
            "clearance_result": self.clearance_result,
            "detected_at": Individual._format_ts(self.detected_at),
            "recording_session_id": self.recording_session_id,
        }
        if include_individual and self.individual:
            data["individual"] = self.individual.to_dict()
        return data


def init_db(app):
    """Create tables inside an application context (safe to call once)."""
    # Avoid double-registration if init_db is invoked more than once
    if "sqlalchemy" not in app.extensions:
        db.init_app(app)
    with app.app_context():
        db.create_all()
