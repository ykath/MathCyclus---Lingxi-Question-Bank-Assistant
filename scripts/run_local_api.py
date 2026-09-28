"""Run the localhost draft-only API used by browser/GPT helper scripts."""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.local_api_service import create_local_api_server


def main() -> int:
    parser = argparse.ArgumentParser(description="MathCyclus localhost draft API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default="data/mathcyclus.sqlite3")
    parser.add_argument(
        "--token",
        default=os.environ.get("MATHCYCLUS_API_TOKEN", ""),
        help="API token; defaults to a fresh random token for this process",
    )
    parser.add_argument("--no-auth", action="store_true", help="Only use this on a private local test machine")
    args = parser.parse_args()

    token = "" if args.no_auth else (str(args.token).strip() or secrets.token_urlsafe(24))
    server = create_local_api_server(
        args.host,
        args.port,
        db_path=args.db,
        auth_token=token,
        migrate=True,
    )
    print(f"MathCyclus local draft API: http://{args.host}:{server.server_port}")
    print("模式：仅草稿 API；批准与正式入库仍需在 Streamlit 人工审核页面完成。")
    if token:
        print(f"本次 token（仅显示一次）：{token}")
        print("浏览器 JS 请求时放入 Authorization: Bearer <token>。")
    else:
        print("警告：当前未启用 token，仅建议在本机临时测试使用。")
    print("按 Ctrl+C 停止 API。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAPI 已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

