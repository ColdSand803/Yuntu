/**
 * 后端 error_code → Web 表单场景的用户文案。
 *
 * 后端的部分 error_message 是为自然语言输入（对话/message 模式）写的，
 * 例如"建议您换个说法再试试"——但 Web 端用户是填结构化表单，没有"说法"可换。
 * 这里按 code 改写成适合表单场景的话；对"城市不支持"等具体可操作的错误，
 * 仍保留后端原文（更有信息量）。
 */

// 这些 code 的后端原文具体且可操作，直接透传后端 message
const PASSTHROUGH_CODES = new Set([
  "CITY_NOT_SUPPORTED",
  "VALIDATION_ERROR",
  "RATE_LIMITED",
]);

// 按 code 映射的表单友好文案
const WEB_MESSAGES: Record<string, string> = {
  GENERATION_FAILED: "这次没能生成成功，请点「重新规划」再试一次",
  GENERATION_TIMEOUT: "生成时间较长，请稍后重试",
  NO_CANDIDATES: "暂时没找到合适的地点，换个目的地或调整偏好再试试",
  NO_USABLE_ROUTE: "这次没能排出合理路线，调整天数或偏好后重试",
  SERVICE_UNAVAILABLE: "服务暂时不可用，请稍后再试",
};

/**
 * 把后端错误转成 Web 端展示文案。
 * @param code 后端 error_code
 * @param backendMessage 后端 error_message（兜底用）
 */
export function webErrorMessage(
  code: string | null | undefined,
  backendMessage?: string | null,
): string {
  if (code && PASSTHROUGH_CODES.has(code) && backendMessage) {
    return backendMessage;
  }
  if (code && WEB_MESSAGES[code]) {
    return WEB_MESSAGES[code];
  }
  // 未知 code：用通用兜底，不透传可能不适配表单场景的后端原文
  return "这次没能生成成功，请点「重新规划」再试一次";
}
