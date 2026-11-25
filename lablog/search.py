import logging
import subprocess
from tempfile import TemporaryFile
from time import monotonic

from werkzeug.exceptions import BadRequest, ServiceUnavailable

MAX_PATTERN_BYTES = 1024
MAX_MATCHES = 10_000
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
SEARCH_SECONDS = 10
BATCH_SIZE = 32
logger = logging.getLogger(__name__)


def validate_pattern(pattern):
    if pattern is not None:
        try:
            if 0 < len(pattern.encode("utf-8")) <= MAX_PATTERN_BYTES and "\0" not in pattern:
                return pattern
        except UnicodeEncodeError:
            pass
    raise BadRequest(f"Provide a UTF-8 pattern of 1 to {MAX_PATTERN_BYTES} bytes without NUL characters.")


def _run_rg(command, paths, directory, deadline, output):
    try:
        return subprocess.run(
            [*command, "--", *paths],
            cwd=directory,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.PIPE,
            timeout=max(0, deadline - monotonic()),
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ServiceUnavailable("Search timed out. Try a narrower pattern.") from None
    except OSError:
        logger.exception("Could not run ripgrep")
        raise ServiceUnavailable("Search is temporarily unavailable.") from None


def search(journal, executable, pattern):
    deadline = monotonic() + SEARCH_SECONDS
    command = [
        executable, "--no-config", "--text", "--encoding=none", "--crlf", "--case-sensitive",
        "--with-filename", "--null", "--no-heading", "--no-line-number", "--color=never",
        "--threads=1", f"--max-count={MAX_MATCHES + 1}", f"--regexp={pattern}",
    ]
    # An empty stdin distinguishes invalid patterns from file errors, even with an empty journal.
    validation = _run_rg(command, ["-"], journal.documents, deadline, subprocess.DEVNULL)
    if validation.returncode not in (0, 1):
        message = validation.stderr.decode("utf-8", errors="replace").strip()
        raise BadRequest(message or "Invalid ripgrep pattern.")

    matches = []
    remaining_bytes = MAX_OUTPUT_BYTES
    with journal.search_documents() as rows:
        while batch := rows.fetchmany(BATCH_SIZE):
            entries = {row["filename"].encode("ascii"): row["id"] for row in batch}
            paths = [row["filename"] for row in batch]
            with TemporaryFile() as output:
                result = _run_rg(command, paths, journal.documents, deadline, output)
                if result.returncode not in (0, 1):
                    logger.error("ripgrep failed with status %s: %r", result.returncode, result.stderr)
                    raise ServiceUnavailable("Search is temporarily unavailable.")
                output.seek(0)
                data = output.read(remaining_bytes + 1)

            remaining_bytes -= len(data)
            if remaining_bytes < 0 or len(matches) + data.count(b"\n") > MAX_MATCHES:
                raise BadRequest("Search returned too many results. Try a narrower pattern.")
            for record in data.split(b"\n")[:-1]:
                filename, _, line = record.partition(b"\0")
                matches.append((entries[filename], line.removesuffix(b"\r").decode("utf-8")))
    return matches
