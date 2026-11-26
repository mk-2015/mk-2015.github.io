import gzip
import hashlib
import html
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

out = Path("shelf/man")
out.mkdir(parents=True, exist_ok=True)
manifest_path = out / ".manifest.json"
secs = ["1", "2", "3", "4", "5", "6", "7", "8"]

old_manifest = {}
if manifest_path.exists():
  try:
    old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError):
    old_manifest = {}


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
  dest = d / fn
  key = f"{s}/{fn}"

  troff_bytes = read_man_bytes(mp)
  if not troff_bytes:
    return None

  digest = hashlib.sha256(troff_bytes).hexdigest()
  if old_manifest.get(key) == digest and dest.is_file():
    return (s, name, fn, key, digest, False)

  r = subprocess.run(
      ["groff", "-man", "-Tutf8", "-P-c", "-P-b", "-P-u"],
      input=troff_bytes,
      capture_output=True,
      cwd="/usr/share/man",
      check=False,
  )
  text = r.stdout.decode("utf-8", errors="replace")
  if r.returncode != 0 or not text.strip():
    return None

  dest.write_text(
      f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{html.escape(name)}({s})</title></head>'
      f'<body><p><a href="/">Home</a> | <a href="/shelf/man/{s}/">man({s})</a></p><hr>'
      f'<pre>{html.escape(text)}</pre></body></html>\n',
      encoding="utf-8",
  )
  return (s, name, fn, key, digest, True)


tasks = []
for s in secs:
  (out / s).mkdir(parents=True, exist_ok=True)
  p = Path(f"/usr/share/man/man{s}")
  if p.exists():
    tasks.extend((s, f) for f in sorted(p.iterdir()))

with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
  results = [x for x in ex.map(job, tasks) if x]

new_manifest = {key: digest for _, _, _, key, digest, _ in results}
built_count = sum(1 for _, _, _, _, _, rebuilt in results if rebuilt)
skipped_count = len(results) - built_count

# Remove stale HTML files for manpages that no longer exist
valid_keys = set(new_manifest.keys())
for s in secs:
  for existing in (out / s).glob("*.html"):
    if existing.name == "index.html":
      continue
    if f"{s}/{existing.name}" not in valid_keys:
      existing.unlink(missing_ok=True)

manifest_path.write_text(json.dumps(new_manifest), encoding="utf-8")

for s in secs:
  items = sorted(
      {(n, f) for sec, n, f, _, _, _ in results if sec == s},
      key=lambda x: x[0].lower(),
  )
  lis = "\n".join(
      f'<li><a href="{html.escape(f)}">{html.escape(n)}({s})</a></li>'
      for n, f in items
  )
  (out / s / "index.html").write_text(
      f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>man({s})</title></head>'
      f'<body><p><a href="/">Home</a> | <a href="/shelf/man/">All sections</a></p>'
      f'<h1>man({s})</h1><hr><ul>{lis}</ul></body></html>\n',
      encoding="utf-8",
  )

sec_lis = "\n".join(f'<li><a href="/shelf/man/{s}/">man({s})</a></li>' for s in secs)
all_entries = sorted(
    {(s, n, f) for s, n, f, _, _, _ in results},
    key=lambda x: (x[1].lower(), x[0]),
)
search_data = json.dumps([[s, n, f] for s, n, f in all_entries])

(out / "index.html").write_text(
    f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>man(1-8)</title></head>
<body>
<p><a href="/">Home</a> | <a href="/shelf/">Shelf</a></p>
<h1>Manual Pages</h1>
<hr>
<fieldset>
<legend>Quick Lookup</legend>
<label for="q">Name: </label>
<input id="q" type="text" placeholder="e.g. fork, open, ls" autocomplete="off">
<ul id="res"></ul>
</fieldset>
<hr>
<h2>Sections</h2>
<ul>{sec_lis}</ul>
<script>
const DB = {search_data};
const q = document.getElementById("q");
const res = document.getElementById("res");
q.addEventListener("input", () => {{
  const v = q.value.trim().toLowerCase();
  res.innerHTML = "";
  if (!v) return;
  let count = 0;
  for (const [s, n, f] of DB) {{
    if (n.toLowerCase().includes(v) || `${{n}}(${{s}})`.toLowerCase().includes(v)) {{
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = `/shelf/man/${{s}}/${{f}}`;
      a.textContent = `${{n}}(${{s}})`;
      li.appendChild(a);
      res.appendChild(li);
      if (++count >= 50) break;
    }}
  }}
}});
</script>
</body>
</html>
""",
    encoding="utf-8",
)
print(f"Built {built_count} pages, skipped {skipped_count} unchanged pages.")
