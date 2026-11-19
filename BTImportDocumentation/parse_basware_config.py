#!/usr/bin/env python3
"""
Basware Integration XML Config Parser & Documentation Generator
===============================================================
Automates the reverse-engineering of ERP Connector XML configuration files into
comprehensive, English-language technical documentation and interactive HTML specifications.

Author: Integration Engineering Team
Date: 2026-11-19
"""

import re
import json
import argparse
from pathlib import Path

class BaswareConfigParser:
    def __init__(self, file_path):
        self.file_path = Path(file_path)
        with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
            self.raw_content = f.read()
        self.parameters = []
        self.variables_map = {}

    def parse(self):
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

        # Regex for both standard (<parameter>...</parameter>) and self-closing (<parameter ... />)
        param_regex = re.compile(
            r'<parameter\s+name=["\']([^"\']+)["\']'                      # Group 1: param name
            r'(?:\s+include=["\']([^"\']*)["\'])?'                        # Group 2: include condition
            r'(?:\s*/>|\s*>(.*?)</parameter>)'                             # Group 3: value content (if not self-closing)
            r'(?:\s*<!--\s*(.*?)\s*-->)?',                                # Group 4: inline comment
            re.DOTALL
        )

        for match in param_regex.finditer(method_body):
            param_name = match.group(1)
            include_cond = match.group(2) or ""
            value_expr = (match.group(3) or "").strip()
            comment = (match.group(4) or "").strip()

            # Parse Basware field name from comment
            basware_field = ""
            if "Basware:" in comment:
                basware_field = comment.split("Basware:")[1].strip()
            elif comment:
                basware_field = comment
            else:
                basware_field = param_name

            # Skip technical internal parameters if not mapped to Basware business fields
            if param_name in ["InstanceName", "debug", "RemovalReason"] and not comment:
                continue

            # Determine Logic Type Category
            logic_type = self._classify_logic_type(value_expr, include_cond, basware_field)

            self.parameters.append({
                "param_name": param_name,
                "basware_field": basware_field,
                "value_expr": value_expr,
                "include_condition": include_cond,
                "raw_comment": comment,
                "logic_type": logic_type
            })

    def _classify_logic_type(self, val_expr, include_cond, basware_field):
        """Classifies mapping into standard categories for business analysis."""
        if "DBSELECT" in val_expr or "DBSELECT" in include_cond:
            return "DB Lookup & Rules"
        elif "Check" in basware_field or "Reference Person" in basware_field or "Order Number" in basware_field:
            return "Cascading Fallback"
        elif val_expr.startswith("{v,") and val_expr.endswith("}") and not include_cond:
            return "Direct XML Mapping"
        elif "file_name" in val_expr or "BLOCK_ID" in val_expr or "skiprule" in val_expr:
            return "System Metadata"
        else:
            return "Business Rule / Conditional"

    def generate_markdown(self, output_file=None):
        """Generates a structured English Markdown documentation file."""
        md = []
        md.append("# Basware ERP Connector Field Mapping Specification\n")
        md.append("This document outlines the field extraction and determination rules for the **NewInvoice** integration section.\n")
        md.append("| # | Basware Field Name | Technical Parameter | Logic Type | Mapping Expression | Condition / Rule |")
        md.append("|---|---|---|---|---|---|")

        for idx, p in enumerate(self.parameters, 1):
            expr = f"`{p['value_expr']}`" if p['value_expr'] else "*Empty*"
            cond = f"`{p['include_condition']}`" if p['include_condition'] else "None"
            md.append(f"| {idx} | **{p['basware_field']}** | `{p['param_name']}` | {p['logic_type']} | {expr} | {cond} |")

        md_content = "\n".join(md)
        if output_file:
            Path(output_file).write_text(md_content, encoding='utf-8')
        return md_content

    def generate_html(self, output_file=None):
        """Generates an interactive, responsive English HTML documentation panel."""
        params_json = json.dumps(self.parameters, indent=2)
        
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Basware Integration Field Specification</title>
    <style>
        :root {{
            --bg-primary: #0f172a;
            --bg-card: #1e293b;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-blue: #38bdf8;
            --accent-purple: #c084fc;
            --accent-green: #4ade80;
            --accent-amber: #fbbf24;
            --border-color: #334155;
        }}

        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
        body {{ background-color: var(--bg-primary); color: var(--text-main); padding: 2rem; line-height: 1.6; }}

        .header {{ margin-bottom: 2rem; text-align: center; }}
        .header h1 {{ font-size: 2.2rem; color: var(--accent-blue); margin-bottom: 0.5rem; }}
        .header p {{ color: var(--text-muted); font-size: 1.1rem; }}

        .controls {{ display: flex; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; justify-content: space-between; }}
        .search-box {{ flex: 1; min-width: 300px; }}
        .search-box input {{
            width: 100%; padding: 0.75rem 1rem; border-radius: 8px; border: 1px solid var(--border-color);
            background: var(--bg-card); color: var(--text-main); font-size: 1rem; outline: none;
        }}
        .search-box input:focus {{ border-color: var(--accent-blue); box-shadow: 0 0 8px rgba(56, 189, 248, 0.3); }}

        .filter-buttons {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
        .filter-btn {{
            padding: 0.6rem 1rem; border-radius: 6px; border: 1px solid var(--border-color);
            background: var(--bg-card); color: var(--text-muted); cursor: pointer; font-size: 0.9rem; transition: all 0.2s;
        }}
        .filter-btn.active, .filter-btn:hover {{ background: var(--accent-blue); color: #000; font-weight: bold; border-color: var(--accent-blue); }}

        .stats-bar {{ display: flex; gap: 1.5rem; margin-bottom: 1.5rem; font-size: 0.95rem; color: var(--text-muted); }}
        .stat-item {{ background: var(--bg-card); padding: 0.5rem 1rem; border-radius: 6px; border: 1px solid var(--border-color); }}

        table {{ width: 100%; border-collapse: collapse; background: var(--bg-card); border-radius: 10px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }}
        th, td {{ padding: 1rem; text-align: left; border-bottom: 1px solid var(--border-color); }}
        th {{ background: #162032; color: var(--accent-blue); font-weight: 600; font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.5px; }}
        tr:hover {{ background-color: rgba(255,255,255,0.03); }}

        .badge {{ display: inline-block; padding: 0.25rem 0.6rem; border-radius: 4px; font-size: 0.8rem; font-weight: 600; }}
        .badge-direct {{ background: rgba(74, 222, 128, 0.15); color: var(--accent-green); border: 1px solid var(--accent-green); }}
        .badge-cascade {{ background: rgba(192, 132, 252, 0.15); color: var(--accent-purple); border: 1px solid var(--accent-purple); }}
        .badge-db {{ background: rgba(251, 191, 36, 0.15); color: var(--accent-amber); border: 1px solid var(--accent-amber); }}
        .badge-sys {{ background: rgba(56, 189, 248, 0.15); color: var(--accent-blue); border: 1px solid var(--accent-blue); }}

        code {{ font-family: 'Courier New', Courier, monospace; background: rgba(0,0,0,0.4); padding: 0.2rem 0.4rem; border-radius: 4px; color: #e2e8f0; font-size: 0.9rem; }}
        .condition-text {{ color: var(--accent-amber); font-size: 0.85rem; margin-top: 0.3rem; display: block; }}
    </style>
</head>
<body>

    <div class="header">
        <h1>Basware Field Mapping Specification</h1>
        <p>Interactive reverse-engineered documentation for <code>NewInvoice</code> integration method</p>
    </div>

    <div class="controls">
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="Search Basware field name, XML parameter, or variable...">
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
                <th style="width: 50px;">#</th>
                <th>Basware Field Name</th>
                <th>XML Parameter</th>
                <th>Category</th>
                <th>Value Mapping / Expression</th>
            </tr>
        </thead>
        <tbody id="paramsTableBody"></tbody>
    </table>

    <script>
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
                const condHtml = item.include_condition ? `<span class="condition-text">Condition: <code>${{item.include_condition}}</code></span>` : '';
                const valueHtml = item.value_expr ? `<code>${{item.value_expr}}</code>` : '<em style="color:#64748b">None / Empty</em>';

                row.innerHTML = `
                    <td style="color: var(--text-muted);">${{index + 1}}</td>
                    <td><strong style="color: var(--text-main); font-size: 1.05rem;">${{item.basware_field}}</strong></td>
                    <td><code>${{item.param_name}}</code></td>
                    <td><span class="badge ${{getBadgeClass(item.logic_type)}}">${{item.logic_type}}</span></td>
                    <td>${{valueHtml}}${{condHtml}}</td>
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
                                      item.include_condition.toLowerCase().includes(query);
                return matchesCat && matchesSearch;
            }});
            renderTable(filtered);
        }}

        document.getElementById('searchInput').addEventListener('input', applyFilters);

        // Initial setup
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
    parser = argparse.ArgumentParser(description="Parse Basware Integration XML and generate documentation.")
    parser.add_argument("input_file", help="Path to the XML / TXT integration configuration file")
    parser.add_argument("--output_html", default="basware_spec.html", help="Path for HTML output")
    parser.add_argument("--output_md", default="basware_spec.md", help="Path for Markdown output")
    
    args = parser.parse_args()

    config_parser = BaswareConfigParser(args.input_file)
    result = config_parser.parse()
    
    config_parser.generate_html(args.output_html)
    config_parser.generate_markdown(args.output_md)
    
    print(f"Successfully processed {len(result['parameters'])} parameters.")
    print(f"HTML Specification written to: {args.output_html}")
    print(f"Markdown Specification written to: {args.output_md}")
