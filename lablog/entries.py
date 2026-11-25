import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

ENTRY_FIELDS = ("title", "timestamp", "commit_hash", "url", "text")
NULLABLE_FIELDS = ("commit_hash", "url")
MAX_ENTRY_BYTES = 2 * 1024 * 1024
TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


class EntryFieldError(BadRequest):
    def __init__(self, field, description):
        super().__init__(description)
        self.field = field


def utc_timestamp(value):
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def now_timestamp():
    return utc_timestamp(datetime.now(UTC))


def normalize_url(value):
    value = value.strip()
    if not value:
        return None
    try:
        address = urlsplit(value)
        port = address.port
        if (
            address.scheme in {"http", "https"}
            and address.hostname
            and (port is None or port > 0)
            and not re.search(r"[\s\x00-\x1f\x7f\\]", value)
        ):
            return value
    except ValueError:
        pass
    raise EntryFieldError("url", "url must be an absolute HTTP or HTTPS URL.")


def entry_fields(values, *, partial=False):
    if not isinstance(values, dict):
        raise BadRequest("Send a JSON object with the entry fields.")

    unknown = values.keys() - set(ENTRY_FIELDS)
    if unknown:
        raise BadRequest(f"Use only {', '.join(ENTRY_FIELDS)} as entry fields.")
    if partial and not values:
        raise BadRequest("Send at least one field to update.")
    if not partial and not {"title", "text"} <= values.keys():
        raise BadRequest("Both title and text are required.")

    fields = values.copy()
    for key, value in fields.items():
        if key in NULLABLE_FIELDS and value is None:
            continue
        if not isinstance(value, str):
            raise EntryFieldError(key, f"{key} must be a string.")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise EntryFieldError(key, f"{key} must be valid Unicode.") from None

    if "title" in fields:
        title = fields["title"]
        if not title.strip() or any(char in title for char in "\r\n\0"):
            raise EntryFieldError("title", "title must be a non-empty single line.")

    commit_hash = fields.get("commit_hash")
    if commit_hash == "":
        fields["commit_hash"] = None
    elif commit_hash is not None and any(char in commit_hash for char in "\r\n\0"):
        raise EntryFieldError("commit_hash", "commit_hash must be a single line.")

    if fields.get("url") is not None:
        fields["url"] = normalize_url(fields["url"])

    if "timestamp" in fields:
        value = fields["timestamp"]
        if not TIMESTAMP.fullmatch(value):
            raise EntryFieldError(
                "timestamp", "Use an RFC 3339 timestamp with a time zone, such as 2026-11-26T12:00:00Z."
            )
        try:
            fields["timestamp"] = utc_timestamp(datetime.fromisoformat(value.upper()))
        except (ValueError, OverflowError):
            raise EntryFieldError("timestamp", "timestamp is outside the supported date and time range.") from None

    if not partial:
        for field in NULLABLE_FIELDS:
            fields.setdefault(field, None)
        if "timestamp" not in fields:
            fields["timestamp"] = now_timestamp()
    return fields


def check_entry_size(entry):
    size = sum(len(entry[key].encode("utf-8")) for key in ENTRY_FIELDS if entry[key] is not None)
    if size > MAX_ENTRY_BYTES:
        raise RequestEntityTooLarge("The entry fields exceed 2 MiB.")


def public_entry(entry):
    return {"id": entry["id"], **{key: entry[key] for key in ENTRY_FIELDS}}
