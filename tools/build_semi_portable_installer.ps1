[CmdletBinding()]
param(
    [string]$ArchivePath = '',
    [string]$OutputDirectory = '',
    [long]$PartSize = 1000000000,
    [string]$InstallerSourceCommit = ''
)

$ErrorActionPreference = 'Stop'
$ExpectedArchiveBytes = 2313314546
$ExpectedArchiveSha256 = '353a7880a07ec7885e1f1fe0d902e75f8c67a67754129586ea827c5579c262c1'
$ReleaseTag = 'ga-2.0.0'
$AssetStem = 'EchoPosture-GA-2.0.0-semi-portable-win-x64.zip'
$SetupName = 'EchoPosture-GA-2.0.0-semi-portable-setup.exe'
$ManifestName = 'EchoPosture-GA-2.0.0-semi-portable-manifest.json'
$ChecksumsName = 'EchoPosture-GA-2.0.0-semi-portable-SHA256SUMS.txt'
$RepositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([string]::IsNullOrWhiteSpace($ArchivePath)) {
    $ArchivePath = Join-Path $RepositoryRoot 'dist\EchoPosture-GA-2.0.0-portable-win-x64.zip'
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $RepositoryRoot 'dist'
}
$ArchivePath = [IO.Path]::GetFullPath($ArchivePath)
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)

function Get-Sha256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha.ComputeHash($stream)
        return ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) {
    throw "Archive not found: $ArchivePath"
}
if ($PartSize -le 0 -or $PartSize -ge 2147483648) {
    throw 'PartSize must be greater than zero and below GitHub''s 2 GiB asset limit.'
}

$archiveItem = Get-Item -LiteralPath $ArchivePath
$archiveHash = Get-Sha256 $ArchivePath
if ($archiveItem.Length -ne $ExpectedArchiveBytes -or $archiveHash -ne $ExpectedArchiveSha256) {
    throw "The input archive is not the approved GA-2.0.0 semi-portable package. Got $($archiveItem.Length) bytes, SHA-256 $archiveHash."
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
if ([string]::IsNullOrWhiteSpace($InstallerSourceCommit)) {
    $InstallerSourceCommit = (& git -C $RepositoryRoot rev-parse HEAD).Trim()
}
$applicationSourceCommit = (& git -C $RepositoryRoot rev-list -n 1 $ReleaseTag).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($applicationSourceCommit)) {
    throw "Unable to resolve source tag $ReleaseTag."
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$uncompressedBytes = 0L
$zip = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
try {
    foreach ($entry in $zip.Entries) { $uncompressedBytes += $entry.Length }
} finally {
    $zip.Dispose()
}

$parts = @()
$input = [IO.File]::OpenRead($ArchivePath)
try {
    $buffer = New-Object byte[] (4MB)
    $index = 1
    while ($input.Position -lt $input.Length) {
        $partName = '{0}.{1:d3}' -f $AssetStem, $index
        $partPath = Join-Path $OutputDirectory $partName
        $remaining = [Math]::Min($PartSize, $input.Length - $input.Position)
        $output = [IO.File]::Open($partPath, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try {
            $written = 0L
            while ($written -lt $remaining) {
                $read = $input.Read($buffer, 0, [int][Math]::Min($buffer.Length, $remaining - $written))
                if ($read -le 0) { throw "Unexpected end of archive while writing $partName" }
                $output.Write($buffer, 0, $read)
                $written += $read
            }
        } finally {
            $output.Dispose()
        }
        $partHash = Get-Sha256 $partPath
        $parts += [ordered]@{
            index = $index
            fileName = $partName
            bytes = $remaining
            sha256 = $partHash
        }
        Write-Output "Prepared $partName ($remaining bytes, SHA-256 $partHash)"
        $index++
    }
} finally {
    $input.Dispose()
}

$manifest = [ordered]@{
    schemaVersion = 1
    productVersion = 'GA-2.0.0'
    releaseTag = $ReleaseTag
    applicationSourceCommit = $applicationSourceCommit
    installerSourceCommit = $InstallerSourceCommit
    officialBaseUrl = "https://github.com/NOVVLA/EchoPosture/releases/download/$ReleaseTag/"
    archive = [ordered]@{
        fileName = $AssetStem
        bytes = $archiveItem.Length
        uncompressedBytes = $uncompressedBytes
        sha256 = $archiveHash
    }
    parts = $parts
}

$manifestPath = Join-Path $OutputDirectory $ManifestName
$utf8NoBom = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 8), $utf8NoBom)

$framework = if ([Environment]::Is64BitOperatingSystem) { 'Framework64' } else { 'Framework' }
$csc = Join-Path $env:SystemRoot "Microsoft.NET\$framework\v4.0.30319\csc.exe"
if (-not (Test-Path -LiteralPath $csc)) {
    $csc = Join-Path $env:SystemRoot 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path -LiteralPath $csc)) { throw 'csc.exe was not found.' }

$setupPath = Join-Path $OutputDirectory $SetupName
$compilerArguments = @(
    '/nologo', '/target:winexe', '/optimize+', "/out:$setupPath",
    '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.Core.dll',
    '/reference:System.Web.Extensions.dll', '/reference:System.IO.Compression.dll',
    '/reference:System.IO.Compression.FileSystem.dll',
    "/resource:$manifestPath,EchoPostureInstaller.Manifest.json",
    (Join-Path $RepositoryRoot 'launcher\EchoPostureInstallerCore.cs'),
    (Join-Path $RepositoryRoot 'launcher\EchoPostureInstaller.cs')
)
& $csc @compilerArguments
if ($LASTEXITCODE -ne 0) { throw "Installer compilation failed with exit code $LASTEXITCODE." }

$checksumPaths = @($setupPath)
foreach ($part in $parts) { $checksumPaths += (Join-Path $OutputDirectory $part.fileName) }
$checksumPaths += $manifestPath
$checksumLines = foreach ($path in $checksumPaths) {
    $hash = Get-Sha256 $path
    "$hash  $([IO.Path]::GetFileName($path))"
}
$checksumsPath = Join-Path $OutputDirectory $ChecksumsName
[IO.File]::WriteAllLines($checksumsPath, $checksumLines, $utf8NoBom)

Write-Output "Installer: $setupPath"
Write-Output "Manifest:  $manifestPath"
Write-Output "Checksums: $checksumsPath"
$signatureStatus = 'Unavailable (Microsoft.PowerShell.Security could not be loaded)'
try {
    $signatureStatus = (Get-AuthenticodeSignature -LiteralPath $setupPath -ErrorAction Stop).Status.ToString()
} catch {
    # Signature reporting is diagnostic only. The release audit still publishes SHA-256 and records that the EXE is unsigned.
}
Write-Output "Installer signature: $signatureStatus"
