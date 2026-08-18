/**
 * 安全 returnTo 路径校验与净化：
 * - 只接受以 `/` 开头的同源相对路径
 * - 拒绝 `//`、协议 URL、反斜杠和外部域名
 * - 防止 Open Redirect 漏洞
 * - 无效值或 /login 回退到 `/`
 */
export function sanitizeReturnTo(
  raw: string | null | undefined,
  fallback: string = "/",
): string {
  const safeFallback =
    fallback && fallback.startsWith("/") && !fallback.startsWith("//")
      ? fallback
      : "/";

  if (!raw || typeof raw !== "string") return safeFallback;
  const trimmed = raw.trim();

  // 必须以 / 开头，且不能以 // 或 /\ 开头
  if (
    !trimmed.startsWith("/") ||
    trimmed.startsWith("//") ||
    trimmed.startsWith("/\\")
  ) {
    return safeFallback;
  }

  // 不能包含协议 scheme (如 http:, https:, javascript:)
  if (trimmed.includes(":") || trimmed.includes("\\")) {
    return safeFallback;
  }

  try {
    // 借用 URL 解析器验证相对路径
    const parsed = new URL(trimmed, "http://localhost");
    // 确保 pathname 还是以 / 开头，且非 /login 重定向循环
    if (parsed.pathname === "/login") {
      return safeFallback;
    }
    return parsed.pathname + parsed.search + parsed.hash;
  } catch {
    return safeFallback;
  }
}
