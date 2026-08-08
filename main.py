"""Main entry point for aiagent application."""
import sys
import json
import argparse
import subprocess
from pathlib import Path

from agents.ai_deploy import AiDeployAgent
from agents.ai_download import AiDownloadAgent
from agents.ai_upload import AiUploadAgent


def _post_deploy_subpath(entry_config, primary_source):
    """
    The source subdirectory a chained config ships, relative to the primary
    deploy's source root — e.g. "scripts/marketplace" for the bot configs when
    the primary deploys the whole repo.

    Compared as raw strings so unresolved templates ({{APPLICATION_NAME}}) match
    without needing the agent's substitution. Returns None when the two sources
    don't share a prefix, which the caller treats as "can't tell, run it".
    """
    try:
        entry_source = (entry_config.get('source') or {}).get('path')
        if not entry_source or not primary_source:
            return None
        if not entry_source.startswith(primary_source):
            return None
        return entry_source[len(primary_source):].replace('\\', '/').strip('/')
    except Exception:
        return None


def _run_post_deploy(post_deploy, base_config_path, changed_paths=None, primary_source=None):
    """
    Run additional deployments listed in the config's 'post_deploy' array.

    Each entry is a path to another config file, which is executed as a
    separate `python main.py <config>` subprocess after the primary
    deployment completes. Running each as its own process keeps deployments
    isolated (independent cache, connections, and error handling).

    Paths are resolved relative to the primary config file's directory so
    configs can reference siblings by name (e.g. "deploy-marketplace-to-cbusbot1.json").

    Args:
        post_deploy: List of config file paths to run after the primary deploy
        base_config_path: Path object for the primary config (used to resolve relatives)

    Returns:
        True if all post-deploy runs succeeded, False if any failed
    """
    config_dir = base_config_path.parent
    all_succeeded = True

    print("\n" + "=" * 60)
    print(f"POST-DEPLOY: running {len(post_deploy)} additional deployment(s)")
    print("=" * 60)

    for entry in post_deploy:
        # Resolve relative paths against the primary config's directory
        entry_path = Path(entry)
        if not entry_path.is_absolute():
            entry_path = config_dir / entry_path

        if not entry_path.exists():
            print(f"\n>>> Running post-deploy: {entry_path}")
            print(f"Error: post_deploy config not found: {entry_path}")
            all_succeeded = False
            continue

        # Skip a chained deploy whose source subtree this run didn't touch.
        # changed_paths is None when the primary agent can't report (non-deploy
        # agents), and an empty set when it genuinely changed nothing — only the
        # latter is safe to act on, so the None case still runs everything.
        if changed_paths is not None:
            try:
                entry_config = json.loads(entry_path.read_text(encoding='utf-8'))
            except Exception:
                entry_config = {}
            subpath = _post_deploy_subpath(entry_config, primary_source)
            if subpath and not any(p.startswith(subpath + '/') or p == subpath
                                   for p in changed_paths):
                print(f"\n>>> Skipping post-deploy (no changes under {subpath}): {entry_path.name}")
                continue

        print(f"\n>>> Running post-deploy: {entry_path}")

        result = subprocess.run([sys.executable, __file__, str(entry_path)])
        if result.returncode != 0:
            print(f"Error: post-deploy failed (exit {result.returncode}): {entry_path}")
            all_succeeded = False
        else:
            print(f">>> Completed post-deploy: {entry_path}")

    print("\n" + "=" * 60)
    if all_succeeded:
        print("POST-DEPLOY: all additional deployments completed successfully")
    else:
        print("POST-DEPLOY: one or more additional deployments failed")
    print("=" * 60)

    return all_succeeded


def main():
    """Main function to run agents."""
    parser = argparse.ArgumentParser(
        description='AI Agent Framework - Run configured agents'
    )
    parser.add_argument(
        'config',
        type=str,
        help='Path to the agent configuration JSON file'
    )
    parser.add_argument(
        '--agent-type',
        type=str,
        default=None,
        choices=['ai-deploy', 'ai-download', 'ai-upload'],
        help='Type of agent to run (auto-detected from config agent_name if not specified)'
    )

    args = parser.parse_args()

    # Validate config file exists
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Configuration file not found: {args.config}")
        sys.exit(1)

    # Load raw config (used for agent-type auto-detection and post_deploy chaining)
    with open(config_path, 'r') as f:
        raw_config = json.load(f)

    # Auto-detect agent type from config if not specified
    agent_type = args.agent_type
    if agent_type is None:
        agent_type = raw_config.get('agent_name', 'ai-deploy')

    # Create and run the appropriate agent
    try:
        if agent_type == 'ai-deploy':
            agent = AiDeployAgent(str(config_path))
        elif agent_type == 'ai-download':
            agent = AiDownloadAgent(str(config_path))
        elif agent_type == 'ai-upload':
            agent = AiUploadAgent(str(config_path))
        else:
            print(f"Error: Unknown agent type: {agent_type}")
            sys.exit(1)

        # Run the agent
        agent.run()

    except Exception as e:
        print(f"Error running agent: {e}")
        sys.exit(1)

    # Run any chained deployments listed in 'post_deploy' (after primary success)
    post_deploy = raw_config.get('post_deploy', [])
    if post_deploy:
        changed_paths = getattr(agent, 'changed_paths', None)
        primary_source = (raw_config.get('source') or {}).get('path')
        if not _run_post_deploy(post_deploy, config_path, changed_paths, primary_source):
            sys.exit(1)


if __name__ == '__main__':
    main()
