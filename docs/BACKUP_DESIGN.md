# Backups of the memory (2026-10-18)

**Why.** Everything Diya knows about the owner is one SQLite file. A bad write, a full disk, or a sync program fighting over the file could lose all of it, and until now the only copy of the memory was the memory. The blueprint's baseline milestone (DIYA-005) asks for a copy with a verified restore before any schema change; this is that, and it then keeps going by itself.

**What it does** (`diya_backup.py`).

```bash
python diya_backup.py make              # a checked snapshot now
python diya_backup.py list              # the snapshots and how old each is
python diya_backup.py verify FILE       # does it open, pass SQLite's check and the memory's own?
python diya_backup.py restore FILE --to NEWPATH   # put it at a NEW path; never over anything
```

- A snapshot is made with SQLite's own backup, so it is whole even if a chat or Dreaming is writing at that moment (an uncommitted write is not in it). It is written to a `.part` name, **checked**, and renamed only if it passes, so a broken snapshot never looks like a good one and a failed attempt leaves nothing behind.
- The check: the file opens; SQLite's integrity check says ok; the tables a Diya database has are there; and the memory's own trail check (every fact has its history, every status agrees with its history) passes. The memory check runs on a throwaway copy, so **checking never changes a snapshot** (opening a Store upgrades an older schema; a backup must stay as it was).
- While the API runs, a snapshot is made when it starts if the newest is a day old, and then checked every hour. `DIYA_BACKUP=0` turns it off. The folder is `backups/` beside the code, or inside `DIYA_DATA_DIR`; `DIYA_BACKUP_DIR` moves it.
- Rotation keeps the newest 14 and removes older ones **of its own making only** (names exactly `diya-YYYYMMDD-HHMMSS.db`). A file anyone else put in the folder is never touched, and at least one snapshot is always kept.
- `restore` never overwrites: the target must not exist. It checks the snapshot first and the restored copy after, and tells the owner how to use it (`DIYA_DB_PATH`); the live database is not touched.

**Tried on real data.** `make`, `list` and the health report were run against a private copy of the owner's real database (228 messages, 8 facts): the snapshot passed its check. The live database and its folder were not written to.

**What it does not do.** It does not protect against deleting the whole project folder (the snapshots sit beside the database, in a folder a sync program may copy, so a OneDrive copy exists but is not a separate backup; a copy on another disk is the owner's step: `python diya_data.py move` and a copy of `backups/`). It does not include connector sign-ins (they are separate files, protected for this Windows user, and deliberately not in a backup). It cannot prove the contents are what the owner wants, only that they are intact.

**Proof.** `tests/test_backup.py` (19 cases): faithful copy, consistent during a write, nothing left behind on failure, never overwritten, rotation touches only its own files, due-ness, the hourly thread never raises, checking does not change an old snapshot, restore refuses an existing path, the command line.
