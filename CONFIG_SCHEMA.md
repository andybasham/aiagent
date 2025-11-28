# AI-Deploy Agent - Configuration Schema

## Complete Configuration Reference

This document describes all available configuration options for the ai-deploy agent.

## Root Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `agent_name` | string | Yes | Must be "ai-deploy" |
| `description` | string | No | Human-readable description of this configuration |
| `application_name` | string | No | Application name for {{APPLICATION_NAME}} template variable replacement in config values and deployed files |
| `source` | object | Yes | Source location configuration |
| `destination` | object | Yes | Destination location configuration |
| `ignore` | object | No | Patterns for files/folders to ignore |
| `options` | object | No | Agent behavior options |

### Application Name Template Variable

The `application_name` field enables template variable replacement throughout your configuration and deployed files. When set, all occurrences of `{{APPLICATION_NAME}}` will be replaced with the specified value.

**Where it's replaced:**
- **All configuration values**: Paths, database names, usernames, etc.
- **SQL files during deployment**: Database scripts can reference {{APPLICATION_NAME}}
- **Template variables in database scripts**: Available as {{APPLICATION_NAME}} in SQL templates

**Example:**
```json
{
  "agent_name": "ai-deploy",
  "application_name": "agencyos",
  "source": {
    "type": "windows_share",
    "path": "C:\\git\\{{APPLICATION_NAME}}"
  },
  "database": {
    "main_database_scripts": {
      "db_name": "{{APPLICATION_NAME}}",
      "db_username": "{{APPLICATION_NAME}}_user",
      "setup_path": "C:\\git\\{{APPLICATION_NAME}}\\database\\main\\setup"
    }
  }
}
```

**After replacement:**
```json
{
  "source": {
    "path": "C:\\git\\agencyos"
  },
  "database": {
    "main_database_scripts": {
      "db_name": "agencyos",
      "db_username": "agencyos_user",
      "setup_path": "C:\\git\\agencyos\\database\\main\\setup"
    }
  }
}
```

**In SQL files:**
```sql
CREATE DATABASE IF NOT EXISTS {{APPLICATION_NAME}};
CREATE USER '{{APPLICATION_NAME}}_user'@'localhost' IDENTIFIED BY 'password';
GRANT ALL PRIVILEGES ON {{APPLICATION_NAME}}.* TO '{{APPLICATION_NAME}}_user'@'localhost';
```

## Source and Destination Objects

Both `source` and `destination` use the same structure:

### Common Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Either "windows_share" or "ssh" |
| `path` | string | Yes | Path to the files |

### Windows Share Type

For `"type": "windows_share"`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | Yes | UNC path (\\\\server\\share) or local path (C:\\folder) |
| `username` | string | No | Username for authentication (if needed) |
| `password` | string | No | Password for authentication (if needed) |

**Examples:**

```json
{
  "type": "windows_share",
  "path": "\\\\server\\share\\folder"
}
```

```json
{
  "type": "windows_share",
  "path": "C:\\projects\\myapp"
}
```

```json
{
  "type": "windows_share",
  "path": "\\\\server\\share\\folder",
  "username": "DOMAIN\\username",
  "password": "password123"
}
```

### SSH Type

For `"type": "ssh"`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `host` | string | Yes | SSH server hostname or IP address |
| `username` | string | Yes | SSH username |
| `path` | string | Yes | Remote path on the server |
| `port` | integer | No | SSH port (default: 22) |
| `password` | string | No* | Password for authentication |
| `key_file` | string | No* | Path to SSH private key file |

\* Either `password` or `key_file` must be provided

**Examples:**

Password authentication:
```json
{
  "type": "ssh",
  "host": "192.168.1.100",
  "port": 22,
  "username": "deploy",
  "password": "securepassword",
  "path": "/var/www/myapp"
}
```

Key-based authentication:
```json
{
  "type": "ssh",
  "host": "production.example.com",
  "username": "deploy",
  "key_file": "/home/user/.ssh/id_rsa",
  "path": "/var/www/production"
}
```

Windows path to SSH key:
```json
{
  "type": "ssh",
  "host": "server.example.com",
  "username": "deploy",
  "key_file": "C:\\Users\\username\\.ssh\\id_rsa",
  "path": "/opt/applications/myapp"
}
```

## Ignore Object

The `ignore` object specifies patterns for files and folders to skip during synchronization.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `files` | array of strings | No | File name patterns (supports wildcards) |
| `folders` | array of strings | No | Folder name patterns (supports wildcards) |
| `extensions` | array of strings | No | File extensions to ignore (include the dot) |

**Pattern Matching:**
- Uses Unix shell-style wildcards
- `*` matches everything
- `?` matches any single character
- `[seq]` matches any character in seq
- `[!seq]` matches any character not in seq

**Examples:**

```json
{
  "ignore": {
    "files": [
      "*.log",
      "*.tmp",
      ".env",
      ".env.local",
      "config.local.json",
      "Thumbs.db",
      ".DS_Store"
    ],
    "folders": [
      "__pycache__",
      ".git",
      ".svn",
      "node_modules",
      ".venv",
      "venv",
      "env",
      "dist",
      "build",
      "logs",
      "temp"
    ],
    "extensions": [
      ".pyc",
      ".pyo",
      ".bak",
      ".swp",
      ".swo",
      ".cache"
    ]
  }
}
```

### Common Ignore Patterns

#### Python Projects
```json
{
  "folders": ["__pycache__", ".venv", "venv", "env", "dist", "build", ".pytest_cache"],
  "extensions": [".pyc", ".pyo"]
}
```

#### Node.js Projects
```json
{
  "folders": ["node_modules", "dist", "build", ".next", "coverage"],
  "files": ["package-lock.json", "yarn.lock"]
}
```

#### General Development
```json
{
  "folders": [".git", ".svn", ".hg"],
  "files": [".env", ".env.local", "*.log", "*.tmp"]
}
```

## Options Object

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `dry_run` | boolean | No | false | If true, shows what would be done without making changes |
| `delete_extra_files` | boolean | No | true | If true, deletes files from destination that don't exist in source |
| `verbose` | boolean | No | true | If true, shows detailed progress messages. If false, only shows essential actions (files copied/updated/deleted, SQL files executed) |

**Examples:**

Test mode (no changes):
```json
{
  "options": {
    "dry_run": true,
    "delete_extra_files": false
  }
}
```

Production mode (full sync):
```json
{
  "options": {
    "dry_run": false,
    "delete_extra_files": true
  }
}
```

Sync without deleting:
```json
{
  "options": {
    "dry_run": false,
    "delete_extra_files": false
  }
}
```

Quiet mode (minimal output):
```json
{
  "options": {
    "dry_run": false,
    "delete_extra_files": true,
    "verbose": false
  }
}
```

## Database Configuration

The `database` object enables database deployment and seeding functionality via SSH tunnel.

### Main Database Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | boolean | Yes | Enable/disable database deployment |
| `ssh_host` | string | Yes* | SSH server hostname/IP |
| `ssh_port` | integer | No | SSH port (default: 22) |
| `ssh_username` | string | Yes* | SSH username |
| `ssh_password` | string | No** | SSH password |
| `ssh_key_file` | string | No** | Path to SSH private key file |
| `admin_username` | string | Yes* | MySQL admin username |
| `admin_password` | string | Yes* | MySQL admin password |
| `main_database_scripts` | object | No | Main database deployment config |
| `tenant_database_scripts` | array | No | Tenant database deployment configs |
| `seed_tables` | object | No | Table seeding configuration |

\* Required when `enabled: true`
\*\* Either `ssh_password` or `ssh_key_file` must be provided

### Main Database Scripts Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `db_name` | string | Yes | Database name |
| `db_username` | string | Yes | Database username |
| `db_password` | string | Yes | Database password |
| `setup_path` | string | No | Path to setup SQL scripts directory |
| `tables_path` | string | No | Path to table creation scripts |
| `procedures_path` | string | No | Path to stored procedure scripts |
| `seeds_path` | string | No | Path to seed data scripts |

### Seed Tables Configuration

The `seed_tables` object enables dynamic table seeding from JSON configuration files.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | boolean | Yes | Enable/disable table seeding |
| `config_files_path` | string | Yes* | Directory containing JSON config files |
| `config_files_extension` | string | No | File extension to match (default: ".json") |
| `tables` | array | Yes* | Array of table seeding definitions |

\* Required when `enabled: true`

### Table Seeding Definition

Each object in the `tables` array:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `table_name` | string | Yes | Name of the database table |
| `table_script_file` | string | Yes | Path to table SQL file with INSERT template |
| `begin_mark` | string | Yes | Comment marker for template start |
| `end_mark` | string | Yes | Comment marker for template end |
| `check_exists_query` | string | No | SQL query with variable replacement to check if data exists. For non-array tables: checks if specific record exists (e.g., `SELECT COUNT(1) FROM tenant WHERE webid = '{{WEBID}}'`). For array tables: checks if any records exist for this tenant before inserting entire array (e.g., `SELECT COUNT(1) FROM user WHERE tenant_id = (SELECT id FROM tenant WHERE webid = '{{WEBID}}')`). |
| `array_field` | string | No | JSON field containing array of records (e.g., "users") |
| `nested_array_field` | string | No | JSON field within each element of `array_field` containing a nested array (e.g., "roles"). When specified, loops through outer array, then inner array, inserting one record per nested element. |
| `variables` | array | Yes | Variable mapping definitions |

### Variable Mapping Definition

Each object in the `variables` array:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sql_var` | string | Yes | SQL variable placeholder (e.g., "{{NAME}}") |
| `json_field` | string | Yes | JSON field path (supports dot notation). Use `"."` to reference the element itself when working with primitive arrays (strings, numbers). |
| `from_parent` | boolean | No | Get value from parent object vs array element (default: false) |
| `default_value` | any | No | Default value to use if JSON field is not found (default: NULL). Can be string, number, boolean, or SQL function like "NOW()". |

**Special Behavior:**
- Variables named `{{PASSWORD_HASH}}` or `{{PASSWORD}}` are automatically hashed with bcrypt using PHP's `PASSWORD_DEFAULT` format (`$2y$10$...`), fully compatible with PHP's `password_verify()` function. Other PASSWORD-related fields (like `{{RESET_PASSWORD}}`) are NOT hashed.
- Missing JSON fields are replaced with SQL NULL (or the `default_value` if specified)
- Dot notation supports nested fields (e.g., "terminology.employee")
- **Primitive Arrays**: When `nested_array_field` contains primitives (e.g., `["Admin", "User"]`), use `"json_field": "."` to reference the element value directly
- **SQL Template Quoting**: String variables must be wrapped in quotes in the template (e.g., `'{{NAME}}'`). The replacement logic only escapes quotes, it doesn't add them.

### Database Example

```json
{
  "database": {
    "enabled": true,
    "ssh_host": "192.168.1.4",
    "ssh_port": 22,
    "ssh_username": "deploy",
    "ssh_password": "sshpassword",
    "admin_username": "root",
    "admin_password": "mysqlpassword",
    "main_database_scripts": {
      "db_name": "myapp_db",
      "db_username": "myapp_user",
      "db_password": "dbpassword",
      "setup_path": "C:\\db\\setup",
      "tables_path": "C:\\db\\tables",
      "procedures_path": "C:\\db\\procedures",
      "seeds_path": "C:\\db\\seeds"
    },
    "seed_tables": {
      "enabled": true,
      "config_files_path": "C:\\config\\tenants",
      "config_files_extension": ".json",
      "tables": [
        {
          "table_name": "tenant",
          "table_script_file": "C:\\db\\tables\\tenant.sql",
          "begin_mark": "BEGIN AI-AGENT.AI-DEPLOY:",
          "end_mark": "END AI-AGENT.AI-DEPLOY:",
          "check_exists_query": "SELECT COUNT(1) FROM tenant WHERE webid = '{{WEBID}}'",
          "variables": [
            {"sql_var": "{{NAME}}", "json_field": "name"},
            {"sql_var": "{{WEBID}}", "json_field": "webid"},
            {"sql_var": "{{EMAIL}}", "json_field": "email"}
          ]
        },
        {
          "table_name": "user",
          "table_script_file": "C:\\db\\tables\\user.sql",
          "begin_mark": "BEGIN AI-AGENT.AI-DEPLOY:",
          "end_mark": "END AI-AGENT.AI-DEPLOY:",
          "check_exists_query": "SELECT COUNT(1) FROM user WHERE tenant_id = (SELECT id FROM tenant WHERE webid = '{{WEBID}}')",
          "array_field": "users",
          "variables": [
            {"sql_var": "{{WEBID}}", "json_field": "webid", "from_parent": true},
            {"sql_var": "{{USERNAME}}", "json_field": "username"},
            {"sql_var": "{{PASSWORD_HASH}}", "json_field": "password"},
            {"sql_var": "{{EMAIL}}", "json_field": "email"}
          ]
        },
        {
          "table_name": "user_role",
          "table_script_file": "C:\\db\\tables\\user_role.sql",
          "begin_mark": "BEGIN AI-AGENT.AI-DEPLOY:",
          "end_mark": "END AI-AGENT.AI-DEPLOY:",
          "check_exists_query": "SELECT COUNT(1) FROM user_role ur JOIN user u ON ur.user_id = u.id WHERE u.tenant_id = (SELECT id FROM tenant WHERE webid = '{{WEBID}}')",
          "array_field": "users",
          "nested_array_field": "roles",
          "variables": [
            {"sql_var": "{{WEBID}}", "json_field": "webid", "from_parent": true},
            {"sql_var": "{{USERNAME}}", "json_field": "username", "from_parent": true},
            {"sql_var": "{{ROLE_NAME}}", "json_field": "."}
          ]
        }
      ]
    }
  }
}
```

**How It Works:**

1. All JSON files in `config_files_path` are processed
2. For each table definition:
   - Executes `check_exists_query` (if provided) to see if data exists
   - For non-array tables: If specific record exists, skips that record
   - For array tables: If any records exist for this tenant, skips entire array
   - Extracts INSERT template from SQL file between markers
   - If `nested_array_field` specified: loops through outer `array_field`, then loops through `nested_array_field` in each outer element, inserting one row per nested element
   - If `array_field` specified (no nested): loops through array, inserting one row per element
   - If no `array_field`: inserts single row from parent JSON
   - Variables are replaced with JSON values:
     - For nested arrays: `from_parent: true` gets value from outer element (user), regular variables get value from nested element (role)
     - For single arrays: `from_parent: true` gets value from root JSON, regular variables get value from array element
   - Passwords are automatically hashed using bcrypt with cost factor 10 (`$2y$10$...` format)
3. Execution order: `setup → tables → procedures → seeds → seed_tables`

**Important Notes:**
- **Main Database Only**: `seed_tables` applies ONLY to the main database. Tenant databases typically have different schemas and should use regular `seeds_path` scripts.
- **PHP Compatibility**: Password hashes use the exact format produced by PHP's `password_hash($password, PASSWORD_DEFAULT)`. Hashes can be verified in PHP using `password_verify($password, $hash)`.
- **Hash Format**: `$2y$10$` prefix + 22-character salt + 31-character hash (60 characters total)
- **Nested Arrays**: When using `nested_array_field`, your JSON structure should have arrays within arrays. The root JSON provides values for variables with `from_parent: true` at the root level, outer array elements provide values for variables with `from_parent: true` at the nested level, and nested array elements provide values for regular variables.

### Example JSON Structure for Nested Arrays

```json
{
  "webid": "demo",
  "name": "Demo Tenant",
  "users": [
    {
      "username": "admin.user",
      "password": "password123",
      "email": "admin@example.com",
      "roles": ["Admin", "User"]
    },
    {
      "username": "regular.user",
      "password": "password456",
      "email": "user@example.com",
      "roles": ["User"]
    }
  ]
}
```

**For the `user_role` table above:**
- Processes 2 users (outer array)
- admin.user has 2 roles → inserts 2 user_role records
- regular.user has 1 role → inserts 1 user_role record
- Total: 3 user_role records inserted
- Variables: `{{WEBID}}` from root, `{{USERNAME}}` from user, `{{ROLE_NAME}}` from role element (using `"json_field": "."` for primitive array)

## Complete Example Configurations

### Example 1: Local to Remote (Development to Production)

```json
{
  "agent_name": "ai-deploy",
  "description": "Deploy from local development to production server",
  "source": {
    "type": "windows_share",
    "path": "C:\\dev\\myproject"
  },
  "destination": {
    "type": "ssh",
    "host": "production.example.com",
    "port": 22,
    "username": "deploy",
    "key_file": "C:\\Users\\developer\\.ssh\\id_rsa",
    "path": "/var/www/production"
  },
  "ignore": {
    "files": [
      "*.log",
      ".env",
      ".env.local"
    ],
    "folders": [
      "__pycache__",
      ".git",
      "node_modules",
      ".venv"
    ],
    "extensions": [
      ".pyc",
      ".bak"
    ]
  },
  "options": {
    "dry_run": false,
    "delete_extra_files": true
  }
}
```

### Example 2: Network Share to Network Share

```json
{
  "agent_name": "ai-deploy",
  "description": "Sync between development and staging servers",
  "source": {
    "type": "windows_share",
    "path": "\\\\dev-server\\applications\\myapp",
    "username": "DOMAIN\\serviceaccount",
    "password": "P@ssw0rd123"
  },
  "destination": {
    "type": "windows_share",
    "path": "\\\\staging-server\\applications\\myapp",
    "username": "DOMAIN\\serviceaccount",
    "password": "P@ssw0rd123"
  },
  "ignore": {
    "folders": [
      "logs",
      "temp",
      "__pycache__"
    ],
    "extensions": [
      ".log",
      ".tmp"
    ]
  },
  "options": {
    "dry_run": false,
    "delete_extra_files": true
  }
}
```

### Example 3: Server to Server via SSH

```json
{
  "agent_name": "ai-deploy",
  "description": "Replicate from primary to backup server",
  "source": {
    "type": "ssh",
    "host": "primary.example.com",
    "username": "admin",
    "key_file": "/home/admin/.ssh/id_rsa",
    "path": "/opt/applications/critical-app"
  },
  "destination": {
    "type": "ssh",
    "host": "backup.example.com",
    "username": "admin",
    "key_file": "/home/admin/.ssh/id_rsa",
    "path": "/opt/backups/critical-app"
  },
  "ignore": {
    "folders": [
      "logs",
      "temp"
    ],
    "files": [
      "*.log"
    ]
  },
  "options": {
    "dry_run": false,
    "delete_extra_files": true
  }
}
```

### Example 4: Safe Testing Configuration

```json
{
  "agent_name": "ai-deploy",
  "description": "Test configuration - no changes will be made",
  "source": {
    "type": "windows_share",
    "path": "C:\\source\\folder"
  },
  "destination": {
    "type": "ssh",
    "host": "test.example.com",
    "username": "testuser",
    "password": "testpass",
    "path": "/tmp/test-deploy"
  },
  "ignore": {
    "files": [],
    "folders": [],
    "extensions": []
  },
  "options": {
    "dry_run": true,
    "delete_extra_files": false
  }
}
```

## Validation Rules

The agent validates configurations and will fail with an error if:

1. **Missing required fields**: `agent_name`, `source`, `destination`
2. **Invalid type**: `type` must be "windows_share" or "ssh"
3. **Missing path**: Both source and destination must have a `path`
4. **SSH missing fields**: SSH type must have `host` and `username`
5. **SSH missing auth**: SSH type must have either `password` or `key_file`
6. **Invalid JSON**: Configuration file must be valid JSON

## Tips for Creating Configurations

1. **Start with dry_run = true**: Always test first
2. **Use absolute paths**: Avoid relative paths for clarity
3. **Escape backslashes**: In JSON, use `\\` for Windows paths
4. **Test ignore patterns**: Run dry-run to verify files are ignored correctly
5. **Be careful with delete_extra_files**: This will remove files from destination
6. **Use comments in a separate file**: JSON doesn't support comments; document separately
7. **Version control**: Keep configurations in version control (without credentials)
8. **Use environment variables**: For sensitive data, consider using env vars
9. **Validate JSON**: Use a JSON validator before running
10. **Keep backups**: Before running with delete_extra_files = true

## Security Best Practices

1. **Never commit passwords**: Use `.gitignore` to exclude config files with credentials
2. **Use SSH keys**: Prefer key-based authentication over passwords
3. **Restrict key permissions**: Ensure private keys have proper permissions (600)
4. **Use strong passwords**: If using password auth, use strong passwords
5. **Encrypt at rest**: Consider encrypting configuration files containing credentials
6. **Rotate credentials**: Regularly rotate passwords and SSH keys
7. **Limit access**: Only give necessary permissions to service accounts
8. **Audit logs**: Review agent logs regularly for suspicious activity

---

**Schema Version**: 1.0.0
**Last Updated**: 2025-11-01
