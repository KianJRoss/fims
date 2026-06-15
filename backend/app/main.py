import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings

app = FastAPI(
    title="FIMS — Fireworks Information Management System",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

media_root = os.getenv("MEDIA_ROOT", "/app/media")
os.makedirs(media_root, exist_ok=True)
app.mount("/media", StaticFiles(directory=media_root), name="media")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/v1")


@app.get("/health")
def health():
    return {"status": "ok"}
