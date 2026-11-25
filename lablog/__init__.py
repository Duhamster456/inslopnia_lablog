import os
import shutil
import sqlite3
from datetime import timedelta
from pathlib import Path

from flask import Flask, g, jsonify, make_response, render_template, request
from werkzeug.exceptions import HTTPException, InternalServerError, ServiceUnavailable

from .admin import admin
from .api import api, authenticate
from .entries import MAX_ENTRY_BYTES
from .guide import GUIDE
from .storage import Journal


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATA_DIR=os.environ.get("DATA_DIR", "data"),
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD"),
        MAX_CONTENT_LENGTH=MAX_ENTRY_BYTES,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        SESSION_COOKIE_NAME="inslopnia_admin",
        SESSION_COOKIE_PATH="/inslopnia_admin",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "").lower() in {"1", "true"},
        SESSION_REFRESH_EACH_REQUEST=False,
        RIPGREP=shutil.which("rg"),
    )
    if config:
        app.config.update(config)

    required = ("SECRET_KEY", "ADMIN_USERNAME", "ADMIN_PASSWORD")
    missing = [name for name in required if not app.config[name]]
    if missing:
        raise RuntimeError("Set the following environment variables: " + ", ".join(missing))
    if not app.config["RIPGREP"]:
        raise RuntimeError("Install ripgrep and make rg available on PATH.")

    app.config["RIPGREP"] = str(Path(app.config["RIPGREP"]).resolve())
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    journal = Journal(Path(app.config["DATA_DIR"]).resolve())

    def is_api_request():
        return request.path == "/api" or request.path.startswith("/api/")

    @app.before_request
    def load_journal():
        g.journal = journal
        if is_api_request():
            g.owner_id = authenticate(journal)

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if is_api_request() or request.path.startswith("/inslopnia_admin"):
            response.headers["Cache-Control"] = "no-store"
        if response.mimetype == "text/html":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
            )
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        response = error.get_response()
        if is_api_request():
            response.set_data(app.json.dumps({"error": error.description}))
            response.content_type = "application/json"
            if error.code == 401:
                response.headers["WWW-Authenticate"] = 'Bearer realm="inslopnia"'
        else:
            response.set_data(render_template("error.html", code=error.code, message=error.description))
        return response

    @app.errorhandler(sqlite3.OperationalError)
    def database_error(error):
        if (getattr(error, "sqlite_errorcode", 0) & 0xFF) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            return http_error(ServiceUnavailable("The journal is busy. Try again shortly."))
        app.logger.error("SQLite operation failed", exc_info=error)
        return http_error(InternalServerError())

    @app.get("/")
    def index():
        preferred = request.accept_mimetypes.best_match(("application/json", "text/html"))
        if preferred == "text/html":
            response = make_response(render_template("index.html", guide=GUIDE))
        else:
            response = jsonify(GUIDE)
        response.vary.add("Accept")
        return response

    app.register_blueprint(api)
    app.register_blueprint(admin)
    return app
