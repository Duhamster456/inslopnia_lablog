import logging
import os
import re
import secrets
import sqlite3
from collections import defaultdict
from contextlib import closing, contextmanager
from hashlib import sha256
from uuid import uuid4

from werkzeug.exceptions import Conflict, Forbidden, NotFound

from .entries import check_entry_size, now_timestamp

SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES users(id),
    digest BLOB NOT NULL UNIQUE,
    prefix TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    owner_id TEXT REFERENCES users(id),
    title TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    commit_hash TEXT,
    url TEXT,
    filename TEXT NOT NULL UNIQUE
);
COMMIT;
"""
DOCUMENT_NAME = re.compile(r"[0-9a-f]{32}\.txt")
ENTRY_COLUMNS = "id, owner_id, title, timestamp, commit_hash, url, filename"
logger = logging.getLogger(__name__)


def token_digest(token):
    return sha256(token.encode("ascii")).digest()


class Journal:
    def __init__(self, directory):
        self.database = directory / "lablog.sqlite3"
        self.documents = directory / "entries"
        self.documents.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode = DELETE").fetchone()
            db.executescript(SCHEMA)

        # A crash can leave an unreferenced document. The write transaction
        # also excludes processes that are preparing a document for commit.
        with self._transaction(write=True) as db:
            referenced = {row["filename"] for row in db.execute("SELECT filename FROM entries")}
            for path in self.documents.iterdir():
                if DOCUMENT_NAME.fullmatch(path.name) and path.name not in referenced:
                    self._remove_document(path.name)

    def _connect(self):
        db = sqlite3.connect(self.database, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @contextmanager
    def _transaction(self, *, write=False):
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()

    def lookup_key(self, token):
        with self._transaction() as db:
            key = db.execute(
                "SELECT owner_id FROM api_keys WHERE digest = ?", (token_digest(token),)
            ).fetchone()
        return key["owner_id"] if key else None

    def users(self):
        with self._transaction() as db:
            users = db.execute("SELECT id, name FROM users ORDER BY name").fetchall()
            keys = db.execute("""
                SELECT id, owner_id, prefix, created_at FROM api_keys ORDER BY created_at DESC
            """).fetchall()
        by_owner = defaultdict(list)
        for key in keys:
            by_owner[key["owner_id"]].append(key)
        return [dict(user, api_keys=by_owner[user["id"]]) for user in users]

    def _user(self, db, user_id):
        user = db.execute("SELECT id, name FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            raise NotFound("User not found.")
        return user

    def save_user(self, name, user_id=None):
        try:
            with self._transaction(write=True) as db:
                if user_id is None:
                    db.execute("INSERT INTO users (id, name) VALUES (?, ?)", (uuid4().hex, name))
                else:
                    self._user(db, user_id)
                    db.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
        except sqlite3.IntegrityError as error:
            if error.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                raise Conflict("This user name is already in use.") from None
            raise

    def issue_key(self, user_id):
        token = secrets.token_urlsafe(32)
        with self._transaction(write=True) as db:
            user = self._user(db, user_id)
            db.execute("""
                INSERT INTO api_keys (id, owner_id, digest, prefix, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (uuid4().hex, user_id, token_digest(token), token[:8], now_timestamp()))
        return user["name"], token

    def revoke_key(self, key_id):
        with self._transaction(write=True) as db:
            deleted = db.execute("DELETE FROM api_keys WHERE id = ?", (key_id,)).rowcount
            if not deleted:
                raise NotFound("API key not found.")

    def list_entries(self):
        with self._transaction() as db:
            return db.execute("""
                SELECT entries.id, title, timestamp, commit_hash, url, users.name AS owner_name
                FROM entries LEFT JOIN users ON users.id = entries.owner_id
                ORDER BY timestamp DESC, entries.id
            """).fetchall()

    def _find_entry(self, db, entry_id):
        row = db.execute(
            f"SELECT {ENTRY_COLUMNS} FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            raise NotFound("Entry not found.")
        return row

    def _read_entry(self, row):
        document = (self.documents / row["filename"]).read_bytes().decode("utf-8")
        return {**dict(row), "text": document.partition("\n")[2]}

    def get_entry(self, entry_id):
        with self._transaction() as db:
            return self._read_entry(self._find_entry(db, entry_id))

    def _stage_document(self, entry):
        filename = f"{uuid4().hex}.txt"
        with (self.documents / filename).open("xb") as document:
            document.write(f"{entry['title']}\n{entry['text']}".encode("utf-8"))
            document.flush()
            os.fsync(document.fileno())
        if os.name == "posix":
            directory_fd = os.open(self.documents, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return filename

    def _remove_document(self, filename):
        try:
            (self.documents / filename).unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove unreferenced entry file %s", filename)

    def create_entry(self, fields, owner_id):
        entry = {**fields, "id": uuid4().hex, "owner_id": owner_id}
        check_entry_size(entry)
        with self._transaction(write=True) as db:
            if owner_id is not None:
                self._user(db, owner_id)
            entry["filename"] = self._stage_document(entry)
            db.execute(f"""
                INSERT INTO entries ({ENTRY_COLUMNS})
                VALUES (:id, :owner_id, :title, :timestamp, :commit_hash, :url, :filename)
            """, entry)
        return entry

    def _writable_entry(self, db, entry_id, owner_id, admin):
        previous = self._find_entry(db, entry_id)
        if not admin and previous["owner_id"] != owner_id:
            raise Forbidden("Only the author can modify this entry.")
        return previous

    def update_entry(self, entry_id, fields, owner_id=None, *, admin=False):
        with self._transaction(write=True) as db:
            previous = self._read_entry(self._writable_entry(db, entry_id, owner_id, admin))
            entry = {**previous, **fields}
            check_entry_size(entry)
            if entry["title"] != previous["title"] or entry["text"] != previous["text"]:
                entry["filename"] = self._stage_document(entry)
            db.execute("""
                UPDATE entries SET title = :title, timestamp = :timestamp,
                    commit_hash = :commit_hash, url = :url, filename = :filename WHERE id = :id
            """, entry)
        if entry["filename"] != previous["filename"]:
            self._remove_document(previous["filename"])
        return entry

    def delete_entry(self, entry_id, owner_id=None, *, admin=False):
        with self._transaction(write=True) as db:
            previous = self._writable_entry(db, entry_id, owner_id, admin)
            db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        self._remove_document(previous["filename"])

    @contextmanager
    def search_documents(self):
        # Rollback-journal readers hold a shared lock while using these files.
        # Writers can retire a previous file after all such readers finish.
        with self._transaction() as db:
            yield db.execute("SELECT filename, id FROM entries ORDER BY id")
