"""Multi-account management for Railguey.

Stores account tokens in ~/.railguey/accounts.json. Supports multiple
Railway accounts (personal, team workspaces) without depending on the
Railway CLI.

Config format:
{
  "accounts": {
    "aic-holdings": {
      "token": "rw_...",
      "email": "dshanklin@aicholdings.com",
      "default_workspace_id": "...",
      "workspaces": {
        "AIC Holdings": "workspace-uuid",
        "Personal": "workspace-uuid"
      }
    },
    "eidos": {
      "token": "rw_...",
      "email": "daniel@eidosagi.com",
      ...
    }
  },
  "default_account": "aic-holdings"
}
"""

import json
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / ".railguey"
CONFIG_FILE = CONFIG_DIR / "accounts.json"


def _load_config() -> dict:
    if not CONFIG_FILE.is_file():
        return {"accounts": {}, "default_account": None}
    return json.loads(CONFIG_FILE.read_text())


def _save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")


def add_account(name: str, token: str, email: Optional[str] = None) -> dict:
    """Register a Railway account token under a name."""
    config = _load_config()
    config["accounts"][name] = {
        "token": token,
        "email": email or "",
        "default_workspace_id": None,
        "workspaces": {},
    }
    if not config["default_account"]:
        config["default_account"] = name
    _save_config(config)
    return {"added": name, "is_default": config["default_account"] == name}


def remove_account(name: str) -> dict:
    """Remove a stored account."""
    config = _load_config()
    if name not in config["accounts"]:
        return {"error": f"Account '{name}' not found"}
    del config["accounts"][name]
    if config["default_account"] == name:
        config["default_account"] = next(iter(config["accounts"]), None)
    _save_config(config)
    return {"removed": name}


def list_accounts() -> dict:
    """List all stored accounts."""
    config = _load_config()
    return {
        "accounts": {
            name: {"email": acct.get("email", ""), "workspaces": acct.get("workspaces", {})}
            for name, acct in config["accounts"].items()
        },
        "default_account": config.get("default_account"),
    }


def set_default_account(name: str) -> dict:
    config = _load_config()
    if name not in config["accounts"]:
        return {"error": f"Account '{name}' not found"}
    config["default_account"] = name
    _save_config(config)
    return {"default_account": name}


def get_account_token(name: Optional[str] = None) -> str:
    """Get the token for a named account, or the default account.

    Falls back to:
    1. Named account in ~/.railguey/accounts.json
    2. Default account in ~/.railguey/accounts.json
    3. RAILWAY_USER_TOKEN env var
    4. ~/.railway/config.json (CLI fallback, last resort)
    """
    import os

    config = _load_config()

    # Named account
    if name and name in config["accounts"]:
        return config["accounts"][name]["token"]

    # Default account
    default = config.get("default_account")
    if default and default in config["accounts"]:
        return config["accounts"][default]["token"]

    # Env var fallback
    env_token = os.environ.get("RAILWAY_USER_TOKEN")
    if env_token:
        return env_token

    # CLI fallback (last resort)
    cli_config = Path.home() / ".railway" / "config.json"
    if cli_config.is_file():
        data = json.loads(cli_config.read_text())
        token = data.get("user", {}).get("token", "")
        if token:
            return token

    raise ValueError(
        "No Railway account token found. Use railguey_account_add to register an account, "
        "or set RAILWAY_USER_TOKEN environment variable."
    )


def set_workspace(account_name: str, workspace_name: str, workspace_id: str) -> dict:
    """Store a workspace ID for an account."""
    config = _load_config()
    if account_name not in config["accounts"]:
        return {"error": f"Account '{account_name}' not found"}
    config["accounts"][account_name]["workspaces"][workspace_name] = workspace_id
    _save_config(config)
    return {"account": account_name, "workspace": workspace_name, "id": workspace_id}


def set_default_workspace(account_name: str, workspace_id: str) -> dict:
    """Set the default workspace for an account."""
    config = _load_config()
    if account_name not in config["accounts"]:
        return {"error": f"Account '{account_name}' not found"}
    config["accounts"][account_name]["default_workspace_id"] = workspace_id
    _save_config(config)
    return {"account": account_name, "default_workspace_id": workspace_id}


def get_workspace_id(account_name: Optional[str] = None, workspace_name: Optional[str] = None) -> Optional[str]:
    """Resolve workspace ID from account + workspace name."""
    config = _load_config()
    acct_name = account_name or config.get("default_account")
    if not acct_name or acct_name not in config["accounts"]:
        return None
    acct = config["accounts"][acct_name]
    if workspace_name:
        return acct.get("workspaces", {}).get(workspace_name)
    return acct.get("default_workspace_id")
