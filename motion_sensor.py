"""
motion_sensor.py — PIR motion trigger for Raspberry Pi (snapshot-on-demand).

On Pi: reads a PIR sensor on GPIO (default BCM 17).
On dev PC: set MOTION_SIMULATE=1 to trigger on a timer, or leave unset for
           manual-only mode (no automatic snapshots).
"""

import os
import time


class MotionSensor:
    """Poll-based PIR wrapper with debounce."""

    def __init__(self, pin: int | None = None, debounce_sec: float = 2.0):
        self.pin = pin or int(os.environ.get("PIR_GPIO_PIN", "17"))
        self.debounce_sec = debounce_sec
        self._last_trigger = 0.0
        self._gpio = None
        self._simulate = os.environ.get("MOTION_SIMULATE", "").lower() in ("1", "true", "yes")
        self._simulate_interval = float(os.environ.get("MOTION_SIMULATE_INTERVAL", "8"))
        self._last_sim = time.time()
        self._init_gpio()

    def _init_gpio(self):
        if self._simulate:
            print("[Motion] Simulated motion enabled (MOTION_SIMULATE=1)")
            return
        try:
            import RPi.GPIO as GPIO

            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.pin, GPIO.IN)
            self._gpio = GPIO
            print(f"[Motion] PIR sensor on GPIO {self.pin}")
        except (ImportError, RuntimeError, ValueError) as exc:
            print(f"[Motion] GPIO unavailable ({exc}) — motion trigger disabled")
            self._gpio = None

    def check(self) -> bool:
        """
        Return True once per debounce window when motion is detected.
        """
        now = time.time()
        if now - self._last_trigger < self.debounce_sec:
            return False

        if self._simulate:
            if now - self._last_sim >= self._simulate_interval:
                self._last_sim = now
                self._last_trigger = now
                return True
            return False

        if self._gpio is None:
            return False

        if self._gpio.input(self.pin):
            self._last_trigger = now
            return True
        return False

    def cleanup(self):
        if self._gpio is not None:
            try:
                self._gpio.cleanup()
            except Exception:
                pass
