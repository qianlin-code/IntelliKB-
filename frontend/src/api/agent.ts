import { get, post } from "./request";
import type { AgentChatRequest, AgentChatResponse } from "@/types";

export function agentChatApi(data: AgentChatRequest) {
  return post<AgentChatResponse>(
    "/agent/chat",
    data as unknown as Record<string, unknown>,
  );
}

/** Phase 6: 获取当前 LLM provider 信息 */
export function getLlmProviderInfo() {
  return get<{ provider: string; model: string }>("/agent/llm-provider");
}

/** Phase 9 P1.4: 重新生成推荐问题 */
export function regenerateFollowUp(question: string, answer: string) {
  return post<{ follow_up_questions: string[] }>(
    "/agent/follow-up",
    undefined,
    {
      params: { question, answer },
    },
  );
}

/** Phase 6: 获取云端 API 成本统计 */
export function getCostStats() {
  return get<{
    daily: { used: number; limit: number };
    monthly: { used: number; limit: number };
  }>("/agent/cost");
}

/**
 * Phase P0: Agent SSE 流式对话（POST body）。
 *
 * 由于 EventSource 不支持 POST / 自定义 Header，前端使用 fetch + ReadableStream 消费。
 * 认证 token 仍通过 query param 或 Cookie 传递（SSE 无法设置 Authorization header）。
 */
export function buildAgentStreamPayload(
  kbId: number,
  question: string,
  conversationId?: number,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    kb_id: kbId,
    question,
  };
  if (conversationId !== undefined) {
    payload.conversation_id = conversationId;
  }
  return payload;
}

/**
 * @deprecated 旧版 GET 流式 URL，仅作兼容参考。P0 后请使用 buildAgentStreamPayload + POST。
 */
export function buildAgentStreamUrl(
  kbId: number,
  question: string,
  conversationId?: number,
  accessToken?: string,
): string {
  const params = new URLSearchParams({
    kb_id: String(kbId),
    question: encodeURIComponent(question),
  });
  if (conversationId !== undefined) {
    params.set("conversation_id", String(conversationId));
  }
  if (accessToken) {
    params.set("access_token", accessToken);
  }
  return `/api/v1/agent/chat-stream?${params.toString()}`;
}
