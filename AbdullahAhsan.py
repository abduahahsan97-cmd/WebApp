from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, flash
import pyodbc
from azure.storage.blob import BlobServiceClient
import os
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import json
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from textblob import TextBlob
import cv2
import tempfile

app = Flask(__name__)
app.secret_key = 'b9e4f7a1c02d8e93f67a4c5d2e8ab91ff4763a6d85c24790'

AZURE_SQL_SERVER = "abdu11ah.database.windows.net"
AZURE_SQL_DATABASE = "abdullah12"
AZURE_SQL_USERNAME = "admin123"
AZURE_SQL_PASSWORD = "Ahsan@1122"

AZURE_STORAGE_CONNECTION_STRING = "DefaultEndpointsProtocol=https;AccountName=abdu11ah;AccountKey=7PXUIFd1PDuYx1IExm39t1C7fQGXxdIpKxpalhSrs+uVmoZ5S+P5GuE4X6dt1JhfZY5RmkE+iqI8+ASt5IUHTw==;EndpointSuffix=core.windows.net"
AZURE_STORAGE_CONTAINER = 'videos'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, user_type):
        self.id = id
        self.username = username
        self.user_type = user_type

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, user_type FROM users WHERE id = ?", user_id)
    user_data = cursor.fetchone()
    conn.close()
    if user_data:
        return User(user_data[0], user_data[1], user_data[2])
    return None

def get_db_connection():
    connection_string = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={AZURE_SQL_SERVER};DATABASE={AZURE_SQL_DATABASE};UID={AZURE_SQL_USERNAME};PWD={AZURE_SQL_PASSWORD}'
    return pyodbc.connect(connection_string)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='users' AND xtype='U')
        CREATE TABLE users (
            id INT IDENTITY(1,1) PRIMARY KEY,
            username NVARCHAR(50) UNIQUE NOT NULL,
            email NVARCHAR(100) UNIQUE NOT NULL,
            password_hash NVARCHAR(255) NOT NULL,
            user_type NVARCHAR(10) NOT NULL,
            created_at DATETIME DEFAULT GETDATE()
        )
    ''')

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='videos' AND xtype='U')
        CREATE TABLE videos (
            id INT IDENTITY(1,1) PRIMARY KEY,
            title NVARCHAR(200) NOT NULL,
            publisher NVARCHAR(100) NOT NULL,
            producer NVARCHAR(100) NOT NULL,
            genre NVARCHAR(50) NOT NULL,
            age_rating NVARCHAR(10) NOT NULL,
            video_url NVARCHAR(500) NOT NULL,
            thumbnail_url NVARCHAR(500),
            creator_id INT NOT NULL,
            created_at DATETIME DEFAULT GETDATE(),
            FOREIGN KEY (creator_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ratings' AND xtype='U')
        CREATE TABLE ratings (
            id INT IDENTITY(1,1) PRIMARY KEY,
            video_id INT NOT NULL,
            user_id INT NOT NULL,
            rating INT NOT NULL,
            created_at DATETIME DEFAULT GETDATE(),
            FOREIGN KEY (video_id) REFERENCES videos(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='comments' AND xtype='U')
        CREATE TABLE comments (
            id INT IDENTITY(1,1) PRIMARY KEY,
            video_id INT NOT NULL,
            user_id INT NOT NULL,
            comment NVARCHAR(500) NOT NULL,
            sentiment NVARCHAR(10),
            created_at DATETIME DEFAULT GETDATE(),
            FOREIGN KEY (video_id) REFERENCES videos(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    conn.commit()
    conn.close()

blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)

@app.route('/')
def home():
    return render_template_string(HOME_TEMPLATE)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        user_type = request.form['user_type']

        password_hash = generate_password_hash(password)

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, user_type) VALUES (?, ?, ?, ?)",
                username, email, password_hash, user_type
            )
            conn.commit()
            conn.close()
            flash('Registration successful!', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Username or email already exists!', 'error')

    return render_template_string(REGISTER_TEMPLATE)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password_hash, user_type FROM users WHERE username = ?", username)
        user_data = cursor.fetchone()
        conn.close()

        if user_data and check_password_hash(user_data[2], password):
            user = User(user_data[0], user_data[1], user_data[3])
            login_user(user)
            if user.user_type == 'creator':
                return redirect(url_for('creator_dashboard'))
            else:
                return redirect(url_for('consumer_dashboard'))
        else:
            flash('Invalid credentials!', 'error')

    return render_template_string(LOGIN_TEMPLATE)

@app.route('/creator-dashboard')
@login_required
def creator_dashboard():
    if current_user.user_type != 'creator':
        return redirect(url_for('login'))
    return render_template_string(CREATOR_DASHBOARD_TEMPLATE)

@app.route('/consumer-dashboard')
@login_required
def consumer_dashboard():
    if current_user.user_type != 'consumer':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
                   SELECT v.id,
                          v.title,
                          v.publisher,
                          v.producer,
                          v.genre,
                          v.age_rating,
                          v.video_url,
                          AVG(CAST(r.rating AS FLOAT)) as avg_rating,
                          v.thumbnail_url
                   FROM videos v
                   LEFT JOIN ratings r ON v.id = r.video_id
                   GROUP BY v.id, v.title, v.publisher, v.producer, v.genre, v.age_rating, v.video_url, v.created_at, v.thumbnail_url
                   ORDER BY v.created_at DESC
                   ''')
    videos = cursor.fetchall()

    # Fetch user ratings
    user_ratings = {}
    cursor.execute('''
        SELECT video_id, rating
        FROM ratings
        WHERE user_id = ?
    ''', current_user.id)
    for row in cursor.fetchall():
        user_ratings[row[0]] = row[1]

    # Fetch comments
    comments_dict = {}
    cursor.execute('''
        SELECT c.video_id, u.username, c.comment, c.created_at, c.sentiment
        FROM comments c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.created_at DESC
    ''')
    all_comments = cursor.fetchall()
    for comment in all_comments:
        vid = comment[0]
        if vid not in comments_dict:
            comments_dict[vid] = []
        comments_dict[vid].append({
            'username': comment[1],
            'comment': comment[2],
            'created_at': comment[3].strftime('%Y-%m-%d %H:%M:%S'),
            'sentiment': comment[4]
        })

    conn.close()

    return render_template_string(CONSUMER_DASHBOARD_TEMPLATE, videos=videos, user_ratings=user_ratings, comments=comments_dict)

@app.route('/upload-video', methods=['POST'])
@login_required
def upload_video():
    if current_user.user_type != 'creator':
        return redirect(url_for('login'))

    title = request.form['title']
    publisher = request.form['publisher']
    producer = request.form['producer']
    genre = request.form['genre']
    age_rating = request.form['age_rating']
    video_file = request.files['video']

    if video_file:
        filename = secure_filename(video_file.filename)
        blob_name = f"{uuid.uuid4()}_{filename}"

        try:
            # Save video to temp file
            with tempfile.NamedTemporaryFile(delete=False) as temp_video:
                video_file.save(temp_video.name)
                temp_video_path = temp_video.name

            # Upload video
            blob_client = blob_service_client.get_blob_client(
                container=AZURE_STORAGE_CONTAINER,
                blob=blob_name
            )
            with open(temp_video_path, "rb") as f:
                blob_client.upload_blob(f, overwrite=True)
            video_url = blob_client.url

            # Generate thumbnail
            thumbnail_url = None
            cap = cv2.VideoCapture(temp_video_path)
            success, frame = cap.read()
            if success:
                thumbnail_blob_name = f"{uuid.uuid4()}_thumb.jpg"
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_thumb:
                    cv2.imwrite(temp_thumb.name, frame)
                    temp_thumb_path = temp_thumb.name

                blob_client_thumb = blob_service_client.get_blob_client(
                    container=AZURE_STORAGE_CONTAINER,
                    blob=thumbnail_blob_name
                )
                with open(temp_thumb_path, "rb") as f:
                    blob_client_thumb.upload_blob(f, overwrite=True)
                thumbnail_url = blob_client_thumb.url

                os.unlink(temp_thumb_path)

            cap.release()
            os.unlink(temp_video_path)

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO videos (title, publisher, producer, genre, age_rating, video_url, thumbnail_url, creator_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                title, publisher, producer, genre, age_rating, video_url, thumbnail_url, current_user.id
            )
            conn.commit()
            conn.close()

            flash('Video uploaded successfully!', 'success')
        except Exception as e:
            flash(f'Upload failed: {str(e)}', 'error')

    return redirect(url_for('creator_dashboard'))

@app.route('/rate-video', methods=['POST'])
@login_required
def rate_video():
    if current_user.user_type != 'consumer':
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    video_id = data['video_id']
    rating = data['rating']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM ratings WHERE video_id = ? AND user_id = ?", video_id, current_user.id)
    existing = cursor.fetchone()

    if existing:
        cursor.execute("UPDATE ratings SET rating = ? WHERE video_id = ? AND user_id = ?",
                       rating, video_id, current_user.id)
    else:
        cursor.execute("INSERT INTO ratings (video_id, user_id, rating) VALUES (?, ?, ?)",
                       video_id, current_user.id, rating)

    conn.commit()

    # Fetch new average
    cursor.execute("SELECT AVG(CAST(rating AS FLOAT)) FROM ratings WHERE video_id = ?", video_id)
    new_avg = cursor.fetchone()[0]

    conn.close()

    return jsonify({'success': True, 'avg_rating': new_avg})

@app.route('/add-comment', methods=['POST'])
@login_required
def add_comment():
    if current_user.user_type != 'consumer':
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    video_id = data['video_id']
    comment_text = data['comment']

    # Perform sentiment analysis
    blob = TextBlob(comment_text)
    polarity = blob.sentiment.polarity
    if polarity > 0:
        sentiment = 'positive'
    elif polarity < 0:
        sentiment = 'negative'
    else:
        sentiment = 'neutral'

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO comments (video_id, user_id, comment, sentiment) VALUES (?, ?, ?, ?)",
                   video_id, current_user.id, comment_text, sentiment)
    conn.commit()
    conn.close()

    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return jsonify({'success': True, 'comment': {'username': current_user.username, 'comment': comment_text, 'created_at': created_at, 'sentiment': sentiment}})

@app.route('/search-videos')
@login_required
def search_videos():
    query = request.args.get('q', '')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
                   SELECT v.id,
                          v.title,
                          v.publisher,
                          v.producer,
                          v.genre,
                          v.age_rating,
                          v.video_url,
                          AVG(CAST(r.rating AS FLOAT)) as avg_rating,
                          v.thumbnail_url
                   FROM videos v
                            LEFT JOIN ratings r ON v.id = r.video_id
                   WHERE v.title LIKE ?
                      OR v.genre LIKE ?
                      OR v.publisher LIKE ?
                   GROUP BY v.id, v.title, v.publisher, v.producer, v.genre, v.age_rating, v.video_url, v.thumbnail_url
                   ''', f'%{query}%', f'%{query}%', f'%{query}%')
    videos = cursor.fetchall()

    video_list = [{
        'id': v[0], 'title': v[1], 'publisher': v[2], 'producer': v[3],
        'genre': v[4], 'age_rating': v[5], 'video_url': v[6], 'avg_rating': v[7], 'thumbnail_url': v[8]
    } for v in videos]

    # Fetch user ratings
    user_ratings = {}
    cursor.execute('''
        SELECT video_id, rating
        FROM ratings
        WHERE user_id = ?
    ''', current_user.id)
    for row in cursor.fetchall():
        user_ratings[row[0]] = row[1]

    for video in video_list:
        video['user_rating'] = user_ratings.get(video['id'], 0)

    # Fetch comments
    comments_dict = {}
    if video_list:
        video_ids = [v['id'] for v in video_list]
        placeholders = ','.join(['?'] * len(video_ids))
        cursor.execute(f'''
            SELECT c.video_id, u.username, c.comment, c.created_at, c.sentiment
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.video_id IN ({placeholders})
            ORDER BY c.created_at DESC
        ''', video_ids)
        all_comments = cursor.fetchall()
        for comment in all_comments:
            vid = comment[0]
            if vid not in comments_dict:
                comments_dict[vid] = []
            comments_dict[vid].append({
                'username': comment[1],
                'comment': comment[2],
                'created_at': comment[3].strftime('%Y-%m-%d %H:%M:%S'),
                'sentiment': comment[4]
            })

    for video in video_list:
        video['comments'] = comments_dict.get(video['id'], [])

    conn.close()

    return jsonify(video_list)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

HOME_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VideoShare - Home</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow-x: hidden;
        }

        .container {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border-radius: 20px;
            padding: 3rem;
            text-align: center;
            box-shadow: 0 25px 50px rgba(0, 0, 0, 0.2);
            animation: slideUp 1s ease-out;
            position: relative;
            overflow: hidden;
        }

        .container::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: linear-gradient(45deg, transparent, rgba(255, 255, 255, 0.1), transparent);
            animation: shine 3s infinite;
            pointer-events: none;
        }

        @keyframes slideUp {
            from { transform: translateY(50px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }

        @keyframes shine {
            0% { transform: translateX(-100%) translateY(-100%) rotate(45deg); }
            100% { transform: translateX(100%) translateY(100%) rotate(45deg); }
        }

        h1 {
            color: #333;
            font-size: 3rem;
            margin-bottom: 1rem;
            background: linear-gradient(45deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            animation: glow 2s ease-in-out infinite alternate;
        }

        @keyframes glow {
            from { filter: drop-shadow(0 0 5px rgba(102, 126, 234, 0.3)); }
            to { filter: drop-shadow(0 0 20px rgba(102, 126, 234, 0.7)); }
        }

        p {
            color: #666;
            font-size: 1.2rem;
            margin-bottom: 2rem;
            animation: fadeIn 1.5s ease-out 0.5s both;
        }

        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        .buttons {
            display: flex;
            gap: 1rem;
            justify-content: center;
            flex-wrap: wrap;
        }

        .btn {
            padding: 1rem 2rem;
            border: none;
            border-radius: 50px;
            font-size: 1.1rem;
            text-decoration: none;
            color: white;
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
            cursor: pointer;
            text-transform: uppercase;
            font-weight: bold;
            letter-spacing: 1px;
        }

        .btn-primary {
            background: linear-gradient(45deg, #667eea, #764ba2);
            box-shadow: 0 10px 30px rgba(102, 126, 234, 0.4);
            animation: float 3s ease-in-out infinite;
        }

        .btn-secondary {
            background: linear-gradient(45deg, #f093fb, #f5576c);
            box-shadow: 0 10px 30px rgba(245, 87, 108, 0.4);
            animation: float 3s ease-in-out infinite 1.5s;
        }

        @keyframes float {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-5px); }
        }

        .btn:hover {
            transform: translateY(-3px);
            box-shadow: 0 15px 40px rgba(0, 0, 0, 0.3);
        }

        .btn::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
            transition: left 0.5s;
        }

        .btn:hover::before {
            left: 100%;
        }

        .floating-elements {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: -1;
        }

        .floating-element {
            position: absolute;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 50%;
            animation: float-random 20s infinite linear;
        }

        @keyframes float-random {
            0% { transform: translateY(100vh) rotate(0deg); }
            100% { transform: translateY(-100px) rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="floating-elements">
        <div class="floating-element" style="width: 60px; height: 60px; left: 10%; animation-delay: -5s;"></div>
        <div class="floating-element" style="width: 80px; height: 80px; left: 20%; animation-delay: -10s;"></div>
        <div class="floating-element" style="width: 40px; height: 40px; left: 30%; animation-delay: -15s;"></div>
        <div class="floating-element" style="width: 100px; height: 100px; left: 40%; animation-delay: -20s;"></div>
        <div class="floating-element" style="width: 70px; height: 70px; left: 50%; animation-delay: -25s;"></div>
        <div class="floating-element" style="width: 90px; height: 90px; left: 60%; animation-delay: -30s;"></div>
        <div class="floating-element" style="width: 50px; height: 50px; left: 70%; animation-delay: -35s;"></div>
        <div class="floating-element" style="width: 120px; height: 120px; left: 80%; animation-delay: -40s;"></div>
    </div>

    <div class="container">
        <h1>VideoShare</h1>
        <p>Welcome to the ultimate video sharing platform</p>
        <div class="buttons">
            <a href="{{ url_for('login') }}" class="btn btn-primary">Login</a>
            <a href="{{ url_for('register') }}" class="btn btn-secondary">Sign Up</a>
        </div>
    </div>
</body>
</html>
'''

REGISTER_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VideoShare - Register</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 2rem;
        }

        .form-container {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border-radius: 20px;
            padding: 3rem;
            box-shadow: 0 25px 50px rgba(0, 0, 0, 0.2);
            animation: slideUp 0.8s ease-out;
            width: 100%;
            max-width: 450px;
        }

        @keyframes slideUp {
            from { transform: translateY(50px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }

        h2 {
            text-align: center;
            color: #333;
            margin-bottom: 2rem;
            font-size: 2rem;
            background: linear-gradient(45deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .form-group {
            margin-bottom: 1.5rem;
            position: relative;
        }

        .form-group label {
            display: block;
            color: #555;
            margin-bottom: 0.5rem;
            font-weight: 600;
        }

        .form-group input, .form-group select {
            width: 100%;
            padding: 1rem;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 1rem;
            transition: all 0.3s ease;
            background: rgba(255, 255, 255, 0.9);
        }

        .form-group input:focus, .form-group select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 20px rgba(102, 126, 234, 0.2);
            transform: scale(1.02);
        }

        .btn {
            width: 100%;
            padding: 1rem;
            border: none;
            border-radius: 10px;
            background: linear-gradient(45deg, #667eea, #764ba2);
            color: white;
            font-size: 1.1rem;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 15px 40px rgba(102, 126, 234, 0.4);
        }

        .alert {
            padding: 1rem;
            margin-bottom: 1rem;
            border-radius: 10px;
            animation: slideDown 0.5s ease-out;
        }

        @keyframes slideDown {
            from { transform: translateY(-20px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }

        .alert-success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }

        .alert-error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }

        .back-link {
            text-align: center;
            margin-top: 2rem;
        }

        .back-link a {
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
            transition: all 0.3s ease;
        }

        .back-link a:hover {
            color: #764ba2;
            text-decoration: underline;
        }

        .radio-group {
            display: flex;
            gap: 2rem;
            margin-top: 0.5rem;
        }

        .radio-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            cursor: pointer;
            padding: 0.5rem 1rem;
            border-radius: 10px;
            transition: all 0.3s ease;
            background: rgba(102, 126, 234, 0.1);
        }

        .radio-item:hover {
            background: rgba(102, 126, 234, 0.2);
        }

        .radio-item input[type="radio"] {
            width: auto;
            margin: 0;
        }
    </style>
</head>
<body>
    <div class="form-container">
        <h2>Create Account</h2>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <form method="POST">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required>
            </div>

            <div class="form-group">
                <label for="email">Email</label>
                <input type="email" id="email" name="email" required>
            </div>

            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required>
            </div>

            <div class="form-group">
                <label>User Type</label>
                <div class="radio-group">
                    <div class="radio-item">
                        <input type="radio" id="creator" name="user_type" value="creator" required>
                        <label for="creator">Creator</label>
                    </div>
                    <div class="radio-item">
                        <input type="radio" id="consumer" name="user_type" value="consumer" required>
                        <label for="consumer">Consumer</label>
                    </div>
                </div>
            </div>

            <button type="submit" class="btn">Register</button>
        </form>

        <div class="back-link">
            <a href="{{ url_for('home') }}">← Back to Home</a>
        </div>
    </div>
</body>
</html>
'''

LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VideoShare - Login</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 2rem;
        }

        .form-container {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border-radius: 20px;
            padding: 3rem;
            box-shadow: 0 25px 50px rgba(0, 0, 0, 0.2);
            animation: slideUp 0.8s ease-out;
            width: 100%;
            max-width: 450px;
        }

        @keyframes slideUp {
            from { transform: translateY(50px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }

        h2 {
            text-align: center;
            color: #333;
            margin-bottom: 2rem;
            font-size: 2rem;
            background: linear-gradient(45deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .form-group {
            margin-bottom: 1.5rem;
            position: relative;
        }

        .form-group label {
            display: block;
            color: #555;
            margin-bottom: 0.5rem;
            font-weight: 600;
        }

        .form-group input {
            width: 100%;
            padding: 1rem;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 1rem;
            transition: all 0.3s ease;
            background: rgba(255, 255, 255, 0.9);
        }

        .form-group input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 20px rgba(102, 126, 234, 0.2);
            transform: scale(1.02);
        }

        .btn {
            width: 100%;
            padding: 1rem;
            border: none;
            border-radius: 10px;
            background: linear-gradient(45deg, #667eea, #764ba2);
            color: white;
            font-size: 1.1rem;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 15px 40px rgba(102, 126, 234, 0.4);
        }

        .alert {
            padding: 1rem;
            margin-bottom: 1rem;
            border-radius: 10px;
            animation: slideDown 0.5s ease-out;
        }

        @keyframes slideDown {
            from { transform: translateY(-20px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }

        .alert-success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }

        .alert-error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }

        .back-link {
            text-align: center;
            margin-top: 2rem;
        }

        .back-link a {
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
            transition: all 0.3s ease;
        }

        .back-link a:hover {
            color: #764ba2;
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="form-container">
        <h2>Login</h2>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <form method="POST">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required>
            </div>

            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required>
            </div>

            <button type="submit" class="btn">Login</button>
        </form>

        <div class="back-link">
            <a href="{{ url_for('home') }}">← Back to Home</a>
        </div>
    </div>
</body>
</html>
'''

CREATOR_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VideoShare - Creator Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 2rem;
        }

        .dashboard-container {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border-radius: 20px;
            padding: 3rem;
            box-shadow: 0 25px 50px rgba(0, 0, 0, 0.2);
            animation: slideUp 0.8s ease-out;
            width: 100%;
            max-width: 600px;
        }

        @keyframes slideUp {
            from { transform: translateY(50px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }

        h2 {
            text-align: center;
            color: #333;
            margin-bottom: 2rem;
            font-size: 2rem;
            background: linear-gradient(45deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .form-group {
            margin-bottom: 1.5rem;
        }

        .form-group label {
            display: block;
            color: #555;
            margin-bottom: 0.5rem;
            font-weight: 600;
        }

        .form-group input, .form-group select {
            width: 100%;
            padding: 1rem;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 1rem;
            transition: all 0.3s ease;
            background: rgba(255, 255, 255, 0.9);
        }

        .form-group input:focus, .form-group select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 20px rgba(102, 126, 234, 0.2);
        }

        .btn {
            width: 100%;
            padding: 1rem;
            border: none;
            border-radius: 10px;
            background: linear-gradient(45deg, #667eea, #764ba2);
            color: white;
            font-size: 1.1rem;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 15px 40px rgba(102, 126, 234, 0.4);
        }

        .alert {
            padding: 1rem;
            margin-bottom: 1rem;
            border-radius: 10px;
            animation: slideDown 0.5s ease-out;
        }

        @keyframes slideDown {
            from { transform: translateY(-20px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }

        .alert-success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }

        .alert-error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }

        .logout-link {
            text-align: center;
            margin-top: 2rem;
        }

        .logout-link a {
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
            transition: all 0.3s ease;
        }

        .logout-link a:hover {
            color: #764ba2;
            text-decoration: underline;
        }

        .form-row {
            display: flex;
            gap: 1rem;
        }

        .form-row .form-group {
            flex: 1;
        }

        .file-input-container {
            position: relative;
            border: 2px dashed #667eea;
            border-radius: 10px;
            padding: 2rem;
            text-align: center;
            transition: all 0.3s ease;
            background: rgba(102, 126, 234, 0.05);
        }

        .file-input-container:hover {
            border-color: #764ba2;
            background: rgba(102, 126, 234, 0.1);
        }

        .file-input-container input[type="file"] {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            opacity: 0;
            cursor: pointer;
        }

        .file-label {
            color: #667eea;
            font-weight: 600;
            font-size: 1rem;
            transition: color 0.3s ease;
        }

        .upload-progress {
            display: none;
            height: 5px;
            background: #e0e0e0;
            border-radius: 5px;
            margin-top: 1rem;
            overflow: hidden;
        }

        .progress-bar {
            height: 100%;
            width: 0;
            background: linear-gradient(45deg, #667eea, #764ba2);
            transition: width 0.3s ease;
        }

        .full-width {
            grid-column: 1 / -1;
        }
    </style>
</head>
<body>
    <div class="dashboard-container">
        <h2>Creator Dashboard</h2>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <form method="POST" action="{{ url_for('upload_video') }}" enctype="multipart/form-data" id="uploadForm">
           <div class="form-row">
               <div class="form-group">
                   <label for="title">Title</label>
                   <input type="text" id="title" name="title" required>
               </div>

               <div class="form-group">
                   <label for="publisher">Publisher</label>
                   <input type="text" id="publisher" name="publisher" required>
               </div>
           </div>

           <div class="form-row">
               <div class="form-group">
                   <label for="producer">Producer</label>
                   <input type="text" id="producer" name="producer" required>
               </div>

               <div class="form-group">
                   <label for="genre">Genre</label>
                   <select id="genre" name="genre" required>
                       <option value="">Select Genre</option>
                       <option value="Action">Action</option>
                       <option value="Comedy">Comedy</option>
                       <option value="Drama">Drama</option>
                       <option value="Horror">Horror</option>
                       <option value="Romance">Romance</option>
                       <option value="Sci-Fi">Sci-Fi</option>
                       <option value="Documentary">Documentary</option>
                       <option value="Animation">Animation</option>
                       <option value="Thriller">Thriller</option>
                       <option value="Adventure">Adventure</option>
                   </select>
               </div>
           </div>

           <div class="form-row">
               <div class="form-group">
                   <label for="age_rating">Age Rating</label>
                   <select id="age_rating" name="age_rating" required>
                       <option value="">Select Rating</option>
                       <option value="G">G - General Audiences</option>
                       <option value="PG">PG - Parental Guidance</option>
                       <option value="PG-13">PG-13 - Parents Strongly Cautioned</option>
                       <option value="R">R - Restricted</option>
                       <option value="NC-17">NC-17 - Adults Only</option>
                       <option value="18">18+ - Adult Content</option>
                   </select>
               </div>
           </div>

           <div class="form-group">
               <label>Video File</label>
               <div class="file-input-container">
                   <input type="file" id="video" name="video" accept="video/*" required>
                   <label for="video" class="file-label">
                       📹 Click to select video file or drag & drop
                   </label>
               </div>
           </div>

           <div class="upload-progress" id="uploadProgress">
               <div class="progress-bar" id="progressBar"></div>
           </div>

           <button type="submit" class="btn">Upload Video</button>
       </form>

       <div class="logout-link">
           <a href="{{ url_for('logout') }}">Logout</a>
       </div>
    </div>

    <script>
        const fileInput = document.getElementById('video');
        const fileLabel = document.querySelector('.file-label');
        const uploadForm = document.getElementById('uploadForm');
        const uploadProgress = document.getElementById('uploadProgress');
        const progressBar = document.getElementById('progressBar');

        fileInput.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                fileLabel.innerHTML = `📹 Selected: ${file.name}`;
                fileLabel.style.color = '#28a745';
            }
        });

        const container = document.querySelector('.file-input-container');

        container.addEventListener('dragover', function(e) {
            e.preventDefault();
            container.style.borderColor = '#764ba2';
            container.style.background = 'rgba(102, 126, 234, 0.2)';
        });

        container.addEventListener('dragleave', function(e) {
            e.preventDefault();
            container.style.borderColor = '#667eea';
            container.style.background = 'rgba(102, 126, 234, 0.05)';
        });

        container.addEventListener('drop', function(e) {
            e.preventDefault();
            container.style.borderColor = '#667eea';
            container.style.background = 'rgba(102, 126, 234, 0.05)';

            const files = e.dataTransfer.files;
            if (files.length > 0) {
                fileInput.files = files;
                fileLabel.innerHTML = `📹 Selected: ${files[0].name}`;
                fileLabel.style.color = '#28a745';
            }
        });

        uploadForm.addEventListener('submit', function(e) {
            const submitBtn = uploadForm.querySelector('.btn');
            submitBtn.style.background = 'linear-gradient(45deg, #28a745, #20c997)';
            submitBtn.innerHTML = 'Uploading...';
            submitBtn.disabled = true;

            uploadProgress.style.display = 'block';

            let progress = 0;
            const interval = setInterval(() => {
                progress += Math.random() * 15;
                if (progress > 90) progress = 90;
                progressBar.style.width = progress + '%';
            }, 500);

            setTimeout(() => {
                clearInterval(interval);
                progressBar.style.width = '100%';
            }, 3000);
        });
    </script>
</body>
</html>
'''

CONSUMER_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
   <meta charset="UTF-8">
   <meta name="viewport" content="width=device-width, initial-scale=1.0">
   <title>VideoShare - Consumer Dashboard</title>
   <style>
       * {
           margin: 0;
           padding: 0;
           box-sizing: border-box;
       }

       body {
           font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
           background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
           min-height: 100vh;
           padding: 2rem;
       }

       .header {
           background: rgba(255, 255, 255, 0.95);
           backdrop-filter: blur(20px);
           border-radius: 15px;
           padding: 1.5rem;
           margin-bottom: 2rem;
           display: flex;
           justify-content: space-between;
           align-items: center;
           box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
           animation: slideDown 0.8s ease-out;
       }

       @keyframes slideDown {
           from { transform: translateY(-50px); opacity: 0; }
           to { transform: translateY(0); opacity: 1; }
       }

       .header h1 {
           background: linear-gradient(45deg, #667eea, #764ba2);
           -webkit-background-clip: text;
           -webkit-text-fill-color: transparent;
           font-size: 2rem;
       }

       .search-container {
           display: flex;
           align-items: center;
           gap: 1rem;
           flex: 1;
           max-width: 400px;
           margin: 0 2rem;
       }

       .search-input {
           flex: 1;
           padding: 0.8rem 1.2rem;
           border: 2px solid #e0e0e0;
           border-radius: 25px;
           font-size: 1rem;
           transition: all 0.3s ease;
       }

       .search-input:focus {
           outline: none;
           border-color: #667eea;
           box-shadow: 0 0 20px rgba(102, 126, 234, 0.2);
       }

       .search-btn {
           padding: 0.8rem 1.5rem;
           background: linear-gradient(45deg, #667eea, #764ba2);
           color: white;
           border: none;
           border-radius: 25px;
           cursor: pointer;
           font-weight: bold;
           transition: all 0.3s ease;
       }

       .search-btn:hover {
           transform: translateY(-2px);
           box-shadow: 0 10px 25px rgba(102, 126, 234, 0.4);
       }

       .logout-btn {
           padding: 0.5rem 1.5rem;
           background: linear-gradient(45deg, #f093fb, #f5576c);
           color: white;
           text-decoration: none;
           border-radius: 25px;
           font-weight: bold;
           transition: all 0.3s ease;
       }

       .logout-btn:hover {
           transform: translateY(-2px);
           box-shadow: 0 10px 25px rgba(245, 87, 108, 0.4);
       }

       .videos-container {
           display: grid;
           grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
           gap: 2rem;
           animation: fadeIn 1s ease-out;
       }

       @keyframes fadeIn {
           from { opacity: 0; }
           to { opacity: 1; }
       }

       .video-card {
           background: rgba(255, 255, 255, 0.95);
           backdrop-filter: blur(20px);
           border-radius: 20px;
           padding: 2rem;
           box-shadow: 0 25px 50px rgba(0, 0, 0, 0.2);
           transition: all 0.3s ease;
           animation: slideUp 0.8s ease-out;
           animation-fill-mode: both;
       }

       .video-card:hover {
           transform: translateY(-10px);
           box-shadow: 0 35px 70px rgba(0, 0, 0, 0.3);
       }

       .video-card:nth-child(odd) {
           animation-delay: 0.2s;
       }

       .video-card:nth-child(even) {
           animation-delay: 0.4s;
       }

       @keyframes slideUp {
           from { transform: translateY(50px); opacity: 0; }
           to { transform: translateY(0); opacity: 1; }
       }

       .video-title {
           font-size: 1.5rem;
           font-weight: bold;
           color: #333;
           margin-bottom: 1rem;
           background: linear-gradient(45deg, #667eea, #764ba2);
           -webkit-background-clip: text;
           -webkit-text-fill-color: transparent;
       }

       .video-meta {
           display: grid;
           grid-template-columns: 1fr 1fr;
           gap: 0.5rem;
           margin-bottom: 1rem;
           font-size: 0.9rem;
           color: #666;
       }

       .video-meta span {
           padding: 0.3rem 0.8rem;
           background: rgba(102, 126, 234, 0.1);
           border-radius: 15px;
           text-align: center;
       }

       .video-player {
           width: 100%;
           max-height: 200px;
           border-radius: 10px;
           margin-bottom: 1rem;
       }

       .rating-container {
           display: flex;
           align-items: center;
           gap: 1rem;
           margin-bottom: 1rem;
       }

       .stars {
           display: flex;
           gap: 0.2rem;
       }

       .star {
           font-size: 1.5rem;
           color: #ddd;
           cursor: pointer;
           transition: all 0.2s ease;
       }

       .star:hover, .star.active {
           color: #ffd700;
           transform: scale(1.2);
       }

       .avg-rating {
           font-size: 0.9rem;
           color: #666;
           font-weight: bold;
       }

       .comment-section {
           border-top: 1px solid #eee;
           padding-top: 1rem;
           margin-top: 1rem;
       }

       .comment-input {
           width: 100%;
           padding: 0.8rem;
           border: 2px solid #e0e0e0;
           border-radius: 10px;
           font-size: 0.9rem;
           resize: vertical;
           min-height: 80px;
           transition: all 0.3s ease;
       }

       .comment-input:focus {
           outline: none;
           border-color: #667eea;
           box-shadow: 0 0 15px rgba(102, 126, 234, 0.2);
       }

       .comment-btn {
           margin-top: 0.5rem;
           padding: 0.5rem 1rem;
           background: linear-gradient(45deg, #667eea, #764ba2);
           color: white;
           border: none;
           border-radius: 8px;
           cursor: pointer;
           font-weight: bold;
           transition: all 0.3s ease;
       }

       .comment-btn:hover {
           transform: translateY(-2px);
           box-shadow: 0 8px 20px rgba(102, 126, 234, 0.4);
       }

       .comments-list {
           margin-top: 1rem;
           max-height: 200px;
           overflow-y: auto;
       }

       .comment {
           padding: 0.5rem 0;
           border-bottom: 1px solid #eee;
           position: relative;
       }

       .comment strong {
           color: #333;
       }

       .comment small {
           display: block;
           color: #999;
           font-size: 0.8rem;
       }

       .sentiment {
           font-size: 0.8rem;
           padding: 0.2rem 0.5rem;
           border-radius: 10px;
           position: absolute;
           right: 0;
           top: 0.5rem;
       }

       .sentiment-positive {
           background: #d4edda;
           color: #155724;
       }

       .sentiment-negative {
           background: #f8d7da;
           color: #721c24;
       }

       .sentiment-neutral {
           background: #fff3cd;
           color: #856404;
       }

       .no-videos {
           text-align: center;
           color: white;
           font-size: 1.5rem;
           margin-top: 4rem;
           animation: fadeIn 1s ease-out;
       }

       @media (max-width: 768px) {
           .header {
               flex-direction: column;
               gap: 1rem;
           }

           .search-container {
               margin: 0;
               max-width: 100%;
           }

           .video-meta {
               grid-template-columns: 1fr;
           }
       }

       .pulse {
           animation: pulse 2s infinite;
       }

       @keyframes pulse {
           0% { box-shadow: 0 0 0 0 rgba(102, 126, 234, 0.7); }
           70% { box-shadow: 0 0 0 10px rgba(102, 126, 234, 0); }
           100% { box-shadow: 0 0 0 0 rgba(102, 126, 234, 0); }
       }
   </style>
</head>
<body>
   <div class="header">
       <h1>Consumer Dashboard</h1>
       <div class="search-container">
           <input type="text" class="search-input" id="searchInput" placeholder="Search videos...">
           <button class="search-btn" onclick="searchVideos()">🔍</button>
       </div>
       <div>
           <span style="margin-right: 1rem; color: #555;">Welcome, {{ current_user.username }}!</span>
           <a href="{{ url_for('logout') }}" class="logout-btn">Logout</a>
       </div>
   </div>

   <div class="videos-container" id="videosContainer">
       {% if videos %}
           {% for video in videos %}
           <div class="video-card">
               <div class="video-title">{{ video[1] }}</div>

               <div class="video-meta">
                   <span><strong>Publisher:</strong> {{ video[2] }}</span>
                   <span><strong>Producer:</strong> {{ video[3] }}</span>
                   <span><strong>Genre:</strong> {{ video[4] }}</span>
                   <span><strong>Rating:</strong> {{ video[5] }}</span>
               </div>

               <video class="video-player" controls poster="{{ video[8] or '' }}">
                   <source src="{{ video[6] }}" type="video/mp4">
                   Your browser does not support the video tag.
               </video>

               <div class="rating-container">
                   <div class="stars" data-video-id="{{ video[0] }}">
                       {% set user_rating = user_ratings.get(video[0], 0) %}
                       {% for i in range(1, 6) %}
                       <span class="star {% if i <= user_rating %}active{% endif %}" data-rating="{{ i }}">⭐</span>
                       {% endfor %}
                   </div>
                   <span class="avg-rating">
                       {% if video[7] %}
                           Avg: {{ "%.1f"|format(video[7]) }}/5
                       {% else %}
                           No ratings yet
                       {% endif %}
                   </span>
               </div>

               <div class="comment-section">
                   <textarea class="comment-input" placeholder="Write your comment..." data-video-id="{{ video[0] }}"></textarea>
                   <button class="comment-btn" onclick="addComment({{ video[0] }})">Add Comment</button>
                   <div class="comments-list">
                       {% if comments[video[0]] %}
                           {% for comment in comments[video[0]] %}
                               <div class="comment">
                                   <strong>{{ comment.username }}:</strong> {{ comment.comment }}
                                   <span class="sentiment sentiment-{{ comment.sentiment }}">{{ comment.sentiment | capitalize }}</span>
                                   <small>{{ comment.created_at }}</small>
                               </div>
                           {% endfor %}
                       {% else %}
                           <p>No comments yet</p>
                       {% endif %}
                   </div>
               </div>
           </div>
           {% endfor %}
       {% else %}
           <div class="no-videos">No videos available yet. Check back later!</div>
       {% endif %}
   </div>

   <script>
       document.querySelectorAll('.stars').forEach(starsContainer => {
           const stars = starsContainer.querySelectorAll('.star');
           const videoId = starsContainer.dataset.videoId;

           stars.forEach((star, index) => {
               star.addEventListener('click', () => {
                   const rating = index + 1;

                   stars.forEach((s, i) => {
                       s.classList.toggle('active', i < rating);
                   });

                   fetch('/rate-video', {
                       method: 'POST',
                       headers: {
                           'Content-Type': 'application/json',
                       },
                       body: JSON.stringify({
                           video_id: videoId,
                           rating: rating
                       })
                   })
                   .then(response => response.json())
                   .then(data => {
                       if (data.success) {
                           starsContainer.classList.add('pulse');
                           setTimeout(() => starsContainer.classList.remove('pulse'), 2000);
                           const avgSpan = starsContainer.closest('.rating-container').querySelector('.avg-rating');
                           avgSpan.textContent = data.avg_rating ? `Avg: ${data.avg_rating.toFixed(1)}/5` : 'No ratings yet';
                       }
                   })
                   .catch(error => console.error('Error:', error));
               });

               star.addEventListener('mouseenter', () => {
                   stars.forEach((s, i) => {
                       s.style.color = i <= index ? '#ffd700' : '#ddd';
                   });
               });

               starsContainer.addEventListener('mouseleave', () => {
                   stars.forEach(s => {
                       s.style.color = s.classList.contains('active') ? '#ffd700' : '#ddd';
                   });
               });
           });
       });

       function addComment(videoId) {
           const commentInput = document.querySelector(`textarea[data-video-id="${videoId}"]`);
           const comment = commentInput.value.trim();

           if (!comment) {
               alert('Please enter a comment');
               return;
           }

           fetch('/add-comment', {
               method: 'POST',
               headers: {
                   'Content-Type': 'application/json',
               },
               body: JSON.stringify({
                   video_id: videoId,
                   comment: comment
               })
           })
           .then(response => response.json())
           .then(data => {
               if (data.success) {
                   const commentsList = commentInput.closest('.comment-section').querySelector('.comments-list');
                   const noComments = commentsList.querySelector('p');
                   if (noComments) noComments.remove();

                   const newComment = document.createElement('div');
                   newComment.className = 'comment';
                   newComment.innerHTML = `<strong>${data.comment.username}:</strong> ${data.comment.comment} <span class="sentiment sentiment-${data.comment.sentiment}">${data.comment.sentiment.charAt(0).toUpperCase() + data.comment.sentiment.slice(1)}</span> <small>${data.comment.created_at}</small>`;
                   commentsList.prepend(newComment);

                   commentInput.value = '';
                   commentInput.style.borderColor = '#28a745';
                   setTimeout(() => commentInput.style.borderColor = '#e0e0e0', 2000);
               }
           })
           .catch(error => console.error('Error:', error));
       }

       function searchVideos() {
           const query = document.getElementById('searchInput').value;

           if (!query.trim()) {
               location.reload();
               return;
           }

           fetch(`/search-videos?q=${encodeURIComponent(query)}`)
               .then(response => response.json())
               .then(videos => {
                   const container = document.getElementById('videosContainer');

                   if (videos.length === 0) {
                       container.innerHTML = '<div class="no-videos">No videos found matching your search.</div>';
                       return;
                   }

                   container.innerHTML = videos.map(video => `
                       <div class="video-card">
                           <div class="video-title">${video.title}</div>

                           <div class="video-meta">
                               <span><strong>Publisher:</strong> ${video.publisher}</span>
                               <span><strong>Producer:</strong> ${video.producer}</span>
                               <span><strong>Genre:</strong> ${video.genre}</span>
                               <span><strong>Rating:</strong> ${video.age_rating}</span>
                           </div>

                           <video class="video-player" controls poster="${video.thumbnail_url || ''}">
                               <source src="${video.video_url}" type="video/mp4">
                               Your browser does not support the video tag.
                           </video>

                           <div class="rating-container">
                               <div class="stars" data-video-id="${video.id}">
                                   ${[1,2,3,4,5].map(i => `<span class="star ${i <= video.user_rating ? 'active' : ''}" data-rating="${i}">⭐</span>`).join('')}
                               </div>
                               <span class="avg-rating">
                                   ${video.avg_rating ? `Avg: ${video.avg_rating.toFixed(1)}/5` : 'No ratings yet'}
                               </span>
                           </div>

                           <div class="comment-section">
                               <textarea class="comment-input" placeholder="Write your comment..." data-video-id="${video.id}"></textarea>
                               <button class="comment-btn" onclick="addComment(${video.id})">Add Comment</button>
                               <div class="comments-list">
                                   ${video.comments.map(comment => `
                                       <div class="comment">
                                           <strong>${comment.username}:</strong> ${comment.comment}
                                           <span class="sentiment sentiment-${comment.sentiment}">${comment.sentiment.charAt(0).toUpperCase() + comment.sentiment.slice(1)}</span>
                                           <small>${comment.created_at}</small>
                                       </div>
                                   `).join('') || '<p>No comments yet</p>'}
                               </div>
                           </div>
                       </div>
                   `).join('');

                   initializeStarRatings();
               })
               .catch(error => console.error('Error:', error));
       }

       function initializeStarRatings() {
           document.querySelectorAll('.stars').forEach(starsContainer => {
               const stars = starsContainer.querySelectorAll('.star');
               const videoId = starsContainer.dataset.videoId;

               stars.forEach((star, index) => {
                   star.addEventListener('click', () => {
                       const rating = index + 1;

                       stars.forEach((s, i) => {
                           s.classList.toggle('active', i < rating);
                       });

                       fetch('/rate-video', {
                           method: 'POST',
                           headers: {
                               'Content-Type': 'application/json',
                           },
                           body: JSON.stringify({
                               video_id: videoId,
                               rating: rating
                           })
                       })
                       .then(response => response.json())
                       .then(data => {
                           if (data.success) {
                               starsContainer.classList.add('pulse');
                               setTimeout(() => starsContainer.classList.remove('pulse'), 2000);
                               const avgSpan = starsContainer.closest('.rating-container').querySelector('.avg-rating');
                               avgSpan.textContent = data.avg_rating ? `Avg: ${data.avg_rating.toFixed(1)}/5` : 'No ratings yet';
                           }
                       })
                       .catch(error => console.error('Error:', error));
                   });

                   star.addEventListener('mouseenter', () => {
                       stars.forEach((s, i) => {
                           s.style.color = i <= index ? '#ffd700' : '#ddd';
                       });
                   });

                   starsContainer.addEventListener('mouseleave', () => {
                       stars.forEach(s => {
                           s.style.color = s.classList.contains('active') ? '#ffd700' : '#ddd';
                       });
                   });
               });
           });
       }

       document.getElementById('searchInput').addEventListener('keypress', function(e) {
           if (e.key === 'Enter') {
               searchVideos();
           }
       });

       document.querySelectorAll('.video-player').forEach(video => {
           video.addEventListener('loadedmetadata', function() {
               const aspectRatio = this.videoWidth / this.videoHeight;
               this.style.height = (this.offsetWidth / aspectRatio) + 'px';
           });
       });

       const observer = new IntersectionObserver((entries) => {
           entries.forEach(entry => {
               if (entry.isIntersecting) {
                   entry.target.style.animationPlayState = 'running';
               }
           });
       });

       document.querySelectorAll('.video-card').forEach(card => {
           observer.observe(card);
       });

       document.querySelectorAll('.video-player').forEach(video => {
           video.addEventListener('loadstart', function() {
               this.style.opacity = '0.5';
               this.style.transform = 'scale(0.95)';
           });

           video.addEventListener('loadeddata', function() {
               this.style.opacity = '1';
               this.style.transform = 'scale(1)';
           });
       });
   </script>
</body>
</html>
'''
init_db()
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)