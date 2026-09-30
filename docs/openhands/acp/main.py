#!/usr/bin/env python3
"""ACP runner for the alert-bot-demo automation: runs inside an OpenHands automation run.

Replaces the prompt preset's ``main.py``. The preset builds an OpenHands ``Agent`` around the
agent server's LLM settings, which ignores the ACP agent profile and ran on the settings' default
model. This runner delegates the whole task to the ACP agent profile instead: Claude Code as a
subprocess spawned by the Agent Server, built through the SDK's ``ACPAgentSettings.create_agent()``.

Local (self-hosted) mode only: ``AGENT_SERVER_URL`` must be set. The script runs on the agent
server host, so the checkout it makes is the checkout the ACP subprocess works in.

Environment set by the automation service:
  AGENT_SERVER_URL, OH_SESSION_API_KEYS_0 (legacy SESSION_API_KEY), WORKSPACE_BASE (run-isolated
  directory), AUTOMATION_EVENT_PAYLOAD (JSON with the webhook event), AUTOMATION_AGENT_PROFILE_ID
  (the automation's profile; the active profile when unset), AUTOMATION_RUN_ID, AUTOMATION_USER_ID,
  AUTOMATION_PHASE_URL, AUTOMATION_CALLBACK_API_KEY, AUTOMATION_CALLBACK_URL (read by the SDK
  workspace on exit), AUTOMATION_CONVERSATION_ID (continue_conversation only).

GitLab is reached over SSH with the host's key (``~/.ssh/id_ed25519_gitlab`` by default): the clone
is made with it and the key is written into the clone's ``core.sshCommand``, so the agent's own
``git fetch`` / ``git push`` need nothing else. Agent-server secrets (Settings -> Secrets) reach the
subprocess environment through ``agent_context.secrets``: OPENHANDS_CALLBACK_TOKEN and, when the
host has no Claude subscription login, ANTHROPIC_API_KEY.
"""

import inspect
import json
import os
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_REF = os.environ.get("ALERT_BOT_REPO_REF", "develop")
REPO_DIR_NAME = "alert-bot-demo"
REPOS: tuple[tuple[str, str], ...] = (
    (REPO_DIR_NAME, os.environ.get("ALERT_BOT_REPO_URL", "git@gitlab.example.com:group/alert-bot-demo.git")),
)
REPO_URL = REPOS[0][1]
# The agent writes the callback body here; the runner delivers it once the run has ended, with the
# usage the agent cannot see (model, tokens, cost).
CALLBACK_FILE_NAME = "callback.json"
CALLBACK_RETRY_DELAYS = (0, 5, 15)
SSH_KEY = os.path.expanduser(os.environ.get("ALERT_BOT_SSH_KEY", "~/.ssh/id_ed25519_gitlab"))
# Secrets that exist for the automation plumbing and have no business in the agent's shell.
SECRETS_KEPT_FROM_AGENT = set(
    filter(None, os.environ.get("ACP_EXCLUDE_SECRETS", "OPENHANDS_AUTOMATION_API_KEY").split(","))
)

agent_server_url = os.environ.get("AGENT_SERVER_URL", "").rstrip("/")
session_key = os.environ.get("OH_SESSION_API_KEYS_0") or os.environ.get("SESSION_API_KEY", "")
automation_user_id = os.environ.get("AUTOMATION_USER_ID") or None
workspace_base = os.path.expanduser(os.environ.get("WORKSPACE_BASE", "/workspace"))

print("=== ENV VARS ===")
print(f"  AGENT_SERVER_URL: {'OK' if agent_server_url else 'MISSING'}")
print(f"  OH_SESSION_API_KEYS_0: {'OK' if session_key else 'NONE (may fail auth)'}")
print(f"  WORKSPACE_BASE: {workspace_base}")
print(f"  AUTOMATION_AGENT_PROFILE_ID: {os.environ.get('AUTOMATION_AGENT_PROFILE_ID') or 'active profile'}")
print(f"  AUTOMATION_RUN_ID: {os.environ.get('AUTOMATION_RUN_ID') or 'NONE'}")
if not agent_server_url:
    print("FAIL: AGENT_SERVER_URL not set; this runner supports the local backend only", file=sys.stderr)
    sys.exit(1)
if not os.path.isabs(workspace_base) or not os.path.isdir(workspace_base):
    print(f"FAIL: WORKSPACE_BASE must be an existing absolute directory, got {workspace_base}", file=sys.stderr)
    sys.exit(1)

# --- Live phase reporting (best-effort, never fatal); same shape as the presets -----------------
AUTOMATION_PHASE_URL = os.environ.get("AUTOMATION_PHASE_URL", "")
_PHASE_TOKEN = os.environ.get("AUTOMATION_CALLBACK_API_KEY") or os.environ.get("OPENHANDS_API_KEY") or ""
PHASE_POST_INTERVAL_SECONDS = 4.0


def report_phase(message: str) -> None:
    """POST a short progress phase to the automation service. Never raises."""
    if not AUTOMATION_PHASE_URL or not _PHASE_TOKEN or not message:
        return
    try:
        import httpx

        httpx.post(
            AUTOMATION_PHASE_URL,
            json={"phase": message[:200]},
            headers={"Authorization": f"Bearer {_PHASE_TOKEN}"},
            timeout=5.0,
        )
    except Exception:
        pass


def _redact_phase(text: str) -> str:
    try:
        from openhands.sdk.utils.redact import redact_api_key_literals, redact_text_secrets

        return redact_api_key_literals(redact_text_secrets(text))
    except Exception:
        return ""


_live_phase: dict = {"pending": None, "posted": None, "stop": False}


def _phase_poster() -> None:
    while not _live_phase["stop"]:
        time.sleep(PHASE_POST_INTERVAL_SECONDS)
        message = _live_phase["pending"]
        if message and message != _live_phase["posted"]:
            _live_phase["posted"] = message
            report_phase(message)


# SDK imports before the workspace context so import errors surface plainly.
from openhands.sdk import ACPAgentSettings, AgentContext, Conversation, RemoteConversation
from openhands.sdk.workspace.remote import RemoteWorkspace


def _conversation_supports_user_id() -> bool:
    try:
        return "user_id" in inspect.signature(Conversation.__new__).parameters
    except (TypeError, ValueError):
        return False


def _secret_value(workspace, names: tuple[str, ...]) -> str | None:
    """A secret's plaintext from the agent server, by the first name that exists; env as fallback."""
    for name in names:
        try:
            value = workspace._get_secret_value(name)
        except Exception:
            value = None
        if value:
            return value
        if os.environ.get(name):
            return os.environ[name]
    return None


def _collect_metrics(conversation, profile: dict, last_event_time: dict) -> dict:
    """Model, tokens and cost of this run as the ACP server reported them; zeros when unknown."""
    summary: dict = {
        "model": profile.get("acp_model") or profile.get("acp_server") or "unknown",
        "tokens_used": 0,
        "cost_usd": 0.0,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
        },
    }
    try:
        while time.time() - last_event_time["ts"] < 2.0:  # let the event stream settle
            time.sleep(0.1)
        metrics = conversation.conversation_stats.get_combined_metrics()
    except Exception as error:
        print(f"  WARNING: metrics unavailable (non-fatal): {error}")
        return summary
    usage = metrics.accumulated_token_usage
    if usage is not None:
        summary["usage"] = {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
        }
        summary["tokens_used"] = (
            usage.prompt_tokens + usage.completion_tokens + usage.cache_read_tokens + usage.cache_write_tokens
        )
    summary["cost_usd"] = round(float(metrics.accumulated_cost or 0.0), 6)
    reported = [u.model for u in (metrics.token_usages or []) if u.model and u.model != "acp-managed"]
    if reported:
        summary["model"] = reported[-1]
    return summary


def _deliver_callback(workspace, event_context, metrics: dict, conversation_id, run_error) -> None:
    """POST the agent's callback body plus the run's usage to the request's callback_url, once."""
    payload = ((event_context or {}).get("event") or {}).get("payload") or {}
    url = payload.get("callback_url")
    if not url:
        print("  no callback_url in the event payload; nothing to deliver")
        return
    request_id = payload.get("request_id") or payload.get("id")
    callback_file = Path(workspace_base) / CALLBACK_FILE_NAME
    body = None
    if callback_file.is_file():
        try:
            body = json.loads(callback_file.read_text(encoding="utf-8"))
        except Exception as error:
            print(f"  WARNING: {callback_file} is not valid JSON: {error}")
    error_text = f"{type(run_error).__name__}: {run_error}" if run_error is not None else None
    if not isinstance(body, dict):
        body = {
            "request_id": request_id,
            "status": "failed",
            "summary": "The run ended without a callback body from the agent.",
            "verdict": None,
            "checker_code": None,
            "brands": payload.get("brands") or [],
            "reviews": [],
            "mr_url": None,
            "apply_after_deploy": False,
            "missing": [],
            "questions": [],
            "notes": [],
            "error": error_text or "the agent wrote no callback.json",
        }
    elif error_text and not body.get("error"):
        body["error"] = error_text
    body.setdefault("request_id", request_id)
    body.update(
        {
            "model": metrics["model"],
            "tokens_used": metrics["tokens_used"],
            "cost_usd": metrics["cost_usd"],
            "usage": metrics["usage"],
            "openhands": {
                "run_id": os.environ.get("AUTOMATION_RUN_ID"),
                "conversation_id": str(conversation_id) if conversation_id else None,
            },
        }
    )
    if "{request_id}" in url or "{token}" in url:
        token = _secret_value(workspace, ("OPENHANDS_CALLBACK_TOKEN",)) or ""
        url = url.replace("{request_id}", str(request_id or "")).replace("{token}", token)
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    for attempt, delay in enumerate(CALLBACK_RETRY_DELAYS, 1):
        if delay:
            time.sleep(delay)
        try:
            request = urllib.request.Request(
                url, data=data, method="POST", headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                print(
                    f"  callback delivered: HTTP {response.status} (status={body.get('status')}, "
                    f"{metrics['tokens_used']} tokens, {metrics['cost_usd']} USD, model={metrics['model']})"
                )
                return
        except urllib.error.HTTPError as error:
            print(f"  callback attempt {attempt}: HTTP {error.code} {error.read()[:200]!r}")
            if error.code < 500:
                return  # a 4xx does not improve with retries
        except Exception as error:
            print(f"  callback attempt {attempt}: {error}")
    print("  WARNING: callback not delivered after retries")


def _ssh_command() -> str | None:
    """The ssh invocation that pins the GitLab key, or None when the host's default config must do."""
    if os.path.isfile(SSH_KEY):
        return f"ssh -i {shlex.quote(SSH_KEY)} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
    print(f"  WARNING: {SSH_KEY} not found; relying on the host's ~/.ssh/config for {REPO_URL}")
    return None


def _clone_repo(url: str, dest: Path) -> None:
    """Clone one repository over SSH into ``dest`` on this host (idempotent on a re-run)."""
    if (dest / ".git").is_dir():
        print(f"  already cloned at {dest}")
        return
    ssh_command = _ssh_command()
    env = dict(os.environ)
    if ssh_command:
        env["GIT_SSH_COMMAND"] = ssh_command
    try:
        subprocess.run(
            ["git", "clone", "--branch", REPO_REF, url, str(dest)],
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"git clone of {url} failed: {error.stderr or ''}") from error
    if ssh_command:
        # The agent's later fetch/push run inside this clone; pin the key there rather than in env.
        subprocess.run(["git", "-C", str(dest), "config", "core.sshCommand", ssh_command], check=True)
    print(f"  cloned {url} ({REPO_REF}) into {dest}")


def _resolve_acp_profile(workspace) -> dict:
    """The ACP agent profile this run uses, as the agent server stores it."""
    listing = workspace.client.get("/api/agent-profiles")
    listing.raise_for_status()
    data = listing.json()
    wanted = os.environ.get("AUTOMATION_AGENT_PROFILE_ID") or data.get("active_agent_profile_id")
    name = next((p.get("name") for p in data.get("profiles", []) if p.get("id") == wanted), None)
    if name is None:
        known = [(p.get("id"), p.get("name")) for p in data.get("profiles", [])]
        raise RuntimeError(f"agent profile {wanted!r} not found on the agent server; known: {known}")
    detail = workspace.client.get(f"/api/agent-profiles/{name}")
    detail.raise_for_status()
    profile = detail.json().get("profile") or {}
    if profile.get("agent_kind") != "acp":
        raise RuntimeError(f"agent profile {name!r} is {profile.get('agent_kind')!r}, this runner needs an ACP profile")
    return profile


def _as_argv(value) -> list[str]:
    if not value:
        return []
    return shlex.split(value) if isinstance(value, str) else list(value)


def _build_agent(profile: dict, mcp_config, agent_context: AgentContext):
    settings = ACPAgentSettings(
        acp_server=profile.get("acp_server") or "claude-code",
        acp_command=_as_argv(profile.get("acp_command")),
        acp_args=_as_argv(profile.get("acp_args")),
        acp_model=profile.get("acp_model"),
        acp_session_mode=profile.get("acp_session_mode"),
        acp_prompt_timeout=float(profile.get("acp_prompt_timeout") or 1800.0),
        acp_startup_timeout=float(profile.get("acp_startup_timeout") or 90.0),
        mcp_config=mcp_config or {},
        agent_context=agent_context,
    )
    return settings.create_agent()


def _build_conversation_title(event_context) -> str | None:
    if not isinstance(event_context, dict):
        return None
    name = event_context.get("automation_name")
    if not isinstance(name, str) or not name.strip():
        return None
    name = " ".join(name.split())
    request_id = None
    event = event_context.get("event")
    if isinstance(event, dict):
        payload = event.get("payload")
        if isinstance(payload, dict):
            request_id = payload.get("request_id") or payload.get("id")
    context = request_id or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"{name} — {context}"[:200]


print("\n=== SDK WORKSPACE ===")
print(f"  RemoteWorkspace at {agent_server_url}, working_dir {workspace_base}")
workspace_ctx = RemoteWorkspace(
    host=agent_server_url,
    api_key=session_key if session_key else None,
    working_dir=workspace_base,
)

# Enter the workspace context EARLY: any exception from here on triggers the completion callback.
with workspace_ctx as workspace:
    report_phase("Setting up workspace")

    event_context = None
    if event_payload_json := os.environ.get("AUTOMATION_EVENT_PAYLOAD"):
        try:
            event_context = json.loads(event_payload_json)
        except json.JSONDecodeError as error:
            print(f"ERROR: Failed to parse AUTOMATION_EVENT_PAYLOAD: {error}", file=sys.stderr)

    print("\n=== CLONE REPOS ===")
    report_phase("Cloning repositories")
    repo_dir = Path(workspace_base) / REPO_DIR_NAME
    for dir_name, url in REPOS:
        _clone_repo(url, Path(workspace_base) / dir_name)

    print("\n=== LOAD SKILLS ===")
    skills = []
    try:
        loaded_skills, loaded_context = workspace.load_skills_from_agent_server(project_dirs=[str(repo_dir)])
        skills = list(getattr(loaded_context, "skills", None) or [])
        print(f"  loaded {len(loaded_skills)} skills, {len(skills)} forwarded to the ACP prompt context")
    except Exception as error:
        print(f"  skill loading failed (non-fatal): {error}")

    print("\n=== SECRETS ===")
    secrets = {}
    try:
        secrets = {k: v for k, v in workspace.get_secrets().items() if k not in SECRETS_KEPT_FROM_AGENT}
        print(f"  forwarded to the subprocess: {sorted(secrets) or '(none)'}")
    except Exception as error:
        print(f"  get_secrets() failed (ok if no secrets): {error}")

    print("\n=== MCP ===")
    mcp_config = {}
    try:
        mcp_config = workspace.get_mcp_config() or {}
        print(f"  servers forwarded to the ACP session: {list(mcp_config) or '(none)'}")
    except Exception as error:
        print(f"  get_mcp_config() failed (ok if no MCP): {error}")

    print("\n=== AGENT (ACP) ===")
    report_phase("Starting the ACP agent")
    profile = _resolve_acp_profile(workspace)
    print(f"  profile: {profile.get('name')} server={profile.get('acp_server')} model={profile.get('acp_model')}")
    try:
        agent = _build_agent(profile, mcp_config, AgentContext(skills=skills, secrets=secrets or None))
    except NotImplementedError as error:
        # Some skill fields are not ACP-compatible on this SDK; the subprocess still needs the secrets.
        print(f"  skills dropped from the prompt context: {error}")
        agent = _build_agent(profile, mcp_config, AgentContext(secrets=secrets or None))
    print(f"  command: {' '.join(agent.acp_command)}")

    print("\n=== PROMPT ===")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, "prompt.txt"), encoding="utf-8") as handle:
        user_prompt = handle.read()

    context_sections = [
        f"""## Workspace

The alert-bot-demo repository is cloned at `{repo_dir}` (branch `{REPO_REF}`). Work inside that
directory; every path in the task is relative to it. Its remote `origin` is SSH (`{REPO_URL}`)
and the clone's `core.sshCommand` already carries the deploy key, so `git fetch` and `git push`
need no further credentials.
Write the callback body to `{Path(workspace_base) / CALLBACK_FILE_NAME}`: the runner delivers it once
your run has ended and adds the usage fields."""
    ]
    if event_context and "event" in event_context:
        event_json = json.dumps(event_context["event"], indent=2, ensure_ascii=False)
        context_sections.append(f"""## Event Payload

This automation was triggered by a webhook event:

```json
{event_json}
```""")
    if event_context and event_context.get("follow_up_turns"):
        follow_ups = "\n\n".join(str(turn) for turn in event_context["follow_up_turns"])
        context_sections.append(f"""## Follow-up messages

More activity arrived on the same subject while this run was queued:

{follow_ups}""")
    user_prompt = "\n\n".join(context_sections) + f"\n\n## Task\n\n{user_prompt}"

    print("\n=== CONVERSATION ===")
    received_events: list = []
    last_event_time = {"ts": time.time()}

    def event_callback(event) -> None:
        received_events.append(event)
        last_event_time["ts"] = time.time()
        if type(event).__name__ == "ActionEvent":
            summary = getattr(event, "summary", None)
            if isinstance(summary, str) and summary.strip():
                redacted = _redact_phase(" ".join(summary.split()))
                if redacted:
                    _live_phase["pending"] = redacted[:200]

    default_tags = workspace.default_conversation_tags or {}
    conversation_tags: dict[str, str] = {}
    if not any(default_tags.get(key) for key in ("automationtrigger", "automationid", "automationrunid")):
        conversation_tags["automationtrigger"] = "automation"
    automation_run_id = os.environ.get("AUTOMATION_RUN_ID")
    if automation_run_id and not default_tags.get("automationrunid"):
        conversation_tags["automationrunid"] = automation_run_id

    conversation_kwargs = {
        "agent": agent,
        "workspace": workspace,
        "callbacks": [event_callback],
        "delete_on_close": False,
        "tags": conversation_tags or None,
    }
    if automation_user_id and _conversation_supports_user_id():
        conversation_kwargs["user_id"] = automation_user_id
    automation_conversation_id = os.environ.get("AUTOMATION_CONVERSATION_ID")
    if automation_conversation_id:
        conversation_kwargs["conversation_id"] = uuid.UUID(automation_conversation_id)
    conversation = Conversation(**conversation_kwargs)
    assert isinstance(conversation, RemoteConversation)
    print(f"  conversation created: {conversation.id}")

    conversation_title = _build_conversation_title(event_context)
    if conversation_title:
        try:
            response = workspace.client.patch(
                f"/api/conversations/{conversation.id}", json={"title": conversation_title}
            )
            response.raise_for_status()
            print(f"  title: {conversation_title}")
        except Exception as error:
            print(f"  set title failed (non-fatal): {error}")

    report_phase("Agent is working on the task")
    threading.Thread(target=_phase_poster, name="phase-poster", daemon=True).start()

    run_error: BaseException | None = None
    try:
        print(f"  sending prompt: {user_prompt[:80]!r}...")
        conversation.send_message(user_prompt)
        conversation.run()
    except BaseException as error:  # the callback below must still go out
        run_error = error
        print(f"  ERROR: the agent run failed: {type(error).__name__}: {error}")
    finally:
        _live_phase["stop"] = True

    metrics = _collect_metrics(conversation, profile, last_event_time)
    print(f"  usage: {metrics}")
    print(f"  events received: {len(received_events)}")
    report_phase("Delivering the callback")
    try:
        _deliver_callback(workspace, event_context, metrics, conversation.id, run_error)
    except Exception as error:
        print(f"  WARNING: callback delivery raised (non-fatal): {error}")
    try:
        conversation.close()
    except Exception as error:
        print(f"  WARNING: conversation.close() failed (non-fatal): {error}")
    if run_error is not None:
        raise run_error

    print("  conversation completed successfully")
    print("\n=== RESULT ===")
    print("ALL_OK")
