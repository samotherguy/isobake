class IsobakeError(Exception):
    """Base class. ``exit_code`` maps to the CLI exit status."""

    exit_code = 1


class ConfigError(IsobakeError):
    exit_code = 1


class BuildError(IsobakeError):
    exit_code = 2


class VerifyError(IsobakeError):
    exit_code = 3


class MissingTool(BuildError):
    def __init__(self, tool: str, package: str):
        super().__init__(f"`{tool}` not found. Install it: sudo apt install {package}")
