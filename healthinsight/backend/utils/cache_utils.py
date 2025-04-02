import json
import os
import logging
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)

class ReportCache:
    def __init__(self, cache_dir: str = "cache"):
        self.cache_dir = cache_dir
        # Ensure cache directories exist
        self._ensure_cache_dirs()

    def _ensure_cache_dirs(self):
        """Create cache directories if they don't exist"""
        try:
            for subdir in ["blood_reports", "other_reports"]:
                dir_path = os.path.join(self.cache_dir, subdir)
                os.makedirs(dir_path, exist_ok=True)
            logger.info("Cache directories created/verified")
        except Exception as e:
            logger.error(f"Failed to create cache directories: {e}")
            raise

    def get_cache_path(self, file_path: str) -> str:
        """Generate cache path with better organization"""
        file_name = os.path.basename(file_path)
        
        # Remove special characters and spaces from cache filename
        cache_name = "".join(c for c in file_name if c.isalnum() or c in '._-')
        
        # Determine subdirectory based on file type
        if file_name.lower().endswith('.pdf'):
            sub_dir = "blood_reports"
        else:
            sub_dir = "other_reports"
            
        return os.path.join(self.cache_dir, sub_dir, f"{cache_name}.json")

    def get_cached_file_path(self, file_name: str) -> str:
        """Get the cached file path for a given filename"""
        cache_name = "".join(c for c in file_name if c.isalnum() or c in '._-')
        return os.path.join(self.cache_dir, "blood_reports", f"{cache_name}.json")

    def save_results(self, file_path: str, results: Dict[str, Any]) -> None:
        cache_path = self.get_cache_path(file_path)
        results["cached_at"] = datetime.now().isoformat()
        with open(cache_path, "w") as f:
            json.dump(results, f)

    def validate_cache_data(self, data: Dict[str, Any]) -> bool:
        """Validate cached data structure and content"""
        try:
            # Basic structure check
            if not isinstance(data, dict):
                return False

            # Must have test results with actual data
            test_results = data.get("test_results", {}).get("by_category", {})
            if not test_results:
                logger.warning("No test results found, forcing rescan")
                return False

            # Check if any categories have tests
            has_tests = False
            for tests in test_results.values():
                if isinstance(tests, list) and len(tests) > 0:
                    has_tests = True
                    break

            if not has_tests:
                logger.warning("No valid test data found, forcing rescan")
                return False

            return True
        except Exception as e:
            logger.error(f"Cache validation error: {e}")
            return False

    def get_results(self, file_path: str) -> Dict[str, Any]:
        """Get cached results with validation"""
        try:
            if not os.path.exists(file_path):
                self._remove_cache(file_path)
                return None

            cache_path = self.get_cache_path(file_path)
            if not os.path.exists(cache_path):
                logger.info(f"No cache exists for {file_path}, needs scanning")
                return None

            with open(cache_path, 'r') as f:
                results = json.load(f)

            if not self.validate_cache_data(results):
                logger.info(f"Cache invalid or empty for {file_path}, forcing rescan")
                self._remove_cache(file_path)
                return None

            return results
        except Exception as e:
            logger.error(f"Error reading cache: {e}")
            self._remove_cache(file_path)
            return None

    def _remove_cache(self, file_path: str) -> None:
        """Helper to remove cache file"""
        try:
            cache_path = self.get_cache_path(file_path)
            if os.path.exists(cache_path):
                os.remove(cache_path)
                logger.info(f"Removed cache file: {cache_path}")
        except Exception as e:
            logger.error(f"Error removing cache: {e}")

    def check_existing_report(self, filename: str) -> Dict[str, Any]:
        """Check if report already exists in cache by filename"""
        # Always return None to force new processing
        return None

    def is_cache_valid(self, file_path: str) -> bool:
        """Check if cache exists and is valid"""
        try:
            # Always force scan if cache is empty or invalid
            results = self.get_results(file_path)
            return results is not None and self.validate_cache_data(results)
        except Exception:
            return False

    def cleanup_orphaned_cache(self):
        """Remove cache files for which original files no longer exist"""
        orphaned = 0
        for subdir in ["blood_reports", "other_reports"]:
            cache_dir = os.path.join(self.cache_dir, subdir)
            if not os.path.exists(cache_dir):
                continue
                
            for cache_file in os.listdir(cache_dir):
                try:
                    upload_exists = False
                    original_name = cache_file.rsplit('.json', 1)[0]
                    
                    # More strict check for original file
                    for f in os.listdir("uploads"):
                        if not f.startswith('temp_'):
                            clean_name = "".join(c for c in f if c.isalnum() or c in '._-')
                            if clean_name == original_name:
                                file_path = os.path.join("uploads", f)
                                if os.path.exists(file_path):
                                    upload_exists = True
                                    break
                    
                    if not upload_exists:
                        cache_path = os.path.join(cache_dir, cache_file)
                        os.remove(cache_path)
                        orphaned += 1
                        logger.info(f"Removed orphaned cache: {cache_file}")
                except Exception as e:
                    logger.error(f"Error cleaning cache file {cache_file}: {e}")
        
        if orphaned > 0:
            logger.info(f"Cleaned up {orphaned} orphaned cache files")
