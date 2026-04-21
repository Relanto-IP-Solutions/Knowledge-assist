"""Slack JSON/NDJSON export preprocessing: extract, clean, and normalise messages into plain text.

Supports two raw file formats:
- JSON array  : [{...}, {...}]          (output of slack_poller.py)
- NDJSON      : one JSON object per line (output of the Drive sync pipeline)

Public API
----------
SlackPreprocessor().preprocess(data, user_map=None, since_ts=None)
    -> tuple[str, float | None]
"""

import html
import json
import re
from collections import defaultdict
from datetime import UTC, datetime


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_SKIP_SUBTYPES: frozenset[str] = frozenset({
    "channel_join",
    "channel_leave",
    "channel_archive",
})

_FILLER_WORDS: frozenset[str] = frozenset({
    "hi",
    "hello",
    "hey",
    "hola",
    "greetings",
    "howdy",
    "bye",
    "goodbye",
    "cya",
    "cheers",
    "thanks",
    "thank",
    "thankyou",
    "thx",
    "ty",
    "please",
    "pls",
    "plz",
    "yes",
    "yep",
    "yup",
    "yeah",
    "nope",
    "nah",
    "ok",
    "okay",
    "alright",
    "sure",
    "understood",
    "roger",
    "ack",
    "lol",
    "lmao",
    "haha",
    "hehe",
    "rofl",
    "np",
    "nw",
    "fyi",
    "btw",
    "imo",
    "imho",
    "afaik",
    "tbh",
    "tbd",
    "tbc",
})

_FILLER_PHRASES: list[str] = [
    "thank you",
    "no problem",
    "no worries",
    "got it",
    "sounds good",
    "noted",
    "good morning",
    "good afternoon",
    "good evening",
    "good night",
    "see you later",
    "see you soon",
    "see you",
    "see ya",
    "have a good",
    "have a great",
    "hope that helps",
    "let me know if",
    "feel free to",
]

_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"
    "\U0001f300-\U0001f5ff"
    "\U0001f680-\U0001f6ff"
    "\U0001f1e0-\U0001f1ff"
    "\U00002702-\U000027b0"
    "\U000024c2-\U0001f251"
    "\U0001f900-\U0001f9ff"
    "\U00002500-\U00002bef"
    "\U00010000-\U0010ffff"
    "]+",
    flags=re.UNICODE,
)

_THREAD_INDENT = "    "


# ---------------------------------------------------------------------------
# SlackPreprocessor
# ---------------------------------------------------------------------------


class SlackPreprocessor:
    """Parse a Slack JSON/NDJSON export and return clean, human-readable dialogue.

    Pipeline:
        decode bytes → parse JSON → select new messages (incremental) →
        clean each message → group into threads → format as dialogue text.
    """

    def preprocess(
        self,
        data: bytes,
        user_map: dict | None = None,
        since_ts: float | None = None,
    ) -> tuple[str, float | None]:
        """Entry point. Takes raw Slack file bytes and returns cleaned dialogue.

        Args:
            data:      Raw bytes of a Slack JSON array or NDJSON file.
            user_map:  Optional {user_id: display_name} dict for @mention resolution.
                       When None, raw user IDs are kept as-is.
            since_ts:  Unix timestamp (float) of the last processed message.
                       Only messages newer than this are included.
                       Pass None to process all messages (cold start / first run).

        Returns:
            (dialogue, latest_ts) where:
            - dialogue   : formatted plain-text string ready for LLM summarisation.
            - latest_ts  : float ts of the newest message included, for checkpointing.
            Returns ("", None) when there are no messages newer than since_ts.
        """
        raw = self._parse_raw(data)
        messages = self._select_messages(raw, since_ts, user_map)

        if not messages:
            return "", None

        top_level, replies = self._group_messages(messages)

        if not top_level:
            return "", None

        latest_ts = messages[-1]["ts"]
        dialogue = self._format_dialogue(top_level, replies)
        return dialogue, latest_ts

    # ------------------------------------------------------------------
    # Step 1 — parse raw bytes into a list of message objects
    # ------------------------------------------------------------------

    def _parse_raw(self, data: bytes) -> list[dict]:
        """Decode bytes and return a flat list of raw Slack message dicts.

        Tries JSON array first; falls back to NDJSON (one object per line).
        """
        text = data.decode("utf-8")
        text = text.strip()

        # Try JSON array format: [{...}, ...]
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            # Single top-level object — treat as a one-element NDJSON
            if isinstance(parsed, dict):
                return [parsed]
        except json.JSONDecodeError:
            pass

        # Fall back to NDJSON: one JSON object per line
        objects = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    objects.append(obj)
            except json.JSONDecodeError:
                continue
        return objects

    # ------------------------------------------------------------------
    # Step 2 — select messages newer than since_ts (3-pass logic)
    # ------------------------------------------------------------------

    def _select_messages(
        self,
        raw: list[dict],
        since_ts: float | None,
        user_map: dict | None,
    ) -> list[dict]:
        """Return cleaned, de-duplicated messages to include in this batch.

        Pass 1: find which threads have new activity and which standalone
                messages are new.
        Pass 2: build the full inclusion set — new standalone messages plus
                every message (parent + replies) for active threads.
        Pass 3: parse + clean each included message; deduplicate; sort by ts.

        When since_ts is None (cold start), all messages are treated as new.
        """
        active_thread_ts: set[str] = set()
        new_standalone_ts: set[str] = set()

        # Pass 1 — discover what is new
        for obj in raw:
            ts_str = obj.get("ts")
            if ts_str is None:
                continue

            try:
                ts = float(ts_str)
            except (TypeError, ValueError):
                continue

            if since_ts is not None and ts <= since_ts:
                continue

            thread_ts = obj.get("thread_ts")
            if thread_ts is None:
                new_standalone_ts.add(ts_str)
            else:
                active_thread_ts.add(thread_ts)

        # Pass 2 — build inclusion set
        to_include: set[str] = set()
        for obj in raw:
            ts_str = obj.get("ts")
            thread_ts = obj.get("thread_ts")

            if ts_str in new_standalone_ts:
                to_include.add(ts_str)
            elif thread_ts in active_thread_ts:
                # Include every message in the thread: parent + all replies
                to_include.add(ts_str)
            elif ts_str in active_thread_ts:
                # Thread parent whose ts == thread_ts
                to_include.add(ts_str)

        if not to_include:
            return []

        # Pass 3 — parse and clean each included message
        messages: list[dict] = []
        seen: set[str] = set()

        for obj in raw:
            ts_str = obj.get("ts")
            if ts_str not in to_include or ts_str in seen:
                continue
            seen.add(ts_str)

            parsed = self._parse_message(obj, user_map)
            if parsed:
                messages.append(parsed)

        messages.sort(key=lambda m: m["ts"])
        return messages

    # ------------------------------------------------------------------
    # Step 3 — parse and clean a single message object
    # ------------------------------------------------------------------

    def _parse_message(self, obj: dict, user_map: dict | None) -> dict | None:
        """Normalise one raw Slack message object into a cleaned dict.

        Returns None if the message should be skipped (wrong subtype,
        empty after cleaning, or missing timestamp).
        """
        if obj.get("subtype") in _SKIP_SUBTYPES:
            return None

        ts_str = obj.get("ts")
        if not ts_str:
            return None

        blocks = obj.get("blocks") or []
        if blocks:
            raw_text = self._extract_text_from_blocks(blocks, user_map)
        else:
            raw_text = obj.get("text") or ""

        cleaned = self._clean_text(raw_text)
        if not cleaned:
            return None

        try:
            ts_float = float(ts_str)
        except (TypeError, ValueError):
            return None

        ts_utc = datetime.fromtimestamp(ts_float, tz=UTC).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

        uid = obj.get("user", "UNKNOWN")
        display_name = (user_map or {}).get(uid, uid)

        return {
            "user": display_name,
            "ts": ts_float,
            "ts_raw": ts_str,
            "ts_utc": ts_utc,
            "thread_ts": obj.get("thread_ts"),
            "text": cleaned,
        }

    # ------------------------------------------------------------------
    # Step 4 — group parsed messages into top-level + replies
    # ------------------------------------------------------------------

    def _group_messages(
        self, messages: list[dict]
    ) -> tuple[list[dict], dict[str, list[dict]]]:
        """Split messages into top-level entries and per-thread reply lists.

        Returns:
            top_level : standalone messages and thread parents, sorted by ts.
            replies   : {thread_ts_raw: [reply, ...]} each list sorted by ts.
        """
        replies: dict[str, list[dict]] = defaultdict(list)
        top_level: list[dict] = []

        for msg in messages:
            t_ts = msg["thread_ts"]
            if t_ts is None:
                top_level.append(msg)
            elif t_ts == msg["ts_raw"]:
                # Thread parent: ts == thread_ts
                top_level.append(msg)
            else:
                replies[t_ts].append(msg)

        for thread_msgs in replies.values():
            thread_msgs.sort(key=lambda m: m["ts"])

        top_level.sort(key=lambda m: m["ts"])
        return top_level, dict(replies)

    # ------------------------------------------------------------------
    # Step 5 — format final dialogue string
    # ------------------------------------------------------------------

    def _format_dialogue(
        self,
        top_level: list[dict],
        replies: dict[str, list[dict]],
    ) -> str:
        """Assemble top-level messages and their thread replies into plain text.

        Standalone messages are left-aligned.
        Thread parents are left-aligned; replies are indented 4 spaces.
        A blank line follows each thread block.

        Each line format: ({ts_utc}) {user}: {text}
        """
        lines: list[str] = []

        for msg in top_level:
            thread_replies = replies.get(msg["ts_raw"], [])
            line = f"({msg['ts_utc']}) {msg['user']}: {msg['text']}"

            if thread_replies:
                lines.append(line)
                lines.extend(
                    f"{_THREAD_INDENT}({reply['ts_utc']}) {reply['user']}: {reply['text']}"
                    for reply in thread_replies
                )
                lines.append("")  # blank line after thread
            else:
                lines.append(line)

        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # Text cleaning helpers
    # ------------------------------------------------------------------

    def _remove_emojis(self, text: str) -> str:
        return _EMOJI_RE.sub("", text)

    def _clean_text(self, text: str) -> str:
        """Full text cleaning pipeline for RAG ingestion.

        Steps (in order):
          1. Early-exit on blank input
          2. HTML entity decoding
          3. Strip HTML tags
          4. Strip URLs
          5. Strip Slack mention tokens (<@ID> and @ALLCAPS)
          6. Strip emojis
          7. Strip Slack inline markdown (backtick, *bold*, _italic_, ~strike~)
          8. Collapse whitespace control chars to space
          9. Collapse multiple spaces; strip
         10. Lowercase
         11. Strip non-word / non-space characters
         12. Remove filler phrases (word-bounded)
         13. Filter filler words
         14. Final collapse + strip
        """
        if not text or not text.strip():
            return ""

        text = html.unescape(text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"https?://\S+|www\.\S+", "", text)
        text = re.sub(r"<@[A-Z0-9_]+>", "", text)
        text = re.sub(r"@[A-Z0-9_]+", "", text)
        text = self._remove_emojis(text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"_([^_]+)_", r"\1", text)
        text = re.sub(r"~([^~]+)~", r"\1", text)
        text = re.sub(r"[\n\r\t]", " ", text)
        text = re.sub(r" {2,}", " ", text).strip()
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)

        for phrase in _FILLER_PHRASES:
            text = re.sub(rf"\b{re.escape(phrase)}\b", "", text, flags=re.IGNORECASE)

        words = text.split()
        text = " ".join(
            w for w in words if w.lower() not in _FILLER_WORDS and w.strip()
        )

        text = re.sub(r" {2,}", " ", text).strip()
        return text

    def _extract_text_from_blocks(self, blocks: list, user_map: dict | None) -> str:
        """Recursively walk a Slack rich-text blocks tree and collect plain text.

        Handles:
        - text nodes         : appended as-is
        - user mention nodes : resolved to @display_name via user_map
        - rich_text_list     : children separated by newlines
        - all other nodes    : recurse into their elements
        """
        parts: list[str] = []

        def walk(node: object) -> None:
            if isinstance(node, dict):
                node_type = node.get("type")
                if node_type == "text" and "text" in node:
                    parts.append(node["text"])
                elif node_type == "user":
                    uid = node.get("user_id", "")
                    name = (user_map or {}).get(uid, uid)
                    parts.append(f"@{name}")
                elif node_type == "rich_text_list":
                    for i, child in enumerate(node.get("elements", [])):
                        if i > 0:
                            parts.append("\n")
                        walk(child)
                else:
                    for child in node.get("elements", []):
                        walk(child)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(blocks)
        return "".join(parts).strip()
