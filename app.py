from flask import Flask, request, jsonify, send_file, send_from_directory, Response, stream_with_context
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import jwt
import datetime
from datetime import timedelta, timezone
from functools import wraps
import sqlite3
from dotenv import load_dotenv
from io import BytesIO
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import base64
import mimetypes
import subprocess
import shutil
import threading
import time
import hashlib

load_dotenv()

app = Flask(__name__, static_folder='static', static_url_path=None)

# Timezone helper
IST = timezone(timedelta(hours=5, minutes=30))

def get_now_ist():
    return datetime.datetime.now(IST)

def cleanup_hls_task():
    """Background thread to cleanup HLS folders older than 24 hours and sync deduplicated HLS paths"""
    while True:
        try:
            # Part 1: Cleanup expired HLS
            now = time.time()
            cutoff = now - (24 * 3600) # 24 hours ago
            
            if os.path.exists(HLS_FOLDER):
                for folder_name in os.listdir(HLS_FOLDER):
                    folder_path = os.path.join(HLS_FOLDER, folder_name)
                    if os.path.isdir(folder_path):
                        mtime = os.path.getmtime(folder_path)
                        if mtime < cutoff:
                            log_error(f"Cleaning up expired HLS folder: {folder_name}")
                            shutil.rmtree(folder_path)
            
            # Part 2: Auto-repair deduplicated HLS paths
            conn = get_db_connection(); cursor = conn.cursor()
            # Find files that have no hls_path but another file with the same physical path DOES have one
            cursor.execute('''
                UPDATE files 
                SET hls_path = (
                    SELECT hls_path FROM files f2 
                    WHERE f2.path = files.path AND f2.hls_path IS NOT NULL 
                    LIMIT 1
                )
                WHERE hls_path IS NULL 
                AND EXISTS (
                    SELECT 1 FROM files f3 
                    WHERE f3.path = files.path AND f3.hls_path IS NOT NULL
                )
            ''')
            if cursor.rowcount > 0:
                log_error(f"Auto-repaired {cursor.rowcount} deduplicated HLS paths.")
            conn.commit(); conn.close()
            
            # Run every 30 minutes
            time.sleep(1800)
        except Exception as e:
            log_error("Background Maintenance Task Error", e)
            time.sleep(600)

def log_error(message, error=None):
    """Log errors to a file for production debugging"""
    timestamp = get_now_ist().strftime('%Y-%m-%d %H:%M:%S')
    error_msg = f"[{timestamp}] {message}"
    if error:
        error_msg += f" | Error: {str(error)}"
    print(error_msg) # Still print to console
    try:
        with open('app.log', 'a') as f:
            f.write(error_msg + '\n')
            if error and hasattr(error, '__traceback__'):
                import traceback
                traceback.print_exc(file=f)
    except:
        pass # If we can't write to log file, just ignore

# Configuration
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or secrets.token_hex(32)

# Encryption Master Key - CRITICAL for production
_raw_key = os.getenv('ENCRYPTION_KEY') or os.getenv('SECRET_KEY')
if not _raw_key:
    log_error("CRITICAL: No ENCRYPTION_KEY found. Generating a random one. Files will be lost on restart!")
    app.config['ENCRYPTION_KEY'] = secrets.token_bytes(32)
else:
    if isinstance(_raw_key, str):
        _raw_key = _raw_key.encode()
    app.config['ENCRYPTION_KEY'] = _raw_key.ljust(32, b'\0')[:32]

# Constants for chunked encryption
CHUNK_SIZE = 512 * 1024 
IV_SIZE = 16

def get_mimetype(filename):
    """Accurately detect mimetype from filename"""
    mtype, _ = mimetypes.guess_type(filename)
    if not mtype:
        ext = filename.split('.')[-1].lower()
        fallbacks = {
            'mp4': 'video/mp4', 'mkv': 'video/x-matroska', 'mov': 'video/quicktime',
            'webm': 'video/webm', 'avi': 'video/x-msvideo', 'm4v': 'video/x-m4v',
            'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg'
        }
        return fallbacks.get(ext, 'application/octet-stream')
    return mtype

# Make upload folder absolute
_upload_folder = os.getenv('UPLOAD_FOLDER', 'uploads')
if not os.path.isabs(_upload_folder):
    _upload_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), _upload_folder)
app.config['UPLOAD_FOLDER'] = _upload_folder
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024 * 1024  # 100GB max
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'xls', 'xlsx', 'zip', 'rar', 'mp4', 'mov', 'avi', 'mp3', 'wav', 'mkv', 'webm', 'm4v', 'ogg'}

# SQLite Database
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cloud_storage.db')

# Initialize CORS
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Create folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
HLS_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hls')
os.makedirs(HLS_FOLDER, exist_ok=True)

# Resource Management for FFmpeg
MAX_CONCURRENT_CONVERSIONS = 1
hls_semaphore = threading.Semaphore(MAX_CONCURRENT_CONVERSIONS)
assembly_lock = threading.Lock()

def get_db_connection():
    """Create SQLite database connection"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def convert_to_hls(file_id, current_user_id, filepath, original_filename, iv_base64):
    """Background task to convert video to HLS with deduplication awareness"""
    temp_decrypted_path = None
    try:
        # Check if another record already has a valid HLS path for this physical file
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT hls_path FROM files WHERE path = ? AND hls_path IS NOT NULL LIMIT 1', (filepath,))
        existing_hls = cursor.fetchone()
        
        if existing_hls:
            hls_rel_path = existing_hls[0]
            # Verify the file actually exists on disk
            if os.path.exists(os.path.join(HLS_FOLDER, hls_rel_path.split('/')[0])):
                cursor.execute('UPDATE files SET hls_path = ? WHERE id = ?', (hls_rel_path, file_id))
                conn.commit(); cursor.close(); conn.close()
                return

        with hls_semaphore:
            iv = base64.b64decode(iv_base64)
            temp_decrypted_path = filepath + ".dec"
            
            cipher = Cipher(algorithms.AES(app.config['ENCRYPTION_KEY']), modes.CTR(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            
            with open(filepath, 'rb') as f_in, open(temp_decrypted_path, 'wb') as f_out:
                while True:
                    chunk = f_in.read(CHUNK_SIZE)
                    if not chunk: break
                    f_out.write(decryptor.update(chunk))
                f_out.write(decryptor.finalize())
            
            hls_output_dir = os.path.join(HLS_FOLDER, str(file_id))
            os.makedirs(hls_output_dir, exist_ok=True)
            playlist_path = os.path.join(hls_output_dir, "index.m3u8")
            
            ffmpeg_cmd = [
                'ffmpeg', '-y', '-i', temp_decrypted_path,
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
                '-vf', 'scale=-2:720,format=yuv420p',
                '-c:a', 'aac', '-b:a', '128k',
                '-start_number', '0', '-hls_time', '10', '-hls_list_size', '0',
                '-f', 'hls', playlist_path
            ]
            
            process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                log_error(f"FFmpeg failed for {file_id}. Stderr: {stderr.decode()}")
            else:
                hls_rel_path = f"{file_id}/index.m3u8"
                cursor.execute('UPDATE files SET hls_path = ? WHERE path = ?', (hls_rel_path, filepath))
                conn.commit()
        
        cursor.close(); conn.close()
    except Exception as e:
        log_error(f"HLS error for file {file_id}", e)
    finally:
        if temp_decrypted_path and os.path.exists(temp_decrypted_path):
            try: os.remove(temp_decrypted_path)
            except: pass

def init_database():
    """Initialize SQLite database tables"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0, is_blocked INTEGER DEFAULT 0,
            balance REAL DEFAULT 0.0, upi_number TEXT, last_seen TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Add file_hash column if it doesn't exist
        try:
            cursor.execute('ALTER TABLE files ADD COLUMN file_hash TEXT')
        except:
            pass # Already exists
            
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        )''')
        defaults = [
            ('registrations_enabled', 'true'), ('blocked_countries', ''),
            ('cpm_inr', '100'), ('cpm_mobile', '120'), ('cpm_tablet', '110'),
            ('ad_top', ''), ('ad_bottom', ''), ('ad_sidebar', '')
        ]
        for k, v in defaults:
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
            
        cursor.execute('''CREATE TABLE IF NOT EXISTS view_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, share_id INTEGER NOT NULL,
            ip_address TEXT NOT NULL, viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            earned_amount REAL DEFAULT 0.0, FOREIGN KEY (share_id) REFERENCES shares(id) ON DELETE CASCADE
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            name TEXT NOT NULL, parent_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_id) REFERENCES folders(id) ON DELETE CASCADE
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            folder_id INTEGER, filename TEXT NOT NULL, stored_filename TEXT NOT NULL,
            size INTEGER NOT NULL, type TEXT, path TEXT NOT NULL,
            is_encrypted INTEGER DEFAULT 0, iv TEXT, hls_path TEXT,
            file_hash TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE SET NULL
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            file_id INTEGER NOT NULL, filename TEXT NOT NULL, token TEXT NOT NULL,
            password TEXT, expires_at TIMESTAMP, access_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            amount REAL NOT NULL, status TEXT DEFAULT 'pending',
            payment_info TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )''')
        
        # Create default admin
        cursor.execute('SELECT id FROM users WHERE email = ?', ('admin@cloudstorage.com',))
        if not cursor.fetchone():
            cursor.execute('INSERT INTO users (username, email, password, is_admin) VALUES (?, ?, ?, ?)',
                         ('Admin', 'admin@cloudstorage.com', generate_password_hash('admin123'), 1))
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"DB Init Error: {e}")
        return False

# DECORATORS
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get('auth_token') or request.headers.get('Authorization')
        if not token: return jsonify({'message': 'Token missing'}), 401
        try:
            if token.startswith('Bearer '): token = token.split(' ')[1]
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            conn = get_db_connection(); cursor = conn.cursor()
            cursor.execute('SELECT is_blocked FROM users WHERE id = ?', (data['user_id'],))
            user = cursor.fetchone()
            if not user or user[0]: return jsonify({'message': 'Access denied'}), 403
            cursor.execute('UPDATE users SET last_seen = ? WHERE id = ?', (get_now_ist().isoformat(), data['user_id']))
            conn.commit(); cursor.close(); conn.close()
            return f(data['user_id'], *args, **kwargs)
        except: return jsonify({'message': 'Invalid token'}), 401
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(current_user_id, *args, **kwargs):
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT is_admin FROM users WHERE id = ?', (current_user_id,))
        user = cursor.fetchone()
        cursor.close(); conn.close()
        if not user or not user[0]: return jsonify({'message': 'Admin access required'}), 403
        return f(current_user_id, *args, **kwargs)
    return decorated

# AUTH ROUTES
@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT id, username, email, password, is_admin, balance, upi_number FROM users WHERE email = ?', (data.get('email'),))
    user = cursor.fetchone()
    if user and check_password_hash(user[3], data.get('password')):
        token = jwt.encode({'user_id': user[0], 'exp': datetime.datetime.now(timezone.utc) + datetime.timedelta(days=365)}, 
                         app.config['SECRET_KEY'], algorithm='HS256')
        response = jsonify({'token': token, 'user': {'id': user[0], 'username': user[1], 'is_admin': bool(user[4]), 'balance': user[5], 'upi_number': user[6]}})
        response.set_cookie('auth_token', token, httponly=True, max_age=365*24*3600)
        return response
    return jsonify({'message': 'Invalid credentials'}), 401

@app.route('/api/user/update-upi', methods=['POST'])
@token_required
def update_upi(uid):
    data = request.get_json()
    upi_no = data.get('upi_no')
    if not upi_no or len(upi_no) != 10 or not upi_no.isdigit():
        return jsonify({'message': 'Invalid 10-digit UPI number'}), 400
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('UPDATE users SET upi_number = ? WHERE id = ?', (upi_no, uid))
    conn.commit(); cursor.close(); conn.close()
    return jsonify({'message': 'UPI saved successfully'})

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.get_json()
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'registrations_enabled'")
    if cursor.fetchone()[0] == 'false': return jsonify({'message': 'Registrations disabled'}), 403
    try:
        cursor.execute('INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
                     (data['username'], data['email'], generate_password_hash(data['password'])))
        conn.commit(); return jsonify({'message': 'Success'}), 201
    except: return jsonify({'message': 'Email exists'}), 400
    finally: cursor.close(); conn.close()

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    res = jsonify({'message': 'Logged out'}); res.delete_cookie('auth_token'); return res

@app.route('/api/files/<int:file_id>', methods=['GET', 'DELETE'])
@token_required
def manage_file(uid, file_id):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT filename, path, iv, is_encrypted, user_id, type FROM files WHERE id = ?', (file_id,))
    f = cursor.fetchone()
    if not f: return jsonify({'message': 'File not found'}), 404
    
    # Check if the file belongs to the user OR if it's shared (for preview/download)
    # Note: for preview/download, we should ideally check share token, but let's keep it simple for now as per current structure
    if f[4] != uid:
        # Check if user is admin
        cursor.execute('SELECT is_admin FROM users WHERE id = ?', (uid,))
        is_admin = cursor.fetchone()[0]
        if not is_admin:
            return jsonify({'message': 'Unauthorized'}), 403

    if request.method == 'DELETE':
        # Check if other records point to the same physical file (Deduplication check)
        cursor.execute('SELECT COUNT(*) FROM files WHERE path = ?', (f[1],))
        ref_count = cursor.fetchone()[0]
        
        if ref_count <= 1:
            if os.path.exists(f[1]): os.remove(f[1])
            h_dir = os.path.join(HLS_FOLDER, str(file_id))
            if os.path.exists(h_dir): shutil.rmtree(h_dir)
        else:
            log_error(f"File {file_id} deleted by user {uid}, but physical file kept due to {ref_count-1} other references.")
            
        cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
        conn.commit(); return jsonify({'message': 'Deleted'})
    
    # GET (Download/Preview)
    try:
        if not f[3]: # Not encrypted
            return send_file(f[1], as_attachment=not request.args.get('preview'), download_name=f[0], mimetype=f[5])
        
        # Encrypted: Decrypt on the fly
        iv = base64.b64decode(f[2])
        def generate():
            cipher = Cipher(algorithms.AES(app.config['ENCRYPTION_KEY']), modes.CTR(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            with open(f[1], 'rb') as file:
                while True:
                    chunk = file.read(CHUNK_SIZE)
                    if not chunk: break
                    yield decryptor.update(chunk)
                yield decryptor.finalize()
        
        headers = {'Content-Disposition': f"{'inline' if request.args.get('preview') else 'attachment'}; filename={f[0]}"}
        return Response(stream_with_context(generate()), headers=headers, mimetype=f[5])
    except Exception as e:
        log_error(f"Download error for {file_id}", e)
        return jsonify({'message': 'Download failed'}), 500

@app.route('/api/shares/download/<token>', methods=['GET', 'POST'])
def share_download(token):
    data = request.get_json(silent=True) or {}
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT id, file_id, password FROM shares WHERE token = ?', (token,))
    share = cursor.fetchone()
    if not share: return jsonify({'message': 'Not found'}), 404
    
    if share[2] and (not data.get('password') or not check_password_hash(share[2], data['password'])):
        return jsonify({'message': 'Password required'}), 401
    
    cursor.execute('SELECT filename, path, iv, is_encrypted, type FROM files WHERE id = ?', (share[1],))
    f = cursor.fetchone()
    
    try:
        if not f[3]: # Not encrypted
            return send_file(f[1], as_attachment=not request.args.get('preview'), download_name=f[0], mimetype=f[4])
        
        # Encrypted: Decrypt on the fly
        iv = base64.b64decode(f[2])
        def generate():
            cipher = Cipher(algorithms.AES(app.config['ENCRYPTION_KEY']), modes.CTR(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            with open(f[1], 'rb') as file:
                while True:
                    chunk = file.read(CHUNK_SIZE)
                    if not chunk: break
                    yield decryptor.update(chunk)
                yield decryptor.finalize()
        
        headers = {'Content-Disposition': f"{'inline' if request.args.get('preview') else 'attachment'}; filename={f[0]}"}
        return Response(stream_with_context(generate()), headers=headers, mimetype=f[4])
    except Exception as e:
        log_error(f"Share download error for {token}", e)
        return jsonify({'message': 'Download failed'}), 500

# USER ROUTES
@app.route('/api/user/stats', methods=['GET'])
@token_required
def user_stats(uid):
    conn = get_db_connection(); cursor = conn.cursor()
    # Get basic user info
    cursor.execute('SELECT balance FROM users WHERE id = ?', (uid,))
    bal = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*), SUM(size) FROM files WHERE user_id = ?', (uid,))
    f_stats = cursor.fetchone()
    
    # Time ranges in IST
    now_ist = get_now_ist()
    today_start = now_ist.replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
    yesterday_start = (now_ist - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
    last_7_days = (now_ist - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    this_month_start = now_ist.replace(day=1, hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')

    # Views stats
    stats_queries = {
        'today': ('SELECT COUNT(*) FROM view_logs vl JOIN shares s ON vl.share_id = s.id WHERE s.user_id = ? AND vl.viewed_at >= ?', (uid, today_start)),
        'yesterday': ('SELECT COUNT(*) FROM view_logs vl JOIN shares s ON vl.share_id = s.id WHERE s.user_id = ? AND vl.viewed_at >= ? AND vl.viewed_at < ?', (uid, yesterday_start, today_start)),
        'last_7_days': ('SELECT COUNT(*) FROM view_logs vl JOIN shares s ON vl.share_id = s.id WHERE s.user_id = ? AND vl.viewed_at >= ?', (uid, last_7_days)),
        'this_month': ('SELECT COUNT(*) FROM view_logs vl JOIN shares s ON vl.share_id = s.id WHERE s.user_id = ? AND vl.viewed_at >= ?', (uid, this_month_start)),
        'total': ('SELECT COUNT(*) FROM view_logs vl JOIN shares s ON vl.share_id = s.id WHERE s.user_id = ?', (uid,))
    }
    
    views_data = {}
    for key, (query, params) in stats_queries.items():
        cursor.execute(query, params)
        views_data[key] = cursor.fetchone()[0]

    # Calculate Average CPM (Total Earned / Total Views * 1000)
    cursor.execute('SELECT SUM(earned_amount) FROM view_logs vl JOIN shares s ON vl.share_id = s.id WHERE s.user_id = ?', (uid,))
    total_earned = cursor.fetchone()[0] or 0.0
    avg_cpm = (total_earned / views_data['total'] * 1000) if views_data['total'] > 0 else 0.0

    # Get recent view activity
    cursor.execute('''
        SELECT vl.ip_address, vl.viewed_at, vl.earned_amount, s.filename
        FROM view_logs vl
        JOIN shares s ON vl.share_id = s.id
        WHERE s.user_id = ?
        ORDER BY vl.viewed_at DESC
        LIMIT 10
    ''', (uid,))
    activity = []
    for row in cursor.fetchall():
        time_str = row[1]
        if time_str and ' ' in time_str: time_str = time_str.replace(' ', 'T')
        activity.append({
            'ip': row[0],
            'time': time_str,
            'earned': row[2],
            'filename': row[3]
        })
    
    return jsonify({
        'balance': bal, 
        'total_files': f_stats[0], 
        'storage_used': f"{(f_stats[1] or 0)/(1024*1024):.2f} MB", 
        'total_views': views_data['total'],
        'views_today': views_data['today'],
        'views_yesterday': views_data['yesterday'],
        'views_7days': views_data['last_7_days'],
        'views_month': views_data['this_month'],
        'avg_cpm': avg_cpm,
        'total_earned': total_earned,
        'recent_activity': activity
    })

@app.route('/api/files', methods=['GET'])
@token_required
def list_files(uid):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''
        SELECT f.id, f.filename, f.size, f.type, f.uploaded_at, f.hls_path,
               (SELECT COUNT(*) FROM view_logs vl JOIN shares s ON vl.share_id = s.id WHERE s.file_id = f.id) as total_views
        FROM files f 
        WHERE f.user_id = ? 
        ORDER BY f.uploaded_at DESC
    ''', (uid,))
    files = [dict(row) for row in cursor.fetchall()]
    return jsonify({'files': files})

@app.route('/api/files/upload', methods=['POST'])
@token_required
def upload(uid):
    file = request.files.get('file')
    if not file:
        return jsonify({'message': 'No file provided'}), 400
        
    filename = secure_filename(file.filename)
    log_error(f"Starting upload for {filename} (User {uid})")
    
    # Ensure user folder exists
    u_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(uid))
    os.makedirs(u_dir, exist_ok=True)
    
    # Generate a unique stored name
    stored_name = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
    final_path = os.path.join(u_dir, stored_name)
    
    iv = secrets.token_bytes(16)
    cipher = Cipher(algorithms.AES(app.config['ENCRYPTION_KEY']), modes.CTR(iv), backend=default_backend())
    enc = cipher.encryptor()
    
    sha256_hash = hashlib.sha256()
    size = 0
    
    try:
        # Write directly to the final path to avoid slow moves
        with open(final_path, 'wb') as f:
            while True:
                chunk = file.read(CHUNK_SIZE)
                if not chunk: break
                
                # Update hash with RAW data
                sha256_hash.update(chunk)
                size += len(chunk)
                
                # Write ENCRYPTED data
                f.write(enc.update(chunk))
            f.write(enc.finalize())
            
        file_hash = sha256_hash.hexdigest()
        log_error(f"File {filename} written. Size: {size} bytes. Hash: {file_hash}")
        
        # Check for deduplication
        conn = get_db_connection(); cursor = conn.cursor()
        try:
            cursor.execute('''SELECT stored_filename, path, iv, hls_path FROM files 
                           WHERE file_hash = ? AND size = ? 
                           ORDER BY hls_path DESC LIMIT 1''', 
                         (file_hash, size))
            existing = cursor.fetchone()
            
            if existing:
                # Deduplicate! Delete the file we just wrote and use existing info
                os.remove(final_path)
                stored_name, existing_path, existing_iv, hls_path = existing
                log_error(f"Deduplicated upload: {filename} -> existing {stored_name}")
                
                cursor.execute('''INSERT INTO files 
                               (user_id, filename, stored_filename, size, type, path, is_encrypted, iv, hls_path, file_hash) 
                               VALUES (?,?,?,?,?,?,?,?,?,?)''',
                             (uid, filename, stored_name, size, file.content_type, existing_path, 1, existing_iv, hls_path, file_hash))
                fid = cursor.lastrowid
                conn.commit()
                
                if file.content_type.startswith('video/') and not hls_path:
                    threading.Thread(target=convert_to_hls, args=(fid, uid, existing_path, filename, existing_iv)).start()
                    
                return jsonify({'message': 'Uploaded (Deduplicated)', 'id': fid}), 201
            
            # Not a duplicate: File is already in its final location
            cursor.execute('''INSERT INTO files 
                           (user_id, filename, stored_filename, size, type, path, is_encrypted, iv, file_hash) 
                           VALUES (?,?,?,?,?,?,?,?,?)''',
                         (uid, filename, stored_name, size, file.content_type, final_path, 1, base64.b64encode(iv).decode(), file_hash))
            fid = cursor.lastrowid
            conn.commit()
            log_error(f"Upload complete for {filename}. Record ID: {fid}")
            
            if file.content_type.startswith('video/'):
                threading.Thread(target=convert_to_hls, args=(fid, uid, final_path, filename, base64.b64encode(iv).decode())).start()
                
            return jsonify({'message': 'Uploaded', 'id': fid}), 201
        finally:
            cursor.close(); conn.close()
            
    except Exception as e:
        if os.path.exists(final_path): os.remove(final_path)
        log_error(f"Upload error for {filename}", e)
        return jsonify({'message': f'Upload failed: {str(e)}'}), 500

@app.route('/api/files/upload/chunk', methods=['POST'])
@token_required
def upload_chunk(uid):
    file = request.files.get('file')
    upload_id = request.form.get('upload_id')
    chunk_index = int(request.form.get('chunk_index'))
    total_chunks = int(request.form.get('total_chunks'))
    filename = secure_filename(request.form.get('filename'))
    content_type = request.form.get('content_type')
    
    # Store chunks in a subfolder named by upload_id
    chunk_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'chunks', upload_id)
    os.makedirs(chunk_dir, exist_ok=True)
    
    chunk_path = os.path.join(chunk_dir, f"{chunk_index}.part")
    
    # Check if chunk already exists (might happen on retries)
    if not os.path.exists(chunk_path):
        file.save(chunk_path)
    
    # Check if this was the last chunk
    parts = [f for f in os.listdir(chunk_dir) if f.endswith('.part')]
    
    if len(parts) == total_chunks:
        # Use a global lock to prevent multiple threads from assembling the same file
        with assembly_lock:
            # Re-check if assembly is still needed (another thread might have finished it)
            if not os.path.exists(chunk_dir):
                return jsonify({'message': 'Upload Complete (Assembled by another thread)', 'id': None}), 200
            
            log_error(f"Assembling {total_chunks} chunks for {filename} (Upload: {upload_id})")
            
            u_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(uid))
            os.makedirs(u_dir, exist_ok=True)
            stored_name = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            final_path = os.path.join(u_dir, stored_name)
            
            iv = secrets.token_bytes(16)
            cipher = Cipher(algorithms.AES(app.config['ENCRYPTION_KEY']), modes.CTR(iv), backend=default_backend())
            enc = cipher.encryptor()
            sha256_hash = hashlib.sha256()
            size = 0
            
            try:
                with open(final_path, 'wb') as f_out:
                    for i in range(total_chunks):
                        p = os.path.join(chunk_dir, f"{i}.part")
                        if not os.path.exists(p):
                            raise Exception(f"Missing chunk {i} during assembly")
                            
                        with open(p, 'rb') as f_in:
                            while True:
                                chunk_data = f_in.read(CHUNK_SIZE)
                                if not chunk_data: break
                                sha256_hash.update(chunk_data)
                                size += len(chunk_data)
                                f_out.write(enc.update(chunk_data))
                        
                        # Delete part immediately after reading to free space
                        try: os.remove(p)
                        except: pass
                
                f_out.write(enc.finalize())
                
                # Clean up empty chunk directory
                try: shutil.rmtree(chunk_dir)
                except: pass
                
                file_hash = sha256_hash.hexdigest()
                log_error(f"Assembly complete: {filename}, Size: {size}, Hash: {file_hash}")
                
                # Database record (Deduplication Check)
                conn = get_db_connection(); cursor = conn.cursor()
                try:
                    cursor.execute('SELECT stored_filename, path, iv, hls_path FROM files WHERE file_hash = ? AND size = ? LIMIT 1', (file_hash, size))
                    existing = cursor.fetchone()
                    
                    if existing:
                        # Deduplicate: use existing file on disk
                        os.remove(final_path)
                        stored_name, existing_path, existing_iv, hls_path = existing
                        cursor.execute('INSERT INTO files (user_id, filename, stored_filename, size, type, path, is_encrypted, iv, hls_path, file_hash) VALUES (?,?,?,?,?,?,?,?,?,?)',
                                     (uid, filename, stored_name, size, content_type, existing_path, 1, existing_iv, hls_path, file_hash))
                    else:
                        # New file
                        cursor.execute('INSERT INTO files (user_id, filename, stored_filename, size, type, path, is_encrypted, iv, file_hash) VALUES (?,?,?,?,?,?,?,?,?)',
                                     (uid, filename, stored_name, size, content_type, final_path, 1, base64.b64encode(iv).decode(), file_hash))
                    
                    fid = cursor.lastrowid
                    conn.commit()
                    
                    # Start HLS if video
                if content_type.startswith('video/'):
                    p_to_conv = final_path if not existing else existing[1]
                    iv_to_use = base64.b64encode(iv).decode() if not existing else existing[2]
                    threading.Thread(target=convert_to_hls, args=(fid, uid, p_to_conv, filename, iv_to_use)).start()
                
                resp = jsonify({'message': 'Upload Complete', 'id': fid})
                resp.headers['Connection'] = 'close'
                return resp, 201
            finally:
                cursor.close(); conn.close()
                
        except Exception as e:
            if os.path.exists(final_path): os.remove(final_path)
            log_error(f"Assembly failed for {filename}", e)
            return jsonify({'message': f'Assembly failed: {str(e)}'}), 500
            
    return jsonify({'message': f'Chunk {chunk_index} accepted'}), 200

# SHARE ROUTES
@app.route('/api/shares', methods=['GET'])
@token_required
def list_shares(uid):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT id, file_id, filename, token, expires_at, access_count FROM shares WHERE user_id = ? ORDER BY created_at DESC', (uid,))
    shares = []
    for row in cursor.fetchall():
        s = dict(row)
        s['url'] = f"{request.host_url}{s['token']}"
        shares.append(s)
    return jsonify({'shares': shares})

@app.route('/api/shares/create', methods=['POST'])
@token_required
def create_share(uid):
    data = request.get_json()
    fid = data.get('file_id')
    pwd = data.get('password')
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT filename FROM files WHERE id = ? AND user_id = ?', (fid, uid))
    file = cursor.fetchone()
    if not file: return jsonify({'message': 'Not found'}), 404
    
    token = secrets.token_urlsafe(9)[:12]
    cursor.execute('INSERT INTO shares (user_id, file_id, filename, token, password) VALUES (?,?,?,?,?)',
                 (uid, fid, file[0], token, generate_password_hash(pwd) if pwd else None))
    conn.commit()
    return jsonify({
        'message': 'Share link created',
        'share': {
            'url': f"{request.host_url}{token}",
            'token': token
        }
    }), 201

@app.route('/api/shares/info/<token>', methods=['GET', 'POST'])
def share_info(token):
    data = request.get_json(silent=True) or {}
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT id, file_id, password, user_id FROM shares WHERE token = ?', (token,))
    share = cursor.fetchone()
    if not share: return jsonify({'message': 'Not found'}), 404
    
    if share[2] and (not data.get('password') or not check_password_hash(share[2], data['password'])):
        cursor.execute("SELECT key, value FROM settings WHERE key LIKE 'ad_%'")
        return jsonify({'password_required': True, 'ads': {r[0]: r[1] for r in cursor.fetchall()}}), 401
    
    # PPV Logic
    ip = request.headers.get('X-Real-IP') or request.headers.get('X-Forwarded-For') or request.remote_addr
    if ',' in ip: ip = ip.split(',')[0].strip() # Handle multiple proxies
    
    # Calculate 24 hours ago in IST
    now_ist = get_now_ist()
    one_day_ago = (now_ist - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    
    # Strictly 1 view per 24 hours per IP globally (Reset in 24 hours)
    cursor.execute('''
        SELECT id FROM view_logs 
        WHERE ip_address = ? 
        AND viewed_at > ?
    ''', (ip, one_day_ago))
    
    if not cursor.fetchone():
        # Detect device type for CPM
        ua = request.headers.get('User-Agent', '').lower()
        device_key = 'cpm_inr' # Default/Laptop
        if 'mobile' in ua:
            device_key = 'cpm_mobile'
        elif 'tablet' in ua or 'ipad' in ua:
            device_key = 'cpm_tablet'
            
        cursor.execute("SELECT value FROM settings WHERE key = ?", (device_key,))
        cpm_value = cursor.fetchone()
        rate = float(cpm_value[0] if cpm_value else 100.0) / 1000.0
        
        # Use current IST timestamp for logging
        now_str = now_ist.strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('INSERT INTO view_logs (share_id, ip_address, earned_amount, viewed_at) VALUES (?,?,?,?)', 
                     (share[0], ip, rate, now_str))
        cursor.execute('UPDATE users SET balance = balance + ? WHERE id = ?', (rate, share[3]))
        cursor.execute('UPDATE shares SET access_count = access_count + 1 WHERE id = ?', (share[0],))
        conn.commit()
        
    cursor.execute('SELECT filename, size, type, hls_path, uploaded_at FROM files WHERE id = ?', (share[1],))
    f = cursor.fetchone()
    cursor.execute('SELECT expires_at FROM shares WHERE id = ?', (share[0],))
    s_expires = cursor.fetchone()
    
    u_at = f[4]
    if u_at and ' ' in u_at: u_at = u_at.replace(' ', 'T')
    e_at = s_expires[0]
    if e_at and ' ' in e_at: e_at = e_at.replace(' ', 'T')
    
    cursor.execute("SELECT key, value FROM settings WHERE key LIKE 'ad_%'")
    return jsonify({
        'filename': f[0], 
        'size': f[1], 
        'type': f[2], 
        'hls_path': f[3], 
        'uploaded_at': u_at,
        'expires_at': e_at,
        'ads': {r[0]: r[1] for r in cursor.fetchall()}, 
        'file_id': share[1]
    })

@app.route('/api/user/request-payment', methods=['POST'])
@token_required
def request_payment(uid):
    data = request.get_json()
    upi_no = data.get('upi_no')
    
    if not upi_no or len(upi_no) != 10 or not upi_no.isdigit():
        return jsonify({'message': 'Please provide a valid 10-digit UPI number'}), 400

    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT balance FROM users WHERE id = ?', (uid,))
    balance = cursor.fetchone()[0]
    
    if balance < 50:
        return jsonify({'message': 'Minimum balance for withdrawal is ₹50'}), 400
    
    # Check for existing pending request
    cursor.execute('SELECT id FROM payments WHERE user_id = ? AND status = "pending"', (uid,))
    if cursor.fetchone():
        return jsonify({'message': 'You already have a pending payment request'}), 400
    
    cursor.execute('INSERT INTO payments (user_id, amount, payment_info) VALUES (?, ?, ?)', (uid, balance, upi_no))
    # Deduct balance immediately or wait until processed? 
    # Usually better to deduct or freeze it. Let's deduct and if rejected, refund.
    cursor.execute('UPDATE users SET balance = 0 WHERE id = ?', (uid,))
    
    conn.commit()
    return jsonify({'message': 'Payment request submitted successfully'})

@app.route('/api/user/payments', methods=['GET'])
@token_required
def get_user_payments(uid):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT id, amount, status, payment_info, created_at, processed_at FROM payments WHERE user_id = ? ORDER BY created_at DESC', (uid,))
    return jsonify({'payments': [dict(row) for row in cursor.fetchall()]})

# ADMIN ROUTES
@app.route('/api/admin/payments', methods=['GET'])
@token_required
@admin_required
def admin_payments(uid):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''
        SELECT p.id, p.amount, p.status, p.payment_info, p.created_at, p.processed_at, u.username, u.email
        FROM payments p
        JOIN users u ON p.user_id = u.id
        ORDER BY p.created_at DESC
    ''')
    return jsonify({'payments': [dict(row) for row in cursor.fetchall()]})

@app.route('/api/admin/payments/<int:payment_id>/action', methods=['POST'])
@token_required
@admin_required
def admin_payment_action(uid, payment_id):
    data = request.get_json()
    action = data.get('action') # 'release' or 'reject'
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT user_id, amount, status FROM payments WHERE id = ?', (payment_id,))
    payment = cursor.fetchone()
    if not payment: return jsonify({'message': 'Payment not found'}), 404
    if payment[2] != 'pending': return jsonify({'message': 'Payment already processed'}), 400
    
    now_ist = get_now_ist().isoformat()
    if action == 'release':
        cursor.execute('UPDATE payments SET status = "completed", processed_at = ? WHERE id = ?', (now_ist, payment_id))
    elif action == 'reject':
        cursor.execute('UPDATE payments SET status = "rejected", processed_at = ? WHERE id = ?', (now_ist, payment_id))
        # Refund balance
        cursor.execute('UPDATE users SET balance = balance + ? WHERE id = ?', (payment[1], payment[0]))
    else:
        return jsonify({'message': 'Invalid action'}), 400
        
    conn.commit()
    return jsonify({'message': f'Payment {action}ed'})

@app.route('/api/admin/sync-files', methods=['POST'])
@token_required
@admin_required
def admin_sync_files(uid):
    """Check files on disk and remove missing ones from database"""
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT id, path, hls_path FROM files')
    files = cursor.fetchall()
    
    removed_count = 0
    fixed_hls_count = 0
    for f in files:
        file_id, path, hls_path = f
        if not os.path.exists(path):
            # File missing on disk, remove from DB
            cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
            # Also cleanup HLS if it exists
            h_dir = os.path.join(HLS_FOLDER, str(file_id))
            if os.path.exists(h_dir): shutil.rmtree(h_dir)
            removed_count += 1
        elif not hls_path:
            # Check if another file record with same path has HLS
            cursor.execute('SELECT hls_path FROM files WHERE path = ? AND hls_path IS NOT NULL LIMIT 1', (path,))
            other_hls = cursor.fetchone()
            if other_hls:
                cursor.execute('UPDATE files SET hls_path = ? WHERE id = ?', (other_hls[0], file_id))
                fixed_hls_count += 1
            
    conn.commit()
    return jsonify({'message': f'Sync complete. Removed {removed_count} missing files. Fixed {fixed_hls_count} deduplicated HLS paths.'})

@app.route('/api/admin/stats', methods=['GET'])
@token_required
@admin_required
def admin_stats(uid):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users'); u_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM shares'); s_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM view_logs'); v_count = cursor.fetchone()[0]
    cursor.execute('SELECT SUM(balance) FROM users'); earnings = cursor.fetchone()[0] or 0
    return jsonify({'total_users': u_count, 'total_shares': s_count, 'total_views': v_count, 'total_earnings': earnings})

@app.route('/api/admin/users', methods=['GET'])
@token_required
@admin_required
def admin_users(uid):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''SELECT u.id, u.username, u.email, u.is_blocked, u.balance, u.created_at,
                   (SELECT COUNT(*) FROM view_logs vl JOIN shares s ON vl.share_id = s.id WHERE s.user_id = u.id) as total_views
                   FROM users u ORDER BY created_at DESC''')
    return jsonify({'users': [dict(row) for row in cursor.fetchall()]})

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@token_required
@admin_required
def admin_delete_user(uid, user_id):
    if uid == user_id: return jsonify({'message': 'Self-delete blocked'}), 400
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT id, path FROM files WHERE user_id = ?', (user_id,))
    for f in cursor.fetchall():
        fid, path = f
        # Check reference count
        cursor.execute('SELECT COUNT(*) FROM files WHERE path = ?', (path,))
        ref_count = cursor.fetchone()[0]
        
        if ref_count <= 1:
            if os.path.exists(path): os.remove(path)
            h_dir = os.path.join(HLS_FOLDER, str(fid))
            if os.path.exists(h_dir): shutil.rmtree(h_dir)
            
    cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit(); return jsonify({'message': 'Deleted'})

@app.route('/api/admin/files', methods=['GET'])
@token_required
@admin_required
def admin_files(uid):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''
        SELECT f.id, f.filename, f.size, f.uploaded_at, u.username as owner, u.email as owner_email, f.type, f.hls_path,
               (SELECT COUNT(*) FROM view_logs vl JOIN shares s ON vl.share_id = s.id WHERE s.file_id = f.id) as total_views
        FROM files f 
        JOIN users u ON f.user_id = u.id 
        ORDER BY f.uploaded_at DESC 
        LIMIT 500
    ''')
    return jsonify({'files': [dict(row) for row in cursor.fetchall()]})

@app.route('/api/admin/files/<int:file_id>', methods=['DELETE'])
@token_required
@admin_required
def admin_delete_file(uid, file_id):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT path FROM files WHERE id = ?', (file_id,))
    row = cursor.fetchone()
    if row:
        path = row[0]
        # Check reference count
        cursor.execute('SELECT COUNT(*) FROM files WHERE path = ?', (path,))
        ref_count = cursor.fetchone()[0]
        
        if ref_count <= 1:
            if os.path.exists(path): os.remove(path)
            h_dir = os.path.join(HLS_FOLDER, str(file_id))
            if os.path.exists(h_dir): shutil.rmtree(h_dir)
            
    cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
    conn.commit(); return jsonify({'message': 'Deleted'})

@app.route('/api/admin/settings', methods=['GET', 'POST'])
@token_required
@admin_required
def admin_settings(uid):
    conn = get_db_connection(); cursor = conn.cursor()
    if request.method == 'POST':
        for k, v in request.get_json().items():
            cursor.execute('UPDATE settings SET value = ? WHERE key = ?', (str(v), k))
        conn.commit(); return jsonify({'message': 'Updated'})
    cursor.execute('SELECT key, value FROM settings')
    return jsonify({row[0]: row[1] for row in cursor.fetchall()})

@app.route('/api/admin/users/<int:user_id>/block', methods=['POST'])
@token_required
@admin_required
def admin_block(uid, user_id):
    data = request.get_json()
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_blocked = ? WHERE id = ?', (1 if data.get('block') else 0, user_id))
    conn.commit(); return jsonify({'message': 'Success'})

# SERVE HLS
@app.route('/hls/<int:file_id>/<path:filename>')
def serve_hls(file_id, filename):
    return send_from_directory(os.path.join(HLS_FOLDER, str(file_id)), filename)

# STATIC & SHARE PAGE
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_all(path):
    if not path:
        return send_from_directory('static', 'index.html')
    
    # Check if it's a potential share token (12 chars, no dots)
    if len(path) == 12 and '.' not in path:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT id FROM shares WHERE token = ?', (path,))
        if cursor.fetchone():
            return send_from_directory('static', 'share.html')
    
    # Try serving as static file
    return send_from_directory('static', path)

if __name__ == '__main__':
    # Start HLS cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_hls_task, daemon=True)
    cleanup_thread.start()
    
    if init_database(): app.run(debug=True, host='0.0.0.0', port=5000)
