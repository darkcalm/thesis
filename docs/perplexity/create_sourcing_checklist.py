#!/usr/bin/env python3
"""
Automation script to extract URLs from a markdown file and create a sourcing checklist.

Usage:
    python create_sourcing_checklist.py <markdown_file_path>

The script will:
1. Extract all URLs from footnote references (format: [^...]: https://...)
2. Create a folder named after the markdown file (without extension)
3. Create a sourcing_checklist.md file with numbered checkboxes and URLs
"""

import re
import sys
import os
from pathlib import Path


def extract_urls_from_markdown(markdown_path):
    """Extract URLs from markdown footnote references."""
    urls = []
    pattern = re.compile(r'^\[.*?\]:\s*(https?://[^\s]+)', re.MULTILINE)
    
    with open(markdown_path, 'r', encoding='utf-8') as f:
        content = f.read()
        matches = pattern.findall(content)
        urls.extend(matches)
    
    return urls


def create_checklist(markdown_path):
    """Create checklist from markdown file."""
    markdown_path = Path(markdown_path)
    
    if not markdown_path.exists():
        print(f"Error: File not found: {markdown_path}")
        return False
    
    # Extract URLs
    print(f"Extracting URLs from {markdown_path.name}...")
    urls = extract_urls_from_markdown(markdown_path)
    
    if not urls:
        print("Warning: No URLs found in the markdown file.")
        return False
    
    print(f"Found {len(urls)} URLs")
    
    # Create folder name from markdown filename (without extension)
    folder_name = markdown_path.stem
    output_dir = markdown_path.parent / folder_name
    
    # Create output directory
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
        print("Usage: python create_sourcing_checklist.py <markdown_file_path>")
        sys.exit(1)
    
    markdown_file = sys.argv[1]
    success = create_checklist(markdown_file)
    
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
