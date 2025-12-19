#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <dirent.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <linux/input.h>
#include <sys/ioctl.h>
#include <stdint.h>

#define DEST_IP   "10.0.0.70"
#define DEST_PORT 6001

#define LEFT_NAME   "Joy-Con (L)"
#define RIGHT_NAME  "Joy-Con (R)"
#define IMU_NAME    "Joy-Con (R) (IMU)"

// Generic event finder:
//  - looks for devices whose name contains `target`
//  - if ignore_imu is non-zero, it will SKIP any device whose name also contains "IMU"
static int find_event(const char *target, int ignore_imu) {
    DIR *dir = opendir("/dev/input");
    if (!dir) return -1;

    struct dirent *de;
    char path[256], name[256];
    int fd = -1;

    while ((de = readdir(dir))) {
        if (strncmp(de->d_name, "event", 5) != 0) continue;

        // limit d_name to avoid truncation warning, 100 is plenty
        snprintf(path, sizeof(path), "/dev/input/%.100s", de->d_name);
        int tfd = open(path, O_RDONLY | O_NONBLOCK);
        if (tfd < 0) continue;

        if (ioctl(tfd, EVIOCGNAME(sizeof(name)), name) >= 0) {
            if (strstr(name, target)) {
                if (ignore_imu && strstr(name, "IMU")) {
                    // skip IMU variants when we want the main controller
                    close(tfd);
                    continue;
                }
                printf("Matched \"%s\" → %s (name=\"%s\")\n", target, path, name);
                fd = tfd;
                break;
            }
        }
        close(tfd);
    }

    closedir(dir);
    return fd;
}

// More specific finder for IMU: must match both target and "IMU"
static int find_imu(const char *target_prefix) {
    DIR *dir = opendir("/dev/input");
    if (!dir) return -1;

    struct dirent *de;
    char path[256], name[256];
    int fd = -1;

    while ((de = readdir(dir))) {
        if (strncmp(de->d_name, "event", 5) != 0) continue;

        snprintf(path, sizeof(path), "/dev/input/%.100s", de->d_name);
        int tfd = open(path, O_RDONLY | O_NONBLOCK);
        if (tfd < 0) continue;

        if (ioctl(tfd, EVIOCGNAME(sizeof(name)), name) >= 0) {
            if (strstr(name, target_prefix) && strstr(name, "IMU")) {
                printf("Matched IMU \"%s\" → %s (name=\"%s\")\n",
                       target_prefix, path, name);
                fd = tfd;
                break;
            }
        }
        close(tfd);
    }

    closedir(dir);
    return fd;
}

int main() {
    // Left uses name match and ignores IMU variants
    int fd_left  = find_event(LEFT_NAME, 1);
    // Right uses name match and ignores IMU variants
    int fd_right = find_event(RIGHT_NAME, 1);
    // IMU: specifically look for the right Joy-Con IMU
    int fd_imu   = find_imu(RIGHT_NAME);

    if (fd_left < 0 || fd_right < 0 || fd_imu < 0) {
        printf("Could not find all Joy-Con devices.\n");
        return 1;
    }

    printf("Joy-Con devices connected.\n");

    int sock = socket(AF_INET, SOCK_DGRAM, 0);

    struct sockaddr_in dest = {
        .sin_family = AF_INET,
        .sin_port   = htons(DEST_PORT),
    };
    inet_pton(AF_INET, DEST_IP, &dest.sin_addr);

    int16_t imu = 0;
    int16_t lsx = 0, lsy = 0;
    int16_t rsx = 0, rsy = 0;
    uint32_t buttons = 0;

    int16_t prev_imu = 0;
    int16_t prev_lsx = 0, prev_lsy = 0;
    int16_t prev_rsx = 0, prev_rsy = 0;
    uint32_t prev_buttons = 0;

    struct input_event ev;

    printf("Streaming raw Joy-Con input...\n");

    while (1) {

        // LEFT JOY-CON EVENTS
        while (read(fd_left, &ev, sizeof(ev)) == sizeof(ev)) {
            if (ev.type == EV_KEY) {
                if (ev.value)
                    buttons |= (1u << ev.code);
                else
                    buttons &= ~(1u << ev.code);
            }
            if (ev.type == EV_ABS) {
                if (ev.code == ABS_X) lsx = ev.value;
                if (ev.code == ABS_Y) lsy = ev.value;
            }
        }

        // RIGHT JOY-CON EVENTS
        while (read(fd_right, &ev, sizeof(ev)) == sizeof(ev)) {
            if (ev.type == EV_KEY) {
                int bit = ev.code + 16;
                if (ev.value)
                    buttons |= (1u << bit);
                else
                    buttons &= ~(1u << bit);
            }
            if (ev.type == EV_ABS) {
                if (ev.code == ABS_X) rsx = ev.value;
                if (ev.code == ABS_Y) rsy = ev.value;
            }
        }

        // IMU EVENTS
        while (read(fd_imu, &ev, sizeof(ev)) == sizeof(ev)) {
            if (ev.type == EV_ABS && ev.code == ABS_Y) {
                imu = ev.value;
            }
        }

        // PRINT ANY CHANGES (debug)
        if (imu != prev_imu) {
            printf("[IMU] %d\n", imu);
            prev_imu = imu;
        }
        if (lsx != prev_lsx || lsy != prev_lsy) {
            printf("[LS] X=%d Y=%d\n", lsx, lsy);
            prev_lsx = lsx; prev_lsy = lsy;
        }
        if (rsx != prev_rsx || rsy != prev_rsy) {
            printf("[RS] X=%d Y=%d\n", rsx, rsy);
            prev_rsx = rsx; prev_rsy = rsy;
        }
        if (buttons != prev_buttons) {
            printf("[BTN] mask=%08X\n", buttons);
            prev_buttons = buttons;
        }

        // BUILD 32-BYTE PACKET
        uint8_t packet[32] = {0};
        memcpy(packet,      &imu,     2);
        memcpy(packet + 2,  &lsx,     2);
        memcpy(packet + 4,  &lsy,     2);
        memcpy(packet + 6,  &rsx,     2);
        memcpy(packet + 8,  &rsy,     2);
        memcpy(packet + 10, &buttons, 4);

        sendto(sock, packet, 32, 0, (struct sockaddr*)&dest, sizeof(dest));

        usleep(1000); // 1ms loop = up to 1000Hz update rate
    }

    return 0;
}
