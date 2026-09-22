"""Create private local service credentials without overwriting existing settings."""

import json
import os
import secrets
from pathlib import Path


def main() -> None:
    """Initialize a new local checkout's private configuration.

    Existing configuration and ledgers are preserved. Provider credentials are
    inherited from the environment and never copied to a generated file.
    """
    env = Path(".env")
    if not env.exists():
        password = secrets.token_urlsafe(32)
        key = secrets.token_urlsafe(32)
        lines = [
            f"NEWTON_POSTGRES_PASSWORD={password}",
            f"NEWTON_DATABASE_URL=postgresql+psycopg://newton:{password}@127.0.0.1:15432/newton",
            f"NEWTON_WEAVIATE_API_KEY={key}",
        ]
        descriptor = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write("\n".join(lines) + "\n")
    Path(".runtime/data").mkdir(parents=True, exist_ok=True, mode=0o700)
    ledger = Path(".runtime/budget.json")
    if not ledger.exists():
        ledger.write_text(json.dumps({"currency": "EUR", "ceiling": 0, "paid_attempts": []}))
    print("Local configuration ready; existing values preserved; no provider keys written.")


if __name__ == "__main__":
    main()
