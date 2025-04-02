from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import shutil
import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.utils.ocr_processor import OCRProcessor

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

@app.get("/api/reports/recent")
async def get_recent_reports():
    # Get list of files in uploads directory
    files = []
    for file in os.listdir("uploads"):
        file_path = os.path.join("uploads", file)
        files.append({
            "filename": file,
            "uploaded_at": os.path.getmtime(file_path)
        })
    return {"reports": sorted(files, key=lambda x: x["uploaded_at"], reverse=True)[:5]}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join("uploads", file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Process the uploaded file with OCR
    ocr_processor = OCRProcessor()
    try:
        results = await ocr_processor.process_file(file_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR processing failed: {str(e)}")
    
    return {
        "filename": file.filename,
        "status": "Uploaded and processed",
        "ocr_results": results
    }
