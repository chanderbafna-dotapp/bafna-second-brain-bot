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
        print(f"Claude error: {data}")
        return None
    import json
    raw = data["choices"][0]["message"]["content"]
    print(f"Claude raw response: {raw[:300]}")
    try:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        print(f"JSON parse error: {e}")
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

def parse_sections(summary_text):
    """Parse markdown summary into named sections."""
    import re
    sections = {}
    current_section = "intro"
    current_lines = []
    
    for line in summary_text.split("\n"):
        # Match numbered headings like "1. TITLE" or "## TITLE"
        match = re.match(r"^(?:\d+\.\s+|#{1,3}\s+)(.+)", line.strip())
        if match:
            if current_lines:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = match.group(1).strip().upper()[:40]
            current_lines = []
        else:
            current_lines.append(line)
    
    if current_lines:
        sections[current_section] = "\n".join(current_lines).strip()
    
    return sections

def render_text_panel(draw, text, font, x, y, max_width, max_y, line_height=20):
    """Render text with word wrap, returns final y position."""
    import re
    # Clean markdown
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    
    for line in text.split("\n"):
        if y > max_y:
            break
        line = line.strip()
        if not line:
            y += line_height // 2
            continue
        
        # Word wrap
        words = line.split()
        current = ""
        for word in words:
            test = (current + " " + word).strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current = test
            else:
                if current:
                    draw.text((x, y), current, fill="#0A0A0A", font=font)
                    y += line_height
                current = word
        if current and y <= max_y:
            draw.text((x, y), current, fill="#0A0A0A", font=font)
            y += line_height
    
    return y

def generate_clinical_infographic(title, summary, doc_type="PDF Summary"):
    """Generate 3 clean black/white PNG panels from clinical summary."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io, re
        from datetime import datetime

        W = 900
        MARGIN = 44
        INNER_W = W - MARGIN * 2
        BG = "#FFFFFF"
        INK = "#0A0A0A"
        GRAY = "#555555"
        LIGHT = "#F5F5F5"
        RULE = "#CCCCCC"

        def get_font(size, bold=False):
            try:
                path = "/usr/share/fonts/truetype/dejavu/"
                fname = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
                return ImageFont.truetype(path + fname, size)
            except:
                return ImageFont.load_default()

        f_title  = get_font(22, bold=True)
        f_h2     = get_font(14, bold=True)
        f_body   = get_font(13)
        f_small  = get_font(11)
        f_mono   = get_font(11)
        f_eyebrow= get_font(10)

        date_str = datetime.now().strftime("%d %b %Y")

        # Parse sections from summary
        sections = parse_sections(summary)
        section_keys = list(sections.keys())

        def make_panel(panel_num, section_slice, panel_title):
            """Create one panel image."""
            # Estimate height
            H = 120  # header
            for key in section_slice:
                text = sections.get(key, "")
                line_count = max(len(text.split("\n")), text.count(" ") // 8 + 2)
                H += 36 + min(line_count, 25) * 18 + 16
            H = max(H, 600) + 60  # footer

            img = Image.new("RGB", (W, H), color=BG)
            draw = ImageDraw.Draw(img)

            # Header
            draw.rectangle([0, 0, W, 4], fill=INK)
            draw.text((MARGIN, 16), f"PANEL {panel_num}/3  —  {panel_title}", fill=GRAY, font=f_eyebrow)
            
            # Title (truncated)
            title_short = title[:65] + ("..." if len(title) > 65 else "")
            draw.text((MARGIN, 32), title_short, fill=INK, font=f_title)
            draw.text((MARGIN, 62), f"Dr. Chander Bafna  •  Bafna Metabolic Center, Raipur  •  {date_str}", fill=GRAY, font=f_small)
            draw.line([(MARGIN, 84), (W - MARGIN, 84)], fill=RULE, width=1)

            y = 96

            for key in section_slice:
                text = sections.get(key, "").strip()
                if not text:
                    continue

                # Section heading
                draw.text((MARGIN, y), key, fill=INK, font=f_h2)
                y += 22
                draw.line([(MARGIN, y), (W - MARGIN, y)], fill=RULE, width=1)
                y += 10

                # Section body
                y = render_text_panel(draw, text, f_body, MARGIN + 8, y, INNER_W - 8, H - 80, line_height=18)
                y += 16

            # Footer
            draw.line([(MARGIN, H - 44), (W - MARGIN, H - 44)], fill=RULE, width=1)
            draw.text((MARGIN, H - 30), "For licensed healthcare professionals only  •  bafnahealthcare.com", fill=GRAY, font=f_small)
            draw.text((W - MARGIN - 120, H - 30), f"Claude AI  •  {date_str}", fill=INK, font=f_mono)

            buf = io.BytesIO()
            img.save(buf, format="PNG", quality=95)
            buf.seek(0)
            return buf

        # Divide sections into 3 panels
        n = len(section_keys)
        third = max(1, n // 3)
        
        panel_configs = [
            (section_keys[:third],           "IDENTITY · EXECUTIVE SUMMARY · EVIDENCE"),
            (section_keys[third:2*third],    "DIAGNOSIS · TREATMENT · INDIAN PRACTICE"),
            (section_keys[2*third:],         "OPD PEARLS · CONTROVERSIES · ACTION CHECKLIST"),
        ]

        panels = []
        for i, (keys, panel_title) in enumerate(panel_configs, 1):
            if keys:
                panels.append(make_panel(i, keys, panel_title))

        return panels  # Returns list of BytesIO objects

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"Infographic error: {e}")
        return []


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
    panels = generate_clinical_infographic(doc_name, clean_markdown(clinical_summary), "PDF Summary")
    if panels:
        tg_send_photo(chat_id, panels[0], caption=f"Panel 1/3 — Identity & Executive Summary: {doc_name[:60]}")
        if len(panels) > 1:
            tg_send_photo(chat_id, panels[1], caption=f"Panel 2/3 — Diagnosis, Treatment & Indian Practice")
        if len(panels) > 2:
            tg_send_photo(chat_id, panels[2], caption=f"Panel 3/3 — OPD Pearls, Controversies & Action Checklist")
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
