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

# =============================
# AI AGENT SETTINGS
# =============================

# True = AI is active
# False = AI is stopped
agent_enabled = True


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


# =============================
# HOME
# =============================

@app.get("/")
def home():
    return {
        "status": "AI agent backend is running!",
        "agent_enabled": agent_enabled
    }


# =============================
# TURN AGENT ON
# =============================

@app.post("/agent/on")
def turn_agent_on():
    global agent_enabled

    agent_enabled = True

    return {
        "agent_enabled": True,
        "message": "AI agent is ON"
    }


# =============================
# TURN AGENT OFF
# =============================

@app.post("/agent/off")
def turn_agent_off():
    global agent_enabled

    agent_enabled = False

    return {
        "agent_enabled": False,
        "message": "AI agent is OFF"
    }


# =============================
# CHECK AGENT STATUS
# =============================

@app.get("/agent/status")
def agent_status():
    return {
        "agent_enabled": agent_enabled
    }


# =============================
# CHAT
# =============================

@app.post("/chat")
def chat(request: ChatRequest):

    # Stop immediately if the agent is OFF
    if not agent_enabled:
        return {
            "response": None,
            "agent_enabled": False,
            "message": "AI agent is currently OFF"
        }

    # Start with the AI's instructions
    messages = [
        {
            "role": "system",
            "content": SYSTEM_INSTRUCTION
        }
    ]

    # Add previous conversation
    messages.extend(request.conversation)

    # Add newest message
    messages.append({
        "role": "user",
        "content": request.message
    })

    # Ask Groq
    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=messages,
        temperature=0.6,
        max_completion_tokens=1024,
    )

    response = completion.choices[0].message.content

    return {
        "response": response,
        "agent_enabled": True
    }
```
