from flask import Flask, request, jsonify, send_from_directory, Response
import os
import re
import tempfile
import yt_dlp
import requests

app = Flask(__name__)

# --- YouTube Video ID Extraction ---
def extract_video_id(url):
    if not url:
        raise ValueError("URL is required")

    patterns = [
        r'(?:youtube\.com/(?:[^/]+/.+/|(?:v|e(?:mbed)?)/|shorts/|live/|youtu\.be/)([^"&?/\\s]{11}))',
        r'youtube\.com/watch\?.*v=([^"&?/\\s]{11})',
        r'youtube\.com/shorts/([^"&?/\\s]{11})',
        r'youtu\.be/([^"&?/\\s]{11})'
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    try:
        from urllib.parse import urlparse, parse_qs
        if "://" not in url:
            url = "https://" + url
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if 'v' in qs and len(qs['v'][0]) == 11:
            return qs['v'][0]
        path_parts = parsed.path.strip('/').split('/')
        last_part = path_parts[-1]
        if len(last_part) == 11:
            return last_part
    except Exception:
        raise ValueError("Invalid YouTube URL")

    raise ValueError("Could not extract video ID")

# --- Get YouTube Video Info ---
def get_video_info(url, retries=3):
    try:
        video_id = extract_video_id(url)
        ydl_opts = {'quiet': True}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
                return {
                    'title': info.get('title'),
                    'length': info.get('duration'),
                    'thumbnail': info.get('thumbnail') or f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg',
                    'available': True,
                    'isShort': '/shorts/' in url
                }
        except Exception:
            print("yt-dlp failed, trying oEmbed fallback...")
            try:
                r = requests.get(
                    f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json',
                    headers={'User-Agent': 'Mozilla/5.0'},
                    timeout=5
                )
                data = r.json()
                return {
                    'title': data['title'],
                    'length': 0,
                    'thumbnail': data['thumbnail_url'],
                    'available': True,
                    'isShort': '/shorts/' in url
                }
            except:
                raise Exception("Both yt-dlp and oEmbed methods failed")
    except Exception as e:
        if retries > 0:
            print(f"Retrying... ({retries} attempts left)")
            return get_video_info(url, retries - 1)
        raise e

# --- /check Route ---
@app.route('/check', methods=['POST'])
def check():
    try:
        url = request.json.get('url')
        if not url:
            return jsonify({'error': 'URL is required', 'available': False}), 400
        info = get_video_info(url)
        return jsonify(info)
    except Exception as e:
        print(f"Error in /check: {e}")
        return jsonify({
            'error': 'Could not get video information. Please try again later.',
            'details': str(e) if os.environ.get('FLASK_ENV') == 'development' else None,
            'available': False
        }), 500

# --- /download Route ---
@app.route('/download', methods=['POST'])
def download():
    url = request.json.get('url')
    format_type = request.json.get('format', 'video')
    quality = request.json.get('quality')  # e.g., "720p"
    bitrate = request.json.get('bitrate')  # e.g., "192"

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    try:
        video_id = extract_video_id(url)
        info = get_video_info(url)
        clean_title = re.sub(r'[^\w\s.-]', '', info['title'])
        extension = 'mp3' if format_type == 'audio' else 'mp4'
        filename = f'{clean_title}.{extension}'

        with tempfile.TemporaryDirectory() as tmpdir:
            output_template = os.path.join(tmpdir, '%(title)s.%(ext)s')

            # Format selection based on quality
            if format_type == 'audio':
                ydl_format = 'bestaudio[ext=m4a]/bestaudio'
            else:
                if quality and quality.endswith('p'):
                    height = re.sub(r'\D', '', quality)
                    ydl_format = f'bestvideo[height<={height}]+bestaudio[ext=m4a]/best[ext=mp4]'
                else:
                    ydl_format = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]'

            # yt-dlp options
            ydl_opts = {
                'format': ydl_format,
                'outtmpl': output_template,
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True
            }

            if format_type == 'audio':
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': bitrate if bitrate else '192'
                }]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=True)
                file_path = ydl.prepare_filename(result)
                if format_type == 'audio':
                    file_path = os.path.splitext(file_path)[0] + '.mp3'

            with open(file_path, 'rb') as f:
                file_data = f.read()

            return Response(
                file_data,
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Content-Type': 'audio/mpeg' if format_type == 'audio' else 'video/mp4',
                    'Cache-Control': 'no-cache'
                }
            )
    except Exception as e:
        print(f"Error in /download: {e}")
        return jsonify({
            'error': 'Download initialization failed',
            'details': str(e) if os.environ.get('FLASK_ENV') == 'development' else None
        }), 500

# --- Serve Static Files ---
@app.route('/')
def root():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)

# --- Start Server ---
if __name__ == '__main__':
    app.run(port=5000)
