from typing import Annotated, Dict, List, Optional, TypedDict, Any
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    current_agent: str
    booking_details: Dict[str, Any]
    validation_errors: List[str]
