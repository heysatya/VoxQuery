# VoxQuery — Voice-Driven Data Analyst

VoxQuery is an AI-powered voice assistant for data analysis. It enables non-technical team leaders and executives to talk directly to their database (such as Snowflake) using plain speech or text, receiving instant charts, spoken summaries, and daily business insights.

---

## Key Features

- 🎙️ **Voice & Text Queries**: Ask questions naturally using speech or text to get instant charts and audio answers.
- 📊 **Interactive Chart Drill-Down**: Click on any chart data point to automatically explore underlying details.
- 🚨 **Automatic Anomaly Alerts**: Detects sudden data spikes or drops and explains them in plain English.
- 🌅 **Daily Morning Briefings**: Delivers automatic daily business metric summaries and audio briefings.
- 🧠 **Saved History & Memory Map**: Saves conversation history, visual memory graphs, and past findings across sessions.
- 🔗 **One-Click Safe Sharing**: Share view-only permalinks for charts and findings with team members.
- 📄 **PDF Workspace Exports**: Export active charts, data tables, and narrative summaries as clean PDF reports.
- 🔐 **Enterprise Security & Multi-Tenancy**: Built with secure user logins (Clerk), multi-tenant data isolation, and admin controls.

---

## Quick Start

### 1. Start the Backend
```powershell
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --ws-ping-interval 30 --ws-ping-timeout 120
```

### 2. Start the Frontend
```powershell
cd frontend
npm run dev
```

### 3. Open in Browser
- **Main App**: [http://localhost:3000/app](http://localhost:3000/app)
- **Landing Page**: [http://localhost:3000](http://localhost:3000)
- **Admin Control Panel**: [http://localhost:3000/admin](http://localhost:3000/admin)

---

## Environment Setup

Create `.env` files in your backend and frontend directories before running:

**Backend (`backend/.env`):**
```env
APP_ENV=development
AUTH_MODE=clerk
SESSION_STORE=redis
STT_PROVIDER=deepgram
TTS_PROVIDER=deepgram
LLM_PROVIDER=claude
RAG_PROVIDER=pgvector
WAREHOUSE_PROVIDER=snowflake

SUPABASE_DATABASE_URL=<supabase_database_url>
UPSTASH_REDIS_URL=<upstash_redis_url>
FERNET_KEY=<fernet_encryption_key>
CLERK_SECRET_KEY=<clerk_secret_key>
ANTHROPIC_API_KEY=<anthropic_api_key>
DEEPGRAM_API_KEY=<deepgram_api_key>
SNOWFLAKE_DSN=<snowflake_dsn>
```

**Frontend (`frontend/.env.local`):**
```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_AUTH_MODE=clerk
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=<clerk_publishable_key>
```

---

## Running Tests

Run the backend test suite:
```powershell
cd backend
uv run pytest
```

---

## Project Documentation

- [Features & Implementation Plan](./docs/wow-features/VoxQuery_WOW_Features_Implementation_Plan.md)
- [Product Requirements Document (PRD)](./docs/prd.md)
- [End-to-End Test Plan](./docs/test/VoxQuery_E2E_Test_Plan.md)
- [Admin Console Test Plan](./docs/test/Admin_UI_Test_Plan.md)
