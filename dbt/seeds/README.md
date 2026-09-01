# Seeds

## own_catalog.csv

**This is the only authored data in the project.** Everything else -- every price,
product, retailer and date -- comes from the Open Prices API and is stored raw in bronze
before parsing.

It stands in for *our* company catalogue: the prices a competitor-monitoring platform
compares against. There is no real company here, so it is generated from real products:

- barcodes, names and currencies are taken from products actually observed in the last
  60 days, so the join in `mart_price_gap_vs_own` matches real data
- `our_price` is set around each product's observed market average using a fixed spread
  (`random.seed(7)`, so the file is reproducible), roughly 55% above market and 45% at or
  below. A catalogue where every line is undercut is as unrealistic as one where none is.
- one deliberately inactive row exercises the `where active` filter

Regenerate it against fresh data rather than editing by hand; the generator is recorded
in the commit that introduced this file.
