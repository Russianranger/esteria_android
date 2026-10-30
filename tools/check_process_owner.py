#!/usr/bin/env python3
"""Compile/run the real Linux owner + JNI adapter; optionally cross-build Android."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def run(command: list[str], *, timeout: int=120) -> None:
    subprocess.run(command,cwd=ROOT,check=True,timeout=timeout)

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--ndk",type=Path)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    java=Path(os.environ["JAVA_HOME"])
    source=ROOT/"native/process-owner"
    with tempfile.TemporaryDirectory(prefix="esteria-owner-check-") as directory:
        build=Path(directory)
        run(["g++","-std=c++17","-Wall","-Wextra","-Werror","-pthread",str(source/"process_owner.cpp"),str(source/"process_owner_test.cpp"),"-o",str(build/"owner-test")])
        run([str(build/"owner-test")],timeout=60)
        run(["g++","-std=c++17","-Wall","-Wextra","-Werror","-fPIC","-shared","-pthread","-fvisibility=hidden",
            "-I"+str(java/"include"),"-I"+str(java/"include/linux"),str(source/"process_owner.cpp"),str(source/"jni_bridge.cpp"),"-o",str(build/"libesteria_process.so")])
        classes=build/"classes"; classes.mkdir()
        core=ROOT/"core/src/main/java/io/github/russianranger/esteria/core/runtime"
        run([str(java/"bin/javac"),"-d",str(classes),str(core/"SessionSupervisor.java"),str(core/"process/OwnedProcess.java"),str(core/"process/ProotLaunch.java"),str(core/"process/WorldConsoleShutdown.java"),
            str(ROOT/"app/src/main/java/io/github/russianranger/esteria/runtime/NativeProcessBridge.java"),str(source/"NativeOwnerIntegrationTest.java"),str(source/"NativeOwnerInputTests.java")])
        run([str(java/"bin/java"),"-Xmx64m","-Djava.library.path="+str(build),"-cp",str(classes),"io.github.russianranger.esteria.runtime.NativeOwnerIntegrationTest"],timeout=60)
    receipt={"formatVersion":1,"scope":"linux-native-owner-and-jni","hostArchitecture":platform.machine(),
        "nativeOwnerPassed":True,"jvmIntegrationGroups":12,"interactiveInputQualified":True,
        "worldShutdownQualified":False,"characterPersistenceQualified":False,"androidCrossBuilt":False,"androidExecuted":False,"guestExecuted":False,"gameplayQualified":False}
    if args.ndk:
        if "Pkg.Revision = 28.2.13676358" not in (args.ndk/"source.properties").read_text():
            raise ValueError("NDK 28.2.13676358 required")
        output=args.output/"android"; output.mkdir(exist_ok=True)
        compiler=args.ndk/"toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android26-clang++"
        library=output/"libesteria_process.so"
        run([str(compiler),"-std=c++17","-Wall","-Wextra","-Werror","-fPIC","-shared","-static-libstdc++","-fvisibility=hidden",
            "-Wl,-z,max-page-size=16384","-Wl,-z,noexecstack",str(source/"process_owner.cpp"),str(source/"jni_bridge.cpp"),"-o",str(library)])
        receipt.update(androidCrossBuilt=True,androidLibrarySha256=hashlib.sha256(library.read_bytes()).hexdigest(),androidLibraryBytes=library.stat().st_size)
    inputs=list(source.iterdir())+list((core/"process").glob("*.java"))+[core/"SessionSupervisor.java",
        ROOT/"app/src/main/java/io/github/russianranger/esteria/runtime/NativeProcessBridge.java",Path(__file__).resolve()]
    receipt["sourceSha256"]={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs) if p.is_file()}
    (args.output/"process-owner-evidence.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps(receipt,indent=2))

if __name__=="__main__": main()
