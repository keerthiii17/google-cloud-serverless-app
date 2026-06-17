#!/bin/bash
# deploy.sh - Bash script to deploy the serverless document processing pipeline.
# Run this script after executing 'gcloud auth login' and 'gcloud config set project [YOUR_PROJECT_ID]'.

# Exit immediately if any command fails
set -e

# Colored output helpers
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

write_header() {
    echo -e "\n${CYAN}==== $1 ====${NC}"
}

write_success() {
    echo -e "${GREEN}SUCCESS: $1${NC}"
}

write_info() {
    echo -e "${YELLOW}$1${NC}"
}

write_error() {
    echo -e "${RED}ERROR: $1${NC}"
}

# --- 1. Detect GCP Configuration ---
write_header "Detecting GCP Project Configuration"
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
    write_error "No active GCP project configuration found. Run 'gcloud config set project <PROJECT_ID>' first."
    exit 1
fi
write_info "Active GCP Project: $PROJECT_ID"

# Define deployment parameters
REGION="us-central1"
BUCKET_NAME="${PROJECT_ID}-document-ingest"
TOPIC_NAME="gcs-document-uploads"
DATASET_NAME="document_pipeline"
TABLE_NAME="processed_metadata"
SERVICE_ACCOUNT_NAME="doc-pipeline-processor"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
SERVICE_NAME="document-processor"
TRIGGER_SA_NAME="pubsub-trigger-sa"
TRIGGER_SA_EMAIL="${TRIGGER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# --- 2. Enable Google Cloud Services ---
write_header "Enabling Google Cloud Services"
write_info "Enabling Storage, Pub/Sub, Cloud Run, BigQuery, Cloud Build, and IAM APIs..."
gcloud services enable \
    storage.googleapis.com \
    pubsub.googleapis.com \
    run.googleapis.com \
    bigquery.googleapis.com \
    cloudbuild.googleapis.com \
    iam.googleapis.com

# --- 3. Create Cloud Storage Bucket ---
write_header "Provisioning Cloud Storage Bucket"
if gcloud storage buckets describe "gs://$BUCKET_NAME" >/dev/null 2>&1; then
    write_info "Cloud Storage bucket gs://$BUCKET_NAME already exists."
else
    write_info "Creating Cloud Storage bucket gs://$BUCKET_NAME in $REGION..."
    gcloud storage buckets create "gs://$BUCKET_NAME" --location=$REGION
    write_success "Bucket created."
fi

# --- 4. Create BigQuery Dataset and Table ---
write_header "Provisioning BigQuery Dataset and Table"
# Create Dataset
if bq show "$PROJECT_ID:$DATASET_NAME" >/dev/null 2>&1; then
    write_info "BigQuery dataset $DATASET_NAME already exists."
else
    write_info "Creating BigQuery dataset $DATASET_NAME..."
    bq mk --location=$REGION --dataset "$PROJECT_ID:$DATASET_NAME"
    write_success "Dataset created."
fi

# Create Table
if bq show "$PROJECT_ID:$DATASET_NAME.$TABLE_NAME" >/dev/null 2>&1; then
    write_info "BigQuery table $TABLE_NAME already exists."
else
    write_info "Creating BigQuery table $TABLE_NAME with schema..."
    bq mk --table "$PROJECT_ID:$DATASET_NAME.$TABLE_NAME" \
        "filename:STRING,gcs_uri:STRING,processed_at:TIMESTAMP,word_count:INTEGER,tags:STRING,file_size:INTEGER,content_type:STRING"
    write_success "Table created."
fi

# --- 5. Create Service Accounts and Assign Roles ---
write_header "Creating and Configuring Service Accounts"

# Create processor Service Account if it doesn't exist
if gcloud iam service-accounts describe "$SERVICE_ACCOUNT_EMAIL" >/dev/null 2>&1; then
    write_info "Service account $SERVICE_ACCOUNT_EMAIL already exists."
else
    write_info "Creating service account for Cloud Run processor..."
    gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" --display-name="Service Account for Document Processor Cloud Run"
    write_success "Service account created."
fi

# Assign roles to Cloud Run Service Account
write_info "Granting Storage Object Viewer role on gs://$BUCKET_NAME..."
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="roles/storage.objectViewer" >/dev/null

write_info "Granting BigQuery Data Editor and User roles to $SERVICE_ACCOUNT_EMAIL..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="roles/bigquery.dataEditor" >/dev/null

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="roles/bigquery.user" >/dev/null

# Create Pub/Sub trigger Service Account
if gcloud iam service-accounts describe "$TRIGGER_SA_EMAIL" >/dev/null 2>&1; then
    write_info "Service account $TRIGGER_SA_EMAIL already exists."
else
    write_info "Creating service account for Pub/Sub triggers..."
    gcloud iam service-accounts create "$TRIGGER_SA_NAME" --display-name="Service Account for Pub/Sub Triggering Cloud Run"
    write_success "Service account created."
fi

# Allow Pub/Sub to create tokens (required for OIDC push subscriptions)
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
write_info "Granting token creator role to Google Pub/Sub service account..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
    --role="roles/iam.serviceAccountTokenCreator" >/dev/null

# --- 6. Build and Deploy Cloud Run Service ---
write_header "Deploying Cloud Run Service"
write_info "Building container via Cloud Build and deploying service '$SERVICE_NAME'..."
gcloud run deploy "$SERVICE_NAME" \
    --source=./processor \
    --region=$REGION \
    --service-account="$SERVICE_ACCOUNT_EMAIL" \
    --set-env-vars="BQ_DATASET=$DATASET_NAME,BQ_TABLE=$TABLE_NAME" \
    --no-allow-unauthenticated

write_success "Cloud Run service deployed."

# --- 7. Configure Pub/Sub Topic and Notifications ---
write_header "Setting up Pub/Sub Topic and GCS Notification"

# Create Pub/Sub Topic if it doesn't exist
if gcloud pubsub topics describe "$TOPIC_NAME" >/dev/null 2>&1; then
    write_info "Pub/Sub topic $TOPIC_NAME already exists."
else
    write_info "Creating Pub/Sub topic $TOPIC_NAME..."
    gcloud pubsub topics create "$TOPIC_NAME"
    write_success "Pub/Sub topic created."
fi

# Attach Pub/Sub notification to storage bucket
write_info "Attaching notification trigger to bucket gs://$BUCKET_NAME..."
if gcloud storage buckets notifications list "gs://$BUCKET_NAME" 2>/dev/null | grep -q "$TOPIC_NAME"; then
    write_info "GCS bucket notification for $TOPIC_NAME already configured."
else
    gcloud storage buckets notifications create "gs://$BUCKET_NAME" --topic="$TOPIC_NAME" --event-types="OBJECT_FINALIZE"
    write_success "GCS bucket notifications created."
fi

# --- 8. Create Pub/Sub Subscription and Grant Invoker Role ---
write_header "Configuring Pub/Sub Push Subscription"

# Grant Invoker permission to Pub/Sub trigger SA
write_info "Granting Run Invoker permission to trigger service account $TRIGGER_SA_EMAIL..."
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
    --region=$REGION \
    --member="serviceAccount:$TRIGGER_SA_EMAIL" \
    --role="roles/run.invoker" >/dev/null

# Retrieve Cloud Run service URL
CLOUD_RUN_URL=$(gcloud run services describe "$SERVICE_NAME" --region=$REGION --format="value(status.url)")
write_info "Cloud Run URL: $CLOUD_RUN_URL"

# Create Push Subscription
SUB_NAME="${SERVICE_NAME}-sub"
if gcloud pubsub subscriptions describe "$SUB_NAME" >/dev/null 2>&1; then
    write_info "Pub/Sub subscription $SUB_NAME already exists."
else
    write_info "Creating Pub/Sub Push subscription '$SUB_NAME' pointing to $CLOUD_RUN_URL..."
    gcloud pubsub subscriptions create "$SUB_NAME" \
        --topic="$TOPIC_NAME" \
        --push-endpoint="$CLOUD_RUN_URL" \
        --push-auth-service-account="$TRIGGER_SA_EMAIL"
    write_success "Pub/Sub subscription created."
fi

write_header "Pipeline Setup Complete!"
echo -e "${GREEN}Deployment completed successfully! The serverless pipeline is live.${NC}"
echo -e "${GREEN}Upload file location: gs://$BUCKET_NAME${NC}"
echo -e "${GREEN}BigQuery table target: $PROJECT_ID.$DATASET_NAME.$TABLE_NAME${NC}"
