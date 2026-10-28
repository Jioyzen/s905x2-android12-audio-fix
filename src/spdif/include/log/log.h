#pragma once
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#ifdef __ANDROID__
#include <android/log.h>
#else
#define ANDROID_LOG_VERBOSE 2
#define ANDROID_LOG_DEBUG 3
#define ANDROID_LOG_INFO 4
#define ANDROID_LOG_WARN 5
#define ANDROID_LOG_ERROR 6
#define ANDROID_LOG_FATAL 7
static inline int __android_log_print(int prio, const char *tag, const char *fmt, ...) {
    va_list ap; va_start(ap, fmt); int n = vfprintf(stderr, fmt, ap); va_end(ap); (void)prio; (void)tag; return n;
}
#endif
#ifndef LOG_TAG
#define LOG_TAG "AudioSPDIF"
#endif
#define ALOGV(...) __android_log_print(ANDROID_LOG_VERBOSE, LOG_TAG, __VA_ARGS__)
#ifndef ALOGD
#define ALOGD(...) __android_log_print(ANDROID_LOG_DEBUG,   LOG_TAG, __VA_ARGS__)
#endif
#define ALOGI(...) __android_log_print(ANDROID_LOG_INFO,    LOG_TAG, __VA_ARGS__)
#define ALOGW(...) __android_log_print(ANDROID_LOG_WARN,    LOG_TAG, __VA_ARGS__)
#define ALOGE(...) __android_log_print(ANDROID_LOG_ERROR,   LOG_TAG, __VA_ARGS__)
#define ALOGD_IF(cond, ...) do { if (cond) ALOGD(__VA_ARGS__); } while (0)
#define ALOGI_IF(cond, ...) do { if (cond) ALOGI(__VA_ARGS__); } while (0)
#define ALOGV_IF(cond, ...) do { if (cond) ALOGV(__VA_ARGS__); } while (0)
#define ALOGW_IF(cond, ...) do { if (cond) ALOGW(__VA_ARGS__); } while (0)
#define ALOGE_IF(cond, ...) do { if (cond) ALOGE(__VA_ARGS__); } while (0)
#ifndef ALOG_ASSERT
#define ALOG_ASSERT(cond, ...) do { if (!(cond)) { ALOGE("assert failed: %s", #cond); abort(); } } while (0)
#endif
#define android_errorWriteLog(tag, info) ((void)0)
#define LOG_ALWAYS_FATAL_IF(cond, ...) do { if (cond) { __android_log_print(ANDROID_LOG_FATAL, LOG_TAG, __VA_ARGS__); abort(); } } while (0)
#define LOG_FATAL_IF(cond, ...) LOG_ALWAYS_FATAL_IF(cond, __VA_ARGS__)
