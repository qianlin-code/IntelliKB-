"""v1 路由聚合"""
from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.knowledge_bases import router as kb_router
from app.api.v1.documents import router as doc_router
from app.api.v1.qa import router as qa_router
from app.api.v1.conversations import router as conv_router
from app.api.v1.agent_chat import router as agent_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(kb_router)
router.include_router(doc_router)
router.include_router(qa_router)
router.include_router(conv_router)
router.include_router(agent_router)
