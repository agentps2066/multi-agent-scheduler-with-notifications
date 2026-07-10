# Multi-Agent Scheduling Assistant

A calendar scheduling assistant built with LangGraph, SQLite, and Streamlit. Two LLM-powered agents coordinate to handle scheduling requests: one classifies intent, the other manages the actual booking workflow through a tool-calling loop.

## Architecture

```
User Input
    │
    ▼
Triage Agent  (llama-4-scout, structured output)
    │
    ├── general query → reply directly → END
    │
    └── booking intent → Booking Specialist
                              │
                              ├── check_availability()
                              ├── reserve_slot()
                              └── send_booking_notification()
                                          │
                                          ▼
                                         END
```

### Agents

**Triage Agent** (`triage.py`)  
Uses Pydantic structured output via `.with_structured_output()` — the model returns a typed `TriageResult` object with `intent: Literal['booking', 'general']`. No fragile string matching.

**Booking Specialist** (`booking.py`)  
Runs a ReAct loop: the LLM reasons, calls tools, receives results, and continues until it produces a final text response. If date or time or email is missing, it asks the user before doing anything. Normalizes relative dates ("tomorrow", "next Friday") to `YYYY-MM-DD` before tool calls.

### Memory layers

| Layer | Implementation | Scope |
|---|---|---|
| Conversation history | `SqliteSaver` → `checkpointer.db` | Per thread |
| User preferences | `SqliteStore` → `user_memory.db` | Cross-thread |

The cross-session store remembers a user's email and preferred meeting duration. On their next session the booking specialist picks these up automatically and prefills them into the prompt.

### Tools (`tools.py`)

- `check_availability(date)` — returns all occupied slots for a given date from SQLite
- `reserve_slot(date, time, email, duration_minutes)` — overlap-safe write to SQLite
- `send_booking_notification(email, details)` — POSTs a JSON payload to the configured webhook URL

### Persistence

Two SQLite files are created automatically on first run:
- `scheduler.db` — busy slots and confirmed reservations
- `checkpointer.db` — LangGraph conversation state (per thread)
- `user_memory.db` — cross-session user preferences (email, duration)

## Stack

- **LangGraph** — state machine, conditional routing, memory stores
- **Groq** — inference (llama-4-scout, 131K context, 30K TPM free tier)
- **Streamlit** — UI with token streaming and voice input
- **SQLite** — all persistence, no external services

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

Create `.env` in the project root:

```env
GROQ_API_KEY=your_key_here
WEBHOOK_URL=https://httpbin.org/post
```

Get a free Groq API key at [console.groq.com](https://console.groq.com).

### 3. Run

```bash
streamlit run main.py
```

Open `http://localhost:8501`.

## Features

**Token streaming** — responses appear word-by-word using `graph.stream()` and `st.write_stream()` instead of waiting for the full reply.

**Voice input** — record audio directly in the browser using Streamlit's native `st.audio_input` widget. Transcriptions are powered by Groq's `whisper-large-v3-turbo` model for lightning-fast speech-to-text.
**iCal export** — confirmed bookings can be downloaded as a `.ics` file compatible with Google Calendar, Outlook, and Apple Calendar.

**Conflict negotiation** — if a requested slot is occupied, the agent checks for alternatives and proposes them rather than failing.

**Live database monitor** — busy slots and reservations update in the right column in real-time without disrupting the chat layout.

## Testing webhooks

To inspect notification payloads:
1. Open [webhook.site](https://webhook.site) and copy your unique URL.
2. Paste it into the **Webhook URL** field in the sidebar.
3. Book a slot — the JSON payload will appear on Webhook.site instantly.
