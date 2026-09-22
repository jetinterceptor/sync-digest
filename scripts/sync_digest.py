#!/usr/bin/env python3
"""
Syncs the latest aerospace digest from the public Google Drive folder
to index.html in the local Git workspace.
"""

import os
import re
import sys
import json
import hashlib
import requests
from datetime import datetime

FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "18gA_PGU12sAlcaPeb_phyeK0MGSgnoZQ")
API_KEY = os.environ.get("GDRIVE_API_KEY", "").strip()
TARGET_FILE = "index.html"
TEMP_COMMIT_FILE = ".sync_commit_msg.tmp"

def get_file_content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

def get_drive_files_via_api(folder_id: str, api_key: str):
    """Query Drive API v3 for files inside the public folder."""
    url = "https://www.googleapis.com/drive/v3/files"
    params = {
        "q": f"'{folder_id}' in parents and trashed = false",
        "fields": "files(id, name, mimeType, modifiedTime, size)",
        "orderBy": "modifiedTime desc",
        "pageSize": 20,
        "key": api_key,
    }
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    return response.json().get("files", [])

def download_via_api(file_id: str, api_key: str) -> bytes:
    """Download binary media from Drive API v3."""
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
    params = {"alt": "media", "key": api_key}
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.content

def download_public_file(file_id: str) -> bytes:
    """Fallback download for public Drive files without an API key."""
    session = requests.Session()
    url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&authuser=0"
    response = session.get(url, timeout=30)
    
    # If intercepted by the virus scan warning page for large files
    if "confirm=" not in response.url and "Google Drive - Virus scan warning" in response.text:
        match = re.search(r'confirm=([0-9A-Za-z_]+)', response.text)
        if match:
            confirm_token = match.group(1)
            confirm_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm={confirm_token}"
            response = session.get(confirm_url, timeout=30)

    response.raise_for_status()
    return response.content

def resolve_target_file(files):
    """
    Selects the newest daily digest HTML file.
    Prefers 'Global_Aerospace_Digest_*.html', followed by any other digest HTML,
    or a standalone 'index.html'.
    """
    digest_pattern = re.compile(r'^(?:Global_)?Aerospace_Digest_.*\.html$', re.IGNORECASE)
    
    candidates = []
    for f in files:
        name = f.get("name", "")
        if name.endswith(".html") or f.get("mimeType") in ["text/html", "text/xml"]:
            candidates.append(f)
            
    if not candidates:
        return None

    # First priority: Newest file matching the Global_Aerospace_Digest pattern
    matching_digests = [f for f in candidates if digest_pattern.match(f.get("name", ""))]
    if matching_digests:
        return matching_digests[0]

    # Second priority: index.html
    index_files = [f for f in candidates if f.get("name", "").lower() == "index.html"]
    if index_files:
        return index_files[0]

    # Fallback: Most recently modified HTML file
    return candidates[0]

def main():
    print(f"Connecting to Google Drive folder: {FOLDER_ID}")
    selected_file = None
    file_bytes = None

    if API_KEY:
        print("Using Google Drive v3 API with provided API key...")
        try:
            files = get_drive_files_via_api(FOLDER_ID, API_KEY)
            if not files:
                print("No files found in folder.")
                sys.exit(0)

            selected_file = resolve_target_file(files)
            if not selected_file:
                print("No eligible HTML digest files found in folder.")
                sys.exit(0)

            print(f"Latest candidate: {selected_file['name']} (ID: {selected_file['id']}, Modified: {selected_file.get('modifiedTime')})")
            file_bytes = download_via_api(selected_file["id"], API_KEY)
        except Exception as e:
            print(f"Error querying Drive API: {e}. Falling back to public endpoints...")

    # Fallback to direct public file download if API key was omitted or failed
    if not file_bytes:
        # Check standard known file ID for index.html or fallback to direct download
        known_index_id = "1DiZ37VasW_ELidAfbh8xaJUyonpQjS1x"
        print(f"Attempting public direct download for file ID: {known_index_id}")
        file_bytes = download_public_file(known_index_id)
        selected_file = {"name": "index.html", "id": known_index_id, "modifiedTime": datetime.utcnow().isoformat()}

    if not file_bytes:
        print("Failed to retrieve file content.")
        sys.exit(1)

    new_hash = get_file_content_hash(file_bytes)

    # Check existing local index.html hash
    current_hash = None
    if os.path.exists(TARGET_FILE):
        with open(TARGET_FILE, "rb") as f:
            current_hash = get_file_content_hash(f.read())

    if new_hash == current_hash:
        print("Local index.html is identical to remote Drive version. No update required.")
        sys.exit(0)

    # Write updated index.html
    print(f"Updating {TARGET_FILE} ({len(file_bytes):,} bytes)...")
    with open(TARGET_FILE, "wb") as f:
        f.write(file_bytes)

    # Write commit message for workflow
    mod_time = selected_file.get("modifiedTime", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    commit_msg = f"Sync digest: {selected_file['name']} ({mod_time})"
    with open(TEMP_COMMIT_FILE, "w", encoding="utf-8") as f:
        f.write(commit_msg)

    print("Sync complete. Ready for commit.")

if __name__ == "__main__":
    main()
