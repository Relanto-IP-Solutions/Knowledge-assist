"""Email text cleaning pipeline for RAG preprocessing.

Cleaning steps applied (in order):
    1. Unicode normalization (NFC) - fixes garbled em-dashes, smart quotes
    2. Line ending normalization (\\r\\n -> \\n)
    3. Quoted reply removal - lines starting with '>' or '|'
    3b. Quote attribution removal - Gmail "On [date], [name] wrote:" lines
    4. Signature block removal - RFC 2646 delimiter + heuristic detection
    5. Disclaimer/footer removal - confidentiality notices, legal boilerplate
    6. Separator line removal - visual dividers (────, ====, ----)
    7. Whitespace normalization - collapse multiple blanks, strip lines
    8. Invisible character removal - zero-width spaces, BOM, control chars
"""

from __future__ import annotations

import re
import unicodedata


# ============================================================================
# Compiled regex patterns (module-level for performance)
# ============================================================================

# Quoted reply lines (Outlook / Gmail style: lines starting with > or |)
_QUOTED_LINE_RE = re.compile(r"^\s*[>|]")

# Visual separator lines (box drawing chars, dashes, equals)
_SEPARATOR_RE = re.compile(r"^[\s\u2500-\u257F\u2550-\u256C=\-_]{5,}\s*$")

# RFC 2646 signature delimiter (-- on its own line)
_SIG_HARD_DELIMITER_RE = re.compile(r"^--\s*$")

# Closing salutations that typically start a signature block
_SIG_SALUTATION_RE = re.compile(
    r"^\s*(Best\s+regards|Kind\s+regards|Warm\s+regards|With\s+regards|Regards|"
    r"Sincerely|Thank\s+you|Thanks|Cheers|Best\s+wishes|Best|Yours\s+(truly|sincerely)|"
    r"With\s+appreciation|Respectfully)[,.]?\s*$",
    re.IGNORECASE,
)

# Contact/identity lines common in signatures (phone, email, URL, title)
_SIG_CONTACT_RE = re.compile(
    r"("
    r"(\+?[\d][\d\s\-\.\(\)]{6,})|"  # Phone numbers
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}|"  # Email
    r"(https?://|www\.)[^\s]+|"  # URLs
    r"\b(Vice\s+President|VP|Director|Manager|Engineer|Analyst|Consultant|"
    r"President|CEO|CTO|CISO|CFO|COO|Partner|Principal|Lead|Head\s+of)\b"  # Titles
    r")",
    re.IGNORECASE,
)

# Disclaimer/confidentiality footer trigger phrases
_DISCLAIMER_TRIGGERS_RE = re.compile(
    r"(IMPORTANT\s+NOTICE|This\s+e[\-]?mail\s+and\s+any|"
    r"The\s+information\s+contained\s+in\s+this|"
    r"CONFIDENTIALITY\s+NOTICE|"
    r"This\s+message\s+is\s+intended\s+solely\s+for|"
    r"Unauthorized\s+disclosure|"
    r"If\s+you\s+are\s+not\s+the\s+intended\s+recipient|"
    r"This\s+email\s+and\s+any\s+attachments\s+are\s+confidential)",
    re.IGNORECASE,
)

# Gmail quote attribution patterns:
# Pattern 1: "On [date], [name] <email> wrote:" (single line)
# Pattern 2: "On [date], [name] <email>" followed by "wrote:" on next line
_QUOTE_ATTRIBUTION_SINGLE_RE = re.compile(
    r"^\s*On\s+.{10,80}\s+wrote:\s*$",
    re.IGNORECASE,
)
# Matches "On [date/time], [name] <email@domain>" - the start of a quote attribution
_QUOTE_ATTRIBUTION_START_RE = re.compile(
    r"^\s*On\s+.{10,60}<[^>]+@[^>]+>\s*$",
    re.IGNORECASE,
)
# Matches standalone "wrote:" line (continuation of attribution)
_QUOTE_ATTRIBUTION_WROTE_RE = re.compile(
    r"^\s*wrote:\s*$",
    re.IGNORECASE,
)

# Blank line detection
_BLANK_LINE_RE = re.compile(r"^\s*$")

# Multiple spaces/tabs within a line
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")

# Invisible/control characters (excluding \t and \n)
_INVISIBLE_CHARS_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f"  # ASCII control chars
    r"\u00ad"  # soft hyphen
    r"\u200b-\u200f"  # zero-width spaces/joiners
    r"\u202a-\u202e"  # directional formatting
    r"\ufeff"  # BOM
    r"]"
)

# Repeated punctuation patterns
_REPEAT_EXCLAIM_RE = re.compile(r"!{2,}")
_REPEAT_QUESTION_RE = re.compile(r"\?{2,}")
_REPEAT_DASH_RE = re.compile(r"-{3,}")
_ELLIPSIS_RE = re.compile(r"\.{4,}")


# ============================================================================
# Cleaning functions
# ============================================================================


def _normalize_unicode(text: str) -> str:
    """Step 1: NFC normalize Unicode (fixes smart quotes, em-dashes)."""
    return unicodedata.normalize("NFC", text)


def _normalize_line_endings(text: str) -> str:
    """Step 2: Standardize all line endings to Unix-style \\n."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _remove_quoted_lines(lines: list[str]) -> list[str]:
    """Step 3: Remove lines that begin with '>' or '|' (quoted replies)."""
    return [line for line in lines if not _QUOTED_LINE_RE.match(line)]


def _remove_quote_attribution(lines: list[str]) -> list[str]:
    """Step 3b: Remove Gmail quote attribution and everything after.

    Gmail inline quotes start with 'On [date], [name] wrote:' followed by
    the quoted content. Handles two formats:
      - Single line: "On Mon, 30 Mar 2026 at 04:24, Name <email> wrote:"
      - Two lines: "On Mon, 30 Mar 2026 at 04:24, Name <email>" + "wrote:"
    """
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Single-line attribution: "On ... wrote:"
        if _QUOTE_ATTRIBUTION_SINGLE_RE.match(line):
            break

        # Two-line attribution: "On ... <email>" followed by "wrote:"
        if _QUOTE_ATTRIBUTION_START_RE.match(line):
            # Check if next line is "wrote:"
            if i + 1 < len(lines) and _QUOTE_ATTRIBUTION_WROTE_RE.match(lines[i + 1]):
                break

        result.append(line)
        i += 1

    return result


def _remove_signature_block(lines: list[str]) -> list[str]:
    """Step 4: Remove email signature blocks.

    Two-tier strategy:
    - Tier 1 (hard): RFC 2646 delimiter (-- on its own line) - unconditional truncation
    - Tier 2 (soft): Salutation + contact info heuristic - requires both to trigger
    """
    result: list[str] = []

    for i, line in enumerate(lines):
        # Tier 1: Hard delimiter
        if _SIG_HARD_DELIMITER_RE.match(line):
            break

        # Tier 2: Salutation followed by contact info
        if _SIG_SALUTATION_RE.match(line):
            window = lines[i + 1 : i + 7]
            has_contact = any(_SIG_CONTACT_RE.search(ln) for ln in window if ln.strip())
            if has_contact:
                break

        result.append(line)

    return result


def _remove_disclaimer_footer(lines: list[str]) -> list[str]:
    """Step 5: Truncate at first disclaimer/confidentiality notice."""
    result: list[str] = []
    for line in lines:
        if _DISCLAIMER_TRIGGERS_RE.search(line):
            break
        result.append(line)
    return result


def _remove_separator_lines(lines: list[str]) -> list[str]:
    """Step 6: Remove pure visual divider lines."""
    return [line for line in lines if not _SEPARATOR_RE.match(line)]


def _normalize_whitespace(lines: list[str]) -> list[str]:
    """Step 7: Normalize whitespace - strip lines, collapse internal spaces."""
    result: list[str] = []
    for line in lines:
        if _BLANK_LINE_RE.match(line):
            result.append("")
        else:
            line = line.rstrip()
            line = _MULTI_SPACE_RE.sub(" ", line)
            result.append(line)
    return result


def _collapse_blank_lines(lines: list[str]) -> list[str]:
    """Step 7b: Reduce multiple consecutive blank lines to one."""
    result: list[str] = []
    blank_count = 0
    for line in lines:
        if _BLANK_LINE_RE.match(line):
            blank_count += 1
            if blank_count <= 1:
                result.append("")
        else:
            blank_count = 0
            result.append(line)
    return result


def _remove_invisible_chars(text: str) -> str:
    """Step 8a: Remove invisible Unicode characters."""
    return _INVISIBLE_CHARS_RE.sub("", text)


def _normalize_punctuation(text: str) -> str:
    """Step 8b: Collapse repeated punctuation (!!!, ???, ....)."""
    text = _REPEAT_EXCLAIM_RE.sub("!", text)
    text = _REPEAT_QUESTION_RE.sub("?", text)
    text = _REPEAT_DASH_RE.sub("--", text)
    text = _ELLIPSIS_RE.sub("...", text)
    return text


# ============================================================================
# Public API
# ============================================================================


def clean_body(raw: str | None) -> str | None:
    """Apply the full 8-step cleaning pipeline to an email body.

    Args:
        raw: Raw email body text.

    Returns:
        Cleaned text, or None if input is empty or all content is removed.
    """
    if not raw or not raw.strip():
        return None

    # Steps 1-2: Unicode and line ending normalization
    text = _normalize_unicode(raw)
    text = _normalize_line_endings(text)

    # Steps 3-7: Line-based cleaning
    lines = text.splitlines()
    lines = _remove_quoted_lines(lines)
    lines = _remove_quote_attribution(lines)
    lines = _remove_separator_lines(lines)
    lines = _remove_signature_block(lines)
    lines = _remove_disclaimer_footer(lines)
    lines = _normalize_whitespace(lines)
    lines = _collapse_blank_lines(lines)

    # Steps 8: Character-level cleaning
    text = "\n".join(lines)
    text = _remove_invisible_chars(text)
    text = _normalize_punctuation(text)

    cleaned = text.strip()
    return cleaned or None


def clean_subject(raw: str | None) -> str | None:
    """Clean an email subject line.

    Args:
        raw: Raw subject header.

    Returns:
        Cleaned subject, or None if empty.
    """
    if not raw:
        return None
    text = _normalize_unicode(raw)
    text = _remove_invisible_chars(text)
    return text.strip() or None


class ThreadCleaner:
    """Stateful cleaner for processing email threads.

    Provides the same cleaning as the module-level functions but as a class
    for consistency with other preprocessing modules.
    """

    @staticmethod
    def clean_body(raw: str | None) -> str | None:
        """Clean an email body using the 8-step pipeline."""
        return clean_body(raw)

    @staticmethod
    def clean_subject(raw: str | None) -> str | None:
        """Clean an email subject line."""
        return clean_subject(raw)
