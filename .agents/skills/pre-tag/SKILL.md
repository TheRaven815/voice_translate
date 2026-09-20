---
name: pre-tag
description: Before git tag, version bump, or release commit, run the full local CI suite and CLI smoke. Triggers on tag, v0., release, git tag, push tag, version bump, cg with a version tag.
---

# Pre-tag local CI

Hard gate. Do not `git tag`, move a tag (`tag -f`), or `git push` a tag until this suite exits 0 **after the commit's code is in the working tree**.

Conversation-green is not a pass. Re-run here.

## User

Repo root, Windows:

```bat
venv\Scripts\python.exe -m pytest -q -m "not device"
venv\Scripts\python.exe -m cli --version
venv\Scripts\python.exe -m cli --list-langs
```

Must be exit code 0. Same command CI uses: `.github/workflows/ci.yml` and `release.yml`.

## Agent

1. Prefer `venv/Scripts/python.exe` when that file exists.
2. Run, timeout ≥ 180s:

```bat
venv\Scripts\python.exe -m pytest -q -m "not device"
```

3. Then:

```bat
venv\Scripts\python.exe -m cli --version
venv\Scripts\python.exe -m cli --list-langs
```

`--list-langs` must print Turkish without `UnicodeEncodeError`.

4. Any non-zero pytest, failed assert, or CLI traceback → **stop**. No commit+tag, no `tag -f`, no `push origin v*`.
5. If creating/moving `vX.Y.Z`, versions must match the tag:
   - `meta.py` `__version__`
   - `pyproject.toml` `project.version`
   - `version_info.txt` `filevers` / `prodvers` / `FileVersion` / `ProductVersion`
6. Local interpreter is often 3.14; CI is 3.11/3.12. Warning filters and Tk `FocusOut` differ. Do not skip the suite because it passed on 3.14 earlier.
7. After a pass, commit (cg skill if the user asked) then tag. Never tag before the test command in this turn.
