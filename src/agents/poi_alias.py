"""Deterministic POI identity relations for locked itinerary validation."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from src.agents.schema import (
    CandidatePlace,
    PoiIdentityRelation,
    PoiIdentityRelationType,
    PoiIdentityResult,
    RoutePlan,
)

_WEAK_CITY_PREFIXES = ("成都", "重庆", "福州", "杭州", "厦门", "上海", "北京", "广州", "深圳")
ALIAS_SUFFIXES = ("景区", "风景区", "旅游区", "街区", "历史文化街区", "老街")
_DISTINCT_SUFFIXES = ("公园", "博物馆", "酒店", "餐厅", "火锅", "咖啡", "店")
_PARENT_TYPES = {"area", "district", "commercial_area", "business_area", "market"}
_CHILD_MARKERS = ("最美转角", "机位", "打卡点", "观景台", "码头", "入口", "小店")


@dataclass(frozen=True)
class RouteNamePolicy:
    route_names: set[str]
    contextual_text_names: set[str]
    forbidden_text_names: set[str]
    contextual_only_names: set[str]


def normalize_place_name(name: str) -> str:
    """Normalize only harmless decoration, not semantic POI suffixes."""
    value = re.sub(r"\s+", "", name or "")
    value = value.strip("（）()【】[]")
    for prefix in _WEAK_CITY_PREFIXES:
        if value.startswith(prefix) and len(value) > len(prefix) + 2:
            value = value[len(prefix):]
            break
    return value


def _strip_alias_suffix(name: str) -> str:
    value = normalize_place_name(name)
    for suffix in ALIAS_SUFFIXES:
        if value.endswith(suffix) and len(value) > len(suffix) + 1:
            return value[: -len(suffix)]
    return value


def _has_distinct_suffix(name: str) -> bool:
    return any(normalize_place_name(name).endswith(suffix) for suffix in _DISTINCT_SUFFIXES)


def _relation_reason(relation: PoiIdentityRelationType) -> str:
    return {
        "canonical_same": "same locked POI name",
        "alias_same": "safe normalized alias",
        "parent_child": "child point may be mentioned only as context",
        "nearby_distinct": "similar or nearby name but not interchangeable",
        "unknown": "insufficient evidence for identity equivalence",
    }[relation]


def classify_relation(
    locked: CandidatePlace,
    candidate: CandidatePlace,
) -> PoiIdentityRelationType:
    """Classify candidate relative to a locked route place."""
    if locked.place_id == candidate.place_id or locked.name == candidate.name:
        return "canonical_same"
    if (
        locked.canonical_place_id is not None
        and candidate.canonical_place_id is not None
        and locked.canonical_place_id == candidate.canonical_place_id
    ):
        return "alias_same"

    locked_norm = normalize_place_name(locked.name)
    candidate_norm = normalize_place_name(candidate.name)
    if not locked_norm or not candidate_norm:
        return "unknown"

    if locked_norm == candidate_norm:
        return "unknown"

    if _strip_alias_suffix(locked_norm) == _strip_alias_suffix(candidate_norm):
        return "unknown"

    if _has_distinct_suffix(locked_norm) != _has_distinct_suffix(candidate_norm):
        if locked_norm in candidate_norm or candidate_norm in locked_norm:
            return "nearby_distinct"

    locked_is_parent = (
        locked.place_type in _PARENT_TYPES
        or any(locked_norm.endswith(suffix) for suffix in ALIAS_SUFFIXES)
    )
    candidate_looks_child = (
        any(marker in candidate_norm for marker in _CHILD_MARKERS)
        or candidate.place_type in {"photo_spot", "snack", "cafe", "restaurant"}
    )
    if locked_is_parent and candidate_looks_child:
        evidence = " ".join(
            str(item.get("reason", ""))
            for item in [*candidate.top_reasons, *candidate.warnings]
            if isinstance(item, dict)
        )
        if locked_norm in evidence or candidate_norm in evidence or locked_norm[:3] in candidate_norm:
            return "parent_child"

    if locked_norm in candidate_norm or candidate_norm in locked_norm:
        return "unknown"

    overlap = set(locked_norm) & set(candidate_norm)
    if len(overlap) >= min(3, len(candidate_norm), len(locked_norm)):
        return "nearby_distinct"

    return "unknown"


def build_poi_identity_results(
    route_plans: list[RoutePlan],
    candidates: list[CandidatePlace],
) -> list[PoiIdentityResult]:
    """Build identity relations for every locked route plan."""
    results: list[PoiIdentityResult] = []
    for route_plan in route_plans:
        locked_places = [
            place
            for day_group in route_plan.day_groups
            for place in day_group.places
        ]
        # A locked route stop can never be demoted to another stop's
        # parent_child context or nearby_distinct forbidden name: its route
        # identity is settled by Route Planning, not by pairwise similarity.
        locked_ids = {
            place.place_id for place in locked_places if place.place_id is not None
        }
        locked_names = {place.name for place in locked_places}
        relations: list[PoiIdentityRelation] = []
        for locked in locked_places:
            for candidate in candidates:
                if (
                    candidate.place_id in locked_ids
                    or candidate.name in locked_names
                ):
                    continue
                relation = classify_relation(locked, candidate)
                if relation in {"canonical_same", "unknown"}:
                    continue
                relations.append(PoiIdentityRelation(
                    source_name=locked.name,
                    target_name=candidate.name,
                    relation=relation,
                    reason=_relation_reason(relation),
                ))
        results.append(PoiIdentityResult(
            plan_label=route_plan.label,
            relations=relations,
        ))
    return results


def accepted_route_names(
    locked_names: set[str],
    identity_result: PoiIdentityResult | None,
) -> set[str]:
    """Names allowed in route nodes, titles, used places, and day_place_names."""
    accepted = set(locked_names)
    if identity_result is None:
        return accepted
    for relation in identity_result.relations:
        if (
            relation.source_name in locked_names
            and relation.relation in {"canonical_same", "alias_same"}
        ):
            accepted.add(relation.target_name)
    return accepted


def contextual_names(
    locked_names: set[str],
    identity_result: PoiIdentityResult | None,
) -> set[str]:
    """Names allowed only in prose context under a locked parent."""
    if identity_result is None:
        return set()
    return {
        relation.target_name
        for relation in identity_result.relations
        if relation.source_name in locked_names
        and relation.relation == "parent_child"
    }


def _cjk_count(value: str) -> int:
    return sum(1 for char in value if "\u4e00" <= char <= "\u9fff")


def _is_nontrivial_context_name(value: str) -> bool:
    cleaned = re.sub(r"\s+", "", value or "")
    return _cjk_count(cleaned) >= 2 or len(cleaned) >= 3


def _city_prefix_variants(city_name: str) -> set[str]:
    city = re.sub(r"\s+", "", city_name or "")
    if not city:
        return set()
    variants = {city}
    if city.endswith("市") and len(city) > 1:
        variants.add(city[:-1])
    elif _cjk_count(city) >= 2:
        variants.add(city + "市")
    return variants


def _generated_contextual_names(
    locked_places: list[CandidatePlace],
    *,
    city_name: str = "",
) -> dict[str, set[str]]:
    generated: dict[str, set[str]] = {}

    def add(source_name: str, value: str) -> None:
        cleaned = re.sub(r"\s+", "", value or "").strip("：:，,、;；")
        if not cleaned:
            return
        generated.setdefault(cleaned, set()).add(source_name)

    city_prefixes = _city_prefix_variants(city_name)
    for place in locked_places:
        locked_name = re.sub(r"\s+", "", place.name or "")
        stripped_alias = _strip_alias_suffix(locked_name)
        if stripped_alias != locked_name:
            add(place.name, stripped_alias)
        for prefix in city_prefixes:
            if locked_name.startswith(prefix) and len(locked_name) > len(prefix):
                add(place.name, locked_name[len(prefix):])
        for match in re.finditer(r"[（(]([^（）()]+)[）)]", place.name or ""):
            add(place.name, match.group(1))
    return generated


def build_route_name_policy(
    *,
    locked_places: list[CandidatePlace],
    candidate_names: list[str],
    identity_result: PoiIdentityResult | None,
    city_name: str = "",
) -> RouteNamePolicy:
    """Build shared route/context/forbidden name surfaces for locked routes."""
    locked_names = {place.name for place in locked_places}
    route_names = accepted_route_names(locked_names, identity_result)
    context_names = contextual_names(locked_names, identity_result)
    candidate_counts = Counter(name for name in candidate_names if name)
    candidate_name_set = set(candidate_counts)

    for name, source_names in _generated_contextual_names(
        locked_places,
        city_name=city_name,
    ).items():
        if candidate_counts.get(name, 0) != 1:
            # Generated short forms (city-prefix strip, parenthetical base,
            # alias-suffix strip) are still contextual-only for locked-route
            # order checks even when the short name is not itself a candidate
            # row, or appears more than once as free text.
            if (
                name not in route_names
                and name not in locked_names
                and _is_nontrivial_context_name(name)
                and len(source_names) == 1
            ):
                context_names.add(name)
            continue
        if not _is_nontrivial_context_name(name):
            continue
        if len(source_names) != 1:
            continue
        if name in route_names:
            continue
        if name in locked_names:
            continue
        context_names.add(name)

    normalized_locked = {
        re.sub(r"\s+", "", name): name
        for name in locked_names
        if name
    }
    parenthetical_by_alias: dict[str, set[str]] = {}
    for locked_name in locked_names:
        for match in re.finditer(r"[（(]([^（）()]+)[）)]", locked_name or ""):
            alias = re.sub(r"\s+", "", match.group(1))
            if alias:
                parenthetical_by_alias.setdefault(alias, set()).add(locked_name)
    city_prefixes = _city_prefix_variants(city_name)

    for candidate_name in candidate_name_set:
        if candidate_name in route_names or candidate_name in locked_names:
            continue
        if not _is_nontrivial_context_name(candidate_name):
            continue
        candidate_norm = re.sub(r"\s+", "", candidate_name)
        if not candidate_norm:
            continue
        matching_locked = {
            locked_name
            for locked_norm, locked_name in normalized_locked.items()
            if candidate_norm in locked_norm and candidate_norm != locked_norm
        }
        if not matching_locked:
            continue

        parenthetical_sources = parenthetical_by_alias.get(candidate_norm, set())
        city_prefix_sources = {
            locked_name
            for locked_norm, locked_name in normalized_locked.items()
            for prefix in city_prefixes
            if prefix and locked_norm == f"{prefix}{candidate_norm}"
        }
        generated_sources = parenthetical_sources | city_prefix_sources

        # Multi-source short forms are ambiguous: never route, never contextual.
        if len(matching_locked) > 1 or len(generated_sources) > 1:
            continue
        if candidate_norm in parenthetical_by_alias and len(parenthetical_sources) == 1:
            context_names.add(candidate_name)
            continue
        if city_prefix_sources and len(city_prefix_sources) == 1:
            context_names.add(candidate_name)
            continue
        if candidate_name in context_names:
            continue
        # Remaining unique nested substring of a single locked name may be a
        # route-safe short form (legacy v0.6.25 behavior).
        route_names.add(candidate_name)

    forbidden_text_names = candidate_name_set - route_names - context_names
    contextual_only_names = context_names - route_names
    return RouteNamePolicy(
        route_names=route_names,
        contextual_text_names=context_names,
        forbidden_text_names=forbidden_text_names,
        contextual_only_names=contextual_only_names,
    )
