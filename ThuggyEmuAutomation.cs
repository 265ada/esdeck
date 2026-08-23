// ThuggyEmuAutomation - a Windows application for esdeck.
//
// Everything runs inside this window: no console windows appear, and output is
// streamed into the app as it happens. That is deliberate - a stray console
// window is one careless click away from being closed mid-sort, whereas this
// asks before it will close while work is running.
//
// Built with csc.exe, which ships with Windows, so there is no toolchain to
// install. The wallpaper and icon are compiled in, so the .exe needs nothing
// beside it.
//
// Build:  build-exe.bat

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace ThuggyEmuAutomation
{
    public class MainForm : Form
    {
        private const int W = 760, H = 620;

        private Label titleLabel, versionLabel, statusLabel, runningLabel;
        private Panel menuPanel, outputPanel;
        private TextBox output;
        private Button cancelButton, backButton;
        private string appDir;
        private bool hasBackground;

        private Process current;                 // the step running right now
        private Thread worker;
        private volatile bool cancelled;
        private volatile bool busy;

        public MainForm()
        {
            appDir = AppDomain.CurrentDomain.BaseDirectory;

            Text = "ThuggyEmuAutomation";
            ClientSize = new Size(W, H);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.FromArgb(24, 28, 40);
            Font = new Font("Segoe UI", 9.75f);
            DoubleBuffered = true;
            LoadBackground();

            titleLabel = new Label();
            titleLabel.Text = "ThuggyEmuAutomation";
            titleLabel.Font = new Font("Segoe UI", 16f, FontStyle.Bold);
            titleLabel.ForeColor = Color.White;
            titleLabel.BackColor = Color.Transparent;
            titleLabel.SetBounds(24, 16, 500, 34);
            Controls.Add(titleLabel);

            versionLabel = new Label();
            versionLabel.ForeColor = Color.FromArgb(186, 198, 216);
            versionLabel.BackColor = Color.Transparent;
            versionLabel.SetBounds(26, 50, 700, 18);
            Controls.Add(versionLabel);

            BuildMenu();
            BuildOutput();

            statusLabel = new Label();
            statusLabel.ForeColor = Color.FromArgb(186, 198, 216);
            statusLabel.BackColor = Color.Transparent;
            statusLabel.SetBounds(26, H - 34, 700, 22);
            Controls.Add(statusLabel);

            FormClosing += OnFormClosing;
            Shown += OnShown;
        }

        // ------------------------------------------------------------ layout

        private void BuildMenu()
        {
            menuPanel = new Panel();
            menuPanel.SetBounds(0, 78, W, H - 118);
            menuPanel.BackColor = Color.Transparent;
            Controls.Add(menuPanel);

            int y = 4;
            AddAction("Set up this PC",
                      "Installs ES-DE, RetroArch, every core, and the folders", ref y,
                      delegate { Run("Setting up this PC", SetupSteps()); });
            AddAction("Sort games",
                      "Files everything in your Incoming folder into the library", ref y,
                      delegate
                      {
                          Run("Sorting games", new string[] {
                              "tidy --yes", "sync --yes" });
                      });
            AddAction("Fix library",
                      "Removes artwork filed as games and makes the pad player 1", ref y,
                      delegate
                      {
                          Run("Fixing the library", new string[] {
                              "cleanup --yes", "controller --yes", "tidy --yes", "doctor" });
                      });
            AddAction("Undo the last sort",
                      "Removes what the last sort added. Originals are untouched", ref y,
                      OnUndo);
            AddAction("Check for problems",
                      "Reports anything needing attention, including missing BIOS", ref y,
                      delegate { Run("Checking", new string[] { "doctor", "bios" }); });
            AddAction("Free up space",
                      "Deletes Incoming copies verified as already in the library", ref y,
                      OnFreeSpace);

            int by = y + 8;
            AddSmall("Change icon", 24, by, OnIcon);
            AddSmall("Change background", 186, by, OnBackground);
            AddSmall("Open games folder", 372, by, OnOpenFolder);
            AddSmall("Check for updates", 558, by, OnUpdate);
        }

        private void AddAction(string text, string hint, ref int y, EventHandler onClick)
        {
            Button b = new Button();
            b.Text = "    " + text;
            b.TextAlign = ContentAlignment.MiddleLeft;
            b.SetBounds(24, y, W - 48, 36);
            b.FlatStyle = FlatStyle.Flat;
            b.FlatAppearance.BorderSize = 1;
            b.FlatAppearance.BorderColor = Color.FromArgb(78, 92, 120);
            b.BackColor = Color.FromArgb(42, 50, 70);
            b.ForeColor = Color.White;
            b.Font = new Font("Segoe UI", 10.5f, FontStyle.Bold);
            b.Cursor = Cursors.Hand;
            b.Click += onClick;
            menuPanel.Controls.Add(b);

            Label l = new Label();
            l.Text = "         " + hint;
            l.ForeColor = Color.FromArgb(178, 190, 210);
            l.BackColor = Color.Transparent;
            l.Font = new Font("Segoe UI", 8.25f);
            l.SetBounds(24, y + 37, W - 48, 16);
            menuPanel.Controls.Add(l);

            y += 60;
        }

        private void AddSmall(string text, int x, int y, EventHandler onClick)
        {
            Button b = new Button();
            b.Text = text;
            b.SetBounds(x, y, 162, 30);
            b.FlatStyle = FlatStyle.Flat;
            b.FlatAppearance.BorderSize = 1;
            b.FlatAppearance.BorderColor = Color.FromArgb(70, 84, 110);
            b.BackColor = Color.FromArgb(34, 41, 58);
            b.ForeColor = Color.White;
            b.Cursor = Cursors.Hand;
            b.Click += onClick;
            menuPanel.Controls.Add(b);
        }

        private void BuildOutput()
        {
            outputPanel = new Panel();
            outputPanel.SetBounds(0, 78, W, H - 118);
            outputPanel.BackColor = Color.Transparent;
            outputPanel.Visible = false;
            Controls.Add(outputPanel);

            runningLabel = new Label();
            runningLabel.ForeColor = Color.White;
            runningLabel.BackColor = Color.Transparent;
            runningLabel.Font = new Font("Segoe UI", 11f, FontStyle.Bold);
            runningLabel.SetBounds(24, 2, W - 48, 24);
            outputPanel.Controls.Add(runningLabel);

            output = new TextBox();
            output.Multiline = true;
            output.ReadOnly = true;
            output.ScrollBars = ScrollBars.Vertical;
            output.WordWrap = false;
            output.BackColor = Color.FromArgb(14, 17, 26);
            output.ForeColor = Color.FromArgb(214, 226, 240);
            output.Font = new Font("Consolas", 9f);
            output.BorderStyle = BorderStyle.FixedSingle;
            output.SetBounds(24, 30, W - 48, H - 200);
            outputPanel.Controls.Add(output);

            cancelButton = new Button();
            cancelButton.Text = "Stop";
            cancelButton.SetBounds(24, H - 164, 150, 32);
            StyleSmall(cancelButton);
            cancelButton.Click += OnCancel;
            outputPanel.Controls.Add(cancelButton);

            backButton = new Button();
            backButton.Text = "Back to menu";
            backButton.SetBounds(186, H - 164, 150, 32);
            StyleSmall(backButton);
            backButton.Enabled = false;
            backButton.Click += delegate { ShowMenu(); };
            outputPanel.Controls.Add(backButton);
        }

        private void StyleSmall(Button b)
        {
            b.FlatStyle = FlatStyle.Flat;
            b.FlatAppearance.BorderSize = 1;
            b.FlatAppearance.BorderColor = Color.FromArgb(70, 84, 110);
            b.BackColor = Color.FromArgb(34, 41, 58);
            b.ForeColor = Color.White;
            b.Cursor = Cursors.Hand;
        }

        // -------------------------------------------------------- background

        private void LoadBackground()
        {
            string[] names = { "background.png", "background.jpg", "background.jpeg",
                               "background.bmp" };
            foreach (string name in names)
            {
                string path = Path.Combine(Path.Combine(appDir, "assets"), name);
                if (!File.Exists(path)) continue;
                try
                {
                    using (FileStream fs = new FileStream(path, FileMode.Open,
                                                          FileAccess.Read))
                        BackgroundImage = Image.FromStream(fs);
                    BackgroundImageLayout = ImageLayout.Zoom;
                    hasBackground = true;
                    return;
                }
                catch { }
            }
            try
            {
                using (Stream st = System.Reflection.Assembly.GetExecutingAssembly()
                        .GetManifestResourceStream("background.jpg"))
                {
                    if (st != null)
                    {
                        BackgroundImage = Image.FromStream(st);
                        BackgroundImageLayout = ImageLayout.Zoom;
                        hasBackground = true;
                    }
                }
            }
            catch { }
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            base.OnPaintBackground(e);
            if (!hasBackground) return;
            // Artwork interesting enough to look at is too busy to read over.
            using (SolidBrush scrim = new SolidBrush(Color.FromArgb(214, 16, 20, 30)))
                e.Graphics.FillRectangle(scrim, 0, 72, ClientSize.Width,
                                         ClientSize.Height - 72);
            using (SolidBrush top = new SolidBrush(Color.FromArgb(150, 16, 20, 30)))
                e.Graphics.FillRectangle(top, 0, 0, ClientSize.Width, 72);
        }

        // ------------------------------------------------------------ esdeck

        private string Python()
        {
            foreach (string candidate in new string[] { "python", "py" })
            {
                try
                {
                    ProcessStartInfo psi = new ProcessStartInfo(candidate, "--version");
                    psi.UseShellExecute = false;
                    psi.CreateNoWindow = true;
                    psi.RedirectStandardOutput = true;
                    Process p = Process.Start(psi);
                    p.WaitForExit(4000);
                    if (p.ExitCode == 0) return candidate;
                }
                catch { }
            }
            return null;
        }

        private string RunAndRead(string arguments)
        {
            string py = Python();
            if (py == null) return null;
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo(py, "-m esdeck " + arguments);
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.RedirectStandardOutput = true;
                psi.WorkingDirectory = appDir;
                Process p = Process.Start(psi);
                string text = p.StandardOutput.ReadToEnd();
                p.WaitForExit(20000);
                return text.Trim();
            }
            catch { return null; }
        }

        private string[] SetupSteps()
        {
            List<string> steps = new List<string>();
            steps.Add("bootstrap --yes");
            steps.Add("link --yes --create");
            steps.Add("cores --all --yes");
            steps.Add("emulators --apply --yes");
            steps.Add("doctor");
            return steps.ToArray();
        }

        // -------------------------------------------------------- running it

        private void ShowMenu()
        {
            outputPanel.Visible = false;
            menuPanel.Visible = true;
            RefreshStatus();
        }

        private void ShowOutput(string what)
        {
            menuPanel.Visible = false;
            outputPanel.Visible = true;
            runningLabel.Text = what;
            output.Clear();
            cancelButton.Enabled = true;
            backButton.Enabled = false;
        }

        private void Append(string line)
        {
            if (output.InvokeRequired)
            {
                output.BeginInvoke((MethodInvoker)delegate { Append(line); });
                return;
            }
            output.AppendText(line + "\r\n");
        }

        /// <summary>Run esdeck commands one after another, output shown here.</summary>
        private void Run(string what, string[] steps)
        {
            if (busy) return;
            string py = Python();
            if (py == null) { NoPython(); return; }

            ShowOutput(what);
            busy = true;
            cancelled = false;

            worker = new Thread(delegate ()
            {
                foreach (string step in steps)
                {
                    if (cancelled) break;
                    Append("> esdeck " + step);
                    int code = RunStep(py, step);
                    if (cancelled)
                    {
                        Append("");
                        Append("Stopped. Nothing further was run.");
                        break;
                    }
                    if (code != 0)
                        Append("(finished with status " + code + ")");
                    Append("");
                }
                Finished();
            });
            worker.IsBackground = true;
            worker.Start();
        }

        private int RunStep(string py, string step)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo(py, "-u -m esdeck " + step);
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                psi.StandardOutputEncoding = Encoding.UTF8;
                psi.StandardErrorEncoding = Encoding.UTF8;
                psi.WorkingDirectory = appDir;

                current = new Process();
                current.StartInfo = psi;
                current.OutputDataReceived += delegate (object s, DataReceivedEventArgs e)
                {
                    if (e.Data != null) Append(e.Data);
                };
                current.ErrorDataReceived += delegate (object s, DataReceivedEventArgs e)
                {
                    if (e.Data != null) Append(e.Data);
                };
                current.Start();
                current.BeginOutputReadLine();
                current.BeginErrorReadLine();
                current.WaitForExit();
                int code = current.ExitCode;
                current = null;
                return code;
            }
            catch (Exception ex)
            {
                Append("Could not run that step: " + ex.Message);
                return -1;
            }
        }

        private void Finished()
        {
            if (InvokeRequired)
            {
                BeginInvoke((MethodInvoker)delegate { Finished(); });
                return;
            }
            busy = false;
            cancelButton.Enabled = false;
            backButton.Enabled = true;
            runningLabel.Text = cancelled ? "Stopped" : "Finished";
            RefreshStatus();
        }

        private void OnCancel(object sender, EventArgs e)
        {
            if (!busy) return;
            if (MessageBox.Show(
                    "Stop what is running?\r\n\r\n" +
                    "Files already copied stay where they are. Nothing is deleted, " +
                    "and you can run it again to carry on.",
                    "Stop", MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question) != DialogResult.Yes)
                return;
            cancelled = true;
            try
            {
                Process p = current;
                if (p != null && !p.HasExited) p.Kill();
            }
            catch { }
        }

        // ------------------------------------------------------------ events

        private void OnFormClosing(object sender, FormClosingEventArgs e)
        {
            if (!busy) return;
            // The whole point of running in-app: a stray console window is one
            // careless click from being closed mid-sort. This asks first.
            DialogResult answer = MessageBox.Show(
                runningLabel.Text + " is still running.\r\n\r\n" +
                "Close anyway and stop it?\r\n\r\n" +
                "Files already copied stay where they are - nothing is deleted.",
                "Still running", MessageBoxButtons.YesNo,
                MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2);
            if (answer != DialogResult.Yes)
            {
                e.Cancel = true;
                return;
            }
            cancelled = true;
            try
            {
                Process p = current;
                if (p != null && !p.HasExited) p.Kill();
            }
            catch { }
        }

        private void OnShown(object sender, EventArgs e) { RefreshStatus(); }

        private void RefreshStatus()
        {
            string version = RunAndRead("--version");
            versionLabel.Text = version == null
                ? "esdeck is not installed yet - start with \"Set up this PC\""
                : version;
            string folder = RunAndRead("drives --current");
            statusLabel.Text = string.IsNullOrEmpty(folder)
                ? "No games folder configured yet."
                : "Games folder:  " + folder;
        }

        private void NoPython()
        {
            MessageBox.Show(
                "Python is not installed yet.\r\n\r\n" +
                "Run esdeck.bat from the folder you extracted, which installs " +
                "Python and esdeck. After that everything works from here.",
                "Not set up", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }

        private void OnUndo(object sender, EventArgs e)
        {
            if (MessageBox.Show(
                    "Undo the most recent sort?\r\n\r\n" +
                    "This removes only what that sort put in your library. " +
                    "Your original files are not touched.",
                    "Undo", MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question) != DialogResult.Yes) return;
            Run("Undoing the last sort", new string[] { "undo --yes" });
        }

        private void OnFreeSpace(object sender, EventArgs e)
        {
            if (MessageBox.Show(
                    "Delete the copies in your Incoming folder?\r\n\r\n" +
                    "Only files verified byte-for-byte against your library are " +
                    "removed. Anything that does not match is kept.\r\n\r\n" +
                    "Your library is not touched.",
                    "Free up space", MessageBoxButtons.YesNo,
                    MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2)
                != DialogResult.Yes) return;
            Run("Freeing up space", new string[] { "clean --yes" });
        }

        private void OnIcon(object sender, EventArgs e)
        {
            OpenFileDialog dlg = new OpenFileDialog();
            dlg.Title = "Choose a square picture for the icon";
            dlg.Filter = "PNG images (*.png)|*.png";
            if (dlg.ShowDialog() != DialogResult.OK) return;
            Run("Setting the icon", new string[] {
                "icon \"" + dlg.FileName + "\" --shortcut \"" +
                Path.Combine(appDir, "ThuggyEmuAutomation.exe") + "\"" });
        }

        private void OnBackground(object sender, EventArgs e)
        {
            OpenFileDialog dlg = new OpenFileDialog();
            dlg.Title = "Choose a background picture";
            dlg.Filter = "Images (*.png;*.jpg;*.jpeg;*.bmp)|*.png;*.jpg;*.jpeg;*.bmp";
            if (dlg.ShowDialog() != DialogResult.OK) return;
            try
            {
                string assets = Path.Combine(appDir, "assets");
                Directory.CreateDirectory(assets);
                foreach (string old in Directory.GetFiles(assets, "background.*"))
                    File.Delete(old);
                File.Copy(dlg.FileName,
                          Path.Combine(assets, "background" +
                                       Path.GetExtension(dlg.FileName).ToLowerInvariant()),
                          true);
                if (BackgroundImage != null)
                {
                    BackgroundImage.Dispose();
                    BackgroundImage = null;
                }
                hasBackground = false;
                LoadBackground();
                Invalidate();
            }
            catch (Exception ex)
            {
                MessageBox.Show("Could not use that picture:\r\n" + ex.Message,
                                "Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void OnOpenFolder(object sender, EventArgs e)
        {
            string folder = RunAndRead("drives --current");
            if (string.IsNullOrEmpty(folder) || !Directory.Exists(folder))
            {
                MessageBox.Show("No games folder yet - run \"Set up this PC\" first.",
                                "Nothing to open", MessageBoxButtons.OK,
                                MessageBoxIcon.Information);
                return;
            }
            Process.Start("explorer.exe", "\"" + folder + "\"");
        }

        private void OnUpdate(object sender, EventArgs e)
        {
            Run("Checking for updates", new string[] {
                "update --yes --bat-dir \"" + appDir.TrimEnd('\\') + "\"" });
        }

        [STAThread]
        public static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
        }
    }
}
