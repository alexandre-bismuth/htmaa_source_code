#pragma once
struct mallinfo { int arena, ordblks, uordblks, fordblks; };
inline struct mallinfo mallinfo() { return {0, 0, 0, 0}; }
