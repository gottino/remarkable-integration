#!/usr/bin/env python3
"""
Patch for rmc library to add missing color support.

This module monkey-patches the rmc library's RM_PALETTE to include
missing colors like PenColor.HIGHLIGHT (ID 9) which causes crashes
when processing pages with light blue highlighters.
"""

import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

def patch_rmc_colors():
    """
    Patch rmc library to add missing colors to RM_PALETTE.
    
    This fixes the KeyError: 9 issue when processing pages with
    light blue highlighters (PenColor.HIGHLIGHT).
    """
    try:
        from rmscene.scene_items import PenColor
        import rmc.exporters.writing_tools as writing_tools
        
        # Check if already patched
        if hasattr(writing_tools, '_rmc_color_patched'):
            logger.debug("rmc color palette already patched")
            return True
        
        # Add missing colors to the palette
        missing_colors = {
            PenColor.HIGHLIGHT: (173, 216, 230),  # Light blue highlighter (ID 9)
        }
        
        original_palette = writing_tools.RM_PALETTE.copy()
        
        # Add missing colors
        for color_id, rgb_value in missing_colors.items():
            if color_id not in writing_tools.RM_PALETTE:
                writing_tools.RM_PALETTE[color_id] = rgb_value
                logger.info(f"Added missing color {color_id.name} (ID {color_id.value}): {rgb_value}")
            else:
                logger.debug(f"Color {color_id.name} (ID {color_id.value}) already exists")
        
        # Mark as patched by setting an attribute on the module
        writing_tools._rmc_color_patched = True
        
        logger.info(f"rmc color palette patched successfully. Total colors: {len(writing_tools.RM_PALETTE)}")
        return True
        
    except ImportError as e:
        logger.warning(f"Cannot patch rmc colors - libraries not available: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to patch rmc colors: {e}")
        return False

def get_color_info() -> Dict[str, Tuple[int, Tuple[int, int, int]]]:
    """
    Get information about available colors after patching.
    
    Returns:
        Dictionary mapping color names to (id, rgb) tuples
    """
    try:
        from rmscene.scene_items import PenColor  
        import rmc.exporters.writing_tools as writing_tools
        
        color_info = {}
        for color_id, rgb in writing_tools.RM_PALETTE.items():
            if hasattr(color_id, 'name') and hasattr(color_id, 'value'):
                color_info[color_id.name] = (color_id.value, rgb)
        
        return color_info
        
    except ImportError:
        return {}
    except Exception as e:
        logger.error(f"Failed to get color info: {e}")
        return {}

# Auto-patch when module is imported
if __name__ != '__main__':
    patch_rmc_colors()