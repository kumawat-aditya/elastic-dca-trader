from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from app.models.schemas import TickData
from app.services.engine import engine

router = APIRouter()

@router.post("/tick")
async def receive_tick(tick: TickData):
    """
    Receives the 1-second heartbeat from MT5 EA.
    Updates the system state and returns the next queued action.
    """
    try:
        # 1. Feed the tick to the engine to evaluate everything
        engine.update_from_tick(tick)
        
        # 2. Extract ALL pending actions and clear the queue
        actions_payload = engine.get_and_clear_pending_actions()
        
        # 3. Return as an array to the EA
        return {"actions": actions_payload}

    except ValidationError as e:
        print(f"[EA TICK ERROR] Validation Failed: {e}")
        return {"action": "WAIT"}
    except Exception as e:
        print(f"[EA TICK ERROR] System Error: {e}")
        return {"action": "WAIT"}