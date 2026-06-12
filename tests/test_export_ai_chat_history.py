from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "export_ai_chat_history.py"
SPEC = importlib.util.spec_from_file_location("export_ai_chat_history", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def make_claude_transcript(cwd: str, user_text: str = "hello", assistant_text: str = "world") -> str:
    return "\n".join(
        [
            json.dumps(
                {
                    "type": "user",
                    "timestamp": "2026-06-12T01:00:00Z",
                    "cwd": cwd,
                    "sessionId": "claude-session",
                    "message": {
                        "content": [
                            {
                                "type": "input_text",
                                "text": user_text,
                            }
                        ]
                    },
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-06-12T01:01:00Z",
                    "cwd": cwd,
                    "sessionId": "claude-session",
                    "message": {
                        "content": [
                            {
                                "type": "output_text",
                                "text": assistant_text,
                            }
                        ]
                    },
                },
                ensure_ascii=False,
            ),
        ]
    )


def make_codex_rollout(user_text: str = "plan", assistant_text: str = "done") -> str:
    return "\n".join(
        [
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-06-12T02:00:00Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": user_text,
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-06-12T02:01:00Z",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": assistant_text,
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            ),
        ]
    )


class ExportAiChatHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.timezone = ZoneInfo("Asia/Shanghai")
        self.target_date = date(2026, 6, 12)

    def test_parse_workspace_targets_supports_local_and_remote_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.md"
            config_path.write_text(
                "\n".join(
                    [
                        "# Config",
                        "- 这里的说明 bullet 不应被当成工作区",
                        "",
                        "## Git Workspaces",
                        "- /Users/fish/docs/daily-report",
                        "- ssh://xyx@192.168.0.16:22/home/xyx/project",
                        "- ssh://xyx@192.168.0.16:22/home/xyx/project",
                    ]
                ),
                encoding="utf-8",
            )

            targets = MODULE.parse_workspace_targets(config_path)

        self.assertEqual(2, len(targets))
        self.assertEqual("local", targets[0].kind)
        self.assertEqual("/Users/fish/docs/daily-report", targets[0].workspace_path)
        self.assertEqual("ssh", targets[1].kind)
        self.assertEqual("xyx", targets[1].user)
        self.assertEqual("192.168.0.16", targets[1].host)
        self.assertEqual(22, targets[1].port)
        self.assertEqual("/home/xyx/project", targets[1].workspace_path)

    def test_parse_workspace_targets_rejects_invalid_ssh_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.md"
            config_path.write_text(
                "\n".join(
                    [
                        "# Config",
                        "- ssh:///home/xyx/project",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as exc_info:
                MODULE.parse_workspace_targets(config_path)

        self.assertIn("without a host", str(exc_info.exception))

    def test_load_remote_codex_sessions_filters_workspace_and_parses_messages(self) -> None:
        target = MODULE.WorkspaceTarget(
            kind="ssh",
            user="xyx",
            host="192.168.0.16",
            port=22,
            workspace_path="/home/xyx/project",
        )
        rows = [
            {
                "id": "match",
                "title": "Remote match",
                "cwd": "/home/xyx/project",
                "rollout_path": "/home/xyx/.codex/sessions/match.jsonl",
            },
            {
                "id": "skip",
                "title": "Other repo",
                "cwd": "/home/xyx/other",
                "rollout_path": "/home/xyx/.codex/sessions/skip.jsonl",
            },
        ]
        warnings: list[str] = []

        with (
            patch.object(MODULE, "query_remote_codex_thread_rows", return_value=rows),
            patch.object(
                MODULE,
                "read_remote_texts",
                return_value={
                    "/home/xyx/.codex/sessions/match.jsonl": {
                        "content": make_codex_rollout(user_text="match", assistant_text="ok")
                    },
                    "/home/xyx/.codex/sessions/skip.jsonl": {
                        "content": make_codex_rollout(user_text="skip", assistant_text="ok")
                    },
                },
            ),
        ):
            sessions = MODULE.load_remote_codex_sessions(
                target=target,
                target_date=self.target_date,
                timezone=self.timezone,
                workspace_filter=None,
                max_chars=4000,
                warnings=warnings,
            )

        self.assertEqual(1, len(sessions))
        self.assertEqual("Remote match", sessions[0].title)
        self.assertEqual("/home/xyx/.codex/sessions/match.jsonl", sessions[0].source_path)
        self.assertEqual(target.display_label, sessions[0].location_label)
        self.assertEqual([], warnings)

    def test_load_remote_claude_sessions_collects_warning_and_continues(self) -> None:
        target = MODULE.WorkspaceTarget(
            kind="ssh",
            user="xyx",
            host="192.168.0.16",
            port=22,
            workspace_path="/home/xyx/project",
        )
        warnings: list[str] = []

        with (
            patch.object(
                MODULE,
                "find_remote_files",
                return_value=[
                    "/home/xyx/.claude/projects/broken.jsonl",
                    "/home/xyx/.claude/projects/good.jsonl",
                ],
            ),
            patch.object(
                MODULE,
                "read_remote_texts",
                return_value={
                    "/home/xyx/.claude/projects/broken.jsonl": {"error": "ssh timeout"},
                    "/home/xyx/.claude/projects/good.jsonl": {
                        "content": make_claude_transcript(
                            "/home/xyx/project",
                            user_text="task",
                            assistant_text="result",
                        )
                    },
                },
            ),
        ):
            sessions = MODULE.load_remote_claude_sessions(
                target=target,
                target_date=self.target_date,
                timezone=self.timezone,
                workspace_filter=None,
                max_chars=4000,
                include_subagents=False,
                warnings=warnings,
            )

        self.assertEqual(1, len(sessions))
        self.assertEqual("task", sessions[0].title)
        self.assertEqual(1, len(warnings))
        self.assertIn("broken.jsonl", warnings[0])

    def test_render_document_includes_local_and_remote_sections(self) -> None:
        session = MODULE.Session(
            tool="Claude Code",
            session_id="local-1",
            title="Local session",
            cwd="/Users/fish/docs/daily-report",
            source_path="/tmp/local.jsonl",
            started_at=datetime(2026, 6, 12, 9, 0, tzinfo=self.timezone),
            ended_at=datetime(2026, 6, 12, 9, 5, tzinfo=self.timezone),
            messages=[MODULE.Message(role="user", timestamp=datetime(2026, 6, 12, 9, 0, tzinfo=self.timezone), text="hi")],
        )
        remote_target = MODULE.WorkspaceTarget(
            kind="ssh",
            user="xyx",
            host="192.168.0.16",
            port=22,
            workspace_path="/home/xyx/project",
        )
        remote_section = MODULE.RemoteSection(
            target=remote_target,
            claude_sessions=[session],
            codex_sessions=[],
        )

        document = MODULE.render_document(
            target_date=self.target_date,
            timezone=self.timezone,
            local_claude_sessions=[session],
            local_codex_sessions=[],
            remote_sections=[remote_section],
            remote_enabled=True,
        )

        self.assertIn("## 本地", document)
        self.assertIn("### Claude Code", document)
        self.assertIn("## 远程", document)
        self.assertIn(f"### {remote_target.display_label}", document)
        self.assertIn("#### Claude Code", document)
        self.assertIn("#### Codex", document)


if __name__ == "__main__":
    unittest.main()
