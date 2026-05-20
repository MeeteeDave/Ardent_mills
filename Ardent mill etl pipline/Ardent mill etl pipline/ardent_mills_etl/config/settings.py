"""
Central configuration for the Ardent Mills ETL pipeline.
Secrets are loaded from the repository root .env file.
"""

import os
from pathlib import Path


def load_dotenv() -> None:
    for parent in Path(__file__).resolve().parents:
        path = parent / ".env"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return


def getenv_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def getenv_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def getenv_list(name: str, default: list[str] | None = None) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


load_dotenv()

EXCEL_FILE_PATH = Path("Ardent_Mills_Data.xlsx")
SOURCE_SHEETS = ["Pack", "Mill", "Sales", "WorkOrder", "BinCleaning", "Fills"]

VALIDATION_WORKBOOK_PATH = Path("Ardent_Mills_ETL_Test_Cases.xlsx")
DIAGNOSTICS_JSON_PATH = Path("Ardent_Mills_ETL_Diagnostics.json")
CHANGE_AUDIT_WORKBOOK_PATH = Path("Ardent_Mills_ETL_Change_Audit.xlsx")
CHANGE_SNAPSHOT_PATH = Path("Ardent_Mills_ETL_Snapshot.json")
CREATED_BY = "Maruthi_RM"
UNKNOWN_TEXT = "UNKNOWN"

ORACLE_CONFIG = {
    "host": os.getenv("ARDENT_OLTP_ORACLE_HOST") or os.getenv("ARDENT_ORACLE_HOST", ""),
    "port": getenv_int("ARDENT_OLTP_ORACLE_PORT", getenv_int("ARDENT_ORACLE_PORT", 1521)),
    "service_name": os.getenv("ARDENT_OLTP_ORACLE_SERVICE") or os.getenv("ARDENT_ORACLE_SERVICE", "orcl"),
    "username": os.getenv("ARDENT_OLTP_ORACLE_USER") or os.getenv("ARDENT_ORACLE_USER", ""),
    "password": os.getenv("ARDENT_OLTP_ORACLE_PASSWORD") or os.getenv("ARDENT_ORACLE_PASSWORD", ""),
    # "dsn": "host:port/service_name",   # override everything above
    # "thick_mode": True,                # set True if using Oracle Instant Client
}

ALERT_CONFIG = {
    "enable_email": getenv_bool("ARDENT_ALERT_ENABLE_EMAIL", False),
    "smtp_server": os.getenv("ARDENT_ALERT_SMTP_SERVER", ""),
    "smtp_port": getenv_int("ARDENT_ALERT_SMTP_PORT", 587),
    "sender_email": os.getenv("ARDENT_ALERT_SENDER_EMAIL", ""),
    "sender_password": os.getenv("ARDENT_ALERT_SENDER_PASSWORD", ""),
    "recipient_emails": getenv_list("ARDENT_ALERT_RECIPIENT_EMAILS"),
}
