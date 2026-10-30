-- Source-derived fresh-instance adaptation; NOT recovered canonical server SQL.
-- The pinned f35 C++ contract requires these two empty character appearance stores.
-- The caller proves all four databases fresh before the original baseline and
-- proves both tables absent immediately before applying this separate file.
-- No defaults, foreign keys, seeded rows or updater-ledger entries are inferred.

CREATE TABLE `character_body_shape` (
  `guid` INT UNSIGNED NOT NULL,
  `data` BINARY(49) NOT NULL,
  PRIMARY KEY (`guid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `character_retail_look` (
  `guid` INT UNSIGNED NOT NULL,
  `data` BINARY(132) NOT NULL,
  PRIMARY KEY (`guid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
