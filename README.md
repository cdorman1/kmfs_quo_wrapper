# KMF Schaumburg Quo/OpenPhone Wrapper

A tiny Python FastAPI wrapper that lets a Custom GPT fetch the latest 10 stored calls for the Krav Maga Force - Schaumburg inbox and return:

- name
- phone_number
- call_details

## Why this wrapper uses a webhook

The OpenPhone/Quo API spec you provided has endpoints for:

- `GET /v1/calls/{callId}`
- `GET /v1/call-transcripts/{id}`
- `GET /v1/call-summaries/{callId}`

But `GET /v1/calls` requires a `participants` parameter, so it is not a clean global “last 10 calls for this inbox” endpoint. This wrapper keeps a small SQLite list of calls received by webhook, then uses the transcript/summary endpoints when your GPT asks for the latest 10 calls.

## Environment variables

Set these in Render/Railway/Vercel/etc.

```bash
OPENPHONE_API_KEY=Get Key from QUO
PHONE_NUMBER_ID=PNS7mc27hm
BUSINESS_PHONE_NUMBER=+12245760059
GPT_SHARED_SECRET=make-up-a-long-random-secret
DATABASE_PATH=calls.db
```

## Run locally

```bash
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Test:

```bash
curl http://localhost:8000/health
```

## Webhook URL

After deployment, add this URL in Quo/OpenPhone webhooks for call events such as `call.completed`, `call.transcript.completed`, and `call.summary.completed`:

```text
https://YOUR-DOMAIN.com/webhooks/openphone
```

## GPT wrapper URL

Your Custom GPT action should call:

```text
GET https://YOUR-DOMAIN.com/api/quo/schaumburg/last-10-calls
```

Header:

```text
X-Wrapper-Secret: your GPT_SHARED_SECRET
```

## Optional manual seed endpoint

If you already know a call ID and want to test before webhooks are active:

```bash
curl -X POST \
  -H "X-Wrapper-Secret: your GPT_SHARED_SECRET" \
  https://YOUR-DOMAIN.com/api/quo/schaumburg/seed-call/ACCNe265680744a541c99388a4d3a7542223
```

Then call:

```bash
curl -H "X-Wrapper-Secret: your GPT_SHARED_SECRET" \
  https://YOUR-DOMAIN.com/api/quo/schaumburg/last-10-calls
```
