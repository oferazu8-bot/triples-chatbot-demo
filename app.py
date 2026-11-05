#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Triple S Hebrew RTL chat assistant demo — FAQ/rule based (no LLM key on box)."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    render_template_string,
    request,
    send_from_directory,
)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(APP_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("DB_PATH", str(DATA_DIR / "chatbot.db")))
KB_PATH = APP_DIR / "knowledge" / "kb.json"
OUTBOX_DIR = DATA_DIR / "outbox"
OUTBOX_DIR.mkdir(parents=True, exist_ok=True)

IL = timezone(timedelta(hours=2))
COMPANY = "טריפל אס אנרגיה מתחדשת"

app = Flask(__name__, static_folder="static", static_url_path="/static")


def now_il() -> str:
    return datetime.now(IL).strftime("%Y-%m-%d %H:%M:%S Asia/Jerusalem")


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
              id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL,
              name TEXT NOT NULL,
              phone TEXT NOT NULL,
              settlement TEXT,
              interest TEXT,
              site TEXT,
              notes TEXT,
              source TEXT DEFAULT 'chatbot-demo'
            );
            CREATE TABLE IF NOT EXISTS messages (
              id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL,
              session_id TEXT,
              role TEXT,
              content TEXT,
              site TEXT
            );
            CREATE TABLE IF NOT EXISTS outbox (
              id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL,
              lead_id TEXT,
              payload TEXT,
              status TEXT DEFAULT 'queued'
            );
            """
        )


init_db()

with open(KB_PATH, encoding="utf-8") as f:
    KB = json.load(f)

LLM_MODE = "faq"
for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
    if os.environ.get(key):
        LLM_MODE = f"llm:{key}"
        break  # key present but we still prefer FAQ unless wired; mark availability


PHONE_RE = re.compile(r"^0[2-9]\d{7,8}$|^05\d{8}$|^07\d{8}$")


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("972"):
        digits = "0" + digits[3:]
    return digits


def match_faq(text: str) -> str | None:
    t = text.strip().lower()
    # light stemming for Hebrew construct forms (אגירת→אגירה)
    t_norm = t.replace("אגירת", "אגירה").replace("סולארית", "סולארי").replace("סולאריות", "סולארי")
    for item in KB["faqs"]:
        for kw in item["q"]:
            k = kw.lower()
            if k in t or k in t_norm:
                return item["a"]
    return None


def answer_price() -> str:
    ranges = "\n".join(f"• {r['topic']}: {r['text']}" for r in KB["stated_ranges"])
    return (
        f"לגבי מחירים — באתרי {COMPANY} לא מופיע מחיר ₪ מדויק למערכת, ולכן אני לא ממציא מספרים.\n\n"
        f"מה שכן כתוב באתרים כטווחים כלליים:\n{ranges}\n\n"
        "העלות תלויה בגודל הגג, בצריכה, בתעריף החשמל ובסוג המערכת. "
        "אשמח להעביר אתכם לייעוץ / הצעת מחיר מותאמת — השאירו שם וטלפון."
    )


def answer_roi() -> str:
    return (
        "לפי אתר האגירה: במערכות אגירה מסחריות החזר השקעה טיפוסי הוא 3–6 שנים "
        "(תלוי בתעריפים, בפרופיל הצריכה ובגודל).\n"
        "במדריך האגירה הביתית באתר הסולארי: בתעריף זמן שימוש הכדאיות גבוהה יותר; "
        "בתעריף רגיל ההחזר עלול להיות ארוך מאוד.\n\n"
        "כדי לבדוק כדאיות אצלכם — כדאי שיחה קצרה עם הצוות. רוצים שנחזור אליכם?"
    )


def answer_contact(site: str) -> str:
    phones = KB["company"]["phones"]
    phone = phones.get(site) or phones["solar"]
    return (
        f"{COMPANY}\n"
        f"טלפון סולארי: {phones['solar']}\n"
        f"טלפון אגירה: {phones['storage']}\n"
        f"מייל: {KB['company']['email']}\n"
        f"כתובת: {KB['company']['address']}\n"
        f"שעות: {KB['company']['hours']}\n\n"
        f"לשיחה מהירה ממליצים להתקשר ל־{phone} או להשאיר פרטים כאן."
    )


def build_reply(user_text: str, site: str) -> dict:
    code = match_faq(user_text)
    lead_hint = False
    if code == "PRICE" or re.search(r"מחיר|כמה עולה|עלות|₪|שקל", user_text):
        reply = answer_price()
        lead_hint = True
    elif code == "ROI" or re.search(r"החזר|כדאי|משתלם|roi", user_text, re.I):
        reply = answer_roi()
        lead_hint = True
    elif code == "CONTACT" or re.search(r"טלפון|וואטסאפ|מייל|צור קשר|שעות", user_text):
        reply = answer_contact(site)
    elif code and code not in ("PRICE", "ROI", "CONTACT"):
        reply = code
        if any(k in user_text for k in ("רוצה", "מעוניין", "חזרו", "ליד", "הצעה")):
            lead_hint = True
    elif re.search(r"רוצה שיחזרו|השאירו פרטים|ליד|מעוניין|ייעוץ|הצעת מחיר", user_text):
        reply = (
            "מעולה. מלאו שם וטלפון (חובה), יישוב/אזור, ובחרו עניין: סולארי / אגירה / שניהם — "
            "ואעביר ל\"פתיחת ליד\" במחלקת המכירות ב״בן״ (בדמו זה נשמר במסד וב־outbox)."
        )
        lead_hint = True
    else:
        reply = (
            f"תודה על השאלה. אני עוזר של {COMPANY} (דמו).\n"
            "אני יכול לעזור בנושאים: מערכות סולאריות, אגירת אנרגיה, תהליך העבודה, וטווחים שמופיעים באתר.\n"
            "מחירים מדויקים ב־₪ איני ממציא — אציע שיחת ייעוץ.\n"
            "רוצים שאפרט על סולארי, אגירה, או התהליך? או להשאיר פרטים לחזרה?"
        )
        lead_hint = True

    return {
        "reply": reply,
        "lead_hint": lead_hint,
        "quick_replies": KB["quick_replies"],
        "mode": "faq-rules",
    }


def save_message(session_id: str, role: str, content: str, site: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO messages(id,created_at,session_id,role,content,site) VALUES(?,?,?,?,?,?)",
            (str(uuid.uuid4()), now_il(), session_id, role, content, site),
        )


def enqueue_ben_lead(lead: dict) -> str:
    """Mock outbox representing פתיחת ליד in בן sales department."""
    oid = str(uuid.uuid4())
    payload = {
        "target": "בן / מכירות / פתיחת ליד",
        "demo": True,
        "created_at": now_il(),
        "lead": lead,
        "note": "Mock outbox — not pushed to live בן until Ofer says תעלה",
    }
    path = OUTBOX_DIR / f"{oid}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with db() as conn:
        conn.execute(
            "INSERT INTO outbox(id,created_at,lead_id,payload,status) VALUES(?,?,?,?,?)",
            (oid, now_il(), lead["id"], json.dumps(payload, ensure_ascii=False), "queued"),
        )
    return oid


@app.get("/health")
def health():
    return jsonify({"ok": True, "mode": LLM_MODE, "company": COMPANY, "time": now_il()})


@app.get("/api/kb-summary")
def kb_summary():
    return jsonify(
        {
            "company": KB["company"]["name_he"],
            "stated_ranges": KB["stated_ranges"],
            "no_price_policy": KB["no_price_policy"],
            "mode": LLM_MODE,
        }
    )


@app.post("/api/chat")
def api_chat():
    body = request.get_json(force=True, silent=True) or {}
    text = (body.get("message") or "").strip()
    site = (body.get("site") or "solar").strip()
    session_id = (body.get("session_id") or str(uuid.uuid4())).strip()
    if not text:
        return jsonify({"error": "empty"}), 400
    if len(text) > 2000:
        text = text[:2000]
    save_message(session_id, "user", text, site)
    result = build_reply(text, site)
    save_message(session_id, "assistant", result["reply"], site)
    result["session_id"] = session_id
    result["company"] = COMPANY
    return jsonify(result)


@app.post("/api/lead")
def api_lead():
    body = request.get_json(force=True, silent=True) or {}
    name = (body.get("name") or "").strip()
    phone = normalize_phone(body.get("phone") or "")
    settlement = (body.get("settlement") or "").strip()
    interest = (body.get("interest") or "both").strip()
    site = (body.get("site") or "solar").strip()
    notes = (body.get("notes") or "").strip()[:500]
    if not name or len(name) < 2:
        return jsonify({"error": "name_required", "message": "נא למלא שם"}), 400
    if not phone or not PHONE_RE.match(phone):
        return jsonify({"error": "phone_invalid", "message": "נא למלא טלפון ישראלי תקין"}), 400
    if interest not in ("solar", "storage", "both"):
        interest = "both"
    lead_id = str(uuid.uuid4())
    lead = {
        "id": lead_id,
        "created_at": now_il(),
        "name": name,
        "phone": phone,
        "settlement": settlement,
        "interest": interest,
        "site": site,
        "notes": notes,
        "source": "chatbot-demo",
    }
    with db() as conn:
        conn.execute(
            "INSERT INTO leads(id,created_at,name,phone,settlement,interest,site,notes,source) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                lead_id,
                lead["created_at"],
                name,
                phone,
                settlement,
                interest,
                site,
                notes,
                "chatbot-demo",
            ),
        )
    outbox_id = enqueue_ben_lead(lead)
    return jsonify(
        {
            "ok": True,
            "lead_id": lead_id,
            "outbox_id": outbox_id,
            "message": "תודה! הפרטים נשמרו. נחזור אליכם בהקדם (בדמו — נשמר במסד + outbox ל״פתיחת ליד״).",
        }
    )


@app.get("/api/admin/leads")
def admin_leads():
    """Demo admin — no auth in demo; do not use on live."""
    with db() as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY created_at DESC LIMIT 200").fetchall()
        out = conn.execute("SELECT * FROM outbox ORDER BY created_at DESC LIMIT 200").fetchall()
    return jsonify(
        {
            "leads": [dict(r) for r in rows],
            "outbox": [dict(r) for r in out],
            "count": len(rows),
        }
    )


@app.get("/widget.js")
def widget_js():
    """Single-script embeddable floating chat bubble."""
    # Prefer HTTPS when behind Railway proxy; fall back to same-origin relative paths.
    proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host") or request.host
    base = f"{proto}://{host}".rstrip("/")
    if proto == "http" and "railway.app" in host:
        base = "https://" + host
    js = f"""
(function(){{
  if (window.__TSS_CHAT_LOADED) return;
  window.__TSS_CHAT_LOADED = true;
  var BASE = (function(){{
    try {{
      var s = document.currentScript && document.currentScript.src;
      if (s) return new URL(s).origin;
    }} catch (e) {{}}
    return {json.dumps(base)};
  }})();
  var cfg = window.TripleSChat || {{}};
  var site = cfg.site || document.currentScript && document.currentScript.getAttribute('data-site') || 'solar';
  var primary = site === 'storage' ? '#0ea5e9' : '#f59e0b';
  var company = {json.dumps(COMPANY)};
  var session = localStorage.getItem('tss_chat_sid') || (crypto.randomUUID && crypto.randomUUID()) || String(Date.now());
  localStorage.setItem('tss_chat_sid', session);

  var css = `
  #tss-chat-root {{ position:fixed; z-index:2147483000; bottom:20px; left:20px; font-family:Heebo,Arial,sans-serif; direction:rtl; }}
  #tss-chat-bubble {{ width:60px; height:60px; border-radius:50%; border:none; cursor:pointer;
    background:linear-gradient(135deg,${{primary}},#111827); color:#fff; box-shadow:0 8px 24px rgba(0,0,0,.35);
    font-size:26px; display:flex; align-items:center; justify-content:center; }}
  #tss-chat-panel {{ display:none; width:min(380px,calc(100vw - 24px)); height:min(560px,calc(100vh - 100px));
    background:#0b1220; color:#f8fafc; border-radius:18px; overflow:hidden; flex-direction:column;
    box-shadow:0 20px 50px rgba(0,0,0,.45); border:1px solid rgba(255,255,255,.08); }}
  #tss-chat-panel.open {{ display:flex; }}
  #tss-chat-hd {{ padding:14px 16px; background:#111827; display:flex; gap:10px; align-items:center; border-bottom:1px solid rgba(255,255,255,.06); }}
  #tss-chat-hd .ttl {{ font-weight:700; font-size:15px; line-height:1.3; }}
  #tss-chat-hd .sub {{ font-size:12px; opacity:.7; }}
  #tss-chat-msgs {{ flex:1; overflow:auto; padding:14px; display:flex; flex-direction:column; gap:10px; background:#0b1220; }}
  .tss-msg {{ max-width:88%; padding:10px 12px; border-radius:14px; font-size:14px; line-height:1.45; white-space:pre-wrap; }}
  .tss-msg.bot {{ align-self:flex-start; background:#1e293b; }}
  .tss-msg.user {{ align-self:flex-end; background:${{primary}}; color:#111; font-weight:600; }}
  #tss-quick {{ display:flex; flex-wrap:wrap; gap:6px; padding:0 12px 8px; }}
  #tss-quick button {{ background:#1e293b; color:#e2e8f0; border:1px solid rgba(255,255,255,.1); border-radius:999px; padding:6px 10px; font-size:12px; cursor:pointer; }}
  #tss-chat-form {{ display:flex; gap:8px; padding:10px; border-top:1px solid rgba(255,255,255,.06); background:#0f172a; }}
  #tss-chat-form input {{ flex:1; border-radius:12px; border:1px solid rgba(255,255,255,.12); background:#111827; color:#fff; padding:10px 12px; font-size:14px; }}
  #tss-chat-form button {{ border:none; border-radius:12px; background:${{primary}}; color:#111; font-weight:700; padding:0 14px; cursor:pointer; }}
  #tss-lead {{ display:none; padding:12px; border-top:1px solid rgba(255,255,255,.06); background:#0f172a; gap:8px; flex-direction:column; }}
  #tss-lead.open {{ display:flex; }}
  #tss-lead input, #tss-lead select {{ border-radius:10px; border:1px solid rgba(255,255,255,.12); background:#111827; color:#fff; padding:9px 10px; font-size:13px; }}
  #tss-lead .row {{ display:flex; gap:8px; }}
  #tss-lead button {{ border:none; border-radius:10px; background:${{primary}}; color:#111; font-weight:700; padding:10px; cursor:pointer; }}
  #tss-close {{ margin-inline-start:auto; background:transparent; border:none; color:#94a3b8; font-size:20px; cursor:pointer; }}
  `;
  var style = document.createElement('style'); style.textContent = css; document.head.appendChild(style);
  try {{
    var link = document.createElement('link');
    link.rel='stylesheet'; link.href='https://fonts.googleapis.com/css2?family=Heebo:wght@400;600;700&display=swap';
    document.head.appendChild(link);
  }} catch(e){{}}

  var root = document.createElement('div'); root.id='tss-chat-root';
  root.innerHTML = `
    <div id="tss-chat-panel" aria-live="polite">
      <div id="tss-chat-hd">
        <div>
          <div class="ttl">💬 עוזר ${{company}}</div>
          <div class="sub">דמו · מענה בעברית · ללא מחירים מומצאים</div>
        </div>
        <button id="tss-close" aria-label="סגור">×</button>
      </div>
      <div id="tss-chat-msgs"></div>
      <div id="tss-quick"></div>
      <div id="tss-lead">
        <div style="font-size:13px;font-weight:700">השארת פרטים לחזרה (פתיחת ליד)</div>
        <input id="tss-name" placeholder="שם מלא *" autocomplete="name"/>
        <input id="tss-phone" placeholder="טלפון *" inputmode="tel" autocomplete="tel"/>
        <input id="tss-area" placeholder="יישוב / אזור"/>
        <select id="tss-interest">
          <option value="solar">עניין: סולארי</option>
          <option value="storage">עניין: אגירה</option>
          <option value="both" selected>עניין: סולארי + אגירה</option>
        </select>
        <button type="button" id="tss-lead-send">שלחו לי חזרה</button>
        <div id="tss-lead-msg" style="font-size:12px;opacity:.85"></div>
      </div>
      <form id="tss-chat-form">
        <input id="tss-input" placeholder="כתבו שאלה..." autocomplete="off"/>
        <button type="submit">שלח</button>
      </form>
    </div>
    <button id="tss-chat-bubble" aria-label="פתח צ׳אט">💬</button>
  `;
  document.body.appendChild(root);

  var panel = document.getElementById('tss-chat-panel');
  var bubble = document.getElementById('tss-chat-bubble');
  var msgs = document.getElementById('tss-chat-msgs');
  var form = document.getElementById('tss-chat-form');
  var input = document.getElementById('tss-input');
  var quick = document.getElementById('tss-quick');
  var leadBox = document.getElementById('tss-lead');

  function addMsg(text, who){{
    var d=document.createElement('div');
    d.className='tss-msg '+who;
    d.textContent=text;
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
  }}

  function setQuick(list){{
    quick.innerHTML='';
    (list||[]).forEach(function(q){{
      var b=document.createElement('button'); b.type='button'; b.textContent=q;
      b.onclick=function(){{ send(q); }};
      quick.appendChild(b);
    }});
    var lb=document.createElement('button'); lb.type='button'; lb.textContent='רוצה שיחזרו אליי';
    lb.onclick=function(){{ leadBox.classList.add('open'); }};
    quick.appendChild(lb);
  }}

  async function send(text){{
    if(!text) return;
    addMsg(text,'user');
    input.value='';
    try{{
      var r = await fetch(BASE+'/api/chat', {{
        method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{message:text, site:site, session_id:session}})
      }});
      var j = await r.json();
      addMsg(j.reply||'שגיאה','bot');
      setQuick(j.quick_replies);
      if(j.lead_hint) leadBox.classList.add('open');
    }}catch(e){{
      addMsg('לא הצלחתי להתחבר לשרת הדמו. נסו שוב.','bot');
    }}
  }}

  bubble.onclick=function(){{ panel.classList.toggle('open'); if(panel.classList.contains('open') && !msgs.childElementCount){{
    addMsg('שלום! אני עוזר של '+company+'. אפשר לשאול על סולארי, אגירה, תהליך העבודה או להשאיר פרטים לחזרה. מחירים מדויקים ב־₪ איני ממציא.','bot');
    setQuick({json.dumps(KB["quick_replies"], ensure_ascii=False)});
  }}}};
  document.getElementById('tss-close').onclick=function(){{ panel.classList.remove('open'); }};
  form.onsubmit=function(e){{ e.preventDefault(); send(input.value.trim()); }};

  document.getElementById('tss-lead-send').onclick=async function(){{
    var name=document.getElementById('tss-name').value.trim();
    var phone=document.getElementById('tss-phone').value.trim();
    var settlement=document.getElementById('tss-area').value.trim();
    var interest=document.getElementById('tss-interest').value;
    var msg=document.getElementById('tss-lead-msg');
    try{{
      var r=await fetch(BASE+'/api/lead',{{
        method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{name, phone, settlement, interest, site, notes:'from widget'}})
      }});
      var j=await r.json();
      if(!r.ok){{ msg.textContent=j.message||'שגיאה'; msg.style.color='#fca5a5'; return; }}
      msg.style.color='#86efac'; msg.textContent=j.message;
      addMsg('תודה '+name+'! קיבלנו את הפרטים.','bot');
    }}catch(e){{ msg.textContent='שגיאת רשת'; msg.style.color='#fca5a5'; }}
  }};
}})();
"""
    return Response(js, mimetype="application/javascript; charset=utf-8")


DEMO_PAGE = """
<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>דמו צ׳אט · טריפל אס אנרגיה מתחדשת</title>
<link href="https://fonts.googleapis.com/css2?family=Heebo:wght@400;600;700&display=swap" rel="stylesheet"/>
<style>
  :root { --bg:#0a0a0f; --card:#12121a; --amber:#f59e0b; --sky:#0ea5e9; }
  *{box-sizing:border-box}
  body{margin:0;font-family:Heebo,Arial,sans-serif;background:var(--bg);color:#f1f5f9;min-height:100vh}
  header{padding:20px 24px;border-bottom:1px solid rgba(255,255,255,.08);display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between}
  h1{margin:0;font-size:1.25rem}
  .badge{font-size:.75rem;background:#1e293b;padding:4px 10px;border-radius:999px;opacity:.9}
  .tabs{display:flex;gap:8px}
  .tabs a{color:#cbd5e1;text-decoration:none;padding:8px 14px;border-radius:999px;border:1px solid rgba(255,255,255,.1)}
  .tabs a.active{background:var(--amber);color:#111;font-weight:700;border-color:transparent}
  .tabs a.storage.active{background:var(--sky)}
  main{padding:16px;display:grid;gap:16px;max-width:1200px;margin:0 auto}
  .note{background:#1e293b;border-radius:14px;padding:14px 16px;font-size:.92rem;line-height:1.5;border:1px solid rgba(255,255,255,.06)}
  .frame-wrap{position:relative;border-radius:16px;overflow:hidden;border:1px solid rgba(255,255,255,.1);min-height:70vh;background:#000}
  .mock{position:absolute;inset:0;background:
    linear-gradient(180deg, rgba(0,0,0,.55), rgba(0,0,0,.75)),
    {% if site=='storage' %}
    linear-gradient(135deg,#0c4a6e,#020617 60%);
    {% else %}
    linear-gradient(135deg,#78350f,#020617 60%);
    {% endif %}
  }
  .mock-inner{position:relative;z-index:1;padding:28px 22px;max-width:720px}
  .mock-inner h2{margin:0 0 8px;font-size:1.6rem}
  .mock-inner p{opacity:.85;line-height:1.55}
  .mock-nav{display:flex;gap:14px;flex-wrap:wrap;font-size:.85rem;opacity:.7;margin-bottom:28px}
  .cta{display:inline-block;margin-top:12px;background:{% if site=='storage' %}var(--sky){% else %}var(--amber){% endif %};color:#111;font-weight:700;padding:10px 16px;border-radius:10px;text-decoration:none}
  code{background:#0f172a;padding:2px 6px;border-radius:6px;font-size:.85rem}
  .embed{font-size:.85rem;background:#0f172a;padding:12px;border-radius:10px;overflow:auto;direction:ltr;text-align:left}
  footer{padding:20px;text-align:center;opacity:.6;font-size:.8rem}
</style>
</head>
<body>
<header>
  <div>
    <h1>דמו עוזר צ׳אט · {{ company }}</h1>
    <div class="badge">מצב: FAQ/כללים · ללא מפתח LLM בסביבה · לא נוגע באתרים החיים</div>
  </div>
  <nav class="tabs">
    <a class="{{ 'active' if site=='solar' else '' }}" href="/?site=solar">אתר סולארי</a>
    <a class="storage {{ 'active' if site=='storage' else '' }}" href="/?site=storage">אתר אגירה</a>
    <a href="/admin">לידים (דמו)</a>
  </nav>
</header>
<main>
  <div class="note">
    זה דמו בלבד. הווידג׳ט צף בפינה (כמו בחנות). הידע מבוסס על תוכן ציבורי שנמשך מ־
    <a style="color:#93c5fd" href="https://triplesolar.co.il" target="_blank" rel="noopener">triplesolar.co.il</a>
    ו־
    <a style="color:#93c5fd" href="https://triples-storage.co.il" target="_blank" rel="noopener">triples-storage.co.il</a>.
    אין מחירים מומצאים. ליד נשמר בדמו + outbox ל״פתיחת ליד״ במכירות.
  </div>
  <div class="frame-wrap" id="mock-frame">
    <div class="mock">
      <div class="mock-inner">
        <div class="mock-nav">
          <span>ראשי</span><span>מוצרים</span><span>פרויקטים</span><span>אודות</span><span>צור קשר</span>
        </div>
        {% if site=='storage' %}
        <h2>פתרונות אחסון אנרגיה חכמים</h2>
        <p>מאגרים עודפי חשמל בשעות ביקוש נמוך ומחזירים אותם בשעות השיא — לעסקים, ליזמים ולבתי מגורים. (מסך דמו המדמה את triples-storage.co.il)</p>
        <a class="cta" href="https://triples-storage.co.il" target="_blank" rel="noopener">לאתר האגירה</a>
        {% else %}
        <h2>פתרונות סולאריים חכמים</h2>
        <p>תכנון, הקמה וליווי של מערכות סולאריות ואגירה. (מסך דמו המדמה את triplesolar.co.il — הרקע הכהה של האתר החי לא השתנה כאן)</p>
        <a class="cta" href="https://triplesolar.co.il" target="_blank" rel="noopener">לאתר הסולארי</a>
        {% endif %}
      </div>
    </div>
  </div>
  <div class="note">
    הטמעה באתר (אחרי אישור ״תעלה״):
    <div class="embed">&lt;script src="{{ request.url_root }}widget.js" data-site="{{ site }}"&gt;&lt;/script&gt;</div>
  </div>
</main>
<footer>Demo service in Railway project triples-calculators-demo · {{ company }}</footer>
<script src="/widget.js" data-site="{{ site }}"></script>
</body>
</html>
"""


ADMIN_PAGE = """
<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>לידים דמו · צ׳אט</title>
<style>
 body{font-family:Heebo,Arial,sans-serif;background:#0b1220;color:#e2e8f0;margin:0;padding:20px;direction:rtl}
 table{width:100%;border-collapse:collapse;font-size:14px}
 th,td{border-bottom:1px solid rgba(255,255,255,.08);padding:8px;text-align:right}
 a{color:#93c5fd}
</style>
</head>
<body>
<h1>לידים שנאספו בדמו</h1>
<p><a href="/">חזרה לדמו</a> · <a href="/api/admin/leads">JSON</a></p>
<table>
<thead><tr><th>זמן</th><th>שם</th><th>טלפון</th><th>יישוב</th><th>עניין</th><th>אתר</th></tr></thead>
<tbody>
{% for L in leads %}
<tr>
<td>{{ L['created_at'] }}</td><td>{{ L['name'] }}</td><td>{{ L['phone'] }}</td>
<td>{{ L['settlement'] or '—' }}</td><td>{{ L['interest'] }}</td><td>{{ L['site'] }}</td>
</tr>
{% else %}
<tr><td colspan="6">אין לידים עדיין — נסו מהווידג׳ט.</td></tr>
{% endfor %}
</tbody>
</table>
<h2>Outbox → בן / מכירות / פתיחת ליד (mock)</h2>
<ul>
{% for o in outbox %}
<li><code>{{ o['id'] }}</code> · {{ o['created_at'] }} · {{ o['status'] }}</li>
{% else %}
<li>ריק</li>
{% endfor %}
</ul>
</body>
</html>
"""


@app.get("/")
def home():
    site = request.args.get("site", "solar")
    if site not in ("solar", "storage"):
        site = "solar"
    return render_template_string(DEMO_PAGE, site=site, company=COMPANY)


@app.get("/admin")
def admin_page():
    with db() as conn:
        leads = conn.execute("SELECT * FROM leads ORDER BY created_at DESC LIMIT 200").fetchall()
        outbox = conn.execute("SELECT * FROM outbox ORDER BY created_at DESC LIMIT 200").fetchall()
    return render_template_string(
        ADMIN_PAGE, leads=[dict(r) for r in leads], outbox=[dict(r) for r in outbox]
    )


@app.get("/static/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
