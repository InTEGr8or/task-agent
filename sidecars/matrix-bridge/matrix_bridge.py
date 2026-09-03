#!/usr/bin/env python3
"""Task Agent <-> Matrix Bridge Sidecar.

Bridges task-agent store inbox messages (.task-agent/inbox/unread/) with Matrix
rooms (Element, SchildiChat, etc.) using the Matrix Client-Server REST API.

Supports both hosted homeservers (e.g. matrix.org, element.io) and self-hosted
homeservers (Conduit, Synapse, Dendrite, Ergo).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Add task-agent src to sys.path if running from repo
repo_root = Path(__file__).resolve().parent.parent.parent
src_dir = repo_root / "src"
if src_dir.is_dir() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


class MatrixClient:
    """Lightweight Matrix Client using standard library HTTP requests."""

    def __init__(self, homeserver: str, access_token: str):
        self.homeserver = homeserver.rstrip("/")
        self.access_token = access_token
        self.txn_counter = int(time.time() * 1000)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        url = f"{self.homeserver}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        body_bytes = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(
            url, data=body_bytes, headers=self._headers(), method=method
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_text = resp.read().decode("utf-8")
                return json.loads(resp_text) if resp_text else {}
        except urllib.error.HTTPError as e:
            err_text = e.read().decode("utf-8")
            try:
                err_json = json.loads(err_text)
                raise RuntimeError(
                    f"Matrix API Error ({e.code}): {err_json.get('error', err_text)}"
                ) from e
            except Exception:
                raise RuntimeError(f"Matrix HTTP Error ({e.code}): {err_text}") from e

    def get_whoami(self) -> Dict[str, Any]:
        return self._request("GET", "/_matrix/client/v3/account/whoami")

    def login(self, username: str, password: str) -> Dict[str, Any]:
        """Authenticate user with homeserver and update access_token."""
        data = {
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": username},
            "password": password,
        }
        res = self._request("POST", "/_matrix/client/v3/login", data=data)
        new_token = res.get("access_token")
        if new_token:
            self.access_token = new_token
        return res

    def send_message(
        self, room_id: str, text: str, formatted_html: Optional[str] = None
    ) -> str:
        self.txn_counter += 1
        txn_id = f"m{self.txn_counter}"
        path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(room_id)}/send/m.room.message/{txn_id}"

        content: Dict[str, Any] = {
            "msgtype": "m.text",
            "body": text,
        }
        if formatted_html:
            content["format"] = "org.matrix.custom.html"
            content["formatted_body"] = formatted_html

        res = self._request("PUT", path, data=content)
        return str(res.get("event_id", ""))

    def get_space_hierarchy(self, space_id: str) -> List[Dict[str, Any]]:
        """Fetch child rooms inside a Matrix Space."""
        path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(space_id)}/hierarchy"
        try:
            res = self._request("GET", path)
            return list(res.get("rooms") or [])
        except Exception as e:
            print(f"[Warning] Could not fetch Space hierarchy for {space_id}: {e}")
            return []

    def sync(
        self,
        since: Optional[str] = None,
        timeout_ms: int = 30000,
    ) -> Dict[str, Any]:
        params = {"timeout": str(timeout_ms)}
        if since:
            params["since"] = since
        return self._request(
            "GET",
            "/_matrix/client/v3/sync",
            params=params,
            timeout=timeout_ms / 1000.0 + 10.0,
        )

    def create_room(
        self,
        name: str,
        is_space: bool = False,
        topic: str = "",
        invite_users: Optional[List[str]] = None,
    ) -> str:
        """Create a Matrix Space or unencrypted room and return room_id."""
        data: Dict[str, Any] = {
            "name": name,
            "preset": "public_chat" if not is_space else "private_chat",
        }
        if topic:
            data["topic"] = topic
        if is_space:
            data["creation_content"] = {"type": "m.space"}
        if invite_users:
            data["invite"] = invite_users

        res = self._request("POST", "/_matrix/client/v3/createRoom", data=data)
        return str(res.get("room_id", ""))

    def link_child_room(
        self, space_id: str, room_id: str, via_servers: Optional[List[str]] = None
    ) -> None:
        """Link a child room inside a parent Matrix Space."""
        if not via_servers:
            via_servers = ["matrix.org", "matrix-client.matrix.org"]
        path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(space_id)}/state/m.space.child/{urllib.parse.quote(room_id)}"
        self._request("PUT", path, data={"via": via_servers})

    def invite_user(self, room_id: str, user_id: str) -> None:
        """Invite a user to a room."""
        path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(room_id)}/invite"
        try:
            self._request("POST", path, data={"user_id": user_id})
            print(f"[Matrix Bot] Invited '{user_id}' to room '{room_id}'")
        except Exception as e:
            print(f"[Warning] Failed inviting '{user_id}' to '{room_id}': {e}")


def parse_matrix_uri(input_str: str) -> str:
    """Extract canonical Matrix Room or Space ID from raw string or matrix.to link."""
    clean = input_str.strip()
    if "matrix.to" in clean:
        if "#/" in clean:
            clean = clean.split("#/", 1)[1]
        elif "#" in clean:
            clean = clean.split("#", 1)[1]
        clean = clean.lstrip("/").split("?")[0]
    return clean


def markdown_to_html(text: str) -> str:
    """Basic markdown formatting to HTML for Matrix client rendering."""
    lines = []
    for line in text.splitlines():
        # Code formatting
        if line.startswith("# "):
            lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("- "):
            lines.append(f"<li>{line[2:]}</li>")
        else:
            lines.append(f"<p>{line}</p>")
    return "".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Task Agent <-> Matrix Bridge Sidecar")
    parser.add_argument(
        "--homeserver",
        default=os.environ.get("MATRIX_HOMESERVER", "https://matrix-client.matrix.org"),
        help="Matrix homeserver URL (default: https://matrix-client.matrix.org)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("MATRIX_ACCESS_TOKEN", ""),
        help="Matrix Bot Access Token (or MATRIX_ACCESS_TOKEN env var)",
    )
    parser.add_argument(
        "--room",
        default=os.environ.get("MATRIX_ROOM_ID", ""),
        help="Matrix Room ID (e.g. !roomid:matrix.org)",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("TA_STORE_PATH", str(Path.cwd())),
        help="Path to task-agent store root or repo",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds (default: 1.0)",
    )
    return parser.parse_args()


def write_inbox_message(
    store_path: Path,
    from_moniker: str,
    body: str,
    kind: str = "comment",
    thread: Optional[str] = None,
    task: Optional[str] = None,
) -> str:
    from taskagent.inbox import send_message

    msg = send_message(
        target_store=store_path,
        from_moniker=from_moniker,
        body=body,
        kind=kind,
        thread=thread,
        task=task,
    )
    return msg.id


def resolve_secret(val: str) -> str:
    """Resolve secret references dynamically without leaking to logs.

    Supports:
    - 1Password CLI: op://vault/item/field
    - Linux System Keyring: secret-tool://service/username
    - Password Store: pass://folder/entry
    - KeePassXC CLI: keepassxc://entry_name
    """
    if not val:
        return ""
    val = val.strip()
    import subprocess

    if val.startswith("op://"):
        cmds = [
            ["op", "read", val],
            ["op.exe", "read", val],
            ["cmd.exe", "/c", "op", "read", val],
        ]
        for cmd in cmds:
            try:
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10,
                )
                out = res.stdout.strip().replace("\r", "")
                if out:
                    return out
            except Exception:
                continue
        print(
            f"[Error] Failed resolving 1Password secret '{val}' via op / op.exe / cmd.exe."
        )
        sys.exit(1)

    if val.startswith("secret-tool://"):
        # secret-tool://service/username
        parts = val[14:].split("/", 1)
        service = parts[0]
        user = parts[1] if len(parts) > 1 else "default"
        try:
            res = subprocess.run(
                ["secret-tool", "lookup", "service", service, "username", user],
                capture_output=True,
                text=True,
                check=True,
            )
            return res.stdout.strip()
        except Exception as e:
            print(f"[Error] Failed resolving system keyring secret '{val}': {e}")
            sys.exit(1)

    if val.startswith("pass://"):
        path_name = val[7:]
        try:
            res = subprocess.run(
                ["pass", "show", path_name],
                capture_output=True,
                text=True,
                check=True,
            )
            return res.stdout.splitlines()[0].strip()
        except Exception as e:
            print(f"[Error] Failed resolving pass secret '{val}': {e}")
            sys.exit(1)

    return val


def main() -> None:
    args = parse_args()

    repo_path = Path(args.repo).resolve()
    # Resolve store root if inside a project repo
    docs_tasks = repo_path / "docs" / "tasks"
    store_path = docs_tasks if docs_tasks.is_dir() else repo_path

    # Read room ID from store.json if omitted
    room_id = parse_matrix_uri(args.room) if args.room else ""
    store_json = store_path / ".task-agent" / "store.json"
    if not room_id and store_json.is_file():
        try:
            meta = json.loads(store_json.read_text(encoding="utf-8"))
            room_id = parse_matrix_uri(meta.get("matrix_room_id") or "")
        except Exception:
            pass

    if not room_id:
        from taskagent.store_registry import get_global_matrix_space

        g_space = get_global_matrix_space()
        if g_space:
            room_id = parse_matrix_uri(g_space)
            print(f"[Config] Loaded global machine Matrix Space link: {g_space}")

    # Read token from args, env, or ~/.config/task-agent/matrix.json
    raw_token = args.token or os.environ.get("MATRIX_ACCESS_TOKEN", "")
    if not raw_token:
        cfg_file = Path.home() / ".config" / "task-agent" / "matrix.json"
        if not cfg_file.is_file():
            cfg_file = Path.home() / ".local" / "share" / "task-agent" / "matrix.json"
        if cfg_file.is_file():
            try:
                cfg_data = json.loads(cfg_file.read_text(encoding="utf-8"))
                raw_token = cfg_data.get("matrix_access_token") or ""
            except Exception:
                pass

    token = resolve_secret(raw_token)

    if not token:
        print("[Error] Matrix access token is required.")
        print(
            "Provide via --token, MATRIX_ACCESS_TOKEN env var, or store 'matrix_access_token' in ~/.config/task-agent/matrix.json."
        )
        sys.exit(1)

    if not room_id:
        print("[Error] Matrix room or space ID is required.")
        print(
            "Provide via --room, MATRIX_ROOM_ID env var, or 'ta store matrix set <room_id_or_matrix_to_link>'."
        )
        sys.exit(1)

    client = MatrixClient(args.homeserver, token)

    # Check if target room_id is a Space and auto-discover child rooms
    child_rooms = client.get_space_hierarchy(room_id)
    target_room_id = room_id
    if child_rooms:
        from taskagent.inbox import moniker_for_store

        store_moniker = moniker_for_store(store_path) or store_path.name
        # Match child room by name or alias
        matched = None
        for r in child_rooms:
            r_name = str(r.get("name") or "").lower()
            r_alias = str(r.get("canonical_alias") or "").lower()
            if (
                store_moniker.lower() in r_name
                or store_moniker.lower() in r_alias
                or store_path.name.lower() in r_name
            ):
                matched = r.get("room_id")
                print(
                    f"[Space Discovery] Matched repo store '{store_moniker}' to child room '{r.get('name')}' ({matched})"
                )
                break
        if matched:
            target_room_id = matched
        else:
            try:
                space_id = room_id
                print(
                    f"[Space Provisioning] Auto-creating unencrypted child room '{store_moniker}' inside Space {space_id}..."
                )
                new_room_id = client.create_room(
                    name=store_moniker,
                    topic=f"Task Agent chat room for {store_moniker}",
                    invite_users=["@integratot:matrix.org"],
                )
                if new_room_id:
                    client.link_child_room(space_id, new_room_id)
                    client.invite_user(new_room_id, "@integratot:matrix.org")
                    target_room_id = new_room_id
                    print(
                        f"[Space Provisioning] ✓ Created room '{store_moniker}' ({new_room_id}) and linked to Space!"
                    )
            except Exception as e:
                print(f"[Space Provisioning Error] Failed creating room: {e}")
                first_child = child_rooms[0].get("room_id")
                if first_child:
                    target_room_id = first_child
                    print(
                        f"[Space Discovery] Defaulting to first child room in Space: {target_room_id}"
                    )

    try:
        whoami = client.get_whoami()
        bot_user_id = whoami.get("user_id", "bot")
    except Exception as e:
        if "401" in str(e):
            print(
                "[Authentication] Access token returned 401. Attempting login for @task-agent:matrix.org..."
            )
            try:
                pwd = resolve_secret("op://Private/6pcab3dt5sml3sslfh6xffqit4/password")
                if pwd:
                    login_res = client.login("task-agent", pwd)
                    bot_user_id = login_res.get("user_id", "@task-agent:matrix.org")
                    print(
                        f"[Authentication] ✓ Successfully authenticated as {bot_user_id}!"
                    )
                else:
                    raise RuntimeError("No password reference found.")
            except Exception as login_err:
                print(
                    f"[Error] Failed connecting to Matrix homeserver: {e} (Login fallback: {login_err})"
                )
                sys.exit(1)
        else:
            print(f"[Error] Failed connecting to Matrix homeserver: {e}")
            sys.exit(1)

    print("====================================================")
    print("  Task Agent <-> Matrix Bridge Sidecar Running")
    print(f"  Homeserver  : {args.homeserver}")
    print(f"  Bot User ID : {bot_user_id}")
    print(f"  Target Room : {target_room_id}")
    print(f"  Store Root  : {store_path}")
    print("====================================================")
    room_id = target_room_id
    print("====================================================")

    from taskagent.inbox import list_unread

    seen_inbox_ids: Set[str] = set()

    # Mark existing unread messages so we only broadcast NEW incoming messages
    for msg in list_unread(store_path):
        seen_inbox_ids.add(msg.id)

    sync_token: Optional[str] = None
    # Perform initial sync to get the latest next_batch token
    try:
        init_sync = client.sync(timeout_ms=0)
        sync_token = init_sync.get("next_batch")
    except Exception as e:
        print(f"[Warning] Initial sync failed: {e}")

    last_check = 0.0

    while True:
        now = time.time()
        # 1. Outbound: Check task-agent inbox for new unread messages
        if now - last_check >= args.interval:
            last_check = now
            try:
                unread = list_unread(store_path)
                for msg in unread:
                    if msg.id not in seen_inbox_ids:
                        seen_inbox_ids.add(msg.id)
                        print(
                            f"[Outbound -> Matrix] [{msg.id}] {msg.kind} from {msg.from_moniker}"
                        )

                        badge = f"📬 **[{msg.kind.upper()}]** from `{msg.from_moniker}`"
                        if msg.linked_slug:
                            badge += f" (task: `{msg.linked_slug}`)"

                        plain_text = f"{badge}\n\n{msg.body}"
                        html_text = f"<p>📬 <b>[{msg.kind.upper()}]</b> from <code>{msg.from_moniker}</code>"
                        if msg.linked_slug:
                            html_text += f" (task: <code>{msg.linked_slug}</code>)"
                        html_text += f"</p><br>{markdown_to_html(msg.body)}"

                        try:
                            client.send_message(
                                room_id, plain_text, formatted_html=html_text
                            )
                        except Exception as err:
                            print(f"[Error] Failed posting to Matrix room: {err}")
            except Exception as e:
                print(f"[Error] Outbound inbox read error: {e}")

        # 2. Inbound: Listen for Matrix room messages
        try:
            sync_res = client.sync(since=sync_token, timeout_ms=5000)
            sync_token = sync_res.get("next_batch")

            rooms_data = sync_res.get("rooms", {}).get("join", {}).get(room_id, {})
            events = rooms_data.get("timeline", {}).get("events", [])

            for ev in events:
                if ev.get("type") == "m.room.message":
                    sender = ev.get("sender", "")
                    content = ev.get("content", {})
                    msgtype = content.get("msgtype")
                    if msgtype == "m.text":
                        body_text = content.get("body", "").strip()
                        # Ignore loopback messages posted by the bridge daemon itself
                        if (
                            body_text.startswith("🤖")
                            or body_text.startswith("📬")
                            or body_text.startswith("[Outbound]")
                        ):
                            continue

                        if body_text:
                            print(
                                f"[Inbound <- Matrix] Message from {sender}: {body_text[:60]}..."
                            )
                            try:
                                delivered_id = write_inbox_message(
                                    store_path=store_path,
                                    from_moniker=sender,
                                    body=body_text,
                                    kind="comment",
                                )
                                seen_inbox_ids.add(delivered_id)
                            except Exception as err:
                                print(f"[Error] Failed delivering to inbox: {err}")
        except Exception:
            # Sync timeout or transient network error
            time.sleep(1.0)


if __name__ == "__main__":
    main()
