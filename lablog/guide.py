import json
from shlex import quote

from .entries import ENTRY_FIELDS, MAX_ENTRY_BYTES
from .search import MAX_MATCHES, MAX_OUTPUT_BYTES, MAX_PATTERN_BYTES, SEARCH_SECONDS

EXAMPLE_ID = "460bc220abf7480ea3f793b592a52b6a"
EXAMPLE_PATH = f"/api/entries/{EXAMPLE_ID}"
ENTRY_PATH = "/api/entries/{id}"
SHELL_ENTRY_PATH = "/api/entries/$ENTRY_ID"
CREATE_BODY = {
    "title": "Сравнение параметров кэша",
    "timestamp": "2026-11-26T12:30:00Z",
    "commit_hash": "a1b2c3d",
    "url": "https://files.example.org/experiments/cache-run/",
    "text": "latency median=121 ms\nНа холодном старте был один timeout.",
}
ENTRY_EXAMPLE = {"id": EXAMPLE_ID, **CREATE_BODY, "timestamp": "2026-11-26T12:30:00.000000Z"}
PATCH_BODY = {"text": "latency median=118 ms", "commit_hash": None, "url": None}
SEARCH_PATTERN = "(?i)latency|timeout"


def curl_example(method, path, *, body=None, pattern=None):
    command = [
        f"curl -i -X {method}",
        f'"$BASE_URL{path}"',
        '-H "Authorization: Bearer $API_KEY"',
    ]
    if body is not None:
        command.extend([
            "-H 'Content-Type: application/json'",
            "--data-binary @- <<'JSON'",
        ])
    if pattern is not None:
        command.extend(["--get", "--data-urlencode " + quote(f"pattern={pattern}")])
    script = " \\\n  ".join(command)
    if body is not None:
        script += "\n" + json.dumps(body, ensure_ascii=False, indent=2) + "\nJSON"
    return script


GUIDE = {
    "title": "API журнала inslopnia",
    "summary": "Создавайте записи экспериментов, ищите совпавшие строки и читайте полные записи.",
    "instruction": {
        "method": "GET",
        "path": "/",
        "description": "Инструкция открыта без ключа. По умолчанию возвращается JSON. "
        "Браузер при открытии страницы запрашивает HTML. Для явного запроса JSON передайте Accept: application/json.",
    },
    "base_url": "Используйте адрес этого сервиса, включая схему и порт, без завершающего /. "
    "Пути API и ссылки из поиска относятся к этому адресу.",
    "authentication": {
        "header": "Authorization",
        "value": "Bearer <API_KEY>",
        "description": "Получите ключ у команды inslopnia и передавайте его при каждом запросе к /api/. "
        "Действующий ключ позволяет искать и читать записи всех авторов, "
        "а также создавать записи от своего имени и изменять или удалять свои.",
    },
    "examples_setup": {
        "description": "В примерах используется POSIX-совместимая оболочка и curl. "
        "Подставьте адрес сервиса и ключ. Отправляйте JSON в кодировке UTF-8. После создания записи задайте ENTRY_ID "
        "равным полю id из ответа.",
        "command": "BASE_URL='https://journal.example.org'\nAPI_KEY='YOUR_API_KEY'\n"
        "curl -H 'Accept: application/json' \"$BASE_URL/\"",
        "after_create": "ENTRY_ID='ID_FROM_CREATE_RESPONSE'",
    },
    "entry_fields": [
        {"name": "id", "type": "string", "description": "Идентификатор, который назначает сервер."},
        {"name": "title", "type": "string", "description": "Непустой заголовок в одну строку."},
        {"name": "timestamp", "type": "string", "description": "Время эксперимента в RFC 3339 с часовым поясом. "
         "Поддерживаются до шести знаков дробной части секунды. Сервер возвращает время в UTC с суффиксом Z."},
        {"name": "commit_hash", "type": "string | null", "description": "Однострочный хеш коммита. "
         "По умолчанию null. Пустая строка также сохраняется как null."},
        {"name": "url", "type": "string | null", "description": "Абсолютная ссылка на файлы эксперимента по HTTP или HTTPS. "
         "По умолчанию null. Пустая строка сохраняется как null."},
        {"name": "text", "type": "string", "description": "Полный текст записи. Может содержать несколько строк."},
    ],
    "endpoints": [
        {
            "method": "POST",
            "path": "/api/entries",
            "description": "Создаёт запись от имени владельца ключа. Если timestamp пропущен, "
            "используется текущее время сервера.",
            "request": {"content_type": "application/json", "required": ["title", "text"],
                        "optional": ["timestamp", "commit_hash", "url"], "example": CREATE_BODY},
            "success": {"status": 201, "description": "Полная запись. Заголовок Location содержит путь к ней.",
                        "headers": {"Location": EXAMPLE_PATH}, "example": ENTRY_EXAMPLE},
            "curl": curl_example("POST", "/api/entries", body=CREATE_BODY),
        },
        {
            "method": "GET",
            "path": ENTRY_PATH,
            "description": "Читает полную запись по id. Можно читать записи других авторов.",
            "request": {"path_parameters": {"id": "Значение id из записи. Можно сразу использовать url из поиска."}},
            "success": {"status": 200, "description": "Полная запись.", "example": ENTRY_EXAMPLE},
            "curl": curl_example("GET", SHELL_ENTRY_PATH),
        },
        {
            "method": "PATCH",
            "path": ENTRY_PATH,
            "description": "Обновляет переданные поля своей записи. Пропущенные поля сохраняют прежние значения. "
            "Чтобы очистить хеш коммита или ссылку на файлы, передайте null в поле commit_hash или url соответственно.",
            "request": {"path_parameters": {"id": "Идентификатор своей записи."},
                        "content_type": "application/json", "optional": list(ENTRY_FIELDS),
                        "body_rule": "Объект должен содержать хотя бы одно из этих полей.", "example": PATCH_BODY},
            "success": {"status": 200, "description": "Полная обновлённая запись.",
                        "example": {**ENTRY_EXAMPLE, **PATCH_BODY}},
            "curl": curl_example("PATCH", SHELL_ENTRY_PATH, body=PATCH_BODY),
        },
        {
            "method": "DELETE",
            "path": ENTRY_PATH,
            "description": "Удаляет свою запись.",
            "request": {"path_parameters": {"id": "Идентификатор своей записи."}},
            "success": {"status": 204, "description": "Запись удалена. Тело ответа пустое."},
            "curl": curl_example("DELETE", SHELL_ENTRY_PATH),
        },
        {
            "method": "GET",
            "path": "/api/grep",
            "description": "Ищет по заголовкам и строкам текста всех записей через ripgrep. "
            "Шаблон учитывает регистр по умолчанию. Флаг (?i) включает поиск без учёта регистра. "
            "Используйте синтаксис стандартных регулярных выражений ripgrep и закодируйте шаблон для URL.",
            "request": {"query_parameters": {"pattern": {
                "required": True, "type": "string", "example": SEARCH_PATTERN,
                "description": f"Регулярное выражение длиной 1–{MAX_PATTERN_BYTES} байт в UTF-8. "
                "Передайте его как значение pattern, без обрамляющих косых черт.",
            }}},
            "success": {"status": 200, "description": "Один объект на совпавшую строку. Поле line содержит "
                        "полный текст совпавшей строки, а url содержит путь к записи на этом же сервере. "
                        "Если совпадений нет, вернётся [].",
                        "example": [{"line": "latency median=121 ms", "url": EXAMPLE_PATH},
                                    {"line": "На холодном старте был один timeout.", "url": EXAMPLE_PATH}]},
            "curl": curl_example("GET", "/api/grep", pattern=SEARCH_PATTERN),
        },
    ],
    "errors": {
        "example": {"error": "Entry not found."},
        "statuses": [
            {"code": 400, "meaning": "Некорректное тело, параметр pattern или слишком широкий поиск."},
            {"code": 401, "meaning": "Ключ отсутствует, недействителен или отозван."},
            {"code": 403, "meaning": "Редактирование или удаление чужой записи."},
            {"code": 404, "meaning": "Запись или маршрут не найдены."},
            {"code": 405, "meaning": "Метод для этого маршрута не поддерживается."},
            {"code": 413, "meaning": "Превышен лимит размера тела запроса или сохранённой записи."},
            {"code": 503, "meaning": "Журнал занят, поиск недоступен или превышено время поиска."},
        ],
    },
    "limits": [
        f"Тело POST или PATCH и суммарный размер значений полей сохранённой записи ограничены "
        f"{MAX_ENTRY_BYTES // (1024 * 1024)} МиБ каждый.",
        f"Один поиск ограничен {MAX_MATCHES} совпавшими строками, "
        f"{MAX_OUTPUT_BYTES // (1024 * 1024)} МиБ вывода ripgrep и {SEARCH_SECONDS} секундами. "
        "При превышении лимита уточните шаблон и повторите запрос.",
    ],
    "retrieval": [
        "Ищите ключевые слова и фрагменты вывода в заголовках и текстах записей через GET /api/grep. "
        "Хеш коммита совпадёт, если он встречается в заголовке или тексте.",
        "Соберите уникальные url из результата. Запросите каждый путь методом GET с тем же ключом, "
        "чтобы получить полную запись. Если id уже известен, сразу вызовите GET /api/entries/{id}.",
        "Используйте тексты полных записей как контекст ответа. Указывайте ссылки на записи рядом с выводами. "
        "Ссылка на файлы эксперимента доступна в поле url полной записи.",
    ],
}
