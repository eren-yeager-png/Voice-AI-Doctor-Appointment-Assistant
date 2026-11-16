from datetime import date

from fastapi.testclient import TestClient

from backend import data
from backend.clinic_tools import book_appointment, cancel_appointment
from backend.dashboard_api import get_app


client = TestClient(get_app())


def setup_function():
    data.reset_data(today=date.today())


def test_doctors_endpoint_returns_doctors_with_slots():
    response = client.get("/api/doctors")

    assert response.status_code == 200
    doctors = response.json()
    assert doctors
    assert doctors[0]["slots"]
    assert {"slot", "available"} <= doctors[0]["slots"][0].keys()


def test_booking_appears_masked_in_appointments_endpoint():
    phone = "9876543211"
    slot = data.available_slots("d1")[0]
    assert book_appointment(phone, "d1", slot)["success"]

    response = client.get("/api/appointments")

    assert response.status_code == 200
    appointment = next(item for item in response.json() if item["phone"] == "******3211")
    assert appointment["doctor_name"] == "Dr. Anjali Rao"
    assert appointment["speciality"] == "Cardiology"
    assert appointment["slot"] == slot
    assert phone not in response.text


def test_cancel_removes_appointment_from_endpoint():
    phone = "9876543211"
    slot = data.available_slots("d1")[0]
    assert book_appointment(phone, "d1", slot)["success"]
    assert any(item["phone"] == "******3211" for item in client.get("/api/appointments").json())

    assert cancel_appointment(phone)["success"]

    assert all(item["phone"] != "******3211" for item in client.get("/api/appointments").json())


def test_health_endpoint():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_both_vite_origins():
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        response = client.options(
            "/api/doctors",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


def test_appointments_are_newest_first():
    first_slot = data.available_slots("d1")[0]
    second_slot = data.available_slots("d2")[0]
    book_appointment("9876543211", "d1", first_slot)
    book_appointment("9876543212", "d2", second_slot)

    response = client.get("/api/appointments")

    dates = [item["booked_at"] for item in response.json()]
    assert dates == sorted(dates, reverse=True)
