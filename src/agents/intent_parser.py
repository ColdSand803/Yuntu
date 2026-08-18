"""Intent Parser: natural language → TripRequest JSON."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.agents.llm import chat, llm_call_context
from src.agents.schema import TripRequest

logger = logging.getLogger(__name__)

KNOWN_DESTINATION_CITIES = (
    "重庆",
    "成都",
    "福州",
    "杭州",
    "长沙",
    "广州",
    "深圳",
    "上海",
    "北京",
    "南京",
    "武汉",
    "西安",
    "厦门",
    "青岛",
    "苏州",
)

SYSTEM_PROMPT = """你是云途旅行规划服务 的意图解析器。
用户会用自然语言描述旅行需求，你需要提取结构化字段。

严格输出 JSON，不要输出任何其他内容：
{
  "from_city": "出发城市（未提及则空字符串）",
  "to_city": "目的地城市（未提及则默认重庆）",
  "start_date": "出行开始日期，明确可解析时用 YYYY-MM-DD，否则 null",
  "end_date": "出行结束日期，明确可解析时用 YYYY-MM-DD，否则 null",
  "days": 天数（整数，未提及则默认3）,
  "people_count": 人数（整数，未提及则默认1）,
  "preferences": ["用户想要的偏好，如 美食、citywalk、慢旅行、拍照"],
  "avoid": ["用户不想要的，如 人多、打卡式旅游"],
  "notes": "其他补充说明（原文摘录）"
}

规则：
- 用户说的"喜欢/想/偏好"类内容 → preferences
- 用户说的"不想/讨厌/避开/不要"类内容 → avoid
- 只有用户明确给出可解析日期时才填写 start_date / end_date；不确定则填 null
- 如果用户没提目的地，默认 "重庆"
- 天数只取整数，"三天两夜" → 3，"五日游" → 5"""


INTENT_SCHEMA_COERCION_DEFAULT_METADATA = {
    "intent_schema_coercion_used": False,
    "intent_schema_coercion_fields": [],
    "intent_schema_coercion_reason": "",
}


def explicit_destination_from_text(user_text: str) -> str | None:
    """Return a deterministic destination city when the user states one."""
    if not user_text:
        return None

    city_pattern = "|".join(re.escape(city) for city in KNOWN_DESTINATION_CITIES)
    destination_match = re.search(
        rf"(?:去|到|前往|目的地[:：]?)(?P<city>{city_pattern})",
        user_text,
    )
    if destination_match:
        return destination_match.group("city")

    departure_match = re.search(
        rf"(?P<city>{city_pattern})(?:出发|出发去|出发到)",
        user_text,
    )
    departure_city = (
        departure_match.group("city")
        if departure_match
        else None
    )
    mentioned = [
        city for city in KNOWN_DESTINATION_CITIES
        if city in user_text and city != departure_city
    ]
    if len(mentioned) == 1:
        return mentioned[0]

    prefix_match = re.match(rf"\s*(?P<city>{city_pattern})", user_text)
    if prefix_match:
        return prefix_match.group("city")

    return None


def _safe_stringify_notes(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    text = text.strip()
    if not text or len(text) > 500:
        return ""
    return text


def _coerce_low_risk_intent_fields(
    data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Coerce only low-risk Intent Parser fields before TripRequest validation."""
    coerced = dict(data)
    metadata = dict(INTENT_SCHEMA_COERCION_DEFAULT_METADATA)
    if "notes" not in coerced or isinstance(coerced["notes"], str):
        return coerced, metadata

    notes = coerced["notes"]
    reason = ""
    if notes is None:
        coerced["notes"] = ""
        reason = "notes_null_to_empty"
    elif isinstance(notes, list) and all(isinstance(item, str) for item in notes):
        coerced["notes"] = "；".join(notes)
        reason = "notes_list_strings_joined"
    else:
        coerced["notes"] = _safe_stringify_notes(notes)
        reason = (
            "notes_complex_stringified"
            if coerced["notes"]
            else "notes_complex_dropped"
        )

    metadata.update({
        "intent_schema_coercion_used": True,
        "intent_schema_coercion_fields": ["notes"],
        "intent_schema_coercion_reason": reason,
    })
    return coerced, metadata


async def parse_intent_with_metadata(
    user_text: str,
) -> tuple[TripRequest, dict[str, Any]]:
    """Parse free-form text into a TripRequest plus parser metadata."""
    with llm_call_context(
        call_reason="intent_parse",
        max_tokens_request=800,
        relay_request_timeout_seconds=30,
        relay_hedge_delay_seconds=1,
    ):
        raw = await chat(
            system=SYSTEM_PROMPT,
            user=user_text,
            role="intent",
            temperature=0.1,
            json_mode=True,
        )
    logger.info("Intent Parser raw output: %s", raw[:300])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Intent parse JSON failed, using defaults")
        data = {}

    data, metadata = _coerce_low_risk_intent_fields(data)
    data.pop("must_include", None)
    trip_request = TripRequest(**{
        k: v for k, v in data.items()
        if k in TripRequest.model_fields
    })
    explicit_destination = explicit_destination_from_text(user_text)
    if explicit_destination and trip_request.to_city != explicit_destination:
        logger.info(
            "Intent Parser destination override: %s -> %s",
            trip_request.to_city,
            explicit_destination,
        )
        trip_request.to_city = explicit_destination
    elif trip_request.to_city == "重庆" and "重庆" not in user_text:
        logger.info(
            "Intent Parser cleared implicit default destination for clarification"
        )
        trip_request.to_city = ""
    return trip_request, metadata


async def parse_intent(user_text: str) -> TripRequest:
    """Parse free-form text into a TripRequest."""
    trip_request, _metadata = await parse_intent_with_metadata(user_text)
    return trip_request
