# ⚡ AetherShare - Ephemeral File Sharing App

AetherShare is a premium, secure, and time-limited file-sharing web application built with **Python** and **Streamlit**. It allows you to upload files of any format (videos, photos, PDFs, zip, docx, etc.), configure access lifetimes (e.g. minutes, hours, or days), and generate secure, self-destructing download links. Senders can also protect their files with passwords and track download history live on a gorgeous glassmorphic dashboard.

---

## ✨ Features

- **Any File Format Supported:** Upload videos, photos, PDFs, zip files, audio, etc.
- **Ephemerality (Time-Limited Links):** Define link lifetimes from **1 minute** to **multiple days** or custom durations. Once expired, the file is automatically purged from the disk and database.
- **Premium Media Viewer:** Receivers get inline preview capabilities:
  - **Photos:** Rendered in beautiful galleries.
  - **Videos/Audio:** Played directly via fluid, styled HTML5 players.
  - **PDFs:** Rendered directly using an embedded browser frame.
  - **Others:** Clear download cards showing file type, size, and secure download triggers.
- **Advanced Security (Password Lock):** Secure files using SHA-256 hashed password locks. Receivers must input the password to gain download rights.
- **Active Dashboard Control:** Keep track of your links in real-time. View how many times a link has been clicked, check live countdown timers, or immediately click **Revoke** to wipe access instantly.
- **Stunning Glassmorphism Design:** Deep space backdrop combined with neon accent gradients, responsive cards, and premium micro-interactions.

---

## 🛠️ Quick Start

### 1. Prerequisite
Ensure you have **Python 3.8+** installed.

### 2. Install Dependencies
Navigate into the application folder and install the required modules:

```bash
pip install -r requirements.txt
```

### 3. Launch the Application
Run the Streamlit application server:

```bash
streamlit run app.py
```

Streamlit will print the local host URI (usually `http://localhost:8501`). Open this link in your browser!

---

## 🏗️ Architecture & Storage Details

- **Single Process Router:** The application uses `st.query_params` to router layouts. Root level requests (`/`) display the **Sender Dashboard**, while requests with a token parameter (`/?share=UUID`) load the secure **Receiver Interface**.
- **SQLite Database:** Upload metadata (UUIDs, expiration targets, password hashes, download counts) are tracked in a lightweight SQLite database (`storage/shares.db`). No cloud storage, external APIs, or key integrations are required — it is fully self-contained and private.
- **Safe Purging / Self-Destruct:** Physical files are stored in `storage/uploads/`. The application runs a cleanup cycle during every interaction, identifying expired or revoked files and safely deleting them from the storage disk immediately.
