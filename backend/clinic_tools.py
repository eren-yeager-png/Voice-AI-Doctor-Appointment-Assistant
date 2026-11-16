"""Plain Python appointment tools. No network or model calls are made here."""

from datetime import date, datetime
import re

from . import data

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2",
    "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9",
}


def normalize_phone(value):
    """Normalize numeric or spoken digits to an Indian 10-digit phone number."""
    if value is None:
        return None
    parts = re.findall(r"[a-z]+|\d+", str(value).lower())
    digits = ""
    for part in parts:
        if part.isdigit():
            digits += part
        elif part in _DIGIT_WORDS:
            digits += _DIGIT_WORDS[part]
        else:
            return None
    # Accept common India country-code forms, but store the local number only.
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) != 10 or digits[0] == "0":
        return None
    return digits


def _result(success, message, **payload):
    return {"success": success, "message": message, "data": payload}


def spoken_slot(slot):
    """Format an internal slot for speech without reading an ISO timestamp."""
    try:
        parsed = datetime.strptime(slot, data.SLOT_FORMAT)
    except (TypeError, ValueError):
        return str(slot)
    return (
        f"{parsed.strftime('%A, %B')} {parsed.day} at "
        f"{parsed.strftime('%I:%M %p').lstrip('0')}"
    )


def _parse_date(value):
    if value is None or value == "":
        return None
    try:
        parsed = datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return False
    return parsed.isoformat()


def check_doctor_availability(doctor_name=None, speciality=None, date=None):
    """Find available slots using case-insensitive partial name/speciality matches."""
    parsed_date = _parse_date(date)
    if parsed_date is False:
        return _result(False, "That date is invalid. Please use YYYY-MM-DD.", slots=[])
    name_query = (doctor_name or "").strip().casefold()
    speciality_query = (speciality or "").strip().casefold()
    doctors = [d for d in data.list_doctors()
               if (not name_query or name_query in d["name"].casefold())
               and (not speciality_query or speciality_query in d["speciality"].casefold())]
    if (name_query or speciality_query) and not doctors:
        return _result(False, "I couldn't find a doctor matching that name or speciality.", slots=[])
    slots = [
        {"doctor_id": doctor["id"], "doctor_name": doctor["name"],
         "speciality": doctor["speciality"], "slot": slot,
         "spoken_slot": spoken_slot(slot)}
        for doctor in doctors
        for slot in data.available_slots(doctor["id"], parsed_date)
    ]
    message = (
        f"I found {len(slots)} available appointment(s). Offer only two or three "
        "choices using doctor_name and spoken_slot; never say doctor_id or slot."
        if slots else "There are no available appointments matching that request."
    )
    return _result(True, message, slots=slots)


def book_appointment(phone_number, doctor_id, slot):
    phone = normalize_phone(phone_number)
    if not phone:
        return _result(False, "That phone number is invalid. Please provide a 10-digit number.", appointment=None)
    doctor = data.get_doctor(doctor_id)
    if not doctor:
        return _result(False, "I couldn't find that doctor.", appointment=None)
    if data.get_appointment(phone):
        return _result(False, "This phone number already has an active appointment.", appointment=data.get_appointment(phone))
    try:
        datetime.strptime(str(slot), data.SLOT_FORMAT)
    except (TypeError, ValueError):
        return _result(False, "That appointment date or time is invalid.", appointment=None)
    if not data.slot_exists(doctor_id, slot):
        return _result(False, "That slot is not available for this doctor.", appointment=None)
    if data.is_slot_booked(doctor_id, slot):
        return _result(False, "That slot has already been booked. Please choose another time.", appointment=None)
    appointment = data.add_appointment(phone, doctor_id, slot)
    display_time = spoken_slot(slot)
    appointment["spoken_slot"] = display_time
    return _result(
        True,
        f"Your appointment with {doctor['name']} is booked for {display_time}.",
        appointment=appointment,
    )


def cancel_appointment(phone_number):
    phone = normalize_phone(phone_number)
    if not phone:
        return _result(False, "That phone number is invalid. Please provide a 10-digit number.", appointment=None)
    appointment = data.remove_appointment(phone)
    if not appointment:
        return _result(False, "I couldn't find an active appointment for that phone number.", appointment=None)
    appointment["spoken_slot"] = spoken_slot(appointment["slot"])
    return _result(
        True,
        f"Your appointment with {appointment['doctor_name']} for "
        f"{appointment['spoken_slot']} has been cancelled.",
        appointment=appointment,
    )
