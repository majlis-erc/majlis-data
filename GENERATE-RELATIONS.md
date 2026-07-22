# Generating Relation JSON Files

This document explains how to generate relation JSON files for the Majlis network visualization feature.

## Overview

The relation generation system creates JSON files for D3.js network visualization. Relations are extracted from two sources and de-duplicated, then stored as one JSON file per entity showing its network (the entity itself plus all directly connected entities and their relations).

### Files

- **`generate-relations.py`** - Python script that extracts relations from XML and generates JSON files (no external dependencies)
- **`build.xml`** - Ant build file with `generate-relations` task that calls the Python script

## Output Structure

Generated JSON files are created in:
- `data/persons/rel/[id].json`
- `data/manuscripts/rel/[id].json`
- `data/places/rel/[id].json`
- `data/works/rel/[id].json`

### JSON Format

```json
{
  "nodes": [
    {
      "id": "person4",
      "type": "person",
      "name": "Yefet ben ʿEli"
    },
    {
      "id": "manuscript992",
      "type": "manuscript",
      "name": "St. Petersburg, National Library of Russia, Yevr.-Arab. I 2122"
    }
  ],
  "links": [
    {
      "source": "manuscript992",
      "target": "person4",
      "rel": "",
      "sources": [
        "St. Petersburg, National Library of Russia, Yevr.-Arab. I 2122",
        "Yefet ben ʿEli"
      ]
    }
  ]
}
```

**Node IDs:** Format is `type+id` (e.g., `person4`, `manuscript992`) for D3.js link resolution.

**Node names:** Simple title from `titleStmt/title[@level='a']` for all entity types.

**Link sources:** 
- For manuscripts: title + locus + objectType (if available)
- For other entities: simple name
- Both source and target names/descriptions included

## How to Run

### Direct Python Execution

```bash
python3 generate-relations.py
```

No external dependencies or services required. The script:
1. Cleans up old JSON files
2. Loads all entities and their metadata
3. Extracts relations from both dedicated files and entity embeddings
4. De-duplicates relations
5. Generates JSON files only for entities with actual relations
6. Logs extraction details to `relation-extraction.log.tsv`

### Build Time Execution

In the build pipeline (via `build.xml`):

```bash
ant xar
```

This runs the `generate-relations` task before packaging the XAR file. Works in CI/CD (GitHub Actions, etc.) without external services.

### Automated Generation (GitHub Actions)

The repository includes a GitHub Action (`.github/workflows/generate-relations.yml`) that automatically regenerates JSON files when committed to main:

**Triggers:**
- Commits to `main` that modify XML files in `data/`
- Changes to `generate-relations.py`
- Manual trigger via `workflow_dispatch`

**Process:**
1. GitHub Action checks out the repo
2. Installs Python 3.11 and `lxml` dependency
3. Runs `python3 generate-relations.py` (which cleans all old JSONs and regenerates from scratch)
4. Creates a pull request with the regenerated files for manual review
5. You review and merge the PR

This keeps the repository automatically in sync when entity XML data changes, while maintaining a review trail in pull request history.

### Manual/Local Updates

To regenerate locally after data changes:

```bash
cd /path/to/majlis-data
python3 generate-relations.py
```

The script removes all existing relation JSON files and regenerates them from scratch.

## Data Sources and XPaths

### Entity Data

**Entity names** extracted from each entity XML file using XPath:
```
.//tei:titleStmt/tei:title[@level='a']
```
- Returns simple text name for the entity
- Used for node names in JSON (all entity types)

**Manuscript metadata** (for rich descriptions in sources) using XPath:
```
.//tei:additions/tei:list/tei:item/tei:locus    (from attribute or text)
.//tei:additions/tei:list/tei:item/tei:objectType
```

### Relation Extraction (Two Sources)

Relations are extracted from **both** locations and de-duplicated:

#### 1. Dedicated Relation Files

**Source:** `data/relations/tei/*.xml`

**XPath:** `.//tei:relation`

**Element structure:**
```xml
<relation 
  name="[relation type]"
  active="https://jalit.org/person/4"
  passive="https://jalit.org/manuscript/1"
  mutual="https://jalit.org/place/12 https://jalit.org/work/13"
/>
```

#### 2. Entity-Embedded Relations

**Source:** Entity XML files in `data/[type]/tei/[id].xml`

**XPath:** `.//tei:additions/tei:list/tei:item//tei:relation`

**Same element structure as dedicated files**

### Relation Processing Logic

For each relation element, extract:
- `@active` → source entity (if present)
- `@passive` → target entity (if present)
- `@mutual` → space-separated list of mutual entities (if present)
- `@name` → relation type

**Valid relations require at least one of:** `@active`, `@passive`, or `@mutual`

**Generate directional links:**
1. If `active` AND `passive` → create link: `active → passive`
2. If `active` AND `mutual` → create links: `active → each_mutual`
3. If `passive` AND `mutual` → create links: `each_mutual → passive`

**De-duplication key:** `(source_type, source_id, target_type, target_id, rel_type)`
- Prevents duplicate links when same relation appears in both dedicated and entity-embedded sources

### JSON File Generation

**Files generated only for entities with relations**

**File content for each entity:**
- Central node: the entity itself
- Connected nodes: all entities directly linked to this entity (source or target)
- Links: all relations where this entity is source OR target

**Relations appear in both source and target files:**
Each relation link appears in both the source entity's JSON and the target entity's JSON with the same direction. For example, a relation `person4 → manuscript992` appears in both `persons/rel/4.json` and `manuscripts/rel/992.json`.

**File removal on re-run:**
All existing JSON files in `data/[type]/rel/` directories are deleted at script startup (via `_cleanup_old_json_files()`), ensuring fresh generation from current XML state. If updated XML removes relations for an entity, its JSON file is not regenerated (deleted and not recreated).

## Integration with srophe

To display the graph on entity pages in srophe:

1. Include the graph HTML template in record.html or a collapsible component
2. Load the JSON file: `/db/apps/majlis-data/data/[type]/rel/[id].json`
3. Pass to D3.js visualization (see `src/main/xar-resources/majlis_graph.html` for example)

Example HTML template:

```html
<div class="collapsible-header">
  <h3>Network Relations</h3>
</div>
<div class="collapsible-content">
  <div id="graph-container" style="width:100%;height:600px"></div>
</div>

<script>
  // Load JSON for current entity
  let entityType = 'person';  // or manuscript, place, work
  let entityId = '4';
  fetch(`/db/apps/majlis-data/data/${entityType}/rel/${entityId}.json`)
    .then(r => r.json())
    .then(data => {
      // Initialize D3 graph with data
      // See majlis_graph.html for implementation
    });
</script>
```

## Notes

- JSON files are generated fresh each time the script runs
- Relations without proper entity URIs are skipped
- Entities without names default to "Unknown"
- The graph includes the entity itself plus all directly connected entities
- Mutual relations are expanded into individual directional links

## Troubleshooting

### No JSON files generated
- Verify eXist-db has majlis-data deployed at `/db/apps/majlis-data/`
- Check that relation files exist in `data/relations/tei/`
- Ensure entity XML files have proper `titleStmt/title[@level='a']` elements

### Missing relations in JSON
- Verify relation URIs follow the format: `https://jalit.org/[type]/[id]`
- Check that both active/passive or mutual URIs reference valid entities
- Entity IDs must match filenames in the data directories

### Entity names are "Unknown"
- Verify XML files have `titleStmt/title[@level='a']` elements
- Check title has text content (not empty)

## Future Improvements

- [x] Integrate generation into CI/CD pipeline (GitHub Actions on XML changes) — **Implemented**
- [ ] Add caching for frequently accessed graphs
- [ ] Support filtering relations by type
- [ ] Add relation metadata (sources, citations) to JSON
- [ ] Optimize for large datasets (current approach loads all entities into memory)
