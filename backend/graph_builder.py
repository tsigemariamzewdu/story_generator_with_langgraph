import sqlite3
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from graph_nodes import State, generate_story, human_feedback, revise_story, title_generator, moral_extractor

def create_graph():
    builder = StateGraph(State)
    builder.add_node("generate_story", generate_story)
    builder.add_node("human_feedback", human_feedback)
    builder.add_node("revise_story", revise_story)
    builder.add_node("title_generator", title_generator)
    builder.add_node("moral_extractor", moral_extractor)

    builder.add_edge(START, "generate_story")
    builder.add_edge("generate_story", "human_feedback")
    builder.add_edge("revise_story", "human_feedback")
    builder.add_edge("title_generator", "moral_extractor")
    builder.add_edge("moral_extractor", END)

    memory = SqliteSaver(sqlite3.connect("stories.db", check_same_thread=False))
    return builder.compile(checkpointer=memory)

# Global graph instance
graph = create_graph()
