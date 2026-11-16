"""Dashboard REST endpoints attached to Pipecat's in-process FastAPI app."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pipecat.runner.run import app

from . import data


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/doctors")
async def get_doctors():
    """Return doctors with every slot and its current availability."""
    return data.list_doctors_with_slots()


@app.get("/api/appointments")
async def get_appointments():
    """Return newest appointments first, masking each caller's phone number."""
    appointments = sorted(
        data.list_appointments(),
        key=lambda appointment: appointment.get("booked_at", ""),
        reverse=True,
    )
    return [
        {
            "doctor_name": appointment["doctor_name"],
            "speciality": appointment["speciality"],
            "slot": appointment["slot"],
            "booked_at": appointment.get("booked_at"),
            "phone": "*" * max(0, len(appointment["phone"]) - 4)
            + appointment["phone"][-4:],
        }
        for appointment in appointments
    ]


@app.get("/api/health")
async def get_health():
    return {"status": "ok"}


def get_app() -> FastAPI:
    """Expose Pipecat's app for TestClient without creating another server."""
    return app
