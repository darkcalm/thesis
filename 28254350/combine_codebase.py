#!/usr/bin/env python3
"""
Script to combine all codebase files from the Automation directory into a single PDF.
Each file starts on a new page with proper formatting.
"""

import os
from pathlib import Path
from datetime import datetime

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Preformatted
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("Warning: reportlab not installed. Install with: pip install reportlab")
    print("Falling back to text output mode.")
    print()


def should_include_file(filepath):
    """Determine if a file should be included in the combined output."""
    # Include these extensions
    include_extensions = {'.py', '.pyw', '.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.js', '.jsx', '.ts', '.tsx', '.css', '.html'}

    # Exclude patterns
    exclude_patterns = {'__pycache__', '.git', '.pyc', '.pyo', 'node_modules', '.DS_Store'}

    # Check if file should be excluded
    for pattern in exclude_patterns:
        if pattern in str(filepath):
            return False

    # Check if file extension is included
    return filepath.suffix.lower() in include_extensions


class NumberedCanvas(canvas.Canvas):
    """Custom canvas to add page numbers and headers."""
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        self.setFont("Courier", 9)
        self.drawRightString(letter[0] - 0.75*inch, 0.5*inch,
                            f"Page {self._pageNumber} of {page_count}")


def combine_codebase_pdf(root_dir, output_file):
    """Combine all code files from root_dir into a single PDF with page breaks."""
    root_path = Path(root_dir)

    if not root_path.exists():
        print(f"Error: Directory {root_dir} does not exist")
        return

    files_found = []

    # Collect all files
    for filepath in sorted(root_path.rglob('*')):
        if filepath.is_file() and should_include_file(filepath):
            files_found.append(filepath)

    if not files_found:
        print("No files found to combine")
        return

    # Create PDF
    doc = SimpleDocTemplate(output_file, pagesize=letter,
                           rightMargin=0.75*inch, leftMargin=0.75*inch,
                           topMargin=0.75*inch, bottomMargin=0.75*inch)

    # Define styles
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor='black',
        spaceAfter=30,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )

    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        textColor='black',
        spaceAfter=12,
        spaceBefore=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )

    file_heading_style = ParagraphStyle(
        'FileHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor='black',
        spaceAfter=12,
        spaceBefore=6,
        fontName='Helvetica-Bold'
    )

    code_style = ParagraphStyle(
        'Code',
        parent=styles['Code'],
        fontSize=8,
        fontName='Courier',
        leftIndent=0,
        rightIndent=0,
        spaceAfter=6,
        leading=10
    )

    toc_style = ParagraphStyle(
        'TOC',
        parent=styles['Normal'],
        fontSize=10,
        fontName='Courier',
        leftIndent=20,
        spaceAfter=4
    )

    story = []

    # Title page / Header
    story.append(Paragraph(f"COMBINED CODEBASE", title_style))
    story.append(Paragraph(f"{root_path.name}", heading_style))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    story.append(Paragraph(f"Total files: {len(files_found)}", styles['Normal']))
    story.append(Spacer(1, 0.5*inch))

    # Table of contents
    story.append(Paragraph("TABLE OF CONTENTS", heading_style))
    story.append(Spacer(1, 0.2*inch))

    for i, filepath in enumerate(files_found, 1):
        rel_path = filepath.relative_to(root_path)
        story.append(Paragraph(f"{i:3}. {rel_path}", toc_style))

    story.append(PageBreak())

    # Add each file with page break
    for i, filepath in enumerate(files_found, 1):
        rel_path = filepath.relative_to(root_path)

        # File header
        file_header = f"FILE {i}/{len(files_found)}: {rel_path}"
        story.append(Paragraph(file_header, file_heading_style))
        story.append(Spacer(1, 0.1*inch))

        # File content
        try:
            with open(filepath, 'r', encoding='utf-8') as inf:
                content = inf.read()

                # Split content into smaller chunks to avoid reportlab issues
                # Preformatted handles code better than Paragraph
                if content.strip():
                    # For very long lines, we might need to wrap or truncate
                    lines = content.split('\n')
                    formatted_lines = []
                    for line in lines:
                        # Truncate very long lines to prevent overflow
                        if len(line) > 100:
                            formatted_lines.append(line[:100] + '...')
                        else:
                            formatted_lines.append(line)

                    formatted_content = '\n'.join(formatted_lines)
                    story.append(Preformatted(formatted_content, code_style))
                else:
                    story.append(Paragraph("[Empty file]", styles['Italic']))

        except Exception as e:
            story.append(Paragraph(f"[Error reading file: {e}]", styles['Italic']))

        # Add page break after each file (except the last one)
        if i < len(files_found):
            story.append(PageBreak())

    # Build PDF with custom canvas for page numbers
    doc.build(story, canvasmaker=NumberedCanvas)

    print(f"Successfully combined {len(files_found)} files into {output_file}")
    print(f"\nFiles included:")
    for filepath in files_found:
        rel_path = filepath.relative_to(root_path)
        print(f"  - {rel_path}")


def combine_codebase_text(root_dir, output_file):
    """Fallback: Combine all code files from root_dir into a single text file."""
    root_path = Path(root_dir)

    if not root_path.exists():
        print(f"Error: Directory {root_dir} does not exist")
        return

    files_found = []

    # Collect all files
    for filepath in sorted(root_path.rglob('*')):
        if filepath.is_file() and should_include_file(filepath):
            files_found.append(filepath)

    if not files_found:
        print("No files found to combine")
        return

    # Write combined output
    with open(output_file, 'w', encoding='utf-8') as outf:
        # Write header
        outf.write("=" * 80 + "\n")
        outf.write(f"COMBINED CODEBASE: {root_path.name}\n")
        outf.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        outf.write(f"Total files: {len(files_found)}\n")
        outf.write("=" * 80 + "\n\n")

        # Write table of contents
        outf.write("TABLE OF CONTENTS\n")
        outf.write("-" * 80 + "\n")
        for i, filepath in enumerate(files_found, 1):
            rel_path = filepath.relative_to(root_path)
            outf.write(f"{i:3}. {rel_path}\n")
        outf.write("\n" + "=" * 80 + "\n\n")

        # Write each file
        for i, filepath in enumerate(files_found, 1):
            rel_path = filepath.relative_to(root_path)

            # File header
            outf.write("\n" + "=" * 80 + "\n")
            outf.write(f"FILE {i}/{len(files_found)}: {rel_path}\n")
            outf.write("=" * 80 + "\n\n")

            # File content
            try:
                with open(filepath, 'r', encoding='utf-8') as inf:
                    content = inf.read()
                    outf.write(content)
                    if not content.endswith('\n'):
                        outf.write('\n')
            except Exception as e:
                outf.write(f"[Error reading file: {e}]\n")

            outf.write("\n")

        # Write footer
        outf.write("\n" + "=" * 80 + "\n")
        outf.write("END OF COMBINED CODEBASE\n")
        outf.write("=" * 80 + "\n")

    print(f"Successfully combined {len(files_found)} files into {output_file}")
    print(f"\nFiles included:")
    for filepath in files_found:
        rel_path = filepath.relative_to(root_path)
        print(f"  - {rel_path}")


if __name__ == "__main__":
    # Configuration
    AUTOMATION_DIR = "/Users/para/Desktop/28254350/Automation"

    print(f"Combining codebase from: {AUTOMATION_DIR}")
    print("-" * 80)

    if REPORTLAB_AVAILABLE:
        OUTPUT_FILE = "/Users/para/Desktop/28254350/Automation_combined.pdf"
        print(f"Output file: {OUTPUT_FILE}")
        print("Generating PDF with page breaks...")
        print()
        combine_codebase_pdf(AUTOMATION_DIR, OUTPUT_FILE)
        print("-" * 80)
        print(f"\nDone! PDF generated successfully.")
        print(f"Open {OUTPUT_FILE} to view the combined codebase.")
    else:
        OUTPUT_FILE = "/Users/para/Desktop/28254350/Automation_combined.txt"
        print(f"Output file: {OUTPUT_FILE}")
        print("Generating text file (reportlab not available)...")
        print()
        combine_codebase_text(AUTOMATION_DIR, OUTPUT_FILE)
        print("-" * 80)
        print(f"\nDone! Text file generated.")
        print(f"\nTo generate PDF with page breaks, install reportlab:")
        print("  pip install reportlab")
        print("\nThen run this script again.")
