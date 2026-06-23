"""
API locale optionnelle pour simuler le run d'un workflow depuis HTTP.

Lancement :
uvicorn app:app --reload --port 7860

Test manuel :
curl -X POST http://127.0.0.1:7860/api/v1/run/S5_J22_AGENT \
  -H "Content-Type: application/json" \
  -d "{\"input_value\":\"Where Morocco is located ?\"}"
"""

from fastapi import FastAPI
from pydantic import BaseModel

from src.agent_graph import run_agent

app = FastAPI(title="Agentic AI Robust Wikipedia Agent")


class RunPayload(BaseModel):
    input_value: str


@app.post("/api/v1/run/S5_J22_AGENT")
def run_flow(payload: RunPayload):
    return run_agent(payload.input_value)
