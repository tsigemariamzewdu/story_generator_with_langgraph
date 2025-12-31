# static_story_generator.py
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

# Initialize LLM
llm = init_chat_model(
    "google_genai:gemini-2.5-flash",
    api_key="AIzaSyAiG9LJcFd1vMySp3-cy_0TumXlwBgKrZk"
)

def generate_story(prompt: str) -> str:
    """Generate initial story"""
    response = llm.invoke([
        SystemMessage(content="You are a storyteller."),
        HumanMessage(content=prompt)
    ])
    return getattr(response, "content", "")

def revise_story(story: str, feedback: str) -> str:
    """Revise story based on human feedback"""
    response = llm.invoke([
        SystemMessage(content="You are an editor."),
        HumanMessage(content=f"Feedback: {feedback}\n\nStory: {story}")
    ])
    return getattr(response, "content", "")

def generate_title(story: str) -> str:
    """Generate title for story"""
    response = llm.invoke([
        SystemMessage(content="You generate a creative title for a story."),
        HumanMessage(content=story)
    ])
    return getattr(response, "content", "")

def extract_moral(story: str) -> str:
    """Extract moral/theme of story"""
    response = llm.invoke([
        SystemMessage(content="You extract the central moral or theme of a story."),
        HumanMessage(content=story)
    ])
    return getattr(response, "content", "")

def static_workflow():
    # Step 1: Input prompt
    prompt = input("Enter story prompt: ")

    # Step 2: Generate initial story
    story = generate_story(prompt)
    print("\n--- Initial Story ---")
    print(story)

    # Step 3: Human-in-the-loop revisions
    revision_count = 0
    while revision_count < 3:
        feedback = input("\nProvide feedback (or type 'done' to finish revisions): ")
        if feedback.lower() == "done":
            break
        story = revise_story(story, feedback)
        print(f"\n--- Revised Story {revision_count+1} ---")
        print(story)
        revision_count += 1

    # Step 4: Generate title
    title = generate_title(story)
    print("\n--- Title ---")
    print(title)

    # Step 5: Extract moral
    moral = extract_moral(story)
    print("\n--- Moral ---")
    print(moral)

if __name__ == "__main__":
    static_workflow()
