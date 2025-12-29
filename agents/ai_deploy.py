"""AI Deploy Agent - Synchronize files between source and destination."""
import os
import json
import fnmatch
import glob
import time
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Set, Optional, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from core.agent_base import AgentBase
from handlers.windows_share_handler import WindowsShareHandler
from handlers.ssh_handler import SSHHandler
from handlers.database_handler import DatabaseHandler
from utils.ssh_connection_pool import SSHConnectionPool


class AiDeployAgent(AgentBase):
    """Agent for deploying/synchronizing files from source to destination."""

    def __init__(self, config_path: str):
        """Initialize the AI Deploy agent."""
        super().__init__(config_path)
        self.source_handler = None
        self.dest_handler = None
        self.db_handler = None
        self.config_path = config_path
        self.cache_data = {}
        self.deployment_made_changes = False
        self.source_pool = None  # Connection pool for source (if SSH)
        self.dest_pool = None  # Connection pool for destination (if SSH)
        self.verbose = self.config.get('options', {}).get('verbose', True)  # Default: True for backward compatibility

    @staticmethod
    def _create_empty_cache() -> Dict[str, Any]:
        """Create empty cache structure with all required fields."""
        return {
            "last_deployment": None,
            "files": {},
            "database": {
                "last_deployment": None,
                "main_scripts": {},
                "tenant_scripts": {}
            },
            "web_tenants": {},
            "file_mappings": {}
        }

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize path to use forward slashes for cross-platform comparison."""
        return path.replace('\\', '/')

    def _log_section(self, title: str, level: str = 'warning') -> None:
        """Log a section header with separator lines."""
        log_func = getattr(self.logger, level)
        log_func("=" * 60)
        log_func(title)
        log_func("=" * 60)

    def _get_cache_path(self) -> str:
        """
        Get the cache file path based on config file path.
        Cache is stored in same directory as config file.

        Returns:
            Path to cache file
        """
        config_dir = os.path.dirname(self.config_path)
        config_name = os.path.splitext(os.path.basename(self.config_path))[0]
        cache_filename = f".deploy_cache_{config_name}.json"
        return os.path.join(config_dir, cache_filename)

    def _load_cache(self) -> Dict[str, Any]:
        """
        Load deployment cache from file.

        Returns:
            Cache dictionary or empty dict if file doesn't exist or is invalid
        """
        cache_path = self._get_cache_path()

        if not os.path.exists(cache_path):
            if self.verbose:
                self.logger.info(f"No cache file found at {cache_path}, treating as first deployment")
            return self._create_empty_cache()

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
                if self.verbose:
                    self.logger.info(f"Loaded cache from {cache_path}")
                return cache
        except Exception as e:
            self.logger.warning(f"Failed to load cache from {cache_path}: {e}")
            self.logger.warning("Treating as first deployment")
            return self._create_empty_cache()

    def _save_cache(self, cache_data: Dict[str, Any]) -> None:
        """
        Save deployment cache to file.

        Args:
            cache_data: Cache dictionary to save
        """
        cache_path = self._get_cache_path()

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)
                if self.verbose:
                    self.logger.info(f"Saved cache to {cache_path}")
        except Exception as e:
            self.logger.error(f"Failed to save cache to {cache_path}: {e}")

    def _update_file_cache(self, source_files: List[Dict]) -> None:
        """
        Update cache with current file metadata.

        Args:
            source_files: List of source files with metadata
        """
        files_cache = {}
        for f in source_files:
            normalized_path = self._normalize_path(f['path'])
            if not self._should_ignore(normalized_path):
                files_cache[normalized_path] = {
                    'mtime': f['modified_time'],
                    'size': f['size']
                }

        self.cache_data['files'] = files_cache
        self.cache_data['last_deployment'] = datetime.utcnow().isoformat() + 'Z'

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """Validate the configuration structure."""
        required_fields = ['agent_name', 'source', 'destination']
        for field in required_fields:
            if field not in config:
                raise ValueError(f"Missing required field in config: {field}")

        # Validate source
        self._validate_location_config(config['source'], 'source', config)

        # Validate destination
        self._validate_location_config(config['destination'], 'destination', config)

        # Validate tenants config if present
        if 'tenants' in config:
            self._validate_tenants_config(config['tenants'], config)

        # Validate website config if present
        if 'website' in config:
            self._validate_website_config(config['website'])

        # Validate database config if present
        if 'database' in config:
            self._validate_database_config(config['database'])


        # Validate options if present
        if 'options' in config:
            options = config['options']
            if not isinstance(options, dict):
                raise ValueError("options must be a dictionary")

            # Validate ignore_cache
            if 'ignore_cache' in options and not isinstance(options['ignore_cache'], bool):
                raise ValueError("options.ignore_cache must be a boolean")

            # Validate clean_install
            if 'clean_install' in options and not isinstance(options['clean_install'], bool):
                raise ValueError("options.clean_install must be a boolean")

            # Validate warn option
            if 'warn' in options:
                if not isinstance(options['warn'], bool):
                    raise ValueError("options.warn must be a boolean")

            # Validate max_concurrent_transfers
            if 'max_concurrent_transfers' in options:
                max_transfers = options['max_concurrent_transfers']
                if not isinstance(max_transfers, int):
                    raise ValueError("options.max_concurrent_transfers must be an integer")
                if max_transfers <= 0:
                    raise ValueError("options.max_concurrent_transfers must be greater than 0")

            # Validate verbose
            if 'verbose' in options and not isinstance(options['verbose'], bool):
                raise ValueError("options.verbose must be a boolean")

            # Validate migration_only
            if 'migration_only' in options and not isinstance(options['migration_only'], bool):
                raise ValueError("options.migration_only must be a boolean")

            # Validate that clean_install and migration_only are not both true
            if options.get('clean_install', False) and options.get('migration_only', False):
                raise ValueError("options.clean_install and options.migration_only cannot both be true")

    def _validate_location_config(self, location: Dict[str, Any], name: str, config: Dict[str, Any]) -> None:
        """Validate source or destination configuration."""
        if 'type' not in location:
            raise ValueError(f"Missing 'type' in {name} configuration")

        if location['type'] not in ['windows_share', 'ssh']:
            raise ValueError(f"Invalid type in {name}: {location['type']}")

        # For destination, path can be in website.path instead
        if name == 'destination':
            has_path_in_location = 'path' in location
            has_website_path = 'website' in config and 'path' in config['website']
            if not has_path_in_location and not has_website_path:
                raise ValueError(f"Missing 'path' in {name} configuration or website.path")
        else:
            # For source, path is required
            if 'path' not in location:
                raise ValueError(f"Missing 'path' in {name} configuration")

        if location['type'] == 'ssh':
            required_ssh = ['host', 'username']
            for field in required_ssh:
                if field not in location:
                    raise ValueError(f"Missing '{field}' in {name} SSH configuration")

            # Must have either password or key_file
            if 'password' not in location and 'key_file' not in location:
                raise ValueError(f"{name} SSH configuration must have either 'password' or 'key_file'")

    def _validate_tenants_config(self, tenants: Dict[str, Any], config: Dict[str, Any]) -> None:
        """Validate tenants configuration."""
        if not isinstance(tenants, dict):
            raise ValueError("tenants must be a dictionary")

        has_path = 'path' in tenants
        has_query = 'query' in tenants

        # Must have either path or query (query is preferred when both are present)
        if not has_path and not has_query:
            raise ValueError("tenants must have either 'path' or 'query'")

        # Validate path if present (directory containing tenant subdirectories)
        if has_path:
            tenants_path = tenants['path']
            if not os.path.exists(tenants_path):
                raise ValueError(f"tenants.path does not exist: {tenants_path}")
            if not os.path.isdir(tenants_path):
                raise ValueError(f"tenants.path is not a directory: {tenants_path}")

        # Validate query if present
        if has_query:
            query = tenants['query']
            if not isinstance(query, str) or not query.strip():
                raise ValueError("tenants.query must be a non-empty string")
            # Query requires database configuration
            if 'database' not in config or not config['database'].get('enabled', False):
                raise ValueError("tenants.query requires database configuration to be enabled")

    def _validate_website_config(self, website: Dict[str, Any]) -> None:
        """Validate website configuration."""
        # Validate path
        if 'path' not in website:
            raise ValueError("website.path is required")

        # Validate file_mappings if present
        if 'file_mappings' in website:
            self._validate_file_mappings(website['file_mappings'])

        # Validate set_permissions_script if present
        if 'set_permissions_script' in website:
            if not isinstance(website['set_permissions_script'], str):
                raise ValueError("website.set_permissions_script must be a string path")

        # Validate cronjobs config if present
        if 'cronjobs' in website:
            cronjobs_config = website['cronjobs']
            if not isinstance(cronjobs_config, dict):
                raise ValueError("website.cronjobs must be a dictionary")
            if 'script' in cronjobs_config:
                if not isinstance(cronjobs_config['script'], str):
                    raise ValueError("website.cronjobs.script must be a string path")
            if 'server_path' in cronjobs_config:
                if not isinstance(cronjobs_config['server_path'], str):
                    raise ValueError("website.cronjobs.server_path must be a string path")
            if 'local_path' in cronjobs_config:
                if not isinstance(cronjobs_config['local_path'], str):
                    raise ValueError("website.cronjobs.local_path must be a string path")
            if 'create_table_file' in cronjobs_config:
                if not isinstance(cronjobs_config['create_table_file'], str):
                    raise ValueError("website.cronjobs.create_table_file must be a string path")
            if 'insert_data_file' in cronjobs_config:
                if not isinstance(cronjobs_config['insert_data_file'], str):
                    raise ValueError("website.cronjobs.insert_data_file must be a string path")

        # Validate ignore if present
        if 'ignore' in website:
            ignore_config = website['ignore']
            if not isinstance(ignore_config, dict):
                raise ValueError("website.ignore must be a dictionary")

        # Validate pre_build config if present
        if 'pre_build' in website:
            self._validate_pre_build_config(website['pre_build'])

    def _validate_pre_build_config(self, pre_build: Dict[str, Any]) -> None:
        """Validate pre_build configuration."""
        if not isinstance(pre_build, dict):
            raise ValueError("website.pre_build must be a dictionary")

        # If not enabled, skip validation
        if not pre_build.get('enabled', False):
            return

        # Validate working_directory
        if 'working_directory' not in pre_build:
            raise ValueError("website.pre_build.working_directory is required when enabled")
        working_dir = pre_build['working_directory']
        if not isinstance(working_dir, str):
            raise ValueError("website.pre_build.working_directory must be a string")
        if not os.path.exists(working_dir):
            raise ValueError(f"website.pre_build.working_directory does not exist: {working_dir}")
        if not os.path.isdir(working_dir):
            raise ValueError(f"website.pre_build.working_directory is not a directory: {working_dir}")

        # Validate command
        if 'command' not in pre_build:
            raise ValueError("website.pre_build.command is required when enabled")
        if not isinstance(pre_build['command'], str) or not pre_build['command'].strip():
            raise ValueError("website.pre_build.command must be a non-empty string")

        # Validate watch_patterns
        if 'watch_patterns' not in pre_build:
            raise ValueError("website.pre_build.watch_patterns is required when enabled")
        watch_patterns = pre_build['watch_patterns']
        if not isinstance(watch_patterns, list):
            raise ValueError("website.pre_build.watch_patterns must be a list")
        if len(watch_patterns) == 0:
            raise ValueError("website.pre_build.watch_patterns must not be empty")
        for pattern in watch_patterns:
            if not isinstance(pattern, str) or not pattern.strip():
                raise ValueError("website.pre_build.watch_patterns must contain non-empty strings")

    def _validate_database_config(self, database: Dict[str, Any]) -> None:
        """Validate database configuration."""
        if not database.get('enabled', False):
            return  # Database deployment is disabled

        required_fields = ['ssh_host', 'admin_username', 'admin_password']
        for field in required_fields:
            if field not in database:
                raise ValueError(f"Missing '{field}' in database configuration")

        # Must have either SSH password or key_file
        if 'ssh_password' not in database and 'ssh_key_file' not in database:
            raise ValueError("Database configuration must have either 'ssh_password' or 'ssh_key_file'")

        # Validate main_database_scripts config if present
        if 'main_database_scripts' in database:
            scripts = database['main_database_scripts']
            # Check required fields
            if 'db_name' not in scripts:
                raise ValueError("main_database_scripts must have 'db_name'")
            if 'db_username' not in scripts:
                raise ValueError("main_database_scripts must have 'db_username'")
            if 'db_password' not in scripts:
                raise ValueError("main_database_scripts must have 'db_password'")
            # Check that at least one script path is provided
            if not any([
                scripts.get('setup_path'),
                scripts.get('tables_path'),
                scripts.get('procedures_path'),
                scripts.get('data_path')
            ]):
                raise ValueError("main_database_scripts must have at least one script path")

        # Validate tenant-database config if present
        if 'tenant-database' in database:
            tenant_db_config = database['tenant-database']
            if not isinstance(tenant_db_config, dict):
                raise ValueError("database.tenant-database must be a dictionary")

            if tenant_db_config.get('enabled', False):
                # Check required fields
                if 'db_name' not in tenant_db_config:
                    raise ValueError("database.tenant-database must have 'db_name' template when enabled")
                if 'db_username' not in tenant_db_config:
                    raise ValueError("database.tenant-database must have 'db_username' when enabled")
                if 'db_password' not in tenant_db_config:
                    raise ValueError("database.tenant-database must have 'db_password' when enabled")


    def _validate_file_mappings(self, file_mappings: List[Dict[str, str]]) -> None:
        """Validate file mappings configuration."""
        if not isinstance(file_mappings, list):
            raise ValueError("file_mappings must be a list")

        for idx, mapping in enumerate(file_mappings):
            if not isinstance(mapping, dict):
                raise ValueError(f"file_mappings[{idx}] must be a dictionary")

            if 'source' not in mapping:
                raise ValueError(f"file_mappings[{idx}] missing 'source' field")

            if 'destination' not in mapping:
                raise ValueError(f"file_mappings[{idx}] missing 'destination' field")

    def _load_tenant_configs(self) -> List[Dict[str, Any]]:
        """
        Load tenant configurations from database query or by scanning subdirectories.

        If tenants.query is specified, queries the database for tenant webids.
        Otherwise, scans the tenants.path directory for subdirectories.

        Returns:
            List of tenant configuration dictionaries
        """
        tenants_config = self.config.get('tenants', {})
        tenants_query = tenants_config.get('query')
        tenants_path = tenants_config.get('path')

        tenant_configs = []

        # Prefer query over path if both are specified
        if tenants_query and self.db_handler:
            # Query the database for tenant webids
            try:
                # Get the main database name for the query
                database_config = self.config.get('database', {})
                main_db_name = database_config.get('main_database_scripts', {}).get('db_name')

                self.logger.info(f"Querying database for tenants: {tenants_query}")
                results = self.db_handler.execute_query(tenants_query, database_name=main_db_name)

                for row in results:
                    # Get the webid from the first column (or 'value' key for single-column results)
                    webid = row.get('value') or row.get('col_0')
                    if webid:
                        tenant_data = {
                            'webid': webid,
                            '_tenant_path': None  # No local path when using query
                        }
                        tenant_configs.append(tenant_data)

                self.logger.info(f"Found {len(tenant_configs)} tenant(s) from database query")

            except Exception as e:
                self.logger.error(f"Failed to query tenants from database: {e}")
                return []

        elif tenants_path and os.path.exists(tenants_path):
            # Scan directory for tenant subdirectories
            try:
                for item in sorted(os.listdir(tenants_path)):
                    item_path = os.path.join(tenants_path, item)

                    # Skip files and hidden directories
                    if not os.path.isdir(item_path) or item.startswith('.') or item.startswith('_'):
                        continue

                    # Create tenant config with subdirectory name as webid
                    tenant_data = {
                        'webid': item,
                        '_tenant_path': item_path
                    }
                    tenant_configs.append(tenant_data)
            except Exception as e:
                self.logger.warning(f"Failed to scan tenant directories in {tenants_path}: {e}")

        return tenant_configs

    def _replace_template_variables(self, template_str: str, tenant_data: Dict[str, Any]) -> str:
        """
        Replace template variables like {{WEBID}} with actual values from tenant data.

        Args:
            template_str: String containing template variables
            tenant_data: Tenant configuration dictionary

        Returns:
            String with variables replaced
        """
        if not template_str:
            return template_str

        result = template_str

        # Replace {{WEBID}} with tenant webid
        if '{{WEBID}}' in result:
            webid = tenant_data.get('webid', '')
            result = result.replace('{{WEBID}}', webid)

        # Add more template variables as needed

        return result

    def _build_tenant_database_configs(self) -> List[Dict[str, Any]]:
        """
        Build tenant database configurations from template and tenant data.

        Returns:
            List of tenant database configurations
        """
        database_config = self.config.get('database', {})

        if not database_config or not database_config.get('enabled', False):
            return []

        tenant_db_config = database_config.get('tenant-database', {})

        if not tenant_db_config.get('enabled', False):
            return []

        tenant_configs = self._load_tenant_configs()
        if not tenant_configs:
            return []

        tenant_database_configs = []

        for tenant_data in tenant_configs:
            webid = tenant_data.get('webid')

            if not webid:
                continue

            # Build tenant-specific database config by replacing template variables
            db_config = {
                'db_name': self._replace_template_variables(
                    tenant_db_config.get('db_name', ''),
                    tenant_data
                ),
                'db_username': tenant_db_config.get('db_username'),
                'db_password': tenant_db_config.get('db_password')
            }

            # Add optional script paths if present
            if 'setup_path' in tenant_db_config:
                db_config['setup_path'] = tenant_db_config['setup_path']
            if 'tables_path' in tenant_db_config:
                db_config['tables_path'] = tenant_db_config['tables_path']
            if 'procedures_path' in tenant_db_config:
                db_config['procedures_path'] = tenant_db_config['procedures_path']
            if 'data_path' in tenant_db_config:
                db_config['data_path'] = tenant_db_config['data_path']
            if 'migration_path' in tenant_db_config:
                db_config['migration_path'] = tenant_db_config['migration_path']

            tenant_database_configs.append(db_config)

        return tenant_database_configs

    def _create_handler(self, location_config: Dict[str, Any], path_override: str = None):
        """Create appropriate handler based on location configuration."""
        location_type = location_config['type']

        # Use path_override if provided (for destination with website.path)
        path = path_override if path_override else location_config['path']

        if location_type == 'windows_share':
            handler = WindowsShareHandler(
                path=path,
                username=location_config.get('username'),
                password=location_config.get('password')
            )
        elif location_type == 'ssh':
            handler = SSHHandler(
                host=location_config['host'],
                path=path,
                username=location_config['username'],
                password=location_config.get('password'),
                key_file=location_config.get('key_file'),
                passphrase=location_config.get('passphrase'),
                port=location_config.get('port', 22)
            )
        else:
            raise ValueError(f"Unsupported location type: {location_type}")

        return handler

    def _create_database_handler(self, database_config: Dict[str, Any]):
        """Create database handler based on configuration."""
        # Extract db_name from main_database_scripts if available
        db_name = None
        if 'main_database_scripts' in database_config:
            db_name = database_config['main_database_scripts'].get('db_name')

        # Use admin credentials for database connection
        admin_username = database_config.get('admin_username')
        admin_password = database_config.get('admin_password')

        handler = DatabaseHandler(
            ssh_host=database_config['ssh_host'],
            ssh_username=database_config.get('ssh_username', admin_username),
            ssh_password=database_config.get('ssh_password'),
            ssh_key_file=database_config.get('ssh_key_file'),
            ssh_passphrase=database_config.get('ssh_passphrase'),
            ssh_port=database_config.get('ssh_port', 22),
            db_host=database_config.get('db_host', '127.0.0.1'),
            db_port=database_config.get('db_port', 3306),
            db_username=admin_username,
            db_password=admin_password,
            db_name=db_name,
            logger=self.logger
        )
        return handler

    def _should_run_pre_build(self) -> Tuple[bool, List[str]]:
        """
        Check if pre-build should run based on source file changes.

        Returns:
            Tuple of (should_run, changed_files)
        """
        website_config = self.config.get('website', {})
        pre_build_config = website_config.get('pre_build', {})

        if not pre_build_config.get('enabled', False):
            return False, []

        working_dir = pre_build_config['working_directory']
        watch_patterns = pre_build_config['watch_patterns']

        # Get cached file mtimes
        cached_pre_build = self.cache_data.get('pre_build', {})
        cached_files = cached_pre_build.get('files', {})

        changed_files = []

        for pattern in watch_patterns:
            # Use glob to find all matching files
            full_pattern = os.path.join(working_dir, pattern)
            matched_files = glob.glob(full_pattern, recursive=True)

            for file_path in matched_files:
                if not os.path.isfile(file_path):
                    continue

                # Get relative path for cache key
                rel_path = os.path.relpath(file_path, working_dir)
                rel_path = self._normalize_path(rel_path)

                try:
                    current_mtime = os.path.getmtime(file_path)
                except OSError:
                    continue

                cached_mtime = cached_files.get(rel_path)

                # File is new or modified
                if cached_mtime is None or current_mtime > cached_mtime:
                    changed_files.append(rel_path)

        return len(changed_files) > 0, changed_files

    def _execute_pre_build(self) -> bool:
        """
        Execute the pre-build command.

        Returns:
            True if build succeeded, raises exception on failure
        """
        website_config = self.config.get('website', {})
        pre_build_config = website_config.get('pre_build', {})

        working_dir = pre_build_config['working_directory']
        command = pre_build_config['command']

        self.logger.warning(f"Running: {command}")
        self.logger.warning(f"Working directory: {working_dir}")

        dry_run = self.config.get('options', {}).get('dry_run', False)
        if dry_run:
            self.logger.warning("  [DRY RUN] Would execute pre-build command")
            return True

        try:
            # Pass current environment to ensure PATH is available (important for npm on Windows)
            result = subprocess.run(
                command,
                shell=True,
                cwd=working_dir,
                capture_output=True,
                text=True,
                env=os.environ.copy()
            )

            # Log stdout line by line
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        self.logger.warning(f"  {line}")

            # Check for failure
            if result.returncode != 0:
                self.logger.error(f"Pre-build failed with exit code {result.returncode}")
                if result.stderr:
                    for line in result.stderr.strip().split('\n'):
                        if line:
                            self.logger.error(f"  {line}")
                raise RuntimeError(f"Pre-build failed: {command}")

            self.logger.warning("Pre-build complete")

            # Update cache with new file mtimes
            self._update_pre_build_cache()

            return True

        except subprocess.SubprocessError as e:
            self.logger.error(f"Failed to execute pre-build command: {e}")
            raise RuntimeError(f"Pre-build execution failed: {e}")

    def _update_pre_build_cache(self) -> None:
        """Update the pre-build cache with current file mtimes."""
        website_config = self.config.get('website', {})
        pre_build_config = website_config.get('pre_build', {})

        if not pre_build_config.get('enabled', False):
            return

        working_dir = pre_build_config['working_directory']
        watch_patterns = pre_build_config['watch_patterns']

        files_cache = {}

        for pattern in watch_patterns:
            full_pattern = os.path.join(working_dir, pattern)
            matched_files = glob.glob(full_pattern, recursive=True)

            for file_path in matched_files:
                if not os.path.isfile(file_path):
                    continue

                rel_path = os.path.relpath(file_path, working_dir)
                rel_path = self._normalize_path(rel_path)

                try:
                    files_cache[rel_path] = os.path.getmtime(file_path)
                except OSError:
                    continue

        # Update cache structure
        if 'pre_build' not in self.cache_data:
            self.cache_data['pre_build'] = {}

        self.cache_data['pre_build']['last_build_timestamp'] = time.time()
        self.cache_data['pre_build']['files'] = files_cache

    def _should_ignore(self, file_path: str) -> bool:
        """
        Check if a file should be ignored based on configuration.

        Args:
            file_path: Relative path to the file

        Returns:
            True if file should be ignored
        """
        # Get ignore config from website section if available
        website_config = self.config.get('website', {})
        ignore_config = website_config.get('ignore', {})

        # Normalize path for consistent comparison
        normalized_path = self._normalize_path(file_path)

        # Check ignored files
        for pattern in ignore_config.get('files', []):
            if fnmatch.fnmatch(file_path, pattern):
                return True

        # Check ignored folders
        path_parts = Path(file_path).parts
        for pattern in ignore_config.get('folders', []):
            # Normalize pattern to use forward slashes
            normalized_pattern = pattern.replace('\\', '/')

            # Check if pattern contains path separator (e.g., "web/tenants")
            if '/' in normalized_pattern:
                # Check if the file path starts with or contains the folder pattern
                if normalized_path.startswith(normalized_pattern + '/') or normalized_path == normalized_pattern:
                    return True
                # Also check if pattern appears as a path segment
                if ('/' + normalized_pattern + '/') in ('/' + normalized_path):
                    return True
            else:
                # Simple folder name - check against individual path parts
                for part in path_parts:
                    if fnmatch.fnmatch(part, pattern):
                        return True

        # Check ignored extensions
        file_ext = Path(file_path).suffix
        if file_ext in ignore_config.get('extensions', []):
            return True

        return False

    def _compare_files(self, source_files: List[Dict], dest_files: List[Dict]) -> Tuple[List[Dict], List[Dict], List[str]]:
        """
        Compare source and destination files to determine changes.
        Uses cache to skip unchanged files for faster incremental deployments.

        Args:
            source_files: List of source file information
            dest_files: List of destination file information (empty if using cache-only mode)

        Returns:
            Tuple of (new_files, modified_files, deleted_files)
        """
        ignore_cache = self.config.get('options', {}).get('ignore_cache', False)
        clean_install = self.config.get('options', {}).get('clean_install', False)
        cached_files = self.cache_data.get('files', {})

        # Check if we're in cache-only mode (dest_files is empty and we have cache)
        using_cache_only = len(dest_files) == 0 and len(cached_files) > 0 and not clean_install and not ignore_cache

        # Normalize all paths to use forward slashes for comparison
        # Create dictionaries for quick lookup
        source_dict = {}
        for f in source_files:
            normalized_path = self._normalize_path(f['path'])
            if not self._should_ignore(normalized_path):
                # Store with normalized path but keep original file info
                f_copy = f.copy()
                f_copy['path'] = normalized_path
                source_dict[normalized_path] = f_copy

        dest_dict = {}
        if using_cache_only:
            # Use cache as destination - create synthetic file entries from cache
            for cached_path, cached_info in cached_files.items():
                if not self._should_ignore(cached_path):
                    dest_dict[cached_path] = {
                        'path': cached_path,
                        'size': cached_info.get('size', 0),
                        'modified_time': cached_info.get('mtime', 0),
                        'is_directory': False
                    }
        else:
            # Use actual destination files
            for f in dest_files:
                normalized_path = self._normalize_path(f['path'])
                f_copy = f.copy()
                f_copy['path'] = normalized_path
                dest_dict[normalized_path] = f_copy

        new_files = []
        modified_files = []
        deleted_files = []

        # Find new and modified files
        for path, source_file in source_dict.items():
            if path not in dest_dict:
                # New file
                new_files.append(source_file)
            else:
                # File exists on destination (or in cache)
                # Check cache first if enabled
                if not ignore_cache and path in cached_files:
                    cached_info = cached_files[path]
                    # Skip file if it hasn't changed since last deployment
                    if (source_file['size'] == cached_info.get('size') and
                        source_file['modified_time'] == cached_info.get('mtime')):
                        # File unchanged, skip it
                        continue

                # Either cache disabled, file not in cache, or file changed
                dest_file = dest_dict[path]
                # Check if modified (compare size and modification time)
                if (source_file['size'] != dest_file['size'] or
                    source_file['modified_time'] > dest_file['modified_time']):
                    modified_files.append(source_file)

        # Get file mapping destinations to exclude from deletion
        file_mapping_dests = set()
        website_config = self.config.get('website', {})
        for mapping in website_config.get('file_mappings', []):
            dest_path = mapping['destination'].replace('\\', '/')
            file_mapping_dests.add(dest_path)

        # Find deleted files
        # When using cache-only mode, we trust the cache and don't delete files
        # (avoids accidentally deleting files that exist on destination but not in cache)
        if not using_cache_only:
            for path in dest_dict:
                if path not in source_dict:
                    # File exists in destination but not in source (and not ignored)
                    # Skip if this file is created by file mappings
                    if path in file_mapping_dests:
                        continue
                    # Only mark for deletion if it's not being ignored
                    if not self._should_ignore(path):
                        deleted_files.append(path)

        return new_files, modified_files, deleted_files

    def _transfer_file_worker(self, file_info: Dict, operation: str, dry_run: bool) -> Tuple[bool, str, str]:
        """
        Worker function for parallel file transfers.
        Uses connection pools for SSH to enable true parallelism.

        Args:
            file_info: File information dictionary with 'path' key
            operation: Type of operation ('copy', 'update', 'delete')
            dry_run: Whether this is a dry run

        Returns:
            Tuple of (success, file_path, error_message)
        """
        file_path = file_info['path'] if isinstance(file_info, dict) else file_info

        # Get handlers from pools or use main handler
        source_handler = self.source_pool.get_handler() if self.source_pool else self.source_handler
        dest_handler = self.dest_pool.get_handler() if self.dest_pool else self.dest_handler

        try:
            # Check if we got valid handlers from the pool
            if source_handler is None and self.source_pool:
                return (False, file_path, 'Timeout waiting for source connection from pool')
            if dest_handler is None and self.dest_pool:
                return (False, file_path, 'Timeout waiting for destination connection from pool')

            if operation in ['copy', 'update']:
                if not dry_run:
                    content = source_handler.read_file(file_path)
                    dest_handler.write_file(file_path, content)
            elif operation == 'delete':
                if not dry_run:
                    dest_handler.delete_file(file_path)

            return (True, file_path, '')
        except Exception as e:
            # Include exception type for better debugging
            error_msg = f"{type(e).__name__}: {str(e)}"
            return (False, file_path, error_msg)
        finally:
            # Return handlers to pools
            if self.source_pool and source_handler:
                self.source_pool.return_handler(source_handler)
            if self.dest_pool and dest_handler:
                self.dest_pool.return_handler(dest_handler)

    def _sync_files(self, new_files: List[Dict], modified_files: List[Dict], deleted_files: List[str]) -> None:
        """
        Synchronize files from source to destination using parallel transfers.
        Creates connection pools for SSH to enable true parallelism.

        Args:
            new_files: List of new files to copy
            modified_files: List of modified files to update
            deleted_files: List of files to delete from destination
        """
        dry_run = self.config.get('options', {}).get('dry_run', False)
        clean_install = self.config.get('options', {}).get('clean_install', False)
        max_workers = self.config.get('options', {}).get('max_concurrent_transfers', 20)

        # Check if source or destination uses SSH
        is_source_ssh = self.config.get('source', {}).get('type') == 'ssh'
        is_dest_ssh = self.config.get('destination', {}).get('type') == 'ssh'

        # Calculate total file changes
        total_file_changes = len(new_files) + len(modified_files) + len(deleted_files)

        # Skip connection pools if clean_install=false and total changes < 10
        # For small deployments, the overhead of creating pools isn't worth it
        skip_pools = not clean_install and total_file_changes < 10
        use_parallel = not skip_pools and max_workers > 1

        if skip_pools and self.verbose:
            self.logger.info(f"Using single connection for small deployment ({total_file_changes} file changes)")

        # Initialize connection pools for SSH (one pool per SSH endpoint)
        if is_source_ssh and use_parallel:
            pool_size = max_workers  # Match pool size to max workers to avoid timeouts
            self.source_pool = SSHConnectionPool(self.config['source'], pool_size)
            self.source_pool.initialize()
            if self.verbose:
                self.logger.info(f"Created SSH connection pool for source ({pool_size} connections)")

        if is_dest_ssh and use_parallel:
            pool_size = max_workers  # Match pool size to max workers to avoid timeouts
            # Merge destination config with website path
            website_config = self.config.get('website', {})
            dest_config = self.config['destination'].copy()
            if 'path' in website_config:
                dest_config['path'] = website_config['path']
            self.dest_pool = SSHConnectionPool(dest_config, pool_size)
            self.dest_pool.initialize()
            if self.verbose:
                self.logger.info(f"Created SSH connection pool for destination ({pool_size} connections)")

        if (is_source_ssh or is_dest_ssh) and use_parallel:
            self.logger.info(f"Using {max_workers} parallel file transfers with connection pooling")

        # Adjust max_workers based on whether we're using pools
        actual_max_workers = max_workers if use_parallel else 1

        # Copy new files in parallel
        if new_files:
            self.logger.info(f"New files to copy: {len(new_files)}")
            with ThreadPoolExecutor(max_workers=actual_max_workers) as executor:
                futures = {
                    executor.submit(self._transfer_file_worker, file_info, 'copy', dry_run): file_info
                    for file_info in new_files
                }

                completed = 0
                for future in as_completed(futures):
                    success, file_path, error = future.result()
                    completed += 1
                    if success:
                        self.logger.info(f"  [{completed}/{len(new_files)}] Copied: {file_path}")
                    else:
                        self.logger.error(f"  [{completed}/{len(new_files)}] Error copying {file_path}: {error}")

        # Update modified files in parallel
        if modified_files:
            self.logger.info(f"Modified files to update: {len(modified_files)}")
            with ThreadPoolExecutor(max_workers=actual_max_workers) as executor:
                futures = {
                    executor.submit(self._transfer_file_worker, file_info, 'update', dry_run): file_info
                    for file_info in modified_files
                }

                completed = 0
                for future in as_completed(futures):
                    success, file_path, error = future.result()
                    completed += 1
                    if success:
                        self.logger.info(f"  [{completed}/{len(modified_files)}] Updated: {file_path}")
                    else:
                        self.logger.error(f"  [{completed}/{len(modified_files)}] Error updating {file_path}: {error}")

        # Delete files from destination in parallel
        delete_enabled = self.config.get('options', {}).get('delete_extra_files', True)
        if delete_enabled and deleted_files:
            self.logger.info(f"Files to delete from destination: {len(deleted_files)}")
            with ThreadPoolExecutor(max_workers=actual_max_workers) as executor:
                # Convert strings to dict format for consistency
                file_dicts = [{'path': path} for path in deleted_files]
                futures = {
                    executor.submit(self._transfer_file_worker, file_dict, 'delete', dry_run): file_dict
                    for file_dict in file_dicts
                }

                completed = 0
                for future in as_completed(futures):
                    success, file_path, error = future.result()
                    completed += 1
                    if success:
                        self.logger.info(f"  [{completed}/{len(deleted_files)}] Deleted: {file_path}")
                    else:
                        self.logger.error(f"  [{completed}/{len(deleted_files)}] Error deleting {file_path}: {error}")
        elif not delete_enabled:
            self.logger.info("Deletion of extra files is disabled")

    def _process_file_mappings(self) -> None:
        """
        Process file mappings - copy source files to destination with different names.
        This allows environment-specific files to be deployed with different names.
        Only copies files that have changed since last deployment.
        """
        website_config = self.config.get('website', {})
        file_mappings = website_config.get('file_mappings', [])

        if not file_mappings:
            return

        dry_run = self.config.get('options', {}).get('dry_run', False)
        ignore_cache = self.config.get('options', {}).get('ignore_cache', False)

        # Get cached file mapping metadata
        file_mappings_cache = self.cache_data.get('file_mappings', {})

        self.logger.warning("=" * 60)
        self.logger.warning("FILE MAPPINGS")
        self.logger.warning("=" * 60)
        self.logger.warning(f"Processing {len(file_mappings)} file mapping(s)")

        files_copied = 0

        for mapping in file_mappings:
            source_path = mapping['source']
            dest_path = mapping['destination']

            try:
                # Check if file has changed
                needs_copy = True
                if not ignore_cache and os.path.isabs(source_path) and os.path.exists(source_path):
                    source_mtime = os.path.getmtime(source_path)
                    cached_mtime = file_mappings_cache.get(source_path, {}).get('mtime', 0)

                    if source_mtime == cached_mtime:
                        # File unchanged, skip it
                        needs_copy = False
                        if self.verbose:
                            self.logger.info(f"  Skipping unchanged mapping: {os.path.basename(source_path)}")

                if not needs_copy:
                    continue

                # Convert to relative path if it's an absolute path
                # If source is absolute, extract just the filename for reading
                if os.path.isabs(source_path):
                    # Read directly from absolute path
                    self.logger.info(f"  Mapping: {source_path} -> {dest_path}")

                    if dry_run:
                        self.logger.info(f"    [DRY RUN] Would copy and rename file")
                        # Check if source exists
                        if not os.path.exists(source_path):
                            self.logger.error(f"    Source file not found: {source_path}")
                    else:
                        # Read from absolute path on local system
                        with open(source_path, 'rb') as f:
                            content = f.read()

                        # Write to destination with new name
                        self.dest_handler.write_file(dest_path, content)
                        self.logger.info(f"    ✓ Successfully copied and renamed")
                        files_copied += 1

                        # Update cache
                        if source_path not in file_mappings_cache:
                            file_mappings_cache[source_path] = {}
                        file_mappings_cache[source_path]['mtime'] = os.path.getmtime(source_path)
                else:
                    # Source is relative path - read from source handler
                    self.logger.info(f"  Mapping: {source_path} -> {dest_path}")

                    if dry_run:
                        self.logger.info(f"    [DRY RUN] Would copy and rename file")
                    else:
                        content = self.source_handler.read_file(source_path)
                        self.dest_handler.write_file(dest_path, content)
                        self.logger.info(f"    ✓ Successfully copied and renamed")
                        files_copied += 1

            except Exception as e:
                self.logger.error(f"  Error processing mapping {source_path} -> {dest_path}: {e}")

        # Update cache and change flag if files were copied
        if files_copied > 0:
            self.deployment_made_changes = True
            self.cache_data['file_mappings'] = file_mappings_cache
            self.logger.info(f"Copied {files_copied} file mapping(s)")
        else:
            self.logger.info("No file mappings needed to be copied")

    def _has_database_files_changed(self, database_config: dict, last_deployment_timestamp: float) -> bool:
        """
        Check if any database files have been modified since last deployment.

        Args:
            database_config: Database configuration dictionary
            last_deployment_timestamp: Unix timestamp of last deployment

        Returns:
            True if any database files have changed, False otherwise
        """
        try:
            migration_only = self.config.get('options', {}).get('migration_only', False)

            # Check main database scripts
            main_database_scripts = database_config.get('main_database_scripts')
            if main_database_scripts:
                # Determine which script types to check based on migration_only
                if migration_only:
                    script_types = ['migration_path']
                else:
                    script_types = ['setup_path', 'tables_path', 'procedures_path', 'data_path']

                for script_type in script_types:
                    script_path = main_database_scripts.get(script_type)
                    if script_path and os.path.exists(script_path):
                        if os.path.isfile(script_path):
                            # Single file
                            if os.path.getmtime(script_path) > last_deployment_timestamp:
                                self.logger.debug(f"Database file changed: {script_path}")
                                return True
                        elif os.path.isdir(script_path):
                            # Directory - check all .sql files
                            for root, dirs, files in os.walk(script_path):
                                for file in files:
                                    if file.endswith('.sql'):
                                        file_path = os.path.join(root, file)
                                        if os.path.getmtime(file_path) > last_deployment_timestamp:
                                            self.logger.debug(f"Database file changed: {file_path}")
                                            return True

            # Check tenant database scripts
            # For migration_only, we need to check migration_path from the tenant-database config template
            tenant_db_config = database_config.get('tenant-database', {})
            if tenant_db_config.get('enabled', False):
                # Determine which script types to check based on migration_only
                if migration_only:
                    script_types = ['migration_path']
                else:
                    script_types = ['setup_path', 'tables_path', 'procedures_path', 'data_path']

                for script_type in script_types:
                    script_path = tenant_db_config.get(script_type)
                    if script_path and os.path.exists(script_path):
                        if os.path.isfile(script_path):
                            # Single file
                            if os.path.getmtime(script_path) > last_deployment_timestamp:
                                self.logger.debug(f"Database file changed: {script_path}")
                                return True
                        elif os.path.isdir(script_path):
                            # Directory - check all .sql files
                            for root, dirs, files in os.walk(script_path):
                                for file in files:
                                    if file.endswith('.sql'):
                                        file_path = os.path.join(root, file)
                                        if os.path.getmtime(file_path) > last_deployment_timestamp:
                                            self.logger.debug(f"Database file changed: {file_path}")
                                            return True

            # Check tenant data scripts (skip if migration_only)
            if not migration_only:
                tenant_data_scripts = database_config.get('tenant_data_scripts')
                if tenant_data_scripts and tenant_data_scripts.get('enabled'):
                    data_path = tenant_data_scripts.get('data_path')
                    if data_path and os.path.exists(data_path) and os.path.isdir(data_path):
                        for root, dirs, files in os.walk(data_path):
                            for file in files:
                                if file.endswith('.sql'):
                                    file_path = os.path.join(root, file)
                                    if os.path.getmtime(file_path) > last_deployment_timestamp:
                                        self.logger.debug(f"Tenant data file changed: {file_path}")
                                        return True

            return False

        except Exception as e:
            self.logger.error(f"Error checking database file changes: {e}")
            # On error, assume files have changed to be safe
            return True

    def _deploy_database(self) -> None:
        """Deploy database scripts if database configuration is present."""
        database_config = self.config.get('database')

        if not database_config or not database_config.get('enabled', False):
            self.logger.info("Database deployment is disabled")
            return

        try:
            dry_run = self.config.get('options', {}).get('dry_run', False)
            ignore_cache = self.config.get('options', {}).get('ignore_cache', False)
            clean_install = self.config.get('options', {}).get('clean_install', False)
            migration_only = self.config.get('options', {}).get('migration_only', False)

            # Get last deployment timestamp from cache
            db_cache = self.cache_data.get('database', {})
            last_deployment_timestamp = db_cache.get('last_deployment_timestamp')

            if ignore_cache or clean_install:
                last_deployment_timestamp = None

            # Skip database deployment if clean_install is false and no files have changed
            if not clean_install and last_deployment_timestamp is not None:
                if not self._has_database_files_changed(database_config, last_deployment_timestamp):
                    self.logger.info("=" * 60)
                    self.logger.info("DATABASE DEPLOYMENT SKIPPED")
                    self.logger.info("=" * 60)
                    self.logger.info("No database files have changed since last deployment")
                    return

            self.logger.warning("=" * 60)
            if migration_only:
                self.logger.warning("DATABASE MIGRATION")
            else:
                self.logger.warning("DATABASE DEPLOYMENT")
            self.logger.warning("=" * 60)

            # Create database handler
            if self.verbose:
                self.logger.info("Creating database handler...")
            self.db_handler = self._create_database_handler(database_config)

            # Connect to SSH
            if self.verbose:
                self.logger.info("Connecting to database server via SSH...")
            if not self.db_handler.connect():
                self.logger.error("Failed to connect to database server")
                return

            # Get admin credentials and script configurations
            admin_username = database_config.get('admin_username')
            admin_password = database_config.get('admin_password')
            main_database_scripts = database_config.get('main_database_scripts')
            tenant_data_scripts = database_config.get('tenant_data_scripts')

            # Build dynamic tenant database configs from tenant data
            tenant_database_scripts = self._build_tenant_database_configs()

            # Deploy database with timestamp for incremental deployment
            success, any_scripts_executed = self.db_handler.deploy_database(
                admin_username=admin_username,
                admin_password=admin_password,
                main_database_scripts=main_database_scripts,
                tenant_database_scripts=tenant_database_scripts,
                tenant_data_scripts=tenant_data_scripts,
                dry_run=dry_run,
                last_deployment_timestamp=last_deployment_timestamp,
                application_name=self.config.get('application_name'),
                migration_only=migration_only
            )

            if success:
                # Update cache with current timestamp only if scripts were executed
                if not dry_run and any_scripts_executed:
                    self.deployment_made_changes = True
                    if 'database' not in self.cache_data:
                        self.cache_data['database'] = {}
                    self.cache_data['database']['last_deployment_timestamp'] = time.time()
                    self.cache_data['database']['last_deployment'] = datetime.utcnow().isoformat() + 'Z'

                self.logger.warning("=" * 60)
                self.logger.warning("Database deployment completed successfully!")
                self.logger.warning("=" * 60)
            else:
                self.logger.error("Database deployment completed with errors")

        except Exception as e:
            self.logger.error(f"Error during database deployment: {e}")
        finally:
            if self.db_handler:
                self.db_handler.disconnect()

    def _clean_website_directory(self) -> None:
        """Delete all files and folders under website.path on destination server."""
        website_config = self.config.get('website', {})
        website_path = website_config.get('path')

        if not website_path:
            self.logger.warning("No website.path configured, skipping directory cleanup")
            return

        dry_run = self.config.get('options', {}).get('dry_run', False)

        self.logger.info("=" * 60)
        self.logger.info("CLEANING WEBSITE DIRECTORY")
        self.logger.info("=" * 60)
        self.logger.warning(f"This will DELETE ALL files and folders in: {website_path}")

        try:
            # Check if destination is SSH (most efficient for recursive deletion)
            if self.config['destination']['type'] == 'ssh' and hasattr(self.dest_handler, 'ssh_client'):
                ssh_client = self.dest_handler.ssh_client
                ssh_password = self.config['destination'].get('password', '')

                if dry_run:
                    # List what would be deleted
                    list_cmd = f"find {website_path} -mindepth 1"
                    stdin, stdout, stderr = ssh_client.exec_command(list_cmd)
                    items = stdout.read().decode().strip().split('\n')
                    items = [item for item in items if item]  # Remove empty strings

                    self.logger.info(f"[DRY RUN] Would delete {len(items)} items from {website_path}")
                    for item in items[:10]:  # Show first 10 items
                        self.logger.info(f"  [DRY RUN] Would delete: {item.replace(website_path + '/', '')}")
                    if len(items) > 10:
                        self.logger.info(f"  [DRY RUN] ... and {len(items) - 10} more items")
                else:
                    # Use sudo rm -rf to recursively delete all contents (handles permission issues)
                    # Delete hidden files separately to avoid issues with .* expansion
                    delete_cmd = f"echo '{ssh_password}' | sudo -S bash -c 'rm -rf {website_path}/* {website_path}/.[!.]* {website_path}/..?*' 2>&1"
                    stdin, stdout, stderr = ssh_client.exec_command(delete_cmd)

                    # Read output and filter sudo password prompts
                    output = stdout.read().decode()
                    exit_status = stdout.channel.recv_exit_status()

                    # Filter out sudo password prompts and "No such file" errors for hidden files
                    error_lines = [line for line in output.split('\n')
                                  if line.strip()
                                  and '[sudo]' not in line.lower()
                                  and 'password' not in line.lower()
                                  and 'no such file or directory' not in line.lower()]

                    if exit_status == 0:
                        self.logger.info(f"✓ Successfully deleted all contents of {website_path}")
                    else:
                        # Only log actual errors
                        if error_lines:
                            self.logger.error(f"Error deleting directory contents: {chr(10).join(error_lines)}")
                        else:
                            # Exit status non-zero but no real errors (probably just missing hidden files)
                            self.logger.info(f"✓ Successfully deleted all contents of {website_path}")

            else:
                # Fallback for non-SSH: list recursively and delete in reverse order (deepest first)
                all_items = self.dest_handler.list_files(recursive=True)

                if dry_run:
                    self.logger.info(f"[DRY RUN] Would delete {len(all_items)} items from {website_path}")
                    for item in all_items[:10]:
                        item_type = "directory" if item['is_directory'] else "file"
                        self.logger.info(f"  [DRY RUN] Would delete {item_type}: {item['path']}")
                    if len(all_items) > 10:
                        self.logger.info(f"  [DRY RUN] ... and {len(all_items) - 10} more items")
                else:
                    # Sort by path depth (deepest first) to delete files before their parent directories
                    sorted_items = sorted(all_items, key=lambda x: x['path'].count('/'), reverse=True)

                    deleted_files = 0
                    deleted_dirs = 0

                    for item in sorted_items:
                        if item['is_directory']:
                            try:
                                self.dest_handler.delete_directory(item['path'])
                                deleted_dirs += 1
                            except Exception as e:
                                self.logger.error(f"  Error deleting directory {item['path']}: {e}")
                        else:
                            try:
                                self.dest_handler.delete_file(item['path'])
                                deleted_files += 1
                            except Exception as e:
                                self.logger.error(f"  Error deleting file {item['path']}: {e}")

                    self.logger.info(f"Deleted {deleted_files} file(s) and {deleted_dirs} directory(ies)")

            self.logger.info("=" * 60)
            self.logger.info("Website directory cleanup completed!")
            self.logger.info("=" * 60)

        except Exception as e:
            self.logger.error(f"Error during website cleanup: {e}")

    def _drop_all_databases(self) -> None:
        """Drop all databases (main and tenants)."""
        database_config = self.config.get('database')

        if not database_config or not database_config.get('enabled', False):
            self.logger.info("Database not configured, skipping database cleanup")
            return

        dry_run = self.config.get('options', {}).get('dry_run', False)

        self.logger.info("=" * 60)
        self.logger.info("DROPPING ALL DATABASES")
        self.logger.info("=" * 60)
        self.logger.warning("This will DROP all configured databases")

        try:
            # Create database handler if needed
            if not self.db_handler:
                self.db_handler = DatabaseHandler(
                    ssh_host=database_config.get('ssh_host'),
                    ssh_port=database_config.get('ssh_port', 22),
                    ssh_username=database_config.get('ssh_username'),
                    ssh_password=database_config.get('ssh_password'),
                    ssh_key_file=database_config.get('ssh_key_file'),
                    ssh_passphrase=database_config.get('ssh_passphrase', ''),
                    db_host=database_config.get('db_host', '127.0.0.1'),
                    db_port=database_config.get('db_port', 3306),
                    db_username=database_config.get('admin_username'),
                    db_password=database_config.get('admin_password')
                )

                self.logger.info("Connecting to database server via SSH...")
                if not self.db_handler.connect():
                    self.logger.error("Failed to connect to database server")
                    return

            # Drop main database
            main_database_scripts = database_config.get('main_database_scripts')
            if main_database_scripts:
                main_db_name = main_database_scripts.get('db_name')
                if dry_run:
                    self.logger.info(f"[DRY RUN] Would drop main database: {main_db_name}")
                else:
                    if self.db_handler.database_exists(main_db_name):
                        if self.db_handler.execute_sql_command(f"DROP DATABASE IF EXISTS {main_db_name}", dry_run=False):
                            self.logger.info(f"✓ Dropped main database: {main_db_name}")
                        else:
                            self.logger.error(f"Failed to drop main database: {main_db_name}")
                    else:
                        self.logger.info(f"Main database '{main_db_name}' does not exist, skipping")

            # Drop tenant databases
            # Build dynamic tenant database configs from tenant data
            tenant_database_scripts = self._build_tenant_database_configs()
            for tenant_config in tenant_database_scripts:
                tenant_db_name = tenant_config.get('db_name')
                if dry_run:
                    self.logger.info(f"[DRY RUN] Would drop tenant database: {tenant_db_name}")
                else:
                    if self.db_handler.database_exists(tenant_db_name):
                        if self.db_handler.execute_sql_command(f"DROP DATABASE IF EXISTS {tenant_db_name}", dry_run=False):
                            self.logger.info(f"✓ Dropped tenant database: {tenant_db_name}")
                        else:
                            self.logger.error(f"Failed to drop tenant database: {tenant_db_name}")
                    else:
                        self.logger.info(f"Tenant database '{tenant_db_name}' does not exist, skipping")

            self.logger.info("=" * 60)
            self.logger.info("Database cleanup completed!")
            self.logger.info("=" * 60)

        except Exception as e:
            self.logger.error(f"Error during database cleanup: {e}")

    def _execute_permissions_script(self, files_changed: bool = False) -> None:
        """
        Execute permissions script on destination server (SSH only).

        Args:
            files_changed: True if any files were copied/modified/deleted
        """
        website_config = self.config.get('website', {})
        script_path = website_config.get('set_permissions_script')

        if not script_path:
            return

        # Skip if no file changes were made (optimization)
        # Permissions script does find/chmod on all files - unnecessary if no files changed
        if not files_changed:
            self.logger.info("No file changes deployed, skipping permissions script")
            return

        # Also skip if no overall changes (shouldn't happen, but double-check)
        if not self.deployment_made_changes:
            self.logger.info("No changes deployed, skipping permissions script")
            return

        # Check if destination is SSH
        if self.config['destination']['type'] != 'ssh':
            self.logger.warning("set_permissions_script only works with SSH destinations - skipping")
            return

        try:
            dry_run = self.config.get('options', {}).get('dry_run', False)

            self.logger.info("=" * 60)
            self.logger.info("SETTING PERMISSIONS")
            self.logger.info("=" * 60)

            # Get SSH handler
            if not hasattr(self.dest_handler, 'ssh_client'):
                self.logger.error("Destination handler is not SSH - cannot execute permissions script")
                return

            ssh_client = self.dest_handler.ssh_client

            # Build full path on destination server
            dest_base_path = website_config.get('path')
            full_script_path = f"{dest_base_path}/{script_path}"

            if dry_run:
                self.logger.info(f"  [DRY RUN] Would make script executable: {full_script_path}")
                self.logger.info(f"  [DRY RUN] Would execute script: {full_script_path}")
                return

            # Get SSH password for sudo
            ssh_password = self.config['destination'].get('password', '')

            # Fix line endings (convert Windows CRLF to Unix LF)
            self.logger.info(f"Converting line endings to Unix format: {full_script_path}")
            dos2unix_cmd = f"sed -i 's/\\r$//' {full_script_path}"
            stdin, stdout, stderr = ssh_client.exec_command(dos2unix_cmd)
            stdout.channel.recv_exit_status()  # Wait for completion

            # Make script executable
            self.logger.info(f"Making script executable: {full_script_path}")
            chmod_cmd = f"echo '{ssh_password}' | sudo -S chmod +x {full_script_path}"
            stdin, stdout, stderr = ssh_client.exec_command(chmod_cmd)
            exit_status = stdout.channel.recv_exit_status()

            # Read stderr but filter out the sudo password prompt
            error_output = stderr.read().decode()
            # Filter out common sudo password prompts
            error_lines = [line for line in error_output.split('\n')
                          if line.strip() and '[sudo]' not in line.lower()
                          and 'password' not in line.lower()]

            if exit_status != 0 and error_lines:
                self.logger.error(f"Failed to make script executable: {chr(10).join(error_lines)}")
                return

            # Execute the script
            self.logger.info(f"Executing permissions script: {full_script_path}")
            exec_cmd = f"cd {dest_base_path} && echo '{ssh_password}' | sudo -S bash {full_script_path}"
            stdin, stdout, stderr = ssh_client.exec_command(exec_cmd)

            # Stream output in real-time (including echo messages from script)
            for line in stdout:
                line_text = line.rstrip()
                if line_text:  # Only log non-empty lines
                    self.logger.info(f"  {line_text}")

            exit_status = stdout.channel.recv_exit_status()

            # Read and filter stderr
            error_output = stderr.read().decode()

            if exit_status != 0:
                self.logger.error(f"Permissions script failed with exit code {exit_status}")

                # Filter out sudo password prompts but show actual errors
                error_lines = [line for line in error_output.split('\n')
                              if line.strip() and '[sudo]' not in line.lower()
                              and 'password for' not in line.lower()]

                if error_lines:
                    self.logger.error("Error output:")
                    for line in error_lines:
                        self.logger.error(f"  {line}")
                else:
                    # If no filtered errors, show raw stderr (might have useful info)
                    if error_output.strip():
                        self.logger.error(f"Raw error output: {error_output}")
            else:
                self.logger.info("=" * 60)
                self.logger.info("Permissions script executed successfully!")
                self.logger.info("=" * 60)

        except Exception as e:
            self.logger.error(f"Error executing permissions script: {e}")

    def _cronjobs_files_changed(self) -> bool:
        """
        Check if cronjobs script, files in local_path, or SQL files have changed since last deployment.

        Returns:
            True if any cronjobs files have changed, False otherwise
        """
        website_config = self.config.get('website', {})
        cronjobs_config = website_config.get('cronjobs', {})
        source_path = self.config.get('source', {}).get('path', '')

        script_name = cronjobs_config.get('script')
        local_path = cronjobs_config.get('local_path', '')
        create_table_file = cronjobs_config.get('create_table_file', '')
        insert_data_file = cronjobs_config.get('insert_data_file', '')

        # Get cached cronjobs data
        cronjobs_cache = self.cache_data.get('cronjobs', {})
        cached_script_mtime = cronjobs_cache.get('script_mtime', 0)
        cached_files = cronjobs_cache.get('files', {})
        cached_create_table_mtime = cronjobs_cache.get('create_table_mtime', 0)
        cached_insert_data_mtime = cronjobs_cache.get('insert_data_mtime', 0)

        # Check if the script file has changed
        if script_name:
            # Script is always relative to source root (matches execution behavior)
            script_local_path = os.path.join(source_path, script_name)

            if os.path.exists(script_local_path):
                script_mtime = os.path.getmtime(script_local_path)
                if script_mtime > cached_script_mtime:
                    if self.verbose:
                        self.logger.info(f"Cronjobs script changed: {script_name}")
                    return True

        # Check if create_table_file has changed
        if create_table_file and os.path.exists(create_table_file):
            create_table_mtime = os.path.getmtime(create_table_file)
            if create_table_mtime > cached_create_table_mtime:
                if self.verbose:
                    self.logger.info(f"Cronjobs create_table_file changed: {os.path.basename(create_table_file)}")
                return True

        # Check if insert_data_file has changed
        if insert_data_file and os.path.exists(insert_data_file):
            insert_data_mtime = os.path.getmtime(insert_data_file)
            if insert_data_mtime > cached_insert_data_mtime:
                if self.verbose:
                    self.logger.info(f"Cronjobs insert_data_file changed: {os.path.basename(insert_data_file)}")
                return True

        # Check if any files in the local_path have changed
        if local_path and os.path.exists(local_path) and os.path.isdir(local_path):
            for root, dirs, files in os.walk(local_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_mtime = os.path.getmtime(file_path)
                    cached_mtime = cached_files.get(file_path, 0)

                    if file_mtime > cached_mtime:
                        if self.verbose:
                            self.logger.info(f"Cronjobs file changed: {file}")
                        return True

        return False

    def _update_cronjobs_cache(self) -> None:
        """Update cache with current cronjobs file metadata."""
        website_config = self.config.get('website', {})
        cronjobs_config = website_config.get('cronjobs', {})
        source_path = self.config.get('source', {}).get('path', '')

        script_name = cronjobs_config.get('script')
        local_path = cronjobs_config.get('local_path', '')
        create_table_file = cronjobs_config.get('create_table_file', '')
        insert_data_file = cronjobs_config.get('insert_data_file', '')

        if 'cronjobs' not in self.cache_data:
            self.cache_data['cronjobs'] = {}

        cronjobs_cache = self.cache_data['cronjobs']

        # Update script mtime
        if script_name:
            # Script is always relative to source root (matches execution behavior)
            script_local_path = os.path.join(source_path, script_name)

            if os.path.exists(script_local_path):
                cronjobs_cache['script_mtime'] = os.path.getmtime(script_local_path)

        # Update create_table_file mtime
        if create_table_file and os.path.exists(create_table_file):
            cronjobs_cache['create_table_mtime'] = os.path.getmtime(create_table_file)

        # Update insert_data_file mtime
        if insert_data_file and os.path.exists(insert_data_file):
            cronjobs_cache['insert_data_mtime'] = os.path.getmtime(insert_data_file)

        # Update files mtimes from local_path
        if local_path and os.path.exists(local_path) and os.path.isdir(local_path):
            if 'files' not in cronjobs_cache:
                cronjobs_cache['files'] = {}

            for root, dirs, files in os.walk(local_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    cronjobs_cache['files'][file_path] = os.path.getmtime(file_path)

    def _execute_cronjobs_script(self) -> None:
        """
        Execute cronjobs setup script on destination server (SSH only).
        This runs after all deployment steps including database and permissions.
        Only executes if the script or files in the cronjobs path have changed.
        """
        website_config = self.config.get('website', {})
        cronjobs_config = website_config.get('cronjobs', {})
        script_name = cronjobs_config.get('script')

        if not script_name:
            return

        # Check if destination is SSH
        if self.config['destination']['type'] != 'ssh':
            self.logger.warning("cronjobs.script only works with SSH destinations - skipping")
            return

        try:
            dry_run = self.config.get('options', {}).get('dry_run', False)
            ignore_cache = self.config.get('options', {}).get('ignore_cache', False)
            clean_install = self.config.get('options', {}).get('clean_install', False)

            # Check if cronjobs files have changed (skip check for clean_install or ignore_cache)
            if not clean_install and not ignore_cache:
                if not self._cronjobs_files_changed():
                    self.logger.info("No cronjobs files changed, skipping cronjobs script")
                    return

            self.logger.info("=" * 60)
            self.logger.info("SETTING UP CRONJOBS")
            self.logger.info("=" * 60)

            # Get SSH handler
            if not hasattr(self.dest_handler, 'ssh_client'):
                self.logger.error("Destination handler is not SSH - cannot execute cronjobs script")
                return

            ssh_client = self.dest_handler.ssh_client

            # Build full path on destination server
            # Script is always relative to website root
            dest_base_path = website_config.get('path')
            full_script_path = f"{dest_base_path}/{script_name}"
            server_path = cronjobs_config.get('server_path', '')

            if dry_run:
                self.logger.info(f"  [DRY RUN] Would make script executable: {full_script_path}")
                if server_path:
                    self.logger.info(f"  [DRY RUN] Would convert line endings for files in: {server_path}")
                self.logger.info(f"  [DRY RUN] Would execute script: {full_script_path}")
                return

            # Get SSH password for sudo
            ssh_password = self.config['destination'].get('password', '')

            # Fix line endings for all PHP files in server_path (convert Windows CRLF to Unix LF)
            if server_path:
                self.logger.info(f"Converting line endings for PHP files in: {server_path}")
                dos2unix_php_cmd = f"find {server_path} -name '*.php' -exec sed -i 's/\\r$//' {{}} \\;"
                stdin, stdout, stderr = ssh_client.exec_command(dos2unix_php_cmd)
                stdout.channel.recv_exit_status()  # Wait for completion

            # Fix line endings for the script itself
            self.logger.info(f"Converting line endings to Unix format: {full_script_path}")
            dos2unix_cmd = f"sed -i 's/\\r$//' {full_script_path}"
            stdin, stdout, stderr = ssh_client.exec_command(dos2unix_cmd)
            stdout.channel.recv_exit_status()  # Wait for completion

            # Make script executable
            self.logger.info(f"Making script executable: {full_script_path}")
            chmod_cmd = f"echo '{ssh_password}' | sudo -S chmod +x {full_script_path}"
            stdin, stdout, stderr = ssh_client.exec_command(chmod_cmd)
            exit_status = stdout.channel.recv_exit_status()

            # Read stderr but filter out the sudo password prompt
            error_output = stderr.read().decode()
            # Filter out common sudo password prompts
            error_lines = [line for line in error_output.split('\n')
                          if line.strip() and '[sudo]' not in line.lower()
                          and 'password' not in line.lower()]

            if exit_status != 0 and error_lines:
                self.logger.error(f"Failed to make script executable: {chr(10).join(error_lines)}")
                return

            # Execute the script
            self.logger.info(f"Executing cronjobs script: {full_script_path}")
            exec_cmd = f"cd {dest_base_path} && echo '{ssh_password}' | sudo -S bash {full_script_path}"
            stdin, stdout, stderr = ssh_client.exec_command(exec_cmd)

            # Stream output in real-time (including echo messages from script)
            for line in stdout:
                line_text = line.rstrip()
                if line_text:  # Only log non-empty lines
                    self.logger.info(f"  {line_text}")

            exit_status = stdout.channel.recv_exit_status()

            # Read and filter stderr
            error_output = stderr.read().decode()

            if exit_status != 0:
                self.logger.error(f"Cronjobs script failed with exit code {exit_status}")

                # Filter out sudo password prompts but show actual errors
                error_lines = [line for line in error_output.split('\n')
                              if line.strip() and '[sudo]' not in line.lower()
                              and 'password for' not in line.lower()]

                if error_lines:
                    self.logger.error("Error output:")
                    for line in error_lines:
                        self.logger.error(f"  {line}")
                else:
                    # If no filtered errors, show raw stderr (might have useful info)
                    if error_output.strip():
                        self.logger.error(f"Raw error output: {error_output}")
            else:
                # Update cache after successful execution
                self._update_cronjobs_cache()
                self.deployment_made_changes = True

                self.logger.info("=" * 60)
                self.logger.info("Cronjobs script executed successfully!")
                self.logger.info("=" * 60)

        except Exception as e:
            self.logger.error(f"Error executing cronjobs script: {e}")

    def _tenant_needs_deployment(self, tenant_name: str, config_file: str, assets_path: str, generated_css_path: str = None) -> bool:
        """
        Check if a tenant needs to be deployed by comparing file modification times.

        Args:
            tenant_name: Name of the tenant
            config_file: Path to tenant config file
            assets_path: Path to tenant assets directory
            generated_css_path: Path to generated CSS for this tenant (optional)

        Returns:
            True if tenant needs deployment, False if unchanged
        """
        web_tenants_cache = self.cache_data.get('web_tenants', {})
        tenant_cache = web_tenants_cache.get(tenant_name, {})

        # Check config file
        if config_file and os.path.exists(config_file):
            config_mtime = os.path.getmtime(config_file)
            cached_config_mtime = tenant_cache.get('config_mtime', 0)
            if config_mtime > cached_config_mtime:
                return True

        # Check assets
        if os.path.exists(assets_path):
            assets_pattern = os.path.join(assets_path, '**', '*')
            asset_files = [f for f in glob.glob(assets_pattern, recursive=True) if os.path.isfile(f)]

            cached_assets = tenant_cache.get('assets', {})

            for asset_file in asset_files:
                asset_mtime = os.path.getmtime(asset_file)
                cached_mtime = cached_assets.get(asset_file, {}).get('mtime', 0)
                if asset_mtime > cached_mtime:
                    return True

        # Check generated CSS
        if generated_css_path and os.path.exists(generated_css_path):
            css_pattern = os.path.join(generated_css_path, '**', '*.css')
            css_files = glob.glob(css_pattern, recursive=True)

            cached_css = tenant_cache.get('css_files', {})

            for css_file in css_files:
                css_mtime = os.path.getmtime(css_file)
                cached_mtime = cached_css.get(css_file, {}).get('mtime', 0)
                if css_mtime > cached_mtime:
                    return True

        return False

    def _update_web_tenant_cache(self, tenant_name: str, config_file: str, assets_path: str, generated_css_path: str = None) -> None:
        """Update cache with current tenant file metadata."""
        if 'web_tenants' not in self.cache_data:
            self.cache_data['web_tenants'] = {}

        if tenant_name not in self.cache_data['web_tenants']:
            self.cache_data['web_tenants'][tenant_name] = {}

        tenant_cache = self.cache_data['web_tenants'][tenant_name]

        # Update config mtime
        if config_file and os.path.exists(config_file):
            tenant_cache['config_mtime'] = os.path.getmtime(config_file)

        # Update assets mtimes
        if os.path.exists(assets_path):
            assets_pattern = os.path.join(assets_path, '**', '*')
            asset_files = [f for f in glob.glob(assets_pattern, recursive=True) if os.path.isfile(f)]

            if 'assets' not in tenant_cache:
                tenant_cache['assets'] = {}

            for asset_file in asset_files:
                if asset_file not in tenant_cache['assets']:
                    tenant_cache['assets'][asset_file] = {}
                tenant_cache['assets'][asset_file]['mtime'] = os.path.getmtime(asset_file)

        # Update CSS mtimes
        if generated_css_path and os.path.exists(generated_css_path):
            css_pattern = os.path.join(generated_css_path, '**', '*.css')
            css_files = glob.glob(css_pattern, recursive=True)

            if 'css_files' not in tenant_cache:
                tenant_cache['css_files'] = {}

            for css_file in css_files:
                if css_file not in tenant_cache['css_files']:
                    tenant_cache['css_files'][css_file] = {}
                tenant_cache['css_files'][css_file]['mtime'] = os.path.getmtime(css_file)

    def _check_confirmation(self) -> bool:
        """
        Check if user confirmation is required and prompt if needed.

        Returns:
            True if deployment should proceed, False if cancelled
        """
        warn_enabled = self.config.get('options', {}).get('warn', False)

        if not warn_enabled:
            return True

        # Use description from config
        description = self.config.get('description', 'proceed with this deployment')
        message = f"Are you sure you want to {description}?"

        print("\n" + "=" * 60)
        print("WARNING")
        print("=" * 60)
        print(message)
        print("=" * 60)
        print("\nType 'yes' to continue or anything else to cancel: ", end='', flush=True)

        try:
            response = input().strip()
        except (EOFError, KeyboardInterrupt):
            print("\n")
            return False

        if response.lower() == 'yes':
            return True
        else:
            self.logger.info("Deployment cancelled by user")
            return False

    def _check_clean_install_confirmation(self) -> bool:
        """
        Check if user wants to proceed with clean install (deletes all files and databases).

        Returns:
            True if clean install should proceed, False if cancelled
        """
        print("\n" + "=" * 60)
        print("CLEAN INSTALL WARNING")
        print("=" * 60)
        print("Clean install mode is ENABLED!")
        print("This will DELETE:")
        print("  - All files in the destination directory")
        print("  - All configured databases (main and tenant databases)")
        print("=" * 60)
        print("\nType 'DELETE EVERYTHING' to continue or anything else to cancel: ", end='', flush=True)

        try:
            response = input().strip()
        except (EOFError, KeyboardInterrupt):
            print("\n")
            return False

        if response == 'DELETE EVERYTHING':
            return True
        else:
            self.logger.info("Clean install cancelled by user")
            return False

    def run(self) -> None:
        """Execute the deployment/synchronization."""
        # Check for user confirmation if warn is enabled
        if not self._check_confirmation():
            return

        # Check for clean install confirmation if enabled
        clean_install = self.config.get('options', {}).get('clean_install', False)
        if clean_install:
            if not self._check_clean_install_confirmation():
                return

        # Load cache for incremental deployments
        ignore_cache = self.config.get('options', {}).get('ignore_cache', False)
        if ignore_cache:
            self.logger.info("Cache disabled (ignore_cache=true), performing full deployment")
            self.cache_data = self._load_cache()  # Still load for structure
        else:
            self.cache_data = self._load_cache()

        # Pre-build step (if configured)
        website_config = self.config.get('website', {})
        pre_build_config = website_config.get('pre_build', {})
        if pre_build_config.get('enabled', False):
            self._log_section("PRE-BUILD")
            should_build, changed_files = self._should_run_pre_build()
            if should_build:
                if len(changed_files) <= 10:
                    self.logger.warning(f"Source files changed ({len(changed_files)}):")
                    for f in changed_files:
                        self.logger.warning(f"  - {f}")
                else:
                    self.logger.warning(f"Source files changed: {len(changed_files)} files")
                self._execute_pre_build()
                self.deployment_made_changes = True
            else:
                self.logger.warning("No source files changed, skipping build")

        try:
            # Create handlers
            if self.verbose:
                self.logger.info("Creating source handler...")
            self.source_handler = self._create_handler(self.config['source'])

            if self.verbose:
                self.logger.info("Creating destination handler...")
            # Get website path if available, otherwise use destination.path
            website_config = self.config.get('website', {})
            website_path = website_config.get('path')
            self.dest_handler = self._create_handler(self.config['destination'], path_override=website_path)

            # Connect to source and destination
            if self.verbose:
                self.logger.info("Connecting to source...")
            self.source_handler.connect()

            if self.verbose:
                self.logger.info("Connecting to destination...")
            self.dest_handler.connect()

            # Perform clean install if requested
            if clean_install:
                self.logger.warning("=" * 60)
                self.logger.warning("CLEAN INSTALL MODE ENABLED")
                self.logger.warning("All files and databases will be deleted!")
                self.logger.warning("=" * 60)

                # Clean website directory first
                self._clean_website_directory()

                # Drop all databases
                self._drop_all_databases()

                # Reset cache since we're starting fresh
                self.cache_data = self._create_empty_cache()

            # List source files (always needed)
            if self.verbose:
                self.logger.info("Listing source files...")
            source_files = self.source_handler.list_files(recursive=True)
            if self.verbose:
                self.logger.info(f"Found {len(source_files)} files in source")

            # Determine if we need to list destination files
            # Skip destination listing if we have cache and clean_install=false
            has_cache = bool(self.cache_data.get('files')) and bool(self.cache_data.get('last_deployment'))
            skip_dest_listing = has_cache and not clean_install and not ignore_cache

            if skip_dest_listing:
                if self.verbose:
                    self.logger.info("Skipping destination file listing (using cache for incremental deployment)")
                # Use empty destination list - cache will handle comparison
                dest_files = []
            else:
                if self.verbose:
                    self.logger.info("Listing destination files...")
                dest_files = self.dest_handler.list_files(recursive=True)
                if self.verbose:
                    self.logger.info(f"Found {len(dest_files)} files in destination")

            # Compare files
            if self.verbose:
                self.logger.info("Comparing files...")
            new_files, modified_files, deleted_files = self._compare_files(source_files, dest_files)

            # Display summary (always show, even when verbose=false)
            self.logger.warning("=" * 60)
            self.logger.warning("SYNCHRONIZATION SUMMARY")
            self.logger.warning("=" * 60)
            self.logger.warning(f"New files: {len(new_files)}")
            self.logger.warning(f"Modified files: {len(modified_files)}")
            self.logger.warning(f"Files to delete: {len(deleted_files)}")
            self.logger.warning("=" * 60)

            # Perform synchronization
            if self.config.get('options', {}).get('dry_run', False):
                self.logger.warning("DRY RUN MODE - No changes will be made")

            # Start database deployment in parallel with file sync (if configured)
            database_future = None
            if self.config.get('database', {}).get('enabled', False):
                with ThreadPoolExecutor(max_workers=1) as db_executor:
                    self.logger.info("=" * 60)
                    self.logger.info("STARTING DATABASE DEPLOYMENT IN BACKGROUND")
                    self.logger.info("=" * 60)
                    database_future = db_executor.submit(self._deploy_database)

                    # Run file sync while database is deploying
                    self._sync_files(new_files, modified_files, deleted_files)

                    # Update cache with deployed file metadata
                    if new_files or modified_files or deleted_files:
                        self.deployment_made_changes = True
                        self._update_file_cache(source_files)

                    self.logger.warning("Synchronization completed successfully!")

                    # Process file mappings (copy files with renamed destinations)
                    self._process_file_mappings()

                    # Wait for database deployment to complete
                    if database_future:
                        self.logger.info("=" * 60)
                        self.logger.info("WAITING FOR DATABASE DEPLOYMENT TO COMPLETE...")
                        self.logger.info("=" * 60)
                        try:
                            database_future.result()  # Wait for completion and raise any exceptions
                        except Exception as e:
                            self.logger.error(f"Database deployment failed: {e}")
                            raise
            else:
                # No database deployment, just run file sync
                self._sync_files(new_files, modified_files, deleted_files)

                # Update cache with deployed file metadata
                if new_files or modified_files or deleted_files:
                    self.deployment_made_changes = True
                    self._update_file_cache(source_files)

                self.logger.warning("Synchronization completed successfully!")

                # Process file mappings (copy files with renamed destinations)
                self._process_file_mappings()

            # Execute permissions script if configured
            # Only run if files were actually changed (new, modified, or deleted)
            files_changed = len(new_files) > 0 or len(modified_files) > 0 or len(deleted_files) > 0
            self._execute_permissions_script(files_changed=files_changed)

            # Execute cronjobs setup script if configured
            self._execute_cronjobs_script()

        except Exception as e:
            self.logger.error(f"Error during deployment: {e}")
            raise
        finally:
            # Close connection pools if they were created
            if self.source_pool:
                self.source_pool.close_all()
            if self.dest_pool:
                self.dest_pool.close_all()

            # Save cache if changes were made and not in dry-run mode
            dry_run = self.config.get('options', {}).get('dry_run', False)
            if self.deployment_made_changes and not dry_run:
                self._save_cache(self.cache_data)

            # Disconnect handlers
            if self.source_handler:
                self.source_handler.disconnect()
            if self.dest_handler:
                self.dest_handler.disconnect()
