"""AI Deploy Agent - Synchronize files between source and destination."""
import os
import json
import fnmatch
from datetime import datetime
from typing import Dict, Any, List, Set, Optional, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from core.agent_base import AgentBase
from handlers.windows_share_handler import WindowsShareHandler
from handlers.ssh_handler import SSHHandler
from handlers.database_handler import DatabaseHandler


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
        self._transfer_lock = Lock()  # Thread-safe lock for SSH operations
        self.verbose = self.config.get('options', {}).get('verbose', True)  # Default: True for backward compatibility

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
            return {
                "last_deployment": None,
                "files": {},
                "css_build": {
                    "base_css_files": {},
                    "tenant_configs": {},
                    "last_built": None
                },
                "database": {
                    "last_deployment": None,
                    "main_scripts": {},
                    "tenant_scripts": {}
                },
                "web_tenants": {}
            }

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
                if self.verbose:
                    self.logger.info(f"Loaded cache from {cache_path}")
                return cache
        except Exception as e:
            self.logger.warning(f"Failed to load cache from {cache_path}: {e}")
            self.logger.warning("Treating as first deployment")
            return {
                "last_deployment": None,
                "files": {},
                "css_build": {
                    "base_css_files": {},
                    "tenant_configs": {},
                    "last_built": None
                },
                "database": {
                    "last_deployment": None,
                    "main_scripts": {},
                    "tenant_scripts": {}
                },
                "web_tenants": {}
            }

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
            normalized_path = f['path'].replace('\\', '/')
            if not self._should_ignore(normalized_path):
                files_cache[normalized_path] = {
                    'mtime': f['modified_time'],
                    'size': f['size']
                }

        self.cache_data['files'] = files_cache
        self.cache_data['last_deployment'] = datetime.utcnow().isoformat() + 'Z'

    def _update_css_build_cache(self, base_css_path: str, tenants: List[Dict]) -> None:
        """
        Update cache with CSS build metadata.

        Args:
            base_css_path: Base path for CSS files
            tenants: List of tenant configurations
        """
        import os
        import glob

        # Update base CSS files cache
        base_css_files_cache = {}
        for css_type in ['public', 'portal']:
            css_pattern = os.path.join(base_css_path, css_type, 'css', '*.css')
            css_files = glob.glob(css_pattern)
            for css_file in css_files:
                if os.path.exists(css_file):
                    base_css_files_cache[css_file] = {
                        'mtime': os.path.getmtime(css_file)
                    }

        # Update tenant configs cache
        tenant_configs_cache = {}
        for tenant in tenants:
            tenant_name = tenant['name']
            config_file = tenant['config_file']
            if os.path.exists(config_file):
                tenant_configs_cache[tenant_name] = {
                    'mtime': os.path.getmtime(config_file)
                }

        # Save to cache
        if 'css_build' not in self.cache_data:
            self.cache_data['css_build'] = {}

        self.cache_data['css_build']['base_css_files'] = base_css_files_cache
        self.cache_data['css_build']['tenant_configs'] = tenant_configs_cache
        self.cache_data['css_build']['last_built'] = datetime.utcnow().isoformat() + 'Z'

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
            self._validate_tenants_config(config['tenants'])

        # Validate website config if present
        if 'website' in config:
            self._validate_website_config(config['website'])

        # Validate database config if present
        if 'database' in config:
            self._validate_database_config(config['database'])

        # Validate warn option if present
        if 'warn' in config:
            warn_config = config['warn']
            if not isinstance(warn_config, dict):
                raise ValueError("warn must be a dictionary")
            if 'enabled' not in warn_config:
                raise ValueError("warn.enabled is required")
            if not isinstance(warn_config['enabled'], bool):
                raise ValueError("warn.enabled must be a boolean")

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

    def _validate_tenants_config(self, tenants: Dict[str, Any]) -> None:
        """Validate tenants configuration."""
        if not isinstance(tenants, dict):
            raise ValueError("tenants must be a dictionary")

        # Validate config_files_path
        if 'config_files_path' not in tenants:
            raise ValueError("tenants.config_files_path is required")

        config_files_path = tenants['config_files_path']
        if not os.path.exists(config_files_path):
            raise ValueError(f"tenants.config_files_path does not exist: {config_files_path}")
        if not os.path.isdir(config_files_path):
            raise ValueError(f"tenants.config_files_path is not a directory: {config_files_path}")

        # config_files_extension is optional, defaults to .json

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

        # Validate ignore if present
        if 'ignore' in website:
            ignore_config = website['ignore']
            if not isinstance(ignore_config, dict):
                raise ValueError("website.ignore must be a dictionary")

        # Validate tenant-website config if present
        if 'tenant-website' in website:
            self._validate_tenant_website_config(website['tenant-website'])

    def _validate_tenant_website_config(self, tenant_website: Dict[str, Any]) -> None:
        """Validate tenant-website configuration."""
        if not isinstance(tenant_website, dict):
            raise ValueError("website.tenant-website must be a dictionary")

        if not tenant_website.get('enabled', False):
            return  # Tenant website deployment is disabled

        # Validate build_css if present
        if 'build_css' in tenant_website and tenant_website['build_css']:
            if 'base_css_path' not in tenant_website:
                raise ValueError("website.tenant-website.base_css_path is required when build_css is true")
            if 'generated_css_path' not in tenant_website:
                raise ValueError("website.tenant-website.generated_css_path is required when build_css is true")

        # Validate assets_path template
        if 'assets_path' not in tenant_website:
            raise ValueError("website.tenant-website.assets_path is required when enabled")

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
                scripts.get('seeds_path')
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

        # Validate seed_tables configuration if present
        if 'seed_tables' in database:
            seed_tables = database['seed_tables']
            if not isinstance(seed_tables, dict):
                raise ValueError("seed_tables must be a dictionary")

            if seed_tables.get('enabled', False):
                # Check required fields
                if 'config_files_path' not in seed_tables:
                    raise ValueError("seed_tables must have 'config_files_path' when enabled")
                if 'tables' not in seed_tables:
                    raise ValueError("seed_tables must have 'tables' when enabled")

                # Validate config_files_path exists
                config_files_path = seed_tables['config_files_path']
                if not os.path.exists(config_files_path):
                    raise ValueError(f"seed_tables config_files_path does not exist: {config_files_path}")
                if not os.path.isdir(config_files_path):
                    raise ValueError(f"seed_tables config_files_path is not a directory: {config_files_path}")

                # Validate tables array
                tables = seed_tables['tables']
                if not isinstance(tables, list):
                    raise ValueError("seed_tables 'tables' must be an array")
                if len(tables) == 0:
                    raise ValueError("seed_tables 'tables' array cannot be empty when enabled")

                # Validate each table definition
                for idx, table_def in enumerate(tables):
                    if not isinstance(table_def, dict):
                        raise ValueError(f"seed_tables.tables[{idx}] must be a dictionary")

                    # Required fields
                    required_table_fields = ['table_name', 'table_script_file', 'begin_mark', 'end_mark', 'variables']
                    for field in required_table_fields:
                        if field not in table_def:
                            raise ValueError(f"seed_tables.tables[{idx}] missing '{field}' field")

                    # Validate table_script_file exists
                    table_script_file = table_def['table_script_file']
                    if not os.path.exists(table_script_file):
                        raise ValueError(f"seed_tables.tables[{idx}] table_script_file does not exist: {table_script_file}")

                    # Validate variables array
                    variables = table_def['variables']
                    if not isinstance(variables, list):
                        raise ValueError(f"seed_tables.tables[{idx}] 'variables' must be an array")

                    # Validate each variable definition
                    for var_idx, var_def in enumerate(variables):
                        if not isinstance(var_def, dict):
                            raise ValueError(f"seed_tables.tables[{idx}].variables[{var_idx}] must be a dictionary")
                        if 'sql_var' not in var_def:
                            raise ValueError(f"seed_tables.tables[{idx}].variables[{var_idx}] missing 'sql_var' field")
                        if 'json_field' not in var_def:
                            raise ValueError(f"seed_tables.tables[{idx}].variables[{var_idx}] missing 'json_field' field")

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
        Load all tenant configuration files from the tenants directory.

        Returns:
            List of tenant configuration dictionaries
        """
        tenants_config = self.config.get('tenants', {})
        config_files_path = tenants_config.get('config_files_path')
        config_files_extension = tenants_config.get('config_files_extension', '.json')

        if not config_files_path or not os.path.exists(config_files_path):
            return []

        tenant_configs = []

        # Get all JSON files in the directory
        import glob
        pattern = os.path.join(config_files_path, f'*{config_files_extension}')
        config_files = sorted(glob.glob(pattern))

        for config_file in config_files:
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    tenant_data = json.load(f)
                    # Add the config file path to the tenant data
                    tenant_data['_config_file_path'] = config_file
                    tenant_configs.append(tenant_data)
            except Exception as e:
                self.logger.warning(f"Failed to load tenant config {config_file}: {e}")

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

    def _build_tenant_website_configs(self) -> List[Dict[str, Any]]:
        """
        Build tenant website configurations from template and tenant data.

        Returns:
            List of tenant website configurations
        """
        website_config = self.config.get('website', {})
        tenant_website_config = website_config.get('tenant-website', {})

        if not tenant_website_config.get('enabled', False):
            return []

        tenant_configs = self._load_tenant_configs()
        if not tenant_configs:
            self.logger.warning("No tenant configurations found")
            return []

        tenant_website_configs = []

        for tenant_data in tenant_configs:
            webid = tenant_data.get('webid')
            name = tenant_data.get('name', webid)

            if not webid:
                self.logger.warning(f"Tenant config missing 'webid' field: {tenant_data.get('_config_file_path')}")
                continue

            # Build tenant-specific config by replacing template variables
            assets_path = self._replace_template_variables(
                tenant_website_config.get('assets_path', ''),
                tenant_data
            )

            tenant_config = {
                'name': webid,  # Use webid as the name
                'webid': webid,
                'display_name': name,
                'config_file': tenant_data.get('_config_file_path'),
                'assets_path': assets_path
            }

            tenant_website_configs.append(tenant_config)

        return tenant_website_configs

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
            if 'seeds_path' in tenant_db_config:
                db_config['seeds_path'] = tenant_db_config['seeds_path']

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

        # Check ignored files
        for pattern in ignore_config.get('files', []):
            if fnmatch.fnmatch(file_path, pattern):
                return True

        # Check ignored folders
        path_parts = Path(file_path).parts
        for pattern in ignore_config.get('folders', []):
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
            dest_files: List of destination file information

        Returns:
            Tuple of (new_files, modified_files, deleted_files)
        """
        ignore_cache = self.config.get('options', {}).get('ignore_cache', False)
        cached_files = self.cache_data.get('files', {})

        # Normalize all paths to use forward slashes for comparison
        # Create dictionaries for quick lookup
        source_dict = {}
        for f in source_files:
            normalized_path = f['path'].replace('\\', '/')
            if not self._should_ignore(normalized_path):
                # Store with normalized path but keep original file info
                f_copy = f.copy()
                f_copy['path'] = normalized_path
                source_dict[normalized_path] = f_copy

        dest_dict = {}
        for f in dest_files:
            normalized_path = f['path'].replace('\\', '/')
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
                # File exists on destination
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
        Uses a lock to ensure thread-safe SSH operations.

        Args:
            file_info: File information dictionary with 'path' key
            operation: Type of operation ('copy', 'update', 'delete')
            dry_run: Whether this is a dry run

        Returns:
            Tuple of (success, file_path, error_message)
        """
        file_path = file_info['path'] if isinstance(file_info, dict) else file_info

        try:
            if operation in ['copy', 'update']:
                if not dry_run:
                    # Use lock to prevent concurrent SSH operations
                    with self._transfer_lock:
                        content = self.source_handler.read_file(file_path)
                        self.dest_handler.write_file(file_path, content)
            elif operation == 'delete':
                if not dry_run:
                    with self._transfer_lock:
                        self.dest_handler.delete_file(file_path)

            return (True, file_path, '')
        except Exception as e:
            return (False, file_path, str(e))

    def _sync_files(self, new_files: List[Dict], modified_files: List[Dict], deleted_files: List[str]) -> None:
        """
        Synchronize files from source to destination using parallel transfers.
        Note: SSH connections are not thread-safe, so we use sequential processing for SSH.

        Args:
            new_files: List of new files to copy
            modified_files: List of modified files to update
            deleted_files: List of files to delete from destination
        """
        dry_run = self.config.get('options', {}).get('dry_run', False)
        max_workers = self.config.get('options', {}).get('max_concurrent_transfers', 20)

        # SSH connections are not thread-safe - use sequential processing
        # Only use parallel transfers for Windows share destinations
        is_ssh = (self.config.get('source', {}).get('type') == 'ssh' or
                  self.config.get('destination', {}).get('type') == 'ssh')

        if is_ssh:
            max_workers = 1  # Sequential for SSH to avoid deadlocks
            self.logger.info("Using sequential file transfers (SSH is not thread-safe)")

        # Copy new files in parallel
        if new_files:
            self.logger.info(f"New files to copy: {len(new_files)}")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
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
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
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
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
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
            # Check main database scripts
            main_database_scripts = database_config.get('main_database_scripts')
            if main_database_scripts:
                # Check all script directories
                for script_type in ['setup_path', 'tables_path', 'procedures_path', 'seeds_path']:
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
            tenant_database_scripts = self._build_tenant_database_configs()
            if tenant_database_scripts:
                for tenant_config in tenant_database_scripts:
                    for script_type in ['setup_path', 'tables_path', 'procedures_path', 'seeds_path']:
                        script_path = tenant_config.get(script_type)
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

            # Check seed tables config files and table script files
            seed_tables_config = database_config.get('seed_tables')
            if seed_tables_config and seed_tables_config.get('enabled', False):
                # Check config files
                config_files_path = seed_tables_config.get('config_files_path')
                config_files_extension = seed_tables_config.get('config_files_extension', '.json')
                if config_files_path and os.path.exists(config_files_path) and os.path.isdir(config_files_path):
                    for file in os.listdir(config_files_path):
                        if file.endswith(config_files_extension):
                            file_path = os.path.join(config_files_path, file)
                            if os.path.getmtime(file_path) > last_deployment_timestamp:
                                self.logger.debug(f"Seed config file changed: {file_path}")
                                return True

                # Check table script files
                tables = seed_tables_config.get('tables', [])
                for table_def in tables:
                    table_script_file = table_def.get('table_script_file')
                    if table_script_file and os.path.exists(table_script_file):
                        if os.path.getmtime(table_script_file) > last_deployment_timestamp:
                            self.logger.debug(f"Table script file changed: {table_script_file}")
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

            # Get last deployment timestamp from cache
            db_cache = self.cache_data.get('database', {})
            last_deployment_timestamp = db_cache.get('last_deployment_timestamp')

            if ignore_cache:
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

            # Build dynamic tenant database configs from tenant data
            tenant_database_scripts = self._build_tenant_database_configs()

            # Deploy database with timestamp for incremental deployment
            success, any_scripts_executed = self.db_handler.deploy_database(
                admin_username=admin_username,
                admin_password=admin_password,
                main_database_scripts=main_database_scripts,
                tenant_database_scripts=tenant_database_scripts,
                dry_run=dry_run,
                last_deployment_timestamp=last_deployment_timestamp,
                application_name=self.config.get('application_name')
            )

            # Seed tables from config files if configured
            # Tables can be seeded on either main database or tenant databases
            # based on the "database" field in each table definition
            seed_tables_config = database_config.get('seed_tables')
            if seed_tables_config and seed_tables_config.get('enabled', False):
                all_tables = seed_tables_config.get('tables', [])

                # Separate tables by target database
                main_tables = []
                tenant_tables = []

                for table_def in all_tables:
                    target_db = table_def.get('database', 'main')  # Default to main if not specified
                    if target_db == 'tenant':
                        tenant_tables.append(table_def)
                    else:
                        main_tables.append(table_def)

                # Seed main database tables
                if main_tables and main_database_scripts:
                    main_db_name = main_database_scripts.get('db_name')
                    if main_db_name:
                        self.logger.info("=" * 60)
                        self.logger.info("SEEDING MAIN DATABASE TABLES FROM CONFIG")
                        self.logger.info("=" * 60)

                        # Create config with only main tables
                        main_seed_config = seed_tables_config.copy()
                        main_seed_config['tables'] = main_tables

                        seed_success, records_inserted = self.db_handler.seed_tables_from_config(
                            seed_tables_config=main_seed_config,
                            database_name=main_db_name,
                            dry_run=dry_run,
                            application_name=self.config.get('application_name')
                        )
                        if not seed_success:
                            success = False
                        if records_inserted > 0:
                            any_scripts_executed = True

                # Seed tenant database tables
                if tenant_tables and tenant_database_scripts:
                    self.logger.info("=" * 60)
                    self.logger.info("SEEDING TENANT DATABASE TABLES FROM CONFIG")
                    self.logger.info("=" * 60)

                    # Create config with only tenant tables
                    tenant_seed_config = seed_tables_config.copy()
                    tenant_seed_config['tables'] = tenant_tables

                    # Seed each tenant database
                    for tenant_config in tenant_database_scripts:
                        tenant_db_name = tenant_config.get('db_name')
                        if tenant_db_name:
                            self.logger.info("=" * 60)
                            self.logger.info(f"SEEDING TENANT DATABASE: {tenant_db_name}")
                            self.logger.info("=" * 60)

                            seed_success, records_inserted = self.db_handler.seed_tables_from_config(
                                seed_tables_config=tenant_seed_config,
                                database_name=tenant_db_name,
                                dry_run=dry_run,
                                is_tenant_db=True,
                                application_name=self.config.get('application_name')
                            )
                            if not seed_success:
                                success = False
                            if records_inserted > 0:
                                any_scripts_executed = True

            if success:
                # Update cache with current timestamp only if scripts were executed
                if not dry_run and any_scripts_executed:
                    import time
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
                    # Use rm -rf to recursively delete all contents (but not the directory itself)
                    delete_cmd = f"rm -rf {website_path}/*"
                    stdin, stdout, stderr = ssh_client.exec_command(delete_cmd)
                    exit_status = stdout.channel.recv_exit_status()

                    if exit_status == 0:
                        self.logger.info(f"✓ Successfully deleted all contents of {website_path}")
                    else:
                        error = stderr.read().decode()
                        self.logger.error(f"Error deleting directory contents: {error}")

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
                from handlers.database_handler import DatabaseHandler

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

    def _execute_permissions_script(self) -> None:
        """Execute permissions script on destination server (SSH only)."""
        website_config = self.config.get('website', {})
        script_path = website_config.get('set_permissions_script')

        if not script_path:
            return

        # Skip if no changes were made (optimization)
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

    def _extract_css_variables_from_config(self, config_file_path: str) -> Dict[str, str]:
        """
        Extract CSS variables from a JSON config file.

        Args:
            config_file_path: Path to the JSON config file

        Returns:
            Dictionary of CSS variable names and values
        """
        import json

        try:
            with open(config_file_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Extract css_variables from the JSON config
            css_variables = config.get('css_variables', {})
            return css_variables

        except Exception as e:
            self.logger.error(f"Error extracting CSS variables from {config_file_path}: {e}")
            return {}

    def _tenant_css_needs_rebuild(self, tenant_name: str, config_file: str, base_css_path: str) -> bool:
        """
        Check if tenant CSS needs to be rebuilt.

        Args:
            tenant_name: Name of the tenant
            config_file: Path to tenant config file
            base_css_path: Base path for CSS files

        Returns:
            True if CSS needs to be rebuilt, False otherwise
        """
        import os
        import glob

        css_cache = self.cache_data.get('css_build', {})
        tenant_configs = css_cache.get('tenant_configs', {})
        base_css_files_cache = css_cache.get('base_css_files', {})

        # Check if tenant config file changed
        if os.path.exists(config_file):
            config_mtime = os.path.getmtime(config_file)
            cached_mtime = tenant_configs.get(tenant_name, {}).get('mtime', 0)
            if config_mtime > cached_mtime:
                return True
        else:
            # Config file doesn't exist, can't build
            return False

        # Check if any base CSS files changed
        for css_type in ['public', 'portal']:
            css_pattern = os.path.join(base_css_path, css_type, 'css', '*.css')
            css_files = glob.glob(css_pattern)

            for css_file in css_files:
                css_mtime = os.path.getmtime(css_file)
                cached_mtime = base_css_files_cache.get(css_file, {}).get('mtime', 0)
                if css_mtime > cached_mtime:
                    return True

        # No changes detected
        return False

    def _build_tenant_css(self) -> None:
        """Build CSS files for each tenant by prepending color variables."""
        website_config = self.config.get('website', {})
        tenant_website_config = website_config.get('tenant-website', {})

        if not tenant_website_config.get('enabled', False):
            return

        if not tenant_website_config.get('build_css', False):
            return

        import os
        import glob
        import re

        dry_run = self.config.get('options', {}).get('dry_run', False)
        ignore_cache = self.config.get('options', {}).get('ignore_cache', False)

        self.logger.info("=" * 60)
        self.logger.info("BUILDING TENANT CSS")
        self.logger.info("=" * 60)

        base_css_path = tenant_website_config['base_css_path']
        generated_css_path = tenant_website_config['generated_css_path']

        # Build dynamic tenant list from tenant configs
        tenants = self._build_tenant_website_configs()

        if not tenants:
            self.logger.warning("No tenant configurations found for CSS building")
            return

        css_built_for_any_tenant = False

        for tenant in tenants:
            tenant_name = tenant['name']
            config_file = tenant['config_file']

            # Check if CSS needs to be rebuilt for this tenant
            if not ignore_cache:
                needs_rebuild = self._tenant_css_needs_rebuild(
                    tenant_name, config_file, base_css_path
                )
                if not needs_rebuild:
                    if self.verbose:
                        self.logger.info(f"Skipping CSS build for tenant '{tenant_name}' (no changes detected)")
                    continue

            self.logger.info(f"Building CSS for tenant: {tenant_name}")
            css_built_for_any_tenant = True

            # Extract CSS variables from JSON config
            css_vars_dict = self._extract_css_variables_from_config(config_file)

            if not css_vars_dict:
                self.logger.warning(f"  No CSS variables found in {config_file}")
                continue

            # Process public CSS files
            public_css_pattern = os.path.join(base_css_path, 'public', 'css', '*.css')
            public_css_files = glob.glob(public_css_pattern)

            for css_file in public_css_files:
                filename = os.path.basename(css_file)
                output_dir = os.path.join(generated_css_path, tenant_name, 'public')
                output_file = os.path.join(output_dir, filename)

                if dry_run:
                    self.logger.info(f"  [DRY RUN] Would generate: {output_file}")
                else:
                    # Create output directory
                    os.makedirs(output_dir, exist_ok=True)

                    # Read original CSS
                    with open(css_file, 'r', encoding='utf-8') as f:
                        original_css = f.read()

                    # Extract non-color CSS variables from :root block
                    non_color_vars = {}
                    root_match = re.search(r':root\s*\{([^}]*)\}', original_css, re.DOTALL)
                    if root_match:
                        root_content = root_match.group(1)
                        for var_match in re.finditer(r'--([a-z0-9\-]+)\s*:\s*([^;]+);', root_content):
                            var_name = var_match.group(1)
                            var_value = var_match.group(2).strip()
                            # Keep non-color variables (not starting with 'c-')
                            if not var_name.startswith('c-'):
                                non_color_vars[f'--{var_name}'] = var_value

                    # Build new :root block with tenant CSS variables + non-color vars
                    css_vars = ":root{\n"
                    for key, value in css_vars_dict.items():
                        css_key = key.replace('_', '-')
                        # Variables starting with 'c_' get '--c-' prefix, others get '--' prefix only
                        if key.startswith('c_'):
                            css_vars += f"  --{css_key}:{value};\n"
                        else:
                            css_vars += f"  --{css_key}:{value};\n"
                    for var_name, var_value in non_color_vars.items():
                        css_vars += f"  {var_name}:{var_value};\n"
                    css_vars += "}\n\n"

                    # Strip old :root block
                    cleaned_css = re.sub(r':root\s*\{[^}]*\}', '', original_css, flags=re.DOTALL)

                    # Replace tenant paths /(demo|livingwater)/ with /tenants/{tenant_name}/
                    cleaned_css = re.sub(r'/(demo|livingwater)/', f'/tenants/{tenant_name}/', cleaned_css)

                    # Write generated CSS
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(css_vars)
                        f.write(cleaned_css)

                    self.logger.info(f"  ✓ Generated: public/{filename}")

            # Process portal CSS files
            portal_css_pattern = os.path.join(base_css_path, 'portal', 'css', '*.css')
            portal_css_files = glob.glob(portal_css_pattern)

            for css_file in portal_css_files:
                filename = os.path.basename(css_file)
                output_dir = os.path.join(generated_css_path, tenant_name, 'portal')
                output_file = os.path.join(output_dir, filename)

                if dry_run:
                    self.logger.info(f"  [DRY RUN] Would generate: {output_file}")
                else:
                    # Create output directory
                    os.makedirs(output_dir, exist_ok=True)

                    # Read original CSS
                    with open(css_file, 'r', encoding='utf-8') as f:
                        original_css = f.read()

                    # Extract non-color CSS variables from :root block
                    non_color_vars = {}
                    root_match = re.search(r':root\s*\{([^}]*)\}', original_css, re.DOTALL)
                    if root_match:
                        root_content = root_match.group(1)
                        for var_match in re.finditer(r'--([a-z0-9\-]+)\s*:\s*([^;]+);', root_content):
                            var_name = var_match.group(1)
                            var_value = var_match.group(2).strip()
                            # Keep non-color variables (not starting with 'c-')
                            if not var_name.startswith('c-'):
                                non_color_vars[f'--{var_name}'] = var_value

                    # Build new :root block with tenant CSS variables + non-color vars
                    css_vars = ":root{\n"
                    for key, value in css_vars_dict.items():
                        css_key = key.replace('_', '-')
                        # Variables starting with 'c_' get '--c-' prefix, others get '--' prefix only
                        if key.startswith('c_'):
                            css_vars += f"  --{css_key}:{value};\n"
                        else:
                            css_vars += f"  --{css_key}:{value};\n"
                    for var_name, var_value in non_color_vars.items():
                        css_vars += f"  {var_name}:{var_value};\n"
                    css_vars += "}\n\n"

                    # Strip old :root block
                    cleaned_css = re.sub(r':root\s*\{[^}]*\}', '', original_css, flags=re.DOTALL)

                    # Replace tenant paths /(demo|livingwater)/ with /tenants/{tenant_name}/
                    cleaned_css = re.sub(r'/(demo|livingwater)/', f'/tenants/{tenant_name}/', cleaned_css)

                    # Write generated CSS
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(css_vars)
                        f.write(cleaned_css)

                    self.logger.info(f"  ✓ Generated: portal/{filename}")

        # Update cache if CSS was built for any tenant
        if css_built_for_any_tenant:
            self.deployment_made_changes = True
            self._update_css_build_cache(base_css_path, tenants)

        self.logger.info("=" * 60)
        self.logger.info("Tenant CSS building completed!")
        self.logger.info("=" * 60)

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
        import glob

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
        import glob

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

    def _deploy_web_tenants(self) -> None:
        """Deploy tenant config files, assets, and generated CSS to destination."""
        website_config = self.config.get('website', {})
        tenant_website_config = website_config.get('tenant-website', {})

        if not tenant_website_config.get('enabled', False):
            return

        dry_run = self.config.get('options', {}).get('dry_run', False)
        ignore_cache = self.config.get('options', {}).get('ignore_cache', False)

        self.logger.info("=" * 60)
        self.logger.info("DEPLOYING WEB TENANTS")
        self.logger.info("=" * 60)

        tenants_deployed = 0

        dest_base_path = website_config.get('path')
        generated_css_path = tenant_website_config.get('generated_css_path')

        # Build dynamic tenant list from tenant configs
        tenants = self._build_tenant_website_configs()

        if not tenants:
            self.logger.warning("No tenant configurations found for deployment")
            return

        for tenant in tenants:
            tenant_name = tenant['name']
            config_file = tenant.get('config_file')
            assets_path = tenant['assets_path']

            # Check if tenant needs deployment
            tenant_css_path = os.path.join(generated_css_path, tenant_name) if generated_css_path else None

            if not ignore_cache:
                needs_deployment = self._tenant_needs_deployment(
                    tenant_name, config_file, assets_path, tenant_css_path
                )
                if not needs_deployment:
                    if self.verbose:
                        self.logger.info(f"Skipping tenant '{tenant_name}' (no changes detected)")
                    continue

            self.logger.info(f"Deploying tenant: {tenant_name}")

            # 1. Deploy config file
            if config_file:
                config_filename = os.path.basename(config_file)
                dest_config_path = f"web/tenants/_config/{config_filename}"

                try:
                    if dry_run:
                        self.logger.info(f"  [DRY RUN] Would deploy config: {dest_config_path}")
                    else:
                        with open(config_file, 'rb') as f:
                            content = f.read()
                        self.dest_handler.write_file(dest_config_path, content)
                        self.logger.info(f"  ✓ Deployed config: {config_filename}")
                except Exception as e:
                    self.logger.error(f"  Error deploying config {config_filename}: {e}")

            # 2. Deploy assets
            if os.path.exists(assets_path):
                try:
                    import glob

                    # Get all files in assets directory recursively
                    assets_pattern = os.path.join(assets_path, '**', '*')
                    asset_files = [f for f in glob.glob(assets_pattern, recursive=True) if os.path.isfile(f)]

                    for asset_file in asset_files:
                        # Calculate relative path from assets_path
                        rel_path = os.path.relpath(asset_file, assets_path)
                        # Convert to forward slashes for destination
                        rel_path = rel_path.replace('\\', '/')
                        dest_asset_path = f"web/tenants/{tenant_name}/{rel_path}"

                        if dry_run:
                            self.logger.info(f"  [DRY RUN] Would deploy asset: {rel_path}")
                        else:
                            with open(asset_file, 'rb') as f:
                                content = f.read()
                            self.dest_handler.write_file(dest_asset_path, content)

                    if not dry_run:
                        self.logger.info(f"  ✓ Deployed {len(asset_files)} asset file(s)")

                except Exception as e:
                    self.logger.error(f"  Error deploying assets for {tenant_name}: {e}")

            # 3. Deploy generated CSS
            if generated_css_path:
                if os.path.exists(tenant_css_path):
                    try:
                        import glob

                        # Get all CSS files recursively
                        css_pattern = os.path.join(tenant_css_path, '**', '*.css')
                        css_files = glob.glob(css_pattern, recursive=True)

                        for css_file in css_files:
                            # Calculate relative path from tenant_css_path
                            rel_path = os.path.relpath(css_file, tenant_css_path)
                            # Convert to forward slashes for destination
                            rel_path = rel_path.replace('\\', '/')
                            dest_css_path = f"web/generated/css/{tenant_name}/{rel_path}"

                            if dry_run:
                                self.logger.info(f"  [DRY RUN] Would deploy CSS: {rel_path}")
                            else:
                                with open(css_file, 'rb') as f:
                                    content = f.read()
                                self.dest_handler.write_file(dest_css_path, content)

                        if not dry_run:
                            self.logger.info(f"  ✓ Deployed {len(css_files)} CSS file(s)")

                    except Exception as e:
                        self.logger.error(f"  Error deploying CSS for {tenant_name}: {e}")

            # Update cache for this tenant
            if not dry_run:
                self._update_web_tenant_cache(tenant_name, config_file, assets_path, tenant_css_path)
                tenants_deployed += 1

        # Update change flag if any tenants were deployed
        if tenants_deployed > 0:
            self.deployment_made_changes = True
            self.logger.info(f"Deployed {tenants_deployed} tenant(s)")
        else:
            self.logger.info("No tenants needed to be deployed")

        self.logger.info("=" * 60)
        self.logger.info("Web tenants deployment completed!")
        self.logger.info("=" * 60)

    def _check_confirmation(self) -> bool:
        """
        Check if user confirmation is required and prompt if needed.

        Returns:
            True if deployment should proceed, False if cancelled
        """
        warn_config = self.config.get('warn', {})

        if not warn_config.get('enabled', False):
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

    def run(self) -> None:
        """Execute the deployment/synchronization."""
        # Check for user confirmation if warn is enabled
        if not self._check_confirmation():
            return

        # Load cache for incremental deployments
        ignore_cache = self.config.get('options', {}).get('ignore_cache', False)
        if ignore_cache:
            self.logger.info("Cache disabled (ignore_cache=true), performing full deployment")
            self.cache_data = self._load_cache()  # Still load for structure
        else:
            self.cache_data = self._load_cache()

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
            clean_install = self.config.get('options', {}).get('clean_install', False)
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
                self.cache_data = {
                    "last_deployment": None,
                    "files": {},
                    "css_build": {},
                    "database": {},
                    "file_mappings": {},
                    "web_tenants": {}
                }

            # List files
            if self.verbose:
                self.logger.info("Listing source files...")
            source_files = self.source_handler.list_files(recursive=True)
            if self.verbose:
                self.logger.info(f"Found {len(source_files)} files in source")

            if self.verbose:
                self.logger.info("Listing destination files...")
            dest_files = self.dest_handler.list_files(recursive=True)
            if self.verbose:
                self.logger.info(f"Found {len(dest_files)} files in destination")

            # Build tenant CSS (before synchronization so generated files exist)
            self._build_tenant_css()

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

            self._sync_files(new_files, modified_files, deleted_files)

            # Update cache with deployed file metadata
            if new_files or modified_files or deleted_files:
                self.deployment_made_changes = True
                self._update_file_cache(source_files)

            self.logger.warning("Synchronization completed successfully!")

            # Process file mappings (copy files with renamed destinations)
            self._process_file_mappings()

            # Deploy web tenants (config files, assets, generated CSS)
            self._deploy_web_tenants()

            # Deploy database if configured
            self._deploy_database()

            # Execute permissions script if configured
            self._execute_permissions_script()

        except Exception as e:
            self.logger.error(f"Error during deployment: {e}")
            raise
        finally:
            # Save cache if changes were made and not in dry-run mode
            dry_run = self.config.get('options', {}).get('dry_run', False)
            if self.deployment_made_changes and not dry_run:
                self._save_cache(self.cache_data)

            # Disconnect handlers
            if self.source_handler:
                self.source_handler.disconnect()
            if self.dest_handler:
                self.dest_handler.disconnect()
