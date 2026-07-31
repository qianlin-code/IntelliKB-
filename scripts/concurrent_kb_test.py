"""
高并发知识库创建测试
目标：验证 quota_service.check_kb_creation 的 SELECT FOR UPDATE 行锁能防止竞态条件
配置：20 并发 / 共 50 请求，管理员当前 KB 数应不超过 QUOTA_MAX_KB_PER_USER
"""
import asyncio
import httpx
import time
from datetime import datetime

BASE_URL = "http://127.0.0.1:8000"  # 测试时若主后端未重启，可临时改为 8002
USERNAME = "admin"
PASSWORD = "admin123"
TOTAL_REQUESTS = 50
CONCURRENCY = 20


async def login(client: httpx.AsyncClient) -> str:
    r = await client.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
    )
    r.raise_for_status()
    return r.json()["data"]["access_token"]


async def create_kb(client: httpx.AsyncClient, token: str, idx: int) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "name": f"并发测试KB_{idx:03d}_{int(time.time())}",
        "description": "high concurrency quota test",
        "is_public": False,
        "chunk_size": 500,
        "chunk_overlap": 50,
    }
    try:
        r = await client.post(
            f"{BASE_URL}/api/v1/knowledge-bases",
            json=payload,
            headers=headers,
            timeout=30,
        )
        return {
            "idx": idx,
            "status": r.status_code,
            "kb_id": r.json().get("data", {}).get("id") if r.status_code == 201 else None,
            "detail": r.json().get("message") if r.status_code != 201 else None,
        }
    except Exception as e:
        return {"idx": idx, "status": 0, "kb_id": None, "detail": str(e)}


async def get_kb_count(client: httpx.AsyncClient, token: str) -> int:
    headers = {"Authorization": f"Bearer {token}"}
    r = await client.get(
        f"{BASE_URL}/api/v1/knowledge-bases?page_size=1",
        headers=headers,
    )
    r.raise_for_status()
    return r.json()["data"]["total"]


async def main():
    async with httpx.AsyncClient() as client:
        token = await login(client)
        before = await get_kb_count(client, token)
        print(f"[{datetime.now().isoformat()}] 测试开始，当前 KB 数: {before}")

        semaphore = asyncio.Semaphore(CONCURRENCY)

        async def bounded_create(idx: int):
            async with semaphore:
                return await create_kb(client, token, idx)

        start = time.time()
        results = await asyncio.gather(*[bounded_create(i) for i in range(TOTAL_REQUESTS)])
        elapsed = time.time() - start

        after = await get_kb_count(client, token)
        success = [r for r in results if r["status"] == 201]
        quota_exceeded = [r for r in results if r["status"] == 429]
        lock_busy = [r for r in results if r["status"] == 400 and "系统繁忙" in (r["detail"] or "")]
        errors = [r for r in results if r["status"] not in (201, 429, 400)]

        print(f"[{datetime.now().isoformat()}] 测试结束")
        print(f"总请求数: {TOTAL_REQUESTS}")
        print(f"并发数: {CONCURRENCY}")
        print(f"耗时: {elapsed:.2f}s")
        print(f"测试前 KB 数: {before}")
        print(f"测试后 KB 数: {after}")
        print(f"成功创建: {len(success)}")
        print(f"配额超限 (429): {len(quota_exceeded)}")
        print(f"锁等待超时/繁忙 (400): {len(lock_busy)}")
        print(f"其他错误: {len(errors)}")
        if errors:
            for e in errors[:10]:
                print(f"  - idx={e['idx']} status={e['status']} detail={e['detail']}")

        expected_success = 10 - before
        rejected = len(quota_exceeded) + len(lock_busy)
        # 核心不变量：成功数必须等于剩余配额，最终总数必须等于配额上限
        ok = (
            len(success) == expected_success
            and after == 10
            and rejected == TOTAL_REQUESTS - expected_success
            and len(errors) == 0
        )
        print(f"预期成功数: {expected_success}")
        print(f"预期拒绝数: {TOTAL_REQUESTS - expected_success}")
        print(f"预期最终 KB 数: 10")
        print(f"结果: {'✅ 通过' if ok else '❌ 失败'}")
        return results, ok


if __name__ == "__main__":
    asyncio.run(main())
