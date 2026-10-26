"""Talk to supervisord over its XML-RPC unix socket (no Flask dependency)."""
from __future__ import annotations

import xmlrpc.client
from datetime import datetime, timezone

from supervisor.xmlrpc import SupervisorTransport

from mods.config import Config

GLOBAL_ACTIONS = {"update", "reread"}
PROGRAM_ACTIONS = {"start", "stop", "restart"}


def proxy() -> xmlrpc.client.ServerProxy:
    transport = SupervisorTransport(None, None, f"unix://{Config.SUPERVISOR_SOCKET}")
    return xmlrpc.client.ServerProxy("http://localhost", transport=transport)


def _fault_message(exc: xmlrpc.client.Fault) -> str:
    return exc.faultString or str(exc)


def reread_update() -> dict:
    """Make supervisord notice added/removed program configs (like ``supervisorctl update``)."""
    try:
        p = proxy()
        added, changed, removed = p.supervisor.reloadConfig()[0]
        for name in removed:
            try:
                p.supervisor.stopProcessGroup(name)
            except xmlrpc.client.Fault:
                pass
            p.supervisor.removeProcessGroup(name)
        for name in changed:
            try:
                p.supervisor.stopProcessGroup(name)
            except xmlrpc.client.Fault:
                pass
            p.supervisor.removeProcessGroup(name)
            p.supervisor.addProcessGroup(name)
        for name in added:
            p.supervisor.addProcessGroup(name)
        return {"status": "success", "added": added, "changed": changed, "removed": removed}
    except xmlrpc.client.Fault as exc:
        return {"status": "error", "message": _fault_message(exc)}
    except OSError as exc:
        return {"status": "error", "message": f"supervisord unreachable: {exc}"}


def control(action: str, program: str) -> dict:
    """start / stop / restart a program."""
    if action not in PROGRAM_ACTIONS:
        return {"status": "error", "message": f"invalid action {action!r}"}
    try:
        p = proxy()
        if action in ("stop", "restart"):
            try:
                p.supervisor.stopProcess(program, True)
            except xmlrpc.client.Fault as exc:
                if "NOT_RUNNING" not in exc.faultString:
                    raise
        if action in ("start", "restart"):
            try:
                p.supervisor.startProcess(program, True)
            except xmlrpc.client.Fault as exc:
                if "ALREADY_STARTED" not in exc.faultString:
                    raise
        return {"status": "success", "action": action, "program": program}
    except xmlrpc.client.Fault as exc:
        return {"status": "error", "action": action, "program": program, "message": _fault_message(exc)}
    except OSError as exc:
        return {"status": "error", "action": action, "program": program,
                "message": f"supervisord unreachable: {exc}"}


def process_info(program: str) -> dict:
    try:
        return proxy().supervisor.getProcessInfo(program)
    except xmlrpc.client.Fault as exc:
        return {"statename": "UNKNOWN", "error": _fault_message(exc)}
    except OSError as exc:
        return {"statename": "UNKNOWN", "error": str(exc)}


def all_process_info() -> dict[str, dict]:
    try:
        return {p["name"]: p for p in proxy().supervisor.getAllProcessInfo()}
    except (xmlrpc.client.Fault, OSError):
        return {}


def uptime_text(info: dict) -> str:
    if info.get("statename") != "RUNNING":
        return "Not running"
    start = datetime.fromtimestamp(info["start"], tz=timezone.utc)
    now = datetime.fromtimestamp(info["now"], tz=timezone.utc)
    secs = int((now - start).total_seconds())
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)
