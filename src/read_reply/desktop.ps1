# The reading window's place on the Windows desktop, and the focus handed back.
#
# 1. Prints, as one line of JSON, the terminal's window (the Windows Terminal
#    window last in front, else the window in front) and the top-left corner
#    of its monitor, in physical pixels, and that monitor's scale.
# 2. Waits for a line on stdin, sent once Edge has started; end of input ends
#    the script.
# 3. Waits for an Edge window to come to the front, the reading window, keeps
#    it above the others, so that the terminal does not cover it, and gives
#    the focus back to the window that had it before.
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
[void][Desktop]::DwmGetWindowAttribute($terminal, $frameBounds, [ref]$frame, 16)
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
      $topmost = [IntPtr](-1)  # HWND_TOPMOST
      $keepPlaceAndFocus = 0x13  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
      [void][Desktop]::SetWindowPos($window, $topmost, 0, 0, 0, 0, $keepPlaceAndFocus)
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
