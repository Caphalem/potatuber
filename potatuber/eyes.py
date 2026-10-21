"""The potato's eyes: takes a screenshot so she can see what you see.

Optional — her brain needs a vision-capable model (Ministral 3 has it).
The screenshot is EPHEMERAL: sent with one request, never saved to history, just like the reminder.
"""

import base64
import io

from PIL import Image
import mss


class Eyes:
    def __init__(self, max_width: int = 1280, quality: int = 70, monitor: int = 1):
        self.max_width = max_width
        self.quality = quality
        self.monitor = monitor

    def look(self) -> str:
        with mss.mss() as sct:
            index = min(self.monitor, len(sct.monitors) - 1)
            shot = sct.grab(sct.monitors[index])
            image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        if image.width > self.max_width:
            ratio = self.max_width / image.width
            image = image.resize((self.max_width, int(image.height * ratio)))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=self.quality)
        return base64.b64encode(buffer.getvalue()).decode()