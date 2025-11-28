"""Database handler for deploying SQL scripts via SSH tunnel."""
import os
import logging
import json
import re
from typing import Optional, List, Dict, Any
from pathlib import Path
import paramiko
import mysql.connector
from mysql.connector import Error
import bcrypt


class DatabaseHandler:
    """Handler for deploying database scripts through SSH tunnel."""

    def __init__(
        self,
        ssh_host: str,
        ssh_username: str,
        ssh_password: Optional[str] = None,
        ssh_key_file: Optional[str] = None,
        ssh_passphrase: Optional[str] = None,
        ssh_port: int = 22,
        db_host: str = "127.0.0.1",
        db_port: int = 3306,
        db_username: str = "root",
        db_password: str = "",
        db_name: Optional[str] = None,
        logger = None
    ):
        """
        Initialize database handler with SSH and MySQL configuration.

        Args:
            ssh_host: SSH server hostname/IP
            ssh_username: SSH username
            ssh_password: SSH password (optional if using key)
            ssh_key_file: Path to SSH private key file
            ssh_passphrase: Passphrase for encrypted SSH private key file
            ssh_port: SSH port (default 22)
            db_host: Database host to forward to (default 127.0.0.1)
            db_port: Database port (default 3306)
            db_username: MySQL username
            db_password: MySQL password
            db_name: Database name (optional, can be set in scripts)
        """
        self.ssh_host = ssh_host
        self.ssh_username = ssh_username
        self.ssh_password = ssh_password
        self.ssh_key_file = ssh_key_file
        self.ssh_passphrase = ssh_passphrase
        self.ssh_port = ssh_port
        self.db_host = db_host
        self.db_port = db_port
        self.db_username = db_username
        self.db_password = db_password
        self.db_name = db_name

        self.ssh_client = None
        self.tunnel = None
        self.connection = None
        self.local_port = None

        # Use provided logger or create a basic one
        if logger:
            self.logger = logger
        else:
            self.logger = logging.getLogger(self.__class__.__name__)

    def connect(self) -> bool:
        """
        Establish SSH tunnel and database connection.

        Returns:
            True if connection successful
        """
        try:
            # Create SSH client
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Connect to SSH server
            self.logger.debug(f"Connecting to SSH server {self.ssh_host}:{self.ssh_port}...")

            if self.ssh_key_file:
                # Pass passphrase if provided (can be None or empty string for unencrypted keys)
                passphrase = self.ssh_passphrase if self.ssh_passphrase else None

                # Try to load the key with different key types
                key = None
                key_types = [
                    ('Ed25519', paramiko.Ed25519Key),
                    ('RSA', paramiko.RSAKey),
                    ('ECDSA', paramiko.ECDSAKey),
                    ('DSS', paramiko.DSSKey)
                ]

                last_error = None
                for key_name, key_class in key_types:
                    try:
                        key = key_class.from_private_key_file(
                            self.ssh_key_file,
                            password=passphrase
                        )
                        break
                    except Exception as e:
                        last_error = e
                        continue

                if key is None:
                    raise ValueError(f"Failed to load private key from {self.ssh_key_file}. Last error: {last_error}")

                self.ssh_client.connect(
                    hostname=self.ssh_host,
                    port=self.ssh_port,
                    username=self.ssh_username,
                    pkey=key
                )
            else:
                self.ssh_client.connect(
                    hostname=self.ssh_host,
                    port=self.ssh_port,
                    username=self.ssh_username,
                    password=self.ssh_password
                )

            # Create SSH tunnel for database connection
            self.logger.debug(f"Creating SSH tunnel to {self.db_host}:{self.db_port}...")
            transport = self.ssh_client.get_transport()

            # Use a local port for forwarding (we'll connect to localhost:local_port)
            # This connects to db_host:db_port on the remote server
            self.local_port = 3307  # Use different port to avoid conflicts with local MySQL

            # Note: For production, you'd want to use paramiko's port forwarding properly
            # For now, we'll connect directly if db_host is 127.0.0.1 (localhost on remote)
            self.logger.debug("SSH connection established successfully")

            return True

        except Exception as e:
            self.logger.error(f"Failed to establish SSH connection: {e}")
            return False

    def disconnect(self) -> None:
        """Close database connection and SSH tunnel."""
        if self.connection:
            try:
                self.connection.close()
                self.logger.info("Database connection closed")
            except Exception as e:
                self.logger.error(f"Error closing database connection: {e}")

        if self.ssh_client:
            try:
                self.ssh_client.close()
                self.logger.info("SSH connection closed")
            except Exception as e:
                self.logger.error(f"Error closing SSH connection: {e}")

    def _connect_database(self) -> bool:
        """
        Connect to MySQL database through SSH tunnel.

        Returns:
            True if connection successful
        """
        try:
            # For SSH tunnel to remote MySQL, we need to use port forwarding
            # Since paramiko doesn't have direct port forwarding in this simple form,
            # we'll execute MySQL commands via SSH for now

            self.logger.debug(f"Connecting to MySQL database...")

            # Test MySQL connection via SSH command
            stdin, stdout, stderr = self.ssh_client.exec_command(
                f'mysql -h {self.db_host} -P {self.db_port} -u {self.db_username} -p{self.db_password} -e "SELECT 1;"'
            )

            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                error = stderr.read().decode()
                self.logger.error(f"MySQL connection test failed: {error}")
                return False

            self.logger.info("MySQL connection test successful")
            return True

        except Exception as e:
            self.logger.error(f"Failed to connect to database: {e}")
            return False

    def _replace_template_variables(self, sql_content: str, template_vars: dict) -> str:
        """
        Replace template variables in SQL content.

        Args:
            sql_content: SQL file content
            template_vars: Dictionary of template variables to replace

        Returns:
            SQL content with variables replaced
        """
        if not template_vars:
            return sql_content

        result = sql_content

        # Replace each template variable
        for key, value in template_vars.items():
            placeholder = f"{{{{{key}}}}}"  # {{KEY}}
            if value is not None:
                result = result.replace(placeholder, str(value))

        return result

    def execute_sql_file(self, sql_file_path: str, dry_run: bool = False, use_database: bool = True, template_vars: dict = None, database_name: str = None) -> bool:
        """
        Execute a SQL file on the database.

        Args:
            sql_file_path: Path to local SQL file
            dry_run: If True, only show what would be executed
            use_database: If True, specify database name in mysql command
            template_vars: Dictionary of template variables to replace in SQL

        Returns:
            True if execution successful
        """
        try:
            # Read SQL file content
            if not os.path.exists(sql_file_path):
                self.logger.error(f"SQL file not found: {sql_file_path}")
                return False

            with open(sql_file_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()

            # Replace template variables
            sql_content = self._replace_template_variables(sql_content, template_vars)

            file_name = os.path.basename(sql_file_path)

            if dry_run:
                self.logger.info(f"  [DRY RUN] Would execute: {file_name}")
                return True

            self.logger.debug(f"  Executing: {file_name}")

            # Upload SQL file to temp location on server
            # Convert Windows line endings (CRLF) to Unix (LF)
            sql_content_unix = sql_content.replace('\r\n', '\n').replace('\r', '\n')

            temp_sql_path = f"/tmp/deploy_sql_{file_name}"
            sftp = self.ssh_client.open_sftp()
            try:
                with sftp.file(temp_sql_path, 'w') as remote_file:
                    remote_file.write(sql_content_unix)
            finally:
                sftp.close()

            # Build MySQL command to execute the uploaded file
            mysql_cmd = f"mysql -h {self.db_host} -P {self.db_port} -u {self.db_username} -p{self.db_password}"
            # Only specify database if use_database is True and db_name is set
            # Use provided database_name parameter, or fall back to self.db_name
            db_to_use = database_name if database_name else self.db_name
            if use_database and db_to_use:
                mysql_cmd += f" {db_to_use}"

            # Execute the SQL file
            stdin, stdout, stderr = self.ssh_client.exec_command(
                f"{mysql_cmd} < {temp_sql_path}"
            )

            exit_status = stdout.channel.recv_exit_status()

            # Clean up temp file
            self.ssh_client.exec_command(f"rm -f {temp_sql_path}")

            if exit_status != 0:
                error = stderr.read().decode()
                self.logger.error(f"  Error executing {file_name}: {error}")
                return False

            # Read stdout/stderr but don't log output (can be verbose)
            stdout.read()
            stderr.read()

            self.logger.info(f"  ✓ Successfully executed: {file_name}")
            return True

        except Exception as e:
            self.logger.error(f"Error executing SQL file {sql_file_path}: {e}")
            return False

    def _find_sql_files_recursive(self, directory_path: str) -> List[str]:
        """
        Recursively find all SQL files in a directory and its subdirectories.

        Args:
            directory_path: Path to directory to search

        Returns:
            List of absolute paths to SQL files, sorted alphabetically
        """
        sql_files = []

        for root, dirs, files in os.walk(directory_path):
            for file in files:
                if file.endswith('.sql'):
                    sql_files.append(os.path.join(root, file))

        # Sort alphabetically (full paths ensure consistent ordering)
        return sorted(sql_files)

    def execute_sql_directory(self, directory_path: str, dry_run: bool = False, use_database: bool = True, template_vars: dict = None, database_name: str = None, last_deployment_timestamp: float = None) -> tuple[bool, int]:
        """
        Execute all SQL files in a directory and subdirectories (sorted alphabetically).
        Optionally skip files that haven't been modified since last deployment.

        Args:
            directory_path: Path to directory containing SQL files
            dry_run: If True, only show what would be executed
            use_database: If True, specify database name in mysql command
            template_vars: Dictionary of template variables to replace in SQL
            database_name: Name of database to use (optional)
            last_deployment_timestamp: Unix timestamp of last deployment, skip files older than this

        Returns:
            Tuple of (success: bool, files_executed_count: int)
        """
        try:
            if not os.path.exists(directory_path):
                self.logger.error(f"Directory not found: {directory_path}")
                return (False, 0)

            if not os.path.isdir(directory_path):
                self.logger.error(f"Not a directory: {directory_path}")
                return (False, 0)

            # Get all .sql files recursively and sort them
            sql_files = self._find_sql_files_recursive(directory_path)

            if not sql_files:
                self.logger.warning(f"No SQL files found in: {directory_path}")
                return (True, 0)

            # Filter files by modification time if timestamp provided
            files_to_execute = []
            skipped_count = 0

            for file_path in sql_files:
                if last_deployment_timestamp is not None:
                    file_mtime = os.path.getmtime(file_path)
                    if file_mtime <= last_deployment_timestamp:
                        # File hasn't changed since last deployment, skip it
                        skipped_count += 1
                        continue

                files_to_execute.append(file_path)

            if skipped_count > 0:
                self.logger.debug(f"Skipped {skipped_count} unchanged SQL file(s)")

            if not files_to_execute:
                self.logger.info(f"No SQL files need to be executed in {os.path.basename(directory_path)}")
                return (True, 0)

            self.logger.debug(f"Found {len(files_to_execute)} SQL file(s) to execute in {os.path.basename(directory_path)}")

            success = True
            for file_path in files_to_execute:
                if not self.execute_sql_file(file_path, dry_run, use_database=use_database, template_vars=template_vars, database_name=database_name):
                    success = False
                    # Continue executing other files even if one fails
                    # but track that there was a failure

            return (success, len(files_to_execute))

        except Exception as e:
            self.logger.error(f"Error executing SQL directory {directory_path}: {e}")
            return (False, 0)

    def database_exists(self, database_name: str) -> bool:
        """
        Check if a database exists.

        Args:
            database_name: Name of the database to check

        Returns:
            True if database exists, False otherwise
        """
        try:
            # Query to check if database exists
            check_cmd = f"mysql -h {self.db_host} -P {self.db_port} -u {self.db_username} -p{self.db_password} -e \"SHOW DATABASES LIKE '{database_name}'\""

            stdin, stdout, stderr = self.ssh_client.exec_command(check_cmd)
            exit_status = stdout.channel.recv_exit_status()

            if exit_status != 0:
                return False

            output = stdout.read().decode()
            # If output contains the database name, it exists
            return database_name in output

        except Exception as e:
            self.logger.error(f"Error checking if database exists: {e}")
            return False

    def execute_sql_command(self, sql_command: str, dry_run: bool = False, database_name: str = None) -> bool:
        """
        Execute a SQL command directly on the database.

        Args:
            sql_command: SQL command to execute
            dry_run: If True, only show what would be executed
            database_name: Optional database name to use

        Returns:
            True if execution successful
        """
        try:
            if dry_run:
                self.logger.info(f"  [DRY RUN] Would execute SQL: {sql_command}")
                return True

            self.logger.debug(f"  Executing SQL: {sql_command}")

            # Upload SQL to temp file to avoid shell escaping issues (especially with $ in bcrypt hashes)
            # Convert Windows line endings (CRLF) to Unix (LF)
            sql_content_unix = sql_command.replace('\r\n', '\n').replace('\r', '\n')

            import hashlib
            temp_sql_path = f"/tmp/deploy_sql_{hashlib.md5(sql_command.encode()).hexdigest()}.sql"
            sftp = self.ssh_client.open_sftp()
            try:
                with sftp.file(temp_sql_path, 'w') as remote_file:
                    remote_file.write(sql_content_unix)
            finally:
                sftp.close()

            # Build MySQL command to execute the uploaded file
            mysql_cmd = f"mysql -h {self.db_host} -P {self.db_port} -u {self.db_username} -p{self.db_password}"

            # Add database name if provided
            if database_name:
                mysql_cmd += f" {database_name}"

            # Execute the SQL file
            stdin, stdout, stderr = self.ssh_client.exec_command(f"{mysql_cmd} < {temp_sql_path}")
            exit_status = stdout.channel.recv_exit_status()

            # Clean up temp file
            self.ssh_client.exec_command(f"rm -f {temp_sql_path}")

            if exit_status != 0:
                error = stderr.read().decode()
                self.logger.error(f"  Error executing SQL command: {error}")
                return False

            self.logger.info(f"  ✓ Successfully executed SQL command")
            return True

        except Exception as e:
            self.logger.error(f"Error executing SQL command: {e}")
            return False

    def _extract_sql_template(self, table_script_file: str, begin_mark: str, end_mark: str) -> Optional[str]:
        """
        Extract SQL INSERT template from between BEGIN and END markers in a SQL file.

        Args:
            table_script_file: Path to SQL table definition file
            begin_mark: Beginning marker (e.g., "BEGIN AI-AGENT.AI-DEPLOY:")
            end_mark: Ending marker (e.g., "END AI-AGENT.AI-DEPLOY:")

        Returns:
            SQL INSERT template string, or None if not found
        """
        try:
            if not os.path.exists(table_script_file):
                self.logger.error(f"Table script file not found: {table_script_file}")
                return None

            with open(table_script_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Find content between markers
            pattern = re.escape(begin_mark) + r'(.*?)' + re.escape(end_mark)
            match = re.search(pattern, content, re.DOTALL)

            if not match:
                self.logger.error(f"Markers not found in {table_script_file}: {begin_mark} ... {end_mark}")
                return None

            template = match.group(1).strip()
            return template

        except Exception as e:
            self.logger.error(f"Error extracting SQL template from {table_script_file}: {e}")
            return None

    def _get_json_value(self, json_obj: Dict[str, Any], field_path: str) -> Any:
        """
        Get value from JSON object using dot notation for nested fields.

        Args:
            json_obj: JSON object to navigate
            field_path: Field path (e.g., "terminology.employee")

        Returns:
            Value at field path, or None if not found
        """
        try:
            keys = field_path.split('.')
            value = json_obj

            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return None

            return value

        except Exception as e:
            self.logger.error(f"Error getting JSON value for path '{field_path}': {e}")
            return None

    def _hash_password(self, plain_password: str) -> str:
        """
        Hash a password using bcrypt compatible with PHP's PASSWORD_DEFAULT.

        Uses cost factor 10 (matching PHP's PASSWORD_DEFAULT) and $2y$ identifier
        for exact compatibility with PHP's password_hash() function.

        Args:
            plain_password: Plain text password

        Returns:
            Bcrypt hashed password string in PHP PASSWORD_DEFAULT format
            Example: $2y$10$xnDBJl/1Q9v4qs42b67pZOTgBFkr6iHJCkDCHdtDARKJrVRq.p2dW
        """
        try:
            # Generate salt with cost factor 10 (matching PHP's PASSWORD_DEFAULT)
            salt = bcrypt.gensalt(rounds=10)
            hashed = bcrypt.hashpw(plain_password.encode('utf-8'), salt)
            hash_str = hashed.decode('utf-8')

            # Convert $2b$ to $2y$ for exact PHP compatibility
            # Python's bcrypt uses $2b$, PHP uses $2y$, but they're interoperable
            # This ensures exact format match with PHP's password_hash()
            if hash_str.startswith('$2b$'):
                hash_str = '$2y$' + hash_str[4:]

            return hash_str

        except Exception as e:
            self.logger.error(f"Error hashing password: {e}")
            return plain_password  # Return original if hashing fails

    def _replace_seed_variables(
        self,
        sql_template: str,
        variables: List[Dict[str, Any]],
        json_data: Dict[str, Any],
        parent_data: Optional[Dict[str, Any]] = None,
        config_file_name: Optional[str] = None,
        table_name: Optional[str] = None,
        warn_on_missing: bool = True
    ) -> str:
        """
        Replace template variables in SQL with values from JSON data.

        Args:
            sql_template: SQL template with {{VARIABLE}} placeholders
            variables: List of variable definitions with sql_var, json_field, and optional from_parent
            json_data: JSON data object (current element or parent)
            parent_data: Parent JSON data object (for from_parent variables)
            config_file_name: Optional config file name for better error messages
            table_name: Optional table name for better error messages
            warn_on_missing: If True, log warnings for missing JSON fields (default: True)

        Returns:
            SQL string with variables replaced
        """
        try:
            result = sql_template

            for var_def in variables:
                sql_var = var_def.get('sql_var', '')
                json_field = var_def.get('json_field', '')
                from_parent = var_def.get('from_parent', False)
                default_value = var_def.get('default_value', None)

                # Determine which JSON object to use
                source_data = parent_data if from_parent and parent_data else json_data

                # Get value from JSON
                # Special case: if json_field is "." or empty, and source_data is a primitive, use it directly
                if (json_field == '.' or json_field == '') and not isinstance(source_data, dict):
                    # source_data is a primitive value (string, int, etc.) from an array
                    value = source_data
                else:
                    # source_data is a dict/object, navigate to the field
                    value = self._get_json_value(source_data, json_field)

                    # Use default value if JSON field not found and default is specified
                    if value is None and default_value is not None:
                        value = default_value

                # Check if this is a password field that should be hashed
                # Only hash PASSWORD_HASH or PASSWORD, not fields like RESET_PASSWORD
                sql_var_upper = sql_var.upper()
                is_password_field = (
                    ('PASSWORD_HASH' in sql_var_upper or sql_var_upper == '{{PASSWORD}}')
                    and value is not None
                )
                if is_password_field:
                    value = self._hash_password(str(value))

                # Check if value is a SQL function (e.g., NOW(), CURRENT_TIMESTAMP(), UUID())
                is_sql_function = isinstance(value, str) and value.strip().upper().endswith('()')

                # Convert value to SQL format based on type
                if value is None:
                    sql_value = 'NULL'
                elif isinstance(value, (int, float)):
                    sql_value = str(value)
                elif isinstance(value, bool):
                    sql_value = '1' if value else '0'
                elif isinstance(value, (dict, list)):
                    # JSON object/array - serialize to JSON string and escape single quotes
                    # MySQL JSON column expects valid JSON format
                    json_str = json.dumps(value, ensure_ascii=False)
                    sql_value = json_str.replace("'", "''")
                elif is_password_field:
                    # Password hash - use UNHEX to avoid shell escaping issues with $ characters
                    # Convert the bcrypt hash to hex representation
                    hex_value = value.encode('utf-8').hex()
                    sql_value = f"UNHEX('{hex_value}')"
                elif is_sql_function:
                    # SQL function - use as-is without quotes
                    sql_value = str(value).strip()
                else:
                    # String value - escape single quotes but DON'T wrap in quotes
                    # The SQL template itself should have quotes (e.g., '{{NAME}}')
                    sql_value = str(value).replace("'", "''")

                # Replace the variable in template
                # Handle both quoted ('{{VAR}}') and unquoted ({{VAR}}) patterns
                quoted_pattern = f"'{sql_var}'"

                if quoted_pattern in result:
                    # Template has quotes around variable: '{{VAR}}'
                    if value is None:
                        # For NULL, remove the quotes: '{{VAR}}' -> NULL
                        result = result.replace(quoted_pattern, sql_value)
                    elif is_password_field:
                        # For password hashes using UNHEX, remove the quotes completely
                        # '{{PASSWORD_HASH}}' -> UNHEX('...')
                        result = result.replace(quoted_pattern, sql_value)
                    elif is_sql_function:
                        # For SQL functions, remove the quotes: '{{VAR}}' -> NOW()
                        result = result.replace(quoted_pattern, sql_value)
                    else:
                        # For other values, keep the quotes: '{{VAR}}' -> 'value'
                        result = result.replace(sql_var, sql_value)
                else:
                    # Template doesn't have quotes: {{VAR}}
                    result = result.replace(sql_var, sql_value)

                # Log if value was missing
                if value is None and warn_on_missing:
                    context = ""
                    if config_file_name and table_name:
                        context = f" in file '{config_file_name}' for table '{table_name}'"
                    elif config_file_name:
                        context = f" in file '{config_file_name}'"
                    elif table_name:
                        context = f" for table '{table_name}'"
                    self.logger.warning(f"JSON field '{json_field}' not found{context}, using NULL for {sql_var}")

            return result

        except Exception as e:
            self.logger.error(f"Error replacing seed variables: {e}")
            return sql_template

    def _check_table_has_data(
        self,
        check_query: str,
        database_name: str,
        variables: List[Dict[str, Any]] = None,
        json_data: Dict[str, Any] = None,
        parent_data: Optional[Dict[str, Any]] = None,
        dry_run: bool = False
    ) -> bool:
        """
        Execute a check query to determine if a table has data.
        Supports variable replacement in the query.

        Args:
            check_query: SQL query that returns a count (e.g., "SELECT COUNT(1) FROM table WHERE webid = '{{WEBID}}'")
            database_name: Database name to query
            variables: List of variable definitions for replacement
            json_data: JSON data object for variable replacement
            parent_data: Parent JSON data object (for from_parent variables)
            dry_run: If True, assume table is empty

        Returns:
            True if table has data (count > 0), False otherwise
        """
        try:
            if dry_run:
                return False  # Assume empty in dry-run mode

            # Replace variables in check query if provided
            query_to_execute = check_query
            if variables and json_data:
                query_to_execute = self._replace_seed_variables(
                    check_query,
                    variables,
                    json_data,
                    parent_data,
                    warn_on_missing=False  # Don't warn for check queries
                )

            # Log the query being executed for debugging
            self.logger.debug(f"  Executing check query: {query_to_execute}")

            # Upload SQL to temp file to avoid shell variable expansion issues
            import hashlib
            temp_sql_path = f"/tmp/check_query_{hashlib.md5(query_to_execute.encode()).hexdigest()}.sql"

            # Convert to Unix line endings
            sql_content_unix = query_to_execute.replace('\r\n', '\n')

            # Upload the SQL to temp file
            sftp = self.ssh_client.open_sftp()
            with sftp.file(temp_sql_path, 'w') as remote_file:
                remote_file.write(sql_content_unix)
            sftp.close()

            # Execute from file
            mysql_cmd = f"mysql -h {self.db_host} -P {self.db_port} -u {self.db_username} -p{self.db_password} {database_name} -N < {temp_sql_path}"

            stdin, stdout, stderr = self.ssh_client.exec_command(mysql_cmd)
            exit_status = stdout.channel.recv_exit_status()

            # Clean up temp file
            self.ssh_client.exec_command(f"rm -f {temp_sql_path}")

            if exit_status != 0:
                error = stderr.read().decode()
                # Check if error is because table doesn't exist (MySQL error 1146)
                # This is expected on clean installs, so only log as debug
                if "ERROR 1146" in error or "doesn't exist" in error.lower():
                    self.logger.debug(f"Check query failed (table may not exist yet): {error.strip()}")
                else:
                    self.logger.error(f"Error executing check query: {error}")
                return False

            output = stdout.read().decode().strip()

            # Parse count result
            try:
                count = int(output)
                self.logger.debug(f"  Check query returned count: {count}")
                return count > 0
            except ValueError:
                self.logger.error(f"Invalid count result from check query: {output}")
                return False

        except Exception as e:
            self.logger.error(f"Error checking table data: {e}")
            return False

    def deploy_database(
        self,
        admin_username: str,
        admin_password: str,
        main_database_scripts: Optional[dict] = None,
        tenant_database_scripts: Optional[List[dict]] = None,
        dry_run: bool = False,
        last_deployment_timestamp: float = None,
        application_name: str = None
    ) -> tuple[bool, bool]:
        """
        Deploy database by executing main and tenant scripts in order.
        Optionally skip scripts that haven't been modified since last deployment.

        Args:
            admin_username: Admin username for template variables
            admin_password: Admin password for template variables
            main_database_scripts: Dictionary with db_name, db_username, db_password, setup_path, tables_path, procedures_path, seeds_path
            tenant_database_scripts: List of dictionaries, each with db_name, db_username, db_password, setup_path, tables_path, procedures_path, seeds_path
            dry_run: If True, only show what would be executed
            last_deployment_timestamp: Unix timestamp of last deployment, skip SQL files older than this
            application_name: Application name for {{APPLICATION_NAME}} template variable replacement

        Returns:
            Tuple of (success: bool, any_scripts_executed: bool)
        """
        try:
            # Connect to database first
            if not dry_run:
                if not self._connect_database():
                    return (False, False)

            success = True
            any_scripts_executed = False

            # MAIN DATABASE DEPLOYMENT
            if main_database_scripts:
                self.logger.warning("=" * 60)
                self.logger.warning("MAIN DATABASE DEPLOYMENT")
                self.logger.warning("=" * 60)

                # Build template variables for main database
                main_template_vars = {
                    'ADMIN_USERNAME': admin_username,
                    'ADMIN_PASSWORD': admin_password,
                    'MAIN_DB_NAME': main_database_scripts.get('db_name'),
                    'MAIN_DB_USERNAME': main_database_scripts.get('db_username'),
                    'MAIN_DB_PASSWORD': main_database_scripts.get('db_password')
                }
                # Add APPLICATION_NAME if provided
                if application_name:
                    main_template_vars['APPLICATION_NAME'] = application_name

                # Check if main database exists
                main_db_name = main_database_scripts.get('db_name')
                main_db_exists = self.database_exists(main_db_name) if not dry_run else True

                # Force setup scripts to run if database doesn't exist
                setup_timestamp = last_deployment_timestamp if main_db_exists else None
                if not main_db_exists and not dry_run:
                    self.logger.info(f"Database '{main_db_name}' does not exist, forcing setup scripts to run")

                # 1. Execute main setup scripts (without specifying database name)
                if main_database_scripts.get('setup_path'):
                    self.logger.info("=" * 60)
                    self.logger.warning("STEP 1: Running main database setup scripts")
                    self.logger.info("=" * 60)
                    dir_success, files_executed = self.execute_sql_directory(main_database_scripts['setup_path'], dry_run, use_database=False, template_vars=main_template_vars, last_deployment_timestamp=setup_timestamp)
                    if not dir_success:
                        success = False
                    if files_executed > 0:
                        any_scripts_executed = True

                # 2. Execute main table scripts
                if main_database_scripts.get('tables_path'):
                    self.logger.info("=" * 60)
                    self.logger.warning("STEP 2: Creating main database tables")
                    self.logger.info("=" * 60)
                    dir_success, files_executed = self.execute_sql_directory(main_database_scripts['tables_path'], dry_run, template_vars=main_template_vars, last_deployment_timestamp=last_deployment_timestamp)
                    if not dir_success:
                        success = False
                    if files_executed > 0:
                        any_scripts_executed = True

                # 3. Execute main procedure scripts
                if main_database_scripts.get('procedures_path'):
                    self.logger.info("=" * 60)
                    self.logger.warning("STEP 3: Creating main database procedures")
                    self.logger.info("=" * 60)
                    dir_success, files_executed = self.execute_sql_directory(main_database_scripts['procedures_path'], dry_run, template_vars=main_template_vars, last_deployment_timestamp=last_deployment_timestamp)
                    if not dir_success:
                        success = False
                    if files_executed > 0:
                        any_scripts_executed = True

                # 4. Execute main seed scripts
                if main_database_scripts.get('seeds_path'):
                    self.logger.info("=" * 60)
                    self.logger.warning("STEP 4: Seeding main database data")
                    self.logger.info("=" * 60)
                    dir_success, files_executed = self.execute_sql_directory(main_database_scripts['seeds_path'], dry_run, template_vars=main_template_vars, last_deployment_timestamp=last_deployment_timestamp)
                    if not dir_success:
                        success = False
                    if files_executed > 0:
                        any_scripts_executed = True

            # TENANT DATABASE DEPLOYMENT
            if tenant_database_scripts:
                self.logger.warning("=" * 60)
                self.logger.warning("TENANT DATABASE DEPLOYMENT")
                self.logger.warning("=" * 60)

                for tenant_config in tenant_database_scripts:
                    tenant_name = tenant_config.get('db_name')
                    self.logger.warning("=" * 60)
                    self.logger.warning(f"DEPLOYING TENANT: {tenant_name}")
                    self.logger.warning("=" * 60)

                    # Extract tenant webid from database name (e.g., "agencyos_livingwater" -> "livingwater")
                    tenant_webid = None
                    if application_name and tenant_name:
                        # Remove application_name prefix and underscore
                        prefix = f"{application_name}_"
                        if tenant_name.startswith(prefix):
                            tenant_webid = tenant_name[len(prefix):]
                        else:
                            # Fallback: use entire database name if pattern doesn't match
                            tenant_webid = tenant_name

                    # Build template variables for this tenant
                    tenant_template_vars = {
                        'ADMIN_USERNAME': admin_username,
                        'ADMIN_PASSWORD': admin_password,
                        'MAIN_DB_NAME': main_database_scripts.get('db_name') if main_database_scripts else None,
                        'MAIN_DB_USERNAME': main_database_scripts.get('db_username') if main_database_scripts else None,
                        'MAIN_DB_PASSWORD': main_database_scripts.get('db_password') if main_database_scripts else None,
                        'TENANT_DB_NAME': tenant_config.get('db_name'),
                        'TENANT_DB_USERNAME': tenant_config.get('db_username'),
                        'TENANT_DB_PASSWORD': tenant_config.get('db_password'),
                        'TENANT_WEBID': tenant_webid
                    }
                    # Add APPLICATION_NAME if provided
                    if application_name:
                        tenant_template_vars['APPLICATION_NAME'] = application_name

                    # Check if tenant database exists
                    tenant_db_exists = self.database_exists(tenant_name) if not dry_run else True

                    # Force setup scripts to run if database doesn't exist
                    tenant_setup_timestamp = last_deployment_timestamp if tenant_db_exists else None
                    if not tenant_db_exists and not dry_run:
                        self.logger.info(f"Database '{tenant_name}' does not exist, forcing setup scripts to run")

                    # 1. Execute tenant setup scripts (creates database if needed)
                    if tenant_config.get('setup_path'):
                        self.logger.info("=" * 60)
                        self.logger.warning(f"STEP 1: Running setup scripts for tenant '{tenant_name}'")
                        self.logger.info("=" * 60)
                        dir_success, files_executed = self.execute_sql_directory(tenant_config['setup_path'], dry_run, use_database=False, template_vars=tenant_template_vars, last_deployment_timestamp=tenant_setup_timestamp)
                        if not dir_success:
                            success = False
                        if files_executed > 0:
                            any_scripts_executed = True

                    # 2. Switch to tenant database
                    self.logger.info("=" * 60)
                    self.logger.warning(f"STEP 2: Switching to tenant database '{tenant_name}'")
                    self.logger.info("=" * 60)
                    if not self.execute_sql_command(f"USE {tenant_name}", dry_run):
                        success = False
                        continue  # Skip to next tenant if we can't switch databases

                    # 3. Execute tenant table scripts
                    if tenant_config.get('tables_path'):
                        self.logger.info("=" * 60)
                        self.logger.warning(f"STEP 3: Creating tables for tenant '{tenant_name}'")
                        self.logger.info("=" * 60)
                        dir_success, files_executed = self.execute_sql_directory(tenant_config['tables_path'], dry_run, use_database=True, template_vars=tenant_template_vars, database_name=tenant_name, last_deployment_timestamp=last_deployment_timestamp)
                        if not dir_success:
                            success = False
                        if files_executed > 0:
                            any_scripts_executed = True

                    # 4. Execute tenant procedure scripts
                    if tenant_config.get('procedures_path'):
                        self.logger.info("=" * 60)
                        self.logger.warning(f"STEP 4: Creating procedures for tenant '{tenant_name}'")
                        self.logger.info("=" * 60)
                        dir_success, files_executed = self.execute_sql_directory(tenant_config['procedures_path'], dry_run, use_database=True, template_vars=tenant_template_vars, database_name=tenant_name, last_deployment_timestamp=last_deployment_timestamp)
                        if not dir_success:
                            success = False
                        if files_executed > 0:
                            any_scripts_executed = True

                    # 5. Execute tenant seed scripts
                    if tenant_config.get('seeds_path'):
                        self.logger.info("=" * 60)
                        self.logger.warning(f"STEP 5: Seeding data for tenant '{tenant_name}'")
                        self.logger.info("=" * 60)
                        dir_success, files_executed = self.execute_sql_directory(tenant_config['seeds_path'], dry_run, use_database=True, template_vars=tenant_template_vars, database_name=tenant_name, last_deployment_timestamp=last_deployment_timestamp)
                        if not dir_success:
                            success = False
                        if files_executed > 0:
                            any_scripts_executed = True

            return (success, any_scripts_executed)

        except Exception as e:
            self.logger.error(f"Error during database deployment: {e}")
            return (False, False)

    def seed_tables_from_config(
        self,
        seed_tables_config: Dict[str, Any],
        database_name: str,
        dry_run: bool = False,
        is_tenant_db: bool = False,
        application_name: str = None
    ) -> tuple[bool, int]:
        """
        Seed database tables from JSON configuration files.

        Args:
            seed_tables_config: Seed tables configuration dictionary
            database_name: Database name to seed
            dry_run: If True, only show what would be executed
            is_tenant_db: If True, only process JSON files where webid matches database_name
            application_name: Application name for building expected database name from webid

        Returns:
            Tuple of (success: bool, total_records_inserted: int)
        """
        try:
            if not seed_tables_config.get('enabled', False):
                self.logger.info("Table seeding is disabled")
                return (True, 0)

            config_files_path = seed_tables_config.get('config_files_path')
            config_files_extension = seed_tables_config.get('config_files_extension', '.json')
            tables = seed_tables_config.get('tables', [])

            if not config_files_path or not os.path.exists(config_files_path):
                self.logger.error(f"Config files path not found: {config_files_path}")
                return (False, 0)

            if not os.path.isdir(config_files_path):
                self.logger.error(f"Config files path is not a directory: {config_files_path}")
                return (False, 0)

            # Get all JSON config files
            config_files = []
            for file in os.listdir(config_files_path):
                if file.endswith(config_files_extension):
                    config_files.append(os.path.join(config_files_path, file))

            if not config_files:
                self.logger.warning(f"No config files found in: {config_files_path}")
                return (True, 0)

            config_files.sort()  # Process in alphabetical order
            self.logger.info(f"Found {len(config_files)} config file(s) to process")

            success = True
            total_records_inserted = 0

            # Process each config file
            for config_file_path in config_files:
                config_file_name = os.path.basename(config_file_path)
                self.logger.debug("=" * 60)
                self.logger.debug(f"Processing config file: {config_file_name}")
                self.logger.debug("=" * 60)

                try:
                    # Read JSON config file
                    with open(config_file_path, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)

                    # For tenant databases, only process the JSON file that matches the database name
                    # Build expected database name from application_name and webid
                    if is_tenant_db:
                        json_webid = json_data.get('webid', '')

                        # Build expected database name: {application_name}_{webid}
                        if application_name:
                            expected_db_name = f"{application_name}_{json_webid}"
                        else:
                            # Fallback: just use webid (for backwards compatibility)
                            expected_db_name = json_webid

                        if expected_db_name != database_name:
                            self.logger.info(f"  ⊘ Skipping config file - expected database '{expected_db_name}' does not match '{database_name}'")
                            continue

                    # Process each table definition
                    for table_def in tables:
                        table_name = table_def.get('table_name')
                        table_script_file = table_def.get('table_script_file')
                        begin_mark = table_def.get('begin_mark')
                        end_mark = table_def.get('end_mark')
                        check_exists_query = table_def.get('check_exists_query')
                        variables = table_def.get('variables', [])
                        array_field = table_def.get('array_field')
                        nested_array_field = table_def.get('nested_array_field')

                        self.logger.info(f"Processing table: {table_name}")

                        # Check if data already exists
                        # For non-array tables: checks if the specific record exists
                        # For array tables: checks if any records exist for this tenant (before processing entire array)
                        if check_exists_query:
                            has_data = self._check_table_has_data(
                                check_exists_query,
                                database_name,
                                variables=variables,
                                json_data=json_data,
                                parent_data=None,
                                dry_run=dry_run
                            )
                            if has_data:
                                if array_field:
                                    self.logger.info(f"  ⊘ Skipping {table_name} - data already exists for this tenant")
                                else:
                                    self.logger.info(f"  ⊘ Skipping {table_name} - record already exists")
                                continue

                        # Extract SQL template from table script file
                        sql_template = self._extract_sql_template(table_script_file, begin_mark, end_mark)
                        if not sql_template:
                            self.logger.error(f"  ✗ Failed to extract SQL template from {table_script_file}")
                            success = False
                            continue

                        # Process based on whether array_field is specified
                        if array_field:
                            # Get array from JSON
                            array_data = self._get_json_value(json_data, array_field)
                            if not array_data or not isinstance(array_data, list):
                                self.logger.debug(f"  ⊘ Array field '{array_field}' not found or empty in {config_file_name}")
                                continue

                            records_inserted = 0

                            # Check if this is a nested array scenario
                            if nested_array_field:
                                # Nested array: loop through outer array, then inner array
                                for outer_element in array_data:
                                    # Get nested array from outer element
                                    nested_array = self._get_json_value(outer_element, nested_array_field)
                                    if not nested_array or not isinstance(nested_array, list):
                                        # Skip if nested array not found or empty for this outer element
                                        continue

                                    # Insert one row per nested element
                                    for nested_element in nested_array:
                                        # For nested arrays, variable hierarchy is:
                                        # - element = nested_element (the role)
                                        # - parent_data = outer_element (the user)
                                        # - Variables with from_parent:true that reference root fields need special handling

                                        # We need to modify _replace_seed_variables to support grandparent
                                        # For now, use a merged approach: merge root and outer element for parent_data
                                        merged_parent = {**json_data, **outer_element}

                                        sql_statement = self._replace_seed_variables(
                                            sql_template,
                                            variables,
                                            nested_element,
                                            parent_data=merged_parent,
                                            config_file_name=config_file_name,
                                            table_name=table_name
                                        )

                                        # Execute INSERT
                                        if dry_run:
                                            self.logger.info(f"  [DRY RUN] Would insert record into {table_name}")
                                        else:
                                            if self.execute_sql_command(sql_statement, dry_run=False, database_name=database_name):
                                                records_inserted += 1
                                                total_records_inserted += 1
                                            else:
                                                success = False
                            else:
                                # Single array: insert one row per array element
                                for element in array_data:
                                    sql_statement = self._replace_seed_variables(
                                        sql_template,
                                        variables,
                                        element,
                                        parent_data=json_data,
                                        config_file_name=config_file_name,
                                        table_name=table_name
                                    )

                                    # Execute INSERT
                                    if dry_run:
                                        self.logger.info(f"  [DRY RUN] Would insert record into {table_name}")
                                    else:
                                        if self.execute_sql_command(sql_statement, dry_run=False, database_name=database_name):
                                            records_inserted += 1
                                            total_records_inserted += 1
                                        else:
                                            success = False

                            if records_inserted > 0 or dry_run:
                                self.logger.info(f"  ✓ Inserted {records_inserted} record(s) into {table_name}")

                        else:
                            # Insert single record from parent JSON
                            sql_statement = self._replace_seed_variables(
                                sql_template,
                                variables,
                                json_data,
                                config_file_name=config_file_name,
                                table_name=table_name
                            )

                            # Execute INSERT
                            if dry_run:
                                self.logger.info(f"  [DRY RUN] Would insert 1 record into {table_name}")
                            else:
                                if self.execute_sql_command(sql_statement, dry_run=False, database_name=database_name):
                                    total_records_inserted += 1
                                    self.logger.info(f"  ✓ Inserted 1 record into {table_name}")
                                else:
                                    success = False

                except json.JSONDecodeError as e:
                    self.logger.error(f"  ✗ Malformed JSON file {config_file_name}: {e}")
                    success = False
                    continue
                except Exception as e:
                    self.logger.error(f"  ✗ Error processing {config_file_name}: {e}")
                    success = False
                    continue

            # Summary
            self.logger.info("=" * 60)
            self.logger.info("TABLE SEEDING SUMMARY")
            self.logger.info("=" * 60)
            self.logger.info(f"Config files processed: {len(config_files)}")
            self.logger.info(f"Total records inserted: {total_records_inserted}")

            return (success, total_records_inserted)

        except Exception as e:
            self.logger.error(f"Error during table seeding: {e}")
            return (False, 0)
