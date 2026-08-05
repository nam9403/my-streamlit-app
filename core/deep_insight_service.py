from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def analyze_earnings_quality(snapshot: dict[str, Any], valuation: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Phát hiện lệch pha giữa lợi nhuận và CFO để cảnh báo chất lượng lợi nhuận.
    """
    pio = snapshot.get("piotroski") if isinstance(snapshot.get("piotroski"), dict) else {}
    net_income = _safe_float(snapshot.get("net_income"), _safe_float((pio or {}).get("net_income"), 0.0))
    cfo_raw = snapshot.get("operating_cash_flow")
    if cfo_raw is None and isinstance(pio, dict):
        cfo_raw = pio.get("operating_cash_flow")
    cfo_present = cfo_raw is not None
    cfo = _safe_float(cfo_raw, 0.0) if cfo_present else 0.0
    net_income_prior = _safe_float(snapshot.get("net_income_prior"), _safe_float((pio or {}).get("net_income_prior"), 0.0))
    cfo_prior_raw = snapshot.get("operating_cash_flow_prior")
    if cfo_prior_raw is None and isinstance(pio, dict):
        cfo_prior_raw = pio.get("operating_cash_flow_prior")
    cfo_prior = _safe_float(cfo_prior_raw, 0.0) if cfo_prior_raw is not None else 0.0

    ni_growth = None
    cfo_growth = None
    if net_income_prior > 0:
        ni_growth = (net_income / net_income_prior - 1.0) * 100.0
    if cfo_prior_raw is not None and cfo_prior != 0:
        cfo_growth = (cfo / cfo_prior - 1.0) * 100.0

    warning = False
    severity = "low"
    notes: list[str] = []
    # Chỉ so LN vs CFO khi có CFO thật — thiếu CFO ≠ CFO âm.
    if cfo_present and net_income > 0 and cfo <= 0:
        warning = True
        severity = "high"
        notes.append("LN dương nhưng CFO âm.")
    elif (not cfo_present) and net_income > 0 and str(snapshot.get("net_income_source") or "").endswith("estimate"):
        notes.append("LNST ước lượng; chưa có CFO để chấm chất lượng lợi nhuận.")
    if ni_growth is not None and ni_growth > 10 and cfo_growth is not None and cfo_growth < 0:
        warning = True
        severity = "high" if severity == "high" else "medium"
        notes.append("Lợi nhuận tăng nhưng dòng tiền kinh doanh suy giảm.")
    if cfo_present and net_income > 0 and cfo > 0 and cfo < net_income * 0.7:
        warning = True
        severity = "medium" if severity != "high" else severity
        notes.append("CFO thấp đáng kể so với lợi nhuận kế toán.")

    f_score = int((valuation or {}).get("piotroski_score") or 0)
    if f_score <= 4 and warning:
        severity = "high"
        notes.append("F-Score thấp củng cố rủi ro chất lượng lợi nhuận.")

    label = "Ổn"
    if warning and severity == "high":
        label = "Cảnh báo chất lượng lợi nhuận (mức cao)"
    elif warning:
        label = "Cảnh báo chất lượng lợi nhuận"
    elif notes and not warning:
        label = "Thiếu CFO để xác nhận"

    return {
        "warning": warning,
        "severity": severity,
        "label": label,
        "net_income": round(net_income, 2),
        "operating_cash_flow": round(cfo, 2) if cfo_present else None,
        "net_income_growth_yoy_pct": None if ni_growth is None else round(ni_growth, 2),
        "operating_cash_flow_growth_yoy_pct": None if cfo_growth is None else round(cfo_growth, 2),
        "notes": notes,
    }


def _extract_structured_events_from_news(news: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in news or []:
        if not isinstance(row, dict):
            continue
        evt = row.get("smart_money_event")
        if isinstance(evt, dict):
            events.append(evt)
    return events


def _load_structured_events_from_disk(symbol: str | None) -> list[dict[str, Any]]:
    if not symbol:
        return []
    path = Path("data") / "smart_money_events.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    out: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol") or "").strip().upper() != str(symbol).strip().upper():
            continue
        out.append(row)
    return out


def _heuristic_smart_money(news: list[dict[str, Any]]) -> tuple[float, list[str]]:
    text = " | ".join(str(x.get("title") or "") for x in (news or [])[:20]).lower()
    if not text:
        return 0.0, []
    pos_kw = (
        "mua ròng",
        "gom",
        "đăng ký mua",
        "tăng sở hữu",
        "khối ngoại mua",
        "cổ đông lớn mua",
        "ban lãnh đạo mua",
    )
    neg_kw = (
        "bán ròng",
        "thoái vốn",
        "đăng ký bán",
        "giảm sở hữu",
        "khối ngoại bán",
        "cổ đông lớn bán",
        "ban lãnh đạo bán",
    )
    signals: list[str] = []
    score = 0.0
    for k in pos_kw:
        if k in text:
            signals.append(f"+ {k}")
            score += 1
    for k in neg_kw:
        if k in text:
            signals.append(f"- {k}")
            score -= 1
    return score, signals[:8]


def _dedupe_structured_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Collapse duplicate scrapes of the same actor/side/value so score is not over-weighted.
    """
    buckets: dict[tuple[Any, ...], dict[str, Any]] = {}
    order: list[tuple[Any, ...]] = []
    for evt in events or []:
        if not isinstance(evt, dict):
            continue
        actor = str(evt.get("actor_type") or "foreign").strip().lower()
        name = str(evt.get("actor_name") or "Unknown").strip()
        side = str(evt.get("side") or "").strip().lower()
        nv = _safe_float(evt.get("net_value_vnd"), 0.0)
        # Bucket by ~100M VND to merge near-identical scrapes.
        nv_bucket = int(round(nv / 100_000_000.0)) * 100_000_000
        key = (actor, name.lower(), side, nv_bucket)
        if key not in buckets:
            row = dict(evt)
            existing_dup = int(evt.get("_dup_count") or 1)
            row["_dup_count"] = max(1, existing_dup)
            row["net_value_vnd"] = nv
            buckets[key] = row
            order.append(key)
            continue
        prev = buckets[key]
        add_dup = max(1, int(evt.get("_dup_count") or 1))
        prev["_dup_count"] = int(prev.get("_dup_count") or 1) + add_dup
        prev_conf = min(1.0, max(0.0, _safe_float(prev.get("confidence"), 0.6)))
        cur_conf = min(1.0, max(0.0, _safe_float(evt.get("confidence"), 0.6)))
        if cur_conf > prev_conf:
            prev["confidence"] = cur_conf
        # Prefer larger absolute value within bucket (more informative).
        if abs(nv) > abs(_safe_float(prev.get("net_value_vnd"), 0.0)):
            prev["net_value_vnd"] = nv
        src = str(evt.get("source") or "").strip()
        if src and not prev.get("source"):
            prev["source"] = src
    return [buckets[k] for k in order]


def _score_structured_events(events: list[dict[str, Any]]) -> tuple[float, list[str], list[str], float, int, list[str]]:
    score = 0.0
    signals: list[str] = []
    sources: list[str] = []
    actor_counter: dict[str, int] = {}
    conf_sum = 0.0
    conf_n = 0
    high_conf_count = 0
    actor_weight = {"insider": 1.5, "major_shareholder": 1.2, "foreign": 1.0}
    deduped = _dedupe_structured_events(events)
    for evt in deduped[:40]:
        side = str(evt.get("side") or "").strip().lower()
        actor = str(evt.get("actor_type") or "foreign").strip().lower()
        source = str(evt.get("source") or "").strip()
        actor_name = str(evt.get("actor_name") or "Unknown").strip()
        confidence = min(1.0, max(0.0, _safe_float(evt.get("confidence"), 0.6)))
        dup = max(1, int(evt.get("_dup_count") or 1))
        conf_sum += confidence
        conf_n += 1
        if confidence >= 0.75:
            high_conf_count += 1
        if source:
            sources.append(source)
        base = float(actor_weight.get(actor, 1.0))
        net_value = _safe_float(evt.get("net_value_vnd"), 0.0)
        amp = min(3.0, 1.0 + math.log10(1.0 + abs(net_value) / 1_000_000_000.0))
        delta = base * amp * (0.6 + 0.8 * confidence)
        actor_counter[actor_name] = int(actor_counter.get(actor_name, 0)) + dup
        dup_tag = f" ×{dup}" if dup > 1 else ""
        if side == "buy":
            score += delta
            signals.append(f"+ {actor_name} ({actor}) buy {net_value:,.0f} VND conf={confidence:.2f}{dup_tag}")
        elif side == "sell":
            score -= delta
            signals.append(f"- {actor_name} ({actor}) sell {net_value:,.0f} VND conf={confidence:.2f}{dup_tag}")
    uniq_sources = sorted({x for x in sources if x})
    avg_conf = (conf_sum / conf_n) if conf_n > 0 else 0.0
    top_actors = [k for k, _ in sorted(actor_counter.items(), key=lambda kv: kv[1], reverse=True)[:3]]
    return score, signals[:10], uniq_sources, avg_conf, high_conf_count, top_actors


def analyze_smart_money_flow(
    news: list[dict[str, Any]],
    *,
    symbol: str | None = None,
    structured_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    heuristic_score, heuristic_signals = _heuristic_smart_money(news)
    events = list(structured_events or [])
    if not events:
        events = _extract_structured_events_from_news(news)
    if not events:
        events = _load_structured_events_from_disk(symbol)

    score = heuristic_score
    signals = list(heuristic_signals)
    data_mode = "heuristic"
    structured_event_count = 0
    source_coverage: list[str] = []
    avg_event_confidence = 0.0
    high_conf_event_count = 0
    top_actors: list[str] = []
    if events:
        st_score, st_signals, st_sources, avg_conf, high_conf_count, top_names = _score_structured_events(events)
        score += st_score
        signals = (st_signals + signals)[:10]
        data_mode = "hybrid" if heuristic_signals else "structured"
        structured_event_count = len(events)
        source_coverage = st_sources
        avg_event_confidence = round(float(avg_conf), 2)
        high_conf_event_count = int(high_conf_count)
        top_actors = top_names

    if score >= 2:
        bias = "bullish"
        label = "Smart money nghiêng mua"
    elif score <= -2:
        bias = "bearish"
        label = "Smart money nghiêng bán"
    else:
        bias = "neutral"
        label = "Smart money trung tính"
    return {
        "bias": bias,
        "score": round(float(score), 2),
        "signals": signals,
        "label": label if signals else "Chưa đủ dữ liệu smart money",
        "data_mode": data_mode,
        "structured_event_count": structured_event_count,
        "source_coverage": source_coverage,
        "avg_event_confidence": avg_event_confidence,
        "high_conf_event_count": high_conf_event_count,
        "top_actors": top_actors,
    }


def confirm_smart_money_flow(
    flow_signal: dict[str, Any] | Any,
    smart_money_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Tier 2 — kết hợp tín hiệu microstructure (Tier 1) với smart money từ news/CBTT.

    Đầu vào:
    - ``flow_signal``: dict (từ ``FlowSignal.to_dict``) hoặc đối tượng có cùng các thuộc tính.
    - ``smart_money_summary``: dict trả về từ ``analyze_smart_money_flow`` (có thể None).

    Logic:
    - ``strong``: Tape (delta) và Smart Money (CBTT) cùng chiều, intensity cao.
    - ``moderate``: Cùng chiều nhưng intensity vừa phải.
    - ``diverging``: Tape và Smart Money ngược chiều ⇒ cảnh báo bull/bear trap.
    - ``weak``: Một trong hai bên không đủ dữ liệu.

    Output dùng cho banner UI + alert + journal.
    """

    def _attr(obj: Any, name: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    delta_status = str(_attr(flow_signal, "delta_status") or "neutral")
    intensity = _safe_float(_attr(flow_signal, "intensity_score"), 0.0)
    is_big_boy = bool(_attr(flow_signal, "is_big_boy") or False)

    tape_bias = "neutral"
    if delta_status in ("bullish", "absorption"):
        tape_bias = "bullish"
    elif delta_status in ("bearish", "distribution"):
        tape_bias = "bearish"

    sm_bias = str((smart_money_summary or {}).get("bias") or "neutral")
    sm_score = _safe_float((smart_money_summary or {}).get("score"), 0.0)
    sm_avg_conf = _safe_float((smart_money_summary or {}).get("avg_event_confidence"), 0.0)
    sm_data_mode = str((smart_money_summary or {}).get("data_mode") or "heuristic")

    reasons: list[str] = []
    risks: list[str] = []

    if tape_bias == "neutral" or sm_bias == "neutral":
        confirmation = "weak"
        verdict = "Chưa đủ tín hiệu để xác nhận dòng tiền lớn"
    elif tape_bias == sm_bias:
        if is_big_boy and intensity >= 7.0 and sm_avg_conf >= 0.65:
            confirmation = "strong"
            verdict = (
                "Smart Money và Tape đồng thuận MẠNH theo chiều " + ("MUA" if tape_bias == "bullish" else "BÁN")
            )
        elif is_big_boy and intensity >= 5.0:
            confirmation = "moderate"
            verdict = (
                "Smart Money và Tape đồng thuận chiều " + ("mua" if tape_bias == "bullish" else "bán")
            )
        else:
            confirmation = "weak"
            verdict = "Đồng thuận yếu — chờ thêm xác nhận"
    else:
        confirmation = "diverging"
        if tape_bias == "bullish":
            verdict = "Tape MUA nhưng Smart Money đang bán — cảnh giác bull trap"
            risks.append("Có khả năng tổ chức đang xả qua các lệnh nhỏ trong khi tin tức tích cực.")
        else:
            verdict = "Tape BÁN nhưng Smart Money đang mua — có thể là rũ hàng"
            reasons.append("Lực bán xuất hiện nhưng smart money tích lũy ⇒ cân nhắc canh mua thận trọng.")

    # Combined intensity: hợp nhất tin cậy giữa Tape và Smart Money.
    base = float(min(10.0, max(0.0, intensity)))
    if confirmation == "strong":
        combined = min(10.0, base + 1.5)
    elif confirmation == "moderate":
        combined = min(10.0, base + 0.5)
    elif confirmation == "diverging":
        combined = max(1.0, base - 2.0)
    else:
        combined = max(1.0, base - 0.5)

    if sm_data_mode == "heuristic":
        risks.append("Smart Money mới ở mức heuristic (news) — cần xác nhận bằng CBTT có cấu trúc.")

    return {
        "confirmation_level": confirmation,
        "tape_bias": tape_bias,
        "smart_money_bias": sm_bias,
        "combined_intensity": round(float(combined), 2),
        "verdict": verdict,
        "reasons": reasons,
        "risks": risks,
        "smart_money_score": round(float(sm_score), 2),
        "smart_money_avg_confidence": round(float(sm_avg_conf), 2),
        "smart_money_data_mode": sm_data_mode,
    }
