import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List

from app.services.engine import engine
from app.models.schemas import GridSettings, GridRow
from app.database.session import get_db
from app.database.models import PresetDB
from pydantic import BaseModel

router = APIRouter()

# --- WEBSOCKET FOR LIVE DASHBOARD ---

@router.websocket("/ws")
async def dashboard_stream(websocket: WebSocket):
    """
    Pushes the entire SystemState to the frontend 1x per second.
    This includes Mid/Ask/Bid, Trends, Grid PnL, Alerts, and Execution Markers.
    """
    await websocket.accept()
    try:
        while True:
            # Send the complete state as JSON
            await websocket.send_json(engine.state.model_dump())
            print(engine.state.model_dump())
            await asyncio.sleep(1) # Sync with the 1-second EA ping
    except WebSocketDisconnect:
        print("[UI] Dashboard WebSocket Disconnected.")
    except Exception as e:
        print(f"[UI] WebSocket Error: {e}")

# --- ALERTS ---
@router.post("/ack-alert/{side}/{index}")
def acknowledge_alert(side: str, index: int):
    """Frontend calls this after playing the notification sound/popup."""
    if side not in ["buy", "sell"]: raise HTTPException(status_code=400, detail="Invalid side")
    settings = engine.state.buy_settings if side == "buy" else engine.state.sell_settings
    
    for row in settings.rows:
        if row.index == index:
            row.alert_executed = True
            return {"status": "success"}
            
    raise HTTPException(status_code=404, detail="Row not found")

# --- GRID CONTROLS & SETTINGS (RUNTIME MODIFICATION) ---

class ControlPayload(BaseModel):
    is_on: bool
    is_cyclic: bool

@router.post("/control/{side}")
def toggle_grid_state(side: str, payload: ControlPayload):
    """Turns the grid ON/OFF or toggles Cyclic mode."""
    if side not in ["buy", "sell"]:
        raise HTTPException(status_code=400, detail="Invalid side")
        
    grid_settings = engine.state.buy_settings if side == "buy" else engine.state.sell_settings
    grid_state = engine.state.buy_state if side == "buy" else engine.state.sell_state
    
    grid_settings.is_cyclic = payload.is_cyclic
    
    # If turning OFF, we send a CLOSE_ALL to EA and hard reset the session
    if grid_settings.is_on and not payload.is_on:
        grid_settings.is_on = False
        if grid_state.session_id:
            engine.pending_ea_actions.append({
                "action": "CLOSE_ALL",
                "comment": grid_state.session_id
            })
            engine._clear_grid_cycle(side, hard_reset=True)
            print(f"[{side.upper()}] Grid manually turned OFF. Sent CLOSE_ALL.")
            
    # If turning ON, Engine will catch it on the next tick and initiate the anchor
    elif not grid_settings.is_on and payload.is_on:
        grid_settings.is_on = True
        print(f"[{side.upper()}] Grid manually turned ON. Awaiting anchor/crossover.")

    return {"status": "success", "is_on": grid_settings.is_on, "is_cyclic": grid_settings.is_cyclic}

@router.put("/settings/{side}")
def update_grid_settings(side: str, new_settings: GridSettings):
    """
    Updates the grid parameters. 
    Implements Blueprint Constraint: Executed rows are locked. 
    Unexecuted rows are editable (gap, lots, alert).
    """
    if side not in ["buy", "sell"]:
        raise HTTPException(status_code=400, detail="Invalid side")
        
    current_settings = engine.state.buy_settings if side == "buy" else engine.state.sell_settings
    
    if current_settings.is_on:
        # Strict Executed Row Map
        old_executed_map = {r.index: r for r in current_settings.rows if r.executed}
        new_rows_map = {r.index: r for r in new_settings.rows}
        
        # 1. Enforce that EVERY old executed row STILL EXISTS identically in the new payload
        for old_idx, old_row in old_executed_map.items():
            if old_idx not in new_rows_map:
                raise HTTPException(status_code=400, detail=f"Cannot delete executed row {old_idx}.")
                
            new_row = new_rows_map[old_idx]
            if new_row.gap != old_row.gap or new_row.lots != old_row.lots:
                raise HTTPException(status_code=400, detail=f"Cannot alter gap/lots of executed row {old_idx}.")
            
            # Carry over internal states
            new_row.price = old_row.price
            new_row.pnl = old_row.pnl
            new_row.cumulative_pnl = old_row.cumulative_pnl
            new_row.executed = True
            new_row.alert_executed = old_row.alert_executed
    
    # Save the merged settings
    if side == "buy":
        engine.state.buy_settings = new_settings
    else:
        engine.state.sell_settings = new_settings
    
    # Run the math recalculation to instantly populate cumulative_lots and price targets!
    engine.recalculate_grid_math(side)
        
    return {"status": "success", "message": f"{side.upper()} settings updated."}


# --- PRESETS (SQLITE CRUD) ---

class PresetCreate(BaseModel):
    name: str
    rows: List[GridRow]  # If this says 'settings: GridSettings', it causes the 422 error!

@router.post("/presets")
def save_preset(payload: PresetCreate, db: Session = Depends(get_db)):
    existing = db.query(PresetDB).filter(PresetDB.name == payload.name).first()
    if existing: 
        raise HTTPException(status_code=400, detail="Preset name already exists.")
        
    rows_json = json.dumps([r.model_dump() for r in payload.rows])
    new_preset = PresetDB(name=payload.name, rows_json=rows_json)
    db.add(new_preset)
    db.commit()
    return {"status": "success"}

@router.get("/presets")
def get_presets(db: Session = Depends(get_db)):
    """Returns a list of all saved presets."""
    presets = db.query(PresetDB).all()
    
    # 2. FIX: Must use 'rows_json' and parse it back to a JSON list, NOT 'settings_json'
    return[{"id": p.id, "name": p.name, "rows": json.loads(p.rows_json)} for p in presets]

@router.post("/presets/{preset_id}/load/{side}")
def load_preset(preset_id: int, side: str, db: Session = Depends(get_db)):
    """
    Loads a preset into the grid.
    Constraint: Cannot load preset if the target grid is actively running.
    """
    if side not in["buy", "sell"]:
        raise HTTPException(status_code=400, detail="Invalid side")
        
    current_settings = engine.state.buy_settings if side == "buy" else engine.state.sell_settings
    if current_settings.is_on:
        raise HTTPException(status_code=400, detail="Cannot load preset while grid is ON.")
        
    preset = db.query(PresetDB).filter(PresetDB.id == preset_id).first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found.")
        
    # Load ONLY the rows, safely bypassing limits/TP/SL settings
    rows_data = json.loads(preset.rows_json)
    loaded_rows =[GridRow(**r) for r in rows_data]
    
    if side == "buy": 
        engine.state.buy_settings.rows = loaded_rows
    else: 
        engine.state.sell_settings.rows = loaded_rows

    # Recalculate to generate immediate cumulative lots logic
    engine.recalculate_grid_math(side)
        
    return {"status": "success", "message": f"Preset '{preset.name}' loaded to {side.upper()} grid."}



