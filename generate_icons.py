"""Generate minimal PWA icons for manifest.json."""
from pathlib import Path

import cv2
import numpy as np

ICONS_DIR = Path(__file__).resolve().parent / "static" / "icons"


def make_icon(size: int, path: Path):
    img = np.zeros((size, size, 3), dtype=np.uint8)
    img[:] = (10, 10, 12)
    cv2.rectangle(img, (4, 4), (size - 5, size - 5), (61, 126, 255), 2)
    cv2.circle(img, (size // 2, size // 2 - 8), size // 6, (200, 200, 210), 2)
    cv2.putText(
        img,
        "BS",
        (size // 4, size // 2 + size // 8),
        cv2.FONT_HERSHEY_SIMPLEX,
        size / 128,
        (232, 234, 239),
        max(1, size // 128),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)


if __name__ == "__main__":
    make_icon(192, ICONS_DIR / "icon-192.png")
    make_icon(512, ICONS_DIR / "icon-512.png")
    print("Icons written to", ICONS_DIR)
