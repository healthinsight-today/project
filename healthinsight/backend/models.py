from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime

class UploadResponse(BaseModel):
    filename: str
    status: str
    ocr_results: Dict[str, Any]

class ReportData(BaseModel):
    filename: str
    uploaded_at: float
    size: Optional[int] = None
    pages: Optional[int] = None
    extracted_values: Optional[Dict[str, Any]] = None
