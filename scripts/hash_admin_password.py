from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.auth import AuthService


def main() -> int:
    password = getpass.getpass("管理员密码：")
    confirmation = getpass.getpass("再次输入密码：")
    if password != confirmation:
        raise SystemExit("两次输入的密码不一致。")
    print(AuthService.hash_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
