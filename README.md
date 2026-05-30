# KMFS QUO Wrapper

Status: public source repository for a private/internal FastAPI integration. Do not
commit live API keys, shared secrets, auth files, database files, logs, or exported
customer/conversation data.

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

Copy the example file and replace placeholder values with deployment-local
secrets:

```bash
cp deploy/quo-wrapper.env.example .env
```

Required values:

```dotenv
QUO_API_KEY=replace-me
PHONE_NUMBER_ID=replace-me
GPT_SHARED_SECRET=replace-me
MAX_CONVERSATIONS=10
```

Keep `.env`, basic-auth files, SQLite databases, logs, and runtime exports out of
git. Use `deploy/quo-wrapper.env.example` only for placeholders.

---

### 5. Run server

uvicorn app:app --reload  

Server runs at:

http://127.0.0.1:8000

---

## Deployment (Recommended)

### Sentinel Forge / Hostinger Domain

This app can run on the same server as the existing Sentinel Forge dashboards and be exposed through Hostinger-managed DNS at:

    https://sentinelforge.tech/quo-wrapper/

The included deployment files are:

    deploy/quo-wrapper.service
    deploy/quo-wrapper.env.example
    deploy/traefik-quo-wrapper.yml

Production setup:

    sudo mkdir -p /opt/quo-wrapper /var/lib/quo-wrapper
    sudo rsync -a --delete ./ /opt/quo-wrapper/
    cd /opt/quo-wrapper
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    sudo cp deploy/quo-wrapper.env.example /etc/quo-wrapper.env
    sudo nano /etc/quo-wrapper.env
    sudo cp deploy/quo-wrapper.service /etc/systemd/system/quo-wrapper.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now quo-wrapper

Traefik setup:

    sudo cp deploy/traefik-quo-wrapper.yml /docker/traefik/dynamic/quo-wrapper.yml

The service listens only on localhost port 8788. Traefik strips the /quo-wrapper prefix and forwards traffic to FastAPI.

Browser access uses HTTP Basic Auth. By default it reuses:

    /root/.openclaw/workspace/dashboards/.dashboard-auth.json

The existing x-wrapper-secret header still works for API callers when GPT_SHARED_SECRET is set.

Optional cron sync:

    */10 7-19 * * * curl -fsS -X POST -H "x-wrapper-secret: $GPT_SHARED_SECRET" https://sentinelforge.tech/quo-wrapper/api/quo/schaumburg/sync-activity >/dev/null

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
- Runtime auth files such as `.dashboard-auth.json` must stay outside this
  public repository.
- Run a secret scan before opening PRs that touch deployment, auth, or config
  files.

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
