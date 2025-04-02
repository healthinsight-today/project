import os
import hashlib
from pathlib import Path
from typing import Tuple

def get_file_hash(file_path: str) -> str:
    """Calculate SHA-256 hash of file content"""
    with open(file_path, 'rb') as f:
        bytes = f.read()
        return hashlib.sha256(bytes).hexdigest()

def is_duplicate_content(new_file_path: str, uploads_dir: str) -> Tuple[bool, str]:
    """Check if file content already exists in uploads directory"""
    new_hash = get_file_hash(new_file_path)
    
    for existing_file in os.listdir(uploads_dir):
        # Skip temp files and the file we're checking
        if existing_file.startswith('temp_') or existing_file == os.path.basename(new_file_path):
            continue
            
        existing_path = os.path.join(uploads_dir, existing_file)
        if os.path.isfile(existing_path):
            if get_file_hash(existing_path) == new_hash:
                return True, existing_file
    return False, ""

def cleanup_temp_files(uploads_dir: str):
    """Remove any temporary files in the uploads directory"""
    for file in os.listdir(uploads_dir):
        if file.startswith('temp_'):
            try:
                os.remove(os.path.join(uploads_dir, file))
            except Exception:
                pass

def get_unique_filename(base_path: str, filename: str) -> str:
    """Generate unique filename by adding counter if file exists"""
    name, ext = os.path.splitext(filename)
    counter = 1
    new_path = os.path.join(base_path, filename)
    
    while os.path.exists(new_path):
        new_filename = f"{name}_{counter}{ext}"
        new_path = os.path.join(base_path, new_filename)
        counter += 1
        
    return os.path.basename(new_path)
