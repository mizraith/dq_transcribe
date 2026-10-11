"""dq_transcribe: local-first audio recording and transcription.

Records audio from the device microphone, transcribes it locally (no cloud
services), and stores the results in an editable, lightweight local database.

The core package is kept platform-neutral so it can run on an Android tablet
(via Termux) and later on Windows. Anything platform-specific belongs in its
own clearly named module, not in the core.
"""

__version__ = "0.1.0"
