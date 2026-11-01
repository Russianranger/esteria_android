#!/usr/bin/env python3
"""Static START ownership gate; complements Android component tests, never gameplay evidence."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def code(text):
    return re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda match: ' ' * len(match.group()), text)


def end_brace(text, start):
    depth = 0
    for index in range(start, len(text)):
        if text[index] == '{':
            depth += 1
        elif text[index] == '}':
            depth -= 1
            if depth == 0:
                return index
    raise ValueError('unclosed Java owner body')


def body(text, name):
    match = re.search(r'private\s+void\s+' + re.escape(name) + r'\s*\([^)]*\)[^{]*\{', text)
    if not match:
        raise ValueError('missing preparation owner method: ' + name)
    start = text.index('{', match.start())
    return text[start + 1:end_brace(text, start)]


def verify(text):
    source = code(text)
    start = body(source, 'startLocalGame')
    protected = re.search(r'runPreparation\s*\(\s*START\s*,\s*\(\s*\)\s*->\s*\{', start)
    if not protected:
        raise ValueError('START must own automatic preparation through runPreparation')
    opening = start.index('{', protected.start())
    closing = end_brace(start, opening)
    preparation = start[opening + 1:closing]
    for name in ('inspectStockClient', 'prepareStockRuntime', 'prepareServerRuntime', 'prepareWorld'):
        if not re.search(r'\b' + name + r'\s*\(', preparation):
            raise ValueError('START preparation scope is missing ' + name)
    game = re.search(r'\bGameSession\.begin\s*\(', start)
    if not game or game.start() <= closing:
        raise ValueError('GameSession must begin after the preparation scope returns')
    owner = body(source, 'runPreparation')
    if not re.search(r'if\s*\(\s*activePreparationIo\s*!=\s*null\s*\)\s*\{\s*operation\.run\(\);\s*return;', owner):
        raise ValueError('nested preparation must retain the existing controller')
    if 'RuntimeReadPolicy.install' not in owner or not re.search(r'finally\s*\{[^}]*activePreparationIo\s*=\s*null', owner):
        raise ValueError('preparation read scope/controller cleanup is missing')


def main():
    text = (ROOT / 'app/src/main/java/io/github/russianranger/esteria/SessionService.java').read_text()
    verify(text)
    for previous, changed in (
        ('runPreparation(START,', 'unprotectedPreparation(START,'),
        ('prepareWorld(selectedLocale);', 'unprotectedWorld(selectedLocale);'),
        ('if(activePreparationIo!=null){operation.run();return;}', 'if(false){operation.run();return;}'),
    ):
        if previous not in text:
            raise ValueError('flow mutation no longer targets production source')
        try:
            verify(text.replace(previous, changed, 1))
        except ValueError:
            pass
        else:
            raise ValueError('flow guard accepted an unprotected START mutation')
    print('PASS START scopes stock/server/world preparation, preserves nested ownership and exits before gameplay; three bypass mutations rejected')


if __name__ == '__main__':
    main()
