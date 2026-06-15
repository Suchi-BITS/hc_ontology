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


import sys, os, io, types, zipfile, requests
from collections import defaultdict, Counter
from owlready2 import *

def import_icd10_french_rdf(atih_data = None):
  """Get atih_data from https://smt.esante.gouv.fr/terminologie-cim-10/ """
  
  if not atih_data:
    raise ValueError("Get atih_data from https://smt.esante.gouv.fr/terminologie-cim-10/!")
  
  PYM  = get_ontology("http://PYM/").load()
  ICD10 = PYM["ICD10"]
  
  print("Importing CIM10 from %s..." % atih_data)
  if atih_data.startswith("http:") or atih_data.startswith("https:"):
    f = requests.get(atih_data)
    f = io.BytesIO(f._content)
  else:
    f = open(atih_data, "rb")
    
  parents = []
  
  CHAPTER_2_CODE = {
    "01" : "A00-B99",
    "02" : "C00-D48",
    "03" : "D50-D89",
    "04" : "E00-E90",
    "05" : "F00-F99",
    "06" : "G00-G99",
    "07" : "H00-H59",
    "08" : "H60-H95",
    "09" : "I00-I99",
    "10" : "J00-J99",
    "11" : "K00-K93",
    "12" : "L00-L99",
    "13" : "M00-M99",
    "14" : "N00-N99",
    "15" : "O00-O99",
    "16" : "P00-P96",
    "17" : "Q00-Q99",
    "18" : "R00-R99",
    "19" : "S00-T98",
    "20" : "V01-Y98",
    "21" : "Z00-Z99",
    "22" : "U00-U99",
  }
  
  # ROMAN = {
  #   "01" : "I",
  #   "02" : "II",
  #   "03" : "III",
  #   "04" : "IV",
  #   "05" : "V",
  #   "06" : "VI",
  #   "07" : "VII",
  #   "08" : "VIII",
  #   "09" : "IX",
  #   "10" : "X",
  #   "11" : "XI",
  #   "12" : "XII",
  #   "13" : "XIII",
  #   "14" : "XIV",
  #   "15" : "XV",
  #   "16" : "XVI",
  #   "17" : "XVII",
  #   "18" : "XVIII",
  #   "19" : "XIX",
  #   "20" : "XX",
  #   "21" : "XXI",
  #   "22" : "XXII",
  # }
  
  onto = get_ontology("http://atih/cim10/")
  with onto:
    class dagger        (AnnotationProperty): pass
    class star          (AnnotationProperty): pass
    class note          (AnnotationProperty): pass
    class definition    (AnnotationProperty): pass
    class exclude       (AnnotationProperty): pass
    class inclusion_note  (AnnotationProperty): pass
    class exclusion_note  (AnnotationProperty): pass
    class coding_hint   (AnnotationProperty): pass
    
  with onto.get_namespace("http://PYM/SRC/"):
    ICD10_FRENCH = types.new_class("CIM10", (PYM["SRC"],))
    onto._set_obj_triple_spo  (ICD10_FRENCH.storid, PYM.terminology.storid, PYM["SRC"].storid)
    onto._set_data_triple_spod(ICD10_FRENCH.storid, label.storid, "CIM10", "@fr")
    
  def order_by_name(i): return i.name
  
  
  world = World()
  with world.get_ontology("http://datashapes.org/graphql"): pass
  with world.get_ontology("http://datashapes.org/dash"): pass
  
  with zipfile.ZipFile(f, "r") as atih_zip:
    with atih_zip.open("dat/terminologie-cim-10-2025-01-01.rdf") as rdf_file:
      atih_cim10 = world.get_ontology("http://data.esante.gouv.fr/atih/cim10").load(fileobj = rdf_file)      
      
  root = world["http://data.esante.gouv.fr/atih/cim10"]

  #chapters = [world["http://data.esante.gouv.fr/atih/cim10/%02i" % i] for i in range(1, 23)]
  #print(chapters)
  
  CIM10 = onto.get_namespace("http://PYM/CIM10/")
  with CIM10:
    def do_term(term):
      concept = types.new_class(CHAPTER_2_CODE.get(term.name, term.name), (ICD10_FRENCH,))
      concept.label = [locstr(label.replace('" ', '').replace(' "', '').replace('"', '').strip(), "fr") for label in term.label]
      onto._set_obj_triple_spo(concept.storid, PYM.terminology.storid, ICD10_FRENCH.storid)
      
      if term.altLabel: concept.synonyms = term.altLabel
      
      if concept.name in CHAPTER_2_CODE:
        icd10 = ICD10[CHAPTER_2_CODE[concept.name]]
        if not icd10:
          icd10 = ICD10[CHAPTER_2_CODE[concept.name] + ".9"]
      else:
        icd10 = ICD10[concept.name]
        if (not icd10) and ("-" in concept.name):
          icd10 = ICD10[concept.name + ".9"]
          
      if icd10:
        concept.unifieds = icd10.unifieds
        for cui in icd10.unifieds: cui.originals.append(concept)
        
      for sub_term in sorted(term.subclasses(), key = lambda c: c.name): do_term(sub_term)
      
    for sub_term in sorted(root.subclasses(), key = lambda c: c.name): do_term(sub_term)
    
    def do_term2(term):
      concept = IRIS["http://PYM/CIM10/%s" % CHAPTER_2_CODE.get(term.name, term.name)]
      
      parent_name = term.is_a[0].name
      if parent_name != "cim10":
        l = list(concept.is_a)
        l.remove(ICD10_FRENCH)
        l.append(IRIS["http://PYM/CIM10/%s" % CHAPTER_2_CODE.get(parent_name, parent_name)])
        concept.is_a = l
        
      concept.exclusion_note = term.exclusionNote
      concept.exclude = sorted([IRIS["http://PYM/CIM10/%s" % CHAPTER_2_CODE.get(i.name, i.name)] for i in term.exclusion], key = order_by_name)

      for note in term.inclusionNote:
        concept.inclusion_note.extend(i.strip() for i in note.split("\n") if i.strip())
      #concept.include = sorted([IRIS["http://PYM/CIM10/%s" % CHAPTER_2_CODE.get(i.name, i.name)] for i in term.inclusion], key = order_by_name)
      
      concept.coding_hint = term.scopeNote
      concept.definition  = term.definition
      concept.note        = term.note
      
      concept.dagger = sorted([IRIS["http://PYM/CIM10/%s" % CHAPTER_2_CODE.get(i.name, i.name)] for i in term.hasManifestation], key = order_by_name)
      for c in concept.dagger: c.star.append(concept)
      
      for sub_term in sorted(term.subclasses(), key = lambda c: c.name): do_term2(sub_term)
      
    #do_term2(root)
    for sub_term in sorted(root.subclasses(), key = lambda c: c.name): do_term2(sub_term)
    
  default_world.save()


  


  

#def import_icd10_french_claml(atih_data = "https://www.atih.sante.fr/sites/default/files/public/content/3963/cim10fmclassification_internationale_des_maladies_cim-10-fr_2021syst_claml_20210302.zip"):
#def import_icd10_french_claml(atih_data = "https://www.atih.sante.fr/sites/default/files/public/content/4674/cim10fr2024syst_claml_20231215.zip"):
def import_icd10_french_claml(atih_data = "https://www.atih.sante.fr/sites/default/files/public/content/4901/cim10frfm2025syst_claml_20241216_0.zip"):
  import xml.sax as sax, xml.sax.handler as handler
  
  PYM  = get_ontology("http://PYM/").load()
  ICD10 = PYM["ICD10"]
  
  print("Importing CIM10 from %s..." % atih_data)
  if atih_data.startswith("http:") or atih_data.startswith("https:"):
    f = requests.get(atih_data)
    f = io.BytesIO(f._content)
  else:
    f = open(atih_data, "rb")
    
  parents = []
  
  CHAPTER_2_CODE = {
    "I" : "A00-B99",
    "II" : "C00-D48",
    "III" : "D50-D89",
    "IV" : "E00-E90",
    "V" : "F00-F99",
    "VI" : "G00-G99",
    "VII" : "H00-H59",
    "VIII" : "H60-H95",
    "IX" : "I00-I99",
    "X" : "J00-J99",
    "XI" : "K00-K93",
    "XII" : "L00-L99",
    "XIII" : "M00-M99",
    "XIV" : "N00-N99",
    "XV" : "O00-O99",
    "XVI" : "P00-P96",
    "XVII" : "Q00-Q99",
    "XVIII" : "R00-R99",
    "XIX" : "S00-T98",
    "XXII" : "U00-U99",
    "XX" : "V01-Y98",
    "XXI" : "Z00-Z99",
  }
  
  onto = get_ontology("http://atih/cim10/")
  with onto:
    class dagger        (AnnotationProperty): pass
    class star          (AnnotationProperty): pass
    class frenchspecific(AnnotationProperty): pass
    class note          (AnnotationProperty): pass
    class definition    (AnnotationProperty): pass
    class include       (AnnotationProperty): pass
    class exclude       (AnnotationProperty): pass
    class reference     (AnnotationProperty): pass
    class coding_hint   (AnnotationProperty): pass
    class introduction  (AnnotationProperty): pass
    class text          (AnnotationProperty): pass
    class footnote      (AnnotationProperty): pass
    
  with onto.get_namespace("http://PYM/SRC/"):
    ICD10_FRENCH = types.new_class("CIM10", (PYM["SRC"],))
    onto._set_obj_triple_spo  (ICD10_FRENCH.storid, PYM.terminology.storid, PYM["SRC"].storid)
    onto._set_data_triple_spod(ICD10_FRENCH.storid, label.storid, "CIM10", "@fr")

  MODIFIERS = defaultdict(list)
  MODIFIER_CODE_2_CHAR = {}
  class Modifier(object):
    def __init__(self, name, code):
      self.name   = name
      self.code   = code
      self.props  = defaultdict(list)
      self.annots = []
      MODIFIERS[name].append(self)
      
  
  ANNOTS = []
  CONCEPT_2_MODIFIER_CODES = defaultdict(list)
  class Handler(handler.ContentHandler):
    def __init__(self):
      self.concept                   = None
      self.inhibited                 = 0
      self.content                   = ""
      self.references                = []
      self.current_modifier_category = None
      self.current_modifier          = None
      self.concept_modifiers         = []
      
    def startElement(self, name, attrs):
      if self.inhibited: return
      
      if   name == "Fragment":
        self.content = "%s " % self.content.strip()
        if attrs.get("usage") == "dagger": self.dagger = True
        
      elif name == "Reference":
        self.content = "%s " % self.content.strip()
        
      elif name == "Modifier":
        self.inhibited += 1
        self.current_modifier_category = attrs["code"]
        
      elif name == "ModifierClass":
        self.current_modifier = Modifier(attrs["modifier"], attrs["code"])
        
      elif name == "ModifiedBy":
        #if "-" in self.concept.name: return # Sinon, c'est juste une annonce commune pour l'ensemble des enfants/descendants
        #char = MODIFIER_CODE_2_CHAR.get(attrs["code"])
        #if char and (char != len(self.concept.name.replace(".", " ")) + 1):
        #  print("!!!!", self.concept.name, attrs["code"], char)
        #  return
        #
        #self.concept_modifiers.append(attrs["code"])
        
        CONCEPT_2_MODIFIER_CODES[self.concept.name].append(attrs["code"])
        
      elif name == "Class":
        self.concept_modifiers = []
        self.concept = types.new_class(attrs["code"].replace("–", "-"), (ICD10_FRENCH,))
        if attrs.get("usage") == "dagger": self.concept.dagger = True
        if attrs.get("usage") == "aster":  self.concept.star   = True
        
        onto._set_obj_triple_spo(self.concept.storid, PYM.terminology.storid, ICD10_FRENCH.storid)
        
        if self.concept.name in CHAPTER_2_CODE:
          icd10 = ICD10[CHAPTER_2_CODE[self.concept.name]]
          if not icd10:
            icd10 = ICD10[CHAPTER_2_CODE[self.concept.name] + ".9"]
        else:
          icd10 = ICD10[self.concept.name]
          if (not icd10) and ("-" in self.concept.name):
            icd10 = ICD10[self.concept.name + ".9"]
            
        if icd10:
          self.concept.unifieds = icd10.unifieds
          for cui in icd10.unifieds: cui.originals.append(self.concept)
          
      elif name == "SuperClass":
        if not self.concept: return
        l = list(self.concept.is_a)
        l.remove(ICD10_FRENCH)
        l.append(ICD10_FRENCH[attrs["code"]])
        self.concept.is_a = l
        
      elif name == "Meta":
        if (attrs["name"] == "frenchspecific") and (attrs["value"] == "true"): self.concept.frenchspecific = True
        
      elif name == "Rubric":
        self.kind = attrs["kind"]
        
      elif name == "Label":
        self.content    = ""
        self.references = []
        self.dagger     = False
        
    def endElement(self, name):
      if name == "Modifier":
        self.current_modifier_category = None
        self.inhibited -= 1
      if self.inhibited: return
      
      if   name == "ModifierClass":
        self.current_modifier = None
        
      self.content = self.content.strip()
      
      if self.content:
        if   name == "Label":
          self.content = locstr(self.content, "fr")
          if   self.kind == "preferred":    prop = label
          elif self.kind == "note":         prop = note
          elif self.kind == "inclusion":    prop = include
          elif self.kind == "exclusion":    prop = exclude
          elif self.kind == "coding-hint":  prop = coding_hint
          elif self.kind == "introduction": prop = introduction
          elif self.kind == "definition":   prop = definition
          elif self.kind == "text":         prop = text
          elif self.kind == "footnote":     prop = footnote
          elif self.kind == "modifierlink": prop = None
          
          if prop:
            if self.current_modifier:
              self.current_modifier.props[prop].append(self.content)
              
              if self.dagger: self.current_modifier.props[dagger] = True
              
              for ref in self.references:
                self.current_modifier.annots.append((prop, self.content, reference, ref))
                
            else:
              getattr(self.concept, prop.name).append(self.content)
              
              if self.dagger: dagger[(self.concept, prop, self.content)] = True
              
              for ref in self.references:
                ANNOTS.append(((self.concept, prop, self.content), reference, ref))
                
        elif name == "Reference":
          self.references.append(self.content.strip().split()[-1])
          
        elif name == "Fragment":
          if self.content.endswith(":"): self.content = self.content[:-1]
          
    def characters(self, content):
      if self.current_modifier_category:
        if   "quatrième" in content:  MODIFIER_CODE_2_CHAR[self.current_modifier_category] = 4
        elif "cinquième" in content:  MODIFIER_CODE_2_CHAR[self.current_modifier_category] = 5
        elif "sixième"   in content:  MODIFIER_CODE_2_CHAR[self.current_modifier_category] = 6
        
      if self.inhibited: return
      self.content += content
      
      
  with onto.get_namespace("http://PYM/CIM10/"):
    with zipfile.ZipFile(f, "r") as atih_zip:
      for filename in atih_zip.namelist():
        if filename.endswith(".xml"): break
      xml = atih_zip.open(filename, "r").read()
      xml = StringIO(xml.decode("utf8"))
      parser = sax.make_parser()
      parser.setContentHandler(Handler())
      parser.parse(xml)

      ALL_CODES = open("/tmp/cim").read().split()
      def add_from_modifiers():
        added = []
        for concept in sorted(ICD10_FRENCH.descendants(), key = lambda concept: (-len(concept.name), concept.name)): # On les trie pour faire en premier les plus profonds
          if "-" in concept.name: continue
          #if not concept.name.startswith("E11"): continue
          
          concept_modifier_codes = set()
          ancestor = concept
          while ancestor:
            concept_modifier_codes.update(CONCEPT_2_MODIFIER_CODES.get(ancestor.name) or [])
            if not ancestor.parents: break
            ancestor = ancestor.parents[0]
            
          for modifier_code in sorted(concept_modifier_codes):
            char = MODIFIER_CODE_2_CHAR.get(modifier_code)
            
            ajout_code = ""
            if char:
              pos = len(concept.name.replace(".", "")) + 1
              if char < pos:   continue
              elif char > pos: continue #ajout_code = "0" * (char - pos)

            for modifier in MODIFIERS[modifier_code]:
              modified_code  = concept.name
              modified_code += ajout_code
              modified_code += modifier.code
              if modified_code[3] != ".": continue
              if ICD10_FRENCH[modified_code]: continue
              if modified_code.count(".") > 1: continue # Bug in ATIH file
              
              if not modified_code in ALL_CODES:
                print("  ", (modified_code, concept.name, ajout_code, modifier.code, "   ", char, modifier_code))
                
              modified_concept = types.new_class(modified_code, (ICD10_FRENCH,))
              l = list(modified_concept.is_a)
              l.remove(ICD10_FRENCH)
              l.append(concept)
              modified_concept.is_a = l
              onto._set_obj_triple_spo(modified_concept.storid, PYM.terminology.storid, ICD10_FRENCH.storid)
              added.append(modified_concept)
              
              for prop, value in modifier.props.items():
                if prop is label:
                  value = value[0]
                  if value[1] == value[1].lower(): value = "%s%s" % (value[0].lower(), value[1:])
                  modified_concept.label.append("%s : %s" % (concept.label.first(), value))
                else:
                  setattr(modified_concept, prop.name, value)

              for prop, value, annot, ref in modifier.annots:
                ANNOTS.append(((modified_concept, prop, value), annot, ref))

              #print(concept.name, modified_concept.name, modified_concept.label.first())
        return added

    #while True:
    #  added = add_from_modifiers()
    #  print(len(added))
    #  if not added: break

    add_from_modifiers()
      
      
    for s, p, o in ANNOTS:
      o = o.replace("–", "-")
      o2 = ICD10_FRENCH[o]
      if o2: p[s].append(o2)
      
    for k, v in CHAPTER_2_CODE.items():
      ICD10_FRENCH[k].name = v
      
  default_world.save()




# TXT data are no longer available, kept only for archive
def import_icd10_french_txt(atih_data = "https://www.atih.sante.fr/plateformes-de-transmission-et-logiciels/logiciels-espace-de-telechargement/telecharger/gratuit/11616/456"):
  PYM  = get_ontology("http://PYM/").load()
  ICD10 = PYM["ICD10"]
  
  print("Importing CIM10 from %s..." % atih_data)
  if atih_data.startswith("http:") or atih_data.startswith("https:"):
    f = requests.get(atih_data)
    f = io.BytesIO(f._content)
  else:
    f = open(atih_data, "rb")
  
  parents = []
  
  onto = get_ontology("http://atih/cim10/")
  with onto:
    class mco_had(AnnotationProperty): pass
    class psy    (AnnotationProperty): pass
    class ssr    (AnnotationProperty): pass
    
  with onto.get_namespace("http://PYM/SRC/"):
    ICD10_FRENCH = types.new_class("CIM10", (PYM["SRC"],))
    onto._set_obj_triple_spo  (ICD10_FRENCH.storid, PYM.terminology.storid, PYM["SRC"].storid)
    onto._set_data_triple_spod(ICD10_FRENCH.storid, label.storid, "CIM10", "@fr")
    
  with onto.get_namespace("http://PYM/CIM10/"):
    for line in open(os.path.join(os.path.dirname(__file__), "icd10_french_group_name.txt")).read().split("\n"):
      line = line.strip()
      if line and not line.startswith("#"):
        code, term = line.split(" ", 1)
        icd10 = ICD10[code]
        if not icd10:
          icd10 = ICD10["%s.9" % code]
          if not icd10:
            if   code == "B95-B98": icd10 = ICD10["B95-B97.9"]
            elif code == "G10-G14": icd10 = ICD10["G10-G13.9"]
            elif code == "J09-J18": icd10 = ICD10["J10-J18.9"]
            elif code == "K55-K64": icd10 = ICD10["K55-K63.9"]
            elif code == "O94-O99": icd10 = ICD10["O95-O99.9"]
            
        if icd10 is None:
          if not code in {"C00-C75", "V01-X59", "U00-U99", "U00-U49", "U82-U85", "U90-U99"}:
            print("WARNING: cannot align %s (%s) with ICD10 in UMLS!" % (code, term))
            
        start, end = code.split("-")
        end = "%s.99" % end
        for parent_start, parent_end, parent in parents:
          if (start >= parent_start) and (end <= parent_end):
            break
        else:
          if not code in {'F00-F99', 'H60-H95', 'E00-E90', 'R00-R99', 'L00-L99', 'O00-O99', 'C00-D48', 'M00-M99', 'U00-U99', 'S00-T98', 'K00-K93', 'G00-G99', 'I00-I99', 'H00-H59', 'N00-N99', 'V01-Y98', 'Q00-Q99', 'P00-P96', 'Z00-Z99', 'A00-B99', 'D50-D89', 'J00-J99'}:
            print("WARNING: cannot find parent for %s (%s)!" % (code, term))
          parent = ICD10_FRENCH
          
        icd10_french = types.new_class(code, (parent,))
        icd10_french.label = locstr(term, "fr")
        onto._set_obj_triple_spo(icd10_french.storid, PYM.terminology.storid, ICD10_FRENCH.storid)
        if icd10:
          icd10.unifieds = icd10.unifieds
          #with PYM:
          for cui in icd10.unifieds: cui.originals.append(icd10_french)
            
        parents.append((start, end, icd10_french))
        
        
    with zipfile.ZipFile(f, "r") as atih_zip:
      for line in atih_zip.open("LIBCIM10MULTI.TXT", "r"):
        if isinstance(line, bytes): line = line.decode("latin")
        line = line.strip()
        code, mco_had, ssr, psy, term_court, term = line.split("|")
        code = code.strip()
        if len(code) > 3: code = "%s.%s" % (code[:3], code[3:])
        

        if "+" in code:
          parent_code = code.split("+", 1)[0]
        else:
          parent_code = code[:-1]
          if parent_code.endswith("."): parent_code = code[:-2]
        parent = ICD10_FRENCH[parent_code]
        
        if not parent:
          code2 = code.split("+", 1)[0]
          for parent_start, parent_end, parent in reversed(parents):
            if (code2 >= parent_start) and (code2 <= parent_end):
              break
          else:
            print("WARNING: cannot find parent for %s (%s)!" % (code, term))
            parent = None
            
        icd10 = ICD10[code]
        
        if term.startswith("*** SU16 *** "): term = term.replace("*** SU16 *** ", "")
        
        icd10_french = types.new_class(code, (parent,))
        onto._set_obj_triple_spo(icd10_french.storid, PYM.terminology.storid, ICD10_FRENCH.storid)
        icd10_french.label = locstr(term, "fr")
        icd10_french.mco_had = [int(mco_had)]
        icd10_french.ssr     = [ssr]
        icd10_french.psy     = [int(psy)]
        if icd10:
          icd10_french.unifieds = icd10.unifieds
          #with PYM:
          for cui in icd10.unifieds: cui.originals.append(icd10_french)
          
  default_world.save()


import_icd10_french = import_icd10_french_rdf
