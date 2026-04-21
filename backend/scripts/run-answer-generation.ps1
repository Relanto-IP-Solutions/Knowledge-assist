# Run Answer Generation via RAG Orchestrator
# Usage: .\run-answer-generation.ps1 [-OpportunityId <string>]

param(
[string]$OpportunityId = "oid1"
)

$URL = "https://us-central1-eighth-bivouac-490806-s2.cloudfunctions.net/rag-orchestrator"

$TOKEN = gcloud auth print-identity-token

$body = @{
    opportunity_id = $OpportunityId
} | ConvertTo-Json -Compress

curl.exe -i -X POST $URL `
    -H "Authorization: Bearer $TOKEN" `
    -H "Content-Type: application/json" `
    -d $body
