import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database.session import engine as db_engine, Base
from app.routers import ea_api, ui_api
from app.config import settings
from app.services.engine import engine

# 1. Create SQLite Tables (if they don't exist)
Base.metadata.create_all(bind=db_engine)


# Background Timeout Watcher Task
@asynccontextmanager
async def lifespan(app: FastAPI):
    # This runs exactly once when the server boots
    async def timeout_watcher():
        while True:
            engine.check_ea_timeout()
            await asyncio.sleep(1) # Evaluate every second
            
    # Start background task
    task = asyncio.create_task(timeout_watcher())
    yield
    # Cleanup task when server shuts down
    task.cancel()

# 2. Initialize FastAPI
app = FastAPI(title="Elastic DCA Engine v4", version="4.0.0", lifespan=lifespan)

# 3. Add CORS Middleware (Crucial for a decoupled frontend Dashboard)
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

@app.get("/")
def health_check():
    return {
        "status": "online",
        "engine": "Elastic DCA v4",
        "message": "Engine running and actively monitoring via background task."
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)