#include <stdio.h>
#include <stdint.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <linux/input.h>
#include <arpa/inet.h>

#define EVENT_DEV "/dev/input/event0"
#define PC_IP "10.0.0.70"
#define PC_PORT 6000

int main() {
    int fd = open(EVENT_DEV, O_RDONLY);
    if (fd < 0) {
        printf("Cannot open %s\n", EVENT_DEV);
        return 1;
    }

    int sock = socket(AF_INET, SOCK_DGRAM, 0);

    struct sockaddr_in pc;
    pc.sin_family = AF_INET;
    pc.sin_port = htons(PC_PORT);
    inet_pton(AF_INET, PC_IP, &pc.sin_addr);

    uint16_t throttle=0, brake=0, clutch=0;

    struct input_event ev;
    printf("[READY] Pedals streaming from %s to %s:%d\n",
           EVENT_DEV, PC_IP, PC_PORT);

    while (1) {
        read(fd, &ev, sizeof(ev));

        if (ev.type == EV_ABS) {
            if (ev.code == ABS_X) throttle = ev.value;
            if (ev.code == ABS_Y) brake    = ev.value;
            if (ev.code == ABS_Z) clutch   = ev.value;

            uint8_t pkt[6] = {
                throttle & 0xFF, throttle >> 8,
                brake    & 0xFF, brake    >> 8,
                clutch   & 0xFF, clutch   >> 8
            };

            sendto(sock, pkt, 6, 0,
                   (struct sockaddr*)&pc, sizeof(pc));

            printf("T=%5u  B=%5u  C=%5u\n", throttle, brake, clutch);
        }
    }
}
