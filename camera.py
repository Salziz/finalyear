"""
camera.py — OpenCV capture, MJPEG streaming, recording, and frame pipeline.

Runs a background thread that continuously grabs frames, applies face
recognition overlays, burns in a timestamp, and optionally writes to disk.
"""

import os
import threading
import time
from datetime import datetime
from pathlib import Path
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

import cv2
import imageio
import numpy as np

from database import Detection, RecordingSession, db
from motion_sensor import MotionSensor
from recognizer import FaceRecognizer

BASE_DIR = Path(__file__).resolve().parent
RECORDINGS_DIR = BASE_DIR / "static" / "recordings"
CAPTURES_DIR = BASE_DIR / "static" / "captures"

# Seconds between repeated detections for the same person (reduces DB spam)
DETECTION_COOLDOWN_SEC = 4.0
EMAIL_SENDER = "abdulazizsalim155@gmail.com"
EMAIL_PASSWORD = "pccf uice avfq jlum"
EMAIL_RECEIVER = "idrismuadh77@gmail.com"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465


class CameraManager:
    """Thread-safe camera + recording + recognition coordinator."""

    def __init__(self, socketio=None, app=None):
        self.socketio = socketio
        self.app = app
        self.recognizer = FaceRecognizer()
        self.motion = MotionSensor()
        self.lock = threading.Lock()
        self.frame = None
        self._latest_bgr = None  # raw frame for manual /api/scan snapshots
        self.running = False
        self.thread = None
        self.recording = False
        self.recording_writer = None  # imageio H.264 MP4 writer
        self.current_session_id = None  # plain int — safe across threads/contexts
        self.session_start_time = None    # datetime when recording began
        self._last_detection_keys = {}  # cooldown tracker
        self.fps = 20
        self.width = 640
        self.height = 480
        # 0 = default webcam; set VIDEO_SOURCE=file.mp4 for testing without camera
        _video_source_raw = os.environ.get("VIDEO_SOURCE", "0")
        try:
            self.video_source = int(_video_source_raw)  # numeric webcam index
        except ValueError:
            self.video_source = _video_source_raw  # treat as URL/path string
        # Auto-recording state (motion-triggered sessions)
        self._auto_recording = False          # True when motion started this session
        self._motion_stop_timer: threading.Timer | None = None  # countdown to auto-stop
        self._auto_stop_delay = 10.0          # seconds after last motion to stop

    def start(self):
        """Begin background capture thread."""
        if self.running:
            return
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop thread and release camera."""
        self.running = False
        if self.recording:
            self.stop_recording()
        if self.thread:
            self.thread.join(timeout=2.0)
        self.motion.cleanup()

    def get_frame(self):
        """Latest JPEG bytes for MJPEG stream."""
        with self.lock:
            if self.frame is None:
                return None
            return self.frame

    def _capture_loop(self):
        """
        Capture frames from either a Raspberry Pi CSI camera (Picamera2) or a
        regular webcam (cv2.VideoCapture), with automatic fallback.

        Priority:
          1. Picamera2  — used when running on a Pi with a CSI camera attached.
          2. cv2.VideoCapture(VIDEO_SOURCE) — used on any other platform.
          3. Synthetic test pattern — used when neither camera opens successfully.
        """
        picam2 = None
        cap = None

        # ── 1. Try Picamera2 (Raspberry Pi CSI) ────────────────────────────
        try:
            from picamera2 import Picamera2  # only available on Pi
            picam2 = Picamera2()
            config = picam2.create_video_configuration(
                main={"size": (self.width, self.height), "format": "RGB888"}
            )
            picam2.configure(config)
            picam2.start()
            print("[Camera] Using Picamera2 (CSI camera)")
        except Exception as exc:
            # Not a Pi, no CSI camera, or picamera2 not installed — fall back
            print(f"[Camera] Picamera2 unavailable ({exc}) — trying cv2.VideoCapture")
            if picam2 is not None:
                try:
                    picam2.close()
                except Exception:
                    pass
            picam2 = None

        # ── 2. Fall back to cv2.VideoCapture ───────────────────────────────
        # ── 2. Fall back to cv2.VideoCapture ───────────────────────────────
        if picam2 is None:
            if isinstance(self.video_source, str) and self.video_source.startswith("http"):
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|timeout;60000000"
            cap = cv2.VideoCapture(self.video_source)
            if not cap.isOpened():
                # ── 3. Synthetic test pattern (demo / CI) ──────────────────
                cap = None
                print("[Camera] No camera found — running in test-pattern demo mode")
            else:
                print(f"[Camera] Using cv2.VideoCapture (source={self.video_source})")

        def grab_frame():
            """Return the next BGR frame, or None if a transient read failure."""
            if picam2 is not None:
                # capture_array() returns RGB888 ndarray; convert to BGR for OpenCV
                rgb = picam2.capture_array()
                return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            if cap is not None and cap.isOpened():
                ret, bgr = cap.read()
                return bgr if ret else None
            # No real camera — return None so the loop falls through to test pattern
            return None

        while self.running:
            try:
                img = grab_frame()
                if img is None:
                    if picam2 is None and cap is not None:
                        # Transient cv2 read failure — wait and retry
                        time.sleep(0.05)
                        continue
                    # No camera at all — generate test pattern
                    img = self._generate_test_pattern()

                img = cv2.resize(img, (self.width, self.height))
                with self.lock:
                    self._latest_bgr = img.copy()

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # DeepFace runs only on PIR motion snapshot — not every frame
                motion_detected = self.motion.check()

                # ── Auto-recording: start on first motion, reset stop timer ──
                if motion_detected:
                    self._on_motion_detected()

                processed, detections = self.recognizer.process_frame(
                    img.copy(), analyze=motion_detected
                )
                self._draw_timestamp(processed, timestamp)

                if self.recording and self.recording_writer is not None:
                    rgb = cv2.cvtColor(processed, cv2.COLOR_BGR2RGB)
                    self.recording_writer.append_data(rgb)

                for det in detections:
                    self._handle_detection(det, timestamp)

                ok, jpeg = cv2.imencode(
                    ".jpg", processed, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
                )
                if ok:
                    with self.lock:
                        self.frame = jpeg.tobytes()
            except Exception as exc:
                # Log but keep capture loop alive so MJPEG feed never dies silently
                print(f"[Camera] Frame error (recovering): {exc}")

            time.sleep(1.0 / self.fps)

        # ── Cleanup ────────────────────────────────────────────────────────
        if picam2 is not None:
            try:
                picam2.stop()
                picam2.close()
            except Exception:
                pass
        if cap is not None:
            cap.release()

    def _generate_test_pattern(self):
        """Colored gradient frame when webcam unavailable."""
        t = time.time()
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        for y in range(self.height):
            img[y, :, 0] = int(128 + 127 * np.sin(t + y * 0.02))
            img[y, :, 1] = int(64 + 64 * np.cos(t))
            img[y, :, 2] = 40
        cv2.putText(
            img,
            "NO CAMERA - DEMO MODE",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )
        return img

    def _draw_timestamp(self, frame, timestamp):
        """Burn date/time into bottom-left of frame."""
        cv2.rectangle(frame, (5, frame.shape[0] - 35), (320, frame.shape[0] - 5), (0, 0, 0), -1)
        cv2.putText(
            frame,
            timestamp,
            (10, frame.shape[0] - 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    # ---------------------------------------------------------------- auto-recording
    def _on_motion_detected(self):
        """
        Called each time the PIR sensor fires (or /api/scan is triggered).
        Starts recording if not already active; resets the auto-stop countdown.
        """
        if not self.recording:
            self.start_recording()
            self._auto_recording = True
            print("[Camera] Auto-recording STARTED by motion")
        elif not self._auto_recording:
            # Manual recording is already running — don't interfere, just skip timer
            return

        # Reset the 10-second auto-stop countdown
        self._arm_stop_timer()

    def _arm_stop_timer(self):
        """Cancel any existing stop timer and start a fresh 10-second countdown."""
        if self._motion_stop_timer is not None:
            self._motion_stop_timer.cancel()
        self._motion_stop_timer = threading.Timer(
            self._auto_stop_delay, self._auto_stop_recording
        )
        self._motion_stop_timer.daemon = True
        self._motion_stop_timer.start()

    def _auto_stop_recording(self):
        """Timer callback — fires 10 s after last motion; stops auto-started session."""
        if self.recording and self._auto_recording:
            print("[Camera] Auto-recording STOPPED (10 s after last motion)")
            self._auto_recording = False
            self.stop_recording()
        self._motion_stop_timer = None
    def scan_frame(self, frame_bgr, source="remote_motion"):
        """
        Scan an externally supplied BGR frame (e.g. from the Raspberry Pi).
        Supports split deployment where the Pi captures the image and the
        laptop performs recognition.
        """
        if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
            return {"ok": False, "error": "Empty frame supplied"}
        img = cv2.resize(frame_bgr, (self.width, self.height))
        with self.lock:
            self._latest_bgr = img.copy()
        self._on_motion_detected()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        processed, detections = self.recognizer.process_frame(img.copy(), analyze=True)
        self._draw_timestamp(processed, timestamp)
        ok, jpeg = cv2.imencode(
            ".jpg", processed, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
        )
        if ok:
            with self.lock:
                self.frame = jpeg.tobytes()
        payloads = []
        for det in detections:
            payload = self._handle_detection(det, timestamp, force=True)
            if payload:
                payloads.append(payload)
        if not payloads:
            return {
                "ok": True,
                "source": source,
                "faces_detected": len(detections),
                "message": "No faces detected" if not detections else "No new detection logged",
                "detections": [],
            }
        return {
            "ok": True,
            "source": source,
            "faces_detected": len(detections),
            "detections": payloads,
            "primary": payloads[-1],
        }
    def scan_now(self):
        """
        Manual snapshot scan (dev /api/scan).
        Auto-starts recording, runs DeepFace on the latest frame, updates overlay
        + MJPEG, emits WebSocket events, and schedules auto-stop 10 s later.
        """
        with self.lock:
            if self._latest_bgr is None:
                return {"ok": False, "error": "No camera frame available yet"}
            img = self._latest_bgr.copy()

        # Treat /api/scan exactly like a motion event (auto-record + reset timer)
        self._on_motion_detected()

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        processed, detections = self.recognizer.process_frame(img.copy(), analyze=True)
        self._draw_timestamp(processed, timestamp)

        ok, jpeg = cv2.imencode(
            ".jpg", processed, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
        )
        if ok:
            with self.lock:
                self.frame = jpeg.tobytes()

        payloads = []
        for det in detections:
            payload = self._handle_detection(det, timestamp, force=True)
            if payload:
                payloads.append(payload)

        if not payloads:
            return {
                "ok": True,
                "faces_detected": len(detections),
                "message": "No faces detected" if not detections else "No new detection logged",
                "detections": [],
            }

        return {
            "ok": True,
            "faces_detected": len(detections),
            "detections": payloads,
            "primary": payloads[-1],
        }
    def _send_email_alert(self, name, capture_path):
        """Send an email alert for a NOT CLEARED detection."""
        try:
            msg = MIMEMultipart()
            msg["Subject"] = "ALERT: Uncleared Individual Detected"
            msg["From"] = EMAIL_SENDER
            msg["To"] = EMAIL_RECEIVER
            body = (
                f"BORDER SURVEILLANCE ALERT\n\n"
                f"Name: {name}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Status: NOT CLEARED\n\n"
                f"Please review the attached image."
            )
            msg.attach(MIMEText(body, "plain"))
            with open(capture_path, "rb") as f:
                img = MIMEImage(f.read())
                img.add_header("Content-Disposition", "attachment", filename="alert.jpg")
                msg.attach(img)
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
            print(f"[Email] Alert sent for {name}")
        except Exception as e:
            print(f"[Email] Failed: {e}")

    def _handle_detection(self, det, timestamp_str, force=False):
        """Log detection, save capture, emit WebSocket if not on cooldown."""
        match = det["match"]
        individual = match.get("individual")
        key = (
            individual.id
            if individual
            else f"unknown_{det['bbox'][0]}_{det['bbox'][1]}"
        )
        now = time.time()
        if not force and key in self._last_detection_keys:
            if now - self._last_detection_keys[key] < DETECTION_COOLDOWN_SEC:
                return None
        self._last_detection_keys[key] = now

        if not self.app:
            return None

        with self.app.app_context():
            capture_name = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
            capture_path = CAPTURES_DIR / capture_name
            # Save an upscaled color crop for a clearer, brighter-looking capture
            roi = det.get("color_roi")
            if roi is None:
                roi = det["roi"]  # fallback to grayscale if color unavailable
            roi_large = cv2.resize(roi, (400, 400), interpolation=cv2.INTER_CUBIC)
            cv2.imwrite(str(capture_path), roi_large, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

            rel_capture = f"static/captures/{capture_name}"
            session_id = self.current_session_id

            detection = Detection(
                individual_id=individual.id if individual else None,
                captured_image_path=rel_capture,
                clearance_result=match["clearance_result"],
                detected_at=datetime.now(),
                recording_session_id=session_id,
            )
            db.session.add(detection)

            if session_id is not None:
                session = db.session.get(RecordingSession, session_id)
                if session:
                    session.detection_count += 1

            db.session.commit()

            payload = self._build_detection_payload(detection, individual, rel_capture)

            if self.socketio:
                self.socketio.emit("detection", payload)
                if match["clearance_result"] == "NOT CLEARED":
                    
                    self.socketio.emit(
                        "alert",
                        {
                            "message": f"UNCLEARED INDIVIDUAL DETECTED — {timestamp_str}",
                            "timestamp": timestamp_str,
                            "detection_id": detection.id,
                        },
                    )
                    self._send_email_alert(payload.get("full_name", "UNKNOWN"), str(capture_path))
            return payload

    def _build_detection_payload(self, detection, individual, rel_capture):
        """JSON-safe dict for right-panel ID card."""
        data = detection.to_dict()
        data["captured_image_url"] = f"/{rel_capture.replace(chr(92), '/')}"
        if individual:
            data["full_name"] = individual.full_name
            data["id_number"] = individual.id_number
            data["role"] = individual.role
            data["clearance_status"] = individual.clearance_status
            data["profile_photo_url"] = f"/{individual.photo_path.replace(chr(92), '/')}"
        else:
            data["full_name"] = "UNKNOWN"
            data["id_number"] = "N/A"
            data["role"] = "Unidentified"
            data["clearance_status"] = False
            data["profile_photo_url"] = data["captured_image_url"]
        return data

    def start_recording(self):
        """Start H.264 MP4 recording (browser-playable via bundled ffmpeg).

        Can be called manually (from /api/recording/start) or automatically
        by _on_motion_detected().  In both cases the session is stored in DB
        and linked to any detections that occur during the recording.
        """
        if self.recording:
            return None

        start = datetime.now()
        filename = f"rec_{start.strftime('%Y%m%d_%H%M%S')}.mp4"
        rel_path = f"static/recordings/{filename}"
        full_path = RECORDINGS_DIR / filename

        try:
            writer = imageio.get_writer(
                str(full_path),
                fps=self.fps,
                codec="libx264",
                format="FFMPEG",
                pixelformat="yuv420p",  # required for Chrome / Edge / Firefox
                macro_block_size=1,
            )
        except Exception as exc:
            print(f"[Camera] ERROR: Could not start MP4 recorder: {exc}")
            return None

        self.recording_writer = writer
        self.recording = True
        print(f"[Camera] Recording H.264 MP4 → {filename}")

        if self.app:
            with self.app.app_context():
                session = RecordingSession(
                    filename=filename,
                    start_time=start,
                    end_time=None,
                    file_path=rel_path,
                    detection_count=0,
                )
                db.session.add(session)
                db.session.commit()
                self.current_session_id = session.id
                self.session_start_time = start

        if self.socketio:
            self.socketio.emit(
                "recording_status",
                {"recording": True, "filename": filename, "start_time": start.strftime("%Y-%m-%d %H:%M:%S")},
            )
        return filename

    def stop_recording(self):
        """Finalize video file and session end time.

        Can be called manually (from /api/recording/stop) or automatically
        by _auto_stop_recording() after the motion idle timeout.
        """
        if not self.recording:
            return None

        # If a manual stop is requested, cancel any pending auto-stop timer
        if self._motion_stop_timer is not None:
            self._motion_stop_timer.cancel()
            self._motion_stop_timer = None
        self._auto_recording = False

        self.recording = False
        if self.recording_writer is not None:
            try:
                self.recording_writer.close()
            except Exception as exc:
                print(f"[Camera] Warning closing recorder: {exc}")
            self.recording_writer = None

        end = datetime.now()
        filename = None
        session_dict = None
        session_id = self.current_session_id

        if self.app and session_id is not None:
            with self.app.app_context():
                session = RecordingSession.query.get(session_id)
                if session:
                    session.end_time = end
                    db.session.commit()
                    filename = session.filename
                    session_dict = session.to_dict()
                self.current_session_id = None
                self.session_start_time = None

        if self.socketio:
            self.socketio.emit(
                "recording_status",
                {
                    "recording": False,
                    "end_time": end.strftime("%Y-%m-%d %H:%M:%S"),
                    "session": session_dict,
                },
            )
        return filename
