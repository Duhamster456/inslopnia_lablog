import secrets

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.exceptions import BadRequest, Forbidden, RequestEntityTooLarge

from .entries import MAX_ENTRY_BYTES, EntryFieldError, entry_fields

admin = Blueprint("admin", __name__, url_prefix="/inslopnia_admin")
# A browser can turn every LF into CRLF and adds multipart field headers.
ENTRY_FORM_BYTES = 2 * MAX_ENTRY_BYTES + 16 * 1024
ENTRY_FORM_ERRORS = {
    "title": "Введите непустое название в одну строку.",
    "timestamp": "Укажите время по RFC 3339 с часовым поясом, например 2026-11-26T12:00:00+03:00.",
    "commit_hash": "Введите хеш коммита в одну строку.",
    "url": "Укажите полную ссылку на файлы эксперимента по HTTP или HTTPS.",
    "text": "Текст записи должен быть в UTF-8.",
}


def same_text(left, right):
    return secrets.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


@admin.before_request
def require_admin():
    if request.endpoint != "admin.login" and not session.get("admin"):
        return redirect(url_for("admin.login"))
    if request.method == "POST":
        if request.endpoint in {"admin.create_entry", "admin.edit_entry"}:
            request.max_content_length = ENTRY_FORM_BYTES
            request.max_form_memory_size = ENTRY_FORM_BYTES
        expected = session.get("csrf_token")
        supplied = request.form.get("csrf_token", "")
        if not expected or not same_text(expected, supplied):
            raise Forbidden("Форма устарела. Откройте страницу заново и повторите действие.")


@admin.context_processor
def csrf_context():
    def csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    return {"csrf_token": csrf_token}


@admin.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin"):
        return redirect(url_for("admin.dashboard"))
    if request.method == "POST":
        config = current_app.config
        username_ok = same_text(request.form.get("username", ""), config["ADMIN_USERNAME"])
        password_ok = same_text(request.form.get("password", ""), config["ADMIN_PASSWORD"])
        if username_ok and password_ok:
            session.clear()
            session["admin"] = True
            session.permanent = True
            return redirect(url_for("admin.dashboard"), code=303)
        return render_template("admin/login.html", error="Проверьте логин и пароль."), 401
    return render_template("admin/login.html")


@admin.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("admin.login"), code=303)


@admin.get("", strict_slashes=False)
def dashboard():
    return render_template(
        "admin/dashboard.html", users=g.journal.users(), entries=g.journal.list_entries()
    )


def form_name():
    name = request.form.get("name", "").strip()
    if not name or any(char in name for char in "\r\n\0"):
        raise BadRequest("Введите имя пользователя в одну строку.")
    return name


@admin.post("/users")
def create_user():
    g.journal.save_user(form_name())
    flash("Пользователь добавлен.", "users")
    return redirect(url_for("admin.dashboard", _anchor="users"), code=303)


@admin.post("/users/<user_id>/rename")
def rename_user(user_id):
    g.journal.save_user(form_name(), user_id)
    flash("Имя пользователя сохранено.", "users")
    return redirect(url_for("admin.dashboard", _anchor="users"), code=303)


@admin.post("/users/<user_id>/keys")
def issue_key(user_id):
    name, token = g.journal.issue_key(user_id)
    return render_template("admin/key.html", name=name, token=token), 201


@admin.post("/keys/<key_id>/revoke")
def revoke_key(key_id):
    g.journal.revoke_key(key_id)
    flash("Ключ отозван.", "users")
    return redirect(url_for("admin.dashboard", _anchor="users"), code=303)


def textarea_text(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\0", "\ufffd")


def form_entry(entry=None):
    text = request.form.get("text")
    if text is not None:
        text = textarea_text(text)
        if entry is not None and text == textarea_text(entry["text"]):
            text = entry["text"]
    fields = {
        "title": request.form.get("title"),
        "text": text,
        "commit_hash": request.form.get("commit_hash"),
    }
    timestamp = request.form.get("timestamp", "").strip()
    if timestamp:
        fields["timestamp"] = timestamp
    if "url" in request.form:
        fields["url"] = request.form["url"]
    return entry_fields(fields, partial=entry is not None)


def render_entry_form(entry=None, error=None):
    values = request.form if error else (entry or {})
    error_field = error.field if isinstance(error, EntryFieldError) else None
    message = ENTRY_FORM_ERRORS.get(error_field, "Размер записи ограничен 2 МиБ.") if error else None
    users = g.journal.users() if entry is None else []
    return render_template(
        "admin/entry.html", entry=entry, values=values, users=users,
        error=message, error_field=error_field,
    ), error.code if error else 200


@admin.route("/entries/new", methods=["GET", "POST"])
def create_entry():
    if request.method == "POST":
        try:
            g.journal.create_entry(form_entry(), request.form.get("owner_id") or None)
        except (EntryFieldError, RequestEntityTooLarge) as error:
            return render_entry_form(error=error)
        flash("Запись создана.")
        return redirect(url_for("admin.dashboard"), code=303)
    return render_entry_form()


@admin.route("/entries/<entry_id>/edit", methods=["GET", "POST"])
def edit_entry(entry_id):
    entry = g.journal.get_entry(entry_id)
    if request.method == "POST":
        try:
            g.journal.update_entry(entry_id, form_entry(entry), admin=True)
        except (EntryFieldError, RequestEntityTooLarge) as error:
            return render_entry_form(entry, error)
        flash("Запись сохранена.")
        return redirect(url_for("admin.dashboard"), code=303)
    return render_entry_form(entry)


@admin.route("/entries/<entry_id>/delete", methods=["GET", "POST"])
def delete_entry(entry_id):
    if request.method == "POST":
        g.journal.delete_entry(entry_id, admin=True)
        flash("Запись удалена.")
        return redirect(url_for("admin.dashboard"), code=303)
    return render_template("admin/delete.html", entry=g.journal.get_entry(entry_id))
