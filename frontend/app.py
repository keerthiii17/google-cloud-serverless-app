import os
import time
import sqlite3
import urllib.request
import json
import pandas as pd
import streamlit as st

# Resolve absolute paths relative to project root
FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(FRONTEND_DIR)
LOCAL_STORAGE_DIR = os.path.join(PROJECT_ROOT, "local_storage")
LOCAL_DB_PATH = os.path.join(PROJECT_ROOT, "local_metadata.db")
FLASK_HEALTH_URL = "http://localhost:8080/health"

# Page Configuration
st.set_page_config(
    page_title="Document Pipeline Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Premium Font and Custom Aesthetics Injector
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Outfit', sans-serif;
    }
    
    .main-title {
        font-size: 2.8rem;
        font-weight: 700;
        background: linear-gradient(90deg, #4F46E5, #3B82F6, #10B981);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    
    .subtitle {
        font-size: 1.1rem;
        color: #6B7280;
        margin-bottom: 2rem;
    }
    
    .status-badge {
        padding: 5px 12px;
        border-radius: 16px;
        font-weight: 600;
        font-size: 0.85rem;
        display: inline-block;
        margin-top: 5px;
    }
    
    .status-online {
        background-color: #D1FAE5;
        color: #065F46;
        border: 1px solid #A7F3D0;
    }
    
    .status-offline {
        background-color: #FEE2E2;
        color: #991B1B;
        border: 1px solid #FCA5A5;
    }
    
    .metric-card {
        background: rgba(255, 255, 255, 0.6);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(229, 231, 235, 0.5);
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    </style>
""", unsafe_allow_html=True)

# Helper Functions
def check_flask_health():
    """Checks if the local Flask service is online."""
    try:
        req = urllib.request.Request(FLASK_HEALTH_URL)
        with urllib.request.urlopen(req, timeout=1.0) as response:
            if response.getcode() == 200:
                data = json.loads(response.read().decode("utf-8"))
                return data.get("status") == "healthy"
    except Exception:
        pass
    return False

def load_metadata():
    """Queries local SQLite DB and loads metadata records as a DataFrame."""
    if not os.path.exists(LOCAL_DB_PATH):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        df = pd.read_sql_query("SELECT * FROM processed_metadata ORDER BY processed_at DESC", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

def clear_data():
    """Deletes all records from SQLite and clears the local storage directory."""
    if os.path.exists(LOCAL_DB_PATH):
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM processed_metadata")
            conn.commit()
            conn.close()
        except Exception as e:
            st.error(f"Error clearing database: {e}")
            
    if os.path.exists(LOCAL_STORAGE_DIR):
        for f in os.listdir(LOCAL_STORAGE_DIR):
            file_path = os.path.join(LOCAL_STORAGE_DIR, f)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                st.error(f"Error deleting local file '{f}': {e}")
    st.success("Database and local storage cleared!")
    time.sleep(1.0)
    st.rerun()

# --- SIDEBAR CONFIGURATION ---
with st.sidebar:
    st.image("https://img.icons8.com/clouds/150/000000/serverless.png", width=100)
    st.markdown("### Pipeline Config")
    
    # Mode Indicator
    st.info("Environment: **LOCAL EMULATOR**")
    
    # Live Health Check
    st.markdown("#### Service Status")
    is_online = check_flask_health()
    if is_online:
        st.markdown('<div class="status-badge status-online">● Flask API: Online</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="status-badge status-offline">● Flask API: Offline</div>', unsafe_allow_html=True)
        st.warning("Run 'python processor/app.py' to start the receiver.")
        
    st.markdown("---")
    
    # Watcher Status Reminder
    st.markdown("💡 **Reminder:** Make sure your folder watcher is running (`python utils/local_watcher.py`) to process file uploads automatically.")
    
    st.markdown("---")
    
    # System Controls
    st.markdown("#### Operations")
    if st.button("🔄 Refresh Dashboard", use_container_width=True):
        st.rerun()
        
    if st.button("🗑️ Clear Database & Storage", type="primary", use_container_width=True):
        clear_data()

# --- MAIN PAGE BODY ---
st.markdown('<div class="main-title">Serverless Document Processing Pipeline</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Local GCS, Pub/Sub, Cloud Run & BigQuery Emulator</div>', unsafe_allow_html=True)

# Load database records
df = load_metadata()

# Define navigation tabs
tab_upload, tab_registry, tab_analytics = st.tabs([
    "📥 Ingestion Hub", 
    "🗂️ Document Registry", 
    "📈 Performance Analytics"
])

# ==================== TAB 1: UPLOAD CENTER ====================
with tab_upload:
    st.markdown("### Upload Documents to Pipeline")
    st.write("Drag and drop documents here. They will be uploaded to the local GCS bucket directory, triggering the simulated OCR parsing pipeline.")
    
    if not is_online:
        st.error("⚠️ Local Flask service is offline. Start the service (python processor/app.py) before uploading files.")
    else:
        uploaded_file = st.file_uploader(
            "Select a document file...", 
            type=["txt", "pdf", "json", "csv", "docx", "md"],
            help="Supported types: Text, PDF, JSON, CSV, Markdown, Word"
        )
        
        if uploaded_file is not None:
            filename = uploaded_file.name
            dest_path = os.path.join(LOCAL_STORAGE_DIR, filename)
            
            # Prevent re-saving if it already exists to avoid instant loops in dashboard render
            file_exists_in_db = not df.empty and filename in df["filename"].values
            
            if st.button("🚀 Push to Pipeline", use_container_width=True):
                # Ensure storage directory exists
                if not os.path.exists(LOCAL_STORAGE_DIR):
                    os.makedirs(LOCAL_STORAGE_DIR)
                    
                # Write file to local storage directory
                with open(dest_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                    
                st.info(f"💾 File written to local storage bucket directory: `local_storage/{filename}`")
                
                # Dynamic Spinner - Polls database to verify watcher + processor completed the trigger
                with st.spinner("Processing: Waiting for local watcher trigger & simulated OCR parser..."):
                    processed_successfully = False
                    # Poll for up to 8 seconds
                    for i in range(8):
                        time.sleep(1.0)
                        df_poll = load_metadata()
                        if not df_poll.empty and filename in df_poll["filename"].values:
                            processed_successfully = True
                            break
                    
                    if processed_successfully:
                        st.success(f"🎉 Success! Document '{filename}' was processed and streamed to SQLite BigQuery emulator.")
                        st.balloons()
                        # Reload dashboard data
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.warning("⚠️ Processing is taking longer than expected. Check that 'utils/local_watcher.py' is running in the background.")

# ==================== TAB 2: DOCUMENT REGISTRY ====================
with tab_registry:
    st.markdown("### Processed Metadata Records")
    
    if df.empty:
        st.info("No records found in database. Ingest documents in the Ingestion Hub tab to get started.")
    else:
        col_search, col_filter = st.columns([3, 1])
        with col_search:
            search_query = st.text_input("🔍 Search documents by filename or tag...", placeholder="e.g. invoice, financial, resume")
        with col_filter:
            content_types = ["All"] + list(df["content_type"].unique())
            selected_type = st.selectbox("Filter by file type:", content_types)
            
        # Apply filters
        filtered_df = df.copy()
        if search_query:
            query = search_query.lower()
            filtered_df = filtered_df[
                filtered_df["filename"].str.lower().str.contains(query) | 
                filtered_df["tags"].str.lower().str.contains(query)
            ]
            
        if selected_type != "All":
            filtered_df = filtered_df[filtered_df["content_type"] == selected_type]
            
        st.write(f"Showing **{len(filtered_df)}** of **{len(df)}** records.")
        
        # Display Registry Dataframe
        display_df = filtered_df.copy()
        # Clean column labels for table presentation
        display_df.columns = [
            "Filename", "Simulated GCS URI", "Processed At (UTC)", 
            "Word Count", "Tags", "File Size (Bytes)", "Content Type"
        ]
        
        st.dataframe(
            display_df, 
            use_container_width=True, 
            column_config={
                "Processed At (UTC)": st.column_config.DatetimeColumn("Processed At (UTC)")
            }
        )
        
        # Detailed Viewer Expander
        st.markdown("#### Document Inspector")
        selected_file = st.selectbox("Select a file to inspect OCR metadata:", filtered_df["filename"])
        if selected_file:
            doc_row = filtered_df[filtered_df["filename"] == selected_file].iloc[0]
            col_doc1, col_doc2 = st.columns(2)
            with col_doc1:
                st.write(f"📄 **Filename:** {doc_row['filename']}")
                st.write(f"🌐 **Storage Target (GCS URI):** `{doc_row['gcs_uri']}`")
                st.write(f"🏷️ **Extracted Tags:** {doc_row['tags']}")
            with col_doc2:
                st.write(f"⏳ **Processed Date:** {doc_row['processed_at']}")
                st.write(f"📏 **File Size:** {doc_row['file_size']} Bytes")
                st.write(f"📊 **Word Count:** {doc_row['word_count']} words")

# ==================== TAB 3: PERFORMANCE ANALYTICS ====================
with tab_analytics:
    st.markdown("### Pipeline Analytics")
    
    if df.empty:
        st.info("No analytics available. Ingest documents in the Ingestion Hub to generate metrics.")
    else:
        # KPI Row
        col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
        
        total_files = len(df)
        total_words = df["word_count"].sum()
        avg_words = int(df["word_count"].mean())
        total_size_kb = round(df["file_size"].sum() / 1024, 2)
        
        with col_kpi1:
            st.metric("Total Documents Processed", f"{total_files} files")
        with col_kpi2:
            st.metric("Cumulative Word Count", f"{total_words:,} words")
        with col_kpi3:
            st.metric("Avg Words per File", f"{avg_words:,} words")
        with col_kpi4:
            st.metric("Total Storage Volume", f"{total_size_kb:,} KB")
            
        st.markdown("---")
        
        # Visualization Row
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            st.markdown("#### Tag Frequencies")
            tags_list = []
            for t in df["tags"].dropna():
                tags_list.extend([x.strip() for x in t.split(",") if x.strip()])
            
            if tags_list:
                tag_counts = pd.Series(tags_list).value_counts().reset_index()
                tag_counts.columns = ["Tag", "Occurrences"]
                st.bar_chart(tag_counts.set_index("Tag"))
            else:
                st.info("No tags found.")
                
        with col_chart2:
            st.markdown("#### Document Formats Breakdown")
            # Group extensions
            df["Extension"] = df["filename"].apply(lambda x: os.path.splitext(x)[1].lower() or "no-ext")
            ext_counts = df["Extension"].value_counts().reset_index()
            ext_counts.columns = ["Extension", "Count"]
            st.bar_chart(ext_counts.set_index("Extension"), color="#3B82F6")
