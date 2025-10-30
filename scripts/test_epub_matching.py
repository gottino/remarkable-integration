#!/usr/bin/env python3
"""Test EPUB text matching with Das kalte Blut."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.processors.epub_text_matcher import EPUBTextMatcher

# Paths
epub_path = "/Users/gabriele/Library/Containers/com.remarkable.desktop/Data/Library/Application Support/remarkable/desktop/02c1d14f-5106-4f02-a699-9a6c97338180.epub"
pdf_path = "/Users/gabriele/Library/Containers/com.remarkable.desktop/Data/Library/Application Support/remarkable/desktop/02c1d14f-5106-4f02-a699-9a6c97338180.pdf"

# Test examples from database with PDF artifacts
test_cases = [
    {
        "page": 220,
        "pdf_text": "Das Alter, in dem Alexander der Große starb. Und Jesus Christus. Mein Bruder, der bis dahin weder ein Reich noch eine Religion gegründet hatte, wurde nervös, fragte sich, ob seine große Zeit überhaupt noch kommen werde.",
        "description": "Page 220 - should be clean already"
    },
    {
        "page": 99,
        "pdf_text": "Sie hatte nie etwas Philosophisches oder gar { 86}Verstiegenes an sich, während Papa immer gedankenvoll wirkte, selbst wenn er stumm an der Staffelei saß und Brustwarzen kolorierte.",
        "description": "Page 99 - has { 86} artifact"
    }
]

# Get total PDF pages
from PyPDF2 import PdfReader
with open(pdf_path, 'rb') as f:
    reader = PdfReader(f)
    total_pages = len(reader.pages)
    print(f"Total PDF pages: {total_pages}\n")

# Initialize EPUB matcher
print(f"Initializing EPUB matcher for: {Path(epub_path).name}")
print(f"Fuzzy threshold: 85%\n")

matcher = EPUBTextMatcher(epub_path, fuzzy_threshold=85)

# Test each case
for i, test in enumerate(test_cases, 1):
    print(f"{'='*80}")
    print(f"Test {i}: {test['description']}")
    print(f"{'='*80}")
    print(f"Page: {test['page']}")
    print(f"\nPDF text (input):")
    print(f"  {test['pdf_text'][:100]}...")

    # Calculate position in book
    position_ratio = test['page'] / total_pages
    print(f"Position in book: {position_ratio:.1%}")
    print(f"Search window: {position_ratio*100 - 10:.1f}% to {position_ratio*100 + 10:.1f}%")

    result = matcher.match_highlight(
        pdf_text=test['pdf_text'],
        pdf_page=test['page'],
        total_pdf_pages=total_pages,
        expand_sentences=True,
        window_size=0.10
    )

    if result:
        epub_text, score = result
        print(f"\n✓ EPUB match found (score: {score})")
        print(f"\nEPUB text (output):")
        print(f"  {epub_text[:200]}...")

        # Check if the text is actually similar
        from fuzzywuzzy import fuzz
        similarity = fuzz.ratio(test['pdf_text'][:100], epub_text[:100])
        print(f"\nText similarity (first 100 chars): {similarity}%")

        # Check if text changed
        if similarity >= 80:
            print(f"→ Texts are similar - match is correct!")
            if epub_text != test['pdf_text']:
                print(f"→ And EPUB version is cleaner!")
        else:
            print(f"⚠️  WARNING: Texts are very different - possible false match!")
    else:
        print(f"\n✗ No EPUB match found")

    print()

print(f"{'='*80}")
print("Testing complete!")
print(f"{'='*80}")
