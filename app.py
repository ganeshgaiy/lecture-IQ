from flask import Flask, flash, render_template, request, session, url_for, redirect
from dotenv import load_dotenv
import os, urllib, requests, logging
from datetime import datetime
import whisper

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Set the secret key for session management
app.secret_key = os.getenv('SECRET_KEY')

ZOOM_OAUTH_AUTHORIZE_API = 'https://zoom.us/oauth/authorize?'
ZOOM_TOKEN_API = 'https://zoom.us/oauth/token'

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/zoom-login')
def login():
    if not session.get("token"):
        params = {
            'response_type': 'code',
            'client_id': os.getenv("CLIENT_ID"),
            'redirect_uri': os.getenv("ZOOM_REDIRECT_URI"),
        }
        url = ZOOM_OAUTH_AUTHORIZE_API + urllib.parse.urlencode(params)
        return redirect(url)
    else:
        return redirect(url_for("recordings"))
    
@app.route('/recordings')
def recordings():
    token = session.get('token')
    if token is None:
        return redirect(url_for('zoom-login'))
    # app.logger.debug(f'token {token}')
    headers = {'Authorization': f'Bearer {token["access_token"]}'}
    # app.logger.debug(f'token-access {token["access_token"]}')
    user_info = requests.get('https://api.zoom.us/v2/users/me', headers=headers)
    if user_info.status_code == 401:  # Unauthorized, try refreshing token
        access_token = refresh_token()
        headers['Authorization'] = f'Bearer {access_token}'
        user_info = requests.get('https://api.zoom.us/v2/users/me', headers=headers)
        
    print(user_info)
    user_info_json = user_info.json()
    # app.logger.debug(f'user_info {user_info_json}')

    user_id = user_info_json['id']
    current_date = datetime.now().strftime('%Y-%m-%d')
    params = {
        'from': "2023-01-01",
        'to': current_date
    }
    recordings = requests.get(f'https://api.zoom.us/v2/users/{user_id}/recordings', headers=headers, params=params)
    recordings_json = recordings.json()
    app.logger.debug(f'recordings {recordings_json}')

    return render_template('recordings.html', meetings=recordings_json.get('meetings',[]))

def refresh_token():
    token = session.get("token")
    if not token or "refresh_token" not in token:
        return redirect(url_for('login'))

    client_auth = requests.auth.HTTPBasicAuth(os.getenv("CLIENT_ID"), os.getenv("CLIENT_SECRET"))
    post_data = {
        "grant_type": "refresh_token",
        "refresh_token": token["refresh_token"]
    }
    token_response = requests.post("https://zoom.us/oauth/token",
                                   auth=client_auth,
                                   data=post_data)

    if token_response.status_code != 200:
        return redirect(url_for('login'))

    try:
        token_json = token_response.json()
    except requests.exceptions.JSONDecodeError:
        return redirect(url_for('login'))

    session["token"] = token_json
    return token_json["access_token"]

@app.route('/authorize')
def get_token():
    # if not session["token"]:

    code = request.args.get('code')
    # get_token(code)
    # Note: In most cases, you'll want to store the access token, in, say,
    # a session for use in other parts of your web app.
    # return "Your user info is: %s" % get_username(access_token)
    # get_recordings()

    client_auth = requests.auth.HTTPBasicAuth(os.getenv("CLIENT_ID"), os.getenv("CLIENT_SECRET"))
    app.logger.debug(f'client ID is: {client_auth}')
    post_data = {"grant_type": "authorization_code",
                 "code": code,
                 "redirect_uri": os.getenv("ZOOM_REDIRECT_URI")}
    app.logger.debug(f'post data is {post_data}')
    token_response = requests.post("https://zoom.us/oauth/token",
                             auth=client_auth,
                             data=post_data)
    # token = response.json()

    print(token_response)
    if token_response.status_code != 200:
        
        return f"Failed to get token: {token_response.text}"
    
    try:
        token_json = token_response.json()
    except requests.exceptions.JSONDecodeError:
        return "Failed to decode token response"
    
    session["token"] = token_json
    # return token_json["access_token"]
    return redirect(url_for('recordings'))

@app.route('/getAudioTranscript', methods=['GET'])
def getTranscript():
    recording_id = request.args.get('meeting_id')
    if not recording_id:
        flash('No recording ID provided')
        return redirect(url_for('recordings'))
    
    token = session.get('token')
    if not token:
        return redirect(url_for('zoom-login'))
    
    headers = {'Authorization': f'Bearer {token["access_token"]}'}
    recordings = requests.get(f'https://api.zoom.us/v2/meetings/{recording_id}/recordings', headers=headers)
    
    if recordings.status_code != 200:
        return f"Failed to retrieve recording: {recordings.text}"
    
    recordings_json = recordings.json()
    app.logger.debug(f'post data is {recordings_json}')

    recording_files = recordings_json['recording_files']

    for file in recording_files:
        if file.get('file_type')=="M4A":
            print("********",file.get("download_url"))
            download_link = f'{file.get("download_url")}?access_token={token["access_token"]}&playback_access_token={recordings_json.get("recording_play_passcode")}'
            local_file = download_audio_file(download_link, "local_file.m4a") 
            model = whisper.load_model("small")
            result = model.transcribe(local_file)
            with open("result.txt", 'w') as f:
                f.write(result["text"])
            app.logger.debug(f'transcribe text is {result["text"]}')
            break
    return 
            

def download_audio_file(url, local_filename):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    with requests.get(url, stream=True, headers=headers, allow_redirects=True) as r:
        r.raise_for_status()
        with open(local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return local_filename

if __name__ == '__main__':
    app.run(debug=True)