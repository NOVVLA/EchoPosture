using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace EchoPostureInstaller
{
    internal static class InstallerProgram
    {
        [STAThread]
        private static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            try
            {
                InstallerManifest manifest = InstallerManifest.LoadEmbedded(Assembly.GetExecutingAssembly());
                Application.Run(new InstallerForm(manifest));
            }
            catch (Exception error)
            {
                MessageBox.Show(error.Message, "EchoPosture Installer", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }

    internal sealed class ChoiceItem<T>
    {
        public string Label { get; private set; }
        public T Value { get; private set; }
        public ChoiceItem(string label, T value) { Label = label; Value = value; }
        public override string ToString() { return Label; }
    }

    internal sealed class InstallerForm : Form
    {
        private readonly InstallerManifest manifest;
        private readonly Panel body = new Panel();
        private readonly Label header = new Label();
        private readonly Label step = new Label();
        private readonly Button back = new Button();
        private readonly Button next = new Button();
        private readonly Button close = new Button();
        private Panel languagePage;
        private Panel optionsPage;
        private Panel progressPage;
        private Panel resultPage;
        private RadioButton chinese;
        private RadioButton english;
        private TextBox installPath;
        private ComboBox tier;
        private RadioButton officialWeights;
        private RadioButton mirrorWeights;
        private CheckBox consent;
        private CheckBox shortcut;
        private Label sourceNotice;
        private Label licenseNotice;
        private Label stageLabel;
        private Label fileLabel;
        private Label transferLabel;
        private ProgressBar programProgress;
        private ProgressBar modelProgress;
        private TextBox logBox;
        private Button pause;
        private Button cancel;
        private Label resultTitle;
        private Label resultDetail;
        private Button retry;
        private Button switchRetry;
        private Button launch;
        private Button openFolder;
        private Button copyLog;
        private Button manualOfficial;
        private Button manualMirror;
        private Button finish;
        private InstallerLanguage selectedLanguage;
        private WeightSource selectedSource;
        private WeightTier selectedTier;
        private InstallerEngine engine;
        private WeightRunner weightRunner;
        private bool running;
        private bool paused;
        private bool programInstalled;
        private bool weightsSucceeded;
        private bool licenseConfirmed;
        private bool createDesktopShortcut;
        private string chosenInstallPath;
        private readonly StringBuilder fullLog = new StringBuilder();
        private string logPath;

        public InstallerForm(InstallerManifest manifest)
        {
            this.manifest = manifest;
            selectedLanguage = System.Globalization.CultureInfo.CurrentUICulture.Name.StartsWith("zh", StringComparison.OrdinalIgnoreCase)
                ? InstallerLanguage.Chinese : InstallerLanguage.English;
            InitializeWindow();
            BuildPages();
            ApplyLanguage();
            ShowPage(languagePage, 1);
            FormClosing += OnFormClosing;
        }

        private void InitializeWindow()
        {
            Text = "EchoPosture GA-2.0.0 Installer";
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(780, 620);
            ClientSize = new Size(820, 650);
            BackColor = Color.FromArgb(246, 248, 251);
            Font = new Font("Segoe UI", 9F);

            var top = new Panel { Dock = DockStyle.Top, Height = 92, BackColor = Color.FromArgb(24, 35, 54) };
            header.AutoSize = false;
            header.SetBounds(30, 18, 740, 34);
            header.Font = new Font("Segoe UI Semibold", 20F);
            header.ForeColor = Color.White;
            step.SetBounds(33, 57, 730, 22);
            step.ForeColor = Color.FromArgb(188, 205, 232);
            top.Controls.Add(header);
            top.Controls.Add(step);
            Controls.Add(top);

            body.Dock = DockStyle.Fill;
            body.Padding = new Padding(30, 22, 30, 16);
            Controls.Add(body);
            body.BringToFront();

            var footer = new Panel { Dock = DockStyle.Bottom, Height = 66, BackColor = Color.White };
            back.SetBounds(520, 16, 86, 34);
            next.SetBounds(614, 16, 86, 34);
            close.SetBounds(708, 16, 86, 34);
            back.Click += delegate { ShowPage(languagePage, 1); };
            next.Click += NextClicked;
            close.Click += delegate { Close(); };
            footer.Controls.Add(back);
            footer.Controls.Add(next);
            footer.Controls.Add(close);
            Controls.Add(footer);
            footer.BringToFront();
        }

        private void BuildPages()
        {
            languagePage = Page();
            var languageTitle = TitleLabel("Choose language / 选择语言", 12);
            var languageHelp = TextLabel("The installer and model download script will use this language.\r\n安装器和模型下载脚本将使用此语言。", 58, 700, 50);
            chinese = new RadioButton { Text = "中文", AutoSize = true, Location = new Point(18, 135), Font = new Font(Font.FontFamily, 12F) };
            english = new RadioButton { Text = "English", AutoSize = true, Location = new Point(18, 180), Font = new Font(Font.FontFamily, 12F) };
            chinese.Checked = selectedLanguage == InstallerLanguage.Chinese;
            english.Checked = !chinese.Checked;
            chinese.CheckedChanged += delegate { if (chinese.Checked) { selectedLanguage = InstallerLanguage.Chinese; ApplyLanguage(); } };
            english.CheckedChanged += delegate { if (english.Checked) { selectedLanguage = InstallerLanguage.English; ApplyLanguage(); } };
            languagePage.Controls.Add(languageTitle);
            languagePage.Controls.Add(languageHelp);
            languagePage.Controls.Add(chinese);
            languagePage.Controls.Add(english);

            optionsPage = Page();
            installPath = new TextBox { Location = new Point(18, 72), Width = 595 };
            installPath.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "EchoPosture", "GA-2.0.0");
            var browse = new Button { Location = new Point(625, 69), Size = new Size(90, 30) };
            browse.Click += BrowseClicked;
            browse.Tag = "browse";
            tier = new ComboBox { Location = new Point(18, 145), Width = 300, DropDownStyle = ComboBoxStyle.DropDownList };
            tier.SelectedIndexChanged += TierChanged;
            officialWeights = new RadioButton { Location = new Point(18, 220), AutoSize = true, Checked = true };
            mirrorWeights = new RadioButton { Location = new Point(250, 220), AutoSize = true };
            sourceNotice = TextLabel(string.Empty, 256, 700, 48);
            licenseNotice = TextLabel(string.Empty, 314, 700, 92);
            licenseNotice.BackColor = Color.FromArgb(255, 248, 226);
            licenseNotice.Padding = new Padding(10);
            consent = new CheckBox { Location = new Point(18, 415), Width = 700, Height = 42 };
            shortcut = new CheckBox { Location = new Point(18, 466), Width = 700, Height = 28, Checked = true };
            optionsPage.Controls.Add(TitleLabel(string.Empty, 6));
            optionsPage.Controls.Add(TextLabel(string.Empty, 48, 650, 22));
            optionsPage.Controls.Add(installPath);
            optionsPage.Controls.Add(browse);
            optionsPage.Controls.Add(TextLabel(string.Empty, 121, 650, 22));
            optionsPage.Controls.Add(tier);
            optionsPage.Controls.Add(TextLabel(string.Empty, 190, 650, 22));
            optionsPage.Controls.Add(officialWeights);
            optionsPage.Controls.Add(mirrorWeights);
            optionsPage.Controls.Add(sourceNotice);
            optionsPage.Controls.Add(licenseNotice);
            optionsPage.Controls.Add(consent);
            optionsPage.Controls.Add(shortcut);

            progressPage = Page();
            stageLabel = TitleLabel(string.Empty, 6);
            fileLabel = TextLabel(string.Empty, 56, 700, 22);
            programProgress = new ProgressBar { Location = new Point(18, 88), Width = 697, Height = 22 };
            transferLabel = TextLabel(string.Empty, 118, 700, 22);
            modelProgress = new ProgressBar { Location = new Point(18, 150), Width = 697, Height = 16, Style = ProgressBarStyle.Blocks };
            logBox = new TextBox
            {
                Location = new Point(18, 184), Size = new Size(697, 260), Multiline = true, ReadOnly = true,
                ScrollBars = ScrollBars.Both, WordWrap = false, Font = new Font("Consolas", 9F), BackColor = Color.White,
            };
            pause = new Button { Location = new Point(18, 458), Size = new Size(105, 32) };
            cancel = new Button { Location = new Point(132, 458), Size = new Size(105, 32) };
            pause.Click += PauseClicked;
            cancel.Click += CancelClicked;
            progressPage.Controls.Add(stageLabel);
            progressPage.Controls.Add(fileLabel);
            progressPage.Controls.Add(programProgress);
            progressPage.Controls.Add(transferLabel);
            progressPage.Controls.Add(modelProgress);
            progressPage.Controls.Add(logBox);
            progressPage.Controls.Add(pause);
            progressPage.Controls.Add(cancel);

            resultPage = Page();
            resultTitle = TitleLabel(string.Empty, 6);
            resultDetail = TextLabel(string.Empty, 58, 700, 92);
            retry = ActionButton(18, 170, RetryClicked);
            switchRetry = ActionButton(188, 170, SwitchRetryClicked);
            launch = ActionButton(358, 170, delegate { LaunchInstalled(); });
            openFolder = ActionButton(528, 170, delegate { OpenInstallFolder(); });
            copyLog = ActionButton(18, 220, delegate { Clipboard.SetText(fullLog.ToString()); });
            manualOfficial = ActionButton(188, 220, delegate { LaunchManualWeightScript(WeightSource.Official); });
            manualMirror = ActionButton(358, 220, delegate { LaunchManualWeightScript(WeightSource.Mirror); });
            finish = ActionButton(528, 220, delegate { Close(); });
            var resultLogLabel = TextLabel(string.Empty, 278, 700, 22);
            resultLogLabel.Tag = "resultLog";
            var resultLog = new TextBox
            {
                Location = new Point(18, 308), Size = new Size(697, 180), Multiline = true, ReadOnly = true,
                ScrollBars = ScrollBars.Both, WordWrap = false, Font = new Font("Consolas", 9F), BackColor = Color.White,
            };
            resultLog.Tag = "resultLogBox";
            resultPage.Controls.Add(resultTitle);
            resultPage.Controls.Add(resultDetail);
            resultPage.Controls.Add(retry);
            resultPage.Controls.Add(switchRetry);
            resultPage.Controls.Add(launch);
            resultPage.Controls.Add(openFolder);
            resultPage.Controls.Add(copyLog);
            resultPage.Controls.Add(manualOfficial);
            resultPage.Controls.Add(manualMirror);
            resultPage.Controls.Add(finish);
            resultPage.Controls.Add(resultLogLabel);
            resultPage.Controls.Add(resultLog);
        }

        private Panel Page()
        {
            return new Panel { Dock = DockStyle.Fill, Visible = false, BackColor = BackColor };
        }

        private Label TitleLabel(string text, int y)
        {
            return new Label { Text = text, Location = new Point(18, y), Size = new Size(700, 38), Font = new Font("Segoe UI Semibold", 16F) };
        }

        private Label TextLabel(string text, int y, int width, int height)
        {
            return new Label { Text = text, Location = new Point(18, y), Size = new Size(width, height) };
        }

        private Button ActionButton(int x, int y, EventHandler handler)
        {
            var button = new Button { Location = new Point(x, y), Size = new Size(158, 36) };
            button.Click += handler;
            return button;
        }

        private void ShowPage(Panel page, int number)
        {
            if (languagePage != null) languagePage.Visible = false;
            if (optionsPage != null) optionsPage.Visible = false;
            if (progressPage != null) progressPage.Visible = false;
            if (resultPage != null) resultPage.Visible = false;
            body.Controls.Clear();
            body.Controls.Add(page);
            page.Visible = true;
            back.Visible = number == 2 && !running;
            next.Visible = number <= 2 && !running;
            close.Visible = !running;
            step.Text = T("Step " + number + " of 4", "第 " + number + "/4 步");
            ApplyLanguage();
        }

        private void ApplyLanguage()
        {
            Text = T("EchoPosture GA-2.0.0 Semi-portable Installer", "EchoPosture GA-2.0.0 半便携版安装器");
            header.Text = T("EchoPosture semi-portable installer", "EchoPosture 半便携版安装器");
            back.Text = T("Back", "上一步");
            next.Text = optionsPage != null && optionsPage.Visible ? T("Install", "开始安装") : T("Next", "下一步");
            close.Text = T("Close", "关闭");
            if (optionsPage == null) return;
            ((Label)optionsPage.Controls[0]).Text = T("Installation options", "安装选项");
            ((Label)optionsPage.Controls[1]).Text = T("Installation directory", "安装目录");
            ((Button)FindTagged(optionsPage, "browse")).Text = T("Browse...", "浏览...");
            ((Label)optionsPage.Controls[4]).Text = T("Pose model set", "姿态模型范围");
            ((Label)optionsPage.Controls[6]).Text = T("Model weight download source", "模型权重下载来源");
            officialWeights.Text = T("Official weight source", "权重官方源");
            mirrorWeights.Text = T("Mirror-first weight source", "权重镜像优先源");
            sourceNotice.Text = T(
                "EchoPosture application files are supplied only by the project through the official GitHub Release. This choice affects model weights only.",
                "EchoPosture 程序文件只由项目通过 GitHub 官方 Release 提供；此选项仅影响模型权重。");
            licenseNotice.Text = T(
                "YOLO weights are published by Ultralytics under AGPL-3.0 and are not bundled by EchoPosture. Mirror mode uses third-party proxies but verifies the official SHA-256. CVLFace weights are not downloaded or mirrored by this installer.",
                "YOLO 权重由 Ultralytics 以 AGPL-3.0 发布，EchoPosture 不随包分发。镜像模式使用第三方代理，但仍校验官方 SHA-256。本安装器不下载或镜像 CVLFace 权重。");
            consent.Text = T(
                "I have read the notice and choose to download the selected YOLO weights under their license.",
                "我已阅读上述说明，并选择按其许可条款下载所选 YOLO 权重。");
            shortcut.Text = T("Create a desktop shortcut", "创建桌面快捷方式");
            FillTierChoices();
            stageLabel.Text = T("Preparing installation", "正在准备安装");
            pause.Text = paused ? T("Resume", "继续") : T("Pause", "暂停");
            cancel.Text = T("Cancel", "取消");
            retry.Text = T("Retry weights", "重试权重");
            switchRetry.Text = T("Switch source & retry", "切换来源重试");
            launch.Text = T("Launch EchoPosture", "启动 EchoPosture");
            openFolder.Text = T("Open folder", "打开目录");
            copyLog.Text = T("Copy log", "复制日志");
            manualOfficial.Text = T("Official script", "官方源脚本");
            manualMirror.Text = T("Mirror script", "镜像源脚本");
            finish.Text = T("Close installer", "关闭安装器");
            Control resultLogLabel = FindTagged(resultPage, "resultLog");
            if (resultLogLabel != null) resultLogLabel.Text = T("Installation log", "安装日志");
        }

        private void FillTierChoices()
        {
            WeightTier previous = selectedTier == 0 ? WeightTier.Standard : selectedTier;
            tier.Items.Clear();
            tier.Items.Add(new ChoiceItem<WeightTier>("Standard - yolo26n-pose", WeightTier.Standard));
            tier.Items.Add(new ChoiceItem<WeightTier>("Professional pose - yolo26l/x-pose", WeightTier.Professional));
            tier.Items.Add(new ChoiceItem<WeightTier>("All pose weights", WeightTier.All));
            tier.Items.Add(new ChoiceItem<WeightTier>(T("Skip - Compatibility mode", "暂不下载 - Compatibility 模式"), WeightTier.Skip));
            for (int i = 0; i < tier.Items.Count; i++)
            {
                if (((ChoiceItem<WeightTier>)tier.Items[i]).Value.Equals(previous)) { tier.SelectedIndex = i; break; }
            }
            if (tier.SelectedIndex < 0) tier.SelectedIndex = 0;
        }

        private Control FindTagged(Control parent, string tag)
        {
            foreach (Control control in parent.Controls) if (object.Equals(control.Tag, tag)) return control;
            return null;
        }

        private void NextClicked(object sender, EventArgs args)
        {
            if (languagePage.Visible)
            {
                selectedLanguage = chinese.Checked ? InstallerLanguage.Chinese : InstallerLanguage.English;
                ShowPage(optionsPage, 2);
                return;
            }
            if (!optionsPage.Visible) return;
            selectedTier = ((ChoiceItem<WeightTier>)tier.SelectedItem).Value;
            selectedSource = mirrorWeights.Checked ? WeightSource.Mirror : WeightSource.Official;
            if (string.IsNullOrWhiteSpace(installPath.Text))
            {
                MessageBox.Show(T("Choose an installation directory.", "请选择安装目录。"), Text);
                return;
            }
            if (selectedTier != WeightTier.Skip && !consent.Checked)
            {
                MessageBox.Show(T("Model license consent is required before downloading weights.", "下载权重前必须确认模型许可说明。"), Text);
                return;
            }
            chosenInstallPath = Path.GetFullPath(installPath.Text);
            licenseConfirmed = consent.Checked;
            createDesktopShortcut = shortcut.Checked;
            BeginInstall();
        }

        private void BrowseClicked(object sender, EventArgs args)
        {
            using (var dialog = new FolderBrowserDialog())
            {
                dialog.Description = T("Choose the EchoPosture installation directory", "选择 EchoPosture 安装目录");
                dialog.SelectedPath = installPath.Text;
                if (dialog.ShowDialog(this) == DialogResult.OK) installPath.Text = dialog.SelectedPath;
            }
        }

        private void TierChanged(object sender, EventArgs args)
        {
            if (tier.SelectedItem == null) return;
            selectedTier = ((ChoiceItem<WeightTier>)tier.SelectedItem).Value;
            bool downloads = selectedTier != WeightTier.Skip;
            officialWeights.Enabled = downloads;
            mirrorWeights.Enabled = downloads;
            consent.Enabled = downloads;
            if (!downloads) consent.Checked = false;
        }

        private void BeginInstall()
        {
            running = true;
            paused = false;
            fullLog.Clear();
            logBox.Clear();
            programProgress.Value = 0;
            modelProgress.Style = ProgressBarStyle.Blocks;
            modelProgress.Value = 0;
            pause.Enabled = true;
            cancel.Enabled = true;
            back.Visible = next.Visible = close.Visible = false;
            ShowPage(progressPage, 3);
            PrepareLogFile();
            AppendLog(T("EchoPosture application source: official project GitHub Release only.", "EchoPosture 程序来源：仅项目 GitHub 官方 Release。"));
            engine = new InstallerEngine(manifest, new HttpTransferSource());
            engine.Log += AppendLog;
            engine.Progress += UpdateProgress;
            ThreadPool.QueueUserWorkItem(delegate
            {
                try
                {
                    string cache = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "EchoPosture", "InstallerCache", "ga-2.0.0");
                    InstallerRunResult result = engine.InstallProgram(cache, chosenInstallPath);
                    programInstalled = true;
                    if (createDesktopShortcut) CreateDesktopShortcut();
                    if (selectedTier == WeightTier.Skip)
                    {
                        weightsSucceeded = false;
                        CompleteOnUi(true, T("EchoPosture is ready in Compatibility mode. No model weights were downloaded.", "EchoPosture 已可以 Compatibility 模式运行；未下载模型权重。"));
                    }
                    else RunWeights(false);
                }
                catch (InstallerCancelledException)
                {
                    CompleteOnUi(false, T("Installation was cancelled. Verified partial downloads were kept for resume.", "安装已取消；已验证的部分下载已保留，可继续。"));
                }
                catch (Exception error)
                {
                    AppendLog(error.ToString());
                    CompleteOnUi(false, error.Message);
                }
            });
        }

        private void RunWeights(bool retryOnly)
        {
            RunOnUi(delegate
            {
                stageLabel.Text = T("Downloading model weights", "正在下载模型权重");
                fileLabel.Text = WeightScriptSelector.GetScriptName(selectedLanguage, selectedSource);
                modelProgress.Style = ProgressBarStyle.Marquee;
                pause.Enabled = false;
            });
            weightRunner = new WeightRunner();
            weightRunner.Output += AppendLog;
            int exitCode;
            try
            {
                exitCode = weightRunner.Run(chosenInstallPath, selectedLanguage, selectedSource, selectedTier, licenseConfirmed);
            }
            catch (InstallerCancelledException)
            {
                CompleteOnUi(false, T("Model download was cancelled. Compatibility mode remains available.", "模型下载已取消；Compatibility 模式仍可使用。"));
                return;
            }
            catch (Exception error)
            {
                AppendLog(error.ToString());
                CompleteOnUi(false, T("Model download failed. Compatibility mode remains available. ", "模型下载失败；Compatibility 模式仍可使用。") + error.Message);
                return;
            }
            weightsSucceeded = exitCode == 0;
            if (weightsSucceeded)
            {
                CompleteOnUi(true, T("EchoPosture and the selected pose weights are ready.", "EchoPosture 及所选姿态权重已就绪。"));
            }
            else
            {
                CompleteOnUi(false, T("The model script exited with code ", "模型脚本退出码为 ") + exitCode
                    + T(". Compatibility mode remains available.", "；Compatibility 模式仍可使用。"));
            }
        }

        private void CompleteOnUi(bool success, string detail)
        {
            RunOnUi(delegate
            {
                running = false;
                paused = false;
                resultTitle.Text = success ? T("Installation complete", "安装完成") : T("Installation needs attention", "安装需要处理");
                resultTitle.ForeColor = success ? Color.FromArgb(24, 122, 72) : Color.FromArgb(177, 80, 32);
                resultDetail.Text = detail;
                retry.Visible = programInstalled && selectedTier != WeightTier.Skip && !weightsSucceeded;
                switchRetry.Visible = retry.Visible;
                launch.Enabled = programInstalled;
                openFolder.Enabled = programInstalled;
                manualOfficial.Visible = programInstalled && selectedTier == WeightTier.Skip;
                manualMirror.Visible = manualOfficial.Visible;
                Control resultLog = FindTagged(resultPage, "resultLogBox");
                if (resultLog != null) resultLog.Text = fullLog.ToString();
                ShowPage(resultPage, 4);
                close.Visible = false;
            });
        }

        private void RetryClicked(object sender, EventArgs args)
        {
            BeginWeightRetry(false);
        }

        private void SwitchRetryClicked(object sender, EventArgs args)
        {
            selectedSource = selectedSource == WeightSource.Official ? WeightSource.Mirror : WeightSource.Official;
            BeginWeightRetry(true);
        }

        private void BeginWeightRetry(bool switched)
        {
            running = true;
            ShowPage(progressPage, 3);
            back.Visible = next.Visible = close.Visible = false;
            cancel.Enabled = true;
            AppendLog(switched ? T("Switched model weight source and retrying.", "已切换模型权重来源并重试。")
                : T("Retrying model weight download.", "正在重试模型权重下载。"));
            ThreadPool.QueueUserWorkItem(delegate { RunWeights(true); });
        }

        private void PauseClicked(object sender, EventArgs args)
        {
            if (engine == null) return;
            paused = !paused;
            if (paused) engine.Pause(); else engine.Resume();
            pause.Text = paused ? T("Resume", "继续") : T("Pause", "暂停");
            AppendLog(paused ? T("Download paused.", "下载已暂停。") : T("Download resumed.", "下载已继续。"));
        }

        private void CancelClicked(object sender, EventArgs args)
        {
            if (MessageBox.Show(T("Cancel the current operation?", "确定取消当前操作吗？"), Text,
                MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
            cancel.Enabled = false;
            if (engine != null) engine.Cancel();
            if (weightRunner != null) weightRunner.Cancel();
            AppendLog(T("Cancellation requested.", "已请求取消。"));
        }

        private void UpdateProgress(InstallerProgress progress)
        {
            RunOnUi(delegate
            {
                stageLabel.Text = progress.Stage == "download" ? T("Downloading official application files", "正在下载官方程序文件")
                    : progress.Stage == "verify" ? T("Verifying and reconstructing", "正在校验并重组")
                    : T("Extracting and installing", "正在解压并安装");
                fileLabel.Text = progress.CurrentFile;
                int percent = progress.TotalBytes <= 0 ? 0 : (int)Math.Min(100, progress.CompletedBytes * 100L / progress.TotalBytes);
                programProgress.Value = Math.Max(0, Math.Min(100, percent));
                transferLabel.Text = FormatBytes(progress.CompletedBytes) + " / " + FormatBytes(progress.TotalBytes)
                    + "    " + FormatBytes((long)progress.BytesPerSecond) + "/s";
            });
        }

        private void AppendLog(string line)
        {
            if (string.IsNullOrEmpty(line)) return;
            string entry = DateTime.Now.ToString("HH:mm:ss") + "  " + line;
            lock (fullLog)
            {
                fullLog.AppendLine(entry);
                try { if (!string.IsNullOrEmpty(logPath)) File.AppendAllText(logPath, entry + Environment.NewLine, new UTF8Encoding(false)); } catch { }
            }
            RunOnUi(delegate
            {
                logBox.AppendText(entry + Environment.NewLine);
                logBox.SelectionStart = logBox.TextLength;
                logBox.ScrollToCaret();
            });
        }

        private void PrepareLogFile()
        {
            try
            {
                string directory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "EchoPosture", "InstallerLogs");
                Directory.CreateDirectory(directory);
                logPath = Path.Combine(directory, "ga-2.0.0-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".log");
            }
            catch { logPath = null; }
        }

        private void CreateDesktopShortcut()
        {
            try
            {
                string shortcutPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "EchoPosture.lnk");
                Type shellType = Type.GetTypeFromProgID("WScript.Shell");
                object shell = Activator.CreateInstance(shellType);
                object link = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { shortcutPath });
                Type linkType = link.GetType();
                linkType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { Path.Combine(chosenInstallPath, "EchoPosture.exe") });
                linkType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { chosenInstallPath });
                linkType.InvokeMember("Description", BindingFlags.SetProperty, null, link, new object[] { "EchoPosture GA-2.0.0" });
                linkType.InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
                AppendLog(T("Desktop shortcut created.", "已创建桌面快捷方式。"));
            }
            catch (Exception error) { AppendLog(T("Desktop shortcut could not be created: ", "无法创建桌面快捷方式：") + error.Message); }
        }

        private void LaunchInstalled()
        {
            string executable = Path.Combine(chosenInstallPath, "EchoPosture.exe");
            if (File.Exists(executable)) Process.Start(executable);
        }

        private void OpenInstallFolder()
        {
            if (Directory.Exists(chosenInstallPath)) Process.Start("explorer.exe", WeightScriptSelector.Quote(chosenInstallPath));
        }

        private void LaunchManualWeightScript(WeightSource source)
        {
            string script = Path.Combine(chosenInstallPath, "tools", "fetch_pose_models", WeightScriptSelector.GetScriptName(selectedLanguage, source));
            if (!File.Exists(script)) return;
            string command = "-NoExit -NoProfile -ExecutionPolicy Bypass -File " + WeightScriptSelector.Quote(script)
                + " -DestinationRoot " + WeightScriptSelector.Quote(Path.Combine(chosenInstallPath, "models", "pose"));
            Process.Start(new ProcessStartInfo("powershell.exe", command) { WorkingDirectory = chosenInstallPath, UseShellExecute = true });
        }

        private void OnFormClosing(object sender, FormClosingEventArgs args)
        {
            if (!running) return;
            if (MessageBox.Show(T("An operation is still running. Cancel it and keep this window open?", "操作仍在进行。是否取消并保留此窗口？"),
                Text, MessageBoxButtons.YesNo, MessageBoxIcon.Warning) == DialogResult.Yes)
            {
                if (engine != null) engine.Cancel();
                if (weightRunner != null) weightRunner.Cancel();
            }
            args.Cancel = true;
        }

        private void RunOnUi(Action action)
        {
            if (IsDisposed) return;
            if (InvokeRequired) BeginInvoke(action); else action();
        }

        private string T(string englishText, string chineseText)
        {
            return selectedLanguage == InstallerLanguage.Chinese ? chineseText : englishText;
        }

        private static string FormatBytes(long bytes)
        {
            if (bytes >= 1024L * 1024 * 1024) return (bytes / (1024d * 1024 * 1024)).ToString("0.00") + " GiB";
            if (bytes >= 1024L * 1024) return (bytes / (1024d * 1024)).ToString("0.0") + " MiB";
            if (bytes >= 1024L) return (bytes / 1024d).ToString("0.0") + " KiB";
            return bytes + " B";
        }
    }
}
