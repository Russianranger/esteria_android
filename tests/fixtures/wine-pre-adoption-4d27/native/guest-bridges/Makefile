# Native Debian 12 ARM64 guest build; NDK/Bionic is not compatible with Wine's glibc process.
CC ?= cc
CPPFLAGS += -D_FILE_OFFSET_BITS=64
CFLAGS += -std=c11 -O2 -Wall -Wextra -Werror -fstack-protector-strong
LDFLAGS += -Wl,-z,relro,-z,now,-z,noexecstack
OUT ?= out
all: $(OUT)/esteria-x11-frame $(OUT)/esteria-x11-input $(OUT)/libasound_module_pcm_esteria.so
$(OUT):
	mkdir -p $(OUT)
$(OUT)/esteria-x11-frame: x11_frame.c private_socket.h ../presentation/frame_protocol.h ../presentation/frame_transport.h | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -lX11 -lXfixes -o $@
$(OUT)/esteria-x11-input: x11_input.c private_socket.h ../presentation/frame_transport.h | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -Wl,-Bstatic -lXtst -Wl,-Bdynamic -lX11 -lXext -o $@
$(OUT)/libasound_module_pcm_esteria.so: pcm_esteria.c | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) -DPIC -fPIC -shared $< $(LDFLAGS) -lasound -o $@
.PHONY: all
