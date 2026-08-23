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

            startedAt = DateTime.Now;
            lastSampled = DateTime.MinValue;
            lastRead = lastWrite = 0;
            readRate = writeRate = 0;
            activityBar.Style = ProgressBarStyle.Marquee;   // until a % arrives
            activityBar.MarqueeAnimationSpeed = 30;
            activityBar.Value = 0;
            activityLabel.Text = "Starting...";
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
            activityLabel.Text = "Working  " + elapsed
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
            string py = Python();
            if (py == null) { NoPython(); return; }

            ShowOutput(what);
            busy = true;
            cancelled = false;
            onDone = done;
            lastCode = 0;

            worker = new Thread(delegate ()
            {
                foreach (string step in steps)
                {
                    if (cancelled) break;
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
