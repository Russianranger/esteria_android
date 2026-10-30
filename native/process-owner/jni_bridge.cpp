// JNI argument conversion completes before fork; no JVM operation runs in the child.
#include "process_owner.h"
#include <jni.h>
#include <stdexcept>

namespace {
std::string string(JNIEnv* env,jstring value) {
    if (!value) throw std::runtime_error("Null native process argument");
    const jsize length=env->GetStringLength(value);
    if (length>16384) throw std::runtime_error("Oversized native process argument");
    const jchar* chars=env->GetStringChars(value,nullptr);
    if (!chars) throw std::runtime_error("Cannot read native process argument");
    std::string result;
    try {
        for (jsize i=0;i<length;++i) {
            unsigned code=chars[i];
            if (!code) throw std::runtime_error("NUL in native process argument");
            if (code>=0xd800 && code<=0xdbff) {
                if (++i>=length || chars[i]<0xdc00 || chars[i]>0xdfff) throw std::runtime_error("Invalid process Unicode");
                code=0x10000+((code-0xd800)<<10)+(chars[i]-0xdc00);
            } else if (code>=0xdc00 && code<=0xdfff) throw std::runtime_error("Invalid process Unicode");
            if (code<0x80) result.push_back(static_cast<char>(code));
            else {
                if (code<0x800) result.push_back(static_cast<char>(0xc0|(code>>6)));
                else {
                    if (code<0x10000) result.push_back(static_cast<char>(0xe0|(code>>12)));
                    else { result.push_back(static_cast<char>(0xf0|(code>>18))); result.push_back(static_cast<char>(0x80|((code>>12)&63))); }
                    result.push_back(static_cast<char>(0x80|((code>>6)&63)));
                }
                result.push_back(static_cast<char>(0x80|(code&63)));
            }
        }
    } catch (...) { env->ReleaseStringChars(value,chars); throw; }
    env->ReleaseStringChars(value,chars); return result;
}
std::vector<std::string> strings(JNIEnv* env,jobjectArray values) {
    if (!values || env->GetArrayLength(values)>128) throw std::runtime_error("Invalid process argument list");
    std::vector<std::string> result;
    for (jsize i=0;i<env->GetArrayLength(values);++i) {
        auto item=static_cast<jstring>(env->GetObjectArrayElement(values,i));
        try { result.push_back(string(env,item)); }
        catch (...) { env->DeleteLocalRef(item); throw; }
        env->DeleteLocalRef(item);
    }
    return result;
}
void error(JNIEnv* env,const std::exception& problem) {
    if (!env->ExceptionCheck()) env->ThrowNew(env->FindClass("java/io/IOException"),problem.what());
}
}
extern "C" JNIEXPORT jlong JNICALL
Java_io_github_russianranger_esteria_runtime_NativeProcessBridge_startNative(JNIEnv* env,jclass,jstring executable,jobjectArray args,jobjectArray environment,jstring cwd,jstring output,jstring errors,jboolean interactive) {
    try { return esteria::start({string(env,executable),strings(env,args),strings(env,environment),string(env,cwd),"",string(env,output),string(env,errors),interactive==JNI_TRUE}); }
    catch (const std::exception& problem) { error(env,problem); return 0; }
}
extern "C" JNIEXPORT jboolean JNICALL
Java_io_github_russianranger_esteria_runtime_NativeProcessBridge_writeInput(JNIEnv* env,jobject,jlong handle,jbyteArray data,jlong timeout) {
    try {
        if (!data) throw std::runtime_error("Missing process input");
        const jsize size=env->GetArrayLength(data);
        if (size<1 || size>4096) throw std::runtime_error("Invalid process input size");
        std::array<jbyte,4096> bytes{};
        env->GetByteArrayRegion(data,0,size,bytes.data());
        if (env->ExceptionCheck()) return JNI_FALSE;
        return esteria::write_input(handle,bytes.data(),static_cast<std::size_t>(size),timeout)?JNI_TRUE:JNI_FALSE;
    } catch (const std::exception& problem) { error(env,problem); return JNI_FALSE; }
}
extern "C" JNIEXPORT void JNICALL
Java_io_github_russianranger_esteria_runtime_NativeProcessBridge_closeInput(JNIEnv* env,jobject,jlong handle) {
    try { esteria::close_input(handle); }
    catch (const std::exception& problem) { error(env,problem); }
}
extern "C" JNIEXPORT jint JNICALL
Java_io_github_russianranger_esteria_runtime_NativeProcessBridge_waitFor(JNIEnv* env,jobject,jlong handle,jlong timeout) {
    try { return esteria::wait_for(handle,timeout); }
    catch (const std::exception& problem) { error(env,problem); return esteria::running; }
}
extern "C" JNIEXPORT jint JNICALL
Java_io_github_russianranger_esteria_runtime_NativeProcessBridge_terminate(JNIEnv* env,jobject,jlong handle) {
    try { return esteria::stop(handle,0); }
    catch (const std::exception& problem) { error(env,problem); return esteria::running; }
}
extern "C" JNIEXPORT jlongArray JNICALL
Java_io_github_russianranger_esteria_runtime_NativeProcessBridge_diagnostics(JNIEnv* env,jobject,jlong handle) {
    try {
        const auto values=esteria::diagnostics(handle); jlong copy[5];
        for (int i=0;i<5;++i) copy[i]=values[i];
        auto result=env->NewLongArray(5); if (result) env->SetLongArrayRegion(result,0,5,copy); return result;
    } catch (const std::exception& problem) { error(env,problem); return nullptr; }
}

extern "C" JNIEXPORT jlongArray JNICALL
Java_io_github_russianranger_esteria_runtime_NativeProcessBridge_usageNative(JNIEnv* env,jobject,jlong handle) {
    try {
        const auto value=esteria::usage(handle);
        const jlong wire[16]={1,value.flags,value.start_nanos,value.duration_nanos,value.scanned_processes,value.members,
            value.rss_members,value.pss_members,value.cpu_members,value.rss_bytes,value.pss_bytes,value.cpu_ticks,value.ticks_per_second,
            value.changed_members,value.denied_entries,0};
        auto result=env->NewLongArray(16);if(result)env->SetLongArrayRegion(result,0,16,wire);return result;
    }catch(const std::exception& problem){error(env,problem);return nullptr;}
}
