import json
import os
from datetime import datetime
from typing import Dict, Any

class ReportCache:
    def __init__(self, cache_dir: str = "cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def get_cache_path(self, file_path: str) -> str:
        file_name = os.path.basename(file_path)
        return os.path.join(self.cache_dir, f"{file_name}.json")

    def save_results(self, file_path: str, results: Dict[str, Any]) -> None:
        cache_path = self.get_cache_path(file_path)
        results["cached_at"] = datetime.now().isoformat()
        with open(cache_path, "w") as f:
            json.dump(results, f)

    def get_results(self, file_path: str) -> Dict[str, Any]:
        cache_path = self.get_cache_path(file_path)
        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                results = json.load(f)
                # Check if cached results are valid and contain OCR data
                if results.get("success") and results.get("is_blood_report"):
                    return results
        return None

    def is_cache_valid(self, file_path: str) -> bool:
        cache_path = self.get_cache_path(file_path)
        if not os.path.exists(cache_path):
            return False
        
        # Check if source file is newer than cache
        file_mtime = os.path.getmtime(file_path)
        cache_mtime = os.path.getmtime(cache_path)
        return cache_mtime > file_mtime
