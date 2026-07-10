import os
import sqlite3
import io
from datetime import datetime, timedelta

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from groq import Groq

from graph import graph
from tools import DB_PATH

load_dotenv()

st.set_page_config(
    page_title="Scheduling Assistant",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

*, *::before, *::after {
    font-family: 'Inter', sans-serif;
    box-sizing: border-box;
}

.stApp {
    background-color: #0b0f17;
    color: #e5e7eb;
}

section[data-testid="stSidebar"] {
    background-color: #0f172a;
    border-right: 1px solid #1e293b;
}

.header-container {
    border-bottom: 1px solid #1e293b;
    padding-bottom: 1.25rem;
    margin-bottom: 1.75rem;
}

.header-title {
    font-size: 1.5rem;
    font-weight: 600;
    color: #f9fafb;
    margin: 0;
    letter-spacing: -0.02em;
}

.header-meta {
    color: #6b7280;
    font-size: 0.8125rem;
    margin: 0.25rem 0 0 0;
}

.section-label {
    font-size: 0.75rem;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin: 0 0 0.875rem 0;
}

.stat-card {
    background-color: #111827;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 1rem;
}

.stat-value {
    font-size: 1.75rem;
    font-weight: 700;
    color: #f9fafb;
    line-height: 1;
}

.stat-label {
    font-size: 0.75rem;
    color: #6b7280;
    margin-top: 0.35rem;
}

.status-card {
    background-color: #111827;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 1rem;
}

.status-row-label {
    font-size: 0.75rem;
    color: #6b7280;
}

.status-row-value {
    font-size: 0.875rem;
    color: #f9fafb;
    font-weight: 500;
    margin-top: 0.2rem;
}

/* Voice button */
.voice-btn-wrapper {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

/* Fix Streamlit button look */
.stButton > button {
    background-color: #1d4ed8 !important;
    color: #fff !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
    padding: 0.375rem 0.875rem !important;
    transition: background-color 0.15s !important;
}
.stButton > button:hover {
    background-color: #1e40af !important;
}

/* Streamlit expander cleanup */
details summary {
    font-size: 0.8rem !important;
    color: #6b7280 !important;
}

/* Chat input */
.stChatInput textarea {
    background-color: #111827 !important;
    border-color: #1e293b !important;
    color: #e5e7eb !important;
    font-size: 0.9rem !important;
}
</style>
""", unsafe_allow_html=True)

THREAD_ID = "scheduler_main_thread_v1"
CONFIG = {"configurable": {"thread_id": THREAD_ID}}


def fetch_busy_slots():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT participant, start_time, end_time FROM busy_slots ORDER BY start_time"
    ).fetchall()
    conn.close()
    return rows


def fetch_reservations():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT date, time, email, details FROM reservations ORDER BY date, time"
    ).fetchall()
    conn.close()
    return rows


def clear_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM busy_slots")
    conn.execute("DELETE FROM reservations")
    conn.commit()
    conn.close()

    cp_path = os.path.join(os.path.dirname(__file__), "checkpointer.db")
    if os.path.exists(cp_path):
        c = sqlite3.connect(cp_path)
        try:
            c.execute("DELETE FROM checkpoints")
            c.execute("DELETE FROM writes")
            c.commit()
        except Exception:
            pass
        c.close()

    mem_path = os.path.join(os.path.dirname(__file__), "user_memory.db")
    if os.path.exists(mem_path):
        m = sqlite3.connect(mem_path)
        try:
            m.execute("DELETE FROM store")
            m.commit()
        except Exception:
            pass
        m.close()


def add_mock_busy(participant, start_iso, end_iso):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO busy_slots (participant, start_time, end_time) VALUES (?, ?, ?)",
        (participant, start_iso, end_iso)
    )
    conn.commit()
    conn.close()


def load_history():
    try:
        snap = graph.get_state(CONFIG)
        if snap and snap.values:
            return snap.values.get("messages", [])
    except Exception:
        pass
    return []


def make_ical(reservations):
    """Generate a minimal .ics file string from the reservations list."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Scheduling Assistant//EN",
        "CALSCALE:GREGORIAN",
    ]
    for row in reservations:
        date_str, time_str, email, details = row
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        dt_end = dt + timedelta(hours=1)
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{date_str}-{time_str}-{email}",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{dt.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND:{dt_end.strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:Meeting with {email}",
            f"DESCRIPTION:{details}",
            f"ATTENDEE:mailto:{email}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


def stream_graph_response(user_input: str):
    """Stream token chunks from the graph and yield text pieces."""
    try:
        for stream_mode, chunk in graph.stream(
            {"messages": [HumanMessage(content=user_input)]},
            CONFIG,
            stream_mode=["messages"],
        ):
            if stream_mode == "messages":
                msg, meta = chunk
                # Only yield final text replies (not tool calls or internal signals)
                if (
                    isinstance(msg, AIMessage)
                    and msg.content
                    and not getattr(msg, "tool_calls", None)
                    and "ROUTE_TO_BOOKING" not in msg.content
                ):
                    yield msg.content
    except Exception as e:
        yield f"\n\n*Error: {e}*"


# Voice input component — uses browser-native Web Speech API, no external services
VOICE_COMPONENT = """
<div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
  <button id="voiceBtn" onclick="toggleListening()" style="
    background:#1d4ed8; color:#fff; border:none; border-radius:6px;
    padding:6px 14px; font-size:13px; font-weight:500; cursor:pointer;
    font-family:Inter,sans-serif; transition:background 0.15s;
  ">Hold to speak</button>
  <span id="voiceStatus" style="font-size:12px; color:#6b7280; font-family:Inter,sans-serif;"></span>
</div>
<input type="text" id="voiceResult" style="display:none;" />

<script>
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let listening = false;

function toggleListening() {
    if (!SpeechRecognition) {
        document.getElementById('voiceStatus').textContent = 'Not supported in this browser.';
        return;
    }
    if (listening) {
        recognition.stop();
        return;
    }
    recognition = new SpeechRecognition();
    recognition.lang = 'en-US';
    recognition.interimResults = false;

    const btn = document.getElementById('voiceBtn');
    const status = document.getElementById('voiceStatus');

    recognition.onstart = () => {
        listening = true;
        btn.textContent = 'Listening...';
        btn.style.background = '#dc2626';
        status.textContent = '';
    };
    recognition.onresult = (e) => {
        const transcript = e.results[0][0].transcript;
        // Send to Streamlit via URL param trick
        window.parent.postMessage({type: 'streamlit:setComponentValue', value: transcript}, '*');
        status.textContent = '\u201c' + transcript + '\u201d';
    };
    recognition.onerror = (e) => {
        status.textContent = 'Error: ' + e.error;
    };
    recognition.onend = () => {
        listening = false;
        btn.textContent = 'Hold to speak';
        btn.style.background = '#1d4ed8';
    };
    recognition.start();
}
</script>
"""


# ── Layout ────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="header-container">
  <h1 class="header-title">Scheduling Assistant</h1>
  <p class="header-meta">LangGraph state machine &middot; llama-4-scout &middot; SQLite persistence</p>
</div>
""", unsafe_allow_html=True)

col_chat, col_db = st.columns([3, 2])


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Settings")

    webhook = st.text_input(
        "Webhook URL",
        value=os.environ.get("WEBHOOK_URL", "https://httpbin.org/post"),
        help="POST target for booking notifications",
    )
    os.environ["WEBHOOK_URL"] = webhook

    st.markdown("---")
    st.markdown("### Block a slot manually")
    st.caption("Useful for testing conflict handling.")

    with st.form("mock_busy_form"):
        p_email = st.text_input("Email", "alice@example.com")
        b_date = st.date_input("Date", datetime.now())
        b_time = st.time_input("Start time")
        b_hrs = st.number_input("Duration (hours)", 1, 8, 1)
        if st.form_submit_button("Add block"):
            start_iso = f"{b_date}T{b_time.strftime('%H:%M')}"
            end_dt = datetime.strptime(
                f"{b_date} {b_time.strftime('%H:%M')}", "%Y-%m-%d %H:%M"
            ) + timedelta(hours=b_hrs)
            add_mock_busy(p_email, start_iso, end_dt.strftime("%Y-%m-%dT%H:%M"))
            st.success("Slot blocked.")

    if st.button("Clear session"):
        clear_db()
        st.success("Cleared.")
        st.rerun()

    st.markdown("---")
    st.markdown("### Quick prompts")
    st.code("What can you do?")
    st.code("Book alice@example.com tomorrow at 2pm for 90 minutes")
    st.code("Check availability for next Monday")


# ── Chat column ───────────────────────────────────────────────────────────────
with col_chat:
    st.markdown('<p class="section-label">Conversation</p>', unsafe_allow_html=True)

    chat_area = st.container(height=500, border=False)

    with chat_area:
        history = load_history()
        i = 0
        while i < len(history):
            msg = history[i]

            is_tool_call = isinstance(msg, AIMessage) and bool(getattr(msg, "tool_calls", None))
            is_tool_msg = isinstance(msg, ToolMessage)

            if is_tool_call or is_tool_msg:
                # Collect all consecutive tool-related messages into one expander
                tool_group = []
                while i < len(history):
                    curr = history[i]
                    if (isinstance(curr, AIMessage) and bool(getattr(curr, "tool_calls", None))) or isinstance(curr, ToolMessage):
                        tool_group.append(curr)
                        i += 1
                    else:
                        break

                with st.expander(f"System activity ({len([m for m in tool_group if isinstance(m, ToolMessage)])} tool calls)", expanded=False):
                    for tm in tool_group:
                        if isinstance(tm, ToolMessage):
                            st.markdown(f"**{tm.name}**")
                            st.code(tm.content, language="json")
                        elif getattr(tm, "tool_calls", None):
                            for tc in tm.tool_calls:
                                st.markdown(f"Requested `{tc['name']}`")
                                st.json(tc["args"])
                continue

            role = "user" if isinstance(msg, HumanMessage) else "assistant"
            content = msg.content or ""

            if content and "ROUTE_TO_BOOKING" not in content:
                with st.chat_message(role):
                    st.write(content)

            i += 1

    # Native Streamlit audio input + Groq Whisper STT
    audio_bytes = st.audio_input("Record a voice message")
    text_input = st.chat_input("Ask to book, check, or reschedule...")
    
    user_input = text_input
    
    if audio_bytes and not text_input:
        try:
            client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
            transcription = client.audio.transcriptions.create(
                file=("audio.wav", audio_bytes.getvalue()),
                model="whisper-large-v3-turbo",
            )
            user_input = transcription.text
        except Exception as e:
            st.error(f"Voice recognition failed: {e}")

    if user_input:
        with chat_area:
            with st.chat_message("user"):
                st.write(user_input)

        with chat_area:
            with st.chat_message("assistant"):
                # Stream token-by-token using st.write_stream
                st.write_stream(stream_graph_response(user_input))

        st.rerun()


# ── Database column ───────────────────────────────────────────────────────────
with col_db:
    st.markdown('<p class="section-label">Database</p>', unsafe_allow_html=True)

    busy_slots = fetch_busy_slots()
    reservations = fetch_reservations()

    s1, s2 = st.columns(2)
    with s1:
        st.markdown(f"""
        <div class="stat-card">
          <div class="stat-value">{len(busy_slots)}</div>
          <div class="stat-label">Busy slots</div>
        </div>""", unsafe_allow_html=True)
    with s2:
        st.markdown(f"""
        <div class="stat-card">
          <div class="stat-value">{len(reservations)}</div>
          <div class="stat-label">Reservations</div>
        </div>""", unsafe_allow_html=True)

    st.markdown('<p class="section-label" style="margin-top:1.25rem">Occupied slots</p>', unsafe_allow_html=True)
    if busy_slots:
        import pandas as pd
        st.dataframe(
            pd.DataFrame(busy_slots, columns=["Email", "Start", "End"]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("None.")

    st.markdown('<p class="section-label" style="margin-top:1.25rem">Confirmed bookings</p>', unsafe_allow_html=True)
    if reservations:
        import pandas as pd
        df = pd.DataFrame(reservations, columns=["Date", "Time", "Email", "Details"])
        st.dataframe(df, use_container_width=True, hide_index=True)

        ical_bytes = make_ical(reservations).encode("utf-8")
        st.download_button(
            label="Export calendar (.ics)",
            data=io.BytesIO(ical_bytes),
            file_name="bookings.ics",
            mime="text/calendar",
        )
    else:
        st.caption("No confirmed bookings.")

    st.markdown('<p class="section-label" style="margin-top:1.25rem">Agent state</p>', unsafe_allow_html=True)
    try:
        snap = graph.get_state(CONFIG)
        agent = snap.values.get("current_agent", "—") if snap.values else "—"
        n_msgs = len(snap.values.get("messages", [])) if snap.values else 0
        st.markdown(f"""
        <div class="status-card">
          <div class="status-row-label">Current agent</div>
          <div class="status-row-value">{agent}</div>
          <div class="status-row-label" style="margin-top:0.75rem">Context messages</div>
          <div class="status-row-value">{n_msgs}</div>
        </div>""", unsafe_allow_html=True)
    except Exception:
        st.caption("No active session.")
