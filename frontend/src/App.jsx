import { useCallback, useEffect, useRef, useState } from "react";
import { PipecatClient } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";

const API_BASE_URL = (import.meta.env.VITE_API_URL || "http://localhost:7860").replace(/\/$/, "");

function getErrorText(error) {
  const name = error?.name || "";
  const message = error?.message || error?.data?.error || "";
  if (/NotAllowed|PermissionDenied|SecurityError|permission.*denied|denied.*permission/i.test(name + " " + message)) {
    return "Microphone access was denied. Allow microphone access in your browser, then try again.";
  }
  if (/fetch|network|failed to connect|connection/i.test(name + " " + message)) {
    return "Could not reach the voice backend at " + API_BASE_URL + ". Check that it is running and try again.";
  }
  return message || "The call could not be started. Check the microphone and backend, then try again.";
}

function formatDay(isoDate) {
  return new Date(isoDate + "T00:00:00").toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function timeFromSlot(slot) {
  return slot?.slice(11) || slot;
}

function groupSlots(doctor) {
  return (doctor.slots || []).filter((slot) => slot.available).reduce((groups, item) => {
    const day = item.slot.slice(0, 10);
    (groups[day] ||= []).push(item);
    return groups;
  }, {});
}

function App() {
  const [status, setStatus] = useState("disconnected");
  const [callError, setCallError] = useState("");
  const [messages, setMessages] = useState([]);
  const [doctors, setDoctors] = useState([]);
  const [appointments, setAppointments] = useState([]);
  const [doctorLoading, setDoctorLoading] = useState(true);
  const [appointmentLoading, setAppointmentLoading] = useState(true);
  const [doctorError, setDoctorError] = useState("");
  const [appointmentError, setAppointmentError] = useState("");
  const [flashingSlots, setFlashingSlots] = useState(() => new Set());
  const [flashingAppointments, setFlashingAppointments] = useState(() => new Set());

  const clientRef = useRef(null);
  const audioRef = useRef(null);
  const transcriptRef = useRef(null);
  const previousSlotsRef = useRef(null);
  const previousAppointmentsRef = useRef(null);

  useEffect(() => {
    transcriptRef.current?.scrollTo({
      top: transcriptRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const addMessage = useCallback((role, text) => {
    const cleanText = String(text || "").trim();
    if (!cleanText) return;
    setMessages((current) => [
      ...current,
      { id: Date.now() + "-" + Math.random(), role, text: cleanText, time: new Date() },
    ]);
  }, []);

  const startCall = async () => {
    setCallError("");
    setMessages([]);
    setStatus("connecting");
    const client = new PipecatClient({
      transport: new SmallWebRTCTransport(),
      enableMic: true,
      enableCam: false,
      callbacks: {
        onConnected: () => setStatus("connected"),
        onDisconnected: () => {
          setStatus("disconnected");
          clientRef.current = null;
          if (audioRef.current) audioRef.current.srcObject = null;
        },
        onTransportStateChanged: (transportState) => {
          if (["initializing", "initialized", "connecting"].includes(transportState)) {
            setStatus("connecting");
          } else if (transportState === "error") {
            setStatus("disconnected");
          }
        },
        onUserTranscript: (transcript) => {
          if (transcript?.final) addMessage("caller", transcript.text);
        },
        onBotTranscript: (transcript) => addMessage("assistant", transcript?.text),
        onDeviceError: (error) => setCallError(getErrorText(error)),
        onError: (error) => setCallError(getErrorText(error)),
        onTrackStarted: (track, participant) => {
          if (track.kind !== "audio" || participant?.local || !audioRef.current) return;
          audioRef.current.srcObject = new MediaStream([track]);
          audioRef.current.play().catch(() => {
            setCallError("Browser blocked bot audio playback. Check the tab's audio permissions and try again.");
          });
        },
        onTrackStopped: (track, participant) => {
          if (track.kind === "audio" && !participant?.local && audioRef.current) {
            audioRef.current.srcObject = null;
          }
        },
      },
    });
    clientRef.current = client;
    try {
      await client.connect({
        // Runner route expects an SDP offer { sdp, type }; the transport creates it
        // and handles the answer and subsequent ICE-candidate PATCH requests.
        webrtcRequestParams: { endpoint: API_BASE_URL + "/api/offer" },
      });
    } catch (error) {
      setCallError(getErrorText(error));
      setStatus("disconnected");
      clientRef.current = null;
      try {
        await client.disconnect();
      } catch {
        // A failed connection may already have disposed the transport.
      }
    }
  };

  const endCall = async () => {
    const client = clientRef.current;
    clientRef.current = null;
    setCallError("");
    if (!client) {
      setStatus("disconnected");
      return;
    }
    try {
      await client.disconnect();
    } catch {
      // Ending a call should remain a clean UI action if the transport already failed.
    } finally {
      setStatus("disconnected");
      if (audioRef.current) audioRef.current.srcObject = null;
    }
  };

  const refreshData = useCallback(async (isActive) => {
    const loadDoctors = async () => {
      try {
        const response = await fetch(API_BASE_URL + "/api/doctors");
        if (!response.ok) throw new Error("Request failed (" + response.status + ")");
        const nextDoctors = await response.json();
        const nextSlotStates = {};
        nextDoctors.forEach((doctor) => {
          (doctor.slots || []).forEach((slot) => {
            nextSlotStates[doctor.id + "|" + slot.slot] = slot.available;
          });
        });
        const previous = previousSlotsRef.current;
        const changed = previous
          ? Object.keys(nextSlotStates).filter((key) => key in previous && previous[key] !== nextSlotStates[key])
          : [];
        previousSlotsRef.current = nextSlotStates;
        if (changed.length) {
          setFlashingSlots(new Set(changed));
          window.setTimeout(() => setFlashingSlots(new Set()), 1000);
        }
        if (isActive()) {
          setDoctors(nextDoctors);
          setDoctorError("");
        }
      } catch {
        if (isActive()) setDoctorError("Could not load doctors. Check the backend at " + API_BASE_URL + ".");
      } finally {
        if (isActive()) setDoctorLoading(false);
      }
    };

    const loadAppointments = async () => {
      try {
        const response = await fetch(API_BASE_URL + "/api/appointments");
        if (!response.ok) throw new Error("Request failed (" + response.status + ")");
        const nextAppointments = await response.json();
        const snapshot = Object.fromEntries(nextAppointments.map((item) => [
          item.phone + "|" + item.doctor_name + "|" + item.speciality,
          item.slot + "|" + item.booked_at,
        ]));
        const previous = previousAppointmentsRef.current;
        const changed = previous
          ? Object.keys(snapshot).filter((key) => !(key in previous) || previous[key] !== snapshot[key])
          : [];
        previousAppointmentsRef.current = snapshot;
        if (changed.length) {
          setFlashingAppointments(new Set(changed));
          window.setTimeout(() => setFlashingAppointments(new Set()), 1000);
        }
        if (isActive()) {
          setAppointments(nextAppointments);
          setAppointmentError("");
        }
      } catch {
        if (isActive()) setAppointmentError("Could not load appointments. Check the backend at " + API_BASE_URL + ".");
      } finally {
        if (isActive()) setAppointmentLoading(false);
      }
    };

    await Promise.all([loadDoctors(), loadAppointments()]);
  }, []);

  useEffect(() => {
    let active = true;
    const isActive = () => active;
    const interval = status === "connected" ? 1500 : 5000;
    void refreshData(isActive);
    const timer = window.setInterval(() => void refreshData(isActive), interval);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [refreshData, status]);

  const canStart = status === "disconnected";
  const canEnd = status !== "disconnected";

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">+</div>
          <div>
            <p className="eyebrow">CLINIC FRONT DESK</p>
            <h1>Voice AI Doctor Appointment Assistant</h1>
          </div>
        </div>
        <div className={"status-badge status-" + status} role="status">
          <span className="status-dot" />
          {status === "connected" ? "Connected" : status === "connecting" ? "Connecting" : "Disconnected"}
        </div>
      </header>

      <div className="dashboard-grid">
        <section className="left-column">
          <section className="panel call-panel">
            <div>
              <p className="eyebrow">VOICE SESSION</p>
              <h2>Talk to the receptionist</h2>
              <p className="muted">Allow microphone access when your browser asks.</p>
            </div>
            <div className="call-controls">
              <button className="button button-primary" onClick={startCall} disabled={!canStart}>
                <span aria-hidden="true">●</span> Start call
              </button>
              <button className="button button-secondary" onClick={endCall} disabled={!canEnd}>
                End call
              </button>
            </div>
            {callError && <p className="error-banner" role="alert">{callError}</p>}
            <audio ref={audioRef} autoPlay playsInline className="sr-only" />
          </section>

          <section className="panel transcript-panel">
            <div className="panel-heading">
              <div><p className="eyebrow">LIVE CONVERSATION</p><h2>Transcript</h2></div>
              <span className="live-indicator"><span /> Live</span>
            </div>
            <div className="transcript-list" ref={transcriptRef} aria-live="polite">
              {messages.length === 0 ? (
                <div className="empty-state transcript-empty">
                  <div className="empty-icon" aria-hidden="true">◖</div>
                  <strong>Your conversation will appear here</strong>
                  <span>Start a call to see the live transcript.</span>
                </div>
              ) : messages.map((message) => (
                <article className={"chat-row " + message.role} key={message.id}>
                  <span className="chat-avatar" aria-hidden="true">{message.role === "caller" ? "Y" : "AI"}</span>
                  <div className="chat-content">
                    <div className="chat-meta">
                      <strong>{message.role === "caller" ? "You" : "Receptionist"}</strong>
                      <time>{message.time.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</time>
                    </div>
                    <p>{message.text}</p>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </section>

        <section className="right-column">
          <section className="panel doctors-panel">
            <div className="panel-heading">
              <div><p className="eyebrow">CLINIC TEAM</p><h2>Doctors & availability</h2></div>
              <span className="refresh-note">Auto refresh</span>
            </div>
            {doctorLoading ? (
              <div className="panel-state">Loading doctors…</div>
            ) : doctorError ? (
              <div className="panel-state panel-error" role="alert">{doctorError}</div>
            ) : doctors.length === 0 ? (
              <div className="panel-state">No doctors available.</div>
            ) : (
              <div className="doctor-list">
                {doctors.map((doctor) => {
                  const groups = groupSlots(doctor);
                  const count = Object.values(groups).reduce((total, slots) => total + slots.length, 0);
                  return (
                    <article className="doctor-card" key={doctor.id}>
                      <div className="doctor-summary">
                        <div className="doctor-avatar" aria-hidden="true">
                          {doctor.name.replace(/^Dr\.\s*/, "").split(" ").map((part) => part[0]).slice(0, 2).join("")}
                        </div>
                        <div className="doctor-info"><h3>{doctor.name}</h3><span>{doctor.speciality}</span></div>
                        <div className="slot-count"><strong>{count}</strong><span>free</span></div>
                      </div>
                      <div className="slot-groups">
                        {Object.entries(groups).length === 0 ? (
                          <span className="no-slots">No open slots</span>
                        ) : Object.entries(groups).map(([day, slots]) => (
                          <div className="slot-day" key={day}>
                            <span className="slot-day-label">{formatDay(day)}</span>
                            <div className="slot-chips">
                              {slots.map((slot) => {
                                const key = doctor.id + "|" + slot.slot;
                                return <span className={"slot-chip " + (flashingSlots.has(key) ? "flash" : "")} key={slot.slot}>{timeFromSlot(slot.slot)}</span>;
                              })}
                            </div>
                          </div>
                        ))}
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          <section className="panel appointments-panel">
            <div className="panel-heading">
              <div><p className="eyebrow">SCHEDULE</p><h2>Appointments</h2></div>
              <span className="appointment-total">{appointments.length} total</span>
            </div>
            {appointmentLoading ? (
              <div className="panel-state">Loading appointments…</div>
            ) : appointmentError ? (
              <div className="panel-state panel-error" role="alert">{appointmentError}</div>
            ) : appointments.length === 0 ? (
              <div className="empty-state appointment-empty">
                <strong>No appointments yet</strong><span>New bookings will show up here.</span>
              </div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Patient</th><th>Doctor</th><th>Speciality</th><th>Date & time</th></tr></thead>
                  <tbody>
                    {appointments.map((appointment) => {
                      const key = appointment.phone + "|" + appointment.doctor_name + "|" + appointment.speciality;
                      return (
                        <tr className={flashingAppointments.has(key) ? "flash-row" : ""} key={key}>
                          <td className="patient-number">{appointment.phone}</td>
                          <td>{appointment.doctor_name}</td>
                          <td><span className="speciality-pill">{appointment.speciality}</span></td>
                          <td>
                            <span className="appointment-date">{formatDay(appointment.slot.slice(0, 10))}</span>
                            <span className="appointment-time">{timeFromSlot(appointment.slot)}</span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </section>
      </div>
      <footer className="page-footer">
        <span><span className="footer-dot" /> Dashboard connected to the clinic&apos;s live in-memory schedule</span>
        <span>Voice data stays in this demo session</span>
      </footer>
    </main>
  );
}

export default App;
