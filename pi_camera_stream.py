"""
Lightweight Raspberry Pi camera streamer for laptop-side real-time inference.

Runs a very small MJPEG HTTP server so the laptop can open the Pi camera as:
    http://<pi-ip>:8080/stream.mjpg

This avoids running DeepFace on the Pi. The Pi only captures and streams frames.
"""

from __future__ import annotations

import os
import threading
import time

import cv2
from flask import Flask, Response, jsonify


class PiCameraStreamer:
    def __init__(self):
        self.width = int(os.environ.get("STREAM_WIDTH", "640"))
        self.height = int(os.environ.get("STREAM_HEIGHT", "480"))
        self.fps = int(os.environ.get("STREAM_FPS", "12"))
        self.jpeg_quality = int(os.environ.get("STREAM_JPEG_QUALITY", "80"))
        self.lock = threading.Lock()
        self.frame = None
        self.running = False
        self.thread = None
        self._picam2 = None
        self._cap = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        self._cleanup()

    def get_frame(self):
        with self.lock:
            return self.frame

    def _init_camera(self):
        try:
            from picamera2 import Picamera2

            self._picam2 = Picamera2()
            config = self._picam2.create_video_configuration(
                main={"size": (self.width, self.height), "format": "BGR888"}
            )
            self._picam2.configure(config)
            self._picam2.start()
            print("[PiStream] Using Picamera2")
            return
        except Exception as exc:
            print(f"[PiStream] Picamera2 unavailable ({exc}) - trying cv2.VideoCapture")

        self._cap = cv2.VideoCapture(0)
        if self._cap.isOpened():
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            print("[PiStream] Using cv2.VideoCapture(0)")
            return

        self._cap = None
        raise RuntimeError("No usable camera found")

    def _grab_frame(self):
        if self._picam2 is not None:
            frame = self._picam2.capture_array()
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        if self._cap is not None and self._cap.isOpened():
            ok, frame = self._cap.read()
            if ok:
                return frame

        return None

    def _capture_loop(self):
        try:
            self._init_camera()
        except Exception as exc:
            print(f"[PiStream] Failed to start camera: {exc}")
            self.running = False
            return

        delay = 1.0 / max(self.fps, 1)
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]

        while self.running:
            frame = self._grab_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            frame = cv2.resize(frame, (self.width, self.height))
            ok, jpeg = cv2.imencode(".jpg", frame, encode_params)
            if ok:
                with self.lock:
                    self.frame = jpeg.tobytes()

            time.sleep(delay)

        self._cleanup()

    def _cleanup(self):
        if self._picam2 is not None:
            try:
                self._picam2.stop()
                self._picam2.close()
            except Exception:
                pass
            self._picam2 = None

        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None


app = Flask(__name__)
streamer = PiCameraStreamer()


def mjpeg_generator():
    while True:
        frame = streamer.get_frame()
        if frame:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
        time.sleep(0.03)


@app.route("/stream.mjpg")
def stream_mjpg():
    return Response(
        mjpeg_generator(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/health")
def health():
    return jsonify({"ok": streamer.running, "width": streamer.width, "height": streamer.height})


if __name__ == "__main__":
    host = os.environ.get("PI_STREAM_HOST", "0.0.0.0")
    port = int(os.environ.get("PI_STREAM_PORT", "8080"))
    streamer.start()
    app.run(host=host, port=port, threaded=True)
