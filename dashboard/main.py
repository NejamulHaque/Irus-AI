import sys
import os
from flask import Flask, render_template, request, redirect, session, url_for, jsonify, flash
from werkzeug.utils import secure_filename
import mysql.connector
import bcrypt
import uuid
from datetime import datetime
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, FLASK_SECRET_KEY

# Fix import path to reach irus_assistant/
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

# ✅ Updated imports
from irus_assistant.groq_logic import ask, search

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

def get_db():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
@app.route('/')
def home():
    return redirect('/dashboard') if 'user_id' in session else redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password'].encode('utf-8')

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and bcrypt.checkpw(password, user['password_hash'].encode('utf-8')):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect('/dashboard')
        flash("❌ Login failed. Check your credentials.", "danger")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password'].encode('utf-8')
        hashed = bcrypt.hashpw(password, bcrypt.gensalt())

        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
            if cursor.fetchone():
                flash("⚠️ Email already registered!", "warning")
                return redirect('/register')
            cursor.execute("INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
                           (username, email, hashed.decode()))
            conn.commit()
            cursor.close()
            conn.close()
            flash("✅ Registered successfully!", "success")
            return redirect('/login')
        except Exception as e:
            flash(f"❌ Registration failed: {e}", "danger")
    return render_template('register.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM conversation_history WHERE user_id=%s ORDER BY timestamp DESC", (session['user_id'],))
    history = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('dashboard.html', username=session['username'], history=history)

@app.route('/delete_history', methods=['POST'])
def delete_history():
    if 'user_id' not in session:
        return redirect('/login')
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM conversation_history WHERE user_id = %s", (session['user_id'],))
        conn.commit()
        cursor.close()
        conn.close()
        flash("🗑️ Conversation history deleted.", "success")
    except Exception as e:
        print("Error deleting history:", e)
        flash("⚠️ An error occurred while deleting history.", "danger")
    return redirect('/dashboard')

@app.route('/delete_message/<int:message_id>', methods=['POST'])
def delete_message(message_id):
    if 'user_id' not in session:
        return jsonify({'status': 'unauthorized'}), 401
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM conversation_history WHERE id = %s AND user_id = %s", (message_id, session['user_id']))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/api/ask', methods=['POST'])
def ask_assistant():
    if 'user_id' not in session:
        return jsonify({'response': 'Unauthorized'}), 401

    data = request.get_json()
    user_msg = data.get("message")
    lang = data.get("lang", "en")
    mode = data.get("mode", "chat")

    print("🧠 Asking Irus:", user_msg, "| lang:", lang, "| mode:", mode)

    response = search(user_msg) or ask(user_msg, lang=lang)

    print("🤖 Irus response:", response)

    # Save to database
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO conversation_history (user_id, user_message, assistant_response) VALUES (%s, %s, %s)",
        (session['user_id'], user_msg, response)
    )
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'response': response})

@app.route("/api/stats")
def usage_stats():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT DATE(timestamp) AS date, COUNT(*) AS count
        FROM conversation_history
        WHERE user_id = %s
        GROUP BY DATE(timestamp)
        ORDER BY DATE(timestamp)
    """, (session['user_id'],))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify({
        "labels": [row['date'].strftime("%d %b") for row in rows],
        "data": [row['count'] for row in rows]
    })

@app.route("/api/memory")
def get_memory():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT fact, DATE_FORMAT(timestamp, '%%Y-%%m-%%d') as date 
        FROM memory 
        WHERE user_id = %s 
        ORDER BY timestamp DESC
    """, (session['user_id'],))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([{"fact": row[0], "date": row[1]} for row in rows])

@app.route("/profile")
def profile():
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    return render_template("profile.html", user=user)

@app.route("/profile/edit")
def edit_profile():
    if 'user_id' not in session:
        return redirect('/login')
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template("profile_update.html", user=user)

@app.route("/update_profile", methods=["POST"])
def update_profile():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    name = request.form.get("name")
    bio = request.form.get("bio")
    github = request.form.get("github")
    linkedin = request.form.get("linkedin")
    twitter = request.form.get("twitter")

    profile_pic_url = None
    resume_url = None
    print("⚙️ Received profile update POST")

    # Handle uploads
    if "profile_pic" in request.files:
        pic = request.files["profile_pic"]
        if pic and pic.filename:
            filename = secure_filename(pic.filename)
            filepath = os.path.join("static", "uploads", filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            pic.save(filepath)
            profile_pic_url = f"/static/uploads/{filename}"

    if "resume" in request.files:
        resume = request.files["resume"]
        if resume and resume.filename:
            filename = secure_filename(resume.filename)
            path = os.path.join("static", "resumes", filename)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            resume.save(path)
            resume_url = f"/static/resumes/{filename}"

    # Password change
    current_password = request.form.get("current_password")
    new_password = request.form.get("new_password")

    try:
        conn = get_db()
        cursor = conn.cursor()

        if current_password and new_password:
            cursor.execute("SELECT password_hash FROM users WHERE id=%s", (user_id,))
            old_hash = cursor.fetchone()[0]
            if bcrypt.checkpw(current_password.encode(), old_hash.encode()):
                new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
                cursor.execute("UPDATE users SET password_hash=%s WHERE id=%s", (new_hash, user_id))
            else:
                flash("⚠️ Incorrect current password", "danger")
                return redirect("/profile")

        # Update fields
        sql = """
        UPDATE users SET name=%s, bio=%s, github=%s, linkedin=%s, twitter=%s
        {pic} {resume}
        WHERE id=%s
        """.format(
            pic=", profile_pic=%s" if profile_pic_url else "",
            resume=", resume=%s" if resume_url else ""
        )

        values = [name, bio, github, linkedin, twitter]
        if profile_pic_url:
            values.append(profile_pic_url)
        if resume_url:
            values.append(resume_url)
        values.append(user_id)

        cursor.execute(sql, values)
        conn.commit()
        cursor.close()
        conn.close()

        flash("✅ Profile updated!", "success")
    except Exception as e:
        print("Update Error:", e)
        flash("❌ Failed to update profile.", "danger")

    return redirect("/profile")

if __name__ == '__main__':
    app.run(debug=True)