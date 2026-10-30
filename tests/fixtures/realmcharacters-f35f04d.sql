-- Exact CREATE fragment from Russianranger/EsteriaWoW f35f04d01689f034778e3474b3c820092f51e461
-- Source: data/sql/base/db_auth/realmcharacters.sql
-- Full source SHA256: ce6b1c44b436373414ed816ee2f14bf2cbf8736d6dd13da8831fea0c10c043e8
CREATE TABLE `realmcharacters` (
  `realmid` int unsigned NOT NULL DEFAULT '0',
  `acctid` int unsigned NOT NULL,
  `numchars` tinyint unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`realmid`,`acctid`),
  KEY `acctid` (`acctid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Realm Character Tracker';
