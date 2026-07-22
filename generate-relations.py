#!/usr/bin/env python3
"""
Generate relation JSON files from TEI XML data.

This script extracts relations from:
1. Dedicated relation XML files (data/relations/tei/*.xml)
2. Embedded relation elements in entity files

Outputs JSON files to data/[type]/rel/[id].json for visualization.
No external dependencies required - uses only Python standard library.
"""

import os
import json
import re
from pathlib import Path
from lxml import etree as ET
from collections import defaultdict


class RelationExtractor:
    """Extract relations from TEI XML files."""

    ENTITY_TYPES = [
        ('persons', 'person'),      # directory name, entity type
        ('manuscripts', 'manuscript'),
        ('places', 'place'),
        ('works', 'work'),
    ]
    TEI_NS = {'tei': 'http://www.tei-c.org/ns/1.0'}

    def __init__(self, data_dir, verbose=False):
        """Initialize with data directory path."""
        self.data_dir = Path(data_dir)
        self.entities = {}  # {type: {id: name}}
        self.entity_metadata = {}  # {type: {id: {name, locus, objectType}}}
        self.relations = []  # list of relation dicts
        self.seen_rels = set()  # for de-duplication
        self.verbose = verbose

        # Logging counters and details
        self.log = {
            'files_processed': {'file': 0, 'entity': 0},
            'relations_found': {'file': 0, 'entity': 0},
            'relations_valid': {'file': 0, 'entity': 0},
            'relations_empty': {'file': 0, 'entity': 0},
            'relations_invalid_uri': {'file': 0, 'entity': 0},
            'relations_deduped': 0,
            'entities_with_relations': 0,
            'entities_skipped_no_relations': 0,
        }
        self.log_entries = []  # TSV log entries

    def run(self):
        """Extract entities and relations, generate JSON files."""
        print("Cleaning up old relation JSON files...")
        self._cleanup_old_json_files()

        print("Loading entities...")
        self._load_entities()
        total_entities = sum(len(ids) for ids in self.entities.values())
        print(f"  Total: {total_entities} entities\n")

        print("Extracting relations from both sources:")
        print("  From data/relations/tei/*.xml:")
        self._extract_relations_from_files()

        print("  From entity files (additions/item//relation):")
        self._extract_relations_from_entities()

        print(f"\nGenerating JSON files...")
        self._generate_json_files()

    def _extract_sources_from_item(self, item, entity_type, entity_id):
        """Extract sources from item element (locus, objectType, quote, note)."""
        sources = []
        try:
            # Build base source from manuscript metadata + locus + objectType
            metadata = self.entity_metadata.get(entity_type, {}).get(entity_id, {})
            if metadata:
                parts = []
                if metadata.get('name'):
                    parts.append(metadata.get('name'))
                if metadata.get('locus'):
                    parts.append(metadata.get('locus'))
                if metadata.get('objectType'):
                    parts.append(metadata.get('objectType'))
                if parts:
                    sources.append(', '.join(parts))

            # Add quote text if available (direct evidence)
            quote = item.find('.//tei:quote', self.TEI_NS)
            if quote is not None:
                quote_text = ''.join(quote.itertext()).strip()
                if quote_text and len(quote_text) > 20:  # Only if substantial text
                    sources.append(f"Quote: {quote_text[:100]}...")

            # Add note if available (contextual info)
            note = item.find('.//tei:note', self.TEI_NS)
            if note is not None:
                note_text = (note.text or '').strip()
                if note_text:
                    sources.append(f"Note: {note_text[:100]}...")

        except Exception:
            pass

        return sources

    def _extract_bibl_sources(self, rel_elem):
        """Extract bibliography sources following a relation element."""
        sources = []
        try:
            # Get the parent listRelation
            list_rel = rel_elem.getparent()
            if list_rel is None:
                return sources

            # Get the parent ab (factoid)
            ab = list_rel.getparent()
            if ab is None:
                return sources

            # Find bibl elements that follow listRelation in the ab
            bibl_elems = ab.findall('.//tei:bibl', self.TEI_NS)
            for bibl in bibl_elems:
                # Try to get title first
                title = bibl.find('.//tei:title', self.TEI_NS)
                if title is not None and title.text:
                    sources.append(title.text.strip())
                else:
                    # Fall back to idno
                    idno = bibl.find('.//tei:idno', self.TEI_NS)
                    if idno is not None and idno.text:
                        sources.append(idno.text.strip())
        except Exception:
            pass  # Silently skip errors

        return sources

    def _cleanup_old_json_files(self):
        """Remove all existing relation JSON files to start fresh."""
        cleaned_count = 0
        for dir_name, entity_type in self.ENTITY_TYPES:
            rel_dir = self.data_dir / dir_name / 'rel'
            if rel_dir.exists():
                for json_file in rel_dir.glob('*.json'):
                    json_file.unlink()
                    cleaned_count += 1
        if cleaned_count > 0:
            print(f"  Removed {cleaned_count} old JSON file(s)\n")

    def _load_entities(self):
        """Load all entities from data directories."""
        for dir_name, entity_type in self.ENTITY_TYPES:
            self.entities[entity_type] = {}
            self.entity_metadata[entity_type] = {}
            type_dir = self.data_dir / dir_name / 'tei'

            if not type_dir.exists():
                print(f"  ⚠ {type_dir} not found")
                continue

            for xml_file in type_dir.glob('*.xml'):
                entity_id = xml_file.stem
                name = self._extract_entity_name(xml_file)
                self.entities[entity_type][entity_id] = name

                # Extract additional metadata for manuscripts
                metadata = {'name': name}
                if entity_type == 'manuscript':
                    locus_info = self._extract_manuscript_metadata(xml_file)
                    if locus_info:
                        metadata.update(locus_info)

                self.entity_metadata[entity_type][entity_id] = metadata
                print(f"  {entity_type}/{entity_id}: {name}")

    def _extract_manuscript_metadata(self, xml_file):
        """Extract locus and objectType from manuscript XML."""
        metadata = {}
        try:
            tree = ET.parse(xml_file, ET.XMLParser(recover=True))
            root = tree.getroot()

            # Get locus from first additions/item/locus (prefer 'from' attribute)
            locus_elem = root.find('.//tei:additions/tei:list/tei:item/tei:locus', self.TEI_NS)
            if locus_elem is not None:
                locus_text = locus_elem.get('from') or locus_elem.text
                if locus_text:
                    # Normalize whitespace
                    locus_clean = ' '.join(locus_text.split())
                    metadata['locus'] = locus_clean.strip()

            # Get objectType from first additions/item/objectType
            obj_type_elem = root.find('.//tei:additions/tei:list/tei:item/tei:objectType', self.TEI_NS)
            if obj_type_elem is not None and obj_type_elem.text:
                # Normalize whitespace
                obj_type_clean = ' '.join(obj_type_elem.text.split())
                metadata['objectType'] = obj_type_clean.strip()

        except Exception as e:
            pass  # Silently skip errors

        return metadata

    def _extract_entity_name(self, xml_file):
        """Extract entity name from titleStmt/title[@level='a']."""
        try:
            tree = ET.parse(xml_file, ET.XMLParser(recover=True))
            root = tree.getroot()

            title = root.find('.//tei:titleStmt/tei:title[@level="a"]', self.TEI_NS)
            if title is not None:
                text = title.text
                if text:
                    # Normalize whitespace: collapse multiple spaces and remove newlines
                    name = ' '.join(text.split())
                    return name.strip()
        except Exception as e:
            pass  # Silently skip errors

        return "Unknown"

    def _extract_relations_from_files(self):
        """Extract relations from dedicated relation XML files at data/relations/tei/*.xml"""
        rel_dir = self.data_dir / 'relations' / 'tei'

        if not rel_dir.exists():
            print(f"  ⚠ {rel_dir} not found")
            return

        for xml_file in sorted(rel_dir.glob('*.xml')):
            self.log['files_processed']['file'] += 1
            try:
                tree = ET.parse(xml_file, ET.XMLParser(recover=True))
                root = tree.getroot()
                file_rels = root.findall('.//tei:relation', self.TEI_NS)

                if file_rels:
                    print(f"  {xml_file.name}: {len(file_rels)} relation(s)")
                    for rel_elem in file_rels:
                        # Extract associated bibl for this relation
                        sources = self._extract_bibl_sources(rel_elem)
                        self._process_relation_element(rel_elem, source='file',
                                                       file_info=f"relations/{xml_file.stem}",
                                                       xpath=".//tei:relation",
                                                       sources=sources)
                else:
                    print(f"  {xml_file.name}: (no relations found)")

            except Exception as e:
                print(f"  ✗ Error parsing {xml_file.name}: {e}")

    def _extract_relations_from_entities(self):
        """Extract relations embedded in entity files at additions/item//relation."""
        total_entity_rels = 0

        for dir_name, entity_type in self.ENTITY_TYPES:
            type_dir = self.data_dir / dir_name / 'tei'

            if not type_dir.exists():
                continue

            entity_rels_in_type = 0
            for xml_file in sorted(type_dir.glob('*.xml')):
                self.log['files_processed']['entity'] += 1
                try:
                    tree = ET.parse(xml_file, ET.XMLParser(recover=True))
                    root = tree.getroot()

                    # Explicit XPath: additions/item//relation
                    for rel_elem in root.findall('.//tei:additions/tei:list/tei:item//tei:relation', self.TEI_NS):
                        # For entity-embedded relations, sources will be added during graph building
                        self._process_relation_element(rel_elem, source='entity',
                                                       file_info=f"{dir_name}/{xml_file.stem}",
                                                       xpath=".//tei:additions/tei:list/tei:item//tei:relation",
                                                       sources=[])
                        entity_rels_in_type += 1

                except Exception as e:
                    print(f"  ✗ Error parsing {xml_file.name}: {e}")

            if entity_rels_in_type > 0:
                print(f"  {dir_name}: {entity_rels_in_type} relation(s) in entity files")
                total_entity_rels += entity_rels_in_type

        if total_entity_rels == 0:
            print(f"  (No embedded relations found in entity files)")

    def _process_relation_element(self, rel_elem, source='file', file_info='', xpath='', sources=None):
        """Process a single relation element with validation and logging."""
        active = rel_elem.get('active', '').strip()
        passive = rel_elem.get('passive', '').strip()
        mutual_str = rel_elem.get('mutual', '').strip()
        rel_name = rel_elem.get('name', '').strip()
        ref = rel_elem.get('ref', '').strip()

        self.log['relations_found'][source] += 1

        # Validate: at least one of active/passive/mutual must be non-empty
        if not active and not passive and not mutual_str:
            self.log['relations_empty'][source] += 1
            self.log_entries.append({
                'source': source,
                'file_info': file_info,
                'xpath': xpath,
                'active': active,
                'passive': passive,
                'mutual': mutual_str,
                'name': rel_name,
                'ref': ref,
                'status': 'EMPTY',
                'created_files': '',
                'created_edges': '',
                'result': 'Skipped - no active/passive/mutual'
            })
            return

        mutual = [m.strip() for m in mutual_str.split() if m.strip()] if mutual_str else []

        # Track if this relation produces any valid edges
        valid_edges = 0
        created_edges = []

        # Extract active-passive relation
        if active and passive:
            if self._add_relation(active, passive, rel_name, ref, source, sources):
                valid_edges += 1
                # Track edges as entity keys (type/id) for later file mapping
                source_entity = self._parse_uri(active)
                target_entity = self._parse_uri(passive)
                if source_entity and target_entity:
                    created_edges.append((source_entity, target_entity))
        elif active and not passive:
            if self.verbose:
                print(f"    ⚠ INCOMPLETE: active without passive")
            self.log['relations_invalid_uri'][source] += 1
            self.log_entries.append({
                'source': source,
                'file_info': file_info,
                'xpath': xpath,
                'active': active,
                'passive': passive,
                'mutual': mutual_str,
                'name': rel_name,
                'ref': ref,
                'status': 'INVALID',
                'created_files': '',
                'created_edges': '',
                'result': 'Skipped - active without passive'
            })
            return
        elif passive and not active:
            if self.verbose:
                print(f"    ⚠ INCOMPLETE: passive without active")
            self.log['relations_invalid_uri'][source] += 1
            self.log_entries.append({
                'source': source,
                'file_info': file_info,
                'xpath': xpath,
                'active': active,
                'passive': passive,
                'mutual': mutual_str,
                'name': rel_name,
                'ref': ref,
                'status': 'INVALID',
                'created_files': '',
                'created_edges': '',
                'result': 'Skipped - passive without active'
            })
            return

        # Extract mutual relations (active + mutual)
        if active and mutual:
            for m_uri in mutual:
                if self._add_relation(active, m_uri, rel_name, ref, source, sources):
                    valid_edges += 1
                    source_entity = self._parse_uri(active)
                    target_entity = self._parse_uri(m_uri)
                    if source_entity and target_entity:
                        created_edges.append((source_entity, target_entity))

        # Extract mutual relations (passive + mutual)
        if passive and mutual:
            for m_uri in mutual:
                if self._add_relation(m_uri, passive, rel_name, ref, source, sources):
                    valid_edges += 1
                    source_entity = self._parse_uri(m_uri)
                    target_entity = self._parse_uri(passive)
                    if source_entity and target_entity:
                        created_edges.append((source_entity, target_entity))

        if valid_edges > 0:
            self.log['relations_valid'][source] += 1
            # Identify which entity files will contain these edges
            created_files = self._get_affected_entity_files(created_edges)
            # Format edges as readable strings: "person/4→place/12"
            edge_strings = [f"{e[0]['type']}/{e[0]['id']}→{e[1]['type']}/{e[1]['id']}"
                           for e in created_edges]
            self.log_entries.append({
                'source': source,
                'file_info': file_info,
                'xpath': xpath,
                'active': active,
                'passive': passive,
                'mutual': mutual_str,
                'name': rel_name,
                'ref': ref,
                'status': 'VALID',
                'created_files': '|'.join(created_files),
                'created_edges': '|'.join(edge_strings),
                'result': f'Created {valid_edges} edge(s)'
            })
            if self.verbose:
                print(f"    ✓ VALID: {valid_edges} edge(s)")
        else:
            self.log['relations_invalid_uri'][source] += 1
            self.log_entries.append({
                'source': source,
                'file_info': file_info,
                'xpath': xpath,
                'active': active,
                'passive': passive,
                'mutual': mutual_str,
                'name': rel_name,
                'ref': ref,
                'status': 'INVALID_URI',
                'created_files': '',
                'created_edges': '',
                'result': 'Skipped - invalid/unparseable URIs'
            })
            if self.verbose:
                print(f"    ✗ INVALID URI: could not parse URIs")

    def _add_relation(self, source_uri, target_uri, rel_type, ref, source, sources=None):
        """Add a relation, de-duplicating by (source, target, rel_type). Returns True if added."""
        source_entity = self._parse_uri(source_uri)
        target_entity = self._parse_uri(target_uri)

        if not source_entity or not target_entity:
            # URI parsing failed
            return False

        # De-duplication key
        key = (source_entity['type'], source_entity['id'],
               target_entity['type'], target_entity['id'],
               rel_type)

        if key in self.seen_rels:
            # Already seen this exact relation
            self.log['relations_deduped'] += 1
            return False

        self.seen_rels.add(key)
        rel_dict = {
            'source': source_entity,
            'target': target_entity,
            'rel': rel_type,
            'ref': ref
        }
        # Add sources if provided
        if sources:
            rel_dict['sources'] = sources

        self.relations.append(rel_dict)
        return True

    def _get_affected_entity_files(self, created_edges):
        """Extract unique entity file paths from created edges (entity tuples)."""
        affected = set()
        # Map entity type to directory name
        dir_map = {'person': 'persons', 'manuscript': 'manuscripts',
                  'place': 'places', 'work': 'works'}

        for source_entity, target_entity in created_edges:
            # Add source entity file
            source_type = source_entity.get('type')
            source_id = source_entity.get('id')
            if source_type and source_id:
                dir_name = dir_map.get(source_type, source_type)
                affected.add(f"{dir_name}/rel/{source_id}.json")

            # Add target entity file
            target_type = target_entity.get('type')
            target_id = target_entity.get('id')
            if target_type and target_id:
                dir_name = dir_map.get(target_type, target_type)
                affected.add(f"{dir_name}/rel/{target_id}.json")

        return sorted(affected)

    def _write_tsv_log(self, output_file):
        """Write detailed TSV log file of all relations processed."""
        import csv

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, delimiter='\t', fieldnames=[
                'source', 'file_info', 'xpath', 'active', 'passive', 'mutual', 'name', 'ref',
                'status', 'created_files', 'created_edges', 'result'
            ])
            writer.writeheader()
            writer.writerows(self.log_entries)

    def _parse_uri(self, uri):
        """Parse entity URI into {type, id}."""
        if not uri or not isinstance(uri, str):
            return None

        # Format: https://jalit.org/[type]/[id]
        match = re.search(r'/([^/]+)/([^/]+)/?$', uri)
        if match:
            return {'type': match.group(1), 'id': match.group(2)}

        return None

    def _generate_json_files(self):
        """Generate JSON graph file only for entities with actual relations."""
        entities_with_relations = 0
        entities_skipped = 0

        for dir_name, entity_type in self.ENTITY_TYPES:
            rel_dir = self.data_dir / dir_name / 'rel'
            rel_dir.mkdir(parents=True, exist_ok=True)

            for entity_id, entity_name in self.entities[entity_type].items():
                graph = self._build_entity_graph(entity_type, entity_id, entity_name)

                # Only generate JSON if entity has relations
                if len(graph['links']) > 0:
                    output_file = rel_dir / f"{entity_id}.json"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(graph, f, indent=2, ensure_ascii=False)

                    entities_with_relations += 1
                    print(f"  Generated {dir_name}/rel/{entity_id}.json")
                else:
                    entities_skipped += 1

        # Log the summary
        self.log['entities_with_relations'] = entities_with_relations
        self.log['entities_skipped_no_relations'] = entities_skipped

    def _build_entity_graph(self, entity_type, entity_id, entity_name):
        """Build a graph object for one entity showing its network."""
        nodes = []
        links = []
        seen_nodes = set()

        # Add the entity itself (node ID is type+id, e.g., "person4", "manuscript992")
        # Use simple name from titleStmt/title[@level='a']
        entity_node_id = f"{entity_type}{entity_id}"
        nodes.append({
            'id': entity_node_id,
            'type': entity_type,
            'name': entity_name
        })
        seen_nodes.add(entity_node_id)

        # Add related entities and links
        for rel in self.relations:
            source_node_id = f"{rel['source']['type']}{rel['source']['id']}"
            target_node_id = f"{rel['target']['type']}{rel['target']['id']}"

            # Include relation if this entity is source or target
            if source_node_id == entity_node_id:
                link = {
                    'source': source_node_id,
                    'target': target_node_id,
                    'rel': rel['rel']
                }

                # Build sources array: use rich descriptions for manuscripts, simple names otherwise
                sources_list = []

                # Add source description
                if rel['source']['type'] == 'manuscript':
                    # Rich description for manuscript (title + locus + objectType)
                    source_desc = self._build_entity_description(rel['source']['type'], rel['source']['id'])
                    if source_desc:
                        sources_list.append(source_desc)
                else:
                    # Simple name for other entities
                    source_name = self.entities.get(rel['source']['type'], {}).get(rel['source']['id'])
                    if source_name:
                        sources_list.append(source_name)

                # Add target description
                if rel['target']['type'] == 'manuscript':
                    # Rich description for manuscript (title + locus + objectType)
                    target_desc = self._build_entity_description(rel['target']['type'], rel['target']['id'])
                    if target_desc:
                        sources_list.append(target_desc)
                else:
                    # Simple name for other entities
                    target_name = self.entities.get(rel['target']['type'], {}).get(rel['target']['id'])
                    if target_name:
                        sources_list.append(target_name)

                if sources_list:
                    link['sources'] = sources_list
                links.append(link)

                # Add target node if not seen
                if target_node_id not in seen_nodes:
                    target_type = rel['target']['type']
                    target_id = rel['target']['id']
                    target_name = self.entities.get(target_type, {}).get(target_id, 'Unknown')
                    if target_name:  # Only add if we found the entity
                        nodes.append({
                            'id': target_node_id,
                            'type': target_type,
                            'name': target_name
                        })
                        seen_nodes.add(target_node_id)

            elif target_node_id == entity_node_id:
                link = {
                    'source': source_node_id,
                    'target': target_node_id,
                    'rel': rel['rel']
                }

                # Build sources array: use rich descriptions for manuscripts, simple names otherwise
                sources_list = []

                # Add source description
                if rel['source']['type'] == 'manuscript':
                    # Rich description for manuscript (title + locus + objectType)
                    source_desc = self._build_entity_description(rel['source']['type'], rel['source']['id'])
                    if source_desc:
                        sources_list.append(source_desc)
                else:
                    # Simple name for other entities
                    source_name = self.entities.get(rel['source']['type'], {}).get(rel['source']['id'])
                    if source_name:
                        sources_list.append(source_name)

                # Add target description
                if rel['target']['type'] == 'manuscript':
                    # Rich description for manuscript (title + locus + objectType)
                    target_desc = self._build_entity_description(rel['target']['type'], rel['target']['id'])
                    if target_desc:
                        sources_list.append(target_desc)
                else:
                    # Simple name for other entities
                    target_name = self.entities.get(rel['target']['type'], {}).get(rel['target']['id'])
                    if target_name:
                        sources_list.append(target_name)

                if sources_list:
                    link['sources'] = sources_list
                links.append(link)

                # Add source node if not seen
                if source_node_id not in seen_nodes:
                    source_type = rel['source']['type']
                    source_id = rel['source']['id']
                    source_name = self.entities.get(source_type, {}).get(source_id, 'Unknown')
                    if source_name:  # Only add if we found the entity
                        nodes.append({
                            'id': source_node_id,
                            'type': source_type,
                            'name': source_name
                        })
                        seen_nodes.add(source_node_id)

        return {'nodes': nodes, 'links': links}

    def _build_entity_description(self, entity_type, entity_id):
        """Build entity description for sources list in edges.
        For manuscripts: title + locus + objectType (any available part).
        For other entities: just the simple name."""
        if entity_type == 'manuscript':
            metadata = self.entity_metadata.get(entity_type, {}).get(entity_id, {})
            if metadata:
                # Get name, locus, objectType
                name = metadata.get('name', '').strip()
                locus = metadata.get('locus', '').strip()
                objecttype = metadata.get('objectType', '').strip()

                # Build description with available parts
                parts = []
                if name:
                    parts.append(name)
                if locus:
                    parts.append(locus)
                if objecttype:
                    parts.append(objecttype)

                if parts:  # If any part exists, join and return
                    return ', '.join(parts)

        # For non-manuscripts or if no metadata, return simple name
        return self.entities.get(entity_type, {}).get(entity_id)


def main():
    """Main entry point."""
    script_dir = Path(__file__).parent
    data_dir = script_dir / 'data'

    if not data_dir.exists():
        print(f"Error: {data_dir} not found")
        return 1

    extractor = RelationExtractor(data_dir)
    extractor.run()

    # Write TSV log
    log_file = script_dir / 'relation-extraction.log.tsv'
    extractor._write_tsv_log(log_file)

    print(f"\n✓ Relation JSON files generated successfully")
    print(f"✓ Log saved to: {log_file}")
    return 0


if __name__ == '__main__':
    exit(main())
