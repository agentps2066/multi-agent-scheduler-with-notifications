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

def _get_safe_conn(db_path):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    try:
        conn.execute("PRAGMA schema_version;")
    except sqlite3.DatabaseError:
        # Corrupted database detected! Delete and recreate.
        conn.close()
        try:
            os.remove(db_path)
            if os.path.exists(db_path + "-wal"): os.remove(db_path + "-wal")
            if os.path.exists(db_path + "-shm"): os.remove(db_path + "-shm")
        except OSError:
            pass
        conn = sqlite3.connect(db_path, check_same_thread=False)
    return conn

_conn = _get_safe_conn(_DB_PATH)
memory = SqliteSaver(_conn)
try:
    memory.setup()
except Exception:
    pass

# Cross-session store: persists user preferences across different conversation threads
_MEM_PATH = os.path.join(os.path.dirname(__file__), "user_memory.db")
_mem_conn = _get_safe_conn(_MEM_PATH)
user_store = SqliteStore(_mem_conn)
try:
    user_store.setup()
except Exception:
    pass

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
