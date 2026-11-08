"""Exercise the signed launcher's SAF export on a disposable Android realm; publish only counts."""
import io
import json
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile

from android_platform import CONTAINER, PACKAGE, android_tool, platform_environment, shell


def visible(match, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            # Android's uiautomator wrapper kills its own process group on some Redroid builds.
            # Accept only a fresh, fully parsed hierarchy written by this invocation as the shell UID.
            target='/data/local/tmp/esteria-qa-ui-'+str(time.monotonic_ns())+'.xml'
            command=['docker','exec','--user','2000:2000',CONTAINER,'/system/bin/env','-i',
                     *platform_environment(),'uiautomator','dump',target]
            result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=20)
            if subprocess.run(['docker','exec',CONTAINER,'test','-s',target]).returncode:
                raise RuntimeError(f'Android shell produced no hierarchy (exit {result.returncode}): {result.stdout[-600:]}')
            try:
                root=ET.fromstring(shell('cat',target))
            finally:
                shell('rm','-f',target)
            for node in root.iter('node'):
                if match(node.attrib):
                    return node.attrib
        except (subprocess.CalledProcessError, ET.ParseError):
            pass
        time.sleep(.4)
    raise RuntimeError('The expected Android control did not appear')


def tap(node):
    bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node['bounds'])
    assert bounds
    x, y, right, bottom = map(int, bounds.groups())
    android_tool('input', 'tap', str((x + right) // 2), str((y + bottom) // 2))


def label(value):
    return visible(lambda node: node.get('package') == PACKAGE and node.get('text') == value)


def main():
    android_tool('input','keyevent','KEYCODE_WAKEUP')
    shell('wm','dismiss-keyguard')
    shell('cmd','activity','start-activity','-W','-n',PACKAGE+'/io.github.russianranger.esteria.MainActivity')
    time.sleep(1)
    resumed=shell('dumpsys','activity','activities')
    assert any(PACKAGE in line and ('mResumedActivity' in line or 'topResumedActivity' in line) for line in resumed.splitlines())
    with Path('evidence/realm-launcher.png').open('wb') as output:
        subprocess.run(['docker','exec',CONTAINER,'screencap','-p'], stdout=output, check=True, timeout=20)
    label('Start local game')
    tap(label('Tools'))
    tap(label('Export support bundle'))
    # Accept the generated name in Android's standard DocumentsUI. A fresh Redroid user defaults to Downloads.
    save = visible(lambda node: node.get('package', '').endswith('.documentsui') and
                   node.get('text', '').casefold() == 'save' and node.get('enabled') == 'true')
    tap(save)
    tap(label('Play'))  # The short Play page keeps the shared status line visible.
    visible(lambda node: node.get('package') == PACKAGE and 'Support bundle saved.' in node.get('text', ''), seconds=90)
    paths = shell('find', '/data/media/0', '-maxdepth', '4', '-name', 'Esteria-support-*.zip', '-type', 'f').splitlines()
    assert len(paths) == 1 and re.fullmatch(r'/data/media/0/(?:[^/]+/)*Esteria-support-\d+\.zip', paths[0])
    size = int(shell('stat', '-c', '%s', paths[0]))
    assert 0 < size <= 4*1024*1024
    archive = subprocess.check_output(['docker', 'exec', CONTAINER, 'cat', paths[0]], timeout=20)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert z.testzip() is None
        names = z.namelist()
        assert 'status.txt' in names and 'logs/launcher.log' in names
        assert all(n == 'status.txt' or re.fullmatch(r'logs/[A-Za-z0-9._-]+\.log', n) for n in names)
        status = z.read('status.txt').decode()
        assert 'app.versionCode=23\n' in status and 'game.frameCap.nextStart=30\n' in status
        omitted = int(re.search(r'^support.omittedFacts=(\d+)$', status, re.M).group(1))
    Path('evidence/export-counts.json').write_text(json.dumps(dict(
        versionCode=23, route='signed launcher, Android DocumentsUI, fresh retained-SQL fixture',
        zipBytes=size, entries=len(names), metadataBytes=len(status.encode()), omittedFacts=omitted))+'\n')


if __name__ == '__main__':
    main()
