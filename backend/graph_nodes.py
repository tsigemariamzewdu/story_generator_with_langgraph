from typing import  List, Optional
from typing_extensions import Annotated,TypedDict
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage,ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt, Command
import time
from state import State
from tools import fix_grammar_locally

import os
from dotenv import load_dotenv
import language_tool_python

from tracker import track_node


load_dotenv()

# -----------------------------
# LLM Initialization
# -----------------------------
llm = init_chat_model(
    "google_genai:gemini-2.5-flash",
    api_key=os.getenv("GOOGLE_API_KEY")
)







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
@track_node("grammar_check_node")
def grammar_check_node(state: State):
    # Important: Small delay to stay under Gemini's Free Tier RPM limit
    time.sleep(1) 
    
    # Bind the tool so the LLM knows it can use it
    llm_with_tools = llm.bind_tools([fix_grammar_locally])
    
    # We ask the LLM to review the story. It will likely call the tool.
    response = llm_with_tools.invoke([
        SystemMessage(content="You are a helpful editor. Use the fix_grammar_locally tool to clean up the story draft."),
        HumanMessage(content=state["story"])
    ])
    
    return {"messages": [response]}

@track_node("apply_corrections")
def apply_corrections(state: State):
    """Takes the output from the tool and updates the 'story' field."""
    last_message = state["messages"][-1]
    
    # If the last message is from a tool, update the story
    if isinstance(last_message, ToolMessage):
        return {
            "story": last_message.content,
            "history": state["history"] + ["Grammar and spelling improved locally."]
        }
    return {} # Do nothing if no tool was called