# story_generator_with_langgraph

A small demo project that combines a Python backend (simple LangGraph workflow) with a static frontend. The backend exposes a minimal API and graph-building utilities; the frontend is a lightweight HTML/JS UI that interacts with the backend.

## Features

- Minimal Flask backend (entry: `backend/app.py`) that serves an API used by the frontend.
- Graph utilities and workflow logic in `backend/graph_builder.py`, `backend/graph_nodes.py`, and `backend/static_workflow.py`.
- Simple static frontend in the `frontend/` folder (`index.html`, `script.js`, `style.css`).

## Repository structure

- `backend/` — Python backend and workflow helpers
	- `app.py` — Flask app / API server
	- `graph_builder.py` — graph construction utilities
	- `graph_nodes.py` — node definitions used by workflows
	- `static_workflow.py` — example workflow using the graph utilities
	- `toolswith.py` — helper utilities to show tool binding
	- `requirements.txt` — Python dependencies for the backend
- `frontend/` — static frontend assets
	- `index.html` — demo UI
	- `script.js` — frontend behaviour and API calls
	- `style.css` — styles
- `README.md` — this file
- `comparison.md` — project notes / comparisons

## Prerequisites

- Python 3.10+ recommended
- Optional: a virtual environment tool (venv, virtualenv)

## Setup (backend)

1. Create and activate a virtual environment (Windows example):

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

2. Install backend dependencies:

```powershell
pip install -r backend/requirements.txt
```

3. Run the backend Flask app from the `backend` folder:

```powershell
cd backend
python app.py
```

By default the app binds to `localhost` (see `backend/app.py` for the exact host/port). The backend provides the API endpoints the frontend calls.

## Run the frontend

The frontend is static and can be opened directly in a browser by opening `frontend/index.html`. For a more realistic setup (CORS and API calls to the local backend) serve the folder via a simple HTTP server from the repo root:

```powershell
# from the repo root
python -m http.server 8000 --directory frontend

# then open http://localhost:8000 in your browser
```

## Development notes

- The backend's behavior and endpoints are implemented in `backend/app.py` — inspect that file to see available routes.
- Workflow logic is in `backend/static_workflow.py` and `backend/graph_builder.py`.
- If you change dependencies, update `backend/requirements.txt` and reinstall.





