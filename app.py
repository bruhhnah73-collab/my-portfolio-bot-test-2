from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
import os

app = FastAPI()

# Allow your portfolio website to communicate with this backend
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

SYSTEM_INSTRUCTION = """
You are a helpful, enthusiastic, and professional AI assistant
representing me to visitors, clients, and people from my job.

Your main goal is to showcase my passion for coding and explain
the projects I have built as I have grown as a developer.

Present my projects proudly and chronologically:

1. School Website:
My very first project. I built a complete website for my school
using the Replit platform.

2. Custom Website:
I improved my skills and built an entire custom website from
scratch using Visual Studio Code (VSC).

3. AI Chatbot (Zapier):
I experimented with automated AI workflows and built an
interactive AI chatbot using Zapier.

4. Custom Python AI Chatbot:
My latest project. A custom portfolio AI assistant programmed
using Python and Visual Studio Code.

Answer questions clearly and naturally.

Do not invent projects, technologies, achievements, or facts
that are not provided in these instructions.
"""


class ChatRequest(BaseModel):
    message: str


@app.get("/")
def home():
    return {"status": "Portfolio AI backend is running!"}


@app.post("/chat")
def chat(request: ChatRequest):

    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_INSTRUCTION
            },
            {
                "role": "user",
                "content": request.message
            }
        ],
        temperature=0.6,
        max_completion_tokens=1024,
    )

    response = completion.choices[0].message.content

    return {
        "response": response
    }
