# Guidelines

Standing rules for anyone (human or AI) working in this repo.

## Owner's coding standards

- Python is the primary language. The owner knows Python well: skip beginner explanations of the language itself.
- Write readable code with descriptive variable and function names. No cryptic abbreviations.
- Write accurate, well-formatted docstrings for every module, class, and function, and a file-level docstring at the top of every file. Keep docstrings in sync when code changes.
- No "magic strings" (or magic numbers). Centralize them in `src/dq_transcribe/constants.py` so refactoring touches one place.

## Project rules

- Local-first: audio and transcripts stay on the device. Do not add cloud services for transcription or storage.
- Keep the core platform-neutral (Android/Termux today, Windows later). Put platform-specific code in clearly named modules behind a small interface.
- The owner develops on a tablet and does not want to copy and paste code. Deliver work by committing to this repo; the owner runs `git pull` in Termux.
- Be honest about what was and was not tested. Code that touches the microphone or the Whisper build can only be verified on the tablet, so say so and ask for the error text if it fails.
- Commit messages: short imperative summary line, details in the body if needed.
