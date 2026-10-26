"""T-5.10 — 前端 types 由 OpenAPI 生成（替代手工镜像）。

断言生成物存在且覆盖关键端点与 schema。
生成命令：
    cd backend
    uv run python -c "import json;from app.main import app;json.dump(app.openapi(), open('openapi.json','w',encoding='utf-8'), ensure_ascii=False)"
    cd ../frontend && npx --yes openapi-typescript ../backend/openapi.json -o src/types/api.gen.ts
"""
from __future__ import annotations

import json
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


def test_openapi_operation_ids_are_unique():
    """OpenAPI 里 operationId 必须全局唯一。

    真实事故：`/{doc_id}/pdf/stream` 用 `api_route(methods=["GET","HEAD"])` 声明，
    FastAPI 的默认 `generate_unique_id` 只取 `route.methods` 的**第一个**方法名拼 ID，
    于是 GET 与 HEAD 得到完全相同的 operationId。OpenAPI 允许这么输出，
    但 `openapi-typescript` 生成时会产生重复标识符，前端 `vue-tsc` 直接 TS2300，
    整个前端类型检查失败 —— 而后端 280 个测试全绿，一点征兆都没有。

    改为 HEAD/GET 各挂一个装饰器后 ID 分离。本测试守住这一点：
    任何新增的多方法路由都会在这里被拦住。
    """
    from app.main import app

    ids: list[str] = []
    for path, operations in app.openapi()["paths"].items():
        for method, op in operations.items():
            if not isinstance(op, dict):
                continue
            op_id = op.get("operationId")
            assert op_id, f"{method.upper()} {path} 缺 operationId"
            ids.append(op_id)

    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"OpenAPI 存在重复 operationId: {sorted(duplicates)}"


def test_openapi_types_are_up_to_date():
    """前端生成物不能落后于后端契约。

    只校验「后端有、生成物里没有」的字段（例如上一轮新增的
    `ChatSendRequest.regenerate_message_id` 一度没同步，直到手工重生成才发现）。
    不比对整份 JSON：那会让任何注释/顺序变化都变成假阳性。
    """
    from app.main import app

    assert _FRONTEND_TYPES.exists(), "前端类型未生成"
    text = _FRONTEND_TYPES.read_text(encoding="utf-8")

    schemas = app.openapi().get("components", {}).get("schemas", {})
    missing: list[str] = []
    for name, schema in schemas.items():
        if name not in text:
            continue  # schema 本身没生成，由 test_openapi_types_generated 负责
        for field in (schema.get("properties") or {}):
            if field not in text:
                missing.append(f"{name}.{field}")

    assert not missing, (
        f"前端类型缺少后端已有字段: {missing}。"
        "请按本文件 docstring 的命令重新生成 api.gen.ts"
    )
