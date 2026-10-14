# Local NBA research data

The owner authorized downloading [llimllib/nba_data](https://github.com/llimllib/nba_data).
Snapshot commit: `62df92a05f16b57498851167b8289cf9ec316aea`.
This preparation is separate from the fixture optimizer and its Yahoo database.

Run from the project root:

```bash
uv run python scripts/prepare_nba_data.py
# Recheck all local hashes, JSON, Parquet schemas and coverage without network:
uv run python scripts/prepare_nba_data.py --offline
```

The script pins the snapshot rather than following a moving branch. Downloads
resume by verifying upstream Git blob hashes. It verifies SHA-256 again before
building a replacement catalog. Errors stop preparation; an existing catalog
survives a failed rebuild. Changing the pin is an explicit reviewed update.

Local files, all ignored by Git:

- `data/nba_data/raw/`: 115 published v1 Parquet/summary JSON/documentation files,
  99,882,513 bytes. All 2010–2026 seasonal exports and four ESPN Parquet datasets.
- `data/nba_data/manifest.json`: commit, retrieval time, per-file Git blob and
  SHA-256 hashes, sizes and download scope.
- `data/nba_data/nba.duckdb`: 76 views over local Parquet. No network extensions.
- `data/nba_data/validation.json`: row counts, schemas, player-log duplicate keys,
  distinct-game coverage, null keys and makes/attempts diagnostics.

Raw daily ESPN response archives (about 2.1 GB) and the separate v2 object-storage
catalog are excluded. The published processed ESPN tables are included. The
upstream README and data dictionary are saved alongside the data.

Query with the installed DuckDB Python package:

```bash
uv run python - <<'PY'
import duckdb
with duckdb.connect('data/nba_data/nba.duckdb', read_only=True) as db:
    print(db.sql('SHOW TABLES'))
    print(db.sql('''
        SELECT personId AS nba_player_id,
               firstName || ' ' || familyName AS name,
               count(*) AS box_score_rows, sum(points) AS points
        FROM playerlog_2026
        WHERE starts_with(gameId, '002') AND minutes <> ''
        GROUP BY ALL ORDER BY points DESC LIMIT 10
    '''))
PY
```

The game prefix filter selects regular-season rows. Blank minutes can describe
nonparticipation; row counts are not automatically official games played. Table
names follow file stems; ESPN tables have the `espn_` prefix. Seasonal player logs
use NBA `personId` and string `gameId`, not Yahoo player keys. Do not concatenate
combined and seasonal exports: they overlap. Season filename 2026 means 2025–26.
Catalog paths are absolute: after moving the project, run the offline rebuild.

## Observed data limitations and review gate

The snapshot's combined player logs have 92,841 rows. Seasonal 2025 logs have
35,088 rows across 1,320 distinct games; 2026 has 37,405 across 1,401 games. Both
have zero duplicate `(gameId, personId, teamId)` keys. These games include multiple
game types; these counts do not establish complete regular-season coverage.
2010–2024 player logs cover only 4–15 distinct games each and contain repeated
keys. Preserve them as upstream evidence, not complete historical training data.
See validation.json for every season's counts and quality flags. Season-total
exports cannot repair missing games and must never be expanded into invented
per-game records. Raw rows remain unchanged; no inferred deduplication is applied.

Game dates, where present in team logs, are event dates. This snapshot provides no
verified historic first-publication timestamps; local retrieval time does not
prove what was known before retrieval. It cannot support leakage-free historical
injury/ownership/waiver replay. Minutes text and missing values need explicit
interpretation before creating a training contract. Percentages must be computed
from summed makes and attempts rather than averaging row percentages.

Acceptance for this stage is the verified downloadable snapshot and working
offline query catalog. Owner review of this preparation is next. Integration,
Yahoo/NBA identity mapping, training and live recommendations are separate work.
Rollback removes `data/nba_data` and the preparation script/docs. No model or
existing optimizer database depends on this catalog.
