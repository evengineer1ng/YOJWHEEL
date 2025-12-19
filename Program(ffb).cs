using System;
using System.Net.Sockets;
using System.IO;

class G29FFBSender_Punchy
{
    //---------------------------------------------------------
    // NETWORK
    //---------------------------------------------------------
    static string piIP = "10.0.0.158";
    const int PI_FFB_PORT = 5000;

    //---------------------------------------------------------
    // SMOOTHING
    //---------------------------------------------------------
    static double Smooth(double prev, double cur, double factor)
        => prev + (cur - prev) * factor;

    static double sAlign;
    static double sSlip;
    static double sImpact;
    static double sRack;
    static double sFinal;

    //---------------------------------------------------------
    // COMPRESSION (Joy-Con style punch)
    //---------------------------------------------------------
    static double Compress(double v)
    {
        double x = Math.Abs(v);
        x = Math.Min(x, 1.0);
        return Math.Sign(v) * Math.Pow(x, 0.6);
    }

    //---------------------------------------------------------
    // DEADZONE
    //---------------------------------------------------------
    static double Deadzone(double v, double dz)
    {
        if (Math.Abs(v) < dz) return 0;
        return Math.Sign(v) * ((Math.Abs(v) - dz) / (1.0 - dz));
    }

    //---------------------------------------------------------
    // MAIN
    //---------------------------------------------------------
    static void Main()
    {
        Console.WriteLine("=== Wheelbase FFB Sender (Punchy / Layered / Responsive) ===");

        //---------------------------------------------------------
        // UDP OUT
        //---------------------------------------------------------
        UdpClient udpFFB = new UdpClient();
        udpFFB.Connect(piIP, PI_FFB_PORT);

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
            "ShakeITMotorsV3Plugin.Export.lateralgforce.Left",
            "ShakeITMotorsV3Plugin.Export.lateralgforce.Right",
            "ShakeITMotorsV3Plugin.Export.wheelslip.FrontLeft",
            "ShakeITMotorsV3Plugin.Export.wheelslip.FrontRight",
            "ShakeITMotorsV3Plugin.Export.roadimpacts.FrontLeft",
            "ShakeITMotorsV3Plugin.Export.roadimpacts.FrontRight",
            "ShakeITMotorsV3Plugin.Export.speed.All",
            "GameData.SteeringWheelAngle",
            "GameData.CarSettings.SteeringLock"
        };

        foreach (var p in props)
            writer.WriteLine("subscribe " + p);

        //---------------------------------------------------------
        // STATE
        //---------------------------------------------------------
        double latL = 0, latR = 0;
        double slipFL = 0, slipFR = 0;
        double riFL = 0, riFR = 0;
        double speed = 0;
        double wheelAngle = 0;
        double steeringLock = 450;

        double lastSteer = 0;

        //---------------------------------------------------------
        // CONSTANTS (STRONGER)
        //---------------------------------------------------------
        const double TRAIL_GAIN = 1.8;
        const double SLIP_GAIN = 1.2;
        const double IMPACT_GAIN = 1.4;
        const double RACK_GAIN = 0.9;
        const double CENTER_SPRING = 0.18;

        const int MAX_TORQUE = 12000;

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
            if (prop.Contains("lateralgforce.Left")) latL = v;
            if (prop.Contains("lateralgforce.Right")) latR = v;

            if (prop.Contains("wheelslip.FrontLeft")) slipFL = v;
            if (prop.Contains("wheelslip.FrontRight")) slipFR = v;

            if (prop.Contains("roadimpacts.FrontLeft")) riFL = v;
            if (prop.Contains("roadimpacts.FrontRight")) riFR = v;

            if (prop.Contains("speed.All")) speed = v;
            if (prop.Contains("SteeringWheelAngle")) wheelAngle = v;
            if (prop.Contains("SteeringLock") && v > 0) steeringLock = v;

            //---------------------------------------------------------
            // NORMALIZATION
            //---------------------------------------------------------
            double steerPos = wheelAngle / steeringLock;
            steerPos = Math.Max(-1, Math.Min(1, steerPos));

            double speedNorm = Math.Min(speed / 220.0, 1.0);

            //---------------------------------------------------------
            // ALIGNING / TRAIL
            //---------------------------------------------------------
            double align =
                (latR - latL) *
                (1.0 - Math.Abs(steerPos)) *
                speedNorm *
                TRAIL_GAIN;

            //---------------------------------------------------------
            // SLIP TORQUE (adds bite on limit)
            //---------------------------------------------------------
            double slip =
                (slipFR - slipFL) *
                speedNorm *
                SLIP_GAIN;

            //---------------------------------------------------------
            // IMPACTS (sharp)
            //---------------------------------------------------------
            double impact =
                (riFR - riFL) *
                IMPACT_GAIN;

            //---------------------------------------------------------
            // RACK / CENTER FEEL
            //---------------------------------------------------------
            double steerVel = steerPos - lastSteer;
            lastSteer = steerPos;

            double rack =
                (-steerVel * 0.6) +
                (-steerPos * CENTER_SPRING);

            rack *= RACK_GAIN;

            //---------------------------------------------------------
            // COMPRESS + SMOOTH EACH LAYER
            //---------------------------------------------------------
            sAlign  = Smooth(sAlign,  Compress(align),  0.18);
            sSlip   = Smooth(sSlip,   Compress(slip),   0.12);
            sImpact = Smooth(sImpact, Compress(impact), 0.08);
            sRack   = Smooth(sRack,   Compress(rack),   0.20);

            //---------------------------------------------------------
            // FINAL MIX
            //---------------------------------------------------------
            double final =
                sAlign * 1.0 +
                sSlip  * 0.9 +
                sImpact* 1.1 +
                sRack  * 1.0;

            final = Deadzone(final, 0.02);
            final = Math.Max(-1.0, Math.Min(1.0, final));

            sFinal = Smooth(sFinal, final, 0.10);

            //---------------------------------------------------------
            // SEND
            //---------------------------------------------------------
            short outTorque = (short)(sFinal * MAX_TORQUE);

            byte[] pkt =
            {
                (byte)(outTorque & 0xFF),
                (byte)((outTorque >> 8) & 0xFF)
            };

            udpFFB.Send(pkt, pkt.Length);

            //---------------------------------------------------------
            // DEBUG
            //---------------------------------------------------------
            Console.WriteLine(
                $"OUT={outTorque,6}  A={sAlign:0.00} S={sSlip:0.00} I={sImpact:0.00} R={sRack:0.00}"
            );
        }
    }
}
