import mysql.connector
import requests
import wikipedia
import pyttsx3
import speech_recognition as sr
from config import GROQ_API_KEY, GROQ_MODEL

from config import HOST, USER, PASSWORD, DATABASE

def get_db_connection():
    return mysql.connector.connect(
        host=HOST,
        user=USER,
        password=PASSWORD,
        database=DATABASE
    )

# Text-to-speech engine
engine = pyttsx3.init()

def speak(text):
    print("Irus:", text)
    engine.say(text)
    engine.runAndWait()

def save_to_history(user_id, question, answer):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        sql = "INSERT INTO conversation_history (user_id, user_message, assistant_response) VALUES (%s, %s, %s)"
        cursor.execute(sql, (user_id, question, answer))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[DB ERROR] {e}")

# Call Groq API
def ask_groq(prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"Groq error: {e}"

# Get answer (Wikipedia → fallback to Groq)
def get_answer(query):
    try:
        return wikipedia.summary(query, sentences=2)
    except:
        return ask_groq(query)

# Listen from mic
def listen():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("\n🎙️ Listening...")
        audio = recognizer.listen(source)
    try:
        command = recognizer.recognize_google(audio)
        print("You:", command)
        return command
    except:
        speak("Sorry, I couldn't hear that.")
        return ""

# Main loop
if __name__ == "__main__":
    user_id = 1  # Later replace with real session user_id
    speak("Hello! I am Irus. How can I assist you?")
    while True:
        query = listen()
        if query.lower() in ['exit', 'quit', 'bye']:
            speak("Goodbye!")
            break
        if query:
            response = get_answer(query)
            speak(response)
            save_to_history(user_id, query, response)