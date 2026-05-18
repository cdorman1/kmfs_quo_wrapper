from typing import Any, Dict, Optional

import requests
from fastapi import HTTPException

from config import (
    HTTP_TIMEOUT_SECONDS,
    MAX_CONVERSATIONS,
    PHONE_NUMBER_ID,
    QUO_API_KEY,
    QUO_BASE_URL,
)


HTTP_SESSION = requests.Session()


def quo_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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


def fetch_latest_conversations(max_results: int = 10) -> list[Dict[str, Any]]:
    return quo_get(
        "/v1/conversations",
        params={
            "phoneNumberId": PHONE_NUMBER_ID,
            "maxResults": max_results,
        },
    ).get("data", [])


def fetch_calls_for_participant(
    participant_number: str,
    max_results: int = 10,
) -> list[Dict[str, Any]]:
    return quo_get(
        "/v1/calls",
        params={
            "phoneNumberId": PHONE_NUMBER_ID,
            "participants": participant_number,
            "maxResults": max_results,
        },
    ).get("data", [])


def fetch_recent_calls(
    max_results: int = 50,
    created_after: Optional[str] = None,
) -> list[Dict[str, Any]]:
    params = {
        "phoneNumberId": PHONE_NUMBER_ID,
        "maxResults": max_results,
    }

    if created_after:
        params["createdAfter"] = created_after

    return quo_get("/v1/calls", params=params).get("data", [])


def fetch_call_summary(activity_id: str) -> Optional[Dict[str, Any]]:
    try:
        return quo_get(f"/v1/call-summaries/{activity_id}").get("data", {})
    except HTTPException as exc:
        error_text = str(exc.detail)
        if "0500404" in error_text or "not found" in error_text.lower():
            return None
        print(f"SUMMARY ERROR for {activity_id}: {exc.detail}")
        return None


def fetch_call_voicemail(call_id: str) -> Optional[Dict[str, Any]]:
    return quo_get(f"/v1/call-voicemails/{call_id}").get("data")


def fetch_messages_for_phone(
    participant_number: str,
    max_results: int = 25,
) -> list[Dict[str, Any]]:
    return quo_get(
        "/v1/messages",
        params={
            "phoneNumberId": PHONE_NUMBER_ID,
            "participants": participant_number,
            "maxResults": max_results,
        },
    ).get("data", [])
