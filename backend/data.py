"""In-memory mock data for the clinic: doctors, slots and appointments.

Everything lives in module-level dicts/lists, so the voice tools (clinic_tools.py)
and the dashboard's REST endpoints (Stage 4) share the same state. Restarting the
server resets it to the seed data below.

Slot format everywhere: "YYYY-MM-DD HH:MM" (24-hour), e.g. "2026-11-17 14:00".
"""

from datetime import date, datetime, timedelta

DOCTORS = [
    {"id": "d1", "name": "Dr. Anjali Rao", "speciality": "Cardiology"},
    {"id": "d2", "name": "Dr. Vikram Mehta", "speciality": "Cardiology"},
    {"id": "d3", "name": "Dr. Priya Nair", "speciality": "Dermatology"},
    {"id": "d4", "name": "Dr. Arjun Reddy", "speciality": "Dermatology"},
    {"id": "d5", "name": "Dr. Sana Khan", "speciality": "General Physician"},
    {"id": "d6", "name": "Dr. Rahul Sharma", "speciality": "General Physician"},
]
SLOT_TIMES = ["10:00", "11:00", "14:00", "15:30"]
DAYS_AHEAD = 4
SLOT_FORMAT = "%Y-%m-%d %H:%M"
_slots = {}
_appointments = {}


def reset_data(today=None):
    """Rebuild slots and seed one existing appointment per doctor; tests can pass today."""
    today = today or date.today()
    _slots.clear()
    _appointments.clear()
    for doctor in DOCTORS:
        _slots[doctor["id"]] = [
            f"{(today + timedelta(days=offset)).isoformat()} {time}"
            for offset in range(1, DAYS_AHEAD + 1)
            for time in SLOT_TIMES
        ]
    for i, doctor in enumerate(DOCTORS):
        slot = _slots[doctor["id"]][(i * 3 + 1) % len(_slots[doctor["id"]])]
        add_appointment(f"900000000{i}", doctor["id"], slot)


def list_doctors():
    return [dict(doctor) for doctor in DOCTORS]


def get_doctor(doctor_id):
    return next((dict(d) for d in DOCTORS if d["id"] == doctor_id), None)


def is_slot_booked(doctor_id, slot):
    return any(a["doctor_id"] == doctor_id and a["slot"] == slot for a in _appointments.values())


def slot_exists(doctor_id, slot):
    return slot in _slots.get(doctor_id, [])


def available_slots(doctor_id, date_str=None):
    """Return free slot strings for a doctor, optionally limited to YYYY-MM-DD."""
    return [s for s in _slots.get(doctor_id, [])
            if (date_str is None or s.startswith(date_str + " "))
            and not is_slot_booked(doctor_id, s)]


def list_slots(doctor_id=None, date_str=None, available_only=False):
    """Dashboard-friendly slot records including availability state."""
    return [
        {"doctor_id": did, "slot": slot, "available": not is_slot_booked(did, slot)}
        for did, slots in _slots.items() if doctor_id is None or did == doctor_id
        for slot in slots if date_str is None or slot.startswith(date_str + " ")
        if not available_only or not is_slot_booked(did, slot)
    ]


def list_doctors_with_slots():
    return [{**doctor, "slots": list_slots(doctor["id"])} for doctor in DOCTORS]


def list_appointments():
    return [dict(a) for a in _appointments.values()]


def get_appointment(phone):
    appointment = _appointments.get(phone)
    return dict(appointment) if appointment else None


def add_appointment(phone, doctor_id, slot):
    doctor = get_doctor(doctor_id)
    appointment = {
        "phone": phone, "doctor_id": doctor_id, "doctor_name": doctor["name"],
        "speciality": doctor["speciality"], "slot": slot,
        "booked_at": datetime.now().isoformat(timespec="seconds"),
    }
    _appointments[phone] = appointment
    return dict(appointment)


def remove_appointment(phone):
    appointment = _appointments.pop(phone, None)
    return dict(appointment) if appointment else None


reset_data()
