# AI-Deploy Agent - Configuration Schema

## Complete Configuration Reference

This document describes all available configuration options for the ai-deploy agent.

## Root Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `agent_name` | string | Yes | Must be "ai-deploy" |
| `description` | string | No | Human-readable description of this configuration (used in warn prompt) |
| `application_name` | string | No | Application name for {{APPLICATION_NAME}} template variable replacement in config values and deployed files |
| `warn` | boolean | No | Enable confirmation prompt before deployment (default: false) |
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

## Website Configuration

The `website` object configures website-specific deployment settings including destination path, file mappings, permissions scripts, and pre-build steps.

### Website Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | Yes | Destination path on server (e.g., "/var/www/myapp") |
| `pre_build` | object | No | Pre-build configuration for running local build commands before deployment |
| `file_mappings` | array | No | File mapping configurations for copying files with different names |
| `set_permissions_script` | string | No | Script to run on server after deployment for setting permissions |
| `cronjobs` | object | No | Cronjobs setup configuration |
| `ignore` | object | No | Website-specific ignore patterns |

### Pre-Build Configuration

The `pre_build` object allows you to run a local build command (e.g., `npm run build`) before syncing files to the destination. The build only runs when watched source files have changed since the last deployment.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | boolean | Yes | Enable/disable pre-build step |
| `working_directory` | string | Yes* | Local directory to run the build command in |
| `command` | string | Yes* | Build command to execute (e.g., "npm run build:prod") |
| `watch_patterns` | array | Yes* | Glob patterns for files to watch for changes |

\* Required when `enabled: true`

**How it works:**

1. Before file sync begins, the agent checks if any files matching `watch_patterns` have changed since the last deployment
2. If changes are detected, the `command` is executed in `working_directory`
3. If the build fails (non-zero exit code), deployment is **aborted** to prevent deploying broken code
4. If no changes are detected, the build is skipped (uses cached build output)
5. The pre-build step runs **locally** on your machine, not on the server

**Example:**
```json
{
  "website": {
    "path": "/var/www/agencyos",
    "pre_build": {
      "enabled": true,
      "working_directory": "C:\\git\\agencyos",
      "command": "npm run build:prod",
      "watch_patterns": [
        "web/src/**/*.js",
        "web/public/js/**/*.js",
        "web/css/**/*.css",
        "web/public/css/**/*.css",
        "build.config.mjs",
        "package.json"
      ]
    }
  }
}
```

**Watch Pattern Examples:**

```json
{
  "watch_patterns": [
    "src/**/*.js",           // All JS files in src
    "src/**/*.ts",           // All TypeScript files
    "styles/**/*.css",       // All CSS files
    "package.json",          // Package dependencies
    "webpack.config.js",     // Build configuration
    "tsconfig.json"          // TypeScript configuration
  ]
}
```

**Output when files changed:**
```
Pre-build check...
  Source files changed (3):
    - web/src/public/features/give.js
    - web/css/shared/buttons.css
    - package.json
Running pre-build: npm run build:prod
Working directory: C:\git\agencyos
  > agencyos@1.0.0 build:prod
  > node build.config.mjs
  Building JavaScript bundles...
  ✓ public.full.js (24.2 KB)
Pre-build complete
```

**Output when no changes:**
```
Pre-build check...
  No source files changed, skipping build
```

**Notes:**
- The pre-build cache is stored in the same deployment cache file (`.deploy_cache_*.json`)
- Use `dry_run: true` to test without actually running the build
- The build command is executed with `shell=True`, so you can use shell features
- Build output (stdout) is logged in real-time
- If build fails, the error output is logged and deployment stops

## Options Object

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `dry_run` | boolean | No | false | If true, shows what would be done without making changes |
| `delete_extra_files` | boolean | No | true | If true, deletes files from destination that don't exist in source |
| `verbose` | boolean | No | true | If true, shows detailed progress messages. If false, only shows essential actions (files copied/updated/deleted, SQL files executed) |
| `ignore_cache` | boolean | No | false | If true, ignores deployment cache and performs full comparison. If false, uses cache to skip unchanged files for faster incremental deployments |
| `clean_install` | boolean | No | false | If true, deletes all destination files and databases before deployment. Forces full re-deployment ignoring cache. Requires user confirmation. |
| `migration_only` | boolean | No | false | If true, only executes migration scripts (migration_path) instead of full database deployment. Cannot be used with `clean_install=true`. |
| `max_concurrent_transfers` | integer | No | 20 | Maximum number of parallel file transfers (only applies when using SSH connections) |

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

Production mode (incremental deployment with cache):
```json
{
  "options": {
    "dry_run": false,
    "delete_extra_files": true,
    "ignore_cache": false
  }
}
```

Force full deployment (ignore cache):
```json
{
  "options": {
    "dry_run": false,
    "delete_extra_files": true,
    "ignore_cache": true
  }
}
```

Clean install (delete everything and redeploy):
```json
{
  "options": {
    "dry_run": false,
    "delete_extra_files": true,
    "clean_install": true
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

Fast incremental deployment (uses cache, skips destination listing):
```json
{
  "options": {
    "dry_run": false,
    "delete_extra_files": false,
    "ignore_cache": false,
    "clean_install": false,
    "verbose": false
  }
}
```

Migration only mode (only run database migration scripts):
```json
{
  "options": {
    "dry_run": false,
    "migration_only": true
  }
}
```

**Note:** `migration_only` cannot be used with `clean_install=true` - an error will be thrown if both are set.

### Incremental Deployment and Cache System

The ai-deploy agent uses a cache system to track deployed files and database scripts for faster incremental deployments.

**How it works:**

1. **Cache File**: After each deployment, a cache file is created in the same directory as your config file (e.g., `.deploy_cache_ai-deploy-example-windows.json`)

2. **File Tracking**: The cache stores:
   - File modification times (mtime) and sizes
   - Last deployment timestamp
   - Database script execution timestamps
   - File mapping metadata
   - Web tenant metadata

3. **Incremental Deployment** (`clean_install=false`, `ignore_cache=false`):
   - **Skips destination file listing** - Uses cache instead of listing all destination files (much faster!)
   - **Only deploys changed files** - Compares source files against cache to detect changes
   - **Only executes changed SQL scripts** - Database scripts modified since last deployment are executed
   - **Trusts the cache** - Assumes destination is in sync with cache (no accidental deletions)

4. **Full Deployment** (`ignore_cache=true` or `clean_install=true`):
   - Lists all destination files
   - Compares all files (ignores cache)
   - Executes all database scripts
   - Updates cache after deployment

**Performance Benefits:**

- **Faster file comparison**: Skips slow destination file listing (especially over SSH)
- **Faster database deployment**: Only executes changed SQL scripts
- **Faster file sync**: Only copies new/modified files based on cache

**Important Notes:**

- Cache is safe to delete - next deployment will perform full comparison
- Always use `clean_install=true` for first deployment to new destination
- Use `ignore_cache=true` if you suspect cache is out of sync
- Cache file should be excluded from version control (add to `.gitignore`)

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
| `tenant-database` | object | No | Tenant database deployment config (per-tenant execution) |
| `tenant_data_scripts` | object | No | Tenant data scripts (executed once, files use explicit USE statements) |
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
| `data_path` | string | No | Path to data SQL scripts (runs after procedures) |
| `migration_path` | string | No | Path to migration SQL scripts (only executed when `options.migration_only=true`) |

### Tenant Database Scripts Object

The `tenant-database` object defines scripts that are executed **for each tenant** using template variable replacement for `{{WEBID}}`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | boolean | Yes | Enable/disable tenant database deployment |
| `db_name` | string | Yes | Database name (supports {{WEBID}} template variable) |
| `db_username` | string | Yes | Database username |
| `db_password` | string | Yes | Database password |
| `setup_path` | string | No | Path to setup SQL scripts directory (executed per tenant) |
| `tables_path` | string | No | Path to table creation scripts (executed per tenant) |
| `procedures_path` | string | No | Path to stored procedure scripts (executed per tenant) |
| `data_path` | string | No | Path to data SQL scripts (executed per tenant) |
| `migration_path` | string | No | Path to migration SQL scripts (only executed when `options.migration_only=true`, executed per tenant) |

**Note**: Scripts in these paths are executed once **per tenant**. Each tenant's database is created using template variables like `{{WEBID}}`.

### Tenant Data Scripts Object

The `tenant_data_scripts` object defines scripts that are executed **once** after all tenant databases are created. Each SQL file uses explicit `USE database_name;` statements to target specific databases.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | boolean | Yes | Enable/disable tenant data scripts |
| `data_path` | string | Yes | Path to tenant data SQL files (executed once, not per-tenant) |

**Key Difference from Tenant Database Scripts**:
- **Tenant Database Scripts** (`tenant-database`): Executed once per tenant (loops through all tenants)
- **Tenant Data Scripts** (`tenant_data_scripts`): Executed once total (files use `USE` statements to target specific databases)

**Example tenant data file structure**:
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

### Database Example

**Example with Main Database Only:**
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
      "data_path": "C:\\db\\data"
    }
  }
}
```

**Example with Multi-Tenant Databases:**
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

**Script Execution Order (Normal Deployment - `migration_only=false`):**

1. **Main Database Scripts** (if configured):
   - `setup_path` - Database setup scripts (create database, users, grants)
   - `tables_path` - Table creation scripts
   - `procedures_path` - Stored procedure scripts
   - `data_path` - Data scripts (runs after procedures)

2. **Tenant Database Scripts** (if configured, executed per tenant):
   - `setup_path` - Database setup scripts (create tenant database, users, grants)
   - `tables_path` - Table creation scripts
   - `procedures_path` - Stored procedure scripts
   - `data_path` - Data scripts

3. **Tenant Data Scripts** (if configured, executed once after all tenant databases are created):
   - `data_path` - SQL files using explicit `USE` statements to insert data into specific databases

**Script Execution Order (Migration Mode - `migration_only=true`):**

When `options.migration_only=true`, only migration scripts are executed:

1. **Main Database Migration** (if configured):
   - `migration_path` - Migration SQL scripts for main database

2. **Tenant Database Migration** (if configured, executed per tenant):
   - `migration_path` - Migration SQL scripts for each tenant database

**Note:** In migration mode, `setup_path`, `tables_path`, `procedures_path`, `data_path`, and `tenant_data_scripts` are all **skipped**.

### Migration Mode

Migration mode (`options.migration_only=true`) is designed for running database schema changes on an existing database without re-running setup, table creation, or data scripts. This is useful for:

- Adding new columns to existing tables
- Creating new tables without re-running all table scripts
- Modifying stored procedures
- Running one-time data fixes

**Key behaviors:**
- Only executes scripts in `migration_path` directories
- Skips all other script paths (setup, tables, procedures, data)
- Cannot be used with `clean_install=true` (will throw an error)
- Uses the same incremental cache system (only executes changed migration scripts)

**Example configuration for migration mode:**
```json
{
  "database": {
    "enabled": true,
    "main_database_scripts": {
      "db_name": "myapp",
      "db_username": "myapp_user",
      "db_password": "password",
      "migration_path": "C:\\git\\myapp\\database\\main\\migration"
    },
    "tenant-database": {
      "enabled": true,
      "db_name": "myapp_{{WEBID}}",
      "db_username": "myapp_user",
      "db_password": "password",
      "migration_path": "C:\\git\\myapp\\database\\tenant\\migration"
    }
  },
  "options": {
    "migration_only": true
  }
}
```

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
