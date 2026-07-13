"""Public API composition root.

Route implementations live in domain modules so this file remains a stable
import target for the FastAPI application and third-party integrations.
"""

from fastapi import APIRouter

from app.api.routers.documents import router as documents_router
from app.api.routers.quality import router as quality_router
from app.api.routers.retrieval import router as retrieval_router


router = APIRouter()
router.include_router(documents_router)
router.include_router(retrieval_router)
router.include_router(quality_router)
