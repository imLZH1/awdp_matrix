import logging
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.core.config import settings
from backend.core.database import engine, Base
from backend.models import models
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import asyncio
from backend.engine.scheduler import game_engine_loop

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup
    logger.info("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # Start game engine background task
    engine_task = asyncio.create_task(game_engine_loop())
    
    yield
    
    # Cleanup on shutdown
    logger.info("Shutting down...")
    engine_task.cancel()
    try:
        await engine_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Include API Router
from backend.api.v1.api import api_router
from backend.api.v1.admin import admin_router

app.include_router(api_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1/admin")

# Mount Static Files for the frontend
frontend_dir = "/opt/awdp/frontend"
if not os.path.exists(frontend_dir):
    os.makedirs(frontend_dir)
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def root():
    # Serve the handwritten HTML file directly at the root
    return FileResponse(os.path.join(frontend_dir, "index.html"))

@app.get("/scoreboard")
async def scoreboard_page():
    # Serve the standalone scoreboard HTML file
    return FileResponse(os.path.join(frontend_dir, "scoreboard.html"))

@app.get("/admin/login")
async def admin_page():
    # Serve the admin dashboard HTML file
    return FileResponse(os.path.join(frontend_dir, "admin.html"))

