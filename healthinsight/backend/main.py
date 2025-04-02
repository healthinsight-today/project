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

logger = logging.getLogger(__name__)

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from backend.utils.ocr_processor import OCRProcessor
except ImportError as e:
    logger.error(f"Failed to import OCRProcessor: {e}")
    raise

from .models import UploadResponse, ReportData
from .utils.file_utils import get_unique_filename, is_duplicate_content, cleanup_temp_files
from .utils.cache_utils import ReportCache

app = FastAPI()

# Create upload directory if not exists
os.makedirs("uploads", exist_ok=True)

# Serve static files
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
    """Calculate metrics for a report"""
    ocr = report_data.get("ocr_data", {})
    test_results = ocr.get("test_results", {}).get("by_category", {})
    
    abnormal_count = 0
    test_count = 0
    
    for category in test_results.values():
        for test in category:
            test_count += 1
            if test.get("is_abnormal"):
                abnormal_count += 1
                
    return {
        "total_tests": test_count,
        "abnormal_count": abnormal_count,
        "uploaded_at": report_data.get("uploaded_at"),
        "filename": report_data.get("filename")
    }

@app.get("/api/reports/recent")
async def get_recent_reports():
    files = []
    logger.info("Fetching recent reports")
    
    for file in os.listdir("uploads"):
        file_path = os.path.join("uploads", file)
        if not file.startswith('temp_'):
            stats = os.stat(file_path)
            
            # Get stored OCR results if available
            ocr_data = None
            page_count = None
            
            # Try cache first
            if report_cache.is_cache_valid(file_path):
                cached_results = report_cache.get_results(file_path)
                if cached_results:
                    ocr_data = {
                        "test_results": cached_results.get("test_results", {}),
                        "patient_info": cached_results.get("patient_info", {}),
                        "page_count": cached_results.get("page_count", 0),
                        "report_summary": cached_results.get("report_summary", {})
                    }
                    page_count = cached_results.get("page_count")
                    logger.info(f"Using cached data for {file}")
            
            # If not in cache, try processing tasks
            if not ocr_data:
                for task in processing_tasks.values():
                    result = task.get("result", {})
                    if result.get("filename") == file:
                        ocr_data = {
                            "test_results": result.get("test_results", {}),
                            "patient_info": result.get("patient_info", {}),
                            "page_count": result.get("page_count", 0),
                            "report_summary": result.get("report_summary", {})
                        }
                        page_count = result.get("page_count")
                        logger.info(f"Using processing task data for {file}")
                        break
            
            report_data = {
                "filename": file,
                "uploaded_at": stats.st_mtime,
                "size": stats.st_size,
                "page_count": page_count,
                "ocr_data": ocr_data or {}
            }
            
            logger.debug(f"Report data for {file}: {report_data}")
            files.append(report_data)
    
    # Add metrics to report data
    for file_data in files:
        metrics = await get_report_metrics(file_data)
        file_data.update(metrics)
    
    sorted_files = sorted(files, key=lambda x: x["uploaded_at"], reverse=True)[:5]
    logger.info(f"Returning {len(sorted_files)} recent reports")
    return {"reports": sorted_files}

# Store processing status
processing_tasks = {}

# Initialize cache
report_cache = ReportCache()

async def process_upload(process_id: str, file_path: str):
    try:
        filename = os.path.basename(file_path)
        # Check cache first
        if report_cache.is_cache_valid(file_path):
            cached_results = report_cache.get_results(file_path)
            if cached_results:
                logger.info(f"Using cached results for {file_path}")
                cached_results["filename"] = filename  # Add filename to results
                processing_tasks[process_id] = {
                    "status": "completed",
                    "result": cached_results,
                    "timestamp": datetime.now(),
                    "from_cache": True,
                    "filename": filename
                }
                return

        # Process if not in cache
        logger.info(f"Starting OCR processing for {file_path}")
        ocr_processor = OCRProcessor()
        results = await ocr_processor.process_file(file_path)
        
        if not results.get("success"):
            raise Exception(results.get("error", "OCR processing failed"))

        # Add filename to results
        results["filename"] = filename
        
        # Log extracted data
        logger.info(f"OCR Results for {filename}: Found {len(results.get('test_results', {}).get('by_category', {}))} categories")
        logger.info(f"Patient info extracted: {bool(results.get('patient_info'))}")
        
        # Save to cache
        report_cache.save_results(file_path, results)
        
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
    temp_path = None
    try:
        process_id = str(uuid.uuid4())
        logger.info(f"Starting upload for file: {file.filename}")
        cleanup_temp_files("uploads")
        
        # Save to temporary file
        temp_path = os.path.join("uploads", f"temp_{os.urandom(8).hex()}_{file.filename}")
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        logger.debug(f"Temporary file saved: {temp_path}")
        
        # Check for duplicate content
        is_duplicate, existing_file = is_duplicate_content(temp_path, "uploads")
        if is_duplicate:
            logger.warning(f"Duplicate file detected: {existing_file}")
            os.remove(temp_path)
            raise HTTPException(
                status_code=400,
                detail=f"This file has already been uploaded as {existing_file}"
            )
        
        # Move to final location
        unique_filename = get_unique_filename("uploads", file.filename)
        final_path = os.path.join("uploads", unique_filename)
        os.rename(temp_path, final_path)
        logger.info(f"File moved to final location: {final_path}")
        temp_path = None  # Clear temp_path as file has been moved
        
        # Start background processing
        background_tasks.add_task(process_upload, process_id, final_path)
        
        response = {
            "status": "uploaded",
            "process_id": process_id,
            "message": "File uploaded, processing started"
        }
        
        # Create response with custom header
        return JSONResponse(
            content=response,
            headers={"X-Process-ID": process_id}
        )
        
    except HTTPException as he:
        logger.error(f"HTTP error during upload: {str(he)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during upload: {str(e)}", exc_info=True)
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@app.get("/api/status/{process_id}")
async def get_process_status(process_id: str):
    if process_id not in processing_tasks:
        return {"status": "not_found"}
    
    task = processing_tasks[process_id]
    logger.debug(f"Status request for {process_id}: {task}")
    return task

@app.post("/api/scan-directory")
async def scan_directory(background_tasks: BackgroundTasks):
    process_ids = []
    processed_files = 0
    cached_files = 0
    found_files = []
    
    # List all non-temp files in uploads directory
    for file in os.listdir("uploads"):
        if not file.startswith('temp_') and os.path.isfile(os.path.join("uploads", file)):
            found_files.append(file)
    
    if not found_files:
        return {
            "message": "No files found in uploads directory",
            "status": "empty",
            "process_ids": [],
            "total_files": 0,
            "cached_files": 0
        }
    
    logger.info(f"Found {len(found_files)} files to process")
    
    for file in found_files:
        file_path = os.path.join("uploads", file)
        
        # Check cache first
        if report_cache.is_cache_valid(file_path):
            cached_results = report_cache.get_results(file_path)
            if cached_results:
                process_id = str(uuid.uuid4())
                cached_results["filename"] = file  # Ensure filename is included
                processing_tasks[process_id] = {
                    "status": "completed",
                    "result": cached_results,
                    "timestamp": datetime.now(),
                    "from_cache": True,
                    "filename": file
                }
                process_ids.append(process_id)
                processed_files += 1
                cached_files += 1
                logger.info(f"Using cached results for {file}")
                continue
        
        # Queue file for processing
        process_id = str(uuid.uuid4())
        logger.info(f"Queueing {file} for processing with ID: {process_id}")
        background_tasks.add_task(process_upload, process_id, file_path)
        process_ids.append(process_id)
        processed_files += 1
    
    return {
        "message": f"Processing {processed_files} files ({cached_files} from cache)",
        "status": "processing",
        "process_ids": process_ids,
        "total_files": processed_files,
        "cached_files": cached_files
    }
