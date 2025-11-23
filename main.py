"""Main entry point for aiagent application."""
import sys
import argparse
from pathlib import Path

from agents.ai_deploy import AiDeployAgent


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
        default='ai-deploy',
        choices=['ai-deploy'],
        help='Type of agent to run (default: ai-deploy)'
    )

    args = parser.parse_args()

    # Validate config file exists
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Configuration file not found: {args.config}")
        sys.exit(1)

    # Create and run the appropriate agent
    try:
        if args.agent_type == 'ai-deploy':
            agent = AiDeployAgent(str(config_path))
        else:
            print(f"Error: Unknown agent type: {args.agent_type}")
            sys.exit(1)

        # Run the agent
        agent.run()

    except Exception as e:
        print(f"Error running agent: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
