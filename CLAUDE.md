# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

### Install dependencies
```bash
pip install -r requirements.txt
```

### Verify installation
```bash
python test_installation.py
```

### Run an agent
```bash
python main.py config/ai-deploy-example-windows.json
```

Or specify agent type explicitly:
```bash
python main.py --agent-type ai-deploy config/your-config.json
```

### Test with dry-run
Set `"dry_run": true` in the config file's `options` section before running to preview changes without modifying files.

## Architecture Overview

### Three-Layer Design Pattern

The framework uses a three-layer architecture that separates concerns:

1. **Agent Layer** (`agents/`): High-level business logic for specific tasks
   - Agents inherit from `AgentBase` abstract class
   - Must implement `_validate_config()` and `run()` methods
   - Orchestrate handlers to accomplish tasks
   - JSON-driven configuration

2. **Handler Layer** (`handlers/`): Connection and file operation abstraction
   - Provide unified interface for different connection types (Windows shares, SSH)
   - Handle authentication and connection lifecycle
   - Abstract file operations: `list_files()`, `read_file()`, `write_file()`, `delete_file()`
   - Each handler maintains its own connection state

3. **Core Layer** (`core/`): Framework foundation
   - `AgentBase`: Template Method pattern for agent lifecycle
   - `ConfigLoader`: JSON configuration utilities
   - Handles logging setup and config validation flow

### Key Architectural Patterns

**Handler Abstraction**: Both `WindowsShareHandler` and `SSHHandler` implement the same interface (`connect()`, `disconnect()`, `list_files()`, `read_file()`, `write_file()`, `delete_file()`, `create_directory()`, `delete_directory()`). This allows agents to work with any handler without knowing implementation details.

**Configuration-Driven**: All agents are configured via JSON. The base class loads the config and calls abstract `_validate_config()` before execution. Agents use `_create_handler()` pattern to instantiate appropriate handlers based on config `type` field.

**File Comparison Algorithm** (ai-deploy): The agent supports both full and incremental deployments:
1. **Full Deployment** (`clean_install=true` or `ignore_cache=true`):
   - Lists all files from both source and destination
   - Filters source files through ignore patterns
   - Categorizes files into new/modified/deleted by comparing metadata (size, mtime)
   - Executes synchronization in three phases: copy new, update modified, delete extra
2. **Incremental Deployment** (`clean_install=false`, default):
   - **Skips destination file listing** for much faster deployment (especially over SSH)
   - Uses deployment cache to track previously deployed files
   - Only copies files that have changed since last deployment
   - Only executes database scripts modified since last deployment
   - Cache file is created in same directory as config file (e.g., `.deploy_cache_config-name.json`)

**Ignore Pattern System**: Three-tier filtering (files, folders, extensions) using `fnmatch` for wildcards. Patterns are checked in `_should_ignore()` method before including files in sync operations.

**Cache System**: The agent maintains a deployment cache (`.deploy_cache_*.json`) that tracks:
- File metadata (mtime, size) for each deployed file
- Last deployment timestamp
- Database script execution timestamps
- File mapping metadata
- Web tenant metadata
This enables fast incremental deployments by skipping unchanged files and database scripts. When `clean_install=false` and cache exists, the agent skips the slow destination file listing step entirely and trusts the cache.

**Migration Mode** (`migration_only=true`): When enabled, only executes scripts from `migration_path` directories:
- Skips `setup_path`, `tables_path`, `procedures_path`, `data_path` in both main and tenant database scripts
- Skips `tenant_data_scripts` entirely
- Cannot be used with `clean_install=true` (throws validation error)
- Useful for running schema changes on existing databases without full re-deployment

## Creating New Agents

1. Create class in `agents/` inheriting from `AgentBase`:
```python
from core.agent_base import AgentBase

class MyAgent(AgentBase):
    def _validate_config(self, config):
        # Check required fields
        if 'required_field' not in config:
            raise ValueError("Missing required_field")

    def run(self):
        # Your agent logic here
        self.logger.info("Running agent...")
```

2. Register in `agents/__init__.py`:
```python
from .my_agent import MyAgent
__all__ = [..., 'MyAgent']
```

3. Add to `main.py` CLI argument choices and instantiation logic.

## Creating New Handlers

Handlers must implement the standard interface:
- `connect()` -> bool
- `disconnect()` -> None
- `list_files(recursive=True)` -> List[Dict]
- `read_file(relative_path)` -> bytes
- `write_file(relative_path, content)` -> None
- `delete_file(relative_path)` -> None
- `create_directory(relative_path)` -> None
- `delete_directory(relative_path)` -> None

File info dictionaries returned by `list_files()` must include:
```python
{
    'path': str,          # Relative path
    'full_path': str,     # Absolute path
    'size': int,          # File size in bytes
    'modified_time': float,  # Unix timestamp
    'is_directory': bool
}
```

## Configuration Structure

See `CONFIG_SCHEMA.md` for complete reference. Key points:

- `source` and `destination` objects have `type` field ("windows_share" or "ssh")
- Windows shares: `path` (UNC or local), optional `username`/`password`
- SSH: `host`, `username`, `path`, either `password` or `key_file`, optional `port`
- `ignore` patterns use Unix shell-style wildcards via `fnmatch`
- `options.dry_run` previews without modifications
- `options.delete_extra_files` controls deletion of files not in source

### Application Name Template Variable

The optional `application_name` field at the root level enables template variable replacement throughout configuration and deployed files:

**Where {{APPLICATION_NAME}} is replaced:**
- All configuration string values (paths, database names, usernames, etc.)
- SQL files during database deployment
- Available as {{APPLICATION_NAME}} in database template variables

**Example:**
```json
{
  "agent_name": "ai-deploy",
  "application_name": "agencyos",
  "source": {
    "path": "C:\\git\\{{APPLICATION_NAME}}"
  },
  "database": {
    "main_database_scripts": {
      "db_name": "{{APPLICATION_NAME}}",
      "db_username": "{{APPLICATION_NAME}}_user"
    }
  }
}
```

The above config becomes:
- Source path: `C:\git\agencyos`
- Database name: `agencyos`
- Database username: `agencyos_user`

In SQL files, you can use:
```sql
CREATE DATABASE IF NOT EXISTS {{APPLICATION_NAME}};
USE {{APPLICATION_NAME}};
```

### File Mappings (Optional)

The ai-deploy agent supports file mappings to copy files with different names on the destination. This is useful for environment-specific configuration files like `.env.production` → `.env`.

**Configuration:**
```json
{
  "file_mappings": [
    {
      "source": "C:\\git\\agencyos\\.env.production",
      "destination": ".env"
    },
    {
      "source": "config.prod.json",
      "destination": "config.json"
    }
  ]
}
```

**Key Points:**
- File mappings are **optional** - omit the section if not needed
- `source` can be an absolute path (e.g., `C:\\path\\to\\file`) or relative to source root
- `destination` is relative path on the destination server
- File mappings are processed **after** regular file sync but **before** database deployment
- Files copied via mappings bypass ignore patterns
- Useful for deploying environment-specific configs (`.env.production` → `.env`)

### Permissions Script (Optional)

The ai-deploy agent can execute a permissions script on the destination server after deployment. This is useful for setting correct file/folder permissions and ownership.

**Configuration:**
```json
{
  "set_permissions_script": "set-permissions.sh"
}
```

**Execution Order:**
1. Sync files from source to destination
2. Process file mappings
3. Deploy database (if enabled)
4. **Execute permissions script** (if configured)

**How it works:**
- Path is relative to destination root (e.g., `/var/www/agencyos/set-permissions.sh`)
- Agent runs `sudo chmod +x` on the script
- Agent executes the script with `sudo`
- Script output is logged in real-time
- **Only works with SSH destinations** (not Windows shares)

**Key Points:**
- Permissions script is **optional** - omit if not needed
- Requires `sudo` access on destination server
- User must have passwordless sudo or provide password when prompted
- Useful for setting ownership (`chown`), permissions (`chmod`), and restarting services
- Script should be included in your source files or deployed separately
- Dry-run mode shows what would be executed without running it

**Example Script:**
```bash
#!/bin/bash
BASE_PATH="/var/www/agencyos"

# Set ownership
sudo chown -R andy:www-data $BASE_PATH

# Set permissions on PHP files
sudo find $BASE_PATH/api -type f -name "*.php" -exec chmod 640 {} \;

# Set permissions on public files
sudo find $BASE_PATH/web/public -type f -exec chmod 644 {} \;

# Restart Apache
sudo systemctl restart apache2
```

### Database Deployment (Optional)

The ai-deploy agent supports optional database deployment via SSH tunnel. Database scripts are read from the **local source machine** and executed on the remote MySQL server.

**Configuration Example (Main Database Only):**
```json
{
  "database": {
    "enabled": true,
    "ssh_host": "192.168.1.4",
    "ssh_port": 22,
    "ssh_username": "andy",
    "ssh_password": "password",
    "db_host": "127.0.0.1",
    "db_port": 3306,
    "admin_username": "root",
    "admin_password": "mysql_password",
    "main_database_scripts": {
      "db_name": "myapp_db",
      "db_username": "myapp_user",
      "db_password": "dbpassword",
      "setup_path": "C:\\path\\to\\setup",
      "tables_path": "C:\\path\\to\\tables",
      "procedures_path": "C:\\path\\to\\procs",
      "data_path": "C:\\path\\to\\data"
    }
  }
}
```

**Configuration Example (Multi-Tenant Databases):**
```json
{
  "database": {
    "enabled": true,
    "ssh_host": "192.168.1.4",
    "ssh_port": 22,
    "ssh_username": "andy",
    "ssh_password": "password",
    "db_host": "127.0.0.1",
    "db_port": 3306,
    "admin_username": "root",
    "admin_password": "mysql_password",
    "main_database_scripts": {
      "db_name": "agencyos",
      "db_username": "agencyos_user",
      "db_password": "dbpassword",
      "setup_path": "C:\\git\\agencyos\\database\\main\\setup",
      "tables_path": "C:\\git\\agencyos\\database\\main\\tables",
      "procedures_path": "C:\\git\\agencyos\\database\\main\\procedures"
    },
    "tenant-database": {
      "enabled": true,
      "db_name": "agencyos_{{WEBID}}",
      "db_username": "agencyos_user",
      "db_password": "dbpassword",
      "setup_path": "C:\\git\\agencyos\\database\\tenant\\setup",
      "tables_path": "C:\\git\\agencyos\\database\\tenant\\tables",
      "procedures_path": "C:\\git\\agencyos\\database\\tenant\\procedures"
    },
    "tenant_data_scripts": {
      "enabled": true,
      "data_path": "C:\\git\\agencyos\\database\\tenant\\data"
    }
  }
}
```

**Database Configuration Sections:**

1. **main_database_scripts**: Scripts for the main database (executed once)
   - `db_name`: Main database name
   - `db_username`: Database username
   - `db_password`: Database password
   - `setup_path`: Database setup scripts (create database, users, grants)
   - `tables_path`: Table creation scripts
   - `procedures_path`: Stored procedure scripts
   - `data_path`: Data scripts

2. **tenant-database**: Scripts executed **per tenant** (uses {{WEBID}} template variable)
   - `db_name`: Tenant database name pattern (e.g., `agencyos_{{WEBID}}`)
   - `setup_path`: Tenant database setup scripts (executed per tenant)
   - `tables_path`: Table creation scripts (executed per tenant)
   - `procedures_path`: Stored procedure scripts (executed per tenant)
   - `data_path`: Data scripts (executed per tenant)

3. **tenant_data_scripts**: Scripts executed **once** after all tenant databases are created
   - `data_path`: SQL files using explicit `USE database_name;` statements
   - Each file targets specific databases and is NOT looped per tenant

**Key Difference:**
- **tenant-database**: Scripts loop through all tenants (e.g., creates `agencyos_demo`, `agencyos_livingwater`)
- **tenant_data_scripts**: Scripts run once, each file uses `USE` to target specific databases

**Execution Order:**
1. **Main Database Scripts** (if configured):
   - `setup_path` - Database setup scripts
   - `tables_path` - Table creation scripts
   - `procedures_path` - Stored procedure scripts
   - `data_path` - Data scripts

2. **Tenant Database Scripts** (if configured, executed per tenant):
   - `setup_path` - Tenant database setup scripts
   - `tables_path` - Table creation scripts
   - `procedures_path` - Stored procedure scripts
   - `data_path` - Data scripts

3. **Tenant Data Scripts** (if configured, executed once):
   - `data_path` - SQL files with explicit `USE` statements

**Example Tenant Data File:**
```sql
-- Insert into main database
USE agencyos;
INSERT INTO tenant (name, webid, ...) VALUES ('Demo', 'demo', ...);

-- Insert into specific tenant database
USE agencyos_demo;
INSERT INTO website_css (name, is_active, ...) VALUES ('default', 1, ...);

-- Insert into another tenant database
USE agencyos_livingwater;
INSERT INTO website_css (name, is_active, ...) VALUES ('default', 1, ...);
```

**Key Points:**
- Database deployment is **optional** - set `enabled: false` or omit the section entirely
- Supports both SSH password and key-file authentication
- SQL files are read from local paths (source machine) and executed remotely
- Dry-run mode shows which SQL files would be executed without running them
- Database deployment occurs **after** file synchronization completes
- All script paths are optional - only provide the ones you need
- Files in directories are executed in alphabetical order (use prefixes like `01-`, `02-` to control order)
- Multi-tenant apps: Use `tenant-database` for per-tenant scripts and `tenant_data_scripts` for one-time data files

## Testing Configuration Changes

Always test configuration changes with dry-run mode first:
1. Set `"dry_run": true` in config
2. Run the agent
3. Review the synchronization summary
4. Set `"dry_run": false` only after verification

## Handler Connection Lifecycle

Handlers follow a strict lifecycle managed by agents:
1. Instantiate handler with config parameters
2. Call `connect()` - establishes connection, sets `_connected = True`
3. Perform operations (list/read/write/delete)
4. Call `disconnect()` - cleanup (especially important for SSH connections)

Always use try/finally to ensure `disconnect()` is called (see `ai_deploy.py:198-253`).

## SSH Handler Implementation Details

- Uses `paramiko` library for SSH/SFTP
- Supports both RSA key files and password authentication
- SFTP client is opened after SSH connection established
- Recursive directory operations handled manually (paramiko doesn't provide native recursive operations)
- Path separators normalized to forward slashes for remote operations

## Windows Share Handler Implementation Details

- Uses standard Python `pathlib` and `shutil`
- No authentication handling (relies on OS-level network authentication)
- UNC paths must use double backslashes in JSON: `"\\\\server\\share"`
- Local paths use standard Windows format: `"C:\\path\\to\\folder"`

## Logging Strategy

All agents inherit a configured logger from `AgentBase._setup_logger()`. Logger name is set to the agent class name. Use appropriate levels:
- `logger.info()` for normal operations and progress
- `logger.error()` for errors (don't raise exception if you want to continue)
- Avoid debug/warning unless adding debugging features

Log format: `'%(asctime)s - %(name)s - %(levelname)s - %(message)s'`
