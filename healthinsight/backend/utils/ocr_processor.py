import re
import os
import logging
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass
import pytesseract
from PIL import Image
from pdf2image import convert_from_path
import cv2
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class TestResult:
    """Class to store a single test result with all relevant information"""
    name: str
    value: float
    unit: str
    reference_range: str
    is_abnormal: bool = False
    category: str = "Uncategorized"
    page_number: int = 1
    confidence: float = 1.0
    
    def to_dict(self):
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "reference_range": self.reference_range,
            "is_abnormal": self.is_abnormal,
            "category": self.category,
            "page_number": self.page_number,
            "confidence": self.confidence
        }

@dataclass
class PatientInfo:
    """Class to store patient information"""
    name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    test_date: Optional[str] = None
    patient_id: Optional[str] = None
    
    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}

class OCRProcessor:
    def __init__(self):
        # Add blood report indicators
        self.blood_report_indicators = [
            r"blood\s+test", r"blood\s+report", r"hematology", r"haematology", 
            r"laboratory\s+report", r"clinical\s+(pathology|biochemistry)",
            r"complete\s+blood\s+count", r"cbc", r"blood\s+sample", r"serum",
            r"test\s+name\s+results?\s+units?\s+reference", r"biochemistry\s+report"
        ]

        # Add basic test pattern
        self.test_pattern = r'([A-Za-z0-9\s\-\(\)\/]+?)[\s:]+(\d+\.?\d*)\s*([A-Za-z%\/]+)?[\s\-]*(?:ref[:\s]+([0-9\s\.\-]+))'

        # More specific test patterns for extraction
        self.test_patterns = [
            # Pattern for "TEST: 123 unit (ref: 10-20)"
            r'([A-Za-z0-9\s\-\(\)\/]+?)[\s:]+(\d+\.?\d*)\s*([A-Za-z%\/]+)?[\s\-]*(?:ref(?:erence)?[:\s]+([0-9\s\.\-]+))',
            # Pattern for tabular format
            r'([A-Za-z0-9\s\-\(\)\/]+?)\s+(\d+\.?\d*)\s*([\w\/%]+)\s+(?:ref\.?:?\s*([0-9\s\.\-]+))',
            # Pattern for simple "TEST 123 unit Ref: 10-20"
            r'([A-Za-z\s\-\(\)\/]+)\s+(\d+\.?\d*)\s*([\w\/%]+)\s+(?:ref\.?:?\s*([0-9\s\.\-]+))',
            # Backup pattern for simple format
            r'([A-Za-z\s\-\(\)\/]+?):?\s+(\d+\.?\d*)\s*([\w\/%]+)'
        ]

        # Define normal ranges for common tests
        self.normal_ranges = {
            'hemoglobin': {'male': (13, 17), 'female': (12, 15), 'unit': 'g/dL'},
            'wbc': (4000, 11000),
            'rbc': (4.5, 5.5),
            'platelets': (150000, 450000),
            'glucose': (70, 100),
            'creatinine': (0.7, 1.3),
            # Add more normal ranges as needed
        }

        # Updated categories with more specific patterns
        self.test_categories = {
            "Hematology": [
                r'haemoglobin|hb', r'wbc|white\s+blood', r'rbc|red\s+blood', 
                r'platelet|plt', r'neutrophil', r'lymphocytes?', r'monocytes?',
                r'basophils?', r'mcv', r'mch', r'mchc'
            ],
            "Biochemistry": [
                r"glucose", r"creatinine", r"urea", r"bun", r"uric acid", r"protein",
                r"albumin", r"globulin", r"a[:/]g ratio", r"esr", r"sodium", r"potassium",
                r"chloride", r"calcium", r"phosphorus", r"magnesium"
            ],
            "Lipid Profile": [
                r"cholesterol", r"triglyceride", r"hdl", r"ldl", r"vldl"
            ],
            "Liver Function": [
                r"bilirubin", r"sgot|ast", r"sgpt|alt", r"alp|alkaline phosphatase",
                r"ggt|gamma", r"ldh", r"protein"
            ],
            "Thyroid": [
                r"tsh", r"t3", r"t4", r"ft3", r"ft4", r"thyroid"
            ],
            "Vitamin & Minerals": [
                r"vitamin", r"b12", r"d3", r"calcium", r"iron", r"ferritin", r"tibc",
                r"transferrin", r"folate", r"zinc"
            ],
            "Diabetes": [
                r"glucose", r"hba1c", r"insulin", r"c-peptide"
            ]
        }

        self.test_categories.update({
            "Urine Analysis": [
                r"urine analysis", r"cue", r"glucose", r"protein",
                r"bilirubin", r"ketone", r"nitrites"
            ],
            "Blood Morphology": [
                r"rbc morphology", r"wbc morphology", r"platelets",
                r"hemoparasites", r"blood picture"
            ],
            "Iron Studies": [
                r"iron", r"tibc", r"transferrin", r"ferritin",
                r"iron saturation", r"uibc"
            ]
        })

        # Updated patient info patterns
        self.patient_patterns = {
            'name': r'(?:name|patient)\s*[:]\s*([^\n]+)',
            'age': r'age\s*[:]\s*(\d+)',
            'gender': r'(?:gender|sex)\s*[:]\s*([A-Za-z]+)',
            'test_date': r'(?:test date|date|collected)\s*[:]\s*([^\n]+)',
            'patient_id': r'(?:patient id|id|reg\.?\s*no\.?)\s*[:]\s*([^\n]+)'
        }

        # Add OCR configuration
        self.ocr_config = '--oem 3 --psm 6 -l eng'
        
        # Reduce preprocessing modes to most effective ones
        self.preprocess_modes = [
            'default',    # Original image
            'enhanced'    # Enhanced version with better contrast
        ]

    def _preprocess_image(self, image: Image.Image, mode: str = 'default') -> Image.Image:
        """Preprocess image for better OCR results"""
        img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        
        if mode == 'enhanced':
            # Convert to grayscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            # Improve contrast
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            img = clahe.apply(gray)
            # Denoise
            img = cv2.fastNlMeansDenoising(img)
        
        return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))

    def _is_blood_report(self, text: str) -> bool:
        """
        Determine if the text is from a blood test report
        
        Args:
            text: The OCR extracted text
            
        Returns:
            bool: True if it's likely a blood report, False otherwise
        """
        # Check if text contains blood report indicators
        text_lower = text.lower()
        
        # Count how many blood test indicators are found
        indicator_count = sum(1 for pattern in self.blood_report_indicators 
                             if re.search(pattern, text_lower))
        
        # Count blood test categories found in the text
        category_count = 0
        for category, patterns in self.test_categories.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    category_count += 1
                    break
        
        # Check for common blood test result patterns
        result_patterns = re.findall(self.test_pattern, text)
        
        logger.info(f"Blood report indicators: {indicator_count}, "
                   f"Category matches: {category_count}, "
                   f"Result patterns: {len(result_patterns)}")
        
        # Decision logic: if we have enough indicators, it's likely a blood report
        return (indicator_count >= 2 or category_count >= 2 or len(result_patterns) >= 5)

    def _extract_patient_info(self, text: str) -> PatientInfo:
        """Extract patient information from the text"""
        patient_info = PatientInfo()
        
        for info_key, pattern in self.patient_patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if info_key == 'age' and value.isdigit():
                    setattr(patient_info, info_key, int(value))
                else:
                    setattr(patient_info, info_key, value)
                
        return patient_info
    
    def _get_category_for_test(self, test_name: str) -> str:
        """Determine the category for a test based on its name"""
        test_name_lower = test_name.lower()
        
        for category, patterns in self.test_categories.items():
            for pattern in patterns:
                if re.search(pattern, test_name_lower):
                    return category
        
        return "Uncategorized"

    def _clean_test_name(self, name: str) -> str:
        """Clean and standardize test names"""
        name = name.lower().strip()
        name = re.sub(r'\s+', ' ', name)
        # Remove common prefixes/suffixes
        name = re.sub(r'^(test|level|total|serum|plasma|blood)\s+', '', name)
        return name.strip()
    
    def _extract_test_results(self, text: str, page_texts: List[str]) -> List[TestResult]:
        results = []
        seen_tests = set()  # Track unique tests

        for pattern in self.test_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                try:
                    name = self._clean_test_name(match.group(1))
                    if not self._is_valid_test_name(name) or name in seen_tests:
                        continue

                    value = float(match.group(2))
                    unit = match.group(3).strip() if match.group(3) else ""
                    ref_range = match.group(4).strip() if len(match.groups()) > 3 and match.group(4) else ""

                    # Extract range values if available
                    range_match = re.search(r'(\d+\.?\d*)\s*-\s*(\d+\.?\d*)', ref_range)
                    is_abnormal = False
                    if range_match:
                        low, high = map(float, range_match.groups())
                        is_abnormal = value < low or value > high

                    # Get page number
                    page_num = self._find_page_number(match.group(0), page_texts)
                    category = self._get_category_for_test(name)

                    result = TestResult(
                        name=name,
                        value=value,
                        unit=unit,
                        reference_range=ref_range,
                        is_abnormal=is_abnormal,
                        category=category,
                        page_number=page_num,
                        confidence=0.9
                    )
                    
                    results.append(result)
                    seen_tests.add(name)

                except Exception as e:
                    logger.debug(f"Failed to parse: {match.group(0)}, Error: {str(e)}")

        return results

    def _is_valid_test_name(self, name: str) -> bool:
        """Filter out invalid test names"""
        invalid_patterns = [
            r'^\d+$',  # Just numbers
            r'^ref',   # Reference values
            r'interpretation',
            r'guidelines'
        ]
        return not any(re.search(pattern, name.lower()) for pattern in invalid_patterns)

    def _find_page_number(self, match_text: str, page_texts: List[str]) -> int:
        """Find the page number for a match"""
        for i, page_text in enumerate(page_texts, 1):
            if match_text in page_text:
                return i
        return 1

    def _check_if_abnormal(self, value: float, ref_range: str) -> bool:
        """Check if a value is abnormal based on reference range"""
        if ref_range:
            range_match = re.search(r'(\d+\.?\d*)\s*-\s*(\d+\.?\d*)', ref_range)
            if range_match:
                low = float(range_match.group(1))
                high = float(range_match.group(2))
                return value < low or value > high
        return False

    def _calculate_confidence(self, test_results: List[TestResult]) -> float:
        """Calculate confidence score based on results quality"""
        if not test_results:
            return 0.0
            
        score = 0.0
        for result in test_results:
            # Higher score for results with units and reference ranges
            if result.unit:
                score += 0.3
            if result.reference_range:
                score += 0.3
            if result.is_abnormal is not None:
                score += 0.2
            if result.category != "Uncategorized":
                score += 0.2
                
        return min(1.0, score / len(test_results))

    async def process_file(self, file_path: str) -> Dict[str, Any]:
        """
        Process a file and extract blood test results
        
        Args:
            file_path: Path to the file (PDF or image)
            
        Returns:
            Dictionary with extracted information
        """
        try:
            # Check if file exists
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "is_blood_report": False,
                    "error": "File not found"
                }
            
            best_mode = None
            best_results = None
            best_confidence = 0
            total_pages = 0

            if file_path.lower().endswith('.pdf'):
                images = convert_from_path(file_path, dpi=300)
                total_pages = len(images)
                logger.info(f"Processing {total_pages} pages")

            for mode in self.preprocess_modes:
                logger.info(f"Trying {mode} mode")
                text = ""
                page_texts = []
                
                if file_path.lower().endswith('.pdf'):
                    for i, image in enumerate(images, 1):
                        logger.info(f"Processing page {i}/{total_pages} ({mode} mode)")
                        processed_image = self._preprocess_image(image, mode)
                        page_text = pytesseract.image_to_string(processed_image, config=self.ocr_config)
                        page_texts.append(page_text)
                        text += page_text + "\n\n"
                else:
                    image = Image.open(file_path)
                    processed_image = self._preprocess_image(image, mode)
                    text = pytesseract.image_to_string(processed_image, config=self.ocr_config)
                    page_texts = [text]

                # Extract test results and check confidence
                test_results = self._extract_test_results(text, page_texts)
                confidence = self._calculate_confidence(test_results)
                
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_results = test_results
                    best_mode = mode
                    
                logger.info(f"Mode {mode} completed with confidence: {confidence:.2f}")

            logger.info(f"Selected best mode: {best_mode} with confidence: {best_confidence:.2f}")
            
            # Use the best results
            text = "\n\n".join(page_texts)
            test_results = best_results
            
            # Check if this is a blood report
            is_blood_report = self._is_blood_report(text)
            
            if not is_blood_report:
                return {
                    "success": True,
                    "is_blood_report": False,
                    "message": "The document does not appear to be a blood test report"
                }
            
            # Extract patient information first
            patient_info = self._extract_patient_info(text)
            
            # Group results by category
            results_by_category = {}
            for result in test_results:
                if result.category not in results_by_category:
                    results_by_category[result.category] = []
                results_by_category[result.category].append(result.to_dict())
                logger.debug(f"Added test: {result.name} to category: {result.category}")

            # Count abnormal results
            abnormal_count = sum(1 for result in test_results if result.is_abnormal)
            
            return {
                "success": True,
                "is_blood_report": True,
                "filename": os.path.basename(file_path),
                "page_count": len(page_texts),
                "patient_info": patient_info.to_dict(),
                "test_results": {
                    "by_category": results_by_category,
                    "total_count": len(test_results),
                    "abnormal_count": abnormal_count
                },
                "report_summary": {
                    "has_abnormal_results": abnormal_count > 0,
                    "categories_found": list(results_by_category.keys())
                }
            }
            
        except Exception as e:
            logger.error(f"Error processing file: {str(e)}", exc_info=True)
            return {
                "success": False,
                "is_blood_report": False,
                "error": f"Error processing file: {str(e)}"
            }