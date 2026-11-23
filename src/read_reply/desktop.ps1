# The reading window's place on the Windows desktop, and the focus handed back.
#
# 1. Prints, as one line of JSON, the terminal's window (the Windows Terminal
#    window last in front, else the window in front) and the top-left corner
#    of its monitor, in physical pixels, and that monitor's scale; or null.
# 2. Follows which window is in front, until a line of JSON on stdin says
#    that Edge has started: its profile, and where its window goes, in
#    physical pixels. End of input ends the script.
# 3. Once that Edge's window comes to the front, puts it in its place, above
#    the other windows, so that the terminal does not cover it, and gives the
#    focus back to the window in front before it.
param([double] $WaitSeconds = 10)

$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class Desktop {
  [StructLayout(LayoutKind.Sequential)]
  public struct Rect { public int Left, Top, Right, Bottom; }

  [StructLayout(LayoutKind.Sequential)]
  public struct MonitorInfo { public int Size; public Rect Monitor; public Rect Work; public uint Flags; }

  [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint from, uint to, bool attach);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern IntPtr MonitorFromWindow(IntPtr window, uint flags);
  [DllImport("user32.dll")] public static extern bool GetMonitorInfo(IntPtr monitor, ref MonitorInfo info);
  [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr window);
  [DllImport("user32.dll")] public static extern IntPtr GetTopWindow(IntPtr parent);
  [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr window, uint command);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr window);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)]
  public static extern int GetClassName(IntPtr window, System.Text.StringBuilder name, int length);
  [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr window, int attribute, out Rect rect, int size);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y, int width, int height, uint flags);

  // The Windows Terminal window highest in the Z order: the one last in front.
  public static IntPtr Terminal() {
    var name = new System.Text.StringBuilder(64);
    for (var window = GetTopWindow(IntPtr.Zero); window != IntPtr.Zero; window = GetWindow(window, 2 /* GW_HWNDNEXT */)) {
      GetClassName(window, name, name.Capacity);
      if (name.ToString() == "CASCADIA_HOSTING_WINDOW_CLASS" && IsWindowVisible(window) && !IsIconic(window)) return window;
    }
    return IntPtr.Zero;
  }
}
"@

# Per-monitor aware (v2): real pixels on every monitor.
[void][Desktop]::SetThreadDpiAwarenessContext([IntPtr](-4))

$front = [Desktop]::GetForegroundWindow()
$terminal = [Desktop]::Terminal()
if ($terminal -eq [IntPtr]::Zero) { $terminal = $front }
# The frame as drawn, without the invisible borders for resizing.
$frame = New-Object Desktop+Rect
$frameBounds = 9  # DWMWA_EXTENDED_FRAME_BOUNDS
$framed = $terminal -ne [IntPtr]::Zero -and
  [Desktop]::DwmGetWindowAttribute($terminal, $frameBounds, [ref]$frame, 16) -eq 0 -and
  $frame.Right -gt $frame.Left
if ($framed) {
  $info = New-Object Desktop+MonitorInfo
  $info.Size = [Runtime.InteropServices.Marshal]::SizeOf($info)
  $nearest = 2  # MONITOR_DEFAULTTONEAREST
  [void][Desktop]::GetMonitorInfo([Desktop]::MonitorFromWindow($terminal, $nearest), [ref]$info)
  $dpi = [Desktop]::GetDpiForWindow($terminal)
  [Console]::Out.WriteLine((@{
    left = $frame.Left; top = $frame.Top; right = $frame.Right
    monitor_left = $info.Monitor.Left; monitor_top = $info.Monitor.Top
    scale = $(if ($dpi) { $dpi / 96.0 } else { 1.0 })
  } | ConvertTo-Json -Compress))
} else {
  [Console]::Out.WriteLine('null')
}
[Console]::Out.Flush()

# Read without blocking, to follow the window in front meanwhile.
$stdin = New-Object IO.StreamReader([Console]::OpenStandardInput())
$line = $stdin.ReadLineAsync()
[void](Get-CimInstance Win32_Process -Filter "ProcessId = $PID")  # warms CIM up

$owners = @{}  # process id: whether it is the reading's Edge
function Test-Reader([IntPtr] $window, [string] $edgeProfile) {
  $processId = 0
  [void][Desktop]::GetWindowThreadProcessId($window, [ref]$processId)
  if (-not $owners.ContainsKey($processId)) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    $owners[$processId] = $process.Name -eq 'msedge.exe' -and
      $process.CommandLine -and $process.CommandLine.Contains($edgeProfile)
  }
  $owners[$processId]
}

function Test-Edge([IntPtr] $window) {
  $processId = 0
  [void][Desktop]::GetWindowThreadProcessId($window, [ref]$processId)
  (Get-Process -Id $processId -ErrorAction SilentlyContinue).ProcessName -eq 'msedge'
}

$edge = $null  # what the line says, once Edge has started
$deadline = $null
$last = $front  # the window in front, other than the reader
while (-not $deadline -or (Get-Date) -lt $deadline) {
  if (-not $edge -and $line.IsCompleted) {
    if ($null -eq $line.Result) { exit }  # end of input: no reading
    $edge = $line.Result | ConvertFrom-Json
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
  }
  $window = [Desktop]::GetForegroundWindow()
  # An Edge window before Edge's start is known waits: it may be the reader.
  if ($window -ne [IntPtr]::Zero -and $window -ne $last -and ($edge -or -not (Test-Edge $window))) {
    if (-not $edge -or -not (Test-Reader $window $edge.profile)) {
      $last = $window
    } else {
      $topmost = [IntPtr](-1)  # HWND_TOPMOST
      $flags = 0x11  # SWP_NOSIZE | SWP_NOACTIVATE
      if ($null -eq $edge.x) { $flags = $flags -bor 0x2 }  # SWP_NOMOVE
      [void][Desktop]::SetWindowPos($window, $topmost, [int]$edge.x, [int]$edge.y, 0, 0, $flags)
      # Windows lets a process give the focus away only while attached to the
      # input of the one that has it.
      $processId = 0
      $thread = [Desktop]::GetWindowThreadProcessId($window, [ref]$processId)
      $me = [Desktop]::GetCurrentThreadId()
      [void][Desktop]::AttachThreadInput($me, $thread, $true)
      [void][Desktop]::SetForegroundWindow($last)
      [void][Desktop]::AttachThreadInput($me, $thread, $false)
      exit
    }
  }
  Start-Sleep -Milliseconds 50
}
