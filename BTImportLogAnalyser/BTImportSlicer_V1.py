import re
import csv
from pathlib import Path

INPUT_LOG = "trelleborg_2026_11_11_ImportInvoiceBT_e60e28f92cc746b29bc0ecb517b645e1_peuwe1ub18i36zu_ImportInvoiceBT_20261111-060146-855_Trelleborg_Group_437215c658024170890dded6b1674e1cX.log"
OUTPUT_DIR = "split_logs"

Path(OUTPUT_DIR).mkdir(exist_ok=True)

# --------------------------------------------------
# Helpers
# --------------------------------------------------

def sanitize(value: str) -> str:
    if value is None:
        return "UNKNOWN"

    value = value.strip()

    if not value:
        return "UNKNOWN"

    value = re.sub(r'[<>:"/\\|?*]', "_", value)
    value = re.sub(r'\s+', "_", value)

    return value


def get_last_nonempty(pattern: str, text: str, default="UNKNOWN"):

    matches = re.findall(pattern, text)

    for value in reversed(matches):
        value = value.strip()

        if value:
            return sanitize(value)

    return default


# --------------------------------------------------
# Patterns
# --------------------------------------------------

re_doc_start = re.compile(
    r"Writing output type:\s*'btDocumentId', value:\s*'(\d+)'"
)

re_timestamp = re.compile(
    r"(\d{2})\/(\d{2})\/(\d{4}) (\d{2}):(\d{2}):(\d{2})"
)

# --------------------------------------------------
# Read file
# --------------------------------------------------

with open(INPUT_LOG, "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

# --------------------------------------------------
# Split to document blocks
# --------------------------------------------------

blocks = []
current_block = []

for line in lines:

    if re_doc_start.search(line):

        if current_block:
            blocks.append(current_block)

        current_block = [line]

    else:
        current_block.append(line)

if current_block:
    blocks.append(current_block)

print(f"Found {len(blocks)} document blocks")

# --------------------------------------------------
# Process blocks
# --------------------------------------------------

index_rows = []

for block in blocks:

    text = "".join(block)

    bt_document_id = get_last_nonempty(
        r"Writing output type:\s*'btDocumentId', value:\s*'([^']*)'",
        text
    )

    invoice_number = get_last_nonempty(
        r"Loading variable 'InvoiceNumber' with value '([^']*)'",
        text
    )

    company_code = get_last_nonempty(
        r"Loading variable 'CompanyCode' with value '([^']*)'",
        text
    )

    # first timestamp from block
    import_date = "UNKNOWN"

    m = re_timestamp.search(text)

    if m:
        dd, mm, yyyy, hh, mi, ss = m.groups()

        import_date = (
            f"{yyyy}{mm}{dd}_{hh}{mi}{ss}"
        )

    filename = (
        f"{bt_document_id}_"
        f"{company_code}_"
        f"{invoice_number}_"
        f"{import_date}.log"
    )

    filepath = Path(OUTPUT_DIR) / filename

    with open(filepath, "w", encoding="utf-8") as out:
        out.write(text)

    index_rows.append({
        "btDocumentId": bt_document_id,
        "CompanyCode": company_code,
        "InvoiceNumber": invoice_number,
        "ImportDate": import_date,
        "FileName": filename
    })

    print(f"Created: {filename}")

# --------------------------------------------------
# Create index.csv
# --------------------------------------------------

index_file = Path(OUTPUT_DIR) / "index.csv"

with open(index_file, "w", newline="", encoding="utf-8") as csvfile:

    writer = csv.DictWriter(
        csvfile,
        fieldnames=[
            "btDocumentId",
            "CompanyCode",
            "InvoiceNumber",
            "ImportDate",
            "FileName"
        ]
    )

    writer.writeheader()

    for row in index_rows:
        writer.writerow(row)

print()
print(f"Created index: {index_file}")
print("Done.")