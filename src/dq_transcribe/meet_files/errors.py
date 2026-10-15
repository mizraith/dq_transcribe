"""Errors raised while reading Meet Manager files (their messages are shown to the admin)."""


class MeetFileError(Exception):
    """A meet file could not be read; the message says why in plain words."""
