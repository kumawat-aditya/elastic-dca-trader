from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from app.models.schemas import TickData
from app.services.engine import engine
from app.logger import get_logger

# Initialize the logger for this file
logger = get_logger(__name__)

router = APIRouter()

@router.post("/tick")
async def receive_tick(tick: TickData):
    """
    Receives the 1-second heartbeat from MT5 EA.
    Updates the system state and returns the bulk queued actions.
    """
    try:
        # Log the tick at DEBUG level so it doesn't spam the console on INFO level
        logger.debug(f"Tick received - Symbol: {tick.symbol} | Ask: {tick.ask} | Bid: {tick.bid}")

        # 1. Feed the tick to the engine to evaluate everything
        engine.update_from_tick(tick)
        
        # 2. Extract ALL pending actions and clear the queue
        actions_payload = engine.get_and_clear_pending_actions()
        
        # If there are actions being sent, log it at INFO level so we see it happening
        if actions_payload:
            logger.info(f"Dispatching {len(actions_payload)} bulk action(s) to EA.")
            for act in actions_payload:
                logger.debug(f"Action Payload: {act}")
        
        # 3. Return as an array to the EA
        return {"actions": actions_payload}

    except ValidationError as e:
        logger.error(f"Validation Failed on EA Tick Payload: {e}")
        # Fixed: return v4 bulk array format instead of v3 single action
        return {"actions":[]} 
    except Exception as e:
        # exc_info=True will print the full traceback to the logs for easier debugging
        logger.error(f"System Error during EA Tick processing: {e}", exc_info=True)
        return {"actions":