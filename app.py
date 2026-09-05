from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from groq import Groq
import os
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================
# API KEYS
# =============================

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose"
]

# =============================
# AI AGENT SETTINGS
# =============================

agent_enabled = True

# Stores OAuth PKCE verifiers temporarily
oauth_states = {}

# Stores Gmail credentials while the server is running
gmail_credentials = None

# =============================
# AI SYSTEM INSTRUCTION
# =============================

SYSTEM_INSTRUCTION = """
You are an AI assistant representing the creator of this portfolio.

Your most important goal is to communicate naturally, like a real helpful
person having a normal conversation.

Do NOT sound robotic, overly formal, repetitive, or like you are reading
from a script.

NATURAL CONVERSATION:
- Respond naturally to what the person actually said.
- Pay attention to conversation history.
- Do not repeat information unnecessarily.
- Keep replies conversational and easy to read.
- Use casual language when the conversation is casual.
- Be polite and professional when the situation is professional.
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
- Only state information explicitly provided.
- Never assume that a technology mentioned in a project means the creator
  is skilled or experienced with it.
- Never add features, achievements, tools, or experiences that aren't
  explicitly mentioned.
- If information isn't provided, say:
  "I don't have that information in the project details I was given."

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

# =============================
# CHAT MODEL
# =============================

class ChatRequest(BaseModel):
    message: str
    conversation: list[dict] = []


# =============================
# GMAIL OAUTH
# =============================

@app.get("/gmail/auth")
def gmail_auth():

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=GMAIL_SCOPES
    )

    flow.redirect_uri = (
        "https://my-portfolio-bot-test-2.onrender.com/gmail/callback"
    )

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true"
    )

    oauth_states[state] = flow.code_verifier

    return {
        "authorization_url": authorization_url
    }


@app.get("/gmail/callback")
def gmail_callback(code: str, state: str):

    global gmail_credentials

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=GMAIL_SCOPES
    )

    flow.redirect_uri = (
        "https://my-portfolio-bot-test-2.onrender.com/gmail/callback"
    )

    code_verifier = oauth_states.pop(state, None)

    if not code_verifier:
        return {
            "error": "OAuth session expired or invalid state"
        }

    flow.code_verifier = code_verifier

    flow.fetch_token(code=code)

    gmail_credentials = flow.credentials

    # Send the user back to the control panel
    return RedirectResponse(
        url="https://email-agent-panel.onrender.com/"
    )


# =============================
# GMAIL STATUS
# =============================

@app.get("/gmail/status")
def gmail_status():

    return {
        "connected": gmail_credentials is not None
    }


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
# AGENT ON/OFF
# =============================

@app.post("/agent/on")
def turn_agent_on():

    global agent_enabled

    agent_enabled = True

    return {
        "agent_enabled": True,
        "message": "AI agent is ON"
    }


@app.post("/agent/off")
def turn_agent_off():

    global agent_enabled

    agent_enabled = False

    return {
        "agent_enabled": False,
        "message": "AI agent is OFF"
    }


@app.get("/agent/status")
def agent_status():

    return {
        "agent_enabled": agent_enabled
    }


# =============================
# AI CHAT
# =============================

@app.post("/chat")
def chat(request: ChatRequest):

    if not agent_enabled:

        return {
            "response": None,
            "agent_enabled": False,
            "message": "AI agent is currently OFF"
        }

    messages = [
        {
            "role": "system",
            "content": SYSTEM_INSTRUCTION
        }
    ]

    messages.extend(request.conversation)

    messages.append({
        "role": "user",
        "content": request.message
    })

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
