"""重置用户密码 / 创建管理员（本地开发用）。

用法：
    .venv/bin/python scripts/reset_password.py admin 你的新密码
    .venv/bin/python scripts/reset_password.py --create-admin boss boss123456

注意：本脚本直接改数据库，不走 API。
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from src.auth import hash_password  # noqa: E402
from src.db import async_session  # noqa: E402
from src.models import User  # noqa: E402


async def reset_password(username: str, password: str) -> bool:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user:
            print(f"❌ 用户不存在: {username}")
            return False
        user.password_hash = hash_password(password)
        # 顺手解封，避免测试时被 banned_until 挡住
        user.enabled = True
        user.banned_until = None
        await session.commit()
        print(f"✅ 已重置 {username} 的密码（role={user.role}）")
        return True


async def create_admin(username: str, password: str) -> bool:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.username == username))
        if result.scalar_one_or_none():
            print(f"⚠️ 用户已存在: {username}（改用 reset_password 重置密码）")
            return False
        session.add(
            User(
                username=username,
                password_hash=hash_password(password),
                role="admin",
                enabled=True,
            )
        )
        await session.commit()
        print(f"✅ 已创建管理员 {username}")
        return True


async def list_users() -> None:
    async with async_session() as session:
        rows = (await session.execute(select(User).order_by(User.created_at))).scalars().all()
        print(f"{'用户名':<16}{'角色':<8}{'状态':<10}{'邮箱'}")
        print("-" * 56)
        for u in rows:
            status = "正常" if u.enabled else ("已封禁" if u.banned_until else "待审核")
            print(f"{u.username:<16}{u.role:<8}{status:<10}{u.email or '-'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="重置密码 / 创建管理员 / 列出用户")
    parser.add_argument("username", nargs="?", help="用户名")
    parser.add_argument("password", nargs="?", help="新密码")
    parser.add_argument("--create-admin", action="store_true", help="创建管理员而非重置密码")
    parser.add_argument("--list", action="store_true", help="列出全部用户")
    args = parser.parse_args()

    if args.list:
        asyncio.run(list_users())
        return

    if not args.username or not args.password:
        parser.error("需要提供 username 和 password（或用 --list）")

    if args.create_admin:
        asyncio.run(create_admin(args.username, args.password))
    else:
        asyncio.run(reset_password(args.username, args.password))


if __name__ == "__main__":
    main()
