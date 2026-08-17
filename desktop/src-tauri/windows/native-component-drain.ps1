param(
    [ValidateSet("Drain", "NormalizePayload")]
    [string] $Mode = "Drain"
)

$ErrorActionPreference = "Stop"
$failureCode = "D11"
$stageExitCodes = @{
    D10 = 10
    D11 = 11
    D12 = 12
    D13 = 13
    D14 = 14
    D15 = 15
    D16 = 16
    D17 = 17
}

function Stop-Drain([string] $code) {
    $exitCode = $stageExitCodes[$code]
    if ($null -eq $exitCode) {
        $code = "D10"
        $exitCode = $stageExitCodes[$code]
    }
    try {
        [Console]::Out.Write($code)
    }
    catch {
        # The installer still receives the non-zero exit if stdout is unavailable.
    }
    # NSIS classifies the numeric process result. Stdout is optional supporting
    # evidence only because some external hosts do not expose Console.Out to
    # nsExec even though the process exit code remains intact.
    exit $exitCode
}

trap {
    Stop-Drain $failureCode
}

$root = [Environment]::GetEnvironmentVariable(
    "AIGUARD_INTERNAL_INSTALL_ROOT",
    "Process"
)
if ([string]::IsNullOrEmpty($root)) {
    Stop-Drain "D11"
}
$driveAbsolute = $root -match '^[A-Za-z]:[\\/]'
$uncAbsolute = $root -match '^\\\\[^\\]+\\[^\\]+(?:\\|$)'
if (-not $driveAbsolute -and -not $uncAbsolute) {
    Stop-Drain "D11"
}

$names = @(
    "desktop.exe",
    "aiguard-chrome-native-host.exe",
    "aiguard-native-broker.exe",
    "aiguard.exe",
    "aiguard-native-host-manager.exe"
)
$payloadNames = @($names + "native-components-v1.json" + "uninstall.exe")
$processFilter = @(
    "Name = 'desktop.exe'"
    "Name = 'aiguard-chrome-native-host.exe'"
    "Name = 'aiguard-native-broker.exe'"
    "Name = 'aiguard.exe'"
    "Name = 'aiguard-native-host-manager.exe'"
) -join " OR "
$originals = @($names | ForEach-Object { [IO.Path]::Combine($root, $_) })
$quarantines = @($originals | ForEach-Object { "$_.aiguard-slice6-quarantine" })

$failureCode = "D12"
if (-not ("AiGuardPackageFileIdentity" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using Microsoft.Win32.SafeHandles;

public static class AiGuardPackageFileIdentity
{
    private const uint TokenQuery = 0x0008U;
    private const int TokenUser = 1;
    private const int TokenOwner = 4;
    private const int SeFileObject = 1;
    private const uint OwnerSecurityInformation = 0x00000001U;
    private const uint GenericRead = 0x80000000U;
    private const uint ReadControl = 0x00020000U;
    private const uint WriteOwner = 0x00080000U;
    private const uint FileShareRead = 0x00000001U;
    private const uint OpenExisting = 3U;
    private const uint FileAttributeNormal = 0x00000080U;
    private const uint FileFlagOpenReparsePoint = 0x00200000U;

    [StructLayout(LayoutKind.Sequential)]
    private struct ByHandleFileInformation
    {
        public uint FileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(
        SafeFileHandle handle,
        out ByHandleFileInformation information
    );

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(
        string path,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile
    );

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetCurrentProcess();

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);

    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr memory);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool OpenProcessToken(
        IntPtr process,
        uint desiredAccess,
        out IntPtr token
    );

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool GetTokenInformation(
        IntPtr token,
        int informationClass,
        IntPtr information,
        uint informationLength,
        out uint returnLength
    );

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern uint GetSecurityInfo(
        SafeFileHandle handle,
        int objectType,
        uint securityInformation,
        out IntPtr owner,
        out IntPtr group,
        out IntPtr dacl,
        out IntPtr sacl,
        out IntPtr securityDescriptor
    );

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern uint SetSecurityInfo(
        SafeFileHandle handle,
        int objectType,
        uint securityInformation,
        IntPtr owner,
        IntPtr group,
        IntPtr dacl,
        IntPtr sacl
    );

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EqualSid(IntPtr left, IntPtr right);

    private sealed class HeldFile : IDisposable
    {
        public readonly SafeFileHandle Handle;
        public readonly ByHandleFileInformation Identity;

        public HeldFile(SafeFileHandle handle, ByHandleFileInformation identity)
        {
            Handle = handle;
            Identity = identity;
        }

        public void Dispose()
        {
            Handle.Dispose();
        }
    }

    private static bool IsSingleNonemptyRegularFile(ByHandleFileInformation information)
    {
        return (information.FileAttributes & 0x410U) == 0
            && information.NumberOfLinks == 1
            && (information.FileSizeHigh != 0 || information.FileSizeLow != 0);
    }

    private static bool SameIdentity(
        ByHandleFileInformation left,
        ByHandleFileInformation right
    )
    {
        return left.VolumeSerialNumber == right.VolumeSerialNumber
            && left.FileIndexHigh == right.FileIndexHigh
            && left.FileIndexLow == right.FileIndexLow
            && left.FileSizeHigh == right.FileSizeHigh
            && left.FileSizeLow == right.FileSizeLow
            && left.NumberOfLinks == right.NumberOfLinks
            && left.FileAttributes == right.FileAttributes;
    }

    private static bool GetTokenSid(
        IntPtr token,
        int informationClass,
        out IntPtr buffer,
        out IntPtr sid
    )
    {
        buffer = IntPtr.Zero;
        sid = IntPtr.Zero;
        uint required;
        GetTokenInformation(token, informationClass, IntPtr.Zero, 0, out required);
        if (required < IntPtr.Size)
        {
            return false;
        }
        buffer = Marshal.AllocHGlobal((int)required);
        if (!GetTokenInformation(token, informationClass, buffer, required, out required))
        {
            Marshal.FreeHGlobal(buffer);
            buffer = IntPtr.Zero;
            return false;
        }
        sid = Marshal.ReadIntPtr(buffer);
        return sid != IntPtr.Zero;
    }

    private static bool OwnerMatches(SafeFileHandle handle, IntPtr expectedOwner)
    {
        IntPtr owner;
        IntPtr group;
        IntPtr dacl;
        IntPtr sacl;
        IntPtr descriptor;
        var status = GetSecurityInfo(
            handle,
            SeFileObject,
            OwnerSecurityInformation,
            out owner,
            out group,
            out dacl,
            out sacl,
            out descriptor
        );
        if (status != 0 || owner == IntPtr.Zero || descriptor == IntPtr.Zero)
        {
            if (descriptor != IntPtr.Zero)
            {
                LocalFree(descriptor);
            }
            return false;
        }
        var matches = EqualSid(owner, expectedOwner);
        LocalFree(descriptor);
        return matches;
    }

    public static bool IsSingleRegularFile(string path)
    {
        using (var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read
        ))
        {
            ByHandleFileInformation information;
            return GetFileInformationByHandle(stream.SafeFileHandle, out information)
                && (information.FileAttributes & 0x410U) == 0
                && information.NumberOfLinks == 1;
        }
    }

    public static bool BytesEqual(byte[] left, byte[] right)
    {
        if (left == null || right == null || left.Length != right.Length)
        {
            return false;
        }
        for (var index = 0; index < left.Length; index++)
        {
            if (left[index] != right[index])
            {
                return false;
            }
        }
        return true;
    }

    public static bool IsOwnedByCurrentUser(string path)
    {
        var security = File.GetAccessControl(path, AccessControlSections.Owner);
        var owner = security.GetOwner(typeof(SecurityIdentifier)) as SecurityIdentifier;
        using (var current = WindowsIdentity.GetCurrent())
        {
            return owner != null && owner.Equals(current.User);
        }
    }

    public static bool SetOwnerToCurrentUser(string path)
    {
        return NormalizePayloadOwners(new string[] { path });
    }

    public static bool NormalizePayloadOwners(string[] paths)
    {
        if (paths == null || paths.Length == 0)
        {
            return false;
        }
        IntPtr token;
        if (!OpenProcessToken(GetCurrentProcess(), TokenQuery, out token))
        {
            return false;
        }
        IntPtr userBuffer = IntPtr.Zero;
        IntPtr ownerBuffer = IntPtr.Zero;
        IntPtr userSid = IntPtr.Zero;
        IntPtr tokenOwnerSid = IntPtr.Zero;
        var files = new List<HeldFile>();
        try
        {
            if (!GetTokenSid(token, TokenUser, out userBuffer, out userSid)
                || !GetTokenSid(token, TokenOwner, out ownerBuffer, out tokenOwnerSid))
            {
                return false;
            }
            var unique = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var path in paths)
            {
                if (String.IsNullOrEmpty(path) || !Path.IsPathRooted(path) || !unique.Add(path))
                {
                    return false;
                }
                var handle = CreateFile(
                    path,
                    GenericRead | ReadControl | WriteOwner,
                    FileShareRead,
                    IntPtr.Zero,
                    OpenExisting,
                    FileAttributeNormal | FileFlagOpenReparsePoint,
                    IntPtr.Zero
                );
                if (handle.IsInvalid)
                {
                    handle.Dispose();
                    return false;
                }
                ByHandleFileInformation identity;
                if (!GetFileInformationByHandle(handle, out identity)
                    || !IsSingleNonemptyRegularFile(identity))
                {
                    handle.Dispose();
                    return false;
                }
                var allowed = OwnerMatches(handle, userSid)
                    || OwnerMatches(handle, tokenOwnerSid);
                if (!allowed)
                {
                    handle.Dispose();
                    return false;
                }
                files.Add(new HeldFile(handle, identity));
            }
            foreach (var file in files)
            {
                if (SetSecurityInfo(
                    file.Handle,
                    SeFileObject,
                    OwnerSecurityInformation,
                    userSid,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    IntPtr.Zero
                ) != 0)
                {
                    return false;
                }
                ByHandleFileInformation identity;
                if (!GetFileInformationByHandle(file.Handle, out identity)
                    || !IsSingleNonemptyRegularFile(identity)
                    || !SameIdentity(file.Identity, identity)
                    || !OwnerMatches(file.Handle, userSid))
                {
                    return false;
                }
            }
            return true;
        }
        finally
        {
            foreach (var file in files)
            {
                file.Dispose();
            }
            if (ownerBuffer != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(ownerBuffer);
            }
            if (userBuffer != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(userBuffer);
            }
            CloseHandle(token);
        }
    }
}
'@
}

$failureCode = "D13"
function Assert-ControlFile([string] $path, [byte[]] $expected, [bool] $requireOwner) {
    $item = Get-Item -LiteralPath $path -Force
    if (
        $item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        $item.Length -ne $expected.Length -or
        -not [AiGuardPackageFileIdentity]::IsSingleRegularFile($path)
    ) {
        throw "invalid package control file"
    }
    if ($requireOwner -and -not [AiGuardPackageFileIdentity]::IsOwnedByCurrentUser($path)) {
        throw "invalid package control owner"
    }
    $observed = [IO.File]::ReadAllBytes($path)
    if (-not [AiGuardPackageFileIdentity]::BytesEqual($observed, $expected)) {
        throw "invalid package control bytes"
    }
}

$marker = [IO.Path]::Combine($root, ".aiguard-component-maintenance-v1")
$receipt = [IO.Path]::Combine($root, ".aiguard-component-transaction-v1")
$markerBytes = [Text.Encoding]::ASCII.GetBytes("AIGUARD_COMPONENT_MAINTENANCE_V1`n")
try {
    $rootItem = Get-Item -LiteralPath $root -Force
    if (-not $rootItem.PSIsContainer -or ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "invalid package root"
    }
    if (Test-Path -LiteralPath $marker) {
        if (-not (Test-Path -LiteralPath $receipt)) {
            Assert-ControlFile $marker $markerBytes $false
            if (
                -not [AiGuardPackageFileIdentity]::IsOwnedByCurrentUser($marker) -and
                -not [AiGuardPackageFileIdentity]::SetOwnerToCurrentUser($marker)
            ) {
                throw "invalid package control owner"
            }
        }
        Assert-ControlFile $marker $markerBytes $true
    }
    if (Test-Path -LiteralPath $receipt) {
        $receiptBytes = [IO.File]::ReadAllBytes($receipt)
        if (
            $receiptBytes.Length -ne 65 -or
            [Text.Encoding]::ASCII.GetString($receiptBytes) -cnotmatch '\A[0-9a-f]{64}\n\z'
        ) {
            throw "invalid package receipt"
        }
        Assert-ControlFile $receipt $receiptBytes $true
    }
    if ($Mode -eq "NormalizePayload") {
        $failureCode = "D17"
        if (-not (Test-Path -LiteralPath $marker)) {
            throw "invalid package control file"
        }
        $payloads = @($payloadNames | ForEach-Object { [IO.Path]::Combine($root, $_) })
        if (-not [AiGuardPackageFileIdentity]::NormalizePayloadOwners($payloads)) {
            throw "invalid package payload"
        }
    }
}
catch {
    Stop-Drain $failureCode
}

if ($Mode -eq "NormalizePayload") {
    exit 0
}

$failureCode = "D14"
for ($index = 0; $index -lt $originals.Count; $index++) {
    if (
        (Test-Path -LiteralPath $originals[$index]) -and
        (Test-Path -LiteralPath $quarantines[$index])
    ) {
        Stop-Drain "D14"
    }
    if (Test-Path -LiteralPath $quarantines[$index]) {
        $item = Get-Item -LiteralPath $quarantines[$index] -Force
        if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            Stop-Drain "D14"
        }
    }
}

function Get-NormalizedProcessPath([string] $path) {
    if ($path.StartsWith('\\?\UNC\', [StringComparison]::OrdinalIgnoreCase)) {
        return '\\' + $path.Substring(8)
    }
    if ($path.StartsWith('\\?\', [StringComparison]::Ordinal)) {
        return $path.Substring(4)
    }
    return $path
}

$failureCode = "D15"
$deadline = [Diagnostics.Stopwatch]::StartNew()
try {
    $isolated = $false
    while ($deadline.Elapsed.TotalSeconds -lt 30) {
        $isolated = $true
        for ($index = 0; $index -lt $originals.Count; $index++) {
            if (Test-Path -LiteralPath $originals[$index]) {
                try {
                    [IO.File]::Move($originals[$index], $quarantines[$index])
                }
                catch {
                    $isolated = $false
                }
            }
        }
        if (-not $isolated) {
            $targets = @($originals + $quarantines)
            $live = @(
                Get-CimInstance Win32_Process -Filter $processFilter -OperationTimeoutSec 2 -ErrorAction Stop |
                    Where-Object {
                        $_.ExecutablePath -and
                        $targets -contains (Get-NormalizedProcessPath $_.ExecutablePath)
                    }
            )
            foreach ($process in $live) {
                Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
            }
        }
        if ($isolated) {
            break
        }
        Start-Sleep -Milliseconds 100
    }
    if (-not $isolated) {
        throw "launcher isolation failed"
    }

    $targets = @($originals + $quarantines)
    $clearSamples = 0
    while ($deadline.Elapsed.TotalSeconds -lt 30) {
        $live = @(
            Get-CimInstance Win32_Process -Filter $processFilter -OperationTimeoutSec 2 -ErrorAction Stop |
                Where-Object {
                    $_.ExecutablePath -and
                    $targets -contains (Get-NormalizedProcessPath $_.ExecutablePath)
                }
        )
        if ($live.Count) {
            foreach ($process in $live) {
                Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
            }
            $clearSamples = 0
        }
        else {
            $clearSamples++
        }
        if ($clearSamples -ge 10) {
            break
        }
        Start-Sleep -Milliseconds 100
    }
    if ($clearSamples -lt 10) {
        throw "live component did not exit"
    }
    $failureCode = "D16"
    foreach ($path in $quarantines) {
        if (Test-Path -LiteralPath $path) {
            [IO.File]::Delete($path)
        }
    }
    if ($quarantines | Where-Object { Test-Path -LiteralPath $_ }) {
        throw "quarantine removal failed"
    }
    exit 0
}
catch {
    # Keep every completed quarantine in place. The package barrier and removed
    # browser discovery make this a fail-closed state that a retry can resume.
    Stop-Drain $failureCode
}
