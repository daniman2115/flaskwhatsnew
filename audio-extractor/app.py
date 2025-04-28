import os
from flask import Flask, request, jsonify, send_file
import ffmpeg
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Config
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['VIDEOS_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'videos')
app.config['AUDIO_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'audio')
app.config['ALLOWED_EXTENSIONS'] = {'mp4', 'avi', 'mov', 'mkv'}
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB limit

# Ensure upload directories exist
os.makedirs(app.config['VIDEOS_FOLDER'], exist_ok=True)
os.makedirs(app.config['AUDIO_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/api/extract-audio', methods=['POST'])
def extract_audio():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type'}), 400

    # Get the custom name from the form
    custom_name = request.form.get('name')
    if not custom_name:
        return jsonify({'error': 'No custom name provided'}), 400

    try:
        # Clean the custom name to be safe
        safe_name = secure_filename(custom_name)

        # Get original extension
        extension = file.filename.rsplit('.', 1)[1].lower()

        # Save video with custom name
        video_filename = f"{safe_name}.{extension}"
        video_path = os.path.join(app.config['VIDEOS_FOLDER'], video_filename)
        file.save(video_path)

        # Extract audio (MP3 format) with the same custom name
        audio_filename = f"{safe_name}.mp3"
        audio_path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)

        (
            ffmpeg.input(video_path)
            .output(audio_path, acodec='libmp3lame', audio_bitrate='192k')
            .overwrite_output()
            .run(quiet=True)
        )

        return jsonify({
            'status': 'success',
            'video_url': f'/api/videos/{video_filename}',
            'audio_url': f'/api/download/{audio_filename}',
            'video_filename': video_filename,
            'audio_filename': audio_filename
        })

    except ffmpeg.Error as e:
        return jsonify({'error': 'FFmpeg processing failed', 'details': str(e)}), 500
    except Exception as e:
        return jsonify({'error': 'Server error', 'details': str(e)}), 500

@app.route('/api/download/<filename>', methods=['GET'])
def download_audio(filename):
    try:
        audio_path = os.path.join(app.config['AUDIO_FOLDER'], filename)
        return send_file(audio_path, as_attachment=True)
    except FileNotFoundError:
        return jsonify({'error': 'Audio file not found'}), 404

@app.route('/api/videos/<filename>', methods=['GET'])
def download_video(filename):
    try:
        video_path = os.path.join(app.config['VIDEOS_FOLDER'], filename)
        return send_file(video_path, as_attachment=True)
    except FileNotFoundError:
        return jsonify({'error': 'Video file not found'}), 404

@app.route('/api/list-files', methods=['GET'])
def list_files():
    try:
        videos = os.listdir(app.config['VIDEOS_FOLDER'])
        audio_files = os.listdir(app.config['AUDIO_FOLDER'])
        
        return jsonify({
            'status': 'success',
            'videos': videos,
            'audio_files': audio_files
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
