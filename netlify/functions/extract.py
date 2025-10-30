import json
import pandas as pd
import pdfplumber
import base64
import tempfile
import os
from io import BytesIO

def handler(event, context):
    if event['httpMethod'] != 'POST':
        return {
            'statusCode': 405,
            'body': json.dumps({'error': 'Method not allowed'})
        }
    
    try:
        body = json.loads(event['body'])
        file_data = body['file']
        filename = body['filename']
        
        # Decode base64 file data
        pdf_bytes = base64.b64decode(file_data.split(',')[1])
        
        # Process PDF (use your existing extraction logic)
        result = process_pdf(pdf_bytes, filename)
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type'
            },
            'body': json.dumps(result)
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def process_pdf(pdf_bytes, filename):
    # Your existing PDF processing logic here
    # This is a simplified version
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            text = ""
            for page in pdf.pages:
                text += page.extract_text() or ""
        
        # Simple extraction logic
        rooms = []
        if 'BEDROOM' in text.upper():
            rooms.append('BEDROOM')
        if 'KITCHEN' in text.upper():
            rooms.append('KITCHEN')
        if 'LIVING' in text.upper():
            rooms.append('LIVING ROOM')
            
        return {
            'filename': filename,
            'rooms': rooms,
            'text_sample': text[:200] + '...' if len(text) > 200 else text
        }
        
    except Exception as e:
        return {'error': str(e)}
