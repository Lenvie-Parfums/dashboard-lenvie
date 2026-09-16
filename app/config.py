import json, os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    omie_app_key: str
    omie_app_secret: str
    spreadsheet_id: str
    google_service_account_json: dict
    admin_token: str


def get_settings() -> Settings:
    raw = os.environ.get("GOOGLE_SA_JSON", "")
    if not raw:
        raise RuntimeError("GOOGLE_SA_JSON não configurado")
    return Settings(
        omie_app_key=os.environ["APP_KEY_OMIE"],
        omie_app_secret=os.environ["APP_SECRET_OMIE"],
        spreadsheet_id=os.environ["GOOGLE_SPREADSHEET_ID"],
        google_service_account_json=json.loads(raw),
        admin_token=os.environ.get("ADMIN_TOKEN", ""),
    )
