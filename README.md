# 🤖 Irus AI Assistant  

Irus is a **personal AI assistant dashboard** built with **Flask + MySQL + Groq AI API**.  
It supports:
- 🗣️ Voice chat (wake word: "Hey Irus")
- 🌦️ Weather updates
- 📄 Resume Builder & Portfolio integrations
- 📕 Document summarization (PDF, DOCX, TXT)
- 🧠 Memory (remembers facts per user)
- 📊 Usage statistics & chat history
- 👤 Profile management (photo, bio, resume, socials)
- 🔐 Login / Register with password hashing

---

## 🚀 Features
- Secure **login & registration** with bcrypt
- **Groq AI** integration for responses
- **Weather search** (OpenWeather API)
- **Web search fallback** if AI can’t answer
- **File upload + summarization**
- **User memory system** (recall last fact)
- **Voice assistant** (speech recognition + text-to-speech)
- **Profile dashboard** with editable info
- **Usage charts** (Chart.js)
- **Session-based authentication**

---

## 🛠️ Tech Stack
- **Backend**: Python (Flask)
- **Database**: MySQL (AlwaysData hosting)
- **Frontend**: HTML, CSS, JavaScript
- **APIs**: Groq AI, OpenWeather
- **Auth**: Flask sessions + bcrypt

---

## 📂 Project Structure
irus-personal-assistant/
│── dashboard/
│   ├── app.py               # Main Flask app
│   ├── templates/           # HTML files
│   │   ├── login.html
│   │   ├── register.html
│   │   ├── dashboard.html
│   │   ├── profile.html
│   │   └── profile_update.html
│   ├── static/              # CSS, JS, uploads
│   │   ├── uploads/         # Profile pics
│   │   └── resumes/         # Resume uploads
│
│── irus_assistant/
│   ├── init.py
│   ├── config.py            # Loads env variables
│   ├── groq_logic.py        # Groq AI integration
│   ├── weather.py           # Weather functions
│
│── .env                     # Secrets (ignored by git)
│── requirements.txt         # Python dependencies
│── README.md                # This file

## ⚙️ Setup Instructions
### 1️⃣ Clone Repository
```bash
git clone https://github.com/your-username/irus-personal-assistant.git
cd irus-personal-assistant/dashboard
```
2️⃣ Create Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate   # Mac/Linux
venv\Scripts\activate      # Windows
```
3️⃣ Install Dependencies
```bash
pip install -r requirements.txt
```
4️⃣ Configure Environment Variables
Create a .env file in project root:
```bash
# Groq AI
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=model_name

# MySQL Database (AlwaysData)
DB_HOST=mysql-yourusername.alwaysdata.net
DB_USER=yourusername
DB_PASSWORD=yourpassword
DB_NAME=yourdbname

# Flask
SECRET_KEY=your_secret_key_here
```
5️⃣ Setup MySQL Database
Run these queries in phpMyAdmin (AlwaysData):
```bash
CREATE TABLE users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(100) NOT NULL,
  email VARCHAR(100) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  name VARCHAR(100),
  bio TEXT,
  github VARCHAR(255),
  linkedin VARCHAR(255),
  twitter VARCHAR(255),
  profile_pic VARCHAR(255),
  resume VARCHAR(255),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE conversation_history (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  user_message TEXT,
  assistant_response TEXT,
  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE memory (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  fact TEXT,
  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```
6️⃣ Run Flask Server
```bash
cd dashboard
python app.py
```
App will be available at 👉 http://127.0.0.1:5000

## 🌍 Deployment
Deploy on AlwaysData
	1.	Upload your project files (irus_assistant/, dashboard/)
	2.	Set Python app entry point → dashboard/app.py
	3.	Add .env in AlwaysData environment settings
	4.	Use MySQL credentials from AlwaysData

## 📦 Requirements
See requirements.txt:
Flask
mysql-connector-python
bcrypt
python-dotenv
requests
PyPDF2
python-docx
if not install
```bash
pip install -r requirements.txt
```
## 🧑‍💻 Author
Built with ❤️ by Nejamul Haque
Portfolio: https://portfolio-ai-theta.vercel.app/
