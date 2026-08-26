"""Subida real a YouTube (videos.insert), resumable -- importante para
vídeos de varios cientos de MB, para poder reportar progreso real en vez
de todo-o-nada."""
from typing import Callable, Optional


def upload_video(
    creds, file_path: str, title: str, description: str = "",
    privacy_status: str = "private", progress_cb: Optional[Callable[[float], None]] = None,
) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {"title": title, "description": description},
        "status": {"privacyStatus": privacy_status},
    }
    media = MediaFileUpload(file_path, chunksize=4 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and progress_cb:
            progress_cb(status.progress())

    return response["id"]
