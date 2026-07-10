"""
Booking specialist agent implementation.

Handles the tool-calling loop for checking availability, reserving slots,
and sending notifications, ensuring relative dates are normalized.
"""

import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from typing import Dict, Any, List, Literal

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, ToolMessage, AIMessage
from langchain_core.runnables import RunnableConfig

from state import AgentState
from tools import TOOLS
from date_normalizer import normalize_date

load_dotenv()

_llm = ChatGroq(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    temperature=0.1,
    api_key=os.environ.get("GROQ_API_KEY"),
).bind_tools(TOOLS)

_TOOL_MAP = {t.name: t for t in TOOLS}

TODAY = datetime.now().strftime("%Y-%m-%d")

_BOOKING_SYSTEM_PROMPT_BASE = f"""You are a Booking Specialist for a calendar scheduling assistant. Today's date is {TODAY}.

You have access to these tools:
- check_availability(date): Check what slots are taken on a date (YYYY-MM-DD)
- reserve_slot(date, time, email, duration_minutes=60): Reserve an appointment slot. date=YYYY-MM-DD, time=HH:MM (24h format), email=string, duration_minutes=integer (default is 60).
- cancel_slot(date, time, email): Cancel an existing appointment slot.
- reschedule_slot(email, old_date, old_time, new_date, new_time, duration_minutes=60): Reschedule an existing appointment.
- send_booking_notification(email, details): Send confirmation via webhook

Your workflow:
1. If the user's request is missing ANY of these: date, time, email — ASK for the missing pieces before calling any tools.
   CRITICAL RULE: DO NOT guess or default the time to 12:00 AM / 00:00! If the user specifies a date but no exact time (e.g., "day after tomorrow", "next Monday"), you MUST ask "What time would you like?" before reserving.
2. ALWAYS normalize relative dates before using tools:
   - "today"    → {TODAY}
   - "tomorrow" → {(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")}
   - "next [weekday]" → compute the correct YYYY-MM-DD
3. First call check_availability to confirm the slot is free.
4. If slot is taken or overlaps → tell the user and suggest 2-3 alternative open times from check_availability results.
5. If slot is free → call reserve_slot with correct duration_minutes (e.g. if user wants 2 hours 45 mins, duration_minutes=165), then call send_booking_notification.
6. After successful booking → give the user a clear confirmation summary.

Be conversational, helpful, and always confirm details with the user before booking.
"""


def _build_system_prompt(remembered_email=None, remembered_duration=None) -> str:
    prompt = _BOOKING_SYSTEM_PROMPT_BASE
    notes = []
    if remembered_email is not None:
        notes.append(f"Note: this user has previously used {remembered_email} as their email.")
    if remembered_duration is not None:
        notes.append(f"Their usual meeting duration is {remembered_duration} minutes.")
    if notes:
        prompt += "\n" + "\n".join(notes) + "\n"
    return prompt


def _execute_tool(tool_call) -> ToolMessage:
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]
    print(f"Calling tool: {tool_name} with arguments: {tool_args}")

    if "date" in tool_args:
        tool_args["date"] = normalize_date(tool_args["date"])

    tool_fn = _TOOL_MAP.get(tool_name)
    if tool_fn is None:
        result_str = f"Error: unknown tool '{tool_name}'"
    else:
        try:
            raw_result = tool_fn.invoke(tool_args)
            if isinstance(raw_result, list) and not raw_result:
                result_str = "No slots are currently occupied. The date is completely free."
            else:
                import json
                result_str = json.dumps(raw_result)
        except Exception as exc:
            result_str = f"Tool error: {exc}"

    return ToolMessage(
        content=result_str,
        tool_call_id=tool_call["id"],
        name=tool_name,
    )


def booking_specialist_node(state: AgentState, config: RunnableConfig, store=None) -> Dict[str, Any]:
    user_id = config.get("configurable", {}).get("thread_id", "default_user")
    remembered_email = None
    remembered_duration = None

    if store is not None:
        try:
            namespace = (user_id, "preferences")
            prefs = store.search(namespace)
            for item in prefs:
                if item.key == "email":
                    remembered_email = item.value.get("value")
                if item.key == "duration_minutes":
                    remembered_duration = item.value.get("value")
        except Exception:
            pass

    messages = list(state.get("messages", []))
    system = SystemMessage(content=_build_system_prompt(remembered_email, remembered_duration))

    new_messages: List = []
    last_reservation_email = None
    last_duration = None

    for _ in range(10):
        response = _llm.invoke([system] + messages + new_messages)

        tool_calls = getattr(response, "tool_calls", None)

        if tool_calls:
            new_messages.append(response)
            for tc in tool_calls:
                tool_msg = _execute_tool(tc)
                new_messages.append(tool_msg)
                # Track email and duration when a reserve_slot succeeds
                if tc["name"] == "reserve_slot" and "success: True" in tool_msg.content:
                    last_reservation_email = tc["args"].get("email")
                    last_duration = tc["args"].get("duration_minutes")
        else:
            new_messages.append(response)
            print(f"Response: {response.content[:100]}")
            break

    if store is not None and last_reservation_email:
        try:
            namespace = (user_id, "preferences")
            store.put(namespace, "email", {"value": last_reservation_email})
            if last_duration is not None:
                store.put(namespace, "duration_minutes", {"value": last_duration})
        except Exception:
            pass

    return {
        "current_agent": "triage_agent",
        "messages": new_messages,
        "validation_errors": [],
    }


def booking_router(state: AgentState) -> Literal["triage_agent", "__end__"]:
    """Routes back to the triage agent after booking execution."""
    return "triage_agent"
