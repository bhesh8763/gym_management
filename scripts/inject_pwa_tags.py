"""Inject PWA tags into every frontend/*.html page.

Inserts, just before </head> (or before <body> on the few pages that never
close their head):

    - <link rel="manifest">            installability
    - <meta name="theme-color">        browser/OS chrome colour
    - apple-touch-icon + apple meta    iOS home-screen support
    - <script src="js/pwa.js" defer>   service-worker registration

The script is idempotent — pages that already carry the manifest link are
skipped — so it is safe to re-run after adding new pages.

    venv\\Scripts\\python.exe scripts/inject_pwa_tags.py     # Windows
    venv/bin/python scripts/inject_pwa_tags.py               # macOS/Linux
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

BLOCK = """  <!-- PWA: installable app + service-worker registration (scripts/inject_pwa_tags.py) -->
  <meta name="theme-color" content="#0f1015">
  <link rel="manifest" href="manifest.webmanifest">
  <link rel="apple-touch-icon" href="icons/apple-touch-icon.png">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black">
  <script src="js/pwa.js" defer></script>
"""


def inject(path: Path) -> str:
    # Read/write bytes so the file's existing line endings are preserved
    # exactly (read_text would silently normalise CRLF to LF).
    text = path.read_bytes().decode("utf-8")
    if 'rel="manifest"' in text:
        return "skip"

    match = re.search(r"[ \t]*</head>", text, flags=re.IGNORECASE)
    if match is None:
        # Some pages never close <head>; the browser implicitly closes it at
        # <body>, so inject immediately before <body> instead.
        match = re.search(r"[ \t]*<body", text, flags=re.IGNORECASE)
        if match is None:
            return "no-head"
    newline = "\r\n" if "\r\n" in text else "\n"
    block = newline.join(line.rstrip() for line in BLOCK.splitlines()) + newline
    start = match.start()
    new_text = text[:start] + block + text[start:]

    path.write_bytes(new_text.encode("utf-8"))
    return "ok"


def main() -> None:
    pages = sorted(FRONTEND.glob("*.html"))
    results = {"ok": 0, "skip": 0, "no-head": 0}
    for page in pages:
        results[inject(page)] += 1
    print(
        f"pages={len(pages)} injected={results['ok']} "
        f"already-done={results['skip']} missing-head={results['no-head']}"
    )


if __name__ == "__main__":
    main()
