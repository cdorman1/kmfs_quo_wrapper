from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from config import GPT_SHARED_SECRET
from db import (
    fetch_recent_messages_by_participant,
    fetch_recent_voicemails_by_participant,
)
from quo_client import fetch_conversations, fetch_messages_for_phone
from sync_activity import sync_latest_activity


router = APIRouter()


def require_gpt_secret(x_wrapper_secret: Optional[str]) -> None:
    if GPT_SHARED_SECRET and x_wrapper_secret != GPT_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Invalid wrapper secret")


@router.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@router.post("/api/quo/schaumburg/sync-activity")
def sync_activity(
    request: Request,
    x_wrapper_secret: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_gpt_secret(x_wrapper_secret)
    return sync_latest_activity(request.app.state.db)


@router.get("/api/quo/schaumburg/last-10-calls")
def last_10_calls(
    request: Request,
    x_wrapper_secret: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_gpt_secret(x_wrapper_secret)

    rows = request.app.state.db.execute(
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


@router.get("/api/quo/schaumburg/simple-calls")
def simple_calls(
    request: Request,
    x_wrapper_secret: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_gpt_secret(x_wrapper_secret)

    rows = request.app.state.db.execute(
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


@router.get("/api/quo/debug/conversations")
def debug_conversations(request: Request) -> Dict[str, Any]:
    rows = request.app.state.db.execute(
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


@router.get("/api/quo/debug/summaries")
def debug_summaries(request: Request) -> Dict[str, Any]:
    rows = request.app.state.db.execute(
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


@router.get("/api/quo/debug/messages/{participant_number}")
def debug_messages(participant_number: str) -> Dict[str, Any]:
    try:
        messages = fetch_messages_for_phone(participant_number, max_results=10)

        return {
            "status": "ok",
            "participant_number": participant_number,
            "count": len(messages),
            "messages": messages,
        }

    except HTTPException as exc:
        return {
            "status": "error",
            "participant_number": participant_number,
            "error": exc.detail,
        }


@router.get("/api/quo/debug/stored-messages/{participant_number}")
def debug_stored_messages(participant_number: str, request: Request) -> Dict[str, Any]:
    rows = request.app.state.db.execute(
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


@router.get("/api/quo/debug/live-conversations")
def debug_live_conversations() -> Dict[str, Any]:
    conversations = fetch_conversations().get("data", [])

    return {
        "count": len(conversations),
        "sample": conversations[:3],
    }


@router.get("/api/quo/schaumburg/activity")
def activity(
    request: Request,
    x_wrapper_secret: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_gpt_secret(x_wrapper_secret)

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
