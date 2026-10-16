#!/usr/bin/env bash
# Read-only: summarise the newest camera diagnostics scans (text only, no images).
# Member IDs (runs of 10-16 letters/digits containing a digit) are blanked out.
DIAGNOSTICS="$HOME/.officials_signin/diagnostics"
echo "== scans"; ls -1 "$DIAGNOSTICS" 2>/dev/null | tail -8
for folder in $(ls -1d "$DIAGNOSTICS"/*/ 2>/dev/null | tail -3); do
  echo; echo "######## $(basename "$folder")  frames: $(ls "$folder" | grep -c jpg)"
  python3 - "$folder/records.jsonl" <<'PYTHON'
import json, re, sys
ID = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{10,16}\b")
for line in open(sys.argv[1]):
    record = json.loads(line)
    kind = record.get("kind")
    if kind == "frame":
        continue
    if kind == "camera":
        settings = record.get("settings") or {}
        capabilities = record.get("capabilities") or {}
        print("CAMERA facing=%s size=%s fps=%s focus=%s zoom=%s" % (
            record.get("facing"), record.get("video_size"), settings.get("frameRate"),
            capabilities.get("focusMode"), capabilities.get("zoom")))
        print("  agent:", record.get("user_agent"), "cores:", record.get("cpu_cores"))
        continue
    if kind == "pass":
        text = ID.sub("[ID]", record.get("text", ""))
        print("--- pass %s layout=%s rot=%s mirror=%s frame=%s prep=%sms ocr=%sms card=%s t=%sms" % (
            record.get("pass"), record.get("layout"), record.get("rotation"), record.get("mirrored"),
            record.get("frame_size"), record.get("prepare_ms"), record.get("ocr_ms"), record.get("card_words"),
            record.get("elapsed_ms")))
        if record.get("card_words"):
            print("\n".join("    | " + line for line in text.splitlines() if line.strip())[:1500])
        continue
    print(kind.upper(), {key: value for key, value in record.items() if key != "kind"})
PYTHON
done
