#ifndef HDPACK_H
#define HDPACK_H
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define HDPACK_DTSHD   1
#define HDPACK_TRUEHD  2

typedef struct HDPacker HDPacker;
/* Called for every completed IEC61937 burst. */
typedef void (*hd_out_cb)(void* ctx, const uint8_t* burst, size_t len);

HDPacker* hd_create(int format, hd_out_cb cb, void* ctx);
void      hd_destroy(HDPacker* p);
/* Feed encoder payload bytes. Returns the length of a completed burst
 * (and stores its pointer in *out), or 0 when no burst is complete. */
size_t    hd_write(HDPacker* p, const uint8_t* buf, size_t n);
void      hd_flush(HDPacker* p);
int       hd_format(HDPacker* p);
/* Diagnostic status from the upstream-backed adapter. */
int       hd_status(HDPacker* p, size_t* frames, size_t* emitted);
/* End-of-stream only; seek/reset uses hd_flush() to discard the old timeline. */
int       hd_finish(HDPacker* p);

#ifdef __cplusplus
}
#endif

#endif
