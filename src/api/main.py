import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S %d-%m-%Y"
)

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware

from src.api.templates.router import static_router
from src.api.video.router import video_router
from src.api.video.handlers import video_requests_handler, register_video_helpers, register_video_handlers

@asynccontextmanager
async def lifespan(app: FastAPI):
    register_video_handlers()
    await register_video_helpers()

    asyncio.create_task(video_requests_handler.start())
    yield
    await video_requests_handler.queue.join()

app: FastAPI = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=["*"],
    allow_headers=["*"]
)

app_router: APIRouter = APIRouter()
app_router.include_router(video_router, prefix="/videos")

app.include_router(app_router, prefix="/v1")
app.include_router(static_router)
