import os
import sqlite3
from dotenv import load_dotenv

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore

from state import AgentState
from triage import triage_agent_node, triage_router
from booking import booking_specialist_node

load_dotenv()

_DB_PATH = os.path.join(os.path.dirname(__file__), "checkpointer.db")
_conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
memory = SqliteSaver(_conn)

# Cross-session store: persists user preferences across different conversation threads
user_store = SqliteStore.from_conn_string(os.path.join(os.path.dirname(__file__), "user_memory.db"))

builder = StateGraph(AgentState)
builder.add_node("triage_agent", triage_agent_node)
builder.add_node("booking_specialist", booking_specialist_node)
builder.add_edge(START, "triage_agent")
builder.add_conditional_edges(
    "triage_agent",
    triage_router,
    {
        "booking_specialist": "booking_specialist",
        "__end__": END,
    }
)
builder.add_edge("booking_specialist", END)

graph = builder.compile(checkpointer=memory, store=user_store)
