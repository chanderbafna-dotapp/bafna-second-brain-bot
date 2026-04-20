from flask import Flask, request
import requests
import os
import re
import base64
import subprocess
import threading
from datetime import datetime
from pathlib import Path

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
OPENROUTER_KEY = os.environ.get('OPENROUTER_API_KEY')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'chanderbafna-dotapp/bafna-second-brain')

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

def tg_send(chat_id, text):
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            requests.post(f"{TELEGRAM_API}/sendMessage", json={
                'chat_id': chat_id,
                'text': chunk,
                'parse_mode': 'Markdown'
            }, timeout=15)
        except Exception as e:
            print(f"Telegram send error: {e}")

def github_commit(filename, folder, content_str, commit_msg):
    content_b64 = base64.b64encode(content_str.encode('utf-8')).decode('utf-8')
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{folder}/{filename}"
    headers = {
        'Authorization': f'Bearer {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    existing = requests.get(url, headers=headers)
    payload = {
        'message': commit_msg,
        'content': content_b64
    }
    if existing.status_code == 200:
        payload['sha'] = existing.json()['sha']
    resp = requests.put(url, headers=headers, json=payload)
    return resp.status_code in [200, 201]

def github_commit_binary(filename, folder, content_bytes, commit_msg):
    content_b64 = base64.b64encode(content_bytes).decode('utf-8')
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{folder}/{filename}"
    headers = {
        'Authorization': f'Bearer {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    existing = requests.get(url, headers=headers)
    payload = {
        'message': commit_msg,
        'content': content_b64
    }
    if existing.status_code == 200:
        payload['sha'] = existing.json()['sha']
    resp = requests.put(url, headers=headers, json=payload)
    return resp.status_code in [200, 201]

def claude_classify_text(text):
    headers = {
        'Authorization': f'Bearer {OPENROUTER_KEY}',
        'Content-Type': 'application/json'
    }
    prompt = f"""You are a clinical assistant for Dr. Chander Bafna, diabetologist in Raipur, India.

Analyse this message from a doctors group:

{text}

Respond in this exact JSON format only:
{{
  "title": "concise title max 8 words",
  "folder": "raw",
  "tags": ["tag1", "tag2"],
  "summary": "2 sentence clinical summary",
  "clinical_relevance": "one sentence relevance to T2DM practice in India",
  "verify_needed": false
}}

JSON only. No other text."""

    payload = {
        'model': 'anthropic/claude-sonnet-4-5',
        'messages': [{'role': 'user', 'content': prompt}],
        'max_tokens': 600
    }
    resp = requests.post('https://openrouter.ai/api/v1/chat/completions', headers=headers, json=payload, timeout=30)
    data = resp.json()
    if 'choices' not in data:
        return None
    import json
    try:
        return json.loads(data['choices'][0]['message']['content'])
    except:
        return None

def claude_summarise_pdf(pdf_text, doc_name):
    headers = {
        'Authorization': f'Bearer {OPENROUTER_KEY}',
        'Content-Type': 'application/json'
    }
    prompt = f"""You are a clinical assistant for Dr. Chander Bafna, diabetologist in Raipur, India.

Analyse this clinical document: {doc_name}

Document text (first 10 pages):
{pdf_text[:4000]}

Generate a structured clinical summary:
1. Document type and purpose
2. Key clinical recommendations (bullet points)
3. Dosing or diagnostic criteria if present
4. Relevance to T2DM/metabolic practice in India
5. 3 key OPD takeaways

Be concise and clinically focused."""

    payload = {
        'model': 'anthropic/claude-sonnet-4-5',
        'messages': [{'role': 'user', 'content': prompt}],
        'max_tokens': 1500
    }
    resp = requests.post('https://openrouter.ai/api/v1/chat/completions', headers=headers, json=payload, timeout=45)
    data = resp.json()
    if 'choices' not in data:
        return 'Clinical summary generation failed'
    return data['choices'][0]['message']['content']

def process_text_message(text, chat_id):
    tg_send(chat_id, f"⏳ *Processing message...*\n\nClassifying with Claude...")
    date_str = datetime.now().strftime('%Y-%m-%d')
    timestamp = int(datetime.now().timestamp())
    parsed = claude_classify_text(text)
    if parsed:
        title = parsed.get('title', 'Clinical Note')
        folder = parsed.get('folder', 'raw')
        tags = parsed.get('tags', ['unprocessed'])
        summary = parsed.get('summary', '')
        relevance = parsed.get('clinical_relevance', '')
    else:
        title = f'Telegram Note {date_str}'
        folder = 'raw'
        tags = ['unprocessed', 'telegram']
        summary = text[:200]
        relevance = ''
    filename = re.sub(r'[^a-z0-9]+', '-', title.lower())[:50] + f'-{timestamp}.md'
    note = f"""---
title: {title}
date: {date_str}
source: Telegram Doctors Group
tags: [{', '.join(tags)}]
status: unprocessed
---

## Summary
{summary}

## Clinical relevance
{relevance}

## Original message
{text}

## Next action
- [ ] Run Cmd+Shift+R for trials or Cmd+Shift+G for guidelines
- [ ] Move to correct folder after review
"""
    success = github_commit(filename, folder, note, f'Telegram clip: {title}')
    if success:
        tg_send(chat_id, f"✅ *Saved to vault*\n\n📁 Folder: `{folder}/`\n📄 File: `{filename}`\n\n*Summary:* {summary}\n\nOpen Obsidian → run *Cmd+Shift+R* to process.")
    else:
        tg_send(chat_id, f"⚠️ *Save failed* — GitHub commit error. Try again.")

def process_pdf_message(document, chat_id):
    file_id = document.get('file_id', '')
    file_name = document.get('file_name', 'document.pdf')
    doc_name = file_name.replace('.pdf', '')
    tg_send(chat_id, f"⏳ *Processing PDF:* `{file_name}`\n\nDownloading and extracting text...")
    file_info = requests.get(f"{TELEGRAM_API}/getFile?file_id={file_id}").json()
    if not file_info.get('ok'):
        tg_send(chat_id, "❌ Failed to download PDF from Telegram.")
        return
    file_path = file_info['result']['file_path']
    pdf_bytes = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}").content
    safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', file_name)
    pdf_saved = github_commit_binary(safe_name, 'Assets', pdf_bytes, f'PDF received: {file_name}')
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        result = subprocess.run(['pdftotext', '-l', '10', tmp_path, '-'], capture_output=True, text=True, timeout=30)
        pdf_text = result.stdout.strip()[:4000] if result.stdout.strip() else ''
        os.unlink(tmp_path)
    except Exception as e:
        pdf_text = ''
        print(f"pdftotext error: {e}")
    tg_send(chat_id, "🧠 *Generating clinical summary with Claude...*")
    clinical_summary = claude_summarise_pdf(pdf_text, doc_name) if pdf_text else f"PDF saved to Assets/{safe_name}. Text extraction unavailable — query directly via Copilot in Obsidian."
    date_str = datetime.now().strftime('%Y-%m-%d')
    timestamp = int(datetime.now().timestamp())
    note_filename = re.sub(r'[^a-zA-Z0-9_-]', '_', doc_name) + f'_{timestamp}.md'
    note = f"""---
title: {doc_name}
type: pdf-summary
status: unprocessed
date_added: {date_str}
source: Telegram Bot
tags: [raw, unprocessed, telegram, pdf]
---

# {doc_name}

## Clinical Summary
{clinical_summary}

## Source Document
![[Assets/{safe_name}]]

## Next action
- [ ] Review summary accuracy
- [ ] Run Cmd+Shift+G for full guideline extraction
- [ ] Move to Literature/ after review
"""
    note_saved = github_commit(note_filename, 'raw', note, f'PDF summary: {doc_name}')
    if note_saved:
        tg_send(chat_id, f"✅ *PDF Processed*\n\n📄 File: `{safe_name}`\n📁 PDF → `Assets/`\n📝 Note → `raw/{note_filename}`\n🖼️ Poster: Generating separately\n\nOpen Obsidian → run *Cmd+Shift+G* for full extraction.")
    else:
        tg_send(chat_id, f"⚠️ PDF saved to Assets/ but note commit failed. Try again.")

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json(silent=True) or {}
    message = update.get('message', {})
    chat_id = str(message.get('chat', {}).get('id', ''))
    text = message.get('text', '').strip()
    document = message.get('document', {})
    if not chat_id:
        return 'ok', 200
    if text and not document:
        threading.Thread(target=process_text_message, args=(text, chat_id), daemon=True).start()
        return 'ok', 200
    if document:
        mime = document.get('mime_type', '')
        if 'pdf' not in mime:
            tg_send(chat_id, 'Please send a PDF file.')
            return 'ok', 200
        threading.Thread(target=process_pdf_message, args=(document, chat_id), daemon=True).start()
        return 'ok', 200
    return 'ok', 200

@app.route('/', methods=['GET'])
def health():
    return 'Bafna Second Brain Bot is running', 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
