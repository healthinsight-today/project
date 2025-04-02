#!/bin/bash

# Install system dependencies
sudo apt-get update
sudo apt-get install -y python3-dev zlib1g-dev libjpeg-dev libpng-dev tesseract-ocr

# Set Python path
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Upgrade pip and install requirements
pip install --upgrade pip
pip install wheel
pip install -r requirements.txt

# Run the FastAPI application
uvicorn backend.main:app --reload
#!/bin/bash

# Create Python virtual environment
python3 -m venv venv
source venv/bin/activate

# Create base directories
mkdir -p backend uploads frontend

# Create minimal main.py
# ...existing code for main.py...

# Create upload.html
# ...existing code for upload.html...

# Create requirements.txt
cat > requirements.txt << EOL
fastapi==0.68.0
uvicorn==0.15.0
python-multipart==0.0.5
aiofiles==0.7.0
python-dotenv==0.19.0
EOL

# Install requirements
pip install --upgrade pip
pip install -r requirements.txt

echo "Setup complete! To run:"
echo "1. source venv/bin/activate"
echo "2. uvicorn backend.main:app --reload"
echo "3. Visit http://localhost:8000"
#!/bin/bash

# Create base directories
mkdir -p backend uploads frontend

# Create minimal main.py
cat > backend/main.py << EOL
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import shutil
import os

app = FastAPI()

# Create upload directory if not exists
os.makedirs("uploads", exist_ok=True)

# Serve static files
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/", response_class=HTMLResponse)
async def home():
    with open("frontend/upload.html", "r") as f:
        return f.read()

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join("uploads", file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"filename": file.filename, "status": "Uploaded"}
EOL

# Create upload.html
cat > frontend/upload.html << EOL
<!DOCTYPE html>
<html>
<head>
    <title>Health Report Upload</title>
    <style>
        body { font-family: Arial; max-width: 800px; margin: 20px auto; padding: 20px; }
        .upload-box { border: 2px dashed #ccc; padding: 20px; text-align: center; }
        .upload-btn { background: #4CAF50; color: white; padding: 10px 20px; border: none; cursor: pointer; }
    </style>
</head>
<body>
    <div class="upload-box">
        <h2>Upload Health Report</h2>
        <form id="upload-form">
            <input type="file" id="file-input" name="file" accept=".pdf,.jpg,.png" required>
            <br><br>
            <button type="submit" class="upload-btn">Upload</button>
        </form>
        <p id="status"></p>
    </div>

    <script>
        document.getElementById("upload-form").addEventListener("submit", async (e) => {
            e.preventDefault();
            const formData = new FormData();
            formData.append("file", document.getElementById("file-input").files[0]);
            
            try {
                const response = await fetch("/upload", {
                    method: "POST",
                    body: formData
                });
                const result = await response.json();
                document.getElementById("status").textContent = "Success: " + result.filename;
            } catch (error) {
                document.getElementById("status").textContent = "Error: " + error;
            }
        });
    </script>
</body>
</html>
EOL

# Create requirements.txt
cat > requirements.txt << EOL
fastapi==0.68.0
uvicorn==0.15.0
python-multipart==0.0.5
aiofiles==0.7.0
EOL

echo "Setup complete! To run:"
echo "1. pip install -r requirements.txt"
echo "2. uvicorn backend.main:app --reload"
echo "3. Visit http://localhost:8000"
