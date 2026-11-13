using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: AssemblyTitle("Распознаватель — установщик")]
[assembly: AssemblyProduct("Распознаватель")]
[assembly: AssemblyDescription("Установщик «Распознаватель» 2.7.0")]
[assembly: AssemblyVersion("2.7.0.0")]
[assembly: AssemblyFileVersion("2.7.0.0")]

namespace RspSetup
{
    static class RunLog
    {
        public static void Write(string message)
        {
            try
            {
                string dir = Path.Combine(Path.GetTempPath(), "RaspoznavatelSetup");
                Directory.CreateDirectory(dir);
                File.AppendAllText(Path.Combine(dir, "run.log"),
                    DateTime.Now.ToString("HH:mm:ss.fff") + " " + message + "\r\n");
            }
            catch { }
        }
    }

    static class Program
    {
        [STAThread]
        static void Main()
        {
            AppDomain.CurrentDomain.AssemblyResolve += ResolveAssembly;
            ExtractNativeLoader();
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new SetupForm());
        }

        static Assembly ResolveAssembly(object sender, ResolveEventArgs args)
        {
            string name = new AssemblyName(args.Name).Name;
            string resource = name + ".dll";
            using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream(resource))
            {
                if (s == null)
                    return null;
                byte[] data = new byte[s.Length];
                s.Read(data, 0, data.Length);
                return Assembly.Load(data);
            }
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool SetDllDirectory(string path);

        static void ExtractNativeLoader()
        {
            string dir = Path.Combine(Path.GetTempPath(), "RaspoznavatelSetup");
            Directory.CreateDirectory(dir);
            string path = Path.Combine(dir, "WebView2Loader.dll");
            if (!File.Exists(path))
            {
                using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream("WebView2Loader.dll"))
                {
                    if (s == null)
                        throw new Exception("WebView2Loader.dll не найден в установщике.");
                    using (FileStream f = File.Create(path))
                        s.CopyTo(f);
                }
            }
            SetDllDirectory(dir);
        }
    }

    class SetupForm : Form
    {
        [DllImport("user32.dll")]
        static extern bool ReleaseCapture();
        [DllImport("user32.dll")]
        static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);

        const int WM_NCLBUTTONDOWN = 0xA1;
        const int HTCAPTION = 2;

        WebView2 web;
        string html;
        string mode = "install";
        string appPath;
        string installPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
            "Raspoznavatel");
        string portablePath = Path.Combine(
            Path.GetDirectoryName(Application.ExecutablePath) ?? Directory.GetCurrentDirectory(),
            "Raspoznavatel-Portable");
        volatile bool busy;
        int progress;
        Timer progressTimer;
        Process backendProcess;
        volatile bool cancelRequested;
        JavaScriptSerializer json = new JavaScriptSerializer();

        public SetupForm()
        {
            Text = "Установка — Распознаватель 2.7.0";
            FormBorderStyle = FormBorderStyle.None;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(833, 541);
            BackColor = Color.FromArgb(7, 11, 22);
            ShowInTaskbar = true;
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
            UpdateWindowRegion();
            Resize += (s, e) => UpdateWindowRegion();

            web = new WebView2
            {
                Dock = DockStyle.Fill
            };
            Controls.Add(web);
            Load += OnLoad;

            progressTimer = new Timer();
            progressTimer.Interval = 700;
            progressTimer.Tick += (s, e) =>
            {
                if (!busy) return;
                progress = Math.Min(90, progress + 4);
                SendProgress(progress, mode == "portable" ? "Распаковываю файлы…" : "Устанавливаю файлы…");
            };

            string resource = "installer_ui.html";
            using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream(resource))
            {
                if (s == null)
                    throw new Exception("HTML-интерфейс не найден в установщике.");
                using (StreamReader r = new StreamReader(s, Encoding.UTF8))
                    html = r.ReadToEnd();
            }
        }

        void UpdateWindowRegion()
        {
            int radius = 18;
            using (GraphicsPath path = new GraphicsPath())
            {
                Rectangle bounds = ClientRectangle;
                int diameter = radius * 2;
                path.AddArc(bounds.Left, bounds.Top, diameter, diameter, 180, 90);
                path.AddArc(bounds.Right - diameter, bounds.Top, diameter, diameter, 270, 90);
                path.AddArc(bounds.Right - diameter, bounds.Bottom - diameter, diameter, diameter, 0, 90);
                path.AddArc(bounds.Left, bounds.Bottom - diameter, diameter, diameter, 90, 90);
                path.CloseFigure();
                Region old = Region;
                Region = new Region(path);
                if (old != null) old.Dispose();
            }
        }

        async void OnLoad(object sender, EventArgs e)
        {
            try
            {
                string dataDir = Path.Combine(Path.GetTempPath(), "RaspoznavatelSetup", "WebView2");
                Directory.CreateDirectory(dataDir);
                CoreWebView2Environment env = await CoreWebView2Environment.CreateAsync(null, dataDir, null);
                await web.EnsureCoreWebView2Async(env);
                web.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
                web.CoreWebView2.Settings.AreDevToolsEnabled = false;
                web.CoreWebView2.Settings.IsStatusBarEnabled = false;
                web.CoreWebView2.WebMessageReceived += OnWebMessage;
                web.CoreWebView2.NavigationCompleted += (s, args) =>
                {
                    if (!args.IsSuccess) return;
                    try
                    {
                        Dictionary<string, object> defaults = new Dictionary<string, object>();
                        defaults["action"] = "defaults";
                        defaults["installPath"] = installPath;
                        defaults["portablePath"] = portablePath;
                        web.CoreWebView2.PostWebMessageAsJson(json.Serialize(defaults));
                    }
                    catch { }
                };
                string htmlPath = Path.Combine(dataDir, "installer_ui.html");
                File.WriteAllText(htmlPath, html, new UTF8Encoding(false));
                web.Source = new Uri(htmlPath);
            }
            catch (Exception ex)
            {
                try
                {
                    string errDir = Path.Combine(Path.GetTempPath(), "RaspoznavatelSetup");
                    Directory.CreateDirectory(errDir);
                    File.WriteAllText(Path.Combine(errDir, "shell_error.txt"), ex.ToString());
                }
                catch { }
                MessageBox.Show(ex.Message, "Распознаватель", MessageBoxButtons.OK, MessageBoxIcon.Error);
                Close();
            }
        }

        void OnWebMessage(object sender, CoreWebView2WebMessageReceivedEventArgs e)
        {
            Dictionary<string, object> msg;
            try
            {
                msg = json.Deserialize<Dictionary<string, object>>(e.WebMessageAsJson);
            }
            catch
            {
                return;
            }
            string action = msg.ContainsKey("action") ? Convert.ToString(msg["action"]) : "";
            RunLog.Write("message " + action);
            if (action == "next" && !busy)
            {
                mode = msg.ContainsKey("mode") ? Convert.ToString(msg["mode"]) : "install";
                if (mode != "portable") mode = "install";
                if (msg.ContainsKey("path"))
                {
                    string selected = Convert.ToString(msg["path"]);
                    if (!string.IsNullOrWhiteSpace(selected))
                    {
                        selected = selected.Trim().Trim('"');
                        try { selected = Path.GetFullPath(selected); }
                        catch { }
                        if (mode == "portable") portablePath = selected;
                        else installPath = selected;
                    }
                }
                cancelRequested = false;
                busy = true;
                progress = 4;
                SendProgress(progress, mode == "portable" ? "Подготавливаю распаковку…" : "Подготавливаю установку…");
                progressTimer.Start();
                Task.Run(() => RunBackend());
            }
            else if (action == "browse")
            {
                using (FolderBrowserDialog dialog = new FolderBrowserDialog())
                {
                    dialog.Description = "Выберите папку для установки";
                    dialog.ShowNewFolderButton = true;
                    string current = msg.ContainsKey("path") ? Convert.ToString(msg["path"]) : installPath;
                    if (!string.IsNullOrWhiteSpace(current))
                        dialog.SelectedPath = current.Trim().Trim('"');
                    if (dialog.ShowDialog(this) == DialogResult.OK)
                    {
                        installPath = dialog.SelectedPath;
                        Dictionary<string, object> reply = new Dictionary<string, object>();
                        reply["action"] = "path";
                        reply["path"] = installPath;
                        web.CoreWebView2.PostWebMessageAsJson(json.Serialize(reply));
                    }
                }
            }
            else if (action == "close" || action == "cancel")
            {
                if (busy) CancelBackend();
                else Close();
            }
            else if (action == "minimize")
            {
                WindowState = FormWindowState.Minimized;
            }
            else if (action == "maximize")
            {
                WindowState = WindowState == FormWindowState.Maximized ? FormWindowState.Normal : FormWindowState.Maximized;
            }
            else if (action == "drag")
            {
                ReleaseCapture();
                SendMessage(Handle, WM_NCLBUTTONDOWN, (IntPtr)HTCAPTION, IntPtr.Zero);
            }
            else if (action == "run")
            {
                if (!string.IsNullOrEmpty(appPath) && File.Exists(appPath))
                    Process.Start(appPath);
                Close();
            }
        }

        void CancelBackend()
        {
            cancelRequested = true;
            try
            {
                if (backendProcess != null && !backendProcess.HasExited)
                    backendProcess.Kill();
            }
            catch { }
            busy = false;
            Close();
        }

        bool IsProtectedInstallPath(string path)
        {
            try
            {
                string full = Path.GetFullPath(path).TrimEnd('\\');
                string[] roots = new string[]
                {
                    Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                    Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
                    Environment.GetFolderPath(Environment.SpecialFolder.Windows)
                };
                foreach (string root in roots)
                {
                    if (string.IsNullOrWhiteSpace(root)) continue;
                    string normalized = Path.GetFullPath(root).TrimEnd('\\');
                    if (full.Equals(normalized, StringComparison.OrdinalIgnoreCase) ||
                        full.StartsWith(normalized + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                        return true;
                }
            }
            catch { }
            return false;
        }

        void RunBackend()
        {
            try
            {
                string setupDir = Path.GetDirectoryName(Application.ExecutablePath);
                string target = mode == "portable" ? portablePath : installPath;
                appPath = Path.Combine(target, "Raspoznavatel.exe");

                string backend = ExtractBackend();
                string args = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART";
                if (mode == "portable")
                    args += " /PORTABLE /TARGET=\"" + target + "\"";
                else
                    args += " /DIR=\"" + target + "\"";

                if (cancelRequested) return;

                bool needsElevation = mode != "portable" && IsProtectedInstallPath(target);
                ProcessStartInfo psi = new ProcessStartInfo(backend, args);
                psi.UseShellExecute = needsElevation;
                psi.CreateNoWindow = !needsElevation;
                if (needsElevation)
                    psi.Verb = "runas";
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                psi.WorkingDirectory = Path.GetDirectoryName(backend);
                RunLog.Write("backend start " + args);
                using (Process p = Process.Start(psi))
                {
                    backendProcess = p;
                    bool exited = p.WaitForExit(180000);
                    if (cancelRequested) return;
                    int code = exited ? p.ExitCode : -1;
                    RunLog.Write("backend exit " + exited + " code " + code);
                    if (!exited)
                        throw new Exception("Установщик не завершился за 3 минуты.");
                    if (code != 0)
                        throw new Exception("Установщик завершился с кодом " + code + ".");
                }

                // Сначала гасим таймер, иначе его последний тик может
                // перерисовать экран прогресса уже после экрана «Готово».
                busy = false;
                try { if (progressTimer != null) progressTimer.Stop(); } catch { }

                SendProgress(100, "Готово.");
                SendScript("window.rspDone(" + json.Serialize(mode) + "," +
                           json.Serialize(target) + "," + json.Serialize(appPath) + ");");
                RunLog.Write("rspDone sent");
                try { File.Delete(backend); } catch { }
            }
            catch (Exception ex)
            {
                RunLog.Write("ERROR " + ex);
                SendScript("window.rspError(" + json.Serialize(ex.Message) + ");");
            }
            finally
            {
                backendProcess = null;
                busy = false;
                if (progressTimer != null)
                    progressTimer.Stop();
            }
        }

        string ExtractBackend()
        {
            string self = Application.ExecutablePath;
            using (FileStream fs = new FileStream(self, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (fs.Length < 24)
                    throw new Exception("В установщике нет встроенного Inno-модуля.");
                fs.Seek(-24, SeekOrigin.End);
                byte[] footer = new byte[24];
                fs.Read(footer, 0, footer.Length);
                string magic = Encoding.ASCII.GetString(footer, 0, 8);
                if (magic != "RSPINNO1")
                    throw new Exception("Не найден модуль установки.");
                long offset = BitConverter.ToInt64(footer, 8);
                long length = BitConverter.ToInt64(footer, 16);
                if (offset <= 0 || length <= 0 || offset + length > fs.Length)
                    throw new Exception("Повреждён встроенный модуль установки.");

                string dir = Path.Combine(Path.GetTempPath(), "RaspoznavatelSetup");
                Directory.CreateDirectory(dir);
                string path = Path.Combine(dir, "Raspoznavatel-backend.exe");
                if (File.Exists(path) && new FileInfo(path).Length == length)
                    return path;

                fs.Seek(offset, SeekOrigin.Begin);
                using (FileStream output = File.Create(path))
                {
                    byte[] buffer = new byte[1024 * 1024];
                    long left = length;
                    while (left > 0)
                    {
                        int want = (int)Math.Min(buffer.Length, left);
                        int read = fs.Read(buffer, 0, want);
                        if (read <= 0) break;
                        output.Write(buffer, 0, read);
                        left -= read;
                    }
                }
                return path;
            }
        }

        void SendProgress(int pct, string text)
        {
            SendScript("window.rspProgress(" + pct.ToString(CultureInfo.InvariantCulture) + "," +
                       json.Serialize(text) + ");");
        }

        void SendScript(string script)
        {
            if (web == null) return;
            try
            {
                if (web.InvokeRequired)
                {
                    web.BeginInvoke(new Action(() => SendScript(script)));
                    return;
                }
                if (web.CoreWebView2 == null) return;
                web.ExecuteScriptAsync(script);
            }
            catch { }
        }
    }
}
