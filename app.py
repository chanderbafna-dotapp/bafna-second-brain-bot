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
    prompt = "You are a clinical assistant for Dr. Chander Bafna, diabetologist in Raipur, India.\n\nAnalyse this message from a doctors group:\n\n" + text + "\n\nRespond in this exact JSON format only:\n{\n  \"title\": \"concise title max 8 words\",\n  \"folder\": \"raw\",\n  \"tags\": [\"tag1\", \"tag2\"],\n  \"summary\": \"3-4 sentences with key numbers and effect sizes\",\n  \"clinical_relevance\": \"2 sentences on relevance to T2DM/CKD practice in Raipur India\",\n  \"mechanism\": \"1-2 sentences on mechanism or pathophysiology\",\n  \"key_recommendation\": \"specific actionable OPD recommendation\",\n  \"caveats\": \"key limitations or contraindications\",\n  \"verify_needed\": false\n}\n\nJSON only."
    payload = {
        "model": "anthropic/claude-sonnet-4-5",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 900
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

def clean_markdown(text):
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"_{1,2}(.+?)_{1,2}", r"\1", text)
    return text.strip()

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
        W = 900
        margin = 28

        BG          = "#FAFAFA"
        HDR_BG      = "#1565C0"
        HDR_TEXT    = "#FFFFFF"
        HDR_SUB     = "#BBDEFB"
        TITLE_BG    = "#E3F2FD"
        TITLE_BORDER= "#1565C0"
        TITLE_TEXT  = "#0D47A1"
        BLACK       = "#212121"
        DIVIDER     = "#E0E0E0"
        FOOTER_BG   = "#F5F5F5"
        FOOTER_TEXT = "#757575"
        BULLET      = "#424242"

        section_styles = [
            ("#E8F5E9", "#43A047", "#1B5E20"),
            ("#E3F2FD", "#1E88E5", "#0D47A1"),
            ("#F3E5F5", "#8E24AA", "#4A148C"),
            ("#FFF3E0", "#FB8C00", "#E65100"),
            ("#E0F7FA", "#00ACC1", "#006064"),
            ("#FCE4EC", "#E91E63", "#880E4F"),
        ]

        try:
            font_hdr   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
            font_sub   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
            font_label = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
            font_body  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except:
            font_hdr = font_sub = font_label = font_body = font_small = ImageFont.load_default()

        tmp = Image.new("RGB", (W, 10))
        tmp_d = ImageDraw.Draw(tmp)

        def wrap(text, font, max_w):
            words = str(text).split()
            lines, line = [], ""
            for w in words:
                test = (line + " " + w).strip()
                bbox = tmp_d.textbbox((0,0), test, font=font)
                if bbox[2] - bbox[0] <= max_w:
                    line = test
                else:
                    if line: lines.append(line)
                    line = w
            if line: lines.append(line)
            return lines

        def text_to_bullets(text):
            """Convert paragraph text to bullet points."""
            import re
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
            text = re.sub(r"\*(.+?)\*", r"\1", text)
            text = re.sub(r"#{1,6}\s*", "", text)
            sentences = re.split(r"(?<=[.!?])\s+|\s*[-•]\s*", text)
            bullets = []
            for s in sentences:
                s = s.strip().strip(".")
                if len(s) > 15:
                    bullets.append(s)
            return bullets[:5]

        sections = []
        current_section = ""
        current_text = []
        for line in summary.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.")) or (line.isupper() and len(line) > 3) or (line.endswith(":") and len(line) < 50):
                if current_section and current_text:
                    sections.append((current_section.rstrip(":"), " ".join(current_text)))
                current_section = line.rstrip(":")
                current_text = []
            else:
                current_text.append(line)
        if current_section and current_text:
            sections.append((current_section.rstrip(":"), " ".join(current_text)))
        if not sections:
            chunks = [summary[i:i+250] for i in range(0, min(len(summary), 1500), 250)]
            sections = [(f"Key Point {i+1}", c) for i, c in enumerate(chunks[:6])]

        inner_w = W - margin * 2 - 16

        H = 88
        title_lines = wrap(title, font_label, inner_w - 10)
        H += 16 + len(title_lines) * 24 + 14
        for st, sx in sections[:6]:
            bullets = text_to_bullets(sx)
            H += 36 + len(bullets) * 22 + 10
        H += 44

        img = Image.new("RGB", (W, H), color=BG)
        draw = ImageDraw.Draw(img)

        draw.rectangle([0, 0, W, 88], fill=HDR_BG)
        draw.text((margin, 16), "BAFNA SECOND BRAIN", fill=HDR_TEXT, font=font_hdr)
        draw.text((margin, 52), doc_type + "  •  " + datetime.now().strftime("%d %b %Y") + "  •  Powered by Claude AI", fill=HDR_SUB, font=font_sub)

        y = 88

        t_h = 16 + len(title_lines) * 24 + 14
        draw.rectangle([0, y, W, y + t_h], fill=TITLE_BG)
        draw.rectangle([0, y, 5, y + t_h], fill=TITLE_BORDER)
        for i, tl in enumerate(title_lines):
            draw.text((margin, y + 8 + i * 24), tl, fill=TITLE_TEXT, font=font_label)
        y += t_h
        draw.line([(0, y), (W, y)], fill=DIVIDER, width=1)

        for i, (section_title, section_text) in enumerate(sections[:6]):
            bg_c, acc_c, dark_c = section_styles[i % len(section_styles)]
            bullets = text_to_bullets(section_text)
            if not bullets:
                bullets = [section_text[:100]]
            sec_h = 36 + len(bullets) * 22 + 10
            draw.rectangle([0, y, W, y + sec_h], fill=bg_c)
            draw.rectangle([0, y, 5, y + sec_h], fill=acc_c)
            draw.text((margin, y + 8), section_title[:55], fill=dark_c, font=font_label)
            for j, bullet in enumerate(bullets):
                bx = margin + 10
                by = y + 30 + j * 22
                draw.ellipse([bx, by + 5, bx + 7, by + 12], fill=acc_c)
                bullet_lines = wrap(bullet, font_body, inner_w - 30)
                draw.text((bx + 14, by), bullet_lines[0] if bullet_lines else bullet[:80], fill=BLACK, font=font_body)
            y += sec_h
            draw.line([(0, y), (W, y)], fill=DIVIDER, width=1)

        draw.rectangle([0, y, W, H], fill=FOOTER_BG)
        draw.text((margin, y + 14), "For educational use only  •  Verify with primary sources  •  Open Obsidian to process", fill=FOOTER_TEXT, font=font_small)

        buf = io.BytesIO()
        img.save(buf, format="PNG", quality=95)
        buf.seek(0)
        return buf
    except Exception as e:
        import traceback; traceback.print_exc()
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
    mechanism = parsed.get("mechanism", "") if parsed else ""
    key_rec = parsed.get("key_recommendation", "") if parsed else ""
    caveats = parsed.get("caveats", "") if parsed else ""
    rich_summary = "SUMMARY\n" + summary
    if mechanism: rich_summary += "\nMECHANISM\n" + mechanism
    if relevance: rich_summary += "\nCLINICAL RELEVANCE\n" + relevance
    if key_rec: rich_summary += "\nOPD RECOMMENDATION\n" + key_rec
    if caveats: rich_summary += "\nCAVEATS\n" + caveats
    img_bytes = generate_clinical_infographic(title, rich_summary, "Text Message")
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
    img_bytes = generate_clinical_infographic(doc_name, clean_markdown(clinical_summary), "PDF Summary")
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
