#!/bin/bash

PROJECT_DIR="/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project"
PYTHON_BIN="/mnt/c/Users/samir/OneDrive/Desktop/New folder (2)/Ardent Mills project/production_pipelines/deploy/.venv/bin/python"
LOG_FILE="$PROJECT_DIR/production_pipelines/logs/inc_pipeline.log"

cd "$PROJECT_DIR" || exit 1

mkdir -p "$PROJECT_DIR/production_pipelines/logs"

echo "===== PIPELINE STARTED $(date) =====" >> "$LOG_FILE"

"$PYTHON_BIN" production_pipelines/01_oltp_load_pipeline.py >> "$LOG_FILE" 2>&1

if [ $? -eq 0 ]; then
    echo "01 OLTP load completed successfully" >> "$LOG_FILE"

    "$PYTHON_BIN" production_pipelines/02_oltp_to_olap_incremental_pipeline.py --skip-oltp >> "$LOG_FILE" 2>&1

    if [ $? -eq 0 ]; then
        echo "02 OLTP-to-OLAP incremental load completed successfully" >> "$LOG_FILE"

        "$PYTHON_BIN" production_pipelines/03_audit_control_pipeline.py >> "$LOG_FILE" 2>&1

        if [ $? -eq 0 ]; then
            echo "03 audit/control pipeline completed successfully" >> "$LOG_FILE"
        else
            echo "03 audit/control pipeline failed" >> "$LOG_FILE"
        fi
    else
        echo "02 OLTP-to-OLAP incremental load failed. Stopping pipeline." >> "$LOG_FILE"
    fi
else
    echo "01 OLTP load failed. Stopping pipeline." >> "$LOG_FILE"
fi

echo "===== PIPELINE ENDED $(date) =====" >> "$LOG_FILE"
