"""Test script to verify installation and imports."""
import sys


def test_imports():
    """Test that all required modules can be imported."""
    print("Testing imports...")

    try:
        from core.agent_base import AgentBase
        print("✓ Core agent_base imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import agent_base: {e}")
        return False

    try:
        from core.config_loader import ConfigLoader
        print("✓ Core config_loader imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import config_loader: {e}")
        return False

    try:
        from handlers.windows_share_handler import WindowsShareHandler
        print("✓ Windows share handler imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import windows_share_handler: {e}")
        return False

    try:
        from handlers.ssh_handler import SSHHandler
        print("✓ SSH handler imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import ssh_handler: {e}")
        return False

    try:
        from agents.ai_deploy import AiDeployAgent
        print("✓ AI Deploy agent imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import ai_deploy: {e}")
        return False

    return True


def test_dependencies():
    """Test that required dependencies are installed."""
    print("\nTesting dependencies...")

    try:
        import paramiko
        print(f"✓ paramiko {paramiko.__version__} installed")
    except ImportError:
        print("✗ paramiko not installed - run: pip install -r requirements.txt")
        return False

    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("AI Agent Framework - Installation Test")
    print("=" * 60)

    all_passed = True

    if not test_imports():
        all_passed = False

    if not test_dependencies():
        all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All tests passed! Installation is correct.")
        print("\nNext steps:")
        print("1. Review the example configurations in config/")
        print("2. Create your own configuration file")
        print("3. Run: python main.py config/your-config.json")
    else:
        print("✗ Some tests failed. Please fix the issues above.")
        sys.exit(1)
    print("=" * 60)


if __name__ == '__main__':
    main()
