#!/bin/bash

# Usage: ./put_image.sh <image_file> <url>

IMAGE_FILE="$1"
URL="$2"

if [[ -z "$IMAGE_FILE" || -z "$URL" ]]; then
    echo "Usage: $0 <image_file> <url>"
    exit 1
fi

# Encode image to base64 and create JSON payload in a temp file
TMP_PAYLOAD=$(mktemp)
echo -n '{"content":"' > "$TMP_PAYLOAD"
base64 -w 0 "$IMAGE_FILE" >> "$TMP_PAYLOAD"
echo '","deveui":"59129eef47ca3802"}' >> "$TMP_PAYLOAD"

# Send PUT request using the temp file
curl -X PUT -H "Content-Type: application/json" --data-binary @"$TMP_PAYLOAD" "$URL"

# Clean up temp file
rm -f "$TMP_PAYLOAD"