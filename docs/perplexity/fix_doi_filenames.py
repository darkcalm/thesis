#!/usr/bin/env python3
"""
Fix PDF filenames in thesis/docs/perplexity by extracting DOIs from metadata/content.

Processes all three scopes and renames files from itemXXX_SUFFIX.pdf to itemXXX_DOI.pdf
where DOI is properly formatted (e.g., 10.XXXX_... with underscores instead of slashes).

For PDFs where DOI cannot be extracted, keeps them as-is.
"""

import os
import sys
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple

# DOI pattern: 10.XXXX/... (flexible pattern to catch most DOIs)
DOI_PATTERN = re.compile(
    r'10\.\d{4,}/[^\s,;.]+',
    re.IGNORECASE
)

# Alternative DOI pattern with underscores (as seen in filenames)
DOI_UNDERSCORE_PATTERN = re.compile(
    r'10\.\d{4,}_[^\s,;.]+',
    re.IGNORECASE
)


def extract_doi_from_metadata(pdf_path: str) -> Optional[str]:
    """
    Extract DOI from PDF metadata using pdfinfo.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        DOI string if found, None otherwise
    """
    try:
        result = subprocess.run(
            ['pdfinfo', pdf_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return None
        
        # Search for DOI in metadata
        for line in result.stdout.split('\n'):
            # Check if line contains DOI
            if 'doi' in line.lower():
                # Extract DOI from line
                match = DOI_PATTERN.search(line)
                if match:
                    return match.group(0)
        
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    except Exception as e:
        print(f"    Error reading metadata: {e}", file=sys.stderr)
        return None


def extract_doi_from_text(pdf_path: str) -> Optional[str]:
    """
    Extract DOI from PDF text content using pdftotext.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        DOI string if found, None otherwise
    """
    try:
        result = subprocess.run(
            ['pdftotext', pdf_path, '-'],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if result.returncode != 0:
            return None
        
        text = result.stdout
        
        # Search for DOI patterns
        match = DOI_PATTERN.search(text)
        if match:
            return match.group(0)
        
        # Try underscore variant
        match = DOI_UNDERSCORE_PATTERN.search(text)
        if match:
            return match.group(0)
        
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    except Exception as e:
        print(f"    Error extracting text: {e}", file=sys.stderr)
        return None


def normalize_doi_for_filename(doi: str) -> Optional[str]:
    """
    Normalize DOI to filename-safe format (10.XXXX_... with underscores).
    
    Args:
        doi: Raw DOI string (can have slashes or underscores)
        
    Returns:
        DOI formatted for use in filenames with underscores, or None
    """
    if not doi:
        return None
    
    # Clean up DOI first
    doi = doi.strip()
    
    # Remove trailing invalid characters
    doi = re.sub(r'[,;:.)]$', '', doi)
    
    if not doi.startswith('10.'):
        return None
    
    # If already in underscore format, return as-is
    if '/' not in doi and '_' in doi:
        match = re.match(r'(10\.\d{4,}_[^/]+)$', doi)
        if match:
            return match.group(1)
    
    # If in slash format, convert to underscore format for filenames
    if '/' in doi:
        # Find the first slash after "10.XXXX"
        match = re.match(r'(10\.(\d{4,}))/(.+)$', doi)
        if match:
            base = match.group(1)  # "10.XXXX"
            suffix = match.group(3)  # Everything after first /
            # Convert ALL slashes and other invalid chars to underscores for filename safety
            suffix = re.sub(r'[/\\]+', '_', suffix)
            # Remove any remaining problematic chars like parentheses
            suffix = re.sub(r'[()]+', '', suffix)
            return f"{base}_{suffix}"
    
    return None


def extract_doi(pdf_path: str) -> Optional[str]:
    """
    Extract DOI from PDF using multiple strategies.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        DOI string formatted for filenames (10.XXXX_...) if found, None otherwise
    """
    # Try metadata first (faster)
    doi = extract_doi_from_metadata(pdf_path)
    if doi:
        normalized = normalize_doi_for_filename(doi)
        if normalized:
            return normalized
    
    # Try text extraction
    doi = extract_doi_from_text(pdf_path)
    if doi:
        normalized = normalize_doi_for_filename(doi)
        if normalized:
            return normalized
    
    return None


def extract_item_number(filename: str) -> Optional[str]:
    """
    Extract item number from filename (e.g., "001" from "item001_suffix.pdf").
    
    Args:
        filename: Basename of the file
        
    Returns:
        Item number or None
    """
    match = re.match(r'item(\d+)_', filename)
    if match:
        return match.group(1)
    return None


def is_properly_formatted_doi_filename(filename: str) -> bool:
    """
    Check if filename is already properly formatted with a DOI.
    
    Args:
        filename: Basename of the file
        
    Returns:
        True if already properly formatted
    """
    # Pattern: item123_10.XXXX_...pdf
    return bool(re.search(r'item\d+_10\.\d{4,}_', filename))


def should_process_file(filename: str) -> bool:
    """
    Check if file should be processed.
    
    Args:
        filename: Basename of the file
        
    Returns:
        True if file should be processed, False otherwise
    """
    # Must be a PDF
    if not filename.lower().endswith('.pdf'):
        return False
    
    # Must match itemXXX_SUFFIX pattern
    if not re.match(r'item\d+_', filename):
        return False
    
    # Skip if already properly formatted with DOI
    if is_properly_formatted_doi_filename(filename):
        return False
    
    return True


def process_scope_directory(scope_dir: Path) -> Tuple[int, int]:
    """
    Process all PDFs in a scope directory.
    
    Args:
        scope_dir: Path to the scope directory
        
    Returns:
        Tuple of (renamed_count, skipped_count)
    """
    renamed = 0
    skipped = 0
    
    print(f"\nProcessing: {scope_dir.name}")
    print("=" * 70)
    
    if not scope_dir.exists():
        print(f"  Directory not found: {scope_dir}")
        return 0, 0
    
    # Find all PDFs
    pdf_files = sorted(scope_dir.glob('*.pdf'))
    
    if not pdf_files:
        print(f"  No PDF files found")
        return 0, 0
    
    print(f"  Found {len(pdf_files)} PDF files to process")
    
    for pdf_path in pdf_files:
        filename = pdf_path.name
        
        # Skip if not matching our pattern
        if not should_process_file(filename):
            continue
        
        item_num = extract_item_number(filename)
        if not item_num:
            skipped += 1
            continue
        
        print(f"\n  Processing: {filename}")
        
        # Extract DOI
        doi = extract_doi(str(pdf_path))
        
        if doi:
            # Create new filename
            new_filename = f"item{item_num}_{doi}.pdf"
            new_path = pdf_path.parent / new_filename
            
            # Check if rename would overwrite an existing file
            if new_path.exists() and new_path != pdf_path:
                print(f"    ⚠️  Cannot rename: target file already exists")
                print(f"       Current: {filename}")
                print(f"       Target:  {new_filename}")
                skipped += 1
                continue
            
            # Perform rename
            if new_path != pdf_path:
                try:
                    pdf_path.rename(new_path)
                    print(f"    ✓  Renamed to: {new_filename}")
                    renamed += 1
                except Exception as e:
                    print(f"    ✗  Error renaming: {e}", file=sys.stderr)
                    skipped += 1
            else:
                print(f"    -  No change needed")
        else:
            print(f"    ⚠️  Could not extract DOI, keeping as-is")
            skipped += 1
    
    return renamed, skipped


def main():
    """Main entry point."""
    base_dir = Path('/Users/para/Desktop/thesis/docs/perplexity')
    
    if not base_dir.exists():
        print(f"Error: Base directory not found: {base_dir}")
        sys.exit(1)
    
    print("PDF Filename DOI Fixer")
    print("=" * 70)
    print(f"Base directory: {base_dir}")
    
    total_renamed = 0
    total_skipped = 0
    
    # Process all scope directories
    scope_dirs = sorted([d for d in base_dir.iterdir() if d.is_dir() and d.name.startswith('scope')])
    
    if not scope_dirs:
        print("No scope directories found")
        sys.exit(1)
    
    for scope_dir in scope_dirs:
        renamed, skipped = process_scope_directory(scope_dir)
        total_renamed += renamed
        total_skipped += skipped
    
    # Also check for PDFs directly in base_dir
    print(f"\nProcessing: {base_dir.name} (root)")
    print("=" * 70)
    
    root_pdfs = sorted([f for f in base_dir.glob('*.pdf') if f.is_file()])
    if root_pdfs:
        print(f"  Found {len(root_pdfs)} PDF files")
        for pdf_path in root_pdfs:
            filename = pdf_path.name
            if should_process_file(filename):
                item_num = extract_item_number(filename)
                if item_num:
                    print(f"\n  Processing: {filename}")
                    doi = extract_doi(str(pdf_path))
                    
                    if doi:
                        new_filename = f"item{item_num}_{doi}.pdf"
                        new_path = pdf_path.parent / new_filename
                        
                        if new_path.exists() and new_path != pdf_path:
                            print(f"    ⚠️  Cannot rename: target file already exists")
                            total_skipped += 1
                            continue
                        
                        if new_path != pdf_path:
                            try:
                                pdf_path.rename(new_path)
                                print(f"    ✓  Renamed to: {new_filename}")
                                total_renamed += 1
                            except Exception as e:
                                print(f"    ✗  Error renaming: {e}", file=sys.stderr)
                                total_skipped += 1
                    else:
                        print(f"    ⚠️  Could not extract DOI, keeping as-is")
                        total_skipped += 1
    else:
        print("  No PDF files found in root")
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"✓  Renamed: {total_renamed}")
    print(f"⚠️  Skipped: {total_skipped}")
    print(f"Total processed: {total_renamed + total_skipped}")


if __name__ == '__main__':
    main()
