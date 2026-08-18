# 数据采集管道

本文档定义 yuntu-travel 的数据采集、筛选、LLM 提纯和入库主流程。带有
“MVP”字样的固定重庆关键词、Top 10 和全量刷新描述是历史基线；当前多城市
批次、关键词和质量 Gate 以 `src/jobs/city_*`、
`src/pipeline/*` 及 canonical SQL 为准。

## 1. 采集管道总览

```
CLI 脚本 / 内部采集接口触发
    ↓ 按关键词搜索
小红书搜索列表 API
    ↓ 硬过滤 + rank_score 排序
取 Top 10
    ↓ 逐条调详情接口
获取笔记正文 + 图片
    ↓ 存入 travel_raw_item
LLM 提纯（Extract, v0.6.1 城市过滤）
    ↓ 输出结构化 JSON
写入 travel_content / travel_place / mention / fact
    ↓ POI 坐标解析（v0.6.1 自动化）
调用高德 geocode + POI search（智能回退）
    ↓ 写入 longitude/latitude/adcode
travel_place (poi_resolution_status=resolved)
    ↓ 刷新聚合（只进 resolved 地点）
travel_place_summary
```

v0.6.1 起，采集管道包含自动 POI 坐标解析步骤，worker 自动执行 `Crawl → Extract → POI_RESOLVE → Refresh`。

## 2. 小红书搜索参数（MVP 历史基线）

MVP 阶段固定 5 个关键词，硬编码：

```python
CHONGQING_KEYWORDS = [
    "重庆旅游",
    "重庆citywalk",
    "重庆两天一夜",
    "重庆美食攻略",
    "重庆避坑",
]
```

每个关键词取搜索结果的前 10 条（经过筛选后），总计约 50 条 raw_item。

v0.2 起，外层 Hermes 可通过 `docs/internal-crawl-job-design.md` 定义的内部接口触发一次采集运行。该接口只包装现有脚本，不改变本文件定义的搜索、筛选、提纯和入库规则。

## 3. 筛选规则

### 3.1 硬过滤（不满足直接丢弃）

| 条件 | 原因 |
|------|------|
| `model_type == "note"` | 排除 hot_query 类型 |
| `note_card.type == "normal"` | 排除 video，视频没正文可提纯 |
| `safe_int(collected_count) >= 50` | 收藏过低大概率非攻略帖；字段缺失或解析失败时按 0 处理 |
| `len(image_list) >= 3` | 多图才可能是攻略 |

### 3.2 排序公式

```python
def safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default

score = safe_int(collected_count) * 2 + safe_int(liked_count) * 1 + safe_int(shared_count) * 1.5
```

- 收藏权重最高（收藏 = 用户认为有实操价值），按 score 降序取 Top 10
- `liked_count` / `collected_count` / `shared_count` 缺失、空串或解析失败时按 0 处理，不因单个统计字段异常丢弃整条 note

### 3.3 采集流程

1. 搜索列表 API 返回候选列表
2. 应用硬过滤
3. 计算 rank_score 排序
4. 取 Top 10
5. 逐条调详情接口获取正文（`raw_text`）
6. 存入 `travel_raw_item`（`raw_json` = 详情接口完整返回，`raw_text` = 正文）

## 4. LLM 提纯规范

### 4.1 提纯目标

从一条小红书笔记中提取：

- 内容摘要（content_summary）
- 提到的地点列表（places）
- 每个地点的推荐理由 / 避坑提醒
- 路线顺序（如有）

### 4.2 输出 JSON 格式

```json
{
  "title": "往返重庆N次，还是最爱南滨路",
  "content_summary": "推荐南滨路 citywalk 路线，从黄桷垭老街到龙门浩，全程下坡不累",
  "tags": ["citywalk", "拍照", "慢旅行"],
  "content_type_tags": ["攻略", "路线"],
  "places": [
    {
      "name": "黄桷垭老街",
      "place_type": "attraction",
      "mention_type": "recommend",
      "sentiment": "positive",
      "reason": "文艺老街，适合起步",
      "evidence_text": "从黄桷垭老街出发，沿途都是老建筑",
      "route_order": 1,
      "confidence": 0.9
    },
    {
      "name": "黄葛古道",
      "place_type": "attraction",
      "mention_type": "recommend",
      "sentiment": "positive",
      "reason": "全程下坡，相对不累，适合 citywalk",
      "evidence_text": "一定是先黄桷垭老街，再黄葛古道，这样黄葛古道全程下坡不累",
      "route_order": 2,
      "confidence": 0.9
    }
  ]
}
```

### 4.3 字段说明

| 字段 | 用途 |
|------|------|
| `reason` | 展示给用户的推荐理由，简洁 |
| `evidence_text` | 原文摘录，用于溯源和复盘 |
| `route_order` | 路线顺序，无路线时为 null |
| `confidence` | LLM 对地点匹配的信心，0-1 |

### 4.4 Prompt 版本管理

- 版本号格式：`xhs_full_v1`、`xhs_full_v2_city_filter`
- 每次修改 Prompt 必须递增版本号
- `travel_extract_log.extract_prompt_version` 记录版本，便于 A/B 对比

**v0.6.1 城市过滤升级**:
- v1 → v2_city_filter：新增城市边界过滤规则
- 验证结果：跨城市污染 0%，召回率仅降 2.3%

### 4.5 POI 坐标解析（v0.6.1 自动化）

Extract 完成后，worker 自动执行 `POI_RESOLVE` 步骤为地点获取坐标。

**解析策略（智能回退）**：

1. **Geocode 优先**：调用高德地理编码 API
   - 输入："城市名+地点名"（如"重庆解放碑"）
   - 成功：写入 `longitude`、`latitude`、`adcode`，标记 `poi_resolution_status='resolved'`
   - 失败（30001/too broad/跨城市）：进入步骤 2

2. **POI 文本搜索回退**：调用高德 POI 搜索 API
   - 限定城市范围（`citylimit=true`）
   - 模糊匹配地点名称（`_poi_name_matches` 护栏防误匹配）
   - 成功：写入坐标，标记 `resolved`
   - 失败：标记 `unresolvable`

**跨城市护栏**：
- adcode 前缀检查（重庆支持 `5001xx` 主城 + `5002xx` 郊县双前缀）
- `resolved_city` 名称匹配验证
- 不匹配时拒绝并标记 `unresolvable`（防止跨城市污染）

**性能指标（v0.6.1）**：
- POI 解析成功率：**77%**（基线 18%）
- 坐标覆盖率：**76%**（1760/2314 个地点有坐标）
- 智能回退救回：451 个原 unresolvable

**失败处理**：
- 单点解析失败记录 `pending` 或 `unresolvable`，脚本仍返回 0（不阻塞后续步骤）
- 系统性失败（脚本非 0 退出）不继续 Refresh，避免 NULL 坐标污染 summary

## 5. 入库流程

提纯完成后，按以下顺序写入数据库：

```
1. travel_extract_log   ← 记录本次提纯（model、prompt_version、token、status）
2. travel_content       ← 写入 title、content_summary、tags、hot_score
3. travel_place         ← 对每个 place，去重后 upsert
4. travel_content_place_mention ← 写入 content↔place 关系
5. travel_place_fact    ← 写入 recommendation / warning 类 fact
6. travel_place_summary ← 刷新聚合（mention_count、top_reasons、recommend_score）
```

### 5.1 地点去重策略

- 按 `(city, normalized_name)` 判重
- `normalized_name` = 去空格、去括号、统一繁简体
- 匹配到已有地点则复用 `place_id`，不重复创建

### 5.2 Summary 刷新逻辑

POI_RESOLVE 步骤成功后自动触发 summary 刷新（v0.6.1）。

**过滤规则（v0.6.1 严格准入）**：
- **只汇总 `poi_resolution_status='resolved'` 的地点**（有坐标）
- `pending` 和 `unresolvable` 不进入 summary（防止 NULL 坐标污染路线规划）

聚合字段：

```sql
-- mention_count_30d：近 30 天该地点被多少条 content 提及
-- positive_count_30d：近 30 天正向提及数
-- top_reasons：聚合所有 mention 的 reason（优先）或 mention_context
-- recommend_score：基于 mention_count + positive_ratio + source_count 综合打分
```

MVP 阶段 summary 刷新为全量重算（数据量小），后续可改为增量更新。

## 6. 错误处理

| 环节 | 错误类型 | 处理方式 |
|------|----------|----------|
| 搜索 API | 限流 / 风控 | 重试 1 次，失败则记录 `crawl_task.last_result_status = RISK_BLOCKED` |
| 详情 API | 笔记已删除 / 私密 | 标记 `raw_status = DELETED / PRIVATE`，跳过 |
| LLM 提纯 | 输出非法 JSON | 标记 `extract_status = FAILED`，记录 `extract_error` |
| LLM 提纯 | 超时 | 标记 `extract_status = FAILED`，记录 latency_ms |
| 入库 | place 名称无法标准化 | 置 `confidence = 0.5`，后续人工复盘 |
