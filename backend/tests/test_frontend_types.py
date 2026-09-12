"""T-5.10 — 前端 types 由 OpenAPI 生成（替代手工镜像）。

断言生成物存在且覆盖本阶段新增/关键端点与 schema。
生成命令（写进阶段报告）：
    uv run python -c "import json;from app.main import app;json.dump(app.openapi(), open('openapi.json','w',encoding='utf-8'), ensure_ascii=False)"
    npx --yes openapi-typescript openapi.json -o ../frontend/src/types/api.gen.ts
"""
from __future__ import annotations

from pathlib import Path

_FRONTEND_TYPES = (
    Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "types" / "api.gen.ts"
)


def test_openapi_types_generated():
    assert _FRONTEND_TYPES.exists(), "前端类型未生成（见本测试 docstring 的生成命令）"
    text = _FRONTEND_TYPES.read_text(encoding="utf-8")
    assert len(text) > 2000, "生成物过短，疑似未真正生成"
    # 关键端点 + schema 出现在生成物中
    assert "/api/v1/chat/stream" in text
    assert "/metrics" in text
    assert "ChatSendRequest" in text
