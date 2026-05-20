# Repository Instructions

## Termux Temporary Paths

- Do not hard-code `/tmp` for this repository.
- In Termux, use `$TMPDIR` for shell commands and Python `tempfile` APIs for
  test/runtime temporary data.
- If an explicit temporary path is needed in a command, prefer
  `${TMPDIR:-/data/data/com.termux/files/usr/tmp}`.
- Keep project runtime outputs under `.photos-data/` unless the task specifically
  needs a disposable temporary directory.
- Before using a new temporary location, verify it is writable in the current
  environment.

Rationale: Android/Termux may expose a `/tmp` directory that exists but is not
writable by the Termux app UID. `$TMPDIR` points to the Termux-owned temporary
directory and is the portable default for this project.
