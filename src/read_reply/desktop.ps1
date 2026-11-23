# The reading window's place on the Windows desktop, and the focus handed back.
#
# 1. Prints, as one line of JSON, the work area of the monitor of the window in
#    front (the terminal where the key was pressed), in physical pixels, and
#    that monitor's scale.
# 2. Waits for a line on stdin, sent once Edge has started; end of input ends
#    the script.
# 3. Waits for an Edge window to come to the front, the reading window, and
#    gives the focus back to the window that had it before.
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
}
"@

# Per-monitor aware (v2): real pixels on every monitor.
[void][Desktop]::SetThreadDpiAwarenessContext([IntPtr](-4))

$front = [Desktop]::GetForegroundWindow()
$info = New-Object Desktop+MonitorInfo
$info.Size = [Runtime.InteropServices.Marshal]::SizeOf($info)
$nearest = 2  # MONITOR_DEFAULTTONEAREST
[void][Desktop]::GetMonitorInfo([Desktop]::MonitorFromWindow($front, $nearest), [ref]$info)
$dpi = [Desktop]::GetDpiForWindow($front)
[Console]::Out.WriteLine((@{
  left = $info.Work.Left; top = $info.Work.Top
  right = $info.Work.Right; bottom = $info.Work.Bottom
  scale = $(if ($dpi) { $dpi / 96.0 } else { 1.0 })
} | ConvertTo-Json -Compress))
[Console]::Out.Flush()

if ($null -eq [Console]::In.ReadLine()) { exit }

function Test-Edge([IntPtr] $window) {
  $processId = 0
  [void][Desktop]::GetWindowThreadProcessId($window, [ref]$processId)
  (Get-Process -Id $processId -ErrorAction SilentlyContinue).ProcessName -eq 'msedge'
}

# The window that had the focus last, should the person have moved since.
$last = $front
$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
  $window = [Desktop]::GetForegroundWindow()
  if ($window -ne [IntPtr]::Zero -and $window -ne $last) {
    if (Test-Edge $window) {
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
    $last = $window
  }
  Start-Sleep -Milliseconds 50
}
