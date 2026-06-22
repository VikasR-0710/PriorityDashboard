"""
Delinea Secret Server credential loader.
Fetches shared service-account credentials from Delinea Secret Server.
"""
from __future__ import annotations  # FIXED: Added double underscores
import json
import logging
import os
import time
from pathlib import Path
import requests

logger = logging.getLogger(__name__)  # FIXED: Added double underscores

# ---------------------------------------------------------------------------
# Bootstrap — values required to authenticate to Delinea itself
# ---------------------------------------------------------------------------
_PLATFORM_URL = "https://xactlycorp.delinea.app"
_SS_HOST = "https://xactlycorp.secretservercloud.com"
_CLIENT_ID = os.getenv("DELINEA_CLIENT_ID", "agenticsupportsa1@xactlycorp.com")
_CLIENT_SECRET_FILE = os.getenv(
    "DELINEA_CLIENT_SECRET_FILE",
    str(Path.home() / ".config" / "xactly_support" / "delinea_client_secret"),
)
_TOKEN_FILE = "/tmp/delinea_token_shared.json"
_COMMENT = "Automated access by Xactly Support Agent"
_FOLDER_SHARED = "433"
_FOLDER_ORACLE = "796"
_FOLDER_SYSADMIN = "798"

_ORACLE_SECRET_NAMES = {
    "secure1": "SECURE1 - Oracle", "secure2": "SECURE2 - Oracle",
    "secure3": "SECURE3 - Oracle", "secure4": "SECURE4 - Oracle",
    "secure5": "SECURE5 - Oracle", "eu1": "EU1 - Oracle",
}
_SYSADMIN_SECRET_NAMES = {
    "secure1": "SECURE1 - SysAdmin", "secure2": "SECURE2 - SysAdmin",
    "secure3": "SECURE3 - SysAdmin", "secure4": "SECURE4 - SysAdmin",
    "secure5": "SECURE5 - SysAdmin", "secure6": "SECURE6 - SysAdmin",
    "eu1": "EU1 - SysAdmin",
}

def _load_client_secret() -> str:
    env_secret = os.getenv("DELINEA_CLIENT_SECRET", "").strip()
    if env_secret:
        return env_secret
    try:
        return Path(_CLIENT_SECRET_FILE).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        logger.warning("Delinea: could not read client secret file %s — %s", _CLIENT_SECRET_FILE, exc)
        return ""

_CLIENT_SECRET = _load_client_secret()

# ---------------------------------------------------------------------------
# OAuth2 token management
# ---------------------------------------------------------------------------
def _get_new_token() -> str:
    if not _CLIENT_SECRET:
        raise RuntimeError(f"Delinea client secret is required. Create {_CLIENT_SECRET_FILE} or set DELINEA_CLIENT_SECRET.")
    
    resp = requests.post(
        f"{_PLATFORM_URL}/identity/api/oauth2/token/xpmplatform",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials", "scope": "xpmheadless", "client_id": _CLIENT_ID, "client_secret": _CLIENT_SECRET},
        timeout=30,
    )
    resp.raise_for_status()
    token_data = resp.json()
    token_data["token_time"] = int(time.time())
    with open(_TOKEN_FILE, "w") as f:
        json.dump(token_data, f)
    return str(token_data["access_token"])

def _is_token_valid() -> bool:
    if not os.path.exists(_TOKEN_FILE):
        return False
    try:
        with open(_TOKEN_FILE) as f:
            data = json.load(f)
        expiry = float(data.get("token_time", 0)) + float(data.get("expires_in", 0))
        return int(time.time()) < (expiry - 60)
    except Exception:
        return False

def _get_access_token() -> str:
    if _is_token_valid():
        with open(_TOKEN_FILE) as f:
            return str(json.load(f)["access_token"])
    return _get_new_token()

def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_access_token()}", "Content-Type": "application/json"}

# ---------------------------------------------------------------------------
# Secret retrieval helpers
# ---------------------------------------------------------------------------
def _get_secret(secret_id: int) -> dict:
    url = f"{_SS_HOST}/api/v1/secrets/{secret_id}"
    resp = requests.get(url, headers=_headers(), timeout=30)
    if resp.status_code in (400, 403):
        resp = requests.post(f"{_SS_HOST}/api/v1/secrets/{secret_id}/restricted", headers=_headers(), json={"comment": _COMMENT}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}

def _field(secret_data: dict, name: str) -> str | None:
    for item in secret_data.get("items", []):
        if item.get("fieldName") == name:
            value = item.get("itemValue")
            return str(value) if value is not None else None
    return None

def _get_secret_by_name(folder_id: str, secret_name: str) -> dict | None:
    resp = requests.get(
        f"{_SS_HOST}/api/v1/secrets",
        params={"filter.folderId": folder_id, "filter.searchText": secret_name, "filter.includeRestricted": "true", "take": "10"},
        headers=_headers(), timeout=30,
    )
    resp.raise_for_status()
    for record in resp.json().get("records", []):
        if record.get("name") == secret_name:
            return _get_secret(record["id"])
    logger.warning("Delinea: secret '%s' not found in folder %s", secret_name, folder_id)
    return None

# ---------------------------------------------------------------------------
# Public credential fetch functions
# ---------------------------------------------------------------------------
def fetch_salesforce_credentials() -> dict | None:
    try:
        secret = _get_secret_by_name(_FOLDER_SHARED, "Agentic Support Salesforce Account")
        if not secret: return None
        return {"username": _field(secret, "Username"), "password": _field(secret, "Password"), "security_token": ""}
    except Exception as exc:
        logger.error("Delinea: could not fetch Salesforce credentials — %s", exc)
        return None

def fetch_snowflake_credentials() -> dict | None:
    try:
        secret = _get_secret_by_name(_FOLDER_SHARED, "Agentic Support Snowflake Account")
        if not secret: return None
        account_id = (_field(secret, "AccountId") or "").replace(".snowflakecomputing.com", "").strip()
        return {"account": account_id, "user": _field(secret, "Username"), "password": _field(secret, "Password")}
    except Exception as exc:
        logger.error("Delinea: could not fetch Snowflake credentials — %s", exc)
        return None

def fetch_openai_credentials() -> dict | None:
    try:
        secret = _get_secret_by_name(_FOLDER_SHARED, "Agentic Support API Key")
        if not secret: return None
        return {"api_key": _field(secret, "API Key")}
    except Exception as exc:
        logger.error("Delinea: could not fetch OpenAI credentials — %s", exc)
        return None