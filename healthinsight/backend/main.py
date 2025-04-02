from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import shutil
import os
import sys
import json
import uuid
from datetime import datetime
from pathlib import Path
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Adjust Python path if needed
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import your new OCR Processor
try:
    from backend.utils.ocr_processor import BloodReportOCRProcessor  # Fix import path
except ImportError as e:
    logger.error(f"Failed to import BloodReportOCRProcessor: {e}")
    raise

# If you have these from separate modules, import them. Otherwise just remove or adapt.
from .models import UploadResponse, ReportData
from .utils.file_utils import get_unique_filename, is_duplicate_content, cleanup_temp_files
from .utils.cache_utils import ReportCache

# Add after imports
ALLOWED_EXTENSIONS = {'.pdf'}
BLOOD_REPORT_PATTERNS = [
    'blood', 'test', 'laboratory', 'lab', 'pathology', 'diagnostic'
]

def is_valid_report(filename: str, file_path: str = None) -> bool:
    """Check if file is a valid blood report based on name and content"""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False
        
    # Check filename for blood report indicators
    name_lower = filename.lower()
    if not any(pattern in name_lower for pattern in BLOOD_REPORT_PATTERNS):
        return False
        
    return True

app = FastAPI()

# Create uploads directory if not exists
os.makedirs("uploads", exist_ok=True)

# Serve your static files
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/", response_class=HTMLResponse)
async def home():
    with open("frontend/upload.html", "r") as f:
        return f.read()

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    with open("frontend/dashboard.html", "r") as f:
        return f.read()

@app.get("/reports", response_class=HTMLResponse)
async def reports_page():
    with open("frontend/reports.html", "r") as f:
        return f.read()

async def get_report_metrics(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate metrics for a report."""
    ocr = report_data.get("ocr_data", {})
    test_results = ocr.get("test_results", {}).get("by_category", {})
    
    abnormal_count = 0
    test_count = 0
    
    for category_tests in test_results.values():
        for test_item in category_tests:
            test_count += 1
            if test_item.get("is_abnormal"):
                abnormal_count += 1
                
    return {
        "total_tests": test_count,
        "abnormal_count": abnormal_count,
        "uploaded_at": report_data.get("uploaded_at"),
        "filename": report_data.get("filename"),
    }

@app.get("/api/reports/recent")
async def get_recent_reports(background_tasks: BackgroundTasks):
    files = []
    logger.info("Fetching recent reports")
    
    # First, clean up any orphaned cache
    if report_cache:
        report_cache.cleanup_orphaned_cache()
    
    # Only process files that actually exist
    for f in os.listdir("uploads"):
        if f.startswith("temp_") or f == ".gitkeep":
            continue

        if not is_valid_report(f):
            logger.debug(f"Skipping non-blood report file: {f}")
            continue

        file_path = os.path.join("uploads", f)
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            continue
        
        stats = os.stat(file_path)
        ocr_data = None
        page_count = None
        
        # Try cache first
        if report_cache:
            cached_results = report_cache.get_results(file_path)
            if cached_results:
                ocr_data = {
                    "test_results": cached_results.get("test_results", {}),
                    "patient_info": cached_results.get("patient_info", {}),
                    "page_count": cached_results.get("page_count", 0),
                    "report_summary": cached_results.get("report_summary", {})
                }
                page_count = cached_results.get("page_count")
                logger.info(f"Using cached data for {f}")
            else:
                # If cache invalid or missing, trigger processing
                process_id = str(uuid.uuid4())
                background_tasks.add_task(process_upload, process_id, file_path)
                logger.info(f"Triggered processing for {f}")

        # Build the final response object
        report_data = {
            "filename": f,
            "uploaded_at": stats.st_mtime,
            "size": stats.st_size,
            "page_count": page_count,
            "ocr_data": ocr_data or {}
        }
        
        files.append(report_data)
    
    # Add test metrics to each
    for file_data in files:
        metrics = await get_report_metrics(file_data)
        file_data.update(metrics)
    
    # Sort by uploaded time desc, limit 5
    sorted_files = sorted(files, key=lambda x: x["uploaded_at"], reverse=True)[:5]
    logger.info(f"Returning {len(sorted_files)} recent reports")
    
    return {"reports": sorted_files}

# Store processing status in memory
processing_tasks = {}

# Initialize cache with error handling
try:
    report_cache = ReportCache()
except Exception as e:
    logger.error(f"Failed to initialize cache: {e}")
    report_cache = None

async def process_upload(process_id: str, file_path: str):
    """Background task to run OCR + parse the report."""
    try:
        filename = os.path.basename(file_path)
        logger.info(f"Starting new processing for {filename}")

        # Always process file, skip cache check
        ocr_processor = BloodReportOCRProcessor()
        results = await ocr_processor.process_file(file_path)

        if not results.get("success"):
            raise Exception(results.get("error", "OCR processing failed"))
        
        # Add filename and update results
        results.update({
            "filename": filename,
            "success": True,
            "processed_at": datetime.now().isoformat()
        })
        
        # Cache the new results
        if report_cache:
            report_cache.save_results(file_path, results)
        
        # Update processing status
        processing_tasks[process_id] = {
            "status": "completed",
            "result": results,
            "timestamp": datetime.now(),
            "from_cache": False,
            "filename": filename
        }
        logger.info(f"Processing completed for {file_path}")

    except Exception as e:
        logger.error(f"Processing failed for {file_path}: {str(e)}", exc_info=True)
        processing_tasks[process_id] = {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now()
        }

@app.post("/upload")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Handle file upload with validation"""
    temp_path = None
    try:
        # Validate file type
        if not is_valid_report(file.filename):
            raise HTTPException(
                status_code=400,
                detail="Invalid file type. Please upload a blood report PDF."
            )

        # Clean up old cache
        if report_cache:
            report_cache.cleanup_orphaned_cache()

        process_id = str(uuid.uuid4())
        logger.info(f"Starting upload for file: {file.filename}")
        cleanup_temp_files("uploads")

        # Save to temp file
        temp_name = f"temp_{os.urandom(8).hex()}_{file.filename}"
        temp_path = os.path.join("uploads", temp_name)
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Move to final location immediately
        unique_filename = get_unique_filename("uploads", file.filename)
        final_path = os.path.join("uploads", unique_filename)
        os.rename(temp_path, final_path)
        temp_path = None

        # Always trigger OCR processing for new uploads
        background_tasks.add_task(process_upload, process_id, final_path)
        
        response = {
            "status": "processing",
            "process_id": process_id,
            "message": "File uploaded, processing started"
        }
        return JSONResponse(
            content=response,
            headers={"X-Process-ID": process_id}
        )

    except Exception as e:
        logger.error(f"Upload error: {str(e)}", exc_info=True)
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status/{process_id}")
async def get_process_status(process_id: str):
    """Check the background task status."""
    if process_id not in processing_tasks:
        return {"status": "not_found"}
    return processing_tasks[process_id]

@app.post("/api/scan-directory")
async def scan_directory(background_tasks: BackgroundTasks):
    """Re-scan the uploads directory and process all files"""
    if report_cache:
        report_cache.cleanup_orphaned_cache()
    
    process_ids = []
    processed_files = 0

    # Find all non-temp files
    found_files = [
        f for f in os.listdir("uploads")
        if os.path.isfile(os.path.join("uploads", f)) and not f.startswith("temp_")
    ]
    
    if not found_files:
        return {
            "message": "No files found in uploads directory",
            "status": "empty",
            "process_ids": [],
            "total_files": 0
        }

    logger.info(f"Found {len(found_files)} files to process")

    # Queue all files for processing
    for f in found_files:
        if not is_valid_report(f):
            logger.debug(f"Skipping non-blood report file: {f}")
            continue

        file_path = os.path.join("uploads", f)
        process_id = str(uuid.uuid4())
        logger.info(f"Queueing {f} for processing with ID: {process_id}")
        background_tasks.add_task(process_upload, process_id, file_path)
        process_ids.append(process_id)
        processed_files += 1

    return {
        "message": f"Processing {processed_files} files",
        "status": "processing",
        "process_ids": process_ids,
        "total_files": processed_files
    }
