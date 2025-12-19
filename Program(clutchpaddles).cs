using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using vJoyInterfaceWrap;

class ClutchVJoy
{
    const int PORT = 5010;
    const uint VJOY_ID = 4;

    // Adjust these to your actual raw ranges
    const int H1_MIN = 2600;
    const int H1_MAX = 2800;
    const int H2_MIN = 2600;
    const int H2_MAX = 2800;

    // 🔧 Strong noise suppression (no latency)
    const int DEADZONE = 450;     // ↑ increased
    const int LOCK_ZONE = 250;    // snap-to-rest threshold

    static int lastX = -1;
    static int lastY = -1;

    static void Main()
    {
        vJoy joystick = new vJoy();

        if (!joystick.vJoyEnabled())
        {
            Console.WriteLine("vJoy not enabled");
            return;
        }

        if (!joystick.AcquireVJD(VJOY_ID))
        {
            Console.WriteLine("Failed to acquire vJoy device");
            return;
        }

        TcpListener listener = new TcpListener(IPAddress.Any, PORT);
        listener.Start();
        Console.WriteLine("Waiting for clutch stream...");

        using TcpClient client = listener.AcceptTcpClient();
        Console.WriteLine("Clutch connected");

        using NetworkStream stream = client.GetStream();

        byte[] buffer = new byte[512];
        StringBuilder lineBuf = new StringBuilder();

        while (true)
        {
            int n = stream.Read(buffer, 0, buffer.Length);
            if (n <= 0)
                break;

            string chunk = Encoding.ASCII.GetString(buffer, 0, n);

            foreach (char c in chunk)
            {
                if (c == '\n')
                {
                    ProcessLine(lineBuf.ToString(), joystick);
                    lineBuf.Clear();
                }
                else
                {
                    lineBuf.Append(c);
                }
            }
        }
    }

    static void ProcessLine(string line, vJoy joystick)
    {
        if (!TryExtractRaw(line, "H1 raw=", out int h1))
            return;

        if (!TryExtractRaw(line, "H2 raw=", out int h2))
            return;

        int x = Scale(h1, H1_MIN, H1_MAX);
        int y = Scale(h2, H2_MIN, H2_MAX);

        // Invert axes
        x = 32767 - x;
        y = 32767 - y;

        x = ApplyNoiseGate(x, ref lastX);
        y = ApplyNoiseGate(y, ref lastY);

        joystick.SetAxis(x, VJOY_ID, HID_USAGES.HID_USAGE_X);
        joystick.SetAxis(y, VJOY_ID, HID_USAGES.HID_USAGE_Y);
    }

    static int ApplyNoiseGate(int value, ref int last)
    {
        // First update
        if (last < 0)
        {
            last = value;
            return value;
        }

        int delta = Math.Abs(value - last);

        // Hard lock when near stable position
        if (delta < LOCK_ZONE)
            return last;

        // Ignore small jitter
        if (delta < DEADZONE)
            return last;

        // Accept real movement instantly
        last = value;
        return value;
    }

    static bool TryExtractRaw(string line, string key, out int value)
    {
        value = 0;
        int idx = line.IndexOf(key);
        if (idx < 0)
            return false;

        idx += key.Length;
        int end = idx;

        while (end < line.Length && char.IsDigit(line[end]))
            end++;

        return int.TryParse(line.Substring(idx, end - idx), out value);
    }

    static int Scale(int raw, int min, int max)
    {
        int v = (raw - min) * 32767 / (max - min);
        return Math.Clamp(v, 0, 32767);
    }
}
