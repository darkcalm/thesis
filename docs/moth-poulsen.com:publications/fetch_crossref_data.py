#!/usr/bin/env python3
"""
Fetch publication data from Crossref API based on CSV titles.
Processes each publication row and retrieves summary information.
"""

import csv
import json
import time
import sys
from pathlib import Path
from typing import Optional, Dict, Any
import urllib.request
import urllib.error


def fetch_from_crossref(title: str, retries: int = 3) -> Optional[Dict[str, Any]]:
    """
    Query Crossref API for a publication by title.
    
    Args:
        title: Publication title to search
        retries: Number of retry attempts on failure
        
    Returns:
        Dictionary with publication data or None if not found
    """
    # URL encode the title
    encoded_title = urllib.parse.quote(title)
    url = f"https://api.crossref.org/v1/works?query.title={encoded_title}&rows=1"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; Thesis Publication Fetcher)'
    }
    
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                if data.get('message', {}).get('items'):
                    return data['message']['items'][0]
                return None
                
        except urllib.error.HTTPError as e:
            if e.code == 429:  # Too many requests
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"  Rate limited. Waiting {wait_time}s...", file=sys.stderr)
                time.sleep(wait_time)
            else:
                print(f"  HTTP Error {e.code}: {e.reason}", file=sys.stderr)
                return None
        except Exception as e:
            print(f"  Error (attempt {attempt + 1}/{retries}): {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(1)
    
    return None


def extract_summary(crossref_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract relevant summary information from Crossref data.
    
    Args:
        crossref_data: Full Crossref API response
        
    Returns:
        Dictionary with extracted summary fields
    """
    return {
        'doi': crossref_data.get('DOI'),
        'title': crossref_data.get('title', [''])[0] if isinstance(crossref_data.get('title'), list) else crossref_data.get('title'),
        'authors': [
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in crossref_data.get('author', [])
        ][:5],  # First 5 authors
        'published_date': crossref_data.get('published-print', {}).get('date-parts', [[None]])[0] if crossref_data.get('published-print') else None,
        'type': crossref_data.get('type'),
        'container_title': crossref_data.get('container-title', [''])[0] if isinstance(crossref_data.get('container-title'), list) else crossref_data.get('container-title'),
        'abstract': crossref_data.get('abstract'),
        'url': crossref_data.get('URL'),
    }


def process_publications(csv_file: Path, output_dir: Optional[Path] = None) -> None:
    """
    Process all publications in CSV and fetch Crossref data.
    Saves a TXT file for each publication containing the summary.
    
    Args:
        csv_file: Path to input CSV file
        output_dir: Path to save TXT files (default: {csv_stem}_summaries/)
    """
    if not csv_file.exists():
        print(f"Error: CSV file not found: {csv_file}")
        sys.exit(1)
    
    if output_dir is None:
        output_dir = csv_file.parent / f"{csv_file.stem}_summaries"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    processed = 0
    found = 0
    
    print(f"Reading CSV: {csv_file}")
    print(f"Output will be saved to: {output_dir}\n")
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    total_rows = len(rows)
    
    for idx, row in enumerate(rows, 1):
        pub_number = row.get('Number', 'N/A')
        title = row.get('Title', '').strip()
        
        if not title:
            continue
        
        processed += 1
        print(f"[{idx}/{total_rows}] #{pub_number}: {title[:60]}...", end='', flush=True)
        
        crossref_data = fetch_from_crossref(title)
        
        if crossref_data:
            summary = extract_summary(crossref_data)
            found += 1
            
            # Create TXT file for this publication
            filename = output_dir / f"{pub_number}_{title[:50].replace('/', '_').replace(' ', '_')}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"Publication #{pub_number}\n")
                f.write(f"{'='*60}\n\n")
                f.write(f"Title: {summary['title']}\n\n")
                
                if summary['authors']:
                    f.write(f"Authors: {', '.join(summary['authors'])}\n\n")
                
                if summary['published_date']:
                    f.write(f"Published: {summary['published_date']}\n\n")
                
                if summary['container_title']:
                    f.write(f"Journal/Conference: {summary['container_title']}\n\n")
                
                if summary['type']:
                    f.write(f"Type: {summary['type']}\n\n")
                
                if summary['doi']:
                    f.write(f"DOI: {summary['doi']}\n\n")
                
                if summary['url']:
                    f.write(f"URL: {summary['url']}\n\n")
                
                if summary['abstract']:
                    f.write(f"Abstract:\n{summary['abstract']}\n")
            
            print(" ✓")
        else:
            print(" ✗")
        
        # Rate limiting: wait between requests
        time.sleep(1)
    
    print(f"\n{'='*60}")
    print(f"Processed: {processed}/{total_rows} publications")
    print(f"Found: {found}/{processed} in Crossref")
    print(f"Success rate: {100*found/processed:.1f}%")
    print(f"Results saved to: {output_dir}")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Fetch publication data from Crossref API based on CSV titles"
    )
    parser.add_argument(
        'csv_file',
        type=Path,
        help='Path to CSV file with publications'
    )
    parser.add_argument(
        '-o', '--output',
        type=Path,
        help='Output directory for TXT files (default: {csv_stem}_summaries/)'
    )
    
    args = parser.parse_args()
    
    try:
        process_publications(args.csv_file, args.output)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    import urllib.parse
    main()
