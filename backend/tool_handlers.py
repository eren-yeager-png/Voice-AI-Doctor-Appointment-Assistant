"""Pipecat schemas and guarded handlers for the clinic tools.

The handler reads back the caller's number together with the exact appointment
change and asks one combined yes/no question. It saves that pending action in
this voice session only. A fresh, clear yes is required before changing data;
no, unclear speech, a new number, or a different action invalidates the pending
confirmation. This keeps the safeguard in Python instead of trusting the model.
"""

import json
from dataclasses import dataclass
from typing import Any

from loguru import logger
from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams

try:  # Support package and direct-script launch styles.
    from . import clinic_tools, data
except ImportError:  # pragma: no cover - exercised by direct script execution
    import clinic_tools
    import data


@dataclass
class ConfirmationState:
    """Pending confirmation for one live voice session."""

    verified_phone: str | None = None
    pending_action: dict[str, Any] | None = None
    prompt_message_count: int = 0
    pending_speech: str | None = None


_YES = {
    "yes", "yes please", "yeah", "yep", "correct", "that's correct",
    "that is correct", "right", "confirm", "i confirm", "yes i confirm",
    "yes book it", "yes cancel it", "go ahead",
}
_NO = {"no", "nope", "incorrect", "that's incorrect", "that is incorrect", "cancel"}


def _context_messages(context) -> list:
    messages = getattr(context, "messages", None)
    if messages is None and hasattr(context, "get_messages"):
        messages = context.get_messages()
    return messages if isinstance(messages, list) else []


def _user_messages(context) -> list[tuple[str, int]]:
    found = []
    for index, message in enumerate(_context_messages(context)):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    part.get("text", "") for part in content if isinstance(part, dict)
                )
            found.append((str(content).strip(), index))
    return found


def _decision(context, after_message_count: int) -> str:
    """Require one clear user utterance after the pending confirmation prompt."""
    turns = [
        " ".join(text.casefold().strip().rstrip(".!?").split())
        for text, index in _user_messages(context)
        if index >= after_message_count
    ]
    if not turns:
        return "waiting"
    if any(text in _NO or text.startswith("no ") for text in turns):
        return "no"
    if len(turns) == 1 and turns[0] in _YES:
        return "yes"
    return "unclear"


def _read_digits(phone: str) -> str:
    return " ".join(phone)


def _next_speech(message: str, **data_fields) -> dict:
    return {
        "success": False,
        "message": message,
        "data": {"next_speech": message, **data_fields},
    }


def _log_arguments(arguments) -> str:
    # Keep the phone argument recognizable without putting caller PII in logs.
    safe_args = dict(arguments)
    if "phone_number" in safe_args:
        normalized = clinic_tools.normalize_phone(safe_args["phone_number"])
        safe_args["phone_number"] = (
            f"******{normalized[-4:]}" if normalized else "[invalid]"
        )
    return json.dumps(safe_args, sort_keys=True, ensure_ascii=True, default=str)


async def _send(params: FunctionCallParams, result: dict) -> None:
    logger.info(
        "clinic_tool name={} arguments={} success={}",
        params.function_name,
        _log_arguments(params.arguments),
        bool(result.get("success")),
    )
    await params.result_callback(result)


def create_clinic_tool_schemas(state: ConfirmationState) -> list[FunctionSchema]:
    """Build schemas and handlers bound to a single voice session's state."""

    async def availability_handler(params: FunctionCallParams) -> None:
        args = params.arguments
        result = clinic_tools.check_doctor_availability(
            doctor_name=args.get("doctor_name"),
            speciality=args.get("speciality"),
            date=args.get("date"),
        )
        if result["success"] and result["data"]["slots"]:
            result["data"]["next_speech"] = (
                "Offer only two or three choices using doctor_name and spoken_slot, "
                "then ask which the caller prefers. Never say doctor_id or raw slot."
            )
        await _send(params, result)

    async def book_handler(params: FunctionCallParams) -> None:
        args = params.arguments
        phone = clinic_tools.normalize_phone(args.get("phone_number"))
        doctor_id = args.get("doctor_id")
        slot = args.get("slot")
        if not phone:
            state.verified_phone = None
            state.pending_action = None
            await _send(params, _next_speech(
                "That phone number is invalid. Please say a valid 10-digit number."
            ))
            return

        doctor = data.get_doctor(doctor_id)
        if not doctor:
            state.pending_action = None
            await _send(params, _next_speech(
                "I couldn't find that doctor. Please choose one from the available options."
            ))
            return

        slot_parts = str(slot).split(" ", 1)
        if len(slot_parts) != 2:
            state.pending_action = None
            await _send(params, _next_speech(
                "That appointment date or time is invalid. Please choose an offered time."
            ))
            return
        availability = clinic_tools.check_doctor_availability(
            doctor_name=doctor["name"], date=slot_parts[0]
        )
        offered = availability.get("data", {}).get("slots", [])
        if not availability.get("success") or not any(
            item["doctor_id"] == doctor_id and item["slot"] == slot
            for item in offered
        ):
            state.pending_action = None
            await _send(params, _next_speech(
                "That appointment time is no longer available. Please choose another offered time."
            ))
            return

        action = {"type": "book", "phone": phone, "doctor_id": doctor_id, "slot": slot}
        if state.pending_action != action:
            if state.verified_phone != phone:
                state.verified_phone = None
            state.pending_action = action
            state.prompt_message_count = len(_context_messages(params.context))
            message = (
                f"I heard your phone number as {_read_digits(phone)}. "
                f"You chose {doctor['name']} on "
                f"{clinic_tools.spoken_slot(slot)}. Is that correct, and shall I book it? "
                "Please say yes or no."
            )
            state.pending_speech = message
            await _send(params, _next_speech(
                message,
                step="confirm_phone_and_booking",
                doctor_name=doctor["name"],
                spoken_slot=clinic_tools.spoken_slot(slot),
            ))
            return

        decision = _decision(params.context, state.prompt_message_count)
        if decision != "yes":
            if decision != "waiting":
                state.pending_action = None
                state.verified_phone = None
            if decision == "waiting":
                message = state.pending_speech or "Please say yes or no to confirm the booking."
            else:
                state.pending_speech = None
                message = "Okay, I won't book that appointment. Nothing was changed."
            await _send(params, _next_speech(message, step="confirm_phone_and_booking"))
            return

        state.verified_phone = phone
        state.pending_action = None
        state.pending_speech = None
        result = clinic_tools.book_appointment(phone, doctor_id, slot)
        result["data"]["next_speech"] = (
            result["message"] + " Ask whether the caller needs anything else."
            if result["success"] else result["message"]
        )
        await _send(params, result)

    async def cancel_handler(params: FunctionCallParams) -> None:
        phone = clinic_tools.normalize_phone(params.arguments.get("phone_number"))
        if not phone:
            state.verified_phone = None
            state.pending_action = None
            await _send(params, _next_speech(
                "That phone number is invalid. Please say a valid 10-digit number."
            ))
            return

        appointment = data.get_appointment(phone)
        if not appointment:
            state.pending_action = None
            state.verified_phone = phone
            await _send(params, {
                "success": False,
                "message": "I couldn't find an active appointment for that phone number.",
                "data": {
                    "appointment": None,
                    "next_speech": "Tell the caller no active appointment was found and offer to check availability.",
                },
            })
            return

        action = {"type": "cancel", "phone": phone, "appointment": appointment}
        if state.pending_action != action:
            if state.verified_phone != phone:
                state.verified_phone = None
            state.pending_action = action
            state.prompt_message_count = len(_context_messages(params.context))
            message = (
                f"I heard your phone number as {_read_digits(phone)}. "
                f"I found an appointment with {appointment['doctor_name']} on "
                f"{clinic_tools.spoken_slot(appointment['slot'])}. "
                "Is that correct, and shall I cancel it? Please say yes or no."
            )
            state.pending_speech = message
            await _send(params, _next_speech(
                message,
                step="confirm_phone_and_cancellation",
                doctor_name=appointment["doctor_name"],
                spoken_slot=clinic_tools.spoken_slot(appointment["slot"]),
            ))
            return

        decision = _decision(params.context, state.prompt_message_count)
        if decision != "yes":
            if decision != "waiting":
                state.pending_action = None
                state.verified_phone = None
            if decision == "waiting":
                message = state.pending_speech or "Please say yes or no to confirm the cancellation."
            else:
                state.pending_speech = None
                message = "Okay, I won't cancel the appointment. It is unchanged."
            await _send(params, _next_speech(message, step="confirm_phone_and_cancellation"))
            return

        state.verified_phone = phone
        state.pending_action = None
        state.pending_speech = None
        result = clinic_tools.cancel_appointment(phone)
        result["data"]["next_speech"] = (
            result["message"] + " Ask whether the caller needs anything else."
            if result["success"] else result["message"]
        )
        await _send(params, result)

    return [
        FunctionSchema(
            name="check_doctor_availability",
            description="Find open appointment slots. This tool does not book or change anything.",
            properties={
                "doctor_name": {"type": "string", "description": "Optional partial doctor name."},
                "speciality": {"type": "string", "description": "Optional speciality, such as cardiology."},
                "date": {"type": "string", "description": "Optional date in YYYY-MM-DD format."},
            },
            required=[],
            handler=availability_handler,
        ),
        FunctionSchema(
            name="book_appointment",
            description=(
                "Begin or confirm a booking. doctor_id must be an ID like d1 from the "
                "availability result. slot must be the exact YYYY-MM-DD HH:MM string "
                "from that result. The server requires a clear yes to its combined "
                "phone-number and appointment confirmation before booking."
            ),
            properties={
                "phone_number": {"type": "string", "description": "Caller phone number, spoken or formatted."},
                "doctor_id": {"type": "string", "description": "Doctor ID from availability, for example d1."},
                "slot": {"type": "string", "description": "Exact YYYY-MM-DD HH:MM slot string from availability results."},
            },
            required=["phone_number", "doctor_id", "slot"],
            handler=book_handler,
        ),
        FunctionSchema(
            name="cancel_appointment",
            description=(
                "Begin or confirm cancellation. The server reads back the caller's "
                "number and found appointment, then requires a clear yes before cancelling."
            ),
            properties={
                "phone_number": {"type": "string", "description": "Caller phone number, spoken or formatted."},
            },
            required=["phone_number"],
            handler=cancel_handler,
        ),
    ]
