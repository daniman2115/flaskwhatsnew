import os
from flask import Flask, request, jsonify, send_file
import ffmpeg
from werkzeug.utils import secure_filename
import json
from vosk import Model, KaldiRecognizer
import wave
from datetime import datetime

app = Flask(__name__)

# Config
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['VIDEOS_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'videos')
app.config['AUDIO_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'audio')
app.config['TRANSCRIPTIONS_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'transcriptions')
app.config['MASTER_TRANSCRIPT'] = os.path.join(app.config['UPLOAD_FOLDER'], 'master_transcript.txt')
app.config['ALLOWED_EXTENSIONS'] = {'mp4', 'avi', 'mov', 'mkv', 'mp3', 'wav'}
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB limit
app.config['VOSK_MODEL_PATH'] = 'models/vosk-model-small-en-us-0.15'

# Ensure upload directories exist
os.makedirs(app.config['VIDEOS_FOLDER'], exist_ok=True)
os.makedirs(app.config['AUDIO_FOLDER'], exist_ok=True)
os.makedirs(app.config['TRANSCRIPTIONS_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def convert_to_wav(input_path, output_path):
    """Convert any audio file to Vosk-compatible WAV format"""
    (
        ffmpeg.input(input_path)
        .output(output_path, acodec='pcm_s16le', ac=1, ar='16000')
        .overwrite_output()
        .run(quiet=True)
    )

def transcribe_audio(audio_path):
    if not os.path.exists(app.config['VOSK_MODEL_PATH']):
        raise ValueError(f"Could not find Vosk model at {app.config['VOSK_MODEL_PATH']}")
    
    model = Model(app.config['VOSK_MODEL_PATH'])
    rec = KaldiRecognizer(model, 16000)
    rec.SetWords(True)

    try:
        wf = wave.open(audio_path, "rb")
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
            raise ValueError("Audio file must be WAV format mono PCM")
        
        results = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                part_result = json.loads(rec.Result())
                results.append(part_result)
        
        final_result = json.loads(rec.FinalResult())
        results.append(final_result)
        
        return " ".join([result['text'] for result in results if 'text' in result]).strip()
    
    except Exception as e:
        raise Exception(f"Transcription failed: {str(e)}")

def save_to_master_transcript(filename, transcription):
    """Append transcription to master transcript file with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n\n--- {filename} ({timestamp}) ---\n{transcription}"
    
    with open(app.config['MASTER_TRANSCRIPT'], 'a', encoding='utf-8') as f:
        f.write(entry)

def get_unique_filename(base_name, extension, folder):
    """Generate a unique filename by appending a number if needed"""
    counter = 1
    name, ext = os.path.splitext(base_name)
    new_filename = f"{name}{extension}"
    
    while os.path.exists(os.path.join(folder, new_filename)):
        new_filename = f"{name}_{counter}{extension}"
        counter += 1
    
    return new_filename

@app.route('/api/extract-audio', methods=['POST'])
def extract_audio():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type'}), 400

    try:
        # Get custom name from form data or use original filename
        custom_name = request.form.get('name', '').strip()
        if not custom_name:
            custom_name = os.path.splitext(secure_filename(file.filename))[0]
        
        # Generate unique filenames with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{custom_name}_{timestamp}"
        
        # Get unique filenames if duplicates exist
        video_filename = get_unique_filename(base_name, '.mp4', app.config['VIDEOS_FOLDER'])
        audio_filename = get_unique_filename(base_name, '.wav', app.config['AUDIO_FOLDER'])
        transcription_filename = get_unique_filename(base_name, '.txt', app.config['TRANSCRIPTIONS_FOLDER'])
        
        video_path = os.path.join(app.config['VIDEOS_FOLDER'], video_filename)
        audio_path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)
        transcription_path = os.path.join(app.config['TRANSCRIPTIONS_FOLDER'], transcription_filename)

        # Save video file
        file.save(video_path)

        # Extract and convert audio to Vosk-compatible WAV
        convert_to_wav(video_path, audio_path)

        # Automatically transcribe the audio
        transcription = transcribe_audio(audio_path)
        
        # Save individual transcription
        with open(transcription_path, 'w', encoding='utf-8') as f:
            f.write(transcription)
        
        # Append to master transcript
        save_to_master_transcript(video_filename, transcription)

        return jsonify({
            'status': 'success',
            'video_url': f'/api/videos/{video_filename}',
            'audio_url': f'/api/download/{audio_filename}',
            'transcription_url': f'/api/download-transcription/{transcription_filename}',
            'master_transcript_url': '/api/download-master-transcript',
            'transcription_preview': transcription[:200] + '...' if len(transcription) > 200 else transcription,
            'video_filename': video_filename,
            'audio_filename': audio_filename,
            'transcription_filename': transcription_filename
        })

    except ffmpeg.Error as e:
        return jsonify({'error': 'FFmpeg processing failed', 'details': str(e)}), 500
    except Exception as e:
        return jsonify({'error': 'Server error', 'details': str(e)}), 500

@app.route('/api/download-master-transcript', methods=['GET'])
def download_master_transcript():
    try:
        if not os.path.exists(app.config['MASTER_TRANSCRIPT']):
            return jsonify({'error': 'Master transcript not found'}), 404
        return send_file(app.config['MASTER_TRANSCRIPT'], as_attachment=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download-transcription/<filename>', methods=['GET'])
def download_transcription(filename):
    try:
        transcription_path = os.path.join(app.config['TRANSCRIPTIONS_FOLDER'], filename)
        return send_file(transcription_path, as_attachment=True)
    except FileNotFoundError:
        return jsonify({'error': 'Transcription file not found'}), 404

if __name__ == '__main__':
    app.run(debug=True)