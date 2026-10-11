curl -s -o /dev/null -w "server status %{http_code}\n" http://127.0.0.1:8000/
curl -s http://127.0.0.1:8000/api/clips; echo; ls ~/.dq_transcribe; ls ~/.dq_transcribe/recordings 2>&1
