#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <termios.h>
#include <string.h>
#include <sys/socket.h>
#include <arpa/inet.h>

#define SERIAL_PORT "/dev/ttyUSB0"
#define BAUDRATE B115200

#define PC_IP   "10.0.0.70"
#define PC_PORT 5010

#define BUF_SIZE 512
#define RECONNECT_DELAY 2


int open_serial(const char *device)
{
    int fd = open(device, O_RDONLY | O_NOCTTY);
    if (fd < 0) {
        perror("open serial");
        return -1;
    }

    struct termios tty;
    tcgetattr(fd, &tty);

    cfsetispeed(&tty, BAUDRATE);
    cfsetospeed(&tty, BAUDRATE);

    tty.c_cflag = (tty.c_cflag & ~CSIZE) | CS8;
    tty.c_cflag |= (CLOCAL | CREAD);
    tty.c_cflag &= ~(PARENB | CSTOPB | CRTSCTS);

    tty.c_lflag = 0;   // raw
    tty.c_iflag = 0;
    tty.c_oflag = 0;

    tty.c_cc[VMIN]  = 1;
    tty.c_cc[VTIME] = 0;

    tcsetattr(fd, TCSANOW, &tty);
    return fd;
}


int connect_socket(void)
{
    int sock;
    struct sockaddr_in addr;

    while (1) {
        sock = socket(AF_INET, SOCK_STREAM, 0);
        if (sock < 0) {
            perror("socket");
            sleep(RECONNECT_DELAY);
            continue;
        }

        memset(&addr, 0, sizeof(addr));
        addr.sin_family = AF_INET;
        addr.sin_port = htons(PC_PORT);
        inet_pton(AF_INET, PC_IP, &addr.sin_addr);

        if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) == 0) {
            printf("[OK] Connected to %s:%d\n", PC_IP, PC_PORT);
            return sock;
        }

        perror("connect");
        close(sock);
        sleep(RECONNECT_DELAY);
    }
}


int send_all(int sock, const char *buf, int len)
{
    int sent = 0;
    while (sent < len) {
        int n = send(sock, buf + sent, len - sent, 0);
        if (n <= 0)
            return -1;
        sent += n;
    }
    return 0;
}


int main(void)
{
    char buf[BUF_SIZE];

    int serial_fd = open_serial(SERIAL_PORT);
    if (serial_fd < 0)
        return 1;

    int sock = connect_socket();

    printf("[INFO] Raw serial stream forwarding\n");

    while (1) {
        int n = read(serial_fd, buf, sizeof(buf));
        if (n <= 0)
            continue;

        /* Write EXACT serial bytes to console */
        write(STDOUT_FILENO, buf, n);

        /* Forward EXACT serial bytes to PC */
        if (send_all(sock, buf, n) < 0) {
            perror("send");
            close(sock);
            sock = connect_socket();
        }
    }

    return 0;
}
