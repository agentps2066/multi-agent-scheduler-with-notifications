import os
from dotenv import load_dotenv
from typing import Dict, Any, Literal, Optional
from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, AIMessage
from state import AgentState

load_dotenv()

llm = ChatGroq(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    temperature=0.1,
    api_key=os.environ.get("GROQ_API_KEY"),
)


class TriageResult(BaseModel):
    intent: Literal["booking", "general"]
    reply: Optional[str] = None  # populated when intent is 'general'


structured_llm = llm.with_structured_output(TriageResult)

TRIAGE_SYSTEM_PROMPT = """You are a classification assistant for a calendar scheduler.

Analyze the user's message and respond with a JSON object containing:
- "intent": either "booking" or "general"
- "reply": a brief response string (only when intent is "general", otherwise omit or set to null)

Use intent "booking" if the user wants to schedule, book, check availability, cancel, or reschedule a meeting.
Use intent "general" for greetings, questions about capabilities, or general conversation — and include a helpful reply.
"""


def triage_agent_node(state: AgentState) -> Dict[str, Any]:
    # Only use the last Human message for triage to avoid Groq JSON mode history errors
    # with previous tool calls or long context.
    messages = state.get("messages", [])
    last_human = None
    for m in reversed(messages):
        if m.type == "human":
            last_human = m
            break

    system = SystemMessage(content=TRIAGE_SYSTEM_PROMPT)
    inputs = [system]
    if last_human:
        inputs.append(last_human)

    result: TriageResult = structured_llm.invoke(inputs)

    if result.intent == "booking":
        return {"current_agent": "booking_specialist"}

    return {
        "current_agent": "triage_agent",
        "messages": [AIMessage(content=result.reply)],
    }


def triage_router(state: AgentState) -> Literal["booking_specialist", "__end__"]:
    if state.get("current_agent") == "booking_specialist":
        return "booking_specialist"
    return "__end__"
