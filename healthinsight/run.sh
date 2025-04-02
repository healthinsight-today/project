#!/bin/bash


# Set Python path
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
else
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
fi

# Install requirements
pip install -r requirements.txt

# Run the FastAPI application
uvicorn backend.main:app --reload
