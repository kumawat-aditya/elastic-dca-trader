import asyncio
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database.session import engine as db_engine, Base
from app.routers import ea_api, ui_api
from app.config import settings
from app.services.engine import engine
from app.logger import get_logger

# Initialize the logger for this file
logger = get_logger(__name__)

# 1. Create SQLite Tables (if they don't exist)
logger.info("Initializing SQLite Database Tables...")
Base.metadata.create_all(bind=db_engine)

# --- NEW: FILTER TO BLOCK UVICORN SPAM ---
class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Hide the 1-second tick and WebSocket connection logs from Uvicorn
        return "/api/v1/ea/tick" not in record.getMessage() and "/ws" not in record.getMessage()

# Attach the filter to Uvicorn's access logger
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())


# --- UPDATED: BACKGROUND TASK WITH LOG AGGREGATION ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    async def timeout_watcher():
        logger.debug("EA Timeout Watcher loop running...")
        last_log_time = time.time()
        last_tick_count = 0
        
        while True:
            engine.check_ea_timeout()
            
            # Aggregate Log Every 60 Seconds
            now = time.time()
            if now - last_log_time >= 60.0:
                ticks_this_minute = engine.ticks_processed - last_tick_count
                if ticks_this_minute > 0:
                    logger.info(f"[System Health] EA Connection Stable. Processed {ticks_this_minute} ticks in the last 60 seconds.")
                
                last_tick_count = engine.ticks_processed
                last_log_time = now
                
            await asyncio.sleep(1) # Evaluate every second
            
    # Start background task
    logger.info("Starting Background EA Timeout Watcher Task...")
    task = asyncio.create_task(timeout_watcher())
    
    yield
    
    # Cleanup task when server shuts down
    logger.info("Shutting down... Canceling Background EA Timeout Watcher Task.")
    task.cancel()

# 2. Initialize FastAPI
logger.info("Booting up Elastic DCA Engine v4...")
app = FastAPI(title="Elastic DCA Engine v4", version="4.0.0", lifespan=lifespan)

# 3. Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Change to your frontend URL in production (e.g., http://localhost:3000)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Include the Routers
app.include_router(ea_api.router, prefix="/api/v1/ea", tags=["EA Communication"])
app.include_router(ui_api.router, prefix="/api/v1/ui", tags=["Dashboard & UI"])
logger.info("API Routers mounted successfully.")

@app.get("/")
def health_check():
    logger.debug("Health check endpoint pinged.")
    return {
        "status": "online",
        "engine": "Elastic DCA v4",
        "message": "Engine running and actively monitoring via background task."
    }

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting Uvicorn server on {settings.HOST}:{settings.PORT}...")
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)