"""Zoom preprocessing package.

Public surface
--------------
VTTPreprocessor — parse, clean, and normalise raw Zoom VTT transcript bytes
                  into plain "Speaker : dialogue" text.
"""

from src.services.preprocessing.zoom.vtt import VTTPreprocessor


__all__ = ["VTTPreprocessor"]
