from flask import Flask, request
import requests
import os
import re
import base64
import subprocess
import threading
import io
import textwrap
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "chanderbafna-dotapp/bafna-second-brain")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

def tg_send(chat_id, text):
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            requests.post(f"{TELEGRAM_API}/sendMessage", json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown"
            }, timeout=15)
        except Exception as e:
            print(f"Telegram send error: {e}")

def tg_send_photo(chat_id, img_bytes, caption=""):
    try:
        img_bytes.seek(0)
        requests.post(f"{TELEGRAM_API}/sendPhoto", data={
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "Markdown"
        }, files={"photo": ("infographic.png", img_bytes, "image/png")}, timeout=30)
    except Exception as e:
        print(f"Telegram send photo error: {e}")

def github_commit(filename, folder, content_str, commit_msg):
    content_b64 = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{folder}/{filename}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    existing = requests.get(url, headers=headers)
    payload = {"message": commit_msg, "content": content_b64}
    if existing.status_code == 200:
        payload["sha"] = existing.json()["sha"]
    resp = requests.put(url, headers=headers, json=payload)
    return resp.status_code in [200, 201]

def github_commit_binary(filename, folder, content_bytes, commit_msg):
    content_b64 = base64.b64encode(content_bytes).decode("utf-8")
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{folder}/{filename}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    existing = requests.get(url, headers=headers)
    payload = {"message": commit_msg, "content": content_b64}
    if existing.status_code == 200:
        payload["sha"] = existing.json()["sha"]
    resp = requests.put(url, headers=headers, json=payload)
    return resp.status_code in [200, 201]

def claude_classify_text(text):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }
    prompt = "You are a clinical assistant for Dr. Chander Bafna, diabetologist in Raipur, India.\n\nAnalyse this message from a doctors group:\n\n" + text + "\n\nRespond in this exact JSON format only:\n{\n  \"title\": \"concise title max 8 words\",\n  \"folder\": \"raw\",\n  \"tags\": [\"tag1\", \"tag2\"],\n  \"summary\": \"2 sentence clinical summary\",\n  \"clinical_relevance\": \"one sentence relevance to T2DM practice in India\",\n  \"verify_needed\": false\n}\n\nJSON only."
    payload = {
        "model": "anthropic/claude-sonnet-4-5",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 600
    }
    resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=30)
    data = resp.json()
    if "choices" not in data:
        return None
    import json
    try:
        return json.loads(data["choices"][0]["message"]["content"])
    except:
        return None

def claude_summarise_pdf(pdf_text, doc_name):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }
    prompt = "You are a clinical assistant for Dr. Chander Bafna, diabetologist in Raipur, India.\n\nAnalyse this clinical document: " + doc_name + "\n\nDocument text:\n" + pdf_text[:4000] + "\n\nGenerate a structured clinical summary:\n1. Document type and purpose\n2. Key clinical recommendations (bullet points)\n3. Dosing or diagnostic criteria if present\n4. Relevance to T2DM/metabolic practice in India\n5. 3 key OPD takeaways\n\nBe concise and clinically focused."
    payload = {
        "model": "anthropic/claude-sonnet-4-5",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1500
    }
    resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=45)
    data = resp.json()
    if "choices" not in data:
        return "Clinical summary generation failed"
    return data["choices"][0]["message"]["content"]

def generate_clinical_infographic(title, summary, doc_type="PDF Summary"):
    try:
        W, H = 900, 1100
        BG = "#0d1b2a"
        HDR = "#e63946"
        SECTION_BG = "#16213e"
        TEXT = "#f1faee"
        SUBTEXT = "#a8dadc"
        ACCENT = "#457b9d"

        img = Image.new("RGB", (W, H), color=BG)
        draw = ImageDraw.Draw(img)

        try:
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
            font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
            font_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 17)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except:
            font_large = font_medium = font_body = font_small = ImageFont.load_default()

        draw.rectangle([0, 0, W, 80], fill=HDR)
        draw.text((30, 15), "BAFNA SECOND BRAIN", fill="white", font=font_large)
        draw.text((30, 50), doc_type + "  |  " + datetime.now().strftime("%d %b %Y") + "  |  Powered by Claude AI", fill="#ffccd5", font=font_small)

        y = 95
        margin = 30

        draw.rectangle([0, y, W, y + 50], fill="#1d3557")
        draw.text((margin, y + 12), title[:80], fill=SUBTEXT, font=font_medium)
        y += 60

        sections = []
        current_section = ""
        current_text = []
        for line in summary.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith(("1.", "2.", "3.", "4.", "5.")) or line.isupper() or line.endswith(":"):
                if current_section and current_text:
                    sections.append((current_section, " ".join(current_text)))
                current_section = line
                current_text = []
            else:
                current_text.append(line)
        if current_section and current_text:
            sections.append((current_section, " ".join(current_text)))

        if not sections:
            sections = [("CLINICAL SUMMARY", summary[:800])]

        colors = ["#1a472a", "#1d3557", "#3d1a47", "#47261a", "#1a3947"]
        accent_colors = ["#2dc653", "#457b9d", "#9b59b6", "#e67e22", "#1abc9c"]

        for i, (section_title, section_text) in enumerate(sections[:6]):
            bg_c = colors[i % len(colors)]
            acc_c = accent_colors[i % len(accent_colors)]
            wrapped = textwrap.wrap(section_text, width=70)
            sec_h = 45 + len(wrapped[:4]) * 24 + 15
            if y + sec_h > H - 60:
                break
            draw.rectangle([0, y, W, y + sec_h], fill=bg_c)
            draw.rectangle([0, y, 6, y + sec_h], fill=acc_c)
            draw.text((margin, y + 10), section_title[:60], fill=acc_c, font=font_medium)
            for j, wline in enumerate(wrapped[:4]):
                draw.text((margin + 10, y + 35 + j * 24), wline, fill=TEXT, font=font_body)
            y += sec_h + 5

        draw.rectangle([0, H - 50, W, H], fill="#1d3557")
        draw.text((margin, H - 35), "For educational use only. Verify with primary sources. Open Obsidian to process.", fill=SUBTEXT, font=font_small)

        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)
        return img_bytes
    except Exception as e:
        print(f"Infographic error: {e}")
        return None

def process_text_message(text, chat_id):
    tg_send(chat_id, "Processing message...")
    date_str = datetime.now().strftime("%Y-%m-%d")
    timestamp = int(datetime.now().timestamp())
    parsed = claude_classify_text(text)
    if parsed:
        title = parsed.get("title", "Clinical Note")
        folder = parsed.get("folder", "raw")
        tags = parsed.get("tags", ["unprocessed"])
        summary = parsed.get("summary", "")
        relevance = parsed.get("clinical_relevance", "")
    else:
        title = f"Telegram Note {date_str}"
        folder = "raw"
        tags = ["unprocessed", "telegram"]
        summary = text[:200]
        relevance = ""
    filename = re.sub(r"[^a-z0-9]+", "-", title.lower())[:50] + f"-{timestamp}.md"
    note = "---\ntitle: " + title + "\ndate: " + date_str + "\nsource: Telegram Doctors Group\ntags: [" + ", ".join(tags) + "]\nstatus: unprocessed\n---\n\n## Summary\n" + summary + "\n\n## Clinical relevance\n" + relevance + "\n\n## Original message\n" + text + "\n\n## Next action\n- [ ] Run Cmd+Shift+R for trials or Cmd+Shift+G for guidelines\n- [ ] Move to correct folder after review\n"
    success = github_commit(filename, folder, note, f"Telegram clip: {title}")
    img_bytes = generate_clinical_infographic(title, summary + "\n\nClinical Relevance:\n" + relevance, "Text Message")
    if img_bytes:
        tg_send_photo(chat_id, img_bytes, caption=f"Clinical Summary: {title}")
    if success:
        tg_send(chat_id, "Saved to vault\n\nFolder: " + folder + "/\nFile: " + filename + "\n\nOpen Obsidian and run Cmd+Shift+R to process.")
    else:
        tg_send(chat_id, "Save failed. Try again.")

def process_pdf_message(document, chat_id):
    file_id = document.get("file_id", "")
    file_name = document.get("file_name", "document.pdf")
    doc_name = file_name.replace(".pdf", "")
    tg_send(chat_id, "Processing PDF: " + file_name + "\n\nDownloading and extracting text...")
    file_info = requests.get(f"{TELEGRAM_API}/getFile?file_id={file_id}").json()
    if not file_info.get("ok"):
        tg_send(chat_id, "Failed to download PDF.")
        return
    file_path = file_info["result"]["file_path"]
    pdf_bytes = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}").content
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", file_name)
    github_commit_binary(safe_name, "Assets", pdf_bytes, f"PDF received: {file_name}")
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        result = subprocess.run(["pdftotext", "-l", "10", tmp_path, "-"], capture_output=True, text=True, timeout=30)
        pdf_text = result.stdout.strip()[:4000] if result.stdout.strip() else ""
        os.unlink(tmp_path)
    except Exception as e:
        pdf_text = ""
        print(f"pdftotext error: {e}")
    tg_send(chat_id, "Generating clinical summary with Claude...")
    clinical_summary = claude_summarise_pdf(pdf_text, doc_name) if pdf_text else "PDF saved. Text extraction unavailable. Query via Copilot in Obsidian."
    date_str = datetime.now().strftime("%Y-%m-%d")
    timestamp = int(datetime.now().timestamp())
    note_filename = re.sub(r"[^a-zA-Z0-9_-]", "_", doc_name) + f"_{timestamp}.md"
    note = "---\ntitle: " + doc_name + "\ntype: pdf-summary\nstatus: unprocessed\ndate_added: " + date_str + "\nsource: Telegram Bot\ntags: [raw, unprocessed, telegram, pdf]\n---\n\n# " + doc_name + "\n\n## Clinical Summary\n" + clinical_summary + "\n\n## Source Document\n![[Assets/" + safe_name + "]]\n\n## Next action\n- [ ] Review summary accuracy\n- [ ] Run Cmd+Shift+G for full guideline extraction\n- [ ] Move to Literature/ after review\n"
    github_commit(note_filename, "raw", note, f"PDF summary: {doc_name}")
    img_bytes = generate_clinical_infographic(doc_name, clinical_summary, "PDF Summary")
    if img_bytes:
        tg_send_photo(chat_id, img_bytes, caption=f"Clinical Summary: {doc_name}")
    tg_send(chat_id, "PDF Processed\n\nFile: " + safe_name + "\nPDF saved to Assets/\nNote saved to raw/" + note_filename + "\n\nOpen Obsidian and run Cmd+Shift+G for full extraction.")

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}
    message = update.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()
    document = message.get("document", {})
    if not chat_id:
        return "ok", 200
    if text and not document:
        threading.Thread(target=process_text_message, args=(text, chat_id), daemon=True).start()
        return "ok", 200
    if document:
        mime = document.get("mime_type", "")
        if "pdf" not in mime:
            tg_send(chat_id, "Please send a PDF file.")
            return "ok", 200
        threading.Thread(target=process_pdf_message, args=(document, chat_id), daemon=True).start()
        return "ok", 200
    return "ok", 200

@app.route("/", methods=["GET"])
def health():
    return "Bafna Second Brain Bot is running", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
