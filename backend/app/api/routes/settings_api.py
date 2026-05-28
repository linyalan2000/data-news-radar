"""API for system settings stored in database."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.deps import get_db

router = APIRouter()

_SETTING_KEYS = {
    "webhook_url": "企业微信 Webhook URL",
    "sources_wechat": "微信公众号列表（逗号分隔）",
    "sources_gov": "官网源列表（逗号分隔）",
    "keywords_cls": "财联社关键词（逗号分隔）",
}


class SettingsResponse(BaseModel):
    settings: dict[str, str] = {}


@router.get("/api/settings/all", response_model=SettingsResponse)
def get_all_settings(db: Session = Depends(get_db)):
    from app.store.news_store import NewsStore
    from app.config import settings as app_settings
    store = NewsStore(session=db)
    # Defaults from .env
    defaults = {
        "webhook_url": "",
        "sources_wechat": ",".join(app_settings.wechat_accounts_list),
        "sources_gov": "",
        "keywords_cls": app_settings.cls_keywords,
    }
    result = {}
    for key in _SETTING_KEYS:
        result[key] = store.get_system_state(key) or defaults.get(key, "")
    return SettingsResponse(settings=result)


@router.put("/api/settings/all", response_model=SettingsResponse)
def set_all_settings(data: SettingsResponse, db: Session = Depends(get_db)):
    from app.store.news_store import NewsStore
    store = NewsStore(session=db)
    for key, value in data.settings.items():
        if key in _SETTING_KEYS:
            store.set_system_state(key, value)
    db.commit()
    # Return all current values
    result = {}
    for key in _SETTING_KEYS:
        result[key] = store.get_system_state(key) or ""
    return SettingsResponse(settings=result)
