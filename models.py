from pydantic import BaseModel
from typing import List, Optional, Literal

InputType = Literal['text', 'youtube', 'transcript']

#-----------------------------------------
# PROMPT MODELS

class Prompt(BaseModel):
    promptText: str
    
#-----------------------------------------
# USER MODELS
class User(BaseModel) :
    id: str
    email: str
    firstName: Optional[str]
    lastName: Optional[str]
    imageUrl: Optional[str]
    roles: Optional[List[str]]

#-----------------------------------------
# NODE WORKFLOW MODELS

class Position(BaseModel):
    x: float
    y: float

class NodeData(BaseModel):
    id: str
    name: str
    type: Optional[InputType] = 'text'
    inputValue: str
    promptValue: str
    resultValue: str
    position: Optional[Position]
    isMinimized: Optional[bool] = False
    selected: Optional[bool] = False
    parentId: Optional[str] = None

class Edge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    sourceHandle: Optional[str] = None
    targetHandle: Optional[str] = None
    
class Workflow(BaseModel):
    id: str
    name: str
    nodes: List[NodeData]
    edges: List[Edge]
    
#-----------------------------------------
# YOUTUBE MODELS
    
class YoutubeVideo(BaseModel):
    id: str
    transcript: Optional[str] = None

#-----------------------------------------
# CHAT MODELS

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    video_id: str
    conversation_history: List[Message]
    video_context: dict

class ChatMessageRecord(BaseModel):
    id: str
    userId: str
    videoId: str
    messages: List[Message]
    lastUpdated: int

#-----------------------------------------
# INSIGHTS MODELS

class VideoInsightMetadata(BaseModel):
    title: Optional[str]
    description: Optional[str] 
    channel_name: Optional[str]
    channel_url: Optional[str]
    publish_date: Optional[str]
    views: Optional[int]
    length_in_seconds: Optional[int]
    rating: Optional[float]
    keywords: Optional[List[str]]

class VideoInsightRecord(BaseModel):
    id: str
    userId: str
    videoId: str
    transcript: str
    summary: str
    insights: str
    starters: str
    metadata: VideoInsightMetadata
    timestamp: int

#-----------------------------------------
# HISTORY MODELS

class HistoryRecord(BaseModel):
    id: str
    userId: str
    videoId: str
    timestamp: int
    metadata: VideoInsightMetadata