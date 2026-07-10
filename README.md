# Multi-Agent Scheduling Assistant

A robust, AI-powered calendar scheduling assistant built with **LangGraph**, **SQLite**, and **Streamlit**. 

This system uses a multi-agent architecture where two distinct LLM-powered agents coordinate to handle your scheduling requests seamlessly. The system includes built-in state persistence, cross-session memory, voice interactions, and a resilient local database.

## Architecture

The workflow routes incoming user messages through a directed graph:

```text
User Input
    │
    ▼
Triage Agent  (llama-4-scout, structured output)
    │
    ├── General Query → Replies directly → END
    │
    └── Booking Intent → Booking Specialist
                              │
                              ├── check_availability()
                              ├── reserve_slot()
                              ├── reschedule_slot()
                              ├── cancel_slot()
                              └── send_booking_notification()
                                          │
                                          ▼
                                         END
```

### Agents

**1. Triage Agent** (`triage.py`)  
Acts as the frontline router. It leverages Pydantic structured output via `.with_structured_output()` to return a strictly typed `TriageResult` object. By categorizing intents as either `booking` or `general`, it avoids fragile string matching and ensures efficient routing.

**2. Booking Specialist** (`booking.py`)  
Handles the complex business logic of scheduling. It runs a ReAct tool-calling loop where the LLM reasons about the user's request, calls necessary tools, and processes the results. It is explicitly instructed to never guess missing information (like exact times or emails) and will pause to ask the user. It also intelligently normalizes relative dates (e.g., "tomorrow", "next Friday") into exact `YYYY-MM-DD` formats before executing tools.

## Memory & State Management

The application features advanced state persistence, ensuring that conversations and user preferences survive across reboots and browser refreshes.

| Layer | Implementation | Scope |
|---|---|---|
| **Conversation History** | `SqliteSaver` → `checkpointer.db` | Per-thread |
| **User Preferences** | `SqliteStore` → `user_memory.db` | Cross-thread |
| **Business Logic** | Standard SQLite → `scheduler.db` | Global |

The cross-session store remembers a user's email and preferred meeting duration. On their next session, the booking specialist automatically retrieves this information and prefills it into the context prompt. 

Additionally, the SQLite connections are equipped with **auto-recovery mechanisms**. If the local database files are ever corrupted (e.g., due to unexpected shutdowns or git conflicts on cloud deployments), the application detects the schema mismatch, cleanly wipes the corrupted files, and rebuilds the tables automatically.

## Tool Arsenal (`tools.py`)

The Booking Specialist is equipped with a suite of strict Python tools to interact with the database safely:

*   `check_availability(date)` — Returns all occupied slots for a given date.
*   `reserve_slot(date, time, email, duration)` — Performs an overlap-safe write to reserve a slot.
*   `cancel_slot(date, time, email)` — Safely removes an existing booking.
*   `reschedule_slot(email, old_date, old_time, new_date, new_time)` — A transactional tool that cancels the old slot and reserves the new one, reverting automatically if the new slot is unavailable.
*   `send_booking_notification(email, details)` — POSTs a JSON payload to a configured webhook URL for external integrations.

## Tech Stack

*   **LangGraph**: Core state machine, conditional routing, and memory stores.
*   **Groq API**: Blazing fast LLM inference (powered by `llama-4-scout` and `whisper-large-v3-turbo`).
*   **Streamlit**: Reactive frontend UI featuring real-time token streaming and embedded voice input.
*   **SQLite**: Zero-dependency local persistence for both application data and agent memory.

## Setup Instructions

### 1. Install Dependencies

Ensure you have Python 3.10+ installed, then install the required packages:

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file in the root of the project and add your API keys and configuration:

```env
GROQ_API_KEY=your_groq_api_key_here
WEBHOOK_URL=https://httpbin.org/post // put your actual webhook url here instead of the placeholder
```

*You can obtain a free Groq API key from the [Groq Console](https://console.groq.com).*

### 3. Run the Application

Start the Streamlit server:

```bash
streamlit run main.py
```

The application will be available at `http://localhost:8501`.

## Key Features

*   **Sleek Organic UI**: Features a modern, human-centric design with dark mode styling, custom CSS components, and a side-by-side chat layout.
*   **Voice Input**: Speak directly to the assistant! Uses `streamlit-mic-recorder` and Groq's Whisper API for near-instant speech-to-text translation.
*   **Token Streaming**: Responses are streamed word-by-word natively using LangGraph's `graph.stream()`, providing a snappy user experience.
*   **Conflict Negotiation**: If a requested slot is occupied, the agent automatically checks for alternatives and proposes them instead of failing abruptly.
*   **iCal Export**: Confirmed bookings can be downloaded as `.ics` files directly from the UI, compatible with Google Calendar, Outlook, and Apple Calendar.
*   **Live Database Monitor**: A real-time dashboard in the side column displays busy slots and confirmed reservations without disrupting the active chat session.

## Testing Webhooks

If you'd like to inspect the JSON payloads dispatched by the agent upon booking:
1. Navigate to [webhook.site](https://webhook.site) and copy your unique URL.
2. Paste it into the **Webhook URL** field in the application's sidebar.
3. Successfully book an appointment through the chat interface.
4. Watch the JSON confirmation payload appear instantly on Webhook.site.
