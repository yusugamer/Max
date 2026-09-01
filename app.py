import os
import re
import uuid
import asyncio
from flask import Flask, request, jsonify, send_from_directory, render_template
from groq import Groq
import edge_tts

app = Flask(__name__)

groq_client = Groq()  # reads GROQ_API_KEY from environment

AUDIO_DIR = "audio_cache"
os.makedirs(AUDIO_DIR, exist_ok=True)

SYSTEM_PROMPT = (
    "Your name is Max. You're Janabi's friend and go-to guy for anything "
    "he needs help with — coding, ideas, random questions, whatever. "
    "Talk like a real person texting a friend, not like a customer service bot. "
    "Keep it casual and natural. No corporate phrasing, no 'as an AI'. "
    "Keep replies short unless the topic actually needs more detail. "
    "Do not use emojis."
)

# Simple in-memory conversation history (resets if the server restarts/sleeps)
conversation_history = []


async def generate_speech(text, path):
    communicate = edge_tts.Communicate(text, voice="en-US-GuyNeural")
    await communicate.save(path)


def clean_for_speech(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"[*_`#]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    global conversation_history

    user_message = request.json.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(conversation_history[-10:])  # last 5 exchanges
    messages.append({"role": "user", "content": user_message})

    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=messages
    )

    reply = response.choices[0].message.content

    conversation_history.append({"role": "user", "content": user_message})
    conversation_history.append({"role": "assistant", "content": reply})

    speech_text = clean_for_speech(reply)
    audio_filename = f"{uuid.uuid4().hex}.mp3"
    audio_path = os.path.join(AUDIO_DIR, audio_filename)

    asyncio.run(generate_speech(speech_text, audio_path))

    return jsonify({
        "reply": reply,
        "audio_url": f"/audio/{audio_filename}"
    })


@app.route("/audio/<filename>")
def get_audio(filename):
    return send_from_directory(AUDIO_DIR, filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)