import streamlit as st
import sqlite3
import uuid
import os
import datetime
import hashlib
import mimetypes
import base64
import pytz

# ==========================================
# 1. APPLICATION DIRECTORY & DATABASE SETUP
# ==========================================

# Determine portable path relative to app.py
APP_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(APP_DIR, "storage")
UPLOAD_DIR = os.path.join(STORAGE_DIR, "uploads")
DB_PATH = os.path.join(STORAGE_DIR, "shares.db")

# Ensure storage and upload directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_db_connection():
    """Returns a SQLite database connection with row factory configured."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database schema if it doesn't already exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shares (
            uuid TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            content_type TEXT NOT NULL,
            upload_time TEXT NOT NULL,
            expire_time TEXT NOT NULL,
            password_hash TEXT,
            download_count INTEGER DEFAULT 0,
            is_revoked INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

# Run database initialization
init_db()

# ==========================================
# 2. UTILITY & HELPER FUNCTIONS
# ==========================================

def get_file_size_friendly(bytes_size):
    """Converts bytes to a human-readable string (KB, MB, GB)."""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.2f} KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.2f} MB"
    else:
        return f"{bytes_size / (1024 * 1024 * 1024):.2f} GB"

def get_utc_now():
    """Returns current datetime in UTC (naive, for database consistency)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

def hash_password(password):
    """Hashes a password string using SHA-256."""
    if not password:
        return None
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def check_password(password, hashed_password):
    """Verifies a password against its SHA-256 hash."""
    if not hashed_password:
        return True
    if not password:
        return False
    return hash_password(password) == hashed_password

def add_share(uuid_str, filename, file_path, content_type, expire_seconds, password=None):
    """Inserts a new share link entry into the database."""
    now_utc = get_utc_now()
    expire_utc = now_utc + datetime.timedelta(seconds=expire_seconds)
    
    password_hash = hash_password(password)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO shares (uuid, filename, file_path, content_type, upload_time, expire_time, password_hash, download_count, is_revoked)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)
    """, (
        uuid_str,
        filename,
        file_path,
        content_type,
        now_utc.isoformat(),
        expire_utc.isoformat(),
        password_hash
    ))
    conn.commit()
    conn.close()

def get_share(uuid_str):
    """Fetches a share record by its UUID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shares WHERE uuid = ?", (uuid_str,))
    row = cursor.fetchone()
    conn.close()
    return row

def increment_download(uuid_str):
    """Increments the download counter for a specific share link."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE shares SET download_count = download_count + 1 WHERE uuid = ?", (uuid_str,))
    conn.commit()
    conn.close()

def revoke_share(uuid_str):
    """Revokes a share link immediately and deletes its file to free disk space."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM shares WHERE uuid = ?", (uuid_str,))
    row = cursor.fetchone()
    
    if row:
        file_path = row["file_path"]
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error deleting file during revocation: {e}")
                
    cursor.execute("UPDATE shares SET is_revoked = 1 WHERE uuid = ?", (uuid_str,))
    conn.commit()
    conn.close()

def cleanup_expired_files():
    """Identifies and physically deletes files from disk for expired or revoked links."""
    now_utc = get_utc_now()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Select all shares that are expired or revoked but still have files stored
    cursor.execute("SELECT uuid, file_path FROM shares WHERE is_revoked = 1")
    revoked_shares = cursor.fetchall()
    
    cursor.execute("SELECT uuid, file_path, expire_time FROM shares WHERE is_revoked = 0")
    active_shares = cursor.fetchall()
    
    cleaned_count = 0
    
    # 1. Process revoked shares
    for share in revoked_shares:
        file_path = share["file_path"]
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                cleaned_count += 1
            except Exception as e:
                print(f"Cleanup error for revoked share {share['uuid']}: {e}")
                
    # 2. Process expired shares
    for share in active_shares:
        expire_time = datetime.datetime.fromisoformat(share["expire_time"])
        if now_utc > expire_time:
            file_path = share["file_path"]
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    cleaned_count += 1
                except Exception as e:
                    print(f"Cleanup error for expired share {share['uuid']}: {e}")
                    
    conn.close()
    return cleaned_count

def get_all_shares():
    """Fetches all share links, sorted by upload time descending."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shares ORDER BY upload_time DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_base_url():
    """Attempts to construct the base URL of the running Streamlit server dynamically."""
    # Fallback to standard Streamlit port
    base = "http://localhost:8501"
    
    # Try reading from Streamlit's server context headers if available
    try:
        # Streamlit 1.30+ context headers
        headers = st.context.headers
        host = headers.get("Host")
        if host:
            # Detect protocol (usually http, unless behind standard https proxy)
            proto = headers.get("X-Forwarded-Proto", "http")
            base = f"{proto}://{host}"
    except Exception:
        pass
        
    return base

# ==========================================
# 3. PREMIUM PREMIUM STYLING INJECTION (CSS)
# ==========================================

def inject_premium_styles():
    """Injects ultra-modern CSS stylesheets into Streamlit to create a glassmorphic dark-mode theme."""
    st.markdown("""
        <style>
        /* Import outfit & inter fonts */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800&display=swap');
        
        /* Apply fonts globally */
        html, body, [class*="css"], .stMarkdown {
            font-family: 'Inter', -apple-system, sans-serif;
            color: #e2e8f0;
        }
        
        h1, h2, h3, h4, h5, h6 {
            font-family: 'Outfit', sans-serif !important;
            font-weight: 700 !important;
            letter-spacing: -0.02em;
        }
        
        /* Outer Background */
        .stApp {
            background: radial-gradient(circle at 50% 0%, #150f2e 0%, #080612 70%);
            background-attachment: fixed;
        }
        
        /* Glassmorphic Container */
        .glass-card {
            background: rgba(18, 14, 38, 0.45);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 20px;
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            padding: 30px;
            margin-bottom: 24px;
            box-shadow: 0 10px 40px 0 rgba(0, 0, 0, 0.4);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .glass-card:hover {
            border-color: rgba(157, 78, 221, 0.3);
            box-shadow: 0 12px 50px 0 rgba(157, 78, 221, 0.15);
        }
        
        /* Micro card details */
        .glass-subcard {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            padding: 15px;
            margin-top: 10px;
        }
        
        /* Main Title Gradient */
        .gradient-text {
            background: linear-gradient(135deg, #f72585 0%, #7209b7 50%, #4cc9f0 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-weight: 800 !important;
            font-size: 3rem !important;
            text-align: center;
            margin-bottom: 10px !important;
            filter: drop-shadow(0px 2px 10px rgba(114, 9, 183, 0.3));
        }
        
        .gradient-subtitle {
            color: #9d4ede;
            text-align: center;
            font-size: 1.1rem;
            margin-bottom: 35px;
            font-weight: 400;
            letter-spacing: 0.05em;
        }
        
        /* Styled buttons */
        div.stButton > button {
            background: linear-gradient(135deg, #7209b7 0%, #9d4ede 100%) !important;
            color: #ffffff !important;
            border: none !important;
            border-radius: 10px !important;
            padding: 12px 24px !important;
            font-family: 'Outfit', sans-serif !important;
            font-weight: 600 !important;
            transition: all 0.25s ease !important;
            box-shadow: 0 4px 15px rgba(114, 9, 183, 0.4) !important;
            width: 100%;
        }
        
        div.stButton > button:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 6px 20px rgba(157, 78, 221, 0.6) !important;
            background: linear-gradient(135deg, #9d4ede 0%, #b5179e 100%) !important;
        }
        
        div.stButton > button:active {
            transform: translateY(0px) !important;
        }
        
        /* Download Button overrides (Streamlit uses different classes) */
        a[role="button"] {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #00f5d4 0%, #00bbf9 100%) !important;
            color: #080612 !important;
            border: none !important;
            border-radius: 10px !important;
            padding: 12px 24px !important;
            font-family: 'Outfit', sans-serif !important;
            font-weight: 700 !important;
            text-decoration: none !important;
            transition: all 0.25s ease !important;
            box-shadow: 0 4px 15px rgba(0, 245, 212, 0.3) !important;
            width: 100%;
            text-align: center;
        }
        
        a[role="button"]:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 6px 20px rgba(0, 187, 249, 0.5) !important;
            color: #000000 !important;
        }
        
        /* Revoke/Dangerous Action Button */
        .revoke-btn button {
            background: linear-gradient(135deg, #f72585 0%, #b5179e 100%) !important;
            box-shadow: 0 4px 15px rgba(247, 37, 133, 0.3) !important;
            font-size: 0.85rem !important;
            padding: 6px 14px !important;
        }
        
        .revoke-btn button:hover {
            background: linear-gradient(135deg, #ff4d6d 0%, #f72585 100%) !important;
            box-shadow: 0 6px 20px rgba(247, 37, 133, 0.5) !important;
        }
        
        /* Decorative badge/glow elements */
        .badge {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 20px;
            padding: 4px 12px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            display: inline-block;
        }
        
        .badge-active {
            background: rgba(0, 245, 212, 0.1);
            border-color: rgba(0, 245, 212, 0.3);
            color: #00f5d4;
        }
        
        .badge-expired {
            background: rgba(247, 37, 133, 0.1);
            border-color: rgba(247, 37, 133, 0.3);
            color: #f72585;
        }
        
        .badge-locked {
            background: rgba(255, 183, 3, 0.1);
            border-color: rgba(255, 183, 3, 0.3);
            color: #ffb703;
        }
        
        /* Custom scrollbar */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: rgba(8, 6, 18, 0.9);
        }
        ::-webkit-scrollbar-thumb {
            background: rgba(114, 9, 183, 0.4);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(157, 78, 221, 0.6);
        }
        
        /* Styling standard inputs */
        .stTextInput input, .stSelectbox div[role="button"], .stNumberInput input {
            background-color: rgba(255, 255, 255, 0.04) !important;
            border: 1px solid rgba(255, 255, 255, 0.1) !important;
            color: #ffffff !important;
            border-radius: 8px !important;
            padding: 8px 12px !important;
        }
        
        .stTextInput input:focus {
            border-color: #9d4ede !important;
            box-shadow: 0 0 0 2px rgba(157, 78, 221, 0.2) !important;
        }
        
        /* Premium Tabs Styling Override */
        div[data-testid="stTabBar"] {
            background: rgba(18, 14, 38, 0.35) !important;
            border: 1px solid rgba(255, 255, 255, 0.06) !important;
            border-radius: 12px !important;
            padding: 5px !important;
            margin-bottom: 20px !important;
            display: flex !important;
            justify-content: center !important;
        }
        
        button[data-baseweb="tab"] {
            font-family: 'Outfit', sans-serif !important;
            font-size: 1.05rem !important;
            font-weight: 600 !important;
            color: #a0aec0 !important;
            background: transparent !important;
            border: none !important;
            padding: 10px 24px !important;
            margin: 0 4px !important;
            border-radius: 8px !important;
            transition: all 0.3s ease !important;
        }
        
        button[data-baseweb="tab"]:hover {
            color: #9d4ede !important;
            background: rgba(255, 255, 255, 0.03) !important;
        }
        
        button[aria-selected="true"] {
            color: #ffffff !important;
            background: linear-gradient(135deg, rgba(114, 9, 183, 0.3) 0%, rgba(157, 78, 221, 0.2) 100%) !important;
            border-bottom: 2px solid #f72585 !important;
            box-shadow: inset 0 0 10px rgba(157, 78, 221, 0.1) !important;
        }
        
        /* Premium File Uploader Box Styling */
        div[data-testid="stFileUploader"] {
            background: rgba(255, 255, 255, 0.01) !important;
            border: 2px dashed rgba(157, 78, 221, 0.25) !important;
            border-radius: 14px !important;
            padding: 20px 10px !important;
            transition: all 0.3s ease !important;
        }
        
        div[data-testid="stFileUploader"]:hover {
            border-color: #f72585 !important;
            background: rgba(157, 78, 221, 0.03) !important;
            box-shadow: 0 0 15px rgba(247, 37, 133, 0.1) !important;
        }

        /* Vercel Copyable Box */
        .copy-container {
            display: flex;
            align-items: center;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 12px 18px;
            margin-top: 15px;
            gap: 12px;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.2);
        }

        .copy-url-input {
            flex-grow: 1;
            background: transparent;
            border: none;
            color: #00f5d4;
            font-family: monospace;
            font-size: 0.95rem;
            outline: none;
            text-overflow: ellipsis;
            white-space: nowrap;
            overflow: hidden;
        }

        .copy-action-btn {
            background: linear-gradient(135deg, #00f5d4 0%, #00bbf9 100%);
            border: none;
            border-radius: 8px;
            color: #080612;
            padding: 8px 16px;
            font-size: 0.85rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s ease;
            white-space: nowrap;
            box-shadow: 0 4px 10px rgba(0, 245, 212, 0.2);
        }

        .copy-action-btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 15px rgba(0, 187, 249, 0.4);
            filter: brightness(1.1);
        }

        .copy-action-btn:active {
            transform: translateY(1px);
        }
        
        /* Hide default Streamlit footer */
        footer {visibility: hidden;}
        #MainMenu {visibility: hidden;}
        </style>
    """, unsafe_allow_html=True)

# ==========================================
# 4. RENDERER COMPONENTS (RECEIVER PAGE)
# ==========================================

def render_file_preview(file_path, filename, content_type):
    """Inlines the correct media player or reader based on MIME type."""
    if not os.path.exists(file_path):
        st.error("The physical file is missing from local storage.")
        return

    # Extract clean file size
    size_bytes = os.path.getsize(file_path)
    friendly_size = get_file_size_friendly(size_bytes)
    
    st.markdown("### 📦 Shared File Preview")
    
    # 1. Image Previewer
    if content_type.startswith("image/"):
        st.markdown('<div class="glass-subcard">', unsafe_allow_html=True)
        st.image(file_path, caption=filename, use_column_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
    # 2. Video Player
    elif content_type.startswith("video/"):
        st.markdown('<div class="glass-subcard">', unsafe_allow_html=True)
        st.video(file_path)
        st.markdown('</div>', unsafe_allow_html=True)
        
    # 3. Audio Player
    elif content_type.startswith("audio/"):
        st.markdown('<div class="glass-subcard">', unsafe_allow_html=True)
        st.audio(file_path)
        st.markdown('</div>', unsafe_allow_html=True)
        
    # 4. PDF Reader
    elif "pdf" in content_type:
        st.markdown('<div class="glass-subcard">', unsafe_allow_html=True)
        try:
            with open(file_path, "rb") as f:
                base64_pdf = base64.b64encode(f.read()).decode('utf-8')
            pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600px" style="border: none; border-radius: 8px;"></iframe>'
            st.markdown(pdf_display, unsafe_allow_html=True)
        except Exception:
            st.info("Direct PDF rendering is restricted by your browser. You can safely download it below.")
        st.markdown('</div>', unsafe_allow_html=True)
        
    # 5. Generic Document File Card
    else:
        st.markdown(f"""
            <div class="glass-subcard" style="text-align: center; padding: 30px;">
                <div style="font-size: 3.5rem; margin-bottom: 10px;">📄</div>
                <div style="font-size: 1.2rem; font-weight: 600; margin-bottom: 5px; word-break: break-all;">{filename}</div>
                <div style="color: #9d4ede; font-weight: 500; font-size: 0.95rem;">{friendly_size} • {content_type}</div>
                <div style="color: #8e9aaf; font-size: 0.85rem; margin-top: 10px;">
                    This file format is not previewable inline. Please download it using the secure button below to access it.
                </div>
            </div>
        """, unsafe_allow_html=True)

    # 6. Action Download Button
    st.markdown("<br>", unsafe_allow_html=True)
    with open(file_path, "rb") as f:
        file_bytes = f.read()
        
    st.download_button(
        label=f"⬇️ Download File ({friendly_size})",
        data=file_bytes,
        file_name=filename,
        mime=content_type,
        key="receiver_download_btn"
    )

# ==========================================
# 5. SCREEN: ACCESS EXPIRED OR REVOKED
# ==========================================

def show_expired_screen(reason="expired"):
    """Displays a stunning full-screen style expiration error card."""
    title = "Access Period Expired" if reason == "expired" else "Secure Share Revoked"
    emoji = "⏰" if reason == "expired" else "🚫"
    description = (
        "This shareable link has surpassed its configured expiration time. The temporary file storage "
        "has been safely self-destructed and purged from disk to guarantee absolute privacy."
        if reason == "expired" else
        "This share link was manually revoked or deactivated by the sender. The underlying physical storage "
        "has been wiped from the database and disk."
    )
    
    st.markdown(f"""
        <div class="glass-card" style="text-align: center; max-width: 600px; margin: 80px auto; padding: 40px;">
            <div style="font-size: 4.5rem; margin-bottom: 20px; animation: pulse 2s infinite;">{emoji}</div>
            <h2 style="color: #f72585; margin-bottom: 15px;">{title}</h2>
            <p style="color: #cbd5e1; font-size: 1.05rem; line-height: 1.6; margin-bottom: 25px;">
                {description}
            </p>
            <div style="border-top: 1px solid rgba(255,255,255,0.08); padding-top: 20px; color: #9d4ede; font-size: 0.9rem; font-weight: 500;">
                If you still need this file, please contact the sender and request a new time-limited share link.
            </div>
        </div>
    """, unsafe_allow_html=True)

# ==========================================
# 6. ROUTER & VIEWS ORCHESTRATOR
# ==========================================

def main():
    # Page settings and responsive design
    st.set_page_config(
        page_title="AetherShare | Ephemeral & Time-Limited Sharing",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    
    # Inject styling
    inject_premium_styles()
    
    # Process auto-cleanup on every app load/interaction
    cleanup_expired_files()
    
    # Check URL query parameters
    query_params = st.query_params
    share_token = query_params.get("share")
    
    if share_token:
        # ==========================================
        # ROUTE: RECEIVER PAGE VIEW
        # ==========================================
        render_receiver_page(share_token)
    else:
        # ==========================================
        # ROUTE: SENDER / ADMIN DASHBOARD VIEW
        # ==========================================
        render_sender_page()

# ==========================================
# 7. SENDER DASHBOARD VIEW
# ==========================================

def render_sender_page():
    # Elegant logo and titles
    st.markdown('<h1 class="gradient-text">⚡ AETHER SHARE</h1>', unsafe_allow_html=True)
    st.markdown('<p class="gradient-subtitle">SECURE, SELF-DESTRUCTING, TIME-LIMITED FILE UTILITY</p>', unsafe_allow_html=True)
    
    # Create beautiful tabs for premium UX layout
    tab_upload, tab_manage = st.tabs(["🚀 UPLOAD & SHARE FILE", "📋 ACTIVE SHARES & HISTORY"])
    
    with tab_upload:
        # Centered card layout for cleaner view
        col_pad1, col_center, col_pad2 = st.columns([1, 4, 1])
        
        with col_center:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            st.markdown("<h3 style='margin-bottom: 20px;'>📤 Upload Temporary File</h3>", unsafe_allow_html=True)
            
            # Step 1: File Uploader
            st.markdown("<div style='font-weight:600; color:#f72585; margin-bottom:8px;'>1️⃣ CHOOSE YOUR DOCUMENT OR MEDIA:</div>", unsafe_allow_html=True)
            uploaded_file = st.file_uploader(
                "Select a file",
                type=None,
                help="Supports any format including MP4, PNG, JPG, PDF, ZIP, keynotes, etc.",
                label_visibility="collapsed"
            )
            
            # Step 2: Access Lifetime Settings
            st.markdown("<br><div style='font-weight:600; color:#9d4ede; margin-bottom:8px;'>2️⃣ CHOOSE LINK LIFESPAN:</div>", unsafe_allow_html=True)
            duration_option = st.selectbox(
                "Select duration",
                [
                    "1 Minute (Best for Testing)",
                    "5 Minutes",
                    "15 Minutes",
                    "1 Hour",
                    "4 Hours",
                    "12 Hours",
                    "1 Day",
                    "Custom Duration"
                ],
                index=1, # Default 5 Minutes
                label_visibility="collapsed"
            )
            
            # Compute Expiration Duration
            expire_seconds = 300
            if duration_option == "1 Minute (Best for Testing)":
                expire_seconds = 60
            elif duration_option == "5 Minutes":
                expire_seconds = 5 * 60
            elif duration_option == "15 Minutes":
                expire_seconds = 15 * 60
            elif duration_option == "1 Hour":
                expire_seconds = 3600
            elif duration_option == "4 Hours":
                expire_seconds = 4 * 3600
            elif duration_option == "12 Hours":
                expire_seconds = 12 * 3600
            elif duration_option == "1 Day":
                expire_seconds = 24 * 3600
            elif duration_option == "Custom Duration":
                c_col1, c_col2 = st.columns(2)
                with c_col1:
                    val = st.number_input("Custom Interval Value", min_value=1, value=10, step=1)
                with c_col2:
                    unit = st.selectbox("Interval Metric", ["Seconds", "Minutes", "Hours", "Days"], index=1)
                    
                if unit == "Seconds":
                    expire_seconds = val
                elif unit == "Minutes":
                    expire_seconds = val * 60
                elif unit == "Hours":
                    expire_seconds = val * 3600
                elif unit == "Days":
                    expire_seconds = val * 24 * 3600
            
            # Step 3: Password Locking
            st.markdown("<br><div style='font-weight:600; color:#4cc9f0; margin-bottom:8px;'>3️⃣ PASSWORD SECURITY OPTIONS (OPTIONAL):</div>", unsafe_allow_html=True)
            with st.expander("🔒 Configure Password Lock"):
                use_password = st.checkbox("Require password to access this file", help="Receivers must input this password to unlock or download.")
                password_str = ""
                if use_password:
                    password_str = st.text_input("Set Access Password:", type="password", placeholder="Enter authorization key")
                    if not password_str:
                        st.warning("Password lock is selected, but key is blank. Receivers can bypass protection.")
            
            # Action: Create Shareable Link
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🚀 Generate Secure Share Link", key="generate_link_btn"):
                if uploaded_file is None:
                    st.error("⚠️ Please select a file to upload first!")
                else:
                    share_uuid = str(uuid.uuid4())
                    original_filename = uploaded_file.name
                    mime_type, _ = mimetypes.guess_type(original_filename)
                    if not mime_type:
                        mime_type = "application/octet-stream"
                    
                    file_ext = os.path.splitext(original_filename)[1]
                    storage_filename = f"{share_uuid}{file_ext}"
                    local_file_path = os.path.join(UPLOAD_DIR, storage_filename)
                    
                    try:
                        with open(local_file_path, "wb") as f:
                            f.write(uploaded_file.getbuffer())
                            
                        add_share(
                            uuid_str=share_uuid,
                            filename=original_filename,
                            file_path=local_file_path,
                            content_type=mime_type,
                            expire_seconds=expire_seconds,
                            password=password_str if use_password else None
                        )
                        
                        st.success("🎉 File uploaded successfully! Link is ready.")
                        
                        base_url = get_base_url()
                        full_share_url = f"{base_url}/?share={share_uuid}"
                        
                        # Breathtaking interactive Vercel-style copy card
                        st.markdown(f"""
                            <div class="copy-container">
                                <input type="text" class="copy-url-input" id="shareUrlInput" value="{full_share_url}" readonly />
                                <button class="copy-action-btn" onclick="navigator.clipboard.writeText('{full_share_url}'); alert('✨ Share link copied to clipboard!');">📋 Copy Link</button>
                            </div>
                        """, unsafe_allow_html=True)
                        
                        # Fallback input for keyboard copy
                        st.text_input("Fallback Link Selection:", value=full_share_url, key="generated_url_box")
                        st.toast("Temporary link generated!", icon="⚡")
                        
                    except Exception as e:
                        st.error(f"Failed to save physical file: {e}")
                        
            st.markdown('</div>', unsafe_allow_html=True) # close glass-card
            
    with tab_manage:
        col_pad1, col_center, col_pad2 = st.columns([1, 10, 1])
        
        with col_center:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            st.markdown("<h3 style='margin-bottom: 20px;'>📋 Active & Expired Shares Track</h3>", unsafe_allow_html=True)
            
            shares = get_all_shares()
            
            if not shares:
                st.markdown("""
                    <div style="text-align: center; padding: 60px 10px; color: #8e9aaf;">
                        <div style="font-size: 4rem; margin-bottom: 15px;">🛡️</div>
                        <div style="font-size: 1.1rem; font-weight: 500;">No active files uploaded yet.</div>
                        <div style="font-size: 0.9rem; margin-top: 5px; color: #626c7a;">Create one in the uploader tab to track access lives.</div>
                    </div>
                """, unsafe_allow_html=True)
            else:
                now_utc = get_utc_now()
                
                # Render beautiful custom dashboard cards for active files
                for i, row in enumerate(shares):
                    uuid_val = row["uuid"]
                    filename = row["filename"]
                    upload_str = row["upload_time"]
                    expire_str = row["expire_time"]
                    password_hash = row["password_hash"]
                    download_count = row["download_count"]
                    is_revoked = row["is_revoked"]
                    
                    expire_dt = datetime.datetime.fromisoformat(expire_str)
                    is_expired = now_utc > expire_dt
                    
                    # Localize time presentation
                    try:
                        utc_dt = pytz.utc.localize(datetime.datetime.fromisoformat(upload_str))
                        local_tz = pytz.timezone('Europe/London')
                        local_time_str = utc_dt.astimezone(local_tz).strftime("%H:%M:%S (%d %b)")
                    except Exception:
                        local_time_str = upload_str.replace("T", " ")[:16]
                    
                    # Badge components
                    if is_revoked:
                        status_badge = '<span class="badge badge-expired">🚫 Revoked</span>'
                    elif is_expired:
                        status_badge = '<span class="badge badge-expired">⏰ Expired</span>'
                    else:
                        status_badge = '<span class="badge badge-active">🟢 Active</span>'
                        
                    security_badge = ""
                    if password_hash:
                        security_badge = '<span class="badge badge-locked" style="margin-left:5px;">🔑 Password</span>'
                    
                    # Expiration Timer Countdown
                    if not is_expired and not is_revoked:
                        diff = expire_dt - now_utc
                        total_sec = int(diff.total_seconds())
                        
                        if total_sec < 60:
                            countdown_text = f"⏰ Self-destructs in {total_sec}s"
                        elif total_sec < 3600:
                            countdown_text = f"⏰ Self-destructs in {total_sec // 60}m {total_sec % 60}s"
                        else:
                            countdown_text = f"⏰ Self-destructs in {total_sec // 3600}h {((total_sec % 3600) // 60)}m"
                    else:
                        countdown_text = "🗑️ Deleted & Cleaned from disk"
                    
                    # Custom CSS Grid layout for premium look
                    st.markdown(f"""
                        <div style="background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 12px; padding: 20px; margin-bottom: 16px; transition: 0.2s;">
                            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
                                <div style="flex-grow: 1; min-width: 250px;">
                                    <h4 style="margin: 0 0 6px 0; color: #f72585; word-break: break-all;">{filename}</h4>
                                    <div style="font-size: 0.85rem; color: #8e9aaf;">
                                        Uploaded: {local_time_str} • Views: <strong>{download_count}</strong>
                                    </div>
                                    <div style="font-size: 0.85rem; color: #00f5d4; font-weight: 600; margin-top: 6px;">
                                        {countdown_text}
                                    </div>
                                </div>
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    {status_badge}
                                    {security_badge}
                                </div>
                            </div>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    # Direct Action Row for active shares
                    if not is_expired and not is_revoked:
                        act_col1, act_col2 = st.columns([6, 1])
                        with act_col1:
                            direct_url = f"{get_base_url()}/?share={uuid_val}"
                            
                            st.markdown(f"""
                                <div class="copy-container" style="margin-top: 0; padding: 6px 14px; border-radius: 8px;">
                                    <input type="text" class="copy-url-input" style="font-size: 0.85rem;" id="shareUrlInput_{uuid_val}" value="{direct_url}" readonly />
                                    <button class="copy-action-btn" style="padding: 5px 12px; font-size: 0.8rem;" onclick="navigator.clipboard.writeText('{direct_url}'); alert('✨ Share link copied!');">📋 Copy</button>
                                </div>
                            """, unsafe_allow_html=True)
                        with act_col2:
                            st.markdown('<div class="revoke-btn" style="margin-top: 5px;">', unsafe_allow_html=True)
                            if st.button("Revoke Link", key=f"rvk_{uuid_val}"):
                                revoke_share(uuid_val)
                                st.toast(f"Revoked link to {filename}", icon="🚫")
                                st.rerun()
                            st.markdown('</div>', unsafe_allow_html=True)
                            
            st.markdown('</div>', unsafe_allow_html=True) # close glass-card

# ==========================================
# 8. RECEIVER PAGE VIEW
# ==========================================

def render_receiver_page(share_uuid):
    # Fetch share record
    share_data = get_share(share_uuid)
    
    if not share_data:
        show_expired_screen("not_found")
        return
        
    is_revoked = share_data["is_revoked"]
    file_path = share_data["file_path"]
    filename = share_data["filename"]
    content_type = share_data["content_type"]
    expire_str = share_data["expire_time"]
    password_hash = share_data["password_hash"]
    
    # Check if manually revoked or already deleted from disk
    if is_revoked or not os.path.exists(file_path):
        show_expired_screen("revoked")
        return
        
    # Check if time expired
    now_utc = get_utc_now()
    expire_dt = datetime.datetime.fromisoformat(expire_str)
    if now_utc > expire_dt:
        # Perform dynamic cleanup for disk safety
        cleanup_expired_files()
        show_expired_screen("expired")
        return
        
    # Calculate live time left
    time_left = expire_dt - now_utc
    total_seconds_left = int(time_left.total_seconds())
    
    if total_seconds_left <= 0:
        cleanup_expired_files()
        show_expired_screen("expired")
        return
        
    # Pretty format countdown
    if total_seconds_left < 60:
        formatted_countdown = f"{total_seconds_left} seconds"
    elif total_seconds_left < 3600:
        formatted_countdown = f"{total_seconds_left // 60}m {total_seconds_left % 60}s"
    else:
        formatted_countdown = f"{total_seconds_left // 3600}h {((total_seconds_left % 3600) // 60)}m"

    # Screen Wrapper
    st.markdown('<h1 class="gradient-text" style="font-size: 2.2rem !important; margin-top:30px !important;">⚡ SECURE SHARE UTILITY</h1>', unsafe_allow_html=True)
    
    # Center Card
    st.markdown('<div class="glass-card" style="max-width: 800px; margin: 0 auto;">', unsafe_allow_html=True)
    
    # Security header banner
    st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255, 255, 255, 0.08); padding-bottom: 15px; margin-bottom: 20px;">
            <div>
                <span class="badge badge-active">🛡️ Secure Share Link Verified</span>
            </div>
            <div style="text-align: right; color: #f72585; font-weight: 600; font-size: 0.95rem;">
                ⏱️ Destructs in {formatted_countdown}
            </div>
        </div>
    """, unsafe_allow_html=True)

    # 1. Password Verification Flow (if protected)
    if password_hash:
        # Initialize session state for unlocked shares
        if "unlocked_shares" not in st.session_state:
            st.session_state.unlocked_shares = set()
            
        if share_uuid not in st.session_state.unlocked_shares:
            # Show Password Access Portal
            st.markdown("""
                <div style="text-align: center; padding: 20px 0;">
                    <div style="font-size: 3rem; margin-bottom: 15px;">🔒</div>
                    <h4>This file is password-protected</h4>
                    <p style="color: #8e9aaf; font-size: 0.9rem;">You must enter the authorization code provided by the sender to view or download this document.</p>
                </div>
            """, unsafe_allow_html=True)
            
            p_col1, p_col2 = st.columns([3, 1])
            with p_col1:
                entered_pass = st.text_input("Enter Passcode:", type="password", key="pass_input_receiver", placeholder="Enter share passcode")
            with p_col2:
                st.markdown("<br>", unsafe_allow_html=True)
                unlock_clicked = st.button("Verify & Unlock")
                
            if unlock_clicked or (entered_pass and st.session_state.get("pass_input_receiver_enter")):
                if check_password(entered_pass, password_hash):
                    st.session_state.unlocked_shares.add(share_uuid)
                    increment_download(share_uuid)
                    st.toast("Unlocked! Fetching secure data...", icon="🔓")
                    st.rerun()
                else:
                    st.error("❌ Incorrect passcode. Please check your credentials and try again.")
            
            st.markdown('</div>', unsafe_allow_html=True) # close glass-card
            return
            
    # If not password protected, track view count on initial load
    if not password_hash:
        # Track that they successfully loaded this session
        if "viewed_shares" not in st.session_state:
            st.session_state.viewed_shares = set()
            
        if share_uuid not in st.session_state.viewed_shares:
            increment_download(share_uuid)
            st.session_state.viewed_shares.add(share_uuid)

    # 2. Render Inline Preview and Download Action
    render_file_preview(file_path, filename, content_type)
    
    st.markdown('</div>', unsafe_allow_html=True) # close glass-card

if __name__ == "__main__":
    main()
