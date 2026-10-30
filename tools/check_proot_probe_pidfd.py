#!/usr/bin/env python3
"""Compile and execute real Linux pidfd/JNI ownership contracts; not an Android pass."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jdk',type=Path,default=os.environ.get('JAVA_HOME'))
    args=parser.parse_args()
    if args.jdk is None:raise ValueError('JDK17 path required')
    if os.readlink('/proc/self')!=str(os.getpid()):
        raise RuntimeError('Host procfs uses a different PID namespace; run this identity test in the normal Linux CI VM')
    with tempfile.TemporaryDirectory(prefix='esteria-pidfd-test-') as raw:
        work=Path(raw)
        subprocess.run(['g++','-std=c++17','-O2','-Wall','-Wextra','-Werror','-fPIC','-shared','-pthread',
            '-I'+str(args.jdk/'include'),'-I'+str(args.jdk/'include/linux'),
            str(ROOT/'native/proot-probe/pidfd_jni.cpp'),'-o',str(work/'libesteria_probe_process.so')],check=True,timeout=60)
        subprocess.run([str(args.jdk/'bin/javac'),'-d',str(work),
            str(ROOT/'app/src/androidTest/java/io/github/russianranger/esteria/runtime/ProbeProcessHandles.java'),
            str(ROOT/'native/proot-probe/PidfdHostTest.java')],check=True,timeout=30)
        subprocess.run([str(args.jdk/'bin/java'),'-Xmx32m','-Djava.library.path='+str(work),'-cp',str(work),
            'io.github.russianranger.esteria.runtime.PidfdHostTest'],check=True,timeout=15)


if __name__=='__main__':main()
