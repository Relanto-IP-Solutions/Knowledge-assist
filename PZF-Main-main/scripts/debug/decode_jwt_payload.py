#!/usr/bin/env python3
"""Decode JWT payload only (no signature verification). For local debugging.

Usage:
  python scripts/debug/decode_jwt_payload.py "<jwt>"
"""

from __future__ import annotations

import base64
import json
import sys


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: decode_jwt_payload.py <jwt>", file=sys.stderr)
        sys.exit(1)
    t = sys.argv[1].strip()
    parts = t.split(".")
    if len(parts) != 3:
        print("Expected three JWT segments.", file=sys.stderr)
        sys.exit(1)
    payload_b64 = parts[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    raw = base64.urlsafe_b64decode(payload_b64)
    print(json.dumps(json.loads(raw), indent=2))


if __name__ == "__main__":
    main()
