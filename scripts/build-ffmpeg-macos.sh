#!/usr/bin/env bash
set -ex

if [ -f /tmp/ffmpeg-macos/lib/libavformat.a ]; then
    echo "FFmpeg already built, skipping."
    exit 0
fi

FFVER=8.0.1
SDK=$(xcrun --sdk macosx --show-sdk-path)
J=$(sysctl -n hw.logicalcpu)
BUILDDIR="/tmp/ffmpeg-build"

CONFIGURE_FLAGS=(
    --disable-shared
    --enable-static
    --disable-programs
    --disable-doc
    --disable-network
    --disable-zlib
    --disable-bzlib
    --disable-lzma
    --disable-iconv
    --disable-x86asm
    --disable-everything
    --enable-protocol=file
    --enable-demuxer=mov,matroska,avi,flv,mp3,ogg,wav
    --enable-decoder=h264,hevc,vp8,vp9,aac,mp3,ac3,opus,vorbis,pcm_s16le,pcm_s16be
    --enable-parser=h264,hevc,aac,mp3,vp8,vp9,opus
)

rm -rf "$BUILDDIR"
mkdir -p "$BUILDDIR"
cd "$BUILDDIR"

curl -LO "https://ffmpeg.org/releases/ffmpeg-${FFVER}.tar.xz"
tar xf "ffmpeg-${FFVER}.tar.xz"
cp -r "ffmpeg-${FFVER}" "ffmpeg-${FFVER}-arm64"

# Build x86_64
cd "${BUILDDIR}/ffmpeg-${FFVER}"
./configure \
    --prefix=/tmp/ffmpeg-x86_64 \
    --arch=x86_64 \
    --extra-cflags="-arch x86_64 -isysroot $SDK -mmacosx-version-min=11.0" \
    --extra-ldflags="-arch x86_64 -isysroot $SDK -mmacosx-version-min=11.0" \
    "${CONFIGURE_FLAGS[@]}"
make -j$J
make install

# Build arm64 (cross-compile from x86_64 host) in a separate source tree
cd "${BUILDDIR}/ffmpeg-${FFVER}-arm64"
./configure \
    --prefix=/tmp/ffmpeg-arm64 \
    --arch=arm64 \
    --target-os=darwin \
    --enable-cross-compile \
    --cc="clang -arch arm64" \
    --extra-cflags="-arch arm64 -isysroot $SDK -mmacosx-version-min=11.0" \
    --extra-ldflags="-arch arm64 -isysroot $SDK -mmacosx-version-min=11.0" \
    "${CONFIGURE_FLAGS[@]}"
make -j$J
make install

# Create universal2 merge
mkdir -p /tmp/ffmpeg-macos/lib/pkgconfig /tmp/ffmpeg-macos/include
cp -r /tmp/ffmpeg-arm64/include/ /tmp/ffmpeg-macos/include/

for lib in avformat avcodec avutil swscale swresample; do
    lipo -create \
        /tmp/ffmpeg-x86_64/lib/lib${lib}.a \
        /tmp/ffmpeg-arm64/lib/lib${lib}.a \
        -output /tmp/ffmpeg-macos/lib/lib${lib}.a
done

for pc in /tmp/ffmpeg-arm64/lib/pkgconfig/*.pc; do
    sed "s|/tmp/ffmpeg-arm64|/tmp/ffmpeg-macos|g" "$pc" \
        > /tmp/ffmpeg-macos/lib/pkgconfig/$(basename $pc)
done
