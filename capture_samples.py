"""
capture_samples.py — Capture training photos from the laptop webcam
for face-recognition enrollment.

Usage:
    python capture_samples.py <folder_name> [--auto SECONDS] [--count N]

Examples:
    python capture_samples.py salim_samples
        -> opens webcam, press SPACE to save a photo, ESC/Q to quit

    python capture_samples.py salim_samples --auto 1 --count 25
        -> automatically captures 25 photos, 1 per second

Photos are saved into:
    static/captures/seed/<folder_name>/<n>.jpg

Existing numbered files in that folder are NOT overwritten silently —
numbering continues after the highest existing file, unless --fresh is passed.
"""

import argparse
import sys
import time
from pathlib import Path

import cv2

BASE_DIR = Path(__file__).resolve().parent
SEED_DIR = BASE_DIR / "static" / "captures" / "seed"


def next_index(folder: Path) -> int:
    existing = list(folder.glob("*.jpg"))
    nums = []
    for f in existing:
        try:
            nums.append(int(f.stem))
        except ValueError:
            continue
    return (max(nums) + 1) if nums else 1


def main():
    parser = argparse.ArgumentParser(description="Capture face-enrollment training photos.")
    parser.add_argument("folder_name", help="Target folder name, e.g. salim_samples")
    parser.add_argument("--auto", type=float, default=0,
                         help="If set, auto-capture every N seconds instead of requiring SPACE")
    parser.add_argument("--count", type=int, default=30,
                         help="Number of photos to capture in --auto mode (default 30)")
    parser.add_argument("--fresh", action="store_true",
                         help="Clear existing photos in the target folder before capturing")
    parser.add_argument("--camera", type=int, default=0,
                         help="Webcam index (default 0)")
    args = parser.parse_args()

    target_dir = SEED_DIR / args.folder_name
    target_dir.mkdir(parents=True, exist_ok=True)

    if args.fresh:
        for f in target_dir.glob("*.jpg"):
            f.unlink()
        print(f"[Capture] Cleared existing photos in {target_dir}")

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"[Capture] ERROR: could not open camera index {args.camera}")
        sys.exit(1)

    idx = next_index(target_dir)
    saved = 0

    print(f"[Capture] Saving to: {target_dir}")
    if args.auto > 0:
        print(f"[Capture] AUTO mode: capturing {args.count} photos, {args.auto}s apart.")
        print("[Capture] Position your face now. Starting in 3 seconds...")
        time.sleep(3)
    else:
        print("[Capture] MANUAL mode: press SPACE to save a photo, Q or ESC to quit.")

    last_capture = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[Capture] Failed to read frame from camera.")
            break

        display = frame.copy()
        cv2.putText(display, f"Saved: {saved}/{args.count if args.auto > 0 else '-'}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(display, "SPACE=capture  Q/ESC=quit" if args.auto == 0 else "AUTO capturing...",
                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.imshow("Capture Samples - press Q to quit", display)

        key = cv2.waitKey(1) & 0xFF

        if args.auto > 0:
            now = time.time()
            if now - last_capture >= args.auto and saved < args.count:
                out_path = target_dir / f"{idx}.jpg"
                cv2.imwrite(str(out_path), frame)
                print(f"[Capture] Saved {out_path.name}")
                idx += 1
                saved += 1
                last_capture = now
            if saved >= args.count:
                print(f"[Capture] Done — captured {saved} photos.")
                break
        else:
            if key == 32:  # SPACE
                out_path = target_dir / f"{idx}.jpg"
                cv2.imwrite(str(out_path), frame)
                print(f"[Capture] Saved {out_path.name}")
                idx += 1
                saved += 1

        if key in (27, ord('q'), ord('Q')):  # ESC or Q
            print(f"[Capture] Quit — captured {saved} photos this session.")
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
