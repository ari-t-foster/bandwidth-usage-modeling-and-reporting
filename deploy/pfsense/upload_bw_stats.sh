#!/bin/sh
PATH="${PATH}:/usr/local/bin"
date_suffix=$(date '+%y%m%d')
day=$(date '+%d')
LOCAL_FOLDER="${LOCAL_FOLDER:-/root/.upload_bw_stats}"
COPY_FILES=""
WAN_INTERFACE="${WAN_INTERFACE:-bge0}"
REMOTE_USER="${REMOTE_USER:-bandwidth-usage-upload}"
REMOTE_HOST="${REMOTE_HOST:-receiver.example.net}"
REMOTE_PATH="${REMOTE_PATH:-bandwidth-usage/}"
MONTHLY_FILE="${LOCAL_FOLDER}/monthly.vnstat.${date_suffix}.json"
DAILY_FILE="${LOCAL_FOLDER}/daily.vnstat.${date_suffix}.json"
#if [ "$day" -eq 1 ]; then
vnstat -d 31 --json | jq --arg interface "$WAN_INTERFACE" ' objects | .interfaces.[] | select(.name == $interface) | .["traffic"] | .month' >"$MONTHLY_FILE"
#fi
vnstat -m 3 --json | jq --arg interface "$WAN_INTERFACE" ' objects | .interfaces.[] | select(.name == $interface) | .["traffic"] | .day' >"$DAILY_FILE"
if [ -f "$MONTHLY_FILE" ]; then
  COPY_FILES="${COPY_FILES} ${MONTHLY_FILE}"
fi
if [ -f "$DAILY_FILE" ]; then
  COPY_FILES="${COPY_FILES} ${DAILY_FILE}"
fi
if [ $# -eq 1 ] && [ "$1" = "-v" ]; then
   scp -vvv -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $COPY_FILES "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}"
else
   scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $COPY_FILES "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}"
fi
