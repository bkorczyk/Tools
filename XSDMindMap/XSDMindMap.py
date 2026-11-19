import sys
import io
from flask import Flask, jsonify, render_template_string, request
import xmlschema

app = Flask(__name__)

# Globalna zmienna do przechowywania aktualnie załadowanego schematu XSD
CURRENT_SCHEMA = None
CURRENT_FILENAME = None

def get_clean_name(name):
    if not name:
        return ""
    if '}' in name:
        return name.split('}', 1)[1]
    return name

def get_root_element():
    """Szuka głównego elementu w załadowanym schemacie."""
    if not CURRENT_SCHEMA:
        return None

    # 1. Próba znalezienia w elements
    if CURRENT_SCHEMA.elements:
        for key, el in CURRENT_SCHEMA.elements.items():
            clean = get_clean_name(key)
            if "INVOICE" in clean.upper() or "ROOT" in clean.upper() or "DOCUMENT" in clean.upper():
                return el
        return list(CURRENT_SCHEMA.elements.values())[0]

    # 2. Szukanie w typach złożonych (ComplexTypes)
    if CURRENT_SCHEMA.types:
        for key, t in CURRENT_SCHEMA.types.items():
            clean = get_clean_name(key)
            if "INVOICE" in clean.upper() or "DOCUMENT" in clean.upper():
                return t
        return list(CURRENT_SCHEMA.types.values())[0]
        
    return None

def iter_element_children(element):
    """Wyciąga potomków niezależnie od tego czy obiekt to Element czy ComplexType."""
    children = []
    target = getattr(element, 'type', element)
    
    if hasattr(target, 'content') and target.content is not None:
        try:
            for child in target.content.iter_elements():
                children.append(child)
        except Exception:
            pass

    if not children and hasattr(target, 'iter_elements'):
        try:
            for child in target.iter_elements():
                if child != element:
                    children.append(child)
        except Exception:
            pass

    return children

def find_element_by_path(path):
    parts = path.split("/")
    root_el = get_root_element()
    if not root_el:
        return None
        
    root_name = get_clean_name(getattr(root_el, 'local_name', None) or getattr(root_el, 'name', ''))
    if root_name != parts[0]:
        return None
        
    current = root_el
    for part in parts[1:]:
        found = False
        children = iter_element_children(current)
        for child in children:
            child_name = get_clean_name(getattr(child, 'local_name', None) or getattr(child, 'name', ''))
            if child_name == part:
                current = child
                found = True
                break
        if not found:
            return None
            
    return current

def extract_children(element, parent_path):
    children = []
    seen_names = set()

    raw_children = iter_element_children(element)
    
    for child in raw_children:
        child_name = get_clean_name(getattr(child, 'local_name', None) or getattr(child, 'name', ''))
        if not child_name or child_name in seen_names:
            continue
            
        seen_names.add(child_name)
        child_path = f"{parent_path}/{child_name}"
        
        sub_children = iter_element_children(child)
        has_sub = len(sub_children) > 0
        
        children.append({
            "id": child_path,
            "label": child_name,
            "hasChildren": has_sub
        })
            
    return children

@app.route('/api/upload', methods=['POST'])
def api_upload():
    """Endpoint do przesyłania pliku XSD z poziomu przeglądarki."""
    global CURRENT_SCHEMA, CURRENT_FILENAME
    
    if 'file' not in request.files:
        return jsonify({"error": "Brak pliku w żądaniu"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nie wybrano pliku"}), 400
        
    try:
        content = file.read().decode('utf-8')
        CURRENT_SCHEMA = xmlschema.XMLSchema(io.StringIO(content))
        CURRENT_FILENAME = file.filename
        
        root_el = get_root_element()
        if not root_el:
            return jsonify({"error": "Plik XSD nie zawiera prawidłowych elementów ani typów."}), 400
            
        root_name = get_clean_name(getattr(root_el, 'local_name', None) or getattr(root_el, 'name', ''))
        sub_children = iter_element_children(root_el)
        
        return jsonify({
            "filename": CURRENT_FILENAME,
            "root": {
                "id": root_name,
                "label": root_name,
                "hasChildren": len(sub_children) > 0
            }
        })
    except Exception as e:
        return jsonify({"error": f"Błąd parsowania XSD: {str(e)}"}), 500

@app.route('/api/root')
def api_root():
    if not CURRENT_SCHEMA:
        return jsonify({"error": "Brak załadowanego schematu XSD"}), 404
        
    root_el = get_root_element()
    if not root_el:
        return jsonify({"error": "Brak elementów w pliku XSD"}), 404
        
    root_name = get_clean_name(getattr(root_el, 'local_name', None) or getattr(root_el, 'name', ''))
    sub_children = iter_element_children(root_el)

    return jsonify({
        "id": root_name,
        "label": root_name,
        "hasChildren": len(sub_children) > 0
    })

@app.route('/api/children/<path:node_path>')
def api_children(node_path):
    if not CURRENT_SCHEMA:
        return jsonify([])
        
    element = find_element_by_path(node_path)
    if not element:
        return jsonify([])
        
    children = extract_children(element, node_path)
    return jsonify(children)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <title>Dynamiczna Mapa Myśli XSD</title>
  <script src="https://d3js.org/d3.v7.min.js"></script>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; margin: 0; background: #f8f9fa; overflow: hidden; }
    
    /* Panel uploadu */
    #upload-overlay {
      position: absolute; top: 0; left: 0; width: 100vw; height: 100vh;
      background: rgba(248, 249, 250, 0.95); z-index: 100;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
    }
    
    .drop-zone {
      border: 2px dashed #007bff; border-radius: 12px; padding: 40px 60px;
      text-align: center; background: white; cursor: pointer; transition: all 0.2s;
      box-shadow: 0 4px 12px rgba(0,0,0,0.05);
    }
    .drop-zone:hover, .drop-zone.dragover { background: #e9ecef; border-color: #0056b3; }
    .drop-zone p { margin: 0 0 12px 0; font-size: 16px; color: #495057; }
    .drop-zone input { display: none; }
    .btn-upload {
      background: #007bff; color: white; border: none; padding: 10px 20px;
      border-radius: 6px; font-weight: 500; cursor: pointer;
    }
    .btn-upload:hover { background: #0056b3; }

    /* Pasek informacyjny w trakcie wizualizacji */
    #info-bar {
      position: absolute; top: 12px; left: 12px; z-index: 10;
      background: white; padding: 8px 16px; border-radius: 6px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.1); display: none; align-items: center; gap: 12px;
      font-size: 14px; color: #333;
    }
    .btn-reset {
      background: #dc3545; color: white; border: none; padding: 4px 10px;
      border-radius: 4px; cursor: pointer; font-size: 12px;
    }
    .btn-reset:hover { background: #bd2130; }

    /* Style grafu D3 */
    .node circle { fill: #fff; stroke: #007bff; stroke-width: 2px; cursor: pointer; }
    .node text { font: 12px sans-serif; }
    .link { fill: none; stroke: #ced4da; stroke-width: 1.5px; }
    .loading { position: absolute; top: 12px; right: 12px; background: rgba(0,0,0,0.7); color: white; padding: 6px 12px; border-radius: 4px; display: none; font-size: 13px; }
    .error-msg { margin-top: 15px; color: #dc3545; font-weight: 500; font-size: 14px; }
  </style>
</head>
<body>

<div id="upload-overlay">
  <div class="drop-zone" id="drop-zone">
    <p>Przeciągnij i upuść plik <strong>.xsd</strong> tutaj</p>
    <p>lub</p>
    <button class="btn-upload" onclick="document.getElementById('file-input').click()">Wybierz plik z dysku</button>
    <input type="file" id="file-input" accept=".xsd">
  </div>
  <div id="upload-error" class="error-msg"></div>
</div>

<div id="info-bar">
  <span>Plik: <strong id="loaded-filename"></strong></span>
  <button class="btn-reset" onclick="resetApp()">Zmień plik XSD</button>
</div>

<div id="loading" class="loading">Ładowanie węzłów z XSD...</div>
<svg width="100vw" height="100vh"></svg>

<script>
  const svg = d3.select("svg");
  const g = svg.append("g").attr("transform", "translate(100,0)");
  svg.call(d3.zoom().on("zoom", (event) => g.attr("transform", event.transform)));

  const treeLayout = d3.tree().nodeSize([30, 220]);
  let root;

  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');

  // Drag & drop handlers
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, preventDefaults, false);
  });
  function preventDefaults(e) { e.preventDefault(); e.stopPropagation(); }

  ['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'), false);
  });
  ['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'), false);
  });

  dropZone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    if (files.length) handleFileUpload(files[0]);
  });

  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length) handleFileUpload(e.target.files[0]);
  });

  function handleFileUpload(file) {
    if (!file.name.endsWith('.xsd')) {
      showUploadError('Proszę wybrać plik z rozszerzeniem .xsd');
      return;
    }

    const formData = new FormData();
    formData.append('file', file);

    showLoading(true);
    showUploadError('');

    fetch('/api/upload', { method: 'POST', body: formData })
      .then(res => res.json().then(data => ({ status: res.status, body: data })))
      .then(res => {
        showLoading(false);
        if (res.status !== 200) {
          throw new Error(res.body.error || 'Błąd wysyłania pliku');
        }
        
        document.getElementById('upload-overlay').style.display = 'none';
        document.getElementById('info-bar').style.display = 'flex';
        document.getElementById('loaded-filename').innerText = res.body.filename;

        root = d3.hierarchy(res.body.root);
        root.x0 = window.innerHeight / 2;
        root.y0 = 0;
        update(root);
      })
      .catch(err => {
        showLoading(false);
        showUploadError(err.message);
      });
  }

  function showUploadError(msg) {
    document.getElementById('upload-error').innerText = msg;
  }

  function showLoading(show) {
    document.getElementById('loading').style.display = show ? 'block' : 'none';
  }

  function resetApp() {
    g.selectAll('*').remove();
    document.getElementById('upload-overlay').style.display = 'flex';
    document.getElementById('info-bar').style.display = 'none';
    fileInput.value = '';
  }

  function update(source) {
    const treeData = treeLayout(root);
    const nodes = treeData.descendants();
    const links = treeData.links();

    nodes.forEach(d => d.y = d.depth * 200);

    const node = g.selectAll('g.node').data(nodes, d => d.data.id);

    const nodeEnter = node.enter().append('g')
        .attr('class', 'node')
        .attr("transform", () => `translate(${source.y0},${source.x0})`)
        .on('click', click);

    nodeEnter.append('circle')
        .attr('r', 6)
        .style("fill", d => d.data.hasChildren ? "lightsteelblue" : "#fff");

    nodeEnter.append('text')
        .attr("dy", ".35em")
        .attr("x", d => (d.children || d._children) ? -10 : 10)
        .attr("text-anchor", d => (d.children || d._children) ? "end" : "start")
        .text(d => d.data.label);

    const nodeUpdate = nodeEnter.merge(node);

    nodeUpdate.transition().duration(300)
      .attr("transform", d => `translate(${d.y},${d.x})`);

    nodeUpdate.select('circle')
      .style("fill", d => {
        if (!d.data.hasChildren) return "#fff";
        return d.children ? "#fff" : "lightsteelblue";
      });

    const nodeExit = node.exit().transition().duration(300)
        .attr("transform", () => `translate(${source.y},${source.x})`)
        .remove();

    nodeExit.select('circle').attr('r', 1e-6);

    const link = g.selectAll('path.link').data(links, d => d.target.data.id);

    const linkEnter = link.enter().insert('path', "g")
        .attr("class", "link")
        .attr('d', () => {
          const o = {x: source.x0, y: source.y0};
          return diagonal(o, o);
        });

    linkEnter.merge(link).transition().duration(300)
        .attr('d', d => diagonal(d.source, d.target));

    link.exit().transition().duration(300)
        .attr('d', () => {
          const o = {x: source.x, y: source.y};
          return diagonal(o, o);
        }).remove();

    nodes.forEach(d => {
      d.x0 = d.x;
      d.y0 = d.y;
    });

    function diagonal(s, t) {
      return `M ${s.y} ${s.x} C ${(s.y + t.y) / 2} ${s.x}, ${(s.y + t.y) / 2} ${t.x}, ${t.y} ${t.x}`;
    }
  }

  function click(event, d) {
    if (!d.data.hasChildren) return;

    if (d.children) {
      d._children = d.children;
      d.children = null;
      update(d);
    } else if (d._children) {
      d.children = d._children;
      d._children = null;
      update(d);
    } else {
      showLoading(true);
      fetch(`/api/children/${encodeURIComponent(d.data.id)}`)
        .then(res => res.json())
        .then(childrenData => {
          showLoading(false);
          if (childrenData.length > 0) {
            d.children = childrenData.map(c => {
              let childNode = d3.hierarchy(c);
              childNode.depth = d.depth + 1;
              childNode.parent = d;
              return childNode;
            });
            update(d);
          }
        })
        .catch(err => {
          showLoading(false);
          console.error(err);
        });
    }
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