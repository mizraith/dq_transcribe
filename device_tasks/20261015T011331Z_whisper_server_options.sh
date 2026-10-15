#!/usr/bin/env bash
# Read-only: show whisper-server options and the request fields its /inference endpoint reads.
W="$HOME/.dq_transcribe/whisper.cpp"; export LD_LIBRARY_PATH="$W/build/bin"
"$W/build/bin/whisper-server" --help 2>&1 | grep -i -E "host|port|prompt|suppress|sns|thread|language|convert|inference|public|no-timestamps|-m " | head -30
echo "--- request fields read by the server ---"
grep -o -E 'req\.(has_file|get_file_value|has_param|get_param_value)\("[a-z_]+"' "$W/examples/server/server.cpp" | sort -u | head -40
grep -n -E '"/inference"|inference_path|/load' "$W/examples/server/server.cpp" | head -5
echo "--- agent queue check ---"; ls device_tasks | tail -3
