#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <dirent.h>
#include <fcntl.h>
#include <unistd.h>
#include <linux/hidraw.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <math.h>

#define PORT 6002
#define PACKET_SIZE 24

#define NINTENDO_VID 0x057E
#define JOYCON_LEFT_PID  0x2006
#define JOYCON_RIGHT_PID 0x2007

//-------------------------------------------------------------
// Utility
//-------------------------------------------------------------
static inline float clamp01(float x)
{
    return (x < 0 ? 0 : (x > 1 ? 1 : x));
}

static inline uint16_t read_u16(uint8_t *p)
{
    return p[0] | (p[1] << 8);
}

//-------------------------------------------------------------
// Exponential smoothing filter
//-------------------------------------------------------------
static inline float smooth(float prev, float cur, float factor)
{
    return prev + (cur - prev) * factor;
}

//-------------------------------------------------------------
// Attack/Release Envelope
//-------------------------------------------------------------
static inline float envelope(float prev, float input, float attack, float release)
{
    if (input > prev)
        return prev + (input - prev) * attack;
    else
        return prev + (input - prev) * release;
}

//-------------------------------------------------------------
// HD Rumble Encoding
//-------------------------------------------------------------
void encode_rumble(float amp, float freq, uint8_t out[4])
{
    // Clamp & limit Joy-Con safe frequency range
    if (freq < 40)  freq = 40;
    if (freq > 1200) freq = 1200;

    float lowHz  = freq;
    float highHz = freq * 0.5f;

    uint16_t lowEnc =
        (uint16_t)(log2f(lowHz  / 10.0f) * 32.0f);

    uint16_t highEnc =
        (uint16_t)(log2f(highHz / 10.0f) * 32.0f);

    uint16_t ampEnc = (uint16_t)(amp * 0x7FFF);

    out[0] = lowEnc & 0xFF;
    out[1] = ((lowEnc >> 8) & 0xFF) | ((ampEnc >> 8) & 0x7F);
    out[2] = highEnc & 0xFF;
    out[3] = (highEnc >> 8) & 0xFF;
}

//-------------------------------------------------------------
// Send rumble packet
//-------------------------------------------------------------
void joycon_rumble_send(int fd, uint8_t seq, float amp, float freq)
{
    uint8_t rumble[4];
    encode_rumble(amp, freq, rumble);

    uint8_t out[10] = {
        0x10, seq,
        rumble[0], rumble[1], rumble[2], rumble[3],
        rumble[0], rumble[1], rumble[2], rumble[3]
    };

    write(fd, out, sizeof(out));
}

//-------------------------------------------------------------
// HID Discovery
//-------------------------------------------------------------
int find_hidraw_by_pid(uint16_t targetPID)
{
    DIR *d = opendir("/dev");
    if (!d) return -1;

    struct dirent *ent;
    while ((ent = readdir(d)))
    {
        if (strncmp(ent->d_name, "hidraw", 6) != 0)
            continue;

        char devPath[64];
        snprintf(devPath, sizeof(devPath), "/dev/%s", ent->d_name);

        int fd = open(devPath, O_RDWR | O_NONBLOCK);
        if (fd < 0) continue;

        struct hidraw_devinfo info = {0};
        if (ioctl(fd, HIDIOCGRAWINFO, &info) >= 0)
        {
            if (info.vendor == NINTENDO_VID && info.product == targetPID)
            {
                printf("[FOUND] %s (PID %04X)\n", devPath, info.product);
                closedir(d);
                return fd;
            }
        }
        close(fd);
    }
    closedir(d);
    return -1;
}

//-------------------------------------------------------------
// MAIN
//-------------------------------------------------------------
int main()
{
    printf("=== Optimized Joy-Con HD Rumble Daemon ===\n");

    //---------------------------------------------------------
    // Find Joy-Cons
    //---------------------------------------------------------
    int leftFd = -1, rightFd = -1;

    while (leftFd < 0 || rightFd < 0)
    {
        if (leftFd < 0)
            leftFd = find_hidraw_by_pid(JOYCON_LEFT_PID);

        if (rightFd < 0)
            rightFd = find_hidraw_by_pid(JOYCON_RIGHT_PID);

        if (leftFd < 0 || rightFd < 0)
        {
            printf("[WAIT] Searching...\n");
            sleep(1);
        }
    }

    printf("[OK] Left FD  = %d\n", leftFd);
    printf("[OK] Right FD = %d\n", rightFd);

    //---------------------------------------------------------
    // UDP Setup
    //---------------------------------------------------------
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port   = htons(PORT),
        .sin_addr.s_addr = INADDR_ANY
    };
    bind(sock, (struct sockaddr*)&addr, sizeof(addr));

    uint8_t buf[PACKET_SIZE];
    uint8_t seq = 0;

    //---------------------------------------------------------
    // Filter state
    //---------------------------------------------------------
    float fAmpL = 0, fAmpR = 0;
    float fFreqL = 120, fFreqR = 120;

    float envImpactL = 0, envImpactR = 0;
    float envSlipL = 0, envSlipR = 0;

    printf("[READY] Listening for smoothed haptics...\n");

    //---------------------------------------------------------
    // MAIN LOOP
    //---------------------------------------------------------
    while (1)
    {
        int n = recv(sock, buf, PACKET_SIZE, 0);
        if (n != PACKET_SIZE) continue;

        // --------------------------
        // Parse 12 channels
        // --------------------------
        float baseL   = read_u16(buf+0)  / 1000.0f;
        float baseR   = read_u16(buf+2)  / 1000.0f;

        float slipL   = read_u16(buf+4)  / 1000.0f;
        float slipR   = read_u16(buf+6)  / 1000.0f;

        float impactL = read_u16(buf+8)  / 1000.0f;
        float impactR = read_u16(buf+10) / 1000.0f;

        float engine  = read_u16(buf+12) / 1000.0f;
        float brake   = read_u16(buf+14) / 1000.0f;
        float accel   = read_u16(buf+16) / 1000.0f;

        float aeroL   = read_u16(buf+18) / 1000.0f;
        float aeroR   = read_u16(buf+20) / 1000.0f;

        float global  = read_u16(buf+22) / 1000.0f;

        //---------------------------------------------------------
        // Dynamic envelopes for impacts/slip
        //---------------------------------------------------------
        envImpactL = envelope(envImpactL, impactL, 0.6f, 0.15f);
        envImpactR = envelope(envImpactR, impactR, 0.6f, 0.15f);

        envSlipL = envelope(envSlipL, slipL, 0.4f, 0.2f);
        envSlipR = envelope(envSlipR, slipR, 0.4f, 0.2f);

        //---------------------------------------------------------
        // Final amplitude mixing
        //---------------------------------------------------------
        float ampL =
            baseL * 0.30f +
            envSlipL * 0.40f +
            envImpactL * 0.50f +
            engine * 0.25f +
            brake  * 0.35f +
            accel  * 0.20f +
            aeroL  * 0.25f +
            global * 0.30f;

        float ampR =
            baseR * 0.30f +
            envSlipR * 0.40f +
            envImpactR * 0.50f +
            engine * 0.25f +
            brake  * 0.35f +
            accel  * 0.20f +
            aeroR  * 0.25f +
            global * 0.30f;

        // Soft limiter
        if (ampL > 1.0f) ampL = 1.0f - (ampL - 1.0f) * 0.4f;
        if (ampR > 1.0f) ampR = 1.0f - (ampR - 1.0f) * 0.4f;

        // Final smoothing
        fAmpL = smooth(fAmpL, ampL, 0.25f);
        fAmpR = smooth(fAmpR, ampR, 0.25f);

        //---------------------------------------------------------
        // Frequency shaping
        //---------------------------------------------------------
        float freqL =
            80.0f +
            envSlipL * 70.0f +
            envImpactL * 140.0f +
            engine * 120.0f +
            aeroL * 40.0f;

        float freqR =
            80.0f +
            envSlipR * 70.0f +
            envImpactR * 140.0f +
            engine * 120.0f +
            aeroR * 40.0f;

        // Smooth frequencies
        fFreqL = smooth(fFreqL, freqL, 0.20f);
        fFreqR = smooth(fFreqR, freqR, 0.20f);

        //---------------------------------------------------------
        // Send
        //---------------------------------------------------------
        joycon_rumble_send(leftFd,  seq++, fAmpL, fFreqL);
        joycon_rumble_send(rightFd, seq++, fAmpR, fFreqR);

        //---------------------------------------------------------
        // Debug print
        //---------------------------------------------------------
        printf("L AMP=%.2f F=%.0f | R AMP=%.2f F=%.0f\n", fAmpL, fFreqL, fAmpR, fFreqR);
    }

    return 0;
}
