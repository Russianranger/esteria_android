#!/usr/bin/env python3
"""Profile-aware app shader coordinator over the unchanged pinned provider helper.

Compiler/translator inputs remain the independently verified original provider.
Only app-owned generation/reuse identities add the content profile.
"""
try:
    from .shader_generation import *
except ImportError:
    from shader_generation import *

CONTENT_PROFILES = ('stock-3.3.5a', 'esteria-custom')
DEFAULT_CONTENT_PROFILE = CONTENT_PROFILES[0]

def generate(store, game, generation, tools, revision, locale, timeout=7200, *, content_profile=DEFAULT_CONTENT_PROFILE):
    require(content_profile in CONTENT_PROFILES, 'unsupported content profile')
    require(locale in LOCALES, 'explicit supported locale required')
    store, game, tools = canonical(store, create=True), canonical(game), canonical(tools)
    require(not any(a == b or a in b.parents or b in a.parents for a, b in
                    ((store, game), (store, tools), (game, tools))), 'shader/input/tool roots must be separate')
    lock = os.open(store / '.setup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        inputs = {'formatVersion': 1, 'contentProfile': content_profile, 'importGeneration': generation, 'clientRevision': revision,
                  'locale': locale, 'importMetadata': imported(game, generation),
                  'toolManifestSha256': tool_identity(tools, revision),
                  'preparationHelperSha256': identity(Path(__file__).resolve(), 131072)['sha256']}
        key = hashlib.sha256(encoded(inputs)).hexdigest()
        generations = canonical(store / 'generations', create=True)
        destination = generations / key
        if destination.exists() or destination.is_symlink():
            canonical(destination)
            receipt = json.loads(read(destination / 'receipt.json', MAX_TEXT))
            require(type(receipt) is dict and set(receipt) == {'formatVersion', 'scope', 'generation', 'inputs',
                    'outputs', 'graphicsQualified', 'androidQualified', 'gameplayQualified'} and
                    type(receipt['formatVersion']) is int and receipt['formatVersion'] == 1 and
                    receipt['scope'] == 'local-generated-shaders-not-render-qualified' and
                    all(receipt[name] is False for name in ('graphicsQualified', 'androidQualified', 'gameplayQualified')) and
                    receipt.get('inputs') == inputs and receipt.get('generation') == key and
                    receipt.get('outputs') == validate_output(destination / 'shaders'), 'prepared shader generation changed')
        else:
            staging = canonical(store / 'staging', create=True) / (key + '-' + uuid.uuid4().hex)
            staging.mkdir(mode=0o700)
            shaders = staging / 'shaders'
            shaders.mkdir(mode=0o700)
            execute([sys.executable, '-B', '-s', '-E', str(tools / 'translate_shaders.py'),
                     '--strict', '--client', str(game / 'generations' / generation / 'data'),
                     '--locale', locale, '--glslang', str(tools / 'bin/glslangValidator'),
                     '--out', str(shaders)], staging / 'setup.log', timeout)
            outputs = validate_output(shaders)
            require(imported(game, generation) == inputs['importMetadata'] and
                    tool_identity(tools, revision) == inputs['toolManifestSha256'] and
                    identity(Path(__file__).resolve(), 131072)['sha256'] == inputs['preparationHelperSha256'], 'inputs changed during shader setup')
            receipt = {'formatVersion': 1, 'scope': 'local-generated-shaders-not-render-qualified',
                       'generation': key, 'inputs': inputs, 'outputs': outputs,
                       'graphicsQualified': False, 'androidQualified': False, 'gameplayQualified': False}
            # Ensure every generated file reaches storage before the completion/pointer commit.
            for name in outputs:
                with (shaders / name).open('rb') as source:
                    os.fsync(source.fileno())
            for folder in ('vertex', 'pixel'):
                sync(shaders / folder)
            sync(shaders)
            atomic(staging / 'receipt.json', encoded(receipt))
            os.rename(staging, destination)
            sync(generations)
        require(imported(game, generation) == inputs['importMetadata'] and
                identity(Path(__file__).resolve(), 131072)['sha256'] == inputs['preparationHelperSha256'],
                'import or helper changed before shader activation')
        atomic(store / 'current', (key + '\n').encode())
        return receipt
    finally:
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('store', 'game', 'tools'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--generation', required=True)
    parser.add_argument('--client-revision', required=True)
    parser.add_argument('--locale', required=True)
    parser.add_argument('--content-profile', choices=CONTENT_PROFILES, default=DEFAULT_CONTENT_PROFILE)
    args = parser.parse_args()
    try:
        receipt = generate(args.store, args.game, args.generation, args.tools, args.client_revision, args.locale, content_profile=args.content_profile)
        print('Shader generation prepared: ' + receipt['generation'] + '; rendering remains unqualified')
        return 0
    except (OSError, ValueError) as error:
        print('Shader generation failed (' + type(error).__name__ + '): ' + str(error) + '; previous output preserved', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
