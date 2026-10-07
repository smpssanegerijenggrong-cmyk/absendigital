"""Vercel/FastAPI entrypoint for SANJARA HADIR.

Vercel scans common Python entrypoint files. The actual application lives in
``app.main`` so the local/Docker layout stays modular.
"""
from app.main import app

__all__ = ["app"]
