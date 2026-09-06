"""AI 分析关注重点的统一 Prompt 契约测试。"""

import json

from app.services.ai_provider import build_focus_instruction, sanitize_focus
from app.services.concept_rotation_analyzer import (
    _build_user_prompt as build_rotation_user_prompt,
)
from app.services.financial_analyzer import (
    _build_user_prompt as build_financial_user_prompt,
)
from app.services.market_recap import (
    _build_structured_json_prompt,
    _validate_structured_json_report,
)
from app.services.market_recap import (
    _build_user_prompt as build_recap_user_prompt,
)
from app.services.stock_analyzer import (
    _build_user_prompt as build_stock_user_prompt,
)


def test_focus_whitespace_is_normalized() -> None:
    assert sanitize_focus("  支撑位\n  多少  ") == "支撑位 多少"


def test_trade_wording_is_reframed_instead_of_silently_dropped() -> None:
    instruction = build_focus_instruction("现在能买吗,目标价多少", report_name="个股分析报告")

    assert "用户关注: 现在能买吗,目标价多少" in instruction
    assert "关注重点回应" in instruction
    assert "不得给出相应操作结论" in instruction
    assert "关键价位" in instruction


def test_safe_focus_requires_a_direct_answer_without_extra_warning() -> None:
    instruction = build_focus_instruction("支撑位多少", report_name="个股分析报告")

    assert "用户关注: 支撑位多少" in instruction
    assert "用 2-4 条带具体数据的结论直接回应" in instruction
    assert "不得给出相应操作结论" not in instruction


def test_all_focus_enabled_analyzers_share_the_priority_contract() -> None:
    focus = "支撑位多少"
    prompts = [
        build_stock_user_prompt([], {}, {}, 10.0, "600000.SH", focus),
        build_financial_user_prompt({}, "600000.SH", focus),
        build_recap_user_prompt({}, [], focus),
        build_rotation_user_prompt({}, {}, 12, [], focus),
    ]

    for prompt in prompts:
        assert "## 用户关注重点(必须优先回应)" in prompt
        assert f"用户关注: {focus}" in prompt
        assert "### 0. 🔎 关注重点回应" in prompt


def test_empty_focus_does_not_add_focus_section() -> None:
    prompts = [
        build_stock_user_prompt([], {}, {}, 10.0, "600000.SH", ""),
        build_financial_user_prompt({}, "600000.SH", ""),
        build_recap_user_prompt({}, [], ""),
        build_rotation_user_prompt({}, {}, 12, [], ""),
    ]

    assert all("用户关注重点" not in prompt for prompt in prompts)


def test_structured_recap_prompt_preserves_requested_json_contract() -> None:
    overview = {
        "indices": [
            {"name": "上证指数", "last_price": 3200.12, "change_pct": -1.25},
        ],
        "breadth": {"up_pct": 36.5},
        "amount": {"total": 3.17e12},
        "activity": {"avg_turnover": 1.82},
        "trend": {"above_ma60_pct": 48.0},
        "emotion": {"score": 42, "label": "偏冷"},
        "concept_rank": {
            "leading": [{"name": "半导体"}],
            "lagging": [{"name": "银行"}],
        },
        "industry_rank": {"leading": [], "lagging": []},
        "limit": {"limit_up": 52, "broken": 21, "max_boards": 6},
    }

    prompt = _build_structured_json_prompt(
        overview,
        "A股量价背离复盘",
        "明日走势推演",
    )

    assert "报告类型: A股量价背离复盘" in prompt
    assert "推演标题: 明日走势推演" in prompt
    assert '"主力与散户行为": "主力净流入未知' in prompt
    context = json.loads(prompt[prompt.index("{"):prompt.index("\n\n请直接输出")])
    assert context["板块热力"]["当前最强板块"] == ["半导体"]
    assert "请直接输出严格 JSON" in prompt


def test_structured_recap_report_validator_requires_exact_top_level_keys() -> None:
    valid = '{"核心矛盾解读": {}, "操作建议": {}, "情景推演": {}}'
    invalid = '{"核心矛盾解读": {}, "操作建议": {}}'

    assert _validate_structured_json_report(valid) is None
    assert _validate_structured_json_report(invalid)
    assert _validate_structured_json_report("```json\n{}\n```")
