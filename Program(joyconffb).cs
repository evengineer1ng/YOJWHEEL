using System;
using System.Net;
using System.Net.Sockets;
using System.IO;

class JoyConHapticsSender
{
    static string piIP = "10.0.0.120";
    const int PI_PORT = 6002;

    //---------------------------------------------------------
    // SMOOTHING STATE
    //---------------------------------------------------------
    static double Smooth(double prev, double cur, double factor)
        => prev + (cur - prev) * factor;

    static double sBaseL, sBaseR;
    static double sSlipL, sSlipR;
    static double sImpactL, sImpactR;
    static double sEngine;
    static double sBrake, sAccel;
    static double sAeroL, sAeroR;
    static double sGlobal;

    //---------------------------------------------------------
    // COMPRESSION (gentle exponential curve)
    //---------------------------------------------------------
    static int Compress(double v)
    {
        double x = v / 1000.0;
        if (x < 0) x = 0;
        if (x > 1) x = 1;
        return (int)(1000.0 * Math.Pow(x, 0.6));
    }

    //---------------------------------------------------------
    // CLAMP
    //---------------------------------------------------------
    static int Clamp(double v)
        => v < 0 ? 0 : (v > 1000 ? 1000 : (int)v);

    //---------------------------------------------------------
    // WRITE U16 LITTLE-ENDIAN
    //---------------------------------------------------------
    static void WriteU16(byte[] buf, int offset, int value)
    {
        buf[offset] = (byte)(value & 0xFF);
        buf[offset + 1] = (byte)((value >> 8) & 0xFF);
    }

    //---------------------------------------------------------
    // MAIN
    //---------------------------------------------------------
    static void Main()
    {
        Console.WriteLine("=== Joy-Con Haptics Sender (12 channels, Smoothed & Tuned) ===");

        //---------------------------------------------------------
        // UDP OUT
        //---------------------------------------------------------
        UdpClient udp = new UdpClient();
        udp.Connect(piIP, PI_PORT);
        Console.WriteLine($"[RUMBLE] Sending to {piIP}:{PI_PORT}\n");

        //---------------------------------------------------------
        // SIMHUB TCP
        //---------------------------------------------------------
        TcpClient sh = new TcpClient("127.0.0.1", 18082);
        var reader = new StreamReader(sh.GetStream());
        var writer = new StreamWriter(sh.GetStream()) { AutoFlush = true };

        Console.WriteLine("[SIMHUB] Connected.\n");

        //---------------------------------------------------------
        // SUBSCRIPTIONS
        //---------------------------------------------------------
        string[] props =
        {
            // Slip
            "ShakeITMotorsV3Plugin.Export.wheelslip.FrontLeft",
            "ShakeITMotorsV3Plugin.Export.wheelslip.FrontRight",
            "ShakeITMotorsV3Plugin.Export.wheelslip.RearLeft",
            "ShakeITMotorsV3Plugin.Export.wheelslip.RearRight",

            // Lock / ABS
            "ShakeITMotorsV3Plugin.Export.wheellock.FrontLeft",
            "ShakeITMotorsV3Plugin.Export.wheellock.FrontRight",
            "ShakeITMotorsV3Plugin.Export.wheellock.RearLeft",
            "ShakeITMotorsV3Plugin.Export.wheellock.RearRight",
            "ShakeITMotorsV3Plugin.Export.abs active.All",

            // Road
            "ShakeITMotorsV3Plugin.Export.roadvibration.FrontLeft",
            "ShakeITMotorsV3Plugin.Export.roadvibration.FrontRight",
            "ShakeITMotorsV3Plugin.Export.roadvibration.RearLeft",
            "ShakeITMotorsV3Plugin.Export.roadvibration.RearRight",

            "ShakeITMotorsV3Plugin.Export.roadrumble.FrontLeft",
            "ShakeITMotorsV3Plugin.Export.roadrumble.FrontRight",
            "ShakeITMotorsV3Plugin.Export.roadrumble.RearLeft",
            "ShakeITMotorsV3Plugin.Export.roadrumble.RearRight",

            "ShakeITMotorsV3Plugin.Export.roadimpacts.FrontLeft",
            "ShakeITMotorsV3Plugin.Export.roadimpacts.FrontRight",
            "ShakeITMotorsV3Plugin.Export.roadimpacts.RearLeft",
            "ShakeITMotorsV3Plugin.Export.roadimpacts.RearRight",

            // Forces
            "ShakeITMotorsV3Plugin.Export.lateralgforce.Left",
            "ShakeITMotorsV3Plugin.Export.lateralgforce.Right",
            "ShakeITMotorsV3Plugin.Export.accelgforce.Rear",
            "ShakeITMotorsV3Plugin.Export.decelgforce.Front",

            // Engine / gearbox
            "ShakeITMotorsV3Plugin.Export.rpms.All",
            "ShakeITMotorsV3Plugin.Export.gearshift.All",
            "ShakeITMotorsV3Plugin.Export.geargrinding.All",
            "ShakeITMotorsV3Plugin.Export.missedgear.All",

            // Aero / traction / speed
            "ShakeITMotorsV3Plugin.Export.staticwind.All",
            "ShakeITMotorsV3Plugin.Export.speed.All",
            "ShakeITMotorsV3Plugin.Export.speedwithcurving.Left",
            "ShakeITMotorsV3Plugin.Export.speedwithcurving.Right",
            "ShakeITMotorsV3Plugin.Export.tractionloss.Left",
            "ShakeITMotorsV3Plugin.Export.tractionloss.Right",
        };

        foreach (string p in props)
            writer.WriteLine("subscribe " + p);

        Console.WriteLine("[SIMHUB] Subscribed to all properties.\n");

        //---------------------------------------------------------
        // STATE VARS
        //---------------------------------------------------------
        double slipFL=0, slipFR=0, slipRL=0, slipRR=0;
        double lockFL=0, lockFR=0, lockRL=0, lockRR=0;
        double absAct=0;

        double rvFL=0, rvFR=0, rvRL=0, rvRR=0;
        double rrFL=0, rrFR=0, rrRL=0, rrRR=0;
        double riFL=0, riFR=0, riRL=0, riRR=0;

        double latL=0, latR=0;
        double accelG=0, decelG=0;

        double rpm=0, gearShift=0, gearGrind=0, missGear=0;

        double wind=0, speed=0, speedL=0, speedR=0;
        double tlL=0, tlR=0;

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
            if (prop.Contains("wheelslip.FrontLeft"))  slipFL = v;
            if (prop.Contains("wheelslip.FrontRight")) slipFR = v;
            if (prop.Contains("wheelslip.RearLeft"))   slipRL = v;
            if (prop.Contains("wheelslip.RearRight"))  slipRR = v;

            if (prop.Contains("wheellock.FrontLeft"))  lockFL = v;
            if (prop.Contains("wheellock.FrontRight")) lockFR = v;
            if (prop.Contains("wheellock.RearLeft"))   lockRL = v;
            if (prop.Contains("wheellock.RearRight"))  lockRR = v;

            if (prop.Contains("abs active")) absAct = v;

            if (prop.Contains("roadvibration.FrontLeft"))  rvFL = v;
            if (prop.Contains("roadvibration.FrontRight")) rvFR = v;
            if (prop.Contains("roadvibration.RearLeft"))   rvRL = v;
            if (prop.Contains("roadvibration.RearRight"))  rvRR = v;

            if (prop.Contains("roadrumble.FrontLeft"))  rrFL = v;
            if (prop.Contains("roadrumble.FrontRight")) rrFR = v;
            if (prop.Contains("roadrumble.RearLeft"))   rrRL = v;
            if (prop.Contains("roadrumble.RearRight"))  rrRR = v;

            if (prop.Contains("roadimpacts.FrontLeft"))  riFL = v;
            if (prop.Contains("roadimpacts.FrontRight")) riFR = v;
            if (prop.Contains("roadimpacts.RearLeft"))   riRL = v;
            if (prop.Contains("roadimpacts.RearRight"))  riRR = v;

            if (prop.Contains("lateralgforce.Left"))  latL = v;
            if (prop.Contains("lateralgforce.Right")) latR = v;

            if (prop.Contains("accelgforce.Rear"))  accelG = v;
            if (prop.Contains("decelgforce.Front")) decelG = v;

            if (prop.Contains("rpms")) rpm = v;
            if (prop.Contains("gearshift")) gearShift = v;
            if (prop.Contains("geargrinding")) gearGrind = v;
            if (prop.Contains("missedgear")) missGear = v;

            if (prop.Contains("staticwind")) wind = v;
            if (prop.Contains("speedwithcurving.Left"))  speedL = v;
            if (prop.Contains("speedwithcurving.Right")) speedR = v;
            if (prop.Contains("speed.All")) speed = v;

            if (prop.Contains("tractionloss.Left"))  tlL = v;
            if (prop.Contains("tractionloss.Right")) tlR = v;

            //---------------------------------------------------------
            // BUILD 12 NORMALIZED, WEIGHTED CHANNELS
            //---------------------------------------------------------

            // Option A: LEFT Joy-Con receives left-side physics
            //          RIGHT Joy-Con receives right-side physics

            double baseL = 
                rvFL * 0.25 + rvRL * 0.25 +
                rrFL * 0.20 + rrRL * 0.20 +
                speedL * 0.05;

            double baseR =
                rvFR * 0.25 + rvRR * 0.25 +
                rrFR * 0.20 + rrRR * 0.20 +
                speedR * 0.05;

            double slipL = (slipFL + slipRL) * 0.50 + tlL * 0.40;
            double slipR = (slipFR + slipRR) * 0.50 + tlR * 0.40;

            double impactL =
                riFL * 0.50 + riRL * 0.50 +
                lockFL * 0.30 + lockRL * 0.30 +
                absAct * 0.50;

            double impactR =
                riFR * 0.50 + riRR * 0.50 +
                lockFR * 0.30 + lockRR * 0.30 +
                absAct * 0.50;

            double engine =
                (rpm / 8000.0) * 400 +
                gearShift * 200 +
                gearGrind * 150 +
                missGear * 300;

            double brake = decelG * 200 + absAct * 400;
            double accel = accelG * 250;

            double aeroLeft  = wind * 150 + speedL * 0.05;
            double aeroRight = wind * 150 + speedR * 0.05;

            double global =
                (tlL + tlR) * 120 +
                speed * 0.04;

            //---------------------------------------------------------
            // COMPRESS & SMOOTH
            //---------------------------------------------------------
            sBaseL   = Smooth(sBaseL,   Compress(baseL),   0.18);
            sBaseR   = Smooth(sBaseR,   Compress(baseR),   0.18);

            sSlipL   = Smooth(sSlipL,   Compress(slipL),   0.22);
            sSlipR   = Smooth(sSlipR,   Compress(slipR),   0.22);

            sImpactL = Smooth(sImpactL, Compress(impactL), 0.12);
            sImpactR = Smooth(sImpactR, Compress(impactR), 0.12);

            sEngine  = Smooth(sEngine,  Compress(engine),  0.06);

            sBrake   = Smooth(sBrake,   Compress(brake),   0.15);
            sAccel   = Smooth(sAccel,   Compress(accel),   0.15);

            sAeroL   = Smooth(sAeroL,   Compress(aeroLeft), 0.15);
            sAeroR   = Smooth(sAeroR,   Compress(aeroRight),0.15);

            sGlobal  = Smooth(sGlobal,  Compress(global),  0.10);

            //---------------------------------------------------------
            // SEND UDP PACKET
            //---------------------------------------------------------
            byte[] pkt = new byte[24];
            WriteU16(pkt, 0,  (int)sBaseL);
            WriteU16(pkt, 2,  (int)sBaseR);
            WriteU16(pkt, 4,  (int)sSlipL);
            WriteU16(pkt, 6,  (int)sSlipR);
            WriteU16(pkt, 8,  (int)sImpactL);
            WriteU16(pkt, 10, (int)sImpactR);
            WriteU16(pkt, 12, (int)sEngine);
            WriteU16(pkt, 14, (int)sBrake);
            WriteU16(pkt, 16, (int)sAccel);
            WriteU16(pkt, 18, (int)sAeroL);
            WriteU16(pkt, 20, (int)sAeroR);
            WriteU16(pkt, 22, (int)sGlobal);

            udp.Send(pkt, pkt.Length);

            //---------------------------------------------------------
            // DEBUG PRINT
            //---------------------------------------------------------
            Console.WriteLine(
                $"L({(int)sBaseL},{(int)sSlipL},{(int)sImpactL},{(int)sAeroL})  " +
                $"R({(int)sBaseR},{(int)sSlipR},{(int)sImpactR},{(int)sAeroR})  " +
                $"ENG={(int)sEngine} BRK={(int)sBrake} ACC={(int)sAccel} GBL={(int)sGlobal}"
            );
        }
    }
}
