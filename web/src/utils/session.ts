const KEY = "yuntu_conversation_id";

export function getConversationId(): string {
  let id = sessionStorage.getItem(KEY);
  if (!id) {
    id = `web:${crypto.randomUUID()}`;
    sessionStorage.setItem(KEY, id);
  }
  return id;
}
