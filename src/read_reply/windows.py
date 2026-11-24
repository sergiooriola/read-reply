"""Windows, seen from WSL: the PowerShell scripts that do what only Windows can,
such as reading its clipboard."""

import base64
import subprocess

from read_reply.errors import UserError

POWERSHELL = "powershell.exe"
# Windows programs started from WSL need a Windows working directory.
WINDOWS_CWD = "/mnt/c"
# In UTF-8 whatever the console's code page; nothing when the clipboard holds
# no text, such as an image.
CLIPBOARD_SCRIPT = """
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$text = Get-Clipboard -Raw
if ($text) { [Console]::Out.Write($text) }
"""


def powershell_command(script: str) -> list[str]:
    """The command that runs the script, passed whole: no quoting, no files."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    return [POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


def clipboard_text() -> str:
    """The text in the Windows clipboard, or "" when it holds none."""
    try:
        result = subprocess.run(
            powershell_command(CLIPBOARD_SCRIPT),
            stdout=subprocess.PIPE,
            # In the console's code page, not UTF-8: "Excepción" would not decode.
            stderr=subprocess.DEVNULL,
            encoding="utf-8",  # with Windows' line ends turned into "\n"
            cwd=WINDOWS_CWD,
            check=False,
        )
    except OSError as error:
        raise UserError("No puedo leer el portapapeles de Windows.") from error
    if result.returncode != 0:
        raise UserError("No puedo leer el portapapeles de Windows.")
    return result.stdout
