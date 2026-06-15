# -*- coding: utf-8 -*-
# Owlready2
# Copyright (C) 2013-2019 Jean-Baptiste LAMY
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

from owlready2.namespace import *
from owlready2.prop      import *
from owlready2.prop      import _CLASS_PROPS


class AnnotatedRelation(object):
  def __init__(self, s, p, o):
    if isinstance(s, AnnotatedRelationValueList): s = s._obj
    if isinstance(s, AnnotatedRelation):
      for bnode in s._bnodes:
        r = next(s.namespace.world.sparql("""SELECT ?g { GRAPH ?g { ??1 ??2 ??3 } }""", (bnode, p, o)), None)
        if r:
          self.__dict__["_s_storid"]  = bnode
          self.__dict__["namespace"] = r[0]
          break
      else:
        self.__dict__["_s_storid"]  = s._bnodes[0]
        self.__dict__["namespace"] = s.namespace
    else:
      self.__dict__["_s_storid"] = s.storid
      r = next(s.namespace.world.sparql("""SELECT ?g { GRAPH ?g { ??1 ??2 ??3 } }""", (s, p, o)), None)
      if r: self.__dict__["namespace"] = r[0]
      else: self.__dict__["namespace"] = s.namespace
    self.__dict__["_s"] = s
    self.__dict__["_p"] = p
    if isinstance(p, int): self.__dict__["_p_storid"] = p
    else:                  self.__dict__["_p_storid"] = p.storid
    self.__dict__["_o"] = o
    self.__dict__["_bnodes"] = []
    self.__dict__["_onto_2_bnode"] = {}
    
    for onto, bnode in self.namespace.world.sparql("""SELECT ?g ?x { GRAPH ?g { ?x owl:annotatedSource ??1 ; owl:annotatedProperty ??2 ; owl:annotatedTarget ??3 } }""", (self._s_storid, self._p_storid, o)):
      self._bnodes.append(bnode)
      self._onto_2_bnode[onto] = bnode
      
  def __repr__(self): return "<AnnotatedRelation for (%s, %s, %s) using blank nodes: %s>" % (self._s, self._p, self._o, " ".join(str(bnode) for bnode in self._bnodes))
  
  def _as_triple(self):
    if isinstance(self._s, AnnotatedRelation): return (self._s._as_triple(), self._p, self._o)
    return (self._s, self._p, self._o)
  
  def _get_bnode_for_onto(self, onto):
    bnode = self._onto_2_bnode.get(onto)
    if not bnode:
      bnode = self._onto_2_bnode[onto] = onto.world.new_blank_node()
    if not bnode in self._bnodes: # bnode can be a non-new, old, blank node reused from onto_2_bnode after deletion.
      self._bnodes.append(bnode)
      onto._add_obj_triple_spo(bnode, rdf_type, owl_axiom)
      onto._add_obj_triple_spo(bnode, owl_annotatedsource  , self._s_storid)
      onto._add_obj_triple_spo(bnode, owl_annotatedproperty, self._p_storid)
      o, d = onto._to_rdf(self._o)
      if d is None: onto._add_obj_triple_spo  (bnode, owl_annotatedtarget, o)
      else:         onto._add_data_triple_spod(bnode, owl_annotatedtarget, o, d)
    return bnode
  
  def _remove_bnode(self, bnode):
    self._bnodes.remove(bnode)
    self.namespace.world._del_obj_triple_spo  (bnode, None, None)
    self.namespace.world._del_data_triple_spod(bnode, None, None, None)

  def get_properties(self):
    return { Prop for Prop, in self.namespace.world.sparql("""
    SELECT DISTINCT ?p { ?x owl:annotatedSource ??1 ; owl:annotatedProperty ??2 ; owl:annotatedTarget ??3 ; ?p ?o .
    FILTER(?p NOT IN (owl:annotatedSource, owl:annotatedProperty, owl:annotatedTarget, rdf:type)) }""",
                                                           [self._s_storid, self._p_storid, self._o]) }
    
  def __getattr__(self, attr):
    Prop = self.namespace.world._props.get(attr)
    if not Prop: raise AttributeError("'%s' annotation is not defined." % attr)
    self.__dict__[attr] = r = AnnotatedRelationValueList(
      (self.namespace.ontology._to_python(o, d)
       for bnode in self._bnodes
       for o, d in self.namespace.world._get_triples_sp_od(bnode, Prop.storid)), self, Prop)
    return r
  
  def __setattr__(self, attr, value): getattr(self, attr).reinit(value)
  
class AnnotatedRelationValueList(CallbackListWithLanguage):
  __slots__ = ["_Prop"]
  def __init__(self, l, obj, Prop):
    list.__init__(self, l)
    self._obj  = obj
    self._Prop = Prop

  def __hash__(self): return id(self)
    
  def _callback(self, obj, old):
    old = set(old)
    new = set(self)
    
    deltas = new - old
    if deltas:
      l = CURRENT_NAMESPACES.get()
      onto  = (l and l[-1].ontology) or self._obj.namespace
      bnode = self._obj._get_bnode_for_onto(onto)
      for added in deltas:
        o, d = onto._to_rdf(added)
        if d is None: onto._add_obj_triple_spo  (bnode, self._Prop.storid, o)
        else:         onto._add_data_triple_spod(bnode, self._Prop.storid, o, d)
        
    world = self._obj.namespace.world
    
    for removed in old - new:
      o, d = self._obj.namespace._to_rdf(removed)
      if d is None:
        for bnode in self._obj._bnodes:
          if world._has_obj_triple_spo(bnode, self._Prop.storid, o):
            world._del_obj_triple_spo(bnode, self._Prop.storid, o) # Needed for observe
            if len(world._get_triples_s_pod(bnode)) <= 4: self._obj._remove_bnode(bnode)
            
      else:
        for bnode in self._obj._bnodes:
          if world._has_data_triple_spod(bnode, self._Prop.storid, o, d):
            world._del_data_triple_spod(bnode, self._Prop.storid, o, d) # Needed for observe
            if len(world._get_triples_s_pod(bnode)) <= 4: self._obj._remove_bnode(bnode)
      
    
class AnnotationPropertyClass(PropertyClass):
  _owl_type = owl_annotation_property
  inverse_property = inverse = None
  
  def __getitem__(Annot, entity):
    if isinstance(entity, tuple):
      return AnnotatedRelation(*entity).__getattr__(Annot.python_name)
    
    else:
      if Annot is entity.namespace.world._props.get(Annot._python_name) and not isinstance(entity, Construct): # use cached value
        r = getattr(entity, Annot._python_name)
        if isinstance(r, list): return r # May not be a list if hacked (e.g. Concept.terminology)
      return Annot._get_values_for_individual(entity)
    
  def __setitem__(Annot, index, values):
    if not isinstance(values, list): values = [values]
    Annot[index].reinit(values)
    
  def __call__(Prop, type, c, *args):
    raise ValueError("Cannot create a property value restriction on an annotation property!")
  
  def _get_indirect_values_for_individual(Prop, entity):
    values = [entity.namespace.ontology._to_python(o, d)
              for P in Prop.descendants(world = entity.namespace.world)
              for o, d in entity.namespace.world._get_triples_sp_od(entity.storid, P.storid)]
    return values
  
  _get_indirect_values_for_class = _get_indirect_values_for_individual
  
AnnotationPropertyClass.entity_class = AnnotationPropertyClass


class AnnotationProperty(Property, metaclass = AnnotationPropertyClass):
  namespace = owl
  
  @classmethod
  def is_functional_for(Prop, o): return False


_CLASS_PROPS.add(AnnotationProperty)

  
class comment               (AnnotationProperty): namespace = rdfs
class label                 (AnnotationProperty): namespace = rdfs
class backwardCompatibleWith(AnnotationProperty): namespace = owl
class deprecated            (AnnotationProperty): namespace = owl
class incompatibleWith      (AnnotationProperty): namespace = owl
class isDefinedBy           (AnnotationProperty): namespace = rdfs
class priorVersion          (AnnotationProperty): namespace = owl
class seeAlso               (AnnotationProperty): namespace = rdfs
class versionInfo           (AnnotationProperty): namespace = owl

