#!/usr/bin/env bash
# Restart with the refine pass at lower CPU priority, re-measure with temporary
# copies of clips 4-6 (deleted afterwards), and measure whisper's model-load overhead.
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 1
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
sleep 3
W="$HOME/.dq_transcribe/whisper.cpp"; export LD_LIBRARY_PATH="$W/build/bin"
echo "--- model load overhead (1 s of silence, idle tablet) ---"
python -c "import wave;w=wave.open('$HOME/.dq_transcribe/tmp/silence.wav','wb');w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*16000);w.close()"
for m in base small.en; do s=$(date +%s.%N); "$W/build/bin/whisper-cli" -m "$W/models/ggml-$m.bin" -f "$HOME/.dq_transcribe/tmp/silence.wav" -t 4 -l en -nt >/dev/null 2>&1; e=$(date +%s.%N); python -c "print('$m', round($e-$s,1), 's')"; done
rm -f "$HOME/.dq_transcribe/tmp/silence.wav"
ls "$W/build/bin" | grep -i server
nproc; cat /proc/cpuinfo | grep -c processor
echo "--- two-pass run ---"
bash device_tasks/measure_two_pass_with_copies.sh 2>&1 | grep -v "^clips in"
