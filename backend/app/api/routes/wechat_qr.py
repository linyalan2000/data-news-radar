"""Serve WeChat QR code image for scanning."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

router = APIRouter()

_QR_FILE = Path(__file__).resolve().parents[4] / "briefings" / "wechat_qr.png"
_FLAG_FILE = Path("/tmp/wechat_login_needed")


_HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>微信扫码登录</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ font-family: -apple-system, sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; background: #f5f5f7; }}
  .card {{ background: white; border-radius: 16px; padding: 40px; text-align: center; box-shadow: 0 2px 12px rgba(0,0,0,.08); max-width: 360px; width: 90%; }}
  .card h2 {{ font-size: 18px; margin: 0 0 4px; color: #1a1a2e; }}
  .card .exp {{ font-size: 13px; color: #999; margin: 0 0 16px; }}
  .card img {{ width: 240px; height: 240px; border: 1px solid #eee; border-radius: 12px; }}
  .card .btn {{ display: inline-block; margin-top: 16px; padding: 10px 24px; border-radius: 8px; background: #e94560; color: white; font-size: 14px; cursor: pointer; border: none; }}
  .card .btn:hover {{ opacity: .9; }}
  .card .btn:disabled {{ opacity: .5; cursor: not-allowed; }}
  .card .status {{ font-size: 13px; margin-top: 12px; color: #999; }}
</style></head>
<body>
<div class="card">
  <h2>微信公众号登录</h2>
  <p class="exp" id="expiry">加载中…</p>
  <img id="qr" src="/api/wechat/qr/img?t={ts}" alt="二维码" />
  <br/>
  <button class="btn" id="refreshBtn" onclick="refreshQR()">刷新二维码</button>
  <div class="status" id="status"></div>
</div>
<script>
function loadExpiry() {{
  fetch('/api/wechat/qr/status').then(function(r) {{ return r.json(); }}).then(function(d) {{
    var el = document.getElementById('expiry');
    if (d.token_expired) {{
      el.innerHTML = 'Token 已过期，请扫码重新登录';
    }} else if (d.expiry) {{
      el.innerHTML = '有效期至：' + d.expiry;
    }} else {{
      el.innerHTML = '暂无 Token';
    }}
  }});
}}
function refreshQR() {{
  var btn = document.getElementById('refreshBtn');
  var st = document.getElementById('status');
  btn.disabled = true; st.textContent = '重新生成中…';
  fetch('/api/wechat/qr/refresh', {{ method: 'POST' }})
    .then(function() {{ setTimeout(function() {{
      document.getElementById('qr').src = '/api/wechat/qr/img?t=' + Date.now();
      btn.disabled = false; st.textContent = '';
    }}, 2000); }});
}}
loadExpiry();
</script>
</body></html>"""


@router.get("/api/wechat/qr", response_class=HTMLResponse)
def get_wechat_qr_page():
    import time
    return HTMLResponse(_HTML_PAGE.format(ts=int(time.time())))


@router.get("/api/wechat/qr/img")
def get_wechat_qr_img():
    if _QR_FILE.exists():
        return FileResponse(str(_QR_FILE), media_type="image/png")
    return JSONResponse(status_code=404, content={"detail": "QR code not available"})


@router.get("/api/wechat/qr/status")
def get_wechat_qr_status():
    import time, json
    from app.fetcher.wechat_client import load_token
    t = load_token()
    if not t:
        return {"token_expired": True, "expiry": None}
    exp = t.get("expiry_timestamp", 0)
    now = time.time()
    if now >= exp:
        return {"token_expired": True, "expiry": time.strftime("%Y-%m-%d %H:%M", time.localtime(exp))}
    return {"token_expired": False, "expiry": time.strftime("%Y-%m-%d %H:%M", time.localtime(exp))}


@router.post("/api/wechat/qr/refresh")
def refresh_wechat_qr():
    import threading
    from app.fetcher.wechat_client import login as wechat_login
    # 立即设标志，避免页面闪烁
    _FLAG_FILE.write_text("1")
    try:
        _QR_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    threading.Thread(target=wechat_login, daemon=True).start()
    return JSONResponse(status_code=202, content={"status": "generating"})
