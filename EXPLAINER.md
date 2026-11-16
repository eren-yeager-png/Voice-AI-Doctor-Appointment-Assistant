# Project walkthrough

## Main files

- **`backend/bot.py`** loads the root `.env`, configures ElevenLabs Realtime STT, Google Gemini, ElevenLabs TTS, Silero VAD, and the Pipecat pipeline. It creates the LLM context with the three clinic tools and handles browser connect/disconnect events. It also imports the dashboard API before Pipecat's runner starts, so REST and WebRTC use the runner's one FastAPI app.
- **`backend/tool_handlers.py`** defines the Pipecat 1.16 function schemas and asynchronous handlers. It keeps pending confirmation state local to one voice session, reads the latest caller utterance, and only calls a mutating business function after a clear, new “yes” for the exact change. It also formats clear next-speech results and logs tool name, masked arguments, and success.
- **`backend/clinic_tools.py`** holds the plain Python business operations: phone normalization, loose availability search, booking, cancellation, and speech-friendly appointment time formatting. It returns structured dictionaries and does not call an LLM or external API.
- **`backend/data.py`** is the shared in-memory source of truth. It defines doctors, generated slots, seed bookings, and helper functions for listing, adding, and removing appointments. Despite the `clinic_data.py` name sometimes used in the assignment, this repository's module is `backend/data.py`.
- **`backend/dashboard_api.py`** adds `GET /api/doctors`, `GET /api/appointments`, and `GET /api/health` to Pipecat's FastAPI app. It imports the same `backend.data` module as the tools, masks appointment phone numbers, and configures CORS for the Vite origins.
- **`frontend/src/App.jsx`** is the dashboard screen. It creates the Pipecat JavaScript client on Start call, connects through Small WebRTC, renders transcript events and remote audio, and polls the REST routes. It groups available slots, shows appointment rows, and briefly highlights schedule changes.
- **`frontend/src/main.jsx`** mounts the React application. **`frontend/src/styles.css`** contains its layout, colors, responsive rules, and change animations. **`frontend/package.json`** pins the client, transport, React, and Vite packages and defines the development/build scripts.
- **`tests/test_clinic_tools.py`** checks business behavior and confirmation safeguards. **`tests/test_dashboard_api.py`** checks the shared REST view of doctors and appointments, phone masking, ordering, health, and CORS.

## One booking from speech to dashboard

1. The caller opens the dashboard and starts a call. The Small WebRTC client creates a browser WebRTC offer and posts the SDP offer to the Pipecat runner's `/api/offer` route. The runner starts a bot session and returns its SDP answer; the transport also handles ICE candidate updates.
2. The browser streams microphone audio to the Pipecat pipeline. Silero VAD detects speech boundaries, ElevenLabs Realtime STT produces the transcript, and the transcript is added to the conversation context. Gemini receives the caller's request and can call `check_doctor_availability`.
3. The availability handler delegates to `clinic_tools.py`, which searches `backend/data.py` and returns matching free slots. The receptionist offers a few options, the caller chooses one, and then says a phone number.
4. Gemini calls `book_appointment`. The handler normalizes the phone number, verifies the doctor and exact slot are still available, then reads the number, doctor, and human-readable appointment time back together. It stores the pending action in this session's confirmation state; nothing is booked yet.
5. Only after the caller says a clear “yes” on a later user turn does the handler call the business function. `clinic_tools.py` validates again and writes the appointment into the shared in-memory `data` store.
6. The API route reads the same store on the next dashboard poll. The appointment appears newest first with its phone masked, while the corresponding doctor slot changes from available to booked. TTS speaks the booking result and WebRTC carries the audio back to the browser.

Cancellation follows the same guard: the caller's number identifies the appointment, the handler reads back the number and appointment details, and the appointment is removed only after a clear yes. Separate callers get separate confirmation state, although all sessions share the demo clinic's in-memory schedule.

## What to emphasize in an interview

The architecture keeps concerns separate: Pipecat and provider setup is in `bot.py`, voice confirmation and schemas are in `tool_handlers.py`, appointment rules are in `clinic_tools.py`, and the shared data lives in `data.py`. The dashboard is a second view of that same state rather than a second database. The confirmation guard is enforced in Python instead of trusting the model's prompt. The main tradeoff is that the in-memory mock is simple for a demo but does not persist across restarts or coordinate state between separate backend processes.
