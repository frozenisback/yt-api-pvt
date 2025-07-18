import os
import shutil
import requests
from flask import Flask, request, jsonify
from http.cookiejar import MozillaCookieJar
from youtube_search import YoutubeSearch
from yt_dlp import YoutubeDL

app = Flask(__name__)

# Load cookies into requests for search functionality
cookie_file = os.path.join(os.getcwd(), 'cookies.txt')
if os.path.exists(cookie_file):
    jar = MozillaCookieJar(cookie_file)
    jar.load(ignore_discard=True, ignore_expires=True)
    session = requests.Session()
    session.cookies = jar
    orig_get = requests.get
    def get_with_cookies(url, **kwargs):
        kwargs.setdefault('cookies', session.cookies)
        return orig_get(url, **kwargs)
    requests.get = get_with_cookies

def to_iso_duration(duration_str):
    parts = duration_str.split(':') if duration_str else []
    iso = 'PT'
    if len(parts) == 3:
        h, m, s = parts
        if int(h): iso += f"{int(h)}H"
        iso += f"{int(m)}M{int(s)}S"
    elif len(parts) == 2:
        m, s = parts
        iso += f"{int(m)}M{int(s)}S"
    elif len(parts) == 1 and parts[0].isdigit():
        iso += f"{int(parts[0])}S"
    else:
        iso += "0S"
    return iso

@app.route('/search')
def search():
    title = request.args.get('title', '').strip()
    if not title:
        return jsonify(error="Missing 'title' parameter"), 400
    try:
        results = YoutubeSearch(title, max_results=1).to_dict()
        if not results:
            return jsonify(error="No results"), 404
        f = results[0]
        vid = f['url_suffix'].split('v=')[-1]
        return jsonify(
            title=f['title'],
            link=f"https://www.youtube.com/watch?v={vid}",
            duration=to_iso_duration(f.get('duration')),
            thumbnail=f.get('thumbnails', [None])[0]
        )
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route('/down')
def down():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify(error="Missing 'url' parameter"), 400

    # Prepare yt-dlp options
    ydl_opts = {
        'noplaylist': True,
        'format': 'best',
        'skip_download': True,
    }
    # Copy cookie file to writable /tmp directory if exists
    if os.path.exists(cookie_file):
        tmp_path = '/tmp/cookies.txt'
        shutil.copy(cookie_file, tmp_path)
        ydl_opts['cookiefile'] = tmp_path

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        formats = info.get('formats', [])
        top = sorted(formats, key=lambda f: f.get('resolution') or 0, reverse=True)[:3]
        return jsonify([
            {
                'format_id': f.get('format_id'),
                'ext': f.get('ext'),
                'resolution': f.get('resolution'),
                'url': f.get('url')
            } for f in top
        ])
    except Exception as e:
        return jsonify(error=str(e)), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
