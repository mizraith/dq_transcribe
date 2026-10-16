"""Officials Sign-In: a local, touch-first sign-in desk for swim meet officials.

Officials sign in on a tablet at the start of each session. The camera reads
the USA Swimming membership card on their phone (OCR in the browser), which
validates membership, background check and athlete protection training
automatically; the admin only steps in for exceptions. The app publishes a
per-session officials roster that dq_transcribe imports.

Shares no code or database with dq_transcribe; see
``ai_docs/officials_roster_format.md`` for the roster file contract.
"""
