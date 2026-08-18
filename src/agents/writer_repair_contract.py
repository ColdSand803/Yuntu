"""Writer repair result contract and diagnostics helpers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.agents.generation_issues import GenerationIssue
from src.agents.schema import PlanOutput


class RepairSanitizerAction(BaseModel):
    action: str
    target: str
    reason: str
    issue_reason: str = ""
    pattern_reason: str = ""


class RepairFailureDetail(BaseModel):
    plan_index: int = 0
    reason: str
    issue_reasons: list[str] = Field(default_factory=list)
    route_outside_names: list[str] = Field(default_factory=list)
    route_violation_reasons: list[str] = Field(default_factory=list)
    allowed_route_names: list[str] = Field(default_factory=list)
    contextual_names: list[str] = Field(default_factory=list)
    snippets: list[str] = Field(default_factory=list)
    unsupported_fact_patterns: list[str] = Field(default_factory=list)


class RepairPlanResult(BaseModel):
    plan: PlanOutput | None = None
    failure_detail: RepairFailureDetail | None = None
    sanitizer_actions: list[Any] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)


REPAIR_HARD_CONSTRAINTS = (
    "硬约束：只输出 plan_name 与 plan_text；used_place_names、day_place_names、"
    "used_place_ids 由系统按锁定路线确定性回填，不要输出结构字段；"
    "不得新增、删除、替换 POI；不得跨天引用 POI；"
    "plan_name 不得包含任何未锁定的地点、县域、河流、山名、景区名或片区名；"
    "plan_text 必须按 Day 输出，每个 Day 标题必须原样列出该日锁定地点，"
    "例如“Day 1｜地点A → 地点B”；每个锁定地点名称在所属 Day 标题或正文"
    "中至少出现一次，不能用简称、代词或泛称替代；正文首次出现的游览顺序"
    "必须与锁定路线一致；"
    "正文中出现的地点、河流、山、公园、街区、景区等专名必须来自锁定路线，"
    "不要写任何未出现在锁定路线里的城市著名地标，也不要把它们作为"
    "方位、远眺、背景、顺路、附近、风景描述、县域概括或路线概括；"
    "不要使用县域/河流/片区来概括当天路线，只能说“这一带”“当天区域”"
    "这类不含专名的泛化表达；"
    "行程组合蓝图中的 meal_slot 是硬约束，meal_slot=lunch 必须写成午餐/中午吃饭节点，"
    "meal_slot=dinner 必须写成晚餐节点，不能把餐饮点写成普通景点或 citywalk 活动；"
    "咖啡店、面包店、甜品店只能写成咖啡/休息/简单补给/轻食节点，"
    "除非候选证据明确支持正餐，否则不要写成午餐或晚餐；"
    "只有通勤 style=walkable 时，才允许写“步行可达/走几步/很近”；"
    "style=nearby 只能写“顺路/附近转场”，不要写步行；"
    "style=normal_transfer 必须写成“转场”或“通勤参考”，不要写“打车或坐车”；"
    "style=long_transfer/remote_transfer 必须同时写交通方式、分钟或预留时间，"
    "并明确提示“这段稍远/路程较远”，不能只写分钟；"
    "公共交通正文只能逐字复制行程组合蓝图中的 deterministic_transit_transition；"
    "详细线路、站点、上下车、方向和换乘链只存在结构化结果中，正文禁止输出；"
    "禁止复制 deterministic_transit_summary 或根据 raw steps 解释路线；"
    "证据写的是“从 A 看/拍 B”“A 视角/机位里的 B”时，只能把 A 写成实际停留点，"
    "不能把 B 改写成游览、拍照或打卡承载点；"
    "可以写慢慢逛、顺路转场、坐下歇歇、茶歇、轻松收尾等"
    "不承诺外部事实的软叙事；但不要写感受氛围、老城氛围、随手拍都有大片感、"
    "拍照记录一下、拍照留念、根据自己状态灵活加减、节奏可以自己说了算、"
    "候选证据没有明确支持的亮灯、夜景更好看、"
    "最佳拍摄时间、最佳机位、必打卡、很出片等文旅套话；"
    "禁止“据说/听说/网传/亲测/博主推荐/作者推荐/本地人常去/当地人推荐”等来源口吻；"
    "除锁定地点原名外，正文只使用常用简体字，不要输出生僻字、异体字或 Unicode 扩展汉字；"
    "不得补充候选证据没有的菜品、口味、价格、营业时间、历史背景、"
    "最佳时间、预约/无需预约建议、购票/票务建议或来源口吻。"
    "低证据地点只能写成顺路停留、午餐节点、简单休息、轻量收尾等安全泛化表达。"
    "必须删除 issues 中 snippet 指向的原文片段；如果 issue 指向价格、门票、"
    "本地人常去、当地人常去、博主很喜欢、作者很喜欢、招牌菜、具体菜名、"
    "口味评价、营业时间、预约/无需预约、购票、售票员或生僻字，不能换一种说法保留，"
    "只能删除或降级成不含新事实且使用常用汉字的中性节奏表达。"
)


def dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def issue_reasons(issues: list[GenerationIssue]) -> list[str]:
    return dedupe_strings([issue.reason for issue in issues])


def issue_snippets(issues: list[GenerationIssue]) -> list[str]:
    return dedupe_strings([issue.snippet for issue in issues if issue.snippet])


def unsupported_fact_patterns(issues: list[GenerationIssue]) -> list[str]:
    return dedupe_strings([
        str(issue.metadata.get("pattern_reason") or "")
        for issue in issues
        if issue.reason == "unsupported_fact_expansion"
        and isinstance(issue.metadata, dict)
    ])


def build_repair_failure_detail(
    *,
    reason: str,
    plan_index: int,
    issues: list[GenerationIssue],
    route_outside_names: list[str] | None = None,
    route_violation_reasons: list[str] | None = None,
    allowed_route_names: list[str] | None = None,
    contextual_route_names: list[str] | None = None,
) -> RepairFailureDetail:
    return RepairFailureDetail(
        plan_index=plan_index,
        reason=reason,
        issue_reasons=issue_reasons(issues),
        route_outside_names=dedupe_strings(route_outside_names or []),
        route_violation_reasons=dedupe_strings(route_violation_reasons or []),
        allowed_route_names=dedupe_strings(allowed_route_names or []),
        contextual_names=dedupe_strings(contextual_route_names or []),
        snippets=issue_snippets(issues),
        unsupported_fact_patterns=unsupported_fact_patterns(issues),
    )


def build_repair_forbidden_payload(
    *,
    locked_names: list[str],
    contextual_names: list[str],
    disallowed_candidate_names: list[str],
    issues: list[GenerationIssue],
) -> dict:
    return {
        "locked_route_names": locked_names,
        "contextual_names": sorted(contextual_names),
        "disallowed_candidate_names": disallowed_candidate_names,
        "issue_snippets_must_disappear": issue_snippets(issues),
        "unsupported_fact_patterns": unsupported_fact_patterns(issues),
    }
