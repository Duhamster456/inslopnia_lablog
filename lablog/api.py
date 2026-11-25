import re

from flask import Blueprint, current_app, g, jsonify, request, url_for
from werkzeug.exceptions import BadRequest, Unauthorized

from .entries import entry_fields, public_entry
from .search import search, validate_pattern

api = Blueprint("api", __name__, url_prefix="/api")
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


def authenticate(journal):
    header = request.headers.get("Authorization", "").split()
    if len(header) == 2 and header[0].lower() == "bearer" and TOKEN.fullmatch(header[1]):
        owner_id = journal.lookup_key(header[1])
        if owner_id is not None:
            return owner_id
    raise Unauthorized("Provide a valid API key in the Authorization: Bearer header.")


def request_entry(*, partial=False):
    if not request.is_json:
        raise BadRequest("Send Content-Type: application/json.")
    return entry_fields(request.get_json(), partial=partial)


@api.post("/entries")
def create_entry():
    entry = g.journal.create_entry(request_entry(), g.owner_id)
    response = jsonify(public_entry(entry))
    response.status_code = 201
    response.headers["Location"] = url_for("api.get_entry", entry_id=entry["id"])
    return response


@api.get("/entries/<entry_id>")
def get_entry(entry_id):
    return jsonify(public_entry(g.journal.get_entry(entry_id)))


@api.patch("/entries/<entry_id>")
def patch_entry(entry_id):
    entry = g.journal.update_entry(entry_id, request_entry(partial=True), g.owner_id)
    return jsonify(public_entry(entry))


@api.delete("/entries/<entry_id>")
def delete_entry(entry_id):
    g.journal.delete_entry(entry_id, g.owner_id)
    return "", 204


@api.get("/grep")
def grep():
    pattern = validate_pattern(request.args.get("pattern"))
    matches = search(g.journal, current_app.config["RIPGREP"], pattern)
    return jsonify([
        {"line": line, "url": url_for("api.get_entry", entry_id=entry_id)}
        for entry_id, line in matches
    ])
