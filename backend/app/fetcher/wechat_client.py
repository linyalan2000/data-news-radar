"""WeChat Official Account QR login + token management.

Adapted from wechat-radar (https://github.com/cathyzhang0905/wechat-radar).
Uses mp.weixin.qq.com internal APIs to authenticate via QR code scan.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).parent
TOKEN_FILE = _SCRIPT_DIR / "token.json"

_BASE = "https://mp.weixin.qq.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://mp.weixin.qq.com/",
}


class TokenExpiredError(Exception):
    """Raised when the WeChat API token has expired or is invalid."""


def load_token() -> Optional[dict]:
    """Read token from token.json. Returns None if missing or corrupt."""
    if not TOKEN_FILE.exists():
        return None
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Cannot load token.json: %s", e)
        return None


def save_token(token: str, cookies: str, expiry_timestamp: int) -> None:
    """Persist token, cookie string, and expiry to token.json."""
    data = {
        "token": token,
        "cookies": cookies,
        "expiry_timestamp": expiry_timestamp,
    }
    TOKEN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Token saved to %s", TOKEN_FILE)


def is_token_valid(token_data: Optional[dict]) -> bool:
    """Return True if token_data exists and has not expired (10 min buffer)."""
    if not token_data:
        return False
    expiry = token_data.get("expiry_timestamp", 0)
    return time.time() < expiry - 600


_QR_FLAG = Path("/tmp/wechat_login_needed")
_LOGIN_DIR = Path(__file__).resolve().parents[3] / "briefings"  # web-accessible


def _save_qr_web(contents: bytes) -> Optional[Path]:
    """Save QR code to briefings/ for web access, return path or None."""
    try:
        _LOGIN_DIR.mkdir(parents=True, exist_ok=True)
        dst = _LOGIN_DIR / "wechat_qr.png"
        dst.write_bytes(contents)
        logger.info("QR code saved for web: %s", dst)
        return dst
    except Exception as e:
        logger.warning("Failed to save web QR: %s", e)
        return None


def _push_wechat_login_notification() -> None:
    """Push a notification to the configured enterprise WeChat webhook."""
    try:
        webhook_url = ""
        db_path = _SCRIPT_DIR.parent.parent / "dev.db"
        if db_path.exists():
            from sqlalchemy import create_engine, text
            engine = create_engine(f"sqlite:///{db_path}")
            with engine.connect() as c:
                r = c.execute(text("SELECT value FROM system_state WHERE key='webhook_url'")).fetchone()
                if r:
                    webhook_url = r[0]
        if webhook_url:
            msg = {
                "msgtype": "markdown",
                "markdown": {
                    "content": (
                        "⚠️ **微信公众号登录过期**\n"
                        "请及时扫码重新登录，否则公众号文章将停止抓取。\n\n"
                        "> 扫码地址：http://106.52.217.187:3000/api/wechat/qr\n\n"
                        "扫码后系统会自动恢复抓取。"
                    )
                },
            }
            httpx.post(webhook_url, json=msg, timeout=10)
            logger.info("WeChat login notification pushed to webhook")
    except Exception as e:
        logger.warning("Failed to push webhook notification: %s", e)


def login() -> bool:
    """Full QR-code login flow for mp.weixin.qq.com.

    Saves QR to briefings/wechat_qr.png and sets /tmp/wechat_login_needed
    so the health endpoint can signal the user.
    """
    client = httpx.Client(timeout=15)
    client.headers.update(_HEADERS)

    uuid = _start_login(client)
    if not uuid:
        logger.error("Failed to get login uuid")
        return False
    logger.info("Got uuid: %s", uuid)

    qr_local = _download_qrcode(client, uuid)
    if not qr_local:
        logger.error("Failed to download QR code")
        return False

    # Save a copy for web access
    _save_qr_web(qr_local.read_bytes())
    _QR_FLAG.write_text("1")
    logger.warning("=== 微信登录需要扫码！访问 http://106.52.217.187:3000/api/wechat/qr ===")
    # Push webhook notification
    _push_wechat_login_notification()

    print(f"\n请扫描二维码登录微信公众号平台（二维码已保存至 {qr_local}）")

    print("等待扫码...", end="", flush=True)
    scan_ok = _poll_scan(client, uuid, timeout=180)
    if not scan_ok:
        logger.error("Scan timeout or failed")
        _QR_FLAG.unlink(missing_ok=True)
        return False
    print(" 扫码成功！")

    token, cookies, expiry = _do_login(client, uuid)
    if not token:
        logger.error("Failed to get token after scan")
        _QR_FLAG.unlink(missing_ok=True)
        return False

    save_token(token, cookies, expiry)
    # Clear flag
    _QR_FLAG.unlink(missing_ok=True)
    # Clean web QR
    try:
        (_LOGIN_DIR / "wechat_qr.png").unlink(missing_ok=True)
    except Exception:
        pass
    print(
        f"登录成功，token 已保存（有效期至 "
        f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(expiry))}）"
    )
    return True


def _start_login(client: httpx.Client) -> Optional[str]:
    """POST bizlogin?action=startlogin → return uuid."""
    try:
        resp = client.post(
            f"{_BASE}/cgi-bin/bizlogin",
            params={"action": "startlogin"},
            data={
                "userlang": "zh_CN",
                "redirect_url": "",
                "login_type": "3",
                "token": "",
                "lang": "zh_CN",
            },
            headers={**_HEADERS, "Referer": "https://mp.weixin.qq.com/"},
        )
        data = resp.json()
        uuid = (
            data.get("uuid")
            or (data.get("data") or {}).get("uuid")
            or resp.cookies.get("uuid")
        )
        return str(uuid) if uuid else None
    except Exception as e:
        logger.error("startlogin error: %s", e)
        return None


def _download_qrcode(client: httpx.Client, uuid: str) -> Optional[Path]:
    """GET scanloginqrcode → save PNG to /tmp/wechat_qr.png."""
    try:
        resp = client.get(
            f"{_BASE}/cgi-bin/scanloginqrcode",
            params={
                "action": "getqrcode",
                "uuid": uuid,
                "rd": str(int(time.time() * 1000)),
            },
        )
        if resp.status_code == 200 and resp.content:
            qr_path = Path(tempfile.gettempdir()) / "wechat_qr.png"
            qr_path.write_bytes(resp.content)
            return qr_path
    except Exception as e:
        logger.error("getqrcode error: %s", e)
    return None


def _poll_scan(client: httpx.Client, uuid: str, timeout: int = 180) -> bool:
    """Poll scanloginqrcode?action=ask until status==1 or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = client.get(
                f"{_BASE}/cgi-bin/scanloginqrcode",
                params={
                    "action": "ask",
                    "uuid": uuid,
                    "rd": str(int(time.time() * 1000)),
                },
            )
            data = resp.json()
            status = data.get("status") or (data.get("data") or {}).get("status")
            if status == 1:
                return True
            if status == 2:
                logger.warning("QR code expired, need to restart login")
                return False
        except Exception as e:
            logger.warning("poll scan error: %s", e)
        print(".", end="", flush=True)
        time.sleep(2)
    return False


def _do_login(
    client: httpx.Client, uuid: str
) -> tuple[Optional[str], str, int]:
    """POST bizlogin?action=login → extract token + cookies + expiry."""
    try:
        resp = client.post(
            f"{_BASE}/cgi-bin/bizlogin",
            params={"action": "login"},
            data={
                "userlang": "zh_CN",
                "redirect_url": "",
                "uuid": uuid,
                "login_type": "3",
                "token": "",
                "lang": "zh_CN",
            },
            headers={**_HEADERS, "Referer": "https://mp.weixin.qq.com/"},
        )
        data = resp.json()
        redirect_url = data.get("redirect_url", "")
        token = None
        if redirect_url:
            parsed = urlparse(redirect_url)
            qs = parse_qs(parsed.query)
            token = (qs.get("token") or [None])[0]
        if not token:
            token = str(data.get("token", "") or None)

        cookie_str = "; ".join(
            f"{name}={value}" for name, value in client.cookies.items()
        )
        # Token expires ~72 hours; don't bother parsing slave_sid
        expiry = int(time.time() + 72 * 3600)
        return token, cookie_str, expiry
    except Exception as e:
        logger.error("do_login error: %s", e)
        return None, "", 0
