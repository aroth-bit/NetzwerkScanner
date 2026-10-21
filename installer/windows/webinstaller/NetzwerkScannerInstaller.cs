// NetzwerkScanner-Installer.exe - Online-Installer
//
// Laedt die neueste Version des NetzwerkScanners aus den GitHub-Releases, prueft die
// SHA-256-Pruefsumme und installiert sie (eingebettetes install-from-github.ps1).
//
//   NetzwerkScanner-Installer.exe                      Installieren / aktualisieren
//   NetzwerkScanner-Installer.exe -Port 9000           eigener Dashboard-Port
//   NetzwerkScanner-Installer.exe -DownloadOnly        nur Paket herunterladen (Server ohne Internet)
//   NetzwerkScanner-Installer.exe -Tag v1.1.1          bestimmte Version
//
// Wird mit dem csc.exe des .NET Frameworks gebaut (build_webinstaller.ps1), nur C# 5.

using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;

[assembly: AssemblyTitle("NetzwerkScanner Installer")]
[assembly: AssemblyDescription("Laedt den NetzwerkScanner von GitHub und installiert ihn")]
[assembly: AssemblyProduct("NetzwerkScanner")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

internal static class Program
{
    private static int Main(string[] args)
    {
        Console.Title = "NetzwerkScanner Installer";
        Console.ForegroundColor = ConsoleColor.Cyan;
        Console.WriteLine("==============================================================");
        Console.WriteLine("  NetzwerkScanner - Online-Installer");
        Console.WriteLine("  Laedt die neueste Version von GitHub und installiert sie.");
        Console.WriteLine("==============================================================");
        Console.ResetColor();
        Console.WriteLine();

        string work = Path.Combine(Path.GetTempPath(), "NetzwerkScanner-Installer-" + Guid.NewGuid().ToString("N"));
        int rc;
        try
        {
            Directory.CreateDirectory(work);
            string script = Path.Combine(work, "install-from-github.ps1");
            using (Stream res = Assembly.GetExecutingAssembly().GetManifestResourceStream("install-from-github.ps1"))
            using (FileStream f = File.Create(script))
            {
                res.CopyTo(f);
            }

            StringBuilder cmd = new StringBuilder();
            cmd.Append("-NoProfile -ExecutionPolicy Bypass -File \"").Append(script).Append('"');
            foreach (string a in args)
            {
                cmd.Append(' ').Append(Quote(a));
            }

            ProcessStartInfo psi = new ProcessStartInfo(PowerShellPath(), cmd.ToString());
            psi.UseShellExecute = false;
            Process p = Process.Start(psi);
            p.WaitForExit();
            rc = p.ExitCode;
        }
        catch (Exception ex)
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine("Fehler: " + ex.Message);
            Console.ResetColor();
            rc = 1;
        }
        finally
        {
            try { Directory.Delete(work, true); } catch { }
        }

        if (rc != 0)
        {
            Console.WriteLine();
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine("Die Installation ist fehlgeschlagen (Code " + rc + ").");
            Console.ResetColor();
            Console.WriteLine("Haeufige Ursachen: keine Internetverbindung zu github.com, Proxy (HTTPS_PROXY setzen),");
            Console.WriteLine("Virenscanner blockiert PowerShell. Alternativ das ZIP-Paket aus den GitHub-Releases verwenden.");
            Console.WriteLine();
            Console.WriteLine("Enter zum Beenden ...");
            Console.ReadLine();
        }
        return rc;
    }

    private static string PowerShellPath()
    {
        string p = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                                @"WindowsPowerShell\v1.0\powershell.exe");
        return File.Exists(p) ? p : "powershell.exe";
    }

    private static string Quote(string a)
    {
        if (a.Length > 0 && a.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
        {
            return a;
        }
        return "\"" + a.Replace("\"", "\\\"") + "\"";
    }
}
