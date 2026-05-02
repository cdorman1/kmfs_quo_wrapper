# KMFS QUO Wrapper

Lightweight FastAPI service that integrates with the OpenPhone (QUO) API to aggregate conversations, messages, call summaries, and voicemails into a single structured endpoint.

Designed to power internal tooling and GPT-based workflows for Krav Maga Force Schaumburg.

---

## Features

- Pulls latest conversations from OpenPhone
- Syncs:
  - Messages
  - Call summaries
  - Voicemails (transcript + recording URL)
- Stores data locally (SQLite) or in Postgres
- Minimizes API usage by only fetching latest 10 active conversations
- Provides a unified `/activity` endpoint for downstream consumption

---

## API Endpoints

### Sync Latest Activity

POST /api/quo/schaumburg/sync-summaries

Fetches latest conversations and updates:
- messages
- call summaries
- voicemails

---

### Get Activity Feed

GET /api/quo/schaumburg/activity

Returns:

{
  "activities": [
    {
      "phone_number": "+1234567890",
      "last_activity_at": "...",
      "messages": [...],
      "call_summary": {...},
      "voicemails": [...]
    }
  ]
}

---

### Debug Endpoints

GET /api/quo/debug/messages/{phone}  
GET /api/quo/debug/stored-messages/{phone}  
GET /api/quo/debug/summaries  
GET /api/quo/debug/voicemails  

---

## Tech Stack

- FastAPI
- SQLite (default) / Postgres (recommended for production)
- OpenPhone (QUO) API
- Python 3.10+

---

## Setup

### 1. Clone repo

git clone https://github.com/cdorman1/kmfs_quo_wrapper.git  
cd kmfs_quo_wrapper

---

### 2. Create virtual environment

python -m venv .venv  
source .venv/bin/activate  

---

### 3. Install dependencies

pip install -r requirements.txt  

---

### 4. Create `.env`

QUO_API_KEY=your_api_key  
PHONE_NUMBER_ID=your_phone_number_id  
GPT_SHARED_SECRET=your_secret  
MAX_CONVERSATIONS=10  

---

### 5. Run server

uvicorn app:app --reload  

Server runs at:

http://127.0.0.1:8000

---

## Deployment (Recommended)

### Render + Supabase

- Deploy FastAPI as a Render Web Service
- Use Supabase (free tier) for Postgres
- Add environment variables in Render dashboard
- Add a Render Cron Job:

*/10 7-19 * * *

Calls:

POST /api/quo/schaumburg/sync-summaries

---

## Design Philosophy

- Keep API calls minimal
- Always maintain latest 10 active conversations
- Avoid re-fetching existing summaries/voicemails
- Store everything locally for fast retrieval

---

## Security

- API key stored via environment variables
- Optional shared secret header:
  - x-wrapper-secret
- .env is gitignored

---

## Future Improvements

- Full Postgres migration
- Pagination support
- Webhook support (instead of polling)
- Frontend dashboard
- Analytics layer (lead tracking, conversion)

---

## Author

Chris Dorman  
Krav Maga Force Schaumburg
