# Quick Start Guide

## Installation

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Using AI-Deploy Agent

### Step 1: Create Your Configuration

Copy one of the example configurations from the `config/` folder and modify it for your needs:

```bash
cp config/ai-deploy-example-ssh-password.json config/my-deployment.json
```

Edit `config/my-deployment.json` with your actual paths and credentials.

### Step 2: Test with Dry Run

First, run in dry-run mode to see what would happen without making changes:

```json
{
  ...
  "options": {
    "dry_run": true,
    "delete_extra_files": false
  }
}
```

```bash
python main.py config/my-deployment.json
```

### Step 3: Run the Deployment

Once you're satisfied with the dry run results, disable dry run mode:

```json
{
  ...
  "options": {
    "dry_run": false,
    "delete_extra_files": true
  }
}
```

```bash
python main.py config/my-deployment.json
```

## Common Use Cases

### Local to Remote Server (SSH with Password)

```json
{
  "agent_name": "ai-deploy",
  "source": {
    "type": "windows_share",
    "path": "C:\\projects\\myapp"
  },
  "destination": {
    "type": "ssh",
    "host": "192.168.1.100",
    "username": "deploy",
    "password": "your_password",
    "path": "/var/www/myapp"
  },
  "ignore": {
    "folders": ["node_modules", ".git", "__pycache__"],
    "files": ["*.log"],
    "extensions": [".pyc"]
  },
  "options": {
    "dry_run": false,
    "delete_extra_files": true
  }
}
```

### Local to Remote Server (SSH with Key)

```json
{
  "agent_name": "ai-deploy",
  "source": {
    "type": "windows_share",
    "path": "C:\\projects\\myapp"
  },
  "destination": {
    "type": "ssh",
    "host": "production.example.com",
    "username": "deploy",
    "key_file": "C:\\Users\\username\\.ssh\\id_rsa",
    "path": "/var/www/production"
  },
  "ignore": {
    "folders": ["node_modules", ".git"],
    "files": [".env", "*.log"],
    "extensions": [".pyc", ".bak"]
  },
  "options": {
    "dry_run": false,
    "delete_extra_files": true
  }
}
```

### Windows Share to Windows Share

```json
{
  "agent_name": "ai-deploy",
  "source": {
    "type": "windows_share",
    "path": "\\\\dev-server\\share\\app",
    "username": "DOMAIN\\user",
    "password": "password"
  },
  "destination": {
    "type": "windows_share",
    "path": "\\\\prod-server\\share\\app",
    "username": "DOMAIN\\user",
    "password": "password"
  },
  "ignore": {
    "folders": [".git", "__pycache__"],
    "extensions": [".pyc", ".log"]
  },
  "options": {
    "dry_run": false,
    "delete_extra_files": true
  }
}
```

## Understanding the Output

The agent will show you:

1. **Connection Status**: Whether it successfully connected to source and destination
2. **File Counts**: Total files found in each location
3. **Synchronization Summary**:
   - New files to copy
   - Modified files to update
   - Files to delete
4. **Detailed Operations**: Each file operation being performed
5. **Errors**: Any issues encountered during sync

Example output:
```
2025-11-01 10:30:00 - AiDeployAgent - INFO - Creating source handler...
2025-11-01 10:30:00 - AiDeployAgent - INFO - Creating destination handler...
2025-11-01 10:30:00 - AiDeployAgent - INFO - Connecting to source...
2025-11-01 10:30:01 - AiDeployAgent - INFO - Connecting to destination...
2025-11-01 10:30:02 - AiDeployAgent - INFO - Listing source files...
2025-11-01 10:30:03 - AiDeployAgent - INFO - Found 150 files in source
2025-11-01 10:30:03 - AiDeployAgent - INFO - Listing destination files...
2025-11-01 10:30:04 - AiDeployAgent - INFO - Found 145 files in destination
2025-11-01 10:30:04 - AiDeployAgent - INFO - Comparing files...
============================================================
SYNCHRONIZATION SUMMARY
============================================================
New files: 8
Modified files: 3
Files to delete: 1
============================================================
2025-11-01 10:30:04 - AiDeployAgent - INFO - New files to copy: 8
2025-11-01 10:30:04 - AiDeployAgent - INFO -   Copying new file: src/new_feature.py
...
```

## Troubleshooting

### SSH Connection Issues

- Verify the host, username, and port are correct
- For key-based auth, ensure the key file path is correct and the key has proper permissions
- For password auth, verify the password is correct

### Windows Share Issues

- Ensure UNC paths use double backslashes: `\\\\server\\share`
- For local paths, use single backslashes or forward slashes: `C:\\path` or `C:/path`
- Verify network share is accessible from your machine

### Files Not Syncing

- Check the `ignore` configuration - files might be excluded
- Verify source files have newer modification times than destination files
- Run in dry-run mode to see what would be synced

### Permission Errors

- Ensure the user has read permissions on source
- Ensure the user has write permissions on destination
- For SSH, verify the user can write to the destination path

## Best Practices

1. **Always test with dry run first**
2. **Use ignore patterns** to exclude unnecessary files
3. **Use key-based authentication** for SSH when possible
4. **Keep credentials secure** - don't commit config files with passwords
5. **Start with `delete_extra_files: false`** until you're confident
6. **Monitor the first few runs** to ensure correct behavior
7. **Keep backups** before running destructive operations

## Next Steps

- Schedule the agent to run automatically using Windows Task Scheduler or cron
- Create multiple configuration files for different deployment scenarios
- Extend the framework with custom agents for other automation tasks
