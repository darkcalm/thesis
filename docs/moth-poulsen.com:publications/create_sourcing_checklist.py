#!/usr/bin/env python3
"""
Create a sourcing checklist from CSV file's Link URL column.

Usage:
    python create_sourcing_checklist.py <csv_file_path>
"""

import csv
import sys
from pathlib import Path


def create_checklist(csv_path):
    """Create checklist from CSV file's Link URL column."""
    csv_path = Path(csv_path)
    
    if not csv_path.exists():
        print(f"Error: File not found: {csv_path}")
        return False
    
    urls = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row.get('Link URL', '').strip()
            if url:
                urls.append(url)
    
    if not urls:
        print("Warning: No URLs found in the CSV file.")
        return False
    
    print(f"Found {len(urls)} URLs")
    
    # Create folder name from CSV filename (without extension)
    folder_name = csv_path.stem + "_002"
    output_dir = csv_path.parent / folder_name
    output_dir.mkdir(exist_ok=True)
    print(f"Created directory: {output_dir}")
    
    # Create sourcing checklist file
    checklist_path = output_dir / "sourcing_checklist.md"
    
    with open(checklist_path, 'w', encoding='utf-8') as f:
        for i, url in enumerate(urls, start=1):
            f.write(f"{i}. [] {url}\n")
    
    print(f"Created sourcing checklist: {checklist_path}")
    print(f"Total items: {len(urls)}")
    
    return True


def main():
    if len(sys.argv) != 2:
        print("Usage: python create_sourcing_checklist.py <csv_file_path>")
        sys.exit(1)
    
    csv_file = sys.argv[1]
    success = create_checklist(csv_file)
    
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
