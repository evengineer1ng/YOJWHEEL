#include <libusb-1.0/libusb.h>
#include <stdio.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>
#include <fcntl.h>
#include <pthread.h>
#include <math.h>

#define VID 0x046D
#define PID 0xC260

#define FFB_PORT   5000
#define STEER_PORT 5002

#define EP_OUT 0x03  // Interrupt OUT endpoint

static libusb_device_handle *h;
static int steerSock;
static int ffbSock;
static struct sockaddr_in pc_addr;

// Last received SimHub torque & steering input
volatile int16_t latestFfb = 0;
volatile uint16_t latestSteer = 32767;
pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;


// ---- SPORTY TUNING CONSTANTS ----
static const float FFB_IDLE_BIAS   = -170.0f;
static const float FFB_DEADZONE    = 120.0f;
static const float FFB_GAIN        = 6.0f;     // increase to 7.0 if soft, reduce to 4.5 if harsh
static const float FFB_MAX_TORQUE  = 30000.0f;


//============================================================
// SEND TORQUE TO WHEEL
//============================================================
void sendFFB(int16_t force)
{
    // clamp
    if (force >  FFB_MAX_TORQUE) force =  FFB_MAX_TORQUE;
    if (force < -FFB_MAX_TORQUE) force = -FFB_MAX_TORQUE;

    uint8_t pkt[4];
    pkt[0] = 0x11;
    pkt[1] = 0xF0;                  // constant torque
    pkt[2] = force & 0xFF;
    pkt[3] = (force >> 8) & 0xFF;

    int x;
    libusb_interrupt_transfer(h, EP_OUT, pkt, sizeof(pkt), &x, 1);
}


//============================================================
// FFB THREAD — receives UDP and applies SPORTY shaping
//============================================================
void *ffbThread(void *arg)
{
    uint8_t buf[2];
    struct sockaddr_in src;
    socklen_t sl = sizeof(src);

    uint32_t lastSend = 0;
    uint32_t lastPrint = 0;

    while (1)
    {
        // Receive torque (nonblocking)
        int r = recvfrom(ffbSock, buf, 2, 0, (struct sockaddr*)&src, &sl);
        if (r == 2)
        {
            short f = (short)(buf[0] | (buf[1] << 8));
            pthread_mutex_lock(&lock);
            latestFfb = f;
            pthread_mutex_unlock(&lock);
        }

        // --- 100 Hz torque output ---
        uint32_t now = (uint32_t)(clock());
        if (now - lastSend > 10000)  // ~10ms
        {
            int16_t fCopy;
            pthread_mutex_lock(&lock);
            fCopy = latestFfb;
            pthread_mutex_unlock(&lock);

            // ---- SPORTY SHAPING ----
            float t = (float)fCopy - FFB_IDLE_BIAS;

            // deadzone
            if (t > -FFB_DEADZONE && t < FFB_DEADZONE)
                t = 0.0f;

            // normalize
            float n = t / 32767.0f;

            // gain
            float g = n * FFB_GAIN;

            // gentle non-linear shaping for crisp feel
            float s = g * (0.6f + 0.4f * fabsf(g));

            // clamp [-1..1]
            if (s >  1.0f) s =  1.0f;
            if (s < -1.0f) s = -1.0f;

            // back to wheel range
            short out = (short)(s * FFB_MAX_TORQUE);

            sendFFB(out);
            lastSend = now;
        }

        // debug print every ~100ms
        uint32_t now2 = (uint32_t)(clock());
        if (now2 - lastPrint > 100000)
        {
            printf("[FFB] in=%6d shaped=%6d\n", latestFfb, (int)(latestFfb*FFB_GAIN));
            fflush(stdout);
            lastPrint = now2;
        }

        usleep(200);
    }
}


//============================================================
// STEERING READ → UDP SEND
//============================================================
void *steerThread(void *arg)
{
    uint8_t b[64];

    while (1)
    {
        // HID GET_REPORT
        int r = libusb_control_transfer(
            h,
            0xA1,
            0x01,
            (1<<8)|0,
            0,
            b,
            sizeof(b),
            1000
        );

        if (r > 6)
        {
            uint16_t ste = (uint16_t)(b[4] | (b[5] << 8));

            pthread_mutex_lock(&lock);
            latestSteer = ste;
            pthread_mutex_unlock(&lock);

            // debug
            printf("[STEER] %5u\n", ste);
            fflush(stdout);

            // send to PC
            uint8_t pkt[2] = { ste & 0xFF, ste >> 8 };
            sendto(steerSock, pkt, 2, 0, (struct sockaddr*)&pc_addr, sizeof(pc_addr));
        }

        usleep(5000);  // ~200 Hz
    }
}


//============================================================
// MAIN
//============================================================
int main()
{
    printf("\n=== G29 SPORTY REMOTE WHEELBASE ===\n\n");

    // ---- USB ----
    libusb_init(NULL);

    h = libusb_open_device_with_vid_pid(NULL, VID, PID);
    if (!h)
    {
        printf("G29 NOT FOUND\n");
        return 1;
    }

    printf("[USB] Using HID driver (NO CLAIM, NO DETACH)\n");

    // ---- UDP STEERING OUTPUT ----
    steerSock = socket(AF_INET, SOCK_DGRAM, 0);
    memset(&pc_addr, 0, sizeof(pc_addr));
    pc_addr.sin_family = AF_INET;
    pc_addr.sin_port   = htons(STEER_PORT);
    inet_pton(AF_INET, "10.0.0.70", &pc_addr.sin_addr);  // CHANGE THIS IP

    // ---- UDP FFB INPUT ----
    ffbSock = socket(AF_INET, SOCK_DGRAM, 0);
    fcntl(ffbSock, F_SETFL, O_NONBLOCK);

    struct sockaddr_in self = {0};
    self.sin_family      = AF_INET;
    self.sin_port        = htons(FFB_PORT);
    self.sin_addr.s_addr = INADDR_ANY;
    bind(ffbSock, (struct sockaddr*)&self, sizeof(self));

    printf("[NET] Steering → PC: %d,  FFB ← PC: %d\n", STEER_PORT, FFB_PORT);
    printf("[READY] GO DRIVE!\n\n");

    pthread_t t1, t2;
    pthread_create(&t1, NULL, steerThread, NULL);
    pthread_create(&t2, NULL, ffbThread, NULL);

    while (1) usleep(20000);
}
