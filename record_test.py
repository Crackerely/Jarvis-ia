import wave
import pyaudio

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
CHUNK = 1024
RECORD_SECONDS = 5
OUTPUT_FILENAME = "test_microphone.wav"

audio = pyaudio.PyAudio()

print("[INFO] Initializing audio stream...")
stream = audio.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=RATE,
    input=True,
    frames_per_buffer=CHUNK
)

print("[INFO] Recording... Speak into the microphone for 5 seconds.")
frames = []

for _ in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
    data = stream.read(CHUNK)
    frames.append(data)

print("[INFO] Recording finished.")

stream.stop_stream()
stream.close()
audio.terminate()

wave_file = wave.open(OUTPUT_FILENAME, "wb")
wave_file.setnchannels(CHANNELS)
wave_file.setsampwidth(audio.get_sample_size(FORMAT))
wave_file.setframerate(RATE)
wave_file.writeframes(b"".join(frames))
wave_file.close()

print(f"[SUCCESS] Audio file successfully saved as: {OUTPUT_FILENAME}")
