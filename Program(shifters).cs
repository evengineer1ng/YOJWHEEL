using System;
using System.Net;
using System.Net.Sockets;
using vJoyInterfaceWrap;

class Program
{
    // =====================
    // CONFIG
    // =====================
    const uint   VJOY_ID   = 3;
    const int    UDP_PORT = 7001;
    const string PI_IP    = "10.0.0.120";

    // vJoy button numbers
    const uint BTN_UP       = 25;
    const uint BTN_DOWN     = 26;
    const uint BTN_CLUTCH_L = 27;
    const uint BTN_CLUTCH_R = 28;
    const uint BTN_5        = 29;
    const uint BTN_6        = 30;

    static byte currentMask = 0;

    static void Main()
    {
        var joy = new vJoy();

        Console.WriteLine("=== Shifter → vJoy #3 ===");
        Console.WriteLine($"Accepting packets only from {PI_IP}");

        if (!joy.vJoyEnabled())
        {
            Console.WriteLine("ERROR: vJoy not enabled");
            return;
        }

        if (!joy.AcquireVJD(VJOY_ID))
        {
            Console.WriteLine("ERROR: Cannot acquire vJoy device #3");
            return;
        }

        Console.WriteLine("vJoy #3 acquired");
        Console.WriteLine($"Listening UDP:{UDP_PORT}");

        using var udp = new UdpClient(UDP_PORT);
        var ep = new IPEndPoint(IPAddress.Any, 0);

        while (true)
        {
            try
            {
                byte[] data = udp.Receive(ref ep);

                // ---------------------
                // SOURCE FILTER
                // ---------------------
                if (ep.Address.ToString() != PI_IP)
                    continue;

                if (data.Length < 1)
                    continue;

                currentMask = data[0];

                PushToVJoy(joy);
            }
            catch
            {
                // swallow errors, keep running
            }
        }
    }

    static void PushToVJoy(vJoy joy)
    {
        // Buttons 1–6 from Pi → vJoy buttons
        joy.SetBtn((currentMask & (1 << 0)) != 0, VJOY_ID, BTN_UP);
        joy.SetBtn((currentMask & (1 << 1)) != 0, VJOY_ID, BTN_DOWN);

        // DO NOT TOUCH CLUTCH LOGIC
        joy.SetBtn((currentMask & (1 << 2)) != 0, VJOY_ID, BTN_CLUTCH_L);
        joy.SetBtn((currentMask & (1 << 3)) != 0, VJOY_ID, BTN_CLUTCH_R);

        joy.SetBtn((currentMask & (1 << 4)) != 0, VJOY_ID, BTN_5);
        joy.SetBtn((currentMask & (1 << 5)) != 0, VJOY_ID, BTN_6);
    }
}
