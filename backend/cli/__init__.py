"""运维 CLI（阶段 5）— 复用 `app`/`src` 的 service/图/适配器，不再各自内联管线。

- 每个模块 `python -m cli.<name>` 可执行（或 pyproject 的 `medrag-<name>` 脚本）。
- 无 `sys.path.insert`：`cli` 与 `app`/`src` 同属 backend 包，从 backend/ 运行即 import 正常。
- 一次性的 **DROP 重建** 脚本（init_es / init_milvus）红线不变：仅限全新环境。
"""
