# Server engine payload and source selection audit

This is a source-selection audit of the measured **six-patch** build
`41005048019.1` at integration
`ae5534d0a9d7fb72c8e5a03dcfc65420c354e7bb`. It is not an Android engine provider,
a completed source companion, or permission to substitute that build for the
application's current seven-patch selection. `engine-source-audit.json` records
the original server/module/compile-command identities, exact Git trees,
candidate notice blobs and remaining false qualification flags.

## Runtime payload

The original installed manifest contains 97 files and 2,774,909,889 bytes. Select
these three programs for a future `/esteria-server` mount:

| Original file | Original bytes | Role |
| --- | ---: | --- |
| `bin/authserver` | 34,991,328 | Local authentication |
| `bin/worldserver` | 2,646,600,344 | World and static modules |
| `bin/dbimport` | 26,569,848 | Compiled schema updater |

Keep the installed `etc/` hierarchy: three main `.conf.dist` files and the 50
module templates named by the actual `server-modules.json` `configFiles` list.
These 53 files total 712,156 bytes. They are immutable templates; the renderer
writes the private session configuration elsewhere. Maps/vmaps/mmaps extractors
belong to a separate optional setup component. Installed headers and
`lib/liblua52.a` are build products, not required runtime companions. This
measured install contains no additional shared-library ELF files.

The three original executables require the AArch64 Linux interpreter,
GLIBC up to 2.38, GLIBCXX up to 3.4.32, Boost 1.83 and libmysqlclient21. Worldserver
also needs readline, SSL and zlib. Their measured dynamic requirements fit the
selected Ubuntu24 dependency family; this observation does not replace an
actual dependency-load or server-start test. Do not run them in the separate
Debian12 Wine rootfs. Preserve the original RUNPATH observation in provenance;
it points at the old CI install directory and is not a device library path.

The unstripped worldserver is too large for a sensible APK payload. A derivative
must record the exact strip tool and original/derived/debug identities, retain
the original manifest unchanged, compare all mapped ELF bytes and required
runtime metadata, and qualify the actual derived programs. Do not silently
rewrite the original module receipt's binary hashes. No stripped size has yet
been measured by this audit.

## Source companion boundaries

The original compile commands were re-read from the exact 2,958,877-byte
diagnostic artifact `12958224918`, SHA256
`3419fc9a42102aeadb3510ba880af9d4a3cc67e3fa28a1d419fe5df77291894a`.
They contain 2,199 distinct source paths beneath the server checkout and 340
source include directories. The generated module receipt names 52 enabled
modules. Compiler-generated loaders, Lua's fetched sources and integration
reference fixtures are recorded separately from server Git paths.

The candidate selection in the JSON uses only pinned Git objects:

1. Server root build/license files, all `src/`, `deps/` and `conf/dist/`.
   Exclude `deps/acore/mysql-tools/bin/`, which contains three Windows MySQL
   executables and two prebuilt dump-parser programs unrelated to this build.
2. Root module CMake inputs, and C/C++ source/header/template, CMake, shell,
   configuration-template and notice files in each of the 52 compiled modules.
   Selection follows the recorded suffix/name rules rather than copying all
   module data. In particular, preserve
   `modules/mod-chat-transmitter/libs/nlohmann/json.hpp`: it is included by a
   relative path and would be missed by a `src/`-only copy.
3. The complete Eluna Git tree at
   `58d7652138887783228b9727bd1fa4e08f00342b`, including its extension licenses.
   Apply the exact selected integration patches reproducibly to pristine blobs;
   record the resulting changed identities separately.
4. Exact integration build/verification recipes, adaptation patches and CMake
   reference-fixture inputs from the actual build revision. Preserve generated
   loader/revision metadata or describe its deterministic regeneration. The
   original CMake revision generator reads Git metadata; an unpacked source tree
   without that metadata reports an archived/unknown revision.
5. The complete original **Lua 5.2.4** archive. The source CMake declaration pins
   `https://www.lua.org/ftp/lua-5.2.4.tar.gz` to SHA256
   `b9e2e4aad6789b3b63a056d442f7b39f0ecfca3ae0f1fc0ae4e9614401b69f4b`.
   The actual compile commands use 32 C files from `out/server/_deps/lua52-src`.
   This archive is external to both Git repositories and has not been downloaded
   by this audit. Retain its actual license-bearing files after verifying it;
   do not invent a required filename.

The candidate Git selection contains 4,942 files and 69,805,005 bytes, before
integration recipes and the external Lua archive. Every observed server source
path is present and each observed source include directory has selected files.
These checks establish coverage of the observed build inputs, **not a complete
transitive include proof**. Require a clean build from the isolated export with
excluded asset trees absent before marking source closure complete. Repeat the
audit against the actual seven-patch build before sealing its provider.

`noticeCandidates` records exact blob identities for 65 license/notice-bearing
files. It includes embedded notices in gSOAP's source, G3D's `license.cpp`,
utf8cpp, fkYAML, zlib and the bundled nlohmann header, as well as standalone
dependency/module/Eluna license files. Preserve their bytes and paths; do not
assign one blanket license to the whole selection. The separately published
Ubuntu dependency runtime retains its own notices and complete package sources.

Do not include the server's `Harvested/`, build/install output, MPQs, DBCs,
models, textures, databases, credentials or unrelated applications in this
engine source package. SQL/runtime Lua content has its own independently
verified content package. No engine or source archive is produced by this audit.
