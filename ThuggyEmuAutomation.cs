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
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace ThuggyEmuAutomation
{
    /// <summary>Windows keeps per-process I/O totals; the difference between
    /// two readings is the throughput. Reading them from the step actually
    /// doing the work is exact, where scraping numbers out of its output is
    /// guesswork that breaks the moment the wording changes.</summary>
    internal struct IoCounters
    {
        public ulong Reads, Writes, Others, ReadBytes, WriteBytes, OtherBytes;
    }

    public class MainForm : Form
    {
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetProcessIoCounters(IntPtr handle,
                                                        out IoCounters counters);

        private const int W = 760, H = 620;

        private Label titleLabel, versionLabel, statusLabel, runningLabel;
        private Panel menuPanel, outputPanel;
        private TextBox output;
        private Button cancelButton, backButton;
        private string appDir;
        private bool hasBackground;
        private Image backdrop;

        private delegate void DoneHandler(int lastCode);
        private DoneHandler onDone;              // runs on the UI thread after a job
        private int lastCode;

        private Label activityLabel;
        private ProgressBar activityBar;
        private System.Windows.Forms.Timer activityTimer;
        private DateTime startedAt;
        private ulong lastRead, lastWrite;
        private DateTime lastSampled;
        private int tickCount;
        private volatile string stage;
        private double readRate, writeRate;

        private readonly List<string> pending = new List<string>();
        private int written;
        private const int MaxLines = 4000;
        private const int MaxPerFlush = 500;

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
            LoadIcon();

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
                      "Installs ES-DE, RetroArch, every core and the folders. "
                      + "Safe to run again to fix an older setup", ref y,
                      OnSetup);
            AddAction("Sort games",
                      "Files everything in your Incoming folder into the library", ref y,
                      delegate
                      {
                          if (!ReadyOrOfferSetup("sorting games")) return;
                          Run("Sort games", new string[] {
                              "tidy --yes", "sync --yes" });
                      });
            AddAction("Fix library",
                      "Removes artwork filed as games and makes the pad player 1", ref y,
                      delegate
                      {
                          if (!ReadyOrOfferSetup("fixing the library")) return;
                          Run("Fix library", new string[] {
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
            AddSmall("Change background", 164, by, OnBackground);
            AddSmall("Open games folder", 304, by, OnOpenFolder);
            AddSmall("Export logs", 444, by, OnExportLogs);
            AddSmall("Check for updates", 584, by, OnUpdate);
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
            b.SetBounds(x, y, 128, 30);
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
            output.SetBounds(24, 30, W - 48, H - 244);
            outputPanel.Controls.Add(output);

            // The activity strip. It is driven by the operating system's own
            // I/O counters for the step that is running, not by reading the
            // text above it, so it keeps telling the truth during the long
            // silences - hashing one huge file, or waiting on 7-Zip - when
            // there is no output at all to go on.
            activityLabel = new Label();
            activityLabel.ForeColor = Color.FromArgb(150, 210, 175);
            activityLabel.BackColor = Color.Transparent;
            activityLabel.Font = new Font("Consolas", 8.5f);
            activityLabel.SetBounds(24, H - 208, W - 48, 18);
            outputPanel.Controls.Add(activityLabel);

            activityBar = new ProgressBar();
            activityBar.SetBounds(24, H - 188, W - 48, 8);
            activityBar.Maximum = 1000;
            outputPanel.Controls.Add(activityBar);

            activityTimer = new System.Windows.Forms.Timer();
            activityTimer.Interval = 250;
            activityTimer.Tick += OnActivityTick;

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

        // -------------------------------------------------------------- icon

        private void LoadIcon()
        {
            // The compiled-in copy first, so a moved .exe keeps its Snorlax.
            try
            {
                using (Stream st = System.Reflection.Assembly.GetExecutingAssembly()
                        .GetManifestResourceStream("appicon.ico"))
                    if (st != null) { Icon = new Icon(st); return; }
            }
            catch { }
            try
            {
                string path = Path.Combine(Path.Combine(appDir, "assets"),
                                           "ThuggyEmuAutomation.ico");
                if (File.Exists(path)) { Icon = new Icon(path); return; }
            }
            catch { }
            // Last resort: build an icon from the artwork itself, which works
            // whatever shape the .ico happens to be in.
            try
            {
                string png = Path.Combine(Path.Combine(appDir, "assets"),
                                          "ThuggyEmuAutomation.png");
                if (File.Exists(png))
                    using (Bitmap bmp = new Bitmap(png))
                        Icon = Icon.FromHandle(bmp.GetHicon());
            }
            catch { }
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
                        backdrop = Image.FromStream(fs);
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
                        backdrop = Image.FromStream(st);
                        hasBackground = true;
                    }
                }
            }
            catch { }
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            base.OnPaintBackground(e);
            if (!hasBackground || backdrop == null) return;

            // Cover, not fit. The poster is tall and the window is not, so
            // fitting it inside leaves it as a narrow strip down the middle
            // with dead space either side. Scale to cover and crop the
            // overflow, which is what a wallpaper is expected to do.
            float sx = (float)ClientSize.Width / backdrop.Width;
            float sy = (float)ClientSize.Height / backdrop.Height;
            float scale = sx > sy ? sx : sy;
            int w = (int)Math.Ceiling(backdrop.Width * scale);
            int h = (int)Math.Ceiling(backdrop.Height * scale);
            e.Graphics.DrawImage(backdrop, (ClientSize.Width - w) / 2,
                                 (ClientSize.Height - h) / 2, w, h);

            // Artwork interesting enough to look at is too busy to read over.
            using (SolidBrush scrim = new SolidBrush(Color.FromArgb(214, 16, 20, 30)))
                e.Graphics.FillRectangle(scrim, 0, 72, ClientSize.Width,
                                         ClientSize.Height - 72);
            using (SolidBrush top = new SolidBrush(Color.FromArgb(150, 16, 20, 30)))
                e.Graphics.FillRectangle(top, 0, 0, ClientSize.Width, 72);
        }

        // ------------------------------------------------------------ esdeck

        /// <summary>Find a usable Python.
        ///
        /// PATH alone is not enough on a machine being set up for the first
        /// time. Two things get in the way. Windows 11 ships a stub at
        /// python.exe that only opens the Microsoft Store, so a name being
        /// found says nothing about it working. And a Python installed a
        /// moment ago by winget is not on this process's PATH, which was
        /// captured when the application started - so the install appears to
        /// have failed when it plainly succeeded.
        ///
        /// So: try the names, then look where installers actually put it.
        /// </summary>
        private string Python()
        {
            foreach (string candidate in new string[] { "python", "py" })
                if (PythonWorks(candidate)) return candidate;

            foreach (string path in LikelyPythons())
                if (PythonWorks(path)) return path;

            return null;
        }

        private bool PythonWorks(string exe)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo(exe, "--version");
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                Process p = Process.Start(psi);
                string said = p.StandardOutput.ReadToEnd() + p.StandardError.ReadToEnd();
                p.WaitForExit(8000);
                // The Store stub exits non-zero and says nothing useful; a real
                // Python prints its version. Insist on hearing the version.
                return p.ExitCode == 0 && said.IndexOf("Python 3") >= 0;
            }
            catch { return false; }
        }

        /// <summary>Where Windows installers actually leave python.exe.</summary>
        private List<string> LikelyPythons()
        {
            List<string> found = new List<string>();
            string local = Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData);
            List<string> roots = new List<string>();
            roots.Add(Path.Combine(local, "Programs\\Python"));   // python.org
            roots.Add(Path.Combine(local, "Python"));             // install manager
            roots.Add(Environment.GetFolderPath(
                Environment.SpecialFolder.ProgramFiles));
            // SpecialFolder.ProgramFilesX86 is not in the .NET 2.0 enum the
            // shipped compiler references; the variable is always set.
            string x86 = Environment.GetEnvironmentVariable("ProgramFiles(x86)");
            if (!string.IsNullOrEmpty(x86)) roots.Add(x86);

            foreach (string root in roots)
            {
                try
                {
                    if (!Directory.Exists(root)) continue;
                    foreach (string dir in Directory.GetDirectories(root))
                    {
                        string name = Path.GetFileName(dir).ToLowerInvariant();
                        // "Python312", and "pythoncore-3.14-64" from the newer
                        // Python install manager.
                        if (!name.StartsWith("python")) continue;
                        string exe = Path.Combine(dir, "python.exe");
                        if (File.Exists(exe)) found.Add(exe);
                    }
                }
                catch { }
            }
            // Newest last-installed first: the names sort usefully enough.
            found.Sort();
            found.Reverse();
            return found;
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
                // Without this, Python puts the working directory first on the
                // import path. A copy of the source sitting beside the .exe -
                // a downloaded repo, say - would then shadow the installed
                // package, so updates appeared to do nothing at all.
                psi.EnvironmentVariables["PYTHONSAFEPATH"] = "1";
                Process p = Process.Start(psi);
                string text = p.StandardOutput.ReadToEnd();
                p.WaitForExit(20000);
                return text.Trim();
            }
            catch { return null; }
        }

        // -------------------------------------------------- setting up a PC

        /// <summary>Ask which drive the games should live on.
        ///
        /// It has to be asked somewhere. A collection is hundreds of gigabytes
        /// and the right drive is a decision only the person in front of the
        /// machine can make - but it is one question with a sensible default,
        /// not an interrogation, and everything after it is automatic.
        /// </summary>
        private string ChooseDrive()
        {
            List<DriveInfo> usable = new List<DriveInfo>();
            try
            {
                foreach (DriveInfo d in DriveInfo.GetDrives())
                {
                    try
                    {
                        // Fixed and removable both: an external drive is a
                        // perfectly ordinary place to keep a collection this
                        // size, and excluding it would hide the very drive
                        // someone bought for the job. Network drives are left
                        // out - a library over the network is its own problem.
                        if (d.IsReady && (d.DriveType == DriveType.Fixed
                                          || d.DriveType == DriveType.Removable))
                            usable.Add(d);
                    }
                    catch { }
                }
            }
            catch { }
            if (usable.Count == 0) return null;

            // Default to the roomiest drive: that is what a large collection
            // needs, and it is right far more often than "wherever Windows is".
            DriveInfo best = null;
            foreach (DriveInfo d in usable)
            {
                if (d.DriveType != DriveType.Fixed) continue;
                if (best == null || d.AvailableFreeSpace > best.AvailableFreeSpace)
                    best = d;
            }
            // Only fall back to a removable drive if there is nothing else: it
            // can be unplugged, and a library that disappears is worse than a
            // smaller one that stays put. It is still offered - just not
            // chosen on someone's behalf.
            if (best == null)
            {
                best = usable[0];
                foreach (DriveInfo d in usable)
                    if (d.AvailableFreeSpace > best.AvailableFreeSpace) best = d;
            }

            Form dlg = new Form();
            dlg.Text = "Where should your games live?";
            dlg.ClientSize = new Size(460, 260);
            dlg.FormBorderStyle = FormBorderStyle.FixedDialog;
            dlg.StartPosition = FormStartPosition.CenterParent;
            dlg.MinimizeBox = false;
            dlg.MaximizeBox = false;
            dlg.BackColor = Color.FromArgb(28, 33, 47);
            dlg.ForeColor = Color.White;
            dlg.Font = Font;

            Label intro = new Label();
            intro.Text = "Pick the drive with room for your collection. A games "
                + "folder and a drop folder are created there.";
            intro.SetBounds(16, 12, 428, 40);
            dlg.Controls.Add(intro);

            ListBox list = new ListBox();
            list.SetBounds(16, 58, 428, 130);
            list.BackColor = Color.FromArgb(18, 22, 33);
            list.ForeColor = Color.White;
            list.BorderStyle = BorderStyle.FixedSingle;
            foreach (DriveInfo d in usable)
            {
                double freeGb = d.AvailableFreeSpace / 1073741824.0;
                double totalGb = d.TotalSize / 1073741824.0;
                string label = d.Name + "   " + freeGb.ToString("0") + " GB free of "
                             + totalGb.ToString("0") + " GB";
                try
                {
                    if (!string.IsNullOrEmpty(d.VolumeLabel))
                        label += "   " + d.VolumeLabel;
                }
                catch { }
                if (d.DriveType == DriveType.Removable) label += "   (removable)";
                if (d.Name == best.Name) label += "      (most room)";
                list.Items.Add(label);
                if (d.Name == best.Name) list.SelectedIndex = list.Items.Count - 1;
            }
            dlg.Controls.Add(list);

            Button ok = new Button();
            ok.Text = "Use this drive";
            ok.SetBounds(240, 200, 130, 32);
            ok.DialogResult = DialogResult.OK;
            StyleSmall(ok);
            dlg.Controls.Add(ok);

            Button cancel = new Button();
            cancel.Text = "Cancel";
            cancel.SetBounds(380, 200, 64, 32);
            cancel.DialogResult = DialogResult.Cancel;
            StyleSmall(cancel);
            dlg.Controls.Add(cancel);

            dlg.AcceptButton = ok;
            dlg.CancelButton = cancel;

            if (dlg.ShowDialog(this) != DialogResult.OK || list.SelectedIndex < 0)
                return null;
            return usable[list.SelectedIndex].Name;      // "D:\"
        }

        /// <summary>True when this PC is ready for the job at hand.
        ///
        /// Nothing but setup itself works on a machine that has never been set
        /// up: there is no library to file into and no drop folder to file
        /// from. Running anyway produces a failure about a folder, which is
        /// true and useless. Offer the step that fixes it instead.
        /// </summary>
        private bool ReadyOrOfferSetup(string what)
        {
            string configured = RunAndRead("drives --configured");
            if (configured != null && configured.Trim() == "yes") return true;

            if (MessageBox.Show(this,
                    "This PC has not been set up yet, so there is nothing for "
                    + what + " to work with - no games folder, and nowhere to "
                    + "drop new games.\r\n\r\n"
                    + "Would you like to set it up now? It asks which drive to "
                    + "use, then does the rest.",
                    "Not set up yet", MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question) == DialogResult.Yes)
                OnSetup(this, EventArgs.Empty);
            return false;
        }

        private void OnSetup(object sender, EventArgs e)
        {
            // Only ask when there is nothing configured. A second run is a
            // repair, and repairs should not move anyone's library.
            // Not "can we guess a path" - esdeck can always guess one - but
            // "has anyone chosen", which is the only thing that distinguishes
            // a fresh PC from a configured one.
            string configured = RunAndRead("drives --configured");
            bool alreadySetUp = configured != null && configured.Trim() == "yes";
            string drive = null;
            if (!alreadySetUp)
            {
                drive = ChooseDrive();
                if (drive == null) return;              // cancelled: change nothing
            }
            else
            {
                // "Set up this PC" reads like something that undoes a setup
                // which already works, so on a machine that has one, say
                // plainly what this does and what it leaves alone. An earlier
                // version installed far fewer emulator cores, and running this
                // again is exactly how that gets put right.
                string where = RunAndRead("drives --rom-dir");
                if (where == null || where.Length == 0) where = "(not known)";
                string message =
                    "This PC is already set up. Running this again checks "
                    + "everything over and installs whatever is missing - which "
                    + "is how a PC set up by an older version gets the rest of "
                    + "its emulator cores."
                    + "\r\n\r\nIt will:"
                    + "\r\n   - install anything not already installed"
                    + "\r\n   - download any emulator cores you do not have"
                    + "\r\n   - re-check the settings and the controller"
                    + "\r\n\r\nIt will not touch your games, and will not move "
                    + "your library:"
                    + "\r\n   " + where
                    + "\r\n\r\nCarry on?";
                if (MessageBox.Show(this, message, "Already set up",
                        MessageBoxButtons.YesNo,
                        MessageBoxIcon.Question) != DialogResult.Yes)
                    return;
            }

            List<string> steps = new List<string>();
            if (drive != null)
            {
                string root = drive.EndsWith("\\") ? drive : drive + "\\";
                steps.Add("init --force"
                    + " --rom-dir \"" + root + "ROMs\""
                    + " --source-dir \"" + root + "Games\\Incoming\"");
            }
            steps.Add("bootstrap --yes");
            steps.Add("link --yes --create");
            steps.Add("cores --all --yes");
            steps.Add("emulators --apply --yes");
            steps.Add("controller --yes");
            steps.Add("doctor");

            Run("Set up this PC", steps.ToArray(), delegate (int code)
            {
                string folder = RunAndRead("drives --rom-dir");
                if (string.IsNullOrEmpty(folder)) return;
                string incoming = Path.Combine(
                    Path.GetPathRoot(folder), "Games\\Incoming");
                MessageBox.Show(this,
                    "This PC is ready.\r\n\r\n"
                    + "Your games library:  " + folder + "\r\n"
                    + "Drop new games in:   " + incoming + "\r\n\r\n"
                    + "Put games - folders, zips, split archives, anything - into "
                    + "the drop folder, then choose \"Sort games\". They are filed "
                    + "into the library and ES-DE picks them up.",
                    "Set up", MessageBoxButtons.OK, MessageBoxIcon.Information);
            });
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

            startedAt = DateTime.Now;
            lastSampled = DateTime.MinValue;
            lastRead = lastWrite = 0;
            readRate = writeRate = 0;
            activityBar.Style = ProgressBarStyle.Marquee;   // until a % arrives
            activityBar.MarqueeAnimationSpeed = 30;
            activityBar.Value = 0;
            activityLabel.Text = "Starting...";
            stage = null;
            lock (pending) pending.Clear();
            written = 0;
            tickCount = 0;
            activityTimer.Start();
        }

        /// <summary>Queue a line for display.
        ///
        /// Deliberately does no UI work. Posting every line to the window as
        /// it arrives saturates the message queue on a busy sort, and Windows
        /// only delivers timer ticks to a queue that has run dry - so the
        /// activity display froze exactly when there was most to report. Lines
        /// are collected here and flushed on a timer instead.
        /// </summary>
        //: The command is the honest label, but "cores --all --yes" is not
        //: what someone is waiting for - "downloading emulator cores" is.
        private static string StepName(string step)
        {
            if (step.StartsWith("init")) return "choosing where games live";
            if (step.StartsWith("bootstrap")) return "installing ES-DE and RetroArch";
            if (step.StartsWith("link")) return "pointing ES-DE at your library";
            if (step.StartsWith("cores")) return "downloading emulator cores";
            if (step.StartsWith("emulators")) return "matching emulators to systems";
            if (step.StartsWith("controller")) return "making the pad player one";
            if (step.StartsWith("doctor")) return "checking everything over";
            if (step.StartsWith("tidy")) return "tidying the library";
            if (step.StartsWith("sync")) return "filing your games";
            if (step.StartsWith("cleanup")) return "removing artwork filed as games";
            if (step.StartsWith("clean")) return "reclaiming space";
            if (step.StartsWith("undo")) return "undoing the last sort";
            if (step.StartsWith("bios")) return "checking BIOS files";
            if (step.StartsWith("logs")) return "bundling the logs";
            if (step.StartsWith("update")) return "checking for updates";
            int space = step.IndexOf(' ');
            return space > 0 ? step.Substring(0, space) : step;
        }

        private void SetStage(string text)
        {
            if (InvokeRequired)
            {
                BeginInvoke((MethodInvoker)delegate { SetStage(text); });
                return;
            }
            stage = text;
        }

        private void Append(string line)
        {
            lock (pending) pending.Add(line);
        }

        private void Flush()
        {
            string[] lines;
            int dropped = 0;
            lock (pending)
            {
                if (pending.Count == 0) return;
                // Bound the work done in one go. A flush is UI-thread work,
                // and a batch of half a million lines blocks it for long
                // enough that the timer never runs again - which is the exact
                // freeze this buffering exists to prevent. Older lines go;
                // the newest are the ones being read.
                if (pending.Count > MaxPerFlush)
                {
                    dropped = pending.Count - MaxPerFlush;
                    lines = pending.GetRange(dropped, MaxPerFlush).ToArray();
                }
                else
                {
                    lines = pending.ToArray();
                }
                pending.Clear();
            }
            foreach (string l in lines) NotePercent(l);
            if (dropped > 0)
            {
                string[] with = new string[lines.Length + 1];
                with[0] = "... " + dropped + " lines went by too fast to show ...";
                lines.CopyTo(with, 1);
                lines = with;
            }

            // A long sort produces tens of thousands of lines, and a text box
            // holding all of them redraws slowly enough to be felt. Keep the
            // recent history, which is the part anyone reads.
            written += lines.Length;
            if (written > MaxLines)
            {
                string[] kept = output.Lines;
                int drop = Math.Max(0, kept.Length - MaxLines / 2);
                StringBuilder sb = new StringBuilder();
                for (int i = drop; i < kept.Length; i++) sb.Append(kept[i]).Append("\r\n");
                output.Text = sb.ToString();
                written = kept.Length - drop;
            }
            output.AppendText(string.Join("\r\n", lines) + "\r\n");
            output.SelectionStart = output.TextLength;
            output.ScrollToCaret();
        }

        //: "[####----] 16.7%" anywhere in a status line.
        private static readonly Regex PercentRe =
            new Regex(@"\]\s*([0-9]{1,3}(?:\.[0-9])?)%");

        private void NotePercent(string line)
        {
            Match m = PercentRe.Match(line);
            if (!m.Success) return;
            try
            {
                double pct = double.Parse(m.Groups[1].Value,
                        System.Globalization.CultureInfo.InvariantCulture);
                if (activityBar.Style == ProgressBarStyle.Marquee)
                {
                    activityBar.Style = ProgressBarStyle.Continuous;
                    activityBar.MarqueeAnimationSpeed = 0;
                }
                activityBar.Value = Math.Max(0, Math.Min(1000, (int)(pct * 10)));
            }
            catch { }
        }

        private static string Bytes(double n)
        {
            string[] units = { "B", "KB", "MB", "GB" };
            int i = 0;
            while (n >= 1024 && i < units.Length - 1) { n /= 1024; i++; }
            return (i < 2 ? n.ToString("0") : n.ToString("0.0")) + " " + units[i];
        }

        /// <summary>Once a second, say that work is still happening.
        ///
        /// The numbers come from the operating system's own I/O counters for
        /// the step that is running, not from reading the text above. That
        /// keeps them honest through the long silences - hashing one huge
        /// file, or waiting on 7-Zip - when there is no output to go on.
        /// </summary>
        private void OnActivityTick(object sender, EventArgs e)
        {
            Flush();
            if (!busy) return;
            if (++tickCount % 4 != 0) return;        // the readout, once a second
            TimeSpan up = DateTime.Now - startedAt;

            Process proc = current;
            if (proc != null)
            {
                try
                {
                    IoCounters c;
                    if (GetProcessIoCounters(proc.Handle, out c))
                    {
                        double gap = (DateTime.Now - lastSampled).TotalSeconds;
                        if (gap > 0.2 && lastSampled != DateTime.MinValue)
                        {
                            // Smoothed: copying alternates reading and writing,
                            // and a raw reading swings between the two on every
                            // tick, which is harder to read than it is useful.
                            double r = c.ReadBytes > lastRead
                                     ? (c.ReadBytes - lastRead) / gap : 0;
                            double w = c.WriteBytes > lastWrite
                                     ? (c.WriteBytes - lastWrite) / gap : 0;
                            readRate = 0.6 * r + 0.4 * readRate;
                            writeRate = 0.6 * w + 0.4 * writeRate;
                        }
                        lastRead = c.ReadBytes;
                        lastWrite = c.WriteBytes;
                        lastSampled = DateTime.Now;
                    }
                }
                catch { }                    // the step can exit mid-reading
            }

            string elapsed = up.TotalHours >= 1
                ? string.Format("{0}:{1:00}:{2:00}", (int)up.TotalHours,
                                up.Minutes, up.Seconds)
                : string.Format("{0}:{1:00}", up.Minutes, up.Seconds);
            bool moving = (readRate + writeRate) > 65536;
            string where = stage;
            activityLabel.Text = (string.IsNullOrEmpty(where) ? "Working" : where)
                + "   " + elapsed
                + "      disk  read " + Bytes(readRate) + "/s"
                + "   write " + Bytes(writeRate) + "/s"
                + (moving ? "" : "      (idle - working it out, not stuck)");
        }

        /// <summary>Run esdeck commands one after another, output shown here.</summary>
        private void Run(string what, string[] steps)
        {
            Run(what, steps, null);
        }

        private void Run(string what, string[] steps, DoneHandler done)
        {
            if (busy) return;
            ShowOutput(what);
            busy = true;
            cancelled = false;
            onDone = done;
            lastCode = 0;

            worker = new Thread(delegate ()
            {
                Append("=== " + what + " ===");
                Append(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
                Append("");

                string py = Python();
                if (!EnsureReady(ref py))
                {
                    lastCode = 1;
                    Finished();
                    return;
                }

                int stepNumber = 0;
                foreach (string step in steps)
                {
                    if (cancelled) break;
                    stepNumber++;
                    if (steps.Length > 1)
                        SetStage("Step " + stepNumber + " of " + steps.Length
                                 + ": " + StepName(step));
                    Append("> esdeck " + step);
                    int code = RunStep(py, step);
                    lastCode = code;
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

        // ------------------------------------------------- making it runnable

        //: pip understands a URL to a zip of the repo, so nothing has to be
        //: downloaded or unzipped by hand.
        private const string SourceZip =
            "https://github.com/265ada/esdeck/archive/refs/heads/master.zip";

        /// <summary>Run any program, streaming its output into the window.</summary>
        private int RunProcess(string exe, string arguments, string display)
        {
            Append("> " + display);
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo(exe, arguments);
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                psi.StandardOutputEncoding = Encoding.UTF8;
                psi.StandardErrorEncoding = Encoding.UTF8;
                psi.WorkingDirectory = appDir;
                psi.EnvironmentVariables["PYTHONSAFEPATH"] = "1";
                psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";

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
                Append("  could not run that: " + ex.Message);
                return -1;
            }
        }

        /// <summary>Whether esdeck can actually be imported by this Python.</summary>
        private bool EsdeckWorks(string py)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo(py, "-m esdeck --version");
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                psi.WorkingDirectory = appDir;
                psi.EnvironmentVariables["PYTHONSAFEPATH"] = "1";
                Process p = Process.Start(psi);
                p.StandardOutput.ReadToEnd();
                p.StandardError.ReadToEnd();
                p.WaitForExit(30000);
                return p.ExitCode == 0;
            }
            catch { return false; }
        }

        /// <summary>Put Python and esdeck in place before anything needs them.
        ///
        /// Every action here is "python -m esdeck ...", so if either is absent
        /// each step fails identically and the whole run reports nothing but
        /// "No module named esdeck" - which says what is missing but not what
        /// to do about it, and leaves nothing installed. This installs them.
        /// </summary>
        private bool EnsureReady(ref string py)
        {
            if (py == null)
            {
                Append("Python is not installed on this PC. Installing it now -");
                Append("this takes a few minutes and needs an internet connection.");
                Append("");
                RunProcess("winget", "install --id Python.Python.3.12 -e "
                    + "--accept-package-agreements --accept-source-agreements "
                    + "--disable-interactivity",
                    "winget install Python");
                Append("");
                py = Python();
                if (py == null)
                {
                    Append("Python still is not there. Two things usually explain it:");
                    Append("  - winget is missing (Windows 10 before 1809), or");
                    Append("  - a new terminal is needed before PATH picks it up.");
                    Append("");
                    Append("Install Python from https://www.python.org/downloads/,");
                    Append("tick \"Add python.exe to PATH\", then start this again.");
                    return false;
                }
            }
            Append("Python: found.");

            if (EsdeckWorks(py))
            {
                Append("esdeck: installed.");
                Append("");
                return true;
            }

            Append("esdeck is not installed for this Python yet. Installing it now...");
            Append("");
            // A source folder beside the .exe is preferred - it is what the
            // person in front of us actually has - and GitHub is the fallback,
            // so nothing needs downloading or unzipping by hand.
            bool local = File.Exists(Path.Combine(appDir, "pyproject.toml"));
            string target = local ? "\"" + appDir.TrimEnd('\\') + "\"" : SourceZip;
            string what = local ? "(the folder beside this app)"
                                : "esdeck from GitHub";
            int code = RunProcess(py,
                "-m pip install --upgrade --disable-pip-version-check " + target,
                "pip install " + what);
            if (code != 0 && !cancelled)
            {
                // A Python installed for everyone lives somewhere this account
                // cannot write to. Installing just for this user always can.
                Append("");
                Append("That Python is installed system-wide. Trying again just "
                       + "for you...");
                RunProcess(py,
                    "-m pip install --user --upgrade --disable-pip-version-check "
                    + target, "pip install --user " + what);
            }
            Append("");
            if (EsdeckWorks(py))
            {
                Append("esdeck: installed.");
                Append("");
                return true;
            }
            Append("esdeck could not be installed automatically. The pip output");
            Append("above says why. Nothing else has been changed.");
            return false;
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
                // Without this, Python puts the working directory first on the
                // import path. A copy of the source sitting beside the .exe -
                // a downloaded repo, say - would then shadow the installed
                // package, so updates appeared to do nothing at all.
                psi.EnvironmentVariables["PYTHONSAFEPATH"] = "1";

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
            Flush();
            activityTimer.Stop();
            activityBar.Style = ProgressBarStyle.Continuous;
            activityBar.MarqueeAnimationSpeed = 0;
            if (!cancelled) activityBar.Value = activityBar.Maximum;
            TimeSpan took = DateTime.Now - startedAt;
            activityLabel.Text = (cancelled ? "Stopped after " : "Finished in ")
                + string.Format("{0}m {1:00}s", (int)took.TotalMinutes, took.Seconds);
            cancelButton.Enabled = false;
            backButton.Enabled = true;
            runningLabel.Text = cancelled ? "Stopped" : "Finished";
            RefreshStatus();

            DoneHandler handler = onDone;
            onDone = null;
            if (handler != null && !cancelled) handler(lastCode);
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
            string folder = RunAndRead("drives --rom-dir");
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
            if (!ReadyOrOfferSetup("undoing a sort")) return;
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
            if (!ReadyOrOfferSetup("freeing up space")) return;
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

        private void OnExportLogs(object sender, EventArgs e)
        {
            // Every run writes a transcript; this collects the lot into one
            // zip, which is the thing worth sending on when something needs
            // explaining after the fact.
            FolderBrowserDialog dlg = new FolderBrowserDialog();
            dlg.Description = "Where should the log bundle be saved?";
            dlg.SelectedPath = Environment.GetFolderPath(
                Environment.SpecialFolder.DesktopDirectory);
            if (dlg.ShowDialog() != DialogResult.OK) return;
            Run("Exporting logs", new string[] {
                "logs --export \"" + dlg.SelectedPath.TrimEnd('\\') + "\"" });
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
