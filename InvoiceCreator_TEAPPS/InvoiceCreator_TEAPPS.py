import sys
import os
import io
import csv
import re
import ftplib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string, request, Response
from dotenv import load_dotenv

# Wczytanie zmiennych środowiskowych z pliku .env
load_dotenv()

app = Flask(__name__)

MAPPING_FILE = "mapping.csv"
LOADED_ORDERS = {}  # Przechowuje wczytane zamówienia {safe_order_id: order_data}

# Konfiguracja FTP z pliku .env
FTP_HOST = os.getenv("FTP_HOST", "ftp.example.com")
FTP_USER = os.getenv("FTP_USER", "user")
FTP_PASS = os.getenv("FTP_PASS", "pass")
FTP_PORT = int(os.getenv("FTP_PORT", 21))
FTP_DIR = os.getenv("FTP_DIR", "/")

def load_mapping_config():
    """Wczytuje reguły mapowania z pliku CSV."""
    rules = []
    if not os.path.exists(MAPPING_FILE):
        create_default_mapping_csv()
        
    with open(MAPPING_FILE, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rules.append(row)
    return rules

def create_default_mapping_csv():
    """Tworzy domyślny plik mapping.csv jeśli nie istnieje."""
    content = """TargetSection,TargetTag,RuleType,SourceXPath,DefaultValue,Description
HEADER,INVOICE_ID,USER_INPUT,,9606251248,Numer faktury
HEADER,INVOICE_TYPE,USER_INPUT,,00,Typ dokumentu
HEADER,INVOICE_DATE,CALCULATED,,INVOICE_DATE,Data faktury
HEADER,DUE_DATE,CALCULATED,,DUE_DATE,Termin platnosci
HEADER,DELIVERY_DATE,CALCULATED,,DELIVERY_DATE,Data dostawy
HEADER,CURRENCY/CODE,USER_INPUT,,EUR,Kod waluty
HEADER,ORDER_INFORMATION/ORDER_NUMBER,USER_INPUT,,4500297257,Numer PO
HEADER,FREE_TEXT[Trelleborg_VAT_number],USER_INPUT,,DE119553041,NIP Trelleborg
HEADER,FREE_TEXT[Reference_person],USER_INPUT,,,Osoba referencyjna
PAYEE,CUSTOMER_INFORMATION/CUSTOMER_NAME,USER_INPUT,,SKF GmbH,Nazwa dostawcy
PAYEE,CUSTOMER_INFORMATION/CUSTOMER_ID,USER_INPUT,,1025025,Kod dostawcy
PAYEE,CUSTOMER_INFORMATION/VAT_NUMBER,USER_INPUT,,DE133898319,NIP Dostawcy
RECEIVER,CUSTOMER_INFORMATION/CUSTOMER_NAME,USER_INPUT,,Trelleborg Sealing Solutions Germany GmbH,Nazwa organizacji
RECEIVER,CUSTOMER_INFORMATION/CUSTOMER_ID,USER_INPUT,,DE119553041,ID Odbiorcy
RECEIVER,CUSTOMER_INFORMATION/PARTY_IDENTIFICATION_ID,USER_INPUT,,DE119553041,Party ID Odbiorcy
RECEIVER,CUSTOMER_INFORMATION/LANGUAGE_CODE,USER_INPUT,,EN,Jezyk
RECEIVER,NET_SERVICE_ID,USER_INPUT,,DE119553041,Net Service ID
ROW,ARTICLE/ARTICLE_CODE,XPATH,Text2,,Kod produktu z GR (Text2)
ROW,NOTE_NUMBER,XPATH,DeliveryNoteNumber,,Numer dowodu dostawy (DeliveryNoteNumber)
ROW,ORDER_INFORMATION/ORDER_POSITION,XPATH,OrderRowNumber,,Pozycja w zamowieniu
ROW,ORDER_INFORMATION/ORDER_NUMBER,XPATH,OrderNumber,,Numer zamowienia w pozycji
ROW,ORDER_NUMBER,XPATH,OrderNumber,,Numer zamowienia w linii
ROW,QUANTITY/CHARGED,CALCULATED,,GR_QTY,Ilosc z GR / Formularza
ROW,PRICE_PER_UNIT/AMOUNT[EXCLUDED],CALCULATED,,GR_PRICE,Cena jednostkowa z GR / Formularza
ROW,ROW_TOTAL/AMOUNT[EXCLUDED],CALCULATED,,GR_NET_SUM,Suma netto linii z GR / Formularza
SUMMARY,INVOICE_TOTAL/AMOUNT[EXCLUDED],CALCULATED,,HEADER_NET,Suma netto
SUMMARY,INVOICE_TOTAL/AMOUNT[INCLUDED],CALCULATED,,HEADER_GROSS,Suma brutto
SUMMARY,VAT_TOTAL/AMOUNT,CALCULATED,,HEADER_VAT,Suma VAT"""
    with open(MAPPING_FILE, "w", encoding="utf-8") as f:
        f.write(content)

def get_clean_val(node, tag, default=""):
    if node is None:
        return default
    child = node.find(tag)
    return child.text.strip() if child is not None and child.text else default

def safe_float(val, default=0.0):
    try:
        return float(str(val).replace(',', '.'))
    except (ValueError, TypeError):
        return default

def parse_order_xml(xml_content, filename):
    """Parsuje strukturę pliku XML zamówienia."""
    root = ET.fromstring(xml_content)
    order_node = root.find(".//Order")
    if order_node is None:
        order_node = root

    order_number = get_clean_val(order_node, "OrderNumber")
    supplier_code = get_clean_val(order_node, "InvoicingSupplierCode")
    supplier_name = get_clean_val(order_node, "InvoicingSupplierName", default="SKF GmbH")
    company_code = get_clean_val(order_node, "CompanyCode", default="")
    
    product_code = get_clean_val(order_node, "Text4", default="")
    payment_term = get_clean_val(order_node, "Text1", default="")
    buyer_name = get_clean_val(order_node, "BuyerName", default="")
    currency_code = get_clean_val(order_node, "CurrencyCode", default="EUR")

    raw_id = f"{order_number}_{filename}"
    safe_order_id = re.sub(r'[^a-zA-Z0-9_]', '_', raw_id)

    order_data = {
        "id": safe_order_id,
        "filename": filename,
        "raw_root": root,
        "order_number": order_number,
        "currency": currency_code,
        "supplier_code": supplier_code,
        "supplier_name": supplier_name,
        "company_code": company_code,
        "buyer_name": buyer_name,
        "rows": [],
        "gr_nodes": {}
    }

    order_rows = order_node.findall(".//OrderRow")
    for row_node in order_rows:
        row_pos = get_clean_val(row_node, "RowIndex", "10")
        product_name = get_clean_val(row_node, "ProductName", "Pozycja zamówienia")
        row_qty = safe_float(get_clean_val(row_node, "Quantity", "0"))
        row_price = safe_float(get_clean_val(row_node, "NetPrice", "0"))
        row_net = safe_float(get_clean_val(row_node, "NetSum", "0"))

        goods_receipts = []
        gr_nodes = row_node.findall(".//GoodsReceipt")
        
        for gr in gr_nodes:
            gr_num = get_clean_val(gr, "GoodsReceiptNumber")
            gr_row_num = get_clean_val(gr, "GoodsReceiptRowNumber")
            gr_id = f"{safe_order_id}_{row_pos}_{gr_num}_{gr_row_num}"
            
            order_data["gr_nodes"][gr_id] = gr

            gr_data = {
                "id": gr_id,
                "gr_number": gr_num,
                "gr_row_number": gr_row_num,
                "delivery_note": get_clean_val(gr, "DeliveryNoteNumber", "-"),
                "quantity": safe_float(get_clean_val(gr, "Quantity", str(row_qty))),
                "net_price": safe_float(get_clean_val(gr, "NetPrice", str(row_price))),
                "net_sum": safe_float(get_clean_val(gr, "NetSum", str(row_net))),
                "delivery_date": get_clean_val(gr, "DeliveryDate"),
                "order_pos": row_pos,
                "product_name": product_name
            }
            goods_receipts.append(gr_data)

        if not goods_receipts:
            direct_id = f"{safe_order_id}_{row_pos}_DIRECT"
            order_data["gr_nodes"][direct_id] = row_node
            goods_receipts.append({
                "id": direct_id,
                "gr_number": "BEZPOŚREDNIA LINIA",
                "gr_row_number": "1",
                "delivery_note": "-",
                "quantity": row_qty,
                "net_price": row_price,
                "net_sum": row_net,
                "delivery_date": "",
                "order_pos": row_pos,
                "product_name": product_name
            })

        order_data["rows"].append({
            "order_pos": row_pos,
            "product_name": product_name,
            "quantity": row_qty,
            "net_price": row_price,
            "net_sum": row_net,
            "goods_receipts": goods_receipts
        })

    return order_data

@app.route('/api/upload', methods=['POST'])
def upload_order():
    if 'file' not in request.files:
        return jsonify({"error": "Brak pliku w żądaniu"}), 400
    file = request.files['file']
    try:
        content = file.read().decode('utf-8', errors='ignore')
        order_data = parse_order_xml(content, file.filename)
        LOADED_ORDERS[order_data['id']] = order_data
        return get_orders_response()
    except Exception as e:
        return jsonify({"error": f"Błąd przetwarzania pliku: {str(e)}"}), 500

@app.route('/api/delete-order/<order_id>', methods=['DELETE'])
def delete_order(order_id):
    if order_id in LOADED_ORDERS:
        del LOADED_ORDERS[order_id]
    return get_orders_response()

def get_orders_response():
    res = []
    for o_id, order in LOADED_ORDERS.items():
        res.append({k: v for k, v in order.items() if k not in ['raw_root', 'gr_nodes']})
    return jsonify(res)

def set_nested_element(parent, path, value):
    parts = path.split('/')
    current = parent
    
    for idx, part in enumerate(parts):
        attr_key, attr_val = None, None
        clean_part = part
        
        if '[' in part and ']' in part:
            clean_part = part.split('[')[0]
            attr_val = part.split('[')[1].replace(']', '')
            if clean_part == 'FREE_TEXT':
                attr_key = 'TEXT_TYPE'
            elif clean_part == 'AMOUNT':
                attr_key = 'VAT'

        child = current.find(clean_part)
        if child is None or idx == len(parts) - 1:
            child = ET.SubElement(current, clean_part)
            if attr_key and attr_val:
                child.set(attr_key, attr_val)
                if clean_part == 'AMOUNT':
                    child.set('SIGN', '+')

        current = child

    current.text = str(value) if value is not None else ""
    return current

def append_date_node(parent, tag_name, date_str):
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        target_date = datetime.now()

    date_el = ET.SubElement(parent, tag_name)
    d_node = ET.SubElement(date_el, "DATE")
    ET.SubElement(d_node, "DAY").text = target_date.strftime("%d")
    ET.SubElement(d_node, "MONTH").text = target_date.strftime("%m")
    ET.SubElement(d_node, "CENTURY").text = target_date.strftime("%Y")[:2]
    ET.SubElement(d_node, "DECADE_AND_YEAR").text = target_date.strftime("%Y")[2:]

def build_xml_tree(data):
    """Buduje pełne drzewo XML faktury TEAPPS 3.0."""
    mapping_rules = load_mapping_config()
    is_debit = (data.get("invoice_type") == "Debit Invoice")
    now_ts = datetime.now().strftime("%Y%m%d%H%M%S000")

    root = ET.Element("INVOICE_CENTER")
    
    tf = ET.SubElement(root, "TRANSPORT_FRAME")
    ET.SubElement(tf, "TF_CODE").text = "TF01"
    ET.SubElement(tf, "TIMESTAMP").text = now_ts
    ET.SubElement(tf, "BATCH_ID").text = "1858619938"
    
    cf = ET.SubElement(root, "CONTENT_FRAME")
    ET.SubElement(cf, "CF_CODE").text = "CF01"
    
    block_rules = ET.SubElement(cf, "BLOCK_RULES")
    ET.SubElement(block_rules, "TRANSACTION_TYPE").text = "00"
    ET.SubElement(block_rules, "BLOCK_ACTION").text = "00"
    ET.SubElement(block_rules, "BLOCK_FORMAT").text = "TEAPPSXML"
    ET.SubElement(block_rules, "FORMAT_VERSION").text = "3.0"

    invoices = ET.SubElement(cf, "INVOICES")
    invoice = ET.SubElement(invoices, "INVOICE")

    sections = {
        "HEADER": ET.SubElement(invoice, "HEADER"),
        "PAYEE": ET.SubElement(invoice, "PAYEE"),
        "RECEIVER": ET.SubElement(invoice, "RECEIVER"),
        "SUMMARY": ET.SubElement(invoice, "SUMMARY")
    }

    order_num = "" if is_debit else data.get("order_number")

    form_map = {
        "INVOICE_ID": data.get("invoice_id"),
        "INVOICE_TYPE": "00",
        "CURRENCY/CODE": data.get("currency"),
        "ORDER_INFORMATION/ORDER_NUMBER": order_num,
        "FREE_TEXT[Trelleborg_VAT_number]": data.get("trelleborg_vat"),
        "FREE_TEXT[Reference_person]": data.get("reference_person"),
        "PAYEE/CUSTOMER_INFORMATION/CUSTOMER_NAME": data.get("supplier_name"),
        "PAYEE/CUSTOMER_INFORMATION/CUSTOMER_ID": data.get("supplier_code"),
        "PAYEE/CUSTOMER_INFORMATION/VAT_NUMBER": data.get("supplier_vat"),
        "RECEIVER/CUSTOMER_INFORMATION/CUSTOMER_NAME": data.get("organization"),
        "RECEIVER/CUSTOMER_INFORMATION/CUSTOMER_ID": data.get("trelleborg_vat"),
        "RECEIVER/CUSTOMER_INFORMATION/PARTY_IDENTIFICATION_ID": data.get("trelleborg_vat"),
        "RECEIVER/CUSTOMER_INFORMATION/LANGUAGE_CODE": data.get("language"),
        "RECEIVER/NET_SERVICE_ID": data.get("trelleborg_vat"),
    }

    first_order = list(LOADED_ORDERS.values())[0] if LOADED_ORDERS else None

    for rule in mapping_rules:
        target_sec_name = rule.get("TargetSection")
        if target_sec_name == "ROW":
            continue

        target_tag = rule.get("TargetTag")
        rule_type = rule.get("RuleType")
        source_xpath = rule.get("SourceXPath")
        default_val = rule.get("DefaultValue")

        if target_sec_name not in sections:
            continue

        section_element = sections[target_sec_name]
        value = ""

        if rule_type == "CONSTANT":
            value = default_val
        elif rule_type == "USER_INPUT":
            full_key = f"{target_sec_name}/{target_tag}" if target_sec_name != "HEADER" else target_tag
            value = form_map.get(full_key, form_map.get(target_tag, default_val))
        elif rule_type == "XPATH" and first_order and "raw_root" in first_order:
            node = first_order["raw_root"].find(source_xpath)
            value = node.text if node is not None and node.text else default_val
        elif rule_type == "CALCULATED":
            if default_val == "INVOICE_DATE":
                append_date_node(section_element, target_tag, data.get("invoice_date"))
                continue
            elif default_val == "DUE_DATE":
                append_date_node(section_element, target_tag, data.get("due_date"))
                continue
            elif default_val == "DELIVERY_DATE":
                append_date_node(section_element, target_tag, data.get("delivery_date"))
                continue
            elif default_val == "HEADER_NET":
                value = data.get("header_net", "0.0")
            elif default_val == "HEADER_GROSS":
                value = data.get("header_gross", "0.0")
            elif default_val == "HEADER_VAT":
                value = data.get("header_vat", "0.0")

        set_nested_element(section_element, target_tag, value)

    if not is_debit and data.get("rows"):
        rows_node = ET.SubElement(invoice, "ROWS")
        row_rules = [r for r in mapping_rules if r.get("TargetSection") == "ROW"]

        for idx, row_item in enumerate(data.get("rows", []), 1):
            row_el = ET.SubElement(rows_node, "ROW")
            ET.SubElement(row_el, "ROW_NUMBER").text = str(idx)

            gr_id = row_item.get("id")
            
            gr_xml_node = None
            for order in LOADED_ORDERS.values():
                if gr_id in order["gr_nodes"]:
                    gr_xml_node = order["gr_nodes"][gr_id]
                    break

            for rule in row_rules:
                target_tag = rule.get("TargetTag")
                rule_type = rule.get("RuleType")
                source_xpath = rule.get("SourceXPath")
                default_val = rule.get("DefaultValue")

                val = ""
                if rule_type == "CONSTANT":
                    val = default_val
                elif rule_type == "XPATH" and gr_xml_node is not None:
                    found_node = gr_xml_node.find(source_xpath)
                    val = found_node.text if found_node is not None and found_node.text else default_val
                elif rule_type == "CALCULATED":
                    if default_val == "GR_QTY":
                        val = str(row_item.get("quantity", "1.0"))
                    elif default_val == "GR_PRICE":
                        val = str(row_item.get("net_price", "0.0"))
                    elif default_val == "GR_NET_SUM":
                        val = str(row_item.get("net_sum", "0.0"))

                set_nested_element(row_el, target_tag, val)

            vat_el = ET.SubElement(row_el, "VAT")
            ET.SubElement(vat_el, "RATE").text = "0"
            vat_amt = ET.SubElement(vat_el, "VAT_AMOUNT")
            ET.SubElement(vat_amt, "AMOUNT", VAT="EXCLUDED", SIGN="+").text = "0.0"

    return root

@app.route('/api/generate-xml', methods=['POST'])
def generate_xml():
    """Generowanie pliku XML do pobrania."""
    data = request.json
    root = build_xml_tree(data)
    xml_str = ET.tostring(root, encoding='utf-8')
    return Response(xml_str, mimetype='text/xml', headers={"Content-disposition": f"attachment; filename=Invoice_{data.get('invoice_id')}.xml"})

@app.route('/api/send-to-basware', methods=['POST'])
def send_to_basware():
    """Generowanie pliku XML i bezpośrednia wysyłka na serwer FTP Basware."""
    data = request.json
    try:
        root = build_xml_tree(data)
        xml_str = ET.tostring(root, encoding='utf-8')
        filename = f"Invoice_{data.get('invoice_id')}.xml"

        with ftplib.FTP() as ftp:
            ftp.connect(FTP_HOST, FTP_PORT, timeout=10)
            ftp.login(FTP_USER, FTP_PASS)
            
            if FTP_DIR and FTP_DIR != "/":
                ftp.cwd(FTP_DIR)

            with io.BytesIO(xml_str) as file_stream:
                ftp.storbinary(f"STOR {filename}", file_stream)

        return jsonify({"success": True, "message": f"Plik {filename} został pomyślnie wysłany do Basware!"})

    except Exception as e:
        return jsonify({"success": False, "error": f"Błąd wysyłki FTP: {str(e)}"}), 500

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <title>Generowanie Faktury TEAPPS 3.0</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; background: #f4f6f9; margin: 0; padding: 20px; color: #333; }
    .container { max-width: 1250px; margin: 0 auto; background: white; padding: 25px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
    h1 { color: #1a2b4c; margin-top: 0; font-size: 20px; border-bottom: 2px solid #007bff; padding-bottom: 8px; }
    
    .drop-zone { border: 2px dashed #007bff; padding: 20px; text-align: center; border-radius: 6px; background: #fafafa; cursor: pointer; margin-bottom: 15px; }
    .drop-zone:hover { background: #e9ecef; }
    
    table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }
    th, td { border: 1px solid #dee2e6; padding: 8px 10px; text-align: left; }
    th { background-color: #e9ecef; }
    .gr-row { background-color: #f8f9fa; }
    .gr-row td:first-child { padding-left: 25px; }

    .header-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; background: #f8f9fa; border: 1px solid #e2e8f0; border-radius: 6px; padding: 15px; margin: 15px 0; }
    .form-group { display: flex; flex-direction: column; }
    .form-group label { font-size: 11px; font-weight: bold; color: #4a5568; margin-bottom: 4px; text-transform: uppercase; }
    .form-group input, .form-group select { padding: 6px 8px; font-size: 13px; border: 1px solid #cbd5e1; border-radius: 4px; background: #fff; }
    .form-group input[readonly] { background: #edf2f7; color: #4a5568; }

    .warning-box { background: #fff3cd; border: 1px solid #ffeeba; color: #856404; padding: 10px 15px; border-radius: 4px; margin-bottom: 15px; display: none; }
 
    .actions-bar { display: flex; gap: 15px; margin-top: 20px; }
    .btn { background: #28a745; color: white; border: none; padding: 10px 20px; border-radius: 4px; font-size: 14px; cursor: pointer; font-weight: bold; }
    .btn:hover { background: #218838; }
    .btn-ftp { background: #007bff; }
    .btn-ftp:hover { background: #0056b3; }
    .btn:disabled { background: #6c757d; cursor: not-allowed; }

    .btn-danger { background: #dc3545; color: white; border: none; padding: 4px 10px; font-size: 12px; border-radius: 4px; cursor: pointer; }
    .btn-danger:hover { background: #c82333; }

    .order-card { border: 1px solid #cbd5e1; border-radius: 6px; margin-bottom: 15px; background: #fff; overflow: hidden; }
    .order-card-header { background: #e2e8f0; padding: 10px 15px; display: flex; justify-content: space-between; align-items: center; font-weight: bold; font-size: 13px; }
    .order-card-body { padding: 10px; }
  </style>
</head>
<body>

<div class="container">
  <h1>Generowanie Faktury TEAPPS 3.0</h1>

  <!-- FORMULARZ NAGŁÓWKA -->
  <h3>Formularz Nagłówka Faktury (Header Data):</h3>
  <div class="header-grid">
    <div class="form-group">
      <label>Organization</label>
      <input type="text" id="hdr-organization" value="Trelleborg Sealing Solutions Germany GmbH">
    </div>
    <div class="form-group">
      <label>Supplier Code *</label>
      <input type="text" id="hdr-supplier-code" value="">
    </div>
    <div class="form-group">
      <label>Supplier Name</label>
      <input type="text" id="hdr-supplier-name" value="">
    </div>
    <div class="form-group">
      <label>Supplier VAT number</label>
      <input type="text" id="hdr-supplier-vat" value="">
    </div>

    <div class="form-group">
      <label>Invoice Type</label>
      <select id="hdr-invoice-type" onchange="handleInvoiceTypeChange()">
        <option value="Debit Invoice" selected>Debit Invoice</option>
        <option value="Purchase Order Invoice">Purchase Order Invoice</option>
      </select>
    </div>
    <div class="form-group">
      <label>Vendor Type</label>
      <input type="text" id="hdr-vendor-type" value="External" readonly>
    </div>
    <div class="form-group">
      <label>Delivery Date *</label>
      <input type="date" id="hdr-delivery-date">
    </div>
    <div class="form-group">
      <label>Invoice Due Date</label>
      <input type="date" id="hdr-due-date">
    </div>

    <div class="form-group">
      <label>Creation Time</label>
      <input type="date" id="hdr-creation-time" readonly>
    </div>
    <div class="form-group">
      <label>Reference Person</label>
      <input type="text" id="hdr-reference-person" placeholder="">
    </div>
    <div class="form-group">
      <label>Currency Code *</label>
      <input type="text" id="hdr-currency" value="">
    </div>
    <div class="form-group">
      <label>Purchase Order Numbers</label>
      <input type="text" id="hdr-order-number" disabled>
    </div>

    <div class="form-group">
      <label>Invoice Number *</label>
      <input type="text" id="hdr-invoice-id" value="9606251248">
    </div>
    <div class="form-group">
      <label>Invoice Date *</label>
      <input type="date" id="hdr-invoice-date">
    </div>
    <div class="form-group">
      <label>Trelleborg VAT Number</label>
      <input type="text" id="hdr-trelleborg-vat" value="DE119553041">
    </div>
    <div class="form-group" id="group-calc-net" style="display:none;">
      <label>Suma Netto z wyselekcjonowanych GR</label>
      <input type="text" id="calc-net" value="0.00" readonly style="background:#e2e8f0; font-weight:bold;">
    </div>

    <div class="form-group">
      <label>Gross total *</label>
      <input type="number" step="0.01" id="hdr-gross" value="662.73" oninput="recalculateTotals()">
    </div>
    <div class="form-group">
      <label>Tax sum *</label>
      <input type="number" step="0.01" id="hdr-vat" value="105.81" oninput="recalculateTotals()">
    </div>
    <div class="form-group">
      <label>Net total (Gross - Tax) *</label>
      <input type="number" step="0.01" id="hdr-net" value="556.92" readonly style="background:#edf2f7; font-weight:bold;">
    </div>
  </div>

  <!-- SEKCJA PO DLA PURCHASE ORDER INVOICE (DOMYŚLNIE UKRYTA) -->
  <div id="po-section" style="display:none;">
    <h3>Wgrywanie i Wybór Zamówień Zakupowych (PO):</h3>
    
    <div class="drop-zone" onclick="document.getElementById('file-input').click()">
      Przeciągnij plik zamówienia (np. <strong>Order_Template.xml.bak</strong>) lub kliknij tutaj, aby dodać nowe zamówienie
      <input type="file" id="file-input" style="display:none" onchange="uploadFile(this.files[0])">
    </div>

    <div id="orders-container"></div>
  </div>

  <div id="warning-msg" class="warning-box"></div>

  <!-- PRZYCISKI AKCJI -->
  <div class="actions-bar">
    <button class="btn" onclick="downloadInvoiceXML()">Pobierz Fakturę TEAPPS 3.0 (XML)</button>
    <button class="btn btn-ftp" id="btn-send-ftp" onclick="sendToBaswareFTP()">Wyślij do BT/Basware QA (FTP)</button>
  </div>
</div>

<script>
  let loadedOrders = [];

  window.onload = function() {
    let today = new Date().toISOString().split('T')[0];
    let due = new Date(Date.now() + 7*24*60*60*1000).toISOString().split('T')[0];

    document.getElementById('hdr-creation-time').value = today;
    document.getElementById('hdr-delivery-date').value = today;
    document.getElementById('hdr-invoice-date').value = today;
    document.getElementById('hdr-due-date').value = due;
    
    handleInvoiceTypeChange();
  };

  function handleInvoiceTypeChange() {
    let invType = document.getElementById('hdr-invoice-type').value;
    let poSec = document.getElementById('po-section');
    let groupCalcNet = document.getElementById('group-calc-net');
    let poInput = document.getElementById('hdr-order-number');

    if (invType === 'Debit Invoice') {
      poSec.style.display = 'none';
      groupCalcNet.style.display = 'none';
      poInput.value = '';
      poInput.disabled = true;
    } else {
      poSec.style.display = 'block';
      groupCalcNet.style.display = 'flex';
      poInput.disabled = false;
      renderOrders();
      updateFormFromOrders();
    }
    recalculateTotals();
  }

  function uploadFile(file) {
    if (!file) return;
    let formData = new FormData();
    formData.append('file', file);

    fetch('/api/upload', { method: 'POST', body: formData })
      .then(res => res.json())
      .then(data => {
        if(data.error) { alert(data.error); return; }
        loadedOrders = data;
        document.getElementById('file-input').value = '';
        renderOrders();
        updateFormFromOrders();
      });
  }

  function deleteOrder(orderId) {
    fetch(`/api/delete-order/${orderId}`, { method: 'DELETE' })
      .then(res => res.json())
      .then(data => {
        loadedOrders = data;
        renderOrders();
        updateFormFromOrders();
      });
  }

  function updateFormFromOrders() {
    if (loadedOrders.length > 0) {
      let first = loadedOrders[0];
      document.getElementById('hdr-organization').value = first.company_code || document.getElementById('hdr-organization').value;
      document.getElementById('hdr-supplier-code').value = first.supplier_code || document.getElementById('hdr-supplier-code').value;
      document.getElementById('hdr-supplier-name').value = first.supplier_name || document.getElementById('hdr-supplier-name').value;
      document.getElementById('hdr-currency').value = first.currency || document.getElementById('hdr-currency').value;
      document.getElementById('hdr-reference-person').value = first.buyer_name || document.getElementById('hdr-reference-person').value;
    }
    updatePOInputNumbers();
    updateCalculations();
  }

  function updatePOInputNumbers() {
    let poInput = document.getElementById('hdr-order-number');
    if (document.getElementById('hdr-invoice-type').value === 'Purchase Order Invoice') {
      let nums = loadedOrders.map(o => o.order_number).filter((v, i, a) => a.indexOf(v) === i);
      poInput.value = nums.join(', ');
    }
  }

  function renderOrders() {
    let container = document.getElementById('orders-container');
    container.innerHTML = '';

    if (loadedOrders.length === 0) {
      container.innerHTML = '<div style="text-align:center; padding: 15px; color:#6c757d; background:#fafafa; border:1px dashed #cbd5e1; border-radius:6px;">Brak wczytanych zamówień. Dodaj plik zamówienia powyżej.</div>';
      return;
    }

    loadedOrders.forEach(order => {
      let card = document.createElement('div');
      card.className = 'order-card';

      let cardHeader = document.createElement('div');
      cardHeader.className = 'order-card-header';
      cardHeader.innerHTML = `
        <span>Zamówienie PO: ${order.order_number} (Plik: ${order.filename})</span>
        <button class="btn-danger" onclick="deleteOrder('${order.id}')">Usuń</button>
      `;

      let cardBody = document.createElement('div');
      cardBody.className = 'order-card-body';

      let table = document.createElement('table');
      table.innerHTML = `
        <thead>
          <tr>
            <th width="40"><input type="checkbox" onchange="toggleSelectAllInOrder('${order.id}', this)"></th>
            <th>Pozycja</th>
            <th>Nazwa / Nr GR</th>
            <th>Nr Dostawy</th>
            <th>Ilość</th>
            <th>Cena Netto</th>
            <th>Suma Netto</th>
          </tr>
        </thead>
        <tbody id="tbody-${order.id}"></tbody>
      `;

      cardBody.appendChild(table);
      card.appendChild(cardHeader);
      card.appendChild(cardBody);
      container.appendChild(card);

      let tbody = table.querySelector(`#tbody-${order.id}`);
      order.rows.forEach(row => {
        let trRow = document.createElement('tr');
        trRow.style.fontWeight = 'bold';
        trRow.style.background = '#eef2f7';
        trRow.innerHTML = `
          <td><input type="checkbox" class="row-check-${order.id}" data-pos="${row.order_pos}" onchange="toggleOrderRow('${order.id}', '${row.order_pos}', this.checked)"></td>
          <td>Pos ${row.order_pos}</td>
          <td colspan="2">${row.product_name}</td>
          <td>${row.quantity}</td>
          <td>${row.net_price.toFixed(2)}</td>
          <td>${row.net_sum.toFixed(2)}</td>
        `;
        tbody.appendChild(trRow);

        row.goods_receipts.forEach(gr => {
          let trGr = document.createElement('tr');
          trGr.className = 'gr-row';
          
          let grLabel = gr.gr_number !== 'BEZPOŚREDNIA LINIA' ? `GR: ${gr.gr_number} (Poz: ${gr.gr_row_number})` : 'BEZPOŚREDNIA LINIA';

          trGr.innerHTML = `
            <td><input type="checkbox" class="gr-check gr-check-all gr-${order.id}-${row.order_pos}" value="${gr.id}" onchange="updateCalculations()"></td>
            <td></td>
            <td>${grLabel}</td>
            <td>${gr.delivery_note}</td>
            <td><input type="number" id="qty-${gr.id}" value="${gr.quantity}" step="0.01" oninput="updateCalculations()"></td>
            <td><input type="number" id="price-${gr.id}" value="${gr.net_price}" step="0.01" oninput="updateCalculations()"></td>
            <td id="sum-${gr.id}">${gr.net_sum.toFixed(2)}</td>
          `;
          tbody.appendChild(trGr);
        });
      });
    });
  }

  function toggleOrderRow(orderId, pos, isChecked) {
    let grChecks = document.querySelectorAll(`.gr-${orderId}-${pos}`);
    grChecks.forEach(cb => cb.checked = isChecked);
    updateCalculations();
  }

  function toggleSelectAllInOrder(orderId, master) {
    let allChecks = document.querySelectorAll(`#tbody-${orderId} input[type="checkbox"]`);
    allChecks.forEach(cb => cb.checked = master.checked);
    updateCalculations();
  }

  function updateCalculations() {
    let totalNet = 0;

    loadedOrders.forEach(order => {
      order.rows.forEach(row => {
        row.goods_receipts.forEach(gr => {
          let cb = document.querySelector(`.gr-check[value="${gr.id}"]`);
          if (cb && cb.checked) {
            let qty = parseFloat(document.getElementById(`qty-${gr.id}`).value) || 0;
            let price = parseFloat(document.getElementById(`price-${gr.id}`).value) || 0;
            let sum = qty * price;
            let sumElem = document.getElementById(`sum-${gr.id}`);
            if (sumElem) sumElem.innerText = sum.toFixed(2);
            totalNet += sum;
          }
        });
      });
    });

    document.getElementById('calc-net').value = totalNet.toFixed(2);
    recalculateTotals();
  }

  function recalculateTotals() {
    let invType = document.getElementById('hdr-invoice-type').value;
    let calcNet = parseFloat(document.getElementById('calc-net').value) || 0;
    
    let grossAmount = parseFloat(document.getElementById('hdr-gross').value) || 0;
    let vatAmount = parseFloat(document.getElementById('hdr-vat').value) || 0;

    let netAmount = grossAmount - vatAmount;
    document.getElementById('hdr-net').value = netAmount.toFixed(2);

    let warn = document.getElementById('warning-msg');
    if (invType === 'Purchase Order Invoice' && Math.abs(calcNet - netAmount) > 0.01) {
      warn.style.display = 'block';
      warn.innerText = `UWAGA: Suma wyselekcjonowanych pozycji GR (${calcNet.toFixed(2)}) różni się od wyliczonej wartości Net Total (${netAmount.toFixed(2)})!`;
    } else {
      warn.style.display = 'none';
    }
  }

  function getPayload() {
    let invType = document.getElementById('hdr-invoice-type').value;
    let selectedRows = [];

    if (invType === 'Purchase Order Invoice') {
      loadedOrders.forEach(order => {
        order.rows.forEach(row => {
          row.goods_receipts.forEach(gr => {
            let cb = document.querySelector(`.gr-check[value="${gr.id}"]`);
            if (cb && cb.checked) {
              let qty = parseFloat(document.getElementById(`qty-${gr.id}`).value) || 0;
              let price = parseFloat(document.getElementById(`price-${gr.id}`).value) || 0;
              selectedRows.push({
                id: gr.id,
                order_pos: row.order_pos,
                quantity: qty,
                net_price: price,
                net_sum: qty * price
              });
            }
          });
        });
      });
    }

    return {
      invoice_type: invType,
      organization: document.getElementById('hdr-organization').value,
      supplier_code: document.getElementById('hdr-supplier-code').value,
      supplier_name: document.getElementById('hdr-supplier-name').value,
      supplier_vat: document.getElementById('hdr-supplier-vat').value,
      delivery_date: document.getElementById('hdr-delivery-date').value,
      due_date: document.getElementById('hdr-due-date').value,
      reference_person: document.getElementById('hdr-reference-person').value,
      currency: document.getElementById('hdr-currency').value,
      invoice_id: document.getElementById('hdr-invoice-id').value,
      invoice_date: document.getElementById('hdr-invoice-date').value,
      order_number: document.getElementById('hdr-order-number').value,
      trelleborg_vat: document.getElementById('hdr-trelleborg-vat').value,
      language: "EN",
      header_net: document.getElementById('hdr-net').value,
      header_vat: document.getElementById('hdr-vat').value,
      header_gross: document.getElementById('hdr-gross').value,
      rows: selectedRows
    };
  }

  function downloadInvoiceXML() {
    let payload = getPayload();

    fetch('/api/generate-xml', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    .then(res => res.blob())
    .then(blob => {
      let url = window.URL.createObjectURL(blob);
      let a = document.createElement('a');
      a.href = url;
      a.download = `Invoice_${payload.invoice_id}.xml`;
      document.body.appendChild(a);
      a.click();
      a.remove();
    });
  }

  function sendToBaswareFTP() {
    let payload = getPayload();
    let btn = document.getElementById('btn-send-ftp');
    
    btn.disabled = true;
    btn.innerText = "Wysyłanie...";

    fetch('/api/send-to-basware', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
      btn.disabled = false;
      btn.innerText = "Wyślij do Basware (FTP)";

      if (data.success) {
        alert("SUKCES: " + data.message);
      } else {
        alert("BŁĄD: " + data.error);
      }
    })
    .catch(err => {
      btn.disabled = false;
      btn.innerText = "Wyślij do Basware (FTP)";
      alert("Wystąpił błąd podczas połączenia z serwerem: " + err);
    });
  }
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    app.run(debug=True, port=5000)