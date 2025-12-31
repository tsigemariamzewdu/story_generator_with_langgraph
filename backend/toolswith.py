from typing import TypedDict, List, Literal, Union
from typing_extensions import Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_core.runnables.config import RunnableConfig

from langchain_google_genai import ChatGoogleGenerativeAI


import json

# Define the addition tool
@tool
def add_numbers(a: float, b: float) -> float:
    """Add two numbers together.
    
    Args:
        a: First number
        b: Second number
        
    Returns:
        The sum of a and b
    """
    return a + b

# Create tools list
tools = [add_numbers]

# Create LangChain Gemini model with tools
llm2 = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0,
    google_api_key="AIzaSyAiG9LJcFd1vMySp3-cy_0TumXlwBgKrZk"
)

# Bind tools to the model
llm_with_tools = llm2.bind_tools(tools)

# State definition
class ChatState(TypedDict):
    messages: Annotated[List, add_messages]

# LangChain Gemini node with tool support
def langchain_gemini_node(state: ChatState, config: RunnableConfig):
    """Gemini node using LangChain's integration for proper tool calling"""
    
    # Get conversation history
    messages = state["messages"]
    
    # Create system message
    system_message = SystemMessage(
        content="You are a helpful assistant that can perform calculations. "
                "When the user asks you to add two numbers, use the add_numbers tool. "
                "Always respond in a friendly and helpful manner."
    )
    
    # Combine system message with conversation history
    all_messages = [system_message] + messages
    
    try:
        # Call Gemini with tools
        response = llm_with_tools.invoke(all_messages)
        
        return {
            "messages": [response]
        }
        
    except Exception as e:
        print(f"Error calling Gemini: {e}")
        return {
            "messages": [
                AIMessage(content=f"I encountered an error: {str(e)}")
            ]
        }

# Create ToolNode for executing tools
tool_node = ToolNode(tools)

# Function to decide whether to use tools or end
def should_use_tools(state: ChatState) :
    """Route to tools if last message has tool calls, otherwise end"""
    messages = state["messages"]
    last_message = messages[-1]
    
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return END

# Build graph
graph = StateGraph(ChatState)

# Add nodes
graph.add_node("chatbot", langchain_gemini_node)
graph.add_node("tools", tool_node)

# Add edges
graph.add_edge(START, "chatbot")
graph.add_conditional_edges(
    "chatbot",
    should_use_tools,
    {
        "tools": "tools",
        END: END
    }
)
graph.add_edge("tools", "chatbot")

# Memory
memory = MemorySaver()
app = graph.compile(checkpointer=memory)

config = {"configurable": {"thread_id": 1}}

# TEST 1: Simple conversation with memory
print("=== Test 1: Memory Test ===")
app.invoke(
    {
        "messages": [
            HumanMessage(content="I am Tsige")
        ]
    },
    config=config
)

result = app.invoke(
    {
        "messages": [
            HumanMessage(content="What is my name?")
        ]
    },
    config=config
)
print("Response:", result["messages"][-1].content)

# TEST 2: Tool usage
print("\n=== Test 2: Addition Tool ===")
result = app.invoke(
    {
        "messages": [
            HumanMessage(content="Can you add 15 and 25 for me?")
        ]
    },
    config=config
)

# Check the result
for msg in result["messages"]:
    if isinstance(msg, AIMessage):
        if msg.tool_calls:
            print(f"Tool called: {msg.tool_calls}")
        else:
            print(f"Response: {msg.content}")

# TEST 3: Complex addition request
print("\n=== Test 3: Complex Addition ===")
result = app.invoke(
    {
        "messages": [
            HumanMessage(content="Add 3.14 and 2.86")
        ]
    },
    config=config
)

for msg in result["messages"]:
    if isinstance(msg, AIMessage):
        if msg.tool_calls:
            print(f"Tool called: {msg.tool_calls}")
        else:
            print(f"Response: {msg.content}")

# TEST 4: Follow-up conversation
print("\n=== Test 4: Follow-up ===")
result = app.invoke(
    {
        "messages": [
            HumanMessage(content="What was the result of adding 3.14 and 2.86?")
        ]
    },
    config=config
)

print("Response:", result["messages"][-1].content)