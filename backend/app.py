from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langgraph.types import interrupt, Command
from typing import Optional, Dict, Any
import uuid
import asyncio
from contextlib import asynccontextmanager

# Models
class StoryRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None

class FeedbackRequest(BaseModel):
    session_id: str
    feedback: str

class EnhancementRequest(BaseModel):
    session_id: str
    enhancement_type: str  # "title" or "moral"

class SessionResponse(BaseModel):
    session_id: str
    story: Optional[str] = None
    title: Optional[str] = None
    moral: Optional[str] = None
    status: str
    revision_count: int
    history: list
    message: Optional[str] = None
    requires_feedback: bool = False
    story_complete: bool = False  # New field to indicate if story is finalized

# Import the graph after defining models
from graph_builder import graph

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Story Generator API starting...")
    yield
    # Shutdown
    print("Story Generator API shutting down...")

app = FastAPI(title="Story Generator API", lifespan=lifespan)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/start", response_model=SessionResponse)
async def start_story(request: StoryRequest):
    session_id = request.session_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}

    initial_state = {
        "prompt": request.prompt,
        "story": "",
        "feedback": None,
        "revision_count": 0,
        "history": [],
        "session_id": session_id,
        "messages":[]
    }

    # Stream until interrupt (or completion)
    output = None
    for event in graph.stream(initial_state, config, stream_mode="values"):
        output = event

    state = graph.get_state(config)

    requires_feedback = bool(state.next)  # If interrupted, next will still have nodes
    story_complete = not requires_feedback

    return SessionResponse(
        session_id=session_id,
        story=output.get("story"),
        revision_count=output.get("revision_count", 0),
        history=output.get("history", []),
        requires_feedback=requires_feedback,
        story_complete=story_complete,
        message="Provide feedback or 'done'" if requires_feedback else "Complete",
        status="awaiting_feedback" if requires_feedback else "completed"
    )
@app.post("/api/feedback", response_model=SessionResponse)
async def provide_feedback(request: FeedbackRequest):
    config = {"configurable": {"thread_id": request.session_id}}

    state = graph.get_state(config)
    if not state.values:
        raise HTTPException(status_code=404, detail="Session not found")

    feedback = request.feedback

    # Resume the interrupted graph with the feedback
    for event in graph.stream(Command(resume=feedback), config, stream_mode="values"):
        pass  # Consume stream to run until next interrupt or end

    # Get final state after resume
    updated_state = graph.get_state(config)
    output = updated_state.values

    requires_feedback = bool(updated_state.next)
    story_complete = not requires_feedback

    # Extract title/moral from history if needed (your existing logic)

    return SessionResponse(
        session_id=request.session_id,
        story=output.get("story"),
        revision_count=output.get("revision_count", 0),
        history=output.get("history", []),
        requires_feedback=requires_feedback,
        story_complete=story_complete,
        message="Provide feedback or 'done'" if requires_feedback else "Story finalized!",
        status="awaiting_feedback" if requires_feedback else "completed"
    )
@app.post("/api/enhance", response_model=SessionResponse)
async def enhance_story(request: EnhancementRequest):
    """Generate title or moral for the story"""
    session_id = request.session_id
    config = {"configurable": {"thread_id": session_id}}
    
    try:
        # Get current state
        state = graph.get_state(config)
        if not state.values:
            raise HTTPException(status_code=404, detail="Session not found")
        
        current_story = state.values.get("story", "")
        current_history = state.values.get("history", [])
        
        # Run specific enhancement node
        if request.enhancement_type == "title":
            from graph_nodes import title_generator
            
            # Run title generator
            title_result = title_generator({"story": current_story, "history": current_history})
            
            # Update state
            new_state = {
                **state.values,
                "title": title_result.get("history", [])[-1].replace("Title: ", "") if title_result.get("history") else None,
                "history": title_result.get("history", current_history)
            }
            
            graph.update_state(config, new_state)
            
        elif request.enhancement_type == "moral":
            from graph_nodes import moral_extractor
            
            # Run moral extractor
            moral_result = moral_extractor({"story": current_story, "history": current_history})
            
            # Update state
            new_state = {
                **state.values,
                "moral": moral_result.get("history", [])[-1].replace("Moral: ", "") if moral_result.get("history") else None,
                "history": moral_result.get("history", current_history)
            }
            
            graph.update_state(config, new_state)
        
        # Get updated state
        updated_state = graph.get_state(config)
        output = updated_state.values
        
        # Extract title and moral from history if not directly in output
        title = output.get("title")
        moral = output.get("moral")
        
        if not title:
            # Try to extract from history
            for item in output.get("history", []):
                if item.startswith("Title: "):
                    title = item.replace("Title: ", "")
                    break
        
        if not moral:
            # Try to extract from history
            for item in output.get("history", []):
                if item.startswith("Moral: "):
                    moral = item.replace("Moral: ", "")
                    break
        
        return SessionResponse(
            session_id=session_id,
            story=output.get("story"),
            title=title,
            moral=moral,
            status="completed",
            revision_count=output.get("revision_count", 0),
            history=output.get("history", []),
            message=f"Story {request.enhancement_type} generated successfully",
            requires_feedback=False,
            story_complete=True
        )
            
    except Exception as e:
        print(f"Error in enhance_story: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/session/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """Get current session state"""
    config = {"configurable": {"thread_id": session_id}}
    
    try:
        state = graph.get_state(config)
        
        if not state.values:
            raise HTTPException(status_code=404, detail="Session not found")
        
        requires_feedback = False
        message = None
        
        if state.next:
            requires_feedback = True
            message = "Please provide feedback to improve the story or type 'done' to finish"
        
        # Extract title and moral from history
        title = state.values.get("title")
        moral = state.values.get("moral")
        
        if not title:
            # Try to extract from history
            for item in state.values.get("history", []):
                if item.startswith("Title: "):
                    title = item.replace("Title: ", "")
                    break
        
        if not moral:
            # Try to extract from history
            for item in state.values.get("history", []):
                if item.startswith("Moral: "):
                    moral = item.replace("Moral: ", "")
                    break
        
        return SessionResponse(
            session_id=session_id,
            story=state.values.get("story"),
            title=title,
            moral=moral,
            status="awaiting_feedback" if requires_feedback else "completed",
            revision_count=state.values.get("revision_count", 0),
            history=state.values.get("history", []),
            message=message,
            requires_feedback=requires_feedback,
            story_complete=not requires_feedback
        )
    except Exception as e:
        print(f"Error in get_session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)