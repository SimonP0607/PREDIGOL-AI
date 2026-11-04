"""Messages to readers (plan UX, A5): one queue (``customer.messages_outbox``) for every e-mail - push joins in B7 -,
templates in Spanish and English, the provider (Resend, over HTTP), its signed webhook, the reader's preferences, and
the owner's notices about all of it (counts and a link to the console, never a reader's address or words).

The messenger process (``apps.messenger``) sends what the queue holds, with the API's database role; the worker of
PrediGol Intelligence never reads any of it. Nothing leaves while ``FBI_EMAIL_SEND`` is off: the queue fills and
waits (QA reads it there).
"""
