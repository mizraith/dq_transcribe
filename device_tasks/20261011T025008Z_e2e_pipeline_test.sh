#!/usr/bin/env bash
# Restart the dq_transcribe server on this device, upload two sample clips, and
# report what the pipeline produced. Only writes under ~/.dq_transcribe.
#   clip A: the JFK sample once
#   clip B: JFK + 1.5 s silence + JFK (should split into two turns)
# Clip B starts 2 s after clip A ends, so both should land in one group.

SERVER_PATTERN="python -m dq_transcribe"
SERVER_LOG="$HOME/.dq_transcribe/server.log"
SAMPLE_WAV="$HOME/.dq_transcribe/whisper.cpp/samples/jfk.wav"
STARTUP_WAIT_SECONDS=3
MAX_WAIT_SECONDS=240

mkdir -p "$HOME/.dq_transcribe"
pkill -f "$SERVER_PATTERN" 2>/dev/null && sleep 1
PYTHONPATH=src nohup python -m dq_transcribe > "$SERVER_LOG" 2>&1 &
disown
sleep "$STARTUP_WAIT_SECONDS"

python - "$SAMPLE_WAV" "$MAX_WAIT_SECONDS" <<'PYTHON'
import array, io, json, sys, time, urllib.request, wave
from datetime import datetime, timedelta, timezone

BASE = "http://127.0.0.1:8000"
sample_path, max_wait = sys.argv[1], float(sys.argv[2])

with wave.open(sample_path, "rb") as source:
    params = source.getparams()
    jfk_frames = source.readframes(source.getnframes())
rate = params.framerate
jfk_seconds = len(jfk_frames) / 2 / rate
silence = array.array("h", [0] * int(1.5 * rate)).tobytes()

def wav_bytes(frames):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate)
        out.writeframes(frames)
    return buffer.getvalue()

def upload(frames, start):
    seconds = len(frames) / 2 / rate
    info = {"startedAt": start.isoformat().replace("+00:00", "Z"),
            "endedAt": (start + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")}
    request = urllib.request.Request(BASE + "/api/clips", data=wav_bytes(frames), method="POST",
        headers={"Content-Type": "audio/wav", "X-Capture-Info": json.dumps(info)})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)

start = datetime.now(timezone.utc)
print("upload A:", upload(jfk_frames, start))
start_b = start + timedelta(seconds=jfk_seconds + 2)
print("upload B:", upload(jfk_frames + silence + jfk_frames, start_b))

deadline = time.time() + max_wait
while time.time() < deadline:
    with urllib.request.urlopen(BASE + "/api/clips", timeout=10) as response:
        clips = json.load(response)["clips"]
    if clips and all(c["status"] in ("done", "failed") for c in clips):
        break
    time.sleep(3)
for clip in sorted(clips, key=lambda c: c["id"]):
    print(f"clip {clip['id']} group={clip['group_id']} status={clip['status']} "
          f"duration={clip['duration_seconds']} transcribe_seconds={clip['transcribe_seconds']} err={clip['error_message']}")
    for u in clip["utterances"]:
        print(f"   [{u['start_seconds']:.1f}-{u['end_seconds']:.1f}] {u['text']}")
with urllib.request.urlopen(BASE + "/api/transcript.txt", timeout=10) as response:
    print("--- transcript.txt ---"); print(response.read().decode())
PYTHON
echo "--- server log (tail) ---"; tail -20 "$SERVER_LOG"
