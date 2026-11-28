"""
backend/database.py — acces a la base, SQLite OU Postgres (Supabase).

- DATABASE_URL defini (chaine de connexion Supabase, de preference le
  pooler « transaction », port 6543) -> Postgres via pg8000 (pur Python,
  aucune DLL : fonctionne meme sur un PC qui bloque les binaires).
- Sinon -> SQLite (backend/minetrack.db, ou MINETRACK_DB_PATH).

L'interface imite le sous-ensemble d'aiosqlite deja utilise dans le code :

    async with connect() as db:
        async with db.execute("SELECT ... WHERE id=?", (x,)) as cur:
            row = await cur.fetchone()        # row[0] et row["col"]
        await db.execute("INSERT ...", params)
        await db.commit()

Les requetes restent ecrites avec des « ? » ; ils sont traduits en « %s »
pour Postgres. Les booleens deviennent 0/1, les dict/list du JSON.
"""
import asyncio
import json
import os
import ssl
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import aiosqlite
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
# Charge backend/.env ici : ce module est importe avant le load_dotenv de server.py.
load_dotenv(ROOT_DIR / ".env")
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
IS_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))
if DATABASE_URL and not IS_POSTGRES:
    raise RuntimeError("DATABASE_URL doit être une URI PostgreSQL")
DB_PATH = Path(os.environ.get("MINETRACK_DB_PATH") or ROOT_DIR / "minetrack.db")


class PgIntegrityError(Exception):
    """Violation de contrainte Postgres (unicite...), code SQLSTATE 23xxx."""


INTEGRITY_ERRORS = (aiosqlite.IntegrityError, sqlite3.IntegrityError, PgIntegrityError)


def backend_label() -> str:
    return "postgres" if IS_POSTGRES else f"sqlite:{DB_PATH}"


# ─── Postgres (pg8000) ────────────────────────────────────────────────────────
def _pg_connect():
    import pg8000.dbapi

    u = urlparse(DATABASE_URL)
    query = parse_qs(u.query)
    sslmode = (query.get("sslmode") or ["verify-full"])[0]
    if sslmode == "disable" and not os.environ.get("VERCEL") and os.environ.get("MINETRACK_ENV") != "production":
        ssl_ctx = False
    else:
        ca_file = os.environ.get("MINETRACK_DB_CA_FILE")
        ssl_ctx = ssl.create_default_context(cafile=ca_file)
        if not ca_file and (u.hostname or "").endswith(".pooler.supabase.com"):
            ssl_ctx.load_verify_locations(cafile=ROOT_DIR / "supabase-ca.crt")
    return pg8000.dbapi.connect(
        user=unquote(u.username or "postgres"),
        password=unquote(u.password or ""),
        host=u.hostname or "localhost",
        port=u.port or 5432,
        database=(u.path or "/postgres").lstrip("/") or "postgres",
        ssl_context=ssl_ctx,
        timeout=30,
    )


def _pg_sql(sql: str) -> str:
    # % est special pour le paramstyle « format » ; « ? » -> « %s ».
    return sql.replace("%", "%%").replace("?", "%s")


def _pg_params(params):
    out = []
    for p in params or ():
        if isinstance(p, bool):
            out.append(int(p))
        elif isinstance(p, (dict, list)):
            out.append(json.dumps(p, ensure_ascii=False))
        else:
            out.append(p)
    return tuple(out)


def _pg_run(cur, sql, params):
    import pg8000.dbapi

    try:
        cur.execute(_pg_sql(sql), _pg_params(params))
    except pg8000.dbapi.DatabaseError as e:
        info = e.args[0] if e.args and isinstance(e.args[0], dict) else {}
        if str(info.get("C", "")).startswith("23"):
            raise PgIntegrityError(info.get("M", str(e))) from e
        raise


class Row(tuple):
    """Ligne accessible par position (row[0]) et par nom (row["email"])."""

    def __new__(cls, values, columns):
        obj = super().__new__(cls, values)
        obj._index = {c: i for i, c in enumerate(columns)}
        return obj

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._index[key])
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._index)


class _PgCursor:
    def __init__(self, cur):
        self._cur = cur
        self._cols = [d[0] for d in (cur.description or [])]
        self.description = [(c, None, None, None, None, None, None) for c in self._cols]
        self.rowcount = cur.rowcount

    async def fetchone(self):
        r = await asyncio.to_thread(self._cur.fetchone)
        return Row(r, self._cols) if r is not None else None

    async def fetchall(self):
        rows = await asyncio.to_thread(self._cur.fetchall)
        return [Row(r, self._cols) for r in rows]


class _PgExec:
    """Resultat de db.execute(...) : utilisable avec « await » OU « async with »."""

    def __init__(self, conn, sql, params):
        self._conn, self._sql, self._params = conn, sql, params

    async def _run(self):
        def work():
            cur = self._conn.cursor()
            _pg_run(cur, self._sql, self._params)
            return cur
        return _PgCursor(await asyncio.to_thread(work))

    def __await__(self):
        return self._run().__await__()

    async def __aenter__(self):
        return await self._run()

    async def __aexit__(self, *exc):
        return False


class _PgConnection:
    row_factory = None  # compat aiosqlite (ignore : les lignes sont deja nommees)

    def __init__(self):
        self._conn = None

    async def __aenter__(self):
        self._conn = await asyncio.to_thread(_pg_connect)
        return self

    async def __aexit__(self, exc_type, *exc):
        def finish():
            try:
                if exc_type is not None:
                    self._conn.rollback()
                else:
                    self._conn.commit()
            finally:
                self._conn.close()
        await asyncio.to_thread(finish)

    def execute(self, sql, params=()):
        return _PgExec(self._conn, sql, params)

    async def commit(self):
        await asyncio.to_thread(self._conn.commit)


def connect():
    """Connexion asynchrone (context manager), meme usage qu'aiosqlite.connect."""
    if IS_POSTGRES:
        return _PgConnection()
    return aiosqlite.connect(DB_PATH)


# ─── Acces synchrone (auth_utils, create_accounts) ────────────────────────────
def sync_fetchone(sql: str, params=()):
    if IS_POSTGRES:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            _pg_run(cur, sql, params)
            return cur.fetchone()
        finally:
            conn.close()
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def sync_execute_many(statements):
    """Execute [(sql, params), ...] dans une transaction."""
    if IS_POSTGRES:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            for sql, params in statements:
                _pg_run(cur, sql, params)
            conn.commit()
        finally:
            conn.close()
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        for sql, params in statements:
            conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


async def protect_tables(db, tables):
    """Postgres/Supabase : active la RLS (sans politique) sur nos tables.

    Supabase expose le schema public via son API REST ; sans RLS, quiconque
    possede la cle « anon » pourrait lire/ecrire ces tables. Le backend se
    connecte en proprietaire des tables : la RLS ne le concerne pas.
    """
    if not IS_POSTGRES:
        return
    for t in tables:
        await db.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
