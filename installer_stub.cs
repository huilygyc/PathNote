using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("PathNote Setup")]
[assembly: AssemblyProduct("PathNote · 路径备注")]
[assembly: AssemblyVersion("1.1.0.0")]
[assembly: AssemblyFileVersion("1.1.0.0")]

namespace PathNoteSetup
{
    public class SetupForm : Form
    {
        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        private TextBox txtDir;
        private CheckBox chkDesktop;
        private CheckBox chkStartMenu;
        private CheckBox chkAutoStart;
        private CheckBox chkLaunchNow;
        private Button btnInstall;
        private Button btnBrowse;
        private Label lblStatus;

        public SetupForm()
        {
            Text = "PathNote · 路径备注 v1.1.0 安装程序";
            ClientSize = new Size(520, 340);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.White;
            Font = new Font("Microsoft YaHei UI", 9.5F, FontStyle.Regular);

            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            PictureBox picIcon = new PictureBox();
            picIcon.Bounds = new Rectangle(28, 24, 48, 48);
            picIcon.SizeMode = PictureBoxSizeMode.Zoom;
            if (Icon != null) picIcon.Image = Icon.ToBitmap();
            Controls.Add(picIcon);

            Label lblTitle = new Label();
            lblTitle.Text = "安装 PathNote · 路径备注 v1.1.0";
            lblTitle.Font = new Font("Microsoft YaHei UI", 13.5F, FontStyle.Bold);
            lblTitle.ForeColor = Color.FromArgb(24, 24, 27);
            lblTitle.Bounds = new Rectangle(88, 24, 400, 28);
            Controls.Add(lblTitle);

            Label lblSub = new Label();
            lblSub.Text = "Windows 英文路径文件与文件夹原位括号备注助手";
            lblSub.ForeColor = Color.FromArgb(113, 113, 122);
            lblSub.Bounds = new Rectangle(90, 52, 400, 22);
            Controls.Add(lblSub);

            Label lblDir = new Label();
            lblDir.Text = "安装位置：";
            lblDir.Font = new Font("Microsoft YaHei UI", 9.5F, FontStyle.Bold);
            lblDir.ForeColor = Color.FromArgb(63, 63, 70);
            lblDir.Bounds = new Rectangle(28, 92, 200, 22);
            Controls.Add(lblDir);

            string defaultDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs", "PathNote"
            );

            txtDir = new TextBox();
            txtDir.Text = defaultDir;
            txtDir.Bounds = new Rectangle(28, 118, 376, 28);
            Controls.Add(txtDir);

            btnBrowse = new Button();
            btnBrowse.Text = "浏览...";
            btnBrowse.Bounds = new Rectangle(412, 116, 80, 30);
            btnBrowse.FlatStyle = FlatStyle.System;
            btnBrowse.Click += OnBrowse;
            Controls.Add(btnBrowse);

            chkDesktop = new CheckBox { Text = "创建桌面快捷方式", Checked = true, Bounds = new Rectangle(30, 162, 220, 26) };
            chkStartMenu = new CheckBox { Text = "创建开始菜单快捷方式", Checked = true, Bounds = new Rectangle(260, 162, 220, 26) };
            chkAutoStart = new CheckBox { Text = "开机自动后台启动（推荐）", Checked = true, Bounds = new Rectangle(30, 194, 220, 26) };
            chkLaunchNow = new CheckBox { Text = "安装完成后立即启动 PathNote", Checked = true, Bounds = new Rectangle(260, 194, 230, 26) };

            Controls.Add(chkDesktop);
            Controls.Add(chkStartMenu);
            Controls.Add(chkAutoStart);
            Controls.Add(chkLaunchNow);

            lblStatus = new Label();
            lblStatus.Text = "准备就绪，无需管理员权限即可安装。";
            lblStatus.ForeColor = Color.FromArgb(113, 113, 122);
            lblStatus.Bounds = new Rectangle(28, 240, 464, 24);
            Controls.Add(lblStatus);

            Button btnCancel = new Button();
            btnCancel.Text = "取消";
            btnCancel.Bounds = new Rectangle(300, 282, 88, 34);
            btnCancel.FlatStyle = FlatStyle.Flat;
            btnCancel.FlatAppearance.BorderColor = Color.FromArgb(228, 228, 231);
            btnCancel.Click += (s, e) => Close();
            Controls.Add(btnCancel);

            btnInstall = new Button();
            btnInstall.Text = "立即安装";
            btnInstall.Bounds = new Rectangle(396, 282, 96, 34);
            btnInstall.BackColor = Color.FromArgb(37, 99, 235);
            btnInstall.ForeColor = Color.White;
            btnInstall.FlatStyle = FlatStyle.Flat;
            btnInstall.FlatAppearance.BorderSize = 0;
            btnInstall.Font = new Font("Microsoft YaHei UI", 9.5F, FontStyle.Bold);
            btnInstall.Click += OnInstall;
            Controls.Add(btnInstall);
        }

        private void OnBrowse(object sender, EventArgs e)
        {
            using (var dlg = new FolderBrowserDialog())
            {
                dlg.Description = "选择 PathNote 安装目录";
                dlg.SelectedPath = txtDir.Text;
                if (dlg.ShowDialog(this) == DialogResult.OK)
                {
                    txtDir.Text = Path.Combine(dlg.SelectedPath, "PathNote");
                }
            }
        }

        private void OnInstall(object sender, EventArgs e)
        {
            btnInstall.Enabled = false;
            btnBrowse.Enabled = false;
            lblStatus.ForeColor = Color.FromArgb(37, 99, 235);
            lblStatus.Text = "正在解压并配置组件，请稍候...";
            Application.DoEvents();

            try
            {
                PerformInstall(
                    txtDir.Text.Trim(),
                    chkDesktop.Checked,
                    chkStartMenu.Checked,
                    chkAutoStart.Checked,
                    chkLaunchNow.Checked
                );
                lblStatus.ForeColor = Color.FromArgb(5, 150, 105);
                lblStatus.Text = "安装成功！";
                Application.DoEvents();
                Close();
            }
            catch (Exception ex)
            {
                btnInstall.Enabled = true;
                btnBrowse.Enabled = true;
                lblStatus.ForeColor = Color.FromArgb(220, 38, 38);
                lblStatus.Text = "安装出错：" + ex.Message;
                MessageBox.Show(this, ex.ToString(), "安装失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        public static void PerformInstall(string targetDir, bool desktopLnk, bool startMenuLnk, bool autoStart, bool launchNow)
        {
            // Close existing running PathNote.exe in targetDir if upgrading
            foreach (var p in Process.GetProcessesByName("PathNote"))
            {
                try { p.Kill(); p.WaitForExit(1500); } catch { }
            }

            Directory.CreateDirectory(targetDir);

            using (Stream res = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
            {
                if (res == null) throw new InvalidOperationException("内置安装包资源损坏");
                using (ZipArchive archive = new ZipArchive(res, ZipArchiveMode.Read))
                {
                    foreach (ZipArchiveEntry entry in archive.Entries)
                    {
                        string rel = entry.FullName;
                        if (rel.StartsWith("PathNote/") || rel.StartsWith("PathNote\\"))
                            rel = rel.Substring(9);
                        if (string.IsNullOrEmpty(rel)) continue;

                        string destPath = Path.Combine(targetDir, rel.Replace('/', Path.DirectorySeparatorChar));
                        if (string.IsNullOrEmpty(entry.Name))
                        {
                            Directory.CreateDirectory(destPath);
                        }
                        else
                        {
                            Directory.CreateDirectory(Path.GetDirectoryName(destPath));
                            entry.ExtractToFile(destPath, true);
                        }
                    }
                }
            }

            string exePath = Path.Combine(targetDir, "PathNote.exe");

            if (desktopLnk)
            {
                string desk = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                CreateShortcut(Path.Combine(desk, "PathNote 路径备注.lnk"), exePath, targetDir);
            }

            if (startMenuLnk)
            {
                string programs = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
                CreateShortcut(Path.Combine(programs, "PathNote 路径备注.lnk"), exePath, targetDir);
            }

            using (RegistryKey runKey = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run", true))
            {
                if (runKey != null)
                {
                    if (autoStart)
                        runKey.SetValue("PathNote", "\"" + exePath + "\" --minimized");
                    else
                        runKey.DeleteValue("PathNote", false);
                }
            }

            // Write simple uninstaller script & register in Windows Installed Apps
            string uninstBat = Path.Combine(targetDir, "Uninstall.bat");
            File.WriteAllText(uninstBat,
                "@echo off\r\n" +
                "taskkill /F /IM PathNote.exe >nul 2>&1\r\n" +
                "reg delete \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\" /v PathNote /f >nul 2>&1\r\n" +
                "reg delete \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PathNote\" /f >nul 2>&1\r\n" +
                "del /f /q \"%USERPROFILE%\\Desktop\\PathNote 路径备注.lnk\" >nul 2>&1\r\n" +
                "del /f /q \"%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\PathNote 路径备注.lnk\" >nul 2>&1\r\n" +
                "start \"\" /b cmd /c \"ping 127.0.0.1 -n 2 >nul & rmdir /s /q \"" + targetDir + "\"\"\r\n"
            );

            using (RegistryKey unKey = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\PathNote"))
            {
                if (unKey != null)
                {
                    unKey.SetValue("DisplayName", "PathNote · 路径备注");
                    unKey.SetValue("DisplayVersion", "1.1.0");
                    unKey.SetValue("Publisher", "PathNote Open Source");
                    unKey.SetValue("DisplayIcon", exePath);
                    unKey.SetValue("InstallLocation", targetDir);
                    unKey.SetValue("UninstallString", "\"" + uninstBat + "\"");
                    unKey.SetValue("NoModify", 1, RegistryValueKind.DWord);
                    unKey.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                }
            }

            if (launchNow && File.Exists(exePath))
            {
                Process.Start(new ProcessStartInfo { FileName = exePath, WorkingDirectory = targetDir, UseShellExecute = true });
            }
        }

        private static void CreateShortcut(string lnkPath, string targetExe, string workDir)
        {
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            if (shellType == null) return;
            dynamic shell = Activator.CreateInstance(shellType);
            dynamic shortcut = shell.CreateShortcut(lnkPath);
            shortcut.TargetPath = targetExe;
            shortcut.WorkingDirectory = workDir;
            shortcut.IconLocation = targetExe + ",0";
            shortcut.Description = "PathNote · 路径备注";
            shortcut.Save();
        }

        [STAThread]
        public static int Main(string[] args)
        {
            try { SetProcessDPIAware(); } catch { }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            if (args.Length >= 2 && args[0] == "--silent-dir")
            {
                PerformInstall(args[1], false, false, false, false);
                return 0;
            }

            Application.Run(new SetupForm());
            return 0;
        }
    }
}
