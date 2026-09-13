"""User-facing notices for Route Planning outcomes."""

ROUTE_DEGRADATION_NOTICE = "路线规划服务暂时不可用，以下行程未经路线优化"
SHORTENED_ROUTE_NOTICE = (
    "部分方案因同区白天可用地点不足，已按可行路线缩短天数"
)
MISSING_ALTERNATIVE_NOTICE = (
    "另一套方案因同区白天可用地点不足未生成"
)
NO_USABLE_ROUTE_NOTICE = (
    "当前候选地点无法组成包含白天活动的完整同区路线，请调整需求后重试"
)
ACCOMMODATION_FALLBACK_NOTICE = (
    "未能定位你填写的住宿位置，已改为按行程推荐住宿区域"
)
ACCOMMODATION_UNRESOLVED_NOTICE = "未能确认你填写的住宿位置，请核对酒店名称或地址后重试"
COUPLED_ROUTE_FAILURE_NOTICES = {
    "ACCOMMODATION_UNRESOLVED": ACCOMMODATION_UNRESOLVED_NOTICE,
    "ROUTE_SEARCH_EXHAUSTED": "在本次规划范围内未找到满足住宿往返和游玩时间的完整行程，请调整需求后重试",
}
TRANSPORT_STATIC_FALLBACK_NOTICE = (
    "大交通查询暂时不可用，出行建议为预估值仅供参考"
)
