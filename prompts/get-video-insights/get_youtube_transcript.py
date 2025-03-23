
from promptflow import tool
from youtube_transcript_api import YouTubeTranscriptApi
from fastapi import FastAPI, HTTPException

# The inputs section will change based on the arguments of the tool function, after you save the code
# Adding type to arguments and return value will help the system show the types properly
# Please update the function name/signature per need
@tool
def get_youtube_transcript(youtube_id: str) -> str:
    try:
        # Clean up video ID from any additional parameters
        clean_id = youtube_id.split('&')[0]
        transcript = YouTubeTranscriptApi.get_transcript(clean_id)
        result = " ".join(i['text'] for i in transcript)
        # transcript = {"transcript": result}  # Changed to match frontend expectations
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch transcript: {str(e)}"
        )
        
    return result
