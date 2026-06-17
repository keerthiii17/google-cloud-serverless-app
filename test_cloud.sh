#!/bin/bash
# test_cloud.sh - Bash script to automate cloud pipeline testing.

# Set mode to GCP
export PIPELINE_MODE="gcp"
echo "Setting PIPELINE_MODE=gcp..."

# 1. Upload the test document
echo -e "\n=== 1. Uploading test file to Google Cloud Storage ==="
python utils/upload_test_file.py

# 2. Wait for Cloud Run processing
echo -e "\n=== 2. Waiting 5 seconds for Pub/Sub and Cloud Run processing ==="
sleep 5

# 3. Query BigQuery results
echo -e "\n=== 3. Querying BigQuery Metadata Table ==="
python utils/query_metadata.py

# 4. Read Cloud Run Service Logs
echo -e "\n=== 4. Fetching Cloud Run Logs ==="
gcloud run services logs read document-processor --region=us-central1 --limit=15
