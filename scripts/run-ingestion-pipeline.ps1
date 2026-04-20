# Run Ingestion Pipeline Workflow
# Usage: .\run-ingestion-pipeline.ps1 [-LookbackMinutes <int>] [-OpportunityId <string>]

param(
    [int]$LookbackMinutes = 1440,
[string]$OpportunityId = "oid1"
)

$data = @{
    lookback_minutes = $LookbackMinutes
    opportunity_id = $OpportunityId
} | ConvertTo-Json -Compress

gcloud workflows run ingestion-pipeline `
    --location=us-central1 `
    --project=eighth-bivouac-490806-s2 `
    --data="$data"
