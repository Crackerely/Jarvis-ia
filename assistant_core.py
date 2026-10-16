import glob
import json
import os
import subprocess
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2"


def query_ollama_intent(user_text):
  system_prompt = (
      "You are a smart home assistant intent router. Analyze the user input."
      " If the user wants to play music, a song, or an artist, output a JSON"
      ' object: {"action": "play_music", "song": "song name"}. If the user'
      ' asks a general question or wants to chat, output: {"action": "chat",'
      ' "response": "your spoken answer"}. Output ONLY valid JSON.'
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
    print(f"[ERROR] Failed to communicate with Ollama: {e}")
    return {
        "action": "chat",
        "response": "System error processing local intelligence.",
    }


def execute_action(intent_data):
  action = intent_data.get("action")

  if action == "play_music":
    song = intent_data.get("song", "")
    print(f"[INFO] Executing action: Play music -> '{song}'")
    try:
      # Clean up previous temporary tracks
      for old_file in glob.glob("/tmp/jarvis_song.*"):
        try:
          os.remove(old_file)
        except OSError:
          pass

      search_query = f"ytsearch1:{song} official audio"

      print("[INFO] Fetching high-quality audio track...")
      subprocess.run(
          [
              "yt-dlp",
              "-f",
              "bestaudio",
              "-o",
              "/tmp/jarvis_song.%(ext)s",
              search_query,
          ],
          check=True,
          stdout=subprocess.DEVNULL,
          stderr=subprocess.DEVNULL,
      )

      # Find the downloaded file regardless of extension (.webm, .m4a, etc.)
      downloaded_files = glob.glob("/tmp/jarvis_song.*")
      if not downloaded_files:
        print("[ERROR] Audio file not found after download.")
        return

      target_file = downloaded_files[0]

      print(f"[INFO] Playing audio track ({target_file})...")
      subprocess.run(["mpv", "--no-video", target_file], check=True)

    except Exception as e:
      print(f"[ERROR] Failed to play music: {e}")
  else:
    response_text = intent_data.get("response", "No response generated.")
    print(f"[ASSISTANT] {response_text}")


if __name__ == "__main__":
  test_inputs = [
      "Can you play El Rito by Soda Stereo?",
      "What is the capital of Honduras?",
  ]

  for text in test_inputs:
    print(f"\n[USER] {text}")
    intent = query_ollama_intent(text)
    print(f"[DEBUG] Parsed Intent JSON: {intent}")
    execute_action(intent)
