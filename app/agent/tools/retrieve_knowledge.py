"""
知识检索工具 —— 调用 HybridSearchService 检索知识库
"""
from langchain_core.tools import tool


def create_retrieve_knowledge_tool(db, kb_id: int, user_id: int):
    """创建检索工具实例（闭包注入 db session + kb_id + user_id）"""
    from app.services.hybrid_search_service import HybridSearchService
    from app.repositories.user import UserRepository

    @tool
    async def retrieve_knowledge(question: str, top_k: int = 5) -> list[dict]:
        """检索知识库中与问题相关的文档片段"""
        # 获取 User 对象（HybridSearchService 需要）
        user_repo = UserRepository(db)
        user = await user_repo.get_by_id(user_id)
        if user is None:
            from app.core.exceptions import NotFoundError
            raise NotFoundError(f"用户 {user_id} 不存在")

        hybrid_service = HybridSearchService(db)
        results, _ = await hybrid_service.search(
            kb_id=kb_id,
            question=question,
            user=user,
            top_k=top_k,
            use_rerank=True,
            use_cache=True,
        )
        return [r.model_dump(mode="json") for r in results]

    return retrieve_knowledge
