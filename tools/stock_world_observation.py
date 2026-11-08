"""Whitelisted native loader events; never returns raw worldserver logs."""
import re


def observations(raw):
    pools = {b'acore_auth', b'acore_characters', b'acore_world', b'acore_playerbots'}
    opened = sorted(name.decode() for name in pools if b"DatabasePool '" + name + b"' opened successfully" in raw)
    missing_tiles = sorted(set(match.decode() for match in re.findall(rb'(?i)(?<![A-Za-z0-9])([0-9]{7,9}\.map)\b', raw)))
    return dict(databasePoolsOpened=opened, configuredFileRead=b'Using configuration file' in raw,
                worldInformationStarted=b'Loading World Information...' in raw, worldVersionLoaded=b'Version DB world:' in raw,
                startingAreaDataRequired=b'Failed to find map files for starting areas' in raw,
                mapFilesNamed=missing_tiles[:16], dataStoresEntered=b'Initialize Data Stores...' in raw,
                databasePoolFailed=b'There were errors opening the MySQL connections' in raw,
                preparedStatementError=b'Error in mysql_stmt_prepare' in raw or b'STMT ERROR' in raw,
                mysqlErrorCodes=sorted(set(x.decode() for x in re.findall(rb'\bMY-[0-9]{6}\b', raw)))[:24],
                missingSharedLibraries=b'error while loading shared libraries' in raw,
                missingSqlTable=b"doesn't exist" in raw and b'Table ' in raw, unknownSqlColumn=b'Unknown column' in raw,
                mysqlConnectionFailed=b"Can't connect to" in raw,
                configErrors=b'Invalid or missing configuration file' in raw or b'Error loading config' in raw)
