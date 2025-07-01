import streamlit as st
import requests
import json
import re
from io import BytesIO
from supabase import create_client

# --- 🔐 HARDCODED CREDENTIALS (for testing only) ---
PCLOUD_AUTH_TOKEN = "fE93KkZMjhg7ZtHMudQY9CHj5m8MDH3CFxLEKsw1y"
SUPABASE_URL = "https://yssrurhhizdcmctxrxec.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inlzc3J1cmhoaXpkY21jdHhyeGVjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTEyOTUzNTUsImV4cCI6MjA2Njg3MTM1NX0.h3x6OjrCWKaKR7CHNfA7dl_bnmmMj6AmmNWhWW6mpo4"
GEMINI_API_KEY = "AIzaSyCGcpIzYiPhFIB8YiQtZNmGYTUtXQCFOoE"
RAPIDAPI_HOST = "youtube-mp36.p.rapidapi.com"
RAPIDAPI_KEY = "0204f09445msh6e8d74df8ff070bp1b4c6ejsn8a38abc65dfc"

SONGS_FOLDER = "songs_test"
IMGS_FOLDER = "imgs_test"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Utility Functions ---
def extract_video_id(url: str):
    if "youtu.be/" in url:
        return url.split("youtu.be/")[-1].split("?")[0]
    elif "watch?v=" in url:
        return url.split("watch?v=")[-1].split("&")[0]
    else:
        raise ValueError("Invalid YouTube URL")

def sanitize_title(title: str):
    return re.sub(r'[\\/*?:"<>|#]', '', title)[:100].strip()

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

def download_mp3_stream(download_url):
    response = requests.get(download_url, stream=True, allow_redirects=True)
    if response.status_code != 200 or 'audio' not in response.headers.get("Content-Type", ""):
        raise Exception("Invalid MP3 content received.")
    buffer = BytesIO()
    for chunk in response.iter_content(chunk_size=8192):
        if chunk:
            buffer.write(chunk)
    buffer.seek(0)
    return buffer

def download_thumbnail_stream(video_id):
    for quality in ["maxresdefault", "hqdefault", "mqdefault", "default"]:
        url = f"https://img.youtube.com/vi/{video_id}/{quality}.jpg"
        res = requests.get(url)
        if res.status_code == 200:
            return BytesIO(res.content)
    raise Exception("Thumbnail not found.")

def get_tags_from_gemini(song_name):
    PREDEFINED_TAGS = {
        "genre": ["pop", "rock", "hiphop", "edm"],
        "mood": ["happy", "sad", "chill"],
        "occasion": ["party", "study", "sleep"],
        "era": ["2000s", "2010s", "2020s"],
        "vocal_instrument": ["male_vocals", "female_vocals", "instrumental"]
    }
    prompt = f"""
Given the song name "{song_name}", identify its primary artist and language.
Then suggest appropriate tags from the predefined categories.
Only use tags from the following:
{json.dumps(PREDEFINED_TAGS, indent=2)}

Respond in JSON:
{{
  "artist": "Artist Name",
  "language": "Language",
  "genre": [...],
  "mood": [...],
  "occasion": [...],
  "era": [...],
  "vocal_instrument": [...]
}}
"""
    res = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"contents": [{"parts": [{"text": prompt}]}]})
    )
    if res.status_code != 200:
        raise Exception("Gemini API failed.")
    text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
    if text.startswith("```json"):
        text = text.strip("` \n").replace("json", "", 1).strip()
    parsed = json.loads(text)
    tags = []
    for key in ["genre", "mood", "occasion", "era", "vocal_instrument"]:
        tags += parsed.get(key, [])
    return {
        "artist": parsed.get("artist", "Unknown"),
        "language": parsed.get("language", "english"),
        "tags": tags
    }

# --- Streamlit UI ---
st.title("🎵 YouTube to pCloud Uploader (Test Version)")

yt_url = st.text_input("Enter YouTube URL")
submit = st.button("Process Song")

if submit and yt_url:
    try:
        with st.spinner("Processing..."):
            video_id = extract_video_id(yt_url)

            # Get audio link
            rapid = requests.get(
                f"https://{RAPIDAPI_HOST}/dl",
                headers={"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": RAPIDAPI_HOST},
                params={"id": video_id}
            ).json()

            title_raw = rapid.get("title", "downloaded_song")
            title = sanitize_title(title_raw)
            download_url = rapid.get("link")
            if not download_url:
                raise Exception("MP3 link not found.")

            mp3_stream = download_mp3_stream(download_url)
            thumb_stream = download_thumbnail_stream(video_id)

            song_folder_id = get_or_create_folder(SONGS_FOLDER)
            img_folder_id = get_or_create_folder(IMGS_FOLDER)
            file_id = upload_file_stream(mp3_stream, f"{title}.mp3", song_folder_id)
            img_id = upload_file_stream(thumb_stream, f"{title}.jpg", img_folder_id)

            pub = requests.get("https://api.pcloud.com/getfilepublink", params={"auth": PCLOUD_AUTH_TOKEN, "fileid": file_id}).json()
            pub_img = requests.get("https://api.pcloud.com/getfilepublink", params={"auth": PCLOUD_AUTH_TOKEN, "fileid": img_id}).json()

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

            # Show output
            st.success("✅ Song processed and uploaded!")
            st.markdown(f"**Name:** {title}")
            st.markdown(f"**Artist:** {meta['artist']}")
            st.markdown(f"**Language:** {meta['language']}")
            st.markdown(f"**Tags:** {', '.join(meta['tags'])}")
            st.markdown(f"[🔗 MP3 Public Link]({pub['link']})")
            st.image(pub_img["link"], caption="Thumbnail")

    except Exception as e:
        st.error(f"❌ Error: {e}")
