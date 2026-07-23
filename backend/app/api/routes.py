"""Public API composition root.

Route implementations live in domain modules so this file remains a stable
import target for the FastAPI application and third-party integrations.
"""

from fastapi import APIRouter

from app.api.routers.documents import router as documents_router
from app.api.routers.quality import router as quality_router
from app.api.routers.retrieval import router as retrieval_router
from app.api.routers.knowledge_bases import router as knowledge_bases_router
from app.api.routers.ingestion import router as ingestion_router
from app.api.routers.conversations import router as conversations_router
from app.api.routers.providers import router as providers_router
from app.api.routers.parsers import router as parsers_router
from app.api.routers.query_assets import router as query_assets_router
from app.api.routers.system import router as system_router


router = APIRouter()
router.include_router(documents_router)
router.include_router(retrieval_router)
router.include_router(quality_router)
router.include_router(knowledge_bases_router)
router.include_router(ingestion_router)
router.include_router(conversations_router)
router.include_router(providers_router)
router.include_router(parsers_router)
router.include_router(query_assets_router)
router.include_router(system_router)
