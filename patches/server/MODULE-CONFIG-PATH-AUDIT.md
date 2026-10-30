# Runtime module configuration directory

This adaptation is prepared against server
`f35f04d01689f034778e3474b3c820092f51e461`. It is not a SQL or content change.

`ConfigMgr::GetConfigPath()` returns the compiled `_CONF_DIR` on Linux and
`configs/` on Windows. All three applications first use that API to resolve
their default main configuration filename, accept `--config`/`-c` through their
existing Boost command-line parser, then pass the resolved filename to
`ConfigMgr::Configure`. Worldserver also passes its generated module file list.

Before this adaptation, `LoadModulesConfigs()` always appended `modules/` to
the compiled default directory, even when the user selected another main
configuration. A relocatable installed runtime would therefore search the
build runner's install path rather than the rendered configuration generation.

Patch 0007 changes only that module directory expression. It obtains the main
filename through the existing locked `GetFilename()` accessor and joins its
parent with `modules` using `std::filesystem`. A bare main filename uses the
relative `modules/` directory; a relative or absolute main filename uses its
sibling directory. The main file is not canonicalized or replaced, and no
fallback to a different directory is introduced. The default resolver is
unchanged, so existing application defaults still select their original
module locations. Module filename registration, order, missing-file policy,
parsing, environment overrides and reload behavior retain their source logic.

The isolated `esteria_config_path_reference` links the real `common` target and
calls the actual `ConfigMgr`: it checks distinct loaded values for absolute,
relative and bare main filenames, reloads changed module values, checks the
existing default directory contract, and verifies that a missing sibling module
does not borrow a configuration from the working directory. It only creates a
new disposable fixture directory, refusing re-entry. No parser, logger or
filesystem implementation is stubbed.

On 2026-10-30 the reference compiled and passed on the x86_64 Linux host with
GNU++20, the actual patched `Config.cpp`, the pinned server's real logging and
utility implementation files and vendored fmt, and previously checksum-verified
Boost 1.83 headers. An otherwise identical build with the original `Config.cpp`
compiled but failed the path reference, establishing the regression check. The
Python runner also verified that an existing fixture is rejected without
rewriting its configuration. The patched executable SHA-256 was
`86483df486b43645983e8a9b6e12c6f52f760b937e8ae9b589d135ce337e3f8e`;
the unpatched control was
`1aa0021565d1989e7c79d089bce31e9ef3cb6620dc397e7ed0fedba8817c3a58`.
This isolated host evidence does not establish ARM64/common-target integration,
world startup or gameplay. Source-lock activation awaits the existing full
server link gate and the next native reference build.
