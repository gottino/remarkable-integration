#!/bin/bash

# Create logs directory if it doesn't exist
mkdir -p data/logs

# Generate timestamp for log filename
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
LOG_FILE="data/logs/processing_${TIMESTAMP}.log"

# Function to log with timestamp
log_with_timestamp() {
    while IFS= read -r line; do
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] $line" | tee -a "$LOG_FILE"
    done
}

echo "Starting processing with logging to: $LOG_FILE"
echo "========================================"

# Run the command and pipe both stdout and stderr to the logging function
"$@" 2>&1 | log_with_timestamp

echo "========================================"
echo "Processing complete. Log saved to: $LOG_FILE"