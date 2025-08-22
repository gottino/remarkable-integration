"""
Export helpers for including reMarkable folder paths in exported content.
"""

import logging
from typing import Optional, Dict
from ..core.notebook_paths import get_notebook_path

logger = logging.getLogger(__name__)

def add_remarkable_path_to_export(data: Dict, notebook_uuid: str, db_connection) -> Dict:
    """Add reMarkable folder path to export data."""
    try:
        path = get_notebook_path(notebook_uuid, db_connection)
        if path:
            data['remarkable_path'] = path
            # Also add just the folder part (without document name)
            if '/' in path:
                data['remarkable_folder'] = '/'.join(path.split('/')[:-1])
            else:
                data['remarkable_folder'] = ''  # Root folder
        else:
            data['remarkable_path'] = None
            data['remarkable_folder'] = None
    except Exception as e:
        logger.warning(f"Could not get remarkable path for {notebook_uuid}: {e}")
        data['remarkable_path'] = None
        data['remarkable_folder'] = None
    
    return data

def create_output_path(notebook_uuid: str, notebook_name: str, db_connection, 
                       base_dir: str = "", extension: str = ".md") -> str:
    """Create output file path respecting reMarkable folder structure."""
    try:
        remarkable_path = get_notebook_path(notebook_uuid, db_connection)
        
        if remarkable_path and '/' in remarkable_path:
            # Use the remarkable folder structure
            # Replace / with os-appropriate separator and sanitize
            import os
            folder_path = remarkable_path.replace('/', os.sep)
            
            # Sanitize folder names for filesystem
            folder_path = sanitize_path(folder_path)
            
            if base_dir:
                full_path = os.path.join(base_dir, folder_path + extension)
            else:
                full_path = folder_path + extension
        else:
            # Fallback to just notebook name
            safe_name = sanitize_filename(notebook_name)
            if base_dir:
                full_path = os.path.join(base_dir, safe_name + extension)
            else:
                full_path = safe_name + extension
        
        return full_path
        
    except Exception as e:
        logger.warning(f"Error creating output path for {notebook_uuid}: {e}")
        # Fallback to safe filename
        safe_name = sanitize_filename(notebook_name)
        if base_dir:
            return os.path.join(base_dir, safe_name + extension)
        else:
            return safe_name + extension

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for filesystem compatibility."""
    import re
    import os
    
    # Replace problematic characters
    unsafe_chars = '<>:"/\\|?*'
    for char in unsafe_chars:
        filename = filename.replace(char, '_')
    
    # Remove control characters
    filename = re.sub(r'[\x00-\x1f\x7f]', '', filename)
    
    # Trim whitespace and dots
    filename = filename.strip(' .')
    
    # Ensure not empty
    if not filename:
        filename = "untitled"
    
    # Limit length
    if len(filename) > 255:
        filename = filename[:255]
    
    return filename

def sanitize_path(path: str) -> str:
    """Sanitize full path for filesystem compatibility."""
    import os
    
    # Split path and sanitize each component
    parts = path.split(os.sep)
    sanitized_parts = [sanitize_filename(part) for part in parts if part]
    
    return os.sep.join(sanitized_parts)