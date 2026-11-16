import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

from backend import data
from backend.clinic_tools import (
    book_appointment,
    cancel_appointment,
    check_doctor_availability,
    normalize_phone,
)
from backend.tool_handlers import ConfirmationState, create_clinic_tool_schemas


def setup_function():
    data.reset_data(today=date.today())


def test_availability_filters_by_doctor_speciality_and_date():
    date_one = (date.today() + timedelta(days=1)).isoformat()
    by_doctor = check_doctor_availability(doctor_name="anjali")
    assert by_doctor["success"]
    assert by_doctor["data"]["slots"]
    assert all(item["doctor_id"] == "d1" for item in by_doctor["data"]["slots"])

    by_speciality = check_doctor_availability(speciality="derm")
    assert by_speciality["data"]["slots"]
    assert all(item["speciality"] == "Dermatology" for item in by_speciality["data"]["slots"])

    by_date = check_doctor_availability(doctor_name="Anjali", date=date_one)
    assert by_date["data"]["slots"]
    assert all(item["slot"].startswith(date_one + " ") for item in by_date["data"]["slots"])


def test_successful_booking_removes_slot_from_availability():
    slot = data.available_slots("d1")[0]
    result = book_appointment("98765-43210", "d1", slot)
    assert result["success"]
    assert slot not in data.available_slots("d1")
    assert " at " in result["message"]
    assert slot not in result["message"]


def test_double_booking_same_slot_fails():
    slot = data.available_slots("d1")[0]
    assert book_appointment("9876543211", "d1", slot)["success"]
    result = book_appointment("9876543212", "d1", slot)
    assert not result["success"]
    assert "already been booked" in result["message"]


def test_cancel_frees_slot_and_slot_can_be_booked_again():
    slot = data.available_slots("d1")[0]
    assert book_appointment("9876543211", "d1", slot)["success"]
    assert cancel_appointment("9876543211")["success"]
    assert slot in data.available_slots("d1")
    assert book_appointment("9876543212", "d1", slot)["success"]


def test_cancel_unknown_phone_fails_cleanly():
    result = cancel_appointment("9876543212")
    assert not result["success"]
    assert result["data"]["appointment"] is None


def test_phone_normalization():
    assert normalize_phone("nine eight seven six five four three two one zero") == "9876543210"
    assert normalize_phone("98765-43210") == "9876543210"
    assert normalize_phone("+91 98765 43210") == "9876543210"
    assert normalize_phone("12345") is None


def test_invalid_date_and_unknown_doctor_are_reported():
    assert not check_doctor_availability(date="not-a-date")["success"]
    assert not book_appointment("9876543211", "unknown", "2026-11-17 14:00")["success"]


def test_booking_twice_for_same_phone_fails():
    first, second = data.available_slots("d1")[:2]
    assert book_appointment("9876543211", "d1", first)["success"]
    assert not book_appointment("9876543211", "d1", second)["success"]


def _handler(name, state):
    return next(s.handler for s in create_clinic_tool_schemas(state) if s.name == name)


def _params(arguments, messages, results, name):
    async def result_callback(result):
        results.append(result)

    return SimpleNamespace(
        function_name=name,
        arguments=arguments,
        context=SimpleNamespace(messages=messages),
        result_callback=result_callback,
    )


def test_booking_completes_with_one_combined_confirmation():
    state = ConfirmationState()
    handler = _handler("book_appointment", state)
    phone = "9876543211"
    slot = data.available_slots("d1")[0]
    messages = [{"role": "user", "content": "Book this doctor at this time"}]
    results = []
    params = _params(
        {"phone_number": phone, "doctor_id": "d1", "slot": slot},
        messages, results, "book_appointment",
    )

    async def flow():
        await handler(params)
        assert results[-1]["data"]["step"] == "confirm_phone_and_booking"
        assert "9 8 7 6 5 4 3 2 1 1" in results[-1]["message"]
        assert data.get_appointment(phone) is None

        # An immediate repeated tool call cannot act without a new user turn.
        await handler(params)
        assert not results[-1]["success"]
        assert data.get_appointment(phone) is None

        messages.extend([
            {"role": "assistant", "content": results[-1]["message"]},
            {"role": "user", "content": "yes"},
        ])
        await handler(params)
        assert results[-1]["success"]
        assert data.get_appointment(phone)["slot"] == slot

    asyncio.run(flow())


def test_cancel_completes_with_one_combined_confirmation():
    state = ConfirmationState()
    handler = _handler("cancel_appointment", state)
    phone = "9000000000"
    old_appointment = data.get_appointment(phone)
    messages = [{"role": "user", "content": "Cancel my appointment"}]
    results = []
    params = _params({"phone_number": phone}, messages, results, "cancel_appointment")

    async def flow():
        await handler(params)
        assert results[-1]["data"]["step"] == "confirm_phone_and_cancellation"
        assert "9 0 0 0 0 0 0 0 0 0" in results[-1]["message"]
        assert data.get_appointment(phone) == old_appointment
        messages.extend([
            {"role": "assistant", "content": results[-1]["message"]},
            {"role": "user", "content": "yes"},
        ])
        await handler(params)
        assert results[-1]["success"]
        assert data.get_appointment(phone) is None
        assert results[-1]["data"]["appointment"]["slot"] == old_appointment["slot"]

    asyncio.run(flow())


def test_no_or_unclear_confirmation_does_not_book():
    state = ConfirmationState()
    handler = _handler("book_appointment", state)
    phone = "9876543211"
    slot = data.available_slots("d1")[0]
    messages = [{"role": "user", "content": "Book this slot"}]
    results = []
    params = _params(
        {"phone_number": phone, "doctor_id": "d1", "slot": slot},
        messages, results, "book_appointment",
    )

    async def flow():
        await handler(params)
        messages.extend([
            {"role": "assistant", "content": results[-1]["message"]},
            {"role": "user", "content": "maybe"},
        ])
        await handler(params)
        assert not results[-1]["success"]
        assert data.get_appointment(phone) is None

    asyncio.run(flow())


def test_prior_no_invalidates_later_yes():
    state = ConfirmationState()
    handler = _handler("book_appointment", state)
    phone = "9876543211"
    slot = data.available_slots("d1")[0]
    messages = [{"role": "user", "content": "Book this slot"}]
    results = []
    params = _params(
        {"phone_number": phone, "doctor_id": "d1", "slot": slot},
        messages, results, "book_appointment",
    )

    async def flow():
        await handler(params)
        messages.extend([
            {"role": "assistant", "content": results[-1]["message"]},
            {"role": "user", "content": "no"},
            {"role": "user", "content": "yes"},
        ])
        await handler(params)
        assert not results[-1]["success"]
        assert data.get_appointment(phone) is None

    asyncio.run(flow())


def test_new_phone_number_invalidates_the_previous_pending_confirmation():
    state = ConfirmationState()
    handler = _handler("book_appointment", state)
    slot = data.available_slots("d1")[0]
    messages = [{"role": "user", "content": "Book a slot"}]
    results = []
    params = _params(
        {"phone_number": "9876543211", "doctor_id": "d1", "slot": slot},
        messages, results, "book_appointment",
    )

    async def flow():
        await handler(params)
        previous_prompt = results[-1]["message"]
        messages.extend([
            {"role": "assistant", "content": previous_prompt},
            {"role": "user", "content": "yes"},
        ])
        params.arguments = {
            "phone_number": "9876543212", "doctor_id": "d1", "slot": slot
        }
        await handler(params)
        assert "9 8 7 6 5 4 3 2 1 2" in results[-1]["message"]
        assert data.get_appointment("9876543211") is None
        assert data.get_appointment("9876543212") is None

    asyncio.run(flow())


def test_tool_schemas_describe_exact_doctor_and_slot_arguments():
    schemas = {schema.name: schema for schema in create_clinic_tool_schemas(ConfirmationState())}
    assert set(schemas) == {
        "check_doctor_availability", "book_appointment", "cancel_appointment"
    }
    assert "d1" in schemas["book_appointment"].properties["doctor_id"]["description"]
    assert "YYYY-MM-DD HH:MM" in schemas["book_appointment"].properties["slot"]["description"]
