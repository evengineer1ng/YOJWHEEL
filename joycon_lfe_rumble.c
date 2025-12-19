#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/hidraw.h>
#include <sys/socket.h>
#include <arpa/inet.h>

#define LEFT_PID  0x2006
#define RIGHT_PID 0x2007
#define VENDOR_NINTENDO 0x057E

#define UDP_PORT 5005

int left_fd = -1;
int right_fd = -1;

// ==========================
// Encode amplitude into HD Rumble (proper format)
// ==========================
void build_rumble_packet(uint8_t *dst, float amp)
{
    if (amp < 0) amp = 0;
    if (amp > 1) amp = 1;

    // Nintendo rumble amplitude encoding
    uint16_t encoded_amp = (uint16_t)(amp * 0xFFFF);

    // Standard frequency pair (Nintendo default)
    uint16_t freq_low  = 0x00F0; 
    uint16_t freq_high = 0x00C8;

    dst[0] = freq_low & 0xFF;
    dst[1] = (freq_low >> 8) & 0xFF;

    dst[2] = encoded_amp & 0xFF;
    dst[3] = (encoded_amp >> 8) & 0xFF;

    dst[4] = freq_high & 0xFF;
    dst[5] = (freq_high >> 8) & 0xFF;

    dst[6] = encoded_amp & 0xFF;
    dst[7] = (encoded_amp >> 8) & 0xFF;
}

void send_rumble(int fd, float amp)
{
    if (fd < 0) return;

    uint8_t rumble_data[8];
    uint8_t packet[10];

    build_rumble_packet(rumble_data, amp);

    packet[0] = 0x10; // rumble subcommand
    packet[1] = 0x00;

    memcpy(&packet[2], rumble_data, 8);

    write(fd, packet, 10);
}

// ==========================
// Try opening Joy-Con
// ==========================
int try_open_joycon(const char *path, int *is_left, int *is_right)
{
    int fd = open(path, O_RDWR | O_NONBLOCK);
    if (fd < 0) return -1;

    struct hidraw_devinfo info;

    if (ioctl(fd, HIDIOCGRAWINFO, &info) < 0) {
        close(fd);
        return -1;
    }

    if (info.vendor == VENDOR_NINTENDO) {
        if (info.product == LEFT_PID) {
            *is_left = 1;
            return fd;
        }
        if (info.product == RIGHT_PID) {
            *is_right = 1;
            return fd;
        }
    }

    close(fd);
    return -1;
}

// ==========================
// Scan /dev/hidraw*
// ==========================
void find_joycons()
{
    char path[64];

    for (int i = 0; i < 32; i++) {
        snprintf(path, sizeof(path), "/dev/hidraw%d", i);

        int is_left = 0, is_right = 0;
        int fd = try_open_joycon(path, &is_left, &is_right);

        if (fd >= 0) {
            if (is_left) {
                left_fd = fd;
                printf("Found LEFT Joy-Con at %s\n", path);
            }
            if (is_right) {
                right_fd = fd;
                printf("Found RIGHT Joy-Con at %s\n", path);
            }
        }
    }
}

// ==========================
// MAIN
// ==========================
int main()
{
    find_joycons();

    if (left_fd < 0 && right_fd < 0) {
        printf("No Joy-Cons found.\n");
        return 1;
    }

    int sock = socket(AF_INET, SOCK_DGRAM, 0);

    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port = htons(UDP_PORT),
        .sin_addr.s_addr = INADDR_ANY
    };

    bind(sock, (struct sockaddr *)&addr, sizeof(addr));

    printf("Listening for rumble amplitudes on UDP port %d\n", UDP_PORT);

    char buf[64];

    while (1) {
        int len = recv(sock, buf, 63, 0);
        if (len <= 0) continue;

        buf[len] = 0;
        float amp = atof(buf);

        send_rumble(left_fd, amp);
        send_rumble(right_fd, amp);
    }

    return 0;
}
