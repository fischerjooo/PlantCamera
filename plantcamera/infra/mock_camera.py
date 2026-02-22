from __future__ import annotations

import threading
from pathlib import Path


class CameraSimulator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.black_ratio = 0.0
        self.fail_next_capture = False
        self._black_ratio_by_file: dict[str, float] = {}

    def configure(self, *, black_ratio: float | None = None, fail_next_capture: bool | None = None) -> None:
        with self._lock:
            if black_ratio is not None:
                self.black_ratio = max(0.0, min(1.0, black_ratio))
            if fail_next_capture is not None:
                self.fail_next_capture = fail_next_capture

    def status(self) -> dict[str, float | bool]:
        with self._lock:
            return {
                "black_ratio": self.black_ratio,
                "fail_next_capture": self.fail_next_capture,
            }

    def capture_photo(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if self.fail_next_capture:
                self.fail_next_capture = False
                raise RuntimeError("simulated capture failure")
            ratio = self.black_ratio
        payload = b"\xff\xd8\xffSIMJPEG\n" + f"BLACK_RATIO={ratio:.4f}\n".encode("utf-8") + b"\xff\xd9"
        output_path.write_bytes(payload)
        with self._lock:
            self._black_ratio_by_file[str(output_path)] = ratio

    def rotate_image_left(self, image_path: Path) -> None:
        payload = image_path.read_bytes()
        image_path.write_bytes(payload + b"ROTATE_LEFT_90=1\n")


    def normalize_image_full_hd(self, image_path: Path) -> None:
        payload = image_path.read_bytes()
        # Marker used by tests; simulator does not generate real pixels.
        image_path.write_bytes(payload + b"NORMALIZED_FULL_HD=1920x1080\n")

    def estimate_black_ratio(self, image_path: Path) -> float | None:
        with self._lock:
            return self._black_ratio_by_file.get(str(image_path))
