import re
from pathlib import Path
from datetime import datetime

INPUT_LOG = "trelleborg_2026_11_2_ImportInvoiceBT_486c362fe6554993a376f13474aa03f1_peuwe1ub18i77im_ImportInvoiceBT_20261102-130153-725_Trelleborg_Group_468126b6876a4f3093789afb1847385bX.log"

OUTPUT_DIR = "split_logs"

Path(OUTPUT_DIR).mkdir(exist_ok=True)

# początek nowego dokumentu
DOC_START = re.compile(
    r"Writing output type:\s*'btDocumentId', value:\s*'(\d+)'"
)

RE_DOC_ID = re.compile(
    r"Writing output type:\s*'btDocumentId', value:\s*'(\d+)'"
)

RE_INVOICE = re.compile(
    r"Loading variable 'InvoiceNumber' with value '([^']*)'"
)

RE_COMPANY = re.compile(
    r"Loading variable 'CompanyCode' with value '([^']*)'"
)

RE_TIMESTAMP = re.compile(
    r"(\d{2})\/(\d{2})\/(\d{4}) (\d{2}):(\d{2}):(\d{2})\."
)


def sanitize(value: str) -> str:
    value = value.strip()
    if not value:
        return "UNKNOWN"

    value = re.sub(r'[^A-Za-z0-9._-]', '_', value)
    return value


with open(INPUT_LOG, encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

documents = []
current = []

for line in lines:

    if DOC_START.search(line):
        if current:
            documents.append(current)
        current = [line]
    else:
        current.append(line)

if current:
    documents.append(current)

print(f"Found {len(documents)} document blocks")

for doc in documents:

    text = "".join(doc)

    doc_id = "UNKNOWN"
    invoice = "UNKNOWN"
    company = "UNKNOWN"
    import_date = "UNKNOWN"

    m = RE_DOC_ID.search(text)
    if m:
        doc_id = m.group(1)

    m = RE_INVOICE.search(text)
    if m and m.group(1).strip():
        invoice = sanitize(m.group(1))

    m = RE_COMPANY.search(text)
    if m and m.group(1).strip():
        company = sanitize(m.group(1))

    m = RE_TIMESTAMP.search(text)
    if m:
        day, month, year, hh, mm, ss = m.groups()

        import_date = (
            f"{year}{month}{day}_{hh}{mm}{ss}"
        )

    filename = (
        f"{sanitize(doc_id)}_"
        f"{company}_"
        f"{invoice}_"
        f"{import_date}.log"
    )

    outfile = Path(OUTPUT_DIR) / filename

    with open(outfile, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"Created: {filename}")

print("Done")