from typing import TypedDict, List, Optional
from typing_extensions import Annotated
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt, Command
from datetime import datetime
import time

# -----------------------------
# LLM Initialization
# -----------------------------
llm = init_chat_model(
    "google_genai:gemini-2.5-flash",
    api_key="AIzaSyAiG9LJcFd1vMySp3-cy_0TumXlwBgKrZk"
)

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

# -----------------------------
# Utilities
# -----------------------------
def track_node(node_name: str):
    def decorator(func):
        def wrapper(state: State):
            print(f"🟢 [{datetime.now().strftime('%H:%M:%S')}] ENTER: {node_name}")
            start = time.time()
            result = func(state)
            print(f"✅ [{datetime.now().strftime('%H:%M:%S')}] EXIT: {node_name} ({time.time()-start:.2f}s)\n")
            return result
        return wrapper
    return decorator

# -----------------------------
# Tools
# -----------------------------
# @tool
# def creative_descriptor(prompt: str) -> str:
#     return f"""
# Write a highly vivid and immersive story based on the following idea.

# Use:
# - rich sensory details (sight, sound, smell, touch)
# - strong imagery and metaphors
# - emotional depth
# - atmospheric descriptions

# Story idea:
# {prompt}
# """



# -----------------------------
# Nodes
# -----------------------------
@track_node("generate_story")
def generate_story(state: State):
    response = llm.invoke([
        SystemMessage(content="You are a storyteller."),
        HumanMessage(content=state["prompt"])
    ])
    return {
        "story": getattr(response, "content", ""),
        "revision_count": 0,
        "history": ["Initial draft generated."],
        "messages": [response]
    }

@track_node("human_feedback")
def human_feedback(state: State):
    if state["revision_count"] >= 3:
        return Command(goto="title_generator")

    user_input = interrupt({
        "current_story": state["story"],
        "revision_count": state["revision_count"],
        "message": "Please provide feedback or type 'done'",
    })

    if user_input.lower() == "done":
        return Command(goto="title_generator")

    return Command(update={"feedback": user_input}, goto="revise_story")

@track_node("revise_story")
def revise_story(state: State):
    response = llm.invoke([
        SystemMessage(content="You are an editor."),
        HumanMessage(content=f"Feedback: {state['feedback']}\n\nStory: {state['story']}")
    ])
    return {
        "story": response.content,
        "revision_count": state["revision_count"] + 1,
        "history": state["history"] + [f"Revision {state['revision_count'] + 1} applied."]
    }

@track_node("title_generator")
def title_generator(state: State):
    response = llm.invoke([
        SystemMessage(content="You generate a creative title for a story."),
        HumanMessage(content=state["story"])
    ])
    return {
        "history": state["history"] + [f"Title: {response.content}"]
    }

@track_node("moral_extractor")
def moral_extractor(state: State):
    response = llm.invoke([
        SystemMessage(content="You extract the central moral or theme of a story."),
        HumanMessage(content=state["story"])
    ])
    return {
        "history": state["history"] + [f"Moral: {response.content}"]
    }
