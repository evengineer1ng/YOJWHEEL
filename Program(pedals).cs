using System;
using System.Net;
using System.Net.Sockets;
using vJoyInterfaceWrap;

namespace PedalReceiver
{
    class Program
    {
        const int PORT = 6000;
        static vJoy joystick;
        static uint id = 1;

        static void Main(string[] args)
        {
            Console.WriteLine("Pedals Receiver v1.0");
            Console.WriteLine($"Listening on UDP port {PORT}");

            // Setup vJoy
            joystick = new vJoy();

            VjdStat status = joystick.GetVJDStatus(id);
            if (status == VjdStat.VJD_STAT_FREE ||
                status == VjdStat.VJD_STAT_OWN ||
                status == VjdStat.VJD_STAT_BUSY)
            {
                if (!joystick.AcquireVJD(id))
                {
                    Console.WriteLine("Failed to acquire vJoy device!");
                    return;
                }
            }
            else
            {
                Console.WriteLine("vJoy device not found!");
                return;
            }

            // UDP listener
            UdpClient client = new UdpClient(PORT);
            IPEndPoint remoteEP = new IPEndPoint(IPAddress.Any, PORT);

            while (true)
            {
                byte[] data = client.Receive(ref remoteEP);
                if (data.Length < 6) continue;

                ushort throttle = BitConverter.ToUInt16(data, 0);
                ushort brake    = BitConverter.ToUInt16(data, 2);
                ushort clutch   = BitConverter.ToUInt16(data, 4);

                // Send to vJoy
                joystick.SetAxis(throttle, id, HID_USAGES.HID_USAGE_X);
                joystick.SetAxis(brake,    id, HID_USAGES.HID_USAGE_Y);
                joystick.SetAxis(clutch,   id, HID_USAGES.HID_USAGE_Z);

                Console.WriteLine($"T={throttle}  B={brake}  C={clutch}");
            }
        }
    }
}
