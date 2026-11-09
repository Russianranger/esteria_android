"""Exercise the visible launcher and real DocumentsUI on a disposable Android realm."""
import csv
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile

from PIL import Image, ImageChops
from android_platform import CONTAINER, PACKAGE, android_tool, shell


def screen():
    data = subprocess.check_output(['docker', 'exec', CONTAINER, 'screencap', '-p'], timeout=15)
    return Image.open(io.BytesIO(data)).convert('RGB')


def button(image, label, launcher):
    # Limit launcher recognition to its controls. DocumentsUI owns the whole display.
    offset_x = offset_y = 0
    modes = ('11', '6')
    if launcher:
        image = image.crop((0, 0, min(image.width, 720), image.height))
    else:
        # Android 13 DocumentsUI presents Save as a small blue pill. OCR the label inside it.
        region = (image.width*3//4, image.height*3//5, image.width, image.height*95//100)
        corner = image.crop(region)
        red, _, blue = corner.split()
        box = ImageChops.subtract(blue, red).point(lambda value: 255 if value>90 else 0).getbbox()
        if box:
            offset_x, offset_y = region[0]+box[0], region[1]+box[1]
            image = corner.crop(box)
            modes = ('8','11','7')
    data = io.BytesIO()
    image.save(data, format='PNG')
    expected = label.casefold().split()
    for mode in modes:
        result = subprocess.run(['tesseract', 'stdin', 'stdout', '--psm', mode, 'tsv'],
                                input=data.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                check=True, timeout=12)
        lines = {}
        for row in csv.DictReader(io.StringIO(result.stdout.decode()), delimiter='\t', quoting=csv.QUOTE_NONE):
            if row.get('level') == '5' and row.get('text'):
                key = (row['block_num'], row['par_num'], row['line_num'])
                lines.setdefault(key, []).append(row)
        for words in lines.values():
            for n in range(len(words)-len(expected)+1):
                match = words[n:n+len(expected)]
                if [r['text'].strip(' .,|').casefold() for r in match] != expected:
                    continue
                mid = match[len(match)//2]
                return (offset_x + int(mid['left']) + int(mid['width'])//2,
                        offset_y + int(mid['top']) + int(mid['height'])//2)
    return None


def foreground():
    rows = shell('dumpsys', 'activity', 'activities').splitlines()
    return ' '.join(r for r in rows if 'mResumedActivity' in r or 'topResumedActivity' in r)


def tap_label(label, launcher=True):
    deadline = time.monotonic()+45
    while time.monotonic()<deadline:
        owner = foreground()
        if (PACKAGE+'/' in owner if launcher else '.documentsui/' in owner):
            point = button(screen(), label, launcher)
            if point:
                android_tool('input','tap',str(point[0]),str(point[1]))
                return
        time.sleep(.4)
    raise RuntimeError('Visible Android control unavailable: '+label)


def completed_export():
    deadline = time.monotonic()+90
    while time.monotonic()<deadline:
        paths = shell('find','/data/media/0','-maxdepth','4','-name','Esteria-support-*.zip','-type','f').splitlines()
        if len(paths)==1 and re.fullmatch(r'/data/media/0/(?:[^/]+/)*Esteria-support-\d+\.zip',paths[0]):
            size=int(shell('stat','-c','%s',paths[0]))
            if 0<size<=4*1024*1024 and PACKAGE+'/' in foreground():
                data=subprocess.check_output(['docker','exec',CONTAINER,'cat',paths[0]],timeout=20)
                if zipfile.is_zipfile(io.BytesIO(data)):
                    return data
        time.sleep(.4)
    raise RuntimeError('DocumentsUI did not produce a completed support ZIP')


def main():
    version=int(sys.argv[1]) if len(sys.argv)>1 else 23
    android_tool('input','keyevent','KEYCODE_WAKEUP')
    shell('wm','dismiss-keyguard')
    shell('cmd','activity','start-activity','-W','-n',PACKAGE+'/io.github.russianranger.esteria.MainActivity')
    time.sleep(1)
    assert PACKAGE+'/' in foreground()
    screen().save('evidence/realm-launcher.png')
    tap_label('Tools')
    tap_label('Export support bundle')
    # This device is freshly provisioned. Record only its synthetic picker if it cannot save.
    try:
        tap_label('Save',launcher=False)
    except RuntimeError:
        print('Picker foreground:',foreground(),flush=True)
        print('Create handler:',shell('cmd','package','resolve-activity','--brief','-a','android.intent.action.CREATE_DOCUMENT',
                                     '-c','android.intent.category.OPENABLE','-t','application/zip'),flush=True)
        screen().save('evidence/qa-document-picker.png')
        raise
    archive=completed_export()
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert z.testzip() is None
        names=z.namelist()
        assert 'status.txt' in names and 'logs/launcher.log' in names
        assert all(n=='status.txt' or re.fullmatch(r'logs/[A-Za-z0-9._-]+\.log',n) for n in names)
        status=z.read('status.txt').decode()
        assert f'app.versionCode={version}\n' in status and 'game.frameCap.nextStart=30\n' in status
        omitted=int(re.search(r'^support.omittedFacts=(\d+)$',status,re.M).group(1))
        if version>=24:
            assert 'game.input.lookPercent=150\n' in status and 'game.retained=false\n' in status
            assert 'support.ownedLogsRejected=0\n' in status
            assert 'logs/game.database.stdout.log' in names and 'logs/game.database.stderr.log' in names
            assert b'fixture cleanup check: observed SQL stop\n' in z.read('logs/launcher.log')
            client=z.read('logs/game.presentation.client.stdout.log')
            world=z.read('logs/game.server.worldserver.log')
            assert client.endswith(b'fixture client logout tail\n') and b'old client marker' not in client
            assert b'pwd=[redacted]' in client and b'pwd=x' not in client
            assert world==b'password=[redacted]\nfixture world stop tail\n'
            assert all(z.getinfo(n).file_size<=65536 for n in names if n.startswith('logs/'))
            assert len(status.encode())<=262144
    Path('evidence/export-counts.json').write_text(json.dumps(dict(
        versionCode=version,route='visible launcher and Android DocumentsUI on disposable Android 13 ARM64',
        logInput='cleanly stopped SQL plus synthetic client, world and cleanup markers' if version>=24 else 'launcher',
        logRoles=sorted(n for n in names if n.startswith('logs/')),
        zipBytes=len(archive),entries=len(names),metadataBytes=len(status.encode()),omittedFacts=omitted))+'\n')


if __name__=='__main__':
    main()
