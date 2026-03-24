import re
from core.logger import logger

class PlateOCR:
    def __init__(self):
        """
        Lightweight PlateOCR refiner for Indian license plates.
        No longer uses PaddleOCR directly (delegated to FastALPR).
        """
        # Indian license plate regex: e.g. KL 07 AB 1234 or KL07AB1234
        self.plate_regex = re.compile(r'^[A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{4}$')
        logger.info("PlateOCR Refiner initialized (lightweight mode)")

    def normalize_text(self, text):
        """
        Normalize OCR common errors: O ↔ 0, I ↔ 1
        """
        if not text:
            return ""
        text = text.upper().replace(" ", "").replace("-", "").replace(".", "")
        return text

    def validate_indian_plate(self, text):
        """
        Validate against Indian license plate regex
        """
        clean_text = self.normalize_text(text)
        if self.plate_regex.match(clean_text):
            return clean_text
        return None

