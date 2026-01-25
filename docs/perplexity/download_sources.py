#!/usr/bin/env python3
"""
Download papers from a sourcing checklist using direct downloads, Sci-Hub, and Gemini agents.

Usage:
    python download_sources.py <sourcing_checklist_path> [options]

Options:
    --start N    Start from item N (1-indexed, default: 1)
    --end M      End at item M (inclusive, default: last item)
    --workers W  Number of parallel workers (default: 2)
    --delay D    Delay in seconds between spawning workers (default: 3)
    --dry-run    Show what would be done without executing
"""

import subprocess
import sys
import os
import re
import time
import argparse
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Thread locks
checklist_lock = threading.Lock()
print_lock = threading.Lock()

# Track downloaded DOIs to detect duplicates: {doi: item_number}
downloaded_dois = {}
doi_lock = threading.Lock()


def thread_print(*args, **kwargs):
    """Thread-safe print with flush."""
    with print_lock:
        print(*args, **kwargs, flush=True)


def init_downloaded_dois(output_dir):
    """Scan existing files to populate downloaded_dois dict."""
    global downloaded_dois
    for pdf_file in output_dir.glob("item*.pdf"):
        match = re.match(r'item(\d+)_(.+)\.pdf', pdf_file.name)
        if match:
            item_num = int(match.group(1))
            doi_part = match.group(2)
            if doi_part.startswith('10.'):
                parts = doi_part.split('_', 1)
                if len(parts) == 2:
                    doi = parts[0] + '/' + parts[1]
                    downloaded_dois[doi] = item_num
    thread_print(f"Found {len(downloaded_dois)} existing DOIs")


def check_duplicate(doi, item_index, output_dir):
    """Check if DOI already downloaded. If so, create stub and return True."""
    if not doi:
        return False
    
    with doi_lock:
        if doi in downloaded_dois:
            original_item = downloaded_dois[doi]
            stub_name = f"item{item_index:03d}_duplicate_of_item{original_item:03d}"
            stub_path = output_dir / stub_name
            stub_path.write_text(f"Duplicate of item {original_item:03d}\nDOI: {doi}\n")
            thread_print(f"  [{item_index}] Duplicate of item {original_item:03d} (DOI: {doi})")
            return True
        return False


def register_doi(doi, item_index):
    """Register a newly downloaded DOI."""
    if doi:
        with doi_lock:
            if doi not in downloaded_dois:
                downloaded_dois[doi] = item_index


def parse_checklist(checklist_path):
    """Parse sourcing checklist and return list of (index, checked, url) tuples."""
    items = []
    pattern = re.compile(r'^(\d+)\.\s*\[(x?)\]\s*(https?://\S+)', re.IGNORECASE)
    
    with open(checklist_path, 'r', encoding='utf-8') as f:
        for line in f:
            match = pattern.match(line.strip())
            if match:
                index = int(match.group(1))
                checked = match.group(2).lower() == 'x'
                url = match.group(3)
                items.append((index, checked, url))
    
    return items


def update_checklist(checklist_path, index, checked=True):
    """Update a single item in the checklist to mark as checked (thread-safe)."""
    with checklist_lock:
        with open(checklist_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        pattern = re.compile(rf'^{index}\.\s*\[\s*\]')
        
        with open(checklist_path, 'w', encoding='utf-8') as f:
            for line in lines:
                if pattern.match(line.strip()):
                    line = re.sub(r'\[\s*\]', '[x]', line, count=1)
                f.write(line)


def extract_doi_from_url(url):
    """Extract DOI from URL if present."""
    # Nature: https://www.nature.com/articles/s44160-023-00424-1 -> 10.1038/s44160-023-00424-1
    nature_match = re.search(r'nature\.com/articles/([a-z0-9\-]+)', url, re.IGNORECASE)
    if nature_match:
        return f"10.1038/{nature_match.group(1)}"
    
    # Direct DOI patterns
    patterns = [
        r'doi[:/]+(10\.\d{4,}/[^\s/]+/[^\s/]+)',
        r'(10\.\d{4,}/[^\s/]+/[^\s/]+)',
        r'(10\.\d{4,}/[^\s/]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            doi = match.group(1)
            doi = re.sub(r'\.pdf$', '', doi, flags=re.IGNORECASE)
            return doi
    return None


def sanitize_filename(url):
    """Create a safe filename from URL."""
    name = url.split('/')[-1]
    if name.lower().endswith('.pdf'):
        name = name[:-4]
    name = re.sub(r'[^\w\-.]', '_', name)
    return name[:80]


def is_valid_pdf(filepath):
    """Check if file is a valid PDF."""
    try:
        with open(filepath, 'rb') as f:
            header = f.read(10)
            return header.startswith(b'%PDF')
    except:
        return False


def get_filename(url, item_index):
    """Generate filename for item based on DOI or URL."""
    doi = extract_doi_from_url(url)
    if doi:
        return f"item{item_index:03d}_{doi.replace('/', '_')}.pdf"
    
    arxiv_match = re.search(r'arxiv\.org/(?:abs|pdf)/(\d+\.\d+)', url)
    if arxiv_match:
        return f"item{item_index:03d}_{arxiv_match.group(1)}.pdf"
    
    return f"item{item_index:03d}_{sanitize_filename(url)}.pdf"


def direct_download(url, output_path):
    """Try direct curl download."""
    try:
        result = subprocess.run(
            ['curl', '-sL', '-o', str(output_path), 
             '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
             '-H', 'Accept: application/pdf',
             '--max-time', '30',
             url],
            capture_output=True, text=True, timeout=60
        )
        
        if output_path.exists():
            size = output_path.stat().st_size
            if size > 50000 and is_valid_pdf(output_path):
                return True, f"Direct download ({size} bytes)"
            output_path.unlink()
        return False, "Invalid or small file"
    except Exception as e:
        if output_path.exists():
            output_path.unlink()
        return False, str(e)


def try_scihub(doi, output_path):
    """Try Sci-Hub mirrors."""
    mirrors = ['https://sci-hub.ru', 'https://sci-hub.se', 'https://sci-hub.st']
    
    for mirror in mirrors:
        try:
            # Fetch Sci-Hub page
            result = subprocess.run(
                ['curl', '-sL', '--max-time', '15', f'{mirror}/{doi}'],
                capture_output=True, text=True, timeout=20
            )
            
            if 'not available' in result.stdout.lower():
                continue
            
            # Find PDF URL
            pdf_match = re.search(r'(https?://[^"\'>\s]+\.pdf[^"\'>\s]*)', result.stdout)
            if not pdf_match:
                pdf_match = re.search(r'src="(//[^"]+)"', result.stdout)
            
            if pdf_match:
                pdf_url = pdf_match.group(1)
                if pdf_url.startswith('//'):
                    pdf_url = 'https:' + pdf_url
                
                # Download PDF
                subprocess.run(
                    ['curl', '-sL', '-o', str(output_path), '--max-time', '60', pdf_url],
                    capture_output=True, timeout=90
                )
                
                if output_path.exists():
                    size = output_path.stat().st_size
                    if size > 50000 and is_valid_pdf(output_path):
                        return True, f"Sci-Hub ({size} bytes)"
                    output_path.unlink()
        except:
            continue
    
    return False, "Not on Sci-Hub"


def download_with_gemini(url, output_dir, item_index):
    """Use Gemini agent to download paper."""
    filename = get_filename(url, item_index)
    output_path = output_dir / filename
    
    prompt = f"""Download the PDF from this URL and save it to {output_dir}:
{url}

The file should be named: {filename}

If it's paywalled, try:
1. Check if there's a free PDF link on the page
2. Use Sci-Hub with the DOI: sci-hub.ru/DOI
3. Check for preprint on arxiv.org

After downloading, verify the file exists and is a valid PDF (starts with %PDF).
Report success or failure."""

    try:
        thread_print(f"    [{item_index}] Gemini agent starting...")
        result = subprocess.run(
            ['gemini', '--yolo', prompt],
            capture_output=True, text=True, timeout=180,
            cwd=str(output_dir)
        )
        
        # Check if file was downloaded
        time.sleep(2)
        if output_path.exists() and is_valid_pdf(output_path):
            size = output_path.stat().st_size
            return True, f"Gemini agent ({size} bytes)"
        
        # Check for any new PDF files
        for f in output_dir.glob(f"item{item_index:03d}*.pdf"):
            if is_valid_pdf(f):
                return True, f"Gemini agent: {f.name}"
        
        return False, "Gemini could not download"
    except subprocess.TimeoutExpired:
        return False, "Gemini timeout"
    except Exception as e:
        return False, f"Gemini error: {str(e)[:50]}"


def process_item(index, url, output_dir, checklist_path):
    """Process a single item."""
    doi = extract_doi_from_url(url)
    
    # Check for duplicate
    if check_duplicate(doi, index, output_dir):
        update_checklist(checklist_path, index, checked=True)
        return (index, True, "duplicate")
    
    filename = get_filename(url, index)
    output_path = output_dir / filename
    
    # Skip if already exists
    if output_path.exists() and is_valid_pdf(output_path):
        thread_print(f"[{index}] Already exists: {filename}")
        update_checklist(checklist_path, index, checked=True)
        register_doi(doi, index)
        return (index, True, "exists")
    
    thread_print(f"[{index}] Processing: {url[:60]}...")
    
    # Try direct download for PDFs
    if url.lower().endswith('.pdf'):
        success, msg = direct_download(url, output_path)
        if success:
            thread_print(f"[{index}] ✓ {msg}")
            update_checklist(checklist_path, index, checked=True)
            register_doi(doi, index)
            return (index, True, msg)
    
    # Try Sci-Hub if we have a DOI
    if doi:
        thread_print(f"  [{index}] Trying Sci-Hub for {doi}...")
        success, msg = try_scihub(doi, output_path)
        if success:
            thread_print(f"[{index}] ✓ {msg}")
            update_checklist(checklist_path, index, checked=True)
            register_doi(doi, index)
            return (index, True, msg)
    
    # Try Gemini agent
    thread_print(f"  [{index}] Trying Gemini agent...")
    success, msg = download_with_gemini(url, output_dir, index)
    if success:
        thread_print(f"[{index}] ✓ {msg}")
        update_checklist(checklist_path, index, checked=True)
        register_doi(doi, index)
        return (index, True, msg)
    
    thread_print(f"[{index}] ✗ Failed: {msg}")
    return (index, False, msg)


def main():
    parser = argparse.ArgumentParser(description='Download papers from sourcing checklist')
    parser.add_argument('checklist', help='Path to sourcing_checklist.md')
    parser.add_argument('--start', type=int, default=1, help='Start from item N')
    parser.add_argument('--end', type=int, default=None, help='End at item M')
    parser.add_argument('--workers', type=int, default=2, help='Parallel workers (default: 2)')
    parser.add_argument('--delay', type=float, default=3.0, help='Delay between workers (default: 3)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    
    args = parser.parse_args()
    
    checklist_path = Path(args.checklist).resolve()
    
    if not checklist_path.exists():
        print(f"Error: Checklist not found: {checklist_path}")
        sys.exit(1)
    
    output_dir = checklist_path.parent
    items = parse_checklist(checklist_path)
    
    if not items:
        print("Error: No items found in checklist")
        sys.exit(1)
    
    print(f"Found {len(items)} items in checklist")
    print(f"Output directory: {output_dir}")
    
    # Initialize downloaded DOIs from existing files
    init_downloaded_dois(output_dir)
    
    # Filter items by range
    start_idx = args.start
    end_idx = args.end if args.end else len(items)
    
    items_to_process = [
        (idx, url) for idx, checked, url in items
        if not checked and start_idx <= idx <= end_idx
    ]
    
    if not items_to_process:
        print("No unchecked items to process")
        sys.exit(0)
    
    print(f"\nProcessing {len(items_to_process)} items with {args.workers} workers")
    
    if args.dry_run:
        print("\n[DRY RUN MODE]")
        for idx, url in items_to_process:
            print(f"  Item {idx}: {url[:70]}")
        sys.exit(0)
    
    results = []
    success_count = 0
    fail_count = 0
    
    print(f"\n{'='*60}")
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        
        for i, (idx, url) in enumerate(items_to_process):
            if i > 0:
                time.sleep(args.delay)
            
            future = executor.submit(process_item, idx, url, output_dir, checklist_path)
            futures[future] = (idx, url)
        
        for future in as_completed(futures):
            idx, url = futures[future]
            try:
                result = future.result()
                results.append(result)
                if result[1]:
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                thread_print(f"[{idx}] Exception: {e}")
                fail_count += 1
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)
    print(f"Total processed: {len(results)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {fail_count}")
    
    failed_items = sorted([r[0] for r in results if not r[1]])
    if failed_items:
        print(f"Failed items: {failed_items}")


if __name__ == "__main__":
    main()
