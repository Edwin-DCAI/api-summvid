from promptflow import tool
from fastapi import FastAPI, HTTPException
from yt_dlp import YoutubeDL

@tool
def get_youtube_metadata(youtube_id: str) -> dict:
    """
    Retrieves basic metadata for the specified YouTube video using yt-dlp.
    Returns a dict with title, description, channel name, publish date, etc.
    """
    try:
        # Clean up video ID from any additional parameters
        clean_id = youtube_id.split('&')[0]
        
        # Construct the full YouTube URL
        youtube_url = f"https://www.youtube.com/watch?v={clean_id}"

        # Configure yt-dlp options
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
        }
        
        # Create YoutubeDL object and extract info
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            
            # Build a dictionary of metadata matching your original structure
            metadata = {
                "title": info.get('title'),
                "description": info.get('description'),
                "channel_name": info.get('uploader'),
                "channel_url": info.get('uploader_url'),
                "publish_date": info.get('upload_date'),  # Format: YYYYMMDD
                "views": info.get('view_count'),
                "length_in_seconds": info.get('duration'),
                "rating": info.get('average_rating'),
                "keywords": info.get('tags', [])
            }
            
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch metadata: {str(e)}"
        )
    
    return metadata