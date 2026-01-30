# PDF Filename DOI Fixer

## Overview

Script that automatically extracts DOIs from PDF files and renames them to a standardized format.

**Location:** `/Users/para/Desktop/thesis/docs/perplexity/fix_doi_filenames.py`

## Purpose

Fixes PDF filenames in the thesis research collection by:
1. Finding PDFs with incomplete filenames (missing proper DOI format)
2. Extracting DOI from PDF metadata or text content
3. Renaming files from `itemXXX_SUFFIX.pdf` to `itemXXX_DOI.pdf`
4. Keeping PDFs where DOI cannot be extracted unchanged

## Target Format

- **Original:** `item001_432158.pdf`
- **Fixed:** `item001_10.55815_432158.pdf`

DOIs are stored with underscores instead of slashes for filename safety: `10.XXXX_...` instead of `10.XXXX/...`

## Scope Coverage

Processes all three research scopes:
1. `scope001 full research on automation efforts in the chemist/`
2. `scope002 Robotic Chemists_ A Comprehensive Research Survey/`
3. `scope003 most recent reviews on Control Barrier Functions/`

## How It Works

### Extraction Methods (in order of preference):

1. **Metadata Extraction** - Uses `pdfinfo` to extract DOI from PDF metadata (fast)
2. **Text Extraction** - Uses `pdftotext` to extract text and search for DOI patterns

### DOI Pattern Matching

Matches standard DOI formats:
- Standard: `10.XXXX/...` (with forward slashes)
- Alternative: `10.XXXX_...` (with underscores, common in filenames)

### Normalization

- Converts slashes to underscores for filename safety
- Removes trailing invalid characters (commas, periods, semicolons)
- Handles parentheses and other problematic characters

## Usage

### Prerequisites

```bash
# Ensure pdfinfo and pdftotext are installed (macOS)
brew install poppler  # Includes pdftotext and pdfinfo
```

### Running the Script

```bash
cd /Users/para/Desktop/thesis/docs/perplexity
python3 fix_doi_filenames.py
```

### Output

The script prints a detailed report showing:
- Files processed
- Successful renames (✓)
- Files that couldn't be fixed (⚠️)
- Summary statistics

Example:
```
Processing: scope001 full research on automation efforts in the chemist
Found 178 PDF files to process

  Processing: item001_2601.13232.pdf
    ✓  Renamed to: item001_10.5281_zenodo.pdf

  Processing: item021_fa1149943d592ec80bf20c3003016b643127d1c7.pdf
    ⚠️  Could not extract DOI, keeping as-is
```

## Results Summary

As of last run:

| Scope | Total Files | With DOI Format | Without Format |
|-------|------------|-----------------|----------------|
| scope001 | 178 | 147 | 31 |
| scope002 | 29 | 24 | 5 |
| scope003 | 53 | 20 | 33 |
| **TOTAL** | **260** | **191** | **69** |

## Error Handling

### Handled Gracefully:
- PDFs with missing or corrupted metadata
- PDFs that fail to extract text
- Timeout errors (15s limit on extraction)
- Files where target already exists (skipped)
- Filesystem errors during rename

### Skipped Files:
- PDFs that already have proper DOI format
- PDFs where DOI extraction fails
- Files that don't match `itemXXX_` pattern

## Technical Details

### Dependencies
- Python 3
- `pdftotext` (from poppler)
- `pdfinfo` (from poppler)

### Timeouts
- PDF metadata extraction: 10 seconds
- PDF text extraction: 15 seconds

### File Pattern
Processes files matching: `item<number>_<suffix>.pdf`

Example valid files:
- `item001_432158.pdf` ✓ (needs DOI)
- `item001_10.5281_zenodo.pdf` ✓ (already fixed, skipped)
- `notitem_test.pdf` ✗ (wrong pattern)

## Non-Modifying Run (Dry Run)

To see what would be renamed without making changes, modify the script to comment out:
```python
pdf_path.rename(new_path)
```

Or create a test copy of the directories and run there first.

## Common Issues

### Issue: "pdftotext: command not found"
**Solution:** Install poppler
```bash
brew install poppler
```

### Issue: Script skips certain files
**Reasons:**
- PDF metadata is not readable (use text extraction fallback)
- DOI not found in document text
- Document is image-based PDF (no extractable text)

### Issue: Partial DOI extracted (truncated)
**Cause:** DOI pattern matching stops at certain characters
**Solution:** Check the extracted DOI in the renamed filename

## Future Improvements

1. Add OCR support for image-based PDFs
2. Support additional DOI databases/APIs for lookup
3. Parallel processing for faster batch operations
4. Dry-run mode flag
5. CSV report export

## Support

For issues or questions about the script, check:
- PDF metadata: `pdfinfo "path/to/file.pdf"`
- Extracted text: `pdftotext "path/to/file.pdf" - | head -100`

## License

Part of thesis research project.
