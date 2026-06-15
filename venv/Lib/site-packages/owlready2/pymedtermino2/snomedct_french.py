# -*- coding: utf-8 -*-
# Owlready2
# Copyright (C) 2019 Jean-Baptiste LAMY
# LIMICS (Laboratoire d'informatique médicale et d'ingénierie des connaissances en santé), UMR_S 1142
# University Paris 13, Sorbonne paris-Cité, Bobigny, France

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


from owlready2 import *

# Download source : https://smt.esante.gouv.fr/terminologie-snomed-ct-fr/
# Then unzip and use file ./terminologie-snomed-ct-fr-Juin 2024 v1.0/dat/SnomedCT_NationalFR_OWL_asserted_20240621.owl
# (exact name may vary according to version)

def import_snomedct_french(snomedct_owl_filename, include_synonyms = True):
  current = None
  in_label = in_syno = False
  
  PYM = get_ontology("http://PYM/").load()
  SNO = PYM["SNOMEDCT_US"]
  
  with open(snomedct_owl_filename) as f:
    for l in f.readlines():
      l = l.strip(".,;\n")
      if   l.startswith("<http://snomed.info/id/"):
        current = l[23:].split(">", 1)[0]
      else:
        l = l.strip()
        if   l.startswith("rdfs:label"):
          l = l.split(None, 1)[1]
          in_label = True
          in_syno  = False
        elif l.startswith("skos:altLabel"):
          l = l.split(None, 1)[1]
          in_label = False
          in_syno  = True
        elif not l.startswith('"'):
          in_label = in_syno = False
        
      if (in_label or in_syno) and l.startswith('"') and l.endswith("@fr"):
        l = l[1:-4]
        c = SNO[current]
        if c:
          if in_label:
            c.label.append(locstr(l, "fr"))
          else:
            if not include_synonyms: continue
            c.synonyms.append(locstr(l, "fr"))
