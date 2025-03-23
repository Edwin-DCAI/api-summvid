
from promptflow import tool


# The inputs section will change based on the arguments of the tool function, after you save the code
# Adding type to arguments and return value will help the system show the types properly
# Please update the function name/signature per need
@tool
def create_prompt(user_message: str, conversation_history: list, transcript: str, summary: str, insights: str):
    # Create system prompt
    system_content = f'''You are an AI assistant helping users understand a video.
        Here is the context about the video:

        Transcript:
        {transcript}

        Summary:
        {summary}

        Key Insights:
        {insights}

        Answer questions based on this context. If asked about something not covered in the video, politely explain that you can only answer questions about the video's content.'''

    # Create messages array for the API
    messages = [
        {
            "role": "system",
            "content": system_content
        }
    ]
    
    # Add conversation history
    for msg in conversation_history:
        messages.append({
            "role": msg["role"],
            "content": msg["content"]
        })
    
    # Add the new user message
    messages.append({
        "role": "user",
        "content": user_message
    })
    
    return messages