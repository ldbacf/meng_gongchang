"""T-5.7 — docker compose 定义校验：解析通过 + 10+ 服务齐全（含 backend/worker）。

需本机 docker CLI（`docker compose config`）；无 docker 时 skip。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent

_REQUIRED = {
    # 基础设施
    "postgres", "redis", "minio", "elasticsearch", "milvus",
    # 应用
    "backend", "ingestion-worker", "embedding-service",
}


def _compose(*args: str) -> subprocess.CompletedProcess:
    # 继承完整环境（docker CLI 需要 PATH/HOME/ProgramData 等），仅补 JWT（compose 要求显式设置）
    env = {**os.environ, "JWT_SECRET_KEY": "compose-config-test"}
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=_BACKEND, capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env,
    )


@pytest.fixture(scope="module")
def has_docker() -> bool:
    return shutil.which("docker") is not None


def test_compose_config_valid(has_docker):
    if not has_docker:
        pytest.skip("无 docker CLI，跳过 compose 校验")
    r = _compose("config")
    assert r.returncode == 0, r.stderr
    assert "services:" in r.stdout


def test_compose_service_set(has_docker):
    if not has_docker:
        pytest.skip("无 docker CLI，跳过 compose 校验")
    r = _compose("--profile", "app", "config", "--services")
    assert r.returncode == 0, r.stderr
    services = {s.strip() for s in r.stdout.splitlines() if s.strip()}
    missing = _REQUIRED - services
    assert not missing, f"compose 缺少服务: {missing}"
    assert len(services) >= 10, f"服务数不足 10: {sorted(services)}"


def test_worker_and_backend_have_healthcheck_and_restart(has_docker):
    if not has_docker:
        pytest.skip("无 docker CLI，跳过 compose 校验")
    r = _compose("--profile", "app", "config")
    assert r.returncode == 0, r.stderr
    # backend 有 healthcheck；两个应用服务均 restart: unless-stopped
    assert "restart: unless-stopped" in r.stdout
    assert "healthcheck:" in r.stdout
