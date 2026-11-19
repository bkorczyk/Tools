#!/usr/bin/env python3
"""
Advanced Basware Integration XML Config Parser & Visual Documentation Generator
================================================================================
Automates the reverse-engineering of ERP Connector XML configuration files into
comprehensive, English-language technical documentation, interactive HTML specifications,
and embedded Mermaid.js flowchart diagrams for complex business logic decision trees.

Author: Gemini Notebook Workbench
"""

import re
import json
import argparse
from pathlib import Path

class AdvancedBaswareParser:
    def __init__(self, file_path):
        self.file_path = Path(file_path)
        with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
            self.raw_content = f.read()
        self.parameters = []
        self.variables_map = {}

    def parse(self):
        """Main parsing entry point."""
        self._extract_variables()
        self._extract_new_invoice_params()
        return {
            "parameters": self.parameters,
            "variables_map": self.variables_map
        }

    def _extract_variables(self):
        """Extracts variable definitions across the script to trace data sources."""
        var_pattern = re.compile(
            r'<variable\s+name=["\']([^"\']+)["\'](?:\s+include=["\']([^"\']*)["\'])?[^>]*>(.*?)</variable>',
            re.DOTALL
        )
        for match in var_pattern.finditer(self.raw_content):
            var_name = match.group(1)
            include_cond = match.group(2) or ""
            val_expr = match.group(3).strip()
            
            if var_name not in self.variables_map:
                self.variables_map[var_name] = []
            self.variables_map[var_name].append({
                "expression": val_expr,
                "condition": include_cond
            })

    def _extract_new_invoice_params(self):
        """Extracts parameters inside the NewInvoice method block."""
        method_match = re.search(r'<method name="NewInvoice"[^>]*>(.*?)</method>', self.raw_content, re.DOTALL)
        if not method_match:
            print("[Warning] Could not find method name='NewInvoice' block.")
            return

        method_body = method_match.group(1)

        param_regex = re.compile(
            r'<parameter\s+name=["\']([^"\']+)["\']'                      # Group 1: Parameter Name
            r'(?:\s+include=["\']([^"\']*)["\'])?'                        # Group 2: Include Condition
            r'(?:\s*/>|\s*>(.*?)</parameter>)'                             # Group 3: Parameter Value
            r'(?:\s*<!--\s*(.*?)\s*-->)?',                                # Group 4: Inline Comment
            re.DOTALL
        )

        for match in param_regex.finditer(method_body):
            param_name = match.group(1)
            include_cond = match.group(2) or ""
            value_expr = (match.group(3) or "").strip()
            comment = (match.group(4) or "").strip()

            basware_field = ""
            if "Basware:" in comment:
                basware_field = comment.split("Basware:")[1].strip()
            elif comment:
                basware_field = comment
            else:
                basware_field = param_name

            if param_name in ["InstanceName", "debug", "RemovalReason"] and not comment:
                continue

            logic_type = self._classify_logic_type(value_expr, include_cond, basware_field, param_name)

            self.parameters.append({
                "param_name": param_name,
                "basware_field": basware_field,
                "value_expr": value_expr,
                "include_condition": include_cond,
                "raw_comment": comment,
                "logic_type": logic_type,
                "description": self._get_field_description(basware_field, param_name)
            })

    def _classify_logic_type(self, val_expr, include_cond, basware_field, param_name):
        """Classifies mapping logic into business categories."""
        if "DBSELECT" in val_expr or "DBSELECT" in include_cond:
            return "DB Lookup & Rules"
        elif basware_field in ["Reference Person", "Order Number", "Delivery Date", "Supplier ID"] or param_name in ["ReferencePerson", "OrderNumber", "Date3"]:
            return "Cascading Fallback"
        elif val_expr.startswith("{v,") and val_expr.endswith("}") and not include_cond:
            return "Direct XML Mapping"
        elif "file_name" in val_expr or "BLOCK_ID" in val_expr or "skiprule" in val_expr:
            return "System Metadata"
        else:
            return "Business Rule / Conditional"

    def _get_field_description(self, basware_field, param_name):
        """Returns English narrative descriptions for specific Basware fields."""
        descriptions = {
            "Supplier ID": "Determined via a 7-step priority cascade (XML Code -> Party ID -> Cleaned VAT -> Local Tax ID -> Currency -> Bank BBAN/IBAN -> Order PO Fallback).",
            "Order Number": "Extracted from XML header (CO -> Non-VN -> VN -> INVOICE_ORDER_NUMBER) or concatenated from line items. Filtered for specific company codes and logistic suppliers.",
            "Reference Person": "Selected via priority chain: BuyerReference -> ContactReference -> ContactPerson -> Empty (min length >= 2 chars).",
            "Delivery Date": "For Scanned invoices: extracted from free text, validated by YYMM match across lines. For E-Invoices: header date compared with line item delivery dates.",
            "Invoice Due Date": "Pulls due date from XML. Defaults to current system date if omitted.",
            "TaxCode": "Matched against Purchase Order rows in ERP (OM_ORDER_DATA). Falls back to Supplier Master default (TaxCodes). Special handling for BUSADE020.",
            "AP Status": "Pulls supplier AP status from EXT_INV_LIST_17 table if C_109 configuration is enabled for the company.",
            "Auto Send to Process": "Determined by checking AUTOSENDTOPROCESSSUPPLIER entries in EXT_INV_LIST_17 by company, supplier, and invoice type. Returns 2 (auto-send) or 1 (manual).",
            "Additional Data 1": "Populated from company division and entity-specific additional data configuration.",
            "Tax Code 2": "Populated with the source XML filename for audit tracking."
        }
        return descriptions.get(basware_field, "Mapped from invoice variable / XML source according to standard ERP connector rules.")

    def get_mermaid_diagrams(self):
        """Returns Mermaid diagram syntax for all major decision trees."""
        diagrams = {
            "supplier_id": """graph TD
    A[Start: Determine Supplier ID] --> B{Step 1: Check XML Supplier Code<br>CUSTOMER_ID in ADM_SUPPLIER?}
    B -- Found (Count=1) --> S[Set SupplierId & Exit]
    B -- Not Found --> C{Step 2: Check Network Party ID<br>VAT_NUMBER / NET_SERVICE_ID in ADM_SUPPLIER_IDENTIFIER?}
    C -- Found (Count=1) --> S
    C -- Not Found --> D{Step 3: Check Cleaned VAT/NIP<br>SupplierVatNumber in ADM_SUPPLIER_IDENTIFIER?}
    D -- Found (Count=1) --> S
    D -- Not Found --> E{Step 4: Check Local Tax ID<br>LocalSupplierTaxID & PAYMENT_DENIED=0?}
    E -- Found (Count=1) --> S
    E -- Not Found --> F{Step 5: Check Party ID + Invoice Currency<br>CURRENCY_CODE match?}
    F -- Found (Count=1) --> S
    F -- Not Found --> G{Step 6: Check Bank Account<br>BBAN or IBAN in ADM_SUPPLIER_BANK_ACCOUNT?}
    G -- Found (Count=1) --> S
    G -- Not Found --> H{Step 7: PO Fallback<br>Query OM_ORDER_DATA by OrderNumber}
    H -- Found & Logistic Filter Passed --> S
    H -- Not Found --> X[Supplier Unresolved / Error]""",

            "order_number": """graph TD
    A[Start: Determine Order Number] --> B{Check Company Exclusions<br>TAB, HAL7, THAB, TREASURY, TIND?}
    B -- Yes --> C[Clear OrderNumber]
    B -- No --> D{Header Order Number Available?}
    D -- Type CO --> E[Use Header CO Order]
    D -- Type Non-VN --> F[Use Header Non-VN Order]
    D -- Type VN --> G[Use Header VN Order]
    D -- Generic INVOICE_ORDER_NUMBER --> H[Use INVOICE_ORDER_NUMBER]
    D -- None Found in Header --> I[Loop Invoice Line Items]
    I --> J[Collect & Deduplicate Row ORDER_NUMBERs]
    J --> K[Concatenate with Commas]
    E & F & G & H & K --> L{Check Company Suffix<br>TSSUS52 / TSSUS262?}
    L -- Yes --> M[Truncate to First 8 Chars]
    L -- No --> N{Logistic Supplier Check<br>Order Supplier != Identified Supplier?}
    M --> N
    N -- Conflict Found --> C
    N -- Passed --> O[Final OrderNumber Output]""",

            "reference_person": """graph TD
    A[Start: Determine Reference Person] --> B{Check BuyerReference<br>TRIM LEN >= 2?}
    B -- Yes --> C[Assign ReferencePerson = BuyerReference]
    B -- No --> D{Check ContactReference<br>TRIM LEN >= 2?}
    D -- Yes --> E[Assign ReferencePerson = ContactReference]
    D -- No --> F{Check ContactPerson<br>TRIM LEN >= 2?}
    F -- Yes --> G[Assign ReferencePerson = ContactPerson]
    F -- No --> H[Assign ReferencePerson = Empty String]""",

            "delivery_date": """graph TD
    A[Start: Determine Delivery Date] --> B{Invoice Source Type?}
    B -- Scanned Invoice --> C[Extract FREE_TEXT DeliveryDate]
    C --> D[Split Multiple Dates by Semicolon]
    D --> E{Validate Year-Month Match across Lines}
    E -- YYMM Match Valid --> F[Take Latest Day]
    E -- YYMM Mismatch --> G[Discard Delivery Date]
    B -- E-Invoice --> H[Extract Header DELIVERY_DATE]
    H --> I[Loop Article Line Items & Compare Line Dates]
    I --> J{Check Year-Month Uniformity}
    J -- Valid --> K[Take Latest Delivery Date]
    J -- Invalid --> L[Use Header Date Only]""",

            "tax_code": """graph TD
    A[Start: Determine Tax Code] --> B{Is Order Number Available?}
    B -- Yes (PO Invoice) --> C[Query OM_ORDER_DATA & OM_ORDER_ROW]
    C --> D{Do all line items share same TAX_CODE?}
    D -- Yes --> E[Assign TaxCode & Set TaxCodeSelectionType = 1]
    D -- Mixed Tax Codes --> F[Set TaxCodeSelectionType = 9 & Clear Header TaxCode]
    B -- No (Non-PO Invoice) --> G[Query ADM_SUPPLIER_ADDITIONAL_DATA for TaxCodes]
    G --> H{TaxCode Found?}
    H -- Yes --> I[Assign TaxCode & Set TaxCodeSelectionType = 2]
    H -- No --> J[Leave TaxCode Empty]
    E & F & I --> K{Check Company Special Rules<br>BUSADE020?}
    K -- DE21 / DES6 / DEW6 --> L[Remap to DE22 / DES9 / DEW9]
    K -- Other / None --> M[Final TaxCode Output]"""
        }
        return diagrams

    def generate_markdown(self, output_file=None):
        """Generates comprehensive English Markdown documentation with embedded Mermaid diagrams."""
        md = []
        md.append("# Basware ERP Connector Field Mapping & Logic Specification\n")
        md.append("This technical document details the field extraction, decision trees, and determination rules for the **NewInvoice** integration process.\n")
        
        md.append("## 1. Executive Summary & Processing Architecture\n")
        md.append("The integration engine processes incoming invoice XML files through four primary operational categories:\n")
        md.append("- **Direct XML Mapping**: Direct 1:1 extraction from XML nodes.\n")
        md.append("- **Cascading Fallback**: Sequential evaluation across multiple potential sources until a match is confirmed.\n")
        md.append("- **DB Lookup & Rules**: Dynamic SQL queries against ERP master tables (`ADM_SUPPLIER`, `OM_ORDER_DATA`, `EXT_INV_LIST_17`).\n")
        md.append("- **System Metadata**: Injection of runtime metadata (filenames, scan IDs, skip flags).\n\n")

        md.append("## 2. Visual Business Logic Decision Trees (Flowcharts)\n")
        diagrams = self.get_mermaid_diagrams()
        
        md.append("### 2.1. Supplier ID Determination Cascade (7-Step Priority)")
        md.append("```mermaid\n" + diagrams["supplier_id"] + "\n```\n")

        md.append("### 2.2. Order Number Extraction & Filtering Flow")
        md.append("```mermaid\n" + diagrams["order_number"] + "\n```\n")

        md.append("### 2.3. Reference Person Selection Priority")
        md.append("```mermaid\n" + diagrams["reference_person"] + "\n```\n")

        md.append("### 2.4. Delivery Date Processing Logic")
        md.append("```mermaid\n" + diagrams["delivery_date"] + "\n```\n")

        md.append("### 2.5. Tax Code Determination & PO Matching")
        md.append("```mermaid\n" + diagrams["tax_code"] + "\n```\n")

        md.append("## 3. Comprehensive Field Mapping Matrix\n")
        md.append("| # | Basware Field Name | Technical Parameter | Logic Category | Value Mapping Expression | Condition / Business Rule | Description & Behavior |")
        md.append("|---|---|---|---|---|---|---|")

        for idx, p in enumerate(self.parameters, 1):
            expr = f"`{p['value_expr']}`" if p['value_expr'] else "*Empty*"
            cond = f"`{p['include_condition']}`" if p['include_condition'] else "None"
            desc = p['description'].replace("\n", " ")
            md.append(f"| {idx} | **{p['basware_field']}** | `{p['param_name']}` | {p['logic_type']} | {expr} | {cond} | {desc} |")

        md_content = "\n".join(md)
        if output_file:
            Path(output_file).write_text(md_content, encoding='utf-8')
        return md_content

    def generate_html(self, output_file=None):
        """Generates an interactive English HTML documentation page with Mermaid rendering and live filters."""
        params_json = json.dumps(self.parameters, indent=2)
        diagrams = self.get_mermaid_diagrams()
        
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Basware ERP Connector Specification & Visual Logic</title>
    <!-- Mermaid.js for rendering flowchart diagrams -->
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <style>
        :root {{
            --bg-primary: #0f172a;
            --bg-card: #1e293b;
            --bg-header: #162032;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-blue: #38bdf8;
            --accent-purple: #c084fc;
            --accent-green: #4ade80;
            --accent-amber: #fbbf24;
            --border-color: #334155;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; }}
        body {{ background-color: var(--bg-primary); color: var(--text-main); padding: 2rem; line-height: 1.6; }}
        .header {{ margin-bottom: 2.5rem; text-align: center; border-bottom: 1px solid var(--border-color); padding-bottom: 1.5rem; }}
        .header h1 {{ font-size: 2.4rem; color: var(--accent-blue); margin-bottom: 0.5rem; }}
        .header p {{ color: var(--text-muted); font-size: 1.1rem; max-width: 800px; margin: 0 auto; }}
        
        .section-title {{ font-size: 1.6rem; color: var(--accent-blue); margin: 2rem 0 1rem 0; display: flex; align-items: center; gap: 0.5rem; }}
        
        /* Flowchart Container */
        .diagram-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(500px, 1fr)); gap: 1.5rem; margin-bottom: 2.5rem; }}
        .diagram-card {{ background: var(--bg-card); border-radius: 12px; border: 1px solid var(--border-color); padding: 1.5rem; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }}
        .diagram-card h3 {{ color: var(--accent-purple); margin-bottom: 1rem; font-size: 1.2rem; border-bottom: 1px solid var(--border-color); padding-bottom: 0.5rem; }}
        .mermaid {{ background: #0b1120; border-radius: 8px; padding: 1rem; overflow-x: auto; display: flex; justify-content: center; }}

        /* Interactive Controls */
        .controls {{ display: flex; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; justify-content: space-between; align-items: center; }}
        .search-box {{ flex: 1; min-width: 320px; }}
        .search-box input {{
            width: 100%; padding: 0.8rem 1.2rem; border-radius: 8px; border: 1px solid var(--border-color);
            background: var(--bg-card); color: var(--text-main); font-size: 1rem; outline: none; transition: border-color 0.2s;
        }}
        .search-box input:focus {{ border-color: var(--accent-blue); box-shadow: 0 0 10px rgba(56, 189, 248, 0.25); }}
        .filter-buttons {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
        .filter-btn {{
            padding: 0.6rem 1.1rem; border-radius: 6px; border: 1px solid var(--border-color);
            background: var(--bg-card); color: var(--text-muted); cursor: pointer; font-size: 0.9rem; font-weight: 500; transition: all 0.2s;
        }}
        .filter-btn.active, .filter-btn:hover {{ background: var(--accent-blue); color: #000; font-weight: 700; border-color: var(--accent-blue); }}
        
        .stats-bar {{ display: flex; gap: 1.5rem; margin-bottom: 1.5rem; font-size: 0.95rem; color: var(--text-muted); }}
        .stat-item {{ background: var(--bg-card); padding: 0.6rem 1.2rem; border-radius: 6px; border: 1px solid var(--border-color); }}
        .stat-item strong {{ color: var(--accent-blue); font-size: 1.1rem; }}

        /* Data Table */
        table {{ width: 100%; border-collapse: collapse; background: var(--bg-card); border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.3); margin-bottom: 3rem; }}
        th, td {{ padding: 1.1rem; text-align: left; border-bottom: 1px solid var(--border-color); font-size: 0.95rem; }}
        th {{ background: var(--bg-header); color: var(--accent-blue); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; font-size: 0.85rem; }}
        tr:hover {{ background-color: rgba(255,255,255,0.025); }}
        
        /* Badges & Code */
        .badge {{ display: inline-block; padding: 0.3rem 0.7rem; border-radius: 4px; font-size: 0.8rem; font-weight: 600; white-space: nowrap; }}
        .badge-direct {{ background: rgba(74, 222, 128, 0.15); color: var(--accent-green); border: 1px solid var(--accent-green); }}
        .badge-cascade {{ background: rgba(192, 132, 252, 0.15); color: var(--accent-purple); border: 1px solid var(--accent-purple); }}
        .badge-db {{ background: rgba(251, 191, 36, 0.15); color: var(--accent-amber); border: 1px solid var(--accent-amber); }}
        .badge-sys {{ background: rgba(56, 189, 248, 0.15); color: var(--accent-blue); border: 1px solid var(--accent-blue); }}
        
        code {{ font-family: 'Fira Code', 'Courier New', monospace; background: rgba(0,0,0,0.4); padding: 0.2rem 0.5rem; border-radius: 4px; color: #e2e8f0; font-size: 0.88rem; }}
        .condition-text {{ color: var(--accent-amber); font-size: 0.85rem; margin-top: 0.4rem; display: block; }}
        .desc-text {{ color: var(--text-muted); font-size: 0.9rem; margin-top: 0.3rem; line-height: 1.4; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Basware ERP Connector Technical Specification</h1>
        <p>Comprehensive English specification & reverse-engineered decision trees for the <code>NewInvoice</code> method.</p>
    </div>

    <h2 class="section-title">📌 Business Logic Decision Trees (Flowcharts)</h2>
    <div class="diagram-grid">
        <div class="diagram-card">
            <h3>1. Supplier ID Determination Cascade (7-Step Priority)</h3>
            <div class="mermaid">{diagrams["supplier_id"]}</div>
        </div>
        <div class="diagram-card">
            <h3>2. Order Number Extraction & Filtering Flow</h3>
            <div class="mermaid">{diagrams["order_number"]}</div>
        </div>
        <div class="diagram-card">
            <h3>3. Reference Person Priority Chain</h3>
            <div class="mermaid">{diagrams["reference_person"]}</div>
        </div>
        <div class="diagram-card">
            <h3>4. Delivery Date Processing (Scanned vs E-Invoice)</h3>
            <div class="mermaid">{diagrams["delivery_date"]}</div>
        </div>
        <div class="diagram-card" style="grid-column: 1 / -1;">
            <h3>5. Tax Code Determination & PO Matching</h3>
            <div class="mermaid">{diagrams["tax_code"]}</div>
        </div>
    </div>

    <h2 class="section-title">📋 Field Mapping Matrix & Rule Directory</h2>
    <div class="controls">
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="Search field name, parameter, SQL query, or keyword...">
        </div>
        <div class="filter-buttons">
            <button class="filter-btn active" onclick="filterCategory('ALL')">All Fields</button>
            <button class="filter-btn" onclick="filterCategory('Direct XML Mapping')">Direct XML</button>
            <button class="filter-btn" onclick="filterCategory('Cascading Fallback')">Cascading</button>
            <button class="filter-btn" onclick="filterCategory('DB Lookup & Rules')">DB & Rules</button>
            <button class="filter-btn" onclick="filterCategory('System Metadata')">System</button>
        </div>
    </div>

    <div class="stats-bar">
        <div class="stat-item">Total Parameters: <strong id="totalCount">0</strong></div>
        <div class="stat-item">Visible Parameters: <strong id="visibleCount">0</strong></div>
    </div>

    <table>
        <thead>
            <tr>
                <th style="width: 40px;">#</th>
                <th>Basware Field Name</th>
                <th>XML Parameter</th>
                <th>Category</th>
                <th>Mapping Expression & Conditions</th>
                <th>Description & Business Behavior</th>
            </tr>
        </thead>
        <tbody id="paramsTableBody"></tbody>
    </table>

    <script>
        mermaid.initialize({{ startOnLoad: true, theme: 'dark' }});

        const paramsData = {params_json};

        function getBadgeClass(category) {{
            switch(category) {{
                case 'Direct XML Mapping': return 'badge-direct';
                case 'Cascading Fallback': return 'badge-cascade';
                case 'DB Lookup & Rules': return 'badge-db';
                case 'System Metadata': return 'badge-sys';
                default: return 'badge-sys';
            }}
        }}

        function renderTable(data) {{
            const tbody = document.getElementById('paramsTableBody');
            tbody.innerHTML = '';
            data.forEach((item, index) => {{
                const row = document.createElement('tr');
                const condHtml = item.include_condition ? `<span class="condition-text">Include Condition: <code>${{item.include_condition}}</code></span>` : '';
                const valueHtml = item.value_expr ? `<code>${{item.value_expr}}</code>` : '<em style="color:#64748b">None / Empty</em>';

                row.innerHTML = `
                    <td style="color: var(--text-muted);">${{index + 1}}</td>
                    <td><strong style="color: var(--text-main); font-size: 1.05rem;">${{item.basware_field}}</strong></td>
                    <td><code>${{item.param_name}}</code></td>
                    <td><span class="badge ${{getBadgeClass(item.logic_type)}}">${{item.logic_type}}</span></td>
                    <td>${{valueHtml}}${{condHtml}}</td>
                    <td><div class="desc-text">${{item.description}}</div></td>
                `;
                tbody.appendChild(row);
            }});
            document.getElementById('visibleCount').innerText = data.length;
        }}

        let currentCategory = 'ALL';
        function filterCategory(cat) {{
            currentCategory = cat;
            document.querySelectorAll('.filter-btn').forEach(btn => {{
                btn.classList.toggle('active', btn.innerText.includes(cat) || (cat === 'ALL' && btn.innerText.includes('All')));
            }});
            applyFilters();
        }}

        function applyFilters() {{
            const query = document.getElementById('searchInput').value.toLowerCase();
            const filtered = paramsData.filter(item => {{
                const matchesCat = (currentCategory === 'ALL' || item.logic_type === currentCategory);
                const matchesSearch = item.basware_field.toLowerCase().includes(query) ||
                                      item.param_name.toLowerCase().includes(query) ||
                                      item.value_expr.toLowerCase().includes(query) ||
                                      item.include_condition.toLowerCase().includes(query) ||
                                      item.description.toLowerCase().includes(query);
                return matchesCat && matchesSearch;
            }});
            renderTable(filtered);
        }}

        document.getElementById('searchInput').addEventListener('input', applyFilters);
        document.getElementById('totalCount').innerText = paramsData.length;
        renderTable(paramsData);
    </script>
</body>
</html>
"""
        if output_file:
            Path(output_file).write_text(html_content, encoding='utf-8')
        return html_content

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse Basware Integration XML and generate comprehensive documentation.")
    parser.add_argument("input_file", help="Path to the XML / TXT integration configuration file")
    parser.add_argument("--output_html", default="basware_spec.html", help="Path for HTML output")
    parser.add_argument("--output_md", default="basware_spec.md", help="Path for Markdown output")
    
    args = parser.parse_args()

    config_parser = AdvancedBaswareParser(args.input_file)
    result = config_parser.parse()
    
    config_parser.generate_html(args.output_html)
    config_parser.generate_markdown(args.output_md)
    
    print(f"[Success] Processed {len(result['parameters'])} parameters.")
    print(f"HTML Specification generated: {args.output_html}")
    print(f"Markdown Specification generated: {args.output_md}")
