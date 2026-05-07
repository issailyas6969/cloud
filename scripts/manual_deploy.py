"""
Manual deploy trigger — useful for testing without a real git push.

Usage:
    python scripts/manual_deploy.py --repo /path/to/repo --branch main --sha abc123def
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from workflow.deploy_graph import deploy_graph


def main():
    parser = argparse.ArgumentParser(description="Manually trigger EC2 deployment")
    parser.add_argument("--repo",    required=True,  help="Local path to repo")
    parser.add_argument("--branch",  default="main", help="Branch name (default: main)")
    parser.add_argument("--sha",     default="manual", help="Commit SHA label")
    parser.add_argument("--host",    default=os.environ.get("EC2_HOST", ""),      help="EC2 IP/hostname")
    parser.add_argument("--user",    default=os.environ.get("EC2_USER", "ubuntu"), help="SSH user")
    parser.add_argument("--key",     default=os.environ.get("EC2_KEY_PATH", ""),  help="Path to .pem key")
    parser.add_argument("--app-dir", default=os.environ.get("APP_DIR", "/home/ubuntu/app"))
    parser.add_argument("--restart", default=os.environ.get("RESTART_CMD", "sudo systemctl restart myapp"))
    args = parser.parse_args()

    state = {
        "repo_path":    args.repo,
        "branch":       args.branch,
        "commit_sha":   args.sha,
        "artifact_path": "",
        "ec2_host":     args.host,
        "ec2_user":     args.user,
        "ec2_key_path": os.path.expanduser(args.key),
        "app_dir":      args.app_dir,
        "restart_cmd":  args.restart,
        "status":       "success",
        "logs":         [],
    }

    result = deploy_graph.invoke(state)
    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
