import re
import subprocess
import yt_dlp


# Read links
with open("links.txt", encoding="utf-8") as file:
    text = file.read()


# Extract and remove duplicate YouTube links
links = re.findall(
    r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[^\s]+",
    text
)

links = list(dict.fromkeys(links))

print(f"Found {len(links)} unique YouTube links.")


# Brave must be closed because it locks the cookie database
input(
    "Save your open Brave tabs, then press Enter "
    "to close Brave and start downloading..."
)



options = {
    "format": "bestaudio/best",
    "cookiesfrombrowser": ("brave",),
    "sleep_interval": 5,
    "max_sleep_interval": 10,
    "ignoreerrors": True,
    "retries": 5,
    "noplaylist": True,
    "outtmpl": "songs/%(title)s.%(ext)s",
}


with yt_dlp.YoutubeDL(options) as ydl:
    ydl.download(links)