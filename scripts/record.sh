#!/usr/bin/env bash
# Continuous arecord loop. Writes 15-second WAV chunks to $RECORDINGS_NEW_DIR.
# Called by birdstation-record.service. Verify device name with: arecord -l

set -euo pipefail

: "${RECORDINGS_NEW_DIR:?RECORDINGS_NEW_DIR must be set}"

echo "Starting recording loop → ${RECORDINGS_NEW_DIR}"

while true; do
    FILENAME="${RECORDINGS_NEW_DIR}/$(date +%Y%m%d_%H%M%S).wav"
    arecord \
        --device=plughw:CARD=Snowball,DEV=0 \
        --format=S16_LE \
        --rate=16000 \
        --channels=1 \
        --duration=15 \
        "$FILENAME" 2>/dev/null || true
done
