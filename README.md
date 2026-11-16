# Voice AI Doctor Appointment Assistant

This project is a browser-based clinic receptionist that can check doctor availability, book appointments, and cancel them by voice.
It streams speech through a Pipecat voice pipeline and displays the conversation beside the clinic schedule.
The dashboard and voice tools use the same in-memory Python data, so confirmed changes appear on the page without a database.

## Technology

- **LLM:** Google Gemini, selected by `GEMINI_MODEL` (default: `gemini-3.5-flash`)
- **Speech to text:** ElevenLabs Realtime STT, `scribe_v2_realtime`
- **Text to speech:** ElevenLabs TTS, `eleven_flash_v2_5`
- **Voice pipeline:** Pipecat 1.16 with Silero VAD and Small WebRTC
- **Dashboard:** React and Vite with Pipecat's JavaScript client

## Architecture

```text
Caller microphone
      |
      v
Browser -- WebRTC --> Pipecat 1.16 pipeline
                       Silero VAD -> ElevenLabs STT
                       -> Gemini LLM + clinic tools
                       -> ElevenLabs TTS
      ^                           |
      +------ WebRTC audio --------+

Dashboard in browser -- polls GET /api/doctors and /api/appointments
                                  |
                                  v
                         Same FastAPI process
                                  |
                                  v
                     backend/data.py in-memory state
                     (also used by clinic tools)
```

The runner's Small WebRTC offer endpoint and the dashboard REST routes run on the same backend process and port.

## Prerequisites

- Windows, macOS, or Linux
- Python 3.11 (the project was built with Python 3.11.3)
- Node.js 22.12 or newer (the frontend was built with Node 24.19.0)
- API access and keys for Google Gemini and ElevenLabs

## Setup

Clone the repository and enter its directory:

```powershell
git clone <repository-url>
cd Voice-AI-Doctor-Appointment-Assistant
```

Create a Python environment, install the backend requirements, and create your local environment file:

```powershell
py -3.11 -m venv .venv
./.venv/Scripts/Activate.ps1
python -m pip install -r backend/requirements.txt
Copy-Item .env.example .env
```

Edit the project-root `.env` and set:

- `ELEVENLABS_API_KEY`: an API key from your ElevenLabs account with access to Realtime STT and TTS.
- `GOOGLE_API_KEY`: a Google AI Studio key enabled for Gemini API access.
- `ELEVENLABS_VOICE_ID`: the ID of a voice available to your ElevenLabs account. Open the voice in your ElevenLabs account and copy its Voice ID from that voice's details.

`GEMINI_MODEL` defaults to `gemini-3.5-flash`; the STT and TTS model defaults are `scribe_v2_realtime` and `eleven_flash_v2_5`. You can override them in `.env`.

## Run the app

Start the backend from the repository root in one PowerShell window:

```powershell
./.venv/Scripts/python.exe backend/bot.py --transport webrtc
```

In a second window, start the dashboard:

```powershell
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. The dashboard reads the schedule from the backend at `http://localhost:7860`. If the backend URL differs, copy `frontend/.env.example` to `frontend/.env` and set `VITE_API_URL`.

## Tests

From the repository root, run:

```powershell
./.venv/Scripts/python.exe -m pytest
cd frontend
npm run build
```

The backend tests cover the clinic tools, phone normalization, confirmation safeguards, and dashboard REST endpoints.

## Appointment tools and mock data

- `check_doctor_availability` finds open slots by a partial doctor name, speciality, and/or date.
- `book_appointment` validates the number, doctor, and exact slot before booking.
- `cancel_appointment` removes the active appointment associated with the caller's number.

For booking or cancellation, the caller says a 10-digit phone number. The server normalizes it, reads the digits back individually along with the specific appointment change, and requires a clear spoken “yes” before changing data. A “no”, unclear reply, invalid number, or different action cannot authorize the change.

The mock clinic has six doctors across cardiology, dermatology, and general medicine. Each doctor has four daily slot times over the next four days, with one seeded booking per doctor. There is at most one active appointment per phone number. All data is in memory and resets to the seed data when the backend restarts.

## Demo script

1. Start the backend and dashboard, open the dashboard, and click **Start call**.
2. Ask for a cardiologist on a preferred day and choose one of the returned appointment times.
3. Say your 10-digit phone number when asked.
4. Listen while the assistant reads back the number, doctor, and appointment time; say “yes” only if they are correct.
5. Confirm the spoken booking result and show the new masked appointment and newly booked slot on the dashboard.

## Known limitations

- Appointments are stored only in memory and reset when the backend restarts.
- The mock schedule has one active appointment per phone number and no persistence or user accounts.
- Gemini and ElevenLabs free-tier quotas and rate limits vary by account.
- This is a demo receptionist for availability and appointment changes, not a medical advice service.

## Troubleshooting

- **Gemini returns a 429 quota error:** wait for quota to recover or set `GEMINI_MODEL` in `.env` to a model that is available to your Google key and quota.
- **Voice ID not found:** copy the exact Voice ID for a voice that is available in your ElevenLabs account.
- **Key or permission errors:** check that `GOOGLE_API_KEY` has Gemini API access and `ELEVENLABS_API_KEY` has access to Realtime STT and TTS. Keep real keys in the ignored `.env`; do not put them in source files.
- **Dashboard says the backend is unavailable:** start the backend first and confirm `VITE_API_URL` points to the same host and port.
- **Microphone permission error:** allow microphone access for the Vite page in your browser, then try the call again.
