"""Delete-only sanitizer for Writer repair output."""

from __future__ import annotations

import re

from src.agents.generation_issues import GenerationIssue
from src.agents.route_planning import _is_day_heading_line, _parse_day_heading_number
from src.agents.text_quality import BANNED_DATABASE_PHRASES
from src.agents.writer_repair_contract import RepairSanitizerAction

DAY_HEADING_RE = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*"
    r"(?:Day\s*(\d+)|第\s*(\d+|[一二三四五六七八九十]+)\s*(?:天|日))"
    r"([^\n]*?)(?:\*\*)?\s*$"
)
SENTENCE_SEGMENT_RE = re.compile(r"([^。！？；;\n]*[。！？；;\n]?)")
RISKY_CONTRACT_SEGMENT_RE = re.compile(
    r"轻松时光|安静的单人时光|自在的单人时光|完美的句号|能量场|"
    r"边走边吃|慢慢闲逛|顺路看看|打卡点|氛围|氛围感拉满|经典拍照机位|"
    r"知名景点|值得|感受一下|到此一游|风貌区|挺有意思|暖宝宝|小游戏|服务细节|"
    r"随手拍都有大片感|大片感|拍照记录|拍照留念|"
    r"核心商业区|随意转转|核心点串起来|节奏不紧|随走随停|"
    r"视野开阔|随意漫步|夜景收尾|路线卖点|人气旺|吃法建议|"
    r"需要预约|无需预约|不用预约|不需要预约|提前预约|预约|"
    r"门票|票价|购票|买票|售票|检票|购买[^。；\n]{0,8}票|"
    r"建议(?:打车|坐车|乘车|乘坐|步行|地铁|公交|自驾|开车)|"
    r"打车前往|坐车前往|乘车前往|步行几分钟就能到|步行几分钟可到|"
    r"打车或坐车|打车或乘车|灵活调整|灵活加减|根据当天状态安排|"
    r"根据自己状态|节奏可以自己说了算|"
    r"可自行权衡|自行权衡|到场再看|到现场再看|根据自己兴趣选择|"
    r"可以根据(?:自己|个人)?兴趣选择"
)


def _remove_banned_database_phrases(
    text: str,
    *,
    issues: list[GenerationIssue],
) -> tuple[str, list[RepairSanitizerAction]]:
    actions: list[RepairSanitizerAction] = []
    if not text:
        return text, actions
    should_clean = any(
        issue.reason == "database_tone"
        or issue.reason == "unsupported_fact_expansion"
        or (
            issue.reason == "unsupported_fact_expansion"
            and isinstance(issue.metadata, dict)
            and issue.metadata.get("pattern_reason") == "source_voice_claim"
        )
        for issue in issues
    )
    if not should_clean:
        return text, actions
    sanitized = text
    for phrase in BANNED_DATABASE_PHRASES:
        if phrase not in sanitized:
            continue
        sanitized = sanitized.replace(phrase, "")
        actions.append(RepairSanitizerAction(
            action="remove_database_phrase",
            target=phrase,
            reason="database_tone",
            issue_reason="database_tone",
        ))
    return sanitized, actions


def _remove_known_snippets(
    text: str,
    *,
    issues: list[GenerationIssue],
) -> tuple[str, list[RepairSanitizerAction]]:
    actions: list[RepairSanitizerAction] = []
    sanitized = text
    for issue in issues:
        if issue.publish_action == "RECORD_ONLY" or issue.category == "WARN":
            continue
        if issue.reason == "long_transfer_missing_or_misleading":
            continue
        snippet = issue.snippet.strip()
        if not snippet or snippet not in sanitized:
            continue
        sanitized = sanitized.replace(snippet, "")
        pattern_reason = ""
        if isinstance(issue.metadata, dict):
            pattern_reason = str(issue.metadata.get("pattern_reason") or "")
        actions.append(RepairSanitizerAction(
            action="remove_snippet",
            target=snippet[:120],
            reason="issue_snippet",
            issue_reason=issue.reason,
            pattern_reason=pattern_reason,
        ))
    return sanitized, actions


def _remove_disallowed_name_segments(
    text: str,
    *,
    disallowed_candidate_names: list[str],
    allowed_candidate_names: list[str] | None = None,
) -> tuple[str, list[RepairSanitizerAction]]:
    actions: list[RepairSanitizerAction] = []
    if not text or not disallowed_candidate_names:
        return text, actions
    names = sorted(set(disallowed_candidate_names), key=lambda value: (-len(value), value))
    allowed_names = sorted(
        set(allowed_candidate_names or []),
        key=lambda value: (-len(value), value),
    )
    pieces = re.split(r"([^。！？；;\n]*[。！？；;\n]?)", text)
    sanitized_parts: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        searchable_piece = piece
        for allowed_name in allowed_names:
            if allowed_name and allowed_name in searchable_piece:
                searchable_piece = searchable_piece.replace(
                    allowed_name,
                    " " * len(allowed_name),
                )
        hits = [
            name for name in names
            if name and name in searchable_piece
        ]
        if hits and not re.search(
            r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*"
            r"(?:Day\s*\d+|第\s*\d+\s*天)",
            piece,
        ):
            actions.append(RepairSanitizerAction(
                action="remove_route_outside_segment",
                target=piece.strip()[:160],
                reason="route_outside_candidate",
            ))
            continue
        sanitized_parts.append(piece)
    return "".join(sanitized_parts), actions


def _remove_cross_day_segments(
    text: str,
    *,
    locked_day_names: list[list[str]] | None,
) -> tuple[str, list[RepairSanitizerAction]]:
    actions: list[RepairSanitizerAction] = []
    if not text or not locked_day_names:
        return text, actions

    all_locked_names = sorted(
        {name for day_names in locked_day_names for name in day_names if name},
        key=lambda value: (-len(value), value),
    )
    if not all_locked_names:
        return text, actions

    valid_matches: list[tuple[re.Match[str], int]] = []
    for match in DAY_HEADING_RE.finditer(text):
        day_number = _parse_day_heading_number(match.group(1) or match.group(2))
        remainder = match.group(3) or ""
        if day_number is None or not _is_day_heading_line(match.group(0), remainder):
            continue
        valid_matches.append((match, day_number))
    if not valid_matches:
        return text, actions

    sanitized_parts: list[str] = [text[:valid_matches[0][0].start()]]
    for index, (match, day_number) in enumerate(valid_matches):
        section_end = (
            valid_matches[index + 1][0].start()
            if index + 1 < len(valid_matches)
            else len(text)
        )
        heading = text[match.start():match.end()]
        body = text[match.end():section_end]
        if day_number < 1 or day_number > len(locked_day_names):
            sanitized_parts.append(text[match.start():section_end])
            continue

        current_day_names = {name for name in locked_day_names[day_number - 1] if name}
        cross_day_forbidden = [
            name for name in all_locked_names if name not in current_day_names
        ]
        if not cross_day_forbidden:
            sanitized_parts.append(text[match.start():section_end])
            continue

        sanitized_body_parts: list[str] = []
        for piece in SENTENCE_SEGMENT_RE.split(body):
            if not piece:
                continue
            hits = [name for name in cross_day_forbidden if name in piece]
            if hits:
                actions.append(RepairSanitizerAction(
                    action="remove_cross_day_segment",
                    target=piece.strip()[:160],
                    reason="cross_day_locked_poi",
                ))
                continue
            sanitized_body_parts.append(piece)
        sanitized_parts.append(heading + "".join(sanitized_body_parts))

    return "".join(sanitized_parts), actions


def _remove_risky_contract_segments(
    text: str,
    *,
    issues: list[GenerationIssue],
) -> tuple[str, list[RepairSanitizerAction]]:
    actions: list[RepairSanitizerAction] = []
    if not text:
        return text, actions
    should_clean = any(
        issue.reason in {
            "unsupported_fact_expansion",
            "food_place_written_as_attraction",
            "long_transfer_missing_or_misleading",
        }
        and issue.publish_action != "RECORD_ONLY"
        for issue in issues
    )
    if not should_clean:
        return text, actions
    sanitized_parts: list[str] = []
    for piece in SENTENCE_SEGMENT_RE.split(text):
        if not piece:
            continue
        if RISKY_CONTRACT_SEGMENT_RE.search(piece):
            actions.append(RepairSanitizerAction(
                action="remove_risky_contract_segment",
                target=piece.strip()[:160],
                reason="v074_contract_risky_expression",
            ))
            continue
        sanitized_parts.append(piece)
    return "".join(sanitized_parts), actions


def _cleanup_sanitized_text(text: str) -> str:
    cleaned = re.sub(r"[ \t]{2,}", " ", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"([，、；;])\s*([。！？])", r"\2", cleaned)
    cleaned = re.sub(r"[，、；;]\s*(\n|$)", r"\1", cleaned)
    return cleaned.strip()


def sanitize_repair_text(
    text: str,
    *,
    issues: list[GenerationIssue],
    disallowed_candidate_names: list[str],
    allowed_candidate_names: list[str] | None = None,
    locked_day_names: list[list[str]] | None = None,
) -> tuple[str, list[RepairSanitizerAction]]:
    """Remove only known risky snippets; never invent replacement facts."""
    sanitized, database_actions = _remove_banned_database_phrases(
        text,
        issues=issues,
    )
    sanitized, snippet_actions = _remove_known_snippets(sanitized, issues=issues)
    sanitized, name_actions = _remove_disallowed_name_segments(
        sanitized,
        disallowed_candidate_names=disallowed_candidate_names,
        allowed_candidate_names=allowed_candidate_names,
    )
    sanitized, cross_day_actions = _remove_cross_day_segments(
        sanitized,
        locked_day_names=locked_day_names,
    )
    sanitized, risky_actions = _remove_risky_contract_segments(
        sanitized,
        issues=issues,
    )
    return (
        _cleanup_sanitized_text(sanitized),
        [
            *database_actions,
            *snippet_actions,
            *name_actions,
            *cross_day_actions,
            *risky_actions,
        ],
    )
