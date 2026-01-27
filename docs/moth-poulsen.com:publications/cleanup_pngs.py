#!/usr/bin/env python3
"""
Cleanup script: Remove PNG files if corresponding PDF exists.
"""

import sys
from pathlib import Path
import re

def cleanup_scope(scope_dir):
    """Remove PNGs for items that have PDFs."""
    scope_path = Path(scope_dir)
    if not scope_path.exists():
        print(f"Skipping {scope_dir} (not found)")
        return
    
    # Find all item*.pdf files
    pdf_files = list(scope_path.glob('item*.pdf'))
    pdf_items = {}
    
    for pdf in pdf_files:
        match = re.match(r'item(\d+)', pdf.name)
        if match:
            item_num = int(match.group(1))
            pdf_items[item_num] = pdf
    
    # Find and remove corresponding PNGs
    removed = 0
    png_files = list(scope_path.glob('item*.png'))
    
    for png in png_files:
        match = re.match(r'item(\d+)', png.name)
        if match:
            item_num = int(match.group(1))
            if item_num in pdf_items:
                try:
                    png.unlink()
                    print(f"Removed: {png.name}")
                    removed += 1
                except Exception as e:
                    print(f"Error removing {png.name}: {e}")
    
    print(f"Scope '{scope_path.name}': Removed {removed} PNG files")
    return removed

def main():
    if len(sys.argv) > 1:
        # Use provided directory
        total_removed = cleanup_scope(sys.argv[1])
        print(f"\nTotal PNG files removed: {total_removed}")
        return
    
    base_dir = Path('/Users/para/Desktop/thesis/docs/moth-poulsen.com/publications')
    
    scopes = [
        base_dir / 'Moth-Poulsen Publications (193-94)_002'
    ]
    
    total_removed = 0
    for scope in scopes:
        total_removed += cleanup_scope(scope)
    
    print(f"\nTotal PNG files removed: {total_removed}")

if __name__ == '__main__':
    main()
