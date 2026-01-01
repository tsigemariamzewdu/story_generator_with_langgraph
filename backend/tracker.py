from state import State
import time
from datetime import datetime

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