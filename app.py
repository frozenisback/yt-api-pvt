import os
import requests
from http.cookiejar import MozillaCookieJar
from flask import Flask, request, jsonify
from youtube_search import YoutubeSearch

# ----- Load Cookies from a Netscape Cookie File and Patch requests.get -----
cookie_file = 'cookies.txt'
if os.path.exists(cookie_file):
    cookie_jar = MozillaCookieJar(cookie_file)
    # Load cookies from the file; ignore discard and expiration for demo purposes
    cookie_jar.load(ignore_discard=True, ignore_expires=True)
    
    # Create a session and assign the loaded cookies
    session = requests.Session()
    session.cookies = cookie_jar

    # Preserve the original requests.get function
    original_get = requests.get

    def get_with_cookies(url, **kwargs):
        # Ensure that cookies are passed with each GET request
        kwargs.setdefault("cookies", session.cookies)
        return original_get(url, **kwargs)

    # Replace requests.get with our custom version
    requests.get = get_with_cookies

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"message": "✅ YouTube Search API is alive!"})

# Helper to convert "MM:SS" or "HH:MM:SS" to ISO 8601 duration (PT...)
def to_iso_duration(duration_str: str) -> str:
    parts = duration_str.split(':') if duration_str else []
    iso = 'PT'
    if len(parts) == 3:
        h, m, s = parts
        if int(h):
            iso += f"{int(h)}H"
        iso += f"{int(m)}M{int(s)}S"
    elif len(parts) == 2:
        m, s = parts
        iso += f"{int(m)}M{int(s)}S"
    elif len(parts) == 1 and parts[0].isdigit():
        iso += f"{int(parts[0])}S"
    else:
        # Fallback if format unexpected
        iso += '0S'
    return iso

@app.route('/search', methods=['GET'])
def search():
    title = request.args.get('title', '').strip()
    if not title:
        return jsonify({"error": "Missing 'title' query parameter."}), 400

    try:
        results = YoutubeSearch(title, max_results=10).to_dict()
        if not results:
            return jsonify({"error": "No results found."}), 404

        first_video = results[0]
        iso_duration = to_iso_duration(first_video.get('duration', ''))
        video_id = first_video.get('url_suffix').split('v=')[-1]
        video_data = {
            "title": first_video.get("title"),
            "link": f"https://www.youtube.com/watch?v={video_id}",
            "duration": iso_duration,
            "thumbnail": first_video.get("thumbnails", [None])[0]
        }

        return jsonify(video_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)






