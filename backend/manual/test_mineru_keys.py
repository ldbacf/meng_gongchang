"""
MinerU API Key 可用性测试
验证每个 Token 是否能正常调用 MinerU 接口。

用法:
    uv run python test_mineru_keys.py
"""

import os
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

API_BASE = os.getenv("MINERU_API_BASE", "https://mineru.net").rstrip("/")
TOKENS_STR = (
    os.getenv("MINERU_TOKENS")
    or os.getenv("MINERU_API_TOKEN")
    or ""
)
# 测试用公共 PDF (MinerU 官方示例)
TEST_URL = "https://cdn-mineru.openxlab.org.cn/demo/example.pdf"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def ok(msg):   print(f"  {GREEN}[OK]{RESET} {msg}")
def fail(msg): print(f"  {RED}[FAIL]{RESET} {msg}")
def warn(msg): print(f"  {YELLOW}[WARN]{RESET} {msg}")


def parse_tokens(raw: str) -> list[str]:
    """解析 Token 列表（逗号分隔，过滤空值）"""
    if "," in raw:
        return [t.strip() for t in raw.split(",") if t.strip()]
    elif raw.strip():
        return [raw.strip()]
    return []


def test_token(token: str, idx: int, total: int) -> bool:
    """测试单个 Token：调用 MinerU 创建任务，验证 auth 是否通过"""
    mask = token[:12] + "..." + token[-4:] if len(token) > 20 else token
    print(f"\n[{idx}/{total}] 测试: {mask}")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    body = {
        "url": TEST_URL,
        "model_version": "vlm",
        "enable_formula": True,
        "enable_table": True,
        "language": "ch",
    }

    try:
        with httpx.Client(
            timeout=httpx.Timeout(30.0, connect=15.0),
            proxy=None,
            http2=False,
            trust_env=False,
        ) as http:
            resp = http.post(f"{API_BASE}/api/v4/extract/task", headers=headers, json=body)
            data = resp.json()
            code = data.get("code", -1)

            if code == 0:
                task_id = data.get("data", {}).get("task_id", "")
                ok(f"验证通过, task_id={task_id}")
                return True

            elif code == -60018:
                warn(f"Token 有效，但当日 1000 页额度已用完")
                return True  # Token 本身可用，只是额度用完

            elif code in (-500, -10002):
                ok(f"Token 有效 (code={code})")
                return True

            else:
                fail(f"code={code}, msg={data.get('msg', '')}")
                return False

    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            fail(f"HTTP {e.response.status_code} — Token 无效或已过期")
        else:
            fail(f"HTTP {e.response.status_code}")
        return False

    except httpx.ConnectError:
        fail(f"连接 {API_BASE} 失败，请检查网络或 API_BASE 配置")
        return False

    except Exception as e:
        fail(f"异常: {e}")
        return False


def main():
    print(f"{'=' * 60}")
    print("   MinerU API Key 可用性测试")
    print(f"{'=' * 60}")

    tokens = parse_tokens(TOKENS_STR)
    if not tokens:
        print(f"\n{RED}错误:{RESET} 未配置 Token")
        print("请在 .env 中设置 MINERU_TOKENS 或 MINERU_API_TOKEN")
        return

    # 去重
    seen = set()
    unique_tokens = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique_tokens.append(t)

    print(f"\n共 {len(unique_tokens)} 个 Token (去重后)")
    print(f"测试接口: {API_BASE}/api/v4/extract/task")
    print(f"测试文件: {TEST_URL}")
    print("-" * 60)

    total = len(unique_tokens)
    valid = 0
    invalid = 0

    for i, token in enumerate(unique_tokens, 1):
        if test_token(token, i, total):
            valid += 1
        else:
            invalid += 1

    print(f"\n{'-' * 60}")
    print(f"结果: {GREEN}{valid} 可用{RESET} / {RED}{invalid} 不可用{RESET} / 共 {total}")


if __name__ == "__main__":
    main()
