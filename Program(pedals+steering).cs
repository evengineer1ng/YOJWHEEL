using System;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;
using vJoyInterfaceWrap;

namespace PiController
{
    class Program
    {
        static vJoy joy = new vJoy();
        static uint id = 1;

        static string piIP = "10.0.0.120";

        const int PORT_STEER  = 5002;
        const int PORT_PEDALS = 6000;
        const int PORT_JOYCON = 6009;

        // ==========================
        // Shared latest-state storage
        // ==========================
        static volatile int steer;

        static volatile ushort throttle, brake, clutch;

        static volatile ushort imu, lsx, lsy, rsx, rsy;
        static volatile uint buttons;

        static CancellationTokenSource cts = new CancellationTokenSource();

        static async Task Main()
        {
            Console.WriteLine("=== Combined vJoy Input Receiver ===");

            if (!joy.vJoyEnabled() || !joy.AcquireVJD(id))
            {
                Console.WriteLine("vJoy init failed");
                return;
            }

            Console.WriteLine("[vJoy] Device acquired");

            _ = Task.Run(() => SteerListener(cts.Token));
            _ = Task.Run(() => PedalListener(cts.Token));
            _ = Task.Run(() => JoyconListener(cts.Token));
            _ = Task.Run(() => VJoyUpdateLoop(cts.Token));

            Console.WriteLine("Running. CTRL+C to exit.");
            await Task.Delay(Timeout.Infinite);
        }

        // ===================================================
        // vJoy single writer loop (CRITICAL FIX)
        // ===================================================
        static async Task VJoyUpdateLoop(CancellationToken ct)
        {
            var delay = TimeSpan.FromMilliseconds(2); // ~500 Hz

            while (!ct.IsCancellationRequested)
            {
                joy.SetAxis(steer,    id, HID_USAGES.HID_USAGE_X);

                joy.SetAxis(throttle, id, HID_USAGES.HID_USAGE_Y);
                joy.SetAxis(brake,    id, HID_USAGES.HID_USAGE_Z);
                joy.SetAxis(clutch,   id, HID_USAGES.HID_USAGE_RX);

                joy.SetAxis(imu,      id, HID_USAGES.HID_USAGE_RY);
                joy.SetAxis(lsx,      id, HID_USAGES.HID_USAGE_SL0);
                joy.SetAxis(lsy,      id, HID_USAGES.HID_USAGE_SL1);
                joy.SetAxis(32767,    id, HID_USAGES.HID_USAGE_RZ);

                // DPAD
                int dz = 8000;
                joy.SetBtn(rsy < 32767 - dz, id, 29);
                joy.SetBtn(rsy > 32767 + dz, id, 30);
                joy.SetBtn(rsx < 32767 - dz, id, 31);
                joy.SetBtn(rsx > 32767 + dz, id, 32);

                for (int i = 0; i < 28; i++)
                    joy.SetBtn(((buttons >> i) & 1) != 0, id, (uint)(i + 1));

                await Task.Delay(delay, ct);
            }
        }

        // ===================================================
        // STEER
        // ===================================================
        static async Task SteerListener(CancellationToken ct)
        {
            using var udp = CreateUdp(PORT_STEER);
            Console.WriteLine($"[STEER] {PORT_STEER}");

            while (!ct.IsCancellationRequested)
            {
                var r = await udp.ReceiveAsync(ct);
                if (!r.RemoteEndPoint.Address.ToString().Equals(piIP)) continue;
                if (r.Buffer.Length != 2) continue;

                ushort raw = (ushort)(r.Buffer[0] | (r.Buffer[1] << 8));
                steer = raw >> 1;
            }
        }

        // ===================================================
        // PEDALS
        // ===================================================
        static async Task PedalListener(CancellationToken ct)
        {
            using var udp = CreateUdp(PORT_PEDALS);
            Console.WriteLine($"[PED] {PORT_PEDALS}");

            while (!ct.IsCancellationRequested)
            {
                var r = await udp.ReceiveAsync(ct);
                if (r.Buffer.Length != 6) continue;

                throttle = BitConverter.ToUInt16(r.Buffer, 0);
                brake    = BitConverter.ToUInt16(r.Buffer, 2);
                clutch   = BitConverter.ToUInt16(r.Buffer, 4);
            }
        }

        // ===================================================
        // JOYCON
        // ===================================================
        static async Task JoyconListener(CancellationToken ct)
        {
            using var udp = CreateUdp(PORT_JOYCON);
            Console.WriteLine($"[JOYCON] {PORT_JOYCON}");

            while (!ct.IsCancellationRequested)
            {
                var r = await udp.ReceiveAsync(ct);
                if (!r.RemoteEndPoint.Address.ToString().Equals(piIP)) continue;
                if (r.Buffer.Length != 18) continue;

                imu = BitConverter.ToUInt16(r.Buffer, 0);
                lsx = BitConverter.ToUInt16(r.Buffer, 2);
                lsy = BitConverter.ToUInt16(r.Buffer, 4);
                rsx = BitConverter.ToUInt16(r.Buffer, 6);
                rsy = BitConverter.ToUInt16(r.Buffer, 8);

                buttons =
                    (uint)r.Buffer[12] |
                    ((uint)r.Buffer[13] << 8) |
                    ((uint)r.Buffer[14] << 16) |
                    ((uint)r.Buffer[15] << 24);
            }
        }

        static UdpClient CreateUdp(int port)
        {
            var udp = new UdpClient(port);
            udp.Client.ReceiveBufferSize = 1 << 20; // 1 MB
            udp.Client.SendBufferSize    = 1 << 20;
            return udp;
        }
    }
}
