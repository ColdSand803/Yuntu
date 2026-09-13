"""Final Writer: render locked travel plans from authorized evidence."""

from __future__ import annotations

from src.agents.route_feasibility import access_summary
from src.agents.arrival_copy import arrival_activity_copy

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from src.agents.blueprint_integrity import check_plan_blueprint_integrity
from src.agents.activity_completion import completion_sentence_for_contract
from src.agents.composition_blueprint import build_base_composition_blueprints
from src.agents.evidence_strength import (
    StructuredEvidencePayload,
    build_structured_evidence_payload,
    missing_action_contract_keys,
    render_place_evidence_line,
    render_structured_evidence_prompt,
)
from src.agents.food_resolver import FoodAttachmentAuthorization

from src.agents.fact_expression_taxonomy import (
    has_hard_fact_marker,
    unsupported_fact_pattern_matches,
    untrusted_transport_claim_matches,
)
from src.agents.generation_issues import GenerationIssue
from src.agents.keyed_fragment_repair import (
    KEYED_FRAGMENT_REPAIR_TIMEOUT_SECONDS,
    build_keyed_fragment_targets,
    call_keyed_fragment_repair,
    fallback_ratio_exceeded,
)
from src.agents.llm import (
    chat,
    current_llm_call_context,
    last_chat_metadata,
    llm_call_context,
)
from src.agents.speculative_archive import (
    SpeculativeArchiveRecord,
    append_speculative_archive,
)
from src.agents.speculative_writer import (
    AdoptedGenerator,
    DSStandbyTask,
    DSTerminalState,
    OpusAdjudicationState,
    OpusDraftResult,
    SpeculativeExecutionResult,
    SpeculativeTelemetry,
    SpeculativeWriterExecutor,
)
from src.agents.writer_relay_router import (
    ATTEMPT_TIMEOUT_SECONDS,
    STREAM_ATTEMPT_TIMEOUT_SECONDS,
    WORKFLOW_WALL_SECONDS,
)
from src.agents.yuntu_review import ORDINARY_REVIEW_REQUEST_TIMEOUT_SECONDS
from src.agents.poi_alias import build_route_name_policy
from src.agents.pretrip_advice import (
    PreTripAdvicePayload,
    render_pretrip_advice_writer_prompt,
    sanitize_writer_advice,
)
from src.agents.route_planning import (
    _is_day_heading_line,
    _parse_day_heading_number,
    mask_authorized_commute_spans,
    route_plan_violations,
)
from src.agents.schema import (
    AccommodationSuggestion,
    BudgetResult,
    CandidateGroup,
    CompositionBlueprint,
    PackingChecklistGroup,
    PlanOutput,
    PoiNarrativeFragment,
    PoiIdentityResult,
    RetrievalResult,
    RoutePlan,
    TransportSuggestion,
    TravelTip,
    TripRequest,
)
from src.agents.text_quality import (
    BANNED_DATABASE_PHRASES,
    PLACEHOLDER_PHRASES,
    extract_claimed_names,
)
from src.agents.weather_advisory import (
    WeatherAdvisoryPayload,
    apply_weather_advisory_to_text,
    render_weather_prompt,
)
from src.agents.writer_repair_contract import (
    REPAIR_HARD_CONSTRAINTS,
    RepairFailureDetail,
    RepairPlanResult,
    RepairSanitizerAction,
    build_repair_failure_detail,
    build_repair_forbidden_payload,
)
from src.agents.writer_repair_sanitizer import sanitize_repair_text
from src.config import get_settings

# Compatibility export for older deterministic regression scripts. Runtime
# fallback call sites below intentionally use build_base_composition_blueprints.
build_composition_blueprints = build_base_composition_blueprints

logger = logging.getLogger(__name__)

FoodAttachmentAuthMap = dict[
    tuple[int, int, int, str, int],
    FoodAttachmentAuthorization,
]


@dataclass
class PlanWriteResult:
    zero_index: int
    plan: PlanOutput | None = None
    failure_reason: str = ""
    latency_ms: int = 0
    parse_error_type: str = ""
    raw_length: int = 0
    json_extract_failed: bool = False
    single_plan_unwrapped_plans_array: bool = False
    writer_plan_retry_used: bool = False
    writer_plan_retry_count: int = 0
    writer_plan_attempt_count: int = 0
    writer_plan_attempt_parse_error_types: list[str] = field(default_factory=list)
    writer_plan_attempt_raw_lengths: list[int] = field(default_factory=list)
    writer_plan_attempt_json_extract_failed: list[bool] = field(default_factory=list)
    writer_plan_retry_latency_ms: int = 0
    parse_failure_diagnostics: dict[str, Any] = field(default_factory=dict)
    sibling_unique_poi_violations: list[str] = field(default_factory=list)
    sanitizer_actions: list[Any] = field(default_factory=list)
    keyed_fragment_count: int = 0
    keyed_fragment_fallback_keys: list[tuple[int, int, int]] = field(default_factory=list)
    keyed_fragment_ignored_keys: list[tuple[int, int, int]] = field(default_factory=list)
    keyed_fragment_invalid_details: list[dict[str, Any]] = field(default_factory=list)
    keyed_fragment_repair_attempted: bool = False
    keyed_fragment_repair_target_count: int = 0
    keyed_fragment_repair_applied_count: int = 0
    keyed_fragment_repair_remaining_count: int = 0
    keyed_fragment_repair_latency_ms: int = 0
    keyed_fragment_repair_failure_reason: str = ""
    keyed_day_opening_count: int = 0
    keyed_day_opening_dropped: list[dict[str, Any]] = field(default_factory=list)
    pretrip_advice_metrics: dict[str, Any] = field(default_factory=dict)
    generator: str = "opus"
    adjudication_reason: str = ""
    opus_adjudication_state: str = ""
    ds_adjudication_state: str = ""
    ds_terminal_state: str = ""
    speculative_review_policy: str = ""
    speculative_alert_owner: str = ""
    speculative_enabled: bool = False
    writer_prompt_version: str = ""
    opus_first_token_ms: int | None = None
    opus_final_ms: int | None = None
    ds_final_ms: int | None = None
    adjudicated_at_ms: int | None = None
    probe_telemetry_enabled: bool = False
    probe_kill_count: int = 0
    probe_kill_endpoints: list[str] = field(default_factory=list)
    probe_kill_kind: str | None = None
    probe_partial_output_before_kill: bool | None = None
    ds_attempted: bool = False
    ds_completed: bool = False
    ds_structural_passed: bool = False
    ds_adopted: bool = False
    ds_latency_ms: int = 0
    ds_token_in: int = 0
    ds_token_out: int = 0
    archive_write_succeeded: bool | None = None


@dataclass
class KeyedPlanAssemblyResult:
    plan_text: str = ""
    fragments: list[PoiNarrativeFragment] = field(default_factory=list)
    fallback_keys: list[tuple[int, int, int]] = field(default_factory=list)
    ignored_keys: list[tuple[int, int, int]] = field(default_factory=list)
    invalid_details: list[dict[str, Any]] = field(default_factory=list)
    sanitizer_actions: list[Any] = field(default_factory=list)
    failure_reason: str = ""
    day_opening_count: int = 0
    day_opening_dropped: list[dict[str, Any]] = field(default_factory=list)


SYSTEM_PROMPT = """你是云途旅行规划服务 的攻略撰写员。
根据用户需求、锁定行程输入和 Structured Evidence Payload，生成旅行攻略。

严格输出合法 JSON，不要输出任何其他内容：
- 只能输出一个 JSON object，必须以 { 开头、以 } 结尾
- 不要 Markdown、不要解释文字、不要代码围栏、不要前后缀说明
- 字符串必须使用双引号，不要尾随逗号，不要输出注释
{
  "plans": [
    {
      "plan_name": "方案名称（如：悠闲慢旅行路线）",
      "plan_text": "完整的攻略文本，按天组织，包含地点、理由、注意事项"
    },
    {
      "plan_name": "方案名称",
      "plan_text": "..."
    }
  ]
}

规则：
- 必须生成用户指令要求数量的方案
- Final Writer 是 evidence-bound locked itinerary prose renderer，只把锁定行程输入写成攻略；不得决定或改写地点身份、路线顺序、Day 分组、餐饮角色、通勤、预算或外部事实
- 未提供锁定路线时，每套方案至少包含 5 个地点
- 只使用提供的候选地点，不要编造不在列表中的地点
- 只使用 Structured Evidence Payload 中授权的 direct_facts、weak_experience、risk_only_warnings；禁止补充任何未授权外部事实（包括但不限于：建筑风格、历史背景、具体展品、菜品名称、营业时间、住宿条件）
- 如果提供 Weather Advisory Payload，只能把 authorized_reminders 写成 Day 级独立“天气提醒：...”行；禁止解释 raw 天气、conditions、temperature、wind，禁止把天气写进 POI 理由、路线依据、标题、主题句、亮点或替代地点建议
- 允许自然的 Soft Experience Expression，但必须绑定 Structured Evidence Payload 的 weak_experience、锁定路线转场、地点类型或蓝图角色；不得自行发挥老城氛围、古风、拍照、打卡、特色、香/好吃/新鲜等未授权体验描述
- 禁止无证据的 Hard Fact Commitment，包括预约/无需预约、票务/价格/营业时间、排队/人流、历史年代/老字号、本地人/博主推荐、最佳/最热门/必打卡/很出片、招牌菜/具体口味
- 即使某个地点没有可陈述事实，也必须依据 place_type、蓝图角色和 authorized_actions 写一个无事实承诺的具体行动建议；可以安排怎么逛、怎么看、怎么取景或怎么休息，但不能把建议写成地点客观事实
- 证据写的是“从 A 看/拍 B”“A 视角/机位里的 B”时，只能把 A 写成实际停留点，不能改写成在 B 游览、拍照或打卡
- 不要写候选证据没有明确支持的亮灯、夜景更好看、最佳拍摄时间、最佳机位、必打卡、很出片等文旅套话
- 不要自行输出负面体验判断、体验包装或决策式建议，例如“没什么好拍的”“不太好拍”“轻松时光”“氛围感拉满”“感受氛围”“老城氛围”“随手拍都有大片感”“拍照记录一下”“拍照留念”“经典拍照机位”“知名景点”“值得停留看看”“根据自己状态灵活加减”“节奏可以自己说了算”“可以根据实际情况决定是否购票/买票/购买车票”“建议打车或坐车”“打车或坐车”“可自行权衡/到场再看”
- 除锁定地点原名外，正文只使用常用简体字，不要输出生僻字、异体字或 Unicode 扩展汉字
- 按天安排行程（Day 1 / Day 2 / ...）
- 餐厅作为早/午/晚餐节点自然融入，不要把餐厅扩写成景点活动。每天应包含至少 1-2 个非餐厅主活动（景点/公园/商圈等）
- 咖啡店、面包店、甜品店只能写成咖啡/休息/简单补给/轻食节点；除非候选证据明确支持正餐，否则不要写成午餐或晚餐
- 如果提供了”锁定路线”，必须逐日使用指定地点：不能跨天移动、不能增加、不能删除；每个 Day 正文必须覆盖该 Day 锁定地点，且首次出现的游览顺序必须与锁定路线一致
- Structured Evidence Payload 中 mandatory_mention_policy.mandatory_mention=true 的地点必须出现在对应 Day 标题和正文；authorized_actions 是该地点唯一可无证据使用的动作类型，可自然改写，但不能扩成菜品、口味、价格、开放时间、历史、展品、景观或其他外部事实
- 每个锁定地点在正文中必须回答“到这里具体做什么”：至少写一个可执行动作；只在 Day 标题、路线复述、通勤起终点或“先到这里再继续/拍照停留/周边看看/作为节点”一类空壳句中出现不算覆盖。有 direct_facts 或 weak_experience 时，应把动作和其中一个可写信息自然结合
- 锁定路线中的地点名称必须逐字原样使用，不能增加“的”、使用简称或做其他改写
- 锁定路线提供“行程组合蓝图”时，把蓝图当作写作参考，不要当成硬模板；可以吸收主题、餐食角色、节奏提示，但不要机械复述蓝图字段
- 行程组合蓝图中的 meal_slot 是硬约束：meal_slot=lunch 必须写成午餐/中午吃饭节点，meal_slot=dinner 必须写成晚餐节点，不能把餐饮点写成普通景点或 citywalk 活动
- 只有通勤 mode=walking 且 style=walkable 时，才允许写“步行可达/走几步/很近”；style=normal_transfer 只用“随后再到/接着去”等无交通方式、无分钟数的自然衔接；style=long_transfer/remote_transfer 才写交通方式与时间，其中 mode=transit 必须把 deterministic_transit_transition 独立成句逐字复制，mode=cycling 写骑行且禁止写驾车/打车；非 walking 不要写步行
- 禁止“据说/听说/网传/亲测/博主推荐/作者推荐/本地人常去/当地人推荐”等来源口吻
- 避免模板化开场，不要连续使用“今天主打/今天体验/继续探索”；餐食也不要写成“解决午餐/解决晚餐”，要像正常攻略一样自然带到吃饭安排
- 如果锁定路线少于用户请求天数，锁定路线的 Day 数就是该方案最终天数，禁止自行补充缺失 Day
- 锁定路线中的地点名称只能出现在所属 Day，禁止在其他天进行比较、回顾、预告或作为方位参照
- 避免数据库口吻，不要写“作者推荐”“当地美食推荐”“数据推荐”“可以解决午饭”“来源推荐”“根据数据”
- 语气亲切自然，像朋友推荐
- 只输出 plan_name 与 plan_text；used_place_names、day_place_names、used_place_ids 由系统按锁定路线确定性回填，不要输出结构字段"""


# writer_prompt_version: opus_v5
OPUS_WRITER_PROMPT_VERSION = "opus_v6"
SINGLE_PLAN_SYSTEM_PROMPT = """你是云途旅行规划服务 的单方案 POI 文案撰写员。
后端已经确定 Day、地点身份、顺序、通勤和每个 POI 的稳定 key；你只填写每个 key 的局部文案。

严格输出合法 JSON，不要输出任何其他内容：
- 只能输出一个 JSON object，必须以 { 开头、以 } 结尾
- 不要 Markdown、不要解释文字、不要代码围栏、不要前后缀说明
- 所有字段名和字符串值必须使用双引号，不要尾随逗号，不要输出注释
{
  "poi_fragments": [
    {"plan_index": 1, "day": 1, "place_id": 123, "text": "只描述这个 POI 的具体行动"}
  ],
  "day_openings": [
    {"plan_index": 1, "day": 1, "text": "一句当天的主题开场，60字以内，可按当天游览顺序点到当天路线里的地点名"}
  ],
  "summary": "80-120 字的全程总述，只写天数、区域、路线特征和主题节奏，不出现具体地点名",
  "packing_checklist": [
    {"category": "当季穿搭与防护", "items": ["带一把晴雨两用伞", "路线步行较多，准备已磨合的轻便运动鞋"]}
  ],
  "travel_tips": [
    {"title": "出发前复核开放时段", "content": "行程中的某场馆当前展示周二至周日开放。", "evidence_ref": "amap:123:opentime_week"}
  ]
}

规则：
- 输入给出的每个 (plan_index, day, place_id) 必须原样输出一次；不要新增或重复 key
- text 只写当前 key 对应 POI 的局部行动文案；可以提当天已经走过的地点（slot 的 arrival_from 或当天更早的站）作方位参照或到达衔接，但不要提当天还没走到的地点或其他天的地点；不要写 Day 标题、地点顺序、路线箭头、精确通勤或天气，最终文章由后端组装
- Final Writer 是 evidence-bound locked itinerary prose renderer，只把锁定行程输入写成攻略；不得决定或改写地点身份、路线顺序、Day 分组、餐饮角色、通勤、预算或外部事实
- 只使用当前方案锁定路线里的地点，不要编造不在当前方案中的地点
- 只使用 Structured Evidence Payload 中授权的 direct_facts、weak_experience、risk_only_warnings；禁止补充任何未授权外部事实（包括但不限于：建筑风格、历史背景、具体展品、菜品名称、营业时间、住宿条件）
- Weather、Day 标题、路线与通勤都由后端处理，fragment text 中禁止输出
- Soft Experience Expression 可以自然表达：动作建议可依据 authorized_actions、地点类型和蓝图角色改写；对实际景物、设施、观景条件的描述仍需 direct_facts 或 weak_experience 支持。类型可指导怎么逛，不能证明此处一定有石阶、窗位、长椅、电梯或江景。
- 禁止无证据的 Hard Fact Commitment，包括预约/无需预约、票务/价格/营业时间、排队/人流、历史年代/老字号、本地人/博主推荐、最佳/最热门/必打卡/很出片、招牌菜/具体口味
- 即使某个地点没有可陈述事实，也必须依据 place_type、蓝图角色和 authorized_actions 写一个无事实承诺的具体行动建议；可以安排怎么逛、怎么看、怎么取景或怎么休息，但不能把建议写成地点客观事实
- 证据写的是“从 A 看/拍 B”“A 视角/机位里的 B”时，只能把 A 写成实际停留点，不能改写成在 B 游览、拍照或打卡
- 不要写候选证据没有明确支持的亮灯、夜景更好看、最佳拍摄时间、最佳机位、必打卡、很出片等文旅套话
- 不要自行输出负面体验判断、体验包装或决策式建议，例如“没什么好拍的”“不太好拍”“轻松时光”“氛围感拉满”“感受氛围”“老城氛围”“随手拍都有大片感”“拍照记录一下”“拍照留念”“经典拍照机位”“知名景点”“值得停留看看”“根据自己状态灵活加减”“节奏可以自己说了算”“可以根据实际情况决定是否购票/买票/购买车票”“建议打车或坐车”“打车或坐车”“可自行权衡/到场再看”
- 除锁定地点原名外，正文只使用常用简体字，不要输出生僻字、异体字或 Unicode 扩展汉字
- 不要自行组织 Day 或完整攻略，只填写 keyed fragments
- 餐厅作为早/午/晚餐节点自然融入，不要把餐厅扩写成景点活动。每天应包含至少 1-2 个非餐厅主活动（景点/公园/商圈等）
- 咖啡店、面包店、甜品店只能写成咖啡/休息/简单补给/轻食节点；除非候选证据明确支持正餐，否则不要写成午餐或晚餐
- 不得改变 fragment key；地点覆盖与最终顺序由后端按锁定路线组装
- Structured Evidence Payload 中 mandatory_mention_policy.mandatory_mention=true 的地点必须出现在对应 Day 标题和正文；authorized_actions、地点类型和蓝图角色共同限定无事实承诺的行动建议，可自然改写，但不能扩成菜品、口味、价格、开放时间、历史、展品、景观或其他外部事实
- 每个锁定地点在正文中必须回答“到这里具体做什么”：至少写一个可执行动作；只在 Day 标题、路线复述、通勤起终点或“先到这里再继续/拍照停留/周边看看/作为节点”一类空壳句中出现不算覆盖。有 direct_facts 或 weak_experience 时，应把动作和其中一个可写信息自然结合
- 地点差异来自各自证据与安排；避免连续套用同一种开头，无需为普通动词设次数，也不要仅换同义词假装内容不同。
- 转场不是每站必写项。路线与交通已由后端展示，可直接开始写当前地点；需要衔接时使用不承诺方式、距离或时长的简短表达。
- text 中不要重复地点名称，地点名称由后端根据 place_id 确定性添加
- day_openings 每天一条：只写一句当天的主题或节奏开场，60 字以内，写在 Day 标题之后、第一个地点之前；不要写成两句或更长
- day_opening 的 text 中可以出现当天路线里的地点名做 Day 级串联，但必须按当天游览顺序、从当天第一站开始点名，不能只点靠后的站或打乱顺序；禁止其他天的地点名、交通方式、分钟数、价格、营业时间或其他可核验事实；可以从当天蓝图主题和地点类型归纳；不要以“Day”或“第X天”开头，可用“这一天/今天”等自然表述
- day_opening 缺失或不合规时后端会直接跳过，不影响正文，但提供自然开场能显著提升可读性，请认真填写
- 锁定路线提供“行程组合蓝图”时，把蓝图当作写作参考，不要当成硬模板；可以吸收主题、餐食角色、节奏提示，但不要机械复述蓝图字段
- 行程组合蓝图中的 meal_slot 是硬约束：meal_slot=lunch 必须写成午餐/中午吃饭节点，meal_slot=dinner 必须写成晚餐节点，不能把餐饮点写成普通景点或 citywalk 活动
- POI 间交通由后端展示，正文不重写交通方式、时长（包括中文模糊数字）、线路、站点、距离或换乘链，也不猜“走过来不远”。餐饮附件只可按专项规则复制已授权的步行时长。
- 禁止“据说/听说/网传/亲测/博主推荐/作者推荐/本地人常去/当地人推荐”等来源口吻
- 避免模板化开场，不要连续使用“今天主打/今天体验/继续探索”；餐食也不要写成“解决午餐/解决晚餐”，要像正常攻略一样自然带到吃饭安排
- 不要补充缺失 Day，不要在一个 fragment 中比较或预告其他地点；回看当天已走过的地点做自然衔接是允许的
- 避免数据库口吻，不要写“作者推荐”“当地美食推荐”“数据推荐”“可以解决午饭”“来源推荐”“根据数据”
- 语气亲切自然，像朋友推荐
- 只输出 poi_fragments、day_openings、summary，以及可选的 packing_checklist 和 travel_tips；不要输出 plan_name、plan_text、used_place_names、day_place_names 或 used_place_ids
- packing_checklist 只能使用 packing_signals，禁止 note_tip_evidence 与 Amap 开放事实；质量目标 3～4 类、每类 2～3 项
- travel_tips 没有最少条数；每条内部草稿必须且只能包含 title、content、evidence_ref，一条 tip 只引用一个授权 ref
- Amap/笔记开放事实不得写入 poi_fragments、day_openings、summary 或 packing_checklist

Food Stop 专项规则（仅当当前 slot 的 writing_hint 是含 evidence_tier 的 JSON object 时生效）：
- writing_hint 中的 food_name 是路线外的附近餐饮附件，只允许出现在当前 meal_stop 的 food span 内；不得写进 Day 标题、路线、plan_name、used_place_names 或 day_place_names
- full / structural tier 的完整餐饮附件句都必须由 writing_hint["span_marker"] 和 <!-- /food --> 包裹；从“午餐/晚餐/附近/步行”等餐饮附件句第一个字开始，到店名、评分、价格、授权证据等最后一个字结束，全部放在 marker 内，不得把“附近”“步行约N分钟”等前半句放在 marker 外
- 当前路线锚点自身的行动文案可以写在 marker 前；餐饮附件的完整格式必须是 <!-- food:plan{i}_day{d}_anchor{a}_slot{s}_food{f} -->{完整餐饮附件句}<!-- /food -->
- full tier：marker 内可写 food_name、amap_rating、amap_avg_price、步行约N分钟和 Food Stop Runtime Payload 中 authorization.direct_facts / authorization.weak_experience 的内容；不得扩展证据
- structural tier：marker 内只写时段、food_name、amap_rating、amap_avg_price、步行约N分钟；禁止体验描述、菜品推断或其他事实
- none tier：只写锚点 POI 的行动文案，不写餐饮附件；后端会拼接 none_tier_text 与 span_marker / <!-- /food -->。
- 所有 tier 禁止来源口吻，包括“笔记里提到”“博主推荐”“据说”“亲测”“作者推荐”“当地推荐”“根据数据”
- 所有 tier 禁止自行推断体验、菜品、口味、环境或食材，禁止“强烈推荐”“值得一试”“评分高达”“性价比高”“人气很旺”“经常排队”等评价或人气描述
- walk_minutes 有值时必须写“步行约N分钟”，“约”字不得省略；不得改写为精确分钟承诺
- amap_rating 缺失时省略评分短语；amap_avg_price 缺失时省略人均价格短语；禁止猜测或补值
- meal_slot=lunch 只表达为“午餐/中午可以去”，meal_slot=dinner 只表达为“晚餐可以去”；禁止写成暗示营业状态的“午市/晚市/营业中”
- full tier 若没有匹配的 authorization，按 structural tier 收紧，不得自行补充证据"""


SINGLE_PLAN_JSON_RETRY_PROMPT = """上一次输出不是合法 JSON。请只输出一个合法 JSON object。
必须以 { 开头，以 } 结尾。
不要 Markdown，不要代码围栏，不要解释文字。
不要输出 plans 数组。
字段只能包含 poi_fragments、day_openings、summary，以及可选的 packing_checklist 和 travel_tips；每个 fragment 只能包含 plan_index、day、place_id、text；每个 day_opening 只能包含 plan_index、day、text；summary 是一个字符串；每个 packing 分类只能包含 category 和 items；每条 travel_tips 必须且只能包含 title、content、evidence_ref。"""


DATABASE_FLAVORED_PHRASES = BANNED_DATABASE_PHRASES


def _writer_strict_evidence_enabled() -> bool:
    settings = get_settings()
    mode = str(getattr(settings, "writer_strict_evidence_mode", "auto") or "auto").strip().lower()
    if mode in {"1", "true", "yes", "on", "strict", "always"}:
        return True
    if mode in {"0", "false", "no", "off", "never", "disabled"}:
        return False
    profile = str(getattr(settings, "writer_relay_profile", "") or "").lower()
    model = str(getattr(settings, "writer_model", "") or "").lower()
    return profile == "gemini" or "gemini" in model


def _writer_temperature(kind: str) -> float:
    settings = get_settings()
    if kind == "repair":
        return float(getattr(settings, "writer_repair_temperature", 0.1))
    if kind == "retry":
        return float(getattr(settings, "writer_retry_temperature", 0.1))
    return float(getattr(settings, "writer_temperature", 0.15))


def _strict_evidence_prompt() -> str:
    return (
        "严格证据模式（复核事实边界，沿用本次输出格式与写作要求）：\n"
        "- Hard Fact Commitment 必须有候选证据或对应的权威输入支持；"
        "地点类型不证明具体设施、窗位、景观、营业状态、预约、票价、排队情况或历史。\n"
        "- Soft Experience Expression 可以使用：把授权信息写得自然，把可执行建议写成建议；"
        "不将 weak_experience 升级为推荐结论，不把 risk_only_warnings 变成卖点。\n"
        "- 路线、Day、餐食角色、通勤和预算由后端决定；正文不补缺失的数字、交通或外部事实。\n"
        "- 证据不足时缩短文字；不靠通用景物、虚构亲历、来源口吻或营销评价补足篇幅。\n"
        "- 本补充不改变上文 JSON 字段、长度要求、餐饮附件规则或行前建议的证据归属。"
    )


_FAMILY_MARKERS = (
    "亲子",
    "带娃",
    "小孩",
    "儿童",
    "孩子",
    "宝宝",
    "遛娃",
)


def _party_guidance(req: TripRequest) -> str:
    people_count = max(1, int(req.people_count or 1))
    context_text = " ".join([*req.preferences, req.notes])
    family_friendly = any(marker in context_text for marker in _FAMILY_MARKERS)

    lines = [f"同行人数：{people_count} 人。"]
    if people_count == 1:
        lines.append(
            "按单人旅行写：突出灵活、citywalk 和可临时调整，不要写成多人同行或亲子场景。"
        )
    elif people_count >= 3:
        lines.append(
            "按多人同行写：减少碎片化转场，餐食和休息安排要适合多人集合，"
            "不要把多人自动等同于亲子、家庭或老人。"
        )
    else:
        lines.append("按双人/结伴出行写，保持正常同行节奏。")

    if family_friendly:
        lines.append(
            "用户明确有亲子/带娃语义：写作中体现亲子友好、休息余量、少折返和儿童可接受节奏。"
        )
    else:
        lines.append(
            "没有明确亲子/带娃语义时，禁止因为人数较多就自行写亲子、带娃、儿童或家庭标签。"
        )
    return "\n".join(f"- {line}" for line in lines)


def _parse_writer_output(raw: str) -> dict | None:
    data, _diagnostics = _parse_writer_output_with_diagnostics(raw)
    return data


def _parse_writer_output_with_diagnostics(
    raw: str,
) -> tuple[dict | None, dict[str, Any]]:
    diagnostics: dict[str, Any] = {
        "raw_length": len(raw or ""),
        "parse_error_type": "",
        "json_extract_failed": False,
    }
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            diagnostics["parse_error_type"] = "no_json_object_found"
            diagnostics["json_extract_failed"] = True
            return None, diagnostics
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            diagnostics["parse_error_type"] = "extracted_json_decode_error"
            diagnostics["json_extract_failed"] = True
            return None, diagnostics
    if not isinstance(data, dict):
        diagnostics["parse_error_type"] = "json_root_not_object"
        return None, diagnostics
    return data, diagnostics


def _writer_parse_failure_excerpt_config() -> tuple[bool, int]:
    settings = get_settings()
    enabled = bool(getattr(settings, "writer_parse_failure_raw_excerpt_enabled", False))
    chars = int(getattr(settings, "writer_parse_failure_raw_excerpt_chars", 1000) or 0)
    chars = max(0, min(chars, 2000))
    return enabled, chars


def _json_candidate_prefix(text: str, limit: int) -> str:
    index = text.find("{")
    if index < 0 or limit <= 0:
        return ""
    return text[index:index + limit]


def _contains_unescaped_control_chars(text: str) -> bool:
    return any(
        ord(char) < 32 and char not in {"\t", "\n", "\r"}
        for char in text
    )


def _single_quote_json_like_pattern(text: str) -> bool:
    return bool(
        re.search(r"[\{\[,]\s*'[^']+'\s*:", text)
        or re.search(r":\s*'[^']*'\s*[,}\]]", text)
    )


def _base_writer_raw_output_diagnostics(raw: str) -> dict[str, Any]:
    text = raw or ""
    excerpt_enabled, excerpt_chars = _writer_parse_failure_excerpt_config()
    candidate_limit = excerpt_chars if excerpt_chars > 0 else 1000
    diagnostics: dict[str, Any] = {
        "raw_length": len(text),
        "writer_raw_output_sha256": hashlib.sha256(
            text.encode("utf-8", errors="replace")
        ).hexdigest(),
        "writer_raw_output_length": len(text),
        "parse_error_type": "",
        "parse_error_message": "",
        "parse_error_position": None,
        "first_json_candidate_prefix": _json_candidate_prefix(text, candidate_limit),
        "contains_markdown_fence": "```" in text,
        "brace_balance": text.count("{") - text.count("}"),
        "bracket_balance": text.count("[") - text.count("]"),
        "contains_unescaped_control_chars": _contains_unescaped_control_chars(text),
        "contains_trailing_comma_like_pattern": bool(
            re.search(r",\s*[\]}]", text)
        ),
        "contains_single_quote_json_like_pattern": _single_quote_json_like_pattern(
            text
        ),
        "json_extract_failed": False,
    }
    if excerpt_enabled and excerpt_chars > 0:
        diagnostics["writer_raw_output_prefix"] = text[:excerpt_chars]
        diagnostics["writer_raw_output_suffix"] = text[-excerpt_chars:]
    return diagnostics


def _apply_json_decode_error_diagnostics(
    diagnostics: dict[str, Any],
    exc: json.JSONDecodeError | None,
    offset: int = 0,
) -> None:
    if exc is None:
        return
    diagnostics["parse_error_message"] = exc.msg
    diagnostics["parse_error_position"] = offset + exc.pos


def _strip_json_bom_and_control_chars(candidate: str) -> str:
    text = candidate.lstrip("\ufeff")
    return "".join(
        char
        for char in text
        if ord(char) >= 32 or char in {"\t", "\n", "\r"}
    )


def _remove_json_trailing_commas(candidate: str) -> str:
    return re.sub(r",\s*([\]}])", r"\1", candidate)


def _escape_non_structural_json_string_quotes(candidate: str) -> str:
    repaired: list[str] = []
    in_string = False
    escaped = False
    length = len(candidate)
    for index, char in enumerate(candidate):
        if not in_string:
            repaired.append(char)
            if char == '"':
                in_string = True
            continue
        if escaped:
            repaired.append(char)
            escaped = False
            continue
        if char == "\\":
            repaired.append(char)
            escaped = True
            continue
        if char != '"':
            repaired.append(char)
            continue

        lookahead = index + 1
        while lookahead < length and candidate[lookahead].isspace():
            lookahead += 1
        next_char = candidate[lookahead] if lookahead < length else ""
        if next_char in {":", ",", "}", "]"}:
            repaired.append(char)
            in_string = False
        else:
            repaired.append('\\"')
    return "".join(repaired)


def _json_candidate_variants(candidate: str) -> list[str]:
    variants = [candidate]
    normalized = _remove_json_trailing_commas(
        _strip_json_bom_and_control_chars(candidate)
    )
    if normalized != candidate:
        variants.append(normalized)
    quote_repaired = _escape_non_structural_json_string_quotes(normalized)
    if quote_repaired not in variants:
        variants.append(quote_repaired)
    return variants


def _extract_first_json_object_with_diagnostics(
    raw: str,
) -> tuple[dict | None, dict[str, Any]]:
    diagnostics = _base_writer_raw_output_diagnostics(raw)
    text = raw or ""
    decoder = json.JSONDecoder()
    saw_object_start = False
    last_decode_error: json.JSONDecodeError | None = None
    last_decode_error_offset = 0
    for index, char in enumerate(text):
        if char != "{":
            continue
        saw_object_start = True
        for candidate in _json_candidate_variants(text[index:]):
            try:
                value, _end = decoder.raw_decode(candidate)
            except json.JSONDecodeError as exc:
                last_decode_error = exc
                last_decode_error_offset = index
                continue
            if isinstance(value, dict):
                return value, diagnostics
            diagnostics["parse_error_type"] = "json_root_not_object"
            diagnostics["parse_error_message"] = "JSON root is not an object"
            diagnostics["parse_error_position"] = index
            return None, diagnostics
    diagnostics["json_extract_failed"] = True
    diagnostics["parse_error_type"] = (
        "extracted_json_decode_error" if saw_object_start else "no_json_object_found"
    )
    _apply_json_decode_error_diagnostics(
        diagnostics,
        last_decode_error,
        offset=last_decode_error_offset,
    )
    return None, diagnostics


def _parse_single_plan_writer_output_with_diagnostics(
    raw: str,
) -> tuple[dict | None, dict[str, Any]]:
    data, diagnostics = _extract_first_json_object_with_diagnostics(raw)
    if data is None:
        return None, diagnostics
    if "plans" not in data:
        return data, diagnostics
    raw_plans = data.get("plans")
    if not isinstance(raw_plans, list):
        diagnostics["parse_error_type"] = "single_plan_plans_not_list"
        return None, diagnostics
    if len(raw_plans) != 1:
        diagnostics["parse_error_type"] = "single_plan_plans_count_not_one"
        return None, diagnostics
    plan = raw_plans[0]
    if not isinstance(plan, dict):
        diagnostics["parse_error_type"] = "single_plan_plan_not_object"
        return None, diagnostics
    diagnostics["single_plan_unwrapped_plans_array"] = True
    return plan, diagnostics


def _structured_evidence_summary(
    retrieval: RetrievalResult,
    route_plans: list[RoutePlan] | None = None,
    composition_blueprints: list[CompositionBlueprint] | None = None,
    structured_evidence_payload: StructuredEvidencePayload | None = None,
) -> str:
    payload = structured_evidence_payload or build_structured_evidence_payload(
        retrieval,
        route_plans=route_plans,
        composition_blueprints=composition_blueprints,
    )
    groups = retrieval.candidate_groups
    if route_plans:
        groups = [
            CandidateGroup(
                label=route_plan.label,
                candidates=[
                    place
                    for day_group in route_plan.day_groups
                    for place in day_group.places
                ],
            )
            for route_plan in route_plans
        ]
    if not groups:
        return render_structured_evidence_prompt(payload)
    sections = []
    for index, group in enumerate(groups, 1):
        lines = []
        for candidate in group.candidates:
            lines.append(render_place_evidence_line(candidate, payload))
        sections.append(
            f"候选组{group.label}（仅供方案{index}使用，已按证据强度授权）：\n"
            + "\n".join(lines)
        )
    return (
        "Structured Evidence Payload（runtime-only）: "
        f"version={payload.version}, classifier_fail_closed=true\n"
        "证据强度规则：可直接陈述=贴近原句事实；可弱表达=只能弱表达；"
        "只能条件提醒=风险提醒；禁止使用摘要/omitted 不得写入攻略。\n"
        "Mandatory Mention Policy：mandatory_mention=true 的地点必须出现在对应 Day 正文、"
        "Day 标题中；该字段只约束是否出现，不授权额外事实扩写。\n"
        + "\n\n".join(sections)
    )


def _route_plan_prompt(route_plans: list[RoutePlan]) -> str:
    sections = []
    for index, route_plan in enumerate(route_plans, 1):
        day_lines = []
        locked_names_by_day = [
            {place.name for place in day_group.places}
            for day_group in route_plan.day_groups
        ]
        locked_names = {
            name
            for names in locked_names_by_day
            for name in names
        }
        for day_group in route_plan.day_groups:
            place_names = "、".join(place.name for place in day_group.places)
            forbidden_names = sorted(
                locked_names - {place.name for place in day_group.places}
            )
            line = (
                f"Day {day_group.day}（{day_group.area or '区域未命名'}）："
                f"{place_names}"
            )
            if forbidden_names:
                line += (
                    "\n  本 Day 禁止提及这些其他天地点："
                    + "、".join(forbidden_names)
                )
            if day_group.commute_notes:
                line += "\n  通勤参考：" + "；".join(day_group.commute_notes)
            if day_group.time_hints:
                line += "\n  时段提示：" + "；".join(day_group.time_hints)
            day_lines.append(line)
        if route_plan.optimized:
            heading = (
                f"方案{index}锁定路线（对应候选组{route_plan.label}，"
                f"最终共{len(route_plan.day_groups)}天）"
            )
        else:
            heading = (
                f"方案{index}降级后的每日地点集合"
                f"（对应候选组{route_plan.label}，"
                f"最终共{len(route_plan.day_groups)}天）"
            )
        sections.append(f"{heading}：\n" + "\n".join(day_lines))
    return "\n\n".join(sections)


def _composition_blueprint_prompt(
    blueprints: list[CompositionBlueprint],
    *,
    plan_indexes: list[int] | None = None,
) -> str:
    sections = []
    for offset, blueprint in enumerate(blueprints):
        zero_index = (
            plan_indexes[offset]
            if plan_indexes is not None and offset < len(plan_indexes)
            else offset
        )
        index = zero_index + 1
        day_lines = []
        for day in blueprint.days:
            stop_lines = []
            for stop in day.stops:
                slot = f", meal_slot={stop.meal_slot}" if stop.meal_slot else ""
                hint = (
                    json.dumps(
                        stop.writing_hint,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    if isinstance(stop.writing_hint, dict)
                    else str(stop.writing_hint)
                )
                stop_lines.append(
                    f"    - {stop.name}: role={stop.role}{slot}, "
                    f"emphasis={stop.emphasis}, hint={hint}"
                )
            commute_lines = []
            for commute in day.commutes:
                mention = "must_mention" if commute.must_mention else "optional"
                commute_lines.append(
                    f"    - {commute.from_place_id}->{commute.to_place_id}: "
                    f"{commute.duration_minutes}min, mode={commute.mode}, "
                    f"style={commute.style}, {mention}"
                    + (
                        f", deterministic_transit_transition={commute.transit_transition}"
                        if commute.transit_transition
                        else ""
                    )
                )
            day_lines.append(
                f"  Day {day.day}: theme={day.theme_code}/{day.theme_label}\n"
                f"  stops:\n" + "\n".join(stop_lines)
                + (
                    "\n  commutes:\n" + "\n".join(commute_lines)
                    if commute_lines
                    else "\n  commutes: none"
                )
                + "\n  writing_notes: " + "；".join(day.writing_notes)
            )
        sections.append(
            f"方案{index}行程组合蓝图（对应候选组{blueprint.plan_label}）：\n"
            + "\n".join(day_lines)
        )
    return "\n\n".join(sections)


def _food_attachment_prompt(
    blueprints: list[CompositionBlueprint],
    attachment_auth_map: FoodAttachmentAuthMap | None,
    *,
    plan_indexes: list[int] | None = None,
) -> str:
    """Serialize food writing hints and full-tier authorization as JSON."""

    rows: list[dict[str, Any]] = []
    auth_map = attachment_auth_map or {}
    for offset, blueprint in enumerate(blueprints):
        zero_index = (
            plan_indexes[offset]
            if plan_indexes is not None and offset < len(plan_indexes)
            else offset
        )
        for day in blueprint.days:
            for stop in day.stops:
                hint = stop.writing_hint
                if not isinstance(hint, dict) or not hint.get("evidence_tier"):
                    continue
                meal_slot = str(hint.get("meal_slot") or stop.meal_slot or "")
                try:
                    food_place_id = int(hint.get("food_place_id"))
                except (TypeError, ValueError):
                    food_place_id = -1
                attachment_key = (
                    zero_index,
                    int(day.day),
                    int(stop.place_id),
                    meal_slot,
                    food_place_id,
                )
                row: dict[str, Any] = {
                    "writer_fragment_key": {
                        "plan_index": zero_index + 1,
                        "day": int(day.day),
                        "place_id": int(stop.place_id),
                    },
                    "attachment_key": {
                        "plan_index": attachment_key[0],
                        "day": attachment_key[1],
                        "anchor_place_id": attachment_key[2],
                        "meal_slot": attachment_key[3],
                        "food_place_id": attachment_key[4],
                    },
                    "writing_hint": dict(hint),
                }
                if str(hint.get("evidence_tier")) == "full":
                    authorization = auth_map.get(attachment_key)
                    if authorization is not None:
                        row["authorization"] = {
                            "direct_facts": list(authorization.direct_facts),
                            "weak_experience": list(
                                authorization.weak_experience
                            ),
                        }
                rows.append(row)
    if not rows:
        return ""
    return (
        "Food Stop Runtime Payload（JSON；仅用于当前 Writer 调用，不持久化）：\n"
        + json.dumps(
            rows,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def _publish_retry_feedback_prompt(
    feedback: list[dict[str, Any]] | None,
    *,
    plan_index: int | None = None,
) -> str:
    """Render bounded deterministic feedback for same-lock regeneration."""
    selected = [
        item
        for item in (feedback or [])
        if (
            plan_index is None
            or item.get("plan_index") in {None, plan_index}
        )
    ]
    if not selected:
        return ""

    lines = [
        "这是同一锁定路线的 Publish Retry。上一轮正文未通过以下确定性门禁；"
        "必须修正这些问题，但不得改变 Day、地点、顺序、通勤或事实边界："
    ]
    for item in selected[:20]:
        reason = str(item.get("reason") or "unknown")
        day = item.get("day")
        locked_places = [
            place
            for place in (item.get("locked_places") or [])
            if isinstance(place, dict)
        ]
        if not locked_places:
            legacy_actions = item.get("authorized_actions") or {}
            locked_places = [
                {
                    "name": str(name),
                    "authorized_actions": legacy_actions.get(name) or [],
                }
                for name in (item.get("locked_place_names") or [])
                if str(name)
            ]
        names = [
            str(place.get("name") or "")
            for place in locked_places
            if str(place.get("name") or "")
        ]
        prefix = f"- reason={reason}"
        if day is not None:
            prefix += f", Day {day}"
        if names:
            prefix += ", locked_places=" + " / ".join(names)
        lines.append(prefix)
        for place in locked_places:
            name = str(place.get("name") or "")
            allowed = [
                str(action)
                for action in (place.get("authorized_actions") or [])
                if str(action) and not str(action).startswith("[INTERNAL")
            ]
            hint = place.get("writing_hint") or ""
            if name:
                if hint:
                    line = f"  - {name}（写作角色：{hint}）"
                else:
                    line = f"  - {name}"
                if allowed:
                    line += "：" + " / ".join(allowed)
                else:
                    line += "：用你自己的表达写出至少一个具体可执行动作，不编造事实即可"
                lines.append(line)
    lines.append(
        "输出前逐 Day 自检：每个非 transfer_context 锁定地点都必须在正文"
        "得到一个具体可执行动作；标题、路线复述、通勤起终点和空壳停留句均不算。"
    )
    return "\n".join(lines)


def _build_user_prompt(
    req: TripRequest,
    retrieval: RetrievalResult,
    route_plans: list[RoutePlan] | None = None,
    composition_blueprints: list[CompositionBlueprint] | None = None,
    structured_evidence_payload: StructuredEvidencePayload | None = None,
    weather_advisory_payload: WeatherAdvisoryPayload | None = None,
    publish_retry_feedback: list[dict[str, Any]] | None = None,
    attachment_auth_map: FoodAttachmentAuthMap | None = None,
    pretrip_advice_payloads: list[PreTripAdvicePayload] | None = None,
) -> str:
    prefs = "、".join(req.preferences) if req.preferences else "无特殊偏好"
    avoids = "、".join(req.avoid) if req.avoid else "无"
    if route_plans and composition_blueprints is None:
        composition_blueprints = build_base_composition_blueprints(
            route_plans,
            req,
        )
    evidence_summary = _structured_evidence_summary(
        retrieval,
        route_plans,
        composition_blueprints,
        structured_evidence_payload,
    )

    locked_routes = ""
    route_instruction = ""
    group_instruction = (
        "方案1只能使用候选组A。"
    )
    generation_request = f"请基于以上真实数据生成 1 套 {req.days} 天的旅行攻略。"
    if route_plans:
        plan_count = len(route_plans)
        locked_routes = "\n\n" + _route_plan_prompt(route_plans)
        locked_routes += "\n\n" + _composition_blueprint_prompt(
            composition_blueprints
        )
        food_prompt = _food_attachment_prompt(
            composition_blueprints,
            attachment_auth_map,
        )
        if food_prompt:
            locked_routes += "\n\n" + food_prompt
        locked_day_counts = "；".join(
            f"方案{index}必须输出{len(route_plan.day_groups)}个 Day"
            for index, route_plan in enumerate(route_plans, 1)
        )
        group_instruction = "；".join(
            f"方案{index}只能使用候选组{route_plan.label}"
            for index, route_plan in enumerate(route_plans, 1)
        ) + "。"
        generation_request = (
            f"请基于以上真实数据生成 {plan_count} 套旅行攻略。"
            f"{locked_day_counts}，锁定 Day 数就是各方案最终天数。"
        )
        route_instruction = (
            "\n必须严格按上述锁定路线逐日写作。天内游览顺序已由锁定路线固定，"
            "不得调整同一天内的地点先后顺序；"
            "也不能跨天移动、增加或删除地点。任何地点名称只能出现在所属 Day，"
            "不要在其他天比较、回顾、预告或引用该地点；也不要把非本日地点写成"
            "“附近、能看到、能拍到、适合远眺、作为背景、可以顺路”的方位参照。"
            "如果一个著名地点不在当日锁定路线里，正文也完全不要出现它。即使锁定路线少于用户"
            "请求天数，也禁止自行新增 Day 或补充地点。行程组合蓝图只是写作参考，"
            "不是硬输出模板；优先保证攻略读起来像自然旅行建议。每个 Day 只允许"
            "出现一次标题，标题和正文首次出现的游览顺序都必须"
            "与锁定路线一致；允许无地点名的主题导语，但禁止提前点名后续地点。"
            "每个锁定地点必须写至少一个具体可执行动作；仅在标题、路线复述、通勤起终点"
            "或空壳停留句中出现不算活动覆盖。没有地点事实时，按 authorized_actions、"
            "place_type 和蓝图角色生成无事实承诺的行动建议。"
            "正文可以有自然的餐食安排和体力提示，但不能改变用户对实际游览顺序"
            "的理解。餐饮点可以自然写成午餐、晚餐、小吃、咖啡或可选夜宵；"
            "行程组合蓝图中的 meal_slot 是硬约束，meal_slot=lunch 必须写成午餐/中午吃饭节点，"
            "meal_slot=dinner 必须写成晚餐节点，不能把餐饮点写成普通景点或 citywalk 活动；"
            "但咖啡店、面包店、甜品店只能写成咖啡/休息/简单补给/轻食节点，"
            "除非候选证据明确支持正餐，否则不要写成午餐或晚餐；"
            "只有 must_mention 的长/远公共交通转场才在正文写交通方式与时间，"
            "并把蓝图的 deterministic_transit_transition 独立成句逐字复制；"
            "详细线路、站点、上下车、方向和换乘链只存在结构化结果中，正文禁止输出，"
            "也禁止复制 deterministic_transit_summary 或从原始步骤自行解释路线；"
            "不要写“解决午餐/解决晚餐”，也不要连续套用“今天主打/今天体验/继续探索”。"
            "transfer_context 和 optional_stop 轻写。只有 commutes 里 mode=walking 且 style=walkable "
            "时，才允许写“步行可达/走几步/很近”；mode=cycling 的长/远转场写骑行"
            "且禁止写驾车/打车；非 walking 不要写步行；"
            "style=normal_transfer 只用“随后再到/接着去”等无交通方式、无分钟数的"
            "自然衔接，不写公交、公共交通或“通勤参考”；"
            "style=long_transfer/remote_transfer 必须同时写 mode 对应交通方式、分钟或预留时间，"
            "并明确提示“这段稍远/路程较远”，不能只写分钟。不要机械堆叠分钟数。"
            "除 must_mention 的长转场外，正文重点应放在每个地点具体怎么玩，不要逐段播报车程；"
            "不要写“感受氛围”“老城氛围”“随手拍都有大片感”“拍照记录一下”“拍照留念”"
            "“根据自己状态灵活加减”“节奏可以自己说了算”等未授权软叙事。"
            "如果证据表达的是“从 A 看/拍 B”“A 视角/机位里的 B”，只能写在 A 停留"
            "并顺带看见/拍到 B，不能把 B 写成实际游览点、打卡点或拍摄承载点。"
            "不要写候选证据没有明确支持的亮灯、夜景更好看、最佳拍摄时间、"
            "最佳机位、必打卡、很出片等文旅套话。"
            "不要写“很值得”“很有氛围”“经典路线”“宝藏小店”“适合沉浸体验”"
            "“本地人爱去/推荐”等未授权软包装。"
            "不要自行输出负面体验判断或决策式建议，例如“没什么好拍的”“不太好拍”"
            "“可以根据实际情况决定是否购票/买票/购买车票”；没有授权时只写路线安排或条件性风险提醒。"
            "禁止“据说/听说/网传/亲测/博主推荐/作者推荐/本地人常去/当地人推荐”等来源口吻。"
            "除锁定地点原名外，正文只使用常用简体字，不要输出生僻字、异体字或 Unicode 扩展汉字。"
            "锁定地点名称必须逐字原样使用，"
            "不得增加“的”、使用简称或做其他改写。不要使用数据库口吻，禁止出现："
            + "、".join(DATABASE_FLAVORED_PHRASES)
            + "。"
        )
        if any(not route_plan.optimized for route_plan in route_plans):
            route_instruction += (
                "\n其中标记为“降级后的每日地点集合”的方案只锁定 Day 数和"
                "每个 Day 的地点集合。行政区、通勤距离和白天/夜间"
                "安排可能未充分优化；但仍必须遵守当日锁定地点的先后顺序，"
                "不得跨 Day 移动、增加、删除或重复地点。"
            )

    strict_instruction = (
        "\n\n" + _strict_evidence_prompt()
        if _writer_strict_evidence_enabled()
        else ""
    )
    retry_instruction = _publish_retry_feedback_prompt(
        publish_retry_feedback
    )
    advice_prompt = ""
    if pretrip_advice_payloads:
        advice_prompt = "\n\n".join(
            render_pretrip_advice_writer_prompt(payload)
            for payload in pretrip_advice_payloads
            if payload is not None
        )

    return f"""用户需求：
- 目的地：{req.to_city}
- 天数：{req.days} 天
- 人数：{req.people_count} 人
- 偏好：{prefs}
- 避开：{avoids}
- 备注：{req.notes or '无'}

人数与同行场景写作要求：
{_party_guidance(req)}

以下是 {retrieval.city} 的 Structured Evidence Payload（按有效推荐顺序分组；不是原始数据库证据）：
{evidence_summary}

{render_weather_prompt(weather_advisory_payload)}
{advice_prompt}
{locked_routes}
{retry_instruction}

{generation_request}
输出必须是一个合法 JSON object，字段按现有 schema；不要 Markdown、解释文字、代码围栏、注释或尾随逗号。
{group_instruction}不要在攻略正文或名称中提及候选组。{route_instruction}{strict_instruction}"""


def _locked_route_names(route_plan: RoutePlan) -> tuple[list[list[str]], list[str], list[int]]:
    day_names = [
        [place.name for place in day_group.places]
        for day_group in route_plan.day_groups
    ]
    names = [
        place.name
        for day_group in route_plan.day_groups
        for place in day_group.places
    ]
    ids = [
        place.place_id
        for day_group in route_plan.day_groups
        for place in day_group.places
    ]
    return day_names, names, ids


def _locked_plan_name(
    *,
    trip_request: TripRequest,
    retrieval: RetrievalResult,
    route_plan: RoutePlan,
    plan_index: int,
    total_plans: int = 1,
    composition_blueprint: CompositionBlueprint | None = None,
) -> str:
    """Build a publish-safe title solely from backend-locked structure."""
    _day_names, locked_names, _ids = _locked_route_names(route_plan)
    city = str(retrieval.city or trip_request.to_city or "目的地").strip()
    day_count = len([
        day_group
        for day_group in route_plan.day_groups
        if day_group.places
    ]) or max(1, int(trip_request.days or 1))
    theme_labels: list[str] = []
    if composition_blueprint is not None:
        for day in composition_blueprint.days:
            theme_label = str(day.theme_label or "").strip()
            if theme_label and theme_label not in theme_labels:
                theme_labels.append(theme_label)
    if theme_labels:
        route_label = "、".join(theme_labels[:2])
    elif len(locked_names) >= 2:
        route_label = f"{locked_names[0]}至{locked_names[-1]}"
    elif locked_names:
        route_label = f"{locked_names[0]}行程"
    else:
        route_label = "锁定行程"
    if total_plans <= 1:
        return f"{city}{day_count}日｜{route_label}"
    return f"{city}{day_count}日｜{route_label}（方案{plan_index}）"


def _merge_locked_place_fields(
    *,
    plan_name: str,
    plan_text: str,
    route_plan: RoutePlan | None = None,
    retrieval: RetrievalResult | None = None,
    composition_blueprint: CompositionBlueprint | None = None,
    poi_identity_result: PoiIdentityResult | None = None,
    budget_result: BudgetResult | None = None,
    poi_fragments: list[PoiNarrativeFragment] | None = None,
    summary: str = "",
    accommodation: AccommodationSuggestion | None = None,
    transport: TransportSuggestion | None = None,
    packing_checklist: list[PackingChecklistGroup] | None = None,
    travel_tips: list[TravelTip] | None = None,
) -> PlanOutput:
    """Build PlanOutput and always fill place structure from the lock.

    Writer-emitted used_place_names / day_place_names / used_place_ids are ignored
    when a RoutePlan is available. Without a route plan, structure fields stay empty;
    they are never trusted from Writer JSON.

    ``summary`` must be threaded through by every rebuild path; a caller that
    omits it silently resets the plan summary to the deterministic fallback.
    Rebuilds of an existing Writer PlanOutput must also pass the already-sanitized
    ``packing_checklist`` and ``travel_tips``; omitting them resets both to None.
    """
    del retrieval  # reserved for diagnostics; structure never comes from Writer
    if route_plan is not None:
        day_names, names, ids = _locked_route_names(route_plan)
        return PlanOutput(
            plan_name=plan_name,
            plan_text=plan_text,
            summary=summary,
            used_place_ids=ids,
            used_place_names=names,
            day_place_names=day_names,
            composition_blueprint=composition_blueprint,
            poi_identity_result=poi_identity_result,
            budget_result=budget_result,
            accommodation=accommodation,
            transport=transport,
            packing_checklist=packing_checklist,
            travel_tips=travel_tips,
            poi_fragments=poi_fragments or [],
        )
    return PlanOutput(
        plan_name=plan_name,
        plan_text=plan_text,
        summary=summary,
        used_place_ids=[],
        used_place_names=[],
        day_place_names=[],
        composition_blueprint=composition_blueprint,
        poi_identity_result=poi_identity_result,
        budget_result=budget_result,
        accommodation=accommodation,
        transport=transport,
        packing_checklist=packing_checklist,
        travel_tips=travel_tips,
        poi_fragments=poi_fragments or [],
    )


def _pretrip_payload_for_index(
    payloads: list[PreTripAdvicePayload] | None,
    zero_index: int,
) -> PreTripAdvicePayload | None:
    if not payloads or zero_index < 0 or zero_index >= len(payloads):
        return None
    return payloads[zero_index]


def _attach_sanitized_pretrip_advice(
    plan: PlanOutput,
    raw_data: dict[str, Any] | None,
    payload: PreTripAdvicePayload | None,
) -> tuple[PlanOutput, dict[str, Any]]:
    empty = {
        "writer_packing_groups_retained": 0,
        "writer_packing_items_retained": 0,
        "writer_tips_retained": 0,
        "writer_advice_dropped_reasons": {},
    }
    if payload is None or not isinstance(raw_data, dict):
        return plan, empty
    # Capture internal draft fields before public TravelTip strips evidence_ref.
    sanitized = sanitize_writer_advice(
        raw_data.get("packing_checklist"),
        raw_data.get("travel_tips"),
        payload,
    )
    return (
        plan.model_copy(
            update={
                "packing_checklist": sanitized.packing_checklist,
                "travel_tips": sanitized.travel_tips,
            }
        ),
        {
            "writer_packing_groups_retained": (
                sanitized.metrics.packing_groups_retained
            ),
            "writer_packing_items_retained": (
                sanitized.metrics.packing_items_retained
            ),
            "writer_tips_retained": sanitized.metrics.tips_retained,
            "writer_advice_dropped_reasons": dict(
                sanitized.metrics.dropped_reasons
            ),
        },
    )


def _single_route_prompt(
    route_plan: RoutePlan,
    *,
    plan_index: int | None = None,
    validation_candidate_names: list[str] | None = None,
    structured_evidence_payload: StructuredEvidencePayload | None = None,
) -> str:
    lines = []
    del validation_candidate_names
    if structured_evidence_payload is None:
        route_payload = build_structured_evidence_payload(
            RetrievalResult(
                city="",
                candidates=[
                    route_place
                    for route_day in route_plan.day_groups
                    for route_place in route_day.places
                ],
            ),
            route_plans=[route_plan],
        )
    else:
        route_payload = structured_evidence_payload.for_route_plan(
            route_plan,
            plan_index=plan_index,
        )
    for day_group in route_plan.day_groups:
        place_lines = []
        for place in day_group.places:
            key_prefix = (
                f"key=({int(plan_index or 1)},{day_group.day},{place.place_id}) | "
            )
            place_lines.append(
                key_prefix + render_place_evidence_line(place, route_payload)
            )
        commute = (
            "\n  通勤参考: " + "；".join(day_group.commute_notes)
            if day_group.commute_notes
            else ""
        )
        lines.append(
            f"Day {day_group.day}: "
            + "、".join(place.name for place in day_group.places)
            + commute
            + "\n"
            + "\n".join(place_lines)
        )
    return "\n\n".join(lines)


def _parse_repair_output(raw: str) -> dict | None:
    data = _parse_writer_output(raw)
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("plans"), list) and data["plans"]:
        first = data["plans"][0]
        return first if isinstance(first, dict) else None
    return data


def _valid_day_heading_matches(
    plan_text: str,
) -> list[tuple[re.Match[str], int]]:
    heading = re.compile(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*"
        r"(?:Day\s*(\d+)|第\s*(\d+|[一二三四五六七八九十]+)\s*(?:天|日))"
        r"([^\n]*?)(?:\*\*)?\s*$"
    )
    valid: list[tuple[re.Match[str], int]] = []
    for match in heading.finditer(plan_text or ""):
        day = _parse_day_heading_number(match.group(1) or match.group(2))
        if day is None or not _is_day_heading_line(
            match.group(0),
            match.group(3) or "",
        ):
            continue
        valid.append((match, day))
    return valid


def _day_heading_text(plan_text: str) -> str:
    return "\n".join(
        match.group(0) for match, _day in _valid_day_heading_matches(plan_text)
    )


def _deduplicate_day_headings(plan_text: str) -> str:
    if not plan_text.strip():
        return plan_text
    seen_days: set[int] = set()
    pieces: list[str] = []
    cursor = 0
    for match, day in _valid_day_heading_matches(plan_text):
        if day in seen_days:
            pieces.append(plan_text[cursor:match.start()])
            cursor = match.end()
            if cursor < len(plan_text) and plan_text[cursor:cursor + 1] == "\n":
                cursor += 1
            continue
        seen_days.add(day)
    if cursor == 0:
        return plan_text
    pieces.append(plan_text[cursor:])
    return "".join(pieces)


def _fill_missing_locked_names_in_day_body(
    body: str,
    locked_names: list[str],
    *,
    scan_body: str | None = None,
) -> str:
    """Restore omitted locked stops beside their nearest present route anchor.

    Existing first-hit reordering is intentionally left untouched so the O1
    structural gate still fails closed. Only genuinely missing canonical names
    are inserted, and contiguous gaps are processed right-to-left so the
    original anchor offsets stay valid.
    """
    names = [name for name in locked_names if name]
    if not names:
        return body
    scan_text = scan_body if scan_body is not None else body
    if len(scan_text) != len(body):
        scan_text = body
    positions = [scan_text.find(name) for name in names]
    present_positions = [position for position in positions if position >= 0]
    if any(
        current <= previous
        for previous, current in zip(
            present_positions,
            present_positions[1:],
        )
    ):
        return body

    missing_indexes = [
        index for index, position in enumerate(positions) if position < 0
    ]
    if not missing_indexes:
        return body

    groups: list[tuple[int, int]] = []
    start = missing_indexes[0]
    end = start + 1
    for index in missing_indexes[1:]:
        if index == end:
            end += 1
            continue
        groups.append((start, end))
        start = index
        end = index + 1
    groups.append((start, end))

    result = body
    for start, end in reversed(groups):
        missing_text = "、".join(names[start:end])
        previous_index = next(
            (
                index
                for index in range(start - 1, -1, -1)
                if positions[index] >= 0
            ),
            None,
        )
        if previous_index is not None:
            insertion_at = (
                positions[previous_index] + len(names[previous_index])
            )
            result = (
                result[:insertion_at]
                + "，随后到"
                + missing_text
                + result[insertion_at:]
            )
            continue

        prefix = (
            f"先到{missing_text}，再继续后面的安排。"
            if end < len(names)
            else f"本日按锁定顺序到{missing_text}。"
        )
        result = "\n" + prefix + "\n" + result.lstrip("\r\n")
    return result


def _minimal_locked_day_text(day_group: RouteDayGroup) -> str:
    names = [place.name for place in day_group.places if place.name]
    if not names:
        return ""
    route_line = " → ".join(names)
    return "\n".join([
        f"Day {day_group.day}｜{route_line}",
        (
            f"本日按锁定路线依次游览：{route_line}。"
            "保留休息时间，避免临时加点。"
        ),
    ])


def _required_commute_lines(
    day_group: RouteDayGroup,
    blueprint_day: Any | None,
) -> list[str]:
    """Render only must-mention commutes from the deterministic blueprint."""
    if blueprint_day is None:
        return []

    name_by_id: dict[int, str] = {}
    for place in day_group.places:
        name_by_id[place.place_id] = place.name
        if place.canonical_place_id is not None:
            name_by_id[place.canonical_place_id] = place.name

    lines: list[str] = []
    mode_labels = {
        "driving": "驾车",
        "transit": "公共交通",
        "cycling": "骑行",
        "walking": "步行",
    }
    for commute in blueprint_day.commutes:
        if not commute.must_mention:
            continue
        from_name = name_by_id.get(commute.from_place_id, "")
        to_name = name_by_id.get(commute.to_place_id, "")
        if commute.mode == "transit":
            transition = commute.transit_transition
            if not transition and from_name and to_name:
                transition = (
                    f"{from_name}→{to_name}，公共交通约 "
                    f"{int(commute.duration_minutes or 0)} 分钟"
                )
            if not transition:
                continue
        else:
            if not from_name or not to_name:
                continue
            transition = (
                f"{from_name}→{to_name}，"
                f"{mode_labels.get(commute.mode, '通勤')}预计 "
                f"{int(commute.duration_minutes or 0)} 分钟"
            )
        lines.append(
            f"通勤参考：{transition}。这段路程较远，请预留通勤时间。"
        )
    return lines


_KEYED_FRAGMENT_DAY_SYNTAX_RE = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(?:Day\s*\d+|第\s*[一二三四五六七八九十\d]+\s*[天日])"
)
_KEYED_FRAGMENT_ROUTE_SYNTAX = ("通勤参考", " -> ", "→")

_DAY_OPENING_TRANSIT_MARKERS = (
    "地铁",
    "公交",
    "换乘",
    "打车",
    "驾车",
    "开车",
    "骑行",
    "轨道",
    "通勤",
    "车程",
    "上车",
    "下车",
)
_DAY_OPENING_MIN_CHARS = 6
_DAY_OPENING_MAX_CHARS = 80


def _sanitize_day_opening_text(
    raw_text: Any,
    *,
    banned_names: list[str],
    same_day_place_names: list[str] | None = None,
) -> tuple[str, str]:
    """Admit a theme-only day opening or return a drop reason.

    Openings are optional prose comfort: any violation drops the opening
    instead of failing the plan, so this path can never reduce availability.

    ``same_day_place_names`` are the day's locked names in route order
    (v0.9.0.1): they may appear in the opening, but only as an in-order
    prefix of the day's route. The opening precedes every fragment in the
    day body, so any other mention pattern would corrupt the ADR 0017
    first-hit order and fail the whole plan downstream.
    """
    if not isinstance(raw_text, str) or not raw_text.strip():
        return "", "opening_empty"
    text = re.sub(r"\s+", " ", raw_text).strip()
    if not (_DAY_OPENING_MIN_CHARS <= len(text) <= _DAY_OPENING_MAX_CHARS):
        return "", "opening_length_out_of_range"
    if re.search(r"\d", text):
        return "", "opening_contains_digit"
    if _KEYED_FRAGMENT_DAY_SYNTAX_RE.search(text) or any(
        marker in text for marker in _KEYED_FRAGMENT_ROUTE_SYNTAX
    ):
        return "", "opening_contains_backend_structure"
    if any(marker in text for marker in _DAY_OPENING_TRANSIT_MARKERS):
        return "", "opening_contains_transit"
    day_names = [name for name in (same_day_place_names or []) if name]
    day_name_set = set(day_names)
    if any(
        name and name in text
        for name in banned_names
        if name not in day_name_set
    ):
        return "", "opening_contains_place_name"
    if day_names:
        mentioned = extract_claimed_names(text, day_names)
        if mentioned and mentioned != day_names[: len(mentioned)]:
            return "", "opening_place_order_violation"
    if has_hard_fact_marker(text):
        return "", "opening_contains_hard_fact"
    if unsupported_fact_pattern_matches(text):
        return "", "opening_unsupported_expression"
    if untrusted_transport_claim_matches(text):
        return "", "opening_transport_claim"
    if any(phrase in text for phrase in BANNED_DATABASE_PHRASES):
        return "", "opening_database_tone"
    if any(phrase in text for phrase in PLACEHOLDER_PHRASES):
        return "", "opening_placeholder_wording"
    return text, ""


_SUMMARY_MIN_CHARS = 50
_SUMMARY_MAX_CHARS = 130


def _sanitize_summary_text(
    raw_text: Any,
    *,
    banned_names: list[str],
) -> tuple[str, str]:
    """Admit a Writer whole-trip summary or return a drop reason.

    Summaries are optional prose comfort (v0.9.0.1): any violation drops
    the summary and the API falls back to the deterministic template, so
    this path can never reduce availability. The summary is trip-level:
    every candidate/locked POI name is banned.
    """
    if not isinstance(raw_text, str) or not raw_text.strip():
        return "", "summary_empty"
    text = re.sub(r"\s+", " ", raw_text).strip()
    if not (_SUMMARY_MIN_CHARS <= len(text) <= _SUMMARY_MAX_CHARS):
        return "", "summary_length_out_of_range"
    if _KEYED_FRAGMENT_DAY_SYNTAX_RE.search(text) or any(
        marker in text for marker in _KEYED_FRAGMENT_ROUTE_SYNTAX
    ):
        return "", "summary_contains_backend_structure"
    if any(name and name in text for name in banned_names):
        return "", "summary_contains_place_name"
    if has_hard_fact_marker(text):
        return "", "summary_contains_hard_fact"
    if unsupported_fact_pattern_matches(text):
        return "", "summary_unsupported_expression"
    if untrusted_transport_claim_matches(text):
        return "", "summary_transport_claim"
    if any(phrase in text for phrase in BANNED_DATABASE_PHRASES):
        return "", "summary_database_tone"
    if any(phrase in text for phrase in PLACEHOLDER_PHRASES):
        return "", "summary_placeholder_wording"
    return text, ""


def _raw_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _sanitize_keyed_fragment_text(
    raw_text: Any,
    *,
    place_name: str,
    route_plan: RoutePlan,
    validation_candidate_names: list[str],
    weather_advisory_payload: WeatherAdvisoryPayload | None,
    allowed_contextual_names: list[str] | None = None,
    same_day_prior_place_names: set[str] | None = None,
) -> tuple[str, list[Any], str]:
    """Clean one already-keyed fragment without inferring its owner from text."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        return "", [], "empty_fragment_text"

    weather_cleaned, weather_actions = apply_weather_advisory_to_text(
        raw_text,
        route_plan=route_plan,
        payload=weather_advisory_payload,
    )
    initial_issues: list[GenerationIssue] = []
    if any(phrase in weather_cleaned for phrase in BANNED_DATABASE_PHRASES):
        initial_issues.append(GenerationIssue(
            source="deterministic",
            category="WARN",
            publish_action="RECORD_ONLY",
            reason="database_tone",
            evidence="exact banned database/source phrase in keyed fragment",
        ))
    allowed_names = {
        name
        for name in (allowed_contextual_names or [])
        if name
    }
    # Same-day locked POI names that were already visited earlier in the day
    # are legal geo references inside a fragment (v0.9.0.1). Forward
    # references to later same-day stops stay disallowed: the ADR 0017
    # ordered-lock body check compares first-hit order against the locked
    # route, and an early mention of a later stop fails the whole plan.
    effective_same_day = {
        name
        for name in (same_day_prior_place_names or set())
        if name
    }
    disallowed_names = sorted(
        {
            name
            for name in validation_candidate_names
            if name
            and name != place_name
            and name not in allowed_names
            and name not in effective_same_day
        },
        key=lambda value: (-len(value), value),
    )
    sanitized, sanitizer_actions = sanitize_repair_text(
        weather_cleaned,
        issues=initial_issues,
        disallowed_candidate_names=disallowed_names,
        allowed_candidate_names=[
            place_name,
            *sorted(allowed_names),
            *sorted(effective_same_day),
        ],
        locked_day_names=None,
    )
    text = re.sub(r"\s+", " ", sanitized).strip()
    text = re.sub(
        rf"^\s*{re.escape(place_name)}\s*[：:，,。\-—]*\s*",
        "",
        text,
        count=1,
    ).strip()
    # Strip leaked [INTERNAL ...] writing hints — these are prompt-only
    # instructions that the Writer sometimes copies into its output.
    text = re.sub(
        r"\[INTERNAL[^\]]*\]\s*[^。]*[。.]?\s*",
        "",
        text,
    ).strip()
    actions: list[Any] = [*weather_actions, *sanitizer_actions]
    if not text:
        return "", actions, "fragment_empty_after_sanitizer"
    if _KEYED_FRAGMENT_DAY_SYNTAX_RE.search(text) or any(
        marker in text for marker in _KEYED_FRAGMENT_ROUTE_SYNTAX
    ):
        return "", actions, "fragment_contains_backend_structure"
    return text, actions, ""


def _assemble_keyed_writer_plan(
    *,
    plan_index: int,
    raw_fragments: Any,
    route_plan: RoutePlan,
    structured_evidence_payload: StructuredEvidencePayload,
    composition_blueprint: CompositionBlueprint | None,
    validation_candidate_names: list[str],
    weather_advisory_payload: WeatherAdvisoryPayload | None,
    raw_day_openings: Any = None,
    accommodation: AccommodationSuggestion | None = None,
    transport: TransportSuggestion | None = None,
) -> KeyedPlanAssemblyResult:
    """Validate Writer fragment slots and assemble final text in backend order.

    Missing, duplicate, malformed, or structurally invasive Writer slots are
    closed from the pre-Writer Action Plan.  No whole-plan LLM retry is used.
    """
    result = KeyedPlanAssemblyResult()
    expected_places = {
        (plan_index, day_group.day, place.place_id): (day_group, place)
        for day_group in route_plan.day_groups
        for place in day_group.places
    }
    raw_by_key: dict[tuple[int, int, int], dict[str, Any]] = {}
    duplicate_keys: set[tuple[int, int, int]] = set()
    if not isinstance(raw_fragments, list):
        result.invalid_details.append({
            "reason": "poi_fragments_not_list",
        })
        raw_fragments = []

    for raw_index, item in enumerate(raw_fragments):
        if not isinstance(item, dict):
            result.invalid_details.append({
                "raw_index": raw_index,
                "reason": "fragment_not_object",
            })
            continue
        key_values = (
            _raw_positive_int(item.get("plan_index")),
            _raw_positive_int(item.get("day")),
            _raw_positive_int(item.get("place_id")),
        )
        if any(value is None for value in key_values):
            result.invalid_details.append({
                "raw_index": raw_index,
                "reason": "fragment_key_invalid",
            })
            continue
        key = (
            int(key_values[0]),
            int(key_values[1]),
            int(key_values[2]),
        )
        if key not in expected_places:
            result.ignored_keys.append(key)
            result.invalid_details.append({
                "raw_index": raw_index,
                "reason": "fragment_key_not_locked",
                "plan_index": key[0],
                "day": key[1],
                "place_id": key[2],
            })
            continue
        if key in raw_by_key or key in duplicate_keys:
            raw_by_key.pop(key, None)
            duplicate_keys.add(key)
            result.invalid_details.append({
                "raw_index": raw_index,
                "reason": "fragment_key_duplicate",
                "plan_index": key[0],
                "day": key[1],
                "place_id": key[2],
            })
            continue
        raw_by_key[key] = item

    blueprint_days = {
        day.day: day
        for day in (
            composition_blueprint.days
            if composition_blueprint is not None
            else []
        )
    }
    # Map (plan_index, day, place_id) → writing_hint for food-stop marker
    # injection.  The Writer never outputs HTML comment markers; the
    # assembler injects them deterministically so publish_gate can verify.
    food_hint_by_key: dict[tuple[int, int, int], dict[str, Any]] = {}
    for day in (
        composition_blueprint.days
        if composition_blueprint is not None
        else []
    ):
        for stop in day.stops:
            if (
                isinstance(stop.writing_hint, dict)
                and stop.writing_hint.get("evidence_tier")
                and stop.writing_hint.get("span_marker")
            ):
                food_hint_by_key[
                    (plan_index, day.day, stop.place_id)
                ] = stop.writing_hint
    contextual_names_by_key = {
        (plan_index, day.day, stop.place_id): [
            str(stop.writing_hint.get("food_name"))
        ]
        for day in (
            composition_blueprint.days
            if composition_blueprint is not None
            else []
        )
        for stop in day.stops
        if (
            isinstance(stop.writing_hint, dict)
            and stop.writing_hint.get("evidence_tier") in {
                "full",
                "structural",
            }
            and stop.writing_hint.get("food_name")
        )
    }

    opening_banned_names = sorted(
        {
            name
            for name in (
                *validation_candidate_names,
                *(
                    place.name
                    for day_group in route_plan.day_groups
                    for place in day_group.places
                ),
            )
            if name
        },
        key=lambda value: (-len(value), value),
    )
    opening_day_names = {
        day_group.day: [
            place.name for place in day_group.places if place.name
        ]
        for day_group in route_plan.day_groups
    }
    openings_by_day: dict[int, str] = {}
    if isinstance(raw_day_openings, list):
        for raw_index, item in enumerate(raw_day_openings):
            if not isinstance(item, dict):
                result.day_opening_dropped.append({
                    "raw_index": raw_index,
                    "reason": "opening_not_object",
                })
                continue
            opening_plan = _raw_positive_int(item.get("plan_index"))
            opening_day = _raw_positive_int(item.get("day"))
            if opening_plan != plan_index or opening_day is None:
                result.day_opening_dropped.append({
                    "raw_index": raw_index,
                    "reason": "opening_key_invalid",
                })
                continue
            if opening_day in openings_by_day:
                openings_by_day.pop(opening_day, None)
                result.day_opening_dropped.append({
                    "raw_index": raw_index,
                    "day": opening_day,
                    "reason": "opening_duplicate_day",
                })
                continue
            text, rejection = _sanitize_day_opening_text(
                item.get("text"),
                banned_names=opening_banned_names,
                same_day_place_names=opening_day_names.get(opening_day),
            )
            if rejection:
                result.day_opening_dropped.append({
                    "raw_index": raw_index,
                    "day": opening_day,
                    "reason": rejection,
                })
                continue
            openings_by_day[opening_day] = text

    parts: list[str] = []
    cursor = 0

    def append(value: str) -> None:
        nonlocal cursor
        parts.append(value)
        cursor += len(value)

    if transport is not None:
        transport_parts: list[str] = []
        for mode_summary in transport.modes:
            if mode_summary.min_duration_minutes < 60:
                duration = f"约{mode_summary.min_duration_minutes}分钟"
            else:
                duration = f"约{mode_summary.min_duration_minutes / 60:.1f}小时"
            if mode_summary.mode == "train":
                prefix = (
                    "查询时可购的高铁"
                    if mode_summary.availability_status == "available_at_query"
                    else "可关注高铁班次"
                )
                transport_parts.append(
                    f"{prefix}{duration}（二等座{mode_summary.price_range}）"
                )
            elif mode_summary.mode == "flight":
                transport_parts.append(
                    f"飞机{duration}（经济舱{mode_summary.price_range}）"
                )
        if transport_parts:
            source_note = "" if transport.source == "realtime" else "（参考值）"
            append(
                f"【出行建议】从{transport.from_city}出发，"
                f"{'，或'.join(transport_parts)}。"
                "实际班次、余票和价格以购票平台为准。"
                f"建议提前1-2周购票。{source_note}\n\n"
            )

    if accommodation is not None:
        if accommodation.source == "user_specified":
            if route_plan.accommodation_policy_version and route_plan.accommodation_anchor:
                precision = route_plan.accommodation_anchor.location_precision
                basis = "住宿区域" if precision == "area" else "住宿位置"
                append(f"【住宿安排】以你指定的{accommodation.name}为每天出发和返回的{basis}，往返时间按该位置估算。\n\n")
            elif accommodation.name == "用户指定住宿位置":
                append(
                    "【住宿建议】从你指定的位置出发，"
                    "每天安排已考虑往返距离。\n\n"
                )
            else:
                append(
                    f"【住宿建议】从你住的{accommodation.name}出发，"
                    "每天安排已考虑往返距离。\n\n"
                )
        else:
            append(
                f"【住宿建议】建议住在{accommodation.name}附近，"
                f"{accommodation.reason}。\n\n"
            )

    for day_offset, day_group in enumerate(route_plan.day_groups):
        if day_offset:
            append("\n\n")
        append(
            f"Day {day_group.day}："
            + " -> ".join(place.name for place in day_group.places)
            + "\n"
        )
        if route_plan.route_policy_version == "selector-route-v2":
            summary = access_summary(day_group)
            if summary:
                append(summary + "。\n")
        grounded_arrival_lines: list[str] = []
        opening = openings_by_day.get(day_group.day)
        if opening:
            append(opening + "\n")
            result.day_opening_count += 1
        for place_offset, place in enumerate(day_group.places):
            if place_offset:
                append("\n")
            key = (plan_index, day_group.day, place.place_id)
            contract = structured_evidence_payload.action_contract(
                plan_index=key[0],
                day=key[1],
                place_id=key[2],
            )
            if (
                contract is None
                or not contract.authorized_actions
                or contract.place_name != place.name
            ):
                result.failure_reason = "writer_keyed_fragment_action_contract_missing"
                result.invalid_details.append({
                    "reason": result.failure_reason,
                    "plan_index": key[0],
                    "day": key[1],
                    "place_id": key[2],
                })
                return result
            raw_item = raw_by_key.get(key)
            raw_text = raw_item.get("text") if raw_item is not None else None
            cleaned, actions, rejection = _sanitize_keyed_fragment_text(
                raw_text,
                place_name=place.name,
                route_plan=route_plan,
                validation_candidate_names=validation_candidate_names,
                weather_advisory_payload=weather_advisory_payload,
                allowed_contextual_names=contextual_names_by_key.get(key),
                same_day_prior_place_names={
                    p.name
                    for p in day_group.places[:place_offset]
                    if p.name
                },
            )
            result.sanitizer_actions.extend(actions)
            if not rejection:
                incoming = next((leg for leg in day_group.commute_legs
                    if leg.to_place_id == place.place_id and place_offset > 0
                    and leg.from_place_id == day_group.places[place_offset-1].place_id), None)
                grounded = arrival_activity_copy(cleaned, incoming)
                if grounded != cleaned:
                    result.sanitizer_actions.append({"action":"arrival_duration_grounded",
                        "reason":"locked_incoming_commute_authority", "plan_index":plan_index,
                        "day":day_group.day, "place_id":place.place_id})
                    mode_label = {"transit": "公共交通", "walking": "步行", "driving": "驾车", "cycling": "骑行"}[incoming.mode]
                    grounded_arrival_lines.append(
                        f"通勤参考：{incoming.from_name}→{incoming.to_name}，"
                        f"{mode_label}约 {incoming.duration_minutes} 分钟。"
                    )
                    cleaned = grounded
                    if not cleaned.strip():
                        rejection = "fragment_empty_after_arrival_removal"
            if rejection:
                result.fallback_keys.append(key)
                result.invalid_details.append({
                    "reason": rejection,
                    "plan_index": key[0],
                    "day": key[1],
                    "place_id": key[2],
                })
                result.sanitizer_actions.append({
                    "action": "keyed_fragment_completion",
                    "reason": rejection,
                    "plan_index": key[0], "day": key[1], "place_id": key[2],
                    "publishable_action_count": sum(
                        bool(str(a).strip()) and not str(a).strip().startswith("[INTERNAL")
                        for a in contract.authorized_actions
                    ),
                })
                line = completion_sentence_for_contract(contract)
                source = "deterministic_completion"
            else:
                line = f"{place.name}：{cleaned}"
                source = "writer"

            # ── Food span marker injection ──────────────────────────
            # The Writer never outputs HTML comment markers.  For every
            # food-stop slot we deterministically wrap the food prose
            # with the marker pair that publish_gate expects.
            food_hint = food_hint_by_key.get(key)
            if food_hint is not None:
                span_marker = str(food_hint.get("span_marker") or "")
                tier = str(food_hint.get("evidence_tier") or "")
                close_marker = "<!-- /food -->"
                if tier == "none":
                    # None tier: replace any Writer attempt with the
                    # canonical none_tier_text wrapped in markers.
                    none_text = str(food_hint.get("none_tier_text") or "")
                    food_span = f"{span_marker}{none_text}{close_marker}"
                    # Append to the existing line (anchor POI text + food span)
                    if none_text:
                        line = line.replace(none_text, "").rstrip("，,；; ")
                    line = f"{line}{food_span}"
                    source = "deterministic_food_none"
                else:
                    # structural / full tier: scan the Writer text for
                    # the food prose and wrap it.  If the Writer already
                    # included markers, leave as-is.
                    if span_marker not in line and close_marker not in line:
                        # Best-effort: the food prose is usually at the
                        # end of the fragment after the anchor POI text.
                        # We wrap everything after the anchor place_name
                        # colon header that mentions meal-related keywords.
                        line = f"{line}{span_marker}{close_marker}"

            start = cursor
            append(line)
            result.fragments.append(PoiNarrativeFragment(
                plan_index=key[0],
                day=key[1],
                place_id=key[2],
                text=line,
                start=start,
                end=cursor,
                source=source,
            ))
        required_lines = _required_commute_lines(
            day_group, blueprint_days.get(day_group.day),
        )
        for commute_line in required_lines:
            append("\n" + commute_line)
        for commute_line in dict.fromkeys(grounded_arrival_lines):
            transition = commute_line.removeprefix("通勤参考：").rstrip("。")
            if not any(transition in required for required in required_lines):
                append("\n" + commute_line)

    result.plan_text = "".join(parts)
    return result


def _ensure_locked_route_text(
    plan_text: str,
    route_plan: RoutePlan,
    composition_blueprint: CompositionBlueprint | None = None,
) -> str:
    """Add only deterministic route-structure text needed for locked coverage."""
    plan_text = _deduplicate_day_headings(plan_text)
    if not plan_text.strip() or not route_plan.day_groups:
        return plan_text
    valid_matches = _valid_day_heading_matches(plan_text)
    if not valid_matches:
        return plan_text

    route_days = {day_group.day: day_group for day_group in route_plan.day_groups}
    route_day_order = [day_group.day for day_group in route_plan.day_groups]
    route_day_indexes = {
        day: index for index, day in enumerate(route_day_order)
    }
    present_days = [day for _match, day in valid_matches]
    present_indexes = [
        route_day_indexes[day]
        for day in present_days
        if day in route_day_indexes
    ]
    can_restore_missing_days = (
        len(present_indexes) == len(present_days)
        and present_indexes == sorted(present_indexes)
        and len(set(present_days)) == len(present_days)
    )
    next_route_day_index = 0
    blueprint_days = {
        day.day: day
        for day in (
            composition_blueprint.days
            if composition_blueprint is not None
            else []
        )
    }

    pieces: list[str] = [plan_text[:valid_matches[0][0].start()]]
    for index, (match, day) in enumerate(valid_matches):
        if can_restore_missing_days:
            current_route_day_index = route_day_indexes[day]
            while next_route_day_index < current_route_day_index:
                missing_day = route_days[route_day_order[next_route_day_index]]
                missing_section = _minimal_locked_day_text(missing_day)
                if missing_section:
                    pieces.append("\n\n" + missing_section + "\n")
                next_route_day_index += 1
            next_route_day_index = current_route_day_index + 1
        section_end = (
            valid_matches[index + 1][0].start()
            if index + 1 < len(valid_matches)
            else len(plan_text)
        )
        section = plan_text[match.start():section_end]
        body = plan_text[match.end():section_end]
        additions: list[str] = []
        day_group = route_days.get(day)
        if day_group is not None:
            locked_names = [
                place.name for place in day_group.places if place.name
            ]
            restored_body = _fill_missing_locked_names_in_day_body(
                body,
                locked_names,
                scan_body=mask_authorized_commute_spans(
                    body,
                    route_plan,
                    day=day,
                ),
            )
            if restored_body != body:
                section = section[: match.end() - match.start()] + restored_body
                body = restored_body
            for commute_line in _required_commute_lines(
                day_group,
                blueprint_days.get(day),
            ):
                transition = commute_line.removeprefix("通勤参考：").split(
                    "。", 1
                )[0]
                if transition not in body:
                    additions.append(commute_line)
        if additions:
            section = section.rstrip() + "\n" + "\n".join(additions) + "\n"
        pieces.append(section)
    if can_restore_missing_days:
        while next_route_day_index < len(route_day_order):
            missing_day = route_days[route_day_order[next_route_day_index]]
            missing_section = _minimal_locked_day_text(missing_day)
            if missing_section:
                pieces.append("\n\n" + missing_section + "\n")
            next_route_day_index += 1
    return "".join(pieces)


def _minimal_locked_route_text(route_plan: RoutePlan) -> str:
    """Build deterministic repair text from locked routes only."""
    sections: list[str] = []
    for day_group in route_plan.day_groups:
        section = _minimal_locked_day_text(day_group)
        if section:
            sections.append(section)
    return "\n".join(sections)


def _route_place_names(route_plan: RoutePlan) -> set[str]:
    return {
        place.name
        for day_group in route_plan.day_groups
        for place in day_group.places
    }


def _sibling_unique_names(
    route_plan: RoutePlan,
    sibling_route_plans: list[RoutePlan],
) -> list[str]:
    own_names = _route_place_names(route_plan)
    sibling_names = {
        place.name
        for sibling in sibling_route_plans
        for day_group in sibling.day_groups
        for place in day_group.places
    }
    return sorted(sibling_names - own_names, key=lambda value: (-len(value), value))


def _sibling_route_signature(
    route_plan: RoutePlan,
    sibling_route_plans: list[RoutePlan],
) -> str:
    if not sibling_route_plans:
        return "无"
    sections = []
    for sibling in sibling_route_plans:
        areas = sorted({
            day_group.area
            for day_group in sibling.day_groups
            if day_group.area
        })
        unique_names = _sibling_unique_names(route_plan, [sibling])
        sections.append(
            "\n".join([
                f"- 方案标签: {sibling.label}",
                f"  主要区域: {'、'.join(areas) if areas else '无明确区域'}",
                (
                    "  本方案禁写的另一方案独有 POI: "
                    + ("、".join(unique_names) if unique_names else "无")
                ),
            ])
        )
    return "\n".join(sections)


def _label_alignment_failure(
    *,
    route_plan: RoutePlan,
    budget_result: BudgetResult | None = None,
    poi_identity_result: PoiIdentityResult | None = None,
    composition_blueprint: CompositionBlueprint | None = None,
) -> str:
    expected = route_plan.label
    labels = [
        ("budget", budget_result.plan_label if budget_result is not None else expected),
        (
            "poi_identity",
            poi_identity_result.plan_label
            if poi_identity_result is not None
            else expected,
        ),
        (
            "composition_blueprint",
            composition_blueprint.plan_label
            if composition_blueprint is not None
            else expected,
        ),
    ]
    for name, actual in labels:
        if actual != expected:
            return f"{name}_label_mismatch:{actual}!={expected}"
    return ""


def _plan_overlap_ratio(plans: list[PlanOutput]) -> float | None:
    if len(plans) < 2:
        return None
    first = set(plans[0].used_place_ids)
    second = set(plans[1].used_place_ids)
    if not first and not second:
        return None
    return len(first & second) / max(len(first | second), 1)


def _serialize_sanitizer_action(action: Any) -> dict[str, Any]:
    if hasattr(action, "model_dump"):
        return action.model_dump(mode="json")
    if isinstance(action, dict):
        return action
    return {"action": str(action), "reason": "unknown_sanitizer_action"}


def _sanitize_initial_writer_plan(
    plan: PlanOutput,
    *,
    route_plan: RoutePlan,
    composition_blueprint: CompositionBlueprint | None,
    validation_candidate_names: list[str],
) -> tuple[PlanOutput, list[RepairSanitizerAction]]:
    """Apply structural cleanup plus exact soft-copy phrase removal."""
    locked_day_names, locked_names, _ = _locked_route_names(route_plan)
    disallowed_names = sorted(
        set(validation_candidate_names) - set(locked_names),
        key=lambda value: (-len(value), value),
    )
    initial_issues = []
    if any(
        phrase in (plan.plan_text or "")
        for phrase in BANNED_DATABASE_PHRASES
    ):
        initial_issues.append(GenerationIssue(
            source="deterministic",
            category="WARN",
            publish_action="RECORD_ONLY",
            reason="database_tone",
            evidence="exact banned database/source phrase",
        ))
    sanitized_text, actions = sanitize_repair_text(
        plan.plan_text,
        # WARN/RECORD_ONLY only enables exact banned-phrase removal. It does not
        # run repair-time snippet or risky-expression sentence deletion.
        issues=initial_issues,
        disallowed_candidate_names=disallowed_names,
        allowed_candidate_names=locked_names,
        locked_day_names=locked_day_names,
    )
    ensured_text = _ensure_locked_route_text(
        sanitized_text,
        route_plan,
        composition_blueprint,
    )
    if not actions and ensured_text == plan.plan_text:
        return plan, []
    return (
        plan.model_copy(update={
            "plan_text": ensured_text
        }),
        actions,
    )


def _build_fragment_slots(
    *,
    plan_index: int,
    route_plan: RoutePlan,
    structured_evidence_payload: StructuredEvidencePayload,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build Writer fragment slots with arrival context for non-first stops.

    Arrival context (v0.9.0.1) carries real commute_legs data so the Writer
    can open a fragment with a vague transition; commute legs may reference
    canonical ids, so legs are matched on both place_id and
    canonical_place_id. The first stop of each day gets no arrival fields,
    and a missing leg degrades to no arrival fields.
    """
    fragment_slots: list[dict[str, Any]] = []
    missing_contract_details: list[dict[str, Any]] = []
    for day_group in route_plan.day_groups:
        prev_place = None
        for place in day_group.places:
            contract = structured_evidence_payload.action_contract(
                plan_index=plan_index,
                day=day_group.day,
                place_id=place.place_id,
            )
            if (
                contract is None
                or not contract.authorized_actions
                or contract.place_name != place.name
            ):
                missing_contract_details.append({
                    "reason": "writer_keyed_fragment_action_contract_missing",
                    "plan_index": plan_index,
                    "day": day_group.day,
                    "place_id": place.place_id,
                })
                prev_place = place
                continue
            slot: dict[str, Any] = {
                "plan_index": plan_index,
                "day": day_group.day,
                "place_id": place.place_id,
                "place_name": place.name,
                "authorized_actions": [
                    a for a in contract.authorized_actions
                    if not str(a).startswith("[INTERNAL")
                ],
                "writing_hint": next(
                    (
                        str(a).replace("[INTERNAL 写作指引，勿输出] ", "")
                        for a in contract.authorized_actions
                        if str(a).startswith("[INTERNAL")
                    ),
                    None,
                ),
            }
            if prev_place is not None:
                prev_ids = {
                    value
                    for value in (
                        prev_place.place_id,
                        prev_place.canonical_place_id,
                    )
                    if value is not None
                }
                cur_ids = {
                    value
                    for value in (
                        place.place_id,
                        place.canonical_place_id,
                    )
                    if value is not None
                }
                leg = next(
                    (
                        candidate_leg
                        for candidate_leg in day_group.commute_legs
                        if candidate_leg.from_place_id in prev_ids
                        and candidate_leg.to_place_id in cur_ids
                    ),
                    None,
                )
                if leg is not None:
                    slot["arrival_from"] = prev_place.name
                    slot["arrival_mode"] = leg.mode
                    slot["arrival_minutes"] = leg.duration_minutes
            fragment_slots.append(slot)
            prev_place = place
    return fragment_slots, missing_contract_details


def _raw_fragment_key(item: Any) -> tuple[int, int, int] | None:
    if not isinstance(item, dict):
        return None
    values = (
        _raw_positive_int(item.get("plan_index")),
        _raw_positive_int(item.get("day")),
        _raw_positive_int(item.get("place_id")),
    )
    if any(value is None for value in values):
        return None
    return (int(values[0]), int(values[1]), int(values[2]))


def _merge_raw_keyed_fragment_replacements(
    raw: str,
    replacements: dict[tuple[int, int, int], str],
) -> str | None:
    data, _diagnostics = _parse_single_plan_writer_output_with_diagnostics(raw)
    if data is None or not replacements:
        return None
    raw_fragments = data.get("poi_fragments")
    if not isinstance(raw_fragments, list):
        return None
    target_keys = set(replacements)
    retained = [
        item for item in raw_fragments
        if _raw_fragment_key(item) not in target_keys
    ]
    retained.extend(
        {
            "plan_index": key[0],
            "day": key[1],
            "place_id": key[2],
            "text": text,
        }
        for key, text in replacements.items()
    )
    data["poi_fragments"] = retained
    return json.dumps(data, ensure_ascii=False)


async def _archive_speculative_losing_drafts(
    execution: SpeculativeExecutionResult[PlanWriteResult],
) -> bool | None:
    """Archive completed non-adopted bodies; never expose them to telemetry."""
    job_id = str(current_llm_call_context().get("job_id") or "").strip()
    records: list[SpeculativeArchiveRecord] = []

    for opus_result in execution.completed_opus_results:
        if (
            execution.decision.adopted is AdoptedGenerator.OPUS
            and opus_result is execution.opus_result
        ):
            continue
        if opus_result.raw_text is None:
            continue
        records.append(SpeculativeArchiveRecord(
            job_id=job_id,
            generator=AdoptedGenerator.OPUS.value,
            adopted=False,
            draft_body=opus_result.raw_text,
            latency_ms=opus_result.latency_ms,
            structurally_valid=(
                opus_result.state is OpusAdjudicationState.VALID
            ),
            writer_prompt_version=opus_result.prompt_version,
            token_in=opus_result.token_in,
            token_out=opus_result.token_out,
        ))

    ds_result = execution.ds_result
    if (
        ds_result.terminal_state is DSTerminalState.COMPLETED
        and execution.decision.adopted is not AdoptedGenerator.DS_FLASH
    ):
        assert ds_result.raw_text is not None
        records.append(SpeculativeArchiveRecord(
            job_id=job_id,
            generator=AdoptedGenerator.DS_FLASH.value,
            adopted=False,
            draft_body=ds_result.raw_text,
            latency_ms=ds_result.latency_ms,
            structurally_valid=ds_result.structurally_valid,
            writer_prompt_version=ds_result.prompt_version,
            token_in=ds_result.token_in,
            token_out=ds_result.token_out,
        ))

    return await archive_speculative_records(records)


async def archive_speculative_records(
    records: list[SpeculativeArchiveRecord],
) -> bool | None:
    """Flush already-classified losing records without failing delivery."""
    if not records:
        return None

    async def append(record: SpeculativeArchiveRecord) -> bool:
        try:
            return await append_speculative_archive(record)
        except Exception as exc:
            logger.warning(
                "speculative_archive_write_failed error_type=%s",
                exc.__class__.__name__,
            )
            return False

    outcomes = await asyncio.gather(*(append(record) for record in records))
    return all(outcomes)


def _adopted_speculative_archive_record(
    execution: SpeculativeExecutionResult[PlanWriteResult],
) -> SpeculativeArchiveRecord | None:
    job_id = str(current_llm_call_context().get("job_id") or "").strip()
    if execution.decision.adopted is AdoptedGenerator.OPUS:
        result = execution.opus_result
        if result.raw_text is None:
            return None
        return SpeculativeArchiveRecord(
            job_id=job_id,
            generator=AdoptedGenerator.OPUS.value,
            adopted=False,
            draft_body=result.raw_text,
            latency_ms=result.latency_ms,
            structurally_valid=True,
            writer_prompt_version=result.prompt_version,
            token_in=result.token_in,
            token_out=result.token_out,
        )
    if execution.decision.adopted is AdoptedGenerator.DS_FLASH:
        result = execution.ds_result
        if result.raw_text is None:
            return None
        return SpeculativeArchiveRecord(
            job_id=job_id,
            generator=AdoptedGenerator.DS_FLASH.value,
            adopted=False,
            draft_body=result.raw_text,
            latency_ms=result.latency_ms,
            structurally_valid=result.structurally_valid,
            writer_prompt_version=result.prompt_version,
            token_in=result.token_in,
            token_out=result.token_out,
        )
    return None


async def _generate_one_locked_plan(
    *,
    zero_index: int,
    trip_request: TripRequest,
    retrieval: RetrievalResult,
    route_plan: RoutePlan,
    sibling_route_plans: list[RoutePlan],
    budget_result: BudgetResult | None = None,
    poi_identity_result: PoiIdentityResult | None = None,
    composition_blueprint: CompositionBlueprint | None = None,
    structured_evidence_payload: StructuredEvidencePayload | None = None,
    weather_advisory_payload: WeatherAdvisoryPayload | None = None,
    publish_retry_feedback: list[dict[str, Any]] | None = None,
    attachment_auth_map: FoodAttachmentAuthMap | None = None,
    accommodation: AccommodationSuggestion | None = None,
    transport: TransportSuggestion | None = None,
    pretrip_advice_payload: PreTripAdvicePayload | None = None,
    workflow_deadline_monotonic: float | None = None,
    residual_reserve_seconds: float = 20.0,
    speculative_initial_generation: bool = True,
    speculative_adopted_archive_sink: list[SpeculativeArchiveRecord] | None = None,
    _raw_override: str | None = None,
) -> PlanWriteResult:
    t0 = time.monotonic()
    plan_index = zero_index + 1
    alignment_error = _label_alignment_failure(
        route_plan=route_plan,
        budget_result=budget_result,
        poi_identity_result=poi_identity_result,
        composition_blueprint=composition_blueprint,
    )
    if alignment_error:
        return PlanWriteResult(
            zero_index=zero_index,
            failure_reason=alignment_error,
            latency_ms=0,
        )
    if structured_evidence_payload is None:
        structured_evidence_payload = build_structured_evidence_payload(
            retrieval,
            route_plans=[route_plan],
            composition_blueprints=(
                [composition_blueprint]
                if composition_blueprint is not None
                else None
            ),
        )

    fragment_slots, missing_contract_details = _build_fragment_slots(
        plan_index=plan_index,
        route_plan=route_plan,
        structured_evidence_payload=structured_evidence_payload,
    )
    if missing_contract_details:
        return PlanWriteResult(
            zero_index=zero_index,
            failure_reason="writer_keyed_fragment_action_contract_missing",
            latency_ms=int((time.monotonic() - t0) * 1000),
            keyed_fragment_invalid_details=missing_contract_details,
        )
    sibling_unique = _sibling_unique_names(route_plan, sibling_route_plans)
    blueprint_prompt = (
        _composition_blueprint_prompt(
            [composition_blueprint],
            plan_indexes=[zero_index],
        )
        if composition_blueprint is not None
        else ""
    )
    food_prompt = (
        _food_attachment_prompt(
            [composition_blueprint],
            attachment_auth_map,
            plan_indexes=[zero_index],
        )
        if composition_blueprint is not None
        else ""
    )
    prompt_parts = [
        (
            f"用户目的地：{trip_request.to_city}；检索城市：{retrieval.city}；"
            f"天数：{trip_request.days}；人数：{trip_request.people_count}；"
            f"当前只生成方案{plan_index}，对应候选组{route_plan.label}。"
        ),
        "人数与同行场景写作要求：\n" + _party_guidance(trip_request),
        (
            "当前方案锁定路线和证据：\n"
            + _single_route_prompt(
                route_plan,
                plan_index=plan_index,
                validation_candidate_names=[c.name for c in retrieval.candidates],
                structured_evidence_payload=structured_evidence_payload,
            )
        ),
        (
            "必须逐项填写以下后端稳定 slots；只回传 key 和 text，顺序不作为结构依据：\n"
            + json.dumps(
                [
                    {k: v for k, v in slot.items() if k != "writing_hint"}
                    for slot in fragment_slots
                ],
                ensure_ascii=False,
            )
        ),
        """写作目标：一份读完对旅程有所期待、拿着又知道怎么玩的旅行攻略。语气像认真帮朋友安排行程，不扮演刚踩完线的人，不写成劝人订票的广告。

正文怎么写：
- 先通读当天各站的授权材料，想清这一天最有意思的体验，再分别写各地点。日开场带起有依据的游览重点，不把站点名单改成“先去、再去”。
- 重点地点挑一处有辨识度的看点、活动或背景，带读者知道留意什么、怎样参与。可以从具体观察展开，不必每段从到达动作写起；不要把所有地点都写成“看看、走走、坐坐”。
- 把保留下来的细节及其位置、否定、季节和条件一起表达。两条街之间的墙画仍在两条街之间，春季笔记的开花观察不能变成本次出行当天的状态；不要为行文顺滑删掉限定。
- 各站轻重不同：主要体验适度展开，普通过渡简短带过。细节充分时自然写出为什么愿意花时间，不强制每段都有主题句、理由、提醒或金句。
- 优先挑出当前地点最有用的一两条授权信息，自然说清可以怎么逛。动作、细节、提醒不必按固定顺序排列，也不用每段全部具备。
- 有辨识度的细节可以多写两句；休息、补给或证据少的地点可以一句带过。长短随内容走，不凑字数、不强求每个地点都有独一无二的故事。
- 有依据的画面可以保留，用具体、平常的词写。比喻、对仗、拟人都是可选项；不要求题眼、首尾呼应或每段一句金句。
- 别把读者的感受提前写死。少用“让心慢下来”“把力气省给眼睛”“让江风沉淀”等空泛抒情，也不要把“值得、治愈、氛围感”当成内容。
- 可直接开始写当前地点，不必每站先交代“从上一站过来”。不用连续以“你可以/建议你/到这里后”开头；也无需为了避免重复而生硬地替换普通动词。
- 每个地点仍要有一个与其类型、角色相符的可执行动作；只写“看看走走、按自己的节奏、拍照停留”不够。authorized_actions 可自然改写，不是逐字照抄的句子。
- 只有内部指引、没有公开动作短句时，依据当前地点类型和授权事实写具体建议，不输出内部指引。没有依据就简短表达，不补设施、景色或游览条件。

示例只示范表达，不提供本次行程事实：
【输入已授权：老街有石阶，从上往下逛；有电梯可到顶楼】
生硬：沿着石阶感受老街氛围，把力气省给眼睛。
自然：可以先乘电梯到顶楼，再沿石阶往下逛。
【输入只有：咖啡店，作为途中休息节点】
自然：点杯咖啡，坐下来歇一会儿。
不补：靠窗座位、店里安静、刚出炉的面包。宁可简短，也别为写得好看加上未知的细节。

day_openings：每天一句，60 字以内，概括当天有依据的内容或节奏；不用强行对仗或抒情，不复述站点清单。不写数字、交通或其他可核验事实。若点名，只能按当天路线从第一站开始依次出现。
summary：80-120 字，交代这趟行程主要看什么、各天怎样组织，归纳锁定安排支持的路线特征。用平常的话写，不为收束而回扣意象；不出现具体地点名、价格、营业时间或交通方式。
输出：单个 JSON 对象，包含 poi_fragments、day_openings、summary，以及按授权输入填写的可选 packing_checklist 和 travel_tips。每个稳定 key 恰好一次。地点名、Day 标题和交通由后端添加；text 不重复当前地点名、不写路线箭头。不新增或调换地点，不补路线外专名。餐饮附件按 System 与 Food Stop Runtime Payload 执行。
""",
    ]
    if blueprint_prompt:
        prompt_parts.insert(
            3,
            "当前方案行程组合蓝图：\n" + blueprint_prompt,
        )
    if food_prompt:
        prompt_parts.insert(4, food_prompt)
    retry_instruction = _publish_retry_feedback_prompt(
        publish_retry_feedback,
        plan_index=plan_index,
    )
    if retry_instruction:
        prompt_parts.append(retry_instruction)
    if pretrip_advice_payload is not None:
        prompt_parts.append(
            render_pretrip_advice_writer_prompt(pretrip_advice_payload)
        )
    if _writer_strict_evidence_enabled():
        prompt_parts.append(_strict_evidence_prompt())
    prompt = "\n\n".join(prompt_parts)

    settings = get_settings()
    stream_probes = bool(settings.writer_stream_probe_enabled)
    speculative_telemetry = SpeculativeTelemetry()

    def attach_probe_metrics(result: PlanWriteResult) -> PlanWriteResult:
        if not stream_probes or _raw_override is not None:
            return result
        snapshot = speculative_telemetry.snapshot()
        result.probe_telemetry_enabled = True
        result.probe_kill_count = snapshot.probe_kill_count
        result.probe_kill_endpoints = list(snapshot.probe_kill_endpoints)
        result.probe_kill_kind = snapshot.probe_kill_kind
        result.probe_partial_output_before_kill = (
            snapshot.probe_partial_output_before_kill
        )
        return result

    speculation_enabled = bool(
        settings.speculative_ds_standby_enabled
        and _raw_override is None
        and speculative_initial_generation
        and not publish_retry_feedback
    )
    if speculation_enabled:
        opus_budget_cancel_requested = asyncio.Event()
        keyed_repair_used = {"opus": False, "ds_flash": False}
        keyed_repair_observations: dict[str, dict[str, Any]] = {}
        validation_kwargs = {
            "zero_index": zero_index,
            "trip_request": trip_request,
            "retrieval": retrieval,
            "route_plan": route_plan,
            "sibling_route_plans": sibling_route_plans,
            "budget_result": budget_result,
            "poi_identity_result": poi_identity_result,
            "composition_blueprint": composition_blueprint,
            "structured_evidence_payload": structured_evidence_payload,
            "weather_advisory_payload": weather_advisory_payload,
            "publish_retry_feedback": publish_retry_feedback,
            "attachment_auth_map": attachment_auth_map,
            "accommodation": accommodation,
            "transport": transport,
            "pretrip_advice_payload": pretrip_advice_payload,
            "workflow_deadline_monotonic": workflow_deadline_monotonic,
            "residual_reserve_seconds": residual_reserve_seconds,
            "speculative_initial_generation": speculative_initial_generation,
        }

        reconstructed_routes = list(sibling_route_plans)
        reconstructed_routes.insert(zero_index, route_plan)

        async def validate_raw_result(
            raw: str,
            *,
            generator: str,
        ) -> PlanWriteResult:
            result = await _generate_one_locked_plan(
                **validation_kwargs,
                _raw_override=raw,
            )
            if result.plan is None or result.failure_reason:
                return result
            fallback_keys = list(dict.fromkeys(result.keyed_fragment_fallback_keys))
            if not fallback_ratio_exceeded(
                fallback_keys,
                total_fragment_count=result.keyed_fragment_count,
            ):
                result.keyed_fragment_repair_remaining_count = len(fallback_keys)
                return result

            result.keyed_fragment_repair_attempted = True
            result.keyed_fragment_repair_target_count = len(fallback_keys)
            observation: dict[str, Any] = {
                "attempted": True,
                "target_count": len(fallback_keys),
                "applied_count": 0,
                "remaining_count": len(fallback_keys),
                "latency_ms": 0,
                "failure_reason": "",
            }
            keyed_repair_observations[generator] = observation
            if keyed_repair_used[generator]:
                result.failure_reason = "writer_excessive_keyed_fragment_fallback"
                result.keyed_fragment_repair_failure_reason = "repair_round_exhausted"
                observation["failure_reason"] = "repair_round_exhausted"
                return result
            keyed_repair_used[generator] = True

            deadline = (
                float(workflow_deadline_monotonic)
                if workflow_deadline_monotonic is not None
                else time.monotonic() + WORKFLOW_WALL_SECONDS
            )
            required_budget = (
                KEYED_FRAGMENT_REPAIR_TIMEOUT_SECONDS
                + ORDINARY_REVIEW_REQUEST_TIMEOUT_SECONDS
                + residual_reserve_seconds
            )
            if deadline - time.monotonic() < required_budget:
                result.failure_reason = "writer_excessive_keyed_fragment_fallback"
                result.keyed_fragment_repair_failure_reason = "budget_denied"
                observation["failure_reason"] = "budget_denied"
                return result

            targets = build_keyed_fragment_targets(
                fallback_keys,
                route_plans=reconstructed_routes,
                structured_evidence_payload=structured_evidence_payload,
            )
            if len(targets) != len(fallback_keys):
                result.failure_reason = "writer_excessive_keyed_fragment_fallback"
                result.keyed_fragment_repair_failure_reason = "target_contract_missing"
                observation["failure_reason"] = "target_contract_missing"
                return result
            repair = await call_keyed_fragment_repair(
                generator=generator,
                targets=targets,
            )
            result.keyed_fragment_repair_latency_ms = repair.latency_ms
            observation["latency_ms"] = repair.latency_ms
            if not repair.replacements:
                result.failure_reason = "writer_excessive_keyed_fragment_fallback"
                result.keyed_fragment_repair_failure_reason = (
                    repair.failure_reason or "no_valid_replacements"
                )
                observation["failure_reason"] = (
                    result.keyed_fragment_repair_failure_reason
                )
                return result
            merged_raw = _merge_raw_keyed_fragment_replacements(
                raw,
                repair.replacements,
            )
            if merged_raw is None:
                result.failure_reason = "writer_excessive_keyed_fragment_fallback"
                result.keyed_fragment_repair_failure_reason = "merge_failed"
                observation["failure_reason"] = "merge_failed"
                return result
            repaired = await _generate_one_locked_plan(
                **validation_kwargs,
                _raw_override=merged_raw,
            )
            remaining_keys = list(dict.fromkeys(
                repaired.keyed_fragment_fallback_keys
            ))
            repaired.keyed_fragment_repair_attempted = True
            repaired.keyed_fragment_repair_target_count = len(fallback_keys)
            repaired.keyed_fragment_repair_remaining_count = len(remaining_keys)
            repaired.keyed_fragment_repair_applied_count = max(
                0,
                len(fallback_keys) - len(set(fallback_keys) & set(remaining_keys)),
            )
            repaired.keyed_fragment_repair_latency_ms = repair.latency_ms
            observation.update({
                "applied_count": repaired.keyed_fragment_repair_applied_count,
                "remaining_count": len(remaining_keys),
            })
            if (
                repaired.plan is None
                or repaired.failure_reason
                or fallback_ratio_exceeded(
                    remaining_keys,
                    total_fragment_count=repaired.keyed_fragment_count,
                )
            ):
                repaired.failure_reason = "writer_excessive_keyed_fragment_fallback"
                repaired.keyed_fragment_repair_failure_reason = (
                    repair.failure_reason or "fallback_ratio_still_exceeded"
                )
                observation["failure_reason"] = (
                    repaired.keyed_fragment_repair_failure_reason
                )
            return repaired

        async def run_opus(attempt_prompt: str, call_reason: str) -> OpusDraftResult[PlanWriteResult]:
            try:
                with llm_call_context(
                    call_reason=call_reason,
                    role="writer",
                    stage="WRITER",
                    writer_budget_cancel_event=opus_budget_cancel_requested,
                    writer_speculative_observer=speculative_telemetry,
                ):
                    raw = await chat(
                        system=SINGLE_PLAN_SYSTEM_PROMPT,
                        user=attempt_prompt,
                        role="writer",
                        temperature=_writer_temperature("original"),
                        json_mode=True,
                    )
            except Exception as exc:
                return OpusDraftResult(
                    OpusAdjudicationState.DEAD,
                    failure_type=exc.__class__.__name__,
                )
            metadata = last_chat_metadata()
            result = await validate_raw_result(raw, generator="opus")
            if result.plan is None or result.failure_reason:
                return OpusDraftResult(
                    OpusAdjudicationState.INVALID,
                    failure_type=result.failure_reason,
                    raw_text=raw,
                    latency_ms=int(metadata.get("latency_ms") or 0),
                    token_in=int(metadata.get("token_input") or 0),
                    token_out=int(metadata.get("token_output") or 0),
                    prompt_version=OPUS_WRITER_PROMPT_VERSION,
                )
            return OpusDraftResult(
                OpusAdjudicationState.VALID,
                draft=result,
                raw_text=raw,
                latency_ms=int(metadata.get("latency_ms") or 0),
                token_in=int(metadata.get("token_input") or 0),
                token_out=int(metadata.get("token_output") or 0),
                prompt_version=OPUS_WRITER_PROMPT_VERSION,
            )

        async def run_opus_initial() -> OpusDraftResult[PlanWriteResult]:
            return await run_opus(
                prompt,
                f"writer_original_plan_{plan_index}",
            )

        async def run_opus_retry() -> OpusDraftResult[PlanWriteResult]:
            return await run_opus(
                prompt + "\n\n" + SINGLE_PLAN_JSON_RETRY_PROMPT,
                f"writer_original_plan_{plan_index}_json_retry",
            )

        def start_ds() -> DSStandbyTask[PlanWriteResult]:
            async def validate_ds(raw: str) -> PlanWriteResult | None:
                result = await validate_raw_result(raw, generator="ds_flash")
                if result.plan is not None and not result.failure_reason:
                    return result
                return None

            return DSStandbyTask.start(
                user=prompt,
                temperature=_writer_temperature("original"),
                validate=validate_ds,
            )

        executor = SpeculativeWriterExecutor(
            run_opus_initial=run_opus_initial,
            run_opus_retry=run_opus_retry,
            start_ds=start_ds,
            workflow_deadline_monotonic=(
                float(workflow_deadline_monotonic)
                if workflow_deadline_monotonic is not None
                else time.monotonic() + WORKFLOW_WALL_SECONDS
            ),
            residual_reserve_seconds=residual_reserve_seconds,
            opus_attempt_cost_seconds=(
                STREAM_ATTEMPT_TIMEOUT_SECONDS
                if stream_probes
                else ATTEMPT_TIMEOUT_SECONDS
            ),
            review_cost_seconds=ORDINARY_REVIEW_REQUEST_TIMEOUT_SECONDS,
            request_opus_budget_cancel=opus_budget_cancel_requested.set,
            telemetry=speculative_telemetry,
        )
        execution = await executor.execute()
        decision = execution.decision
        archive_write_succeeded = await _archive_speculative_losing_drafts(
            execution
        )
        adopted_archive_record = _adopted_speculative_archive_record(execution)
        if (
            adopted_archive_record is not None
            and speculative_adopted_archive_sink is not None
        ):
            speculative_adopted_archive_sink.append(adopted_archive_record)
        if execution.adopted_draft is None:
            adopted_result = PlanWriteResult(
                zero_index=zero_index,
                failure_reason="speculative_no_publishable_draft",
                latency_ms=int((time.monotonic() - t0) * 1000),
                generator=AdoptedGenerator.SAFE.value,
            )
        else:
            adopted_result = execution.adopted_draft
            adopted_result.generator = decision.adopted.value
            adopted_result.writer_plan_retry_used = execution.opus_retry_used
            adopted_result.writer_plan_retry_count = int(execution.opus_retry_used)
        adopted_result.adjudication_reason = decision.reason.value
        adopted_result.opus_adjudication_state = decision.opus_state.value
        adopted_result.ds_adjudication_state = decision.ds_state.value
        adopted_result.ds_terminal_state = (
            execution.ds_result.terminal_state.value.lower()
        )
        adopted_result.speculative_review_policy = decision.review_policy.value
        adopted_result.speculative_alert_owner = (
            decision.alert_owner.value if decision.alert_owner is not None else ""
        )
        adopted_result.speculative_enabled = True
        adopted_result.writer_prompt_version = (
            OPUS_WRITER_PROMPT_VERSION
            if decision.adopted is AdoptedGenerator.OPUS
            else (
                execution.ds_result.prompt_version
                if decision.adopted is AdoptedGenerator.DS_FLASH
                else ""
            )
        )
        telemetry = execution.telemetry or speculative_telemetry.snapshot()
        adopted_result.opus_first_token_ms = telemetry.opus_first_token_ms
        adopted_result.opus_final_ms = telemetry.opus_final_ms
        adopted_result.ds_final_ms = telemetry.ds_final_ms
        adopted_result.adjudicated_at_ms = telemetry.adjudicated_at_ms
        adopted_result.probe_telemetry_enabled = True
        adopted_result.probe_kill_count = telemetry.probe_kill_count
        adopted_result.probe_kill_endpoints = list(
            telemetry.probe_kill_endpoints
        )
        adopted_result.probe_kill_kind = telemetry.probe_kill_kind
        adopted_result.probe_partial_output_before_kill = (
            telemetry.probe_partial_output_before_kill
        )
        adopted_result.ds_attempted = True
        adopted_result.ds_completed = (
            execution.ds_result.terminal_state is DSTerminalState.COMPLETED
        )
        adopted_result.ds_structural_passed = (
            adopted_result.ds_completed
            and execution.ds_result.structurally_valid
        )
        adopted_result.ds_adopted = (
            decision.adopted is AdoptedGenerator.DS_FLASH
        )
        adopted_result.ds_latency_ms = execution.ds_result.latency_ms
        adopted_result.ds_token_in = execution.ds_result.token_in
        adopted_result.ds_token_out = execution.ds_result.token_out
        adopted_result.archive_write_succeeded = archive_write_succeeded
        repair_observation = keyed_repair_observations.get(
            decision.adopted.value,
            next(
                iter(keyed_repair_observations.values()),
                None,
            ),
        )
        if repair_observation is not None:
            adopted_result.keyed_fragment_repair_attempted = bool(
                repair_observation.get("attempted")
            )
            adopted_result.keyed_fragment_repair_target_count = int(
                repair_observation.get("target_count") or 0
            )
            adopted_result.keyed_fragment_repair_applied_count = int(
                repair_observation.get("applied_count") or 0
            )
            adopted_result.keyed_fragment_repair_remaining_count = int(
                repair_observation.get("remaining_count") or 0
            )
            adopted_result.keyed_fragment_repair_latency_ms = int(
                repair_observation.get("latency_ms") or 0
            )
            adopted_result.keyed_fragment_repair_failure_reason = str(
                repair_observation.get("failure_reason") or ""
            )
        return adopted_result

    data: dict[str, Any] | None = None
    parse_diagnostics: dict[str, Any] = {}
    attempt_parse_error_types: list[str] = []
    attempt_raw_lengths: list[int] = []
    attempt_json_extract_failed: list[bool] = []
    retry_latency_ms = 0
    retry_used = False
    retry_count = 0
    for attempt_index in range(1 if _raw_override is not None else 2):
        retry_used_for_attempt = attempt_index == 1
        attempt_t0 = time.monotonic()
        attempt_prompt = prompt
        call_reason = f"writer_original_plan_{plan_index}"
        if retry_used_for_attempt:
            retry_used = True
            retry_count = 1
            attempt_prompt = prompt + "\n\n" + SINGLE_PLAN_JSON_RETRY_PROMPT
            call_reason = f"writer_original_plan_{plan_index}_json_retry"
        if _raw_override is not None:
            raw = _raw_override
        else:
            try:
                with llm_call_context(
                    call_reason=call_reason,
                    role="writer",
                    stage="WRITER",
                    writer_speculative_observer=(
                        speculative_telemetry if stream_probes else None
                    ),
                ):
                    raw = await chat(
                        system=SINGLE_PLAN_SYSTEM_PROMPT,
                        user=attempt_prompt,
                        role="writer",
                        temperature=_writer_temperature(
                            "retry"
                            if publish_retry_feedback
                            else "original"
                        ),
                        json_mode=True,
                    )
            except Exception as exc:
                return attach_probe_metrics(PlanWriteResult(
                    zero_index=zero_index,
                    failure_reason=f"writer_call_failed:{exc.__class__.__name__}",
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    writer_plan_retry_used=retry_used,
                    writer_plan_retry_count=retry_count,
                    writer_plan_attempt_count=attempt_index + 1,
                    writer_plan_attempt_parse_error_types=attempt_parse_error_types,
                    writer_plan_attempt_raw_lengths=attempt_raw_lengths,
                    writer_plan_attempt_json_extract_failed=attempt_json_extract_failed,
                    writer_plan_retry_latency_ms=retry_latency_ms,
                ))
        data, parse_diagnostics = _parse_single_plan_writer_output_with_diagnostics(raw)
        if retry_used_for_attempt:
            retry_latency_ms = int((time.monotonic() - attempt_t0) * 1000)
        attempt_parse_error_types.append(
            str(parse_diagnostics.get("parse_error_type") or "")
        )
        attempt_raw_lengths.append(int(parse_diagnostics.get("raw_length") or 0))
        attempt_json_extract_failed.append(
            bool(parse_diagnostics.get("json_extract_failed"))
        )
        if data is not None:
            break
    if data is None:
        parse_failure_diagnostics = dict(parse_diagnostics)
        parse_failure_diagnostics["retry_attempts_summary"] = {
            "attempt_count": len(attempt_raw_lengths),
            "retry_used": retry_used,
            "retry_count": retry_count,
            "parse_error_types": attempt_parse_error_types,
            "raw_lengths": attempt_raw_lengths,
            "json_extract_failed": attempt_json_extract_failed,
        }
        return attach_probe_metrics(PlanWriteResult(
            zero_index=zero_index,
            failure_reason="writer_output_not_parseable",
            latency_ms=int((time.monotonic() - t0) * 1000),
            parse_error_type=str(parse_diagnostics.get("parse_error_type") or ""),
            raw_length=int(parse_diagnostics.get("raw_length") or 0),
            json_extract_failed=bool(parse_diagnostics.get("json_extract_failed")),
            single_plan_unwrapped_plans_array=bool(
                parse_diagnostics.get("single_plan_unwrapped_plans_array")
            ),
            writer_plan_retry_used=retry_used,
            writer_plan_retry_count=retry_count,
            writer_plan_attempt_count=len(attempt_raw_lengths),
            writer_plan_attempt_parse_error_types=attempt_parse_error_types,
            writer_plan_attempt_raw_lengths=attempt_raw_lengths,
            writer_plan_attempt_json_extract_failed=attempt_json_extract_failed,
            writer_plan_retry_latency_ms=retry_latency_ms,
            parse_failure_diagnostics=parse_failure_diagnostics,
        ))
    retry_fields = {
        "parse_error_type": str(parse_diagnostics.get("parse_error_type") or ""),
        "raw_length": int(parse_diagnostics.get("raw_length") or 0),
        "json_extract_failed": bool(parse_diagnostics.get("json_extract_failed")),
        "writer_plan_retry_used": retry_used,
        "writer_plan_retry_count": retry_count,
        "writer_plan_attempt_count": len(attempt_raw_lengths),
        "writer_plan_attempt_parse_error_types": attempt_parse_error_types,
        "writer_plan_attempt_raw_lengths": attempt_raw_lengths,
        "writer_plan_attempt_json_extract_failed": attempt_json_extract_failed,
        "writer_plan_retry_latency_ms": retry_latency_ms,
    }

    assembly = _assemble_keyed_writer_plan(
        plan_index=plan_index,
        raw_fragments=data.get("poi_fragments"),
        route_plan=route_plan,
        structured_evidence_payload=structured_evidence_payload,
        composition_blueprint=composition_blueprint,
        validation_candidate_names=[
            candidate.name for candidate in retrieval.candidates
        ],
        weather_advisory_payload=weather_advisory_payload,
        raw_day_openings=data.get("day_openings"),
        accommodation=accommodation,
        transport=transport,
    )
    assembly_fields = {
        "keyed_fragment_count": len(assembly.fragments),
        "keyed_fragment_fallback_keys": assembly.fallback_keys,
        "keyed_fragment_ignored_keys": assembly.ignored_keys,
        "keyed_fragment_invalid_details": assembly.invalid_details,
        "keyed_day_opening_count": assembly.day_opening_count,
        "keyed_day_opening_dropped": assembly.day_opening_dropped,
    }
    if assembly.failure_reason:
        return attach_probe_metrics(PlanWriteResult(
            zero_index=zero_index,
            failure_reason=assembly.failure_reason,
            latency_ms=int((time.monotonic() - t0) * 1000),
            single_plan_unwrapped_plans_array=bool(
                parse_diagnostics.get("single_plan_unwrapped_plans_array")
            ),
            **retry_fields,
            **assembly_fields,
            sanitizer_actions=assembly.sanitizer_actions,
        ))

    summary_text, summary_rejection = _sanitize_summary_text(
        data.get("summary"),
        banned_names=sorted(
            {
                *(candidate.name for candidate in retrieval.candidates),
                *(
                    place.name
                    for day_group in route_plan.day_groups
                    for place in day_group.places
                ),
            },
            key=lambda value: (-len(value), value),
        ),
    )
    if summary_rejection:
        logger.info(
            "writer summary dropped plan=%d reason=%s",
            plan_index,
            summary_rejection,
        )
    plan = _merge_locked_place_fields(
        plan_name=_locked_plan_name(
            trip_request=trip_request,
            retrieval=retrieval,
            route_plan=route_plan,
            plan_index=plan_index,
            total_plans=1 + len(sibling_route_plans),
            composition_blueprint=composition_blueprint,
        ),
        plan_text=assembly.plan_text,
        route_plan=route_plan,
        retrieval=retrieval,
        composition_blueprint=composition_blueprint,
        poi_identity_result=poi_identity_result,
        budget_result=budget_result,
        poi_fragments=assembly.fragments,
        summary=summary_text,
        accommodation=accommodation,
        transport=transport,
    )
    plan, advice_metrics = _attach_sanitized_pretrip_advice(
        plan,
        data,
        pretrip_advice_payload,
    )
    sanitizer_actions = assembly.sanitizer_actions
    sibling_violations = [
        name
        for name in sibling_unique
        if name and (name in plan.plan_text or name in plan.plan_name)
    ]
    if sibling_violations:
        return attach_probe_metrics(PlanWriteResult(
            zero_index=zero_index,
            plan=plan,
            failure_reason="sibling_unique_poi_violation",
            latency_ms=int((time.monotonic() - t0) * 1000),
            single_plan_unwrapped_plans_array=bool(
                parse_diagnostics.get("single_plan_unwrapped_plans_array")
            ),
            **retry_fields,
            **assembly_fields,
            sibling_unique_poi_violations=sibling_violations,
            sanitizer_actions=sanitizer_actions,
            pretrip_advice_metrics=advice_metrics,
        ))
    if not plan.plan_text.strip():
        return attach_probe_metrics(PlanWriteResult(
            zero_index=zero_index,
            plan=plan,
            failure_reason="empty_plan_text",
            latency_ms=int((time.monotonic() - t0) * 1000),
            single_plan_unwrapped_plans_array=bool(
                parse_diagnostics.get("single_plan_unwrapped_plans_array")
            ),
            **retry_fields,
            **assembly_fields,
            sanitizer_actions=sanitizer_actions,
            pretrip_advice_metrics=advice_metrics,
        ))
    violations = route_plan_violations([plan], [route_plan])
    if violations:
        return attach_probe_metrics(PlanWriteResult(
            zero_index=zero_index,
            plan=plan,
            failure_reason="route_plan_violation",
            latency_ms=int((time.monotonic() - t0) * 1000),
            single_plan_unwrapped_plans_array=bool(
                parse_diagnostics.get("single_plan_unwrapped_plans_array")
            ),
            **retry_fields,
            **assembly_fields,
            sanitizer_actions=sanitizer_actions,
            pretrip_advice_metrics=advice_metrics,
        ))
    return attach_probe_metrics(PlanWriteResult(
        zero_index=zero_index,
        plan=plan,
        latency_ms=int((time.monotonic() - t0) * 1000),
        single_plan_unwrapped_plans_array=bool(
            parse_diagnostics.get("single_plan_unwrapped_plans_array")
        ),
        **retry_fields,
        **assembly_fields,
        sanitizer_actions=sanitizer_actions,
        pretrip_advice_metrics=advice_metrics,
    ))


async def generate_locked_plans_concurrently(
    trip_request: TripRequest,
    retrieval: RetrievalResult,
    route_plans: list[RoutePlan],
    *,
    poi_identity_results: list[PoiIdentityResult] | None = None,
    budget_results: list[BudgetResult] | None = None,
    composition_blueprints: list[CompositionBlueprint] | None = None,
    structured_evidence_payload: StructuredEvidencePayload | None = None,
    weather_advisory_payload: WeatherAdvisoryPayload | None = None,
    publish_retry_feedback: list[dict[str, Any]] | None = None,
    attachment_auth_map: FoodAttachmentAuthMap | None = None,
    accommodation: AccommodationSuggestion | None = None,
    transport: TransportSuggestion | None = None,
    pretrip_advice_payloads: list[PreTripAdvicePayload] | None = None,
    parallel: bool = True,
    workflow_deadline_monotonic: float | None = None,
    residual_reserve_seconds: float = 20.0,
    speculative_initial_generation: bool = True,
    speculative_adopted_archive_sink: list[SpeculativeArchiveRecord] | None = None,
) -> tuple[list[PlanOutput] | None, dict]:
    """Generate one keyed locked plan per route, optionally in parallel.

    Returns (plans, metrics). plans is None when per-plan Writer generation
    produced no publishable plan; callers should fail fast rather than invoking
    the legacy multi-plan Writer path.
    """
    if composition_blueprints is None:
        composition_blueprints = build_base_composition_blueprints(
            route_plans,
            trip_request,
        )
    if structured_evidence_payload is None:
        structured_evidence_payload = build_structured_evidence_payload(
            retrieval,
            route_plans=route_plans,
            composition_blueprints=composition_blueprints,
        )

    metrics = {
        "writer_plan_concurrency_used": bool(parallel),
        "writer_plan_concurrency_fallback_used": False,
        "writer_plan_index_alignment_passed": True,
        "writer_expected_plan_count": len(route_plans),
        "writer_generated_plan_count": 0,
        "writer_no_publishable_plans": False,
        "writer_plan_success_count": 0,
        "writer_plan_failure_count": 0,
        "writer_plan_failure_reasons": [],
        "writer_plan_failure_details": [],
        "single_plan_unwrapped_plans_array": False,
        "single_plan_unwrapped_plan_indexes": [],
        "writer_plan_retry_used": False,
        "writer_plan_retry_count": 0,
        "writer_plan_attempt_count": 0,
        "writer_plan_attempt_parse_error_types": [],
        "writer_plan_attempt_raw_lengths": [],
        "writer_plan_attempt_json_extract_failed": [],
        "writer_plan_retry_latency_ms": 0,
        "writer_output_not_parseable": False,
        "parse_error_type": "",
        "raw_length": 0,
        "json_extract_failed": False,
        "writer_plan_latencies_ms": [],
        "writer_plan_sibling_unique_poi_violations": [],
        "writer_plan_name_duplicate": False,
        "writer_plan_name_backend_owned": True,
        "writer_plan_overlap_ratio": None,
        "writer_initial_sanitizer_actions": [],
        "writer_initial_sanitizer_action_count": 0,
        "writer_action_plan_complete": False,
        "writer_action_contract_count": len(
            structured_evidence_payload.action_plan
        ),
        "writer_action_plan_missing_keys": [],
        "writer_action_plan_missing_count": 0,
        "writer_keyed_fragment_contract_enabled": True,
        "writer_keyed_fragment_count": 0,
        "writer_keyed_fragment_fallback_count": 0,
        "writer_keyed_fragment_fallback_keys": [],
        "writer_keyed_fragment_ignored_count": 0,
        "writer_keyed_fragment_ignored_keys": [],
        "writer_keyed_fragment_invalid_details": [],
        "writer_keyed_fragment_repair_attempted": False,
        "writer_keyed_fragment_repair_target_count": 0,
        "writer_keyed_fragment_repair_applied_count": 0,
        "writer_keyed_fragment_repair_remaining_count": 0,
        "writer_keyed_fragment_repair_latency_ms": 0,
        "writer_keyed_fragment_repair_failure_reason": "",
        "writer_day_opening_count": 0,
        "writer_day_opening_dropped_count": 0,
        "writer_day_opening_dropped_details": [],
        "writer_packing_groups_retained": 0,
        "writer_packing_items_retained": 0,
        "writer_tips_retained": 0,
        "writer_advice_dropped_reasons": {},
    }
    counts = [
        len(route_plans),
        len(poi_identity_results or route_plans),
        len(budget_results or route_plans),
        len(composition_blueprints or route_plans),
    ]
    if len(set(counts)) != 1:
        metrics["writer_plan_index_alignment_passed"] = False
        metrics["writer_plan_failure_count"] = len(route_plans)
        metrics["writer_plan_failure_reasons"] = ["writer_plan_index_alignment_failed"]
        metrics["writer_plan_failure_details"] = [
            {
                "plan_index": index + 1,
                "reason": "writer_plan_index_alignment_failed",
            }
            for index in range(len(route_plans))
        ]
        metrics["writer_no_publishable_plans"] = True
        return None, metrics

    missing_action_keys = missing_action_contract_keys(
        structured_evidence_payload.action_plan,
        route_plans,
    )
    metrics["writer_action_plan_missing_keys"] = [
        {
            "plan_index": plan_index,
            "day": day,
            "place_id": place_id,
        }
        for plan_index, day, place_id in missing_action_keys
    ]
    metrics["writer_action_plan_missing_count"] = len(missing_action_keys)
    metrics["writer_action_plan_complete"] = not missing_action_keys
    if missing_action_keys:
        failed_plan_indexes = sorted({
            plan_index
            for plan_index, _day, _place_id in missing_action_keys
        })
        metrics["writer_plan_failure_count"] = len(failed_plan_indexes)
        metrics["writer_plan_failed_plan_indexes"] = failed_plan_indexes
        metrics["writer_plan_failure_reasons"] = [
            "writer_action_plan_incomplete"
        ]
        metrics["writer_plan_failure_details"] = [
            {
                "reason": "writer_action_plan_incomplete",
                "plan_index": plan_index,
                "day": day,
                "place_id": place_id,
            }
            for plan_index, day, place_id in missing_action_keys
        ]
        metrics["writer_no_publishable_plans"] = True
        return None, metrics

    t0 = time.monotonic()
    tasks = []
    for zero_index, route_plan in enumerate(route_plans):
        siblings = [
            sibling
            for sibling_index, sibling in enumerate(route_plans)
            if sibling_index != zero_index
        ]
        tasks.append(_generate_one_locked_plan(
            zero_index=zero_index,
            trip_request=trip_request,
            retrieval=retrieval,
            route_plan=route_plan,
            sibling_route_plans=siblings,
            budget_result=(
                budget_results[zero_index]
                if budget_results and zero_index < len(budget_results)
                else None
            ),
            poi_identity_result=(
                poi_identity_results[zero_index]
                if poi_identity_results and zero_index < len(poi_identity_results)
                else None
            ),
            composition_blueprint=(
                composition_blueprints[zero_index]
                if composition_blueprints and zero_index < len(composition_blueprints)
                else None
            ),
            structured_evidence_payload=structured_evidence_payload,
            weather_advisory_payload=weather_advisory_payload,
            publish_retry_feedback=publish_retry_feedback,
            attachment_auth_map=attachment_auth_map,
            accommodation=accommodation,
            transport=transport,
            pretrip_advice_payload=_pretrip_payload_for_index(
                pretrip_advice_payloads,
                zero_index,
            ),
            workflow_deadline_monotonic=workflow_deadline_monotonic,
            residual_reserve_seconds=residual_reserve_seconds,
            speculative_initial_generation=speculative_initial_generation,
            speculative_adopted_archive_sink=(
                speculative_adopted_archive_sink
            ),
        ))
    if parallel:
        results = await asyncio.gather(*tasks)
    else:
        results = []
        for task in tasks:
            results.append(await task)
    metrics["writer_plan_parallel_wall_latency_ms"] = int(
        (time.monotonic() - t0) * 1000
    )
    metrics["writer_plan_latencies_ms"] = [result.latency_ms for result in results]
    probe_results = [
        result for result in results if result.probe_telemetry_enabled
    ]
    if probe_results:
        last_probe_result = next(
            (
                result
                for result in reversed(probe_results)
                if result.probe_kill_kind is not None
            ),
            None,
        )
        metrics.update({
            "probe_kill_count": sum(
                result.probe_kill_count for result in probe_results
            ),
            "probe_kill_endpoints": [
                endpoint
                for result in probe_results
                for endpoint in result.probe_kill_endpoints
            ],
            "probe_kill_kind": (
                last_probe_result.probe_kill_kind
                if last_probe_result is not None
                else None
            ),
            "probe_partial_output_before_kill": (
                last_probe_result.probe_partial_output_before_kill
                if last_probe_result is not None
                else None
            ),
        })
    speculative_results = [result for result in results if result.adjudication_reason]
    if speculative_results:
        # Current production has one plan. If that changes, any DS-authored
        # member makes the whole delivery mandatory-Review without per-plan
        # public or telemetry fields (design §14.1 ruling 3).
        speculative_result = next(
            (
                result
                for result in speculative_results
                if result.generator == AdoptedGenerator.DS_FLASH.value
            ),
            speculative_results[0],
        )
        metrics.update({
            "speculative_enabled": True,
            "generator": speculative_result.generator,
            "adjudication_reason": speculative_result.adjudication_reason,
            "opus_adjudication_state": speculative_result.opus_adjudication_state,
            "ds_adjudication_state": speculative_result.ds_adjudication_state,
            "ds_terminal_state": speculative_result.ds_terminal_state,
            "opus_first_token_ms": speculative_result.opus_first_token_ms,
            "opus_final_ms": speculative_result.opus_final_ms,
            "ds_final_ms": speculative_result.ds_final_ms,
            "adjudicated_at_ms": speculative_result.adjudicated_at_ms,
            "ds_attempted": speculative_result.ds_attempted,
            "ds_completed": speculative_result.ds_completed,
            "ds_structural_passed": speculative_result.ds_structural_passed,
            "ds_adopted": speculative_result.ds_adopted,
            "ds_latency_ms": speculative_result.ds_latency_ms,
            "ds_token_in": speculative_result.ds_token_in,
            "ds_token_out": speculative_result.ds_token_out,
            "writer_prompt_version": speculative_result.writer_prompt_version,
            "archive_write_succeeded": (
                speculative_result.archive_write_succeeded
            ),
            "speculative_review_policy": (
                speculative_result.speculative_review_policy
            ),
            "speculative_alert_owner": speculative_result.speculative_alert_owner,
        })
    sanitizer_actions = [
        _serialize_sanitizer_action(action)
        for result in results
        for action in result.sanitizer_actions
    ]
    metrics["writer_initial_sanitizer_actions"] = sanitizer_actions
    metrics["writer_initial_sanitizer_action_count"] = len(sanitizer_actions)
    metrics["writer_keyed_fragment_count"] = sum(
        result.keyed_fragment_count for result in results
    )
    fallback_keys = [
        key
        for result in results
        for key in result.keyed_fragment_fallback_keys
    ]
    ignored_keys = [
        key
        for result in results
        for key in result.keyed_fragment_ignored_keys
    ]
    metrics["writer_keyed_fragment_fallback_count"] = len(fallback_keys)
    metrics["writer_keyed_fragment_fallback_keys"] = [
        {"plan_index": key[0], "day": key[1], "place_id": key[2]}
        for key in fallback_keys
    ]
    metrics["writer_keyed_fragment_ignored_count"] = len(ignored_keys)
    metrics["writer_keyed_fragment_ignored_keys"] = [
        {"plan_index": key[0], "day": key[1], "place_id": key[2]}
        for key in ignored_keys
    ]
    metrics["writer_keyed_fragment_invalid_details"] = [
        detail
        for result in results
        for detail in result.keyed_fragment_invalid_details
    ]
    repair_results = [
        result for result in results if result.keyed_fragment_repair_attempted
    ]
    metrics["writer_keyed_fragment_repair_attempted"] = bool(repair_results)
    metrics["writer_keyed_fragment_repair_target_count"] = sum(
        result.keyed_fragment_repair_target_count for result in repair_results
    )
    metrics["writer_keyed_fragment_repair_applied_count"] = sum(
        result.keyed_fragment_repair_applied_count for result in repair_results
    )
    metrics["writer_keyed_fragment_repair_remaining_count"] = sum(
        result.keyed_fragment_repair_remaining_count for result in repair_results
    )
    metrics["writer_keyed_fragment_repair_latency_ms"] = sum(
        result.keyed_fragment_repair_latency_ms for result in repair_results
    )
    metrics["writer_keyed_fragment_repair_failure_reason"] = next(
        (
            result.keyed_fragment_repair_failure_reason
            for result in repair_results
            if result.keyed_fragment_repair_failure_reason
        ),
        "",
    )
    metrics["writer_day_opening_count"] = sum(
        result.keyed_day_opening_count for result in results
    )
    opening_dropped = [
        detail
        for result in results
        for detail in result.keyed_day_opening_dropped
    ]
    metrics["writer_day_opening_dropped_count"] = len(opening_dropped)
    metrics["writer_day_opening_dropped_details"] = opening_dropped
    dropped_reasons: dict[str, int] = {}
    for result in results:
        piece = result.pretrip_advice_metrics or {}
        metrics["writer_packing_groups_retained"] += int(
            piece.get("writer_packing_groups_retained") or 0
        )
        metrics["writer_packing_items_retained"] += int(
            piece.get("writer_packing_items_retained") or 0
        )
        metrics["writer_tips_retained"] += int(piece.get("writer_tips_retained") or 0)
        for reason, count in (
            piece.get("writer_advice_dropped_reasons") or {}
        ).items():
            dropped_reasons[reason] = dropped_reasons.get(reason, 0) + int(count)
    metrics["writer_advice_dropped_reasons"] = dropped_reasons
    failures = [result for result in results if result.failure_reason]
    successful_results = [
        result
        for result in results
        if result.plan is not None and not result.failure_reason
    ]
    metrics["writer_plan_success_count"] = len(results) - len(failures)
    metrics["writer_plan_failure_count"] = len(failures)
    metrics["writer_generated_plan_count"] = len(successful_results)
    metrics["writer_plan_successful_plan_indexes"] = [
        result.zero_index + 1 for result in successful_results
    ]
    metrics["writer_plan_sibling_unique_poi_violations"] = [
        {
            "plan_index": result.zero_index + 1,
            "names": result.sibling_unique_poi_violations,
        }
        for result in results
        if result.sibling_unique_poi_violations
    ]
    unwrapped_results = [
        result for result in results if result.single_plan_unwrapped_plans_array
    ]
    metrics["single_plan_unwrapped_plans_array"] = bool(unwrapped_results)
    metrics["single_plan_unwrapped_plan_indexes"] = [
        result.zero_index + 1 for result in unwrapped_results
    ]
    retry_results = [result for result in results if result.writer_plan_retry_used]
    metrics["writer_plan_retry_used"] = bool(retry_results)
    metrics["writer_plan_retry_count"] = sum(
        result.writer_plan_retry_count for result in results
    )
    metrics["writer_plan_attempt_count"] = sum(
        result.writer_plan_attempt_count for result in results
    )
    metrics["writer_plan_attempt_parse_error_types"] = [
        error_type
        for result in results
        for error_type in result.writer_plan_attempt_parse_error_types
    ]
    metrics["writer_plan_attempt_raw_lengths"] = [
        raw_length
        for result in results
        for raw_length in result.writer_plan_attempt_raw_lengths
    ]
    metrics["writer_plan_attempt_json_extract_failed"] = [
        json_extract_failed
        for result in results
        for json_extract_failed in result.writer_plan_attempt_json_extract_failed
    ]
    metrics["writer_plan_retry_latency_ms"] = sum(
        result.writer_plan_retry_latency_ms for result in results
    )
    final_parse_source = next(
        (
            result for result in results
            if result.writer_plan_retry_used or result.failure_reason == "writer_output_not_parseable"
        ),
        None,
    )
    if final_parse_source is not None:
        metrics["parse_error_type"] = final_parse_source.parse_error_type
        metrics["raw_length"] = final_parse_source.raw_length
        metrics["json_extract_failed"] = final_parse_source.json_extract_failed
    repairable_failure_reasons = {
        "route_plan_violation",
        "sibling_unique_poi_violation",
    }
    if failures:
        metrics["writer_plan_failed_plan_indexes"] = [
            result.zero_index + 1 for result in failures
        ]
        metrics["writer_plan_failure_reasons"] = [
            result.failure_reason for result in failures
        ]
        metrics["writer_plan_failure_details"] = [
            {
                "plan_index": result.zero_index + 1,
                "reason": result.failure_reason,
                **(
                    {"parse_error_type": result.parse_error_type}
                    if result.parse_error_type
                    else {}
                ),
                **({"raw_length": result.raw_length} if result.raw_length else {}),
                **(
                    {"json_extract_failed": result.json_extract_failed}
                    if result.json_extract_failed
                    else {}
                ),
                **(
                    result.parse_failure_diagnostics
                    if result.failure_reason == "writer_output_not_parseable"
                    else {}
                ),
                **(
                    {
                        "single_plan_unwrapped_plans_array": (
                            result.single_plan_unwrapped_plans_array
                        )
                    }
                    if result.single_plan_unwrapped_plans_array
                    else {}
                ),
                "writer_plan_retry_used": result.writer_plan_retry_used,
                "writer_plan_retry_count": result.writer_plan_retry_count,
                "writer_plan_attempt_count": result.writer_plan_attempt_count,
                "writer_plan_attempt_parse_error_types": (
                    result.writer_plan_attempt_parse_error_types
                ),
                "writer_plan_attempt_raw_lengths": (
                    result.writer_plan_attempt_raw_lengths
                ),
                "writer_plan_attempt_json_extract_failed": (
                    result.writer_plan_attempt_json_extract_failed
                ),
                "writer_plan_retry_latency_ms": result.writer_plan_retry_latency_ms,
            }
            for result in failures
        ]
        parse_failures = [
            result for result in failures
            if result.failure_reason == "writer_output_not_parseable"
        ]
        metrics["writer_output_not_parseable"] = bool(parse_failures)
        if parse_failures:
            first_parse_failure = parse_failures[0]
            metrics["parse_error_type"] = first_parse_failure.parse_error_type
            metrics["raw_length"] = first_parse_failure.raw_length
            metrics["json_extract_failed"] = first_parse_failure.json_extract_failed
            metrics.update(first_parse_failure.parse_failure_diagnostics)
    blocking_failures = [
        result
        for result in failures
        if result.plan is None
        or result.failure_reason not in repairable_failure_reasons
    ]
    if blocking_failures:
        if successful_results:
            metrics["writer_plan_partial_success_used"] = True
            return [
                result.plan
                for result in sorted(successful_results, key=lambda item: item.zero_index)
                if result.plan is not None
            ], metrics
        metrics["writer_no_publishable_plans"] = True
        return None, metrics
    if failures:
        metrics["writer_plan_concurrency_repairable_failures_used"] = True

    ordered: list[PlanOutput | None] = [None] * len(route_plans)
    for result in results:
        ordered[result.zero_index] = result.plan
    plans = [plan for plan in ordered if plan is not None]
    if len(plans) != len(route_plans):
        metrics["writer_plan_index_alignment_passed"] = False
        metrics["writer_plan_failure_count"] = len(route_plans) - len(plans)
        metrics["writer_generated_plan_count"] = len(plans)
        metrics["writer_no_publishable_plans"] = not plans
        return None, metrics
    names = [plan.plan_name for plan in plans]
    metrics["writer_plan_name_duplicate"] = len(set(names)) != len(names)
    metrics["writer_plan_overlap_ratio"] = _plan_overlap_ratio(plans)
    return plans, metrics


async def repair_plan(
    *,
    trip_request: TripRequest,
    retrieval_city: str,
    original_plan: PlanOutput,
    route_plan: RoutePlan,
    issues: list[GenerationIssue],
    budget_result: BudgetResult | None = None,
    poi_identity_result: PoiIdentityResult | None = None,
    composition_blueprint: CompositionBlueprint | None = None,
    validation_candidate_names: list[str] | None = None,
    plan_index: int = 0,
    return_result: bool = False,
    structured_evidence_payload: StructuredEvidencePayload | None = None,
    weather_advisory_payload: WeatherAdvisoryPayload | None = None,
) -> PlanOutput | RepairPlanResult | None:
    """Repair one target plan while preserving its locked route."""
    locked_day_names, locked_names, locked_ids = _locked_route_names(route_plan)
    locked_places = [
        place
        for day_group in route_plan.day_groups
        for place in day_group.places
    ]
    policy = build_route_name_policy(
        locked_places=locked_places,
        candidate_names=validation_candidate_names or [],
        identity_result=poi_identity_result,
        city_name=retrieval_city or trip_request.to_city,
    )
    route_names = policy.route_names
    context_names = policy.contextual_text_names
    disallowed_names = sorted(
        policy.forbidden_text_names,
        key=lambda value: (-len(value), value),
    )
    route_surface_disallowed_names = sorted(
        set(validation_candidate_names or []) - route_names,
        key=lambda value: (-len(value), value),
    )
    extraction_names = [*(validation_candidate_names or []), *route_names]

    def finish(result: RepairPlanResult) -> PlanOutput | RepairPlanResult | None:
        return result if return_result else result.plan

    issue_payload = [issue.model_dump(mode="json") for issue in issues]
    required_headings = [
        f"Day {day_group.day}｜"
        + " → ".join(place.name for place in day_group.places)
        for day_group in route_plan.day_groups
    ]
    prompt_parts = [
        (
            f"用户目的地：{trip_request.to_city}；检索城市：{retrieval_city}；"
            f"天数：{trip_request.days}；人数：{trip_request.people_count}"
        ),
        "人数与同行场景写作要求：\n" + _party_guidance(trip_request),
        "目标锁定路线和候选证据：\n"
        + _single_route_prompt(
            route_plan,
            plan_index=plan_index or None,
            validation_candidate_names=validation_candidate_names,
            structured_evidence_payload=structured_evidence_payload,
        ),
        render_weather_prompt(weather_advisory_payload),
        "必须逐字使用这些 Day 标题，不要改写：\n" + "\n".join(required_headings),
        (
            "Day section 约束：每个 Day section 只能出现该 Day locked names；"
            "其他 Day locked names 不能作为回顾、预告、附近、远眺、背景、顺路出现。"
            "contextual_names 只能作为正文语境，不得放入 plan_name、Day 标题、"
            "used_place_names 或 day_place_names。"
        ),
        "原始方案 JSON：\n"
        + original_plan.model_dump_json(
            exclude={"packing_checklist", "travel_tips"},
        ),
        "必须修复的 issues：\n" + json.dumps(issue_payload, ensure_ascii=False),
        "机器可读禁写清单：\n"
        + json.dumps(
            build_repair_forbidden_payload(
                locked_names=locked_names,
                contextual_names=list(context_names),
                disallowed_candidate_names=disallowed_names,
                issues=issues,
            ),
            ensure_ascii=False,
        ),
        (
            "请只输出单个 PlanOutput JSON 对象，字段只能包含 plan_name、plan_text。"
            "不要输出 used_place_names、day_place_names、used_place_ids、"
            "packing_checklist 或 travel_tips；"
            "结构字段由系统按锁定路线确定性回填。"
        ),
        REPAIR_HARD_CONSTRAINTS,
    ]
    if composition_blueprint is not None:
        prompt_parts.append(
            "目标行程组合蓝图：\n"
            + composition_blueprint.model_dump_json()
        )
    if budget_result is not None:
        prompt_parts.append("目标预算结果：\n" + budget_result.model_dump_json())
    if poi_identity_result is not None:
        prompt_parts.append(
            "目标 POI identity 关系：\n" + poi_identity_result.model_dump_json()
        )
    if _writer_strict_evidence_enabled():
        prompt_parts.append(_strict_evidence_prompt())
    prompt = "\n\n".join(prompt_parts)
    base_metrics = {
        "repair_prompt_issue_count": len(issues),
        "repair_prompt_disallowed_name_count": len(disallowed_names),
    }
    local_repair_candidate: PlanOutput | None = None
    local_repair_actions: list[RepairSanitizerAction] = []
    local_repair_metrics: dict[str, Any] = {}

    repair_base_text = _ensure_locked_route_text(
        original_plan.plan_text,
        route_plan,
        composition_blueprint,
    )
    local_text, local_actions = sanitize_repair_text(
        repair_base_text,
        issues=issues,
        disallowed_candidate_names=disallowed_names,
        locked_day_names=locked_day_names,
    )
    local_text, weather_local_actions = apply_weather_advisory_to_text(
        local_text,
        route_plan=route_plan,
        payload=weather_advisory_payload,
    )
    local_actions = [*local_actions, *weather_local_actions]
    if local_actions and local_text.strip():
        local_repaired = original_plan.model_copy(update={
            "plan_text": local_text,
            "used_place_ids": locked_ids,
            "used_place_names": locked_names,
            "day_place_names": locked_day_names,
            "composition_blueprint": composition_blueprint,
            "poi_identity_result": poi_identity_result,
            "budget_result": budget_result,
        })
        local_metrics = {
            **base_metrics,
            "repair_mode": "local_sanitizer",
            "writer_llm_repair_called": False,
            "writer_repair_local_delete_only_used": True,
            "writer_repair_sanitizer_action_count": len(local_actions),
        }
        local_repair_candidate = local_repaired
        local_repair_actions = local_actions
        local_repair_metrics = local_metrics
        local_outside_names: list[str] = []
        if validation_candidate_names:
            local_outside_names.extend(
                extract_claimed_names(local_repaired.plan_text, disallowed_names)
            )
            local_outside_names.extend(
                extract_claimed_names(local_repaired.plan_name, extraction_names)
            )
            local_outside_names.extend(
                extract_claimed_names(
                    _day_heading_text(local_repaired.plan_text),
                    extraction_names,
                )
            )
            local_outside_names = [
                name for name in local_outside_names
                if name in disallowed_names or name in route_surface_disallowed_names
            ]
            local_outside_names = list(dict.fromkeys(local_outside_names))
        if (
            not local_outside_names
            and not route_plan_violations([local_repaired], [route_plan])
            and not check_plan_blueprint_integrity([local_repaired], [route_plan])
        ):
            return finish(RepairPlanResult(
                plan=local_repaired,
                sanitizer_actions=local_actions,
                metrics=local_metrics,
            ))

    with llm_call_context(call_reason=f"writer_repair_plan_{plan_index or 'unknown'}"):
        raw = await chat(
            system=SYSTEM_PROMPT,
            user=prompt,
            role="writer",
            temperature=_writer_temperature("repair"),
            json_mode=True,
        )
    data = _parse_repair_output(raw)
    if data is None:
        logger.warning("Writer repair output not parseable")
        minimal_text = _minimal_locked_route_text(route_plan)
        if local_repair_candidate is not None and minimal_text.strip():
            minimal_text, minimal_actions = sanitize_repair_text(
                minimal_text,
                issues=issues,
                disallowed_candidate_names=disallowed_names,
                locked_day_names=locked_day_names,
            )
            minimal_text, weather_minimal_actions = apply_weather_advisory_to_text(
                minimal_text,
                route_plan=route_plan,
                payload=weather_advisory_payload,
            )
            minimal_actions = [*minimal_actions, *weather_minimal_actions]
            minimal_repaired = local_repair_candidate.model_copy(update={
                "plan_name": (
                    f"{retrieval_city or trip_request.to_city}锁定路线方案"
                    + (str(plan_index) if plan_index else "")
                ),
                "plan_text": minimal_text,
                "used_place_ids": locked_ids,
                "used_place_names": locked_names,
                "day_place_names": locked_day_names,
                "composition_blueprint": composition_blueprint,
                "poi_identity_result": poi_identity_result,
                "budget_result": budget_result,
            })
            if (
                not route_plan_violations([minimal_repaired], [route_plan])
                and not check_plan_blueprint_integrity(
                    [minimal_repaired],
                    [route_plan],
                )
            ):
                return finish(RepairPlanResult(
                    plan=minimal_repaired,
                    sanitizer_actions=[
                        *local_repair_actions,
                        *minimal_actions,
                        RepairSanitizerAction(
                            action="replace_with_locked_route_minimal_text",
                            target=f"plan_index:{plan_index}",
                            reason="writer_repair_output_not_parseable",
                            issue_reason=",".join(
                                sorted({issue.reason for issue in issues})
                            ),
                        ),
                    ],
                    metrics={
                        **local_repair_metrics,
                        "repair_mode": "deterministic_normalize",
                        "writer_llm_repair_called": True,
                        "writer_repair_minimal_locked_route_fallback_used": True,
                        "writer_repair_sanitizer_action_count": (
                            len(local_repair_actions) + len(minimal_actions) + 1
                        ),
                    },
                ))
        return finish(RepairPlanResult(
            failure_detail=build_repair_failure_detail(
                reason="writer_repair_output_not_parseable",
                plan_index=plan_index,
                issues=issues,
                allowed_route_names=sorted(route_names),
                contextual_route_names=sorted(context_names),
            ),
            metrics={
                "repair_prompt_issue_count": len(issues),
                "repair_prompt_disallowed_name_count": len(disallowed_names),
                "repair_mode": "llm_repair",
                "writer_llm_repair_called": True,
            },
        ))
    data.pop("packing_checklist", None)
    data.pop("travel_tips", None)
    repaired = _merge_locked_place_fields(
        plan_name=str(data.get("plan_name") or original_plan.plan_name),
        plan_text=str(data.get("plan_text") or ""),
        route_plan=route_plan,
        composition_blueprint=composition_blueprint,
        poi_identity_result=poi_identity_result,
        budget_result=budget_result,
        summary=original_plan.summary,
        accommodation=original_plan.accommodation,
        transport=original_plan.transport,
        packing_checklist=original_plan.packing_checklist,
        travel_tips=original_plan.travel_tips,
    )
    sanitized_text, sanitizer_actions = sanitize_repair_text(
        repaired.plan_text,
        issues=issues,
        disallowed_candidate_names=disallowed_names,
        locked_day_names=locked_day_names,
    )
    sanitized_text, weather_actions = apply_weather_advisory_to_text(
        sanitized_text,
        route_plan=route_plan,
        payload=weather_advisory_payload,
    )
    sanitizer_actions = [*sanitizer_actions, *weather_actions]
    repaired = repaired.model_copy(update={
        "plan_text": _ensure_locked_route_text(
            sanitized_text,
            route_plan,
            composition_blueprint,
        )
    })
    metrics = {
        **base_metrics,
        "repair_mode": "llm_repair",
        "writer_llm_repair_called": True,
        "writer_repair_sanitizer_action_count": len(sanitizer_actions),
    }
    if not repaired.plan_text.strip():
        return finish(RepairPlanResult(
            failure_detail=build_repair_failure_detail(
                reason="empty_plan_text",
                plan_index=plan_index,
                issues=issues,
                allowed_route_names=sorted(route_names),
                contextual_route_names=sorted(context_names),
            ),
            sanitizer_actions=sanitizer_actions,
            metrics=metrics,
        ))
    if validation_candidate_names:
        outside_names = []
        outside_names.extend(
            extract_claimed_names(repaired.plan_text, disallowed_names)
        )
        outside_names.extend(
            extract_claimed_names(
                repaired.plan_name,
                extraction_names,
            )
        )
        outside_names.extend(
            extract_claimed_names(
                _day_heading_text(repaired.plan_text),
                extraction_names,
            )
        )
        outside_names = [
            name for name in outside_names
            if name in disallowed_names or name in route_surface_disallowed_names
        ]
        outside_names = list(dict.fromkeys(outside_names))
        if outside_names:
            logger.warning(
                "Writer repair mentioned route-outside candidate names: %s",
                outside_names,
            )
            return finish(RepairPlanResult(
                failure_detail=build_repair_failure_detail(
                    reason="route_outside_candidate_after_repair",
                    plan_index=plan_index,
                    issues=issues,
                    route_outside_names=outside_names,
                    allowed_route_names=sorted(route_names),
                    contextual_route_names=sorted(context_names),
                ),
                sanitizer_actions=sanitizer_actions,
                metrics=metrics,
            ))
    violations = route_plan_violations([repaired], [route_plan])
    if violations:
        logger.warning(
            "Writer repair failed locked-route validation: %s",
            json.dumps(violations, ensure_ascii=False),
        )
        return finish(RepairPlanResult(
            failure_detail=build_repair_failure_detail(
                reason="route_plan_violation_after_repair",
                plan_index=plan_index,
                issues=issues,
                route_violation_reasons=[
                    str(violation.get("reason") or "")
                    for violation in violations
                ],
                allowed_route_names=sorted(route_names),
                contextual_route_names=sorted(context_names),
            ),
            sanitizer_actions=sanitizer_actions,
            metrics=metrics,
        ))
    return finish(RepairPlanResult(
        plan=repaired,
        sanitizer_actions=sanitizer_actions,
        metrics=metrics,
    ))


async def generate(
    trip_request: TripRequest,
    retrieval: RetrievalResult,
    route_plans: list[RoutePlan] | None = None,
    poi_identity_results: list[PoiIdentityResult] | None = None,
    budget_results: list[BudgetResult] | None = None,
    composition_blueprints: list[CompositionBlueprint] | None = None,
    structured_evidence_payload: StructuredEvidencePayload | None = None,
    weather_advisory_payload: WeatherAdvisoryPayload | None = None,
    publish_retry_feedback: list[dict[str, Any]] | None = None,
    attachment_auth_map: FoodAttachmentAuthMap | None = None,
    accommodation: AccommodationSuggestion | None = None,
    transport: TransportSuggestion | None = None,
    pretrip_advice_payloads: list[PreTripAdvicePayload] | None = None,
) -> list[PlanOutput]:
    """Generate the requested locked plans from retrieval results."""
    if route_plans and composition_blueprints is None:
        composition_blueprints = build_base_composition_blueprints(
            route_plans,
            trip_request,
        )
    user_prompt = _build_user_prompt(
        trip_request,
        retrieval,
        route_plans=route_plans,
        composition_blueprints=composition_blueprints,
        structured_evidence_payload=structured_evidence_payload,
        weather_advisory_payload=weather_advisory_payload,
        publish_retry_feedback=publish_retry_feedback,
        attachment_auth_map=attachment_auth_map,
        pretrip_advice_payloads=pretrip_advice_payloads,
    )
    logger.debug("Final Writer prompt length: %d chars", len(user_prompt))

    data = None
    for attempt in range(2):
        prompt = user_prompt
        if attempt:
            prompt += "\n\n上一次输出不是合法 JSON。请只输出一个 JSON 对象，不要 Markdown、解释文字或代码块。"
        with llm_call_context(
            call_reason=f"writer_legacy_full_plan_attempt_{attempt + 1}",
            attempt=attempt + 1,
        ):
            raw = await chat(
                system=SYSTEM_PROMPT,
                user=prompt,
                role="writer",
                temperature=(
                    _writer_temperature(
                        "retry"
                        if publish_retry_feedback
                        else "original"
                    )
                    if attempt == 0
                    else _writer_temperature("retry")
                ),
                json_mode=True,
            )
        logger.info(
            "Final Writer raw output length: %d attempt=%d",
            len(raw),
            attempt + 1,
        )
        data = _parse_writer_output(raw)
        if data is not None:
            break
        logger.warning("Final Writer output not parseable attempt=%d", attempt + 1)
    if data is None:
        logger.error("Final Writer output not parseable after retry")
        return []

    expected_plan_count = len(route_plans) if route_plans else 2
    raw_plans = data.get("plans", [])
    if not isinstance(raw_plans, list):
        raw_plans = []
    plans = []
    for p in raw_plans[:expected_plan_count]:
        if not isinstance(p, dict):
            continue
        plan_index = len(plans)
        route_plan = (
            route_plans[plan_index]
            if route_plans and plan_index < len(route_plans)
            else None
        )
        plan = _merge_locked_place_fields(
            plan_name=str(p.get("plan_name") or ""),
            plan_text=str(p.get("plan_text") or ""),
            summary=_sanitize_summary_text(
                p.get("summary"),
                banned_names=sorted(
                    {candidate.name for candidate in retrieval.candidates},
                    key=lambda value: (-len(value), value),
                ),
            )[0],
            route_plan=route_plan,
            retrieval=retrieval,
            composition_blueprint=(
                composition_blueprints[plan_index]
                if composition_blueprints and plan_index < len(composition_blueprints)
                else None
            ),
            poi_identity_result=(
                poi_identity_results[plan_index]
                if poi_identity_results and plan_index < len(poi_identity_results)
                else None
            ),
            budget_result=(
                budget_results[plan_index]
                if budget_results and plan_index < len(budget_results)
                else None
            ),
            accommodation=accommodation,
            transport=transport,
        )
        plan, _advice_metrics = _attach_sanitized_pretrip_advice(
            plan,
            p,
            _pretrip_payload_for_index(pretrip_advice_payloads, plan_index),
        )
        if route_plan is not None:
            weather_text, _ = apply_weather_advisory_to_text(
                plan.plan_text,
                route_plan=route_plan,
                payload=weather_advisory_payload,
            )
            plan = plan.model_copy(update={"plan_text": weather_text})
        plans.append(plan)

    logger.info("Final Writer produced %d plans", len(plans))
    return plans
