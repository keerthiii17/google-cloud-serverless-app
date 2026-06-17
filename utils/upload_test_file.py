import sys
import os
import shutil

# Try to import storage library; do not fail if missing in local mode
try:
    from google.cloud import storage
    gcp_storage_available = True
except ImportError:
    gcp_storage_available = False

# Resolve absolute paths
UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(UTILS_DIR)
LOCAL_STORAGE_DIR = os.path.join(PROJECT_ROOT, "local_storage")

PIPELINE_MODE = os.getenv("PIPELINE_MODE", "local").lower()

def main():
    # Detect active GCP project if in GCP mode
    project_id = None
    if PIPELINE_MODE == "gcp":
        if not gcp_storage_available:
            print("Error: GCP Mode is active, but Google Cloud Storage library is not installed.")
            print("Run: pip install google-cloud-storage")
            sys.exit(1)
            
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
        if not project_id:
            import subprocess
            try:
                project_id = subprocess.check_output(
                    ["gcloud", "config", "get-value", "project"], 
                    text=True
                ).strip()
            except Exception:
                pass
                
        if not project_id:
            print("Error: Could not detect GCP project. Please set GOOGLE_CLOUD_PROJECT environment variable.")
            sys.exit(1)

    bucket_name = f"{project_id}-document-ingest" if project_id else "local-bucket"
    
    # Check if a custom file was provided
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        if not os.path.exists(file_path):
            print(f"Error: File '{file_path}' does not exist.")
            sys.exit(1)
        filename = os.path.basename(file_path)
        print(f"Using provided file: {file_path}")
        is_temp_file = False
    else:
        # Create a mock invoice text file
        filename = "invoice_9045_consulting.txt"
        file_path = filename
        sample_content = """INVOICE #9045
Date: 2026-06-17
Client: Globex Corporation
Service: Serverless Cloud Architecture Implementation and Deployment
Consultant: Lead DevOps Architect

Details:
- GCS Trigger configuration: $500
- Cloud Run service setup: $1200
- BigQuery streaming ingestion: $800

TOTAL AMOUNT DUE: $2500.00 USD
Payment Terms: Net 30

Thank you for your business!
"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(sample_content)
        print(f"Created temporary mock invoice file: {filename}")
        is_temp_file = True

    try:
        if PIPELINE_MODE == "local":
            print(f"Running in LOCAL mode. Output directory: {LOCAL_STORAGE_DIR}")
            if not os.path.exists(LOCAL_STORAGE_DIR):
                os.makedirs(LOCAL_STORAGE_DIR)
                
            dest_path = os.path.join(LOCAL_STORAGE_DIR, filename)
            print(f"Simulating upload. Saving '{filename}' to local folder...")
            
            if is_temp_file:
                # If we generated a temp file in the current dir, move it
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                shutil.move(file_path, dest_path)
            else:
                # Copy from user provided source path
                shutil.copy2(file_path, dest_path)
                
            print(f"Successfully uploaded locally! Path: {dest_path}")
        else:
            # GCP Mode
            print(f"Initializing Storage client for project: {project_id}...")
            storage_client = storage.Client(project=project_id)
            
            print(f"Retrieving bucket: gs://{bucket_name}...")
            bucket = storage_client.bucket(bucket_name)
            
            blob = bucket.blob(filename)
            print(f"Uploading '{filename}' to gs://{bucket_name}/{filename}...")
            
            content_type = "text/plain"
            if filename.endswith(".pdf"):
                content_type = "application/pdf"
            elif filename.endswith(".json"):
                content_type = "application/json"
                
            blob.upload_from_filename(file_path, content_type=content_type)
            print(f"Successfully uploaded! GCS URI: gs://{bucket_name}/{filename}")
            
    except Exception as e:
        print(f"Error during upload/copy: {e}")
        sys.exit(1)
    finally:
        # Clean up temporary file if it was created and not moved
        if is_temp_file and PIPELINE_MODE == "gcp" and os.path.exists(file_path):
            try:
                os.remove(file_path)
                print("Cleaned up temporary local mock file.")
            except Exception:
                pass

if __name__ == "__main__":
    main()
