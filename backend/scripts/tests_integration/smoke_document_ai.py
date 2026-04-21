"""Smoke-check for Document AI: process a small PDF and print extracted text.

Run with: uv run python scripts/tests_integration/smoke_document_ai.py [path/to/sample.pdf]

If no path is given, uses a minimal one-page PDF in memory.
Requires: Document AI API enabled, processor name in settings, service account with Document AI permissions.
"""

import pathlib
import sys


sys.path.insert(
    0, pathlib.Path(pathlib.Path(pathlib.Path(__file__).resolve()).parent).parent
)

# Minimal valid single-page PDF (no text content)
MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000052 00000 n
0000000101 00000 n
trailer<</Size 4/Root 1 0 R>>
startxref
178
%%EOF
"""


def main() -> None:
    from src.services.format_processors.pdf import extract_pdf

    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path, "rb") as f:
            data = f.read()
        print(f"Loaded PDF from {path} ({len(data)} bytes)")
    else:
        data = MINIMAL_PDF
        print(f"Using minimal in-memory PDF ({len(data)} bytes)")

    print("Calling Document AI...")
    text = extract_pdf(data)
    print(f"Extracted text length: {len(text)} chars")
    if text.strip():
        snippet = text.strip()[:500] + ("..." if len(text.strip()) > 500 else "")
        print(f"Preview:\n{snippet}")
    else:
        print("(No text in document - OK for empty/minimal PDF)")
    print("Document AI smoke check OK.")


if __name__ == "__main__":
    main()
