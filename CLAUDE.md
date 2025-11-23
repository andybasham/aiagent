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

**File Comparison Algorithm** (ai-deploy): The agent doesn't stream or transfer immediately. Instead, it:
1. Lists all files from both source and destination
2. Filters source files through ignore patterns
3. Categorizes files into new/modified/deleted by comparing metadata (size, mtime)
4. Executes synchronization in three phases: copy new, update modified, delete extra

**Ignore Pattern System**: Three-tier filtering (files, folders, extensions) using `fnmatch` for wildcards. Patterns are checked in `_should_ignore()` method before including files in sync operations.

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

**Configuration:**
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
    "db_username": "root",
    "db_password": "mysql_password",
    "db_name": "database_name",
    "scripts": {
      "create_db": "C:\\path\\to\\create-db.sql",
      "tables_path": "C:\\path\\to\\tables",
      "procedures_path": "C:\\path\\to\\procs",
      "seeds_path": "C:\\path\\to\\seeds"
    }
  }
}
```

**Execution Order:**
1. **create_db**: Single SQL file for database creation (runs first)
2. **tables_path**: Directory of table creation scripts (sorted alphabetically)
3. **procedures_path**: Directory of stored procedure scripts (sorted alphabetically)
4. **seeds_path**: Directory of seed data scripts (sorted alphabetically)

**Key Points:**
- Database deployment is **optional** - set `enabled: false` or omit the section entirely
- Supports both SSH password and key-file authentication
- SQL files are read from local paths (source machine) and executed remotely
- Dry-run mode shows which SQL files would be executed without running them
- Database deployment occurs **after** file synchronization completes
- All script paths are optional - only provide the ones you need
- Files in directories are executed in alphabetical order (use prefixes like `01-`, `02-` to control order)

### Dynamic Table Seeding (Optional)

The ai-deploy agent supports dynamic table seeding from JSON configuration files. This feature reads JSON files containing data and automatically generates INSERT statements from SQL templates embedded in table definition files.

**Use Case:** Perfect for multi-tenant applications where each tenant needs initial data (tenant record, admin users, default settings) seeded from tenant-specific configuration files.

**Configuration:**
```json
{
  "database": {
    "enabled": true,
    "ssh_host": "192.168.1.4",
    "ssh_username": "deploy",
    "ssh_password": "password",
    "admin_username": "root",
    "admin_password": "mysql_password",
    "main_database_scripts": {
      "db_name": "myapp_db",
      "db_username": "myapp_user",
      "db_password": "dbpassword",
      "tables_path": "C:\\db\\tables"
    },
    "seed_tables": {
      "enabled": true,
      "config_files_path": "C:\\git\\myapp\\config\\tenants",
      "config_files_extension": ".json",
      "tables": [
        {
          "table_name": "tenant",
          "table_script_file": "C:\\git\\myapp\\database\\tables\\tenant.sql",
          "begin_mark": "BEGIN AI-AGENT.AI-DEPLOY:",
          "end_mark": "END AI-AGENT.AI-DEPLOY:",
          "check_exists_query": "SELECT COUNT(1) FROM tenant",
          "variables": [
            {"sql_var": "{{NAME}}", "json_field": "name"},
            {"sql_var": "{{WEBID}}", "json_field": "webid"},
            {"sql_var": "{{EMAIL}}", "json_field": "email"},
            {"sql_var": "{{EMPLOYEE_TERM}}", "json_field": "terminology.employee"}
          ]
        },
        {
          "table_name": "user",
          "table_script_file": "C:\\git\\myapp\\database\\tables\\user.sql",
          "begin_mark": "BEGIN AI-AGENT.AI-DEPLOY:",
          "end_mark": "END AI-AGENT.AI-DEPLOY:",
          "array_field": "users",
          "check_exists_query": "SELECT COUNT(1) FROM user",
          "variables": [
            {"sql_var": "{{WEBID}}", "json_field": "webid", "from_parent": true},
            {"sql_var": "{{USERNAME}}", "json_field": "username"},
            {"sql_var": "{{PASSWORD_HASH}}", "json_field": "password"},
            {"sql_var": "{{ROLE}}", "json_field": "role"},
            {"sql_var": "{{EMAIL}}", "json_field": "email"}
          ]
        },
        {
          "table_name": "tenant_module",
          "database": "tenant",
          "table_script_file": "C:\\git\\myapp\\database\\tenant\\tables\\tenant_module.sql",
          "begin_mark": "BEGIN AI-AGENT.AI-DEPLOY:",
          "end_mark": "END AI-AGENT.AI-DEPLOY:",
          "array_field": "modules",
          "check_exists_query": "SELECT COUNT(1) FROM tenant_module WHERE module_code = '{{MODULE_CODE}}'",
          "variables": [
            {"sql_var": "{{MODULE_CODE}}", "json_field": "module_code"},
            {"sql_var": "{{MODULE_NAME}}", "json_field": "module_name"},
            {"sql_var": "{{IS_ACTIVE}}", "json_field": "is_active"}
          ]
        }
      ]
    }
  }
}
```

**How It Works:**

1. **JSON Config Files**: All `.json` files in `config_files_path` are processed (e.g., tenant configurations)
2. **SQL Templates**: Table SQL files contain INSERT statement templates between comment markers:
   ```sql
   /*
   BEGIN AI-AGENT.AI-DEPLOY:
   INSERT INTO tenant (name, webid, email) VALUES ('{{NAME}}', '{{WEBID}}', '{{EMAIL}}');
   END AI-AGENT.AI-DEPLOY:
   */
   ```
   **Important**: String variables must be wrapped in quotes in the template (e.g., `'{{NAME}}'`). Numeric variables should not have quotes (e.g., `{{ID}}`).
3. **Variable Replacement**: Variables like `{{NAME}}` are replaced with JSON values (quotes are already in template)
4. **Array Processing**: If `array_field` is specified, creates one INSERT per array element
5. **Conditional Seeding**: `check_exists_query` determines if seeding should be skipped

**Key Features:**

- **Automatic Password Hashing**: Variables containing "PASSWORD" are hashed with bcrypt using PHP's `PASSWORD_DEFAULT` format (`$2y$10$...`), fully compatible with PHP's `password_verify()`
- **Nested JSON Access**: Use dot notation (e.g., `"terminology.employee"`) for nested fields
- **Parent Context**: Use `"from_parent": true` to access parent JSON object from array elements
- **NULL Handling**: Missing JSON fields are replaced with SQL NULL (even if template has quotes like `'{{VAR}}'`, result is `NULL` not `'NULL'`)
- **Skip Existing Records**: Records are skipped if they already exist based on `check_exists_query` with variable replacement (e.g., `SELECT COUNT(1) FROM tenant WHERE webid = '{{WEBID}}'`)
- **Array Tables**: For tables with `array_field`, `check_exists_query` is ignored (each array element is always inserted - use database unique constraints to prevent duplicates)

**Execution Order:**
```
setup → tables → procedures → seeds → seed_tables
```

**Example JSON Config File** (`tenants/livingwater.json`):
```json
{
  "name": "Living Water Therapy",
  "webid": "livingwater",
  "email": "admin@livingwater.org",
  "terminology": {
    "employee": "Clinician",
    "customer": "Client"
  },
  "users": [
    {
      "username": "admin",
      "password": "temp123",
      "role": "admin",
      "email": "admin@livingwater.org"
    },
    {
      "username": "therapist1",
      "password": "temp123",
      "role": "clinician",
      "email": "therapist@livingwater.org"
    }
  ]
}
```

**Example Table SQL File** (`database/tables/user.sql`):
```sql
CREATE TABLE IF NOT EXISTS user (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id INT NOT NULL,
    username VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL,
    email VARCHAR(100) NOT NULL
);

/*
BEGIN AI-AGENT.AI-DEPLOY:
INSERT INTO user (
    tenant_id,
    username,
    password_hash,
    role,
    email
) VALUES (
    (SELECT id FROM tenant WHERE webid = '{{WEBID}}'),
    '{{USERNAME}}',
    '{{PASSWORD_HASH}}',
    '{{ROLE}}',
    '{{EMAIL}}'
);
END AI-AGENT.AI-DEPLOY:
*/
```

**Key Points:**
- Dynamic table seeding is **optional** - omit `seed_tables` section if not needed
- Processes ALL JSON files in `config_files_path` directory
- Tables are seeded in the order defined in `tables` array
- Passwords are automatically hashed before insertion using bcrypt with cost factor 10
- **PHP Compatible**: Hashes use `$2y$10$...` format, identical to PHP's `password_hash($password, PASSWORD_DEFAULT)`
- **PHP Verification**: Hashes can be verified in PHP using `password_verify($password, $hash)`
- **Database Target**: Each table definition can specify `"database": "main"` or `"database": "tenant"` to control which database(s) to seed
  - Tables without the `database` field default to `"main"`
  - Tables with `"database": "main"` are seeded only on the main database
  - Tables with `"database": "tenant"` are seeded on ALL tenant databases
- Dry-run mode shows summary without executing INSERTs
- Skips tables that already contain data
- Ideal for multi-tenant initial data seeding in both main and tenant databases

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
