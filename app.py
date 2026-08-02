from flask import Flask, render_template, request, Response, send_from_directory, redirect, url_for, jsonify, send_file
import re
import sqlite3
import os
import time
import json
import yt_dlp

app = Flask(__name__)

PROJECT_FOLDER = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_FOLDER = os.path.join(PROJECT_FOLDER, 'Download Files')
THUMB_FOLDER = os.path.join(PROJECT_FOLDER, 'Thumbnails')

app.config['DOWNLOAD_FOLDER'] = DOWNLOAD_FOLDER
app.config['THUMB_FOLDER'] = THUMB_FOLDER

for folder in [DOWNLOAD_FOLDER, THUMB_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

CURRENT_PERCENT = "0"
CURRENT_STATUS = "Starting up..."

def init_db():
    conn = sqlite3.connect('history.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT UNIQUE,
            title TEXT
        )
    ''')
    conn.commit()
    conn.close()

def extract_video_id(url):
    pattern = r'(?:v=|\/v\/|embed\/|youtu\.be\/|\/shorts\/|\/live\/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def calculate_size_mb(info_dict, max_height):
    if info_dict.get('is_live') or info_dict.get('live_status') == 'is_live':
        return "Live Stream (No Fixed Size)"

    formats = info_dict.get('formats', [])
    video_bytes = 0
    audio_bytes = 0
    duration = info_dict.get('duration', 0)
    
    for f in formats:
        if f.get('vcodec') == 'none' and f.get('ext') == 'm4a':
            audio_bytes = f.get('filesize') or f.get('filesize_approx') or 0
            if audio_bytes > 0:
                break

    best_matching_video = None
    for f in formats:
        if f.get('height') == max_height and f.get('acodec') == 'none' and f.get('ext') == 'mp4':
            best_matching_video = f
            break
            
    if best_matching_video:
        video_bytes = best_matching_video.get('filesize') or best_matching_video.get('filesize_approx') or 0
    
    if video_bytes == 0 and duration:
        v_bitrate = 2200 if max_height == 720 else 600
        video_bytes = (v_bitrate * 1000 * duration) / 8

    if audio_bytes == 0 and duration:
        audio_bytes = (128 * 1000 * duration) / 8

    total_bytes = video_bytes + audio_bytes
    if total_bytes == 0:
        return "Calculation Pending"
        
    return f"~{round(total_bytes / (1024 * 1024), 1)} MB"

def ydl_progress_hook(d):
    global CURRENT_PERCENT, CURRENT_STATUS
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_approx') or 0
        downloaded = d.get('downloaded_bytes', 0)
        if total > 0:
            percent_num = int((downloaded / total) * 100)
            CURRENT_PERCENT = str(percent_num)
            CURRENT_STATUS = f"Downloading track... {CURRENT_PERCENT}%"
    elif d['status'] == 'finished':
        CURRENT_PERCENT = "100"
        CURRENT_STATUS = "Stitching audio/video tracks together... Please wait."

@app.route('/local-thumbs/<filename>')
def serve_thumbnail(filename):
    return send_from_directory(app.config['THUMB_FOLDER'], filename)

@app.route('/', methods=['GET', 'POST'])
def home():
    global CURRENT_PERCENT, CURRENT_STATUS
    CURRENT_PERCENT = "0"
    CURRENT_STATUS = "Initializing processing framework..."
    
    video_data = None
    error_message = None

    conn = sqlite3.connect('history.db')
    cursor = conn.cursor()

    if request.method == 'POST':
        user_url = request.form.get('video_url', '').strip()
        if not user_url:
            error_message = "Please paste a video link first."
        else:
            video_id = extract_video_id(user_url)
            if video_id and len(video_id) == 11:
                title = f"Video ID: {video_id}"
                size_720, size_360 = "Calculating...", "Calculating..."
                
                ydl_opts = {
                    'writethumbnail': True,
                    'skip_download': True,
                    'outtmpl': os.path.join(THUMB_FOLDER, video_id),
                    'quiet': True,
                    'no_warnings': True,
                    'noplaylist': True
                }
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(user_url, download=True)
                        title = info.get('title', title)
                        is_live = info.get('is_live') or info.get('live_status') == 'is_live'
                        size_720 = calculate_size_mb(info, 720)
                        size_360 = calculate_size_mb(info, 360)
                except Exception:
                    is_live = False

                local_thumb_file = f"{video_id}.jpg"
                if not os.path.exists(os.path.join(THUMB_FOLDER, local_thumb_file)):
                    if os.path.exists(os.path.join(THUMB_FOLDER, f"{video_id}.webp")):
                        local_thumb_file = f"{video_id}.webp"
                    else:
                        local_thumb_file = ""

                video_data = {
                    "title": title,
                    "video_id": video_id,
                    "local_thumb": local_thumb_file,
                    "original_url": user_url,
                    "size_720": size_720,
                    "size_360": size_360,
                    "is_live": is_live
                }

                try:
                    cursor.execute('INSERT OR REPLACE INTO video_history (video_id, title) VALUES (?, ?)', (video_id, title))
                    conn.commit()
                except sqlite3.Error:
                    pass
            else:
                error_message = "Invalid link structure. Could not find a valid 11-character video ID."

    cursor.execute('SELECT title, video_id FROM video_history ORDER BY id DESC LIMIT 5')
    raw_history = cursor.fetchall()
    conn.close()

    saved_history = []
    for item in raw_history:
        v_title = item[0]
        v_id = item[1]
        
        hist_thumb = f"{v_id}.jpg"
        if not os.path.exists(os.path.join(THUMB_FOLDER, hist_thumb)):
            if os.path.exists(os.path.join(THUMB_FOLDER, f"{v_id}.webp")):
                hist_thumb = f"{v_id}.webp"
            else:
                hist_thumb = ""
                
        saved_history.append({
            "title": v_title,
            "id": v_id,
            "local_thumb": hist_thumb
        })

    return render_template('index.html', data=video_data, error=error_message, history=saved_history)

@app.route('/clear-history', methods=['POST'])
def clear_history():
    conn = sqlite3.connect('history.db')
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM video_history')
        conn.commit()
        success = True
    except sqlite3.Error:
        success = False
    conn.close()
    return jsonify({"success": success})

@app.route('/progress-stream')
def progress_stream():
    def generate_live_feed():
        global CURRENT_PERCENT, CURRENT_STATUS
        while True:
            json_data = json.dumps({'percent': CURRENT_PERCENT, 'status': CURRENT_STATUS})
            yield f"data: {json_data}\n\n"
            time.sleep(0.4)
            if CURRENT_PERCENT == "100" and "Stitching" not in CURRENT_STATUS:
                break
    return Response(generate_live_feed(), mimetype='text/event-stream')

@app.route('/download', methods=['POST'])
def download_video():
    global CURRENT_PERCENT, CURRENT_STATUS
    video_url = request.form.get('video_url')
    quality_choice = request.form.get('quality', '720')
    is_live_flag = request.form.get('is_live_flag', 'False') == 'True'
    
    if not video_url:
        return "Missing video link parameters", 400

    if quality_choice == '360':
        format_string = 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]/best'
    else:
        format_string = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best'

    ydl_opts = {
        'format': format_string,
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [ydl_progress_hook]
    }

    if is_live_flag:
        ydl_opts['live_from_start'] = True
        ydl_opts['format'] = 'best'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        CURRENT_STATUS = "Complete!"
        files=sorted([os.path.join(DOWNLOAD_FOLDER,f) for f in os.listdir(DOWNLOAD_FOLDER)], key=os.path.getmtime)
        return send_file(files[-1], as_attachment=True)
    except Exception as e:
        init_db()
        CURRENT_STATUS = "Error crashed pipeline connection."
        return f"<body style='font-family: sans-serif; padding: 30px;'><h1>Download Pipeline Blocked</h1><p>{str(e)}</p><br><a href='/'>Go Back</a></body>"

if __name__ == '__main__':
    init_db()
    port=int(os.environ.get('PORT',5000))
    app.run(host='0.0.0.0', port=port)
