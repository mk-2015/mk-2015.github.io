import gzip
import html
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

out = Path("shelf/man")
out.mkdir(parents=True, exist_ok=True)
secs = ["1", "2", "3", "4", "5", "6", "7", "8"]

def read_man_bytes(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    raw = path.read_bytes()
    if path.suffix == ".gz" or raw[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(raw)
        except OSError:
            return None
    return raw

def job(item):
    s, mp = item
    d = out / s
    stem = mp.name[:-3] if mp.name.endswith(".gz") else mp.name
    name = stem.rsplit(".", 1)[0]
    fn = name.replace("/", "_") + ".html"

    troff_bytes = read_man_bytes(mp)
    if not troff_bytes:
        return None

    r = subprocess.run(
        ["groff", "-man", "-Tutf8", "-P-c", "-P-b", "-P-u"],
        input=troff_bytes,
        capture_output=True,
        check=False,
    )
    text = r.stdout.decode("utf-8", errors="replace")
    if r.returncode != 0 or not text.strip():
        return None

    (d / fn).write_text(
        f"<!DOCTYPE html><html><head><meta charset=\"UTF-8\"><title>{html.escape(name)}({s})</title></head>"
        f"<body><p><a href=\"/\">Home</a> | <a href=\"/shelf/man/{s}/\">man({s})</a></p><hr>"
        f"<pre>{html.escape(text)}</pre></body></html>\n",
        encoding="utf-8",
    )
    return (s, name, fn)

tasks = []
for s in secs:
    (out / s).mkdir(parents=True, exist_ok=True)
    p = Path(f"/usr/share/man/man{s}")
    if p.exists():
        tasks.extend((s, f) for f in sorted(p.iterdir()))

with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
    rows = [x for x in ex.map(job, tasks) if x]

for s in secs:
    items = sorted({(n, f) for sec, n, f in rows if sec == s}, key=lambda x: x[0].lower())
    lis = "\n".join(f'<li><a href="{html.escape(f)}">{html.escape(n)}({s})</a></li>' for n, f in items)
    (out / s / "index.html").write_text(
        f"<!DOCTYPE html><html><head><meta charset=\"UTF-8\"><title>man({s})</title></head>"
        f"<body><h1>man({s})</h1><p><a href=\"/shelf/man/\">All sections</a></p><hr><ul>{lis}</ul></body></html>\n",
        encoding="utf-8",
    )

sec_lis = "\n".join(f'<li><a href="/shelf/man/{s}/">man({s})</a></li>' for s in secs)
(out / "index.html").write_text(
    f"<!DOCTYPE html><html><head><meta charset=\"UTF-8\"><title>man(1-8)</title></head>"
    f"<body><h1>Manual Pages</h1><hr><ul>{sec_lis}</ul></body></html>\n",
    encoding="utf-8",
)
print(f"Built {len(rows)} pages.")