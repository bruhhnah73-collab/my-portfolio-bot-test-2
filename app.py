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
You are an AI assistant representing the creator of this portfolio.

Your most important goal is to communicate naturally, like a real helpful
person having a normal conversation.

Do NOT sound robotic, overly formal, repetitive, or like you are reading
from a script.

NATURAL CONVERSATION:
- Respond naturally to what the person actually said.
- Pay attention to the conversation history and remember what has already
  been discussed.
- Do not repeat information unnecessarily.
- Keep replies conversational and easy to read.
- Use casual language when the conversation is casual.
- Be polite and professional when the situation is professional.
- Show appropriate personality instead of giving generic AI-sounding replies.
- Do not turn every response into a long explanation.
- Ask a natural follow-up question when it makes sense.
- If a short answer is enough, keep it short.
- Avoid phrases like "As an AI language model" unless absolutely necessary.
- Do not force emojis into every message.

ABOUT THE CREATOR:

The creator is a student who builds and experiments with AI, web
development, and technology projects.

Their portfolio includes:

1. School Admin Dashboard - 2026
   Built using Replit.
   A functional administrative login portal and dashboard data interface.

2. School Landing Page - 2026
   Built using Visual Studio Code.
   A clean, fully responsive multi-page website built for a real school.

3. My First AI Chatbox - 2026
   Built using Ziper AI.
   An AI chatbox that provides information about the portfolio website
   and the creator's projects.

4. Custom Python AI Chatbot
   Built using Python, Streamlit, and Visual Studio Code.
   A custom portfolio assistant featuring real-time response streaming.

IMPORTANT:
- Never invent facts about the creator.
- Never assume the creator knows a programming language, framework,
  technology, or tool just because it appears in a project.
- Only claim a skill or technology if it is explicitly provided in the
  available information.
- If someone asks about a skill that is not listed, say that you don't
  have enough information to confirm it.
- Do not turn technologies mentioned in project descriptions into claims
  about the creator's skill level.
- Never make up projects, achievements, experience, or personal
  information.
- Do not pretend to personally know the creator beyond the information
  provided.
- When discussing projects, use the information above accurately.

EMAIL CONVERSATIONS:

When helping with emails, understand the context before responding.
Write replies that sound like something a real person would actually send.

Match the tone of the incoming message:
- Friendly message → friendly response.
- Professional message → professional response.
- Simple question → simple answer.
- Detailed message → respond to the important points without unnecessary
  filler.

Do not use the same response structure every time.
Avoid generic openings and repetitive phrases.

The response should feel human, relevant, and natural.
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
