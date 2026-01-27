#!/usr/bin/env python3
"""Update original checklist with DOIs for failed items."""

import re
from pathlib import Path

# Failed items
failed_items = [1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 18, 19, 20, 21, 22, 23, 24, 25, 26, 28, 29, 31, 32, 33, 36, 38, 39, 42, 44, 45, 46, 47, 48, 49, 50, 52, 53, 54, 55, 56, 57, 67, 69, 70, 71, 73, 76, 78, 79, 80, 81, 82, 86, 88, 89, 90, 92, 96, 97, 98]

# Map item numbers to publication numbers
def item_to_pub(item):
    return 194 - item

# Extract DOIs from _001 folder
doi_folder = Path("Moth-Poulsen Publications (193-94)_001")
dois = {}

for txt_file in doi_folder.glob("*.txt"):
    match = re.match(r'(\d+)_', txt_file.name)
    if match:
        pub_num = int(match.group(1))
        content = txt_file.read_text()
        doi_match = re.search(r'DOI:\s*(10\.\d+/[^\s]+)', content)
        if doi_match:
            # Clean up DOI - remove trailing review/supplement markers for main article
            doi = doi_match.group(1)
            # Remove supplement indicators like .s001, .s002, /v2/review1
            doi = re.sub(r'\.(s\d+|v\d+.*)$', '', doi, flags=re.IGNORECASE)
            doi = re.sub(r'/v\d+/.*$', '', doi)
            dois[pub_num] = doi

# Read and update checklist
checklist_path = Path("Moth-Poulsen Publications (193-94)_002/sourcing_checklist.md")
lines = checklist_path.read_text().splitlines()

new_lines = []
updated = 0
for line in lines:
    match = re.match(r'^(\d+)\.\s*\[\s*(x?)\s*\]\s*(https?://\S+)', line, re.IGNORECASE)
    if match:
        item_num = int(match.group(1))
        checked = match.group(2)
        url = match.group(3)
        
        if item_num in failed_items and not checked:
            pub_num = item_to_pub(item_num)
            doi = dois.get(pub_num)
            if doi:
                new_url = f"https://doi.org/{doi}"
                new_lines.append(f"{item_num}. [] {new_url}")
                print(f"Item {item_num}: {url[:50]}... -> {new_url}")
                updated += 1
                continue
    
    new_lines.append(line)

checklist_path.write_text('\n'.join(new_lines) + '\n')
print(f"\nUpdated {updated} items in {checklist_path}")
