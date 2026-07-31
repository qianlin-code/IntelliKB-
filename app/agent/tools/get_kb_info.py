"""
知识库信息工具 —— 获取当前知识库的统计信息

通过闭包注入 db / kb_id / user_id。
"""
from langchain_core.tools import tool


def create_kb_info_tool(db, kb_id: int, user_id: int):
    """创建 KB 信息工具实例"""
    from app.services.kb_service import KBService

    @tool
    async def get_knowledge_base_info() -> dict:
        """获取当前知识库的统计信息（名称、描述、文档数、分块数）"""
        kb_service = KBService(db)
        kb = await kb_service.get_accessible(kb_id, user_id)
        stats = await kb_service.get_stats(kb_id, user_id)
        return {
            "name": kb.name,
            "description": kb.description,
            "document_count": stats.document_count,
            "chunk_count": stats.chunk_count,
        }

    return get_knowledge_base_info
