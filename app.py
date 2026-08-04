"""
app.py — Flask application entry point.

Registers HTTP routes (MJPEG feed, REST API, static files),
initializes SocketIO for real-time detection alerts, and starts
the camera background thread on launch.
"""

import os
from datetime import datetime
from pathlib import Path
import re
import shutil
from werkzeug.utils import secure_filename

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from flask_socketio import SocketIO

from camera import CameraManager, RECORDINGS_DIR
from database import Detection, Individual, RecordingSession, db, init_db
from recognizer import EMBEDDINGS_PATH, FaceRecognizer

BASE_DIR = Path(__file__).resolve().parent


def is_dev_mode() -> bool:
    """True when MOTION_SIMULATE=1 (laptop testing without PIR)."""
    return os.environ.get("MOTION_SIMULATE", "").lower() in ("1", "true", "yes")


def remote_node_token() -> str | None:
    """Optional shared secret for Raspberry Pi -> laptop requests."""
    token = os.environ.get("REMOTE_NODE_TOKEN", "").strip()
    return token or None


def remote_request_authorized(req) -> bool:
    """Allow remote sensor uploads when token is absent or matches."""
    token = remote_node_token()
    if token is None:
        return True

    supplied = (
        req.headers.get("X-Node-Token")
        or req.form.get("token")
        or req.args.get("token")
    )
    return supplied == token


app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "surveillance-dev-key")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DIR / 'surveillance.db'}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Allow threading mode for OpenCV + SocketIO on Windows
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Global camera manager (started once)
camera = CameraManager(socketio=socketio, app=app)
recognizer = FaceRecognizer()

# Initialize database tables on import (also safe when running via app.py)
init_db(app)


def mjpeg_generator():
    """Yield multipart JPEG chunks for browser <img src='/video_feed'>."""
    import time

    while True:
        frame = camera.get_frame()
        if frame:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
        time.sleep(0.05)


@app.route("/")
def index():
    """Single-page surveillance dashboard."""
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    """MJPEG stream consumed by live feed panel."""
    return Response(
        mjpeg_generator(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )
@app.route("/api/trigger-scan", methods=["POST"])
def api_trigger_scan():
    """
    Pi motion sensor calls this with no image — laptop captures its OWN
    webcam frame and runs recognition on it.
    """
    if not camera.running:
        return jsonify({"ok": False, "error": "Camera offline"}), 503
    result = camera.scan_now()
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route("/api/status")
def api_status():
    """Top status bar: camera, recording, DB, session duration."""
    db_ok = True
    try:
        Individual.query.first()
    except Exception:
        db_ok = False

    recording = camera.recording
    session_duration = 0
    start_str = None
    if camera.recording and camera.session_start_time:
        start_str = camera.session_start_time.strftime("%Y-%m-%d %H:%M:%S")
        session_duration = int(
            (datetime.now() - camera.session_start_time).total_seconds()
        )

    return jsonify(
        {
            "camera": "ONLINE" if camera.running else "OFFLINE",
            "recording": recording,
            "database": "CONNECTED" if db_ok else "ERROR",
            "session_duration_seconds": session_duration,
            "session_start": start_str,
            "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "dev_mode": is_dev_mode(),
        }
    )


@app.route("/api/scan", methods=["POST"])
def api_scan():
    """
    Manual face scan for laptop testing (dev mode only).
    Captures current frame, runs DeepFace SFace, emits WebSocket events.
    """
    if not is_dev_mode():
        return jsonify({"ok": False, "error": "Scan endpoint disabled outside dev mode"}), 403

    if not camera.running:
        return jsonify({"ok": False, "error": "Camera offline"}), 503

    result = camera.scan_now()
    status = 200 if result.get("ok") else 400
    return jsonify(result), status



@app.route("/api/remote-motion", methods=["POST"])
def api_remote_motion():
    """
    Raspberry Pi motion endpoint.

    Accepts a multipart `frame` image upload, runs recognition on the laptop,
    logs detections, and returns the same payload shape as `/api/scan`.
    """
    if not remote_request_authorized(request):
        return jsonify({"ok": False, "error": "Unauthorized remote node"}), 401

    frame_file = request.files.get("frame")
    if frame_file is None:
        return jsonify({"ok": False, "error": "Missing uploaded frame"}), 400

    payload = frame_file.read()
    if not payload:
        return jsonify({"ok": False, "error": "Uploaded frame is empty"}), 400

    import cv2
    import numpy as np

    frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return jsonify({"ok": False, "error": "Invalid image payload"}), 400

    result = camera.scan_frame(frame, source="remote_motion")
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route("/api/recording/start", methods=["POST"])
def start_recording():
    filename = camera.start_recording()
    if not filename:
        return jsonify({"error": "Already recording"}), 400
    return jsonify({"ok": True, "filename": filename})


@app.route("/api/recording/stop", methods=["POST"])
def stop_recording():
    filename = camera.stop_recording()
    if filename is None and not camera.recording:
        return jsonify({"ok": True, "message": "Stopped or was not recording"})
    return jsonify({"ok": True, "filename": filename})


@app.route("/api/sessions")
def list_sessions():
    """Timeline panel: all sessions newest first."""
    sessions = (
        RecordingSession.query.order_by(RecordingSession.start_time.desc()).all()
    )
    return jsonify([s.to_dict() for s in sessions])


@app.route("/api/sessions/<int:session_id>")
def get_session(session_id):
    session = RecordingSession.query.get_or_404(session_id)
    detections = (
        Detection.query.filter_by(recording_session_id=session_id)
        .order_by(Detection.detected_at.asc())
        .all()
    )
    return jsonify(
        {
            "session": session.to_dict(),
            "detections": [d.to_dict(include_individual=True) for d in detections],
            "playback_url": f"/recordings/{session.filename}",
        }
    )


@app.route("/recordings/<path:filename>")
def serve_recording(filename):
    """Stream saved recordings with correct MIME type for HTML5 playback."""
    if ".." in filename or filename.startswith("/"):
        abort(404)
    path = RECORDINGS_DIR / filename
    if not path.is_file():
        abort(404)

    mime = "video/mp4"
    if filename.lower().endswith(".webm"):
        mime = "video/webm"
    elif filename.lower().endswith(".avi"):
        mime = "video/x-msvideo"

    # conditional=True enables Range requests so the scrubber can seek
    return send_from_directory(
        RECORDINGS_DIR, filename, mimetype=mime, conditional=True
    )


@app.route("/api/detections/latest")
def latest_detection():
    """Most recent detection for initial page load."""
    det = Detection.query.order_by(Detection.detected_at.desc()).first()
    if not det:
        return jsonify(None)
    individual = det.individual
    data = det.to_dict()
    data["captured_image_url"] = f"/{det.captured_image_path.replace(chr(92), '/')}"
    if individual:
        data.update(
            {
                "full_name": individual.full_name,
                "id_number": individual.id_number,
                "role": individual.role,
                "clearance_status": individual.clearance_status,
                "profile_photo_url": f"/{individual.photo_path.replace(chr(92), '/')}",
            }
        )
    else:
        data.update(
            {
                "full_name": "UNKNOWN",
                "id_number": "N/A",
                "role": "Unidentified",
                "clearance_status": False,
                "profile_photo_url": data["captured_image_url"],
            }
        )
    return jsonify(data)


@app.route("/api/individuals")
def list_individuals():
    return jsonify([i.to_dict() for i in Individual.query.all()])


@app.route("/api/train", methods=["POST"])
def retrain_model():
    """Rebuild SFace embedding database from seed sample folders."""
    ok = recognizer.train_from_database(app)
    camera.recognizer = recognizer
    return jsonify({"ok": ok})


@app.route("/manifest.json")
def manifest():
    return send_from_directory(BASE_DIR, "manifest.json")


@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(BASE_DIR, "service-worker.js", mimetype="application/javascript")


@socketio.on("connect")
def on_connect():
    socketio.emit(
        "recording_status",
        {"recording": camera.recording},
    )


@socketio.on("dismiss_alert")
def dismiss_alert():
    socketio.emit("alert_dismissed", {})


if __name__ == "__main__":
    with app.app_context():
        # Train if possible; always refresh in-memory label cache for camera thread
        trained = recognizer.train_from_database(app)
        if not trained and EMBEDDINGS_PATH.exists():
            recognizer.load_model()
        recognizer.rebuild_label_map()
        camera.recognizer = recognizer

    camera.start()
    print("Border Surveillance PWA running at http://127.0.0.1:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
