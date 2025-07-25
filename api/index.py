import os
import shutil
import requests
from http.cookiejar import MozillaCookieJar
from flask import Flask, request, send_file, jsonify
from youtube_search import YoutubeSearch
import yt_dlp

# -------------------------
# Constants for cookie paths
# -------------------------
COOKIE_SRC = os.path.join(os.getcwd(), 'cookies.txt')
COOKIE_TMP = '/tmp/cookies.txt'

# -------------------------
# Copy cookies.txt into /tmp (writable) on cold start
# -------------------------
if os.path.exists(COOKIE_SRC):
    try:
        shutil.copy(COOKIE_SRC, COOKIE_TMP)
    except PermissionError:
        pass  # already copied in this container

# -------------------------
# Patch requests.get to use the cookie jar
# -------------------------
if os.path.exists(COOKIE_TMP):
    jar = MozillaCookieJar(COOKIE_TMP)
    jar.load(ignore_discard=True, ignore_expires=True)
    session = requests.Session()
    session.cookies = jar
    original_get = requests.get

    def get_with_cookies(url, **kwargs):
        kwargs.setdefault('cookies', session.cookies)
        return original_get(url, **kwargs)

    requests.get = get_with_cookies

# -------------------------
# Flask App Initialization
# -------------------------
app = Flask(__name__)

# -------------------------
# Helper: Convert durations to ISO 8601
# -------------------------
def to_iso_duration(duration_str: str) -> str:
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
        iso += '0S'
    return iso

# -------------------------
# yt-dlp Options
# -------------------------
ydl_opts_full = {
    'quiet': True,
    'skip_download': True,
    'format': 'bestvideo+bestaudio/best',
    'cookiefile': COOKIE_TMP
}
ydl_opts_meta = {
    'quiet': True,
    'skip_download': True,
    'simulate': True,
    'noplaylist': True,
    'cookiefile': COOKIE_TMP
}

ydl_opts_download = {
    'quiet': True,
    'nocheckcertificate': True,
    'skip_download': False,
    'format': 'worstaudio',
    'outtmpl': '/tmp/%(id)s.%(ext)s',
    'noplaylist': True,
    'cookiefile': COOKIE_TMP,  # if you're using cookies
    'cachedir': '/tmp/yt-dlp-cache'
}



def extract_info(url=None, search_query=None, opts=None):
    opts = opts or ydl_opts_full
    with yt_dlp.YoutubeDL(opts) as ydl:
        if search_query:
            data = ydl.extract_info(f"ytsearch:{search_query}", download=False)
            entries = data.get('entries') or []
            if not entries:
                return None, {'error': 'No search results'}, 404
            return entries[0], None, None
        info = ydl.extract_info(url, download=False)
        return info, None, None

# -------------------------
# Format/List Helpers
# -------------------------
def get_size_bytes(fmt):
    return fmt.get('filesize') or fmt.get('filesize_approx') or 0

def format_size(bytes_val):
    if bytes_val >= 1e9: return f"{bytes_val/1e9:.2f} GB"
    if bytes_val >= 1e6: return f"{bytes_val/1e6:.2f} MB"
    if bytes_val >= 1e3: return f"{bytes_val/1e3:.2f} KB"
    return f"{bytes_val} B"

def build_formats_list(info):
    fmts = []
    for f in info.get('formats', []):
        url_f = f.get('url')
        if not url_f:
            continue
        has_v = f.get('vcodec') != 'none'
        has_a = f.get('acodec') != 'none'
        kind = (
            'progressive' if has_v and has_a else
            'video-only' if has_v else
            'audio-only' if has_a else
            None
        )
        if not kind:
            continue
        size = get_size_bytes(f)
        fmts.append({
            'format_id': f.get('format_id'),
            'ext': f.get('ext'),
            'kind': kind,
            'filesize_bytes': size,
            'filesize': format_size(size),
            'width': f.get('width'),
            'height': f.get('height'),
            'fps': f.get('fps'),
            'abr': f.get('abr'),
            'asr': f.get('asr'),
            'url': url_f
        })
    return fmts

# -------------------------
# Routes
# -------------------------
@app.route('/')
def home():
    return jsonify({'message': '✅ YouTube API is alive'})

@app.route('/api/fast-meta')
def api_fast_meta():
    q = request.args.get('search', '').strip()
    u = request.args.get('url', '').strip()
    if not (q or u):
        return jsonify({'error': 'Provide "search" or "url"'}), 400
    try:
        if q:
            results = YoutubeSearch(q, max_results=1).to_dict()
            if not results:
                return jsonify({'error': 'No results'}), 404
            vid = results[0]
            return jsonify({
                'title': vid['title'],
                'link': f"https://www.youtube.com/watch?v={vid['url_suffix'].split('v=')[-1]}",
                'duration': to_iso_duration(vid.get('duration', '')),
                'thumbnail': vid.get('thumbnails', [None])[0]
            })
        else:
            with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
                info = ydl.extract_info(u, download=False)
            return jsonify({
                'title': info.get('title'),
                'link': info.get('webpage_url'),
                'duration': to_iso_duration(str(info.get('duration'))),
                'thumbnail': info.get('thumbnail')
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/all')
def api_all():
    q = request.args.get('search', '').strip()
    u = request.args.get('url', '').strip()
    if not (q or u):
        return jsonify({'error': 'Provide "search" or "url"'}), 400
    info, err, code = extract_info(u or None, q or None)
    if err:
        return jsonify(err), code
    fmts = build_formats_list(info)
    suggestions = [{
        'id': rel.get('id'),
        'title': rel.get('title'),
        'url': rel.get('webpage_url') or rel.get('url'),
        'thumbnail': rel.get('thumbnails', [{}])[0].get('url')
    } for rel in info.get('related', [])]
    return jsonify({
        'title': info.get('title'),
        'video_url': info.get('webpage_url'),
        'duration': info.get('duration'),
        'upload_date': info.get('upload_date'),
        'view_count': info.get('view_count'),
        'like_count': info.get('like_count'),
        'thumbnail': info.get('thumbnail'),
        'description': info.get('description'),
        'tags': info.get('tags'),
        'is_live': info.get('is_live'),
        'age_limit': info.get('age_limit'),
        'average_rating': info.get('average_rating'),
        'channel': {
            'name': info.get('uploader'),
            'url': info.get('uploader_url') or info.get('channel_url'),
            'id': info.get('uploader_id')
        },
        'formats': fmts,
        'suggestions': suggestions
    })

@app.route('/api/meta')
def api_meta():
    q = request.args.get('search', '').strip()
    u = request.args.get('url', '').strip()
    if not (q or u):
        return jsonify({'error': 'Provide "search" or "url"'}), 400
    info, err, code = extract_info(u or None, q or None, opts=ydl_opts_meta)
    if err:
        return jsonify(err), code
    keys = ['id','title','webpage_url','duration','upload_date',
            'view_count','like_count','thumbnail','description',
            'tags','is_live','age_limit','average_rating',
            'uploader','uploader_url','uploader_id']
    return jsonify({'metadata': {k: info.get(k) for k in keys}})

@app.route('/api/channel')
def api_channel():
    cid = request.args.get('id', '').strip()
    cu = request.args.get('url', '').strip()
    if not (cid or cu):
        return jsonify({'error': 'Provide "id" or "url"'}), 400
    try:
        with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
            info = ydl.extract_info(cid or cu, download=False)
        return jsonify({
            'id': info.get('id'),
            'name': info.get('uploader'),
            'url': info.get('webpage_url'),
            'description': info.get('description'),
            'subscriber_count': info.get('subscriber_count'),
            'video_count': info.get('channel_follower_count') or info.get('video_count'),
            'thumbnails': info.get('thumbnails'),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/playlist')
def api_playlist():
    pid = request.args.get('id', '').strip()
    pu = request.args.get('url', '').strip()
    if not (pid or pu):
        return jsonify({'error': 'Provide "id" or "url"'}), 400
    try:
        with yt_dlp.YoutubeDL(ydl_opts_full) as ydl:
            info = ydl.extract_info(pid or pu, download=False)
        videos = [{
            'id': e.get('id'),
            'title': e.get('title'),
            'url': e.get('webpage_url'),
            'duration': e.get('duration')
        } for e in info.get('entries', [])]
        return jsonify({
            'id': info.get('id'),
            'title': info.get('title'),
            'url': info.get('webpage_url'),
            'item_count': info.get('playlist_count'),
            'videos': videos
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/instagram')
def api_instagram():
    u = request.args.get('url', '').strip()
    if not u:
        return jsonify({'error': 'Provide "url"'}), 400
    try:
        with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
            info = ydl.extract_info(u, download=False)
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/twitter')
def api_twitter():
    u = request.args.get('url', '').strip()
    if not u:
        return jsonify({'error': 'Provide "url"'}), 400
    try:
        with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
            info = ydl.extract_info(u, download=False)
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tiktok')
def api_tiktok():
    u = request.args.get('url', '').strip()
    if not u:
        return jsonify({'error': 'Provide "url"'}), 400
    try:
        with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
            info = ydl.extract_info(u, download=False)
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/facebook')
def api_facebook():
    u = request.args.get('url', '').strip()
    if not u:
        return jsonify({'error': 'Provide "url"'}), 400
    try:
        with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
            info = ydl.extract_info(u, download=False)
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# -------------------------
# Stream Endpoints
# -------------------------
STREAM_TIMEOUT = 5 * 3600

@app.route('/download')
def download():
    url = request.args.get('url')
    search = request.args.get('search')
    if not (url or search):
        return jsonify({'error': 'Provide "url" or "search"'}), 400
    info, err, code = extract_info(url, search)
    if err:
        return jsonify(err), code
    return jsonify({'formats': build_formats_list(info)})

@app.route('/api/audio')
def api_audio():
    url = request.args.get('url')
    search = request.args.get('search')
    if not (url or search):
        return jsonify({'error': 'Provide "url" or "search"'}), 400
    info, err, code = extract_info(url, search)
    if err:
        return jsonify(err), code
    afmts = [f for f in build_formats_list(info) if f['kind'] in ('audio-only','progressive')]
    return jsonify({'audio_formats': afmts})

@app.route('/api/video')
def api_video():
    url = request.args.get('url')
    search = request.args.get('search')
    if not (url or search):
        return jsonify({'error': 'Provide "url" or "search"'}), 400
    info, err, code = extract_info(url, search)
    if err:
        return jsonify(err), code
    vfmts = [f for f in build_formats_list(info) if f['kind'] in ('video-only','progressive')]
    return jsonify({'video_formats': vfmts})


@app.route('/api/down')
def api_download_audio():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'Provide "url" parameter'}), 400

    try:
        # Download the worst-quality audio (with cookies) into /tmp
        with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
            info = ydl.extract_info(url, download=True)

        # Construct the filename from the video ID and extension
        filename = f"{info['id']}.{info.get('ext', 'm4a')}"
        filepath = os.path.join('/tmp', filename)

        # Verify download
        if not os.path.isfile(filepath):
            return jsonify({'error': 'Download failed'}), 500

        # Stream back as a file attachment
        return send_file(
            filepath,
            as_attachment=True,
            download_name=os.path.basename(filepath)
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)


