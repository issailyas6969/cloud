"""
Lightweight webhook server — listens for GitHub push events and
kicks off the LangGraph deploy workflow automatically.

Run with:  python webhook_server.py
"""

import hashlib
import hmac
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from workflow.deploy_graph import deploy_graph


# ─────────────────────────────────────────
# Config (override via environment variables)
# ─────────────────────────────────────────
WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "changeme")
LISTEN_PORT    = int(os.environ.get("WEBHOOK_PORT", 8000))
DEPLOY_BRANCH  = os.environ.get("DEPLOY_BRANCH", "main")   # only deploy this branch

# AWS EC2 settings
EC2_HOST       = os.environ.get("EC2_HOST", "")            # e.g. 1.2.3.4
EC2_USER       = os.environ.get("EC2_USER", "ubuntu")
EC2_KEY_PATH   = os.environ.get("EC2_KEY_PATH", "~/.ssh/my-key.pem")
APP_DIR        = os.environ.get("APP_DIR", "/home/ubuntu/app")
RESTART_CMD    = os.environ.get("RESTART_CMD", "sudo systemctl restart myapp")

# Where to clone / pull the repo locally
LOCAL_REPO_DIR = os.environ.get("LOCAL_REPO_DIR", "/tmp/deploy_repo")
REPO_CLONE_URL = os.environ.get("REPO_CLONE_URL", "")      # e.g. https://github.com/you/repo.git


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────
def verify_signature(payload: bytes, sig_header: str) -> bool:
    """Verify GitHub HMAC-SHA256 webhook signature."""
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig_header)


def clone_or_pull(repo_url: str, local_dir: str, branch: str):
    """Clone repo if not present, otherwise pull latest."""
    if os.path.isdir(os.path.join(local_dir, ".git")):
        subprocess.run(["git", "fetch", "origin"], cwd=local_dir, check=True)
        subprocess.run(["git", "checkout", branch], cwd=local_dir, check=True)
        subprocess.run(["git", "reset", "--hard", f"origin/{branch}"], cwd=local_dir, check=True)
    else:
        os.makedirs(local_dir, exist_ok=True)
        subprocess.run(["git", "clone", "--branch", branch, repo_url, local_dir], check=True)


def run_deployment(payload: dict):
    """Pull latest code and run the LangGraph deploy workflow."""
    ref    = payload.get("ref", "")
    branch = ref.replace("refs/heads/", "")
    sha    = payload.get("after", "unknown")

    print(f"\n📨 Push received — branch={branch} sha={sha[:8]}")

    if branch != DEPLOY_BRANCH:
        print(f"⏭  Skipping: not the deploy branch ({DEPLOY_BRANCH})")
        return

    # Pull latest code
    if REPO_CLONE_URL:
        print("⬇️  Cloning / pulling latest code...")
        clone_or_pull(REPO_CLONE_URL, LOCAL_REPO_DIR, branch)
    else:
        print("⚠️  REPO_CLONE_URL not set — using existing LOCAL_REPO_DIR")

    # Build initial state and run graph
    initial_state = {
        "repo_path":    LOCAL_REPO_DIR,
        "branch":       branch,
        "commit_sha":   sha,
        "artifact_path": "",
        "ec2_host":     EC2_HOST,
        "ec2_user":     EC2_USER,
        "ec2_key_path": os.path.expanduser(EC2_KEY_PATH),
        "app_dir":      APP_DIR,
        "restart_cmd":  RESTART_CMD,
        "status":       "success",
        "logs":         [],
    }

    deploy_graph.invoke(initial_state)


# ─────────────────────────────────────────
# HTTP handler
# ─────────────────────────────────────────
class WebhookHandler(BaseHTTPRequestHandler):

    def do_POST(self):
        if self.path != "/webhook":
            self.send_response(404)
            self.end_headers()
            return

        length  = int(self.headers.get("Content-Length", 0))
        payload = self.rfile.read(length)
        sig     = self.headers.get("X-Hub-Signature-256", "")

        if not verify_signature(payload, sig):
            print("⛔  Invalid signature — request rejected.")
            self.send_response(403)
            self.end_headers()
            return

        event = self.headers.get("X-GitHub-Event", "")
        if event != "push":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ignored")
            return

        self.send_response(202)
        self.end_headers()
        self.wfile.write(b"accepted")

        # Run deployment in background thread so we return 202 quickly
        data = json.loads(payload)
        thread = threading.Thread(target=run_deployment, args=(data,), daemon=True)
        thread.start()

    def log_message(self, fmt, *args):  # suppress default access logs
        pass


# ─────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────
if __name__ == "__main__":
    print(f"🌐 Webhook server listening on port {LISTEN_PORT}")
    print(f"   Deploy branch : {DEPLOY_BRANCH}")
    print(f"   EC2 host      : {EC2_HOST or '(not set)'}")
    print(f"   App dir       : {APP_DIR}")
    print(f"   Restart cmd   : {RESTART_CMD}")
    print(f"\n   POST your GitHub webhook to: http://<this-server>:{LISTEN_PORT}/webhook\n")

    server = HTTPServer(("0.0.0.0", LISTEN_PORT), WebhookHandler)
    server.serve_forever()
