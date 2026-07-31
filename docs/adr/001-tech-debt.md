# ADR-001: API Key 验证性能技术债

## 状态
已记录（Phase 0 实现，Phase 2 优化）

## 背景
API Key 使用 bcrypt 哈希存储，验证时需遍历所有 enabled 用户做 bcrypt 逐一比对。
Phase 0 用户量小（<100），遍历成本可接受。

## 技术债
当前 `_verify_api_key_and_get_user` 通过 `api_key_prefix` 缩小范围后
对匹配用户做 bcrypt 逐一校验。用户量增长后（>1000）性能不可接受。

## 计划
- Phase 2：给 `api_key_hash` 字段加 UNIQUE 索引
- 客户端提交 `X-API-Key` header 时先 hash 再查数据库
- 或者：API Key 拆为 `prefix.id.secret` 三段式，prefix 查库 + secret bcrypt 验证

## 候选方案对比

| 方案 | 优势 | 劣势 | 建议阶段 |
|------|------|------|----------|
| api_key_hash 唯一索引 | 实现简单，一次查询定位 | 仍需 bcrypt 验证 | Phase 2 |
| prefix.id.secret 三段式 | prefix 查询无需 bcrypt | 改 API Key 格式，前端适配 | Phase 1 优先 |
| Redis hash 缓存 | 查询 < 1ms | 增加缓存一致性维护 | Phase 3 |

## 触发评估条件

- API Key 认证 P95 延迟 > 200ms
- 或启用 API Key 的用户数 > 500
- 或 bcrypt CPU 占用 > 单核 30%

当任一条件满足时，优先实施方案"prefix.id.secret 三段式"。

## 相关文件
- app/depends/auth.py → _verify_api_key_and_get_user()
