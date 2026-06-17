# test_cloud.ps1 - PowerShell script to automate cloud pipeline testing.

# Set mode to GCP
$env:PIPELINE_MODE = "gcp"
Write-Host "Setting PIPELINE_MODE=gcp..." -ForegroundColor Cyan

# 1. Upload the test document
Write-Host "`n=== 1. Uploading test file to Google Cloud Storage ===" -ForegroundColor Cyan
python utils/upload_test_file.py

# 2. Wait for Cloud Run processing
Write-Host "`n=== 2. Waiting 5 seconds for Pub/Sub and Cloud Run processing ===" -ForegroundColor Cyan
Start-Sleep -Seconds 5

# 3. Query BigQuery results
Write-Host "`n=== 3. Querying BigQuery Metadata Table ===" -ForegroundColor Cyan
python utils/query_metadata.py

# 4. Read Cloud Run Service Logs
Write-Host "`n=== 4. Fetching Cloud Run Logs ===" -ForegroundColor Cyan
gcloud run services logs read document-processor --region="us-central1" --limit=15
