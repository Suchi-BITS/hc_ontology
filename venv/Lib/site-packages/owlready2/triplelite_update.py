# -*- coding: utf-8 -*-
# Owlready2
# Copyright (C) 2017-2019 Jean-Baptiste LAMY
# LIMICS (Laboratoire d'informatique mÃ©dicale et d'ingÃ©nierie des connaissances en santÃ©), UMR_S 1142
# University Paris 13, Sorbonne paris-CitÃ©, Bobigny, France

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.

# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


# This file is used to update older versions of the triple store to the current version.

import os, os.path, sys, sqlite3

def update_graph(graph, version):
  if version == 1:
    print("* Owlready2 * Converting quadstore to internal format 2...", file = sys.stderr)
    graph.execute("""CREATE TABLE ontology_alias (iri TEXT, alias TEXT)""")
    graph.execute("""UPDATE store SET version=2""")
    graph.db.commit()
    version += 1
    
  if version == 2:
    print("* Owlready2 * Converting quadstore to internal format 3...", file = sys.stderr)
    graph.execute("""CREATE TABLE prop_fts (fts INTEGER PRIMARY KEY, storid TEXT)""")
    graph.execute("""UPDATE store SET version=3""")
    graph.db.commit()
    version += 1
        
  if version == 3:
    print("* Owlready2 * Converting quadstore to internal format 4 (this can take a while)...", file = sys.stderr)
    graph.execute("""CREATE TABLE objs (c INTEGER, s TEXT, p TEXT, o TEXT)""")
    graph.execute("""CREATE TABLE datas (c INTEGER, s TEXT, p TEXT, o BLOB, d TEXT)""")
    
    objs  = []
    datas = []
    for c,s,p,o in graph.execute("""SELECT c,s,p,o FROM quads"""):
      if o.endswith('"'):
        o, d = o.rsplit('"', 1)
        o = o[1:]
        if   d in {'H', 'N', 'R', 'O', 'J', 'I', 'M', 'P', 'K', 'Q', 'S', 'L'}: o = int(o)
        elif d in {'U', 'X', 'V', 'W'}: o = float(o)
        datas.append((c,s,p,o,d))
      else:
        objs.append((c,s,p,o))
    graph.db.executemany("INSERT INTO objs VALUES (?,?,?,?)",    objs)
    graph.db.executemany("INSERT INTO datas VALUES (?,?,?,?,?)", datas)
    
    graph.execute("""DROP TABLE quads""")
    graph.execute("""DROP INDEX IF EXISTS index_quads_s """)
    graph.execute("""DROP INDEX IF EXISTS index_quads_o""")
    graph.execute("""CREATE VIEW quads AS SELECT c,s,p,o,NULL AS d FROM objs UNION ALL SELECT c,s,p,o,d FROM datas""")
    graph.execute("""CREATE INDEX index_objs_sp ON objs(s,p)""")
    graph.execute("""CREATE INDEX index_objs_po ON objs(p,o)""")
    graph.execute("""CREATE INDEX index_datas_sp ON datas(s,p)""")
    graph.execute("""CREATE INDEX index_datas_po ON datas(p,o)""")
    
    graph.execute("""UPDATE store SET version=4""")
    graph.db.commit()
    version += 1
    
  if version == 4:
    print("* Owlready2 * Converting quadstore to internal format 5 (this can take a while)...", file = sys.stderr)
    graph.execute("""CREATE TABLE objs2 (c INTEGER, s INTEGER, p INTEGER, o INTEGER)""")
    graph.execute("""CREATE TABLE datas2 (c INTEGER, s INTEGER, p INTEGER, o BLOB, d INTEGER)""")
    
    _BASE_62 = { c : i for (i, c) in enumerate("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ") }
    def _base_62_2_int(storid):
      if storid.startswith("_"): sgn = -1; storid = storid[1:]
      else:                      sgn =  1
      r = 0
      for (i, c) in enumerate(storid):
        r += _BASE_62[c] * (62 ** (len(storid) - i - 1))
      return sgn * r
    
    try:
      graph.execute("""CREATE TABLE resources2 (storid INTEGER PRIMARY KEY, iri TEXT) WITHOUT ROWID""")
    except sqlite3.OperationalError: # Old SQLite3 does not support WITHOUT ROWID -- here it is just an optimization
      graph.execute("""CREATE TABLE resources2 (storid INTEGER PRIMARY KEY, iri TEXT)""")
    l = []
    for storid, iri in graph.execute("""SELECT storid, iri FROM resources"""):
      l.append((_base_62_2_int(storid), iri))
    graph.db.executemany("INSERT INTO resources2 VALUES (?,?)", l)
        
    l = []
    for c,s,p,o in graph.execute("""SELECT c,s,p,o FROM objs"""):
      s = _base_62_2_int(s)
      p = _base_62_2_int(p)
      o = _base_62_2_int(o)
      l.append((c,s,p,o))
    graph.db.executemany("INSERT INTO objs2 VALUES (?,?,?,?)", l)
        
    l = []
    for c,s,p,o,d in graph.execute("""SELECT c,s,p,o,d FROM datas"""):
      s = _base_62_2_int(s)
      p = _base_62_2_int(p)
      if   not d:  d = 0
      elif d.startswith("@"): pass
      else:        d = _base_62_2_int(d)
      l.append((c,s,p,o,d))
    graph.db.executemany("INSERT INTO datas2 VALUES (?,?,?,?,?)", l)
        
    graph.execute("""DROP INDEX IF EXISTS index_resources_iri""")
    graph.execute("""DROP INDEX IF EXISTS index_quads_s""")
    graph.execute("""DROP INDEX IF EXISTS index_quads_o""")
    graph.execute("""DROP INDEX IF EXISTS index_objs_sp""")
    graph.execute("""DROP INDEX IF EXISTS index_objs_po""")
    graph.execute("""DROP INDEX IF EXISTS index_datas_sp""")
    graph.execute("""DROP INDEX IF EXISTS index_datas_po""")
    graph.execute("""DROP VIEW IF EXISTS quads""")
    graph.execute("""DROP TABLE resources""")
    graph.execute("""DROP TABLE objs""")
    graph.execute("""DROP TABLE datas""")
    
    graph.execute("""ALTER TABLE resources2 RENAME TO resources""")
    graph.execute("""ALTER TABLE objs2 RENAME TO objs""")
    graph.execute("""ALTER TABLE datas2 RENAME TO datas""")
    graph.execute("""CREATE VIEW quads AS SELECT c,s,p,o,NULL AS d FROM objs UNION ALL SELECT c,s,p,o,d FROM datas""")
    
    graph.execute("""CREATE UNIQUE INDEX index_resources_iri ON resources(iri)""")
    graph.execute("""CREATE INDEX index_objs_sp ON objs(s,p)""")
    graph.execute("""CREATE INDEX index_objs_po ON objs(p,o)""")
    graph.execute("""CREATE INDEX index_datas_sp ON datas(s,p)""")
    graph.execute("""CREATE INDEX index_datas_po ON datas(p,o)""")
    
    prop_fts  = { storid : fts for (fts, storid) in graph.execute("""SELECT fts, storid FROM prop_fts;""") }
    prop_fts2 = { _base_62_2_int(storid) : fts for (storid, fts) in prop_fts.items() }
    for fts in prop_fts.values():
      graph.execute("""DROP TABLE fts_%s""" % fts)
      graph.execute("""DROP TRIGGER IF EXISTS fts_%s_after_insert""" % fts)
      graph.execute("""DROP TRIGGER IF EXISTS fts_%s_after_delete""" % fts)
      graph.execute("""DROP TRIGGER IF EXISTS fts_%s_after_update""" % fts)
      
    graph.execute("""DROP TABLE prop_fts""")
    graph.execute("""CREATE TABLE prop_fts(storid INTEGER)""")
    graph.prop_fts = set()
    for storid in prop_fts2: graph.enable_full_text_search(storid)
    
    graph.execute("""UPDATE store SET version=5""")
    graph.db.commit()
    version += 1

  if version == 5:
    print("* Owlready2 * Converting quadstore to internal format 6 (this can take a while)...", file = sys.stderr)
    graph.execute("""DROP INDEX IF EXISTS index_objs_po""")
    graph.execute("""DROP INDEX IF EXISTS index_datas_po""")
    graph.execute("""CREATE INDEX index_objs_op ON objs(o,p)""")
    graph.execute("""CREATE INDEX index_datas_op ON datas(o,p)""")
    
    graph.execute("""UPDATE store SET version=6""")
    graph.db.commit()
    version += 1
    
  if version == 6:
    print("* Owlready2 * Converting quadstore to internal format 7 (this can take a while)...", file = sys.stderr)

    prop_fts2 = { storid for (storid,) in graph.execute("""SELECT storid FROM prop_fts;""") }
    for prop_storid in prop_fts2:
      graph.execute("""DELETE FROM prop_fts WHERE storid = ?""", (prop_storid,))
      graph.execute("""DROP TABLE fts_%s""" % prop_storid)
      graph.execute("""DROP TRIGGER fts_%s_after_insert""" % prop_storid)
      graph.execute("""DROP TRIGGER fts_%s_after_delete""" % prop_storid)
      graph.execute("""DROP TRIGGER fts_%s_after_update""" % prop_storid)
    graph.prop_fts = set()
    for prop_storid in prop_fts2: graph.enable_full_text_search (prop_storid)

    graph.execute("""UPDATE store SET version=7""")
    graph.db.commit()
    version += 1
        
  if version == 7:
    print("* Owlready2 * Converting quadstore to internal format 8...", file = sys.stderr)
    
    import owlready2.base
    graph.db.executemany("""INSERT INTO resources VALUES (?,?)""", [
      (owlready2.base.swrl_variable, "http://www.w3.org/2003/11/swrl#Variable"),
      (owlready2.base.swrl_imp,                  "http://www.w3.org/2003/11/swrl#Imp"),
      (owlready2.base.swrl_body,                 "http://www.w3.org/2003/11/swrl#body"),
      (owlready2.base.swrl_head,                 "http://www.w3.org/2003/11/swrl#head"),
      (owlready2.base.swrl_class_atom,           "http://www.w3.org/2003/11/swrl#ClassAtom"),
      (owlready2.base.swrl_class_predicate,      "http://www.w3.org/2003/11/swrl#classPredicate"),
      (owlready2.base.swrl_dataprop_atom,        "http://www.w3.org/2003/11/swrl#DatavaluedPropertyAtom"),
      (owlready2.base.swrl_objprop_atom,         "http://www.w3.org/2003/11/swrl#IndividualPropertyAtom"),
      (owlready2.base.swrl_property_predicate,   "http://www.w3.org/2003/11/swrl#propertyPredicate"),
      (owlready2.base.swrl_builtin_atom,         "http://www.w3.org/2003/11/swrl#BuiltinAtom"),
      (owlready2.base.swrl_builtin,              "http://www.w3.org/2003/11/swrl#builtin"),
      (owlready2.base.swrl_datarange_atom,       "http://www.w3.org/2003/11/swrl#DataRangeAtom"),
      (owlready2.base.swrl_datarange,            "http://www.w3.org/2003/11/swrl#dataRange"),
      (owlready2.base.swrl_argument1,            "http://www.w3.org/2003/11/swrl#argument1"),
      (owlready2.base.swrl_argument2,            "http://www.w3.org/2003/11/swrl#argument2"),
      (owlready2.base.swrl_arguments,            "http://www.w3.org/2003/11/swrl#arguments"),
      (owlready2.base.swrl_equivalentindividual, "http://www.w3.org/2003/11/swrl#SameIndividualAtom"),
      (owlready2.base.swrl_differentfrom,        "http://www.w3.org/2003/11/swrl#DifferentIndividualsAtom"),
    ])
    graph.execute("""UPDATE store SET version=8""")
    graph.db.commit()
    version += 1

  if version == 8:
    print("* Owlready2 * Converting quadstore to internal format 9...", file = sys.stderr)
    graph.execute("""CREATE TABLE last_numbered_iri(prefix TEXT, i INTEGER)""")
    graph.execute("""CREATE INDEX index_last_numbered_iri ON last_numbered_iri(prefix)""")
    graph.execute("""UPDATE store SET version=9""")
    graph.db.commit()
    version += 1

  if version == 9:
    print("* Owlready2 * Converting quadstore to internal format 10...", file = sys.stderr)
    graph.execute("""CREATE INDEX index_objs_c ON objs(c)""")
    graph.execute("""CREATE INDEX index_datas_c ON datas(c)""")
    graph.execute("""UPDATE store SET version=10""")
    graph.db.commit()
    version += 1

  if version == 10:
    print("* Owlready2 * Converting quadstore to internal format 11...", file = sys.stderr)
    graph.execute("""CREATE VIEW quads2 AS SELECT c,s,p,o,'o' AS d FROM objs UNION ALL SELECT c,s,p,o,d FROM datas""") # AVoid using NULL because, in SQL, NULL != NULL.
    graph.execute("""UPDATE store SET version=11""")
    graph.db.commit()
    version += 1
    
  if version == 11:
    print("* Owlready2 * Converting quadstore to internal format 12...", file = sys.stderr)
    graph.execute("""UPDATE store SET current_resource=(SELECT MAX(storid) FROM resources)""")
    graph.execute("""UPDATE store SET version=12""")
    graph.db.commit()
    version += 1
