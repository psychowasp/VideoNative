// Compiled as Objective-C++ so miniaudio's Core Audio / AVFoundation backend works on iOS.
// Kept separate from media_decoder.cpp to avoid the AVMediaType name clash between
// FFmpeg (libavutil) and Apple's AVFoundation — they both define AVMediaType.
#define MINIAUDIO_IMPLEMENTATION
#include "miniaudio.h"
