"""Windows, seen from WSL: the PowerShell scripts that do what only Windows can."""

import base64

POWERSHELL = "powershell.exe"
# Windows programs started from WSL need a Windows working directory.
WINDOWS_CWD = "/mnt/c"


def powershell_command(script: str) -> list[str]:
    """The command that runs the script, passed whole: no quoting, no files."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    return [POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
