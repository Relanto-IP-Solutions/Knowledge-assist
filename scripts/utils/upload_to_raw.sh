#!/usr/bin/env bash
# Upload a test file to GCS raw/ and trigger the ingestion workflow.
#
# Uses predefined test files:
#   documents: data/sample_test3.pdf
#   zoom:      data/test/meeting-1.vtt (or meeting.vtt)
#   slack:     data/test/slack_messages.json + data/test/slack-metadata.json
#
# Usage:
#   ./scripts/utils/upload_to_raw.sh --opp-id oid1023 --source documents
#   ./scripts/utils/upload_to_raw.sh --opp-id oid1023 --source zoom
#   ./scripts/utils/upload_to_raw.sh --opp-id oid1023 --source slack
#
# Requires: gcloud CLI (gsutil, gcloud workflows), configs/.env with GCP_PROJECT_ID, GCS_BUCKET_INGESTION

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_TEST="${PROJECT_ROOT}/data/test"
DATA_ROOT="${PROJECT_ROOT}/data"

# Predefined test files
DOCUMENTS_FILE="${DATA_ROOT}/sample_test3.pdf"
ZOOM_FILE="${DATA_TEST}/meeting.vtt"
ZOOM_FILE_FALLBACK="${DATA_TEST}/meeting-1.vtt"
SLACK_MESSAGES="${DATA_TEST}/slack_messages.json"
SLACK_METADATA="${DATA_TEST}/slack-metadata.json"
SLACK_CHANNEL="test-channel"

OPP_ID=""
SOURCE=""

usage() {
  echo "Usage: $0 --opp-id OPP_ID --source [documents|zoom|slack]"
  echo ""
  echo "  --opp-id   Opportunity ID (required)"
  echo "  --source   documents, zoom, or slack (required)"
  echo ""
  echo "Uses predefined test files:"
  echo "  documents: $DOCUMENTS_FILE"
  echo "  zoom:      $ZOOM_FILE or $ZOOM_FILE_FALLBACK"
  echo "  slack:     $SLACK_MESSAGES + $SLACK_METADATA"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --opp-id) OPP_ID="$2"; shift 2 ;;
    --source) SOURCE="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

if [[ -z "$OPP_ID" || -z "$SOURCE" ]]; then
  echo "Error: --opp-id and --source are required"
  usage
fi

if [[ "$SOURCE" != "documents" && "$SOURCE" != "zoom" && "$SOURCE" != "slack" ]]; then
  echo "Error: source must be 'documents', 'zoom', or 'slack'"
  exit 1
fi

cd "$PROJECT_ROOT"

BUCKET=$(uv run python -c "
from configs.settings import get_settings
print(get_settings().ingestion.gcs_bucket_ingestion)
")
PROJECT_ID=$(uv run python -c "
from configs.settings import get_settings
print(get_settings().ingestion.gcp_project_id)
")
REGION=$(uv run python -c "
from configs.settings import get_settings
s = get_settings()
print(s.llm.vertex_ai_location or s.retrieval.vertex_ai_location or 'us-central1')
")

[[ -n "$PROJECT_ID" ]] || { echo "ERROR: GCP_PROJECT_ID not set in configs/.env" >&2; exit 1; }

echo "=== Uploading to GCS (gs://${BUCKET}/) ==="
if [[ "$SOURCE" == "documents" ]]; then
  [[ -f "$DOCUMENTS_FILE" ]] || { echo "Error: Documents file not found: $DOCUMENTS_FILE" >&2; exit 1; }
  GCS_PATH="${OPP_ID}/raw/documents/$(basename "$DOCUMENTS_FILE")"
  echo "  ${GCS_PATH}"
  gsutil cp "$DOCUMENTS_FILE" "gs://${BUCKET}/${GCS_PATH}"
elif [[ "$SOURCE" == "zoom" ]]; then
  if [[ -f "$ZOOM_FILE" ]]; then
    ZOOM_SRC="$ZOOM_FILE"
  elif [[ -f "$ZOOM_FILE_FALLBACK" ]]; then
    ZOOM_SRC="$ZOOM_FILE_FALLBACK"
  else
    echo "Error: Zoom file not found: $ZOOM_FILE or $ZOOM_FILE_FALLBACK" >&2
    exit 1
  fi
  GCS_PATH="${OPP_ID}/raw/zoom/$(basename "$ZOOM_SRC")"
  echo "  ${GCS_PATH}"
  gsutil cp "$ZOOM_SRC" "gs://${BUCKET}/${GCS_PATH}"
else
  [[ -f "$SLACK_MESSAGES" ]] || { echo "Error: Slack messages not found: $SLACK_MESSAGES" >&2; exit 1; }
  [[ -f "$SLACK_METADATA" ]] || { echo "Error: Slack metadata not found: $SLACK_METADATA" >&2; exit 1; }
  echo "  ${OPP_ID}/raw/slack/${SLACK_CHANNEL}/slack_messages.json"
  gsutil cp "$SLACK_MESSAGES" "gs://${BUCKET}/${OPP_ID}/raw/slack/${SLACK_CHANNEL}/slack_messages.json"
  echo "  ${OPP_ID}/raw/slack/slack_metadata.json"
  gsutil cp "$SLACK_METADATA" "gs://${BUCKET}/${OPP_ID}/raw/slack/slack_metadata.json"
fi
echo "  Upload complete."

echo ""
echo "=== Triggering ingestion workflow (opportunity_id=$OPP_ID, lookback_minutes=2) ==="
gcloud workflows run ingestion-pipeline \
  --location="$REGION" \
  --project="$PROJECT_ID" \
  --data="{\"lookback_minutes\": 2, \"opportunity_id\": \"$OPP_ID\"}"
echo "Workflow triggered. Check status: gcloud workflows executions list ingestion-pipeline --location=$REGION --project=$PROJECT_ID"
echo ""
echo "=== Done ==="
