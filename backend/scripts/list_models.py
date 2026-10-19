"""List Gemini models your key can use, so you can set the *_MODEL env vars correctly.

Usage: .venv/bin/python -m scripts.list_models [filter]
"""

import sys

from app.genai_client import client

needle = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
for m in client().models.list():
    name = m.name.removeprefix("models/")
    if needle in name.lower():
        actions = ",".join(getattr(m, "supported_actions", None) or [])
        print(f"{name:55s} {actions}")
