import os
import sys
import sqlite3

# Try to import BigQuery client; do not fail if missing in local mode
try:
    from google.cloud import bigquery
    gcp_bq_available = True
except ImportError:
    gcp_bq_available = False

# Resolve absolute paths
UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(UTILS_DIR)
LOCAL_DB_PATH = os.path.join(PROJECT_ROOT, "local_metadata.db")

PIPELINE_MODE = os.getenv("PIPELINE_MODE", "local").lower()

def main():
    # Detect active GCP project if in GCP mode
    project_id = None
    if PIPELINE_MODE == "gcp":
        if not gcp_bq_available:
            print("Error: GCP Mode is active, but Google Cloud BigQuery library is not installed.")
            print("Run: pip install google-cloud-bigquery")
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

    dataset_name = "document_pipeline"
    table_name = "processed_metadata"
    
    rows = []
    
    if PIPELINE_MODE == "local":
        print(f"Connecting to local SQLite database: {LOCAL_DB_PATH}...")
        if not os.path.exists(LOCAL_DB_PATH):
            print("\nLocal SQLite database file not found.")
            print("Please start the processor and upload a file first.")
            return
            
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH)
            # Use Row factory to access columns by name
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute(f"""
                SELECT 
                    filename, 
                    processed_at as processed_time,
                    word_count, 
                    tags, 
                    file_size, 
                    content_type 
                FROM {table_name}
                ORDER BY processed_at DESC
                LIMIT 10
            """)
            rows = cursor.fetchall()
            conn.close()
            
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                print("\nMetadata table does not exist in SQLite database yet.")
                print("Make sure the processor is running (python processor/app.py) and a file has been uploaded.")
            else:
                print(f"SQLite operational error: {e}")
            return
        except Exception as e:
            print(f"Error querying SQLite database: {e}")
            return
            
    else:
        # GCP Mode
        print(f"Connecting to BigQuery project: {project_id}...")
        bq_client = bigquery.Client(project=project_id)
        
        query = f"""
            SELECT 
                filename, 
                FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', processed_at) as processed_time,
                word_count, 
                tags, 
                file_size, 
                content_type 
            FROM `{project_id}.{dataset_name}.{table_name}`
            ORDER BY processed_at DESC
            LIMIT 10
        """
        
        try:
            print("Executing BigQuery query...")
            query_job = bq_client.query(query)
            results = query_job.result()
            rows = list(results)
        except Exception as e:
            print(f"Error querying BigQuery: {e}")
            sys.exit(1)
            
    # Print results in a formatted table
    if not rows:
        print("\nNo processed documents found in the database yet.")
        print("Upload a file using the upload script to trigger processing.")
        return

    print("\n" + "="*95)
    print(f"| {'Filename':<30} | {'Processed At (UTC)':<19} | {'Words':<5} | {'Size':<6} | {'Tags':<22} |")
    print("="*95)
    for row in rows:
        filename = row["filename"]
        if len(filename) > 30:
            filename = filename[:27] + "..."
            
        # Format date for sqlite strings (often has full ISO timestamp with Z)
        processed_time = row["processed_time"]
        if "T" in processed_time:
            # Simple clean up: '2026-06-17T07:13:28.123456Z' -> '2026-06-17 07:13:28'
            processed_time = processed_time.replace("T", " ").split(".")[0]
            
        tags = row["tags"] or ""
        if len(tags) > 22:
            tags = tags[:19] + "..."
            
        print(f"| {filename:<30} | {processed_time:<19} | {row['word_count']:<5} | {row['file_size']:<6} | {tags:<22} |")
    print("="*95)
    print(f"Total entries listed: {len(rows)}\n")

if __name__ == "__main__":
    main()
