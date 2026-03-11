"""SQLite database — users, balance, transactions, stats."""

import aiosqlite
import logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger(__name__)
DB_PATH = Path("data/vclipai.db")


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                balance INTEGER DEFAULT 10,
                total_spent INTEGER DEFAULT 0,
                total_gens INTEGER DEFAULT 0,
                model TEXT DEFAULT 'gemini',
                referrer_id INTEGER,
                is_admin INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                op TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.commit()
    log.info("DB ready: %s", DB_PATH)


def _conn():
    return aiosqlite.connect(DB_PATH)


# ── Users ─────────────────────────────────────────────────────────

async def get_or_create_user(tg_id: int, username: str = "", first_name: str = "", referrer_id: int = None) -> dict:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        if row:
            # Update username/name if changed
            if username or first_name:
                await db.execute(
                    "UPDATE users SET username=?, first_name=? WHERE tg_id=?",
                    (username or row["username"], first_name or row["first_name"], tg_id),
                )
                await db.commit()
            return dict(row)
        await db.execute(
            "INSERT INTO users (tg_id, username, first_name, balance, referrer_id) VALUES (?,?,?,10,?)",
            (tg_id, username, first_name, referrer_id),
        )
        if referrer_id and referrer_id != tg_id:
            await db.execute("UPDATE users SET balance = balance + 3 WHERE tg_id = ?", (referrer_id,))
            await _log_tx(db, referrer_id, 3, "referral", f"Реферал: {first_name}")
        await _log_tx(db, tg_id, 10, "bonus", "Бонус за регистрацию")
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        return dict(await cur.fetchone())


async def get_user(tg_id: int) -> dict | None:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


# ── Balance ───────────────────────────────────────────────────────

async def get_balance(tg_id: int) -> int:
    async with _conn() as db:
        cur = await db.execute("SELECT balance FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        return row[0] if row else 0


async def spend(tg_id: int, amount: int, description: str) -> bool:
    async with _conn() as db:
        cur = await db.execute("SELECT balance FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        if not row or row[0] < amount:
            return False
        await db.execute(
            "UPDATE users SET balance=balance-?, total_spent=total_spent+?, total_gens=total_gens+1 WHERE tg_id=?",
            (amount, amount, tg_id),
        )
        await _log_tx(db, tg_id, -amount, "spend", description)
        await db.commit()
        return True


async def topup(tg_id: int, amount: int, description: str = "Пополнение"):
    async with _conn() as db:
        await db.execute("UPDATE users SET balance=balance+? WHERE tg_id=?", (amount, tg_id))
        await _log_tx(db, tg_id, amount, "topup", description)
        await db.commit()


# ── Model ─────────────────────────────────────────────────────────

async def get_model(tg_id: int) -> str:
    async with _conn() as db:
        cur = await db.execute("SELECT model FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        return row[0] if row else "gemini"


async def set_model(tg_id: int, model: str):
    async with _conn() as db:
        await db.execute("UPDATE users SET model=? WHERE tg_id=?", (model, tg_id))
        await db.commit()


# ── History ───────────────────────────────────────────────────────

async def get_history(tg_id: int, limit: int = 10) -> list[dict]:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM transactions WHERE tg_id=? ORDER BY created_at DESC LIMIT ?",
            (tg_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]


# ── Referral ──────────────────────────────────────────────────────

async def get_referral_count(tg_id: int) -> int:
    async with _conn() as db:
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (tg_id,))
        return (await cur.fetchone())[0]


# ── Admin stats ───────────────────────────────────────────────────

async def is_admin(tg_id: int) -> bool:
    async with _conn() as db:
        cur = await db.execute("SELECT is_admin FROM users WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        return bool(row and row[0])


async def get_stats() -> dict:
    async with _conn() as db:
        total = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        today = (await (await db.execute(
            "SELECT COUNT(*) FROM users WHERE date(created_at)=date('now')"
        )).fetchone())[0]
        total_gens = (await (await db.execute("SELECT COALESCE(SUM(total_gens),0) FROM users")).fetchone())[0]
        total_revenue = (await (await db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE op='topup'"
        )).fetchone())[0]
        return {"users": total, "today": today, "gens": total_gens, "revenue": total_revenue}


async def get_all_user_ids() -> list[int]:
    async with _conn() as db:
        cur = await db.execute("SELECT tg_id FROM users")
        return [r[0] for r in await cur.fetchall()]


async def find_user_by_id(tg_id: int) -> dict | None:
    return await get_user(tg_id)


async def grant_balance(tg_id: int, amount: int):
    await topup(tg_id, amount, f"Начисление от админа: +{amount}")


async def _log_tx(db, tg_id: int, amount: int, op: str, desc: str):
    await db.execute(
        "INSERT INTO transactions (tg_id, amount, op, description) VALUES (?,?,?,?)",
        (tg_id, amount, op, desc),
    )
