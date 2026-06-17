# Serverless Event-Driven Document Processing Pipeline on Google Cloud

This repository contains an event-driven document processing pipeline built for Google Cloud Platform (GCP). The application features two execution modes: **Local Emulator Mode** (requires zero GCP credentials, billing, or cost) and **GCP Cloud Mode** (for deploying to real serverless GCP infrastructure).

---

## Architecture

```
[ User / Upload Script ]
           │
           ├──────────────────────────────┐ (GCP Mode)
           │ (Local Mode)                 │
           ▼                              ▼
   ┌───────────────┐              ┌───────────────┐
   │ local_storage │ (Folder)     │  GCS Bucket   │ (GCP Bucket)
   └───────┬───────┘              └───────┬───────┘
           │ (Watched by script)          │ (OBJECT_FINALIZE Trigger)
           ▼                              ▼
   ┌───────────────┐              ┌───────────────┐
   │ local_watcher │ (POSTs Event)│ Pub/Sub Topic │ (Push Subscription)
   └───────┬───────┘              └───────┬───────┘
           │                              │
           └──────────────┬───────────────┘
                          │ (Event JSON POST)
                          ▼
                  ┌───────────────┐
                  │  Cloud Run    │ (Flask Web Service)
                  │  (Processor)  │ ──> Simulates OCR, word counts & tags
                  └───────┬───────┘
                          │
         ┌────────────────┴────────────────┐
         │ (Local Mode)                    │ (GCP Mode)
         ▼                                 ▼
 ┌───────────────┐                 ┌───────────────┐
 │ SQLite DB     │ (local_metadata)│ BigQuery      │ (dataset.table)
 └───────────────┘                 └───────────────┘
```

---

## Option A: Quick Start (Local Emulator Mode - Recommended)

Run the entire pipeline locally on your machine. **No GCP setup, CLI authentication, or billing account is required.**

### Prerequisites
- Python 3.8+ installed.
- Install the required dependencies:
  ```bash
  pip install Flask streamlit pandas
  ```

### Step-by-Step Local Run

1. **Start the Processor Service**
   In your first terminal window, start the Flask app:
   ```bash
   python processor/app.py
   ```
   *This starts the processor webhook on `http://localhost:8080` and auto-creates the `local_storage/` folder and `local_metadata.db` SQLite database.*

2. **Start the Directory Watcher**
   In a second terminal window, start the watcher:
   ```bash
   python utils/local_watcher.py
   ```
   *This script monitors the `local_storage/` folder. When a file is copied there, it POSTs a base64-encoded mock Pub/Sub event to the Flask app.*

3. **Start the Streamlit Web Dashboard**
   In a third terminal window, run the frontend:
   ```bash
   streamlit run frontend/app.py
   ```
   *This will launch a premium web UI in your browser at `http://localhost:8501` where you can upload documents, search database records, and view real-time pipeline charts.*

4. **Optional: CLI Ingestion & Testing**
   If you want to test via the command-line alongside the web dashboard:
   - Upload file: `python utils/upload_test_file.py`
   - Query records: `python utils/query_metadata.py`

---

## Option B: GCP Cloud Mode (Requires Billing Enabled)

Deploy the service to real, production-ready serverless infrastructure on Google Cloud.

### Prerequisites
1. **Google Cloud Account** with an active billing account linked to the target project.
2. **Google Cloud SDK (gcloud CLI)** installed.
3. Authenticate with GCP and select your project:
   ```bash
   gcloud auth login
   gcloud config set project [YOUR_PROJECT_ID]
   ```
4. Install local dependencies to run the helper scripts:
   ```bash
   pip install google-cloud-storage google-cloud-bigquery Flask
   ```

### Step-by-Step GCP Deployment

1. **Set Mode to GCP**
   Set the `PIPELINE_MODE` environment variable to `gcp`:
   - **PowerShell (Windows)**:
     ```powershell
     $env:PIPELINE_MODE="gcp"
     ```
   - **Bash (macOS/Linux/Git Bash)**:
     ```bash
     export PIPELINE_MODE="gcp"
     ```

2. **Deploy the Infrastructure**
   Deploy using the provided provisioning scripts:
   - **Windows (PowerShell)**:
     ```powershell
     .\deploy.ps1
     ```
   - **macOS/Linux (Bash)**:
     ```bash
     chmod +x deploy.sh
     ./deploy.sh
     ```

3. **Trigger the Pipeline**
   Upload a file using the upload utility:
   ```bash
   python utils/upload_test_file.py
   ```

4. **Observe Cloud Run Logs**
   Check the live container logs:
   ```bash
   gcloud run services logs read document-processor --region=us-central1 --limit=20
   ```

5. **Query BigQuery Database**
   Query the metadata streamed into BigQuery:
   ```bash
   python utils/query_metadata.py
   ```

6. **Cleanup**
   Follow the teardown instructions in `deploy.sh` / `deploy.ps1` to delete all GCP resources and prevent ongoing billing charges.
