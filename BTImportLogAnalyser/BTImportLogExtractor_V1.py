import re
import base64
import zipfile
from pathlib import Path
from io import BytesIO

LOG_FILE = "1904567107_BUSAFR_2981170_20261111_060334.log"
OUTPUT_DIR = "extracted"

Path(OUTPUT_DIR).mkdir(exist_ok=True)

STREAM_PATTERN = re.compile(
    r"Writing output type:\s*'Stream', value:\s*'([^']+)'",
    re.DOTALL
)


def sanitize_filename(name):
    """
    Remove characters illegal in file names.
    """
    name = Path(name).name
    return re.sub(r'[<>:"/\\|?*]', "_", name)


def unique_path(path):
    """
    Ensure file won't be overwritten.
    """
    if not path.exists():
        return path

    counter = 1

    while True:

        candidate = (
            path.parent /
            f"{path.stem}_{counter}{path.suffix}"
        )

        if not candidate.exists():
            return candidate

        counter += 1


def detect_filetype(data):
    """
    Detect file type using magic bytes.
    """

    if data.startswith(b"%PDF"):
        return "pdf"

    if data.startswith(b"<?xml"):
        return "xml"

    if data.startswith(b"PK\x03\x04"):
        return "zip"

    if data.startswith(b"\x89PNG"):
        return "png"

    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"

    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"

    return "bin"


def find_name_near_stream(content, position):
    """
    Find sensible file name in log before stream.
    """

    lookback = 100000

    start = max(0, position - lookback)

    context = content[start:position]

    patterns = [

        r"(IMAGE-[A-Za-z0-9_.-]+\.(?:pdf|tif|tiff|png|jpg|jpeg))",

        r"(ATTACHMENT-[A-Za-z0-9_.-]+)",

        r"Loading variable 'rawFilename' with value '([^']+)'",

        r"Loading variable 'OriginalFileName' with value '([^']+)'",

        r"Loading variable 'FileName' with value '([^']+)'"
    ]

    for pattern in patterns:

        matches = list(
            re.finditer(pattern, context, re.IGNORECASE)
        )

        if matches:

            match = matches[-1]

            if match.groups():
                return sanitize_filename(match.group(1))
            else:
                return sanitize_filename(match.group(0))

    return None


def save_file(data, filename):

    target = unique_path(
        Path(OUTPUT_DIR) / filename
    )

    with open(target, "wb") as f:
        f.write(data)

    return target


def extract_zip(zip_path):

    extract_dir = zip_path.parent / zip_path.stem

    extract_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    try:

        with zipfile.ZipFile(zip_path, "r") as z:

            z.extractall(extract_dir)

            print(
                f"  Extracted ZIP -> {extract_dir}"
            )

            for member in z.namelist():
                print(
                    f"    {member}"
                )

    except Exception as e:

        print(
            f"  ZIP extract failed: {e}"
        )


def determine_filename(
        content,
        stream_position,
        filetype,
        index):

    base_name = find_name_near_stream(
        content,
        stream_position
    )

    if base_name:

        stem = Path(base_name).stem

        return f"{stem}.{filetype}"

    return f"stream_{index}.{filetype}"


with open(
    LOG_FILE,
    "r",
    encoding="utf-8",
    errors="ignore"
) as f:

    log_content = f.read()

streams = list(
    STREAM_PATTERN.finditer(log_content)
)

print(
    f"Found {len(streams)} stream(s)"
)

print()

for idx, stream_match in enumerate(streams, start=1):

    b64 = stream_match.group(1)

    b64 = "".join(b64.split())

    try:

        data = base64.b64decode(b64)

    except Exception as e:

        print(
            f"Stream {idx}: decode failed"
        )
        print(
            f"Reason: {e}"
        )
        continue

    filetype = detect_filetype(data)

    filename = determine_filename(
        log_content,
        stream_match.start(),
        filetype,
        idx
    )

    saved_file = save_file(
        data,
        filename
    )

    print(
        f"Stream {idx}"
    )
    print(
        f"  Type : {filetype.upper()}"
    )
    print(
        f"  Saved: {saved_file}"
    )

    #
    # Auto extract ZIP
    #

    if filetype == "zip":

        extract_zip(saved_file)

        #
        # Additionally inspect ZIP contents
        #

        try:

            with zipfile.ZipFile(
                BytesIO(data),
                "r"
            ) as z:

                xml_files = [
                    x for x in z.namelist()
                    if x.lower().endswith(".xml")
                ]

                if xml_files:

                    print(
                        f"  XML files inside ZIP:"
                    )

                    for xml_file in xml_files:

                        print(
                            f"    {xml_file}"
                        )

        except Exception:
            pass

    print()

print("Finished.")
