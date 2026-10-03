"""Single-household shopping group app."""
import asyncio
import os
import secrets
import sqlite3
from functools import wraps
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .core import aggregate, connect, format_quantity, quantity, set_setting, setting


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("APP_SECRET_KEY"),
        DATABASE=os.environ.get("DATABASE_PATH", "instance/bring_loader.sqlite3"),
        ENCRYPTION_KEY=os.environ.get("ENCRYPTION_KEY"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("Set APP_SECRET_KEY to a persistent random value")
    if not app.config["ENCRYPTION_KEY"]:
        raise RuntimeError("Set ENCRYPTION_KEY to a persistent Fernet key")
    cipher = Fernet(app.config["ENCRYPTION_KEY"].encode())

    def db():
        if "db" not in g:
            g.db = connect(app.config["DATABASE"])
        return g.db

    @app.teardown_appcontext
    def close_db(error):
        conn = g.pop("db", None)
        if conn:
            conn.close()

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def check_csrf():
        if request.method == "POST" and not secrets.compare_digest(
            session.get("csrf", ""), request.form.get("csrf", "")
        ):
            abort(400)

    def protected(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login"))
            return fn(*args, **kwargs)
        return wrapper

    def group_or_404(group_id):
        row = db().execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
        if not row:
            abort(404)
        return row

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            password_hash = setting(db(), "password_hash")
            if password_hash and check_password_hash(password_hash, request.form.get("password", "")):
                session.clear()
                session["logged_in"] = True
                flash("Signed in")
                return redirect(url_for("index"))
            flash("Incorrect password")
        return render_template("login.html", configured=bool(setting(db(), "password_hash")))

    @app.post("/logout")
    @protected
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @protected
    def index():
        groups = db().execute("""SELECT g.*, COUNT(gi.id) AS item_count FROM groups g
            LEFT JOIN group_items gi ON gi.group_id=g.id GROUP BY g.id ORDER BY g.sort_order,g.name""").fetchall()
        return render_template("index.html", groups=groups)

    def selected_counts():
        counts = {}
        for row in db().execute("SELECT id FROM groups"):
            raw = request.form.get(f"count_{row['id']}", "0").strip() or "0"
            try:
                count = int(raw)
            except ValueError:
                abort(400)
            if count < 0 or count > 99:
                abort(400)
            if count:
                counts[row["id"]] = count
        return counts

    @app.post("/preview")
    @protected
    def preview():
        counts = selected_counts()
        items = aggregate(db(), counts)
        if not items:
            flash("Choose at least one group with items")
            return redirect(url_for("index"))
        names = {r["id"]: r["name"] for r in db().execute("SELECT id,name FROM groups")}
        return render_template("preview.html", items=items, counts=counts, names=names,
                               target=setting(db(), "bring_list_name"))

    @app.post("/send")
    @protected
    def send():
        counts = selected_counts()
        items = aggregate(db(), counts)
        if not items:
            abort(400)
        email = setting(db(), "bring_email")
        encrypted = setting(db(), "bring_password")
        list_uuid = setting(db(), "bring_list_uuid")
        if not email or not encrypted or not list_uuid:
            flash("Configure your Bring! account and list first")
            return redirect(url_for("settings"))
        try:
            password = cipher.decrypt(encrypted.encode()).decode()
            asyncio.run(_send_bring(email, password, list_uuid, items))
        except Exception:
            app.logger.exception("Bring! send failed")
            flash("Bring! could not send every item. Check the list before retrying; some items may have been added.")
            return redirect(url_for("index"))
        flash(f"Sent {len(items)} items to Bring!")
        return redirect(url_for("index"))

    @app.route("/groups")
    @protected
    def groups():
        return render_template("groups.html", groups=db().execute("SELECT * FROM groups ORDER BY sort_order,name").fetchall())

    @app.post("/groups")
    @protected
    def add_group():
        name = request.form.get("name", "").strip()
        if not name:
            abort(400)
        try:
            with db():
                row = db().execute("INSERT INTO groups(name,sort_order) VALUES(?,(SELECT COALESCE(MAX(sort_order),0)+1 FROM groups))", (name,))
        except sqlite3.IntegrityError:
            flash("A group with that name already exists")
            return redirect(url_for("groups"))
        return redirect(url_for("edit_group", group_id=row.lastrowid))

    @app.route("/groups/<int:group_id>")
    @protected
    def edit_group(group_id):
        group = group_or_404(group_id)
        entries = db().execute("""SELECT gi.id,gi.quantity,i.name,i.unit FROM group_items gi
            JOIN items i ON i.id=gi.item_id WHERE gi.group_id=? ORDER BY gi.sort_order""", (group_id,)).fetchall()
        items = db().execute("SELECT * FROM items ORDER BY name").fetchall()
        return render_template("edit_group.html", group=group, entries=entries, items=items)

    @app.post("/groups/<int:group_id>/rename")
    @protected
    def rename_group(group_id):
        group_or_404(group_id)
        name = request.form.get("name", "").strip()
        if not name:
            abort(400)
        try:
            with db():
                db().execute("UPDATE groups SET name=? WHERE id=?", (name, group_id))
        except sqlite3.IntegrityError:
            flash("A group with that name already exists")
        return redirect(url_for("edit_group", group_id=group_id))

    @app.post("/groups/<int:group_id>/delete")
    @protected
    def delete_group(group_id):
        group_or_404(group_id)
        with db():
            db().execute("DELETE FROM groups WHERE id=?", (group_id,))
        return redirect(url_for("groups"))

    @app.post("/groups/<int:group_id>/items")
    @protected
    def add_group_item(group_id):
        group_or_404(group_id)
        try:
            item_id = int(request.form.get("item_id", ""))
            amount = format_quantity(quantity(request.form.get("quantity", "")))
            with db():
                db().execute("INSERT INTO group_items(group_id,item_id,quantity,sort_order) VALUES(?,?,?,(SELECT COALESCE(MAX(sort_order),0)+1 FROM group_items WHERE group_id=?))",
                             (group_id, item_id, amount, group_id))
        except (ValueError, sqlite3.IntegrityError):
            flash("Choose an existing item and a positive quantity. An item can appear once per group.")
        return redirect(url_for("edit_group", group_id=group_id))

    @app.post("/groups/<int:group_id>/items/<int:entry_id>")
    @protected
    def edit_group_item(group_id, entry_id):
        group_or_404(group_id)
        if request.form.get("action") == "delete":
            with db():
                db().execute("DELETE FROM group_items WHERE id=? AND group_id=?", (entry_id, group_id))
        else:
            try:
                amount = format_quantity(quantity(request.form.get("quantity", "")))
                with db():
                    db().execute("UPDATE group_items SET quantity=? WHERE id=? AND group_id=?", (amount, entry_id, group_id))
            except ValueError:
                flash("Quantity must be greater than zero")
        return redirect(url_for("edit_group", group_id=group_id))

    @app.route("/items")
    @protected
    def items():
        rows = db().execute("""SELECT i.*, COUNT(gi.id) AS uses FROM items i
            LEFT JOIN group_items gi ON gi.item_id=i.id GROUP BY i.id ORDER BY i.name""").fetchall()
        return render_template("items.html", items=rows)

    @app.post("/items")
    @protected
    def add_item():
        name = request.form.get("name", "").strip()
        unit = request.form.get("unit", "").strip()
        if not name:
            abort(400)
        try:
            with db():
                db().execute("INSERT INTO items(name,unit) VALUES(?,?)", (name, unit))
        except sqlite3.IntegrityError:
            flash("That item already exists. Select it when adding to a group.")
        return redirect(url_for("items"))

    @app.route("/items/<int:item_id>")
    @protected
    def edit_item(item_id):
        item = db().execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if not item:
            abort(404)
        uses = db().execute("""SELECT gi.id,gi.quantity,g.name FROM group_items gi JOIN groups g
            ON gi.group_id=g.id WHERE gi.item_id=? ORDER BY g.name""", (item_id,)).fetchall()
        return render_template("edit_item.html", item=item, uses=uses)

    @app.post("/items/<int:item_id>")
    @protected
    def update_item(item_id):
        item = db().execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if not item:
            abort(404)
        if request.form.get("action") == "delete":
            try:
                with db():
                    db().execute("DELETE FROM items WHERE id=?", (item_id,))
                return redirect(url_for("items"))
            except sqlite3.IntegrityError:
                flash("Remove this item from its groups before deleting it")
                return redirect(url_for("edit_item", item_id=item_id))
        name, unit = request.form.get("name", "").strip(), request.form.get("unit", "").strip()
        if not name:
            abort(400)
        uses = db().execute("SELECT id FROM group_items WHERE item_id=?", (item_id,)).fetchall()
        new_amounts = {}
        if unit != item["unit"] and uses:
            if request.form.get("confirm_unit") != "yes":
                flash("Confirm the unit change and enter replacement quantities for every group")
                return redirect(url_for("edit_item", item_id=item_id))
            try:
                new_amounts = {r["id"]: format_quantity(quantity(request.form.get(f"quantity_{r['id']}", ""))) for r in uses}
            except ValueError:
                flash("Enter a positive replacement quantity for every group")
                return redirect(url_for("edit_item", item_id=item_id))
        try:
            with db():
                db().execute("UPDATE items SET name=?,unit=? WHERE id=?", (name, unit, item_id))
                for entry_id, amount in new_amounts.items():
                    db().execute("UPDATE group_items SET quantity=? WHERE id=?", (amount, entry_id))
        except sqlite3.IntegrityError:
            flash("That item name already exists")
        return redirect(url_for("edit_item", item_id=item_id))

    @app.route("/settings", methods=["GET", "POST"])
    @protected
    def settings():
        if request.method == "POST":
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            if not email:
                abort(400)
            if email != setting(db(), "bring_email") and not password:
                flash("Enter the password when changing the Bring! email")
                return redirect(url_for("settings"))
            with db():
                if email != setting(db(), "bring_email"):
                    set_setting(db(), "bring_list_uuid", "")
                    set_setting(db(), "bring_list_name", "")
                set_setting(db(), "bring_email", email)
                if password:
                    set_setting(db(), "bring_password", cipher.encrypt(password.encode()).decode())
            flash("Bring! account saved. Connect to refresh available lists.")
            return redirect(url_for("settings"))
        return render_template("settings.html", email=setting(db(), "bring_email"),
                               configured=bool(setting(db(), "bring_password")),
                               selected=setting(db(), "bring_list_name"))

    @app.post("/settings/lists")
    @protected
    def list_choices():
        try:
            password = cipher.decrypt(setting(db(), "bring_password").encode()).decode()
            lists = asyncio.run(_get_bring_lists(setting(db(), "bring_email"), password))
        except Exception:
            app.logger.exception("Bring! list lookup failed")
            flash("Could not connect to Bring!. Check the account details and try again.")
            return redirect(url_for("settings"))
        return render_template("choose_list.html", lists=lists, selected=setting(db(), "bring_list_uuid"))

    @app.post("/settings/select-list")
    @protected
    def select_list():
        # Re-fetch to ensure the submitted UUID belongs to this account.
        try:
            password = cipher.decrypt(setting(db(), "bring_password").encode()).decode()
            lists = asyncio.run(_get_bring_lists(setting(db(), "bring_email"), password))
        except Exception:
            flash("Could not verify the Bring! list")
            return redirect(url_for("settings"))
        chosen = next((entry for entry in lists if entry[0] == request.form.get("list_uuid")), None)
        if not chosen:
            abort(400)
        with db():
            set_setting(db(), "bring_list_uuid", chosen[0])
            set_setting(db(), "bring_list_name", chosen[1])
        flash(f"Using Bring! list: {chosen[1]}")
        return redirect(url_for("settings"))

    @app.cli.command("set-password")
    def set_password():
        import getpass
        password = getpass.getpass("New app password: ")
        if len(password) < 8:
            raise SystemExit("Use at least 8 characters")
        confirm = getpass.getpass("Confirm: ")
        if password != confirm:
            raise SystemExit("Passwords did not match")
        with db():
            set_setting(db(), "password_hash", generate_password_hash(password))
        print("App password saved")

    return app


async def _get_bring_lists(email, password):
    import aiohttp
    from bring_api import Bring
    async with aiohttp.ClientSession() as client:
        bring = Bring(client, email, password)
        await bring.login()
        response = await bring.load_lists()
        return [(entry.listUuid, entry.name) for entry in response.lists]


async def _send_bring(email, password, list_uuid, items):
    import aiohttp
    from bring_api import Bring
    async with aiohttp.ClientSession() as client:
        bring = Bring(client, email, password)
        await bring.login()
        for name, amount, unit in items:
            await bring.save_item(list_uuid, name, f"{amount} {unit}".strip())
