"""
Central secrets file support.

A single dotenv-style file (default ``C:\\keys\\agencyos.txt``) is the source
of truth for every secret. Configs and templated files reference values with
``{{secret:NAME}}`` placeholders; nothing else stores the real value.

File format (one per line)::

    # comments and blank lines are ignored
    DB_PASS=7#Xy%A!!A2!mPq*L8Wr
    AUTH_SIGNING_KEY=abc123...
    PROD_SSH_PASSWORD="quotes are optional and stripped"

Values are taken literally after the first ``=`` (so ``=`` inside a password is
preserved). Optional surrounding single/double quotes are stripped.
"""
import os
import re
from pathlib import Path
from typing import Dict

_SECRET_RE = re.compile(r"\{\{secret:([A-Za-z0-9_]+)\}\}")

# Resolution order for the secrets file path:
#   1. AIAGENT_SECRETS_FILE env var
#   2. config["secrets_file"] (passed in by the caller)
#   3. this default
DEFAULT_SECRETS_PATH = r"C:\keys\agencyos.txt"


def resolve_secrets_path(config_value: str | None = None) -> str:
    """Pick the secrets-file path from env var, config, or the default."""
    return os.environ.get("AIAGENT_SECRETS_FILE") or config_value or DEFAULT_SECRETS_PATH


def load_secrets(path: str | None = None) -> Dict[str, str]:
    """
    Parse the secrets file into a dict. Returns an empty dict if the file does
    not exist (so deployments that use no placeholders keep working).

    Raises ValueError on a malformed line.
    """
    resolved = resolve_secrets_path(path)
    p = Path(resolved)
    if not p.exists():
        return {}

    secrets: Dict[str, str] = {}
    with open(p, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(
                    f"{resolved}:{lineno}: expected NAME=VALUE, got: {line!r}"
                )
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip()
            # Strip a single layer of matching surrounding quotes.
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if not name:
                raise ValueError(f"{resolved}:{lineno}: empty secret name")
            secrets[name] = value
    return secrets


def has_secret_placeholder(text: str) -> bool:
    """True if ``text`` contains at least one ``{{secret:NAME}}`` reference."""
    return bool(_SECRET_RE.search(text))


def substitute(text: str, secrets: Dict[str, str], *, where: str = "") -> str:
    """
    Replace every ``{{secret:NAME}}`` in ``text`` with its value.

    Raises KeyError (with a clear message) if a referenced secret is missing —
    we fail loudly rather than deploy a half-rendered file/config.
    """
    missing = []

    def _repl(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name not in secrets:
            missing.append(name)
            return m.group(0)
        return secrets[name]

    result = _SECRET_RE.sub(_repl, text)
    if missing:
        loc = f" in {where}" if where else ""
        raise KeyError(
            f"Missing secret(s){loc}: {', '.join(sorted(set(missing)))}. "
            f"Add them to the secrets file ({resolve_secrets_path()})."
        )
    return result
