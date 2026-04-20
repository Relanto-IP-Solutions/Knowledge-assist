#!/usr/bin/env bash
# Test script: upload a Zoom, Slack, or documents file to GCS, trigger ingestion workflow, then RAG orchestrator.
#
# Matches these commands:
#   Documents: gsutil cp data/test/<file> gs://BUCKET/{opp-id}/raw/documents/<file>
#   Slack:     gsutil cp data/test/slack_messages.json gs://BUCKET/{opp-id}/raw/slack/test-channel/slack_messages.json
#              gsutil cp data/test/slack-metadata.json gs://BUCKET/{opp-id}/raw/slack/slack_metadata.json
#   Zoom:      gsutil cp data/test/meeting.vtt gs://BUCKET/{opp-id}/raw/zoom/meeting.vtt
#   Ingest:    gcloud workflows run ingestion-pipeline --data='{"lookback_minutes": 2, "opportunity_id": "..."}'
#   RAG:       curl -X POST $RAG_ORCH_URL -d '{}'
#
# Uses data/test/: meeting.vtt (or meeting-1.vtt), slack_messages.json, slack-metadata.json;
#   for documents: --document-file NAME (file under data/test/ or data/test/documents/)
#
# Usage:
#   ./scripts/tests_integration/test_ingestion_and_rag.sh --opp-id oid1023 --source zoom
#   ./scripts/tests_integration/test_ingestion_and_rag.sh --opp-id oid1023 --source slack
#   ./scripts/tests_integration/test_ingestion_and_rag.sh --opp-id oid1023 --source documents --document-file sample.pdf
#
# Prerequisites:
#   - gcloud auth login && gcloud auth application-default login
#   - PROJECT_ID, REGION, GCS_BUCKET_INGESTION set (or use defaults)
#   - Workflow ingestion-pipeline and Cloud Run rag-orchestrator deployed

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_TEST="${SCRIPT_DIR}/../data/test"

# Hardcoded paths (data/test/)
ZOOM_FILE="${DATA_TEST}/meeting.vtt"
ZOOM_FILE_FALLBACK="${DATA_TEST}/meeting-1.vtt"
SLACK_MESSAGES="${DATA_TEST}/slack_messages.json"
SLACK_METADATA="${DATA_TEST}/slack-metadata.json"
SLACK_CHANNEL="test-channel"
DOCUMENTS_DIR="${DATA_TEST}/documents"
DOCUMENT_FILE_DEFAULT="sample.pdf"

PROJECT_ID="${PROJECT_ID:-your-gcp-project-id}"
REGION="${REGION:-us-central1}"
BUCKET="${GCS_BUCKET_INGESTION:-${PROJECT_ID}-ingestion}"
LOOKBACK_MINUTES="${LOOKBACK_MINUTES:-2}"
WAIT_SECONDS="${WAIT_FOR_INGESTION:-60}"

OPP_ID=""
SOURCE=""
DOCUMENT_FILE_NAME=""

usage() {
  echo "Usage: $0 --opp-id OPP_ID --source [zoom|slack|documents] [--document-file FILENAME]"
  echo ""
  echo "  --opp-id          Opportunity ID (required)"
  echo "  --source          zoom, slack, or documents (required)"
  echo "  --document-file   For source=documents: filename under data/test/ or data/test/documents/ (required for documents)"
  echo ""
  echo "  zoom:      data/test/meeting.vtt (or meeting-1.vtt)"
  echo "  slack:     data/test/slack_messages.json + slack-metadata.json"
  echo "  documents: put file in data/test/ or data/test/documents/, pass name with --document-file"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --opp-id) OPP_ID="$2"; shift 2 ;;
    --source) SOURCE="$2"; shift 2 ;;
    --document-file) DOCUMENT_FILE_NAME="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

if [[ -z "$OPP_ID" || -z "$SOURCE" ]]; then
  echo "Error: --opp-id and --source are required"
  usage
fi

if [[ "$SOURCE" != "zoom" && "$SOURCE" != "slack" && "$SOURCE" != "documents" ]]; then
  echo "Error: source must be 'zoom', 'slack', or 'documents'"
  exit 1
fi

if [[ "$SOURCE" == "documents" && -z "$DOCUMENT_FILE_NAME" ]]; then
  echo "Error: --document-file FILENAME is required when --source is documents"
  usage
fi

if [[ "$SOURCE" == "zoom" ]]; then
  if [[ -f "$ZOOM_FILE" ]]; then
    ZOOM_SRC="$ZOOM_FILE"
  elif [[ -f "$ZOOM_FILE_FALLBACK" ]]; then
    ZOOM_SRC="$ZOOM_FILE_FALLBACK"
  else
    echo "Error: Zoom file not found: $ZOOM_FILE or $ZOOM_FILE_FALLBACK"
    exit 1
  fi
  GCS_PATH="${OPP_ID}/raw/zoom/meeting.vtt"
elif [[ "$SOURCE" == "slack" ]]; then
  if [[ ! -f "$SLACK_MESSAGES" ]]; then
    echo "Error: Slack messages not found: $SLACK_MESSAGES"
    exit 1
  fi
  if [[ ! -f "$SLACK_METADATA" ]]; then
    echo "Error: Slack metadata not found: $SLACK_METADATA"
    exit 1
  fi
  GCS_PATH="${OPP_ID}/raw/slack/${SLACK_CHANNEL}/slack_messages.json"
elif [[ "$SOURCE" == "documents" ]]; then
  DOC_NAME="$DOCUMENT_FILE_NAME"
  if [[ -f "${DATA_TEST}/${DOC_NAME}" ]]; then
    DOC_SRC="${DATA_TEST}/${DOC_NAME}"
  elif [[ -f "${DOCUMENTS_DIR}/${DOC_NAME}" ]]; then
    DOC_SRC="${DOCUMENTS_DIR}/${DOC_NAME}"
  else
    echo "Error: Document file not found: ${DATA_TEST}/${DOC_NAME} or ${DOCUMENTS_DIR}/${DOC_NAME}"
    echo "  Put the file in data/test/ or data/test/documents/"
    exit 1
  fi
  GCS_PATH="${OPP_ID}/raw/documents/${DOC_NAME}"
fi

echo "=== Uploading to GCS (gs://${BUCKET}/) ==="
if [[ "$SOURCE" == "zoom" ]]; then
  echo "  ${GCS_PATH}"
  gsutil cp "$ZOOM_SRC" "gs://${BUCKET}/${GCS_PATH}"
elif [[ "$SOURCE" == "slack" ]]; then
  echo "  ${GCS_PATH}"
  gsutil cp "$SLACK_MESSAGES" "gs://${BUCKET}/${GCS_PATH}"
  echo "  ${OPP_ID}/raw/slack/slack_metadata.json"
  gsutil cp "$SLACK_METADATA" "gs://${BUCKET}/${OPP_ID}/raw/slack/slack_metadata.json"
else
  echo "  ${GCS_PATH}"
  gsutil cp "$DOC_SRC" "gs://${BUCKET}/${GCS_PATH}"
fi
echo "  Upload complete."

echo ""
echo "=== Ingestion: gcloud workflows run ingestion-pipeline ==="
gcloud workflows run ingestion-pipeline \
  --location="$REGION" \
  --project="$PROJECT_ID" \
  --data="{\"lookback_minutes\": ${LOOKBACK_MINUTES}, \"opportunity_id\": \"${OPP_ID}\"}"

echo ""
echo "=== Waiting ${WAIT_SECONDS}s for rag-ingestion to process Pub/Sub messages ==="
sleep "$WAIT_SECONDS"

echo ""
echo "=== RAG orchestrator (batch poll, empty body) ==="
RAG_ORCH_URL=$(gcloud run services describe rag-orchestrator --region=$REGION --project=$PROJECT_ID --format='value(status.url)')
curl -s -X POST "$RAG_ORCH_URL" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{}' | jq . 2>/dev/null || cat
echo ""

echo "=== Done ==="
