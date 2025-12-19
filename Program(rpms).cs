using System;
using System.Net.Sockets;
using System.IO;

class SimHubRPMLightSender
{
    //---------------------------------------------------------
    // NETWORK
    //---------------------------------------------------------
    static string piIP = "10.0.0.120";
    const int PI_RPM_PORT = 5009;

    //---------------------------------------------------------
    // STATE
    //---------------------------------------------------------
    static double rpm = 0;
    static double maxRpm = 8000;
    static double redlineRpm = 7500;
    static bool redlineReached = false;

    //---------------------------------------------------------
    // MAIN
    //---------------------------------------------------------
    static void Main()
    {
        Console.WriteLine("=== SimHub RPM Light Sender ===");

        //---------------------------------------------------------
        // UDP OUT
        //---------------------------------------------------------
        UdpClient udp = new UdpClient();
        udp.Connect(piIP, PI_RPM_PORT);

        //---------------------------------------------------------
        // SIMHUB TCP
        //---------------------------------------------------------
        TcpClient sh = new TcpClient("127.0.0.1", 18082);
        var reader = new StreamReader(sh.GetStream());
        var writer = new StreamWriter(sh.GetStream()) { AutoFlush = true };

        //---------------------------------------------------------
        // SUBSCRIPTIONS
        //---------------------------------------------------------
        string[] props =
        {
            "DataCorePlugin.GameData.Rpms",
            "DataCorePlugin.GameData.MaxRpm",
            "DataCorePlugin.GameData.CarSettings_RedLineRPM",
            "DataCorePlugin.GameData.CarSettings_RPMRedLineReached"
        };

        foreach (var p in props)
            writer.WriteLine("subscribe " + p);

        //---------------------------------------------------------
        // LOOP
        //---------------------------------------------------------
        while (true)
        {
            string line = reader.ReadLine();
            if (line == null) continue;

            string[] s = line.Split(' ');
            if (s.Length < 4) continue;

            string prop = s[1];
            double v = double.TryParse(s[3], out double tmp) ? tmp : 0;

            //------------------------------
            // UPDATE STATE
            //------------------------------
            if (prop.EndsWith("Rpms"))
                rpm = v;

            else if (prop.EndsWith("MaxRpm") && v > 0)
                maxRpm = v;

            else if (prop.EndsWith("CarSettings_RedLineRPM") && v > 0)
                redlineRpm = v;

            else if (prop.EndsWith("CarSettings_RPMRedLineReached"))
                redlineReached = v > 0.5;

            //---------------------------------------------------------
            // NORMALIZE
            //---------------------------------------------------------
            double rpmNorm = rpm / maxRpm;
            rpmNorm = Math.Max(0.0, Math.Min(1.0, rpmNorm));

            byte rpm255 = (byte)(rpmNorm * 255);
            byte rpmPct = (byte)(rpmNorm * 100);
            byte redline = (byte)(redlineReached ? 1 : 0);

            //---------------------------------------------------------
            // PACKET
            //---------------------------------------------------------
            byte[] pkt =
            {
                rpm255,
                redline,
                rpmPct,
                0 // reserved for future effects
            };

            udp.Send(pkt, pkt.Length);

            //---------------------------------------------------------
            // DEBUG
            //---------------------------------------------------------
            Console.WriteLine(
                $"RPM={rpm,6:0}  MAX={maxRpm,5:0}  NORM={rpmNorm:0.00}  RED={redline}"
            );
        }
    }
}
