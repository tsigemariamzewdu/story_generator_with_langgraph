from typing_extensions import TypedDict,Optional,List,Annotated
from langgraph.graph.message import add_messages
# -----------------------------
# State Definition
# -----------------------------
class State(TypedDict):
    prompt: str
    story: str
    feedback: Optional[str]
    revision_count: int
    history: List[str]
    session_id: str
    messages: Annotated[List, add_messages]
