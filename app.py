"""
Project-Travel  –  清水・駿河湾クルーズ 研修旅行サイト
Flask + SQLite  (no other dependency)

Run:   pip install -r requirements.txt
       python app.py
Open:  http://127.0.0.1:5000
"""
import os
import re
import sqlite3
import secrets
import string
import time
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "instance" / "travel.db"
UPLOAD_DIR = BASE / "uploads"
IMAGES_DIR = BASE / "images"

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
SEED_STUDENT_PASSWORD = "student123"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024  # 6 MB per request
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

(BASE / "instance").mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

_key_file = BASE / "instance" / "secret.key"
if os.environ.get("SECRET_KEY"):
    app.secret_key = os.environ["SECRET_KEY"]
else:
    if not _key_file.exists():
        _key_file.write_text(secrets.token_hex(32))
    app.secret_key = _key_file.read_text().strip()


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS years (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student',
    year_id INTEGER REFERENCES years(id),
    bio TEXT NOT NULL DEFAULT '',
    website TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    year_id INTEGER NOT NULL REFERENCES years(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    photo TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS likes (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    memory_id INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, memory_id)
);
"""

SEED = {
    2024: [
        ("vihara", "ビハラ", "images/2024 students/vihara.webp", "クルーズから見る富士山", "クルーズから見る富士山がとてもきれいで、忘れられない思い出になりました。"),
        ("afuka", "アフカ", "images/2024 students/afuka.webp", "おいしいランチと写真撮影", "友達と一緒においしいランチを食べたり、写真を撮ったりできて楽しかったです。"),
        ("karki", "カルキ", "images/2024 students/karki.webp", "三保の松原と久能山東照宮の見学", "三保の松原と久能山東照宮を見学して、日本の歴史や文化を学ぶことができました。"),
        ("sharma", "サルマ", "images/2024 students/sharma.webp", "バスの中の雰囲気とクラスメイト", "バスの中の雰囲気も良く、クラスメイトみんなと仲良くなれる最高の行事でした。"),
    ],
    2025: [
        ("ayau", "アユ", "images/2025 students/ayau.webp", "船の上からの景色", "船の上から見る景色が最高でした。海風も気持ちよく、また参加したいです。"),
        ("khadka", "カドカ", "images/2025 students/khadka.webp", "友達との思い出", "普段なかなか行けない場所を友達と一緒に回れて、とても充実した一日でした。"),
        ("karishma", "カリスマ", "images/2025 students/karishma.webp", "久能山東照宮の建物", "久能山東照宮の建物が美しく、日本の歴史に興味を持つきっかけになりました。"),
        ("sapana", "サパナ", "images/2025 students/sapana.webp", "写真スポットでの思い出", "写真スポットがたくさんあって、思い出に残るすばらしい一日になりました。"),
    ],
    2026: [
        ("kumari", "クマリ", "images/2026 students/kumari.webp", "駿河湾クルーズと富士山", "駿河湾クルーズで富士山を見ることができて感動しました。写真もたくさん撮れました。"),
        ("sangita", "サンギタ", "images/2026 students/sangita.webp", "ランチタイムの会話", "はとばキッチンのランチがおいしく、友達との会話も弾んで楽しかったです。"),
        ("gc", "ジシ", "images/2026 students/gc.webp", "研修旅行の感想", "美しい景色と歴史ある場所の両方を楽しめて、思い出に残る研修旅行になりました。"),
        ("dan", "ダン", "images/2026 students/dan.webp", "最高の景色と思い出", "天気に恵まれて最高の景色でした！友達と最高の思い出が作れて大満足です。"),
    ],
}


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def normalize_url(u):
    s = (u or "").strip()
    if not s:
        return ""
    if not re.match(r"^https?://", s, re.I):
        return "https://" + s
    return s


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def q(sql, args=(), one=False):
    rows = db().execute(sql, args).fetchall()
    if one:
        return rows[0] if rows else None
    return rows


def ex(sql, args=()):
    cur = db().execute(sql, args)
    db().commit()
    return cur.lastrowid


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)

    # Existing DB ekata website column eka nathnam auto add kirima
    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "website" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN website TEXT NOT NULL DEFAULT ''")

    # admin account
    if not conn.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        conn.execute(
            "INSERT INTO users (name,email,password_hash,role,created_at) VALUES (?,?,?,?,?)",
            ("管理者", ADMIN_EMAIL.lower(), generate_password_hash(ADMIN_PASSWORD), "admin", now()),
        )
        print(f"[setup] Admin created -> {ADMIN_EMAIL} / {ADMIN_PASSWORD}  (change it!)")

    # starting data (only the very first run)
    if not conn.execute("SELECT 1 FROM years").fetchone():
        pw = generate_password_hash(SEED_STUDENT_PASSWORD)
        for year, rows in SEED.items():
            yid = conn.execute("INSERT INTO years (year,created_at) VALUES (?,?)", (year, now())).lastrowid
            for key, name, photo, title, comment in reversed(rows):
                uid = conn.execute(
                    "INSERT INTO users (name,email,password_hash,role,year_id,created_at) VALUES (?,?,?,?,?,?)",
                    (name, f"{key}@example.com", pw, "student", yid, now()),
                ).lastrowid
                conn.execute(
                    "INSERT INTO memories (user_id,year_id,title,description,photo,status,created_at) "
                    "VALUES (?,?,?,?,?,'approved',?)",
                    (uid, yid, title, comment, photo, now()),
                )
        print(f"[setup] Sample students created (password: {SEED_STUDENT_PASSWORD})")
    conn.commit()
    conn.close()


init_db()


# --------------------------------------------------------------------------
# Security helpers: CSRF, login throttle, safe redirect, image check
# --------------------------------------------------------------------------
@app.before_request
def load_user_and_check_csrf():
    g.user = None
    uid = session.get("user_id")
    if uid:
        g.user = q("SELECT * FROM users WHERE id=?", (uid,), one=True)
        if g.user is None:
            session.clear()
    if request.method == "POST":
        sent = request.form.get("_csrf", "")
        token = session.get("_csrf", "")
        if not token or not secrets.compare_digest(sent, token):
            abort(400)


@app.context_processor
def inject_globals():
    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]

    return {"csrf_token": csrf_token, "me": g.get("user")}


@app.after_request
def secure_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return resp


FAILS = {}


def throttled(key):
    t = time.time()
    FAILS[key] = [x for x in FAILS.get(key, []) if t - x < 300]
    return len(FAILS[key]) >= 5


def record_fail(key):
    FAILS.setdefault(key, []).append(time.time())


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def sniff_image(head):
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"GIF8":
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def save_photo(file):
    if not file or not file.filename:
        return None, "写真を選択してください (Please choose a photo)"
    kind = sniff_image(file.stream.read(16))
    file.stream.seek(0)
    if not kind:
        return None, "JPG / PNG / GIF / WEBP の画像のみアップロードできます"
    name = f"{uuid.uuid4().hex}.{kind}"
    file.save(UPLOAD_DIR / name)
    return f"uploads/{name}", None


def remove_photo(path):
    if path and path.startswith("uploads/"):
        try:
            (UPLOAD_DIR / path[len("uploads/"):]).unlink()
        except FileNotFoundError:
            pass


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.template_filter("photo_url")
def photo_url(path):
    if path.startswith("uploads/"):
        return url_for("uploads", filename=path[len("uploads/"):])
    return url_for("images", filename=path[len("images/"):])


def login_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if g.user is None:
            flash("ログインしてください (Please log in)", "error")
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapper


def student_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if g.user is None:
            flash("ログインしてください (Please log in)", "error")
            return redirect(url_for("login", next=request.path))
        if g.user["role"] != "student":
            flash("この操作は学生アカウントのみ可能です (Students only)", "error")
            return redirect(url_for("index"))
        return view(*a, **kw)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if g.user is None or g.user["role"] != "admin":
            return redirect(url_for("admin_login", next=request.path))
        return view(*a, **kw)
    return wrapper


# --------------------------------------------------------------------------
# Queries (author_website & author_bio athulath karala thiyenne)
# --------------------------------------------------------------------------
MEMORY_SELECT = """
SELECT m.*, u.name AS author, u.role AS author_role, u.website AS author_website, u.bio AS author_bio, y.year AS year_num,
  (SELECT COUNT(*) FROM likes l WHERE l.memory_id = m.id)    AS like_count,
  (SELECT COUNT(*) FROM comments c WHERE c.memory_id = m.id) AS comment_count
FROM memories m
JOIN users u ON u.id = m.user_id
JOIN years y ON y.id = m.year_id
"""


def active_years():
    return q("SELECT * FROM years WHERE is_active=1 ORDER BY year")


def all_years():
    return q("SELECT * FROM years ORDER BY year")


# --------------------------------------------------------------------------
# Public pages
# --------------------------------------------------------------------------
@app.route("/")
@app.route("/index.html")
def index():
    years = active_years()
    numbers = [y["year"] for y in years]
    selected = request.args.get("year", type=int)
    if selected not in numbers:
        selected = numbers[-1] if numbers else None
    memories = []
    if selected:
        memories = q(MEMORY_SELECT + " WHERE y.year=? AND m.status='approved' ORDER BY m.id DESC", (selected,))
    return render_template("index.html", years=years, selected=selected, memories=memories)


@app.route("/detail<int:n>.html")
def detail(n):
    if n not in (1, 2, 3, 4):
        abort(404)
    return send_from_directory(BASE, f"detail{n}.html")


@app.route("/images/<path:filename>")
def images(filename):
    return send_from_directory(IMAGES_DIR, filename)


@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/memory/<int:mid>")
def memory_view(mid):
    m = q(MEMORY_SELECT + " WHERE m.id=?", (mid,), one=True)
    if m is None:
        abort(404)
    can_see = m["status"] == "approved" or (
        g.user and (g.user["role"] == "admin" or g.user["id"] == m["user_id"]))
    if not can_see:
        abort(404)
    comments = q(
        "SELECT c.*, u.name AS author, u.role AS author_role FROM comments c "
        "JOIN users u ON u.id=c.user_id WHERE c.memory_id=? ORDER BY c.id", (mid,))
    liked = bool(g.user and q("SELECT 1 FROM likes WHERE user_id=? AND memory_id=?", (g.user["id"], mid), one=True))
    return render_template("memory.html", m=m, comments=comments, liked=liked)


@app.post("/memory/<int:mid>/like")
@student_required
def memory_like(mid):
    m = q("SELECT * FROM memories WHERE id=? AND status='approved'", (mid,), one=True)
    if m is None:
        abort(404)
    if q("SELECT 1 FROM likes WHERE user_id=? AND memory_id=?", (g.user["id"], mid), one=True):
        ex("DELETE FROM likes WHERE user_id=? AND memory_id=?", (g.user["id"], mid))
    else:
        ex("INSERT INTO likes (user_id, memory_id) VALUES (?,?)", (g.user["id"], mid))
    return redirect(url_for("memory_view", mid=mid))


@app.post("/memory/<int:mid>/comment")
@student_required
def memory_comment(mid):
    m = q("SELECT * FROM memories WHERE id=? AND status='approved'", (mid,), one=True)
    if m is None:
        abort(404)
    body = request.form.get("body", "").strip()
    if not body or len(body) > 500:
        flash("コメントは1〜500文字で入力してください", "error")
    else:
        ex("INSERT INTO comments (memory_id,user_id,body,created_at) VALUES (?,?,?,?)",
           (mid, g.user["id"], body, now()))
        flash("コメントを投稿しました", "ok")
    return redirect(url_for("memory_view", mid=mid) + "#comments")


@app.post("/comment/<int:cid>/delete")
@login_required
def comment_delete(cid):
    c = q("SELECT * FROM comments WHERE id=?", (cid,), one=True)
    if c is None:
        abort(404)
    if g.user["role"] != "admin" and c["user_id"] != g.user["id"]:
        abort(403)
    ex("DELETE FROM comments WHERE id=?", (cid,))
    flash("コメントを削除しました", "ok")
    return redirect(safe_next(request.form.get("next")) or url_for("memory_view", mid=c["memory_id"]))


# --------------------------------------------------------------------------
# Student: register / login / profile / upload
# --------------------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    years = active_years()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        raw_year = request.form.get("year_id", "").strip()
        custom_year = request.form.get("custom_year", type=int)
        website = normalize_url(request.form.get("website", ""))
        bio = request.form.get("bio", "").strip()[:300]
        errors = []
        if not name or len(name) > 50:
            errors.append("名前を入力してください (Name required)")
        if not EMAIL_RE.match(email):
            errors.append("メールアドレスの形式が正しくありません")
        if len(password) < 8:
            errors.append("パスワードは8文字以上にしてください")

        year_id = None
        if raw_year == "new":
            if not custom_year or not (2000 <= custom_year <= 2100):
                errors.append("新しい年度は 2000〜2100 の数字で入力してください")
            else:
                existing_y = q("SELECT * FROM years WHERE year=?", (custom_year,), one=True)
                if existing_y:
                    year_id = existing_y["id"]
                else:
                    year_id = ex("INSERT INTO years (year,created_at) VALUES (?,?)", (custom_year, now()))
        else:
            year_id = int(raw_year) if raw_year.isdigit() else None
            if not q("SELECT 1 FROM years WHERE id=? AND is_active=1", (year_id,), one=True):
                errors.append("参加年度を選択してください")

        if q("SELECT 1 FROM users WHERE email=?", (email,), one=True):
            errors.append("このメールアドレスは既に登録されています")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("register.html", years=years, form=request.form)
        uid = ex("INSERT INTO users (name,email,password_hash,role,year_id,bio,website,created_at) VALUES (?,?,?,?,?,?,?,?)",
                 (name, email, generate_password_hash(password), "student", year_id, bio, website, now()))
        session.clear()
        session["user_id"] = uid
        flash("登録が完了しました！ようこそ 🎉", "ok")
        return redirect(url_for("index"))
    return render_template("register.html", years=years, form={})


def do_login(role, template, fallback_endpoint):
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        key = f"{request.remote_addr}|{email}"
        if throttled(key):
            flash("ログイン失敗が続いています。5分後にもう一度お試しください。", "error")
            return render_template(template)
        user = q("SELECT * FROM users WHERE email=?", (email,), one=True)
        if not user or not check_password_hash(user["password_hash"], password):
            record_fail(key)
            flash("メールアドレスまたはパスワードが違います", "error")
            return render_template(template)
        if user["role"] != role:
            flash("このアカウントはこのログイン画面では使えません。"
                  + ("管理者ログインをご利用ください。" if user["role"] == "admin" else "学生ログインをご利用ください。"), "error")
            return render_template(template)
        session.clear()
        session["user_id"] = user["id"]
        return redirect(safe_next(request.args.get("next")) or url_for(fallback_endpoint))
    return render_template(template)


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user and g.user["role"] == "student":
        return redirect(url_for("index"))
    return do_login("student", "login.html", "index")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if g.user and g.user["role"] == "admin":
        return redirect(url_for("admin_dashboard"))
    return do_login("admin", "admin/login.html", "admin_dashboard")


@app.post("/logout")
def logout():
    was_admin = g.user and g.user["role"] == "admin"
    session.clear()
    return redirect(url_for("admin_login") if was_admin else url_for("index"))


@app.route("/profile", methods=["GET", "POST"])
@student_required
def profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        website = normalize_url(request.form.get("website", ""))
        bio = request.form.get("bio", "").strip()[:300]
        cur_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        errors = []
        if not name or len(name) > 50:
            errors.append("名前を入力してください")
        if not EMAIL_RE.match(email):
            errors.append("メールアドレスの形式が正しくありません")
        if q("SELECT 1 FROM users WHERE email=? AND id<>?", (email, g.user["id"]), one=True):
            errors.append("このメールアドレスは既に使われています")
        if new_pw:
            if not check_password_hash(g.user["password_hash"], cur_pw):
                errors.append("現在のパスワードが違います")
            if len(new_pw) < 8:
                errors.append("新しいパスワードは8文字以上にしてください")
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            ex("UPDATE users SET name=?, email=?, bio=?, website=? WHERE id=?", (name, email, bio, website, g.user["id"]))
            if new_pw:
                ex("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_pw), g.user["id"]))
            flash("プロフィールを更新しました", "ok")
            return redirect(url_for("profile"))
    year = q("SELECT year FROM years WHERE id=?", (g.user["year_id"],), one=True)
    return render_template("profile.html", year=year)


@app.route("/my/memories")
@student_required
def my_memories():
    rows = q(MEMORY_SELECT + " WHERE m.user_id=? ORDER BY m.id DESC", (g.user["id"],))
    return render_template("my_memories.html", memories=rows)


@app.route("/memories/new", methods=["GET", "POST"])
@student_required
def memory_new():
    year = q("SELECT * FROM years WHERE id=?", (g.user["year_id"],), one=True)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        desc = request.form.get("description", "").strip()
        if not title or len(title) > 80:
            flash("タイトルを入力してください (80文字まで)", "error")
        elif len(desc) > 1000:
            flash("感想は1000文字以内で入力してください", "error")
        else:
            path, err = save_photo(request.files.get("photo"))
            if err:
                flash(err, "error")
            else:
                ex("INSERT INTO memories (user_id,year_id,title,description,photo,status,created_at) "
                   "VALUES (?,?,?,?,?,'pending',?)",
                   (g.user["id"], g.user["year_id"], title, desc, path, now()))
                flash("アップロードしました。管理者の承認後に公開されます。", "ok")
                return redirect(url_for("my_memories"))
    return render_template("memory_new.html", year=year)


@app.post("/memory/<int:mid>/delete")
@student_required
def memory_delete(mid):
    m = q("SELECT * FROM memories WHERE id=? AND user_id=?", (mid, g.user["id"]), one=True)
    if m is None:
        abort(404)
    ex("DELETE FROM memories WHERE id=?", (mid,))
    remove_photo(m["photo"])
    flash("削除しました", "ok")
    return redirect(url_for("my_memories"))


# --------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin_dashboard():
    stats = {
        "students": q("SELECT COUNT(*) c FROM users WHERE role='student'", one=True)["c"],
        "years": q("SELECT COUNT(*) c FROM years", one=True)["c"],
        "memories": q("SELECT COUNT(*) c FROM memories", one=True)["c"],
        "pending": q("SELECT COUNT(*) c FROM memories WHERE status='pending'", one=True)["c"],
        "comments": q("SELECT COUNT(*) c FROM comments", one=True)["c"],
    }
    per_year = q("""
        SELECT y.*,
          (SELECT COUNT(*) FROM users u WHERE u.year_id=y.id AND u.role='student') AS students,
          (SELECT COUNT(*) FROM memories m WHERE m.year_id=y.id AND m.status='approved') AS memories,
          (SELECT COUNT(*) FROM memories m WHERE m.year_id=y.id AND m.status='pending') AS pending
        FROM years y ORDER BY y.year""")
    pending = q(MEMORY_SELECT + " WHERE m.status='pending' ORDER BY m.id LIMIT 6")
    return render_template("admin/dashboard.html", stats=stats, per_year=per_year, pending=pending)


@app.route("/admin/years", methods=["GET", "POST"])
@admin_required
def admin_years():
    if request.method == "POST":
        year = request.form.get("year", type=int)
        if not year or not (2000 <= year <= 2100):
            flash("年度は 2000〜2100 の数字で入力してください", "error")
        elif q("SELECT 1 FROM years WHERE year=?", (year,), one=True):
            flash(f"{year}年度は既に登録されています", "error")
        else:
            ex("INSERT INTO years (year,created_at) VALUES (?,?)", (year, now()))
            flash(f"{year}年度を追加しました。ドロップダウンに自動で表示されます。", "ok")
        return redirect(url_for("admin_years"))
    rows = q("""
        SELECT y.*,
          (SELECT COUNT(*) FROM users u WHERE u.year_id=y.id AND u.role='student') AS students,
          (SELECT COUNT(*) FROM memories m WHERE m.year_id=y.id) AS memories
        FROM years y ORDER BY y.year DESC""")
    return render_template("admin/years.html", years=rows)


@app.post("/admin/years/<int:yid>/toggle")
@admin_required
def admin_year_toggle(yid):
    y = q("SELECT * FROM years WHERE id=?", (yid,), one=True) or abort(404)
    ex("UPDATE years SET is_active=? WHERE id=?", (0 if y["is_active"] else 1, yid))
    flash(f"{y['year']}年度を{'非表示' if y['is_active'] else '表示'}にしました", "ok")
    return redirect(url_for("admin_years"))


@app.post("/admin/years/<int:yid>/delete")
@admin_required
def admin_year_delete(yid):
    y = q("SELECT * FROM years WHERE id=?", (yid,), one=True) or abort(404)
    used = q("SELECT (SELECT COUNT(*) FROM users WHERE year_id=?) + (SELECT COUNT(*) FROM memories WHERE year_id=?) c",
             (yid, yid), one=True)["c"]
    if used:
        flash("学生または思い出が登録されている年度は削除できません（非表示にできます）", "error")
    else:
        ex("DELETE FROM years WHERE id=?", (yid,))
        flash(f"{y['year']}年度を削除しました", "ok")
    return redirect(url_for("admin_years"))


def random_password(n=10):
    alphabet = string.ascii_letters.replace("l", "").replace("I", "").replace("O", "") + "23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


@app.route("/admin/students")
@admin_required
def admin_students():
    year_id = request.args.get("year_id", type=int)
    search = request.args.get("q", "").strip()
    sql = """SELECT u.*, y.year AS year_num,
               (SELECT COUNT(*) FROM memories m WHERE m.user_id=u.id) AS memories
             FROM users u LEFT JOIN years y ON y.id=u.year_id WHERE u.role='student'"""
    args = []
    if year_id:
        sql += " AND u.year_id=?"
        args.append(year_id)
    if search:
        sql += " AND (u.name LIKE ? OR u.email LIKE ?)"
        args += [f"%{search}%", f"%{search}%"]
    sql += " ORDER BY y.year DESC, u.name"
    return render_template("admin/students.html", students=q(sql, args), years=all_years(),
                           year_id=year_id, search=search)


@app.route("/admin/students/new", methods=["GET", "POST"])
@admin_required
def admin_student_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        year_id = request.form.get("year_id", type=int)
        website = normalize_url(request.form.get("website", ""))
        password = request.form.get("password", "") or random_password()
        errors = []
        if not name:
            errors.append("名前を入力してください")
        if not EMAIL_RE.match(email):
            errors.append("メールアドレスの形式が正しくありません")
        if len(password) < 8:
            errors.append("パスワードは8文字以上にしてください")
        if not q("SELECT 1 FROM years WHERE id=?", (year_id,), one=True):
            errors.append("年度を選択してください")
        if q("SELECT 1 FROM users WHERE email=?", (email,), one=True):
            errors.append("このメールアドレスは既に登録されています")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("admin/student_form.html", years=all_years(), s=request.form, is_new=True)
        ex("INSERT INTO users (name,email,password_hash,role,year_id,bio,website,created_at) VALUES (?,?,?,?,?,?,?,?)",
           (name, email, generate_password_hash(password), "student", year_id,
            request.form.get("bio", "").strip()[:300], website, now()))
        flash(f"学生を登録しました。ログイン: {email} / 初期パスワード: {password}", "ok")
        return redirect(url_for("admin_students"))
    return render_template("admin/student_form.html", years=all_years(), s={}, is_new=True)


@app.route("/admin/students/<int:uid>/edit", methods=["GET", "POST"])
@admin_required
def admin_student_edit(uid):
    s = q("SELECT * FROM users WHERE id=? AND role='student'", (uid,), one=True) or abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        year_id = request.form.get("year_id", type=int)
        website = normalize_url(request.form.get("website", ""))
        new_pw = request.form.get("password", "")
        errors = []
        if not name:
            errors.append("名前を入力してください")
        if not EMAIL_RE.match(email):
            errors.append("メールアドレスの形式が正しくありません")
        if new_pw and len(new_pw) < 8:
            errors.append("パスワードは8文字以上にしてください")
        if not q("SELECT 1 FROM years WHERE id=?", (year_id,), one=True):
            errors.append("年度を選択してください")
        if q("SELECT 1 FROM users WHERE email=? AND id<>?", (email, uid), one=True):
            errors.append("このメールアドレスは既に使われています")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("admin/student_form.html", years=all_years(), s=request.form, is_new=False, sid=uid)
        ex("UPDATE users SET name=?, email=?, year_id=?, bio=?, website=? WHERE id=?",
           (name, email, year_id, request.form.get("bio", "").strip()[:300], website, uid))
        if new_pw:
            ex("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_pw), uid))
        flash("学生情報を更新しました", "ok")
        return redirect(url_for("admin_students"))
    return render_template("admin/student_form.html", years=all_years(), s=s, is_new=False, sid=uid)


@app.post("/admin/students/<int:uid>/delete")
@admin_required
def admin_student_delete(uid):
    s = q("SELECT * FROM users WHERE id=? AND role='student'", (uid,), one=True) or abort(404)
    photos = [r["photo"] for r in q("SELECT photo FROM memories WHERE user_id=?", (uid,))]
    ex("DELETE FROM users WHERE id=?", (uid,))
    for p in photos:
        remove_photo(p)
    flash(f"{s['name']} のアカウントを削除しました", "ok")
    return redirect(url_for("admin_students"))


@app.route("/admin/memories")
@admin_required
def admin_memories():
    year_id = request.args.get("year_id", type=int)
    status = request.args.get("status", "")
    sql, args = MEMORY_SELECT + " WHERE 1=1", []
    if year_id:
        sql += " AND m.year_id=?"
        args.append(year_id)
    if status in ("pending", "approved", "rejected"):
        sql += " AND m.status=?"
        args.append(status)
    sql += " ORDER BY (m.status='pending') DESC, m.id DESC"
    return render_template("admin/memories.html", memories=q(sql, args), years=all_years(),
                           year_id=year_id, status=status)


@app.route("/admin/memories/new", methods=["GET", "POST"])
@admin_required
def admin_memory_new():
    students = q("SELECT u.id, u.name, u.year_id, y.year AS year_num FROM users u "
                 "LEFT JOIN years y ON y.id=u.year_id WHERE u.role='student' ORDER BY y.year DESC, u.name")
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        desc = request.form.get("description", "").strip()
        year_id = request.form.get("year_id", type=int)
        user_id = request.form.get("user_id", type=int) or g.user["id"]
        if not title or len(title) > 80:
            flash("タイトルを入力してください", "error")
        elif not q("SELECT 1 FROM years WHERE id=?", (year_id,), one=True):
            flash("年度を選択してください", "error")
        elif not q("SELECT 1 FROM users WHERE id=?", (user_id,), one=True):
            flash("学生が見つかりません", "error")
        else:
            path, err = save_photo(request.files.get("photo"))
            if err:
                flash(err, "error")
            else:
                ex("INSERT INTO memories (user_id,year_id,title,description,photo,status,created_at) "
                   "VALUES (?,?,?,?,?,'approved',?)", (user_id, year_id, title, desc[:1000], path, now()))
                flash("写真を公開しました", "ok")
                return redirect(url_for("admin_memories"))
    return render_template("admin/memory_new.html", years=all_years(), students=students)


@app.route("/admin/memories/<int:mid>/edit", methods=["GET", "POST"])
@admin_required
def admin_memory_edit(mid):
    m = q(MEMORY_SELECT + " WHERE m.id=?", (mid,), one=True) or abort(404)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        desc = request.form.get("description", "").strip()[:1000]
        year_id = request.form.get("year_id", type=int)
        status = request.form.get("status")
        if not title or len(title) > 80:
            flash("タイトルを入力してください", "error")
        elif status not in ("pending", "approved", "rejected") or not q(
                "SELECT 1 FROM years WHERE id=?", (year_id,), one=True):
            flash("入力内容を確認してください", "error")
        else:
            ex("UPDATE memories SET title=?, description=?, year_id=?, status=? WHERE id=?",
               (title, desc, year_id, status, mid))
            flash("更新しました", "ok")
            return redirect(url_for("admin_memories"))
    return render_template("admin/memory_edit.html", m=m, years=all_years())


@app.post("/admin/memories/<int:mid>/status")
@admin_required
def admin_memory_status(mid):
    status = request.form.get("status")
    if status not in ("approved", "rejected", "pending"):
        abort(400)
    q("SELECT 1 FROM memories WHERE id=?", (mid,), one=True) or abort(404)
    ex("UPDATE memories SET status=? WHERE id=?", (status, mid))
    flash({"approved": "承認しました ✅", "rejected": "却下しました", "pending": "保留に戻しました"}[status], "ok")
    return redirect(safe_next(request.form.get("next")) or url_for("admin_memories"))


@app.post("/admin/memories/<int:mid>/delete")
@admin_required
def admin_memory_delete(mid):
    m = q("SELECT * FROM memories WHERE id=?", (mid,), one=True) or abort(404)
    ex("DELETE FROM memories WHERE id=?", (mid,))
    remove_photo(m["photo"])
    flash("削除しました", "ok")
    return redirect(url_for("admin_memories"))


@app.route("/admin/comments")
@admin_required
def admin_comments():
    rows = q("""SELECT c.*, u.name AS author, m.title AS memory_title, y.year AS year_num
                FROM comments c JOIN users u ON u.id=c.user_id
                JOIN memories m ON m.id=c.memory_id JOIN years y ON y.id=m.year_id
                ORDER BY c.id DESC""")
    return render_template("admin/comments.html", comments=rows)


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
def http_error(e):
    msgs = {400: "リクエストが正しくありません。ページを再読み込みしてやり直してください。",
            403: "この操作の権限がありません。", 404: "ページが見つかりません。",
            413: "ファイルが大きすぎます（最大 5MB）。"}
    return render_template("error.html", code=e.code, message=msgs.get(e.code, "エラー")), e.code


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")