from typing import Any, Dict

from config import BUSINESS_PHONE_NUMBER


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
