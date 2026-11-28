"""
Minetrack - Backend API Server (SQLite version)
FastAPI + aiosqlite (no MongoDB required)
"""
import json
import logging
import os
import uuid
import aiosqlite
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from models import (
    UserCreate, UserLogin,
    PegCreate, PegUpdate,
    WorkProgressCreate, DrillingCreate, BlastingCreate,
    ProductionCreate, EquipmentCreate, LaborCreate,
    HSECreate, GeologyCreate, SupportCreate, FinancialCreate,
    PegAdvanceCreate, IncidentCreate, HSEChecklistCreate,
    EquipmentPanneCreate, MiniReportCreate,
    PtoCreate, FaceExaminationCreate, GroundSupportCreate
)
import database
from routers import operations
from auth_utils import (
    hash_password, verify_password,
    create_access_token, get_current_user, require_role
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
logger = logging.getLogger(__name__)

# Chemin de la base : backend/minetrack.db en local ; sur un hebergeur sans
# disque inscriptible (Vercel), MINETRACK_DB_PATH=/tmp/minetrack.db.
DB_PATH = database.DB_PATH  # utilise seulement en mode SQLite

# ─── Tables DDL ──────────────────────────────────────────────────────────────
TABLES = {
    "auth_throttle": """
        CREATE TABLE IF NOT EXISTS auth_throttle (
            bucket TEXT PRIMARY KEY,
            expires_at BIGINT NOT NULL,
            attempts INTEGER NOT NULL
        )
    """,
    "users": """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            password TEXT NOT NULL,
            name TEXT,
            role TEXT DEFAULT 'operator',
            created_at TEXT,
            status TEXT DEFAULT 'active'
        )
    """,
    "pegs": """
        CREATE TABLE IF NOT EXISTS pegs (
            id TEXT PRIMARY KEY,
            peg_id TEXT,
            zone TEXT,
            coordinates TEXT,
            status TEXT DEFAULT 'active',
            date_installed TEXT,
            notes TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "work_progress": """
        CREATE TABLE IF NOT EXISTS work_progress (
            id TEXT PRIMARY KEY,
            peg_id TEXT,
            activity TEXT,
            team TEXT,
            progress_percent REAL DEFAULT 0,
            status TEXT DEFAULT 'in_progress',
            start_date TEXT,
            end_date TEXT,
            notes TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "drilling": """
        CREATE TABLE IF NOT EXISTS drilling (
            id TEXT PRIMARY KEY,
            peg_id TEXT,
            hole_id TEXT,
            depth_m REAL,
            diameter_mm REAL,
            rock_type TEXT,
            status TEXT DEFAULT 'planned',
            date TEXT,
            operator TEXT,
            notes TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "blasting": """
        CREATE TABLE IF NOT EXISTS blasting (
            id TEXT PRIMARY KEY,
            peg_id TEXT,
            blast_id TEXT,
            explosives_kg REAL,
            holes_count INTEGER,
            date TEXT,
            status TEXT DEFAULT 'planned',
            result TEXT,
            advance_after_blast_m REAL,
            reentry_minutes INTEGER,
            notes TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "production": """
        CREATE TABLE IF NOT EXISTS production (
            id TEXT PRIMARY KEY,
            peg_id TEXT,
            date TEXT,
            material_type TEXT,
            volume_m3 REAL,
            tonnage REAL,
            equipment_id TEXT,
            shift TEXT DEFAULT 'day',
            notes TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "equipment": """
        CREATE TABLE IF NOT EXISTS equipment (
            id TEXT PRIMARY KEY,
            equipment_id TEXT,
            name TEXT,
            type TEXT,
            status TEXT DEFAULT 'operational',
            hours_used REAL DEFAULT 0,
            next_service_date TEXT,
            location TEXT,
            notes TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "labor": """
        CREATE TABLE IF NOT EXISTS labor (
            id TEXT PRIMARY KEY,
            employee_id TEXT,
            name TEXT,
            role TEXT,
            team TEXT,
            shift TEXT DEFAULT 'day',
            hours_worked REAL DEFAULT 0,
            date TEXT,
            peg_id TEXT,
            origin_status TEXT DEFAULT 'national',
            contract_type TEXT DEFAULT 'direct',
            notes TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "hse": """
        CREATE TABLE IF NOT EXISTS hse (
            id TEXT PRIMARY KEY,
            incident_id TEXT,
            type TEXT,
            severity TEXT DEFAULT 'low',
            description TEXT,
            location TEXT,
            date TEXT,
            reported_by TEXT,
            status TEXT DEFAULT 'open',
            corrective_action TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "geology": """
        CREATE TABLE IF NOT EXISTS geology (
            id TEXT PRIMARY KEY,
            sample_id TEXT,
            peg_id TEXT,
            depth_from REAL,
            depth_to REAL,
            rock_type TEXT,
            grade_au_gt REAL,
            grade_cu_pct REAL,
            grade_co_pct REAL,
            grade_coltan_gt REAL,
            date TEXT,
            geologist TEXT,
            notes TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "support": """
        CREATE TABLE IF NOT EXISTS support (
            id TEXT PRIMARY KEY,
            ticket_id TEXT,
            category TEXT,
            priority TEXT DEFAULT 'medium',
            description TEXT,
            requested_by TEXT,
            assigned_to TEXT,
            status TEXT DEFAULT 'open',
            date_created TEXT,
            date_resolved TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "pto": """
        CREATE TABLE IF NOT EXISTS pto (
            id TEXT PRIMARY KEY,
            employee_id TEXT,
            employee_name TEXT,
            date TEXT,
            leave_type TEXT DEFAULT 'conge',
            days REAL DEFAULT 1,
            status TEXT DEFAULT 'pending',
            notes TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "face_examinations": """
        CREATE TABLE IF NOT EXISTS face_examinations (
            id TEXT PRIMARY KEY,
            peg_id TEXT,
            date TEXT,
            examiner TEXT,
            ground_condition TEXT DEFAULT 'safe',
            hazards_observed TEXT,
            ventilation_ok INTEGER DEFAULT 1,
            gas_readings TEXT,
            action_required TEXT,
            status TEXT DEFAULT 'cleared',
            photo TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "ground_support": """
        CREATE TABLE IF NOT EXISTS ground_support (
            id TEXT PRIMARY KEY,
            peg_id TEXT,
            support_type TEXT,
            quantity REAL,
            date_installed TEXT,
            state TEXT DEFAULT 'good',
            shotcrete_m3 REAL,
            concrete_m3 REAL,
            notes TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "financial": """
        CREATE TABLE IF NOT EXISTS financial (
            id TEXT PRIMARY KEY,
            record_id TEXT,
            date TEXT,
            category TEXT,
            currency TEXT DEFAULT 'USD',
            description TEXT,
            amount REAL,
            amount_usd REAL,
            peg_id TEXT,
            approved_by TEXT,
            notes TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "peg_advances": """
        CREATE TABLE IF NOT EXISTS peg_advances (
            id TEXT PRIMARY KEY,
            peg_id TEXT,
            shift TEXT,
            date TEXT,
            drilled_meters REAL DEFAULT 0,
            blasted_holes INTEGER DEFAULT 0,
            mucked_tonnage REAL DEFAULT 0,
            notes TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "incidents": """
        CREATE TABLE IF NOT EXISTS incidents (
            id TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            severity TEXT DEFAULT 'low',
            location TEXT,
            date TEXT,
            reported_by TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "hse_checklists": """
        CREATE TABLE IF NOT EXISTS hse_checklists (
            id TEXT PRIMARY KEY,
            peg_id TEXT,
            shift TEXT,
            date TEXT,
            face_safe INTEGER DEFAULT 0,
            ventilation_ok INTEGER DEFAULT 0,
            gas_checked INTEGER DEFAULT 0,
            water_sprayed INTEGER DEFAULT 0,
            supports_ok INTEGER DEFAULT 0,
            notes TEXT,
            created_at TEXT,
            created_by TEXT,
            shift_boss TEXT,
            pic TEXT,
            gas_ch4 REAL,
            gas_co REAL,
            gas_o2 REAL,
            reentry_minutes INTEGER,
            status TEXT DEFAULT 'pending',
            reviewed_by TEXT,
            reviewed_at TEXT
        )
    """,
    "equipment_pannes": """
        CREATE TABLE IF NOT EXISTS equipment_pannes (
            id TEXT PRIMARY KEY,
            equipment_id TEXT,
            issue_type TEXT,
            description TEXT,
            reported_date TEXT,
            reported_by TEXT,
            status TEXT DEFAULT 'open',
            photo TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
    "mini_reports": """
        CREATE TABLE IF NOT EXISTS mini_reports (
            id TEXT PRIMARY KEY,
            shift TEXT,
            date TEXT,
            peg_id TEXT,
            weather_conditions TEXT DEFAULT 'normal',
            safety_summary TEXT,
            production_summary TEXT,
            issues_encountered TEXT,
            submitted_by TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """,
}


async def get_db():
    return await database.connect()


def row_to_dict(row, cursor):
    if row is None:
        return None
    cols = [d[0] for d in cursor.description]
    d = dict(zip(cols, row))
    # Rename 'id' -> '_id' for frontend compatibility
    if 'id' in d:
        d['_id'] = d.pop('id')
    # Parse JSON fields
    if 'coordinates' in d and d['coordinates']:
        try:
            d['coordinates'] = json.loads(d['coordinates'])
        except Exception:
            pass
    return d


def rows_to_list(rows, cursor):
    cols = [d[0] for d in cursor.description]
    result = []
    for row in rows:
        d = dict(zip(cols, row))
        if 'id' in d:
            d['_id'] = d.pop('id')
        if 'coordinates' in d and d['coordinates']:
            try:
                d['coordinates'] = json.loads(d['coordinates'])
            except Exception:
                pass
        result.append(d)
    return result


# ─── Initialisation de la base ────────────────────────────────────────────────
_db_ready = False
_unique_user_emails = False


async def _add_columns(columns):
    """Ajoute des colonnes manquantes (idempotent, SQLite et Postgres)."""
    for table, col, ddl in columns:
        try:
            async with database.connect() as db:
                if database.IS_POSTGRES:
                    await db.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}')
                else:
                    await db.execute(f'ALTER TABLE {table} ADD COLUMN {col} {ddl}')
                await db.commit()
        except Exception:
            pass  # SQLite : colonne deja presente


async def ensure_db():
    """Cree les tables (idempotent), une fois par processus.

    Appelee au demarrage ET au premier appel d'API : sur Vercel, le lifespan
    n'est pas garanti et /tmp repart vide a chaque nouvelle instance.
    Avec MINETRACK_DEMO_ACCOUNTS=1, les comptes de demo sont aussi crees.
    """
    global _db_ready, _unique_user_emails
    if _db_ready:
        return
    if not database.IS_POSTGRES:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with database.connect() as db:
        for sql in TABLES.values():
            await db.execute(sql)
        await database.protect_tables(db, TABLES.keys())
        await db.commit()
    # Migrations : colonnes ajoutees apres coup (bases deja creees).
    await _add_columns([
        ("users", "status", "TEXT DEFAULT 'active'"),
        ("hse_checklists", "shift_boss", "TEXT"),
        ("hse_checklists", "pic", "TEXT"),
        ("hse_checklists", "gas_ch4", "REAL"),
        ("hse_checklists", "gas_co", "REAL"),
        ("hse_checklists", "gas_o2", "REAL"),
        ("hse_checklists", "reentry_minutes", "INTEGER"),
        ("hse_checklists", "status", "TEXT DEFAULT 'pending'"),
        ("hse_checklists", "reviewed_by", "TEXT"),
        ("hse_checklists", "reviewed_at", "TEXT"),
    ])
    async with database.connect() as db:
        try:
            await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email_normalized ON users (LOWER(TRIM(email)))")
            await db.commit()
            _unique_user_emails = True
        except database.INTEGRITY_ERRORS:
            logger.error("Existing duplicate account emails prevent account creation until reconciled")
    await operations.init_operations_tables()
    if _unique_user_emails and os.environ.get("MINETRACK_DEMO_ACCOUNTS") == "1":
        from create_accounts import ensure_accounts
        ensure_accounts(DB_PATH, verbose=False)
    _db_ready = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_db()
    yield


# En production (Vercel), la documentation interactive de l'API n'est pas publiee :
# elle listait publiquement toutes les routes. En local : /docs reste disponible.
_IS_PROD = bool(os.environ.get("VERCEL")) or os.environ.get("MINETRACK_ENV") == "production"
app = FastAPI(
    title="Minetrack API", version="2.0.0", lifespan=lifespan,
    docs_url=None if _IS_PROD else "/docs",
    redoc_url=None if _IS_PROD else "/redoc",
    openapi_url=None if _IS_PROD else "/openapi.json",
)

MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 Mo (photos en base64 comprises)

class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                response = JSONResponse({"detail": "Requête trop volumineuse (10 Mo maximum)"}, status_code=413)
                await response(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body"):
                break

        async def read_body():
            nonlocal body
            if body is None:
                return await receive()
            data, body = bytes(body), None
            return {"type": "http.request", "body": data, "more_body": False}

        await self.app(scope, read_body, send)


@app.middleware("http")
async def _init_db_middleware(request: Request, call_next):
    await ensure_db()
    return await call_next(request)

app.add_middleware(BodyLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4000", "http://127.0.0.1:4000",  # port réel du frontend (vite.config.js)
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:5173", "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(operations.router)


# ─── Auth ─────────────────────────────────────────────────────────────────────
# Inscription publique : le compte est cree EN ATTENTE (status='pending') avec
# le role demande. Il ne peut pas se connecter tant qu'un admin ou un
# superviseur ne l'a pas valide (page Utilisateurs). Le role admin ne peut
# pas etre demande. (Avant l'audit : inscription « supervisor » immediate.)
SELF_REGISTER_ROLES = {"operator", "geologist", "logistique", "support", "supervisor", "management"}
REGISTER_MAX_PER_HOUR = 5
LOGIN_MAX_FAILURES = 10
LOGIN_WINDOW_SECONDS = 15 * 60


def _client_ip(request: Request) -> str:
    if os.environ.get("VERCEL"):
        forwarded = request.headers.get("x-vercel-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# Hash factice : /login fait toujours un calcul bcrypt, que l'email existe ou non
# (sinon le temps de reponse revele quels emails ont un compte).
_DUMMY_HASH = hash_password("minetrack-timing-equalizer")


def _is_https(request: Request) -> bool:
    return _IS_PROD or request.url.scheme == "https"


def _set_session_cookie(response: Response, request: Request, token: str):
    # secure=True en HTTPS (Vercel) : le cookie ne part jamais en clair.
    response.set_cookie("access_token", token, httponly=True, samesite="lax",
                        secure=_is_https(request), max_age=86400)


async def _consume_auth_quota(bucket: str, limit: int, window: int) -> bool:
    now = int(datetime.now(timezone.utc).timestamp())
    async with database.connect() as db:
        async with db.execute(
            """INSERT INTO auth_throttle (bucket, expires_at, attempts) VALUES (?, ?, 1)
               ON CONFLICT (bucket) DO UPDATE SET
                   attempts=CASE WHEN auth_throttle.expires_at <= ? THEN 1 ELSE auth_throttle.attempts + 1 END,
                   expires_at=CASE WHEN auth_throttle.expires_at <= ? THEN excluded.expires_at ELSE auth_throttle.expires_at END
               WHERE auth_throttle.expires_at <= ? OR auth_throttle.attempts < ?
               RETURNING attempts""",
            (bucket, now + window, now, now, now, limit),
        ) as cur:
            admitted = await cur.fetchone() is not None
        if now % 60 == 0:
            await db.execute("DELETE FROM auth_throttle WHERE expires_at <= ?", (now,))
        await db.commit()
    return admitted


@app.post("/api/auth/register")
async def register(user_input: UserCreate, request: Request):
    """Demande de compte : creee en attente, sans session, a valider par l'equipe."""
    ip = _client_ip(request)
    if not await _consume_auth_quota(f"register:{ip}", REGISTER_MAX_PER_HOUR, 3600):
        raise HTTPException(status_code=429, detail="Trop de demandes : réessayez dans une heure")

    email = (user_input.email or "").lower().strip()
    name = (user_input.name or "").strip()
    if len(email) > 254 or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=422, detail="Email invalide")
    if not name:
        raise HTTPException(status_code=422, detail="Nom requis")
    if len(user_input.password or "") < 8:
        raise HTTPException(status_code=422, detail="Mot de passe : 8 caractères minimum")
    if len(user_input.password.encode()) > 72:
        raise HTTPException(status_code=422, detail="Mot de passe : 72 octets maximum")
    if user_input.role not in SELF_REGISTER_ROLES:
        raise HTTPException(status_code=422, detail="Rôle non disponible à l'inscription")
    await _insert_user(str(uuid.uuid4()), email, user_input.password, name, user_input.role,
                       datetime.now(timezone.utc).isoformat(), "pending")
    return {"message": "Demande envoyée : un administrateur ou un superviseur doit valider votre compte.",
            "status": "pending"}


@app.post("/api/auth/login")
async def login(user_input: UserLogin, request: Request, response: Response):
    email = user_input.email.lower().strip()
    if len(email) > 254:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    client_ip = _client_ip(request)
    ip_bucket = f"login-ip:{client_ip}"
    account_bucket = f"login-source-account:{client_ip}:{email}"
    if not await _consume_auth_quota(ip_bucket, 60, LOGIN_WINDOW_SECONDS) or not await _consume_auth_quota(
        account_bucket, LOGIN_MAX_FAILURES, LOGIN_WINDOW_SECONDS
    ):
        raise HTTPException(status_code=429, detail="Trop de tentatives : réessayez dans 15 minutes")
    async with database.connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE email=?", (email,)) as cur:
            users = await cur.fetchall()
    
    valid_user = None
    for u in users:
        if verify_password(user_input.password, u["password"]):
            valid_user = u
            break
    if not users:
        verify_password(user_input.password, _DUMMY_HASH)

    if not valid_user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    async with database.connect() as db:
        await db.execute("DELETE FROM auth_throttle WHERE bucket=?", (account_bucket,))
        await db.commit()
    if (valid_user["status"] or "active") != "active":
        raise HTTPException(status_code=403, detail="Compte en attente de validation par un administrateur ou un superviseur")

    token = create_access_token({"sub": valid_user["id"], "email": email, "role": valid_user["role"], "name": valid_user["name"]})
    _set_session_cookie(response, request, token)
    return {"message": "Login successful", "sub": valid_user["id"], "email": email,
            "role": valid_user["role"], "name": valid_user["name"]}


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    response.delete_cookie("access_token", httponly=True, samesite="lax", secure=_is_https(request))
    return {"message": "Logged out"}


@app.get("/api/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


@app.get("/api/supervisor/users")
async def list_users(current_user: dict = Depends(require_role("supervisor", "admin"))):
    async with database.connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, email, name, role, created_at, status FROM users ORDER BY created_at DESC") as cur:
            rows = await cur.fetchall()
            return [{"id": r["id"], "email": r["email"], "name": r["name"], "role": r["role"],
                     "created_at": r["created_at"], "status": r["status"] or "active"} for r in rows]


ALL_ROLES = {"admin", "management", "supervisor", "logistique", "support", "geologist", "operator"}
# Ce qu'un superviseur a le droit de creer (jamais admin / management / superviseur).
SUPERVISOR_CREATABLE = {"operator", "geologist", "logistique", "support"}


class StaffCreate(BaseModel):
    email: str
    name: str
    role: str
    password: str


async def _insert_user(uid, email, password, name, role, created, status):
    if not _unique_user_emails:
        raise HTTPException(status_code=503, detail="La création de comptes est temporairement indisponible")
    try:
        async with database.connect() as db:
            await db.execute(
                "INSERT INTO users (id, email, password, name, role, created_at, status) VALUES (?,?,?,?,?,?,?)",
                (uid, email, hash_password(password), name, role, created, status),
            )
            await db.commit()
    except database.INTEGRITY_ERRORS as error:
        raise HTTPException(status_code=409, detail="Un compte existe déjà avec cet email") from error


@app.post("/api/supervisor/users")
async def create_user(body: StaffCreate, current_user: dict = Depends(require_role("supervisor", "admin"))):
    email = body.email.lower().strip()
    if len(email) > 254 or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=422, detail="Email invalide")
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Nom requis")
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Mot de passe : 8 caractères minimum")
    if len(body.password.encode()) > 72:
        raise HTTPException(status_code=422, detail="Mot de passe : 72 octets maximum")
    if body.role not in ALL_ROLES:
        raise HTTPException(status_code=422, detail="Rôle inconnu")
    if current_user.get("role") != "admin" and body.role not in SUPERVISOR_CREATABLE:
        raise HTTPException(status_code=403, detail="Un superviseur ne peut pas créer ce rôle")
    uid = str(uuid.uuid4())
    created = datetime.now(timezone.utc).isoformat()
    await _insert_user(uid, email, body.password, body.name.strip(), body.role, created, "active")
    return {"id": uid, "email": email, "name": body.name.strip(), "role": body.role, "created_at": created}


@app.post("/api/supervisor/users/{user_id}/approve")
async def approve_user(user_id: str, current_user: dict = Depends(require_role("supervisor", "admin"))):
    """Valide une demande de compte (status pending -> active)."""
    async with database.connect() as db:
        async with db.execute("SELECT role, status FROM users WHERE id=?", (user_id,)) as cur:
            target = await cur.fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
        if current_user.get("role") != "admin" and target[0] not in SUPERVISOR_CREATABLE:
            raise HTTPException(status_code=403, detail="Seul un administrateur peut valider ce rôle")
        await db.execute("UPDATE users SET status='active' WHERE id=?", (user_id,))
        await db.commit()
    return {"message": "Compte validé"}


@app.delete("/api/supervisor/users/{user_id}")
async def delete_user(user_id: str, current_user: dict = Depends(require_role("supervisor", "admin"))):
    if user_id == current_user.get("sub"):
        raise HTTPException(status_code=400, detail="Impossible de supprimer son propre compte")
    async with database.connect() as db:
        async with db.execute("SELECT role FROM users WHERE id=?", (user_id,)) as cur:
            target = await cur.fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
        if current_user.get("role") != "admin" and target[0] not in SUPERVISOR_CREATABLE:
            raise HTTPException(status_code=403, detail="Seul un administrateur peut supprimer ce rôle")
        await db.execute("DELETE FROM users WHERE id=?", (user_id,))
        await db.commit()
    return {"message": "User deleted"}


# ─── Dashboard ────────────────────────────────────────────────────────────────
# Les indicateurs globaux (dont le total des depenses) sont reserves a l'encadrement :
# avant, tout compte connecte (operateur, logistique...) pouvait lire les finances ici.
DASHBOARD_READERS = require_role("admin", "supervisor", "management")


@app.get("/api/health")
async def health():
    """Vérifie la disponibilité de la base sans divulguer les erreurs internes."""
    try:
        async with database.connect() as db:
            async with db.execute("SELECT 1") as cur:
                await cur.fetchone()
    except Exception as error:
        raise HTTPException(status_code=503, detail="Base de données indisponible") from error
    return {"status": "ok", "database": "postgres" if database.IS_POSTGRES else "sqlite"}


@app.get("/api/dashboard/stats")
async def dashboard_stats(current_user: dict = Depends(DASHBOARD_READERS)):
    async with database.connect() as db:
        async def count(table, where="1=1"):
            async with db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}") as c:
                return (await c.fetchone())[0]

        async def scalar(sql):
            async with db.execute(sql) as c:
                r = await c.fetchone()
                return r[0] or 0 if r else 0

        avg_progress = await scalar("SELECT AVG(progress_percent) FROM work_progress WHERE status != 'completed'")

        async with db.execute(
            "SELECT team, AVG(progress_percent) as perf FROM work_progress WHERE team IS NOT NULL AND team != '' GROUP BY team ORDER BY perf DESC LIMIT 5"
        ) as c:
            team_performance = [{"team": r[0], "avg_progress": round(r[1] or 0, 1)} for r in await c.fetchall()]

        return {
            "pegs": {
                "total": await count("pegs"),
                "active": await count("pegs", "status='active'"),
                "completed": await count("pegs", "status='completed'"),
                "avg_progress": round(avg_progress, 1),
            },
            "safety": {
                "open_incidents": await count("hse", "status='open'"),
                "critical": await count("hse", "severity='critical'"),
            },
            "equipment": {
                "operational": await count("equipment", "status='operational'"),
                "maintenance": await count("equipment", "status='maintenance'"),
                "breakdown": await count("equipment", "status='breakdown'"),
            },
            "production": {
                "total_tonnage": round(await scalar("SELECT SUM(tonnage) FROM production"), 2),
            },
            "labor": {
                "total": await count("labor"),
                "national": await count("labor", "origin_status='national'"),
                "expat": await count("labor", "origin_status='expat'"),
            },
            "financial": {
                "total_cost_usd": round(await scalar("SELECT SUM(amount_usd) FROM financial"), 2),
            },
            "team_performance": team_performance,
        }


@app.get("/api/dashboard/charts")
async def dashboard_charts(current_user: dict = Depends(DASHBOARD_READERS)):
    async with database.connect() as db:
        async with db.execute("SELECT date, SUM(tonnage) as tonnage FROM production GROUP BY date ORDER BY date DESC LIMIT 14") as c:
            prod = [{"date": r[0], "tonnage": r[1]} for r in await c.fetchall()]

        async with db.execute("SELECT type, COUNT(*) FROM hse GROUP BY type") as c:
            hse_by_type = {r[0]: r[1] for r in await c.fetchall()}

        async with db.execute("SELECT status, COUNT(*) FROM equipment GROUP BY status") as c:
            equip_status = {r[0]: r[1] for r in await c.fetchall()}

        # Avancement par PEG (dernière valeur connue par peg)
        async with db.execute(
            "SELECT peg_id, AVG(progress_percent) as pct FROM work_progress WHERE peg_id IS NOT NULL AND peg_id != '' GROUP BY peg_id ORDER BY peg_id LIMIT 20"
        ) as c:
            peg_progress = [{"peg_id": r[0], "progress": round(r[1] or 0, 1)} for r in await c.fetchall()]

        # Incidents par jour (14 derniers jours avec données)
        async with db.execute(
            "SELECT date, COUNT(*) as n FROM incidents WHERE date IS NOT NULL AND date != '' GROUP BY date ORDER BY date DESC LIMIT 14"
        ) as c:
            incidents_by_day = [{"date": r[0], "count": r[1]} for r in await c.fetchall()]

        # PTO (congés) par jour
        async with db.execute(
            "SELECT date, SUM(days) as total_days FROM pto WHERE date IS NOT NULL AND date != '' GROUP BY date ORDER BY date DESC LIMIT 14"
        ) as c:
            pto_by_day = [{"date": r[0], "days": r[1] or 0} for r in await c.fetchall()]

    return {
        "production_trend": list(reversed(prod)),
        "hse_by_type": hse_by_type,
        "equipment_status": equip_status,
        "peg_progress": peg_progress,
        "incidents_by_day": list(reversed(incidents_by_day)),
        "pto_by_day": list(reversed(pto_by_day)),
    }


# Modifier / supprimer des donnees metier : admin et superviseur uniquement.
# (Avant : tout compte connecte, ex. un operateur pouvait effacer les finances.)
MANAGERS = require_role("admin", "supervisor")


@app.get("/api/pegs")
async def list_pegs(current_user: dict = Depends(get_current_user)):
    async with database.connect() as db:
        async with db.execute("SELECT * FROM pegs ORDER BY created_at DESC LIMIT 200") as cur:
            rows = await cur.fetchall()
            return rows_to_list(rows, cur)


@app.post("/api/pegs")
async def create_peg(body: PegCreate, current_user: dict = Depends(get_current_user)):
    uid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    coords = json.dumps(body.coordinates) if body.coordinates else None
    async with database.connect() as db:
        await db.execute(
            "INSERT INTO pegs VALUES (?,?,?,?,?,?,?,?,?)",
            (uid, body.peg_id, body.zone, coords, body.status,
             body.date_installed, body.notes, now, current_user.get("email"))
        )
        await db.commit()
    return {"_id": uid, **body.model_dump(), "created_at": now}


@app.get("/api/pegs/{item_id}")
async def get_peg(item_id: str, current_user: dict = Depends(get_current_user)):
    async with database.connect() as db:
        async with db.execute("SELECT * FROM pegs WHERE id=?", (item_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404)
            return row_to_dict(row, cur)


@app.put("/api/pegs/{item_id}")
async def update_peg(item_id: str, body: PegUpdate, current_user: dict = Depends(MANAGERS)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return {"message": "Nothing to update"}
    set_clause = ", ".join(f"{k}=?" for k in updates)
    async with database.connect() as db:
        await db.execute(f"UPDATE pegs SET {set_clause} WHERE id=?", (*updates.values(), item_id))
        await db.commit()
    return {"message": "Updated"}


@app.delete("/api/pegs/{item_id}")
async def delete_peg(item_id: str, current_user: dict = Depends(MANAGERS)):
    async with database.connect() as db:
        await db.execute("DELETE FROM pegs WHERE id=?", (item_id,))
        await db.commit()
    return {"message": "Deleted"}


# ─── Generic CRUD factory ─────────────────────────────────────────────────────
def make_generic_routes(route_name: str, table: str, ModelClass, fields: list):
    """Adds GET list, POST create, GET one, DELETE one for a table."""
    read_access = {
        "financial": DASHBOARD_READERS,
        "labor": MANAGERS,
        "pto": MANAGERS,
    }.get(route_name, get_current_user)
    write_access = {
        "financial": require_role("admin"),
        "labor": MANAGERS,
        "pto": MANAGERS,
    }.get(route_name, get_current_user)
    manage_access = write_access if route_name == "financial" else MANAGERS

    @app.get(f"/api/{route_name}")
    async def list_items(current_user: dict = Depends(read_access)):
        async with database.connect() as db:
            async with db.execute(f"SELECT * FROM {table} ORDER BY created_at DESC LIMIT 200") as cur:
                rows = await cur.fetchall()
                return rows_to_list(rows, cur)

    @app.post(f"/api/{route_name}")
    async def create_item(body: ModelClass, current_user: dict = Depends(write_access)):
        uid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        data = body.model_dump()
        values = [uid] + [data.get(f) for f in fields] + [now, current_user.get("email")]
        placeholders = ",".join("?" for _ in range(len(values)))
        cols = "id," + ",".join(fields) + ",created_at,created_by"
        async with database.connect() as db:
            await db.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", values)
            await db.commit()
        return {"id": uid, **data, "created_at": now}

    @app.get(f"/api/{route_name}/{{item_id}}")
    async def get_item(item_id: str, current_user: dict = Depends(read_access)):
        async with database.connect() as db:
            async with db.execute(f"SELECT * FROM {table} WHERE id=?", (item_id,)) as cur:
                row = await cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404)
                return row_to_dict(row, cur)

    @app.delete(f"/api/{route_name}/{{item_id}}")
    async def delete_item(item_id: str, current_user: dict = Depends(manage_access)):
        async with database.connect() as db:
            await db.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
            await db.commit()
        return {"message": "Deleted"}

    @app.put(f"/api/{route_name}/{{item_id}}")
    async def update_item(item_id: str, body: dict, current_user: dict = Depends(manage_access)):
        updates = {k: v for k, v in body.items() if k in fields}
        if not updates:
            return {"message": "Nothing to update"}
        async with database.connect() as db:
            async with db.execute(f"SELECT {','.join(fields)} FROM {table} WHERE id=?", (item_id,)) as cur:
                row = await cur.fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="Enregistrement introuvable")
                record = row_to_dict(row, cur)
            try:
                validated = ModelClass.model_validate({**record, **updates}).model_dump()
            except ValidationError as error:
                raise HTTPException(status_code=422, detail="Valeurs de mise à jour invalides") from error
            updates = {field: validated[field] for field in updates}
            if table == "hse_checklists":
                updates.update(status="pending", reviewed_by=None, reviewed_at=None)
            set_clause = ", ".join(f"{key}=?" for key in updates)
            await db.execute(f"UPDATE {table} SET {set_clause} WHERE id=?", (*updates.values(), item_id))
            await db.commit()
        return {"message": "Updated"}


MODULES_CONFIG = [
    ("work-progress", "work_progress", WorkProgressCreate,
     ["peg_id", "activity", "team", "progress_percent", "status", "start_date", "end_date", "notes"]),
    ("drilling", "drilling", DrillingCreate,
     ["peg_id", "hole_id", "depth_m", "diameter_mm", "rock_type", "status", "date", "operator", "notes"]),
    ("blasting", "blasting", BlastingCreate,
     ["peg_id", "blast_id", "explosives_kg", "holes_count", "date", "status", "result", "advance_after_blast_m", "reentry_minutes", "notes"]),
    ("production", "production", ProductionCreate,
     ["peg_id", "date", "material_type", "volume_m3", "tonnage", "equipment_id", "shift", "notes"]),
    ("equipment", "equipment", EquipmentCreate,
     ["equipment_id", "name", "type", "status", "hours_used", "next_service_date", "location", "notes"]),
    ("labor", "labor", LaborCreate,
     ["employee_id", "name", "role", "team", "shift", "hours_worked", "date", "peg_id", "origin_status", "contract_type", "notes"]),
    ("hse", "hse", HSECreate,
     ["incident_id", "type", "severity", "description", "location", "date", "reported_by", "status", "corrective_action"]),
    ("geology", "geology", GeologyCreate,
     ["sample_id", "peg_id", "depth_from", "depth_to", "rock_type", "grade_au_gt", "grade_cu_pct", "grade_co_pct", "grade_coltan_gt", "date", "geologist", "notes"]),
    ("support", "support", SupportCreate,
     ["ticket_id", "category", "priority", "description", "requested_by", "assigned_to", "status", "date_created", "date_resolved"]),
    ("financial", "financial", FinancialCreate,
     ["record_id", "date", "category", "currency", "description", "amount", "amount_usd", "peg_id", "approved_by", "notes"]),
    ("peg-advances", "peg_advances", PegAdvanceCreate,
     ["peg_id", "shift", "date", "drilled_meters", "blasted_holes", "mucked_tonnage", "notes"]),
    ("incidents", "incidents", IncidentCreate,
     ["title", "description", "severity", "location", "date", "reported_by"]),
    ("hse-checklists", "hse_checklists", HSEChecklistCreate,
     ["peg_id", "shift", "date", "face_safe", "ventilation_ok", "gas_checked", "water_sprayed", "supports_ok", "notes",
      "shift_boss", "pic", "gas_ch4", "gas_co", "gas_o2", "reentry_minutes"]),
    ("equipment-pannes", "equipment_pannes", EquipmentPanneCreate,
     ["equipment_id", "issue_type", "description", "reported_date", "reported_by", "status", "photo"]),
    ("mini-reports", "mini_reports", MiniReportCreate,
     ["shift", "date", "peg_id", "weather_conditions", "safety_summary", "production_summary", "issues_encountered", "submitted_by"]),
    ("pto", "pto", PtoCreate,
     ["employee_id", "employee_name", "date", "leave_type", "days", "status", "notes"]),
    ("face-examinations", "face_examinations", FaceExaminationCreate,
     ["peg_id", "date", "examiner", "ground_condition", "hazards_observed", "ventilation_ok", "gas_readings", "action_required", "status", "photo"]),
    ("ground-support", "ground_support", GroundSupportCreate,
     ["peg_id", "support_type", "quantity", "date_installed", "state", "shotcrete_m3", "concrete_m3", "notes"]),
]

for route_name, table, ModelClass, fields in MODULES_CONFIG:
    make_generic_routes(route_name, table, ModelClass, fields)


# ─── Reports ──────────────────────────────────────────────────────────────────
@app.get("/api/reports/summary")
async def reports_summary(current_user: dict = Depends(DASHBOARD_READERS)):
    async with database.connect() as db:
        async def count(table, where="1=1"):
            async with db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}") as c:
                return (await c.fetchone())[0]

        async def group(table, col):
            async with db.execute(f"SELECT {col}, COUNT(*) FROM {table} GROUP BY {col}") as c:
                return {r[0]: r[1] for r in await c.fetchall()}

        async def sum_group(table, group_col, val_col):
            async with db.execute(f"SELECT {group_col}, SUM({val_col}) FROM {table} GROUP BY {group_col}") as c:
                return {r[0]: round(r[1] or 0, 2) for r in await c.fetchall()}

        async def scalar(sql):
            async with db.execute(sql) as c:
                r = await c.fetchone()
                return r[0] or 0 if r else 0

        return {
            "pegs_summary": {
                "total": await count("pegs"),
                "by_status": await group("pegs", "status"),
                "by_zone": await group("pegs", "zone"),
            },
            "production_summary": {
                "total_tonnage": round(await scalar("SELECT SUM(tonnage) FROM production"), 2),
                "total_volume_m3": round(await scalar("SELECT SUM(volume_m3) FROM production"), 2),
                "by_material": await sum_group("production", "material_type", "tonnage"),
            },
            "safety_summary": {
                "total_incidents": await count("hse"),
                "by_type": await group("hse", "type"),
                "by_severity": await group("hse", "severity"),
            },
            "financial_summary": {
                "total_expenditure": round(await scalar("SELECT SUM(amount_usd) FROM financial"), 2),
                "by_category": await sum_group("financial", "category", "amount_usd"),
            }
        }

@app.get("/api/supervisor/alerts")
async def supervisor_alerts(current_user: dict = Depends(MANAGERS)):
    async with database.connect() as db:
        async with db.execute("SELECT * FROM incidents WHERE severity='high' OR severity='critical' ORDER BY created_at DESC LIMIT 20") as cur:
            incidents = rows_to_list(await cur.fetchall(), cur)
        async with db.execute("SELECT * FROM equipment_pannes WHERE status='open' ORDER BY created_at DESC LIMIT 20") as cur:
            pannes = rows_to_list(await cur.fetchall(), cur)
    return {"incidents": incidents, "pannes": pannes}

class HSEReview(BaseModel):
    decision: str  # approved | rejected


@app.post("/api/hse-checklists/{item_id}/review")
async def review_hse(item_id: str, body: HSEReview, current_user: dict = Depends(require_role("supervisor", "admin"))):
    """Validation « Face Safe » par le superviseur : statut + auteur + date, cote serveur."""
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=422, detail="Décision invalide")
    async with database.connect() as db:
        async with db.execute("SELECT created_by FROM hse_checklists WHERE id=?", (item_id,)) as cur:
            author = await cur.fetchone()
        if author is None:
            raise HTTPException(status_code=404, detail="Déclaration introuvable")
        if body.decision == "approved":
            if not author[0]:
                raise HTTPException(status_code=409, detail="Le déclarant doit être identifié avant validation")
            if author[0].strip().lower() == current_user["email"].strip().lower():
                raise HTTPException(status_code=403, detail="Un autre responsable doit valider cette déclaration")
        await db.execute(
            "UPDATE hse_checklists SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?",
            (body.decision, current_user.get("email"), datetime.now(timezone.utc).isoformat(), item_id),
        )
        await db.commit()
    return {"message": "Déclaration mise à jour", "status": body.decision}


# /api/sync a ete supprimee (audit) : elle inserait des noms de colonnes
# fournis par le client dans le SQL (injection) et pouvait ecrire dans la
# table users (creation d'un compte admin). Le frontend ne l'utilisait pas :
# la file hors-ligne rejoue les requetes normales (utils/offlineSync.js).

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8001, reload=True)
