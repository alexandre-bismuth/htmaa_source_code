#pragma once
#define GPIO_IN 0
inline void gpio_pull_up(int) {}
inline void gpio_set_dir(int, int) {}
inline bool gpio_get(int) { return true; }   // pads charge instantly: never touched
