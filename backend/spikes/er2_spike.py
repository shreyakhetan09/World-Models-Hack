"""P0-A: does ER 2 return sensible decisions for disaster frames, and how fast?

Usage:
  .venv/bin/python -m spikes.er2_spike                 # uses static/scenarios/*.jpg (run make_assets images first)
  .venv/bin/python -m spikes.er2_spike img1.jpg img2.png
Writes annotated images + a results table to spikes/out_er2/.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from app.er2 import decide_sync, run_streaming

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "out_er2"


def to_jpeg(path: Path) -> bytes:
    img = Image.open(path).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def annotate(jpeg: bytes, d, out: Path) -> None:
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    W, H = img.size
    draw = ImageDraw.Draw(img)
    for s in d.survivors:
        y, x = s.point[0] * H / 1000, s.point[1] * W / 1000
        draw.ellipse([x - 14, y - 14, x + 14, y + 14], outline="lime", width=4)
        draw.text((x + 16, y - 8), s.label, fill="lime")
    for h in d.hazards:
        y, x = h.point[0] * H / 1000, h.point[1] * W / 1000
        color = "red" if h.severity == 3 else "orange"
        draw.polygon([(x, y - 14), (x + 12, y + 10), (x - 12, y + 10)], outline=color, width=3)
        draw.text((x + 14, y - 8), f"{h.label} ({h.severity})", fill=color)
    draw.rectangle([0, H - 28, W, H], fill="black")
    draw.text((8, H - 22), f"{d.action.move}/{d.action.look} {d.action.duration_ms}ms: {d.reason}", fill="white")
    img.save(out)


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]] or sorted((ROOT / "static" / "scenarios").glob("*.*"))
    if not paths:
        raise SystemExit("No images. Run: .venv/bin/python -m scripts.make_assets images")
    OUT.mkdir(exist_ok=True)
    rows = ["| image | standard ms | streaming ms | action | reason | hazards | survivors |", "|---|---|---|---|---|---|---|"]
    for p in paths:
        jpeg = to_jpeg(p)
        d, ms = decide_sync(jpeg)
        annotate(jpeg, d, OUT / f"{p.stem}_annotated.jpg")
        try:
            ds, ms_s, raw = run_streaming(jpeg)
            stream_cell = f"{ms_s:.0f}" + ("" if ds else " (unparsed)")
        except Exception as e:  # endpoint may not accept this usage; record and move on
            stream_cell = f"error: {type(e).__name__}: {str(e)[:80]}"
        rows.append(f"| {p.name} | {ms:.0f} | {stream_cell} | {d.action.move}/{d.action.look} | {d.reason} | "
                    f"{len(d.hazards)} | {len(d.survivors)} |")
        print(rows[-1])
    (OUT / "RESULTS.md").write_text("\n".join(rows) + "\n")
    print(f"\nAnnotated images + RESULTS.md in {OUT}")


if __name__ == "__main__":
    main()
