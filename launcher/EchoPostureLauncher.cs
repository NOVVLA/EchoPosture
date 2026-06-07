using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows.Forms;

namespace EchoPostureLauncher
{
    internal static class Program
    {
        private const string AppName = "EchoPosture";

        [STAThread]
        private static int Main(string[] args)
        {
            try
            {
                string packageRoot = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(
                    Path.DirectorySeparatorChar,
                    Path.AltDirectorySeparatorChar);
                string runRoot = PrepareRunRoot(packageRoot);
                ConfigureEnvironment(runRoot);

                bool selfTest = HasArg(args, "--self-test")
                    || Path.GetFileNameWithoutExtension(Application.ExecutablePath)
                        .IndexOf("SelfTest", StringComparison.OrdinalIgnoreCase) >= 0;

                if (selfTest)
                {
                    return RunSelfTest(packageRoot, runRoot);
                }

                bool debugUiMode = HasArg(args, "--debug-ui");
                string pythonw = Path.Combine(runRoot, "runtime", "python311", "pythonw.exe");
                string appScript = Path.Combine(runRoot, debugUiMode ? "debug_ui.py" : "tray_app.py");
                if (!File.Exists(pythonw) || !File.Exists(appScript))
                {
                    throw new FileNotFoundException("EchoPosture runtime or app script was not found.");
                }

                string forwardedArgs = string.Join(
                    " ",
                    args.Where(arg => !string.Equals(arg, "--debug-ui", StringComparison.OrdinalIgnoreCase))
                        .Select(QuoteArgument));
                var startInfo = new ProcessStartInfo
                {
                    FileName = pythonw,
                    Arguments = QuoteArgument(appScript) + (forwardedArgs.Length > 0 ? " " + forwardedArgs : string.Empty),
                    WorkingDirectory = runRoot,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                ApplyEnvironment(startInfo, runRoot);
                Process.Start(startInfo);
                return 0;
            }
            catch (Exception ex)
            {
#if CONSOLE_APP
                Console.Error.WriteLine(ex.ToString());
#else
                MessageBox.Show(ex.Message, AppName + " startup error", MessageBoxButtons.OK, MessageBoxIcon.Error);
#endif
                return 1;
            }
        }

        private static bool HasArg(string[] args, string value)
        {
            return args.Any(arg => string.Equals(arg, value, StringComparison.OrdinalIgnoreCase));
        }

        private static string PrepareRunRoot(string packageRoot)
        {
            string runtimePython = Path.Combine(packageRoot, "runtime", "python311", "python.exe");
            if (!File.Exists(runtimePython))
            {
                throw new FileNotFoundException("Embedded Python runtime was not found: " + runtimePython);
            }

            string bridgeBase = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "EchoPostureDev");
            string bridgeRoot = Path.Combine(bridgeBase, "current");

            try
            {
                Directory.CreateDirectory(bridgeBase);
                string bridgeScript =
                    "$ErrorActionPreference='Stop';" +
                    "if (Test-Path -LiteralPath " + QuotePowerShellLiteral(bridgeRoot) + ") {" +
                    "Remove-Item -LiteralPath " + QuotePowerShellLiteral(bridgeRoot) + " -Force -Recurse;" +
                    "};" +
                    "New-Item -ItemType Junction -Path " + QuotePowerShellLiteral(bridgeRoot) +
                    " -Target " + QuotePowerShellLiteral(packageRoot) + " | Out-Null;";
                RunHidden(
                    "powershell.exe",
                    "-NoProfile -ExecutionPolicy Bypass -Command " + QuoteArgument(bridgeScript),
                    packageRoot,
                    10000);

                string bridgedPython = Path.Combine(bridgeRoot, "runtime", "python311", "python.exe");
                if (File.Exists(bridgedPython))
                {
                    return bridgeRoot;
                }
            }
            catch
            {
                // Fall through to the mirror copy below. The bridge is only a compatibility layer for non-ASCII paths.
            }

            try
            {
                string mirrorRoot = Path.Combine(bridgeBase, "current-copy");
                MirrorDirectory(packageRoot, mirrorRoot);
                string mirroredPython = Path.Combine(mirrorRoot, "runtime", "python311", "python.exe");
                if (File.Exists(mirroredPython))
                {
                    return mirrorRoot;
                }
            }
            catch
            {
                // Fall back to the package directory. Some locked-down environments deny writes to LocalAppData.
            }

            return packageRoot;
        }

        private static void MirrorDirectory(string sourceRoot, string destinationRoot)
        {
            if (Directory.Exists(destinationRoot))
            {
                Directory.Delete(destinationRoot, true);
            }
            Directory.CreateDirectory(destinationRoot);
            CopyDirectory(sourceRoot, destinationRoot);
        }

        private static void CopyDirectory(string sourceRoot, string destinationRoot)
        {
            foreach (string sourceFile in Directory.GetFiles(sourceRoot))
            {
                string name = Path.GetFileName(sourceFile);
                if (string.Equals(name, "EchoPostureSelfTest.exe", StringComparison.OrdinalIgnoreCase))
                {
                    // Keep the diagnostic entry in the original package root so self-test logs stay there.
                }
                string destinationFile = Path.Combine(destinationRoot, name);
                File.Copy(sourceFile, destinationFile, true);
            }

            foreach (string sourceDirectory in Directory.GetDirectories(sourceRoot))
            {
                string name = Path.GetFileName(sourceDirectory);
                if (string.Equals(name, "logs", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(name, "__pycache__", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                string destinationDirectory = Path.Combine(destinationRoot, name);
                Directory.CreateDirectory(destinationDirectory);
                CopyDirectory(sourceDirectory, destinationDirectory);
            }
        }

        private static void ConfigureEnvironment(string runRoot)
        {
            Environment.SetEnvironmentVariable("PYTHONUTF8", "1");
            Environment.SetEnvironmentVariable("PYTHONIOENCODING", "utf-8");
            Environment.SetEnvironmentVariable("GLOG_minloglevel", "2");
            Environment.SetEnvironmentVariable("TF_CPP_MIN_LOG_LEVEL", "2");

            string qtPlugins = Path.Combine(runRoot, "runtime", "python311", "Lib", "site-packages", "PyQt5", "Qt5", "plugins");
            Environment.SetEnvironmentVariable("QT_PLUGIN_PATH", qtPlugins);
            Environment.SetEnvironmentVariable("QT_QPA_PLATFORM_PLUGIN_PATH", Path.Combine(qtPlugins, "platforms"));
        }

        private static void ApplyEnvironment(ProcessStartInfo startInfo, string runRoot)
        {
            startInfo.EnvironmentVariables["PYTHONUTF8"] = "1";
            startInfo.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            startInfo.EnvironmentVariables["GLOG_minloglevel"] = "2";
            startInfo.EnvironmentVariables["TF_CPP_MIN_LOG_LEVEL"] = "2";

            string qtPlugins = Path.Combine(runRoot, "runtime", "python311", "Lib", "site-packages", "PyQt5", "Qt5", "plugins");
            startInfo.EnvironmentVariables["QT_PLUGIN_PATH"] = qtPlugins;
            startInfo.EnvironmentVariables["QT_QPA_PLATFORM_PLUGIN_PATH"] = Path.Combine(qtPlugins, "platforms");
        }

        private static int RunSelfTest(string packageRoot, string runRoot)
        {
            string logs = Path.Combine(packageRoot, "logs");
            Directory.CreateDirectory(logs);
            string report = Path.Combine(logs, "self-test-latest.txt");

            var builder = new StringBuilder();
            builder.AppendLine("EchoPosture Canary self-test");
            builder.AppendLine("Package root: " + packageRoot);
            builder.AppendLine("Run root: " + runRoot);
            builder.AppendLine("Time: " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
            builder.AppendLine();

            int blurCode = RunExecutable(
                runRoot,
                "BlurOverlayHost.exe",
                "--self-test",
                builder,
                "[1/4] GPU blur overlay host self-test");

            int uiCode = RunPython(
                runRoot,
                "debug_ui.py",
                "--self-test --fps 1",
                builder,
                "[2/4] Debug UI offscreen self-test");

            int visionCode = RunPython(
                runRoot,
                "vision_test.py",
                "--max-samples 1 --fps 1",
                builder,
                "[3/4] Vision one-frame self-test");

            int trayCode = RunPython(
                runRoot,
                "tray_app.py",
                "--self-test --fps 1",
                builder,
                "[4/4] Tray monitor self-test");

            File.WriteAllText(report, builder.ToString(), Encoding.UTF8);
            string message = (blurCode == 0 && uiCode == 0 && visionCode == 0 && trayCode == 0)
                ? "Self-test passed."
                : "Self-test failed.";
            string notification = message + Environment.NewLine + report;
#if CONSOLE_APP
            Console.WriteLine(notification);
#else
            MessageBox.Show(notification, AppName + " self-test", MessageBoxButtons.OK,
                blurCode == 0 && uiCode == 0 && visionCode == 0 && trayCode == 0 ? MessageBoxIcon.Information : MessageBoxIcon.Error);
#endif
            if (blurCode != 0) return blurCode;
            if (uiCode != 0) return uiCode;
            if (visionCode != 0) return visionCode;
            return trayCode;
        }

        private static int RunExecutable(string runRoot, string fileName, string arguments, StringBuilder output, string title)
        {
            output.AppendLine(title);
            string executable = Path.Combine(runRoot, fileName);
            if (!File.Exists(executable))
            {
                output.AppendLine("Missing executable: " + executable);
                output.AppendLine("Exit code: 1");
                output.AppendLine();
                return 1;
            }

            var startInfo = new ProcessStartInfo
            {
                FileName = executable,
                Arguments = arguments,
                WorkingDirectory = runRoot,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
            };

            using (Process process = Process.Start(startInfo))
            {
                string stdout = process.StandardOutput.ReadToEnd();
                string stderr = process.StandardError.ReadToEnd();
                process.WaitForExit();
                output.Append(stdout);
                output.Append(stderr);
                output.AppendLine("Exit code: " + process.ExitCode);
                output.AppendLine();
                return process.ExitCode;
            }
        }

        private static int RunPython(string runRoot, string scriptName, string arguments, StringBuilder output, string title)
        {
            output.AppendLine(title);
            string python = Path.Combine(runRoot, "runtime", "python311", "python.exe");
            string script = Path.Combine(runRoot, scriptName);
            var startInfo = new ProcessStartInfo
            {
                FileName = python,
                Arguments = QuoteArgument(script) + " " + arguments,
                WorkingDirectory = runRoot,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
            };
            ApplyEnvironment(startInfo, runRoot);

            using (Process process = Process.Start(startInfo))
            {
                string stdout = process.StandardOutput.ReadToEnd();
                string stderr = process.StandardError.ReadToEnd();
                process.WaitForExit();
                output.Append(stdout);
                output.Append(stderr);
                output.AppendLine("Exit code: " + process.ExitCode);
                output.AppendLine();
                return process.ExitCode;
            }
        }

        private static int RunHidden(string fileName, string arguments, string workingDirectory, int timeoutMs)
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                WorkingDirectory = workingDirectory,
                UseShellExecute = false,
                CreateNoWindow = true,
            };

            using (Process process = Process.Start(startInfo))
            {
                if (!process.WaitForExit(timeoutMs))
                {
                    try { process.Kill(); } catch { }
                    return 1;
                }
                return process.ExitCode;
            }
        }

        private static string QuotePowerShellLiteral(string value)
        {
            return "'" + value.Replace("'", "''") + "'";
        }

        private static string QuoteArgument(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "\"\"";
            }

            return "\"" + value.Replace("\"", "\\\"") + "\"";
        }
    }
}
