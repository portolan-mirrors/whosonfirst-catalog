-- Every distribution behind every style class break and every count this
-- catalog's prose quotes. Run it against the built files and compare:
--
--   duckdb -c ".read tools/distributions.sql"
--
-- from the repository root, with the staging tree in its default place
-- (../whosonfirst-staging). Nothing here writes anything.
--
-- If a number here has moved, a style's legend or a sentence in a README is
-- now wrong. tests/test_styles.py is the gate for the style half of that.

INSTALL spatial; LOAD spatial;
SET memory_limit = '12GB';

CREATE OR REPLACE MACRO b(c) AS
  '../whosonfirst-staging/publish/' || c || '/wof_' || c || '.parquet';

-- ---------------------------------------------------------------------------
-- 1. The upstream file: what is in it, and what this catalog carries
-- ---------------------------------------------------------------------------
.print '=== upstream placetypes ==='
SELECT placetype, count(*) AS rows
FROM read_parquet('../whosonfirst-staging/sources/whosonfirst-data-admin-latest.parquet')
GROUP BY 1 ORDER BY 2 DESC;

-- ---------------------------------------------------------------------------
-- 2. Vertex distribution per level -- the measurement that decides which
--    levels get a display-simplified companion (DISPLAY_LEVELS).
-- ---------------------------------------------------------------------------
.print '=== vertices per feature, per level ==='
SELECT level, count(*) AS features,
       count(*) FILTER (vertices = 1) AS point_geometries,
       round(sum(vertices) / 1e6, 2) AS mega_vertices,
       round(median(vertices)) AS median,
       round(quantile_cont(vertices, 0.95)) AS p95,
       max(vertices) AS max
FROM read_parquet([b('country'), b('region'), b('county'),
                   b('localadmin'), b('locality'), b('neighbourhood')])
GROUP BY 1 ORDER BY 1;

-- ---------------------------------------------------------------------------
-- 3. Style class breaks
-- ---------------------------------------------------------------------------
.print '=== placetype within each collection (the placetype style) ==='
SELECT level, placetype, count(*) AS rows
FROM read_parquet([b('country'), b('region'), b('county'),
                   b('localadmin'), b('locality'), b('neighbourhood')])
GROUP BY 1, 2 ORDER BY 1, 3 DESC;

.print '=== geometry provenance (the geom_src style) ==='
SELECT level, coalesce(geom_src, '(none)') AS geom_src, count(*) AS rows
FROM read_parquet([b('country'), b('region'), b('county'),
                   b('localadmin'), b('locality'), b('neighbourhood')])
GROUP BY 1, 2 ORDER BY 1, 3 DESC;

.print '=== population coverage and bands (the population style) ==='
SELECT level,
       count(*) AS features,
       count(population) AS with_population,
       round(100.0 * count(population) / count(*), 1) AS pct,
       min(population) AS min, max(population) AS max,
       round(median(population)) AS median
FROM read_parquet([b('country'), b('region'), b('county'),
                   b('localadmin'), b('locality'), b('neighbourhood')])
GROUP BY 1 ORDER BY 1;

.print '=== min_zoom, WOF own label-importance signal (the prominence style) ==='
SELECT level, min_zoom, count(*) AS rows
FROM read_parquet([b('country'), b('region'), b('county'),
                   b('localadmin'), b('locality'), b('neighbourhood')])
GROUP BY 1, 2 ORDER BY 1, 2;

.print '=== is_funky, WOF own "needs a human" flag ==='
SELECT level, coalesce(is_funky::VARCHAR, '(null)') AS is_funky, count(*) AS rows
FROM read_parquet([b('country'), b('region'), b('county'),
                   b('localadmin'), b('locality'), b('neighbourhood')])
GROUP BY 1, 2 ORDER BY 1, 2;

.print '=== area_km2 bands ==='
SELECT level,
       round(min(area_km2), 4) AS min,
       round(quantile_cont(area_km2, 0.25), 2) AS p25,
       round(median(area_km2), 2) AS median,
       round(quantile_cont(area_km2, 0.75), 2) AS p75,
       round(quantile_cont(area_km2, 0.95), 2) AS p95,
       round(max(area_km2), 2) AS max
FROM read_parquet([b('country'), b('region'), b('county'),
                   b('localadmin'), b('locality'), b('neighbourhood')])
WHERE area_km2 > 0
GROUP BY 1 ORDER BY 1;

-- ---------------------------------------------------------------------------
-- 4. Country codes: the alpha-3 derivation, and WOF's six synthetic codes
-- ---------------------------------------------------------------------------
.print '=== country codes with no ISO 3166-1 alpha-3 ==='
SELECT country, country_iso2, count(*) AS rows
FROM read_parquet([b('country'), b('region'), b('county'),
                   b('localadmin'), b('locality'), b('neighbourhood')])
WHERE length(country) <> 3
GROUP BY 1, 2 ORDER BY 3 DESC;

-- ---------------------------------------------------------------------------
-- 5. The gazetteer index
-- ---------------------------------------------------------------------------
.print '=== index rows: primary against alternative spellings ==='
SELECT level,
       count(*) AS rows,
       count(*) FILTER (alt_of IS NULL) AS primary_rows,
       count(*) FILTER (alt_of IS NOT NULL) AS alt_rows
FROM read_parquet('../whosonfirst-staging/publish/names/wof_names.parquet')
GROUP BY 1 ORDER BY 1;

.print '=== the languages the alternative spellings come from ==='
SELECT name_lang, count(*) AS rows
FROM read_parquet('../whosonfirst-staging/publish/names/wof_names.parquet')
WHERE name_lang IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC;

.print '=== how ambiguous a bare name is (the ambiguity style) ==='
SELECT CASE WHEN name_dupes = 1 THEN '1'
            WHEN name_dupes <= 5 THEN '2-5'
            WHEN name_dupes <= 25 THEN '6-25'
            WHEN name_dupes <= 100 THEN '26-100'
            ELSE '100+' END AS band,
       count(*) AS rows
FROM read_parquet('../whosonfirst-staging/publish/names/wof_names.parquet')
GROUP BY 1 ORDER BY 1;

.print '=== the most ambiguous names in the world ==='
SELECT name_norm, any_value(name) AS example, max(name_dupes) AS places
FROM read_parquet('../whosonfirst-staging/publish/names/wof_names.parquet')
GROUP BY 1 ORDER BY 3 DESC LIMIT 15;
