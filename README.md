# Solar-Powered Remote Border Surveillance Station

This project provides a lightweight monitoring console for AI camera feeds so operators can view live video from a remote station, mobile phone, or PC.

## Features
- Responsive monitoring dashboard for desktop and mobile.
- Supports HLS, MJPEG, snapshot, or WebRTC feed placeholders.
- Includes a local webcam option for testing without external cameras.
- Simple JSON configuration for camera metadata.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open `http://localhost:5000` in your browser.

## Configure Camera Feeds
Edit `config/cameras.json` to point at your camera feeds. For IP Webcam, use the MJPEG endpoint (e.g., `http://<ip>:8080/video`).

```json
{
  "cameras": [
    {
      "id": "north-perimeter-01",
      "name": "North Perimeter",
      "location": "Sector A",
      "type": "hls",
      "url": "https://example.com/stream/north.m3u8"
    }
  ]
}
```

### Supported Types
- `hls` for HTTP Live Streaming (`.m3u8`).
- `mjpeg` for MJPEG HTTP streams.
- `snapshot` for periodic JPEG/PNG snapshots.
- `webrtc` (placeholder text for now) for WebRTC operators.
- `webcam` for using a local browser webcam during testing.

## Next Steps
- Add authentication for operators.
- Connect WebRTC signaling for low-latency feeds.
- Add alert overlays from AI detections.
