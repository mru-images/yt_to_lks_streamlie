import streamlit as st
import yt_dlp
import requests
import re
import json
from io import BytesIO
from supabase import create_client, Client

# 🔐 Hardcoded credentials
PCLOUD_AUTH_TOKEN = "fE93KkZMjhg7ZtHMudQY9CHj5m8MDH3CFxLEKsw1y"
SUPABASE_URL = "https://yssrurhhizdcmctxrxec.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inlzc3J1cmhoaXpkY21jdHhyeGVjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTEyOTUzNTUsImV4cCI6MjA2Njg3MTM1NX0.h3x6OjrCWKaKR7CHNfA7dl_bnmmMj6AmmNWhWW6mpo4"
GEMINI_API_KEY = "AIzaSyCGcpIzYiPhFIB8YiQtZNmGYTUtXQCFOoE"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Utility functions
def sanitize_title(title):
    return re.sub(r'[\\/*?:"<>|#]', "", title).strip()[:100]

def extract_video_id(url):
    if "youtu.be/" in url:
        return url.split("youtu.be/")[-1]
    elif "watch?v=" in url:
        return url.split("watch?v=")[-1]
    raise ValueError("Invalid YouTube URL")

def get_or_create_folder(folder_name):
    res = requests.get("https://api.pcloud.com/listfolder", params={"auth": PCLOUD_AUTH_TOKEN, "folderid": 0})
    for item in res.json().get("metadata", {}).get("contents", []):
        if item.get("isfolder") and item.get("name") == folder_name:
            return item["folderid"]
    res = requests.get("https://api.pcloud.com/createfolder", params={"auth": PCLOUD_AUTH_TOKEN, "name": folder_name, "folderid": 0})
    return res.json()["metadata"]["folderid"]

def upload_file_stream(stream, filename, folder_id):
    res = requests.post(
        "https://api.pcloud.com/uploadfile",
        params={"auth": PCLOUD_AUTH_TOKEN, "folderid": folder_id},
        files={"file": (filename, stream)}
    )
    return res.json()["metadata"][0]["fileid"]

def download_audio_stream(url):
    buffer = BytesIO()

    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio',
        'outtmpl': '-',  # No file output path
        'quiet': True,
        'noplaylist': True,
        'prefer_ffmpeg': False,  # Don't require ffmpeg
        'postprocessors': [],    # No conversion
        'logtostderr': False,
        'cachedir': False,
        'logger': None,
        'progress_hooks': [lambda d: None],
        'outtmpl': {
            'default': '%(title).100s.%(ext)s'
        },
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = sanitize_title(info["title"])
        ext = info["ext"] or "m4a"

        # Actually download the file
        ydl.download([url])

        # Use `info['requested_downloads'][0]['filepath']` to open the saved temp file
        filepath = info["requested_downloads"][0]["filepath"]
        with open(filepath, "rb") as f:
            buffer.write(f.read())
        buffer.seek(0)

    return buffer, title, extract_video_id(url)

def download_thumbnail_stream(video_id):
    for q in ["maxresdefault", "hqdefault", "mqdefault", "default"]:
        url = f"https://img.youtube.com/vi/{video_id}/{q}.jpg"
        r = requests.get(url)
        if r.status_code == 200:
            return BytesIO(r.content)
    raise Exception("Thumbnail not found.")

def get_tags_from_gemini(song_name):
    TAG_CATEGORIES = {
        "genre": ["pop", "rock", "hiphop", "rap", "edm", "classical", "folk"],
        "mood": ["happy", "sad", "chill", "energetic"],
        "occasion": ["party", "study", "sleep", "wedding"],
        "era": ["2020s", "2010s", "2000s", "90s"],
        "vocal_instrument": ["male_vocals", "female_vocals", "instrumental"]
    }

    prompt = f"""
Given the song name "{song_name}", identify its artist and language.
Then suggest tags from ONLY the predefined list below.
Return JSON format like:
{{
  "artist": "Artist Name",
  "language": "Language",
  "genre": [...],
  "mood": [...],
  "occasion": [...],
  "era": [...],
  "vocal_instrument": [...]
}}
Predefined tags: {json.dumps(TAG_CATEGORIES)}
"""
    res = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"contents": [{"parts": [{"text": prompt}]}]})
    )
    text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
    if text.startswith("```json"):
        text = text.strip("` \n").replace("json", "", 1).strip()
    parsed = json.loads(text)
    all_tags = sum([parsed.get(k, []) for k in TAG_CATEGORIES], [])
    return {
        "artist": parsed.get("artist", "Unknown"),
        "language": parsed.get("language", "english"),
        "tags": all_tags
    }

# Streamlit UI
st.title("🎵 YouTube Audio to pCloud + Supabase")
yt_url = st.text_input("Enter YouTube URL")

if st.button("Process") and yt_url:
    try:
        st.info("Downloading audio...")
        audio_stream, title, vid_id = download_audio_stream(yt_url)

        st.info("Downloading thumbnail...")
        thumb_stream = download_thumbnail_stream(vid_id)

        st.info("Uploading to pCloud...")
        song_folder = get_or_create_folder("songs_streamlit")
        img_folder = get_or_create_folder("imgs_streamlit")
        file_id = upload_file_stream(audio_stream, f"{title}.m4a", song_folder)
        img_id = upload_file_stream(thumb_stream, f"{title}.jpg", img_folder)

        st.info("Getting metadata from Gemini...")
        meta = get_tags_from_gemini(title)

        st.info("Inserting into Supabase...")
        supabase.table("songs").insert({
            "file_id": file_id,
            "img_id": img_id,
            "name": title,
            "artist": meta["artist"],
            "language": meta["language"],
            "tags": meta["tags"],
            "views": 0,
            "likes": 0
        }).execute()

        st.success(f"✅ Uploaded: {title}")
        st.write(f"**Artist:** {meta['artist']}")
        st.write(f"**Language:** {meta['language']}")
        st.write(f"**Tags:** {meta['tags']}")

    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
