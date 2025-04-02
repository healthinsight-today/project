"""
ocr_processor.py

Handles OCR + text parsing to produce a structured JSON
with test results, patient info, etc.
"""
import os
import re
import logging
import pytesseract
from typing import Any, Dict
import pdf2image
from PIL import Image
import cv2
import numpy as np

logger = logging.getLogger(__name__)

class BloodReportOCRProcessor:
    def __init__(self):
        """
        Initialize any resources (like Tesseract config, etc.)
        """
        self.tesseract_config = '--oem 3 --psm 6'
        self.blood_markers = [
            'hemoglobin', 'hematology', 'wbc', 'rbc', 
            'platelets', 'blood count', 'cholesterol'
        ]

    async def process_file(self, file_path: str) -> Dict[str, Any]:
        """Process file and ensure results"""
        try:
            if not file_path.lower().endswith('.pdf'):
                raise Exception("Invalid file type. Only PDF files are supported.")

            logger.info(f"Processing file: {file_path}")
            
            # Extract text
            text = self._extract_text_from_pdf(file_path)
            
            # Quick validation that this is a blood report
            text_lower = text.lower()
            if not any(marker in text_lower for marker in self.blood_markers):
                raise Exception("This doesn't appear to be a blood test report")

            if not text.strip():
                raise Exception("No text extracted from file")

            # Parse content
            lines = self._basic_clean_lines(text.splitlines())
            if not lines:
                raise Exception("No valid content found after cleaning")

            patient_info = self._parse_patient_info(lines)
            test_results = self._parse_test_results(lines)
            
            # Validate results
            if not test_results:
                raise Exception("No test results extracted")

            # Build response with required data
            final_output = {
                "success": True,
                "filename": os.path.basename(file_path),
                "page_count": self._count_pages(text),
                "patient_info": patient_info,
                "test_results": {
                    "by_category": test_results
                },
                "report_summary": {
                    "has_abnormal_results": any(
                        test.get("is_abnormal", False) 
                        for category in test_results.values() 
                        for test in category
                    ),
                    "categories_found": list(test_results.keys()),
                    "total_tests": sum(len(tests) for tests in test_results.values())
                }
            }

            logger.info(f"Successfully processed {file_path}")
            return final_output

        except Exception as e:
            logger.error(f"Failed to process {file_path}: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "filename": os.path.basename(file_path)
            }

    def _extract_text_from_pdf(self, pdf_path: str) -> str:
        """Convert PDF to images and extract text using Tesseract"""
        try:
            logger.info(f"Starting PDF processing: {pdf_path}")
            # Convert PDF to images
            logger.info("Converting PDF to images...")
            pages = pdf2image.convert_from_path(pdf_path, dpi=300)
            logger.info(f"Converted {len(pages)} pages")
            
            text_content = []
            for i, page in enumerate(pages, 1):
                logger.info(f"Processing page {i}/{len(pages)}")
                
                # Convert to numpy array for OpenCV
                img_np = np.array(page)
                logger.debug(f"Page {i}: Converted to numpy array")
                
                # Convert to grayscale
                gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
                logger.debug(f"Page {i}: Converted to grayscale")
                
                # Apply thresholding
                _, threshold = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                logger.debug(f"Page {i}: Applied thresholding")
                
                # Convert back to PIL Image
                pil_image = Image.fromarray(threshold)
                
                # Extract text using Tesseract
                logger.info(f"Running OCR on page {i}...")
                text = pytesseract.image_to_string(pil_image, config=self.tesseract_config)
                logger.info(f"Page {i}: Extracted {len(text)} characters")
                text_content.append(text)
                
            final_text = "\n".join(text_content)
            logger.info(f"Completed PDF processing. Total text length: {len(final_text)}")
            return final_text
            
        except Exception as e:
            logger.error(f"PDF processing error: {str(e)}", exc_info=True)
            raise Exception(f"Failed to process PDF: {str(e)}")

    def _extract_text_from_image(self, image_path: str) -> str:
        """Simple Tesseract image read."""
        text = pytesseract.image_to_string(image_path)
        return text

    def _basic_clean_lines(self, raw_lines):
        """
        Remove empty lines, page headers, disclaimers, etc.
        """
        cleaned = []
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue  # skip blank
            # skip disclaimers or repeated noise
            if "Your Health Buddy" in line:
                continue
            if line.startswith("--- PAGE END ---"):
                continue
            # Add other noisy patterns as needed

            cleaned.append(line)
        return cleaned

    def _parse_patient_info(self, lines):
        """
        Example parse of patient name, age, gender from lines
        """
        patient = {}
        for line in lines:
            # name
            match_name = re.search(r"NAME:\s*(.+)", line, re.IGNORECASE)
            if match_name:
                patient["name"] = match_name.group(1).strip()

            # age
            match_age = re.search(r"AGE:\s*(\d+)", line, re.IGNORECASE)
            if match_age:
                patient["age"] = match_age.group(1).strip()

            # gender
            match_gender = re.search(r"GENDER:\s*(Male|Female|Other)", line, re.IGNORECASE)
            if match_gender:
                patient["gender"] = match_gender.group(1).capitalize()

        return patient

    def _parse_test_results(self, lines):
        """Parse test results with improved pattern matching"""
        categories = {}
        current_category = "General Tests"
        
        # More comprehensive patterns
        category_pattern = re.compile(
            r"(COMPLETE BLOOD COUNT|HAEMATOLOGY|BIOCHEMISTRY|"
            r"KIDNEY FUNCTION|LIVER FUNCTION|LIPID PROFILE|"
            r"THYROID PROFILE|DIABETES SCREENING|SERUM ELECTROLYTES)",
            re.IGNORECASE
        )
        
        test_pattern = re.compile(
            r"""^
            (?P<test_name>[A-Za-z0-9()/\s-]+?)\s+
            (?P<value>(<|>)?[\d.]+([-\s]*[\d.]+)?)\s*
            (?P<unit>[A-Za-z%/\s]+)?\s*
            (?P<range>[\d.]+-[\d.]+|\d+(-|\sto\s)\d+)?
            """, re.VERBOSE)

        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Check for category headers
            cat_match = category_pattern.search(line)
            if cat_match:
                current_category = cat_match.group(1).title()
                categories.setdefault(current_category, [])
                continue
            
            # Try to match test pattern
            test_match = test_pattern.match(line)
            if test_match:
                test_name = test_match.group("test_name").strip()
                value_str = test_match.group("value").strip()
                unit = (test_match.group("unit") or "").strip()
                ref_range = (test_match.group("range") or "").strip()
                
                # Convert value to float if possible
                try:
                    value = float(value_str)
                except ValueError:
                    value = value_str
                
                # Add the test result
                categories.setdefault(current_category, []).append({
                    "test_name": test_name,
                    "value": value,
                    "unit": unit,
                    "reference_range": ref_range,
                    "is_abnormal": False  # Will be updated when range is parsed
                })
        
        return categories if categories else {"General Tests": []}

    def _count_pages(self, text: str) -> int:
        """Example: if your PDF or text had 'Page x of y' lines, parse them. Or just return 1."""
        # Quick guess approach
        pages = re.findall(r"Page\s+\d+\s+of\s+\d+", text, re.IGNORECASE)
        if pages:
            # last match => parse the final 'of N'
            last_page = pages[-1]
            match_end = re.search(r"of\s+(\d+)", last_page, re.IGNORECASE)
            if match_end:
                return int(match_end.group(1))
        return 1
