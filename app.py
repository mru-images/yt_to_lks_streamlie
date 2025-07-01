import streamlit as st
import os, requests, json, re
from io import BytesIO
from yt_dlp import YoutubeDL
from supabase import create_client, Client

# --- 🔐 HARDCODED CREDENTIALS ---
PCLOUD_AUTH_TOKEN = "fE93KkZMjhg7ZtHMudQY9CHj5m8MDH3CFxLEKsw1y"
SUPABASE_URL = "https://yssrurhhizdcmctxrxec.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
GEMINI_API_KEY = "AIzaSyCGcpIzYiPhFIB8YiQtZNmGYTUtXQCFOoE"

SONGS_FOLDER = "songs_test"
IMGS_FOLDER = "imgs_test"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- UTILS ---
def sanitize_title(title: str):
    return re.sub(r'[\\/*?:"<>|#]', '', title).strip()[:100]

def extract_video_id(url):
    if "youtu.be/" in url:
        return url.split("youtu.be/")[-1].split("?")[0]
    elif "watch?v=" in url:
        return url.split("watch?v=")[-1].split("&")[0]
    else:
        raise ValueError("Invalid YouTube URL")

def download_mp3_stream(url):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'outtmpl': '-',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
        }],
        'prefer_ffmpeg': True,
    }
    buffer = BytesIO()
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = sanitize_title(info.get("title", "downloaded_song"))
        stream_url = info["url"]
        r = requests.get(stream_url, stream=True)
        for chunk in r.iter_content(8192):
            buffer.write(chunk)
        buffer.seek(0)
    return buffer, title

def download_thumbnail_stream(video_id):
    for q in ["maxresdefault", "hqdefault", "mqdefault", "default"]:
        url = f"https://img.youtube.com/vi/{video_id}/{q}.jpg"
        res = requests.get(url)
        if res.status_code == 200:
            return BytesIO(res.content)
    raise Exception("Thumbnail not found")

def get_or_create_folder(folder_name):
    res = requests.get("https://api.pcloud.com/listfolder", params={"auth": PCLOUD_AUTH_TOKEN, "folderid": 0})
    for item in res.json().get("metadata", {}).get("contents", []):
        if item.get("isfolder") and item.get("name") == folder_name:
            return item["folderid"]
    res = requests.get("https://api.pcloud.com/createfolder", params={"auth": PCLOUD_AUTH_TOKEN, "name": folder_name, "folderid": 0})
    return res.json()["metadata"]["folderid"]

def upload_file_stream(file_stream, filename, folder_id):
    res = requests.post(
        "https://api.pcloud.com/uploadfile",
        params={"auth": PCLOUD_AUTH_TOKEN, "folderid": folder_id},
        files={"file": (filename, file_stream)}
    )
    return res.json()["metadata"][0]["fileid"]

def get_tags_from_gemini(song_name):
    PREDEFINED_TAGS = {
        "genre": ["pop", "rock", "hiphop", "rap", "r&b"],
        "mood": ["happy", "sad", "romantic", "chill", "energetic"],
        "occasion": ["party", "study", "sleep"],
        "era": ["2000s", "2010s", "2020s"],
        "vocal_instrument": ["female_vocals", "male_vocals", "instrumental_only"]
    }
    prompt = f"""
Given the song name "{song_name}", identify its primary artist and language.
Then, suggest tags from these predefined categories only.
Format:
{{
  "artist": "...", "language": "...",
  "genre": [...], "mood": [...],
  "occasion": [...], "era": [...], "vocal_instrument": [...]
}}
Predefined:
{json.dumps(PREDEFINED_TAGS, indent=2)}
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
    tags = []
    for k in ["genre", "mood", "occasion", "era", "vocal_instrument"]:
        tags += parsed.get(k, [])
    return {
        "artist": parsed.get("artist", "Unknown"),
        "language": parsed.get("language", "english"),
        "tags": tags
    }

# --- STREAMLIT APP ---
st.title("🎵 YouTube to pCloud Music Uploader")

url = st.text_input("Enter YouTube URL:")

if st.button("Process"):
    try:
        with st.spinner("Downloading..."):
            video_id = extract_video_id(url)
            mp3_stream, title = download_mp3_stream(url)
            thumb_stream = download_thumbnail_stream(video_id)

        with st.spinner("Uploading..."):
            song_folder_id = get_or_create_folder(SONGS_FOLDER)
            img_folder_id = get_or_create_folder(IMGS_FOLDER)
            file_id = upload_file_stream(mp3_stream, f"{title}.mp3", song_folder_id)
            img_id = upload_file_stream(thumb_stream, f"{title}.jpg", img_folder_id)

        with st.spinner("Publishing..."):
            meta = get_tags_from_gemini(title)
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

        st.success("✅ Song uploaded and inserted successfully!")
        st.write("**Title:**", title)
        st.write("**Artist:**", meta["artist"])
        st.write("**Tags:**", meta["tags"])
    except Exception as e:
        st.error(f"❌ Error: {e}")
