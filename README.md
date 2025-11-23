# AI Agent Framework

A flexible Python-based agent framework for automated tasks. Currently includes the **ai-deploy** agent for synchronizing files between different locations.

## Features

- **Modular Agent Architecture**: Easy to extend with new agent types
- **Multiple Connection Types**: Support for Windows shares and SSH/SFTP
- **Flexible Authentication**: Password or SSH key-based authentication
- **Intelligent File Comparison**: Detects new, modified, and deleted files
- **Flexible Ignore Patterns**: Exclude files, folders, or extensions
- **Dry Run Mode**: Preview changes before applying them
- **Detailed Logging**: Track all operations and errors

## Project Structure

```
aiagent/
├── agents/              # Agent implementations
│   └── ai_deploy.py    # File deployment/sync agent
├── core/               # Core framework classes
│   ├── agent_base.py   # Base class for all agents
│   └── config_loader.py # Configuration loading utilities
├── handlers/           # Connection handlers
│   ├── windows_share_handler.py  # Windows network share handler
│   └── ssh_handler.py            # SSH/SFTP handler
├── config/             # Configuration examples
│   ├── ai-deploy-example-windows.json
│   ├── ai-deploy-example-ssh-password.json
│   ├── ai-deploy-example-ssh-key.json
│   └── ai-deploy-example-dry-run.json
├── main.py            # Main entry point
├── requirements.txt   # Python dependencies
└── README.md         # This file
```

## Installation

1. Clone or download this repository
2. Install dependencies:

```bash
pip install -r requirements.txt
```

## AI-Deploy Agent

The **ai-deploy** agent synchronizes files from a source location to a destination location, making the destination match the source.

### Features

- Compare source and destination files
- Copy new files
- Update modified files (based on size and modification time)
- Delete extra files from destination (optional)
- Ignore specific files, folders, or extensions
- Dry run mode for testing

### Configuration

Create a JSON configuration file with the following structure:

```json
{
  "agent_name": "ai-deploy",
  "description": "Description of this deployment",
  "source": {
    "type": "windows_share|ssh",
    ...
  },
  "destination": {
    "type": "windows_share|ssh",
    ...
  },
  "ignore": {
    "files": ["*.log", "*.tmp"],
    "folders": ["__pycache__", ".git"],
    "extensions": [".pyc", ".bak"]
  },
  "options": {
    "dry_run": false,
    "delete_extra_files": true
  }
}
```

#### Windows Share Configuration

```json
{
  "type": "windows_share",
  "path": "\\\\server\\share\\folder",
  "username": "DOMAIN\\username",  // Optional
  "password": "password"           // Optional
}
```

Or for local paths:

```json
{
  "type": "windows_share",
  "path": "C:\\path\\to\\folder"
}
```

#### SSH Configuration

With password authentication:

```json
{
  "type": "ssh",
  "host": "server.example.com",
  "port": 22,
  "username": "user",
  "password": "password",
  "path": "/remote/path"
}
```

With key-based authentication:

```json
{
  "type": "ssh",
  "host": "server.example.com",
  "port": 22,
  "username": "user",
  "key_file": "/path/to/private/key",
  "path": "/remote/path"
}
```

#### Ignore Configuration

```json
{
  "ignore": {
    "files": [
      "*.log",
      "*.tmp",
      ".env"
    ],
    "folders": [
      "__pycache__",
      ".git",
      "node_modules",
      ".venv"
    ],
    "extensions": [
      ".pyc",
      ".pyo",
      ".bak"
    ]
  }
}
```

#### Options

- `dry_run`: If `true`, shows what would be done without making changes
- `delete_extra_files`: If `true`, deletes files from destination that don't exist in source

### Usage

Run the agent with a configuration file:

```bash
python main.py config/ai-deploy-example-windows.json
```

Or explicitly specify the agent type:

```bash
python main.py --agent-type ai-deploy config/my-config.json
```

### Example Scenarios

#### Deploy from local folder to remote server

```bash
python main.py config/ai-deploy-example-ssh-password.json
```

#### Sync between two Windows shares

```bash
python main.py config/ai-deploy-example-windows.json
```

#### Test deployment without changes (dry run)

```bash
python main.py config/ai-deploy-example-dry-run.json
```

### Example Configuration Files

Several example configurations are provided in the `config/` directory:

- `ai-deploy-example-windows.json` - Windows share to Windows share
- `ai-deploy-example-ssh-password.json` - Local to SSH with password
- `ai-deploy-example-ssh-key.json` - SSH to SSH with key authentication
- `ai-deploy-example-dry-run.json` - Dry run example

## Creating New Agents

To create a new agent:

1. Create a new class in `agents/` that inherits from `AgentBase`
2. Implement `_validate_config()` and `run()` methods
3. Add the agent to `agents/__init__.py`
4. Update `main.py` to support the new agent type

Example:

```python
from core.agent_base import AgentBase

class MyNewAgent(AgentBase):
    def _validate_config(self, config):
        # Validate your configuration
        pass

    def run(self):
        # Implement your agent logic
        pass
```

## Requirements

- Python 3.7+
- paramiko (for SSH connections)

## Security Notes

- Configuration files may contain sensitive credentials
- Use key-based authentication when possible
- Store configuration files securely
- Consider using environment variables for credentials
- Be cautious with the `delete_extra_files` option

## License

This project is provided as-is for educational and commercial use.

## Contributing

Feel free to extend this framework with new agents and handlers!
