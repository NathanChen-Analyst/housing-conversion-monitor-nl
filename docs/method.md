# Method

*Placeholder. The full method card will be published together with the paper.*

**What is counted.** A dwelling (BAG verblijfsobject with `woonfunctie`) that came into existence, or
into residential use, in a building where office use disappeared. One count per dwelling, in the year
its first residential version became valid.

**How it is detected.** The production detector implements the CBS definition of a *transformatie*
(a dwelling added to the stock without new construction) as a set of rule families evaluated on
yearly stock snapshots of every pand and verblijfsobject reconstructed from the BAG version history,
with the office origin established from the building's own use history. Rule families cover: stock
presence, use change, unit creation, unit size, timing relative to construction, and the exclusion of
subdivisions and purely residential alterations. Thresholds and implementation are withheld until
publication.

**Validation.** *(placeholder)* Office-derived dwellings per year against the CBS *transformaties*
series by original use (kantoor). Chart to follow.

**Geography.** Every dwelling is assigned by coordinate to the 2012 CBS Wijk- en buurtkaart, so one
boundary vintage carries the whole series. Water-only buurten are excluded.

**Disclosure control.** Neighbourhood-years with fewer than three dwellings are published as "<3".
They remain in national and municipal totals.
