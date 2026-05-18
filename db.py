import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import DATABASE_PATH
from quo_utils import extract_participant_number


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(database_path: str = DATABASE_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path, check_same_thread=False)
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
    return conn


def get_last_sync(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute(
        "SELECT value FROM sync_state WHERE key='last_call_sync'",
    ).fetchone()
    return row["value"] if row else None


def set_last_sync(conn: sqlite3.Connection, timestamp: str) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO sync_state (key, value)
        VALUES ('last_call_sync', ?)
        """,
        (timestamp,),
    )


def save_conversation(
    conn: sqlite3.Connection,
    last_activity_id: str,
    last_activity_at: str,
    conversation: Dict[str, Any],
) -> str:
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
            utc_now(),
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

    conn.execute(
        """
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
        """,
        (
            call_id,
            call.get("phoneNumberId"),
            participant_number,
            None,
            voicemail.get("transcript"),
            voicemail.get("recordingUrl"),
            call.get("createdAt") or call.get("startedAt") or call.get("completedAt"),
            utc_now(),
            json.dumps({
                "call": call,
                "voicemail": voicemail,
            }),
        ),
    )

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

    grouped = {participant_number: [] for participant_number in participant_numbers}
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

    grouped = {participant_number: [] for participant_number in participant_numbers}
    for row in rows:
        grouped[row["participant_phone_number"]].append(row)
    return grouped
