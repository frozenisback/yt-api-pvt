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

@app.route('/api/fast-meta')
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

@app.route('/api/all')
def down():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify(error="Missing 'url' parameter"), 400

    # Build a headers dict that clients should replay
    # 'Range': 'bytes=0-' allows parallel / chunked fetching
    common_headers = {
        'User-Agent': request.headers.get('User-Agent', 'yt-dlp'),
        'Accept-Language': request.headers.get('Accept-Language', 'en-US,en;q=0.5'),
        'Referer': url,
        'Range': 'bytes=0-'
    }

    # yt-dlp options
    ydl_opts = {
        'noplaylist'   : True,
        'format'       : 'best',
        'skip_download': True,
        'http_headers' : common_headers,
    }

    # Copy cookies.txt into /tmp (writable) on cold start
    if os.path.exists(cookie_file):
        tmp_path = '/tmp/cookies.txt'
        shutil.copy(cookie_file, tmp_path)
        ydl_opts['cookiefile'] = tmp_path

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # Global headers that extractor used
        global_headers = info.get('http_headers', {}) or common_headers

        # Build format list, pulling any per‐format headers too
        formats = []
        for f in info.get('formats', []):
            if not f.get('url'):
                continue
            # many extractors may attach per‐format headers under 'http_headers'
            fmt_headers = f.get('http_headers', {}) or global_headers
            formats.append({
                'format_id'    : f.get('format_id'),
                'ext'          : f.get('ext'),
                'resolution'   : f.get('resolution') or f.get('format_note'),
                'filesize'     : f.get('filesize'),
                'audio_codec'  : f.get('acodec'),
                'video_codec'  : f.get('vcodec'),
                'url'          : f.get('url'),
                'headers'      : fmt_headers,
            })

        data = {
            'title'         : info.get('title'),
            'video_url'     : info.get('webpage_url'),
            'duration'      : info.get('duration'),
            'upload_date'   : info.get('upload_date'),
            'view_count'    : info.get('view_count'),
            'like_count'    : info.get('like_count'),
            'thumbnail'     : info.get('thumbnail'),
            'description'   : info.get('description'),
            'tags'          : info.get('tags'),
            'is_live'       : info.get('is_live'),
            'age_limit'     : info.get('age_limit'),
            'average_rating': info.get('average_rating'),
            'channel'       : {
                'name': info.get('uploader'),
                'url' : info.get('uploader_url') or info.get('channel_url'),
                'id'  : info.get('uploader_id')
            },
            'formats'       : formats,
            'suggestions'   : info.get('automatic_captions', {}),
        }

        return jsonify(data)
    except Exception as e:
        return jsonify(error=str(e)), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
