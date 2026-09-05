```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
import os

app = FastAPI()

# Allow your frontend to communicate with this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get Groq API key securely
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)

# AI instructions
SYSTEM_INSTRUCTION = """
You are an AI assistant that responds naturally and appropriately
to messages in an ongoing conversation.

Read the previous messages carefully so that your response fits
the conversation and does not feel random or disconnected.

Keep responses natural and conversational.

Do not invent facts about the person you are representing.
If you do not know something, do not make it up.
"""


class ChatRequest(BaseModel):
    message: str
    conversation: list[dict] = []


@app.get("/")
def home():
    return {
        "status": "AI agent backend is running!"
    }


@app.post("/chat")
def chat(request: ChatRequest):

    # Start with the AI's instructions
    messages = [
        {
            "role": "system",
            "content": SYSTEM_INSTRUCTION
        }
    ]

    # Add previous conversation
    messages.extend(request.conversation)

    # Add the newest message
    messages.append({
        "role": "user",
        "content": request.message
    })

    # Ask the AI for a response
    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=messages,
        temperature=0.6,
        max_completion_tokens=1024,
    )

    response = completion.choices[0].message.content

    return {
        "response": response
    }
```
