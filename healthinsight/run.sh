#!/bin/bash

# Install system dependencies
sudo apt-get update
sudo apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    python3-pip \
    python3-dev

# Create fresh virtual environment
python3 -m venv venv
source venv/bin/activate

# Upgrade basic tools
pip install --upgrade pip setuptools wheel

# Install dependencies in order
pip install numpy
pip install opencv-python-headless
pip install -r requirements.txt

# Run the FastAPI application
uvicorn backend.main:app --reload
