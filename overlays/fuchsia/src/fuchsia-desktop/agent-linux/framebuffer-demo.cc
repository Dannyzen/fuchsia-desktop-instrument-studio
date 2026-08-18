// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <stdint.h>

#include <asm/unistd.h>
#include <linux/fb.h>
#include <linux/input.h>

#define AT_FDCWD -100
#define O_RDONLY 0
#define O_RDWR 2
#define PROT_READ 1
#define PROT_WRITE 2
#define MAP_SHARED 1
#define POLLIN 1

extern "C" void* memset(void* dest, int value, unsigned long count) {
  volatile unsigned char* out = (volatile unsigned char*)dest;
  while (count--)
    *out++ = (unsigned char)value;
  return dest;
}

static long syscall4(long number, long a1, long a2, long a3, long a4) {
  long ret;
#if defined(__x86_64__)
  register long r10 asm("r10") = a4;
  __asm__ volatile("syscall"
                   : "=a"(ret)
                   : "a"(number), "D"(a1), "S"(a2), "d"(a3), "r"(r10)
                   : "rcx", "r11", "memory");
#else
#error "The Workbench graphical proof currently targets x86_64 FEMU."
#endif
  return ret;
}

static long syscall6(long number, long a1, long a2, long a3, long a4, long a5, long a6) {
  long ret;
#if defined(__x86_64__)
  register long r10 asm("r10") = a4;
  register long r8 asm("r8") = a5;
  register long r9 asm("r9") = a6;
  __asm__ volatile("syscall"
                   : "=a"(ret)
                   : "a"(number), "D"(a1), "S"(a2), "d"(a3), "r"(r10), "r"(r8), "r"(r9)
                   : "rcx", "r11", "memory");
#else
#error "The Workbench graphical proof currently targets x86_64 FEMU."
#endif
  return ret;
}

static long sys_open(const char* path, long flags) {
  return syscall4(__NR_openat, AT_FDCWD, (long)path, flags, 0);
}
static long sys_ioctl(long fd, long request, void* value) {
  return syscall4(__NR_ioctl, fd, request, (long)value, 0);
}
static long sys_write(long fd, const void* data, long size) {
  return syscall4(__NR_write, fd, (long)data, size, 0);
}
static long sys_read(long fd, void* data, long size) {
  return syscall4(__NR_read, fd, (long)data, size, 0);
}
struct linux_pollfd {
  int fd;
  short events;
  short revents;
};
static long sys_poll(linux_pollfd* fds, long count, long timeout) {
  return syscall4(__NR_poll, (long)fds, count, timeout, 0);
}
static void* sys_mmap(long length, long fd) {
  return (void*)syscall6(__NR_mmap, 0, length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
}
static void sys_exit(int status) {
  syscall4(__NR_exit_group, status, 0, 0, 0);
  __builtin_unreachable();
}
static void fail(const char* message, int status) {
  long size = 0;
  while (message[size])
    ++size;
  sys_write(2, message, size);
  sys_write(2, "\n", 1);
  sys_exit(status);
}

static uint8_t glyph_row(char c, int row) {
  static const struct {
    char c;
    uint8_t rows[7];
  } glyphs[] = {
      {'A', {14, 17, 17, 31, 17, 17, 17}}, {'B', {30, 17, 17, 30, 17, 17, 30}},
      {'C', {14, 17, 16, 16, 16, 17, 14}}, {'E', {31, 16, 16, 30, 16, 16, 31}},
      {'F', {31, 16, 16, 30, 16, 16, 16}}, {'H', {17, 17, 17, 31, 17, 17, 17}},
      {'I', {31, 4, 4, 4, 4, 4, 31}},      {'L', {16, 16, 16, 16, 16, 16, 31}},
      {'M', {17, 27, 21, 21, 17, 17, 17}}, {'N', {17, 25, 21, 19, 17, 17, 17}},
      {'O', {14, 17, 17, 17, 17, 17, 14}}, {'R', {30, 17, 17, 30, 20, 18, 17}},
      {'S', {15, 16, 16, 14, 1, 1, 30}},   {'T', {31, 4, 4, 4, 4, 4, 4}},
      {'U', {17, 17, 17, 17, 17, 17, 14}}, {'X', {17, 17, 10, 4, 10, 17, 17}},
      {' ', {0, 0, 0, 0, 0, 0, 0}},        {'-', {0, 0, 0, 31, 0, 0, 0}},
  };
  for (unsigned i = 0; i < sizeof(glyphs) / sizeof(glyphs[0]); ++i)
    if (glyphs[i].c == c)
      return glyphs[i].rows[row];
  return 0;
}

static int text_pixel(const char* text, int px, int py, int origin_x, int origin_y, int scale) {
  if (px < origin_x || py < origin_y)
    return 0;
  int x = (px - origin_x) / scale, y = (py - origin_y) / scale;
  if (y < 0 || y >= 7)
    return 0;
  int cell = x / 6, col = x % 6;
  int length = 0;
  while (text[length])
    ++length;
  if (cell < 0 || cell >= length || col >= 5)
    return 0;
  char c = text[cell];
  return (glyph_row(c, y) >> (4 - col)) & 1;
}

[[maybe_unused]] static uint32_t pixel(int x, int y, int w, int h) {
  const uint32_t dark = 0xff17131f, panel = 0xff2b203d, cyan = 0xffffd54a, violet = 0xffc45cff,
                 white = 0xfff6f2ff;
  uint32_t color = dark;
  if (x > 42 && x < w - 42 && y > 80 && y < h - 80)
    color = panel;
  if (x > 42 && x < w - 42 && y > 80 && y < 104)
    color = cyan;
  if (x > 42 && x < w - 42 && y > h - 104 && y < h - 80)
    color = violet;
  int scale = w >= 700 ? 7 : 4;
  if (text_pixel("LINUX ON FUCHSIA", x, y, 74, 180, scale))
    color = white;
  if (text_pixel("STARNIX FRAMEBUFFER", x, y, 74, 300, scale - 1))
    color = cyan;
  int cx = w / 2, cy = h * 2 / 3, dx = x - cx, dy = y - cy;
  int r = (w < h ? w : h) / 7;
  if (dx * dx + dy * dy < r * r)
    color = (x < cx) ? cyan : violet;
  if (dx * dx + dy * dy < (r / 2) * (r / 2))
    color = dark;
  return color;
}

extern "C" __attribute__((force_align_arg_pointer)) void _start() {
  long fd = sys_open("/dev/fb0", O_RDWR);
  if (fd < 0)
    fail("FRAMEBUFFER_DEMO_OPEN_FAILED", 10);
  struct fb_var_screeninfo var = {};
  struct fb_fix_screeninfo fix = {};
  if (sys_ioctl(fd, FBIOGET_VSCREENINFO, &var) < 0)
    fail("FRAMEBUFFER_DEMO_VINFO_FAILED", 11);
  if (sys_ioctl(fd, FBIOGET_FSCREENINFO, &fix) < 0)
    fail("FRAMEBUFFER_DEMO_FINFO_FAILED", 12);
  if (var.bits_per_pixel != 32 || fix.line_length > 4096)
    fail("FRAMEBUFFER_DEMO_LAYOUT_FAILED", 13);
  uint8_t* framebuffer = (uint8_t*)sys_mmap(fix.smem_len, fd);
  if ((long)framebuffer < 0 && (long)framebuffer >= -4095)
    fail("FRAMEBUFFER_DEMO_MMAP_FAILED", 14);
  sys_write(2, "FRAMEBUFFER_DEMO_MMAP_READY\n", 28);
  for (uint32_t y = 0; y < var.yres; ++y) {
    uint32_t* row = (uint32_t*)(framebuffer + (long)y * fix.line_length);
    for (uint32_t x = 0; x < var.xres; ++x)
      row[x] = (x < var.xres / 2) ? 0xffffd54a : 0xffc45cff;
  }
  sys_write(2, "FRAMEBUFFER_DEMO_DRAW_READY\n", 28);

  long input_fd = sys_open("/dev/input/event1", O_RDONLY);
  if (input_fd < 0)
    fail("FRAMEBUFFER_DEMO_INPUT_OPEN_FAILED", 15);
  sys_write(2, "FRAMEBUFFER_DEMO_INPUT_READY\n", 29);
  linux_pollfd input_poll = {.fd = (int)input_fd, .events = POLLIN, .revents = 0};
  for (;;) {
    if (sys_poll(&input_poll, 1, -1) <= 0)
      continue;
    struct input_event event = {};
    long count = sys_read(input_fd, &event, sizeof(event));
    if (count != sizeof(event))
      continue;
    if (event.type != EV_KEY || event.value != 1)
      continue;
    for (uint32_t y = 0; y < var.yres; ++y) {
      uint32_t* row = (uint32_t*)(framebuffer + (long)y * fix.line_length);
      for (uint32_t x = 0; x < var.xres / 2; ++x)
        row[x] = 0xff87e341;
    }
    sys_write(2, "FRAMEBUFFER_DEMO_KEY_ACCEPTED\n", 30);
    for (;;)
      syscall4(__NR_pause, 0, 0, 0, 0);
  }
}
