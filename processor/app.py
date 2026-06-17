import base64
import json
import os
import time
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify

# Try to import GCP libraries; do not fail if they are missing in local mode
try:
    from google.cloud import storage
    from google.cloud import bigquery
    gcp_libs_available = True
except ImportError:
    gcp_libs_available = False

app = Flask(__name__)

# Fetch configurations from environment variables
PIPELINE_MODE = os.getenv("PIPELINE_MODE", "local").lower()
BQ_DATASET = os.getenv("BQ_DATASET", "document_pipeline")
BQ_TABLE = os.getenv("BQ_TABLE", "processed_metadata")

# Resolve absolute paths relative to project root
APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
LOCAL_DB_PATH = os.path.join(PROJECT_ROOT, "local_metadata.db")
LOCAL_STORAGE_DIR = os.path.join(PROJECT_ROOT, "local_storage")

if PIPELINE_MODE == "gcp" and not gcp_libs_available:
    raise ImportError(
        "GCP Mode is active, but Google Cloud client libraries are not installed. "
        "Run: pip install google-cloud-storage google-cloud-bigquery"
    )

def init_sqlite_db():
    """Initializes the local SQLite database schema for local mode."""
    print(f"Initializing local SQLite database: {LOCAL_DB_PATH}")
    conn = sqlite3.connect(LOCAL_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_metadata (
            filename TEXT,
            gcs_uri TEXT,
            processed_at TEXT,
            word_count INTEGER,
            tags TEXT,
            file_size INTEGER,
            content_type TEXT
        )
    """)
    conn.commit()
    conn.close()

# Auto-initialize local environment if in local mode
if PIPELINE_MODE == "local":
    if not os.path.exists(LOCAL_STORAGE_DIR):
        os.makedirs(LOCAL_STORAGE_DIR)
    init_sqlite_db()


def process_document(bucket_name, object_name, content_type, file_size):
    """
    Simulates OCR processing. Reads file if it's text, otherwise uses file metrics
    to construct simulated metadata. Works in both Local and GCP modes.
    """
    print(f"Retrieving document for simulated OCR (Mode: {PIPELINE_MODE})...")
    word_count = 0
    file_content_snippet = ""
    
    if PIPELINE_MODE == "local":
        file_path = os.path.join(LOCAL_STORAGE_DIR, object_name)
        print(f"Reading local file: {file_path}")
        try:
            # If it's a text file and exists, read it to perform a real word count
            if "text/" in content_type and os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    text_content = f.read()
                word_count = len(text_content.split())
                file_content_snippet = text_content[:500]
            else:
                # For non-text/larger files, simulate a realistic word count (approx 1 word per 8 bytes)
                word_count = max(10, int(file_size / 8))
        except Exception as e:
            print(f"Warning: Could not read local file content: {e}. Using simulated value.")
            word_count = max(10, int(file_size / 8))
    else:
        # GCP Mode
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        try:
            if "text/" in content_type and file_size < 1024 * 1024:
                text_content = blob.download_as_text(encoding="utf-8")
                word_count = len(text_content.split())
                file_content_snippet = text_content[:500]
            else:
                word_count = max(10, int(file_size / 8))
        except Exception as e:
            print(f"Warning: Could not read GCS file content: {e}. Using simulated value.")
            word_count = max(10, int(file_size / 8))
            
    # Simulate OCR time delay (mimics compute intensive vision/OCR tasks)
    print("Simulating OCR text extraction (1s delay)...")
    time.sleep(1.0)
    
    # Generate tags based on name and content snippet
    tags = []
    lower_name = object_name.lower()
    
    # Tagging by file metadata hints
    if "invoice" in lower_name:
        tags.append("invoice")
    if "receipt" in lower_name:
        tags.append("receipt")
    if "resume" in lower_name or "cv" in lower_name:
        tags.append("resume")
    if "report" in lower_name:
        tags.append("report")
    if "contract" in lower_name or "agreement" in lower_name:
        tags.append("contract")
        
    # Tagging by snippet content analysis
    if file_content_snippet:
        lower_snippet = file_content_snippet.lower()
        if any(term in lower_snippet for term in ["total", "amount", "usd", "tax", "billing"]):
            tags.append("financial")
        if any(term in lower_snippet for term in ["experience", "education", "skills", "employment"]):
            tags.append("hr")
        if any(term in lower_snippet for term in ["hereby", "parties", "agreement", "section"]):
            tags.append("legal")
            
    # Tagging by file extension
    ext = os.path.splitext(lower_name)[1].replace(".", "")
    if ext:
        tags.append(ext)
        
    # Deduplicate tags
    tags = list(set(tags))
    if not tags:
        tags.append("document")
        
    tags_str = ", ".join(tags)
    
    processed_metadata = {
        "filename": os.path.basename(object_name),
        "gcs_uri": f"gs://{bucket_name}/{object_name}" if PIPELINE_MODE == "gcp" else f"local://local_storage/{object_name}",
        "processed_at": datetime.utcnow().isoformat() + "Z",
        "word_count": word_count,
        "tags": tags_str,
        "file_size": file_size,
        "content_type": content_type
    }
    
    print(f"Simulated OCR complete. Metadata generated: {processed_metadata}")
    return processed_metadata


def save_to_bigquery(metadata):
    """
    Saves the processed metadata. In GCP mode, streams to BigQuery.
    In Local mode, writes to SQLite.
    """
    if PIPELINE_MODE == "local":
        print(f"Saving metadata to local SQLite database: {LOCAL_DB_PATH}...")
        conn = sqlite3.connect(LOCAL_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO processed_metadata 
            (filename, gcs_uri, processed_at, word_count, tags, file_size, content_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            metadata["filename"],
            metadata["gcs_uri"],
            metadata["processed_at"],
            metadata["word_count"],
            metadata["tags"],
            metadata["file_size"],
            metadata["content_type"]
        ))
        conn.commit()
        conn.close()
        print("Successfully written to SQLite.")
    else:
        # GCP Mode
        print(f"Streaming metadata to BigQuery table {BQ_DATASET}.{BQ_TABLE}...")
        bq_client = bigquery.Client()
        dataset_ref = bq_client.dataset(BQ_DATASET)
        table_ref = dataset_ref.table(BQ_TABLE)
        
        row_to_insert = {
            "filename": metadata["filename"],
            "gcs_uri": metadata["gcs_uri"],
            "processed_at": metadata["processed_at"],
            "word_count": metadata["word_count"],
            "tags": metadata["tags"],
            "file_size": metadata["file_size"],
            "content_type": metadata["content_type"]
        }
        
        errors = bq_client.insert_rows_json(table_ref, [row_to_insert])
        if errors:
            raise RuntimeError(f"BigQuery insert failed: {errors}")
        print("Successfully written to BigQuery.")


@app.route("/", methods=["POST"])
def handle_pubsub_message():
    """
    Webhook handler for Pub/Sub push messages (or mock Pub/Sub messages locally).
    """
    envelope = request.get_json()
    if not envelope:
        msg = "No Pub/Sub message received"
        print(f"Error: {msg}")
        return f"Bad Request: {msg}", 400

    if not isinstance(envelope, dict) or "message" not in envelope:
        msg = "Invalid Pub/Sub message format"
        print(f"Error: {msg}")
        return f"Bad Request: {msg}", 400

    pubsub_message = envelope["message"]
    
    # Extract event details from message attributes
    attributes = pubsub_message.get("attributes", {})
    event_type = attributes.get("eventType")
    
    # Filter for upload event (OBJECT_FINALIZE)
    if event_type and event_type != "OBJECT_FINALIZE":
        print(f"Skipping event type: {event_type}")
        return f"Skipped: eventType is {event_type}", 200

    # Retrieve and base64 decode message data
    data_str = ""
    if "data" in pubsub_message:
        try:
            data_str = base64.b64decode(pubsub_message["data"]).decode("utf-8")
        except Exception as e:
            print(f"Error base64 decoding data: {e}")
            return "Bad Request: Base64 decode failed", 400

    if not data_str:
        print("Empty data payload in Pub/Sub message.")
        return "Bad Request: empty data", 400

    try:
        gcs_event = json.loads(data_str)
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        return "Bad Request: invalid JSON data payload", 400

    bucket_name = gcs_event.get("bucket")
    object_name = gcs_event.get("name")
    content_type = gcs_event.get("contentType", "application/octet-stream")
    size_str = gcs_event.get("size", "0")
    
    if not bucket_name or not object_name:
        print(f"Missing bucket or object name in GCS event. Bucket: {bucket_name}, Object: {object_name}")
        return "Bad Request: missing bucket or object name", 400

    print(f"Received GCS event for file: gs://{bucket_name}/{object_name} (Type: {content_type}, Size: {size_str} bytes)")
    
    try:
        # Run simulated OCR and construct metadata
        metadata = process_document(bucket_name, object_name, content_type, int(size_str))
        
        # Save results (SQLite or BigQuery)
        save_to_bigquery(metadata)
        
        return "Success: Document processed and metadata stored.", 200
    except Exception as e:
        print(f"Error processing document: {e}")
        return f"Internal Server Error: {str(e)}", 500


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting pipeline processor in mode: {PIPELINE_MODE.upper()}")
    app.run(host="0.0.0.0", port=port, debug=True)
