using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace EchoPostureInstaller
{
    internal enum InstallerLanguage { English, Chinese }
    internal enum WeightSource { Official, Mirror }
    internal enum WeightTier { Skip, Standard, Professional, All }

    internal sealed class InstallerPart
    {
        public int index { get; set; }
        public string fileName { get; set; }
        public long bytes { get; set; }
        public string sha256 { get; set; }
    }

    internal sealed class InstallerArchive
    {
        public string fileName { get; set; }
        public long bytes { get; set; }
        public long uncompressedBytes { get; set; }
        public string sha256 { get; set; }
    }

    internal sealed class InstallerManifest
    {
        public int schemaVersion { get; set; }
        public string productVersion { get; set; }
        public string releaseTag { get; set; }
        public string applicationSourceCommit { get; set; }
        public string installerSourceCommit { get; set; }
        public string officialBaseUrl { get; set; }
        public InstallerArchive archive { get; set; }
        public InstallerPart[] parts { get; set; }

        public static InstallerManifest Load(Stream stream)
        {
            using (var reader = new StreamReader(stream, Encoding.UTF8, true, 4096, false))
            {
                var manifest = new JavaScriptSerializer().Deserialize<InstallerManifest>(reader.ReadToEnd());
                Validate(manifest);
                return manifest;
            }
        }

        public static InstallerManifest LoadEmbedded(Assembly assembly)
        {
            Stream stream = assembly.GetManifestResourceStream("EchoPostureInstaller.Manifest.json");
            if (stream == null)
            {
                throw new InvalidOperationException("The trusted installer manifest is missing.");
            }
            using (stream)
            {
                return Load(stream);
            }
        }

        public static void Validate(InstallerManifest manifest)
        {
            if (manifest == null || manifest.schemaVersion != 1)
            {
                throw new InvalidDataException("Unsupported installer manifest.");
            }
            if (manifest.archive == null || manifest.parts == null || manifest.parts.Length == 0)
            {
                throw new InvalidDataException("The installer manifest is incomplete.");
            }
            if (string.IsNullOrWhiteSpace(manifest.officialBaseUrl)
                || !manifest.officialBaseUrl.StartsWith("https://github.com/NOVVLA/EchoPosture/releases/download/", StringComparison.Ordinal))
            {
                throw new InvalidDataException("The application package source is not the official EchoPosture release URL.");
            }
            long total = 0;
            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            for (int i = 0; i < manifest.parts.Length; i++)
            {
                InstallerPart part = manifest.parts[i];
                if (part == null || part.index != i + 1 || part.bytes <= 0 || !IsSha256(part.sha256)
                    || string.IsNullOrWhiteSpace(part.fileName) || Path.GetFileName(part.fileName) != part.fileName
                    || !names.Add(part.fileName))
                {
                    throw new InvalidDataException("Invalid application package part in the trusted manifest.");
                }
                total += part.bytes;
            }
            if (manifest.archive.bytes != total || manifest.archive.uncompressedBytes <= 0
                || !IsSha256(manifest.archive.sha256))
            {
                throw new InvalidDataException("The application archive metadata is inconsistent.");
            }
        }

        private static bool IsSha256(string value)
        {
            if (value == null || value.Length != 64) return false;
            for (int i = 0; i < value.Length; i++)
            {
                char c = char.ToLowerInvariant(value[i]);
                if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
            }
            return true;
        }
    }

    internal static class WeightScriptSelector
    {
        public static string GetScriptName(InstallerLanguage language, WeightSource source)
        {
            if (language == InstallerLanguage.Chinese)
            {
                return source == WeightSource.Mirror
                    ? "fetch_pose_models_mirror_zh.ps1"
                    : "fetch_pose_models_zh.ps1";
            }
            return source == WeightSource.Mirror
                ? "fetch_pose_models_mirror.ps1"
                : "fetch_pose_models.ps1";
        }

        public static string BuildArguments(string script, WeightTier tier, string destination, bool confirmed)
        {
            if (!confirmed) throw new InvalidOperationException("Model license consent is required.");
            if (tier == WeightTier.Skip) throw new InvalidOperationException("No model script is used for Compatibility mode.");
            string command =
                "function Get-FileHash { param([string]$LiteralPath, [string]$Algorithm) "
                + "$stream = [IO.File]::OpenRead($LiteralPath); $sha = [Security.Cryptography.SHA256]::Create(); "
                + "try { [pscustomobject]@{ Algorithm = 'SHA256'; Hash = ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant(); Path = $LiteralPath } } "
                + "finally { $sha.Dispose(); $stream.Dispose() } }; "
                + "& " + QuotePowerShellLiteral(script)
                + " -Tier " + QuotePowerShellLiteral(tier.ToString())
                + " -DestinationRoot " + QuotePowerShellLiteral(destination)
                + " -Yes; exit $LASTEXITCODE";
            return "-NoLogo -NoProfile -ExecutionPolicy Bypass -Command " + Quote(command);
        }

        private static string QuotePowerShellLiteral(string value)
        {
            return "'" + (value ?? string.Empty).Replace("'", "''") + "'";
        }

        public static string Quote(string value)
        {
            return "\"" + (value ?? string.Empty).Replace("\"", "\\\"") + "\"";
        }
    }

    internal static class FileHash
    {
        public static string Sha256(string path)
        {
            using (FileStream stream = File.OpenRead(path))
            using (SHA256 hash = SHA256.Create())
            {
                return ToHex(hash.ComputeHash(stream));
            }
        }

        public static string Sha256Segment(string path, long offset, long count)
        {
            using (FileStream stream = File.OpenRead(path))
            using (SHA256 hash = SHA256.Create())
            {
                stream.Position = offset;
                byte[] buffer = new byte[1024 * 1024];
                long remaining = count;
                while (remaining > 0)
                {
                    int read = stream.Read(buffer, 0, (int)Math.Min(buffer.Length, remaining));
                    if (read == 0) throw new EndOfStreamException();
                    hash.TransformBlock(buffer, 0, read, null, 0);
                    remaining -= read;
                }
                hash.TransformFinalBlock(new byte[0], 0, 0);
                return ToHex(hash.Hash);
            }
        }

        private static string ToHex(byte[] value)
        {
            var builder = new StringBuilder(value.Length * 2);
            foreach (byte item in value) builder.Append(item.ToString("x2", CultureInfo.InvariantCulture));
            return builder.ToString();
        }
    }

    internal sealed class TransferResponse : IDisposable
    {
        public Stream Stream { get; private set; }
        public bool IsPartial { get; private set; }
        private readonly IDisposable owner;

        public TransferResponse(Stream stream, bool isPartial, IDisposable owner)
        {
            Stream = stream;
            IsPartial = isPartial;
            this.owner = owner;
        }

        public void Dispose()
        {
            if (Stream != null) Stream.Dispose();
            if (owner != null) owner.Dispose();
        }
    }

    internal interface ITransferSource
    {
        TransferResponse Open(string uri, long offset);
    }

    internal sealed class HttpTransferSource : ITransferSource
    {
        public TransferResponse Open(string uri, long offset)
        {
            var request = (HttpWebRequest)WebRequest.Create(uri);
            request.UserAgent = "EchoPosture-GA-2.0.0-Installer";
            request.AllowAutoRedirect = true;
            request.MaximumAutomaticRedirections = 10;
            request.Timeout = 30000;
            request.ReadWriteTimeout = 30000;
            request.AutomaticDecompression = DecompressionMethods.None;
            if (offset > 0) request.AddRange(offset);
            var response = (HttpWebResponse)request.GetResponse();
            bool partial = response.StatusCode == HttpStatusCode.PartialContent;
            return new TransferResponse(response.GetResponseStream(), partial, response);
        }
    }

    internal sealed class InstallerProgress
    {
        public string Stage { get; set; }
        public string CurrentFile { get; set; }
        public long CompletedBytes { get; set; }
        public long TotalBytes { get; set; }
        public double BytesPerSecond { get; set; }
    }

    internal sealed class InstallerRunResult
    {
        public bool AlreadyInstalled { get; set; }
        public string InstallDirectory { get; set; }
        public string ArchivePath { get; set; }
    }

    internal sealed class InstallerCancelledException : OperationCanceledException { }

    internal sealed class InstallerEngine
    {
        private readonly InstallerManifest manifest;
        private readonly ITransferSource transfer;
        private readonly ManualResetEvent pauseGate = new ManualResetEvent(true);
        private volatile bool cancelled;
        private long downloadedAtStart;
        private readonly Stopwatch speedWatch = new Stopwatch();

        public event Action<string> Log;
        public event Action<InstallerProgress> Progress;

        public InstallerEngine(InstallerManifest manifest, ITransferSource transfer)
        {
            InstallerManifest.Validate(manifest);
            this.manifest = manifest;
            this.transfer = transfer;
        }

        public void Pause() { pauseGate.Reset(); }
        public void Resume() { pauseGate.Set(); }
        public void Cancel() { cancelled = true; pauseGate.Set(); }

        public InstallerRunResult InstallProgram(string cacheDirectory, string installDirectory)
        {
            installDirectory = Path.GetFullPath(installDirectory);
            cacheDirectory = Path.GetFullPath(cacheDirectory);
            if (IsMatchingInstallation(installDirectory))
            {
                WriteLog("A matching GA-2.0.0 installation already exists.");
                return new InstallerRunResult { AlreadyInstalled = true, InstallDirectory = installDirectory };
            }
            EnsureDestinationAvailable(installDirectory);
            Directory.CreateDirectory(cacheDirectory);
            CheckDiskSpace(cacheDirectory, installDirectory);
            downloadedAtStart = CountCachedBytes(cacheDirectory);
            speedWatch.Restart();

            foreach (InstallerPart part in manifest.parts)
            {
                DownloadPart(cacheDirectory, part);
            }
            string archivePath = Reassemble(cacheDirectory);
            ExtractAndCommit(archivePath, installDirectory);
            CleanupCache(cacheDirectory, archivePath);
            return new InstallerRunResult
            {
                AlreadyInstalled = false,
                InstallDirectory = installDirectory,
                ArchivePath = archivePath,
            };
        }

        private void DownloadPart(string cacheDirectory, InstallerPart part)
        {
            ThrowIfCancelled();
            string complete = Path.Combine(cacheDirectory, part.fileName);
            string partial = complete + ".partial";
            if (File.Exists(complete))
            {
                if (new FileInfo(complete).Length == part.bytes
                    && string.Equals(FileHash.Sha256(complete), part.sha256, StringComparison.OrdinalIgnoreCase))
                {
                    WriteLog("Verified cached part: " + part.fileName);
                    Report("download", part.fileName, CountCachedBytes(cacheDirectory));
                    return;
                }
                File.Delete(complete);
            }

            long offset = File.Exists(partial) ? new FileInfo(partial).Length : 0;
            if (offset > part.bytes)
            {
                File.Delete(partial);
                offset = 0;
            }
            string uri = manifest.officialBaseUrl.TrimEnd('/') + "/" + Uri.EscapeDataString(part.fileName);
            WriteLog((offset > 0 ? "Resuming " : "Downloading ") + part.fileName + " from the official EchoPosture release.");
            using (TransferResponse response = transfer.Open(uri, offset))
            {
                if (offset > 0 && !response.IsPartial)
                {
                    WriteLog("The server did not accept the range request; restarting the current part.");
                    offset = 0;
                }
                FileMode mode = offset > 0 && response.IsPartial ? FileMode.Append : FileMode.Create;
                using (var output = new FileStream(partial, mode, FileAccess.Write, FileShare.None))
                {
                    byte[] buffer = new byte[1024 * 1024];
                    int read;
                    while ((read = response.Stream.Read(buffer, 0, buffer.Length)) > 0)
                    {
                        pauseGate.WaitOne();
                        ThrowIfCancelled();
                        output.Write(buffer, 0, read);
                        offset += read;
                        Report("download", part.fileName, CountCachedBytes(cacheDirectory));
                        if (offset > part.bytes) throw new InvalidDataException("The downloaded part is larger than expected: " + part.fileName);
                    }
                }
            }
            if (new FileInfo(partial).Length != part.bytes)
            {
                throw new InvalidDataException("The downloaded part has an unexpected size: " + part.fileName);
            }
            string actual = FileHash.Sha256(partial);
            if (!string.Equals(actual, part.sha256, StringComparison.OrdinalIgnoreCase))
            {
                File.Delete(partial);
                throw new InvalidDataException("SHA-256 verification failed for " + part.fileName + ". The untrusted data was discarded.");
            }
            File.Move(partial, complete);
            WriteLog("Verified part: " + part.fileName);
        }

        private string Reassemble(string cacheDirectory)
        {
            ThrowIfCancelled();
            string outputPath = Path.Combine(cacheDirectory, manifest.archive.fileName);
            string temporary = outputPath + ".assembling";
            if (File.Exists(outputPath)
                && new FileInfo(outputPath).Length == manifest.archive.bytes
                && string.Equals(FileHash.Sha256(outputPath), manifest.archive.sha256, StringComparison.OrdinalIgnoreCase))
            {
                WriteLog("Verified cached complete application archive.");
                return outputPath;
            }
            if (File.Exists(temporary)) File.Delete(temporary);
            Report("verify", manifest.archive.fileName, manifest.archive.bytes);
            using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                byte[] buffer = new byte[4 * 1024 * 1024];
                foreach (InstallerPart part in manifest.parts)
                {
                    using (var input = File.OpenRead(Path.Combine(cacheDirectory, part.fileName)))
                    {
                        int read;
                        while ((read = input.Read(buffer, 0, buffer.Length)) > 0)
                        {
                            ThrowIfCancelled();
                            output.Write(buffer, 0, read);
                        }
                    }
                }
            }
            if (new FileInfo(temporary).Length != manifest.archive.bytes
                || !string.Equals(FileHash.Sha256(temporary), manifest.archive.sha256, StringComparison.OrdinalIgnoreCase))
            {
                File.Delete(temporary);
                throw new InvalidDataException("The reconstructed application archive failed verification.");
            }
            if (File.Exists(outputPath)) File.Delete(outputPath);
            File.Move(temporary, outputPath);
            WriteLog("The complete application archive passed SHA-256 verification.");
            return outputPath;
        }

        private void ExtractAndCommit(string archivePath, string installDirectory)
        {
            ThrowIfCancelled();
            Report("extract", Path.GetFileName(archivePath), manifest.archive.bytes);
            string parent = Path.GetDirectoryName(installDirectory);
            Directory.CreateDirectory(parent);
            string staging = Path.Combine(parent, ".EchoPosture-GA-2.0.0-installing-" + Guid.NewGuid().ToString("N"));
            try
            {
                Directory.CreateDirectory(staging);
                SafeArchiveExtractor.Extract(archivePath, staging, delegate { ThrowIfCancelled(); });
                string packageRoot = FindPackageRoot(staging);
                ValidatePackage(packageRoot);
                if (Directory.Exists(installDirectory)) Directory.Delete(installDirectory, false);
                Directory.Move(packageRoot, installDirectory);
                File.WriteAllText(
                    Path.Combine(installDirectory, ".echoposture-install.json"),
                    "{\"version\":\"GA-2.0.0\",\"archiveSha256\":\"" + manifest.archive.sha256.ToLowerInvariant()
                    + "\",\"installedUtc\":\"" + DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture) + "\"}",
                    new UTF8Encoding(false));
                WriteLog("EchoPosture was installed to " + installDirectory);
            }
            finally
            {
                if (Directory.Exists(staging))
                {
                    try { Directory.Delete(staging, true); } catch { }
                }
            }
        }

        private static string FindPackageRoot(string staging)
        {
            if (File.Exists(Path.Combine(staging, "EchoPosture.exe"))) return staging;
            string[] directories = Directory.GetDirectories(staging);
            foreach (string directory in directories)
            {
                if (File.Exists(Path.Combine(directory, "EchoPosture.exe"))) return directory;
            }
            throw new InvalidDataException("EchoPosture.exe was not found in the verified archive.");
        }

        private static void ValidatePackage(string root)
        {
            string[] required = {
                "EchoPosture.exe", "EchoPostureSelfTest.exe", "BlurOverlayHost.exe", "tray_app.py",
                Path.Combine("runtime", "python311", "python.exe"),
                Path.Combine("tools", "fetch_pose_models", "fetch_pose_models.ps1"),
                Path.Combine("tools", "fetch_pose_models", "fetch_pose_models_mirror.ps1"),
                Path.Combine("tools", "fetch_pose_models", "fetch_pose_models_zh.ps1"),
                Path.Combine("tools", "fetch_pose_models", "fetch_pose_models_mirror_zh.ps1"),
            };
            foreach (string item in required)
            {
                if (!File.Exists(Path.Combine(root, item)))
                    throw new InvalidDataException("Required package file is missing: " + item);
            }
        }

        private bool IsMatchingInstallation(string installDirectory)
        {
            string marker = Path.Combine(installDirectory, ".echoposture-install.json");
            if (!File.Exists(marker) || !File.Exists(Path.Combine(installDirectory, "EchoPosture.exe"))) return false;
            try
            {
                string content = File.ReadAllText(marker);
                return content.IndexOf(manifest.archive.sha256, StringComparison.OrdinalIgnoreCase) >= 0;
            }
            catch { return false; }
        }

        private static void EnsureDestinationAvailable(string installDirectory)
        {
            if (!Directory.Exists(installDirectory)) return;
            if (Directory.GetFileSystemEntries(installDirectory).Length != 0)
                throw new IOException("The selected installation directory is not empty and is not a matching EchoPosture installation.");
        }

        private void CheckDiskSpace(string cacheDirectory, string installDirectory)
        {
            long cached = CountCachedBytes(cacheDirectory);
            long cacheRequired = Math.Max(0, manifest.archive.bytes - cached) + manifest.archive.bytes + 512L * 1024 * 1024;
            long installRequired = manifest.archive.uncompressedBytes + 512L * 1024 * 1024;
            string cacheRoot = Path.GetPathRoot(cacheDirectory);
            string installRoot = Path.GetPathRoot(installDirectory);
            if (string.Equals(cacheRoot, installRoot, StringComparison.OrdinalIgnoreCase))
            {
                EnsureFreeSpace(cacheRoot, cacheRequired + installRequired);
            }
            else
            {
                EnsureFreeSpace(cacheRoot, cacheRequired);
                EnsureFreeSpace(installRoot, installRequired);
            }
        }

        private static void EnsureFreeSpace(string root, long required)
        {
            var drive = new DriveInfo(root);
            if (drive.AvailableFreeSpace < required)
                throw new IOException("Insufficient free space on " + root + ". Required: " + required + " bytes.");
        }

        private long CountCachedBytes(string cacheDirectory)
        {
            long total = 0;
            foreach (InstallerPart part in manifest.parts)
            {
                string complete = Path.Combine(cacheDirectory, part.fileName);
                string partial = complete + ".partial";
                if (File.Exists(complete)) total += Math.Min(part.bytes, new FileInfo(complete).Length);
                else if (File.Exists(partial)) total += Math.Min(part.bytes, new FileInfo(partial).Length);
            }
            return total;
        }

        private void CleanupCache(string cacheDirectory, string archivePath)
        {
            foreach (InstallerPart part in manifest.parts)
            {
                TryDelete(Path.Combine(cacheDirectory, part.fileName));
                TryDelete(Path.Combine(cacheDirectory, part.fileName) + ".partial");
            }
            TryDelete(archivePath);
        }

        private static void TryDelete(string path)
        {
            try { if (File.Exists(path)) File.Delete(path); } catch { }
        }

        private void Report(string stage, string current, long completed)
        {
            Action<InstallerProgress> handler = Progress;
            if (handler == null) return;
            double speed = speedWatch.Elapsed.TotalSeconds > 0
                ? Math.Max(0, completed - downloadedAtStart) / speedWatch.Elapsed.TotalSeconds : 0;
            handler(new InstallerProgress
            {
                Stage = stage,
                CurrentFile = current,
                CompletedBytes = Math.Min(completed, manifest.archive.bytes),
                TotalBytes = manifest.archive.bytes,
                BytesPerSecond = speed,
            });
        }

        private void WriteLog(string message)
        {
            Action<string> handler = Log;
            if (handler != null) handler(message);
        }

        private void ThrowIfCancelled()
        {
            if (cancelled) throw new InstallerCancelledException();
        }
    }

    internal static class SafeArchiveExtractor
    {
        public static void Extract(string archivePath, string destination, Action checkpoint)
        {
            string root = Path.GetFullPath(destination).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            using (ZipArchive archive = ZipFile.OpenRead(archivePath))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    if (checkpoint != null) checkpoint();
                    string relative = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                    string target = Path.GetFullPath(Path.Combine(destination, relative));
                    if (!target.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                        throw new InvalidDataException("The archive contains an unsafe path: " + entry.FullName);
                    if (string.IsNullOrEmpty(entry.Name))
                    {
                        Directory.CreateDirectory(target);
                        continue;
                    }
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    using (Stream input = entry.Open())
                    using (var output = new FileStream(target, FileMode.Create, FileAccess.Write, FileShare.None))
                    {
                        input.CopyTo(output);
                    }
                }
            }
        }
    }

    internal sealed class WeightRunner
    {
        private volatile bool cancelled;
        private Process process;
        public event Action<string> Output;

        public void Cancel()
        {
            cancelled = true;
            try { if (process != null && !process.HasExited) process.Kill(); } catch { }
        }

        public int Run(string installDirectory, InstallerLanguage language, WeightSource source, WeightTier tier, bool confirmed)
        {
            string script = Path.Combine(installDirectory, "tools", "fetch_pose_models", WeightScriptSelector.GetScriptName(language, source));
            if (!File.Exists(script)) throw new FileNotFoundException("The selected model download script is missing.", script);
            string destination = Path.Combine(installDirectory, "models", "pose");
            string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
            if (!File.Exists(powershell)) powershell = "powershell.exe";
            var start = new ProcessStartInfo
            {
                FileName = powershell,
                Arguments = WeightScriptSelector.BuildArguments(script, tier, destination, confirmed),
                WorkingDirectory = installDirectory,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            process = new Process { StartInfo = start, EnableRaisingEvents = true };
            process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs args) { Emit(args.Data); };
            process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs args) { Emit(args.Data); };
            process.Start();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            while (!process.WaitForExit(250))
            {
                if (cancelled)
                {
                    try { process.Kill(); } catch { }
                    throw new InstallerCancelledException();
                }
            }
            process.WaitForExit();
            return process.ExitCode;
        }

        private void Emit(string line)
        {
            if (line == null) return;
            Action<string> handler = Output;
            if (handler != null) handler(line);
        }
    }
}
