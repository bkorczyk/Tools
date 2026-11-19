#!/usr/bin/env python3
"""
Basware Integration XML Config Parser & Interactive HTML Specification Generator
================================================================================
Parses Basware ERP Connector XML configuration files (e.g. InvoicePro_Customer_BT_Import)
and dynamically generates a full-featured, interactive HTML documentation dashboard
matching the Carbon-styled layout, interactive flowchart explorer, search/filter matrix,
and field detail view of 'Brak Treści'.

Usage:
    python generate_basware_html_spec.py <path_to_config.txt_or_xml> [output_html_path]
"""

import sys
import os
import re
import json
from pathlib import Path

def parse_config_file(file_path):
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # 1. Parse NewInvoice parameters
    new_inv_match = re.search(r'<method name="NewInvoice"[^>]*>(.*?)</method>', content, re.DOTALL)
    new_inv_content = new_inv_match.group(1) if new_inv_match else ""

    params = []
    param_regex = re.compile(
        r'<parameter\s+name=["\']([^"\']+)["\']'
        r'(?:\s+include=["\']([^"\']*)["\'])?'
        r'(?:\s*/>|\s*>(.*?)</parameter>)'
        r'(?:\s*<!--\s*(.*?)\s*-->)?',
        re.DOTALL
    )

    for match in param_regex.finditer(new_inv_content):
        pname = match.group(1)
        icond = match.group(2) or ""
        val = (match.group(3) or "").strip()
        comment = (match.group(4) or "").strip()

        # Clean basware field name from comment
        basware_name = ""
        if "Basware:" in comment:
            basware_name = comment.replace("Basware:", "").strip()
        elif comment:
            basware_name = comment.strip()
        else:
            basware_name = pname

        # Skip technical params with no comments if desired, or keep all
        if pname in ["InstanceName", "debug", "RemovalReason"] and not comment:
            basware_name = f"Parametr techniczny ({pname})"

        params.append({
            "param": pname,
            "baswareName": basware_name,
            "value_expr": val,
            "include_cond": icond,
            "raw_comment": comment
        })

    # Check for nested sections inside NewInvoice (e.g., CheckReferencePerson)
    has_ref_cascade = "CheckReferencePerson" in new_inv_content

    # 2. Parse global variables & logic sections
    variables = {}
    var_regex = re.compile(
        r'<variable\s+name=["\']([^"\']+)["\'](?:\s+include=["\']([^"\']*)["\'])?[^>]*>(.*?)</variable>',
        re.DOTALL
    )
    for m in var_regex.finditer(content):
        vname = m.group(1)
        vcond = m.group(2) or ""
        vval = m.group(3).strip()
        if vname not in variables:
            variables[vname] = []
        variables[vname].append({"value": vval, "condition": vcond})

    return {
        "params": params,
        "variables": variables,
        "has_ref_cascade": has_ref_cascade,
        "raw_content": content
    }

def classify_param(p):
    pname = p["param"]
    val = p["value_expr"]
    bname = p["baswareName"]
    icond = p["include_cond"]

    if pname in ["ReferencePerson", "OrderNumber"]:
        return "Cascading Fallback"
    if "DBSELECT" in val or "DBSELECT" in icond or pname in ["Text11", "Text8", "Text6", "Text14", "Num2", "Num8"]:
        return "DB Lookup & Rules"
    if pname in ["Text15", "Text19", "Text51"]:
        return "System Metadata"
    if icond:
        return "Business Rule / Conditional"
    if val.startswith("{v,") and val.endswith("}"):
        return "Direct XML Mapping"
    return "Business Rule / Conditional"

def build_field_data(parsed):
    fields = []
    order = 1

    for p in parsed["params"]:
        pname = p["param"]
        bname = p["baswareName"]
        val = p["value_expr"]
        icond = p["include_cond"]
        cat = classify_param(p)

        # Build detailed Polish explanations & rules summaries matching Brak Treści standards
        rules_summary = ""
        detail_steps = []
        sql_queries = []
        xpath_sources = []
        edge_cases = ""

        if pname == "BaseDate":
            rules_summary = "Pobiera datę faktury z widoku zmiennej `InvoiceDate`, o ile przesłała poprawny format daty (`isInvoiceDate = True`)."
            detail_steps = [
                "1. Odczyt elementu `//INVOICE_DATE` z XML faktury wejściowej.",
                "2. Weryfikacja funkcji ISDATE w formacie `yyyy-MM-dd`.",
                "3. Przypisanie do pola `BaseDate` w Basware jako data bazowa płatności."
            ]
            xpath_sources = ["//INVOICE_DATE/DATE/CENTURY", "//INVOICE_DATE/DATE/DECADE_AND_YEAR", "//INVOICE_DATE/DATE/MONTH", "//INVOICE_DATE/DATE/DAY"]
        elif pname == "CurrencyCode" or pname == "CurrencyCodeCompany" or pname == "CurrencyCodeOrganization":
            rules_summary = "Pobiera 3-literowy kod waluty nagłówka faktury z tagu XML `//HEADER/CURRENCY/CODE`."
            detail_steps = ["Odczyt bezpośredni z nagłówka pliku XML faktury."]
            xpath_sources = ["//HEADER/CURRENCY/CODE"]
        elif pname == "Num10":
            rules_summary = "Przekazuje kurs wymiany waluty z nagłówka faktury `//HEADER/CURRENCY/RATE`."
            detail_steps = ["Odczyt kursu walutowego dla przeliczeń lokalnych."]
            xpath_sources = ["//HEADER/CURRENCY/RATE"]
        elif pname == "Date2":
            rules_summary = "Data skanowania/wpływu dokumentu przekazana z nagłówka skanu."
            detail_steps = ["Przekazanie daty skanowania faktury."]
        elif pname == "GrossSum":
            rules_summary = "Kwota brutto faktury z uwzględnieniem znaku (+/-) odczytana z `//SUMMARY/INVOICE_TOTAL/AMOUNT[@VAT='INCLUDED']`."
            detail_steps = ["1. Odczyt kwoty brutto z podsumowania XML.", "2. Uwzględnienie atrybutu SIGN (dla korekt/ujemnych kwot mnożenie przez -1)."]
            xpath_sources = ["//SUMMARY/INVOICE_TOTAL/AMOUNT[@VAT='INCLUDED']", "//SUMMARY/INVOICE_TOTAL/AMOUNT/@SIGN"]
        elif pname == "NetSum":
            rules_summary = "Kwota netto faktury z uwzględnieniem znaku odczytana z `//SUMMARY/INVOICE_TOTAL/AMOUNT[@VAT='EXCLUDED']`."
            detail_steps = ["1. Odczyt kwoty netto z XML.", "2. Obsługa znaków kwot ujemnych."]
            xpath_sources = ["//SUMMARY/INVOICE_TOTAL/AMOUNT[@VAT='EXCLUDED']"]
        elif pname == "TaxSum" or pname == "Num11":
            rules_summary = "Łączna kwota podatku VAT nagłówka z uwzględnieniem odliczeń `DeductibleVAT` oraz reguł dla spółek zależnych."
            detail_steps = [
                "1. Odczyt sumy VAT z `//SUMMARY/VAT_TOTAL/AMOUNT`.",
                "2. Weryfikacja pola wolnego `DeductibleVAT`.",
                "3. Dla spółek `TWSA` / `TWSMITCA` lub konfiguracji `C_108` wymuszenie wartości 0."
            ]
            xpath_sources = ["//SUMMARY/VAT_TOTAL/AMOUNT", "//HEADER/FREE_TEXT[@TEXT_TYPE='DeductibleVAT']"]
        elif pname == "Num23":
            rules_summary = "Kwota VAT w drugiej walucie. Aktywne tylko dla spółek z walidacją `V_051`."
            detail_steps = ["Weryfikacja bazy walidacji spółki `V_051` ➔ odczyt `INVOICE_TOTAL_IN_OTHER_CURRENCY`."]
            xpath_sources = ["//SUMMARY/INVOICE_TOTAL_IN_OTHER_CURRENCY/AMOUNT"]
        elif pname == "InvoiceDate":
            rules_summary = "Data wystawienia faktury wyznaczona i sformatowana do `yyyy-MM-dd`."
            detail_steps = ["1. Parsowanie składowych daty z `//INVOICE_DATE`.", "2. Walidacja formatu date `ISDATE`."]
            xpath_sources = ["//INVOICE_DATE"]
        elif pname == "InvoiceNumber":
            rules_summary = "Numer faktury z wyczyszczonymi znakami specjalnymi. Wyjątki dla typów systemowych ERP (np. `TIPINTSS`)."
            detail_steps = [
                "1. Odczyt z `//HEADER/INVOICE_ID`.",
                "2. Zamiana myślników i znaków nienormatywnych.",
                "3. Jeśli 'NOT_FOUND' ➔ pobranie z `FI_PAYMENT_REFERENCE`.",
                "4. Dla wybranych spółek (np. `BUSAITL`, `TSSFR`, `TSSUK11`) usuwanie znaków `+`, `_`, `&`, `/`, `.`."
            ]
            xpath_sources = ["//HEADER/INVOICE_ID", "//PAYEE/DETAILS_OF_PAYMENT/FI_PAYMENT_REFERENCE"]
        elif pname == "InvoiceTypeCode":
            rules_summary = "Kod typu faktury przekazywany z logiki ustalania typu dokumentu `InvoiceType`."
            detail_steps = ["Mapowanie kodu typu faktury."]
        elif pname == "OrderNumber":
            rules_summary = "Numer zamówienia PO wyznaczany kaskadowo z nagłówka lub pozycji faktury z czyszczeniem dla wybranych spółek."
            detail_steps = [
                "1. Weryfikacja czyszczenia zamówienia dla spółek: TAB, HAL7, HAL8, THAB, TREASURY, TIND.",
                "2. Priorytet zamówień w nagłówku: Typ 'CO' ➔ Typ inny niż 'VN' ➔ Typ 'VN' ➔ INVOICE_ORDER_NUMBER.",
                "3. W przypadku braku w nagłówku: Pętla po pozycjach LoopLineItems i scalanie unikalnych numerów zamówień po przecinku.",
                "4. Dla dostawców logistycznych (EXT_INV_LIST_14): Weryfikacja zgodności dostawcy z zamówienia ERP."
            ]
            xpath_sources = ["//HEADER/ORDER_INFORMATION[@ORDER_TYPE='CO']/ORDER_NUMBER", "//HEADER/INVOICE_ORDER_NUMBER", "/INVOICE_CENTER/CONTENT_FRAME/INVOICES/INVOICE/ROWS/ROW/ORDER_INFORMATION/ORDER_NUMBER"]
            edge_cases = "Wybrane spółki amerykańskie (np. TSSUS52) obcinają numer zamówienia do pierwszych 8 znaków."
        elif pname == "ReferencePerson":
            rules_summary = "Osoba referencyjna / zamawiający wyznaczana kaskadowo w pętli 3 poziomów (min. 2 znaki)."
            detail_steps = [
                "1. Pierwszy wybór: BuyerReference (`//HEADER/BUYER_REFERENCE`).",
                "2. Jeśli długość < 2 znaki ➔ drugi wybór: ContactReference (`//RECEIVER/.../CONTACT_PERSON`).",
                "3. Jeśli długość < 2 znaki ➔ trzeci wybór: ContactPerson (`//ORDERER/.../CONTACT_PERSON`).",
                "4. Jeśli nadal brak ➔ pusty ciąg znaków."
            ]
            xpath_sources = ["//HEADER/BUYER_REFERENCE", "//RECEIVER/CUSTOMER_INFORMATION/CONTACT_INFORMATION/CONTACT_PERSON", "//ORDERER/CUSTOMER_INFORMATION/CONTACT_INFORMATION/CONTACT_PERSON"]
        elif pname == "ContractNumber":
            rules_summary = "Numer umowy odczytany z faktury lub pobrany ze słownika domyślnych umów dostawcy w Basware."
            detail_steps = [
                "1. Odczyt z `//HEADER/CONTRACT_INFORMATION/CONTRACT_NUMBER`.",
                "2. Nadpisanie ze słownika EXT_INV_LIST_17 ('SupplierDefaultContract') dla danej spółki i dostawcy."
            ]
            sql_queries = ["SELECT l.TEXT_3 FROM EXT_inv_list_17 l WHERE l.TEXT_1='SupplierDefaultContract' AND l.TEXT_2=? AND o.code=?"]
            xpath_sources = ["//HEADER/CONTRACT_INFORMATION/CONTRACT_NUMBER"]
        elif pname == "ReferenceNumber":
            rules_summary = "Numer referencyjny płatności / referencja bankowa."
            detail_steps = ["1. Odczyt z `FI_PAYMENT_REFERENCE`.", "2. Nadpisanie z pola `BW-0000020` jeśli istnieje."]
            xpath_sources = ["//PAYEE/DETAILS_OF_PAYMENT/FI_PAYMENT_REFERENCE", "//HEADER/HEADER_INFO[TITLE/@INFO_TYPE='BW-0000020']/CONTENT"]
        elif pname == "Text11":
            rules_summary = "Status AP dostawcy pobierany z tabeli słownikowej po włączeniu reguły C_109."
            detail_steps = ["Zapytanie do EXT_INV_LIST_17 dla TEXT_1='SupplierAPStatus' przy włączonej konfiguracji C_109."]
            sql_queries = ["SELECT TEXT_3 FROM EXT_INV_LIST_17 WHERE TEXT_1='SupplierAPStatus' AND ADMINISTRATIVE_SITE_ID=? AND TEXT_2=?"]
        elif pname == "Text19":
            rules_summary = "Identyfikator usługi skanującej / ID bloku przetwarzania."
            detail_steps = ["Odczyt z `BLOCK_ID` pliku XML."]
            xpath_sources = ["/INVOICE_CENTER/CONTENT_FRAME/BLOCK_ID"]
        elif pname == "TaxCode":
            rules_summary = "Kod podatku VAT wyznaczany z pozycji zamówienia ERP lub karty dostawcy."
            detail_steps = [
                "1. Jeśli faktura jest powiązana z PO ➔ odczyt TAX_CODE z pozycji zamówienia w OM_ORDER_ROW (TaxCodeSelectionType = 1).",
                "2. Jeśli na pozycjach zamówienia są różne kody VAT ➔ TaxCodeSelectionType = 9.",
                "3. Dla faktur bez PO ➔ pobranie domyślnego kodu z ADM_SUPPLIER_ADDITIONAL_DATA (TaxCodeSelectionType = 2)."
            ]
            sql_queries = [
                "SELECT MAX(TAX_CODE) FROM OM_ORDER_DATA INNER JOIN OM_ORDER_ROW ... WHERE ORDER_NUMBER = ?",
                "SELECT VALUE FROM ADM_SUPPLIER_ADDITIONAL_DATA WHERE NAME = 'TaxCodes' AND SUPPLIER_ID = ?"
            ]
            edge_cases = "Dla spółki BUSADE020 następuje specyficzne przenumerowanie kodów (np. DE21 ➔ DE22, DES6 ➔ DES9)."
        elif pname == "TaxPercent":
            rules_summary = "Stawka procentowa VAT pobierana z tabeli podatkowej `ADM_TAX_CODE` dla wyznaczonego `TaxCode`."
            detail_steps = ["Odpytanie bazy danych po kodzie podatku i identyfikatorze spółki."]
            sql_queries = ["SELECT TAX_PERCENT FROM ADM_TAX_CODE WHERE CODE = ? AND ADMINISTRATIVE_SITE_ID = ?"]
        elif pname == "Date3":
            rules_summary = "Data dostawy towaru/usługi z obsługą skanów (analiza najnowszej daty z nagłówków/pozycji) oraz e-faktur."
            detail_steps = [
                "1. Dla skanów: Parsowanie listy dat z rozdzielaczem ';', porównanie lat/miesięcy YYMM i wybór najnowszego dnia.",
                "2. Dla e-faktur: Odczyt nagłówka DELIVERY_DATE lub analiza dat na pozycjach w pętli LoopLineItems."
            ]
            xpath_sources = ["//HEADER/FREE_TEXT[@TEXT_TYPE='DeliveryDate']", "//HEADER/DELIVERY_DATE"]
        elif pname == "Date4":
            rules_summary = "Data wymagalności płatności (Termin płatności). W przypadku braku w pliku XML przyjmowana jest data bieżąca (`NOW()`)."
            detail_steps = ["1. Odczyt `//DUE_DATE`.", "2. Walidacja formatu `ISDATE`.", "3. Fallback do daty bieżącej."]
            xpath_sources = ["//DUE_DATE"]
        elif pname == "Text23":
            rules_summary = "Numer NIP dostawcy (Supplier VAT Number)."
            detail_steps = ["Odczyt z `//PAYEE/CUSTOMER_INFORMATION/VAT_NUMBER`."]
            xpath_sources = ["//PAYEE/CUSTOMER_INFORMATION/VAT_NUMBER"]
        elif pname == "Text25":
            rules_summary = "Lokalny numer podatkowy dostawcy (Local Supplier Tax ID)."
            detail_steps = ["Odczyt z pola wolnego `local_TaxID` lub `ORGANIZATION_NUMBER`."]
            xpath_sources = ["//HEADER/FREE_TEXT[@TEXT_TYPE='local_TaxID']", "//PAYEE/CUSTOMER_INFORMATION/ORGANIZATION_NUMBER"]
        elif pname == "Text26":
            rules_summary = "Numer VAT spółki Trelleborg z faktury."
            detail_steps = ["1. NIP odbiorcy (`//RECEIVER/.../VAT_NUMBER`).", "2. NIP zamawiającego (`//ORDERER/.../VAT_NUMBER`).", "3. Pole wolne Trelleborg_VAT_number."]
            xpath_sources = ["//RECEIVER/CUSTOMER_INFORMATION/VAT_NUMBER", "//HEADER/FREE_TEXT[@TEXT_TYPE='Trelleborg_VAT_number']"]
        elif pname == "Text28":
            rules_summary = "Nazwa spółki widniejąca na fakturze (`CompNameFromInvoice`)."
            detail_steps = ["Odczyt z `company name from invoice` lub nazwy odbiorcy z nagłówka XML."]
            xpath_sources = ["//HEADER/FREE_TEXT[@TEXT_TYPE='company name from invoice']", "//RECEIVER/CUSTOMER_INFORMATION/CUSTOMER_NAME"]
        elif pname == "Num2":
            rules_summary = "Flaga automatycznego skierowania faktury do procesu (1 = manualne, 2 = auto-send)."
            detail_steps = [
                "1. Sprawdzenie słownika `EXT_INV_LIST_17` dla wpisu `AUTOSENDTOPROCESSSUPPLIER`.",
                "2. Jeśli typ faktury lub dostawca pasuje do listy ➔ przypisanie wartości 2."
            ]
            sql_queries = ["SELECT UPPER(TEXT_3) FROM EXT_INV_LIST_17 WHERE UPPER(TEXT_1)='AUTOSENDTOPROCESSSUPPLIER' AND ADMINISTRATIVE_SITE_ID=? AND TEXT_2=?"]
        elif pname == "SupplierBankAccountBBAN" or pname == "SupplierBankAccountIBAN":
            rules_summary = "Numer konta bankowego dostawcy (BBAN/IBAN)."
            detail_steps = ["Odczyt z odpowiedniego węzła bankowego `//PAYEE/BANKS/`."]
            xpath_sources = ["//PAYEE/BANKS/IBAN_ACCOUNT_NUMBER", "//PAYEE/BANKS/BANK_ACCOUNT_NUMBER"]
        elif pname == "Text8":
            rules_summary = "Kod dywizji / jednostki organizacyjnej."
            detail_steps = ["Przekazanie wartości zmiennej Division."]
        elif pname == "Text6":
            rules_summary = "Dodatkowe dane organizacyjne 1 (Additional Data 1)."
            detail_steps = ["Mapowanie kodu podziału w zależności od typu faktury i spółki."]
        elif pname == "Text14":
            rules_summary = "Typ dostawcy (Internal / External)."
            detail_steps = ["Weryfikacja przynależności dostawcy do grupy wewnętrznej Trelleborg."]
        elif pname == "Text15":
            rules_summary = "Uwaga: Pole Text15 w systemie Basware pełni rolę Tax Code 2. Zasilane jest nazwą pliku źródłowego (`file_name`)."
            detail_steps = ["Przypisanie nazwy pliku wejściowego `file_name` do pola Tax Code 2 w Basware."]
            edge_cases = "Nazwa parametru Text15 w Basware odpowiada drugiemu kodowi podatkowemu, mimo że skrypt przekazuje tam nazwę pliku."
        elif pname == "Text30":
            rules_summary = "Adres e-mail nadawcy zgłoszenia skanowania."
            detail_steps = ["Odczyt nagłówka `ScanCaptureSentFrom`."]
            xpath_sources = ["//HEADER/HEADER_INFO[TITLE/@INFO_TYPE='ScanCaptureSentFrom']/CONTENT"]
        elif pname == "Text34" or pname == "Text35":
            rules_summary = "Numer seryjny oraz format dekretacji VAT."
            detail_steps = ["Odczyt z dedykowanych pól nagłówka TEXT34 i TEXT35."]
            xpath_sources = ["//HEADER/TEXT34", "//HEADER/TEXT35"]
        elif pname == "Text51":
            rules_summary = "Kod pomijania reguł / flaga specyficznej obsługi (skiprule)."
            detail_steps = [
                "1. Kwota zerowa faktury ➔ dodanie wskaźnika 'P'.",
                "2. Słowa kluczowe RESERVE / RETENUE / GARANTIE ➔ dodanie wskaźnika 'R'.",
                "3. Flaga AAB w nagłówku ➔ dodanie wskaźnika 'D'."
            ]
            xpath_sources = ["//HEADER/HEADER_INFO/CONTENT"]
        else:
            rules_summary = f"Mapowanie parametru {pname} z wyrażenia: {val}"
            detail_steps = [f"Wartość źródłowa: {val}"]
            if icond:
                detail_steps.append(f"Warunek dołączenia: {icond}")

        fields.append({
            "order": order,
            "param": pname,
            "baswareName": bname,
            "category": cat,
            "sourceExpr": val if val else "(Brak / Direct)",
            "includeCond": icond if icond else "(Brak)",
            "rulesSummary": rules_summary,
            "detailSteps": detail_steps,
            "sqlQueries": sql_queries,
            "xpathSources": xpath_sources,
            "edgeCases": edge_cases
        })
        order += 1

    return fields

def build_companion_fields():
    return [
        {
            "order": 54,
            "param": "SupplierId (AddSupplierIdentifier)",
            "baswareName": "Identyfikator dostawcy (poza NewInvoice)",
            "category": "DB Lookup & Rules",
            "sourceExpr": "{v,SupplierId}",
            "includeCond": "SupplierCount = 1 (kaskada 7 kroków)",
            "rulesSummary": "System wykonuje 7-stopniową sekwencję zapytań SQL w celu jednoznacznego ustalenia ID dostawcy w bazie danych. Jeśli którykolwiek krok zwróci dokładnie 1 rekord (SupplierCount = 1), wartość jest przypisywana.",
            "detailSteps": [
                "Krok 1: Wyszukanie po kodzie dostawcy z XML (PAYEE/CUSTOMER_INFORMATION/CUSTOMER_ID).",
                "Krok 2: Wyszukanie po identyfikatorze sieciowym / Party ID w ADM_SUPPLIER_IDENTIFIER.",
                "Krok 3: Wyszukanie po oczyszczonym numerze NIP/VAT (bez spacji, myślników i kropki).",
                "Krok 4: Wyszukanie po lokalnym identyfikatorze podatkowym (local_TaxID) z kryterium PAYMENT_DENIED = 0.",
                "Krok 5: Wyszukanie po Party ID z dopasowaniem waluty faktury (CURRENCY_CODE).",
                "Krok 6: Wyszukanie po numerze konta bankowego BBAN lub IBAN w ADM_SUPPLIER_BANK_ACCOUNT.",
                "Krok 7 (Fallback): Odczyt ID dostawcy fakturującego z zamówienia ERP w OM_ORDER_DATA po numerze PO."
            ],
            "sqlQueries": [
                "SELECT ADM_SUPPLIER.ID FROM ADM_SUPPLIER WHERE is_Active=1 AND ADMINISTRATIVE_SITE_ID = ? AND CODE = ?",
                "SELECT ADM_SUPPLIER.ID FROM ADM_SUPPLIER INNER JOIN ADM_SUPPLIER_IDENTIFIER ON ... WHERE IDENTIFIER_VALUE = ?",
                "SELECT INVOICING_SUPPLIER_ID FROM OM_ORDER_DATA WHERE ORDER_NUMBER = ? AND COMPANY_ID = ?"
            ],
            "edgeCases": "Dla spółki TSSUS52 krok sprawdzania zamówień wykonywany jest niezależnie. Dla dostawców logistycznych zamówienie jest czyszczone w przypadku niezgodności dostawcy."
        },
        {
            "order": 55,
            "param": "IntegrationID",
            "baswareName": "Identyfikator integracji dostawcy",
            "category": "System Metadata",
            "sourceExpr": "{v,IntegrationID}",
            "includeCond": "(Brak)",
            "rulesSummary": "Unikalny identyfikator powiązania dostawcy ze spółką w systemie integracyjnym.",
            "detailSteps": ["Tworzony z połączenia kodu spółki CompanyCode oraz kodu dostawcy SupplierCode."],
            "sqlQueries": [],
            "edgeCases": ""
        },
        {
            "order": 56,
            "param": "SupplierNetServiceId",
            "baswareName": "Identyfikator sieciowy dostawcy",
            "category": "Direct XML Mapping",
            "sourceExpr": "{xmlInvoice,'//PAYEE/CUSTOMER_INFORMATION/VAT_NUMBER'}",
            "includeCond": "SupplierNetServiceId <> '999999999'",
            "rulesSummary": "Identyfikator sieciowy używany do komunikacji elektronicznej i mapowania dostawców w sieci Basware.",
            "detailSteps": ["Odczytywany z numeru VAT dostawcy lub bezpośrednio z pola NET_SERVICE_ID."],
            "sqlQueries": [],
            "edgeCases": "Wartość sztuczna '999999999' jest automatycznie czyszczona i ignorowana."
        },
        {
            "order": 57,
            "param": "CompanyNetServiceId",
            "baswareName": "Identyfikator odbiorcy (Administrative Site)",
            "category": "DB Lookup & Rules",
            "sourceExpr": "{xmlInvoice,'//RECEIVER/NET_SERVICE_ID'}",
            "includeCond": "(Brak)",
            "rulesSummary": "Służy do automatycznego wyznaczenia identyfikatora spółki odbiorcy (CompanyId / AdministrativeSiteID) w strukturze Trelleborg.",
            "detailSteps": [
                "1. Odczyt z RECEIVER/NET_SERVICE_ID lub RECEIVER/CUSTOMER_INFORMATION/PARTY_IDENTIFICATION_ID.",
                "2. Odpytanie bazy danych ADM_ORGANIZATION_IDENTIFIER w celu znalezienia elementu organizacji."
            ],
            "sqlQueries": ["SELECT organization_element_id FROM adm_organization_identifier WHERE identifier_value = ?"],
            "edgeCases": ""
        }
    ]

def generate_html_spec(fields_data, companion_fields, raw_xml):
    total_count = len(fields_data)
    direct_count = sum(1 for f in fields_data if f["category"] == "Direct XML Mapping")
    cascade_count = sum(1 for f in fields_data if f["category"] == "Cascading Fallback")
    db_count = sum(1 for f in fields_data if f["category"] == "DB Lookup & Rules")
    rules_count = sum(1 for f in fields_data if f["category"] in ["Business Rule / Conditional", "System Metadata"])

    fields_json = json.dumps(fields_data, ensure_ascii=False, indent=2)
    companion_json = json.dumps(companion_fields, ensure_ascii=False, indent=2)

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="artifact-type" content="dashboard">
  <meta name="design-style" content="carbon">
  <title>Specyfikacja mapowania NewInvoice — Basware BT Import</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:ital,wght@0,100..700;1,100..700&family=IBM+Plex+Mono:ital,wght@0,100;0,700;1,100;1,700&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/lucide@1.43.0/dist/umd/lucide.min.js"></script>
  <style>
    :root {{
      color-scheme: light dark;
      --background: #0f172a;
      --surface-low: #1e293b;
      --surface-high: #334155;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --accent-blue: #38bdf8;
      --accent-purple: #c084fc;
      --accent-green: #4ade80;
      --accent-amber: #fbbf24;
      --accent-red: #f87171;
      --border: #334155;
      --card-bg: #1e293b;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'IBM Plex Sans', system-ui, sans-serif; }}
    body {{ background: var(--background); color: var(--text-main); padding: 2rem; line-height: 1.6; }}
    
    .page-header {{
      display: flex; justify-content: space-between; align-items: flex-start;
      margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--border);
    }}
    .page-header h1 {{ font-size: 2rem; color: var(--accent-blue); display: flex; align-items: center; gap: 0.75rem; }}
    .subtitle {{ color: var(--text-muted); font-size: 1.05rem; margin-top: 0.3rem; }}
    .header-badges {{ display: flex; gap: 0.75rem; margin-top: 0.75rem; }}
    .status-badge {{ background: rgba(56, 189, 248, 0.15); color: var(--accent-blue); padding: 0.3rem 0.75rem; border-radius: 6px; font-size: 0.85rem; border: 1px solid var(--accent-blue); font-weight: 600; }}
    
    .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2.5rem; }}
    .metric-card {{ background: var(--card-bg); padding: 1.25rem; border-radius: 10px; border: 1px solid var(--border); transition: transform 0.2s; }}
    .metric-card:hover {{ transform: translateY(-3px); border-color: var(--accent-blue); }}
    .metric-title {{ font-size: 0.85rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }}
    .metric-value {{ font-size: 2.2rem; font-weight: 700; color: var(--text-main); margin-top: 0.25rem; font-family: 'IBM Plex Mono', monospace; }}
    
    .section-title {{ font-size: 1.4rem; color: var(--text-main); margin-bottom: 1rem; display: flex; align-items: center; gap: 0.6rem; border-left: 4px solid var(--accent-blue); padding-left: 0.75rem; }}
    
    /* Flowchart Explorer */
    .flow-explorer {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin-bottom: 2.5rem; }}
    .flow-tabs {{ display: flex; gap: 0.5rem; overflow-x: auto; padding-bottom: 0.75rem; margin-bottom: 1.25rem; border-bottom: 1px solid var(--border); }}
    .flow-tab {{ background: var(--surface-low); border: 1px solid var(--border); color: var(--text-muted); padding: 0.6rem 1.2rem; border-radius: 8px; cursor: pointer; white-space: nowrap; font-size: 0.9rem; font-weight: 600; transition: all 0.2s; }}
    .flow-tab.is-active {{ background: var(--accent-blue); color: #000; border-color: var(--accent-blue); }}
    .flow-viewer {{ display: grid; grid-template-columns: 2fr 1fr; gap: 1.5rem; }}
    @media (max-width: 900px) {{ .flow-viewer {{ grid-template-columns: 1fr; }} }}
    .flow-canvas {{ background: #0b1120; border: 1px solid var(--border); border-radius: 8px; padding: 1.5rem; display: flex; flex-direction: column; gap: 0.75rem; min-height: 380px; justify-content: center; }}
    .flow-node {{ background: var(--surface-low); border: 1px solid var(--border); padding: 1rem; border-radius: 8px; cursor: pointer; transition: all 0.2s; position: relative; }}
    .flow-node.is-selected {{ border-color: var(--accent-blue); box-shadow: 0 0 12px rgba(56, 189, 248, 0.3); background: #1e293b; }}
    .flow-node-title {{ font-weight: 700; color: var(--accent-blue); font-size: 0.95rem; }}
    .flow-node-desc {{ font-size: 0.85rem; color: var(--text-muted); margin-top: 0.25rem; }}
    .flow-details-panel {{ background: var(--surface-low); border: 1px solid var(--border); border-radius: 8px; padding: 1.25rem; }}
    .flow-details-panel h4 {{ color: var(--accent-amber); font-size: 1.1rem; margin-bottom: 0.75rem; }}

    /* Controls & Table */
    .table-controls {{ display: flex; justify-content: space-between; gap: 1rem; margin-bottom: 1.25rem; flex-wrap: wrap; }}
    .search-input {{ flex: 1; min-width: 280px; background: var(--card-bg); border: 1px solid var(--border); color: var(--text-main); padding: 0.75rem 1rem; border-radius: 8px; font-size: 0.95rem; outline: none; }}
    .search-input:focus {{ border-color: var(--accent-blue); }}
    .cat-filters {{ display: flex; gap: 0.4rem; flex-wrap: wrap; }}
    .cat-btn {{ background: var(--card-bg); border: 1px solid var(--border); color: var(--text-muted); padding: 0.5rem 0.9rem; border-radius: 6px; cursor: pointer; font-size: 0.85rem; font-weight: 600; transition: all 0.2s; }}
    .cat-btn.active {{ background: var(--accent-blue); color: #000; border-color: var(--accent-blue); }}
    
    .data-table {{ width: 100%; border-collapse: collapse; background: var(--card-bg); border-radius: 10px; overflow: hidden; border: 1px solid var(--border); margin-bottom: 2.5rem; }}
    .data-table th {{ background: #162032; color: var(--accent-blue); text-align: left; padding: 1rem; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--border); }}
    .data-table td {{ padding: 0.9rem 1rem; border-bottom: 1px solid var(--border); vertical-align: top; font-size: 0.9rem; }}
    .data-table tr:hover {{ background: rgba(255,255,255,0.02); }}
    .data-table tr.is-expanded {{ background: rgba(56, 189, 248, 0.05); }}
    
    .badge {{ display: inline-block; padding: 0.2rem 0.55rem; border-radius: 4px; font-size: 0.78rem; font-weight: 700; text-transform: uppercase; }}
    .badge-direct {{ background: rgba(74, 222, 128, 0.15); color: var(--accent-green); border: 1px solid var(--accent-green); }}
    .badge-cascade {{ background: rgba(192, 132, 252, 0.15); color: var(--accent-purple); border: 1px solid var(--accent-purple); }}
    .badge-db {{ background: rgba(251, 191, 36, 0.15); color: var(--accent-amber); border: 1px solid var(--accent-amber); }}
    .badge-sys {{ background: rgba(56, 189, 248, 0.15); color: var(--accent-blue); border: 1px solid var(--accent-blue); }}
    .badge-rule {{ background: rgba(248, 113, 113, 0.15); color: var(--accent-red); border: 1px solid var(--accent-red); }}

    code {{ font-family: 'IBM Plex Mono', monospace; background: rgba(0,0,0,0.4); padding: 0.2rem 0.4rem; border-radius: 4px; color: #e2e8f0; font-size: 0.85rem; }}
    .detail-drawer {{ background: var(--surface-low); padding: 1.25rem; border-top: 1px solid var(--border); font-size: 0.88rem; display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
    @media (max-width: 800px) {{ .detail-drawer {{ grid-template-columns: 1fr; }} }}

    /* Traps Grid */
    .traps-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.25rem; margin-bottom: 2.5rem; }}
    .trap-card {{ background: var(--card-bg); border: 1px solid var(--border); border-left: 4px solid var(--accent-amber); padding: 1.25rem; border-radius: 8px; }}
    .trap-card h4 {{ color: var(--accent-amber); font-size: 1.05rem; margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.5rem; }}

    .footer-note {{ text-align: center; color: var(--text-muted); font-size: 0.85rem; padding: 2rem 0; border-top: 1px solid var(--border); }}
  </style>
</head>
<body>
  <div class="page-grid">
    <header class="page-header">
      <div>
        <h1><i data-lucide="file-code-2"></i> Specyfikacja mapowania NewInvoice — Basware BT Import</h1>
        <p class="subtitle">Interaktywna dokumentacja logiki wyznaczania pól w integracji ERP Connector z systemem Basware</p>
        <div class="header-badges">
          <span class="status-badge"><i data-lucide="check-circle-2" style="width:14px; height:14px; display:inline;"></i> Wygenerowano dynamicznie</span>
          <span class="status-badge" style="border-color: var(--accent-purple); color: var(--accent-purple);">Plik: InvoicePro_Customer_BT_Import</span>
        </div>
      </div>
    </header>

    <!-- Statystyki -->
    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-title">Wszystkie pola NewInvoice</div>
        <div class="metric-value">{total_count}</div>
      </div>
      <div class="metric-card">
        <div class="metric-title">Bezpośrednie z XML (Direct)</div>
        <div class="metric-value" style="color: var(--accent-green);">{direct_count}</div>
      </div>
      <div class="metric-card">
        <div class="metric-title">Kaskady priorytetowe</div>
        <div class="metric-value" style="color: var(--accent-purple);">{cascade_count}</div>
      </div>
      <div class="metric-card">
        <div class="metric-title">Zapytania DB & Słowniki</div>
        <div class="metric-value" style="color: var(--accent-amber);">{db_count}</div>
      </div>
      <div class="metric-card">
        <div class="metric-title">Reguły & Metadane</div>
        <div class="metric-value" style="color: var(--accent-blue);">{rules_count}</div>
      </div>
    </div>

    <!-- Interaktywne Diagramy Przepływu -->
    <h2 class="section-title" id="flows-heading"><i data-lucide="git-circuit"></i> Diagramy Przepływu Determinowania Kluczowych Pola</h2>
    <div class="flow-explorer">
      <div class="flow-tabs" id="flowTabs">
        <button class="flow-tab is-active" data-flow="supplierId">1. SupplierID (7 Kroków)</button>
        <button class="flow-tab" data-flow="orderNumber">2. OrderNumber (Nagłówek/Wiersze)</button>
        <button class="flow-tab" data-flow="referencePerson">3. ReferencePerson (Kaskada)</button>
        <button class="flow-tab" data-flow="taxCode">4. TaxCode (Zamówienia vs Słownik)</button>
        <button class="flow-tab" data-flow="deliveryDate">5. DeliveryDate (Skan vs E-Faktura)</button>
      </div>
      <div class="flow-viewer">
        <div class="flow-canvas" id="flowCanvas"></div>
        <div class="flow-details-panel" id="flowDetails">
          <h4 id="flowNodeTitle">Wybierz krok z diagramu</h4>
          <p id="flowNodeDesc" style="color: var(--text-muted); font-size: 0.9rem;">Kliknij na dowolny węzeł na schemacie, aby wyświetlić szczegółowe zapytanie SQL, warunki biznesowe i reguły walidacji.</p>
        </div>
      </div>
    </div>

    <!-- Matryca Pola NewInvoice -->
    <h2 class="section-title"><i data-lucide="table-properties"></i> Szczegółowa Matryca Mapowania Pola NewInvoice</h2>
    <div class="table-controls">
      <input type="text" id="searchInput" class="search-input" placeholder="Wyszukaj pole Basware, parametr techniczny, zapytanie SQL lub słowo kluczowe...">
      <div class="cat-filters">
        <button class="cat-btn active" onclick="filterCat('ALL')">Wszystkie ({total_count})</button>
        <button class="cat-btn" onclick="filterCat('Direct XML Mapping')">Direct XML</button>
        <button class="cat-btn" onclick="filterCat('Cascading Fallback')">Kaskadowe</button>
        <button class="cat-btn" onclick="filterCat('DB Lookup & Rules')">Baza Danych DB</button>
        <button class="cat-btn" onclick="filterCat('System Metadata')">Systemowe</button>
      </div>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th style="width: 50px;">#</th>
          <th>Nazwa Pola Basware</th>
          <th>Parametr XML</th>
          <th>Typ Logiki</th>
          <th>Wyrażenie Źródłowe / Warunek</th>
        </tr>
      </thead>
      <tbody id="matrixTbody"></tbody>
    </table>

    <!-- Powiązane Pola poza NewInvoice -->
    <h2 class="section-title"><i data-lucide="layers"></i> Powiązane Identyfikatory Obiektu Faktury poza NewInvoice</h2>
    <table class="data-table">
      <thead>
        <tr>
          <th style="width: 50px;">#</th>
          <th>Nazwa Pola / Funkcji</th>
          <th>Parametr Integracji</th>
          <th>Typ Logiki</th>
          <th>Kluczowa Logika Biznesowa</th>
        </tr>
      </thead>
      <tbody id="companionTbody"></tbody>
    </table>

    <!-- Krytyczne Pułapki Wdrożeniowe -->
    <h2 class="section-title"><i data-lucide="alert-triangle"></i> Krytyczne Zależności i Pułapki Wdrożeniowe</h2>
    <div class="traps-grid">
      <div class="trap-card">
        <h4><i data-lucide="file-warning"></i> Text15 w Basware oznacza Tax Code 2</h4>
        <p style="font-size: 0.9rem; color: var(--text-muted);">Mimo że nazwa parametru w kodzie XML to <code>Text15</code>, w systemie Basware jest to pole zarezerwowane dla <strong>Tax Code 2</strong>. Skrypt przypisuje tam oryginalną nazwę pliku wejściowego <code>{{v,file_name}}</code>.</p>
      </div>
      <div class="trap-card">
        <h4><i data-lucide="building-2"></i> Usunięcie zamówienia dla wybranych spółek</h4>
        <p style="font-size: 0.9rem; color: var(--text-muted);">Dla spółek <code>TAB</code>, <code>HAL7</code>, <code>HAL8</code>, <code>THAB</code>, <code>TREASURY</code> oraz <code>TIND</code> numer zamówienia PO jest celowo czyszczony w sekcji <code>CheckRemoveOrderNumber</code>.</p>
      </div>
      <div class="trap-card">
        <h4><i data-lucide="shield-alert"></i> Flaga Payment Denied w dostawcach</h4>
        <p style="font-size: 0.9rem; color: var(--text-muted);">Podczas wyszukiwania dostawcy po lokalnym identyfikatorze podatkowym (Krok 4), skrypt wymaga parametru <code>SUP.PAYMENT_DENIED = 0</code>. Zablokowani dostawcy są ignorowani.</p>
      </div>
    </div>

    <footer class="footer-note">
      <p>Specyfikacja wygenerowana automatycznie ze skryptu integracyjnego Basware BT Import w języku Python.</p>
    </footer>
  </div>

  <script>
    const FIELDS_DATA = {fields_json};
    const COMPANION_DATA = {companion_json};

    const FLOW_DATA = {{
      supplierId: {{
        title: "Kaskada 7-stopniowego wyznaczania SupplierID",
        nodes: [
          {{ id: "s1", title: "1. Kod Dostawcy z XML", desc: "Sprawdzenie PAYEE/CUSTOMER_INFORMATION/CUSTOMER_ID w tabeli ADM_SUPPLIER po CODE." }},
          {{ id: "s2", title: "2. Party ID (Net Service)", desc: "Wyszukanie w ADM_SUPPLIER_IDENTIFIER po kluczu Sup_Party_ID." }},
          {{ id: "s3", title: "3. Oczyszczony NIP / VAT", desc: "Przeszukiwanie po numerze VAT bez spacji i myślników w ADM_SUPPLIER_IDENTIFIER." }},
          {{ id: "s4", title: "4. Local Tax ID", desc: "Szukanie po Supplier_Local_Tax_ID przy warunku PAYMENT_DENIED = 0." }},
          {{ id: "s5", title: "5. Dopasowanie Waluty", desc: "Wyszukanie po Party ID z uwzględnieniem waluty faktury CURRENCY_CODE." }},
          {{ id: "s6", title: "6. Konta Bankowe BBAN/IBAN", desc: "Przeszukiwanie bazy kont ADM_SUPPLIER_BANK_ACCOUNT." }},
          {{ id: "s7", title: "7. Fallback z Zamówienia PO", desc: "Odczyt INVOICING_SUPPLIER_ID z tabeli OM_ORDER_DATA po numerze PO." }}
        ]
      }},
      orderNumber: {{
        title: "Logika ustalania i czyszczenia OrderNumber",
        nodes: [
          {{ id: "o1", title: "1. Sprawdzenie Spółki", desc: "Wykluczenie zamówień dla spółek TAB, HAL7, HAL8, THAB, TREASURY, TIND." }},
          {{ id: "o2", title: "2. Priorytet Nagłówka", desc: "Odczyt zamówień w sekwencji: Typ CO ➔ Typ non-VN ➔ Typ VN ➔ INVOICE_ORDER_NUMBER." }},
          {{ id: "o3", title: "3. Scalanie z Pozycji", desc: "Jeśli brak w nagłówku: Pętla po wierszach LoopLineItems i zbieranie unikalnych numerów PO po przecinku." }},
          {{ id: "o4", title: "4. Obcinanie Prefiksów", desc: "Obcinanie numeru zamówienia do 8 znaków dla spółek amerykańskich (TSSUS52)." }}
        ]
      }},
      referencePerson: {{
        title: "Kaskada wyznaczania osoby kontaktowej (ReferencePerson)",
        nodes: [
          {{ id: "r1", title: "1. BuyerReference", desc: "Pobranie z nagłówka //HEADER/BUYER_REFERENCE. Weryfikacja LEN > 1." }},
          {{ id: "r2", title: "2. ContactReference", desc: "Fallback jeśli BuyerRef < 2 znaki: //RECEIVER/.../CONTACT_PERSON." }},
          {{ id: "r3", title: "3. ContactPerson", desc: "Fallback jeśli ContactRef < 2 znaki: //ORDERER/.../CONTACT_PERSON." }},
          {{ id: "r4", title: "4. Pusta wartość", desc: "Jeśli żaden warunek nie został spełniony: przypisanie wartości pustej." }}
        ]
      }},
      taxCode: {{
        title: "Wyznaczanie kodów podatkowych TaxCode",
        nodes: [
          {{ id: "t1", title: "1. Pozycje Zamówienia PO", desc: "Odczyt TAX_CODE z pozycji OM_ORDER_ROW (TaxCodeSelectionType = 1)." }},
          {{ id: "t2", title: "2. Różne Kody na PO", desc: "Ustawienie TaxCodeSelectionType = 9 w przypadku wykrycia sporu kodów." }},
          {{ id: "t3", title: "3. Słownik Dostawcy", desc: "Dla faktur bez PO: odczyt z ADM_SUPPLIER_ADDITIONAL_DATA (TaxCodeSelectionType = 2)." }},
          {{ id: "t4", title: "4. Nadpisanie BUSADE020", desc: "Przenumerowanie kodów niemieckich (np. DE21 ➔ DE22, DES6 ➔ DES9)." }}
        ]
      }},
      deliveryDate: {{
        title: "Obsługa daty dostawy DeliveryDate (Date3)",
        nodes: [
          {{ id: "d1", title: "1. Faktury Skanowane", desc: "Odczyt z pola wolnego DeliveryDate, rozbicie po ';', weryfikacja zgodności YYMM i wybór najnowszej daty." }},
          {{ id: "d2", title: "2. E-Faktury", desc: "Odczyt //HEADER/DELIVERY_DATE lub analiza najnowszej daty z pozycji wierszy w pętli." }}
        ]
      }}
    }};

    let currentCat = 'ALL';

    function getBadge(cat) {{
      switch(cat) {{
        case 'Direct XML Mapping': return 'badge-direct';
        case 'Cascading Fallback': return 'badge-cascade';
        case 'DB Lookup & Rules': return 'badge-db';
        case 'System Metadata': return 'badge-sys';
        default: return 'badge-rule';
      }}
    }}

    function renderMatrix() {{
      const q = document.getElementById('searchInput').value.toLowerCase();
      const tbody = document.getElementById('matrixTbody');
      tbody.innerHTML = '';

      const filtered = FIELDS_DATA.filter(f => {{
        const mCat = (currentCat === 'ALL' || f.category === currentCat);
        const mQ = f.baswareName.toLowerCase().includes(q) ||
                   f.param.toLowerCase().includes(q) ||
                   f.sourceExpr.toLowerCase().includes(q) ||
                   f.rulesSummary.toLowerCase().includes(q);
        return mCat && mQ;
      }});

      filtered.forEach(f => {{
        const tr = document.createElement('tr');
        tr.onclick = () => toggleRowDetail(f.order);
        tr.innerHTML = `
          <td style="color: var(--text-muted); font-family: monospace;">${{f.order}}</td>
          <td><strong style="color: var(--text-main);">${{f.baswareName}}</strong></td>
          <td><code>${{f.param}}</code></td>
          <td><span class="badge ${{getBadge(f.category)}}">${{f.category}}</span></td>
          <td>
            <code>${{f.sourceExpr}}</code>
            ${{f.includeCond && f.includeCond !== '(Brak)' ? `<div style="color: var(--accent-amber); font-size: 0.8rem; margin-top:0.2rem;">Cond: <code>${{f.includeCond}}</code></div>` : ''}}
          </td>
        `;
        tbody.appendChild(tr);

        // Row details drawer
        const detailTr = document.createElement('tr');
        detailTr.id = `detail-${{f.order}}`;
        detailTr.style.display = 'none';
        detailTr.innerHTML = `
          <td colspan="5" style="padding:0;">
            <div class="detail-drawer">
              <div>
                <h4 style="color: var(--accent-blue); margin-bottom: 0.5rem;"><i data-lucide="info"></i> Opis Logiki Biznesowej</h4>
                <p>${{f.rulesSummary}}</p>
                ${{f.detailSteps && f.detailSteps.length > 0 ? `<ul style="margin-top:0.5rem; padding-left:1.2rem; color:var(--text-muted);">${{f.detailSteps.map(s => `<li>${{s}}</li>`).join('')}}</ul>` : ''}}
              </div>
              <div>
                ${{f.sqlQueries && f.sqlQueries.length > 0 ? `<h4 style="color: var(--accent-amber); margin-bottom:0.4rem;">Zapytania DB:</h4>${{f.sqlQueries.map(sql => `<code style="display:block; margin-bottom:0.3rem;">${{sql}}</code>`).join('')}}` : ''}}
                ${{f.edgeCases ? `<h4 style="color: var(--accent-red); margin-top:0.5rem; margin-bottom:0.3rem;">Wyjątki:</h4><p style="color: var(--text-muted);">${{f.edgeCases}}</p>` : ''}}
              </div>
            </div>
          </td>
        `;
        tbody.appendChild(detailTr);
      }});

      if (typeof lucide !== 'undefined') lucide.createIcons();
    }}

    function renderCompanion() {{
      const tbody = document.getElementById('companionTbody');
      tbody.innerHTML = '';
      COMPANION_DATA.forEach(c => {{
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td style="color: var(--text-muted); font-family: monospace;">${{c.order}}</td>
          <td><strong style="color: var(--accent-blue);">${{c.baswareName}}</strong></td>
          <td><code>${{c.param}}</code></td>
          <td><span class="badge ${{getBadge(c.category)}}">${{c.category}}</span></td>
          <td>
            <p style="font-size:0.9rem;">${{c.rulesSummary}}</p>
            ${{c.sqlQueries && c.sqlQueries.length > 0 ? `<div style="margin-top:0.4rem;">${{c.sqlQueries.map(s => `<code style="display:block; margin-bottom:0.2rem;">${{s}}</code>`).join('')}}</div>` : ''}}
          </td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    function toggleRowDetail(order) {{
      const row = document.getElementById(`detail-${{order}}`);
      if (row) {{
        row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
      }}
    }}

    function filterCat(cat) {{
      currentCat = cat;
      document.querySelectorAll('.cat-btn').forEach(btn => {{
        btn.classList.toggle('active', btn.innerText.includes(cat) || (cat === 'ALL' && btn.innerText.includes('Wszystkie')));
      }});
      renderMatrix();
    }}

    function renderFlow(flowKey) {{
      const flow = FLOW_DATA[flowKey];
      if (!flow) return;
      
      const canvas = document.getElementById('flowCanvas');
      canvas.innerHTML = '';
      
      flow.nodes.forEach((node, idx) => {{
        const div = document.createElement('div');
        div.className = `flow-node ${{idx === 0 ? 'is-selected' : ''}}`;
        div.onclick = () => selectFlowNode(div, node);
        div.innerHTML = `
          <div class="flow-node-title">${{node.title}}</div>
          <div class="flow-node-desc">${{node.desc}}</div>
        `;
        canvas.appendChild(div);
      }});
      
      // Select first node by default
      selectFlowNode(canvas.children[0], flow.nodes[0]);
    }}

    function selectFlowNode(elem, node) {{
      document.querySelectorAll('.flow-node').forEach(n => n.classList.remove('is-selected'));
      if (elem) elem.classList.add('is-selected');
      
      document.getElementById('flowNodeTitle').innerText = node.title;
      document.getElementById('flowNodeDesc').innerText = node.desc;
    }}

    document.querySelectorAll('.flow-tab').forEach(tab => {{
      tab.onclick = () => {{
        document.querySelectorAll('.flow-tab').forEach(t => t.classList.remove('is-active'));
        tab.classList.add('is-active');
        renderFlow(tab.dataset.flow);
      }};
    }});

    document.getElementById('searchInput').addEventListener('input', renderMatrix);

    document.addEventListener('DOMContentLoaded', () => {{
      renderFlow('supplierId');
      renderMatrix();
      renderCompanion();
      if (typeof lucide !== 'undefined') lucide.createIcons();
    }});
  </script>
</body>
</html>
"""
    return html

def main():
    if len(sys.argv) < 2:
        input_path = "/workspace/knowledge/InvoicePro_Customer_BT_Import_20261030_cleaned.txt"
        if not os.path.exists(input_path):
            print("Usage: python generate_basware_html_spec.py <input_config_file> [output_html_path]")
            sys.exit(1)
    else:
        input_path = sys.argv[1]

    output_path = sys.argv[2] if len(sys.argv) > 2 else "Brak_Treści.html"

    print(f"Parsing configuration file: {input_path}")
    parsed = parse_config_file(input_path)
    fields_data = build_field_data(parsed)
    companion_fields = build_companion_fields()

    print(f"Extracted {len(fields_data)} NewInvoice parameters and {len(companion_fields)} companion fields.")
    html_output = generate_html_spec(fields_data, companion_fields, parsed["raw_content"])

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_output)

    print(f"Successfully generated HTML specification dashboard at: {output_path}")

    # Also sync to /workspace/out/ if in sandbox
    out_path = "Brak_Treści.html"
    try:
        import shutil
        shutil.copy(output_path, out_path)
        print(f"Published artifact to Studio: {out_path}")
    except Exception as e:
        print(f"Note: Could not copy to /workspace/out: {e}")

if __name__ == "__main__":
    main()
