"""Execute pinned CMake enumeration against empty and populated script fixtures.

The native-server job has its exact checkout available. Tooling-only jobs skip
this source-backed test rather than substituting a reimplementation of CMake.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('ESTERIA_SERVER_SOURCE', ROOT / 'sources/server'))
if not (SOURCE / '.git').exists() and (ROOT.parent / 'server-src/.git').exists():
    SOURCE = ROOT.parent / 'server-src'
COMMIT = 'f35f04d01689f034778e3474b3c820092f51e461'
MACRO = 'src/cmake/macros/ConfigureScripts.cmake'
PATCH = ROOT / 'patches/server/0006-empty-script-modules.patch'
CMAKE = os.environ.get('CMAKE') or shutil.which('cmake')


@unittest.skipUnless((SOURCE / '.git').exists() and CMAKE, 'requires pinned server checkout and actual CMake')
class EmptyScriptModules(unittest.TestCase):
    def test_actual_cmake_omits_documentation_only_and_keeps_every_collectable_input(self):
        def original(name):
            return subprocess.check_output(['git', 'show', COMMIT + ':' + name], cwd=SOURCE)
        macro = original(MACRO)
        self.assertEqual(hashlib.sha256(macro).hexdigest(),
                         '5c63622f80e9eb9c5e06ccea9ddbe67298065ca387bb29aad6d909ba9dcd2877')
        custom = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', COMMIT,
                                          'src/server/scripts/Custom'], cwd=SOURCE, text=True)
        self.assertEqual(custom.splitlines(), ['src/server/scripts/Custom/README.md'])
        with tempfile.TemporaryDirectory(prefix='esteria-script-enumeration-') as name:
            root = Path(name)
            target = root / MACRO
            target.parent.mkdir(parents=True)
            target.write_bytes(macro)
            collect = target.with_name('AutoCollect.cmake')
            collect.write_bytes(original('src/cmake/macros/AutoCollect.cmake'))
            subprocess.run(['git', 'apply', '--check', str(PATCH)], cwd=root, check=True)
            subprocess.run(['git', 'apply', str(PATCH)], cwd=root, check=True)
            scripts = root / 'src/server/scripts'
            custom = scripts / 'Custom'
            custom.mkdir(parents=True)
            (custom / 'README.md').write_text('Optional private scripts, not a loader definition.\n')
            for extension in ('c', 'cc', 'cpp', 'inl', 'def', 'h', 'hh', 'hpp'):
                nested = scripts / ('Fixture_' + extension) / 'nested'
                nested.mkdir(parents=True)
                (nested / ('input.' + extension)).write_text('// source fixture\n')
            script = root / 'check.cmake'
            script.write_text('''cmake_minimum_required(VERSION 3.16)
set(CMAKE_SOURCE_DIR "''' + str(root) + '''")
include("''' + str(target) + '''")
include("''' + str(collect) + '''")
GetScriptModuleList(MODULES)
list(FIND MODULES Custom EMPTY_CUSTOM)
if(NOT EMPTY_CUSTOM EQUAL -1)
  message(FATAL_ERROR "README-only Custom generated a loader requirement")
endif()
file(GLOB DIRECTORIES "${CMAKE_SOURCE_DIR}/src/server/scripts/*")
set(EXPECTED)
foreach(DIRECTORY ${DIRECTORIES})
  unset(INPUTS)
  CollectSourceFiles("${DIRECTORY}" INPUTS)
  if(INPUTS)
    get_filename_component(NAME "${DIRECTORY}" NAME)
    list(APPEND EXPECTED "${NAME}")
  endif()
endforeach()
list(SORT MODULES)
list(SORT EXPECTED)
if(NOT "${MODULES}" STREQUAL "${EXPECTED}")
  message(FATAL_ERROR "Enumeration differs from actual recursive AutoCollect inputs")
endif()
file(WRITE "${CMAKE_SOURCE_DIR}/src/server/scripts/Custom/private.cpp"
  "int customScriptFixture; // no loader: populated modules must still be selected\\n")
GetScriptModuleList(POPULATED)
list(FIND POPULATED Custom PRESENT_CUSTOM)
if(PRESENT_CUSTOM EQUAL -1)
  message(FATAL_ERROR "Populated Custom was silently disabled")
endif()
message(STATUS "PINNED_SCRIPT_ENUMERATION_PASS")
''')
            result = subprocess.run([str(CMAKE), '-P', str(script)], check=True, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertIn('PINNED_SCRIPT_ENUMERATION_PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
