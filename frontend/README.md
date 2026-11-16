# Voice AI Doctor Appointment Dashboard

Copy `.env.example` to `.env` if the backend runs somewhere other than
`http://localhost:7860`. The app connects to Pipecat's Small WebRTC
`/api/offer` endpoint and reads dashboard data from the backend's `/api`
routes.

From this directory:

```sh
npm install
npm run dev
```

Vite serves the dashboard at `http://localhost:5173`.
