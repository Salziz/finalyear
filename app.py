from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, jsonify, render_template

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "cameras.json"

app = Flask(__name__)


def load_cameras() -> list[dict]:
    if not CONFIG_PATH.exists():
        return []
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    cameras = data.get("cameras", [])
    return [camera for camera in cameras if isinstance(camera, dict)]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/cameras")
def api_cameras():
    return jsonify({"cameras": load_cameras()})


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
