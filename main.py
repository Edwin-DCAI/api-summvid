import json
import os
import uuid
from pathlib import Path

from datetime import datetime, timedelta
from typing import AsyncGenerator, Optional, List, Dict, Any
from dotenv import load_dotenv

from fastapi import Depends, FastAPI, HTTPException, Header, Request, Security
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials

import jwt
from promptflow.core import Prompty
from promptflow.client import PFClient
from azure.cosmos import CosmosClient, PartitionKey

from rich import _console
from youtube_transcript_api import YouTubeTranscriptApi
from models import ChatMessageRecord, ChatRequest, HistoryRecord, Message, Prompt, VideoInsightRecord, YoutubeVideo

from auth import AuthMiddleware
auth_handler = AuthMiddleware()

from promptflow.entities import AzureOpenAIConnection

# ---------------------------------------------------------------------------------
# Load Environment Variables
# ---------------------------------------------------------------------------------

# Load from .env unless we're in Docker/Azure (example flags)
#  - You can set RUNNING_IN_DOCKER=1 in your Dockerfile,
#  - RUNNING_IN_AZURE=1 in Azure App Service or Container Apps settings.
if not (os.getenv("RUNNING_IN_DOCKER") or os.getenv("RUNNING_IN_AZURE")):
    load_dotenv()  # loads .env in local development

# ---------------------------------------------------------------------------------
# Create Prompt Flow Client
# ---------------------------------------------------------------------------------

# Initialize the Prompt Flow client
pf_client = PFClient()

# Initialize an AzureOpenAIConnection object
connection = AzureOpenAIConnection(
    name="dcai-aoai-connection",
    api_key=os.getenv("PF_AZURE_OPENAI_API_KEY"),
    api_base=os.getenv("PF_AZURE_OPENAI_ENDPOINT"),
)

# Create the connection, note that api_key will be scrubbed in the returned result
result = pf_client.connections.create_or_update(connection)
print(result)


# ---------------------------------------------------------------------------------
# COSMOS DB CONFIGURATION
# ---------------------------------------------------------------------------------

# Cosmos DB Configuration remains the same
COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT")
COSMOS_KEY = os.getenv("COSMOS_KEY")
COSMOS_DATABASE = os.getenv("COSMOS_DATABASE")
# COSMOS_CONTAINER = os.getenv("COSMOS_CONTAINER")

# Initialize Cosmos DB client (unchanged)
client = CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)
database = client.create_database_if_not_exists(id=COSMOS_DATABASE)

# ---------------------------------------------------------------------------------
# FAST API AND ORIGIN CONFIGURATION
# ---------------------------------------------------------------------------------

if (os.getenv("FORCE_ALL_ORIGINS")):
    # Fallback to all
    origins = ["*"]
else:
    origins_file_path = Path(__file__).parent / "origins.txt"
    if origins_file_path.exists():
        # Each line in origins.txt is a separate allowed origin
        origins = [
            o.strip()
            for o in origins_file_path.read_text().splitlines()
            if o.strip()
        ]
    else:
        # Fallback to all
        origins = ["*"]

# Update your FastAPI app configuration to include security schemes
app = FastAPI(
    title="DataChef AI SummVid API",
    description="DataChef AI SummVid API for video insights and chat",
    version="1.0.0",
    # openapi_tags=[{"name": "api", "description": "API endpoints"}],
    swagger_ui_init_oauth={
        "usePkceWithAuthorizationCodeGrant": True,
    }
)

# CORS configuration remains the same
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add security schemes to OpenAPI
app.swagger_ui_init_oauth = {
    "usePkceWithAuthorizationCodeGrant": True
}

# Add middleware configuration
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# ---------------------------------------------------------------------------------
# SECURITY SCHEMES AND DEPENDENCIES
# ---------------------------------------------------------------------------------

# Define security schemes
api_key_header = APIKeyHeader(name="x-api-key", auto_error=True)
bearer_scheme = HTTPBearer()

# Security dependency
async def get_api_key(api_key: str = Security(api_key_header)):
    if api_key != os.getenv("FRONTEND_API_KEY"):
        raise HTTPException(
            status_code=403,
            detail="Could not validate API key"
        )
    return api_key

async def get_bearer_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    # Your JWT validation logic here
    return credentials.credentials

# ---------------------------------------------------------------------------------
# AUTHENTICATION ENDPOINT
# ---------------------------------------------------------------------------------

# Add this to your existing FastAPI app
@app.post("/auth/token")
async def get_service_token(x_api_key: Optional[str] = Header(None)):
    if x_api_key != os.getenv("FRONTEND_API_KEY"):
        raise HTTPException(
            status_code=403,
            detail="Invalid API key"
        )
    
    # Generate JWT token
    expiration = datetime.utcnow() + timedelta(hours=24)  # Token valid for 24 hours
    token_data = {
        "sub": "frontend-service",
        "exp": expiration
    }
    
    token = jwt.encode(
        token_data,
        os.getenv("JWT_SECRET_KEY"),
        algorithm="HS256"
    )
    
    return {"token": token}

# ---------------------------------------------------------------------------------
# PROMPT FLOW ENDPOINT
# ---------------------------------------------------------------------------------


@app.post("/prompt/")
async def root(prompt: Prompt, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    f = Prompty.load(source="./agents/prompt/chat.prompty")

    # execute the flow as function
    result = f(question=prompt.promptText)   
    return {"message": result}

# ---------------------------------------------------------------------------------
# YOUTUBE API ENDPOINTS
# ---------------------------------------------------------------------------------

youtube_container = database.create_container_if_not_exists(
    id='youtube_videos', 
    partition_key=PartitionKey(path="/id")
)
 
@app.get("/youtube_transcript/{youtube_id}")
async def get_youtube_transcript(youtube_id: str, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    try:
        # Clean up video ID from any additional parameters
        clean_id = youtube_id.split('&')[0]
        transcript = YouTubeTranscriptApi.get_transcript(clean_id)
        result = " ".join(i['text'] for i in transcript)
        return {"transcript": result}  # Changed to match frontend expectations
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch transcript: {str(e)}"
        )

@app.post("/youtube_videos/", response_model=YoutubeVideo)
async def create_youtube_video(video: YoutubeVideo, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    youtube_container.create_item(body=video.dict())
    return video

@app.get("/youtube_videos/", response_model=List[YoutubeVideo])
async def list_youtube_videos(dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    query = "SELECT * FROM c"
    items = list(youtube_container.query_items(query=query, enable_cross_partition_query=True))
    return items

@app.delete("/youtube_videos/{video_id}")
async def delete_youtube_video(video_id: str, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    youtube_container.delete_item(item=video_id, partition_key=video_id)
    return {"message": "Video deleted"}

# ---------------------------------------------------------------------------------
# INSIGHTS ENDPOINTS
# ---------------------------------------------------------------------------------

insights_container = database.create_container_if_not_exists(
    id='insights',
    partition_key=PartitionKey(path="/userId"),
    offer_throughput=1000
)

@app.get("/get-video-insights/{youtube_id}")
async def get_video_insights(youtube_id: str, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]) -> Dict[str, Any]:
    """
    Get insights from a YouTube video using Prompt Flow.
    
    Args:
        youtube_id: The YouTube video ID
        
    Returns:
        Dict containing the analysis results
    """
    try:
        # Clean up video ID from any additional parameters
        clean_id = youtube_id.split('&')[0]

        # Get video transcript
        try:
            transcript = YouTubeTranscriptApi.get_transcript(clean_id)
            text = " ".join(i['text'] for i in transcript)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to fetch video transcript: {str(e)}"
            )

        # Define flow path
        flow_path = os.path.join("prompts", "get-video-insights")
        
        # Validate flow exists
        if not os.path.exists(os.path.join(flow_path, "flow.dag.yaml")):
            raise HTTPException(
                status_code=404,
                detail=f"Prompt flow configuration not found"
            )

        # Run the flow
        try:
            result = pf_client.test(
                flow=flow_path,
                inputs={
                    "youtube_id": clean_id,
                    "transcript": text
                }
            )
            
            # Extract outputs from the run
            if hasattr(result, 'outputs'):
                outputs = result.outputs
            else:
                outputs = result  # Some versions return the outputs directly
                
            return {
                "status": "success",
                "video_id": clean_id,
                "insights": outputs
            }
            
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process video insights: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}"
        )


@app.post("/insights/", response_model=VideoInsightRecord)
async def create_insight(insight: VideoInsightRecord, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    try:
        insights_container.create_item(body=insight.dict())
        return insight
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/insights/{video_id}")
async def get_insight(video_id: str, user_id: str, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    try:
        query = f"SELECT * FROM c WHERE c.videoId = '{video_id}' AND c.userId = '{user_id}'"
        items = list(insights_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        if items:
            return items[0]
        raise HTTPException(status_code=404, detail="Insight not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------------
# CHAT ENDPOINTS
# ---------------------------------------------------------------------------------

chat_container = database.create_container_if_not_exists(
    id='chat',
    partition_key=PartitionKey(path="/userId"),
    offer_throughput=1000
)

async def chat_stream(prompt_flow_response) -> AsyncGenerator[str, None]:
    """Convert prompt flow response to streaming format"""
    # Handle the prompt flow response
    if hasattr(prompt_flow_response, 'answer'):
        # If it's a single response
        yield f"data: {json.dumps({'text': prompt_flow_response.answer})}\n\n"
    elif isinstance(prompt_flow_response, dict) and 'answer' in prompt_flow_response:
        # If it's a dictionary with answer key
        yield f"data: {json.dumps({'text': prompt_flow_response['answer']})}\n\n"
    elif isinstance(prompt_flow_response, str):
        # If it's a plain string
        yield f"data: {json.dumps({'text': prompt_flow_response})}\n\n"
    else:
        # For any other format, try to get the content
        content = str(prompt_flow_response)
        yield f"data: {json.dumps({'text': content})}\n\n"
    
    yield "data: [DONE]\n\n"

@app.post("/chat")
async def chat(request: ChatRequest, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    try:
        # Define flow path for chat
        flow_path = os.path.join("prompts", "video-chat")
        
        # Prepare the input for prompt flow
        flow_inputs = {
            "user_message": request.message,
            "video_id": request.video_id,
            "conversation_history": [msg.dict() for msg in request.conversation_history],
            "transcript": request.video_context.get("transcript", ""),
            "summary": request.video_context.get("summary", ""),
            "insights": request.video_context.get("insights", "")
        }

        # Run the flow
        try:
            # Initialize streaming response
            result = pf_client.test(
                flow=flow_path,
                inputs=flow_inputs
            )
            
            # Debug: Print the result format
            print("Prompt flow result type:", type(result))
            print("Prompt flow result:", result)
            
            # If result has outputs attribute, use it
            if hasattr(result, 'outputs'):
                result_stream = result.outputs
            else:
                result_stream = result
            
            return StreamingResponse(
                chat_stream(result_stream), 
                media_type="text/event-stream"
            )
            
        except Exception as e:
            print(f"Error in chat processing: {str(e)}")  # Debug print
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process chat: {str(e)}"
            )

    except Exception as e:
        print(f"Unexpected error: {str(e)}")  # Debug print
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}"
        )


@app.post("/chat/", response_model=ChatMessageRecord)
async def create_chat(chat: ChatMessageRecord, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    try:
        chat_container.create_item(body=chat.dict())
        return chat
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/chat/{video_id}")
async def get_chat(video_id: str, user_id: str, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    try:
        query = f"SELECT * FROM c WHERE c.videoId = '{video_id}' AND c.userId = '{user_id}'"
        items = list(chat_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        if items:
            return items[0]
        return {"messages": []}  # Return empty messages array if no chat found
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/{video_id}/messages")
async def add_chat_message(video_id: str, message: Message, user_id: str, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    try:
        query = f"SELECT * FROM c WHERE c.videoId = '{video_id}' AND c.userId = '{user_id}'"
        items = list(chat_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        
        if items:
            # Update existing chat
            chat = items[0]
            chat['messages'].append(message.dict())
            chat['lastUpdated'] = int(datetime.now().timestamp())
            chat_container.replace_item(item=chat['id'], body=chat)
            return chat
        else:
            # Create new chat
            new_chat = ChatMessageRecord(
                id=str(uuid.uuid4()),
                userId=user_id,
                videoId=video_id,
                messages=[message.dict()],
                lastUpdated=int(datetime.now().timestamp())
            )
            chat_container.create_item(body=new_chat.dict())
            return new_chat
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/chat/{video_id}/messages/last")
async def update_last_message(video_id: str, user_id: str, content: dict, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    try:
        # Get the current chat
        query = f"SELECT * FROM c WHERE c.videoId = '{video_id}' AND c.userId = '{user_id}'"
        items = list(chat_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        
        if not items:
            raise HTTPException(status_code=404, detail="Chat not found")
            
        chat = items[0]
        
        if not chat['messages']:
            raise HTTPException(status_code=400, detail="No messages to update")
            
        # Update the last message's content
        chat['messages'][-1]['content'] = content['content']
        chat['lastUpdated'] = int(datetime.now().timestamp())
        
        # Update in database
        chat_container.replace_item(item=chat['id'], body=chat)
        
        return chat
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------------
# HISTORY ENDPOINTS
# ---------------------------------------------------------------------------------

history_container = database.create_container_if_not_exists(
    id='history',
    partition_key=PartitionKey(path="/userId"),
    offer_throughput=1000
)

@app.post("/history/", response_model=HistoryRecord)
async def create_history(history: HistoryRecord, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    try:
        history_container.create_item(body=history.dict())
        return history
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history/")
async def get_history(user_id: str, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    try:
        query = f"SELECT * FROM c WHERE c.userId = '{user_id}' ORDER BY c.timestamp DESC"
        items = list(history_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        return items
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# Add these to main.py after the existing history endpoints

@app.delete("/history/")
async def clear_history(user_id: str, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    try:
        # Delete all history entries for the user
        query = f"SELECT * FROM c WHERE c.userId = '{user_id}'"
        items = list(history_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        
        for item in items:
            history_container.delete_item(
                item=item['id'],
                partition_key=user_id
            )
            
        return {"message": "History cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Update the existing create_history endpoint
@app.post("/history/", response_model=HistoryRecord)
async def create_history(history: HistoryRecord, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    try:
        # Check if entry already exists
        query = f"SELECT * FROM c WHERE c.videoId = '{history.videoId}' AND c.userId = '{history.userId}'"
        items = list(history_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        
        if items:
            # Update existing entry
            existing_item = items[0]
            existing_item['timestamp'] = history.timestamp
            existing_item['metadata'] = history.metadata.dict()
            history_container.replace_item(
                item=existing_item['id'],
                body=existing_item
            )
            return HistoryRecord(**existing_item)
        
        # Create new entry
        history_container.create_item(body=history.dict())
        return history
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Update the existing get_history endpoint
@app.get("/history/", response_model=List[HistoryRecord])
async def get_history(user_id: str, limit: int = 50, dependencies=[Depends(get_api_key), Depends(get_bearer_token)]):
    try:
        query = f"SELECT TOP {limit} * FROM c WHERE c.userId = '{user_id}' ORDER BY c.timestamp DESC"
        items = list(history_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        return items
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
