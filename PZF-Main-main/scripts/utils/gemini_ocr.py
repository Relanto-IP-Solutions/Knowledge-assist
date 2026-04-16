"""
Gemini OCR — PDF and image transcription via Vertex AI Gemini Vision.

Supports JPG, PNG, WebP, GIF, and PDF files.
For PDFs, splits into page batches to stay within output token limits.

Usage:
    python gemini_ocr.py --file document.pdf
    python gemini_ocr.py --file notes.jpg
    python gemini_ocr.py --file document.pdf --batch-size 20
    python gemini_ocr.py --file document.pdf --model gemini-2.5-flash

Output:
    gemini_output/parsed_<filename>.md
"""

import argparse
import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


# ── Config ───────────────────────────────────────────────────────────────────
GCP_PROJECT = os.environ.get("GCP_PROJECT_ID", "your-gcp-project-id")
GCP_LOCATION = os.environ.get("VERTEX_AI_LOCATION", "us-central1")
DEFAULT_MODEL = os.environ.get("LLM_MODEL_NAME", "gemini-2.5-flash")

OUTPUT_DIR = Path(__file__).parent / "out/Data_Engineering_Design_Patterns_2025_copy"
OUTPUT_DIR.mkdir(exist_ok=True)

SUPPORTED_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}

DEFAULT_PROMPT = """\
You are an expert at reading handwritten notes and documents.

Transcribe all text from these pages into clean Markdown format:
- Use # ## ### for headings and section titles
- Preserve bullet points, numbered lists, and table
- Do NOT add summaries, explanations, or commentary
- Do NOT wrap in JSON or code blocks
- Output ONLY the transcribed content, nothing else
"""

BATCH_PROMPT_SUFFIX = (
    "\n\nNote: This is a batch of pages from a larger document. "
    "Transcribe only the content visible in these pages."
)


# ── Post-processing ──────────────────────────────────────────────────────────


def clean_markdown(text: str) -> str:
    """Strip excessive whitespace padding Gemini adds when reproducing visual layouts."""
    import re

    # Collapse runs of 4+ spaces (cell padding) down to a single space
    text = re.sub(r" {4,}", " ", text)
    # Collapse runs of 3+ blank lines down to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── PDF helpers ───────────────────────────────────────────────────────────────


def get_pdf_page_count(pdf_path: Path) -> int:
    import pypdf

    with open(pdf_path, "rb") as f:
        return len(pypdf.PdfReader(f).pages)


def extract_pdf_pages(pdf_path: Path, start: int, end: int) -> bytes:
    """Return bytes for pages [start, end) (0-indexed) of the given PDF."""
    import pypdf

    with open(pdf_path, "rb") as f:
        reader = pypdf.PdfReader(f)
        writer = pypdf.PdfWriter()
        for i in range(start, min(end, len(reader.pages))):
            writer.add_page(reader.pages[i])
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()


# ── Gemini calls ──────────────────────────────────────────────────────────────


def _call_gemini(file_bytes: bytes, mime_type: str, prompt: str, model) -> str:
    from vertexai.generative_models import Part

    part = Part.from_data(data=file_bytes, mime_type=mime_type)
    response = model.generate_content(
        [part, prompt],
        generation_config={"temperature": 0.1, "max_output_tokens": 8192},
    )
    return response.text


def run_ocr(
    file_path: Path,
    prompt: str,
    model_name: str,
    batch_size: int,
    max_workers: int,
) -> str:
    """
    Run Gemini OCR on the given file.
    - Images: single API call.
    - PDFs with batch_size > 0: split into page batches, merge results.
    - PDFs with batch_size == 0: single call with full PDF.
    """
    import vertexai
    from vertexai.generative_models import GenerativeModel

    vertexai.init(project=GCP_PROJECT, location=GCP_LOCATION)
    print(f"[Gemini] Model: {model_name}")

    mime_type = SUPPORTED_MIME.get(file_path.suffix.lower(), "image/jpeg")

    if mime_type != "application/pdf" or batch_size <= 0:
        file_bytes = file_path.read_bytes()
        size_kb = len(file_bytes) // 1024
        print(f"[Gemini] Single call — {mime_type} ({size_kb} KB)")
        model = GenerativeModel(model_name)
        return _call_gemini(file_bytes, mime_type, prompt, model)

    total_pages = get_pdf_page_count(file_path)
    total_batches = (total_pages + batch_size - 1) // batch_size
    print(
        f"[Gemini] {total_pages} pages → {total_batches} batches of {batch_size} pages"
    )

    batch_prompt = prompt + BATCH_PROMPT_SUFFIX

    # Submit all batches concurrently (executed up to max_workers at a time),
    # then collate results strictly in original page order.
    batches: list[tuple[int, int, int]] = []
    for batch_num, start in enumerate(range(0, total_pages, batch_size), start=1):
        end = min(start + batch_size, total_pages)
        batches.append((batch_num, start, end))

    effective_workers = max(1, min(int(max_workers), total_batches))
    print(f"[Gemini] Running batches concurrently (max_workers={effective_workers})")

    def _run_one(batch_num: int, start: int, end: int) -> tuple[int, str]:
        from vertexai.generative_models import GenerativeModel

        print(
            f"[Gemini] Batch {batch_num}/{total_batches}: pages {start + 1}–{end} ..."
        )
        chunk_bytes = extract_pdf_pages(file_path, start, end)

        # Retry this batch on HTTP 429 (rate limit) with simple exponential backoff.
        max_retries = 3
        backoff = 5.0  # seconds
        attempt = 0

        while True:
            attempt += 1
            model = GenerativeModel(model_name)
            try:
                text = _call_gemini(chunk_bytes, mime_type, batch_prompt, model)
                print(
                    f"[Gemini] Batch {batch_num} done (attempt {attempt}, {len(text):,} chars)"
                )
                return batch_num, text
            except Exception as exc:
                # Try to detect HTTP 429 from common error shapes.
                status_code = getattr(exc, "code", None) or getattr(
                    exc, "status_code", None
                )
                message = str(exc)
                is_429 = (
                    status_code == 429
                    or "429" in message
                    or "Too Many Requests" in message
                )

                if is_429 and attempt <= max_retries:
                    print(
                        f"[Gemini] Batch {batch_num} hit 429 (attempt {attempt}/{max_retries}). "
                        f"Retrying in {backoff:.1f}s..."
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                print(f"[Gemini] Batch {batch_num} failed (attempt {attempt}): {exc}")
                return (
                    batch_num,
                    f"\n\n<!-- Pages {start + 1}–{end} FAILED: {exc} -->\n\n",
                )

    results_by_batch: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        future_map = {
            executor.submit(_run_one, batch_num, start, end): batch_num
            for (batch_num, start, end) in batches
        }
        for fut in as_completed(future_map):
            batch_num, text = fut.result()
            results_by_batch[batch_num] = text

    parts = [results_by_batch[i] for i in range(1, total_batches + 1)]
    return "\n\n".join(parts)


# ── CLI ───────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Gemini OCR — transcribe PDFs and images to Markdown"
    )
    parser.add_argument("--file", required=True, help="Path to PDF or image file")
    parser.add_argument(
        "--prompt", default=DEFAULT_PROMPT, help="Override transcription prompt"
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=15,
        help="Pages per API call for PDFs (default: 15, set 0 for single call)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=int(os.environ.get("GEMINI_OCR_MAX_WORKERS", "10")),
        help="Max concurrent batch calls for PDFs (default: 4)",
    )
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"ERROR: File not found: {file_path}")
        sys.exit(1)

    if file_path.suffix.lower() not in SUPPORTED_MIME:
        print(
            f"ERROR: Unsupported file type '{file_path.suffix}'. Supported: {', '.join(SUPPORTED_MIME)}"
        )
        sys.exit(1)

    is_pdf = file_path.suffix.lower() == ".pdf"

    print("=" * 60)
    print("Gemini OCR")
    print(f"  File:       {file_path}")
    print(f"  Model:      {args.model}")
    if is_pdf:
        total_pages = get_pdf_page_count(file_path)
        if args.batch_size > 0:
            total_batches = (total_pages + args.batch_size - 1) // args.batch_size
            print(
                f"  Pages:      {total_pages} → {total_batches} batches of {args.batch_size}"
            )
        else:
            print(f"  Pages:      {total_pages} (single call, no batching)")
    print("=" * 60)

    start_time = time.time()
    result = run_ocr(
        file_path, args.prompt, args.model, args.batch_size, args.max_workers
    )
    elapsed = time.time() - start_time

    result = clean_markdown(result)

    out_file = OUTPUT_DIR / f"parsed_{file_path.stem}.md"
    out_file.write_text(result, encoding="utf-8")
    print(f"\n[Done] Output → {out_file}  ({len(result):,} chars)")
    print(f"[Time] Total execution time: {elapsed:.1f}s")
    sys.exit(0)


if __name__ == "__main__":
    main()
