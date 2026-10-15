"""Read-only prompt comparison: re-transcribe speech turns of clips 25-52 through the
running whisper servers with several initial prompts, print the results as JSON lines."""
import json, os, sqlite3, subprocess, tempfile, time, urllib.request, uuid, wave

PROMPTS = {
    "none": "",
    "current": open("src/dq_transcribe/data/whisper_prompt.txt").read().strip(),
    "vocab_only": ("Possible DQ. Disqualification. One hand touch, alternating kick, scissors kick, butterfly kick, "
                   "shoulders past vertical, did not finish, underwater recovery, arms past hipline, hands not separated, "
                   "no touch at turn, delay initiating turn, false start. Accepted. Acknowledged. Confirmed."),
    "numbered": ("Radio calls between swim officials. Possible DQ, event 7, heat 2, lane 4, one hand touch. "
                 "Event 15, heat 1, lanes 3 and 8, scissors kick. Shoulders past vertical, did not finish, "
                 "underwater recovery, arms past hipline. Accepted. Acknowledged."),
}
PLAN = [("base", 8178, ["none", "current", "vocab_only", "numbered"]), ("small.en", 8179, ["vocab_only", "numbered"])]
ACK = {"accepted.", "acknowledged.", "got it.", "roger that.", "confirmed."}

db = sqlite3.connect(os.path.expanduser("~/.dq_transcribe/notes.db"))
rows = db.execute("select c.id, c.audio_filename, u.position, u.start_seconds, u.end_seconds, u.original_text "
                  "from clips c join utterances u on u.clip_id=c.id where c.id between 25 and 52 order by c.id, u.position").fetchall()
turns = [r for r in rows if r[5].strip().lower() not in ACK and (r[4] - r[3]) > 2.5]
tmp = tempfile.mkdtemp(dir=os.path.expanduser("~/.dq_transcribe/tmp"))

def cut(path, start, end, out):
    with wave.open(path, "rb") as w:
        rate = w.getframerate(); w.setpos(int(start * rate)); frames = w.readframes(int((end - start) * rate))
    with wave.open(out, "wb") as o:
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(rate); o.writeframes(frames)

def ask(port, wav, prompt):
    boundary = uuid.uuid4().hex
    fields = {"response_format": "json", "temperature": "0.0", "prompt": prompt}
    body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items())
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="t.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
    body += open(wav, "rb").read() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/inference", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.load(urllib.request.urlopen(req, timeout=300))["text"].strip()

print(json.dumps({"turns": len(turns)}))
for clip_id, name, pos, start, end, draft in turns:
    wav = os.path.join(tmp, f"{clip_id}_{pos}.wav")
    cut(os.path.expanduser(f"~/.dq_transcribe/recordings/{name}"), start, end, wav)
    result = {"clip": clip_id, "pos": pos}
    for model, port, variants in PLAN:
        for variant in variants:
            t0 = time.time()
            result[f"{model}|{variant}"] = ask(port, wav, PROMPTS[variant])
            result[f"{model}|{variant}|s"] = round(time.time() - t0, 1)
    print(json.dumps(result), flush=True)
    os.remove(wav)
os.rmdir(tmp)
