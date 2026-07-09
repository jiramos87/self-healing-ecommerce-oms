"""Vercel Python entry: re-export the FastAPI app."""

from app.main import app

__all__ = ["app"]
