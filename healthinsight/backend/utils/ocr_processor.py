import pytesseract
from pdf2image import convert_from_path
import re
from typing import Dict, Any
import os

class OCRProcessor:
    def __init__(self):
        self.common_tests = {
            'hemoglobin': r'hemoglobin[:\s]+(\d+\.?\d*)',
            'wbc': r'wbc[:\s]+(\d+\.?\d*)',
            'rbc': r'rbc[:\s]+(\d+\.?\d*)',
            'platelets': r'platelets[:\s]+(\d+\.?\d*)',
        }

    async def process_file(self, file_path: str) -> Dict[str, Any]:
        """Process uploaded file and extract health data"""
        if file_path.lower().endswith('.pdf'):
            # Convert PDF to images
            images = convert_from_path(file_path)
            text = ''
            for image in images:
                text += pytesseract.image_to_string(image)
        else:
            # Process image directly
            text = pytesseract.image_to_string(file_path)

        # Extract test results
        results = {}
        for test, pattern in self.common_tests.items():
            match = re.search(pattern, text.lower())
            if match:
                results[test] = float(match.group(1))

        return {
            "raw_text": text[:500],  # First 500 chars for debugging
            "extracted_values": results
        }
