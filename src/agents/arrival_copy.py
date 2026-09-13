"""Ground explicit arrival-time clauses in a locked incoming POI leg."""
import re

_TIME = r"(?:[0-9０-９零〇一二两三四五六七八九十百半几]+(?:[.．点][0-9零一二三四五六七八九]+)?(?:来|多|余|几)?\s*(?:个?小时|分钟|分)|半小时|一刻钟)"
_SPLIT = re.compile(r"([。！？!?；;\n])")


def normalize_arrival_copy(text, leg):
    """Only an explicit arrival at this stop is owned by the incoming leg.

    Leave local walks, meals, visits, and unbound destinations untouched. Run
    before fragment offsets are assembled; the publish gate also uses this
    idempotent comparison against the final rendered POI paragraph.
    """
    if leg is None or leg.duration_minutes <= 0:
        return text
    mode = {"transit":"公共交通", "walking":"步行", "driving":"驾车", "cycling":"骑行"}.get(leg.mode)
    if mode is None:
        return text
    prefix = rf"(?:从(?:{re.escape(leg.from_name)}|上一站)(?:出发)?[，,]?\s*)?"
    movement = r"(?:搭车|坐车|乘车|坐地铁|乘地铁|乘公交|坐公交|步行|走|骑车|骑行|开车|驾车|打车)"
    arrival = rf"(?:{movement})?(?:过来|到这里|来到这里|到{re.escape(leg.to_name)})"
    locked_pair = rf"{re.escape(leg.from_name)}→{re.escape(leg.to_name)}"
    pattern = re.compile(rf"^\s*(?:{prefix}{arrival}|{locked_pair})[^。；!?\n]{{0,12}}?{_TIME}(?:左右|上下)?(?:就到|即可)?\s*(?=$|[，,])")
    tokens = _SPLIT.split(text)
    for i in range(0,len(tokens),2):
        clause=tokens[i]
        label=''
        if clause.startswith(leg.to_name+'：') or clause.startswith(leg.to_name+':'):
            label=clause[:len(leg.to_name)+1]
            clause=clause[len(label):]
        match = pattern.match(clause)
        if match:
            tokens[i]=label+f"{leg.from_name}→{leg.to_name}，{mode}约 {leg.duration_minutes} 分钟"+clause[match.end():]
    result = ''.join(tokens)
    canonical = f"{leg.from_name}→{leg.to_name}，{mode}约 {leg.duration_minutes} 分钟"
    # Keep structured transport separate from activity prose such as “往街区方向
    # 走走”; existing transit grounding must not read that as a bus headsign.
    return re.sub(rf"({re.escape(canonical)})[，,。；;](?=[^\n])", r"\1。\n", result)


def arrival_activity_copy(text, leg):
    """Remove an explicit incoming-time clause; the day transport block owns it.

    Keep the validator's canonical normalization independent of presentation.
    Local activity and food times are never removed by this matcher.
    """
    grounded = normalize_arrival_copy(text, leg)
    if leg is None or leg.duration_minutes <= 0:
        return grounded
    mode = {"transit": "公共交通", "walking": "步行", "driving": "驾车", "cycling": "骑行"}.get(leg.mode)
    if mode is None:
        return grounded
    canonical = f"{leg.from_name}→{leg.to_name}，{mode}约 {leg.duration_minutes} 分钟"
    return re.sub(rf"(?:^|(?<=[。！？!?；;\n]))\s*{re.escape(canonical)}[。；;，,]?\s*", "", grounded).strip()
