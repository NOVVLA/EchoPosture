using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Text;

namespace EchoPostureInstaller
{
    internal sealed class MemoryTransferSource : ITransferSource
    {
        public readonly Dictionary<string, byte[]> Files = new Dictionary<string, byte[]>();
        public readonly List<long> RequestedOffsets = new List<long>();
        public bool Corrupt;

        public TransferResponse Open(string uri, long offset)
        {
            RequestedOffsets.Add(offset);
            byte[] source = Files[uri];
            byte[] result = new byte[source.Length - offset];
            Buffer.BlockCopy(source, (int)offset, result, 0, result.Length);
            if (Corrupt && result.Length > 0) result[0] ^= 0x7f;
            return new TransferResponse(new MemoryStream(result, false), offset > 0, null);
        }
    }

    internal static class InstallerTests
    {
        private static int passed;

        private static void Main()
        {
            Run("weight script matrix", TestWeightScriptMatrix);
            Run("weight consent and arguments", TestWeightArguments);
            Run("manifest validation", TestManifestValidation);
            Run("resume, verify, extract, and existing install", TestInstallEndToEnd);
            Run("corrupt part rejection", TestCorruptPartRejected);
            Run("unsafe archive path rejection", TestUnsafeArchiveRejected);
            Run("non-empty target rejection", TestNonEmptyTargetRejected);
            Console.WriteLine("ALL INSTALLER TESTS PASSED (" + passed + ")");
        }

        private static void Run(string name, Action test)
        {
            try
            {
                test();
            }
            catch (Exception ex)
            {
                Console.WriteLine("[FAIL] " + name + " " + ex.GetType().FullName + ": " + ex.Message);
                throw;
            }
            passed++;
            Console.WriteLine("[PASS] " + name);
        }

        private static void TestWeightScriptMatrix()
        {
            Equal("fetch_pose_models.ps1", WeightScriptSelector.GetScriptName(InstallerLanguage.English, WeightSource.Official));
            Equal("fetch_pose_models_mirror.ps1", WeightScriptSelector.GetScriptName(InstallerLanguage.English, WeightSource.Mirror));
            Equal("fetch_pose_models_zh.ps1", WeightScriptSelector.GetScriptName(InstallerLanguage.Chinese, WeightSource.Official));
            Equal("fetch_pose_models_mirror_zh.ps1", WeightScriptSelector.GetScriptName(InstallerLanguage.Chinese, WeightSource.Mirror));
        }

        private static void TestWeightArguments()
        {
            string arguments = WeightScriptSelector.BuildArguments("C:\\app\\fetch.ps1", WeightTier.All, "C:\\app\\models\\pose", true);
            Contains(arguments, "-Tier 'All'");
            Contains(arguments, "-DestinationRoot 'C:\\app\\models\\pose'");
            Contains(arguments, "-Yes");
            Contains(arguments, "function Get-FileHash");
            Throws<InvalidOperationException>(delegate { WeightScriptSelector.BuildArguments("x", WeightTier.Standard, "y", false); });
            Throws<InvalidOperationException>(delegate { WeightScriptSelector.BuildArguments("x", WeightTier.Skip, "y", true); });
        }

        private static void TestManifestValidation()
        {
            InstallerManifest valid = MakeManifest(new byte[] { 1, 2 }, new byte[] { 3, 4 }, 1);
            InstallerManifest.Validate(valid);
            valid.officialBaseUrl = "https://ghfast.top/https://github.com/NOVVLA/EchoPosture/releases/download/ga-2.0.0/";
            Throws<InvalidDataException>(delegate { InstallerManifest.Validate(valid); });
        }

        private static void TestInstallEndToEnd()
        {
            string root = TempRoot();
            try
            {
                byte[] archive = BuildValidPackageZip();
                byte[] first = Slice(archive, 0, archive.Length / 2);
                byte[] second = Slice(archive, first.Length, archive.Length - first.Length);
                InstallerManifest manifest = MakeManifest(first, second, GetUncompressedBytes(archive));
                var source = new MemoryTransferSource();
                PopulateSource(source, manifest, first, second);
                string cache = Path.Combine(root, "cache");
                string install = Path.Combine(root, "install");
                Directory.CreateDirectory(cache);
                File.WriteAllBytes(Path.Combine(cache, manifest.parts[0].fileName) + ".partial", Slice(first, 0, 5));
                var engine = new InstallerEngine(manifest, source);
                InstallerRunResult result = engine.InstallProgram(cache, install);
                True(!result.AlreadyInstalled, "Fresh install was reported as existing.");
                True(File.Exists(Path.Combine(install, "EchoPosture.exe")), "Launcher was not installed.");
                True(File.Exists(Path.Combine(install, ".echoposture-install.json")), "Install marker was not written.");
                True(source.RequestedOffsets.Contains(5), "The partial part was not resumed.");
                InstallerRunResult secondRun = new InstallerEngine(manifest, source).InstallProgram(cache, install);
                True(secondRun.AlreadyInstalled, "Matching installation was not detected.");
            }
            finally { DeleteTree(root); }
        }

        private static void TestCorruptPartRejected()
        {
            string root = TempRoot();
            try
            {
                byte[] archive = BuildValidPackageZip();
                byte[] first = Slice(archive, 0, archive.Length / 2);
                byte[] second = Slice(archive, first.Length, archive.Length - first.Length);
                InstallerManifest manifest = MakeManifest(first, second, GetUncompressedBytes(archive));
                var source = new MemoryTransferSource { Corrupt = true };
                PopulateSource(source, manifest, first, second);
                Throws<InvalidDataException>(delegate
                {
                    new InstallerEngine(manifest, source).InstallProgram(Path.Combine(root, "cache"), Path.Combine(root, "install"));
                });
                True(!File.Exists(Path.Combine(root, "cache", manifest.parts[0].fileName) + ".partial"), "Untrusted partial data was retained.");
            }
            finally { DeleteTree(root); }
        }

        private static void TestUnsafeArchiveRejected()
        {
            string root = TempRoot();
            try
            {
                string zip = Path.Combine(root, "unsafe.zip");
                using (var archive = ZipFile.Open(zip, ZipArchiveMode.Create))
                {
                    ZipArchiveEntry entry = archive.CreateEntry("../outside.txt");
                    using (var writer = new StreamWriter(entry.Open())) writer.Write("unsafe");
                }
                Throws<InvalidDataException>(delegate { SafeArchiveExtractor.Extract(zip, Path.Combine(root, "out"), null); });
                True(!File.Exists(Path.Combine(root, "outside.txt")), "Unsafe archive escaped the destination.");
            }
            finally { DeleteTree(root); }
        }

        private static void TestNonEmptyTargetRejected()
        {
            string root = TempRoot();
            try
            {
                byte[] archive = BuildValidPackageZip();
                byte[] first = Slice(archive, 0, archive.Length / 2);
                byte[] second = Slice(archive, first.Length, archive.Length - first.Length);
                InstallerManifest manifest = MakeManifest(first, second, GetUncompressedBytes(archive));
                var source = new MemoryTransferSource();
                PopulateSource(source, manifest, first, second);
                string install = Path.Combine(root, "install");
                Directory.CreateDirectory(install);
                File.WriteAllText(Path.Combine(install, "user-file.txt"), "keep");
                Throws<IOException>(delegate { new InstallerEngine(manifest, source).InstallProgram(Path.Combine(root, "cache"), install); });
                True(File.Exists(Path.Combine(install, "user-file.txt")), "Existing user file was changed.");
            }
            finally { DeleteTree(root); }
        }

        private static InstallerManifest MakeManifest(byte[] first, byte[] second, long uncompressed)
        {
            byte[] all = new byte[first.Length + second.Length];
            Buffer.BlockCopy(first, 0, all, 0, first.Length);
            Buffer.BlockCopy(second, 0, all, first.Length, second.Length);
            string root = TempRoot();
            try
            {
                string a = Path.Combine(root, "a");
                string b = Path.Combine(root, "b");
                string whole = Path.Combine(root, "whole");
                File.WriteAllBytes(a, first);
                File.WriteAllBytes(b, second);
                File.WriteAllBytes(whole, all);
                return new InstallerManifest
                {
                    schemaVersion = 1,
                    productVersion = "GA-2.0.0",
                    releaseTag = "ga-2.0.0",
                    officialBaseUrl = "https://github.com/NOVVLA/EchoPosture/releases/download/ga-2.0.0/",
                    archive = new InstallerArchive { fileName = "fixture.zip", bytes = all.Length, uncompressedBytes = uncompressed, sha256 = FileHash.Sha256(whole) },
                    parts = new[]
                    {
                        new InstallerPart { index = 1, fileName = "fixture.zip.001", bytes = first.Length, sha256 = FileHash.Sha256(a) },
                        new InstallerPart { index = 2, fileName = "fixture.zip.002", bytes = second.Length, sha256 = FileHash.Sha256(b) },
                    },
                };
            }
            finally { DeleteTree(root); }
        }

        private static void PopulateSource(MemoryTransferSource source, InstallerManifest manifest, byte[] first, byte[] second)
        {
            source.Files[manifest.officialBaseUrl + manifest.parts[0].fileName] = first;
            source.Files[manifest.officialBaseUrl + manifest.parts[1].fileName] = second;
        }

        private static byte[] BuildValidPackageZip()
        {
            string root = TempRoot();
            string path = Path.Combine(root, "fixture.zip");
            try
            {
                using (var archive = ZipFile.Open(path, ZipArchiveMode.Create))
                {
                    string[] required = {
                        "EchoPosture/EchoPosture.exe", "EchoPosture/EchoPostureSelfTest.exe", "EchoPosture/BlurOverlayHost.exe",
                        "EchoPosture/tray_app.py", "EchoPosture/runtime/python311/python.exe",
                        "EchoPosture/tools/fetch_pose_models/fetch_pose_models.ps1",
                        "EchoPosture/tools/fetch_pose_models/fetch_pose_models_mirror.ps1",
                        "EchoPosture/tools/fetch_pose_models/fetch_pose_models_zh.ps1",
                        "EchoPosture/tools/fetch_pose_models/fetch_pose_models_mirror_zh.ps1",
                    };
                    foreach (string item in required)
                    {
                        ZipArchiveEntry entry = archive.CreateEntry(item, CompressionLevel.NoCompression);
                        using (Stream stream = entry.Open())
                        {
                            byte[] data = Encoding.UTF8.GetBytes(item);
                            stream.Write(data, 0, data.Length);
                        }
                    }
                }
                return File.ReadAllBytes(path);
            }
            finally { DeleteTree(root); }
        }

        private static long GetUncompressedBytes(byte[] archiveBytes)
        {
            using (var memory = new MemoryStream(archiveBytes, false))
            using (var archive = new ZipArchive(memory, ZipArchiveMode.Read))
            {
                long total = 0;
                foreach (ZipArchiveEntry entry in archive.Entries) total += entry.Length;
                return total;
            }
        }

        private static byte[] Slice(byte[] source, int offset, int count)
        {
            byte[] result = new byte[count];
            Buffer.BlockCopy(source, offset, result, 0, count);
            return result;
        }

        private static string TempRoot()
        {
            string path = Path.Combine(Path.GetTempPath(), "EchoPostureInstallerTests-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(path);
            return path;
        }

        private static void DeleteTree(string path)
        {
            try { if (Directory.Exists(path)) Directory.Delete(path, true); } catch { }
        }

        private static void Equal(string expected, string actual)
        {
            if (!string.Equals(expected, actual, StringComparison.Ordinal)) throw new Exception("Expected '" + expected + "', got '" + actual + "'.");
        }

        private static void Contains(string value, string expected)
        {
            if (value.IndexOf(expected, StringComparison.Ordinal) < 0) throw new Exception("Expected substring '" + expected + "' in '" + value + "'.");
        }

        private static void True(bool condition, string message)
        {
            if (!condition) throw new Exception(message);
        }

        private static void Throws<T>(Action action) where T : Exception
        {
            try { action(); }
            catch (T) { return; }
            throw new Exception("Expected " + typeof(T).Name + ".");
        }
    }
}
