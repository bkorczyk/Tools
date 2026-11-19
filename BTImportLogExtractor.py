logExtractor.py
import re
import base64
from pathlib import Path

LOG_FILE = "bt.log"
OUTPUT_DIR = "extracted"

Path(OUTPUT_DIR).mkdir(exist_ok=True)

pattern = re.compile(
    r"Writing output type:\s*'Stream', value:\s*'([^']+)'",
    re.DOTALL
)

with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

matches = pattern.findall(content)

print(f"Found {len(matches)} stream(s)")

for idx, b64 in enumerate(matches, start=1):

    b64 = ''.join(b64.split())

    try:
        data = base64.b64decode(b64)
    except Exception as e:
        print(f"Stream {idx}: decode failed ({e})")
        continue

    extension = "bin"

    if data.startswith(b"%PDF"):
        extension = "pdf"

    elif data.startswith(b"<?xml"):
        extension = "xml"

    elif data.startswith(b"PK\x03\x04"):
        extension = "zip"

    elif data.startswith(b"\x89PNG"):
        extension = "png"

    elif data.startswith(b"\xff\xd8\xff"):
        extension = "jpg"

    elif data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        extension = "gif"

    filename = Path(OUTPUT_DIR) / f"stream_{idx}.{extension}"

    with open(filename, "wb") as out:
        out.write(data)

    print(f"Saved: {filename}")