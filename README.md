# Border Surveillance PWA

Full-stack border surveillance web interface with live MJPEG feed, LBPH facial identification, recording timeline, and real-time WebSocket alerts.

## Stack

| Layer | Technology |
|-------|------------|
| Backend | Python, Flask, Flask-SocketIO |
| Frontend | HTML, CSS, Vanilla JS |
| Database | SQLite + SQLAlchemy |
| Vision | OpenCV Haar + DeepFace SFace |
| Real-time | WebSockets |

## Project structure

```
surveillance-app/
  app.py              # Flask routes + SocketIO
  database.py         # SQLAlchemy models
  recognizer.py       # DeepFace SFace embeddings
  motion_sensor.py    # PIR GPIO trigger (Pi)
  camera.py           # Capture, recording, MJPEG frames
  seed_individuals.py # Sample data + model training
  templates/index.html
  static/css/styles.css
  static/js/main.js, socket.js, timeline.js
  static/recordings/  # Saved .mp4 files (H.264, browser-playable)
  static/captures/    # Detection stills
  static/models/      # embeddings.pkl
  manifest.json
  service-worker.js
```

## Setup (Windows / macOS / Linux)

### 1. Create virtual environment

```bash
cd surveillance-app
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** Uses `opencv-python` (not contrib) plus `deepface` and `tf-keras`. SFace model only.

### 3. Enrol faces and build embeddings

Place sample photos per person:

```
static/captures/seed/salim_samples/001.jpg … 030.jpg
```

Then run:

```bash
python generate_icons.py
python seed_individuals.py
```

This registers individuals in SQLite and builds `static/models/embeddings.pkl`.

### 4. Run the server

```bash
python app.py
```

Open **http://127.0.0.1:5000** in Chrome or Edge (recommended for PWA install).

### 5. Install as PWA (optional)

Use the browser menu **Install app** / **Add to Home screen**. The service worker caches the UI shell for offline viewing; live camera and API still need the server running.

## Camera options

| Variable | Default | Description |
|----------|---------|-------------|
| `VIDEO_SOURCE` | `0` | Webcam index, video file path, or remote stream URL |

```bash
# Use a test video file instead of webcam
set VIDEO_SOURCE=path\to\test.mp4
python app.py
```

```bash
# Use a Raspberry Pi camera stream from the laptop
set VIDEO_SOURCE=http://<pi-ip>:8080/stream.mjpg
python app.py
```

If no camera is available, the app shows a **demo gradient frame** so you can still test recording and UI.

## Enrolling new individuals (DeepFace SFace)

1. Create a sample folder with 10–30 face photos:

```
static/captures/seed/newperson_samples/001.jpg …
```

2. Register the person in the database (unique `face_encoding_label`):

```python
from app import app
from database import db, Individual
from datetime import datetime

with app.app_context():
    p = Individual(
        full_name="New Person",
        id_number="BDR-2001",
        role="Contractor",
        clearance_status=True,
        face_encoding_label=4,
        photo_path="static/captures/seed/newperson.jpg",
        registered_at=datetime.now(),
    )
    db.session.add(p)
    db.session.commit()
```

3. Rebuild embeddings:

```bash
curl -X POST http://127.0.0.1:5000/api/train
```

### Recognition rules

- Cosine distance **below 0.35** → matched to enrolled person
- Matched + `clearance_status=True` → **CLEARED** (green box)
- Matched + `clearance_status=False` → **NOT CLEARED** (red box)
- Distance **≥ 0.35** or unknown → **UNKNOWN / NOT CLEARED** (red box)

### Motion trigger (PIR)

Recognition runs on **motion snapshots only** (not every frame). On Raspberry Pi, wire PIR OUT to GPIO 17 (BCM).

| Variable | Default | Description |
|----------|---------|-------------|
| `PIR_GPIO_PIN` | `17` | BCM pin for PIR sensor |
| `MOTION_SIMULATE` | off | Set `1` on dev PC to fake motion every 8s |
| `MOTION_SIMULATE_INTERVAL` | `8` | Seconds between simulated triggers |
| `REMOTE_NODE_TOKEN` | unset | Optional shared secret for Pi uploads to `/api/remote-motion` |

## Recommended presentation setup

If the Raspberry Pi becomes unstable while running DeepFace, use a **split deployment**:

1. **Laptop**
   - Run `python app.py`
   - Store the database, recordings, UI, and face-recognition model here
   - Set `VIDEO_SOURCE` to the Pi camera stream URL if you want the dashboard live feed to show the Pi camera

2. **Raspberry Pi**
   - Keep the PIR sensor, camera, and SIM module connected here
   - On motion, capture one JPEG frame and `POST` it to the laptop's `/api/remote-motion` endpoint
   - Optionally keep SMS / GSM alert logic on the Pi, using the laptop response to decide when to send

This removes the heavy face-recognition workload from the Pi while preserving the real hardware demonstration.

## Real-time laptop inference

If you want **live** recognition instead of motion-snapshot uploads, use the Pi as a camera streamer and the laptop as the inference server.

### 1. Start the Pi camera streamer

On the Raspberry Pi:

```bash
cd ~/surveillance-app
source venv/bin/activate
python pi_camera_stream.py
```

This exposes the camera at:

```text
http://<pi-ip>:8080/stream.mjpg
```

### 2. Start continuous recognition on the laptop

On the laptop PowerShell:

```powershell
cd C:\Users\abdul\flutterprojects\finalyearproj1\surveillance-app
.\venv\Scripts\Activate.ps1
$env:VIDEO_SOURCE="http://<pi-ip>:8080/stream.mjpg"
$env:RECOGNITION_CONTINUOUS="1"
python app.py
```

### 3. Open the dashboard

```text
http://127.0.0.1:5000
```

### Notes

- This is the best option for a presentation if you need real-time recognition.
- The Pi does only camera streaming; the laptop does all face detection and DeepFace matching.
- Keep both devices on the same Wi-Fi network.
- Use `STREAM_WIDTH`, `STREAM_HEIGHT`, and `STREAM_FPS` on the Pi if you need to reduce bandwidth or improve smoothness.

### Remote motion upload

The laptop server can now accept a frame from the Pi:

```bash
curl -X POST http://<laptop-ip>:5000/api/remote-motion ^
  -H "X-Node-Token: your-shared-token" ^
  -F "frame=@capture.jpg"
```

If you do not want token protection during a demo, leave `REMOTE_NODE_TOKEN` unset on the laptop.

## Raspberry Pi 5 (2 GB) deployment

```bash
# On Pi (Pi OS Lite 64-bit recommended)
sudo apt update
sudo apt install -y python3-venv python3-dev libatlas-base-dev libcap-dev
cd ~/surveillance-app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install RPi.GPIO

python seed_individuals.py   # or copy your salim_samples/ folder first
python app.py
```

Access from phone/laptop: `http://<pi-ip>:5000`

**RAM tips:** SFace uses ~200 MB. Avoid other heavy services. First DeepFace load takes ~30–60s on Pi.

## API overview

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/video_feed` | MJPEG live stream |
| GET | `/api/status` | Status bar JSON |
| POST | `/api/recording/start` | Start AVI recording |
| POST | `/api/recording/stop` | Stop recording |
| POST | `/api/remote-motion` | Pi uploads motion snapshot for laptop-side recognition |
| GET | `/api/sessions` | Timeline list |
| GET | `/api/sessions/<id>` | Session + detections |
| GET | `/api/detections/latest` | Last ID card data |
| POST | `/api/train` | Rebuild SFace embeddings |

## WebSocket events

| Event | Direction | Description |
|-------|-----------|-------------|
| `detection` | server → client | Update ID card |
| `alert` | server → client | NOT CLEARED banner |
| `recording_status` | server → client | REC indicator |
| `dismiss_alert` | client → server | Dismiss alert |

## Timestamps

All times use 24-hour format: `YYYY-MM-DD HH:MM:SS`.

## Troubleshooting

- **No recognition on PC:** Set `MOTION_SIMULATE=1` before `python app.py` (PIR only fires on Pi).
- **DeepFace slow on first run:** Model downloads once to `~/.deepface/weights/`.
- **Webcam busy:** Close other apps or set `VIDEO_SOURCE`.
- **Poor matches:** Add more sample photos; rebuild with `POST /api/train`.
- **Socket.IO fails:** Ensure port 5000 is free.

## Learning notes

- **Haar Cascade** — fast face *detection* (where is the face?).
- **SFace + DeepFace** — embedding-based recognition; cosine distance vs enrolled vectors.
- **Snapshot-on-demand** — DeepFace runs only when PIR motion fires (saves Pi RAM/CPU).
- **MJPEG** — multipart HTTP stream for `<img src="/video_feed">`.

## License

Educational / final-year project use.
z
