"""OpenSoul UI entrypoint — Apple-clean custom frontend (FastAPI).

Launch:
  OPENSOUL_DRY_RUN=1 GRADIO_SERVER_PORT=7860 python -m app.ui

Gradio was replaced so the main path can stay plain-language and visually quiet.
Advanced / SDK status lives at /api/health (Advanced link in the UI).
"""

from __future__ import annotations

from app.server import main

if __name__ == "__main__":
    main()
