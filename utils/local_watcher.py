import os
import time
import base64
import json
import sqlite3
import mimetypes
from datetime import datetime
import urllib.request
import urllib.error

# Resolve absolute paths relative to project structure
UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(UTILS_DIR)
LOCAL_STORAGE_DIR = os.path.join(PROJECT_ROOT, "local_storage")
LOCAL_DB_PATH = os.path.join(PROJECT_ROOT, "local_metadata.db")
RECEIVER_URL = "http://localhost:8080/"

def get_processed_files():
    """Queries the SQLite database to see what has already been processed."""
    processed = set()
    if os.path.exists(LOCAL_DB_PATH):
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH)
            cursor = conn.cursor()
            # If table doesn't exist yet, we just handle the exception
            cursor.execute("SELECT filename FROM processed_metadata")
            for row in cursor.fetchall():
                processed.add(row[0])
            conn.close()
        except sqlite3.OperationalError:
            # Table does not exist yet (normal on fresh startup)
            pass
        except Exception as e:
            print(f"Error reading processed database list: {e}")
    return processed

def trigger_mock_pubsub(filename, file_size, content_type):
    """
    Constructs a mock GCS and Pub/Sub event payload, base64 encodes it,
    and sends a POST request to the local Flask application using urllib.
    """
    gcs_object_metadata = {
        "bucket": "local-bucket-simulation",
        "name": filename,
        "contentType": content_type,
        "size": str(file_size),
        "timeCreated": datetime.utcnow().isoformat() + "Z",
        "updated": datetime.utcnow().isoformat() + "Z"
    }
    
    # Format and base64-encode the storage metadata payload
    metadata_json = json.dumps(gcs_object_metadata)
    base64_data = base64.b64encode(metadata_json.encode("utf-8")).decode("utf-8")
    
    # Wrap in Pub/Sub push notification envelope
    envelope = {
        "message": {
            "attributes": {
                "eventType": "OBJECT_FINALIZE"
            },
            "data": base64_data,
            "messageId": str(int(time.time() * 1000)),
            "publishTime": datetime.utcnow().isoformat() + "Z"
        },
        "subscription": "projects/local-project/subscriptions/local-watcher-sub"
    }
    
    req_data = json.dumps(envelope).encode("utf-8")
    req = urllib.request.Request(
        RECEIVER_URL, 
        data=req_data, 
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode("utf-8")
            print(f"Successfully triggered processor for '{filename}'. Response: {res_body}")
            return True
    except urllib.error.HTTPError as e:
        print(f"Processor returned HTTP error status {e.code}: {e.read().decode('utf-8')}")
        return False
    except urllib.error.URLError as e:
        print(f"Error connecting to processor at {RECEIVER_URL}: {e.reason}")
        print("Please ensure the Flask app is running (python processor/app.py).")
        return False
    except Exception as e:
        print(f"Unexpected error sending trigger: {e}")
        return False

def main():
    if not os.path.exists(LOCAL_STORAGE_DIR):
        os.makedirs(LOCAL_STORAGE_DIR)
        
    print("======================================================")
    print("       Local GCS -> Pub/Sub Trigger Emulator         ")
    print("======================================================")
    print(f"Watching directory : {LOCAL_STORAGE_DIR}")
    print(f"Posting events to  : {RECEIVER_URL}")
    print("Press Ctrl+C to stop.\n")
    
    # Load previously processed files from DB to prevent double-processing on start
    processed_files = get_processed_files()
    if processed_files:
        print(f"Found {len(processed_files)} files in database. Excluding from initial scan.")
        
    # Track filename -> mtime
    last_seen_files = {}
    
    # Populate seen cache with current files if they are already in the DB
    for entry in os.scandir(LOCAL_STORAGE_DIR):
        if entry.is_file():
            filename = entry.name
            mtime = entry.stat().st_mtime
            if filename in processed_files:
                last_seen_files[filename] = mtime

    # Primary polling loop
    while True:
        try:
            current_files = {}
            for entry in os.scandir(LOCAL_STORAGE_DIR):
                if entry.is_file():
                    current_files[entry.name] = entry.stat().st_mtime
            
            # Identify new or modified files
            for filename, mtime in current_files.items():
                is_new = filename not in last_seen_files
                is_modified = not is_new and mtime > last_seen_files[filename]
                
                if is_new or is_modified:
                    action = "New file" if is_new else "Modified file"
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {action} detected: {filename}")
                    
                    file_path = os.path.join(LOCAL_STORAGE_DIR, filename)
                    file_size = os.path.getsize(file_path)
                    
                    # Guess file mime type
                    content_type, _ = mimetypes.guess_type(file_path)
                    if not content_type:
                        content_type = "application/octet-stream"
                        
                    # Fire mock event
                    success = trigger_mock_pubsub(filename, file_size, content_type)
                    if success:
                        last_seen_files[filename] = mtime
                    else:
                        print("Trigger failed. Will retry on next scan.")
            
            # Clean up tracking for files that were deleted from the folder
            for filename in list(last_seen_files.keys()):
                if filename not in current_files:
                    del last_seen_files[filename]
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Removed tracking for deleted file: {filename}")
                    
        except KeyboardInterrupt:
            print("\nStopping watcher...")
            break
        except Exception as e:
            print(f"Error in scan loop: {e}")
            
        time.sleep(1.0)

if __name__ == "__main__":
    main()
