/* Exercises the actual JNI decoder/copy with fake Android windows and real Unix socketpairs. */
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include "../native/presentation/surface.c"
static ANativeWindow window;
static uint32_t target[64];
static int width,height,stride,geometries,posts,locks,releases,bad_buffer;
static unsigned char *cache;
static jlong stats[6];
static jsize array_length(JNIEnv *env,jarray array) { (void)env;(void)array;return 6; }
static void *buffer_address(JNIEnv *env,jobject object) { (void)env;(void)object;return cache; }
static jlong buffer_capacity(JNIEnv *env,jobject object) { (void)env;(void)object;return ESTERIA_FRAME_BYTES+16; }
static void array_region(JNIEnv *env,jlongArray array,jsize offset,jsize count,const jlong *values) {
    (void)env;(void)array;assert(offset==0&&count==6);memcpy(stats,values,sizeof(stats));
}
static jboolean no_exception(JNIEnv *env) { (void)env;return JNI_FALSE; }
ANativeWindow *ANativeWindow_fromSurface(JNIEnv *env,jobject object) { (void)env;(void)object;return &window; }
int32_t ANativeWindow_setBuffersGeometry(ANativeWindow *w,int32_t x,int32_t y,int32_t format) {
    assert(w==&window&&format==WINDOW_FORMAT_RGBA_8888);width=x;height=y;stride=x+2;geometries++;return 0;
}
int32_t ANativeWindow_lock(ANativeWindow *w,ANativeWindow_Buffer *buffer,ARect *rect) {
    (void)rect;assert(w==&window);locks++;
    *buffer=(ANativeWindow_Buffer){.width=width,.height=height,.stride=bad_buffer?width-1:stride,
        .format=WINDOW_FORMAT_RGBA_8888,.bits=target};return 0;
}
int32_t ANativeWindow_unlockAndPost(ANativeWindow *w) { assert(w==&window);posts++;return 0; }
void ANativeWindow_release(ANativeWindow *w) { assert(w==&window);releases++; }
static int frame(uint32_t *header,const uint32_t *pixels,size_t pixel_bytes) {
    int sockets[2];assert(!socketpair(AF_UNIX,SOCK_STREAM,0,sockets));
    uint32_t wire[8];for(unsigned i=0;i<8;++i)wire[i]=htonl(header[i]);
    /* Deliberately fragment every header byte and use a separate pixel write. */
    for(size_t i=0;i<sizeof(wire);++i)assert(send(sockets[0],(char *)wire+i,1,MSG_NOSIGNAL)==1);
    if(pixel_bytes)assert(!esteria_send(sockets[0],pixels,pixel_bytes));
    shutdown(sockets[0],SHUT_WR);
    const struct JNINativeInterface_ api={.GetArrayLength=array_length,.GetDirectBufferAddress=buffer_address,
        .GetDirectBufferCapacity=buffer_capacity,.SetLongArrayRegion=array_region,.ExceptionCheck=no_exception};
    JNIEnv env=&api;
    int result=Java_io_github_russianranger_esteria_presentation_SurfaceBridge_receiveFrame(&env,NULL,(jobject)&window,
        sockets[1],(jobject)cache,(jlongArray)stats);
    unsigned char request;assert(recv(sockets[0],&request,1,0)==1&&request==1);
    close(sockets[0]);close(sockets[1]);return result;
}
int main(void) {
    signal(SIGPIPE,SIG_IGN);
    cache=calloc(1,ESTERIA_FRAME_BYTES+16);assert(cache);
    uint32_t pixels[]={0x112233,0xff0000,0x00ff00,0x0000ff};
    uint32_t h[]={ESTERIA_FRAME_MAGIC,2,2,8,7,100,0,ESTERIA_FRAME_UNCHANGED};
    assert(frame(h,NULL,0)==-3&&posts==0); /* Cannot inherit a missing baseline. */
    h[6]=16;h[7]=0;memset(target,0xab,sizeof(target));
    assert(frame(h,pixels,sizeof(pixels))==0&&geometries==1&&posts==1);
    assert(target[0]==0xff332211&&target[1]==0xff0000ff&&target[4]==0xff00ff00&&target[5]==0xffff0000);
    assert(target[2]==0xabababab&&target[3]==0xabababab&&stats[0]==2&&stats[1]==2&&stats[2]==7000&&stats[5]==16);
    h[5]++;h[6]=0;h[7]=ESTERIA_FRAME_UNCHANGED;
    assert(frame(h,NULL,0)==1&&posts==1&&locks==1);
    assert(frame(h,NULL,0)==-3); /* Duplicate/out-of-order sequence rejected. */
    h[5]++;h[1]=3;h[2]=1;h[3]=12;h[6]=12;h[7]=0;
    assert(frame(h,pixels,12)==0&&geometries==2&&posts==2);
    h[5]++;bad_buffer=1;
    assert(frame(h,pixels,12)==-4&&posts==3&&releases==3);bad_buffer=0;
    assert(frame(h,pixels,8)==-2&&posts==3); /* Truncated payload never posts. */
    h[7]=4;assert(frame(h,NULL,0)==-3); /* Region format is explicitly unsupported. */
    h[7]=0;h[1]=1280;h[2]=768;h[3]=5120;h[6]=1280*768*4;
    assert(frame(h,NULL,0)==-3); /* Geometry exceeds fixed allocation. */
    h[1]=UINT32_MAX;h[2]=UINT32_MAX;h[3]=UINT32_MAX-3;h[6]=16;
    assert(frame(h,NULL,0)==-3);
    free(cache);puts("SURFACE_PROTOCOL_COPY_OK full colour stride resize unchanged sequence bounds truncation");return 0;
}
