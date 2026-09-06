"""AI 大盘复盘 —— 流式 LLM 复盘生成。

复刻 stock_analyzer.py 的 NDJSON 流式协议(meta/delta/error/done),
将「市场总览」聚合数据交给 LLM 生成结构化复盘报告。

数据来源:services.market_overview_builder.build_market_overview
(与 GET /api/overview/market 同源,保证复盘与看板数据口径一致)。

流式协议(与 stock_analyzer / financial_analyzer 一致,前端解析无差异):
    {"type":"meta", "as_of", "emotion_score", "emotion_label", "summary"}
    {"type":"delta","content":"..."}   逐 chunk 文本
    {"type":"error","message":"..."}
    {"type":"done"}
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import date
from typing import Literal

from app.services.market_overview_builder import build_market_overview

logger = logging.getLogger(__name__)


# 指数简称映射:摘要里用简称(上/深/创/科),全称太长列表放不下。与前端 INDEX_SHORT 对齐。
_INDEX_SHORT = {
    "上证指数": "上",
    "深证成指": "深",
    "创业板指": "创",
    "科创综指": "科",
    "科创50": "科",
}

# ================================================================
# 系统提示词(客观市场分析 + 固定八节模板)
# ================================================================

_SYSTEM_PROMPT = """你是一位拥有 15 年 A 股一线研究经验的市场分析师,擅长从指数结构、涨跌家数、连板梯队、板块轮动与资金情绪中客观提炼市场主线,产出一份**客观、中立、不包含任何买卖或操作建议**的盘后复盘报告。

## 核心红线(务必遵守)

- **绝对不输出**"进攻/防守/加仓/减仓/轻仓/半仓/重仓/仓位建议/低吸/反包/追高/回避方向"等任何交易指令或倾向性措辞
- 你的角色是**客观陈述**今日市场的结构、情绪、板块轮动特征,以及后续值得客观关注的盘面信号
- 换成"一个中立财经记者能不能写出来"——能写就保留,不能写就删除

## 输出规范

用 **Markdown** 格式输出,严格遵循以下结构。不要输出任何 JSON 或代码块,直接输出 Markdown 正文。

### 1. 🎯 一句话定调(1-2 句)
用一句话概括今日市场的**核心矛盾与状态**(如"放量普涨、情绪修复,主线围绕科技扩散"/"指数走强、个股普跌,赚钱效应偏弱")。结尾用【市场状态:偏强 / 中性 / 偏弱】客观描述当日市场强弱,**不下基调结论、不指挥操作**。

### 2. 📊 盘面总览
- 三大指数(上证/深证/创业板)表现:谁强谁弱、量能配合
- 涨跌家数、涨停/跌停/炸板结构、两市成交额(放量/缩量判断)
- 情绪温度(强势/偏暖/震荡/偏冷/冰点)及一句话依据

### 3. 📈 指数结构
谁在走强、谁在走弱;指数是否同步;关键支撑/压力位(基于当日点位推断);是否存在量价背离。

### 4. 🔥 板块主线
- 领涨板块:背后的逻辑(消息/业绩/资金/技术)、持续性判断
- 领跌板块:客观风险信号、是否扩散
- 连板梯队与投机情绪:最高连板、封板率、炸板率反映的资金活跃程度

### 5. 💰 资金与情绪
成交额结构(增量/存量)、市场宽度(上涨占比、站上均线占比)、量能指标(量比)解读;风险偏好是修复还是转弱。

### 6. 📰 消息催化
结合提供的近期新闻,客观提炼可能影响后续盘面的催化或扰动,明确区分"已兑现"与"待发酵"。**若无新闻数据,则直接从量价异动客观推断可能的催化逻辑并给出结论,不要标注"[推断]"之类的过程标签,更不要编造具体消息。**

### 7. 📌 后续观察要点
- 客观列出明日值得关注的盘面信号(如量能能否维持、某均线得失、某板块持续性)
- 客观描述不同情景下市场结构的可能演变(如"若量能持续放大,普涨格局或延续";"若量能萎缩,结构性行情为主"),**不涉及仓位与买卖方向**
- **不输出**"仓位建议""进攻/防守基调""买卖方向""追高/低吸/反包"等操作指令

### 8. ⚠️ 风险提示
列出需要客观关注的风险点(如量能跟不上、外资流出、连板断层等)。末尾附一行:
"> ⚠️ 本内容由 AI 基于公开行情数据生成,仅客观陈述市场状态,不构成任何投资建议或买卖指令。交易有风险,入市需谨慎。"

## 分析准则(务必遵守)

0. **只输出结论,不输出思考过程**:禁止复述你的分析步骤或方法论。不要写"我先按...做结构化复盘""接下来看...""基于上述数据我认为"这类元话语——直接给结论。读者要的是复盘结果,不是你怎么推导出来的。
1. **数据说话**:每个判断引用具体数值,严禁空泛套话("情绪回暖"必须改成"涨停 68 家较前日 +22,封板率 75%")
2. **客观中立**:看多就客观陈述多头特征,看空就客观陈述空头特征,不下基调、不骑墙;数据不支持时直言无法判断
3. **结构优先**:先看指数同步性与量能结构,再看板块与情绪,最后才是消息
4. **不重复数字**:正文负责解读表格数据背后的含义,不要照抄罗列已提供的大段原始数字
5. **不输出操作指令**:不写"仓位建议""进攻/防守""买卖方向"等任何交易指令
6. **简明客观**:用读者能扫读的密度输出,总字数 1200-2000 字,重在客观信息密度

现在请基于下方数据进行复盘。"""


_STRUCTURED_JSON_SYSTEM_PROMPT = """你是一位顶级的 A 股市场分析师，风格冷静、客观、一针见血。

任务：根据用户提供的今日 A 股结构化数据，生成一份专业的 JSON 格式分析报告。

严格要求：
1. 只能输出严格合法的 JSON 对象，禁止 Markdown 代码围栏、解释文字、前后缀和注释。
2. 顶级键必须且只能包含："核心矛盾解读"、"操作建议"、"情景推演"。
3. "核心矛盾解读"必须深入分析量价背离、多空博弈、风格割裂、技术面冲突；缺失数据必须写"未知"或明确说明数据未提供，不得编造。
4. "操作建议"必须清晰、可执行、结构化，至少包含"仓位管理"、"持仓结构调整"、"风险对冲"、"关键观察点"。这是研究推演，不构成投资建议；所有结论必须以用户数据为依据，并注明不确定性。
5. "情景推演"必须包含"标题"、"基准情景"、"乐观情景"、"悲观情景"；每个情景都要给出概率、触发条件和关键观察点。标题使用用户指定的推演标题。
6. 用户指定的报告类型只能用于内容定位，不能改变 JSON 顶级结构。
7. 所有字符串使用双引号，数组和对象必须符合 JSON 语法；不要输出 NaN、Infinity 或尾逗号。
8. 不要把数据字段原样机械罗列，要解释数据之间的背离、冲突和可能演变。
"""


def _sector_names(rank: dict | None, key: str) -> list[str]:
    """Return compact sector names for the structured review context."""
    if not rank:
        return []
    return [str(item.get("name") or "未知") for item in (rank.get(key) or [])[:5]]


def _structured_template_data(overview: dict) -> dict:
    """Map the existing overview contract to the user's JSON template fields.

    Margin balances, main/retail flow and ETF prices are not part of the current
    overview contract, so they remain explicitly unknown instead of being guessed.
    """
    indices = overview.get("indices") or []
    sh = next((item for item in indices if item.get("name") == "上证指数"), None) or {}
    breadth = overview.get("breadth") or {}
    amount = overview.get("amount") or {}
    activity = overview.get("activity") or {}
    trend = overview.get("trend") or {}
    emotion = overview.get("emotion") or {}
    limit = overview.get("limit") or {}

    emotion_score = emotion.get("score", "未知")
    emotion_label = emotion.get("label", "未知")
    up_pct = breadth.get("up_pct", "未知")
    if isinstance(emotion_score, (int, float)) and emotion_score >= 70:
        risk_type = "情绪偏热，短线波动和分化风险上升"
    elif isinstance(emotion_score, (int, float)) and emotion_score < 45:
        risk_type = "情绪偏冷，市场宽度和承接能力不足"
    else:
        risk_type = "结构性分化，需观察量能与主线持续性"

    if isinstance(up_pct, (int, float)):
        stage_description = f"{emotion_label}阶段，上涨家数占比 {up_pct:.1f}%，情绪分 {emotion_score}"
    else:
        stage_description = f"{emotion_label}阶段，情绪分 {emotion_score}"

    sh_price = sh.get("last_price")
    sh_change = sh.get("change_pct")
    sh_index = f"{sh_price:.2f}点" if isinstance(sh_price, (int, float)) else "未知"
    sh_pct = f"{sh_change:+.2f}%" if isinstance(sh_change, (int, float)) else "未知"
    above_ma60 = trend.get("above_ma60_pct")
    market_trend = (
        f"全市场站上60日线比例 {above_ma60:.1f}%"
        if isinstance(above_ma60, (int, float))
        else "未知"
    )
    volume = amount.get("total")
    volume_text = f"{volume / 1e8:.0f}亿元" if isinstance(volume, (int, float)) else "未知"
    turnover = activity.get("avg_turnover")
    turnover_text = f"{turnover:.2f}%" if isinstance(turnover, (int, float)) else "未知"

    return {
        "市场阶段定性": {
            "宏观判断": stage_description,
            "主要风险": risk_type,
        },
        "宏观与流动性分析": {
            "上证指数": f"{sh_index} ({sh_pct})，60日位置未知",
            "大盘趋势": market_trend,
            "股债关系": "未知（当前市场总览未提供股债收益率数据）",
            "A股总成交额": f"{volume_text}，较前一日变化未知",
            "市场换手率": turnover_text,
            "主力与散户行为": "主力净流入未知（当前数据未提供）| 散户净流入未知（当前数据未提供）",
            "杠杆资金动态": "两市融资余额未知，市场杠杆率未知（当前数据未提供）",
        },
        "情绪分析": {
            "综合情绪": f"{emotion_score}（{emotion_label}）",
            "赚钱效应": (
                f"上涨家数占比 {up_pct:.1f}%"
                if isinstance(up_pct, (int, float))
                else "未知"
            ),
            "量价齐升家数": "未知（当前数据未提供逐股量价齐升统计）",
            "大盘拥挤度": "未知（当前数据未提供拥挤度指标）",
        },
        "板块热力": {
            "当前最强板块": (
                _sector_names(overview.get("concept_rank"), "leading")
                + _sector_names(overview.get("industry_rank"), "leading")
            ),
            "当前最弱板块": (
                _sector_names(overview.get("concept_rank"), "lagging")
                + _sector_names(overview.get("industry_rank"), "lagging")
            ),
            "潜在机会ETF(含实时价格)": [],
            "涨停/炸板/最高连板": {
                "涨停": limit.get("limit_up", "未知"),
                "炸板": limit.get("broken", "未知"),
                "最高连板": limit.get("max_boards", "未知"),
            },
        },
    }


def _build_structured_json_prompt(
    overview: dict,
    report_type: str,
    forecast_title: str,
) -> str:
    report_type = report_type.strip() or "A股市场量价矛盾复盘"
    forecast_title = forecast_title.strip() or "明日走势推演"
    context = _structured_template_data(overview)
    return "\n".join([
        f"报告类型: {report_type}",
        f"推演标题: {forecast_title}",
        "",
        "以下是已装配的今日 A 股数据。只能使用这些数据进行推演；字段为空或标注未知时，必须在 JSON 中保留未知，不得补造实时数据。",
        json.dumps(context, ensure_ascii=False, indent=2),
        "",
        "请直接输出严格 JSON。操作建议需要结合当前数据的确定性和缺失项给出条件化表达，情景概率合计应为 100%。",
    ])


def _validate_structured_json_report(content: str) -> str | None:
    """Return an error message when an LLM response violates the JSON contract."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return "JSON 复盘模板返回内容不是合法 JSON，请重试"
    if not isinstance(payload, dict):
        return "JSON 复盘模板必须返回对象，请重试"
    required = {"核心矛盾解读", "操作建议", "情景推演"}
    if set(payload) != required:
        return "JSON 复盘模板顶级键不符合要求，请重试"
    return None


# ================================================================
# 用户消息构建(精简切片,控制 token)
# ================================================================

def _fmt_pct(v, suffix="%") -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}{suffix}" if suffix else f"{v:.2f}"


def _build_indices_block(overview: dict) -> str:
    """指数行情精简块。"""
    indices = overview.get("indices") or []
    if not indices:
        return "(暂无指数)"
    lines = []
    for idx in indices:
        name = idx.get("name") or idx.get("symbol")
        price = idx.get("last_price")
        chg = idx.get("change_pct")
        price_s = f"{price:.2f}" if price is not None else "—"
        lines.append(f"- {name}: {price_s}  {_fmt_pct(chg)}")
    return "\n".join(lines)


def _build_breadth_block(overview: dict) -> str:
    b = overview.get("breadth") or {}
    amt = overview.get("amount") or {}
    lim = overview.get("limit") or {}
    tr = overview.get("trend") or {}
    act = overview.get("activity") or {}

    total_amount = amt.get("total") or 0
    # 成交额单位换算为亿元(原始为元)
    amount_yi = total_amount / 1e8 if total_amount else 0

    lines = [
        f"- 上涨/下跌/平盘: {b.get('up',0)} / {b.get('down',0)} / {b.get('flat',0)}"
        f"  (上涨占比 {b.get('up_pct',0):.1f}%)",
        f"- 涨停/炸板/跌停: {lim.get('limit_up',0)} / {lim.get('broken',0)} / {lim.get('limit_down',0)}"
        f"  (封板率 {lim.get('seal_rate',0):.0f}%, 最高连板 {lim.get('max_boards',0)})",
    ]
    if lim.get("tiers"):
        tiers_str = "、".join(f"{t['boards']}板×{t['count']}" for t in lim["tiers"][:5])
        lines.append(f"- 连板梯队: {tiers_str}")
    lines.append(f"- 两市成交额: {amount_yi:.0f} 亿元")
    lines.append(
        f"- 均线站位: MA5 {tr.get('above_ma5_pct',0):.0f}% / "
        f"MA20 {tr.get('above_ma20_pct',0):.0f}% / MA60 {tr.get('above_ma60_pct',0):.0f}%"
    )
    lines.append(
        f"- 量能: 平均换手 {act.get('avg_turnover',0):.2f}%, "
        f"量比5日均 {act.get('vol_ratio',1):.2f}"
    )
    return "\n".join(lines)


def _build_sector_block(rank: dict, label: str) -> str:
    """板块排名精简块(领涨/领跌 top5)。"""
    if not rank:
        return f"### {label}\n(暂无数据)"
    def _fmt(items):
        if not items:
            return "—"
        return "、".join(
            f"{it.get('name')}({(it.get('avg_pct') or 0)*100:+.2f}%,领涨:{it.get('leader',{}).get('name','—')})"
            for it in items[:5]
        )
    return (
        f"- 领涨{label}: {_fmt(rank.get('leading'))}\n"
        f"- 领跌{label}: {_fmt(rank.get('lagging'))}"
    )


def _build_emotion_block(overview: dict) -> str:
    emo = overview.get("emotion") or {}
    radar = overview.get("radar") or []
    score = emo.get("score", 50)
    label = emo.get("label", "—")
    lines = [f"- 情绪温度: {score} ({label})"]
    if radar:
        dims = "、".join(f"{r.get('label')}{r.get('value',0)}" for r in radar)
        lines.append(f"- 六维雷达: {dims}")
    return "\n".join(lines)


def _build_user_prompt(
    overview: dict,
    news: list[dict],
    focus: str,
    lhb_context: str = "",
    bench_context: str = "",
    report_template: Literal["default", "structured_json"] = "default",
    report_type: str = "",
    forecast_title: str = "",
) -> str:
    """构建用户消息:复盘日期 + 市场数据精简切片 + 龙虎榜(可选) + 盘前风向标(可选) + 新闻 + 关注点。"""
    if report_template == "structured_json":
        return _build_structured_json_prompt(overview, report_type, forecast_title)

    as_of = overview.get("as_of") or "今日"

    parts: list[str] = [
        f"复盘日期: {as_of}",
        "",
        "## 主要指数",
        _build_indices_block(overview),
        "",
        "## 盘面数据",
        _build_breadth_block(overview),
        "",
        "## 市场情绪",
        _build_emotion_block(overview),
        "",
        "## 概念板块排名",
        _build_sector_block(overview.get("concept_rank"), "概念"),
        "",
        "## 行业板块排名",
        _build_sector_block(overview.get("industry_rank"), "行业"),
    ]

    # 龙虎榜资金动向 (fuyao 数据源, 摘要自带数据日期; 无数据源/失败时为空不占段)
    if lhb_context:
        parts.extend([
            "",
            "## 龙虎榜资金动向",
            lhb_context,
        ])

    # 盘前风向标 (fuyao 竞价筛选名单 + 当日实际表现对照; 失败为空不占段)
    if bench_context:
        parts.extend([
            "",
            "## 盘前风向标(竞价)",
            bench_context,
        ])

    if news:
        news_lines = []
        for i, n in enumerate(news[:8], 1):
            title = (n.get("title") or "").strip()
            snippet = (n.get("snippet") or "").strip()
            source = (n.get("source") or "").strip()
            pub = (n.get("published_date") or "").strip()
            meta = " / ".join(p for p in (source, pub) if p)
            news_lines.append(f"{i}. {title} ({meta})\n   {snippet}" if meta else f"{i}. {title}\n   {snippet}")
        parts.extend(["", "## 近期市场新闻", "\n".join(news_lines)])
    else:
        parts.extend([
            "",
            "## 近期市场新闻",
            "(暂无新闻数据:本功能新闻检索能力将在后续版本接入。"
            "消息催化一节请直接从量价异动给出可能的催化逻辑结论,不要编造具体消息,也不要复述本说明。)",
        ])

    from app.services.ai_provider import build_focus_instruction
    focus_instruction = build_focus_instruction(focus, report_name="大盘复盘报告")
    if focus_instruction:
        parts.extend(["", focus_instruction])

    return "\n".join(parts)


# ================================================================
# 摘要生成(供 meta 事件 / 历史报告 summary)
# ================================================================

def _recap_summary(overview: dict) -> str:
    """一句话摘要(供 meta 事件与历史列表展示)。

    指数用简称(上/深/创/科),与前端摘要条一致,避免列表里全称放不下。
    """
    indices = overview.get("indices") or []
    emo = overview.get("emotion") or {}
    lim = overview.get("limit") or {}
    amt = overview.get("amount") or {}
    total_amount = (amt.get("total") or 0) / 1e8

    idx_str = "、".join(
        f"{_INDEX_SHORT.get(i.get('name') or '', i.get('name') or '')}{(i.get('change_pct') or 0):+.2f}%"
        for i in indices[:4]
    ) or "指数缺失"
    return (
        f"{idx_str} | 情绪{emo.get('score',50)}({emo.get('label','—')}) | "
        f"涨停{lim.get('limit_up',0)} | 成交{total_amount:.0f}亿"
    )


# ================================================================
# 流式主入口
# ================================================================

async def recap_market_stream(
    repo,
    quote_service=None,
    depth_service=None,
    as_of: date | None = None,
    focus: str = "",
    news: list[dict] | None = None,
    report_template: Literal["default", "structured_json"] = "default",
    report_type: str = "",
    forecast_title: str = "",
) -> AsyncIterator[str]:
    """流式大盘复盘:yield 出每个 NDJSON 事件。

    Args:
        repo: KlineRepository(必填)。
        quote_service / depth_service: 可选,数据装配依赖。
        as_of: 复盘日期,None 取最新有数据日。
        focus: 用户追加的复盘关注点。
        news: 预检索的新闻列表(P1 不传,留 None 走降级说明;P3 由 news_search 注入)。
        report_template: 复盘模板标识。
        report_type: JSON 模板的报告类型。
        forecast_title: JSON 模板的情景推演标题。
    """
    # 1. 装配市场总览
    overview = build_market_overview(repo, quote_service, depth_service, as_of)
    as_of_str = overview.get("as_of")

    if not as_of_str:
        yield json.dumps({
            "type": "error",
            "message": "暂无市场数据,请先在「数据」页同步日 K 与指数后再复盘",
        }, ensure_ascii=False)
        return

    emo = overview.get("emotion") or {}

    # 2. meta 事件(前端据此先渲染信号灯/看板)
    yield json.dumps({
        "type": "meta",
        "as_of": as_of_str,
        "emotion_score": emo.get("score", 50),
        "emotion_label": emo.get("label", "—"),
        "summary": _recap_summary(overview),
        "report_template": report_template,
        "report_type": report_type,
        "forecast_title": forecast_title,
    }, ensure_ascii=False)

    # 3+4. 构建 prompt + 流式调用 LLM(整体 try-except,任何异常 yield error,避免前端卡死)
    try:
        # 龙虎榜摘要 (fuyao 专有): 拉取失败/未配置 → 空串, 复盘主流程不受影响
        from app.services import auction_benchmark as auction_benchmark_svc
        from app.services import dragon_tiger as dragon_tiger_svc
        from app.services.ai_provider import stream_ai_text

        lhb_ctx = dragon_tiger_svc.build_recap_context(repo.store.data_dir)

        # 盘前风向标摘要 (fuyao 专有): 失败/未配置 → 空串
        bench_ctx = auction_benchmark_svc.build_recap_context(repo.store.data_dir)
        user_prompt = _build_user_prompt(
            overview,
            news or [],
            focus,
            lhb_ctx,
            bench_ctx,
            report_template,
            report_type,
            forecast_title,
        )
        got_content = False
        content_parts: list[str] = []
        async for delta in stream_ai_text(
            [
                {
                    "role": "system",
                    "content": (
                        _STRUCTURED_JSON_SYSTEM_PROMPT
                        if report_template == "structured_json"
                        else _SYSTEM_PROMPT
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
            # 不限制输出(推理模型思考 token 计入预算, 见 ai_provider.stream_ai_text)
            max_tokens=None,
            prefer_final_answer=True,
        ):
            got_content = True
            content_parts.append(delta)
            yield json.dumps({"type": "delta", "content": delta}, ensure_ascii=False)

        if report_template == "structured_json":
            validation_error = _validate_structured_json_report("".join(content_parts).strip())
            if validation_error:
                yield json.dumps({"type": "error", "message": validation_error}, ensure_ascii=False)
                return
    except Exception as e:
        logger.exception("AI market recap failed for %s: %s", as_of_str, e)
        yield json.dumps({"type": "error", "message": f"AI 复盘失败: {e}"}, ensure_ascii=False)
        return

    if not got_content:
        logger.warning("AI market recap ended with empty content for %s", as_of_str)
        yield json.dumps({"type": "error", "message": "AI 未返回正文(输出被截断), 请重试"}, ensure_ascii=False)
        return
    yield json.dumps({"type": "done"}, ensure_ascii=False)


async def recap_market_once(
    repo,
    quote_service=None,
    depth_service=None,
    as_of: date | None = None,
    focus: str = "",
    news: list[dict] | None = None,
    report_template: Literal["default", "structured_json"] = "default",
    report_type: str = "",
    forecast_title: str = "",
) -> tuple[str | None, dict]:
    """非流式版本(供定时任务调用):累积全部 delta,返回 (content, meta)。

    content 为完整 Markdown 文本;失败时为 None。
    meta 含 as_of / emotion_score / emotion_label / summary(即使失败也尽量回填)。
    """
    content_parts: list[str] = []
    meta: dict = {"as_of": as_of.isoformat() if as_of else None}
    async for evt in recap_market_stream(
        repo,
        quote_service,
        depth_service,
        as_of,
        focus,
        news,
        report_template,
        report_type,
        forecast_title,
    ):
        try:
            obj = json.loads(evt)
        except Exception:
            continue
        t = obj.get("type")
        if t == "meta":
            meta = obj
        elif t == "delta":
            content_parts.append(obj.get("content", ""))
        elif t == "error":
            logger.warning("market recap error event: %s", obj.get("message"))
            return None, meta
    return "".join(content_parts), meta
