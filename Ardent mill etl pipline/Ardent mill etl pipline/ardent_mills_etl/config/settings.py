"""
config/settings.py
──────────────────
Central configuration for the Ardent Mills ETL pipeline.
Edit ORACLE_CONFIG and EXCEL_FILE_PATH before running.
"""

from pathlib import Path

# ── Source file ────────────────────────────────────────────────────────────────
EXCEL_FILE_PATH = Path("Ardent_Mills_Data.xlsx")
SOURCE_SHEETS = ["Pack", "Mill", "Sales", "WorkOrder", "BinCleaning", "Fills"]

# ── Output files ───────────────────────────────────────────────────────────────
VALIDATION_WORKBOOK_PATH = Path("Ardent_Mills_ETL_Test_Cases.xlsx")
DIAGNOSTICS_JSON_PATH = Path("Ardent_Mills_ETL_Diagnostics.json")
CHANGE_AUDIT_WORKBOOK_PATH = Path("Ardent_Mills_ETL_Change_Audit.xlsx")
CHANGE_SNAPSHOT_PATH = Path("Ardent_Mills_ETL_Snapshot.json")
CREATED_BY = "Maruthi_RM"
UNKNOWN_TEXT = "UNKNOWN"

# ── Oracle connection ──────────────────────────────────────────────────────────
ORACLE_CONFIG = {
    "host": "ec2-3-111-0-185.ap-south-1.compute.amazonaws.com",
    "port": 1521,
    "service_name": "orcl",
    "username": "maruthi_nov25",
    "password": "maruthi_nov25",
    # "dsn": "host:port/service_name",   # override everything above
    # "thick_mode": True,                # set True if using Oracle Instant Client
}

# ── Alert configuration ──────────────────────────────────────────────────────
ALERT_CONFIG = {
    "enable_email": True,  # Set to True to enable email alerts (configure SMTP settings below)
    "smtp_server": "smtp.gmail.com",  # Example: Gmail SMTP
    "smtp_port": 587,
    "sender_email": "maruthi4199@gmail.com",  # Replace with actual sender email
    "sender_password": "uyrkdpgwyoagpjsn",  # Use app password for Gmail
    "recipient_emails": ["maruthi.rm@aroha.co.in"],  # Emails to receive alerts
}
