# wikipedia_search.py

import wikipedia

def search(query):
    try:
        summary = wikipedia.summary(query, sentences=2)
        return summary
    except wikipedia.exceptions.DisambiguationError as e:
        return f"This query is too ambiguous. Try one of these: {e.options[:5]}"
    except wikipedia.exceptions.PageError:
        return None
    except Exception as e:
        print("Wikipedia search error:", e)
        return None
