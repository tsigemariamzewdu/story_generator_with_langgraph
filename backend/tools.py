from langchain_core.tools import tool
from textblob import TextBlob

# @track_node("fix_grammar_locally")
@tool
def fix_grammar_locally(text: str) -> str:
    """Corrects spelling and basic grammar mistakes in the story draft locally."""
    # TextBlob doesn't require an API key or internet
    corrected = TextBlob(text).correct()
    return str(corrected)

