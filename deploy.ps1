# deploy.ps1 - Windows PowerShell script to deploy the serverless document processing pipeline.
# Run this script after executing 'gcloud auth login' and 'gcloud config set project [YOUR_PROJECT_ID]'.

# Exit immediately if any command fails
$ErrorActionPreference = "Stop"

# Write colored messages
function Write-Header($msg) {
    Write-Host "`n==== $msg ====" -ForegroundColor Cyan
}

function Write-Success($msg) {
    Write-Host "SUCCESS: $msg" -ForegroundColor Green
}

function Write-Info($msg) {
    Write-Host $msg -ForegroundColor Yellow
}

# --- 1. Detect GCP Configuration ---
Write-Header "Detecting GCP Project Configuration"
$ProjectId = (gcloud config get-value project)
if ([string]::IsNullOrEmpty($ProjectId)) {
    Write-Error "No active GCP project configuration found. Run 'gcloud config set project <PROJECT_ID>' first."
    exit 1
}
Write-Info "Active GCP Project: $ProjectId"

# Define deployment parameters
$Region = "us-central1"
$BucketName = "${ProjectId}-document-ingest"
$TopicName = "gcs-document-uploads"
$DatasetName = "document_pipeline"
$TableName = "processed_metadata"
$ServiceAccountName = "doc-pipeline-processor"
$ServiceAccountEmail = "${ServiceAccountName}@${ProjectId}.iam.gserviceaccount.com"
$ServiceName = "document-processor"
$TriggerSaName = "pubsub-trigger-sa"
$TriggerSaEmail = "${TriggerSaName}@${ProjectId}.iam.gserviceaccount.com"

# --- 2. Enable Google Cloud Services ---
Write-Header "Enabling Google Cloud Services"
Write-Info "Enabling Storage, Pub/Sub, Cloud Run, BigQuery, Cloud Build, and IAM APIs..."
gcloud services enable `
    storage.googleapis.com `
    pubsub.googleapis.com `
    run.googleapis.com `
    bigquery.googleapis.com `
    cloudbuild.googleapis.com `
    iam.googleapis.com

# --- 3. Create Cloud Storage Bucket ---
Write-Header "Provisioning Cloud Storage Bucket"
# Check if bucket already exists
$bucketExists = $false
try {
    gcloud storage buckets describe "gs://$BucketName" > $null 2>&1
    $bucketExists = $true
} catch {
    # Bucket doesn't exist
}

if ($bucketExists) {
    Write-Info "Cloud Storage bucket gs://$BucketName already exists."
} else {
    Write-Info "Creating Cloud Storage bucket gs://$BucketName in $Region..."
    gcloud storage buckets create "gs://$BucketName" --location=$Region
    Write-Success "Bucket created."
}

# --- 4. Create BigQuery Dataset and Table ---
Write-Header "Provisioning BigQuery Dataset and Table"
# Create Dataset
$datasetExists = $false
try {
    bq show "$ProjectId`:$DatasetName" > $null 2>&1
    $datasetExists = $true
} catch {}

if ($datasetExists) {
    Write-Info "BigQuery dataset $DatasetName already exists."
} else {
    Write-Info "Creating BigQuery dataset $DatasetName..."
    bq mk --location=$Region --dataset "$ProjectId`:$DatasetName"
    Write-Success "Dataset created."
}

# Create Table
$tableExists = $false
try {
    bq show "$ProjectId`:$DatasetName`.$TableName" > $null 2>&1
    $tableExists = $true
} catch {}

if ($tableExists) {
    Write-Info "BigQuery table $TableName already exists."
} else {
    Write-Info "Creating BigQuery table $TableName with schema..."
    bq mk --table "$ProjectId`:$DatasetName`.$TableName" `
        "filename:STRING,gcs_uri:STRING,processed_at:TIMESTAMP,word_count:INTEGER,tags:STRING,file_size:INTEGER,content_type:STRING"
    Write-Success "Table created."
}

# --- 5. Create Service Accounts and Assign Roles ---
Write-Header "Creating and Configuring Service Accounts"

# Create processor Service Account if it doesn't exist
$saExists = $false
try {
    gcloud iam service-accounts describe $ServiceAccountEmail > $null 2>&1
    $saExists = $true
} catch {}

if ($saExists) {
    Write-Info "Service account $ServiceAccountEmail already exists."
} else {
    Write-Info "Creating service account for Cloud Run processor..."
    gcloud iam service-accounts create $ServiceAccountName --display-name="Service Account for Document Processor Cloud Run"
    Write-Success "Service account created."
}

# Assign roles to Cloud Run Service Account
Write-Info "Granting Storage Object Viewer role on gs://$BucketName..."
gcloud storage buckets add-iam-policy-binding "gs://$BucketName" `
    --member="serviceAccount:$ServiceAccountEmail" `
    --role="roles/storage.objectViewer" > $null

Write-Info "Granting BigQuery Data Editor and User roles to $ServiceAccountEmail..."
gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$ServiceAccountEmail" `
    --role="roles/bigquery.dataEditor" > $null

gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$ServiceAccountEmail" `
    --role="roles/bigquery.user" > $null

# Create Pub/Sub trigger Service Account
$triggerSaExists = $false
try {
    gcloud iam service-accounts describe $TriggerSaEmail > $null 2>&1
    $triggerSaExists = $true
} catch {}

if ($triggerSaExists) {
    Write-Info "Service account $TriggerSaEmail already exists."
} else {
    Write-Info "Creating service account for Pub/Sub triggers..."
    gcloud iam service-accounts create $TriggerSaName --display-name="Service Account for Pub/Sub Triggering Cloud Run"
    Write-Success "Service account created."
}

# Allow Pub/Sub to create tokens (required for OIDC push subscriptions)
$ProjectNumber = (gcloud projects describe $ProjectId --format="value(projectNumber)").Trim()
Write-Info "Granting token creator role to Google Pub/Sub service account..."
gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:service-$ProjectNumber@gcp-sa-pubsub.iam.gserviceaccount.com" `
    --role="roles/iam.serviceAccountTokenCreator" > $null

# --- 6. Build and Deploy Cloud Run Service ---
Write-Header "Deploying Cloud Run Service"
Write-Info "Building container via Cloud Build and deploying service '$ServiceName'..."
gcloud run deploy $ServiceName `
    --source=./processor `
    --region=$Region `
    --service-account=$ServiceAccountEmail `
    --set-env-vars="BQ_DATASET=$DatasetName,BQ_TABLE=$TableName" `
    --no-allow-unauthenticated

Write-Success "Cloud Run service deployed."

# --- 7. Configure Pub/Sub Topic and Notifications ---
Write-Header "Setting up Pub/Sub Topic and GCS Notification"

# Create Pub/Sub Topic if it doesn't exist
$topicExists = $false
try {
    gcloud pubsub topics describe $TopicName > $null 2>&1
    $topicExists = $true
} catch {}

if ($topicExists) {
    Write-Info "Pub/Sub topic $TopicName already exists."
} else {
    Write-Info "Creating Pub/Sub topic $TopicName..."
    gcloud pubsub topics create $TopicName
    Write-Success "Pub/Sub topic created."
}

# Attach Pub/Sub notification to storage bucket
Write-Info "Attaching notification trigger to bucket gs://$BucketName..."
# We try to create it. If it already exists, this command might return an error, so we catch it gracefully.
try {
    gcloud storage buckets notifications create "gs://$BucketName" --topic=$TopicName --event-types="OBJECT_FINALIZE"
    Write-Success "GCS bucket notifications created."
} catch {
    Write-Info "GCS notification trigger already configured or could not be verified."
}

# --- 8. Create Pub/Sub Subscription and Grant Invoker Role ---
Write-Header "Configuring Pub/Sub Push Subscription"

# Grant Invoker permission to Pub/Sub trigger SA
Write-Info "Granting Run Invoker permission to trigger service account $TriggerSaEmail..."
gcloud run services add-iam-policy-binding $ServiceName `
    --region=$Region `
    --member="serviceAccount:$TriggerSaEmail" `
    --role="roles/run.invoker" > $null

# Retrieve Cloud Run service URL
$CloudRunUrl = (gcloud run services describe $ServiceName --region=$Region --format="value(status.url)").Trim()
Write-Info "Cloud Run URL: $CloudRunUrl"

# Create Push Subscription
$subName = "${ServiceName}-sub"
$subExists = $false
try {
    gcloud pubsub subscriptions describe $subName > $null 2>&1
    $subExists = $true
} catch {}

if ($subExists) {
    Write-Info "Pub/Sub subscription $subName already exists."
} else {
    Write-Info "Creating Pub/Sub Push subscription '$subName' pointing to $CloudRunUrl..."
    gcloud pubsub subscriptions create $subName `
        --topic=$TopicName `
        --push-endpoint=$CloudRunUrl `
        --push-auth-service-account=$TriggerSaEmail
    Write-Success "Pub/Sub subscription created."
}

Write-Header "Pipeline Setup Complete!"
Write-Host "Deployment completed successfully! The serverless pipeline is live." -ForegroundColor Green
Write-Host "Upload file location: gs://$BucketName" -ForegroundColor Green
Write-Host "BigQuery table target: $ProjectId.$DatasetName.$TableName" -ForegroundColor Green
