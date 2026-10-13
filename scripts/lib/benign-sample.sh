# Builds the harmless Windows sample (guest/testsample/benign.c) with mingw-w64 in a throwaway
# container. Sourced by scripts that submit it; expects SAMPLE_SRC and SAMPLE_DIR to be set.

build_sample() {
    mkdir -p "$SAMPLE_DIR"
    [[ -f $SAMPLE_DIR/benign.exe ]] && return 0
    docker run --rm -e OWNER="$(id -u):$(id -g)" -v "$SAMPLE_SRC:/src/benign.c:ro" -v "$SAMPLE_DIR:/out" \
        --entrypoint "" ubuntu:24.04 \
        sh -c 'apt-get -qq update >/dev/null && apt-get -qq install -y gcc-mingw-w64-x86-64 >/dev/null 2>&1 &&
               x86_64-w64-mingw32-gcc -O2 -s /src/benign.c -o /out/benign.exe -lws2_32 &&
               chown "$OWNER" /out/benign.exe' \
        || return 1
    [[ -f $SAMPLE_DIR/benign.exe ]]
}
