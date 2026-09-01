"""Scheduled agent runs.

A cron job is a prompt attached to a schedule. When the schedule fires, the
scheduler starts a fresh agent turn — no conversation, no memory of the last
run except what the job records — and delivers the answer where the job says.

The module is deliberately small and file-backed: `jobs.json` holds every job
and is written atomically, the way the user configuration is. A database
would be the wrong weight for what is, in the end, a handful of entries
somebody edits by hand when a schedule changes.
"""
