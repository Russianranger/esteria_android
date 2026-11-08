"""Read-only X11 setup observation. Every title/class outside a fixed vocabulary is hashed."""
import ctypes as c
import hashlib

WORD=c.c_ulong
WIN=c.c_ulong
DISPLAY=c.c_void_p
PTR=c.c_void_p
LABELS={'Wine','Wine configuration','Wine Gecko Installer','Wine Mono Installer','Wine Configuration',
        'Wine Mono','Wine Gecko','Default IME','Desktop','explorer.exe','rundll32.exe','wineboot.exe','#32770'}


def label(raw):
    value=raw.decode('utf-8','replace')
    return value if value in LABELS else 'sha256:'+hashlib.sha256(raw).hexdigest()


class ClassHint(c.Structure):
    _fields_=[('name',PTR),('kind',PTR)]


def snapshot(display):
    lib=c.CDLL('libX11.so.6')
    def fn(name,args,ret):
        func=getattr(lib,name);func.argtypes=args;func.restype=ret
        return func
    ptr=c.POINTER
    open_display=fn('XOpenDisplay',[c.c_char_p],DISPLAY)
    close=fn('XCloseDisplay',[DISPLAY],c.c_int)
    root=fn('XDefaultRootWindow',[DISPLAY],WIN)
    tree=fn('XQueryTree',[DISPLAY,WIN,ptr(WIN),ptr(WIN),ptr(ptr(WIN)),ptr(c.c_uint)],c.c_int)
    name=fn('XFetchName',[DISPLAY,WIN,ptr(PTR)],c.c_int)
    hint=fn('XGetClassHint',[DISPLAY,WIN,ptr(ClassHint)],c.c_int)
    intern=fn('XInternAtom',[DISPLAY,c.c_char_p,c.c_int],WORD)
    prop=fn('XGetWindowProperty',[DISPLAY,WIN,WORD,c.c_long,c.c_long,c.c_int,WORD,
                                  ptr(WORD),ptr(c.c_int),ptr(WORD),ptr(WORD),ptr(PTR)],c.c_int)
    free=fn('XFree',[PTR],c.c_int)
    # A client may destroy a transient window during traversal. Xlib's default error
    # handler terminates the calling process on BadWindow. Use a nonfatal local handler.
    callback=c.CFUNCTYPE(c.c_int,DISPLAY,PTR)
    handler=callback(lambda d,e:0)
    handle=fn('XSetErrorHandler',[PTR],PTR)
    d=open_display(display.encode())
    if not d: return []
    previous=handle(c.cast(handler,PTR))
    rows=[]
    def read(ptr):
        if not ptr:return None
        try:return label(c.string_at(ptr))
        finally:free(ptr)
    try:
        queue=[(root(d),0)]
        pid_atom=intern(d,b'_NET_WM_PID',1)
        seen=0
        while queue and seen<128 and len(rows)<24:
            w,depth=queue.pop(0);seen+=1
            if depth:
                value=PTR();name(d,w,c.byref(value));title=read(value)
                cl=ClassHint();hint(d,w,c.byref(cl))
                cls=[v for v in (read(cl.name),read(cl.kind)) if v is not None]
                pid=None
                if pid_atom:
                    actual=WORD();fmt=c.c_int();n=WORD();after=WORD();data=PTR()
                    code=prop(d,w,pid_atom,0,1,0,0,c.byref(actual),c.byref(fmt),c.byref(n),c.byref(after),c.byref(data))
                    if data:
                        if code==0 and fmt.value==32 and n.value==1:
                            pid=c.cast(data,ptr(WORD)).contents.value
                        free(data)
                if title or cls or pid: rows.append(dict(title=title,classes=cls,pid=pid))
            if depth<3:
                returned=WIN();parent=WIN();children=ptr(WIN)();n=c.c_uint()
                if tree(d,w,c.byref(returned),c.byref(parent),c.byref(children),c.byref(n)) and children:
                    queue.extend((children[i],depth+1) for i in range(min(n.value,64)))
                    free(children)
        return rows
    finally:
        close(d)
        handle(previous)
