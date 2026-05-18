from dotenv import load_dotenv

load_dotenv()
import base64
from hmac import compare_digest
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

QUO_BASE_URL = os.getenv("QUO_BASE_URL", "https://api.openphone.com")
QUO_API_KEY = os.getenv("QUO_API_KEY")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
BUSINESS_PHONE_NUMBER = os.getenv("BUSINESS_PHONE_NUMBER", "+12245760059")

if not QUO_API_KEY:
    raise RuntimeError("QUO_API_KEY is not set")

if not PHONE_NUMBER_ID:
    raise RuntimeError("PHONE_NUMBER_ID is not set")

GPT_SHARED_SECRET = os.getenv("GPT_SHARED_SECRET", "")
DATABASE_PATH = os.getenv("DATABASE_PATH") or "summaries.db"
MAX_CONVERSATIONS = int(os.getenv("MAX_CONVERSATIONS", "25"))
HTTP_TIMEOUT_SECONDS = int(os.getenv("HTTP_TIMEOUT_SECONDS", "30"))
HTTP_SESSION = requests.Session()
BASIC_AUTH_FILE = os.getenv(
    "QUO_BASIC_AUTH_FILE",
    "/root/.openclaw/workspace/dashboards/.dashboard-auth.json",
)

print("QUO_API_KEY loaded:", bool(QUO_API_KEY))


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting app...")
    print("DB PATH:", os.path.abspath(DATABASE_PATH))

    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            last_activity_id TEXT PRIMARY KEY,
            participant_number TEXT,
            raw_conversation_json TEXT,
            last_activity_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS summaries (
            call_id TEXT PRIMARY KEY,
            last_activity_id TEXT,
            participant_number TEXT,
            next_steps TEXT,
            status TEXT,
            summary TEXT,
            raw_summary_json TEXT,
            last_activity_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            message_id TEXT PRIMARY KEY,
            participant_number TEXT,
            direction TEXT,
            text TEXT,
            created_at TEXT,
            raw_message_json TEXT,
            stored_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute(""" 
        CREATE TABLE IF NOT EXISTS voicemails (
            call_id TEXT PRIMARY KEY,
            phone_number_id TEXT,
            participant_phone_number TEXT,
            participant_name TEXT,
            transcript TEXT,
            recording_url TEXT,
            created_at TEXT,
            updated_at TEXT,
            raw_json TEXT
        )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_last_activity_at
        ON conversations(last_activity_at DESC)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_summaries_last_activity_at
        ON summaries(last_activity_at DESC)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_summaries_last_activity_id
        ON summaries(last_activity_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_participant_created
        ON messages(participant_number, created_at DESC)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_voicemails_participant_created
        ON voicemails(participant_phone_number, created_at DESC)
    """)

    conn.commit()
    app.state.db = conn

    yield

    print("Shutting down...")
    conn.close()


app = FastAPI(
    title="KMF Schaumburg Quo Activity Wrapper",
    version="3.0.0",
    lifespan=lifespan,
)


def require_gpt_secret(x_wrapper_secret: Optional[str]) -> None:
    if GPT_SHARED_SECRET and x_wrapper_secret != GPT_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Invalid wrapper secret")


def load_basic_credentials() -> Optional[dict[str, str]]:
    username = os.getenv("QUO_BASIC_USER") or os.getenv("DASHBOARD_USER")
    password = os.getenv("QUO_BASIC_PASSWORD") or os.getenv("DASHBOARD_PASSWORD")
    if username and password:
        return {"username": username, "password": password}

    auth_path = Path(BASIC_AUTH_FILE)
    if auth_path.exists():
        data = json.loads(auth_path.read_text(encoding="utf-8"))
        if data.get("username") and data.get("password"):
            return {"username": data["username"], "password": data["password"]}

    return None


BASIC_CREDENTIALS = load_basic_credentials()


def valid_wrapper_secret(x_wrapper_secret: Optional[str]) -> bool:
    return bool(GPT_SHARED_SECRET and x_wrapper_secret == GPT_SHARED_SECRET)


def valid_basic_auth(authorization: Optional[str]) -> bool:
    if not BASIC_CREDENTIALS or not authorization or not authorization.startswith("Basic "):
        return False

    try:
        decoded = base64.b64decode(authorization[6:]).decode("utf-8")
    except Exception:
        return False

    username, separator, password = decoded.partition(":")
    if not separator:
        return False

    return (
        compare_digest(username, BASIC_CREDENTIALS["username"])
        and compare_digest(password, BASIC_CREDENTIALS["password"])
    )


@app.middleware("http")
async def require_public_auth(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    if valid_wrapper_secret(request.headers.get("x-wrapper-secret")):
        request.state.authenticated_by = "wrapper-secret"
        return await call_next(request)

    if valid_basic_auth(request.headers.get("authorization")):
        request.state.authenticated_by = "basic"
        return await call_next(request)

    return Response(
        "Authentication required\n",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="KMF Schaumburg QUO", charset="UTF-8"'},
        media_type="text/plain",
    )


def require_api_access(request: Request, x_wrapper_secret: Optional[str]) -> None:
    if getattr(request.state, "authenticated_by", None) == "basic":
        return
    require_gpt_secret(x_wrapper_secret)


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KMF Schaumburg QUO</title>
  <style>
    :root { color-scheme: dark; --bg: #0e1116; --panel: #171b22; --line: #2b3240; --text: #eef2f7; --muted: #99a4b3; --accent: #f2c94c; --danger: #ff6b6b; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
    header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 20px clamp(16px, 4vw, 40px); border-bottom: 1px solid var(--line); }
    h1 { margin: 0; font-size: clamp(22px, 3vw, 32px); letter-spacing: 0; }
    main { width: min(1180px, 100%); margin: 0 auto; padding: 24px clamp(16px, 4vw, 40px) 48px; }
    button { border: 1px solid var(--line); background: #222936; color: var(--text); border-radius: 6px; padding: 10px 14px; font: inherit; cursor: pointer; }
    button.primary { background: var(--accent); border-color: var(--accent); color: #16130a; font-weight: 700; }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 18px; }
    .status { color: var(--muted); min-height: 24px; }
    .stack { display: grid; gap: 24px; }
    .panel h2 { font-size: 20px; margin: 0 0 12px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; }
    .card { border: 1px solid var(--line); background: var(--panel); border-radius: 8px; padding: 16px; min-width: 0; }
    .card h2 { margin: 0 0 8px; font-size: 18px; letter-spacing: 0; overflow-wrap: anywhere; }
    .meta { color: var(--muted); font-size: 13px; margin-bottom: 12px; overflow-wrap: anywhere; }
    .section { margin-top: 12px; }
    .label { color: var(--accent); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
    .field { margin-top: 12px; }
    .field-label { color: var(--accent); display: block; font-size: 12px; font-weight: 700; text-transform: uppercase; }
    .badge { border: 1px solid var(--line); border-radius: 999px; color: var(--muted); display: inline-block; font-size: 12px; font-weight: 700; margin-bottom: 10px; padding: 4px 8px; text-transform: uppercase; }
    .badge.hot { border-color: var(--accent); color: var(--accent); }
    .suggestions { display: grid; gap: 10px; }
    .suggestion { border: 1px solid var(--line); border-left: 4px solid var(--accent); background: var(--panel); border-radius: 8px; padding: 12px 14px; }
    .suggestion strong { display: block; margin-bottom: 4px; overflow-wrap: anywhere; }
    p { margin: 6px 0 0; line-height: 1.45; overflow-wrap: anywhere; }
    ul { margin: 6px 0 0; padding-left: 18px; }
    li { margin: 4px 0; line-height: 1.4; overflow-wrap: anywhere; }
    .empty, .error { border: 1px solid var(--line); border-radius: 8px; padding: 18px; color: var(--muted); background: var(--panel); }
    .error { color: var(--danger); border-color: var(--danger); }
  </style>
</head>
<body>
  <header><h1>KMF Schaumburg QUO</h1><button id="sync" class="primary">Sync now</button></header>
  <main><div class="toolbar"><button id="refresh">Refresh activity</button><span id="status" class="status"></span></div><div id="content" class="empty">Syncing activity...</div></main>
  <script>
    const content = document.getElementById("content");
    const statusEl = document.getElementById("status");
    const syncButton = document.getElementById("sync");
    const refreshButton = document.getElementById("refresh");
    function esc(value, fallback) {
      const text = value == null || value === "" ? (fallback || "None found") : String(value);
      return text.replace(/[&<>\"]/g, function(ch) { return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[ch]; });
    }
    function apiPath(path) {
      const mountPath = window.location.pathname.split("/").filter(Boolean)[0];
      const prefix = mountPath ? "/" + mountPath : "";
      return prefix + path;
    }
    function missing(value) {
      return value == null || value === "" || value === "None found";
    }
    function allText(item) {
      const summary = item.call_summary || {};
      const messages = (item.messages || []).map(function(msg) { return msg.text || ""; }).join(" ");
      const voicemails = (item.voicemails || []).map(function(vm) { return vm.transcript || ""; }).join(" ");
      return [summary.summary, summary.next_steps, messages, voicemails].filter(Boolean).join(" ").toLowerCase();
    }
    function priorityScore(item) {
      const text = allText(item);
      const rules = [
        ["trial", 40], ["free class", 40], ["free trial", 45], ["book", 25], ["schedule", 25],
        ["price", 35], ["pricing", 35], ["membership", 35], ["cost", 30], ["month", 20],
        ["private", 35], ["training", 25], ["missed", 30], ["call back", 30], ["callback", 30],
        ["lead", 25], ["interested", 25], ["urgent", 45], ["student", 15], ["member", 15]
      ];
      return rules.reduce(function(score, rule) {
        return score + (text.indexOf(rule[0]) >= 0 ? rule[1] : 0);
      }, 0);
    }
    function priorityLabel(item) {
      const score = priorityScore(item);
      if (score >= 60) return "Hot lead";
      if (score >= 30) return "Follow-up";
      return "Recent activity";
    }
    function inferredNextStep(item) {
      const summary = item.call_summary || {};
      if (!missing(summary.next_steps)) return summary.next_steps;
      const text = allText(item);
      if (text.indexOf("trial") >= 0 || text.indexOf("free class") >= 0) return "Follow up to book the free trial lesson.";
      if (text.indexOf("price") >= 0 || text.indexOf("pricing") >= 0 || text.indexOf("membership") >= 0 || text.indexOf("cost") >= 0) return "Follow up with membership options and offer a trial lesson.";
      if (text.indexOf("private") >= 0 || text.indexOf("training") >= 0) return "Follow up about private training availability and goals.";
      if ((item.messages || []).length || (item.voicemails || []).length) return "Review the latest message and respond if no reply has been sent.";
      return "Call back to confirm what they need and offer the next available trial lesson.";
    }
    function isToday(value) {
      if (!value) return false;
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return false;
      const now = new Date();
      return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
    }
    function cardHtml(item) {
      const summary = item.call_summary || {};
      const messages = (item.messages || []).slice(0, 5).map(function(msg) { return "<li><strong>" + esc(msg.direction, "unknown") + ":</strong> " + esc(msg.text, "") + "<br><span class=\"meta\">" + esc(msg.created_at, "") + "</span></li>"; }).join("");
      const voicemailText = (item.voicemails || []).map(function(vm) { return vm.transcript; }).filter(Boolean).join(" ");
      const messageBlock = messages ? "<ul>" + messages + "</ul>" : (voicemailText ? "<p>" + esc(voicemailText) + "</p>" : "<p>None found</p>");
      const label = priorityLabel(item);
      return "<article class=\"card\"><span class=\"badge " + (label === "Hot lead" ? "hot" : "") + "\">" + esc(label) + "</span><h2><span class=\"field-label\">Phone number:</span>" + esc(item.phone_number, "Unknown") + "</h2><div class=\"field\"><span class=\"field-label\">Last activity:</span><p>" + esc(item.last_activity_at, "Unknown") + "</p></div><div class=\"field\"><span class=\"field-label\">Messages:</span>" + messageBlock + "</div><div class=\"field\"><span class=\"field-label\">Call summary:</span><p>" + esc(summary.summary) + "</p></div><div class=\"field\"><span class=\"field-label\">Next steps:</span><p>" + esc(inferredNextStep(item)) + "</p></div></article>";
    }
    function sectionHtml(title, items, emptyText) {
      return "<section class=\"panel\"><h2>" + esc(title) + "</h2>" + (items.length ? "<div class=\"grid\">" + items.map(cardHtml).join("") + "</div>" : "<div class=\"empty\">" + esc(emptyText) + "</div>") + "</section>";
    }
    function suggestionsHtml(items) {
      const suggestions = items.filter(function(item) {
        return priorityScore(item) >= 30 || missing((item.call_summary || {}).next_steps);
      }).slice(0, 8);
      return "<section class=\"panel\"><h2>Follow-up suggestions</h2>" + (suggestions.length ? "<div class=\"suggestions\">" + suggestions.map(function(item) { return "<div class=\"suggestion\"><strong>" + esc(item.phone_number, "Unknown") + "</strong><p>" + esc(inferredNextStep(item)) + "</p></div>"; }).join("") + "</div>" : "<div class=\"empty\">No follow-up suggestions found.</div>") + "</section>";
    }
    function render(data) {
      const activities = (data.activities || []).slice().sort(function(a, b) {
        const priority = priorityScore(b) - priorityScore(a);
        if (priority) return priority;
        return String(b.last_activity_at || "").localeCompare(String(a.last_activity_at || ""));
      });
      if (!activities.length) { content.className = "empty"; content.textContent = "No recent activity was found."; return; }
      const today = activities.filter(function(item) { return isToday(item.last_activity_at); });
      content.className = "stack";
      content.innerHTML = [
        sectionHtml("Latest QUO activity", activities, "No recent activity was found."),
        sectionHtml("Today's activity", today, "No activity found for today."),
        suggestionsHtml(activities),
      ].join("");
    }
    async function request(path, options) { const response = await fetch(path, options); if (!response.ok) throw new Error(await response.text() || String(response.status)); return response.json(); }
    async function syncAndLoadActivity() { syncButton.disabled = true; refreshButton.disabled = true; statusEl.textContent = "Syncing from OpenPhone..."; try { await request(apiPath("/api/quo/schaumburg/sync-activity"), { method: "POST" }); statusEl.textContent = "Loading activity..."; render(await request(apiPath("/api/quo/schaumburg/activity"))); statusEl.textContent = "Updated " + new Date().toLocaleString(); } catch (error) { content.className = "error"; content.textContent = error.message; statusEl.textContent = "Load failed"; } finally { syncButton.disabled = false; refreshButton.disabled = false; } }
    syncButton.addEventListener("click", syncAndLoadActivity); refreshButton.addEventListener("click", syncAndLoadActivity); syncAndLoadActivity();
  </script>
</body>
</html>"""


def get_last_sync(conn):
    row = conn.execute("SELECT value FROM sync_state WHERE key='last_call_sync'").fetchone()
    return row["value"] if row else None


def set_last_sync(conn, timestamp):
    conn.execute("""
        INSERT OR REPLACE INTO sync_state (key, value)
        VALUES ('last_call_sync', ?)
    """, (timestamp,))


def quo_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not QUO_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Missing QUO_API_KEY environment variable",
        )

    response = HTTP_SESSION.get(
        f"{QUO_BASE_URL}{path}",
        headers={"Authorization": QUO_API_KEY},
        params=params,
        timeout=HTTP_TIMEOUT_SECONDS,
    )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail={
                "url": response.url,
                "quo_error": response.text,
            },
        )

    return response.json()


def fetch_conversations() -> Dict[str, Any]:
    return quo_get(
        "/v1/conversations",
        params={"maxResults": MAX_CONVERSATIONS},
    )


def extract_participant_number(conversation: Dict[str, Any]) -> str:
    participants = conversation.get("participants") or []

    for participant in participants:
        if isinstance(participant, str):
            phone = participant
        elif isinstance(participant, dict):
            phone = (
                    participant.get("phoneNumber")
                    or participant.get("phone")
                    or participant.get("number")
            )
        else:
            continue

        if phone and phone != BUSINESS_PHONE_NUMBER:
            return phone

    return "Unknown"


def fetch_call_summary(activity_id: str) -> Optional[Dict[str, Any]]:
    try:
        return quo_get(f"/v1/call-summaries/{activity_id}").get("data", {})
    except HTTPException as e:
        error_text = str(e.detail)
        if "0500404" in error_text or "not found" in error_text.lower():
            return None
        print(f"SUMMARY ERROR for {activity_id}: {e.detail}")
        return None


def fetch_messages_for_phone(participant_number: str, max_results: int = 25) -> list[Dict[str, Any]]:
    return quo_get(
        "/v1/messages",
        params={
            "phoneNumberId": PHONE_NUMBER_ID,
            "participants": participant_number,
            "maxResults": max_results,
        },
    ).get("data", [])


def fetch_and_store_voicemails(conn: sqlite3.Connection) -> Dict[str, Any]:
    last_sync = get_last_sync(conn)

    params = {
        "phoneNumberId": PHONE_NUMBER_ID,
        "maxResults": 50,
    }

    if last_sync:
        params["createdAfter"] = last_sync

    calls_response = quo_get("/v1/calls", params=params)
    calls = calls_response.get("data", [])

    saved = 0
    checked = 0
    skipped_no_voicemail = 0
    errors = []

    for call in calls:
        call_id = call.get("id")
        phone_number_id = call.get("phoneNumberId")
        participants = call.get("participants") or []

        if not call_id:
            continue

        checked += 1

        participant_number = "Unknown"

        for participant in participants:
            if isinstance(participant, str):
                participant_number = participant
                break

            if isinstance(participant, dict):
                participant_number = (
                        participant.get("phoneNumber")
                        or participant.get("phone")
                        or participant.get("number")
                        or "Unknown"
                )
                break

        try:
            voicemail_response = quo_get(f"/v1/call-voicemails/{call_id}")
            voicemail = voicemail_response.get("data")
        except HTTPException as e:
            error_text = str(e.detail).lower()

            if "not found" in error_text or "404" in error_text:
                skipped_no_voicemail += 1
                continue

            errors.append({
                "call_id": call_id,
                "error": e.detail,
            })
            continue

        if not voicemail:
            skipped_no_voicemail += 1
            continue

        conn.execute("""
            INSERT OR REPLACE INTO voicemails (
                call_id,
                phone_number_id,
                participant_phone_number,
                participant_name,
                transcript,
                recording_url,
                created_at,
                updated_at,
                raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            call_id,
            phone_number_id,
            participant_number,
            None,
            voicemail.get("transcript"),
            voicemail.get("recordingUrl"),
            call.get("createdAt") or call.get("startedAt") or call.get("completedAt"),
            datetime.now(timezone.utc).isoformat(),
            json.dumps({
                "call": call,
                "voicemail": voicemail,
            }),
        ))

        saved += 1

    set_last_sync(conn, datetime.now(timezone.utc).isoformat())
    conn.commit()

    return {
        "voicemails_checked_from_calls_endpoint": checked,
        "voicemails_saved": saved,
        "skipped_no_voicemail": skipped_no_voicemail,
        "voicemail_errors": errors,
    }


def save_conversation(conn: sqlite3.Connection, last_activity_id: str, last_activity_at: str,
                      conversation: Dict[str, Any]) -> str:
    participant_number = extract_participant_number(conversation)

    conn.execute(
        """
        INSERT OR REPLACE INTO conversations
        (last_activity_id, participant_number, raw_conversation_json, last_activity_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            last_activity_id,
            participant_number,
            json.dumps(conversation),
            last_activity_at,
        ),
    )

    return participant_number


def save_summary(
        conn: sqlite3.Connection,
        last_activity_id: str,
        last_activity_at: str,
        participant_number: str,
        summary_data: Dict[str, Any],
) -> bool:
    call_id = summary_data.get("callId")
    status = summary_data.get("status")
    summary = summary_data.get("summary") or []
    next_steps = summary_data.get("nextSteps") or []

    if not call_id:
        return False

    conn.execute(
        """
        INSERT OR REPLACE INTO summaries
        (call_id, last_activity_id, participant_number, next_steps, status, summary, raw_summary_json, last_activity_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            call_id,
            last_activity_id,
            participant_number,
            " ".join(next_steps),
            status,
            " ".join(summary),
            json.dumps(summary_data),
            last_activity_at,
        ),
    )

    return True


def save_message(
        conn: sqlite3.Connection,
        participant_number: str,
        message: Dict[str, Any],
) -> bool:
    message_id = message.get("id")
    text = message.get("text") or ""

    if not message_id or not text:
        return False

    conn.execute(
        """
        INSERT OR REPLACE INTO messages
        (message_id, participant_number, direction, text, created_at, raw_message_json, stored_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message_id,
            participant_number,
            message.get("direction"),
            text,
            message.get("createdAt"),
            json.dumps(message),
            datetime.now(timezone.utc).isoformat(),
        ),
    )

    return True


def save_voicemail(
        conn: sqlite3.Connection,
        call: Dict[str, Any],
        voicemail: Dict[str, Any],
) -> bool:
    call_id = call.get("id")

    if not call_id:
        return False

    participant_number = extract_participant_number(call)

    transcript = voicemail.get("transcript")
    recording_url = voicemail.get("recordingUrl")

    conn.execute("""
        INSERT OR REPLACE INTO voicemails (
            call_id,
            phone_number_id,
            participant_phone_number,
            participant_name,
            transcript,
            recording_url,
            created_at,
            updated_at,
            raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        call_id,
        call.get("phoneNumberId"),
        participant_number,
        None,
        transcript,
        recording_url,
        call.get("createdAt") or call.get("startedAt") or call.get("completedAt"),
        datetime.now(timezone.utc).isoformat(),
        json.dumps({
            "call": call,
            "voicemail": voicemail,
        }),
    ))

    return True


def existing_ids(
        conn: sqlite3.Connection,
        table: str,
        id_column: str,
        ids: list[str],
) -> set[str]:
    if not ids:
        return set()

    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT {id_column} FROM {table} WHERE {id_column} IN ({placeholders})",
        ids,
    ).fetchall()
    return {row[id_column] for row in rows}


def latest_message_created_at(
        conn: sqlite3.Connection,
        participant_number: str,
) -> Optional[str]:
    row = conn.execute(
        """
        SELECT created_at
        FROM messages
        WHERE participant_number = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (participant_number,),
    ).fetchone()
    return row["created_at"] if row else None


def should_fetch_messages(
        conn: sqlite3.Connection,
        participant_number: str,
        last_activity_id: Optional[str],
        last_activity_at: Optional[str],
        call_ids: list[str],
) -> bool:
    latest_stored_message_at = latest_message_created_at(conn, participant_number)

    if not latest_stored_message_at:
        return True

    if last_activity_id in call_ids:
        return False

    if not last_activity_at:
        return True

    return latest_stored_message_at < last_activity_at


def fetch_recent_messages_by_participant(
        conn: sqlite3.Connection,
        participant_numbers: list[str],
) -> dict[str, list[sqlite3.Row]]:
    if not participant_numbers:
        return {}

    placeholders = ", ".join("?" for _ in participant_numbers)
    rows = conn.execute(
        f"""
        SELECT participant_number, direction, text, created_at
        FROM (
            SELECT
                participant_number,
                direction,
                text,
                created_at,
                ROW_NUMBER() OVER (
                    PARTITION BY participant_number
                    ORDER BY created_at DESC
                ) AS row_num
            FROM messages
            WHERE participant_number IN ({placeholders})
        )
        WHERE row_num <= 10
        ORDER BY participant_number, created_at DESC
        """,
        participant_numbers,
    ).fetchall()

    grouped: dict[str, list[sqlite3.Row]] = {
        participant_number: [] for participant_number in participant_numbers
    }
    for row in rows:
        grouped[row["participant_number"]].append(row)
    return grouped


def fetch_recent_voicemails_by_participant(
        conn: sqlite3.Connection,
        participant_numbers: list[str],
) -> dict[str, list[sqlite3.Row]]:
    if not participant_numbers:
        return {}

    placeholders = ", ".join("?" for _ in participant_numbers)
    rows = conn.execute(
        f"""
        SELECT
            call_id,
            phone_number_id,
            participant_phone_number,
            participant_name,
            transcript,
            recording_url,
            created_at
        FROM (
            SELECT
                call_id,
                phone_number_id,
                participant_phone_number,
                participant_name,
                transcript,
                recording_url,
                created_at,
                ROW_NUMBER() OVER (
                    PARTITION BY participant_phone_number
                    ORDER BY created_at DESC
                ) AS row_num
            FROM voicemails
            WHERE participant_phone_number IN ({placeholders})
        )
        WHERE row_num <= 10
        ORDER BY participant_phone_number, created_at DESC
        """,
        participant_numbers,
    ).fetchall()

    grouped: dict[str, list[sqlite3.Row]] = {
        participant_number: [] for participant_number in participant_numbers
    }
    for row in rows:
        grouped[row["participant_phone_number"]].append(row)
    return grouped


def sync_latest_activity(conn: sqlite3.Connection) -> Dict[str, Any]:
    conversations_response = quo_get(
        "/v1/conversations",
        params={
            "phoneNumberId": PHONE_NUMBER_ID,
            "maxResults": 10,
        },
    )

    conversations = conversations_response.get("data", [])

    conversations_seen = 0
    messages_saved = 0
    calls_checked = 0
    summaries_saved = 0
    voicemails_saved = 0
    skipped_existing_messages = 0
    skipped_existing_summaries = 0
    skipped_existing_voicemails = 0

    for conversation in conversations:
        conversations_seen += 1

        last_activity_id = conversation.get("lastActivityId")
        last_activity_at = conversation.get("lastActivityAt")
        participant_number = extract_participant_number(conversation)

        if not participant_number or participant_number == "Unknown":
            continue

        save_conversation(
            conn,
            last_activity_id,
            last_activity_at,
            conversation,
        )

        calls_response = quo_get(
            "/v1/calls",
            params={
                "phoneNumberId": PHONE_NUMBER_ID,
                "participants": participant_number,
                "maxResults": 10,
            },
        )

        calls = calls_response.get("data", [])
        call_ids = [call["id"] for call in calls if call.get("id")]
        existing_summary_ids = existing_ids(conn, "summaries", "call_id", call_ids)
        existing_voicemail_ids = existing_ids(conn, "voicemails", "call_id", call_ids)

        if should_fetch_messages(
                conn,
                participant_number,
                last_activity_id,
                last_activity_at,
                call_ids,
        ):
            messages = fetch_messages_for_phone(participant_number, max_results=10)
            message_ids = [message["id"] for message in messages if message.get("id")]
            existing_message_ids = existing_ids(
                conn,
                "messages",
                "message_id",
                message_ids,
            )

            for message in messages:
                message_id = message.get("id")
                if message_id in existing_message_ids:
                    skipped_existing_messages += 1
                    continue

                if save_message(conn, participant_number, message):
                    messages_saved += 1
                    if message_id:
                        existing_message_ids.add(message_id)
        else:
            skipped_existing_messages += 1

        for call in calls:
            calls_checked += 1

            call_id = call.get("id")
            if not call_id:
                continue

            if call_id not in existing_summary_ids:
                summary_data = fetch_call_summary(call_id)

                if summary_data:
                    if save_summary(
                            conn=conn,
                            last_activity_id=last_activity_id,
                            last_activity_at=call.get("createdAt") or last_activity_at,
                            participant_number=participant_number,
                            summary_data=summary_data,
                    ):
                        summaries_saved += 1
                        existing_summary_ids.add(call_id)
            else:
                skipped_existing_summaries += 1

            if call_id not in existing_voicemail_ids:
                try:
                    voicemail_response = quo_get(f"/v1/call-voicemails/{call_id}")
                    voicemail = voicemail_response.get("data")
                except HTTPException:
                    voicemail = None

                if voicemail:
                    if save_voicemail(conn, call, voicemail):
                        voicemails_saved += 1
                        existing_voicemail_ids.add(call_id)
            else:
                skipped_existing_voicemails += 1

    conn.commit()

    return {
        "status": "ok",
        "conversations_seen": conversations_seen,
        "calls_checked": calls_checked,
        "messages_saved": messages_saved,
        "summaries_saved": summaries_saved,
        "voicemails_saved": voicemails_saved,
        "skipped_existing_messages": skipped_existing_messages,
        "skipped_existing_summaries": skipped_existing_summaries,
        "skipped_existing_voicemails": skipped_existing_voicemails,
    }


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/quo/schaumburg/sync-activity")
def sync_activity(
        request: Request,
        x_wrapper_secret: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_api_access(request, x_wrapper_secret)

    conn = request.app.state.db
    result = sync_latest_activity(conn)

    return result


@app.get("/api/quo/schaumburg/last-10-calls")
def last_10_calls(
        request: Request,
        x_wrapper_secret: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_api_access(request, x_wrapper_secret)

    conn = request.app.state.db

    rows = conn.execute(
        """
        SELECT *
        FROM summaries
        ORDER BY last_activity_at DESC
        LIMIT 10
        """
    ).fetchall()

    return {
        "calls": [
            {
                "name": "Unknown",
                "phone_number": row["participant_number"] or "Unknown",
                "call_details": row["summary"],
                "next_steps": row["next_steps"],
                "call_id": row["call_id"],
                "summary_status": row["status"],
            }
            for row in rows
        ]
    }


@app.get("/api/quo/schaumburg/simple-calls")
def simple_calls(
        request: Request,
        x_wrapper_secret: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_api_access(request, x_wrapper_secret)

    conn = request.app.state.db

    rows = conn.execute(
        """
        SELECT participant_number, summary, next_steps, last_activity_at
        FROM summaries
        ORDER BY last_activity_at DESC
        LIMIT 10
        """
    ).fetchall()

    return {
        "calls": [
            {
                "phone_number": row["participant_number"] or "Unknown",
                "call_details": row["summary"],
                "next_steps": row["next_steps"],
                "last_activity_at": row["last_activity_at"],
            }
            for row in rows
        ]
    }


@app.get("/api/quo/debug/conversations")
def debug_conversations(request: Request) -> Dict[str, Any]:
    conn = request.app.state.db

    rows = conn.execute(
        """
        SELECT last_activity_id, last_activity_at
        FROM conversations
        ORDER BY last_activity_at DESC
        LIMIT 50
        """
    ).fetchall()

    return {
        "conversations": [
            {
                "last_activity_id": row["last_activity_id"],
                "last_activity_at": row["last_activity_at"],
            }
            for row in rows
        ]
    }


@app.get("/api/quo/debug/summaries")
def debug_summaries(request: Request) -> Dict[str, Any]:
    conn = request.app.state.db

    rows = conn.execute(
        """
        SELECT call_id, last_activity_id, status, summary, next_steps, last_activity_at
        FROM summaries
        ORDER BY last_activity_at DESC
        LIMIT 50
        """
    ).fetchall()

    return {
        "summaries": [
            {
                "call_id": row["call_id"],
                "last_activity_id": row["last_activity_id"],
                "status": row["status"],
                "summary": row["summary"],
                "next_steps": row["next_steps"],
                "last_activity_at": row["last_activity_at"],
            }
            for row in rows
        ]
    }


@app.get("/api/quo/debug/messages/{participant_number}")
def debug_messages(participant_number: str):
    try:
        messages = fetch_messages_for_phone(participant_number, max_results=10)

        return {
            "status": "ok",
            "participant_number": participant_number,
            "count": len(messages),
            "messages": messages,
        }

    except HTTPException as e:
        return {
            "status": "error",
            "participant_number": participant_number,
            "error": e.detail,
        }


@app.get("/api/quo/debug/stored-messages/{participant_number}")
def debug_stored_messages(participant_number: str, request: Request):
    conn = request.app.state.db

    rows = conn.execute(
        """
        SELECT message_id, participant_number, direction, text, created_at
        FROM messages
        WHERE participant_number = ?
        ORDER BY created_at DESC
        """,
        (participant_number,),
    ).fetchall()

    return {
        "participant_number": participant_number,
        "count": len(rows),
        "messages": [
            {
                "message_id": row["message_id"],
                "direction": row["direction"],
                "text": row["text"],
                "created_at": row["created_at"],
            }
            for row in rows
        ],
    }


@app.get("/api/quo/debug/live-conversations")
def debug_live_conversations() -> Dict[str, Any]:
    data = fetch_conversations()
    conversations = data.get("data", [])

    return {
        "count": len(conversations),
        "sample": conversations[:3],
    }


@app.get("/api/quo/schaumburg/activity")
def activity(
        request: Request,
        x_wrapper_secret: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_api_access(request, x_wrapper_secret)

    conn = request.app.state.db

    rows = conn.execute("""
        SELECT
            c.participant_number,
            c.last_activity_id,
            c.last_activity_at,
            s.summary,
            s.next_steps,
            s.status
        FROM conversations c
        LEFT JOIN summaries s
            ON s.last_activity_id = c.last_activity_id
        ORDER BY c.last_activity_at DESC
        LIMIT 10
    """).fetchall()

    participant_numbers = []
    for row in rows:
        participant_number = row["participant_number"]
        if participant_number and participant_number not in participant_numbers:
            participant_numbers.append(participant_number)

    messages_by_participant = fetch_recent_messages_by_participant(
        conn,
        participant_numbers,
    )
    voicemails_by_participant = fetch_recent_voicemails_by_participant(
        conn,
        participant_numbers,
    )

    activities = []

    for row in rows:
        participant_number = row["participant_number"]
        message_rows = messages_by_participant.get(participant_number, [])
        voicemail_rows = voicemails_by_participant.get(participant_number, [])

        activities.append({
            "phone_number": participant_number,
            "last_activity_at": row["last_activity_at"],
            "messages": [
                {
                    "direction": msg["direction"] or "unknown",
                    "text": msg["text"] or "",
                    "created_at": msg["created_at"],
                }
                for msg in message_rows
                if msg["text"]
            ],
            "call_summary": {
                "status": row["status"] or "None found",
                "summary": row["summary"] or "None found",
                "next_steps": row["next_steps"] or "None found",
            },
            "voicemails": [
                {
                    "call_id": vm["call_id"],
                    "phone_number_id": vm["phone_number_id"],
                    "participant_phone_number": vm["participant_phone_number"],
                    "participant_name": vm["participant_name"],
                    "transcript": vm["transcript"],
                    "recording_url": vm["recording_url"],
                    "created_at": vm["created_at"],
                }
                for vm in voicemail_rows
            ],
        })

    return {"activities": activities}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
