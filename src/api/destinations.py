"""Destinations API — public directory for supported cinematic cities."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["destinations"])

# 开源版目前种子数据库仅包含【重庆】的 POI 与实景数据
# 如需扩展其他城市，可向数据库 travel_canonical_place 导入数据并在此处激活
CITIES_DATA: list[dict[str, Any]] = [
    {
        "id": "chongqing",
        "name": "重庆",
        "en_name": "Chongqing",
        "iata": "CKG",
        "region": "西南",
        "coordinates": {"lat": 29.56301, "lng": 106.551557},
        "map_label_offset": {"x": 10, "y": 6},
        "tags": ["8D魔幻", "赛博朋克", "火锅之都", "江畔夜景"],
        "quality": {"canonical_pass": True, "evidence_pass": True, "last_check_at": None},
        "card_cover_url": "/city-placeholder.svg",
        "background_image_url": "https://images.unsplash.com/photo-1548685913-fe6678babe8d?w=1600&auto=format&fit=crop&q=80",
        "reference_images": [],
    },
]


@router.get("/destinations")
@router.get("/api/destinations")
async def get_destinations() -> dict[str, Any]:
    return {
        "success": True,
        "destinations": CITIES_DATA,
        "total": len(CITIES_DATA),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
