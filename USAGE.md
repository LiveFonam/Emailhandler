# inbox-zero-agent

Personal Gmail AI assistant + cold outreach tool.

Triages your inbox, drafts replies, runs multi-variant cold outreach, scrapes leads — all from a Streamlit dashboard.

---

## How to use it right now

The project lives at `C:\Users\lucas\Desktop\inbox-zero-agent\`. To run it:

### 1. Configure secrets

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

Edit `.env` with your real values:

- **`ANTHROPIC_API_KEY`** — your Anthropic API key. This is the LLM.
- **`CLAUDE_BUDGET_USD`** — cap on Claude spend per session. Default 5.00. After this is hit, the router falls through to Groq, then Ollama.
- **OAuth client** — see step 3.
- **`GOOGLE_CSE_KEY`** + **`GOOGLE_CSE_ID`** — for lead scraping via Google Custom Search (free, 100/day).
- **`GOOGLE_MAPS_API_KEY`** — for Google Maps Places lead scraping (free $200/mo credit).

Optional fallbacks: `GROQ_API_KEY`, `GEMINI_API_KEY`.

### 2. Configure sender profile

Edit `config.yaml`. The `sender_profile` section:

```yaml
sender_profile:
  name: "Lucas"
  email: "you@gmail.com"
  physical_address: "123 Your Street, City, State ZIP, Country"   # REQUIRED for cold outreach
  reply_to: "you@gmail.com"
```

The `physical_address` is non-negotiable — CAN-SPAM fines are $53,088 per non-compliant email. The Send Now button is disabled until this is filled in.

### 3. OAuth for Gmail

Create a Google Cloud project at <https://console.cloud.google.com/>:
1. Enable the **Gmail API**
2. Create an **OAuth 2.0 Client ID** of type **Desktop app**
3. Download the JSON and save it as `data/credentials.json` (the path is `data/credentials.json` relative to project root)

Then run the consent flow:

```bash
python -m tools.oauth_init
```

A browser window opens, you grant `gmail.readonly` + `gmail.compose` + `gmail.send`, and `data/token.json` is written. (For multiple accounts: `python -m tools.oauth_init --account your.other@gmail.com` and add to settings.)

### 4. Start the dashboard

```bash
.\launch.ps1
```

This launches:
- The APScheduler in a hidden PowerShell window (background, runs 24/7)
- Streamlit on port 8502

Open <http://localhost:8502> in your browser.

### 5. Triage your inherited inbox

In the **Inbox** page, click "Triage all" — OR run the CLI for the initial 342-email backfill:

```bash
python -m tools.backfill_inbox --max 342
```

This will classify every unread thread into one of {action-required, fyi, newsletter, promotion, cold-reply} using Claude Haiku, then apply Gmail labels so you can see them in your normal Gmail UI.

### 6. Use the dashboard

The sidebar has 8 pages:

| Page | What it does |
|---|---|
| **Home** | Quick stats + LLM router health + compliance status |
| **Inbox** | See triaged threads. Pick a tone (warm/concise/formal/playful), click "Draft reply" |
| **Drafts** | Review AI-drafted replies. Edit, "Save to Gmail" (overwrites the Gmail draft), "Send now" (compliance-checked + Gmail API send), or "Discard" |
| **Leads** | Scrape new leads from Google CSE or Google Maps. CSV import tab. Add to campaigns. Suppression list |
| **Campaigns** | Create a campaign, pick frameworks (question_hook, recent_news, mutual_connection, value_prop, soft_compliment), click "Generate variants" (M3 writes a unique email per framework per lead), then "Materialize send jobs" to schedule them |
| **Warmup Status** | Live per-mailbox daily cap, lifetime sent, last 30 days chart. Auto-refreshes every 5s |
| **Compliance** | Suppression list, audit history, "Run audit now" button, required CAN-SPAM headers list |
| **Settings** | Sender profile editor (with physical-address validation), OAuth re-consent button |
| **Logs** | sent_log, scheduler stdout, failed send jobs |

### 7. Cold outreach flow

1. **Scrape leads**: Leads page → "Scrape new" tab → pick Google CSE or Google Maps → query → "Run scrape" → review preview → "Save to database"
2. **Create campaign**: Campaigns page → "+ New campaign" → name, pick frameworks, save
3. **Add leads to campaign**: Leads page → "Existing leads" tab → select rows → pick the campaign → "Add to campaign"
4. **Generate variants**: Campaigns page → click "Generate variants" on the campaign. The M3 writes 1 unique subject + body per (framework × lead) combination. For 50 leads × 3 frameworks, that's 150 personalized emails.
5. **Materialize send jobs**: Campaigns page → "Materialize send jobs". This respects warmup caps, suppression, recipient-timezone business hours, and 60-90s jitter.
6. **Watch them go out**: Warmup Status page shows the per-mailbox cap fill in real time.

The scheduler's `outreach_dispatch` job runs every 60s, claims a job atomically (no double-sends), runs the CAN-SPAM compliance gate, sends via Gmail, persists the unsubscribe token, and updates sent_log.

### 8. Test it works (no live creds needed)

```bash
python -m pytest tests/ -v
```

23/23 should pass. Includes tests for CAN-SPAM compliance, atomic send claims, busy_timeout PRAGMAs, multi-variant prompts, and lead dedupe.

```bash
python -m tests.smoke_e2e
```

Validates the full module graph, all 12 tables, all 8 Streamlit pages parse, and all CLIs work.

---

## What's where

```
inbox-zero-agent/
├── app/                  # Streamlit UI
│   ├── Home.py           # Entry point
│   ├── pages/0-7         # Sidebar pages
│   ├── scheduler.py      # APScheduler (runs in separate process)
│   └── paths.py          # Adds Evil's src/ to sys.path
├── src/                  # Core library
│   ├── config.py         # Typed Settings (loads config.yaml + .env)
│   ├── db.py             # SQLite WAL, 13 tables
│   ├── llm_compat.py     # Bridge to Evil's llm.py
│   ├── schemas.py        # Pydantic v2 contracts
│   ├── gmail/            # OAuth, fetch, labels, drafts, send
│   ├── triage/           # Classify + summarize + draft_reply
│   ├── outreach/         # Compliance, throttler, warmup, variants, sender
│   ├── leads/            # Sources (CSE, Maps), dedupe, enrich, store
│   └── analytics/        # Warmup metrics, reply rate, audit
├── tools/                # CLIs
│   ├── oauth_init.py
│   ├── backfill_inbox.py
│   └── scrape.py
├── tests/                # 23 tests, all passing
├── data/                 # DB, run.log, sent_mime/ (gitignored)
├── config.yaml           # Sender profile, warmup schedule, caps
├── .env.example          # Copy to .env, fill in
├── launch.ps1            # Starts scheduler + streamlit
└── requirements.txt
```

---

## Important rules

- **DO NOT** send cold outreach from the inherited friend's Gmail account. Use your own established accounts.
- **DO NOT** disable the warmup ramp. The cap starts at ~10/day per mailbox and grows 50% per week.
- **DO NOT** skip the `physical_address` in `config.yaml`. The send gate refuses without it.
- **DO NOT** add `instantly.ai` to the send path. It's deliberately not in the codebase.
- **APScheduler MUST run in a separate process** (`launch.ps1` does this). Streamlit's script-rerun would kill any in-script scheduler.

---

## Production verification (after configuring creds)

1. Run `python -m tools.oauth_init` → consent screen
2. Run `python -m tools.backfill_inbox --max 10` (small batch first) → see AI labels in Gmail
3. Inbox page → click "Draft reply" with tone=warm on one thread → confirm in Gmail Drafts
4. Settings → confirm physical address is saved
5. Campaigns → create a 5-lead test campaign → generate variants → materialize → watch Warmup Status
6. Run `python -m pytest tests/ -v` to confirm 23/23 still pass
