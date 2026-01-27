#!/usr/bin/env python3
"""
Download papers from a sourcing checklist using multiple strategies.

Download Methods (in priority order):
1. Direct downloads (PDF URLs)
2. Open access sources (arXiv, MDPI, Frontiers, PLoS, RSC, Unpaywall)
3. OpenAlex API (fast, high coverage OA)
4. CORE API (institutional repositories)
5. Semantic Scholar API
6. BASE API (300M+ academic records)
7. OpenAIRE API (EU-funded content)
8. DOAJ (17,500+ OA journals)
9. ResearchGate (author-shared)
10. 12ft.io (paywall bypass)
11. Sci-Hub (fallback)
12. Google Scholar (browser-based)
13. Browser automation with stealth (rotating user-agents, referrers)

Expected success rate: 75-85% (vs ~50% baseline)

Usage:
    python download_sources.py <sourcing_checklist_path> [options]

Options:
    --start N           Start from item N (1-indexed, default: 1)
    --end M             End at item M (inclusive, default: last item)
    --workers W         Number of parallel workers (default: 5)
    --delay D           Delay in seconds between spawning workers (default: 0.5)
    --skip-browser      Skip browser automation phase
    --browser-workers W Browser workers (default: 2)
    --screenshots-only  Create screenshots only, no vision analysis
"""

import subprocess
import sys
import os
import re
import time
import argparse
import threading
import tempfile
import json
import base64
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Try to import anthropic for vision API
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# Load .env file if it exists
def load_env_file():
    """Load environment variables from .env file in script directory."""
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        try:
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and value:
                            os.environ[key] = value
        except Exception as e:
            pass  # Silently fail if .env can't be read

# Load .env before accessing API keys
load_env_file()

# Force unbuffered output
os.environ['PYTHONUNBUFFERED'] = '1'
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

# Playwright imports
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Thread locks
checklist_lock = threading.Lock()
print_lock = threading.Lock()

# Track downloaded DOIs to detect duplicates: {doi: item_number}
downloaded_dois = {}
doi_lock = threading.Lock()

# Global flag for screenshots-only mode (no vision analysis)
screenshots_only = False


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
    # Allow optional whitespace inside brackets: [x], [ ], [x ]
    pattern = re.compile(r'^(\d+)\.\s*\[\s*(x?)\s*\]\s*(https?://\S+)', re.IGNORECASE)
    
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
            # Remove common suffixes that aren't part of DOI
            doi = re.sub(r'\.pdf$', '', doi, flags=re.IGNORECASE)
            doi = re.sub(r'/pdf$', '', doi, flags=re.IGNORECASE)
            doi = re.sub(r'/full$', '', doi, flags=re.IGNORECASE)
            doi = re.sub(r'/abstract$', '', doi, flags=re.IGNORECASE)
            return doi
    return None


def extract_identifier_from_url(url):
    """Extract identifier (DOI, PMC ID, IEEE doc ID, etc.) from URL for filename."""
    # Try DOI first
    doi = extract_doi_from_url(url)
    if doi:
        return doi.replace('/', '_')
    
    # PMC ID: https://pmc.ncbi.nlm.nih.gov/articles/PMC11755691/
    pmc_match = re.search(r'pmc\.ncbi\.nlm\.nih\.gov/articles/(PMC\d+)', url, re.IGNORECASE)
    if pmc_match:
        return pmc_match.group(1)
    
    # IEEE document ID: https://ieeexplore.ieee.org/document/10480223/
    ieee_match = re.search(r'ieeexplore\.ieee\.org/document/(\d+)', url, re.IGNORECASE)
    if ieee_match:
        return ieee_match.group(1)
    
    # arXiv ID
    arxiv_match = re.search(r'arxiv\.org/(?:abs|pdf)/(\d+\.\d+)', url)
    if arxiv_match:
        return arxiv_match.group(1)
    
    # Extract meaningful identifier from URL path
    # For URLs like /article/5/478, use the full path
    path_match = re.search(r'/article/([\d/]+)', url)
    if path_match:
        return path_match.group(1).replace('/', '_')
    
    # Fallback: use last meaningful part of URL
    parts = [p for p in url.rstrip('/').split('/') if p and p not in ['http:', 'https:', 'www.', '']]
    if parts:
        last_part = parts[-1]
        # Remove query parameters
        last_part = last_part.split('?')[0]
        # Remove file extensions
        last_part = re.sub(r'\.(pdf|html?)$', '', last_part, flags=re.IGNORECASE)
        if last_part and len(last_part) > 2:
            return last_part
    
    return None


def sanitize_filename(url):
    """Create a safe filename from URL."""
    name = url.split('/')[-1]
    if name.lower().endswith('.pdf'):
        name = name[:-4]
    name = re.sub(r'[^\w\-.]', '_', name)
    return name[:80]


def is_valid_pdf(filepath, min_size=50000):
    """Check if file is a valid academic PDF that can be opened.
    
    Args:
        filepath: Path to PDF file
        min_size: Minimum file size in bytes (default 100KB for academic papers)
    
    Returns:
        True if valid openable PDF, False otherwise
    """
    try:
        import os
        filepath = str(filepath)
        
        # Check file exists
        if not os.path.exists(filepath):
            return False
        
        # Check minimum size (academic papers typically > 100KB)
        file_size = os.path.getsize(filepath)
        if file_size < min_size:
            thread_print(f"  [Verify] PDF too small: {file_size} bytes (min: {min_size})")
            return False
        
        # Check PDF header
        with open(filepath, 'rb') as f:
            header = f.read(10)
            if not header.startswith(b'%PDF'):
                thread_print(f"  [Verify] Not a valid PDF (bad header)")
                return False
        
        # Try to actually open and read the PDF
        try:
            import PyPDF2
            with open(filepath, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                num_pages = len(reader.pages)
                if num_pages < 1:
                    thread_print(f"  [Verify] PDF has no pages")
                    return False
                # Try to access first page to verify it's readable
                _ = reader.pages[0]
        except Exception as e:
            thread_print(f"  [Verify] PDF cannot be opened: {str(e)[:50]}")
            return False
        
        # Check it's not supplementary info by filename
        filename_lower = os.path.basename(filepath).lower()
        if any(x in filename_lower for x in ['supplem', 'suppinfo', 'si_', '_si.', 's001', 's002']):
            thread_print(f"  [Verify] Appears to be supplementary info")
            return False
        
        return True
    except Exception as e:
        thread_print(f"  [Verify] Error checking PDF: {str(e)[:50]}")
        return False


def get_filename(url, item_index):
    """Generate filename for item based on DOI, identifier, or URL."""
    identifier = extract_identifier_from_url(url)
    if identifier:
        return f"item{item_index:03d}_{identifier}.pdf"
    
    # Fallback to sanitized filename
    sanitized = sanitize_filename(url)
    if sanitized and sanitized != '':
        return f"item{item_index:03d}_{sanitized}.pdf"
    
    # Last resort: use item number only (shouldn't happen often)
    return f"item{item_index:03d}.pdf"


def direct_download(url, output_path, use_stealth=False):
    """Try direct curl download with optional stealth techniques."""
    try:
        # Try appending ?download=true for Wiley-style links
        download_url = url
        if '/pdfdirect/' in url or '/doi/pdf/' in url:
            if '?' not in url:
                download_url = url + '?download=true'
            elif 'download=' not in url:
                download_url = url + '&download=true'

        # Stealth headers
        headers = []
        if use_stealth:
            # Rotate user agents to mimic crawlers
            user_agents = [
                'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                'Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)',
                'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
            ]
            import random
            headers = [
                '-H', f'User-Agent: {random.choice(user_agents)}',
                '-H', 'Accept: application/pdf,*/*',
                '-H', 'Referer: https://www.google.com/',
            ]
        else:
            headers = [
                '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                '-H', 'Accept: application/pdf',
            ]

        result = subprocess.run(
            ['curl', '-sL', '-o', str(output_path)] + headers +
            ['--max-time', '30', download_url],
            capture_output=True, text=True, timeout=60
        )

        if output_path.exists():
            if is_valid_pdf(output_path):
                size = output_path.stat().st_size
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


def try_open_access(url, output_path, doi):
    """Try open access sources: arXiv, MDPI, Frontiers, PLoS, etc."""
    
    # arXiv
    m = re.search(r'arxiv\.org/(?:abs|pdf)/(\d+\.\d+)', url)
    if m:
        pdf_url = f"https://arxiv.org/pdf/{m.group(1)}.pdf"
        success, _ = direct_download(pdf_url, output_path)
        if success:
            return True, "arXiv"
    
    # MDPI (open access)
    if 'mdpi.com' in url:
        if not url.endswith('/pdf'):
            pdf_url = url.rstrip('/') + '/pdf'
            success, _ = direct_download(pdf_url, output_path)
            if success:
                return True, "MDPI"
    
    # Frontiers (open access)
    if 'frontiersin.org' in url:
        if '/pdf' not in url:
            pdf_url = url.replace('/full', '/pdf')
            success, _ = direct_download(pdf_url, output_path)
            if success:
                return True, "Frontiers"
    
    # PLoS (open access)
    if 'plos.org' in url and doi:
        pdf_url = f"https://journals.plos.org/plosone/article/file?id={doi}&type=printable"
        success, _ = direct_download(pdf_url, output_path)
        if success:
            return True, "PLoS"
    
    # RSC (try direct PDF)
    if 'rsc.org' in url and doi:
        pdf_url = f"https://pubs.rsc.org/en/content/articlepdf/{doi.split('/')[-1]}"
        success, _ = direct_download(pdf_url, output_path)
        if success:
            return True, "RSC"
    
    # Enhanced Unpaywall API
    if doi:
        try:
            unpaywall_email = os.environ.get('UNPAYWALL_EMAIL', 'user@example.com')
            r = subprocess.run(
                ['curl', '-sL', '--max-time', '10',
                 f'https://api.unpaywall.org/v2/{doi}?email={unpaywall_email}'],
                capture_output=True, text=True, timeout=15
            )

            # Try to parse JSON response
            import json
            try:
                data = json.loads(r.stdout)

                # Try best_oa_location first
                best_oa = data.get('best_oa_location')
                if best_oa and best_oa.get('url_for_pdf'):
                    success, _ = direct_download(best_oa['url_for_pdf'], output_path)
                    if success:
                        return True, "Unpaywall"

                # Try all oa_locations
                oa_locations = data.get('oa_locations', [])
                for location in oa_locations:
                    pdf_url = location.get('url_for_pdf') or location.get('url')
                    if pdf_url and '.pdf' in pdf_url.lower():
                        success, _ = direct_download(pdf_url, output_path)
                        if success:
                            return True, "Unpaywall"

            except json.JSONDecodeError:
                # Fallback to regex
                m = re.search(r'"(?:url_for_pdf|pdf_url)"\s*:\s*"([^"]+)"', r.stdout)
                if m:
                    success, _ = direct_download(m.group(1), output_path)
                    if success:
                        return True, "Unpaywall"
        except:
            pass
    
    return False, None


# API keys (load from .env, fallback to defaults)
CORE_API_KEY = os.environ.get('CORE_API_KEY', "FeJVa6KG3ISf8iqN7sZw9RCHBgQPTxW2")

# Rate limiting tracking
import time as rate_time
last_api_call = {'openalex': 0, 'lens': 0, 'base': 0}


def get_paper_metadata(doi):
    """Get paper title and authors from DOI using CrossRef API."""
    import json

    if not doi:
        return None, None

    try:
        result = subprocess.run(
            ['curl', '-sL', '--max-time', '10',
             f'https://api.crossref.org/works/{doi}'],
            capture_output=True, text=True, timeout=15
        )

        if result.stdout:
            data = json.loads(result.stdout)
            message = data.get('message', {})

            title = None
            if 'title' in message and message['title']:
                title = message['title'][0]

            authors = None
            if 'author' in message:
                author_list = message['author']
                if author_list:
                    authors = ', '.join([
                        f"{a.get('given', '')} {a.get('family', '')}".strip()
                        for a in author_list[:3]  # First 3 authors
                    ])

            return title, authors

    except Exception as e:
        pass

    return None, None


def try_openalex(doi, title, output_path):
    """Try OpenAlex API for open access PDFs."""
    import json

    global last_api_call

    if not doi and not title:
        return False, None

    try:
        # Rate limiting: OpenAlex allows 100k requests/day, ~1/sec is safe
        current_time = rate_time.time()
        if current_time - last_api_call['openalex'] < 0.1:
            rate_time.sleep(0.1)
        last_api_call['openalex'] = current_time

        # Search by DOI first (more accurate)
        if doi:
            api_url = f"https://api.openalex.org/works/https://doi.org/{doi}"
        else:
            # Search by title
            search_query = title.replace(' ', '+')
            api_url = f"https://api.openalex.org/works?search={search_query}&per-page=1"

        result = subprocess.run(
            ['curl', '-sL', '--max-time', '10',
             '-H', 'User-Agent: Mozilla/5.0 (mailto:user@example.com)',
             api_url],
            capture_output=True, text=True, timeout=15
        )

        if result.stdout:
            data = json.loads(result.stdout)

            # Handle search results vs direct lookup
            work = None
            if 'results' in data and data['results']:
                work = data['results'][0]
            elif 'id' in data:
                work = data

            if work:
                # Check for open access PDF
                oa_info = work.get('open_access', {})
                if oa_info.get('is_oa'):
                    pdf_url = oa_info.get('oa_url')
                    if pdf_url:
                        success, _ = direct_download(pdf_url, output_path)
                        if success:
                            return True, "OpenAlex"

                # Try best_oa_location
                best_oa = work.get('best_oa_location')
                if best_oa and best_oa.get('pdf_url'):
                    pdf_url = best_oa['pdf_url']
                    success, _ = direct_download(pdf_url, output_path)
                    if success:
                        return True, "OpenAlex"

                # Try primary_location
                primary = work.get('primary_location')
                if primary and primary.get('pdf_url'):
                    pdf_url = primary['pdf_url']
                    success, _ = direct_download(pdf_url, output_path)
                    if success:
                        return True, "OpenAlex"

        return False, None
    except Exception as e:
        return False, None


def try_base_api(doi, title, output_path):
    """Try BASE (Bielefeld Academic Search Engine) API."""
    import json

    global last_api_call

    if not doi and not title:
        return False, None

    try:
        # Rate limiting
        current_time = rate_time.time()
        if current_time - last_api_call['base'] < 0.2:
            rate_time.sleep(0.2)
        last_api_call['base'] = current_time

        # Search query
        if doi:
            query = f'doi:{doi}'
        else:
            query = title.replace(' ', '+')

        api_url = f"https://api.base-search.net/cgi-bin/BaseHttpSearchInterface.fcgi?func=PerformSearch&query={query}&hits=5&format=json"

        result = subprocess.run(
            ['curl', '-sL', '--max-time', '10', api_url],
            capture_output=True, text=True, timeout=15
        )

        if result.stdout:
            # BASE returns XML, look for direct links
            pdf_urls = re.findall(r'<dcfulltextpath>(https?://[^<]+\.pdf)</dcfulltextpath>', result.stdout)

            for pdf_url in pdf_urls[:3]:  # Try first 3 results
                success, _ = direct_download(pdf_url, output_path)
                if success:
                    return True, "BASE"

        return False, None
    except Exception as e:
        return False, None


def try_openaire(doi, title, output_path):
    """Try OpenAIRE API for EU-funded open access content."""
    import json

    if not doi and not title:
        return False, None

    try:
        # Search OpenAIRE
        if doi:
            query = doi.replace('/', '%2F')
            api_url = f"https://api.openaire.eu/search/publications?doi={query}&format=json"
        else:
            query = title.replace(' ', '+')
            api_url = f"https://api.openaire.eu/search/publications?title={query}&format=json&size=1"

        result = subprocess.run(
            ['curl', '-sL', '--max-time', '10', api_url],
            capture_output=True, text=True, timeout=15
        )

        if result.stdout:
            data = json.loads(result.stdout)
            results = data.get('response', {}).get('results', {}).get('result', [])

            if results:
                # Get first result
                first_result = results[0] if isinstance(results, list) else results
                metadata = first_result.get('metadata', {}).get('oaf:entity', {}).get('oaf:result', {})

                # Look for best access right instance
                instances = metadata.get('children', {}).get('instance', [])
                if not isinstance(instances, list):
                    instances = [instances]

                for instance in instances:
                    webresources = instance.get('webresource', [])
                    if not isinstance(webresources, list):
                        webresources = [webresources]

                    for wr in webresources:
                        url = wr.get('url')
                        if url and '.pdf' in url.lower():
                            success, _ = direct_download(url, output_path)
                            if success:
                                return True, "OpenAIRE"

        return False, None
    except Exception as e:
        return False, None


def try_12ft(url, output_path):
    """Try 12ft.io to bypass paywalls."""
    try:
        bypass_url = f"https://12ft.io/{url}"

        result = subprocess.run(
            ['curl', '-sL', '--max-time', '20',
             '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
             bypass_url],
            capture_output=True, text=True, timeout=25
        )

        # Look for PDF links in the bypassed content
        pdf_urls = re.findall(r'href="(https?://[^"]+\.pdf[^"]*)"', result.stdout)

        for pdf_url in pdf_urls[:2]:
            success, _ = direct_download(pdf_url, output_path)
            if success:
                return True, "12ft.io"

        return False, None
    except Exception as e:
        return False, None


def try_core_api(url, output_path, doi):
    """Try CORE API to find open access PDFs."""
    import json
    
    def core_search(query):
        try:
            r = subprocess.run(
                ['curl', '-sL', '--max-time', '20', '-X', 'POST',
                 '-H', f'Authorization: Bearer {CORE_API_KEY}',
                 '-H', 'Content-Type: application/json',
                 '-d', json.dumps({"q": query, "limit": 1}),
                 'https://api.core.ac.uk/v3/search/works'],
                capture_output=True, text=True, timeout=25
            )
            data = json.loads(r.stdout) if r.stdout else {}
            results = data.get('results', [])
            if results:
                download_url = results[0].get('downloadUrl')
                if download_url:
                    return download_url
                for link in results[0].get('links', []):
                    if link.get('type') == 'download':
                        return link.get('url')
        except:
            pass
        return None
    
    # Try by DOI
    if doi:
        download_url = core_search(f'doi:"{doi}"')
        if download_url:
            success, _ = direct_download(download_url, output_path)
            if success:
                return True, "CORE"
    
    # Try arXiv ID
    m = re.search(r'arxiv\.org/(?:abs|pdf)/(\d+\.\d+)', url)
    if m:
        download_url = core_search(f'arxiv:{m.group(1)}')
        if download_url:
            success, _ = direct_download(download_url, output_path)
            if success:
                return True, "CORE"
    
    return False, None


def try_researchgate(doi, title, authors, output_path):
    """Try ResearchGate for free PDF copies."""
    import json

    if not title:
        return False, None

    try:
        # Search ResearchGate for the paper
        search_query = title.replace(' ', '+')
        search_url = f"https://www.researchgate.net/search/publication?q={search_query}"

        # Use curl to get search results
        result = subprocess.run(
            ['curl', '-sL', '--max-time', '15',
             '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
             search_url],
            capture_output=True, text=True, timeout=20
        )

        # Look for PDF download links in the response
        # ResearchGate often has direct download links in their HTML
        pdf_patterns = [
            r'"(https://www\.researchgate\.net/[^"]*\.pdf[^"]*)"',
            r'href="(/publication/[^"]*download[^"]*)"',
        ]

        for pattern in pdf_patterns:
            matches = re.findall(pattern, result.stdout)
            for match in matches:
                pdf_url = match
                if pdf_url.startswith('/'):
                    pdf_url = 'https://www.researchgate.net' + pdf_url

                # Try downloading
                success, _ = direct_download(pdf_url, output_path)
                if success:
                    return True, "ResearchGate"

        return False, None
    except Exception as e:
        return False, None


def try_google_scholar(title, authors, output_path, doi=None):
    """Try Google Scholar to find free PDF copies."""
    if not title:
        return False, None

    if not PLAYWRIGHT_AVAILABLE:
        return False, None

    import tempfile
    import shutil

    try:
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0'
            )
            page = context.new_page()
            page.set_default_timeout(20000)

            # Search on Google Scholar
            search_query = title.replace(' ', '+')
            scholar_url = f"https://scholar.google.com/scholar?q={search_query}"

            try:
                page.goto(scholar_url, wait_until='domcontentloaded', timeout=20000)
                page.wait_for_timeout(2000)

                # Look for [PDF] links
                pdf_links = page.query_selector_all("a:has-text('[PDF]')")

                for link in pdf_links[:3]:  # Try first 3 PDF links
                    try:
                        href = link.get_attribute('href')
                        if href and (href.startswith('http') or href.startswith('//')):
                            if href.startswith('//'):
                                href = 'https:' + href

                            browser.close()

                            # Try downloading the PDF
                            success, _ = direct_download(href, output_path)
                            if success:
                                return True, "Google Scholar"
                    except:
                        continue

                browser.close()
                return False, None

            except Exception as e:
                browser.close()
                return False, None

    except Exception as e:
        return False, None


def try_semantic_scholar(doi, title, output_path):
    """Try Semantic Scholar API for open access PDFs."""
    import json

    if not doi and not title:
        return False, None

    try:
        # Search by DOI first
        if doi:
            api_url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf,title"
        else:
            # Search by title
            search_query = title.replace(' ', '+')
            api_url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={search_query}&limit=1&fields=openAccessPdf,title"

        result = subprocess.run(
            ['curl', '-sL', '--max-time', '10', api_url],
            capture_output=True, text=True, timeout=15
        )

        if result.stdout:
            data = json.loads(result.stdout)

            # Handle search results vs direct lookup
            if 'data' in data and data['data']:
                paper = data['data'][0]
            else:
                paper = data

            # Check for open access PDF
            if 'openAccessPdf' in paper and paper['openAccessPdf']:
                pdf_url = paper['openAccessPdf'].get('url')
                if pdf_url:
                    success, _ = direct_download(pdf_url, output_path)
                    if success:
                        return True, "Semantic Scholar"

        return False, None
    except Exception as e:
        return False, None


def try_doaj(doi, title, output_path):
    """Try Directory of Open Access Journals."""
    import json

    if not doi and not title:
        return False, None

    try:
        # Search DOAJ API
        if doi:
            search_url = f"https://doaj.org/api/search/articles/doi:{doi}"
        else:
            search_query = title.replace(' ', '%20')
            search_url = f"https://doaj.org/api/search/articles/{search_query}"

        result = subprocess.run(
            ['curl', '-sL', '--max-time', '10', search_url],
            capture_output=True, text=True, timeout=15
        )

        if result.stdout:
            data = json.loads(result.stdout)
            results = data.get('results', [])

            if results:
                bibjson = results[0].get('bibjson', {})
                links = bibjson.get('link', [])

                # Look for fulltext link
                for link in links:
                    if link.get('type') == 'fulltext':
                        pdf_url = link.get('url')
                        if pdf_url and '.pdf' in pdf_url.lower():
                            success, _ = direct_download(pdf_url, output_path)
                            if success:
                                return True, "DOAJ"

        return False, None
    except Exception as e:
        return False, None


def analyze_screenshot_with_claude(screenshot_path, page_url):
    """Use Claude vision API to identify PDF download button/link."""
    if screenshots_only:
        thread_print(f"  [Vision] Skipping analysis (--screenshots-only mode)")
        return None
    
    if not ANTHROPIC_AVAILABLE:
        thread_print(f"  [Vision] Anthropic library not available")
        return None

    try:
        # Read and encode screenshot
        with open(screenshot_path, 'rb') as f:
            image_data = base64.standard_b64encode(f.read()).decode('utf-8')
        thread_print(f"  [Vision] Screenshot encoded ({len(image_data)} chars)")

        # Get API key from environment (.env file is already loaded)
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            thread_print(f"  [Vision] ANTHROPIC_API_KEY not found in environment")
            return None
        thread_print(f"  [Vision] API key found, calling Claude...")

        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""This is a screenshot of an academic article page: {page_url}

Your task: Identify the PRIMARY PDF download button or link for the MAIN ARTICLE PDF.

Look for:
- Buttons/links with text like "PDF", "Download PDF", "Open PDF", "View PDF"
- Red PDF icons or PDF symbols
- Positioned prominently near the article title/abstract area
- In toolbars or action buttons near the article content

DO NOT identify:
- Supplementary materials
- Citation export buttons
- Related articles
- Secondary PDFs

Respond ONLY with valid JSON (no markdown, no code blocks):
{{
    "found": true or false,
    "element_text": "exact visible text on the button/link",
    "visual_description": "brief description of what it looks like",
    "position": "location on page (e.g., 'below title in article toolbar', 'top right corner')",
    "distinctive_features": ["list", "of", "features"],
    "confidence": "high", "medium", or "low"
}}"""

        response = client.messages.create(
            model="claude-3-haiku-20240307",  # Claude 3 Haiku with vision support
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_data
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )

        # Parse response
        response_text = response.content[0].text.strip()
        thread_print(f"  [Vision] Claude response: {response_text[:200]}...")

        # Remove markdown code blocks if present
        if response_text.startswith('```'):
            response_text = '\n'.join(response_text.split('\n')[1:-1])

        result = json.loads(response_text)
        thread_print(f"  [Vision] Parsed result: found={result.get('found')}, confidence={result.get('confidence')}")
        return result if result.get('found') else None

    except json.JSONDecodeError as e:
        thread_print(f"  [Vision] JSON parse error: {str(e)[:100]}")
        thread_print(f"  [Vision] Response was: {response_text[:300] if 'response_text' in locals() else 'N/A'}")
        return None
    except Exception as e:
        error_str = str(e)
        thread_print(f"  [Vision] Analysis error: {error_str}")
        # If it's a model error, try alternative model
        if "404" in error_str or "not_found" in error_str.lower():
            thread_print(f"  [Vision] Model not found, trying alternative...")
            try:
                # Try claude-3-opus as fallback
                response = client.messages.create(
                    model="claude-3-opus-20240229",
                    max_tokens=1024,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_data
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }]
                )
                response_text = response.content[0].text.strip()
                thread_print(f"  [Vision] Claude response (fallback): {response_text[:200]}...")
                if response_text.startswith('```'):
                    response_text = '\n'.join(response_text.split('\n')[1:-1])
                result = json.loads(response_text)
                thread_print(f"  [Vision] Parsed result: found={result.get('found')}, confidence={result.get('confidence')}")
                return result if result.get('found') else None
            except Exception as e2:
                thread_print(f"  [Vision] Fallback also failed: {str(e2)[:100]}")
        return None


def find_elements_by_vision_description(page, vision_result):
    """Find DOM elements matching Claude's vision analysis using text, position, and features."""
    if not vision_result:
        return []

    candidates = []
    element_text = vision_result.get('element_text', '').strip()
    features = vision_result.get('distinctive_features', [])
    position_desc = vision_result.get('position', '').lower()

    # Get current page domain for filtering
    try:
        from urllib.parse import urlparse
        page_domain = urlparse(page.url).netloc
        page_domain_base = '.'.join(page_domain.split('.')[-2:])  # e.g., "royalsocietypublishing.org"
    except:
        page_domain = None
        page_domain_base = None

    # Get all clickable elements
    try:
        all_clickables = page.query_selector_all('a, button')
    except:
        return []
    
    # Get viewport size for position calculations
    try:
        viewport = page.viewport_size
        viewport_width = viewport.get('width', 1280)
        viewport_height = viewport.get('height', 720)
    except:
        viewport_width = 1280
        viewport_height = 720

    for elem in all_clickables:
        try:
            if not elem.is_visible():
                continue

            score = 0
            elem_text = (elem.inner_text() or '').strip()
            elem_classes = (elem.get_attribute('class') or '').lower()
            elem_href = (elem.get_attribute('href') or '').lower()
            elem_title = (elem.get_attribute('title') or '').lower()
            
            # Get element position for matching
            try:
                box = elem.bounding_box()
                if box:
                    elem_x = box['x'] + box['width'] / 2  # Center X
                    elem_y = box['y'] + box['height'] / 2  # Center Y
                    # Normalize to 0-1 range
                    elem_x_norm = elem_x / viewport_width
                    elem_y_norm = elem_y / viewport_height
                else:
                    elem_x_norm = None
                    elem_y_norm = None
            except:
                elem_x_norm = None
                elem_y_norm = None

            # Exact text match = very high score
            if elem_text == element_text:
                score += 100
            # Case-insensitive exact match
            elif elem_text.lower() == element_text.lower():
                score += 95
            # Contains the text
            elif element_text.lower() in elem_text.lower():
                score += 60
            # Partial word match (check if key words match)
            element_words = set(word.lower() for word in element_text.split() if len(word) > 2)
            elem_words = set(word.lower() for word in elem_text.split() if len(word) > 2)
            if element_words and elem_words:
                overlap = len(element_words & elem_words) / len(element_words)
                if overlap > 0.5:  # More than 50% word overlap
                    score += 40
            # Check if "pdf" appears in both
            if 'pdf' in element_text.lower() and 'pdf' in elem_text.lower():
                score += 30
            # Check if "download" appears in both
            if 'download' in element_text.lower() and 'download' in elem_text.lower():
                score += 25

            # Check for PDF in href
            if 'pdf' in elem_href:
                score += 20
            
            # IMPORTANT: Filter out external domains (ads, unrelated links)
            if elem_href and page_domain_base:
                try:
                    from urllib.parse import urlparse
                    href_domain = urlparse(elem_href).netloc
                    href_domain_base = '.'.join(href_domain.split('.')[-2:]) if href_domain else ''
                    
                    # Penalize external domains heavily (unless it's a known academic domain)
                    if href_domain_base and href_domain_base != page_domain_base:
                        # Allow known academic domains
                        academic_domains = ['doi.org', 'arxiv.org', 'pubmed.ncbi.nlm.nih.gov', 'pmc.ncbi.nlm.nih.gov']
                        if not any(domain in href_domain_base for domain in academic_domains):
                            score -= 200  # Heavy penalty for external non-academic domains
                            continue  # Skip this element entirely
                        else:
                            score += 5  # Small bonus for academic domains
                    else:
                        # Same domain = bonus
                        score += 30
                except:
                    pass
            
            # Bonus for article-related paths in href
            if elem_href:
                if '/article/' in elem_href or '/doi/' in elem_href or '/pdf' in elem_href:
                    score += 25

            # Check distinctive features
            for feature in features:
                feature_lower = feature.lower()
                if feature_lower in elem_classes:
                    score += 15
                if feature_lower in elem_href:
                    score += 15
                if feature_lower in elem_title:
                    score += 10
                if 'pdf' in feature_lower and 'pdf' in elem_text.lower():
                    score += 10
            
            # POSITION-BASED MATCHING (high priority) - use vision's position description
            position_desc = vision_result.get('position', '').lower()
            if position_desc:
                try:
                    box = elem.bounding_box()
                    if box:
                        elem_x = box['x'] + box['width'] / 2  # Center X
                        elem_y = box['y'] + box['height'] / 2  # Center Y
                        # Normalize to 0-1 range
                        elem_x_norm = elem_x / viewport_width
                        elem_y_norm = elem_y / viewport_height
                        
                        position_score = 0
                        
                        # Top of page
                        if ('top' in position_desc or 'above' in position_desc) and elem_y_norm < 0.3:
                            position_score += 40
                        # Bottom of page
                        elif ('bottom' in position_desc or 'below' in position_desc) and elem_y_norm > 0.7:
                            position_score += 40
                        # Right side
                        elif ('right' in position_desc) and elem_x_norm > 0.7:
                            position_score += 40
                        # Left side
                        elif ('left' in position_desc) and elem_x_norm < 0.3:
                            position_score += 40
                        # Center
                        elif ('center' in position_desc or 'middle' in position_desc):
                            if 0.3 < elem_x_norm < 0.7 and 0.3 < elem_y_norm < 0.7:
                                position_score += 40
                        
                        # Toolbar/header area (top 20% of page)
                        if ('toolbar' in position_desc or 'header' in position_desc or 'below title' in position_desc) and elem_y_norm < 0.2:
                            position_score += 50
                        
                        # Near title (top 30% of page)
                        if ('below title' in position_desc or 'near title' in position_desc) and elem_y_norm < 0.3:
                            position_score += 45
                        
                        score += position_score
                        
                        # If position matches well, boost score significantly
                        if position_score > 30:
                            score += 30  # Bonus for good position match
                except:
                    pass

            # Only keep candidates with reasonable score (lowered threshold to catch more)
            if score > 10:  # Lowered from 20 to catch more elements
                candidates.append((score, elem))

        except Exception as e:
            continue

    return sorted(candidates, key=lambda x: x[0], reverse=True)


def dismiss_cookie_consent(page, timeout=5000):
    """
    Attempt to dismiss cookie consent dialogs that may obstruct download interactions.
    Tries multiple common patterns used by publishers (Wiley, Springer, Elsevier, etc.).
    """
    try:
        # List of common cookie consent button selectors (in priority order)
        dismiss_selectors = [
            # Wiley Advanced (as seen in screenshot)
            'button:has-text("Accept All")',
            'button:has-text("Reject Non-Essential")',

            # Generic patterns
            'button:has-text("Accept")',
            'button:has-text("Accept all")',
            'button:has-text("Accept All Cookies")',
            'button:has-text("Reject All")',
            'button:has-text("Reject")',
            'button:has-text("Close")',

            # Common CSS classes/IDs
            '#onetrust-accept-btn-handler',
            '.optanon-alert-box-close',
            'button[id*="accept"]',
            'button[class*="accept"]',
            'button[id*="cookie"]',
            'button[class*="cookie"]',
            '.cookie-consent-accept',
            '.cc-dismiss',
            '.cc-allow',

            # Springer Nature
            'button[data-cc-action="accept"]',
            'button.cc-banner__button--accept',

            # Elsevier
            'button#onetrust-accept-btn-handler',

            # Generic ARIA patterns
            'button[aria-label*="Accept"]',
            'button[aria-label*="Close"]',
        ]

        for selector in dismiss_selectors:
            try:
                # Check if element exists and is visible
                element = page.query_selector(selector)
                if element and element.is_visible():
                    thread_print(f"  [Cookie] Found consent button with selector: {selector[:50]}")
                    element.click(timeout=timeout)
                    page.wait_for_timeout(1000)  # Wait for dialog to dismiss
                    thread_print(f"  [Cookie] Successfully dismissed cookie consent")
                    return True
            except Exception as e:
                # Selector didn't match or click failed, try next
                continue

        # No cookie consent found or already dismissed
        return False

    except Exception as e:
        thread_print(f"  [Cookie] Error dismissing consent: {str(e)[:50]}")
        return False


def try_browser_download(url, output_path, timeout=30):
    """Intelligent exhaustive browser automation - scores and tries ALL promising download elements."""
    if not PLAYWRIGHT_AVAILABLE:
        return False, "Playwright not available"

    import shutil
    download_dir = tempfile.mkdtemp()

    def score_element(element):
        """Score an element's likelihood of being a PDF download link/button (0-100)."""
        score = 0
        try:
            # Get all relevant attributes
            tag = element.evaluate('el => el.tagName.toLowerCase()')
            text = (element.inner_text() or '').lower().strip()
            classes = (element.get_attribute('class') or '').lower()
            href = (element.get_attribute('href') or '').lower()
            title = (element.get_attribute('title') or '').lower()
            aria_label = (element.get_attribute('aria-label') or '').lower()
            role = (element.get_attribute('role') or '').lower()

            # Get all data-* attributes
            data_attrs = element.evaluate('''el => {
                return Array.from(el.attributes)
                    .filter(a => a.name.startsWith('data-'))
                    .map(a => a.name + '=' + a.value.toLowerCase())
                    .join(' ');
            }''')

            # Check visibility - invisible elements get 0
            if not element.is_visible():
                return 0

            # Combine all text for searching
            all_text = f"{text} {classes} {href} {title} {aria_label} {data_attrs} {role}"

            # === HIGH PRIORITY PATTERNS (45-70 points) ===

            # Perfect matches
            if text == 'pdf' and tag == 'a':
                score += 70
            elif text in ['download pdf', 'open pdf', 'view pdf']:
                score += 68
            elif text == 'download' and ('pdf' in href or 'pdf' in classes):
                score += 65

            # Publisher-specific high-value patterns
            elif 'article__btn__secondary--pdf' in classes:
                score += 65  # ACS Open PDF
            elif 'galley-link' in classes and 'pdf' in all_text:
                score += 65  # OJS/PKP
            elif 'ud_articlepdf' in classes:
                score += 65  # MDPI dropdown
            elif 'c-pdf-download' in classes:
                score += 60  # Nature/Springer

            # Strong URL patterns
            elif '/doi/pdf/' in href or '/doi/epdf/' in href:
                score += 60
            elif href.endswith('.pdf'):
                score += 58
            elif '/pdf/download' in href or 'download' in href and '.pdf' in href:
                score += 55

            # Strong text + context combinations
            elif 'download' in text and 'pdf' in text:
                score += 55
            elif ('pdf' in text or text == 'pdf') and tag in ['a', 'button']:
                score += 50
            elif 'articlepdf' in href or 'article-pdf' in href:
                score += 50

            # === MEDIUM PRIORITY PATTERNS (25-44 points) ===

            elif 'pdf' in text and len(text) < 15:  # Short PDF text
                score += 40
            elif '/pdf' in href and tag == 'a':
                score += 38
            elif 'download' in text and tag in ['a', 'button']:
                score += 35
            elif 'pdf' in classes and tag in ['a', 'button']:
                score += 33
            elif 'pdf' in title or 'pdf' in aria_label:
                score += 30
            elif 'download' in classes and 'pdf' in all_text:
                score += 28

            # === LOWER PRIORITY (10-24 points) ===

            elif 'pdf' in href:
                score += 24
            elif 'download' in all_text:
                score += 20
            elif 'view' in text and 'pdf' in all_text:
                score += 18
            elif tag == 'button' and 'download' in data_attrs:
                score += 15
            elif 'full text' in text or 'fulltext' in text:
                score += 12

            # === BONUS MODIFIERS (up to +20) ===

            # Dropdown indicators (need second click)
            if 'dropdown' in classes or 'drop-down' in classes:
                score += 8

            # Publisher-specific class bonuses
            if 'coolbar' in classes and 'pdf' in all_text:
                score += 10  # Wiley
            elif 'obj_galley' in classes:
                score += 10  # OJS

            # Icon indicators
            if 'icon' in classes and 'pdf' in all_text:
                score += 5

            # Button with download data attribute
            if 'data-download' in data_attrs or 'data-l10n-id="download"' in data_attrs:
                score += 10

            # Penalize vague or risky elements
            if len(text) > 50:  # Too much text, probably not a button
                score -= 10
            if 'abstract' in text or 'citation' in text:
                score -= 15
            if 'supplementary' in text or 'supporting' in text:
                score -= 5  # Might be supp materials, not main PDF

            return max(0, min(score, 100))  # Clamp to 0-100

        except Exception as e:
            return 0

    try:
        with sync_playwright() as p:
            # Use Firefox instead of Chromium for better PDF handling
            browser = p.firefox.launch(headless=True)

            import random
            user_agents = [
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
                'Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0',
            ]

            context = browser.new_context(
                user_agent=random.choice(user_agents),
                accept_downloads=True,
                extra_http_headers={
                    'Referer': 'https://www.google.com/',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                }
            )
            page = context.new_page()
            page.set_default_timeout(timeout * 1000)

            # Track all pages for new tab detection
            all_pages = [page]

            def handle_new_page(new_page):
                all_pages.append(new_page)

            context.on('page', handle_new_page)
            
            # Set up context-level download listener to catch downloads from any page
            downloads = []
            def handle_download(download):
                downloads.append(download)
            context.on('download', handle_download)

            def try_download_from_new_tab(new_page):
                """Handle new tab opened by vision-identified element - download PDFs from viewer or direct links."""
                try:
                    # Wait for navigation and any redirects to complete
                    new_page.wait_for_load_state('networkidle', timeout=30000)
                    new_page.wait_for_timeout(5000)  # Extra wait for redirects and PDF viewer to load
                    
                    current_url = new_page.url
                    thread_print(f"  [Vision] New tab URL (after redirects): {current_url[:150]}")

                    # Dismiss cookie consent in new tab before interacting with page
                    dismiss_cookie_consent(new_page)

                    # Check if this is a PDF viewer page (PDF displayed in browser)
                    is_pdf_viewer = False
                    try:
                        # Check if page title or content suggests PDF viewer
                        page_title = new_page.title().lower()
                        if 'pdf' in page_title or '.pdf' in current_url.lower():
                            # Check if there's an embedded PDF or PDF viewer
                            pdf_embed = new_page.query_selector('embed[type="application/pdf"], object[type="application/pdf"], iframe[src*=".pdf"]')
                            if pdf_embed:
                                is_pdf_viewer = True
                                thread_print(f"  [Vision] Detected PDF viewer page with embedded PDF")
                            # Also check if the page itself is serving PDF content
                            elif '.pdf' in current_url.lower():
                                # Try to detect if it's a viewer vs direct download
                                try:
                                    content_type = new_page.evaluate("document.contentType || ''")
                                    if 'pdf' in content_type.lower():
                                        is_pdf_viewer = True
                                        thread_print(f"  [Vision] Detected PDF viewer page (content-type: {content_type})")
                                except:
                                    # If .pdf in URL, assume it might be a viewer
                                    if 'viewer' in current_url.lower() or 'watermark' in current_url.lower():
                                        is_pdf_viewer = True
                                        thread_print(f"  [Vision] Detected PDF viewer page (based on URL)")
                    except:
                        pass
                    
                    # If it's a PDF viewer, look for download button
                    if is_pdf_viewer:
                        thread_print(f"  [Vision] Looking for download button in PDF viewer...")
                        # Common PDF viewer download button selectors
                        download_selectors = [
                            'button[title*="Download"]',
                            'button[aria-label*="Download"]',
                            'a[title*="Download"]',
                            'a[aria-label*="Download"]',
                            'button:has-text("Download")',
                            'a:has-text("Download")',
                            # Adobe Acrobat viewer
                            'button#download',
                            'button.download',
                            # Generic PDF.js viewer
                            'button[data-l10n-id="download"]',
                            # Chrome PDF viewer
                            'button[aria-label*="download" i]',
                        ]
                        
                        for selector in download_selectors:
                            try:
                                download_btn = new_page.query_selector(selector)
                                if download_btn and download_btn.is_visible():
                                    thread_print(f"  [Vision] Found download button: {selector}")
                                    # Set up download listener before clicking
                                    with new_page.expect_download(timeout=15000) as download_info:
                                        download_btn.click()
                                        new_page.wait_for_timeout(3000)
                                    
                                    download = download_info.value
                                    download_path = Path(download_dir) / download.suggested_filename
                                    download.save_as(download_path)
                                    
                                    if download_path.exists() and download_path.stat().st_size > 50000:
                                        thread_print(f"  [Vision] Download from PDF viewer! File: {download.suggested_filename} ({download_path.stat().st_size} bytes)")
                                        shutil.move(str(download_path), str(output_path))
                                        if is_valid_pdf(output_path):
                                            thread_print(f"  [Vision] ✓ Valid PDF downloaded from PDF viewer")
                                            return True, "Browser+Vision+PDFViewer"
                            except:
                                continue
                        
                        # If no download button found, try keyboard automation (Ctrl+S / Command+S)
                        thread_print(f"  [Vision] No download button found, trying keyboard automation (Ctrl+S)...")
                        try:
                            # Set up download listener before triggering save
                            download_happened = False
                            download_obj = None

                            def on_download(download):
                                nonlocal download_happened, download_obj
                                download_happened = True
                                download_obj = download
                                thread_print(f"  [Vision] Keyboard save triggered download: {download.suggested_filename}")

                            new_page.on("download", on_download)

                            # Detect OS for keyboard shortcut
                            import platform
                            is_mac = platform.system() == 'Darwin'

                            # Press Ctrl+S (or Command+S on Mac) to trigger save dialog
                            if is_mac:
                                new_page.keyboard.press('Meta+s')
                            else:
                                new_page.keyboard.press('Control+s')

                            # Wait for download to trigger
                            new_page.wait_for_timeout(5000)

                            if download_happened and download_obj:
                                thread_print(f"  [Vision] Download triggered via keyboard, saving...")
                                download_path = Path(download_dir) / download_obj.suggested_filename
                                download_obj.save_as(download_path)

                                if download_path.exists() and download_path.stat().st_size > 50000:
                                    thread_print(f"  [Vision] Keyboard save successful! File: {download_obj.suggested_filename} ({download_path.stat().st_size} bytes)")
                                    shutil.move(str(download_path), str(output_path))
                                    if is_valid_pdf(output_path):
                                        thread_print(f"  [Vision] ✓ Valid PDF saved via keyboard automation")
                                        return True, "Browser+Vision+Keyboard"
                        except Exception as e:
                            thread_print(f"  [Vision] Keyboard automation failed: {str(e)[:80]}")

                        # If keyboard automation didn't work, try to extract PDF URL from viewer
                        thread_print(f"  [Vision] Keyboard automation failed, trying to extract PDF URL...")
                        try:
                            # Try to get PDF URL from embed/iframe
                            pdf_url = new_page.evaluate("""
                                () => {
                                    const embed = document.querySelector('embed[type="application/pdf"]');
                                    if (embed) return embed.src;
                                    const iframe = document.querySelector('iframe[src*=".pdf"]');
                                    if (iframe) return iframe.src;
                                    // If page itself is PDF, return current URL
                                    if (window.location.href.includes('.pdf')) return window.location.href;
                                    return null;
                                }
                            """)
                            if pdf_url:
                                thread_print(f"  [Vision] Extracted PDF URL from viewer: {pdf_url[:150]}")
                                success, _ = direct_download(pdf_url, output_path, use_stealth=True)
                                if success:
                                    return True, "Browser+Vision+PDFViewerURL"
                        except:
                            pass

                    # Skip if chrome error page
                    if 'chrome-error' in current_url.lower():
                        thread_print(f"  [Vision] New tab shows error page, waiting for redirect...")
                        new_page.wait_for_timeout(5000)
                        new_page.wait_for_load_state('networkidle', timeout=30000)
                        current_url = new_page.url
                        thread_print(f"  [Vision] URL after waiting: {current_url[:150]}")
                    
                    # If this is a direct PDF URL, try downloading using browser context (has cookies/session)
                    if '.pdf' in current_url.lower() or '/article-pdf/' in current_url.lower():
                        thread_print(f"  [Vision] New tab is direct PDF URL, waiting for redirects...")
                        # Wait for any redirects to complete
                        try:
                            new_page.wait_for_load_state('networkidle', timeout=30000)
                        except:
                            pass

                        # Actively wait for URL to change (indicating redirect)
                        initial_url = current_url
                        redirect_detected = False
                        for i in range(15):
                            new_page.wait_for_timeout(1000)
                            current_url = new_page.url
                            if current_url != initial_url:
                                thread_print(f"  [Vision] Redirect detected after {i+1}s: {current_url[:150]}")
                                redirect_detected = True
                                # Wait a bit more for page to stabilize
                                new_page.wait_for_timeout(3000)
                                current_url = new_page.url  # Update again
                                break

                        if not redirect_detected:
                            thread_print(f"  [Vision] No redirect detected after 15s")
                            new_page.wait_for_timeout(3000)
                            current_url = new_page.url

                        thread_print(f"  [Vision] Final URL after redirects: {current_url[:150]}")
                        
                        # If URL still has .pdf, it might be a PDF viewer - check for download button first
                        if '.pdf' in current_url.lower():
                            # Check if it's a PDF viewer page
                            is_pdf_viewer = False
                            try:
                                # Check page content
                                page_content = new_page.content()
                                if 'pdf' in page_content.lower()[:1000]:  # Check first 1000 chars
                                    is_pdf_viewer = True
                            except:
                                pass
                            
                            if is_pdf_viewer:
                                thread_print(f"  [Vision] Detected PDF viewer, looking for download button...")
                                # Try download button selectors
                                download_selectors = [
                                    'button[title*="Download" i]',
                                    'button[aria-label*="Download" i]',
                                    'a[title*="Download" i]',
                                    'button#download',
                                    'button.download',
                                ]
                                for selector in download_selectors:
                                    try:
                                        btn = new_page.query_selector(selector)
                                        if btn and btn.is_visible():
                                            with new_page.expect_download(timeout=15000) as dl_info:
                                                btn.click()
                                                new_page.wait_for_timeout(3000)
                                            dl = dl_info.value
                                            dl_path = Path(download_dir) / dl.suggested_filename
                                            dl.save_as(dl_path)
                                            if dl_path.exists() and dl_path.stat().st_size > 50000:
                                                shutil.move(str(dl_path), str(output_path))
                                                if is_valid_pdf(output_path):
                                                    return True, "Browser+Vision+PDFViewerBtn"
                                    except:
                                        continue
                        
                        # Try downloading using browser context
                        thread_print(f"  [Vision] Trying download via browser context...")
                        
                        # Try to fetch PDF using JavaScript in page context (has cookies)
                        try:
                            content_base64 = new_page.evaluate(f"""
                                async () => {{
                                    const response = await fetch('{current_url}');
                                    const blob = await response.blob();
                                    return new Promise((resolve) => {{
                                        const reader = new FileReader();
                                        reader.onloadend = () => resolve(reader.result.split(',')[1]);
                                        reader.readAsDataURL(blob);
                                    }});
                                }}
                            """)
                            
                            if content_base64:
                                import base64
                                content = base64.b64decode(content_base64)
                                if len(content) > 50000:
                                    output_path.write_bytes(content)
                                    if is_valid_pdf(output_path):
                                        thread_print(f"  [Vision] ✓ PDF downloaded via browser context ({len(content)} bytes)")
                                        return True, "Browser+Vision+BrowserContext"
                                    else:
                                        thread_print(f"  [Vision] ✗ Downloaded content is not a valid PDF")
                                else:
                                    thread_print(f"  [Vision] ✗ Downloaded content too small ({len(content)} bytes)")
                        except Exception as e:
                            thread_print(f"  [Vision] Browser context download failed: {str(e)[:80]}")
                        
                        # Fallback: try direct download
                        thread_print(f"  [Vision] Trying direct download from new tab URL...")
                        success, _ = direct_download(current_url, output_path, use_stealth=True)
                        if success:
                            return True, "Browser+Vision+DirectPDF"
                    
                    # Check if page contains PDF viewer or PDF link
                    try:
                        # Look for PDF download links in the new page
                        pdf_links = new_page.query_selector_all('a[href*=".pdf"], a[href*="/pdf"], a[href*="/article-pdf/"]')
                        for link in pdf_links[:3]:  # Try first 3 PDF links
                            try:
                                link_href = link.get_attribute('href') or ''
                                if link_href:
                                    # Make absolute
                                    if link_href.startswith('/'):
                                        from urllib.parse import urljoin
                                        link_href = urljoin(current_url, link_href)
                                    elif not link_href.startswith('http'):
                                        from urllib.parse import urljoin
                                        link_href = urljoin(current_url, link_href)
                                    
                                    if '.pdf' in link_href.lower() or '/article-pdf/' in link_href.lower():
                                        thread_print(f"  [Vision] Found PDF link in new tab: {link_href[:150]}")
                                        success, _ = direct_download(link_href, output_path, use_stealth=True)
                                        if success:
                                            return True, "Browser+Vision+PDFLink"
                            except:
                                continue
                    except:
                        pass
                    
                    # Try downloading the current page URL anyway (might be a PDF served without .pdf extension)
                    if '/pdf' in current_url.lower() or '/article-pdf/' in current_url.lower():
                        thread_print(f"  [Vision] Trying to download new tab URL as PDF...")
                        success, _ = direct_download(current_url, output_path, use_stealth=True)
                        if success:
                            return True, "Browser+Vision+NewTabURL"
                    
                    return None

                except Exception as e:
                    thread_print(f"  [Vision] Error handling new tab: {str(e)[:50]}")
                    return None

            try:
                # Navigate to the article page - handle download events that may occur
                try:
                    # Set up download listener to capture PDF downloads
                    downloads_captured = []
                    
                    def handle_download(download):
                        downloads_captured.append(download)
                        thread_print(f"  [Download] Captured download: {download.suggested_filename}")
                    
                    page.on('download', handle_download)
                    page.on('popup', lambda popup: popup.close() if popup else None)
                    
                    # Try to navigate
                    try:
                        page.goto(url, wait_until='domcontentloaded', timeout=timeout * 1000)
                    except Exception as nav_error:
                        # If navigation fails due to download, that's expected
                        if 'download' in str(nav_error).lower():
                            thread_print(f"  [Download] Page triggered auto-download during navigation")
                        else:
                            raise
                    
                    # Wait for download to complete
                    page.wait_for_timeout(5000)

                    # Dismiss any cookie consent dialogs that may obstruct interactions
                    dismiss_cookie_consent(page)

                    # If download was captured, save it
                    if downloads_captured:
                        download = downloads_captured[0]
                        try:
                            # Use a temp directory specific to this browser session
                            temp_dl_dir = Path(download_dir)
                            temp_dl_dir.mkdir(parents=True, exist_ok=True)
                            download_path = temp_dl_dir / download.suggested_filename
                            download.save_as(str(download_path))
                            page.wait_for_timeout(2000)  # Wait for file to be fully written
                            
                            if download_path.exists():
                                file_size = download_path.stat().st_size
                                thread_print(f"  [Download] Downloaded file size: {file_size} bytes")
                                if file_size > 50000 and is_valid_pdf(download_path):
                                    thread_print(f"  [Download] ✓ Auto-downloaded PDF: {download.suggested_filename}")
                                    shutil.move(str(download_path), str(output_path))
                                    return True, "Browser+AutoDownload"
                                else:
                                    thread_print(f"  [Download] File invalid or too small ({file_size} bytes), not a PDF")
                                    download_path.unlink()
                            else:
                                thread_print(f"  [Download] Downloaded file not found at {download_path}")
                        except Exception as e:
                            thread_print(f"  [Download] Error saving auto-download: {str(e)[:80]}")
                            if download_path.exists():
                                try:
                                    download_path.unlink()
                                except:
                                    pass
                
                except Exception as e:
                    thread_print(f"  [Vision] Page load error: {str(e)[:80]}")
                    page.wait_for_timeout(2000)

                # STRATEGY 1: Use vision analysis to identify PDF download element
                # Save screenshot to output directory for inspection
                output_dir = output_path.parent
                item_num = output_path.stem.split('_')[0].replace('item', '')
                
                def try_vision_analysis(screenshot_path, region="top"):
                    """Try vision analysis on a screenshot and attempt download if found."""
                    thread_print(f"  [Vision] Calling Claude API for {region} screenshot...")
                    vision_result = analyze_screenshot_with_claude(screenshot_path, url)
                    
                    if vision_result:
                        thread_print(f"  [Vision] Found: '{vision_result.get('element_text', 'N/A')}' ({vision_result.get('confidence', 'N/A')} confidence)")
                        
                        # Find matching elements based on vision analysis
                        vision_candidates = find_elements_by_vision_description(page, vision_result)
                        
                        if not vision_candidates:
                            thread_print(f"  [Vision] No matching DOM elements found for vision result")
                            return False
                        
                        thread_print(f"  [Vision] Found {len(vision_candidates)} matching DOM elements:")
                        for idx, (score, elem) in enumerate(vision_candidates[:5], 1):
                            try:
                                elem_text = (elem.inner_text() or '').strip()[:50]
                                elem_href = (elem.get_attribute('href') or '')[:100]
                                elem_class = (elem.get_attribute('class') or '')[:50]
                                elem_tag = elem.evaluate('el => el.tagName.toLowerCase()')
                                thread_print(f"    [{idx}] Score: {score} | Tag: {elem_tag} | Text: '{elem_text}' | Href: '{elem_href}' | Class: '{elem_class}'")
                            except:
                                thread_print(f"    [{idx}] Score: {score} | (could not get element details)")
                        
                        # Try clicking vision-identified elements first
                        for idx, (score, elem) in enumerate(vision_candidates[:5], 1):  # Try top 5 matches
                            try:
                                elem_text = (elem.inner_text() or '').strip()
                                href = elem.get_attribute('href') or ''
                                elem_class = (elem.get_attribute('class') or '')
                                elem_tag = elem.evaluate('el => el.tagName.toLowerCase()')
                                thread_print(f"  [Vision] Processing element #{idx} (score: {score}): {elem_tag} with text '{elem_text[:50]}' and href '{href[:100]}'")
                                
                                # FIRST: Try fast download methods on the href BEFORE clicking
                                if href:
                                    # Make absolute URL
                                    if href.startswith('/'):
                                        from urllib.parse import urljoin
                                        href_absolute = urljoin(page.url, href)
                                    elif not href.startswith('http'):
                                        from urllib.parse import urljoin
                                        href_absolute = urljoin(page.url, href)
                                    else:
                                        href_absolute = href
                                    
                                    # Check if it's a PDF link
                                    if '.pdf' in href_absolute.lower() or '/pdf' in href_absolute.lower() or '/article-pdf/' in href_absolute.lower():
                                        thread_print(f"  [Vision] Element #{idx} has PDF href, trying fast download methods first...")
                                        
                                        # Try 1: Direct download with stealth
                                        success, msg = direct_download(href_absolute, output_path, use_stealth=True)
                                        if success:
                                            thread_print(f"  [Vision] ✓ Direct download (stealth) successful from element #{idx} href")
                                            return True
                                        
                                        # Try 2: Direct download without stealth
                                        success, msg = direct_download(href_absolute, output_path, use_stealth=False)
                                        if success:
                                            thread_print(f"  [Vision] ✓ Direct download successful from element #{idx} href")
                                            return True
                                        
                                        # Try 3: Extract DOI and try other methods
                                        doi = extract_doi_from_url(href_absolute) or extract_doi_from_url(page.url)
                                        if doi:
                                            thread_print(f"  [Vision] Trying fast methods with DOI: {doi}")
                                            # Try OpenAlex
                                            success, _ = try_openalex(doi, None, output_path)
                                            if success:
                                                thread_print(f"  [Vision] ✓ OpenAlex download successful")
                                                return True
                                            # Try CORE
                                            success, _ = try_core_api(href_absolute, output_path, doi)
                                            if success:
                                                thread_print(f"  [Vision] ✓ CORE download successful")
                                                return True
                                            # Try Semantic Scholar
                                            success, _ = try_semantic_scholar(doi, None, output_path)
                                            if success:
                                                thread_print(f"  [Vision] ✓ Semantic Scholar download successful")
                                                return True
                                        
                                        thread_print(f"  [Vision] Fast methods failed for element #{idx} href, will try clicking...")
                                
                                # SECOND: Navigate directly to href URL instead of clicking
                                if href:
                                    # Make absolute URL
                                    if href.startswith('/'):
                                        from urllib.parse import urljoin
                                        href_absolute = urljoin(page.url, href)
                                    elif not href.startswith('http'):
                                        from urllib.parse import urljoin
                                        href_absolute = urljoin(page.url, href)
                                    else:
                                        href_absolute = href
                                    
                                    # Check if it's a PDF link
                                    if '.pdf' in href_absolute.lower() or '/pdf' in href_absolute.lower() or '/article-pdf/' in href_absolute.lower():
                                        thread_print(f"  [Vision] Element #{idx} has PDF href, navigating directly: {href_absolute[:150]}")

                                        # Navigate directly to the PDF URL in a new page
                                        new_page = None
                                        try:
                                            new_page = context.new_page()
                                            thread_print(f"  [Vision] Created new page, navigating to PDF URL...")

                                            # Track if download happens
                                            download_happened = False
                                            download_obj = None

                                            def on_download(download):
                                                nonlocal download_happened, download_obj
                                                download_happened = True
                                                download_obj = download
                                                thread_print(f"  [Vision] Download detected: {download.suggested_filename}")

                                            new_page.on("download", on_download)

                                            # Navigate and wait for page to load (but don't block on download)
                                            new_page.goto(href_absolute, wait_until='networkidle', timeout=60000)

                                            # Wait for redirects - actively monitor URL changes
                                            initial_url = new_page.url
                                            thread_print(f"  [Vision] Initial URL after navigation: {initial_url[:150]}")

                                            # Wait up to 15 seconds for URL to change (indicating redirect)
                                            redirect_detected = False
                                            for i in range(15):
                                                new_page.wait_for_timeout(1000)
                                                current_url = new_page.url
                                                if current_url != initial_url:
                                                    thread_print(f"  [Vision] Redirect detected after {i+1}s: {current_url[:150]}")
                                                    redirect_detected = True
                                                    # Wait a bit more for page to stabilize after redirect
                                                    new_page.wait_for_timeout(3000)
                                                    break

                                            if not redirect_detected:
                                                thread_print(f"  [Vision] No redirect detected after 15s, URL unchanged")

                                            # Dismiss any cookie consent on new page
                                            dismiss_cookie_consent(new_page)
                                            # Still wait a bit in case redirect is slow
                                            new_page.wait_for_timeout(3000)

                                            # Check if download was triggered
                                            if download_happened and download_obj:
                                                thread_print(f"  [Vision] Download triggered, saving...")
                                                download_path = Path(download_dir) / download_obj.suggested_filename
                                                download_obj.save_as(download_path)

                                                if download_path.exists() and download_path.stat().st_size > 50000:
                                                    thread_print(f"  [Vision] Download successful! File: {download_obj.suggested_filename} ({download_path.stat().st_size} bytes)")
                                                    shutil.move(str(download_path), str(output_path))
                                                    if is_valid_pdf(output_path):
                                                        thread_print(f"  [Vision] ✓ Valid PDF downloaded via direct navigation")
                                                        new_page.close()
                                                        return True

                                            # No download triggered - check if it's a PDF viewer page
                                            current_url = new_page.url
                                            thread_print(f"  [Vision] No download triggered. Final URL: {current_url[:150]}")

                                            # Skip if navigation failed
                                            if 'chrome-error' in current_url.lower() or 'about:blank' in current_url.lower():
                                                thread_print(f"  [Vision] Navigation failed (error page)")
                                                new_page.close()
                                                continue

                                            # If URL still has .pdf, likely a PDF viewer - try keyboard automation first
                                            if '.pdf' in current_url.lower():
                                                thread_print(f"  [Vision] PDF viewer detected, trying keyboard save (Ctrl+S)...")
                                                try:
                                                    import platform
                                                    is_mac = platform.system() == 'Darwin'

                                                    # Press Ctrl+S (or Command+S on Mac) to trigger save
                                                    if is_mac:
                                                        new_page.keyboard.press('Meta+s')
                                                    else:
                                                        new_page.keyboard.press('Control+s')

                                                    # Wait for download to trigger
                                                    new_page.wait_for_timeout(5000)

                                                    if download_happened and download_obj:
                                                        thread_print(f"  [Vision] Keyboard save triggered download: {download_obj.suggested_filename}")
                                                        download_path = Path(download_dir) / download_obj.suggested_filename
                                                        download_obj.save_as(download_path)

                                                        if download_path.exists() and download_path.stat().st_size > 50000:
                                                            thread_print(f"  [Vision] Keyboard save successful! File: {download_obj.suggested_filename} ({download_path.stat().st_size} bytes)")
                                                            shutil.move(str(download_path), str(output_path))
                                                            if is_valid_pdf(output_path):
                                                                thread_print(f"  [Vision] ✓ Valid PDF saved via keyboard automation")
                                                                new_page.close()
                                                                return True
                                                except Exception as e:
                                                    thread_print(f"  [Vision] Keyboard automation failed: {str(e)[:80]}")

                                            # Try PDF viewer detection and download (includes more keyboard attempts)
                                            thread_print(f"  [Vision] Checking if page is PDF viewer...")
                                            result = try_download_from_new_tab(new_page)
                                            if result:
                                                new_page.close()
                                                return True

                                            # Last resort: direct download from final URL
                                            if '.pdf' in current_url.lower():
                                                thread_print(f"  [Vision] Final URL is PDF, trying direct download: {current_url[:150]}")
                                                success, _ = direct_download(current_url, output_path, use_stealth=True)
                                                if success:
                                                    thread_print(f"  [Vision] ✓ Direct download from final URL successful")
                                                    new_page.close()
                                                    return True

                                            new_page.close()
                                        except Exception as e:
                                            thread_print(f"  [Vision] PDF navigation failed: {str(e)[:80]}")
                                            if new_page:
                                                try:
                                                    new_page.close()
                                                except:
                                                    pass
                            
                            except Exception as e:
                                continue
                        
                        thread_print(f"  [Vision] Vision-identified elements failed - no download found")
                        return False
                    else:
                        return False
                
                try:
                    # Check if screenshots already exist
                    vision_top_path = output_dir / f"item{item_num}_vision_top.png"
                    vision_bottom_path = output_dir / f"item{item_num}_vision_bottom.png"

                    # Ensure cookie consent is dismissed before taking screenshots
                    # (Second attempt in case it appeared after initial page load)
                    dismiss_cookie_consent(page)

                    # Try 1: Top of page (viewport-sized screenshot)
                    if not vision_top_path.exists():
                        screenshot_name = f"item{item_num}_vision_top.png"
                        screenshot_path = output_dir / screenshot_name
                        page.screenshot(path=str(screenshot_path), full_page=False)
                        thread_print(f"  [Vision] Top screenshot saved: {screenshot_name}")
                        thread_print(f"  [Vision] Analyzing top of page...")
                        
                        if try_vision_analysis(screenshot_path, "top"):
                            return True, "Browser+Vision(top)"
                    else:
                        thread_print(f"  [Vision] Using existing top screenshot")
                        if try_vision_analysis(vision_top_path, "top"):
                            return True, "Browser+Vision(top-cached)"
                    
                    # Try 2: Bottom of page (scroll down and take screenshot)
                    if not vision_bottom_path.exists():
                        thread_print(f"  [Vision] Top analysis failed, trying bottom of page...")
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(2000)
                        
                        screenshot_name = f"item{item_num}_vision_bottom.png"
                        screenshot_path = output_dir / screenshot_name
                        page.screenshot(path=str(screenshot_path), full_page=False)
                        thread_print(f"  [Vision] Bottom screenshot saved: {screenshot_name}")
                        thread_print(f"  [Vision] Analyzing bottom of page...")
                        
                        if try_vision_analysis(screenshot_path, "bottom"):
                            return True, "Browser+Vision(bottom)"
                    else:
                        thread_print(f"  [Vision] Using existing bottom screenshot")
                        if try_vision_analysis(vision_bottom_path, "bottom"):
                            return True, "Browser+Vision(bottom-cached)"
                    
                    thread_print(f"  [Vision] No PDF element identified by vision analysis (tried top and bottom)")

                except Exception as e:
                    thread_print(f"  [Vision] Vision analysis failed: {str(e)[:40]}")

                # No fallback - vision-only approach
                return False, "Vision system could not identify PDF download element"

            finally:
                browser.close()

    except Exception as e:
        return False, f"Browser: {str(e)[:40]}"
    finally:
        shutil.rmtree(download_dir, ignore_errors=True)






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


def process_item_fast(index, url, output_dir, checklist_path):
    """Process item with fast methods only (no browser, no agent)."""
    doi = extract_doi_from_url(url)
    
    # Check for duplicate
    if check_duplicate(doi, index, output_dir):
        update_checklist(checklist_path, index, checked=True)
        return (index, True, "duplicate", url, doi)
    
    filename = get_filename(url, index)
    output_path = output_dir / filename
    
    # Skip if already exists
    if output_path.exists() and is_valid_pdf(output_path):
        update_checklist(checklist_path, index, checked=True)
        register_doi(doi, index)
        return (index, True, "exists", url, doi)
    
    thread_print(f"[{index}] {url[:70]}...")
    
    # 1. Try direct download for PDF URLs
    if url.lower().endswith('.pdf') or '/pdf' in url.lower():
        success, msg = direct_download(url, output_path)
        if success:
            thread_print(f"[{index}] ✓ Direct")
            update_checklist(checklist_path, index, checked=True)
            register_doi(doi, index)
            return (index, True, "direct", url, doi)
    
    # 2. Try open access sources (arXiv, MDPI, Frontiers, etc.)
    success, source = try_open_access(url, output_path, doi)
    if success:
        thread_print(f"[{index}] ✓ {source}")
        update_checklist(checklist_path, index, checked=True)
        register_doi(doi, index)
        return (index, True, source, url, doi)
    
    # Get paper metadata for additional methods
    title, authors = get_paper_metadata(doi) if doi else (None, None)

    # 3. Try OpenAlex API (fast, high coverage)
    success, source = try_openalex(doi, title, output_path)
    if success:
        thread_print(f"[{index}] ✓ OpenAlex")
        update_checklist(checklist_path, index, checked=True)
        register_doi(doi, index)
        return (index, True, "OpenAlex", url, doi)

    # 4. Try CORE API
    success, source = try_core_api(url, output_path, doi)
    if success:
        thread_print(f"[{index}] ✓ CORE")
        update_checklist(checklist_path, index, checked=True)
        register_doi(doi, index)
        return (index, True, "CORE", url, doi)

    # 5. Try Semantic Scholar
    success, source = try_semantic_scholar(doi, title, output_path)
    if success:
        thread_print(f"[{index}] ✓ Semantic Scholar")
        update_checklist(checklist_path, index, checked=True)
        register_doi(doi, index)
        return (index, True, "Semantic Scholar", url, doi)

    # 6. Try BASE API (300M+ records)
    success, source = try_base_api(doi, title, output_path)
    if success:
        thread_print(f"[{index}] ✓ BASE")
        update_checklist(checklist_path, index, checked=True)
        register_doi(doi, index)
        return (index, True, "BASE", url, doi)

    # 7. Try OpenAIRE (EU-funded content)
    success, source = try_openaire(doi, title, output_path)
    if success:
        thread_print(f"[{index}] ✓ OpenAIRE")
        update_checklist(checklist_path, index, checked=True)
        register_doi(doi, index)
        return (index, True, "OpenAIRE", url, doi)

    # 8. Try DOAJ
    success, source = try_doaj(doi, title, output_path)
    if success:
        thread_print(f"[{index}] ✓ DOAJ")
        update_checklist(checklist_path, index, checked=True)
        register_doi(doi, index)
        return (index, True, "DOAJ", url, doi)

    # 9. Try ResearchGate
    if title:
        success, source = try_researchgate(doi, title, authors, output_path)
        if success:
            thread_print(f"[{index}] ✓ ResearchGate")
            update_checklist(checklist_path, index, checked=True)
            register_doi(doi, index)
            return (index, True, "ResearchGate", url, doi)

    # 10. Try 12ft.io bypass (for soft paywalls)
    success, source = try_12ft(url, output_path)
    if success:
        thread_print(f"[{index}] ✓ 12ft.io")
        update_checklist(checklist_path, index, checked=True)
        register_doi(doi, index)
        return (index, True, "12ft.io", url, doi)

    # 11. Try Sci-Hub before browser
    if doi:
        success, msg = try_scihub(doi, output_path)
        if success:
            thread_print(f"[{index}] ✓ Sci-Hub")
            update_checklist(checklist_path, index, checked=True)
            register_doi(doi, index)
            return (index, True, "scihub", url, doi)

    # 12. Try Google Scholar with browser (slower, so later in sequence)
    if title and PLAYWRIGHT_AVAILABLE:
        success, source = try_google_scholar(title, authors, output_path, doi)
        if success:
            thread_print(f"[{index}] ✓ Google Scholar")
            update_checklist(checklist_path, index, checked=True)
            register_doi(doi, index)
            return (index, True, "Google Scholar", url, doi)
    
    thread_print(f"[{index}] - fast failed")
    return (index, False, "needs_browser", url, doi)


def has_screenshots(index, output_dir):
    """Check if item already has screenshots."""
    item_num = f"{index:03d}"
    vision_top = output_dir / f"item{item_num}_vision_top.png"
    vision_bottom = output_dir / f"item{item_num}_vision_bottom.png"
    return vision_top.exists() and vision_bottom.exists()


def process_item_browser(index, url, doi, output_dir, checklist_path):
    """Process item with browser automation."""
    # Skip if screenshots already exist and we're in screenshots-only mode
    if screenshots_only and has_screenshots(index, output_dir):
        thread_print(f"[{index}] Skipping (screenshots exist)")
        return (index, None, "skipped_screenshots_exist", url, doi)
    
    filename = get_filename(url, index)
    output_path = output_dir / filename
    
    thread_print(f"[{index}] Browser: {url[:50]}...")
    success, msg = try_browser_download(url, output_path)
    if success:
        thread_print(f"[{index}] ✓ Browser")
        update_checklist(checklist_path, index, checked=True)
        register_doi(doi, index)
        return (index, True, "browser")
    
    thread_print(f"[{index}] ✗ {msg}")
    return (index, False, msg)


def main():
    print("=" * 60, flush=True)
    print("PAPER DOWNLOAD SCRIPT", flush=True)
    print("=" * 60, flush=True)
    
    parser = argparse.ArgumentParser(description='Download papers from sourcing checklist')
    parser.add_argument('checklist', help='Path to sourcing_checklist.md')
    parser.add_argument('--start', type=int, default=1, help='Start from item N')
    parser.add_argument('--end', type=int, default=None, help='End at item M')
    parser.add_argument('--workers', type=int, default=5, help='Parallel workers (default: 5)')
    parser.add_argument('--delay', type=float, default=0.5, help='Delay between workers (default: 0.5)')
    parser.add_argument('--skip-browser', action='store_true', help='Skip browser automation')
    parser.add_argument('--browser-workers', type=int, default=2, help='Browser workers (default: 2)')
    parser.add_argument('--screenshots-only', action='store_true', help='Create screenshots only, no vision analysis')
    
    args = parser.parse_args()
    
    # Set global screenshots_only flag
    global screenshots_only
    screenshots_only = args.screenshots_only
    
    checklist_path = Path(args.checklist).resolve()
    
    if not checklist_path.exists():
        print(f"Error: Checklist not found: {checklist_path}", flush=True)
        sys.exit(1)
    
    output_dir = checklist_path.parent
    items = parse_checklist(checklist_path)
    
    if not items:
        print("Error: No items found in checklist", flush=True)
        sys.exit(1)
    
    print(f"Checklist: {checklist_path.name} ({len(items)} items)", flush=True)
    print(f"Output: {output_dir}", flush=True)
    
    # Initialize downloaded DOIs from existing files
    init_downloaded_dois(output_dir)
    
    # Filter items by range
    end_idx = args.end if args.end else len(items)
    to_process = [(idx, url) for idx, checked, url in items
                  if not checked and args.start <= idx <= end_idx]
    
    if not to_process:
        print("No unchecked items to process", flush=True)
        sys.exit(0)
    
    # ========== PHASE 1: Fast methods (parallel) ==========
    print(f"\n{'='*50}", flush=True)
    print(f"PHASE 1: Fast methods ({len(to_process)} items, {args.workers} workers)", flush=True)
    print("="*50, flush=True)
    
    fast_results = []
    needs_browser = []
    
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process_item_fast, idx, url, output_dir, checklist_path): idx 
                   for idx, url in to_process}
        
        for f in as_completed(futures):
            try:
                result = f.result()
                fast_results.append(result)
                if not result[1]:  # Failed
                    needs_browser.append((result[0], result[3], result[4]))  # idx, url, doi
            except Exception as e:
                thread_print(f"[{futures[f]}] Error: {e}")
            time.sleep(args.delay)
    
    fast_success = sum(1 for r in fast_results if r[1])
    print(f"\nPhase 1: {fast_success} downloaded, {len(needs_browser)} need browser", flush=True)
    
    # ========== PHASE 2: Browser automation ==========
    browser_success = 0
    if needs_browser and not args.skip_browser and PLAYWRIGHT_AVAILABLE:
        print(f"\n{'='*50}", flush=True)
        print(f"PHASE 2: Browser ({len(needs_browser)} items, {args.browser_workers} workers)", flush=True)
        print("="*50, flush=True)
        
        browser_results = []
        with ThreadPoolExecutor(max_workers=args.browser_workers) as ex:
            futures = {ex.submit(process_item_browser, idx, url, doi, output_dir, checklist_path): idx
                       for idx, url, doi in needs_browser}
            
            for f in as_completed(futures):
                try:
                    result = f.result()
                    browser_results.append(result)
                except Exception as e:
                    thread_print(f"Error: {e}")
                time.sleep(1)  # Rate limit browser requests
        
        browser_success = sum(1 for r in browser_results if r[1])
        print(f"\nPhase 2: {browser_success} downloaded", flush=True)
        
        total_failed = [r[0] for r in browser_results if not r[1]]
    else:
        total_failed = [r[0] for r in fast_results if not r[1]]
        if args.skip_browser and needs_browser:
            print(f"\nSkipped {len(needs_browser)} items (--skip-browser)", flush=True)
        elif not PLAYWRIGHT_AVAILABLE and needs_browser:
            print(f"\nSkipped {len(needs_browser)} items (playwright not installed)", flush=True)
    
    # Summary
    total_success = fast_success + browser_success
    print(f"\n{'='*50}", flush=True)
    print(f"DONE: {total_success} downloaded, {len(total_failed)} failed", flush=True)
    if total_failed:
        print(f"Failed: {sorted(total_failed)}", flush=True)


if __name__ == "__main__":
    main()
