import sqlite3
from typing import Any, Dict

from fastapi import HTTPException

from db import (
    existing_ids,
    get_last_sync,
    save_conversation,
    save_message,
    save_summary,
    save_voicemail,
    set_last_sync,
    should_fetch_messages,
    utc_now,
)
from quo_client import (
    fetch_call_summary,
    fetch_call_voicemail,
    fetch_calls_for_participant,
    fetch_latest_conversations,
    fetch_messages_for_phone,
    fetch_recent_calls,
)
from quo_utils import extract_participant_number


def fetch_and_store_voicemails(conn: sqlite3.Connection) -> Dict[str, Any]:
    calls = fetch_recent_calls(max_results=50, created_after=get_last_sync(conn))

    saved = 0
    checked = 0
    skipped_no_voicemail = 0
    errors = []

    for call in calls:
        call_id = call.get("id")
        if not call_id:
            continue

        checked += 1

        try:
            voicemail = fetch_call_voicemail(call_id)
        except HTTPException as exc:
            error_text = str(exc.detail).lower()

            if "not found" in error_text or "404" in error_text:
                skipped_no_voicemail += 1
                continue

            errors.append({
                "call_id": call_id,
                "error": exc.detail,
            })
            continue

        if not voicemail:
            skipped_no_voicemail += 1
            continue

        if save_voicemail(conn, call, voicemail):
            saved += 1

    set_last_sync(conn, utc_now())
    conn.commit()

    return {
        "voicemails_checked_from_calls_endpoint": checked,
        "voicemails_saved": saved,
        "skipped_no_voicemail": skipped_no_voicemail,
        "voicemail_errors": errors,
    }


def sync_latest_activity(conn: sqlite3.Connection) -> Dict[str, Any]:
    conversations = fetch_latest_conversations(max_results=10)

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

        calls = fetch_calls_for_participant(participant_number, max_results=10)
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
                    voicemail = fetch_call_voicemail(call_id)
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
