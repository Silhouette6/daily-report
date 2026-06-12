#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import shlex
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Sequence
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


CLAUDE_PROJECTS_DIR = Path("~/.claude/projects").expanduser()
CODEX_STATE_DB = Path("~/.codex/state_5.sqlite").expanduser()
DEFAULT_CONFIG_PATH = Path("config.md")
DEFAULT_TIMEZONE = "Asia/Shanghai"
WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
CODEX_THREADS_QUERY = """
SELECT id, title, cwd, rollout_path, created_at_ms, updated_at_ms
FROM threads
WHERE updated_at_ms >= ? AND updated_at_ms < ?
ORDER BY updated_at_ms ASC
"""


@dataclass(frozen=True)
class WorkspaceTarget:
    kind: str
    workspace_path: str
    user: str | None = None
    host: str | None = None
    port: int | None = None

    @property
    def display_label(self) -> str:
        if self.kind == "ssh":
            return f"{self.user}@{self.host}:{self.port} {self.workspace_path}"
        return "Local"

    @property
    def ssh_destination(self) -> str:
        if self.kind != "ssh" or not self.user or not self.host:
            raise ValueError("SSH destination is only available for ssh workspace targets.")
        return f"{self.user}@{self.host}"

    @property
    def dedupe_key(self) -> tuple[object, ...]:
        return (self.kind, self.user, self.host, self.port, self.workspace_path)


@dataclass
class Message:
    role: str
    timestamp: datetime
    text: str


@dataclass
class Session:
    tool: str
    session_id: str
    title: str
    cwd: str
    source_path: str
    started_at: datetime
    ended_at: datetime
    messages: list[Message]
    location_label: str = "Local"


@dataclass
class RemoteSection:
    target: WorkspaceTarget
    claude_sessions: list[Session]
    codex_sessions: list[Session]


class RemoteCommandError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export today's Claude Code and Codex conversations to Markdown."
    )
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Target date in YYYY-MM-DD. Default: today.",
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help="IANA timezone used to group messages by date.",
    )
    parser.add_argument(
        "--workspace",
        help="Optional substring filter for session cwd, such as '/Users/fish/docs/daily-report'.",
    )
    parser.add_argument(
        "--max-chars-per-message",
        type=int,
        default=4000,
        help="Maximum characters kept per message. Use 0 for no limit.",
    )
    parser.add_argument(
        "--output",
        help="Optional output Markdown path. Defaults to Report/DailyReportYYYY-MM-DD/ai_chat_historyYYYY-MM-DD.md",
    )
    parser.add_argument(
        "--include-subagents",
        action="store_true",
        help="Include Claude Code subagent transcripts under ~/.claude/projects/**/subagents/",
    )
    parser.add_argument(
        "--include-remote",
        action="store_true",
        help="Load remote Claude Code and Codex sessions from ssh:// workspaces in config.md.",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the workspace config file. Default: ./config.md",
    )
    return parser.parse_args()


def parse_iso8601(timestamp: str) -> datetime:
    if timestamp.endswith("Z"):
        timestamp = timestamp[:-1] + "+00:00"
    return datetime.fromisoformat(timestamp)


def to_local(dt: datetime, timezone: ZoneInfo) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone)
    return dt.astimezone(timezone)


def clean_text(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 32].rstrip() + "\n\n[... truncated ...]"


def extract_text_from_content(role: str, content: object) -> str:
    if isinstance(content, str):
        return clean_text(content)

    if not isinstance(content, list):
        return ""

    chunks: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue

        item_type = item.get("type")
        if role == "user" and item_type == "input_text":
            chunks.append(str(item.get("text", "")))
        elif role == "assistant" and item_type == "output_text":
            chunks.append(str(item.get("text", "")))
        elif role == "assistant" and item_type == "text":
            chunks.append(str(item.get("text", "")))

    return clean_text("\n\n".join(part for part in chunks if part.strip()))


def should_skip_user_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.startswith("<environment_context>"):
        return True
    if stripped.startswith("<task-notification>"):
        return True
    return False


def session_title_from_text(text: str, fallback: str) -> str:
    stripped = text.strip()
    if not stripped:
        return fallback
    first_line = stripped.splitlines()[0].strip()
    if len(first_line) > 60:
        return first_line[:57] + "..."
    return first_line


def is_local_workspace_entry(entry: str) -> bool:
    return entry.startswith(("/", "~/")) or bool(WINDOWS_ABS_PATH_RE.match(entry))


def parse_workspace_target(entry: str, config_path: Path, line_number: int) -> WorkspaceTarget:
    if entry.startswith("ssh://"):
        parsed = urlparse(entry)
        if not parsed.hostname:
            raise ValueError(
                f"{config_path}:{line_number} contains an ssh workspace without a host: {entry}"
            )
        if not parsed.username:
            raise ValueError(
                f"{config_path}:{line_number} contains an ssh workspace without a username: {entry}"
            )
        if not parsed.path or not parsed.path.startswith("/"):
            raise ValueError(
                f"{config_path}:{line_number} contains an ssh workspace without an absolute path: {entry}"
            )
        return WorkspaceTarget(
            kind="ssh",
            user=parsed.username,
            host=parsed.hostname,
            port=parsed.port or 22,
            workspace_path=parsed.path,
        )

    if is_local_workspace_entry(entry):
        return WorkspaceTarget(kind="local", workspace_path=str(Path(entry).expanduser()))

    raise ValueError(
        f"{config_path}:{line_number} contains an unsupported workspace entry: {entry}. "
        "Use an absolute local path or ssh://user@host:port/abs/path."
    )


def parse_workspace_targets(config_path: Path) -> list[WorkspaceTarget]:
    if not config_path.exists():
        raise FileNotFoundError(f"Workspace config not found: {config_path}")

    lines = config_path.read_text(encoding="utf-8").splitlines()
    heading_names = [
        line.strip().lstrip("#").strip().lower()
        for line in lines
        if line.strip().startswith("#")
    ]
    restrict_to_workspace_section = "git workspaces" in heading_names

    targets: list[WorkspaceTarget] = []
    seen: set[tuple[object, ...]] = set()
    in_workspace_section = not restrict_to_workspace_section

    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if stripped.lstrip("#").strip().lower() == "git workspaces":
                in_workspace_section = True
            elif restrict_to_workspace_section:
                in_workspace_section = False
            continue
        if not in_workspace_section:
            continue
        if not stripped.startswith(("- ", "* ")):
            continue

        entry = stripped[2:].strip()
        if not entry:
            continue

        target = parse_workspace_target(entry, config_path, line_number)
        if target.dedupe_key in seen:
            continue
        seen.add(target.dedupe_key)
        targets.append(target)

    return targets


def matches_session_cwd(
    cwd: str,
    required_workspace: str | None,
    workspace_filter: str | None,
) -> bool:
    if required_workspace and required_workspace not in cwd:
        return False
    if workspace_filter and workspace_filter not in cwd:
        return False
    return True


def build_claude_session(
    text: str,
    source_path: str,
    location_label: str,
    target_date: date,
    timezone: ZoneInfo,
    workspace_filter: str | None,
    max_chars: int,
    required_workspace: str | None = None,
) -> Session | None:
    messages: list[Message] = []
    cwd = ""
    session_id = Path(source_path).stem
    title = Path(source_path).stem

    for line in text.splitlines():
        obj = json.loads(line)
        role = None
        timestamp_str = obj.get("timestamp")
        payload = None

        if obj.get("type") in {"user", "assistant"}:
            role = obj.get("type")
            payload = obj.get("message", {})
        elif isinstance(obj.get("message"), dict) and obj["message"].get("role") in {"user", "assistant"}:
            role = obj["message"]["role"]
            payload = obj["message"]
        else:
            continue

        if not timestamp_str or not isinstance(payload, dict):
            continue

        local_ts = to_local(parse_iso8601(timestamp_str), timezone)
        if local_ts.date() != target_date:
            continue

        text_value = extract_text_from_content(role, payload.get("content"))
        if role == "user" and should_skip_user_text(text_value):
            continue
        if not text_value:
            continue

        text_value = truncate_text(text_value, max_chars)
        cwd = cwd or str(obj.get("cwd", ""))
        session_id = str(obj.get("sessionId", session_id))
        if title == Path(source_path).stem and role == "user":
            title = session_title_from_text(text_value, Path(source_path).stem)
        messages.append(Message(role=role, timestamp=local_ts, text=text_value))

    if not messages:
        return None
    if not matches_session_cwd(cwd, required_workspace, workspace_filter):
        return None

    return Session(
        tool="Claude Code",
        session_id=session_id,
        title=title,
        cwd=cwd,
        source_path=source_path,
        started_at=messages[0].timestamp,
        ended_at=messages[-1].timestamp,
        messages=messages,
        location_label=location_label,
    )


def build_codex_session(
    text: str,
    row: dict,
    location_label: str,
    target_date: date,
    timezone: ZoneInfo,
    workspace_filter: str | None,
    max_chars: int,
    required_workspace: str | None = None,
) -> Session | None:
    cwd = str(row.get("cwd") or "")
    if not matches_session_cwd(cwd, required_workspace, workspace_filter):
        return None

    messages: list[Message] = []
    for line in text.splitlines():
        obj = json.loads(line)
        if obj.get("type") != "response_item":
            continue

        payload = obj.get("payload", {})
        if not isinstance(payload, dict) or payload.get("type") != "message":
            continue

        role = payload.get("role")
        if role not in {"user", "assistant"}:
            continue

        timestamp_str = obj.get("timestamp")
        if not timestamp_str:
            continue
        local_ts = to_local(parse_iso8601(timestamp_str), timezone)
        if local_ts.date() != target_date:
            continue

        text_value = extract_text_from_content(role, payload.get("content"))
        if role == "user" and should_skip_user_text(text_value):
            continue
        if not text_value:
            continue

        messages.append(
            Message(
                role=role,
                timestamp=local_ts,
                text=truncate_text(text_value, max_chars),
            )
        )

    if not messages:
        return None

    session_id = str(row["id"])
    title = str(row.get("title") or "") or session_title_from_text(messages[0].text, session_id)
    return Session(
        tool="Codex",
        session_id=session_id,
        title=title,
        cwd=cwd,
        source_path=str(row["rollout_path"]),
        started_at=messages[0].timestamp,
        ended_at=messages[-1].timestamp,
        messages=messages,
        location_label=location_label,
    )


def sort_sessions(sessions: list[Session]) -> list[Session]:
    sessions.sort(key=lambda item: (item.started_at, item.title))
    return sessions


def read_local_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_claude_sessions_from_paths(
    paths: Sequence[str],
    reader: Callable[[str], str],
    target_date: date,
    timezone: ZoneInfo,
    workspace_filter: str | None,
    max_chars: int,
    location_label: str,
    required_workspace: str | None = None,
    warnings: list[str] | None = None,
) -> list[Session]:
    sessions: list[Session] = []
    for source_path in sorted(paths):
        try:
            session = build_claude_session(
                text=reader(source_path),
                source_path=source_path,
                location_label=location_label,
                target_date=target_date,
                timezone=timezone,
                workspace_filter=workspace_filter,
                max_chars=max_chars,
                required_workspace=required_workspace,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RemoteCommandError) as exc:
            if warnings is not None:
                warnings.append(f"跳过 {location_label} 的 Claude transcript `{source_path}`: {exc}")
            continue
        if session is not None:
            sessions.append(session)

    return sort_sessions(sessions)


def load_codex_sessions_from_rows(
    rows: Sequence[dict],
    reader: Callable[[str], str],
    target_date: date,
    timezone: ZoneInfo,
    workspace_filter: str | None,
    max_chars: int,
    location_label: str,
    required_workspace: str | None = None,
    warnings: list[str] | None = None,
) -> list[Session]:
    sessions: list[Session] = []
    for row in rows:
        rollout_path = str(row["rollout_path"])
        try:
            session = build_codex_session(
                text=reader(rollout_path),
                row=row,
                location_label=location_label,
                target_date=target_date,
                timezone=timezone,
                workspace_filter=workspace_filter,
                max_chars=max_chars,
                required_workspace=required_workspace,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RemoteCommandError) as exc:
            if warnings is not None:
                warnings.append(f"跳过 {location_label} 的 Codex transcript `{rollout_path}`: {exc}")
            continue
        if session is not None:
            sessions.append(session)

    return sort_sessions(sessions)


def load_local_claude_sessions(
    target_date: date,
    timezone: ZoneInfo,
    workspace_filter: str | None,
    max_chars: int,
    include_subagents: bool,
) -> list[Session]:
    if not CLAUDE_PROJECTS_DIR.exists():
        return []

    paths = [
        str(path)
        for path in CLAUDE_PROJECTS_DIR.rglob("*.jsonl")
        if include_subagents or "subagents" not in path.parts
    ]
    return load_claude_sessions_from_paths(
        paths=paths,
        reader=read_local_text,
        target_date=target_date,
        timezone=timezone,
        workspace_filter=workspace_filter,
        max_chars=max_chars,
        location_label="Local",
    )


def codex_time_range_ms(target_date: date, timezone: ZoneInfo) -> tuple[int, int]:
    start_local = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone)
    end_local = start_local + timedelta(days=1)
    return int(start_local.timestamp() * 1000), int(end_local.timestamp() * 1000)


def query_local_codex_thread_rows(start_ms: int, end_ms: int) -> list[dict]:
    if not CODEX_STATE_DB.exists():
        return []

    conn = sqlite3.connect(f"file:{CODEX_STATE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(CODEX_THREADS_QUERY, (start_ms, end_ms)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def load_local_codex_sessions(
    target_date: date,
    timezone: ZoneInfo,
    workspace_filter: str | None,
    max_chars: int,
) -> list[Session]:
    start_ms, end_ms = codex_time_range_ms(target_date, timezone)
    rows = []
    for row in query_local_codex_thread_rows(start_ms, end_ms):
        rollout_path = Path(str(row["rollout_path"]))
        if rollout_path.exists():
            rows.append(row)

    return load_codex_sessions_from_rows(
        rows=rows,
        reader=read_local_text,
        target_date=target_date,
        timezone=timezone,
        workspace_filter=workspace_filter,
        max_chars=max_chars,
        location_label="Local",
    )


def run_remote_command(target: WorkspaceTarget, command: str) -> str:
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-p",
            str(target.port or 22),
            target.ssh_destination,
            command,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise RemoteCommandError(detail)
    return result.stdout


def run_remote_python(target: WorkspaceTarget, script: str, payload: dict | None = None) -> str:
    payload_json = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))
    command = (
        "python3 - <<'PY'\n"
        "import json\n"
        f"payload = json.loads({payload_json!r})\n"
        f"{script.strip()}\n"
        "PY"
    )
    return run_remote_command(target, command)


def run_remote_python_json(target: WorkspaceTarget, script: str, payload: dict | None = None) -> object:
    output = run_remote_python(target, script, payload)
    try:
        return json.loads(output or "null")
    except json.JSONDecodeError as exc:
        raise RemoteCommandError(f"Remote command did not return valid JSON: {exc}") from exc


def find_remote_files(target: WorkspaceTarget, root: str, pattern: str) -> list[str]:
    result = run_remote_python_json(
        target,
        """
from pathlib import Path

root = Path(payload["root"]).expanduser()
if not root.exists():
    print("[]")
else:
    paths = sorted(str(path) for path in root.rglob(payload["pattern"]) if path.is_file())
    print(json.dumps(paths, ensure_ascii=False))
""",
        {"root": root, "pattern": pattern},
    )
    return [str(item) for item in result or []]


def read_remote_text(target: WorkspaceTarget, path: str) -> str:
    return run_remote_command(target, f"cat {shlex.quote(path)}")


def read_remote_texts(target: WorkspaceTarget, paths: Sequence[str]) -> dict[str, dict[str, str]]:
    if not paths:
        return {}

    result = run_remote_python_json(
        target,
        """
from pathlib import Path

results = {}
for raw_path in payload["paths"]:
    path = Path(raw_path)
    try:
        results[str(path)] = {"content": path.read_text(encoding="utf-8")}
    except Exception as exc:
        results[str(path)] = {"error": str(exc)}
print(json.dumps(results, ensure_ascii=False))
""",
        {"paths": list(paths)},
    )
    return {
        str(path): {
            str(key): str(value)
            for key, value in details.items()
        }
        for path, details in dict(result or {}).items()
    }


def query_remote_codex_thread_rows(
    target: WorkspaceTarget,
    start_ms: int,
    end_ms: int,
) -> list[dict]:
    result = run_remote_python_json(
        target,
        f"""
from pathlib import Path
import sqlite3

db_path = Path("~/.codex/state_5.sqlite").expanduser()
if not db_path.exists():
    print("[]")
else:
    conn = sqlite3.connect(f"file:{{db_path}}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout = 2000")
        rows = conn.execute({CODEX_THREADS_QUERY!r}, (payload["start_ms"], payload["end_ms"])).fetchall()
        print(json.dumps([dict(row) for row in rows], ensure_ascii=False))
    finally:
        conn.close()
""",
        {"start_ms": start_ms, "end_ms": end_ms},
    )
    return [dict(row) for row in result or []]


def load_remote_claude_sessions(
    target: WorkspaceTarget,
    target_date: date,
    timezone: ZoneInfo,
    workspace_filter: str | None,
    max_chars: int,
    include_subagents: bool,
    warnings: list[str],
) -> list[Session]:
    try:
        paths = find_remote_files(target, "~/.claude/projects", "*.jsonl")
    except RemoteCommandError as exc:
        warnings.append(f"无法读取 {target.display_label} 的 Claude 会话列表: {exc}")
        return []

    filtered_paths = [
        path
        for path in paths
        if include_subagents or "subagents" not in Path(path).parts
    ]
    try:
        contents_by_path = read_remote_texts(target, filtered_paths)
    except RemoteCommandError as exc:
        warnings.append(f"无法批量读取 {target.display_label} 的 Claude transcript: {exc}")
        return []

    sessions: list[Session] = []
    for source_path in filtered_paths:
        details = contents_by_path.get(source_path, {})
        if "error" in details:
            warnings.append(
                f"跳过 {target.display_label} 的 Claude transcript `{source_path}`: {details['error']}"
            )
            continue
        try:
            session = build_claude_session(
                text=details.get("content", ""),
                source_path=source_path,
                location_label=target.display_label,
                target_date=target_date,
                timezone=timezone,
                workspace_filter=workspace_filter,
                max_chars=max_chars,
                required_workspace=target.workspace_path,
            )
        except json.JSONDecodeError as exc:
            warnings.append(f"跳过 {target.display_label} 的 Claude transcript `{source_path}`: {exc}")
            continue
        if session is not None:
            sessions.append(session)

    return sort_sessions(sessions)


def load_remote_codex_sessions(
    target: WorkspaceTarget,
    target_date: date,
    timezone: ZoneInfo,
    workspace_filter: str | None,
    max_chars: int,
    warnings: list[str],
) -> list[Session]:
    start_ms, end_ms = codex_time_range_ms(target_date, timezone)
    try:
        rows = query_remote_codex_thread_rows(target, start_ms, end_ms)
    except RemoteCommandError as exc:
        warnings.append(f"无法读取 {target.display_label} 的 Codex 线程索引: {exc}")
        return []

    relevant_rows = [
        row
        for row in rows
        if matches_session_cwd(str(row.get("cwd") or ""), target.workspace_path, workspace_filter)
    ]
    try:
        contents_by_path = read_remote_texts(
            target,
            [str(row["rollout_path"]) for row in relevant_rows],
        )
    except RemoteCommandError as exc:
        warnings.append(f"无法批量读取 {target.display_label} 的 Codex transcript: {exc}")
        return []

    sessions: list[Session] = []
    for row in relevant_rows:
        rollout_path = str(row["rollout_path"])
        details = contents_by_path.get(rollout_path, {})
        if "error" in details:
            warnings.append(
                f"跳过 {target.display_label} 的 Codex transcript `{rollout_path}`: {details['error']}"
            )
            continue
        try:
            session = build_codex_session(
                text=details.get("content", ""),
                row=row,
                location_label=target.display_label,
                target_date=target_date,
                timezone=timezone,
                workspace_filter=workspace_filter,
                max_chars=max_chars,
                required_workspace=target.workspace_path,
            )
        except json.JSONDecodeError as exc:
            warnings.append(f"跳过 {target.display_label} 的 Codex transcript `{rollout_path}`: {exc}")
            continue
        if session is not None:
            sessions.append(session)

    return sort_sessions(sessions)


def collect_remote_sections(
    config_path: Path,
    target_date: date,
    timezone: ZoneInfo,
    workspace_filter: str | None,
    max_chars: int,
    include_subagents: bool,
    warnings: list[str],
) -> list[RemoteSection]:
    targets = [target for target in parse_workspace_targets(config_path) if target.kind == "ssh"]
    sections: list[RemoteSection] = []
    for target in targets:
        sections.append(
            RemoteSection(
                target=target,
                claude_sessions=load_remote_claude_sessions(
                    target=target,
                    target_date=target_date,
                    timezone=timezone,
                    workspace_filter=workspace_filter,
                    max_chars=max_chars,
                    include_subagents=include_subagents,
                    warnings=warnings,
                ),
                codex_sessions=load_remote_codex_sessions(
                    target=target,
                    target_date=target_date,
                    timezone=timezone,
                    workspace_filter=workspace_filter,
                    max_chars=max_chars,
                    warnings=warnings,
                ),
            )
        )
    return sections


def render_message(message: Message) -> str:
    role_name = "User" if message.role == "user" else "Assistant"
    timestamp = message.timestamp.strftime("%H:%M:%S")
    return f"**{timestamp} {role_name}**\n\n{message.text}\n"


def render_sessions(title: str, sessions: Iterable[Session], heading_level: int, item_level: int) -> str:
    items = list(sessions)
    heading = "#" * heading_level
    item_heading = "#" * item_level
    lines = [f"{heading} {title}", ""]
    if not items:
        lines.append("今天没有找到可导出的会话。")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"共 {len(items)} 个会话。")
    lines.append("")
    for index, session in enumerate(items, start=1):
        lines.append(f"{item_heading} {index}. {session.title}")
        lines.append("")
        lines.append(f"- 会话 ID: `{session.session_id}`")
        lines.append(f"- 工作目录: `{session.cwd or '未知'}`")
        lines.append(
            f"- 时间: `{session.started_at.strftime('%H:%M:%S')} - {session.ended_at.strftime('%H:%M:%S')}`"
        )
        lines.append(f"- 来源文件: `{session.source_path}`")
        lines.append("")
        for message in session.messages:
            lines.append(render_message(message))
        lines.append("")
    return "\n".join(lines)


def render_location_group(
    title: str,
    claude_sessions: list[Session],
    codex_sessions: list[Session],
    heading_level: int,
    tool_heading_level: int,
    item_level: int,
) -> str:
    heading = "#" * heading_level
    lines = [
        f"{heading} {title}",
        "",
        render_sessions("Claude Code", claude_sessions, tool_heading_level, item_level),
        render_sessions("Codex", codex_sessions, tool_heading_level, item_level),
    ]
    return "\n".join(lines).strip()


def render_remote_section(
    remote_enabled: bool,
    remote_sections: list[RemoteSection],
) -> str:
    lines = ["## 远程", ""]
    if not remote_enabled:
        lines.append("未启用 `--include-remote`，未扫描远程会话。")
        lines.append("")
        return "\n".join(lines)

    if not remote_sections:
        lines.append("配置文件中没有找到 `ssh://` 远程工作区。")
        lines.append("")
        return "\n".join(lines)

    for section in remote_sections:
        lines.append(
            render_location_group(
                title=section.target.display_label,
                claude_sessions=section.claude_sessions,
                codex_sessions=section.codex_sessions,
                heading_level=3,
                tool_heading_level=4,
                item_level=5,
            )
        )
        lines.append("")

    return "\n".join(lines).rstrip()


def default_output_path(target_date: date) -> Path:
    folder = Path(f"Report/DailyReport{target_date.isoformat()}")
    return folder / f"ai_chat_history{target_date.isoformat()}.md"


def render_document(
    target_date: date,
    timezone: ZoneInfo,
    local_claude_sessions: list[Session],
    local_codex_sessions: list[Session],
    remote_sections: list[RemoteSection],
    remote_enabled: bool,
) -> str:
    generated_at = datetime.now(timezone).strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        f"# AI 对话记录 {target_date.isoformat()}",
        "",
        f"- 生成时间: `{generated_at}`",
        f"- 时区: `{timezone.key}`",
        "",
        render_location_group(
            title="本地",
            claude_sessions=local_claude_sessions,
            codex_sessions=local_codex_sessions,
            heading_level=2,
            tool_heading_level=3,
            item_level=4,
        ),
        "",
        render_remote_section(remote_enabled=remote_enabled, remote_sections=remote_sections),
    ]
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    args = parse_args()
    timezone = ZoneInfo(args.timezone)
    target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    config_path = Path(args.config).expanduser()
    warnings: list[str] = []

    local_claude_sessions = load_local_claude_sessions(
        target_date=target_date,
        timezone=timezone,
        workspace_filter=args.workspace,
        max_chars=args.max_chars_per_message,
        include_subagents=args.include_subagents,
    )
    local_codex_sessions = load_local_codex_sessions(
        target_date=target_date,
        timezone=timezone,
        workspace_filter=args.workspace,
        max_chars=args.max_chars_per_message,
    )

    remote_sections: list[RemoteSection] = []
    if args.include_remote:
        remote_sections = collect_remote_sections(
            config_path=config_path,
            target_date=target_date,
            timezone=timezone,
            workspace_filter=args.workspace,
            max_chars=args.max_chars_per_message,
            include_subagents=args.include_subagents,
            warnings=warnings,
        )

    output_path = Path(args.output) if args.output else default_output_path(target_date)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    document = render_document(
        target_date=target_date,
        timezone=timezone,
        local_claude_sessions=local_claude_sessions,
        local_codex_sessions=local_codex_sessions,
        remote_sections=remote_sections,
        remote_enabled=args.include_remote,
    )
    output_path.write_text(document, encoding="utf-8")

    remote_claude_count = sum(len(section.claude_sessions) for section in remote_sections)
    remote_codex_count = sum(len(section.codex_sessions) for section in remote_sections)

    print(output_path)
    print(
        json.dumps(
            {
                "date": target_date.isoformat(),
                "timezone": timezone.key,
                "claude_sessions": len(local_claude_sessions),
                "codex_sessions": len(local_codex_sessions),
                "remote_targets": len(remote_sections),
                "remote_claude_sessions": remote_claude_count,
                "remote_codex_sessions": remote_codex_count,
                "remote": [
                    {
                        "target": section.target.display_label,
                        "claude_sessions": len(section.claude_sessions),
                        "codex_sessions": len(section.codex_sessions),
                    }
                    for section in remote_sections
                ],
                "warnings": warnings,
                "output": str(output_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
