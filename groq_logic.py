import requests
from .config import GROQ_API_KEY, GROQ_MODEL
import traceback

HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}

def ask(prompt, lang="en"):
    try:
        system_prompt = {
            "en": "You are a helpful assistant. Reply in clear, fluent English.",
            "hi": "आप एक सहायक हैं। कृपया उत्तर हिंदी में दें।"
        }.get(lang, "You are a helpful assistant.")

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=HEADERS,
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ]
            }
        )

        if response.status_code != 200:
            print("❌ Groq API returned error:", response.status_code, response.text)
            return "⚠️ Assistant is currently offline. Please try again later."

        data = response.json()
        return data['choices'][0]['message']['content'].strip()

    except Exception as e:
        print("❌ Exception in Groq API call:", e)
        traceback.print_exc()
        return "⚠️ Assistant is currently unavailable."
def search(prompt):
    prompt = prompt.lower()
    if "who are you" in prompt or "your name" in prompt:
        return "I am Irus, your personal assistant."
    elif "creator" in prompt or "who made you" in prompt:
        return "I was built by Nejamul Haque."
    return None  # if nothing matched