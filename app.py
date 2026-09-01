import os
import re
import uuid
import asyncio
import smtplib
import requests
from email.message import EmailMessage
from flask import Flask, request, jsonify, send_from_directory, render_template
from groq import Groq
import edge_tts

app = Flask(__name__)

groq_client = Groq()  # reads GROQ_API_KEY from environment

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")

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


def send_email(subject, body, attachment_path=None):

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Max <{GMAIL_ADDRESS}>"
    msg["To"] = GMAIL_ADDRESS
    msg.set_content(body)

    if attachment_path and os.path.isfile(attachment_path):
        with open(attachment_path, "rb") as f:
            file_data = f.read()
            file_name = os.path.basename(attachment_path)
        msg.add_attachment(file_data, maintype="application", subtype="octet-stream", filename=file_name)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as error:
        print(f"EMAIL ERROR: {error}")
        return False


def generate_image(prompt):

    url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}"

    try:
        response = requests.get(url, timeout=30)

        if response.status_code != 200:
            return None

        image_path = os.path.join(AUDIO_DIR, f"max_image_{uuid.uuid4().hex}.jpg")

        with open(image_path, "wb") as f:
            f.write(response.content)

        return image_path

    except Exception as error:
        print(f"IMAGE GEN ERROR: {error}")
        return None


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    global conversation_history

    user_message = request.json.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    lower_message = user_message.lower().strip()

    # =========================
    # EMAIL AN IMAGE
    # =========================

    image_email_match = re.match(r"e[\-\s]?mail me an? image of (.+)", lower_message, re.IGNORECASE)

    if image_email_match:
        prompt = image_email_match.group(1).strip()

        image_path = generate_image(prompt)

        if not image_path:
            reply = "I couldn't generate that image, sorry."
        else:
            sent = send_email("Image from Max", f"Here's the image you asked for: {prompt}", attachment_path=image_path)
            reply = "Sent it, check your inbox." if sent else "Generated it, but couldn't send the email."

        speech_text = clean_for_speech(reply)
        audio_filename = f"{uuid.uuid4().hex}.mp3"
        audio_path = os.path.join(AUDIO_DIR, audio_filename)
        asyncio.run(generate_speech(speech_text, audio_path))

        return jsonify({"reply": reply, "audio_url": f"/audio/{audio_filename}"})

    # =========================
    # EMAIL PLAIN TEXT
    # =========================

    email_match = re.match(r"e[\-\s]?mail me (.+)", lower_message, re.IGNORECASE)

    if email_match:
        message_body = email_match.group(1).strip()
        sent = send_email("Update from Max", message_body)
        reply = "Sent it, check your inbox." if sent else "Something went wrong sending that."

        speech_text = clean_for_speech(reply)
        audio_filename = f"{uuid.uuid4().hex}.mp3"
        audio_path = os.path.join(AUDIO_DIR, audio_filename)
        asyncio.run(generate_speech(speech_text, audio_path))

        return jsonify({"reply": reply, "audio_url": f"/audio/{audio_filename}"})

    # =========================
    # NORMAL CONVERSATION
    # =========================

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