"""Main entry point for aiagent application."""
import sys
import argparse
from pathlib import Path

from agents.ai_deploy import AiDeployAgent
from agents.ai_download import AiDownloadAgent
from agents.ai_upload import AiUploadAgent


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

    # Auto-detect agent type from config if not specified
    agent_type = args.agent_type
    if agent_type is None:
        import json
        with open(config_path, 'r') as f:
            raw_config = json.load(f)
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


if __name__ == '__main__':
    main()
