<#
.SYNOPSIS
Prints the peak level of the default Windows audio output, four times a second.

.DESCRIPTION
Proves that a reading is actually heard, which the tests cannot: run it from
WSL while read-reply speaks, and the peaks rise above the silence (about
0.001) while Edge talks. See "Probar que suena" in the README.

.PARAMETER Seconds
How long to measure.
#>
param([double] $Seconds = 20)

$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
class MMDeviceEnumeratorCom {}

[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
  int EnumAudioEndpoints();
  [PreserveSig] int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice device);
}

[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
  [PreserveSig] int Activate(ref Guid iid, int context, IntPtr parameters,
    [MarshalAs(UnmanagedType.IUnknown)] out object instance);
}

[Guid("C02216F6-8C67-4B5B-9D00-D008E73E0064"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioMeterInformation {
  [PreserveSig] int GetPeakValue(out float peak);
}

public static class AudioMeter {
  static IAudioMeterInformation meter;

  public static float Peak() {
    if (meter == null) {
      var devices = (IMMDeviceEnumerator)(new MMDeviceEnumeratorCom());
      IMMDevice device;
      devices.GetDefaultAudioEndpoint(0 /* render */, 1 /* multimedia */, out device);
      var iid = typeof(IAudioMeterInformation).GUID;
      object instance;
      device.Activate(ref iid, 23 /* CLSCTX_ALL */, IntPtr.Zero, out instance);
      meter = (IAudioMeterInformation)instance;
    }
    float peak;
    meter.GetPeakValue(out peak);
    return peak;
  }
}
"@

$culture = [Globalization.CultureInfo]::InvariantCulture
$start = Get-Date
while (((Get-Date) - $start).TotalSeconds -lt $Seconds) {
  $elapsed = ((Get-Date) - $start).TotalSeconds
  [string]::Format($culture, '{0:F2} {1:F3}', $elapsed, [AudioMeter]::Peak())
  Start-Sleep -Milliseconds 250
}
