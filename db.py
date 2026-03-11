"""SQLite database — users, balance, transactions, logs, promos."""

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
                balance INTEGER DEFAULT 5,
                total_spent INTEGER DEFAULT 0,
                total_gens INTEGER DEFAULT 0,
                model TEXT DEFAULT 'gemini',
                referrer_id INTEGER,
                ref_earnings INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                daily_uses INTEGER DEFAULT 0,
                daily_reset TEXT DEFAULT '',
                last_active TIMESTAMP,
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
            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                event TEXT NOT NULL,
                tool TEXT DEFAULT '',
                details TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                stars INTEGER NOT NULL,
                max_uses INTEGER DEFAULT 1,
                used_count INTEGER DEFAULT 0,
                expires_at TIMESTAMP,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS promo_redemptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                promo_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tg_id, promo_id)
            );
            CREATE TABLE IF NOT EXISTS notify_settings (
                event TEXT PRIMARY KEY,
                enabled INTEGER DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_logs_event ON activity_logs(event);
            CREATE INDEX IF NOT EXISTS idx_logs_tg ON activity_logs(tg_id);
            CREATE INDEX IF NOT EXISTS idx_logs_date ON activity_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_tx_tg ON transactions(tg_id);
        """)
        # Seed default notification settings
        for evt in ("new_user", "payment", "tool_use", "error", "referral", "promo"):
            await db.execute(
                "INSERT OR IGNORE INTO notify_settings (event, enabled) VALUES (?, ?)",
                (evt, 1 if evt in ("new_user", "payment", "error") else 0),
            )
        await db.commit()

    await _migrate()
    log.info("DB ready: %s", DB_PATH)


async def _migrate():
    """Add new columns to existing tables if they don't exist."""
    async with _conn() as db:
        cols = set()
        async with db.execute("PRAGMA table_info(users)") as cur:
            async for row in cur:
                cols.add(row[1])
        new_cols = {
            "ref_earnings": "INTEGER DEFAULT 0",
            "is_banned": "INTEGER DEFAULT 0",
            "daily_uses": "INTEGER DEFAULT 0",
            "daily_reset": "TEXT DEFAULT ''",
            "last_active": "TIMESTAMP",
        }
        for col, dtype in new_cols.items():
            if col not in cols:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
                log.info("Added column users.%s", col)
        await db.commit()


def _conn():
    return aiosqlite.connect(DB_PATH)


# ── Users ─────────────────────────────────────────────────────────

async def get_or_create_user(tg_id: int, username: str = "", first_name: str = "",
                              referrer_id: int = None) -> dict:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        if row:
            await db.execute(
                "UPDATE users SET username=?, first_name=?, last_active=CURRENT_TIMESTAMP WHERE tg_id=?",
                (username or row["username"], first_name or row["first_name"], tg_id),
            )
            await db.commit()
            return dict(row)
        # New user — 5 free stars
        await db.execute(
            "INSERT INTO users (tg_id, username, first_name, balance, referrer_id, last_active) "
            "VALUES (?,?,?,5,?,CURRENT_TIMESTAMP)",
            (tg_id, username, first_name, referrer_id),
        )
        await _log_tx(db, tg_id, 5, "bonus", "Бонус за регистрацию")
        # Referral bonus
        if referrer_id and referrer_id != tg_id:
            ref_bonus = await _calc_ref_bonus(db, referrer_id)
            await db.execute(
                "UPDATE users SET balance=balance+?, ref_earnings=ref_earnings+? WHERE tg_id=?",
                (ref_bonus, ref_bonus, referrer_id),
            )
            await _log_tx(db, referrer_id, ref_bonus, "referral", f"Реферал: {first_name} (+{ref_bonus}⭐)")
        await _log_event(db, tg_id, "new_user", details=f"ref={referrer_id or 'organic'}")
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        return dict(await cur.fetchone())


async def _calc_ref_bonus(db, referrer_id: int) -> int:
    """Tiered referral bonus: 3⭐ base, +1 every 5 referrals, cap 10."""
    cur = await db.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (referrer_id,))
    count = (await cur.fetchone())[0]
    return min(3 + count // 5, 10)


async def get_user(tg_id: int) -> dict | None:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def touch_user(tg_id: int):
    async with _conn() as db:
        await db.execute("UPDATE users SET last_active=CURRENT_TIMESTAMP WHERE tg_id=?", (tg_id,))
        await db.commit()


async def ban_user(tg_id: int, banned: bool = True):
    async with _conn() as db:
        await db.execute("UPDATE users SET is_banned=? WHERE tg_id=?", (int(banned), tg_id))
        await db.commit()


async def is_banned(tg_id: int) -> bool:
    async with _conn() as db:
        cur = await db.execute("SELECT is_banned FROM users WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        return bool(row and row[0])


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


# ── Daily limits ──────────────────────────────────────────────────

async def check_daily_limit(tg_id: int, max_daily: int = 50) -> tuple[bool, int]:
    today = datetime.now().strftime("%Y-%m-%d")
    async with _conn() as db:
        cur = await db.execute("SELECT daily_uses, daily_reset FROM users WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        if not row:
            return False, 0
        uses, reset_date = row[0] or 0, row[1] or ""
        if reset_date != today:
            uses = 0
        if uses >= max_daily:
            return False, 0
        await db.execute(
            "UPDATE users SET daily_uses=?, daily_reset=? WHERE tg_id=?",
            (uses + 1, today, tg_id),
        )
        await db.commit()
        return True, max_daily - uses - 1


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


async def get_referral_earnings(tg_id: int) -> int:
    async with _conn() as db:
        cur = await db.execute("SELECT ref_earnings FROM users WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        return row[0] if row else 0


async def get_top_referrers(limit: int = 10) -> list[dict]:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT tg_id, first_name, username, ref_earnings, "
            "(SELECT COUNT(*) FROM users u2 WHERE u2.referrer_id=users.tg_id) as ref_count "
            "FROM users WHERE ref_earnings > 0 ORDER BY ref_count DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in await cur.fetchall()]


# ── Promo codes ───────────────────────────────────────────────────

async def create_promo(code: str, stars: int, max_uses: int = 1,
                       expires_at: str = None, created_by: int = None) -> bool:
    async with _conn() as db:
        try:
            await db.execute(
                "INSERT INTO promo_codes (code, stars, max_uses, expires_at, created_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (code.upper(), stars, max_uses, expires_at, created_by),
            )
            await db.commit()
            return True
        except Exception:
            return False


async def redeem_promo(tg_id: int, code: str) -> tuple[bool, str]:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM promo_codes WHERE code=?", (code.upper(),))
        promo = await cur.fetchone()
        if not promo:
            return False, "Промокод не найден"
        promo = dict(promo)
        if promo["used_count"] >= promo["max_uses"]:
            return False, "Промокод уже использован максимальное число раз"
        if promo["expires_at"]:
            try:
                exp = datetime.fromisoformat(promo["expires_at"])
                if datetime.now() > exp:
                    return False, "Промокод истёк"
            except Exception:
                pass
        cur = await db.execute(
            "SELECT 1 FROM promo_redemptions WHERE tg_id=? AND promo_id=?",
            (tg_id, promo["id"]),
        )
        if await cur.fetchone():
            return False, "Ты уже использовал этот промокод"
        await db.execute(
            "INSERT INTO promo_redemptions (tg_id, promo_id) VALUES (?, ?)",
            (tg_id, promo["id"]),
        )
        await db.execute(
            "UPDATE promo_codes SET used_count=used_count+1 WHERE id=?", (promo["id"],))
        await db.execute(
            "UPDATE users SET balance=balance+? WHERE tg_id=?", (promo["stars"], tg_id))
        await _log_tx(db, tg_id, promo["stars"], "promo", f"Промокод {code.upper()}: +{promo['stars']}⭐")
        await db.commit()
        return True, f"+{promo['stars']}⭐ зачислено!"


async def get_promos(active_only: bool = True) -> list[dict]:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        q = "SELECT * FROM promo_codes"
        if active_only:
            q += " WHERE used_count < max_uses"
        q += " ORDER BY created_at DESC LIMIT 20"
        cur = await db.execute(q)
        return [dict(r) for r in await cur.fetchall()]


# ── Activity logs ─────────────────────────────────────────────────

async def log_activity(tg_id: int, event: str, tool: str = "", details: str = ""):
    async with _conn() as db:
        await _log_event(db, tg_id, event, tool, details)
        await db.commit()


async def get_recent_logs(limit: int = 30, event: str = None) -> list[dict]:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        if event:
            cur = await db.execute(
                "SELECT * FROM activity_logs WHERE event=? ORDER BY created_at DESC LIMIT ?",
                (event, limit),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in await cur.fetchall()]


# ── Notification settings ─────────────────────────────────────────

async def get_notify_settings() -> dict[str, bool]:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM notify_settings")
        return {r["event"]: bool(r["enabled"]) for r in await cur.fetchall()}


async def toggle_notify(event: str) -> bool:
    async with _conn() as db:
        cur = await db.execute("SELECT enabled FROM notify_settings WHERE event=?", (event,))
        row = await cur.fetchone()
        if not row:
            return False
        new_val = 0 if row[0] else 1
        await db.execute("UPDATE notify_settings SET enabled=? WHERE event=?", (new_val, event))
        await db.commit()
        return bool(new_val)


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
        active_24h = (await (await db.execute(
            "SELECT COUNT(*) FROM users WHERE last_active > datetime('now', '-1 day')"
        )).fetchone())[0]
        total_gens = (await (await db.execute(
            "SELECT COALESCE(SUM(total_gens),0) FROM users"
        )).fetchone())[0]
        total_revenue = (await (await db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE op='topup'"
        )).fetchone())[0]
        today_revenue = (await (await db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions "
            "WHERE op='topup' AND date(created_at)=date('now')"
        )).fetchone())[0]
        today_gens = (await (await db.execute(
            "SELECT COUNT(*) FROM activity_logs "
            "WHERE event='tool_use' AND date(created_at)=date('now')"
        )).fetchone())[0]
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT tool, COUNT(*) as cnt FROM activity_logs "
            "WHERE event='tool_use' AND tool != '' "
            "GROUP BY tool ORDER BY cnt DESC LIMIT 5"
        )
        top_tools = {r["tool"]: r["cnt"] for r in await cur.fetchall()}
        return {
            "users": total, "today_users": today, "active_24h": active_24h,
            "gens": total_gens, "today_gens": today_gens,
            "revenue": total_revenue, "today_revenue": today_revenue,
            "top_tools": top_tools,
        }


async def get_all_user_ids() -> list[int]:
    async with _conn() as db:
        cur = await db.execute("SELECT tg_id FROM users WHERE is_banned=0")
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


async def _log_event(db, tg_id: int, event: str, tool: str = "", details: str = ""):
    await db.execute(
        "INSERT INTO activity_logs (tg_id, event, tool, details) VALUES (?,?,?,?)",
        (tg_id, event, tool, details),
    )
