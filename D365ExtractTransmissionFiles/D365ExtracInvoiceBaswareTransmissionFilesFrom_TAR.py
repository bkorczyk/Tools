import argparse
import csv
import gzip
import io
import os
import re
import sys
import tarfile
import xml.etree.ElementTree as ET


def clean_filename(name: str) -> str:
    """Usuwa znaki niedozwolone w nazwach folderów/plików."""
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def get_tag_value(root: ET.Element, tag_names: list[str]) -> str | None:
    """Szuka wartości dla pierwszej dopasowanej nazwy tagu z listy tag_names (bez namespace)."""
    for elem in root.iter():
        clean_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if clean_tag in tag_names and elem.text:
            return elem.text.strip()
    return None


def extract_invoice_from_description(description: str | None) -> str | None:
    """Wyciąga numer faktury z opisu typu 'BW: 17360 Brait AB' lub 'BW:17360'."""
    if not description:
        return None
    match = re.search(r"BW:?\s*([^\s]+)", description, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def parse_invoices_parameter(invoice_param: str) -> set[str]:
    """Parsuje parametr z numerami faktur z CSV lub CLI."""
    if os.path.isfile(invoice_param):
        return load_invoices_from_csv(invoice_param)

    tokens = re.split(r"[,\s]+", invoice_param.strip())
    return {token.strip() for token in tokens if token.strip()}


def load_invoices_from_csv(csv_path: str) -> set[str]:
    """Wczytuje numery faktur z pliku CSV."""
    invoices = set()
    possible_headers = [
        "invoicenumber",
        "invoice",
        "numerfaktury",
        "invoice_no",
        "invoiceno",
    ]

    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        sample = f.read(2048)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t")

        reader = csv.reader(f, dialect)
        rows = list(reader)

        if not rows:
            return invoices

        first_row_lower = [col.strip().lower() for col in rows[0]]
        target_col_idx = None

        for idx, col_name in enumerate(first_row_lower):
            if col_name in possible_headers:
                target_col_idx = idx
                break

        start_row = 1 if target_col_idx is not None else 0
        if target_col_idx is None:
            target_col_idx = 0

        for row in rows[start_row:]:
            if len(row) > target_col_idx:
                val = row[target_col_idx].strip()
                if val:
                    invoices.add(val)

    return invoices


def scan_tar_object(
    tar: tarfile.TarFile,
    file_metadata: dict,
    ref_to_invoice_map: dict,
    invoice_to_ref_map: dict,
    found_extensions: set,
):
    """Przeszukuje podany obiekt TarFile (działa też rekurencyjnie dla włożonego pliku .tar)."""
    HEADER_REF_TAGS = [
        "HeaderReference",
        "InvoiceLineReference",
        "LineReference",
        "JournalBatchNumber",
    ]
    INVOICE_NUM_TAGS = ["InvoiceNumber"]
    DESCRIPTION_TAGS = ["Description"]

    while True:
        try:
            member = tar.next()
            if member is None:
                break
        except tarfile.ReadError:
            break

        if not member.isfile():
            continue

        lower_name = member.name.lower()

        # SPRAWDZENIE: Czy wewnątrz archiwum znajduje się zagnieżdżony plik .tar?
        if lower_name.endswith(".tar"):
            print(
                f" -> Wykryto zagnieżdżone archiwum TAR: {member.name}. Rozpakowywanie w pamięci RAM..."
            )
            extracted_tar_file = tar.extractfile(member)
            if extracted_tar_file:
                tar_bytes = io.BytesIO(extracted_tar_file.read())
                with tarfile.open(
                    fileobj=tar_bytes, mode="r:*", ignore_zeros=True
                ) as inner_tar:
                    scan_tar_object(
                        inner_tar,
                        file_metadata,
                        ref_to_invoice_map,
                        invoice_to_ref_map,
                        found_extensions,
                    )
            continue

        ext = os.path.splitext(lower_name)[1]
        found_extensions.add(ext)

        is_xml = lower_name.endswith(".xml")
        is_xml_gz = lower_name.endswith(".xml.gz") or lower_name.endswith(
            ".tgz"
        )

        if not (is_xml or is_xml_gz):
            continue

        try:
            extracted_file = tar.extractfile(member)
            if extracted_file is None:
                continue

            raw_bytes = extracted_file.read()

            if is_xml_gz:
                try:
                    content = gzip.decompress(raw_bytes)
                except Exception:
                    content = raw_bytes
            else:
                content = raw_bytes

            root = ET.fromstring(content)

            header_ref = get_tag_value(root, HEADER_REF_TAGS)
            invoice_num = get_tag_value(root, INVOICE_NUM_TAGS)
            description = get_tag_value(root, DESCRIPTION_TAGS)

            if not invoice_num:
                invoice_num = extract_invoice_from_description(description)

            clean_out_name = os.path.basename(member.name)
            if clean_out_name.lower().endswith(".gz"):
                clean_out_name = clean_out_name[:-3]

            file_metadata[member.name] = {
                "header_ref": header_ref,
                "invoice_num": invoice_num,
                "content": content,
                "out_filename": clean_out_name,
            }

            if header_ref and invoice_num:
                ref_to_invoice_map[header_ref] = invoice_num
                invoice_to_ref_map[invoice_num] = header_ref

        except (ET.ParseError, Exception):
            continue


def process_tar_archive(tar_path: str, invoice_param: str, output_dir: str):
    if not os.path.isfile(tar_path):
        print(f"Błąd: Plik archiwum '{tar_path}' nie istnieje.")
        return

    extract_all = invoice_param.strip() == "*"
    target_invoices = set()

    if extract_all:
        print(
            "Wybrano tryb Pełnej Ekstrakcji ('*') -> Zostaną wypakowane wszystkie faktury."
        )
    else:
        try:
            target_invoices = parse_invoices_parameter(invoice_param)
            if os.path.isfile(invoice_param):
                print(
                    f"Wczytano {len(target_invoices)} numerów faktur z pliku CSV: {invoice_param}"
                )
            else:
                print(
                    f"Wczytano {len(target_invoices)} numerów faktur z wiersza poleceń: {', '.join(sorted(target_invoices))}"
                )
        except Exception as e:
            print(f"Błąd podczas odczytu listy/pliku faktur: {e}")
            return

        if not target_invoices:
            print("Nie znaleziono żadnych numerów faktur do ekstrakcji.")
            return

    print(f"Otwieranie archiwum: {tar_path}\n")

    file_metadata = {}
    ref_to_invoice_map = {}
    invoice_to_ref_map = {}
    found_extensions = set()

    with tarfile.open(tar_path, "r:*", ignore_zeros=True) as tar:
        print("Faza 1/2: Skanowanie i indeksowanie zawartości archiwum XML...")
        scan_tar_object(
            tar,
            file_metadata,
            ref_to_invoice_map,
            invoice_to_ref_map,
            found_extensions,
        )

    if not file_metadata:
        print("\nOSTRZEŻENIE: Nie znaleziono żadnych plików XML w archiwum!")
        print(f"Wykryte rozszerzenia plików w archiwum: {found_extensions}")
        return

    print(
        "\nFaza 2/2: Uzupełnianie relacji i rozpakowywanie dopasowanych plików..."
    )
    extracted_count = 0
    skipped_count = 0

    for member_name, data in file_metadata.items():
        header_ref = data["header_ref"]
        invoice_num = data["invoice_num"]
        content = data["content"]
        out_filename = data["out_filename"]

        if not invoice_num and header_ref in ref_to_invoice_map:
            invoice_num = ref_to_invoice_map[header_ref]

        if not header_ref and invoice_num in invoice_to_ref_map:
            header_ref = invoice_to_ref_map[invoice_num]

        should_extract = extract_all or (
            invoice_num and invoice_num in target_invoices
        )

        if should_extract and (invoice_num or header_ref):
            if invoice_num and header_ref:
                folder_name = clean_filename(f"{invoice_num} - {header_ref}")
            elif invoice_num:
                folder_name = clean_filename(invoice_num)
            else:
                folder_name = clean_filename(header_ref)

            dest_folder = os.path.join(output_dir, folder_name)
            os.makedirs(dest_folder, exist_ok=True)

            out_path = os.path.join(dest_folder, out_filename)

            with open(out_path, "wb") as f_out:
                f_out.write(content)

            print(f"[EXTRACTED] {out_filename} -> {folder_name}/")
            extracted_count += 1
        else:
            skipped_count += 1

    print(f"\nPodsumowanie:")
    print(f" - Wyekstrahowano plików: {extracted_count}")
    print(f" - Pominięto plików XML: {skipped_count}")


if __name__ == "__main__":
    usage_examples = """
Przykłady użycia:
  Usage 1 (Lista faktur po przecinku):
    python3 .\\D365ExtracInvoiceBaswareTransmissionFilesFrom_TAR.py [tarfile] [invoice1, invoice2] -o [output directory]
    
  Usage 2 (Plik CSV z fakturami):
    python3 .\\D365ExtracInvoiceBaswareTransmissionFilesFrom_TAR.py [tarfile] invoicesToExtract.csv -o [output directory]
    
  Usage 3 (Wszystkie faktury):
    python3 .\\D365ExtracInvoiceBaswareTransmissionFilesFrom_TAR.py [tarfile] "*" -o [output directory]
"""

    parser = argparse.ArgumentParser(
        description="Przegląda archiwum TAR/TAR.GZ i wypakowuje pliki integracji D365.",
        epilog=usage_examples,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("tar_file", help="Ścieżka do pliku archiwum (.tar / .tar.gz)")
    parser.add_argument(
        "invoices", help="Plik CSV, lista po przecinku lub '*' dla wszystkich"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="./extracted_invoices",
        help="Katalog wyjściowy (domyślnie: ./extracted_invoices)",
    )

    # Wyświetl help jeśli uruchomiono bez parametrów
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    process_tar_archive(args.tar_file, args.invoices, args.output)