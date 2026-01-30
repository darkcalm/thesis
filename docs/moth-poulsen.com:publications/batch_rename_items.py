#!/usr/bin/env python3
"""
Batch rename script: Rename itemXXX_*.pdf to itemXXX_NNN_*.pdf
where NNN is (194 - item_number) and * preserves any suffix (like DOI).

Example:
  item001_10.1002_adma.202511822.pdf -> item001_193_10.1002_adma.202511822.pdf
  item002_10.1038_s41467-025-61301-3.pdf -> item002_192_10.1038_s41467-025-61301-3.pdf
  item100_10.1039_C8CC07076H.pdf -> item100_094_10.1039_C8CC07076H.pdf

Usage:
  python batch_rename_items.py <directory>
"""

import sys
import re
from pathlib import Path


def batch_rename(directory):
    """Rename all item*.pdf files in the given directory."""
    dir_path = Path(directory)
    
    if not dir_path.exists():
        print(f"Error: Directory not found: {directory}")
        return False
    
    if not dir_path.is_dir():
        print(f"Error: Not a directory: {directory}")
        return False
    
    # Find all item*.pdf files
    pdf_files = list(dir_path.glob('item*.pdf'))
    
    if not pdf_files:
        print(f"No PDF files found in {directory}")
        return True
    
    print(f"Found {len(pdf_files)} PDF files")
    
    renamed_count = 0
    for pdf_file in sorted(pdf_files):
        # Match itemXXX_* or itemXXX (extract item number and suffix)
        match = re.match(r'(item)(\d+)(.*)(\.pdf)$', pdf_file.name)
        if not match:
            print(f"Skipping: {pdf_file.name} (doesn't match pattern)")
            continue
        
        prefix = match.group(1)  # "item"
        item_num = int(match.group(2))
        suffix = match.group(3)  # e.g., "_10.1002_adma.202511822"
        ext = match.group(4)  # ".pdf"
        
        # Calculate numeric suffix: 194 - item_number
        numeric_suffix = 194 - item_num
        
        # Create new name: itemXXX_NNN_*.pdf
        new_name = f"{prefix}{item_num:03d}_{numeric_suffix:03d}{suffix}{ext}"
        new_path = dir_path / new_name
        
        try:
            pdf_file.rename(new_path)
            print(f"Renamed: {pdf_file.name} -> {new_name}")
            renamed_count += 1
        except Exception as e:
            print(f"Error renaming {pdf_file.name}: {e}")
    
    print(f"\nTotal renamed: {renamed_count}/{len(pdf_files)}")
    return True


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <directory>")
        sys.exit(1)
    
    directory = sys.argv[1]
    success = batch_rename(directory)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
