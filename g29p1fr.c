#include <libusb-1.0/libusb.h>
#include <stdio.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>
#include <fcntl.h>
#include <pthread.h>

#define VID 0x046D
#define PID 0xC260

#define EP_IN   0x84
#define EP_OUT  0x03

static libusb_device_handle *h;
static int steerSock;
static int ffbSock;
static struct sockaddr_in pc_addr;

volatile uint16_t latestSteer = 32767;
pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;

//====================================
// Send force to wheel (torque)
//====================================
//===================================

//====================================
int main()
{
    //~~~~~~~~ USB ~~~~~~~~
    libusb_init(NULL);

    h = libusb_open_device_with_vid_pid(NULL, VID, PID);
    if(!h){ printf("NO G29\n"); return 0; }

    if(libusb_kernel_driver_active(h,0))
        libusb_detach_kernel_driver(h,0);

    libusb_claim_interface(h, 0);

    //~~~~~~~~ NETWORK OUT steering → PC ~~~~~~~~
    steerSock = socket(AF_INET, SOCK_DGRAM, 0);

    const char *pcIp = "10.0.0.70";   // CHANGE THIS
    memset(&pc_addr, 0, sizeof(pc_addr));
    pc_addr.sin_family = AF_INET;
    pc_addr.sin_port   = htons(5002);
    inet_pton(AF_INET, pcIp, &pc_addr.sin_addr);

    //~~~~~~~~ NETWORK IN  FFB ← PC ~~~~~~~~
    ffbSock = socket(AF_INET, SOCK_DGRAM, 0);
    fcntl(ffbSock, F_SETFL, O_NONBLOCK);

    struct sockaddr_in self = {0};
    self.sin_family = AF_INET;
    self.sin_port = htons(5000);
    self.sin_addr.s_addr = INADDR_ANY;
    bind(ffbSock,(struct sockaddr*)&self,sizeof(self));
    uint8_t b[64];

    printf("\n[READY] Remote wheelbase link ACTIVE\n");

    //====================================
    while(1)
    {
        int r = libusb_control_transfer(
            h,
            0xA1,
            0x01,
            (0x01 << 8) | 0,
            0,
            b, 64,
            1000
        );

        if(r > 5)
        {
            uint16_t ste = b[4] | (b[5] << 8);

            pthread_mutex_lock(&lock);
            latestSteer = ste;
            pthread_mutex_unlock(&lock);

            // ===== DO NOT REMOVE THIS PRINT =====
            printf("[STEER] %u\n", ste);
            fflush(stdout);
            // ===== DO NOT REMOVE THIS PRINT =====

            uint8_t pkt[2] = { ste & 0xFF, ste >> 8 };
            sendto(steerSock, pkt, 2, 0,
                   (struct sockaddr*)&pc_addr,
                   sizeof(pc_addr));
        }

        usleep(500);
    }
}
