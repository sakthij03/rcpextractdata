import os
import re
import pandas as pd
import pdfplumber
from io import BytesIO
from flask import Flask, render_template, request, jsonify, send_file
import base64

# Use Netlify's provided port or default to 5000
port = int(os.environ.get("PORT", 5000))

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("SECRET_KEY", "dev-key-for-netlify")

# ======================================================
# 🎯 PDF Extraction Configuration
# ======================================================
ROOM_REGEX = re.compile(r"(?i)\b(BEDROOM|BED|KITCHEN|LIVING|DINING|BATH|TOILET|BALCONY|MASTER|GUEST|ROOM)\b")
AFFL_REGEX = re.compile(r"(?i)(?:AFFL|FFL|LEVEL)\s*\+?\s*(\d{3,4})")
APT_REGEX = re.compile(r"(?i)\b(\d+\s*BED\s*TYPE\s*[A-Z]|TYPE\s*[A-Z]\s*\d+\s*BED)\b")
HEIGHT_REGEX = re.compile(r"(?i)(?:CEILING|HEIGHT|C\.H\.|CH)\s*:?\s*(\d{3,4})\s*(?:MM)?")
DRAWING_TITLE_REGEX = re.compile(r"(?i)(?:DRAWING\s*TITLE|TITLE|DWG\s*TITLE)\s*:?\s*(.+)")

# ======================================================
# 🏠 Application Routes
# ======================================================
@app.route("/")
def home():
    return render_template("index.html", app_name="PDF Ceiling Height Extractor")

@app.route("/upload")
def upload_page():
    return render_template("upload.html", app_name="Upload PDF Files")

# ======================================================
# 📤 File Upload Handling
# ======================================================
ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ======================================================
# 🧩 PDF Extraction Logic (Same as before)
# ======================================================
def extract_text_from_pdf(pdf_bytes):
    """Extract text and positions from PDF bytes"""
    text_elements = []
    
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages):
                words = page.extract_words()
                for word in words:
                    text_elements.append({
                        "text": word['text'],
                        "x": word['x0'],
                        "y": word['top'],
                        "page": page_num
                    })
                
                text = page.extract_text()
                if text:
                    lines = text.split('\n')
                    for line_num, line in enumerate(lines):
                        text_elements.append({
                            "text": line.strip(),
                            "x": 0,
                            "y": line_num * 20,
                            "page": page_num,
                            "is_line": True
                        })
    except Exception as e:
        raise RuntimeError(f"PDF parsing failed: {str(e)}")
    
    return text_elements

def extract_drawing_title(text_elements):
    for element in text_elements:
        text = element['text']
        match = DRAWING_TITLE_REGEX.search(text)
        if match:
            return match.group(1).strip()
        if re.search(r"(?i)(floor\s*plan|ceiling\s*plan|rcp|reflected)", text):
            return text
    return "Unknown Drawing"

def extract_apartment_type(text_elements):
    for element in text_elements:
        text = element['text']
        match = APT_REGEX.search(text)
        if match:
            return match.group(0)
    for element in text_elements:
        text = element['text']
        if re.search(r"(?i)\bTYPE\s*[A-Z]\b", text) and re.search(r"(?i)\bBED\b", text):
            return text
    return "Unknown Type"

def find_ceiling_heights(text_elements):
    heights = []
    for element in text_elements:
        text = element['text']
        match = AFFL_REGEX.search(text)
        if match:
            height_val = int(match.group(1))
            if 2000 <= height_val <= 4000:
                heights.append({
                    **element,
                    "val": height_val,
                    "text": f"+{height_val}",
                    "matched_pattern": "AFFL"
                })
                continue
        match = HEIGHT_REGEX.search(text)
        if match:
            height_val = int(match.group(1))
            if 2000 <= height_val <= 4000:
                heights.append({
                    **element,
                    "val": height_val,
                    "text": f"{height_val}mm",
                    "matched_pattern": "HEIGHT"
                })
        if re.search(r'^\d{3,4}$', text.strip()):
            height_val = int(text.strip())
            if 2000 <= height_val <= 4000:
                heights.append({
                    **element,
                    "val": height_val,
                    "text": f"{height_val}mm",
                    "matched_pattern": "NUMERIC"
                })
    return heights

def find_rooms(text_elements):
    rooms = []
    for element in text_elements:
        text = element['text']
        if ROOM_REGEX.search(text):
            rooms.append(element)
    return rooms

def calculate_distance(element1, element2):
    return ((element1['x'] - element2['x'])**2 + (element1['y'] - element2['y'])**2)**0.5

def match_rooms_with_heights(rooms, heights, max_distance=200):
    matches = []
    for room in rooms:
        if not heights:
            matches.append({
                **room,
                "ceiling_height": "N/A",
                "matched_height": None
            })
            continue
        nearest_height = min(heights, key=lambda h: calculate_distance(room, h))
        distance = calculate_distance(room, nearest_height)
        if distance <= max_distance:
            matches.append({
                **room,
                "ceiling_height": nearest_height['text'],
                "matched_height": nearest_height,
                "distance": distance
            })
        else:
            matches.append({
                **room,
                "ceiling_height": "N/A (No nearby height)",
                "matched_height": None,
                "distance": distance
            })
    return matches

def extract_from_pdf_bytes(pdf_bytes, filename):
    try:
        text_elements = extract_text_from_pdf(pdf_bytes)
        if not text_elements:
            return pd.DataFrame([{
                "Drawing Title": "No text found",
                "Apartment Type": "N/A",
                "Room": "No extractable text",
                "Ceiling Height": "N/A",
                "Source File": filename
            }])
        
        drawing_title = extract_drawing_title(text_elements)
        apartment_type = extract_apartment_type(text_elements)
        rooms = find_rooms(text_elements)
        heights = find_ceiling_heights(text_elements)
        matched_data = match_rooms_with_heights(rooms, heights)
        
        rows = []
        for match in matched_data:
            rows.append({
                "Drawing Title": drawing_title,
                "Apartment Type": apartment_type,
                "Room": match['text'],
                "Ceiling Height": match['ceiling_height'],
                "Source File": filename
            })
        
        if not rows and heights:
            rows.append({
                "Drawing Title": drawing_title,
                "Apartment Type": apartment_type,
                "Room": "Heights Found (No Room Labels)",
                "Ceiling Height": ", ".join([h['text'] for h in heights[:3]]),
                "Source File": filename
            })
        
        if not rows:
            rows.append({
                "Drawing Title": drawing_title,
                "Apartment Type": apartment_type,
                "Room": "No Room/Height Data Extracted",
                "Ceiling Height": "N/A",
                "Source File": filename
            })
        
        return pd.DataFrame(rows)
        
    except Exception as e:
        return pd.DataFrame([{
            "Drawing Title": "Error",
            "Apartment Type": "Error",
            "Room": f"Extraction failed: {str(e)}",
            "Ceiling Height": "N/A",
            "Source File": filename
        }])

# ======================================================
# 🧾 API Routes
# ======================================================
@app.route("/api/extract", methods=["POST"])
def api_extract():
    if 'files' not in request.files:
        return jsonify({"error": "No files provided"}), 400
    
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return jsonify({"error": "No files selected"}), 400
    
    combined_data = []
    
    for file in files:
        if file and allowed_file(file.filename):
            filename = file.filename
            try:
                pdf_bytes = file.read()
                df = extract_from_pdf_bytes(pdf_bytes, filename)
                combined_data.append(df)
            except Exception as e:
                combined_data.append(pd.DataFrame([{
                    "Source File": filename,
                    "Drawing Title": "Error",
                    "Apartment Type": "Error",
                    "Room": str(e),
                    "Ceiling Height": "N/A"
                }]))
    
    if not combined_data:
        return jsonify({"error": "No valid files processed"}), 400
    
    final_df = pd.concat(combined_data, ignore_index=True)
    
    try:
        matrix = final_df.pivot_table(
            index=["Source File", "Drawing Title", "Apartment Type"],
            columns="Room",
            values="Ceiling Height",
            aggfunc="first"
        ).reset_index()
    except Exception as e:
        matrix = final_df
    
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        final_df.to_excel(writer, sheet_name="Raw Data", index=False)
        matrix.to_excel(writer, sheet_name="Matrix View", index=False)
    out.seek(0)
    
    return send_file(
        out,
        as_attachment=True,
        download_name="Ceiling_Heights_Extracted.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/api/analyze-pdf", methods=["POST"])
def api_analyze_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if file and allowed_file(file.filename):
        try:
            pdf_bytes = file.read()
            text_elements = extract_text_from_pdf(pdf_bytes)
            
            analysis = {
                "total_text_elements": len(text_elements),
                "rooms_found": len(find_rooms(text_elements)),
                "heights_found": len(find_ceiling_heights(text_elements)),
                "drawing_title": extract_drawing_title(text_elements),
                "apartment_type": extract_apartment_type(text_elements),
                "sample_texts": [elem['text'] for elem in text_elements[:10]]
            }
            
            return jsonify(analysis)
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    return jsonify({"error": "Invalid file type"}), 400

# ======================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port, debug=False)