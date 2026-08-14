import os
import re
import csv
import io
import json
import time
import random
import secrets
import hashlib
import base64
import urllib.parse
from datetime import datetime, timedelta
from sqlalchemy import func
from werkzeug.utils import secure_filename

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    Response, jsonify, current_app, make_response
)
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from app import limiter
from app.models import (
    db, User, Conversation, Message, Document, DocumentChunk,
    Memory, ErrorLog, APIKey, APIRequestLog, LoginAudit, Broadcast
)
from app.services import ai_service, document_service, search_service

main = Blueprint('main', __name__)


# -----------------------
# Helpers
# -----------------------

USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_.-]{3,30}$')
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


def validate_password(password):
    if len(password) < 8:
        return 'Password must be at least 8 characters long.'
    if not re.search(r'[A-Za-z]', password):
        return 'Password must contain at least one letter.'
    if not re.search(r'\d', password):
        return 'Password must contain at least one number.'
    return None


def get_user_conversation(conversation_id):
    return Conversation.query.filter_by(
        id=conversation_id, user_id=current_user.id
    ).first()


def _auth_api_key():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    raw = auth[7:].strip()
    if not raw.startswith('irus_'):
        return None
    key = APIKey.query.filter_by(key_hash=hashlib.sha256(raw.encode()).hexdigest()).first()
    if key:
        key.last_used_at = datetime.utcnow()
        db.session.commit()
    return key


def _log_api(key, endpoint, method, status_code, latency_ms=None):
    try:
        db.session.add(APIRequestLog(
            api_key_id=key.id if key else None,
            user_id=key.user_id if key else None,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            latency_ms=latency_ms,
            ip=request.remote_addr
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


# -----------------------
# Health & PWA
# -----------------------

@main.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200


@main.route('/sw.js')
def service_worker():
    response = current_app.send_static_file('sw.js')
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response


@main.route('/broadcast')
def broadcast_current():
    b = Broadcast.query.filter_by(is_active=True).order_by(Broadcast.created_at.desc()).first()
    return jsonify({'active': bool(b), 'message': b.message if b else ''})


# -----------------------
# Auth (with audit + ban check)
# -----------------------

@main.route('/auth', methods=['GET', 'POST'])
@limiter.limit("20 per minute")
def auth():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        if request.form.get('website'):
            return redirect(url_for('main.auth'))

        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        action = request.form.get('action')

        if not username or not password:
            flash('Username and password are required.', 'error')
            return render_template('auth.html')

        if action == 'login':
            if '@' in username:
                user = User.query.filter_by(email=username.lower()).first()
            else:
                user = User.query.filter_by(username=username).first()

            if user and check_password_hash(user.password_hash, password):
                if getattr(user, 'is_banned', False):
                    flash('Your account has been suspended.', 'error')
                    return render_template('auth.html')
                login_user(user)
                db.session.add(LoginAudit(
                    user_id=user.id,
                    ip=request.remote_addr,
                    user_agent=(request.user_agent.string or '')[:200]
                ))
                db.session.commit()
                return redirect(url_for('main.index'))
            flash('Invalid username or password.', 'error')

        elif action == 'register':
            if not USERNAME_PATTERN.match(username):
                flash('Username must be 3–30 characters (letters, numbers, dots, dashes, underscores).', 'error')
                return render_template('auth.html')
            if not EMAIL_PATTERN.match(email):
                flash('Please enter a valid email address.', 'error')
                return render_template('auth.html')
            password_error = validate_password(password)
            if password_error:
                flash(password_error, 'error')
                return render_template('auth.html')
            if User.query.filter_by(username=username).first():
                flash('Username already exists.', 'error')
                return render_template('auth.html')
            if User.query.filter_by(email=email).first():
                flash('An account with this email already exists.', 'error')
                return render_template('auth.html')

            new_user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                is_admin=(User.query.count() == 0)
            )
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user)
            return redirect(url_for('main.index'))

    return render_template('auth.html')


@main.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.auth'))


# -----------------------
# Home / Conversations
# -----------------------

@main.route('/')
@login_required
def index():
    conversation = Conversation.query.filter_by(user_id=current_user.id).order_by(
        Conversation.updated_at.desc()).first()
    if not conversation:
        conversation = Conversation(user_id=current_user.id, title='New Chat')
        db.session.add(conversation)
        db.session.commit()
    return redirect(url_for('main.chat', conversation_id=conversation.id))


@main.route('/chat/new', methods=['GET', 'POST'])
@login_required
def new_chat():
    conversation = Conversation(user_id=current_user.id, title='New Chat')
    db.session.add(conversation)
    db.session.commit()
    return redirect(url_for('main.chat', conversation_id=conversation.id))


@main.route('/chat/<int:conversation_id>')
@login_required
def chat(conversation_id):
    conversation = get_user_conversation(conversation_id)
    if not conversation:
        flash('Conversation not found.', 'error')
        return redirect(url_for('main.index'))
    messages = Message.query.filter_by(conversation_id=conversation.id).order_by(
        Message.created_at.asc()).all()
    return render_template('chat.html', conversation=conversation, messages=messages)


@main.route('/chat/<int:conversation_id>/delete', methods=['POST'])
@login_required
def delete_chat(conversation_id):
    conversation = get_user_conversation(conversation_id)
    if not conversation:
        flash('Conversation not found.', 'error')
        return redirect(url_for('main.index'))
    db.session.delete(conversation)
    db.session.commit()
    flash('Chat deleted.', 'success')
    return redirect(url_for('main.index'))


@main.route('/chat/<int:conversation_id>/rename', methods=['POST'])
@login_required
def rename_chat(conversation_id):
    conversation = get_user_conversation(conversation_id)
    if not conversation:
        return jsonify({'error': 'Conversation not found'}), 404
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Title is required'}), 400
    if len(title) > 120:
        return jsonify({'error': 'Title is too long. Max 120 characters.'}), 400
    conversation.title = title
    db.session.commit()
    return jsonify({'success': True, 'title': conversation.title})


# -----------------------
# Folders & History
# -----------------------

@main.route('/chat/history')
@login_required
def chat_history():
    conversations = Conversation.query.filter_by(user_id=current_user.id).order_by(
        Conversation.updated_at.desc()).all()
    return jsonify({'conversations': [{
        'id': c.id, 'title': c.title, 'folder': c.folder,
        'updated_at': c.updated_at.isoformat()
    } for c in conversations]})


@main.route('/chat/<int:conversation_id>/folder', methods=['POST'])
@login_required
def update_folder(conversation_id):
    conversation = get_user_conversation(conversation_id)
    if not conversation:
        return jsonify({'error': 'Conversation not found'}), 404
    data = request.get_json(silent=True) or {}
    folder = (data.get('folder') or '').strip()
    conversation.folder = folder if folder else None
    db.session.commit()
    return jsonify({'success': True, 'folder': conversation.folder})


@main.route('/folders')
@login_required
def get_folders():
    folders = db.session.query(Conversation.folder).filter_by(user_id=current_user.id).distinct().all()
    return jsonify(sorted([f[0] for f in folders if f[0]]))


@main.route('/folders/<path:folder_name>/delete', methods=['DELETE'])
@login_required
def delete_folder(folder_name):
    Conversation.query.filter_by(user_id=current_user.id, folder=folder_name).update({'folder': None})
    db.session.commit()
    return jsonify({'success': True})


# -----------------------
# Public Share Links
# -----------------------

@main.route('/chat/<int:conversation_id>/share', methods=['POST'])
@login_required
def share_chat(conversation_id):
    conversation = get_user_conversation(conversation_id)
    if not conversation:
        return jsonify({'error': 'Conversation not found'}), 404
    if not conversation.share_token:
        conversation.share_token = secrets.token_urlsafe(16)
        db.session.commit()
    return jsonify({
        'success': True,
        'token': conversation.share_token,
        'url': url_for('main.shared_chat', token=conversation.share_token, _external=True)
    })


@main.route('/chat/<int:conversation_id>/unshare', methods=['POST'])
@login_required
def unshare_chat(conversation_id):
    conversation = get_user_conversation(conversation_id)
    if not conversation:
        return jsonify({'error': 'Conversation not found'}), 404
    conversation.share_token = None
    db.session.commit()
    return jsonify({'success': True})


@main.route('/share/<token>')
def shared_chat(token):
    conversation = Conversation.query.filter_by(share_token=token).first()
    if not conversation:
        flash('This share link is invalid or has been disabled.', 'error')
        return redirect(url_for('main.auth'))
    messages = Message.query.filter_by(conversation_id=conversation.id).order_by(
        Message.created_at.asc()).all()
    return render_template('share.html', conversation=conversation, messages=messages)


# -----------------------
# Streaming Chat (vision, search, memory, image-gen, creator)
# -----------------------

@main.route('/chat/<int:conversation_id>/stream', methods=['POST'])
@login_required
@limiter.limit("40 per minute")
def stream_chat(conversation_id):
    conversation = get_user_conversation(conversation_id)
    if not conversation:
        return jsonify({'error': 'Conversation not found'}), 404

    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'send')
    message_text = (data.get('message') or '').strip()
    message_id = data.get('message_id')
    document_id = data.get('document_id')
    web_search = data.get('web_search', False)
    image_mode = data.get('image_mode', False)
    image_data = data.get('image_data') or None
    if image_data and not str(image_data).startswith('data:image'):
        image_data = None

    doc_id_int = None
    if document_id:
        try:
            doc_id_int = int(document_id)
        except (TypeError, ValueError):
            doc_id_int = None

    user_message_id = None
    if message_id is not None:
        try:
            message_id = int(message_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid message ID'}), 400

    if mode == 'send':
        if not message_text and not image_data:
            return jsonify({'error': 'Message is required'}), 400
        if len(message_text) > 8000:
            return jsonify({'error': 'Message is too long. Max 8000 characters.'}), 400
        user_message = Message(
            conversation_id=conversation.id, role='user',
            content=message_text or '(image attached)',
            document_id=doc_id_int, image_data=image_data
        )
        db.session.add(user_message)
        if conversation.title == 'New Chat':
            title_src = message_text or 'Image analysis'
            conversation.title = title_src[:60] + ('...' if len(title_src) > 60 else '')
        conversation.updated_at = datetime.utcnow()
        db.session.commit()
        user_message_id = user_message.id

    elif mode == 'edit':
        if not message_text:
            return jsonify({'error': 'Edited message is required'}), 400
        if not message_id:
            return jsonify({'error': 'Message ID is required for editing'}), 400
        message = Message.query.get(message_id)
        if not message or message.conversation_id != conversation.id or message.role != 'user':
            return jsonify({'error': 'Message not found'}), 404
        Message.query.filter(
            Message.conversation_id == conversation.id, Message.id > message.id
        ).delete(synchronize_session=False)
        message.content = message_text
        first_user = Message.query.filter_by(conversation_id=conversation.id, role='user').order_by(Message.id.asc()).first()
        if first_user and first_user.id == message.id:
            conversation.title = message_text[:60] + ('...' if len(message_text) > 60 else '')
        conversation.updated_at = datetime.utcnow()
        db.session.commit()
        user_message_id = message.id

    elif mode == 'regenerate':
        if message_id:
            message = Message.query.get(message_id)
            if not message or message.conversation_id != conversation.id or message.role != 'assistant':
                return jsonify({'error': 'Assistant message not found'}), 404
            Message.query.filter(
                Message.conversation_id == conversation.id, Message.id >= message.id
            ).delete(synchronize_session=False)
        else:
            last_message = Message.query.filter_by(conversation_id=conversation.id).order_by(Message.id.desc()).first()
            if last_message and last_message.role == 'assistant':
                db.session.delete(last_message)
        conversation.updated_at = datetime.utcnow()
        db.session.commit()
    else:
        return jsonify({'error': 'Invalid mode'}), 400

    # RAG context
    context_prompt = ""
    if doc_id_int:
        doc = Document.query.filter_by(id=doc_id_int, user_id=current_user.id).first()
        if doc:
            context = document_service.get_relevant_context(message_text, doc_id_int)
            if context:
                context_prompt = f"[CONTEXT FROM DOCUMENT: {doc.original_name}]\n{context}\n[END OF CONTEXT]\nUse the context above to answer. If the answer is not in the context, say so."
            else:
                context_prompt = f"[System Note: The document '{doc.original_name}' has no readable text. Ask the user for a text-based PDF/Word file.]"
        else:
            context_prompt = "[System Note: The selected document could not be found.]"

    history_messages = Message.query.filter_by(conversation_id=conversation.id).order_by(Message.id.asc()).all()
    if not history_messages and mode != 'send':
        return jsonify({'error': 'No messages available to regenerate'}), 400
    limited_history = history_messages[-30:]

    # Auto memory
    if mode == 'send' and message_text.lower().startswith(('remember ', 'remember:', 'remember that ')):
        fact = message_text.split(':', 1)[-1].strip() if ':' in message_text else message_text[9:].strip()
        if fact.lower().startswith('that '):
            fact = fact[5:].strip()
        if fact:
            db.session.add(Memory(user_id=current_user.id, content=fact))
            db.session.commit()
            context_prompt += f"\n[System Note: You just saved this to memory: '{fact}']"

    # Live web search
    search_sources = []
    if web_search and message_text:
        search_results = search_service.search_web(message_text)
        search_sources = search_results
        if search_results:
            context_prompt += f"\n[LIVE WEB RESULTS for \"{message_text}\"]\n{search_service.format_search_context(search_results)}\n[END]\nCite sources like [Source 1]."

    user_memories = [m.content for m in Memory.query.filter_by(user_id=current_user.id).all()]
    ai_messages = ai_service.build_messages(
        [{'role': m.role, 'content': m.content} for m in limited_history],
        extra_context=context_prompt,
        user_memories=user_memories
    )

    user_model = current_user.preferred_model
    current_user_id = current_user.id

    # Vision attach
    if image_data and mode == 'send':
        for m in reversed(ai_messages):
            if m['role'] == 'user':
                m['content'] = [
                    {'type': 'text', 'text': message_text or 'Describe this image in detail.'},
                    {'type': 'image_url', 'image_url': {'url': image_data}},
                ]
                break
        user_model = os.getenv('GROQ_VISION_MODEL', 'qwen/qwen3.6-27b')

    app = current_app._get_current_object()

    def sse(payload):
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def generate():
        assistant_message_id = None
        full_response = []
        yield sse({'type': 'meta', 'mode': mode, 'conversation_id': conversation_id,
                   'user_message_id': user_message_id, 'sources': search_sources})
        try:
            creator = ai_service.creator_reply(message_text)
            if creator and mode in ('send', 'regenerate'):
                for piece in [creator[i:i + 32] for i in range(0, len(creator), 32)]:
                    full_response.append(piece)
                    yield sse({'type': 'chunk', 'content': piece})
            elif image_mode and message_text:
                seed = random.randint(1, 10000000)
                img_url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(message_text)
                           + f"?width=1024&height=1024&seed={seed}&nologo=true")
                image_text = (f"🎨 **Here is your image for:** *{message_text}*\n\n"
                              f"![{message_text}]({img_url})\n\n_Generated by Irus._")
                for piece in [image_text[i:i + 32] for i in range(0, len(image_text), 32)]:
                    full_response.append(piece)
                    yield sse({'type': 'chunk', 'content': piece})
            else:
                for chunk in ai_service.stream_chat(ai_messages, model_override=user_model):
                    full_response.append(chunk)
                    yield sse({'type': 'chunk', 'content': chunk})
        except Exception as e:
            error_text = f"\n\n[AI error] {e}"
            full_response.append(error_text)
            yield sse({'type': 'chunk', 'content': error_text})
            with app.app_context():
                try:
                    db.session.add(ErrorLog(user_id=current_user_id, error_type='AI Stream Error', message=str(e)))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                finally:
                    db.session.remove()
        finally:
            with app.app_context():
                try:
                    assistant_message = Message(
                        conversation_id=conversation_id, role='assistant',
                        content=''.join(full_response) or 'No response.'
                    )
                    db.session.add(assistant_message)
                    convo = db.session.get(Conversation, conversation_id)
                    if convo:
                        convo.updated_at = datetime.utcnow()
                    db.session.commit()
                    assistant_message_id = assistant_message.id
                except Exception as save_error:
                    app.logger.error(f'Failed to save assistant message: {save_error}')
                    db.session.rollback()
                finally:
                    db.session.remove()
        yield sse({'type': 'done', 'assistant_message_id': assistant_message_id})

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'})


# -----------------------
# Compare (Groq vs Ollama)
# -----------------------

@main.route('/chat/<int:conversation_id>/compare', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def compare_chat(conversation_id):
    conversation = get_user_conversation(conversation_id)
    if not conversation:
        return jsonify({'error': 'Conversation not found'}), 404

    data = request.get_json(silent=True) or {}
    message_text = (data.get('message') or '').strip()
    if not message_text:
        return jsonify({'error': 'Message is required'}), 400
    if len(message_text) > 8000:
        return jsonify({'error': 'Message is too long. Max 8000 characters.'}), 400

    user_message = Message(conversation_id=conversation.id, role='user', content=message_text)
    db.session.add(user_message)
    if conversation.title == 'New Chat':
        conversation.title = message_text[:60] + ('...' if len(message_text) > 60 else '')
    conversation.updated_at = datetime.utcnow()
    db.session.commit()
    user_message_id = user_message.id

    history = Message.query.filter_by(
        conversation_id=conversation.id
    ).order_by(Message.id.asc()).all()[-12:]

    memories = [m.content for m in Memory.query.filter_by(user_id=current_user.id).all()]
    ai_messages = ai_service.build_messages(
        [{'role': h.role, 'content': h.content} for h in history],
        user_memories=memories
    )

    app = current_app._get_current_object()

    def sse(payload):
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def generate():
        yield sse({'type': 'meta', 'user_message_id': user_message_id})
        
        # Compare Groq vs Pollinations (cloud-safe)
        full = {'groq': [], 'pollinations': []}
        gens = {
            'groq': ai_service._stream_groq(ai_messages),
            'pollinations': ai_service._stream_pollinations(ai_messages)
        }
        active = {'groq': True, 'pollinations': True}

        while any(active.values()):
            for name in ('groq', 'pollinations'):
                if not active[name]:
                    continue
                try:
                    chunk = next(gens[name])
                    full[name].append(chunk)
                    yield sse({'type': 'chunk', 'provider': name, 'content': chunk})
                except StopIteration:
                    active[name] = False
                    yield sse({'type': 'provider_done', 'provider': name})
                except Exception as e:
                    msg = f"\n\n_[{name} unavailable: {e}]_"
                    full[name].append(msg)
                    yield sse({'type': 'chunk', 'provider': name, 'content': msg})
                    active[name] = False
                    yield sse({'type': 'provider_done', 'provider': name})

        combined = (
            "**⚡ Groq answer:**\n\n" + (''.join(full['groq']) or '_no response_') +
            "\n\n---\n\n**🌐 Pollinations answer:**\n\n" + (''.join(full['pollinations']) or '_no response_')
        )
        assistant_message_id = None
        with app.app_context():
            try:
                assistant_message = Message(
                    conversation_id=conversation_id,
                    role='assistant',
                    content=combined
                )
                db.session.add(assistant_message)
                db.session.commit()
                assistant_message_id = assistant_message.id
            except Exception:
                db.session.rollback()
            finally:
                db.session.remove()
        yield sse({'type': 'done', 'assistant_message_id': assistant_message_id})

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


# -----------------------
# Documents
# -----------------------

@main.route('/documents/upload', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def upload_document():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    try:
        doc = document_service.process_and_save_document(file, current_user.id)
        return jsonify({'success': True, 'id': doc.id, 'name': doc.original_name})
    except Exception as e:
        db.session.add(ErrorLog(user_id=current_user.id, error_type='Document Upload Error', message=str(e)))
        db.session.commit()
        return jsonify({'error': str(e)}), 400


@main.route('/documents/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete_document(doc_id):
    doc = Document.query.filter_by(id=doc_id, user_id=current_user.id).first()
    if not doc:
        return jsonify({'error': 'Document not found'}), 404
    if doc.file_path and os.path.exists(doc.file_path):
        os.remove(doc.file_path)
    db.session.delete(doc)
    db.session.commit()
    return jsonify({'success': True})


@main.route('/documents')
@login_required
def list_documents():
    docs = Document.query.filter_by(user_id=current_user.id).order_by(Document.created_at.desc()).all()
    return jsonify([{'id': d.id, 'name': d.original_name, 'date': d.created_at.strftime('%Y-%m-%d')} for d in docs])


# -----------------------
# Memories
# -----------------------

@main.route('/memories', methods=['GET'])
@login_required
def get_memories():
    memories = Memory.query.filter_by(user_id=current_user.id).order_by(Memory.created_at.desc()).all()
    return jsonify([{'id': m.id, 'content': m.content} for m in memories])


@main.route('/memories', methods=['POST'])
@login_required
def add_memory():
    data = request.get_json()
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'error': 'Content is required'}), 400
    mem = Memory(user_id=current_user.id, content=content)
    db.session.add(mem)
    db.session.commit()
    return jsonify({'success': True, 'id': mem.id, 'content': mem.content})


@main.route('/memories/<int:mem_id>', methods=['DELETE'])
@login_required
def delete_memory(mem_id):
    mem = Memory.query.filter_by(id=mem_id, user_id=current_user.id).first()
    if mem:
        db.session.delete(mem)
        db.session.commit()
    return jsonify({'success': True})


# -----------------------
# Profile (with stats)
# -----------------------

@main.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.bio = request.form.get('bio', '').strip()
        current_user.preferred_model = request.form.get('preferred_model', 'llama-3.1-8b-instant')
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename != '':
                data = file.read()
                if len(data) > 1_500_000:
                    flash('Avatar too large. Max 1.5 MB.', 'error')
                    return redirect(url_for('main.profile'))
                mime = file.mimetype or 'image/png'
                current_user.avatar = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        new_password = request.form.get('new_password', '')
        if new_password:
            current_user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('main.profile'))

    stats = {
        'conversations': Conversation.query.filter_by(user_id=current_user.id).count(),
        'messages': db.session.query(func.count(Message.id)).join(
            Conversation, Message.conversation_id == Conversation.id
        ).filter(Conversation.user_id == current_user.id).scalar() or 0,
        'documents': Document.query.filter_by(user_id=current_user.id).count(),
        'memories': Memory.query.filter_by(user_id=current_user.id).count(),
        'api_keys': APIKey.query.filter_by(user_id=current_user.id).count(),
        'api_requests': APIRequestLog.query.filter_by(user_id=current_user.id).count(),
    }
    return render_template('profile.html', stats=stats)


# -----------------------
# Developer API Console
# -----------------------

@main.route('/api-keys')
@login_required
def api_keys_page():
    keys = APIKey.query.filter_by(user_id=current_user.id).order_by(APIKey.created_at.desc()).all()
    key_ids = [k.id for k in keys]
    logs = APIRequestLog.query.filter(APIRequestLog.api_key_id.in_(key_ids)).order_by(
        APIRequestLog.created_at.desc()).limit(50).all() if key_ids else []
    total_requests = APIRequestLog.query.filter_by(user_id=current_user.id).count()
    total_errors = APIRequestLog.query.filter(
        APIRequestLog.user_id == current_user.id,
        APIRequestLog.status_code >= 400
    ).count()
    return render_template('api_keys.html', keys=keys, logs=logs,
                           total_requests=total_requests, total_errors=total_errors)


@main.route('/api-keys/logs')
@login_required
def api_key_logs():
    key_ids = [k.id for k in APIKey.query.filter_by(user_id=current_user.id).all()]
    logs = APIRequestLog.query.filter(APIRequestLog.api_key_id.in_(key_ids)).order_by(
        APIRequestLog.created_at.desc()).limit(50).all() if key_ids else []
    return jsonify([{
        'time': l.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'key': l.api_key.prefix if l.api_key else '—',
        'endpoint': l.endpoint, 'method': l.method, 'status': l.status_code,
        'latency_ms': l.latency_ms, 'ip': l.ip
    } for l in logs])


@main.route('/api-keys/create', methods=['POST'])
@login_required
def create_api_key():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or 'Default').strip()[:100] or 'Default'
    raw = 'irus_' + secrets.token_urlsafe(24)
    key = APIKey(user_id=current_user.id, name=name, prefix=raw[:10],
                 key_hash=hashlib.sha256(raw.encode()).hexdigest())
    db.session.add(key)
    db.session.commit()
    return jsonify({'success': True, 'id': key.id, 'key': raw})


@main.route('/api-keys/<int:key_id>/revoke', methods=['POST'])
@login_required
def revoke_api_key(key_id):
    key = APIKey.query.filter_by(id=key_id, user_id=current_user.id).first()
    if key:
        db.session.delete(key)
        db.session.commit()
    return jsonify({'success': True})


# -----------------------
# Public Developer API (with logging)
# -----------------------

@main.route('/api/v1/me')
def api_me():
    start = time.time()
    key = _auth_api_key()
    if not key:
        _log_api(None, '/api/v1/me', 'GET', 401, int((time.time() - start) * 1000))
        return jsonify({'error': 'Invalid API key'}), 401
    user = User.query.get(key.user_id)
    _log_api(key, '/api/v1/me', 'GET', 200, int((time.time() - start) * 1000))
    return jsonify({'username': user.username, 'email': user.email})


@main.route('/api/v1/chat', methods=['POST'])
@limiter.limit("30 per minute")
def api_chat():
    start = time.time()
    key = _auth_api_key()
    if not key:
        _log_api(None, '/api/v1/chat', 'POST', 401, int((time.time() - start) * 1000))
        return jsonify({'error': 'Invalid API key'}), 401
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    if not message:
        _log_api(key, '/api/v1/chat', 'POST', 400, int((time.time() - start) * 1000))
        return jsonify({'error': 'message is required'}), 400

    context_prompt = ""
    if data.get('web_search'):
        results = search_service.search_web(message)
        if results:
            context_prompt = "[LIVE WEB SEARCH RESULTS]\n" + search_service.format_search_context(results)

    memories = [m.content for m in Memory.query.filter_by(user_id=key.user_id).all()]
    ai_messages = ai_service.build_messages(
        [{'role': 'user', 'content': message}], extra_context=context_prompt, user_memories=memories)

    chunks = []
    try:
        for chunk in ai_service.stream_chat(ai_messages):
            chunks.append(chunk)
    except Exception as e:
        _log_api(key, '/api/v1/chat', 'POST', 502, int((time.time() - start) * 1000))
        return jsonify({'error': f'AI provider error: {e}'}), 502

    _log_api(key, '/api/v1/chat', 'POST', 200, int((time.time() - start) * 1000))
    return jsonify({'success': True, 'reply': ''.join(chunks)})


# -----------------------
# Admin Control Plane
# -----------------------

@main.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Access denied. Administrators only.', 'error')
        return redirect(url_for('main.index'))

    stats = {
        'users': User.query.count(),
        'conversations': Conversation.query.count(),
        'messages': Message.query.count(),
        'documents': Document.query.count(),
        'memories': Memory.query.count(),
        'errors': ErrorLog.query.count(),
        'api_keys': APIKey.query.count(),
        'api_requests': APIRequestLog.query.count(),
    }

    activity = []
    max_count = 1
    for i in range(6, -1, -1):
        day = (datetime.utcnow() - timedelta(days=i)).date()
        start = datetime.combine(day, datetime.min.time())
        end = start + timedelta(days=1)
        count = Message.query.filter(Message.created_at >= start, Message.created_at < end).count()
        max_count = max(max_count, count)
        activity.append({'label': day.strftime('%a'), 'count': count})
    for d in activity:
        d['height'] = max(4, int((d['count'] / max_count) * 100))

    signups = []
    for i in range(6, -1, -1):
        day = (datetime.utcnow() - timedelta(days=i)).date()
        start = datetime.combine(day, datetime.min.time())
        end = start + timedelta(days=1)
        signups.append({'label': day.strftime('%a'),
                        'count': User.query.filter(User.created_at >= start, User.created_at < end).count()})

    most_used_docs = db.session.query(
        Document.original_name, func.count(Message.id).label('uses')
    ).join(Message, Message.document_id == Document.id).group_by(Document.id).order_by(
        func.count(Message.id).desc()).limit(5).all()

    model_usage = db.session.query(User.preferred_model, func.count(User.id)).group_by(User.preferred_model).all()
    top_ips = db.session.query(LoginAudit.ip, func.count(LoginAudit.id).label('hits')).group_by(
        LoginAudit.ip).order_by(func.count(LoginAudit.id).desc()).limit(5).all()

    api_stats = {
        'total_keys': APIKey.query.count(),
        'total_requests': APIRequestLog.query.count(),
        'requests_24h': APIRequestLog.query.filter(
            APIRequestLog.created_at >= datetime.utcnow() - timedelta(hours=24)).count(),
        'error_count': APIRequestLog.query.filter(APIRequestLog.status_code >= 400).count(),
    }
    recent_api_logs = APIRequestLog.query.order_by(APIRequestLog.created_at.desc()).limit(10).all()
    top_keys = db.session.query(APIKey, func.count(APIRequestLog.id).label('uses')).outerjoin(
        APIRequestLog, APIRequestLog.api_key_id == APIKey.id).group_by(APIKey.id).order_by(
        func.count(APIRequestLog.id).desc()).limit(5).all()

    recent_users = User.query.order_by(User.created_at.desc()).limit(8).all()
    error_logs = ErrorLog.query.order_by(ErrorLog.created_at.desc()).limit(10).all()
    all_users = User.query.order_by(User.created_at.desc()).all()
    all_conversations = Conversation.query.order_by(Conversation.updated_at.desc()).limit(20).all()
    active_broadcast = Broadcast.query.filter_by(is_active=True).first()

    return render_template(
        'admin.html', stats=stats, activity=activity, signups=signups,
        most_used_docs=most_used_docs, model_usage=model_usage, top_ips=top_ips,
        api_stats=api_stats, recent_api_logs=recent_api_logs, top_keys=top_keys,
        recent_users=recent_users, error_logs=error_logs, all_users=all_users,
        all_conversations=all_conversations, active_broadcast=active_broadcast
    )


@main.route('/admin/users/<int:user_id>/toggle-admin', methods=['POST'])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Denied'}), 403
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot demote yourself'}), 400
    user.is_admin = not user.is_admin
    db.session.commit()
    return jsonify({'success': True, 'is_admin': user.is_admin})


@main.route('/admin/users/<int:user_id>/toggle-ban', methods=['POST'])
@login_required
def toggle_ban(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Denied'}), 403
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot ban yourself'}), 400
    user.is_banned = not getattr(user, 'is_banned', False)
    db.session.commit()
    return jsonify({'success': True, 'is_banned': user.is_banned})


@main.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Denied'}), 403
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    db.session.delete(user)
    db.session.commit()
    return jsonify({'success': True})


@main.route('/admin/broadcast', methods=['POST'])
@login_required
def manage_broadcast():
    if not current_user.is_admin:
        return jsonify({'error': 'Denied'}), 403
    data = request.get_json(silent=True) or {}
    msg = (data.get('message') or '').strip()
    Broadcast.query.filter_by(is_active=True).update({'is_active': False})
    if msg:
        db.session.add(Broadcast(message=msg, is_active=True))
    db.session.commit()
    return jsonify({'success': True})


@main.route('/admin/errors/clear', methods=['POST'])
@login_required
def clear_errors():
    if not current_user.is_admin:
        return jsonify({'error': 'Denied'}), 403
    ErrorLog.query.delete()
    db.session.commit()
    return jsonify({'success': True})


@main.route('/admin/export/users')
@login_required
def export_users():
    if not current_user.is_admin:
        return redirect(url_for('main.index'))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Username', 'Email', 'Admin', 'Banned', 'Created'])
    for u in User.query.all():
        writer.writerow([u.id, u.username, u.email, u.is_admin, getattr(u, 'is_banned', False), u.created_at])
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = 'attachment; filename=users.csv'
    return response


@main.route('/admin/chat/<int:conversation_id>')
@login_required
def inspect_chat(conversation_id):
    if not current_user.is_admin:
        return redirect(url_for('main.index'))
    conversation = Conversation.query.get_or_404(conversation_id)
    messages = Message.query.filter_by(conversation_id=conversation.id).order_by(Message.created_at.asc()).all()
    return render_template('share.html', conversation=conversation, messages=messages)