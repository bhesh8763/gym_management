"""Generate FitCore PWA icons from frontend/logo.png.

Run from the project root (uses the project venv, which has Pillow):

    venv\\Scripts\\python.exe scripts/generate_pwa_icons.py     # Windows
    venv/bin/python scripts/generate_pwa_icons.py               # macOS/Linux

Outputs into frontend/icons/:
    icon-192.png           PWA icon (any purpose)
    icon-512.png           PWA icon (any purpose)
    icon-maskable-512.png  Android adaptive icon (maskable safe zone)
    apple-touch-icon.png   iOS home-screen icon (180x180, no transparency)

The logo (brand red on transparent background) is composited centred onto the
dark surface colour used by the app theme (#0f1015) so it reads well on any
launcher background. Re-run this script whenever logo.png changes.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "frontend" / "logo.png"
OUT_DIR = ROOT / "frontend" / "icons"

# --bg-topbar / dark surface from frontend/css/theme.css
BG_COLOR = (15, 16, 21, 255)  # #0f1015

# (filename, pixel size, logo bounding ratio)
# The maskable icon keeps content inside the 80%-diameter safe circle.
ICONS = [
    ("icon-192.png", 192, 0.72),
    ("icon-512.png", 512, 0.72),
    ("icon-maskable-512.png", 512, 0.56),
    ("apple-touch-icon.png", 180, 0.70),
]


def build_icon(size: int, logo_ratio: float) -> Image.Image:
    """Composite the logo, scaled to `logo_ratio` of the canvas, on the BG."""
    canvas = Image.new("RGBA", (size, size), BG_COLOR)
    logo = Image.open(LOGO).convert("RGBA")

    target = int(size * logo_ratio)
    scale = min(target / logo.width, target / logo.height)
    new_size = (max(1, round(logo.width * scale)), max(1, round(logo.height * scale)))
    logo = logo.resize(new_size, Image.Resampling.LANCZOS)

    pos = ((size - logo.width) // 2, (size - logo.height) // 2)
    canvas.alpha_composite(logo, pos)
    return canvas


def main() -> None:
    if not LOGO.exists():
        raise SystemExit(f"Logo not found: {LOGO}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for filename, size, ratio in ICONS:
        icon = build_icon(size, ratio)
        # Flatten to RGB: PWA/home-screen icons never need their own alpha.
        out = OUT_DIR / filename
        icon.convert("RGB").save(out, "PNG", optimize=True)
        print(f"wrote {out.relative_to(ROOT)} ({size}x{size})")


if __name__ == "__main__":
    main()
