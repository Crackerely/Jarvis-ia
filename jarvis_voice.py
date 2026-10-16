import contextlib
import json
import os
import re
import select
import socket
import subprocess
import sys
import termios
import time
import tty
import urllib.request
import wave
import pyaudio
from faster_whisper import WhisperModel

# Configuración Global
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2"
MPV_SOCKET = "/tmp/mpvsocket"

# Estado global de interrupción, reproducción y procesos
CANCEL_CURRENT_ACTION = False
IS_MUSIC_PAUSED = False
LAST_TOGGLE_TIME = 0
ACTIVE_SPEAK_PROC = None

print("[INFO] Cargando modelo STT Whisper (tiny optimizado para Raspberry Pi)...")
stt_model = WhisperModel("tiny", device="cpu", compute_type="int8")


@contextlib.contextmanager
def suppress_stderr():
  """Oculta mensajes molestos de ALSA/JACK en la terminal."""
  devnull = os.open(os.devnull, os.O_WRONLY)
  old_stderr = os.dup(2)
  os.dup2(devnull, 2)
  os.close(devnull)
  try:
    yield
  finally:
    os.dup2(old_stderr, 2)
    os.close(old_stderr)


def send_mpv_command(command_list):
  """Envía comandos en tiempo real al socket IPC de mpv."""
  if not os.path.exists(MPV_SOCKET):
    return False
  try:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(MPV_SOCKET)
    message = json.dumps({"command": command_list}) + "\n"
    client.sendall(message.encode("utf-8"))
    client.close()
    return True
  except Exception:
    return False


def speak(text, lang="es", block_shortcuts=False):
  """Sintetiza voz controlando el proceso de forma nativa en Python."""
  global CANCEL_CURRENT_ACTION, ACTIVE_SPEAK_PROC
  if not text.strip() or CANCEL_CURRENT_ACTION:
    return

  voice = "es" if lang.startswith("es") else "en-us"
  print(f"[JARVIS SPEAKING ({voice})]: {text}")

  ACTIVE_SPEAK_PROC = subprocess.Popen([
      "espeak-ng",
      "-v",
      voice,
      "-p",
      "40",
      "-s",
      "155",
      text,
  ])

  while ACTIVE_SPEAK_PROC.poll() is None:
    if not block_shortcuts:
      check_keyboard_shortcuts()
    if CANCEL_CURRENT_ACTION:
      try:
        ACTIVE_SPEAK_PROC.kill()
      except Exception:
        pass
      break
  ACTIVE_SPEAK_PROC = None


def get_single_key():
  """Lee una sola tecla filtrando secuencias de escape de terminales modernas."""
  if not sys.stdin.isatty():
    return ""

  dr, _, _ = select.select([sys.stdin], [], [], 0.01)
  if not dr:
    return ""

  old_settings = termios.tcgetattr(sys.stdin)
  try:
    tty.setraw(sys.stdin.fileno())
    ch = sys.stdin.read(1)

    if ch == "\x1b":
      select.select([sys.stdin], [], [], 0.02)
      while select.select([sys.stdin], [], [], 0.001)[0]:
        sys.stdin.read(1)
      return ""

    return ch
  finally:
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


def toggle_music_pause():
  """Pausa/reanuda mpv de forma limpia evitando rebotes de tecla."""
  global IS_MUSIC_PAUSED, LAST_TOGGLE_TIME

  current_time = time.time()
  if current_time - LAST_TOGGLE_TIME < 0.5:  # Antirrebote de 500ms
    return

  LAST_TOGGLE_TIME = current_time

  if not IS_MUSIC_PAUSED:
    print("\n[TECLADO 'f']: Pausando...")
    send_mpv_command(["set_property", "pause", True])
    IS_MUSIC_PAUSED = True
    speak("Pausado", "es", block_shortcuts=True)
  else:
    print("\n[TECLADO 'f']: Reanudando...")
    send_mpv_command(["set_property", "pause", False])
    IS_MUSIC_PAUSED = False
    speak("Reanudado", "es", block_shortcuts=True)


def check_keyboard_shortcuts():
  """Detecta atajos globales ('d' o 'f') de forma nativa."""
  global CANCEL_CURRENT_ACTION, ACTIVE_SPEAK_PROC

  key = get_single_key().lower()
  if not key:
    return

  if key == "d":
    print("\n[TECLADO 'd']: Cancelando todo y volviendo al menú...")
    CANCEL_CURRENT_ACTION = True
    send_mpv_command(["stop"])
    if ACTIVE_SPEAK_PROC and ACTIVE_SPEAK_PROC.poll() is None:
      try:
        ACTIVE_SPEAK_PROC.kill()
      except Exception:
        pass
    try:
      termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
      pass

  elif key == "f":
    toggle_music_pause()


def hum_thinking(lang):
  """Feedback auditivo mientras descarga o busca."""
  voice = "es" if lang.startswith("es") else "en-us"
  hum_text = "estoy en eso maldita puta dame tiempo mi cerebro es lento"
  print(f"[JARVIS THINKING]: *{hum_text}*")
  speak(hum_text, lang)


def wait_for_wakeword():
  """Escucha la wake word, ENTER, 'e' (escritura limpia) o atajos."""
  global CANCEL_CURRENT_ACTION, IS_MUSIC_PAUSED
  CANCEL_CURRENT_ACTION = False

  FORMAT = pyaudio.paInt16
  CHANNELS = 1
  RATE = 16000
  CHUNK = 1024
  TEMP_WAKE_FILE = "/tmp/wakeword_check.wav"

  print(
      "\n[LISTENING...] Di 'Jarvis activar' | ENTER (hablar) | 'e' (escribir) |"
      " Atajos: 'd' parar, 'f' pausar"
  )

  with suppress_stderr():
    audio = pyaudio.PyAudio()
    stream = audio.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )

  frames = []
  try:
    while True:
      if CANCEL_CURRENT_ACTION:
        stream.stop_stream()
        stream.close()
        audio.terminate()
        return ("cancel", None)

      key = get_single_key()
      if key:
        if key.lower() == "d":
          print("\n[TECLADO 'd']: Cancelando reproducción...")
          send_mpv_command(["stop"])
          if ACTIVE_SPEAK_PROC and ACTIVE_SPEAK_PROC.poll() is None:
            try:
              ACTIVE_SPEAK_PROC.kill()
            except Exception:
              pass
          try:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
          except Exception:
            pass
          CANCEL_CURRENT_ACTION = True
          stream.stop_stream()
          stream.close()
          audio.terminate()
          return ("cancel", None)

        elif key.lower() == "f":
          toggle_music_pause()

        elif key.lower() == "e":
          print("e")
          print("\n[TECLADO 'e']: Modo texto activado.")
          stream.stop_stream()
          stream.close()
          audio.terminate()

          try:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
          except Exception:
            pass

          speak("escribe lo que quieres nene", "es")

          try:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
          except Exception:
            pass

          typed_input = input(
              "\nEscribe tu comando para Jarvis (enter para enviarlo): "
          ).strip()
          return ("text", typed_input)

        elif key in ["\n", "\r"]:
          print("\n[TECLADO]: ¡Activación manual por ENTER!")
          stream.stop_stream()
          stream.close()
          audio.terminate()
          try:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
          except Exception:
            pass
          return ("voice", None)

      data = stream.read(CHUNK, exception_on_overflow=False)
      frames.append(data)

      if len(frames) >= 31:
        wf = wave.open(TEMP_WAKE_FILE, "wb")
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))
        wf.close()

        segments, _ = stt_model.transcribe(TEMP_WAKE_FILE, beam_size=1)
        text = "".join([s.text for s in segments]).strip().lower()

        if "jarvis" in text or "activar" in text or "activa" in text or "ak" in text:
          print(f"\n[WAKEWORD DETECTED]: Intent matched -> '{text}'")
          stream.stop_stream()
          stream.close()
          audio.terminate()
          try:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
          except Exception:
            pass
          return ("voice", None)

        frames = frames[-10:]

  except Exception as e:
    print(f"[ERROR WAKEWORD]: {e}")
    try:
      stream.stop_stream()
      stream.close()
      audio.terminate()
    except Exception:
      pass
    return ("cancel", None)


def record_user_command(output_filename="/tmp/user_input.wav", record_seconds=5):
  """Confirma con 'Escuchando' y graba la orden del usuario."""
  global CANCEL_CURRENT_ACTION
  if CANCEL_CURRENT_ACTION:
    return None

  speak("Escuchando", "es")

  FORMAT = pyaudio.paInt16
  CHANNELS = 1
  RATE = 16000
  CHUNK = 1024

  print("[JARVIS]: Escuchando comando...")

  with suppress_stderr():
    audio = pyaudio.PyAudio()
    stream = audio.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )

  frames = []
  for _ in range(0, int(RATE / CHUNK * record_seconds)):
    check_keyboard_shortcuts()
    if CANCEL_CURRENT_ACTION:
      print("\n[INFO] Grabación cancelada por tecla 'd'.")
      try:
        stream.stop_stream()
        stream.close()
        audio.terminate()
      except Exception:
        pass
      return None

    data = stream.read(CHUNK, exception_on_overflow=False)
    frames.append(data)

  print("[INFO] Grabación terminada. Procesando...")

  try:
    stream.stop_stream()
    stream.close()
    audio.terminate()
  except Exception:
    pass

  wf = wave.open(output_filename, "wb")
  wf.setnchannels(CHANNELS)
  wf.setsampwidth(audio.get_sample_size(FORMAT))
  wf.setframerate(RATE)
  wf.writeframes(b"".join(frames))
  wf.close()

  return output_filename


def transcribe_audio(audio_file):
  """Transcribe audio y detecta idioma."""
  if not audio_file or os.path.getsize(audio_file) == 0:
    return "", "es"
  segments, info = stt_model.transcribe(audio_file, beam_size=5)
  text = "".join([segment.text for segment in segments]).strip()
  detected_lang = info.language
  return text, detected_lang


def stream_ollama_chat(user_text, lang):
  """STREAMING TTS: Respuestas ultracortas y directas en tiempo real."""
  global CANCEL_CURRENT_ACTION

  system_prompt = (
      "You are Jarvis, an ultra-concise bilingual voice assistant. Give"
      " extremely short, direct, and precise answers in the SAME language as"
      f" the user input ({lang}). NEVER give long explanations or full"
      " context. Maximum 1 sentence. Straight to the point."
  )

  data = {
      "model": MODEL,
      "prompt": f"{system_prompt}\nUser: {user_text}\nJarvis:",
      "stream": True,
  }

  req = urllib.request.Request(
      OLLAMA_URL,
      data=json.dumps(data).encode("utf-8"),
      headers={"Content-Type": "application/json"},
  )

  try:
    with urllib.request.urlopen(req) as response:
      sentence_buffer = ""
      for line in response:
        check_keyboard_shortcuts()
        if CANCEL_CURRENT_ACTION:
          print("\n[INFO] Chat cancelado por tecla 'd'.")
          return

        if line:
          chunk = json.loads(line.decode("utf-8"))
          text_token = chunk.get("response", "")
          sentence_buffer += text_token

          if any(sentence_buffer.endswith(p) for p in [".", "!", "?", "\n"]):
            clean_sentence = sentence_buffer.strip()
            if clean_sentence:
              speak(clean_sentence, lang)
            sentence_buffer = ""

      if sentence_buffer.strip() and not CANCEL_CURRENT_ACTION:
        speak(sentence_buffer.strip(), lang)

  except Exception as e:
    print(f"[ERROR OLLAMA STREAM]: {e}")
    speak("Hubo un error.", lang)


def query_ollama_intent(user_text, lang):
  """Enruta intenciones extrayendo limpiamente la canción solicitada."""
  system_prompt = (
      "You are a bilingual smart home assistant intent router. Analyze the user"
      " input.\n"
      "1. If user wants to stop/pause/resume/volume music, output JSON:\n"
      '   {"action": "control_playback", "command":'
      ' "stop|pause|resume|volume_up|volume_down"}\n'
      "2. If user mentions ANY song, track name, album, or music artist, output"
      " JSON:\n"
      '   {"action": "play_music", "song": "the exact song title and'
      ' artist requested by the user"}\n'
      "3. ONLY if the user asks a genuine non-music question or wants to chat"
      " about general topics, output JSON:\n"
      '   {"action": "chat"}\n'
      "Do NOT use dollar signs ($) in artist names.\n"
      "Output ONLY valid JSON."
  )

  full_prompt = f"{system_prompt}\nUser input: {user_text}\nJSON response:"

  data = {
      "model": MODEL,
      "prompt": full_prompt,
      "stream": False,
      "format": "json",
  }

  req = urllib.request.Request(
      OLLAMA_URL,
      data=json.dumps(data).encode("utf-8"),
      headers={"Content-Type": "application/json"},
  )

  try:
    with urllib.request.urlopen(req) as response:
      result = json.loads(response.read().decode("utf-8"))
      raw_response = result.get("response", "{}")
      return json.loads(raw_response)
  except Exception as e:
    print(f"[ERROR OLLAMA INTENT]: {e}")
    return {"action": "chat"}


def execute_action(intent_data, user_text, lang):
  global CANCEL_CURRENT_ACTION, IS_MUSIC_PAUSED
  if CANCEL_CURRENT_ACTION:
    return

  action = intent_data.get("action")

  if action == "control_playback":
    cmd = intent_data.get("command")
    if cmd == "stop":
      send_mpv_command(["stop"])
      speak("Música detenida." if lang.startswith("es") else "Music stopped.", lang)
    elif cmd == "pause":
      send_mpv_command(["set_property", "pause", True])
      IS_MUSIC_PAUSED = True
      speak("Pausado", lang, block_shortcuts=True)
    elif cmd == "resume":
      send_mpv_command(["set_property", "pause", False])
      IS_MUSIC_PAUSED = False
      speak("Reanudado", lang, block_shortcuts=True)
    elif cmd == "volume_up":
      send_mpv_command(["add", "volume", 15])
      speak("Subiendo volumen." if lang.startswith("es") else "Volume up.", lang)
    elif cmd == "volume_down":
      send_mpv_command(["add", "volume", -15])
      speak("Bajando volumen." if lang.startswith("es") else "Volume down.", lang)

  elif action == "play_music":
    raw_song = intent_data.get("song", "")
    clean_song = (
        raw_song.replace("en youtube", "")
        .replace("por favor", "")
        .replace("$", "S")
        .strip()
    )
    clean_song = re.sub(r"[^\w\s]", " ", clean_song)

    print(f"[INTENT MATCHED]: Reproduciendo -> '{clean_song}'")
    hum_thinking(lang)

    if CANCEL_CURRENT_ACTION:
      return

    send_mpv_command(["stop"])
    IS_MUSIC_PAUSED = False

    if os.path.exists(MPV_SOCKET):
      try:
        os.remove(MPV_SOCKET)
      except OSError:
        pass

    search_query = f"ytsearch1:{clean_song} audio"

    mpv_cmd = [
        "mpv",
        "--no-video",
        f"--input-ipc-server={MPV_SOCKET}",
        f"ytdl://{search_query}",
    ]
    subprocess.Popen(
        mpv_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    speak(
        "Reproduciendo." if lang.startswith("es") else "Playing.",
        lang,
    )

  else:
    stream_ollama_chat(user_text, lang)


if __name__ == "__main__":
  while True:
    mode, payload = wait_for_wakeword()

    if mode == "cancel":
      continue

    if mode == "text":
      user_text = payload
      lang = "es"
    else:
      audio_path = record_user_command(record_seconds=5)
      if CANCEL_CURRENT_ACTION or not audio_path:
        continue
      user_text, lang = transcribe_audio(audio_path)

    if CANCEL_CURRENT_ACTION:
      continue

    print(f"\n[STT/Entrada Idioma]: {lang}")
    print(f"[Entrada Usuario]: '{user_text}'")

    if user_text:
      intent = query_ollama_intent(user_text, lang)
      print(f"[DEBUG Intent Parsed]: {intent}")
      execute_action(intent, user_text, lang)
    else:
      if not CANCEL_CURRENT_ACTION:
        speak("No recibí ninguna entrada.", "es")
