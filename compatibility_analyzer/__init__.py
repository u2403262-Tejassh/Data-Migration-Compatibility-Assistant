"""Compatibility package shim for this repository's flat source layout.

The application imports modules as ``compatibility_analyzer.*``, while the
source directories live at the repository root. Point this package's search
path at that root so the existing package imports resolve without relocating
or changing the application modules.
"""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent.parent)]
