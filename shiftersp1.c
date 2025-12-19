#include <gpiod.h>
#include <stdio.h>
#include <unistd.h>
#include <string.h>
#include <arpa/inet.h>
#include <stdint.h>

#define CHIP "/dev/gpiochip4"
#define NUM_BTNS 6

// GPIO offsets on gpiochip4
unsigned int gpio_lines[NUM_BTNS] = {17, 27, 22, 23, 24, 25};

int main(void)
{
    struct gpiod_chip *chip;
    struct gpiod_line_settings *settings;
    struct gpiod_line_config *line_cfg;
    struct gpiod_request_config *req_cfg;
    struct gpiod_line_request *request;

    chip = gpiod_chip_open(CHIP);
    if (!chip) {
        perror("gpiod_chip_open");
        return 1;
    }

    settings = gpiod_line_settings_new();
    gpiod_line_settings_set_direction(settings, GPIOD_LINE_DIRECTION_INPUT);
    gpiod_line_settings_set_bias(settings, GPIOD_LINE_BIAS_PULL_UP);

    line_cfg = gpiod_line_config_new();
    gpiod_line_config_add_line_settings(
        line_cfg,
        gpio_lines,
        NUM_BTNS,
        settings
    );

    req_cfg = gpiod_request_config_new();
    gpiod_request_config_set_consumer(req_cfg, "shifters");

    request = gpiod_chip_request_lines(chip, req_cfg, line_cfg);
    if (!request) {
        perror("gpiod_chip_request_lines");
        return 1;
    }

    /* UDP setup */
    int sock = socket(AF_INET, SOCK_DGRAM, 0);

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(7001);
    inet_pton(AF_INET, "10.0.0.70", &addr.sin_addr); // Windows PC IP

    printf("Shifter sender running\n");

    uint8_t last_mask = 0xFF;

    while (1)
    {
        uint8_t mask = 0;

        /* IMPORTANT: use INDEX 0..NUM_BTNS-1 */
        for (int i = 0; i < NUM_BTNS; i++)
        {
            int val = gpiod_line_request_get_value(request, i);

            if (val == 0) // active-low
                mask |= (1 << i);
        }

        /* Print only when something changes */
        if (mask != last_mask)
        {
            printf("Buttons: ");

            for (int i = 0; i < NUM_BTNS; i++)
            {
                if ((mask ^ last_mask) & (1 << i))
                {
                    printf("B%d %s  ",
                           i + 1,
                           (mask & (1 << i)) ? "DOWN" : "UP");
                }
            }

            printf(" | mask=0b");
            for (int b = 7; b >= 0; b--)
                printf("%d", (mask >> b) & 1);
            printf("\n");

            last_mask = mask;
        }

        /* Send EXACTLY 1 byte */
        sendto(sock, &mask, 1, 0,
               (struct sockaddr*)&addr, sizeof(addr));

        usleep(1000); // 5 ms
    }
}
