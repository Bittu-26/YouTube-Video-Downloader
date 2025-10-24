from flask import Flask, request, jsonify, send_from_directory, Response
import os
import re
import tempfile
import yt_dlp
import requests
import time
import random

app = Flask(__name__)

# --- Utility to get Proxy URL ---
# This is where the code reads the Vercel Environment Variable
def get_proxy():
    return os.environ.get('YTDLP_PROXY')

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
        raise ValueError("Invalid URL format.")

    raise ValueError("Could not extract video ID from the provided link. Please ensure it is a valid YouTube video URL.")

# --- Get YouTube Video Info ---
def get_video_info(url, retries=3):
    proxy_url = get_proxy()

    try:
        video_id = extract_video_id(url)
        # Increase the connection timeout and prepare for proxy
        ydl_opts = {'quiet': True, 'socket_timeout': 10} 
        
        # ADD PROXY TO YDL_OPTS FOR RELIABILITY
        if proxy_url:
            ydl_opts['proxy'] = proxy_url

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Ensure we are explicitly using HTTPS
                info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
                return {
                    'title': info.get('title'),
                    'length': info.get('duration'),
                    'thumbnail': info.get('thumbnail') or f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg',
                    'available': True,
                    'isShort': '/shorts/' in url
                }
        except Exception:
            # Fallback for when yt-dlp fails signature extraction/connection
            print("yt-dlp failed, trying oEmbed fallback...")
            try:
                # Use requests for oEmbed; must pass proxy if available
                requests_kwargs = {'timeout': 10}
                if proxy_url:
                    # Requests uses a different proxy dictionary format
                    requests_kwargs['proxies'] = {'http': proxy_url, 'https': proxy_url}
                    
                r = requests.get(
                    f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json',
                    headers={'User-Agent': 'Mozilla/5.0'},
                    **requests_kwargs # Unpack proxy/timeout kwargs
                )
                data = r.json()
                return {
                    'title': data['title'],
                    'length': 0, # oEmbed does not provide duration
                    'thumbnail': data['thumbnail_url'],
                    'available': True,
                    'isShort': '/shorts/' in url
                }
            except:
                raise Exception("Both yt-dlp and oEmbed methods failed or video is unavailable. IP/Proxy may be blocked.")
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
        
    except ValueError as e:
        # Catch ValueError (from invalid URL) and return 400 Bad Request
        print(f"Error in /check (Bad Request): {e}")
        return jsonify({
            'error': str(e),
            'available': False
        }), 400
        
    except Exception as e:
        # Catch all other exceptions (e.g., yt-dlp, network issues) and return 500
        print(f"Error in /check (Internal Server Error): {e}")
        return jsonify({
            'error': 'Could not get video information. Please ensure the link is public and available.',
            'details': str(e) if os.environ.get('FLASK_ENV') == 'development' else None,
            'available': False
        }), 500

# --- /download Route ---
@app.route('/download', methods=['POST'])
def download():
    url = request.json.get('url')
    format_type = request.json.get('format', 'video')
    quality = request.json.get('quality')
    bitrate = request.json.get('bitrate')
    proxy_url = get_proxy()

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    try:
        video_id = extract_video_id(url)
        info = get_video_info(url)
        clean_title = re.sub(r'[^\w\s.-]', '', info['title'])
        extension = 'mp3' if format_type == 'audio' else 'mp4'
        filename = f'{clean_title}.{extension}'

        # WORKAROUND: Introduce a random delay to mitigate bot detection
        time.sleep(random.uniform(2, 5)) 

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
                'noplaylist': True,
                'socket_timeout': 15, # Increased timeout for download stability
                'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            }
            
            # ADD PROXY TO YDL_OPTS FOR DOWNLOAD
            if proxy_url:
                ydl_opts['proxy'] = proxy_url

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
            
    except ValueError as e:
        # Catch ValueError for malformed download URLs
        return jsonify({'error': str(e)}), 400
        
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
    # Dynamically get port from environment for local testing
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
