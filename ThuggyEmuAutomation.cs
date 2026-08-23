// ThuggyEmuAutomation - a real Windows application for esdeck.
//
// Built with csc.exe, which ships with Windows, so there is no toolchain to
// install and no Python runtime bundled inside. The buttons run the same batch
// files and esdeck commands as before, each in its own console window so the
// progress bar and time estimate stay visible.
//
// Build:  build-exe.bat

using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace ThuggyEmuAutomation
{
    public class MainForm : Form
    {
        private Label statusLabel;
        private Label versionLabel;
        private string appDir;

        public MainForm()
        {
            appDir = AppDomain.CurrentDomain.BaseDirectory;

            Text = "ThuggyEmuAutomation";
            ClientSize = new Size(430, 486);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.FromArgb(32, 38, 52);
            Font = new Font("Segoe UI", 9.75f);

            Label title = new Label();
            title.Text = "ThuggyEmuAutomation";
            title.Font = new Font("Segoe UI", 15f, FontStyle.Bold);
            title.ForeColor = Color.White;
            title.SetBounds(20, 16, 390, 32);
            Controls.Add(title);

            versionLabel = new Label();
            versionLabel.ForeColor = Color.FromArgb(150, 165, 190);
            versionLabel.SetBounds(22, 48, 390, 18);
            Controls.Add(versionLabel);

            int y = 82;
            AddButton("Set up this PC", "Installs ES-DE, RetroArch, cores and folders",
                      ref y, OnSetup);
            AddButton("Sort games", "Files everything in your Incoming folder",
                      ref y, OnSort);
            AddButton("Fix library", "Removes artwork filed as games, fixes the controller",
                      ref y, OnFix);
            AddButton("Undo the last sort", "Puts the library back as it was",
                      ref y, OnUndo);
            AddButton("Check for problems", "Reports anything that needs attention",
                      ref y, OnDoctor);
            AddButton("Change the icon", "Use your own picture for this app",
                      ref y, OnIcon);

            Button folder = new Button();
            folder.Text = "Open games folder";
            folder.SetBounds(22, y + 6, 190, 30);
            Style(folder, false);
            folder.Click += OnOpenFolder;
            Controls.Add(folder);

            Button update = new Button();
            update.Text = "Check for updates";
            update.SetBounds(220, y + 6, 190, 30);
            Style(update, false);
            update.Click += OnUpdate;
            Controls.Add(update);

            statusLabel = new Label();
            statusLabel.ForeColor = Color.FromArgb(150, 165, 190);
            statusLabel.SetBounds(22, y + 48, 390, 36);
            Controls.Add(statusLabel);

            Shown += OnShown;
        }

        private void AddButton(string text, string hint, ref int y, EventHandler onClick)
        {
            Button b = new Button();
            b.Text = "   " + text;
            b.TextAlign = ContentAlignment.MiddleLeft;
            b.SetBounds(22, y, 388, 34);
            Style(b, true);
            b.Click += onClick;
            Controls.Add(b);

            Label l = new Label();
            l.Text = "        " + hint;
            l.ForeColor = Color.FromArgb(140, 155, 180);
            l.Font = new Font("Segoe UI", 8f);
            l.SetBounds(22, y + 35, 388, 15);
            Controls.Add(l);

            y += 56;
        }

        private void Style(Button b, bool primary)
        {
            b.FlatStyle = FlatStyle.Flat;
            b.FlatAppearance.BorderSize = 1;
            b.FlatAppearance.BorderColor = Color.FromArgb(70, 84, 110);
            b.BackColor = primary ? Color.FromArgb(45, 54, 74)
                                  : Color.FromArgb(38, 45, 62);
            b.ForeColor = Color.White;
            b.Cursor = Cursors.Hand;
        }

        // ------------------------------------------------------------------

        private string Python()
        {
            // "py" is the launcher installed with Python on Windows; "python"
            // is there when it was added to PATH. Either will do.
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
                string output = p.StandardOutput.ReadToEnd();
                p.WaitForExit(20000);
                return output.Trim();
            }
            catch { return null; }
        }

        /// <summary>Run a batch file in its own console so progress stays visible.</summary>
        private void RunBat(string batName, string args)
        {
            string path = Path.Combine(appDir, batName);
            if (!File.Exists(path))
            {
                MessageBox.Show(
                    batName + " is not next to this application.\r\n\r\n" +
                    "Keep ThuggyEmuAutomation.exe in the folder you extracted " +
                    "from GitHub, or copy the .bat files beside it.",
                    "File missing", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo(path, args);
                psi.UseShellExecute = true;
                psi.WorkingDirectory = appDir;
                Process.Start(psi);
            }
            catch (Exception ex)
            {
                MessageBox.Show("Could not start " + batName + ":\r\n" + ex.Message,
                                "Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void RunCommand(string arguments)
        {
            string py = Python();
            if (py == null) { NoPython(); return; }
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo(
                    "cmd.exe", "/c \"" + py + " -m esdeck " + arguments + " & pause\"");
                psi.UseShellExecute = true;
                psi.WorkingDirectory = appDir;
                Process.Start(psi);
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.Message, "Error",
                                MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void NoPython()
        {
            MessageBox.Show(
                "Python is not installed yet.\r\n\r\n" +
                "Use \"Set up this PC\" first - it installs everything needed.",
                "Not set up", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }

        // ------------------------------------------------------------------

        private void OnShown(object sender, EventArgs e)
        {
            RefreshStatus();
        }

        private void RefreshStatus()
        {
            string version = RunAndRead("--version");
            versionLabel.Text = version == null
                ? "Not installed yet - start with \"Set up this PC\""
                : version;

            string folder = RunAndRead("drives --current");
            if (!string.IsNullOrEmpty(folder))
                statusLabel.Text = "Games folder:  " + folder;
            else
                statusLabel.Text = "No games folder configured yet.";
        }

        private void OnSetup(object sender, EventArgs e) { RunBat("esdeck.bat", ""); }
        private void OnSort(object sender, EventArgs e) { RunBat("sort-games.bat", ""); }
        private void OnFix(object sender, EventArgs e) { RunBat("fix-library.bat", ""); }
        private void OnDoctor(object sender, EventArgs e) { RunCommand("doctor"); }

        private void OnUndo(object sender, EventArgs e)
        {
            if (MessageBox.Show(
                    "Undo the most recent sort?\r\n\r\n" +
                    "This removes only what that sort put in your library. " +
                    "Your original files are not touched.",
                    "Undo", MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question) == DialogResult.Yes)
                RunCommand("undo --yes");
        }

        private void OnIcon(object sender, EventArgs e)
        {
            OpenFileDialog dlg = new OpenFileDialog();
            dlg.Title = "Choose a square picture";
            dlg.Filter = "PNG images (*.png)|*.png";
            if (dlg.ShowDialog() != DialogResult.OK) return;
            RunBat("set-icon.bat", "\"" + dlg.FileName + "\"");
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
            string py = Python();
            if (py == null) { NoPython(); return; }
            RunCommand("update --yes --bat-dir \"" + appDir.TrimEnd('\\') + "\"");
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
