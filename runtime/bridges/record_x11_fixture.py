#!/usr/bin/env python3
"""Record a separate source-built observer; production bridge receipt is unchanged."""
import json
from pathlib import Path
from record_build import elf, identity, require


def main():
    production = json.loads(Path('/out/bridge-build.json').read_text())
    require(production['scope'] == 'linux-arm64-guest-bridge-build-only' and production['compiled'] is True,
            'production-build-receipt-required')
    receipt = dict(formatVersion=1, scope='linux-arm64-x11-observer-build-only',
                   integrationRevision=production['integrationRevision'],
                   inputLockSha256=production['inputLockSha256'],
                   bridgeReceipt=identity(Path('/out/bridge-build.json')),
                   binary=elf(Path('/out/x11-test/esteria-x11-input-observer')),
                   source=identity(Path('/fixture-src/x11_input_observer.c')),
                   executionQualified=False, androidQualified=False, gameplayQualified=False)
    Path('/out/x11-test/observer-build.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
