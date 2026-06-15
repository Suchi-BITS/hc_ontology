# -*- coding: utf-8 -*-
# Owlready2
# Copyright (C) 2007-2019 Jean-Baptiste LAMY
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

__all__ = ["start_observing", "stop_observing", "observe", "unobserve", "isobserved", "emit", "coalesced_observations", "InstancesOfClass"]

import weakref

from owlready2.base import rdf_type, rdfs_subclassof, owl_equivalentclass, owl_equivalentproperty, owl_equivalentindividual, owl_annotatedsource, owl_annotatedproperty, owl_annotatedtarget, owl_annotation_property
from owlready2.annotation import AnnotatedRelation
from owlready2 import Thing, ThingClass, owl_world

  
def _gen_triple_method_obj(onto, triple_method):
  def f(s, p, o):
    triple_method(s, p, o)
    observation = onto.world._observations.get(s)
    if observation: observation.call([p])
    elif s < 0:     _check_annotation_axiom(onto.world, s, p)
    
    observation = onto.world._observations.get(o)
    if observation:
      Prop = onto.world._entities.get(p)
      if Prop and Prop.inverse: observation.call([Prop._inverse_storid])
      
    if (p == rdf_type) and _INSTANCES_OF_CLASS:
      Class = onto.world._get_by_storid(o)
      if not Class is None: # Else it is Thing
        for parent in Class.ancestors():
          for l in _INSTANCES_OF_CLASS.get(parent.storid, ()):
            l._changed(onto)
  return f
  
def _gen_triple_method_data(onto, triple_method):
  def f(s, p, o, d):
    triple_method(s, p, o, d)
    observation = onto.world._observations.get(s)
    if observation: observation.call([p])
    elif s < 0:     _check_annotation_axiom(onto.world, s, p)
  return f
  
def _recursive_axiom(world, s):
  source = world._get_obj_triple_sp_o(s, owl_annotatedsource)
  prop   = world._get_obj_triple_sp_o(s, owl_annotatedproperty)
  target = world._get_triple_sp_od   (s, owl_annotatedtarget)
  if target is None: target = (None, None)
  if source and (source < 0): source = _recursive_axiom(world, source)
  return (source, prop, *target)
  
def _check_annotation_axiom(world, s, p = None):
  if p:
    prop = world._entities.get(p)
    if (not prop) or (prop._owl_type != owl_annotation_property): return
  source = world._get_obj_triple_sp_o(s, owl_annotatedsource)
  if not source: return
  if source < 0: # Annotation axiom on an annotation axiom
    source = _recursive_axiom(world, source)
  prop   = world._get_obj_triple_sp_o(s, owl_annotatedproperty)
  target = world._get_triple_sp_od   (s, owl_annotatedtarget)
  if target is None: target, target_d = None, None
  else:              target, target_d = target
  
  observation = world._observations.get((source, prop, target, target_d))
  if observation: observation.call([p])
  
  observation = world._observations.get((source, prop, None, None))
  if observation: observation.call([p])
  
  observation = world._observations.get((source, None, None, None))
  if observation: observation.call([prop])
  
  
def start_observing(onto_or_world):
  world = onto_or_world.world
  if not hasattr(world, "_observations"):
    world._observations = {}
    
    triple_obj_method = world._del_obj_triple_raw_spo
    def _del_obj_triple_raw_spo_observed(s = None, p = None, o = None):
      if s is None:
        if p is None:
          if o is None: observations_ps = [(world._observations.get(s), p) for (s, p) in world.graph.execute("SELECT DISTINCT s, p FROM objs")]
          else:         observations_ps = [(world._observations.get(s), p) for (s, p) in world.graph.execute("SELECT DISTINCT s, p FROM objs WHERE o=?", (o,))]
          triple_obj_method(s, p, o)
          for observation, p in observations_ps:
            if observation: observation.call([p])
            
        else:
          if o is None: observations = [world._observations.get(s) for (s,) in world.graph.execute("SELECT DISTINCT s FROM objs WHERE p=?", (p,))]
          else:         observations = [world._observations.get(s) for (s,) in world.graph.execute("SELECT DISTINCT s FROM objs WHERE p=? AND o=?", (p, o,))]
          triple_obj_method(s, p, o)
          for observation in observations:
            if observation: observation.call([p])
            
      else:
        p2 = [p] if p else [i for i, in world.graph.execute("SELECT DISTINCT p FROM objs WHERE s=?", (s,))]
        triple_obj_method(s, p, o)
        observation = world._observations.get(s)
        if observation: observation.call(p2)
        elif s < 0:
          for i in p2: _check_annotation_axiom(world, s, i)
          
      if (p == rdf_type) and _INSTANCES_OF_CLASS:
        Class = onto.world._get_by_storid(o)
        if not Class is None: # Else it is Thing
          for parent in Class.ancestors():
            for l in _INSTANCES_OF_CLASS.get(parent.storid, ()): l._changed()
            
    world._del_obj_triple_raw_spo = _del_obj_triple_raw_spo_observed
    
    triple_data_method = world._del_data_triple_raw_spod
    def _del_data_triple_raw_spod_observed(s = None, p = None, o = None, d = None):
      if s is None:
        if p is None:
          if   o is None: observations_ps = [(world._observations.get(s), p) for (s, p) in world.graph.execute("SELECT DISTINCT s, p FROM objs")]
          elif d is None: observations_ps = [(world._observations.get(s), p) for (s, p) in world.graph.execute("SELECT DISTINCT s, p FROM objs WHERE o=?", (o,))]
          else:           observations_ps = [(world._observations.get(s), p) for (s, p) in world.graph.execute("SELECT DISTINCT s, p FROM objs WHERE o=? AND d=?", (o, d,))]
          triple_data_method(s, p, o, d)
          for observation, p in observations_ps:
            if observation: observation.call([p])
            
        else:
          if   o is None: observations = [world._observations.get(s) for (s,) in world.graph.execute("SELECT DISTINCT s FROM datas WHERE p=?", (p,))]
          elif d is None: observations = [world._observations.get(s) for (s,) in world.graph.execute("SELECT DISTINCT s FROM datas WHERE p=? AND o=?", (p, o,))]
          else:           observations = [world._observations.get(s) for (s,) in world.graph.execute("SELECT DISTINCT s FROM datas WHERE p=? AND o=? AND d=?", (p, o, d,))]
          triple_data_method(s, p, o, d)
          for observation in observations:
            if observation: observation.call([p])
            
      else:
        p2 = [p] if p else [i for i, in world.graph.execute("SELECT DISTINCT p FROM datas WHERE s=?", (s,))]
        triple_data_method(s, p, o, d)
        observation = world._observations.get(s)
        if observation: observation.call(p2)
        elif s < 0:
          for i in p2: _check_annotation_axiom(world, s, i)
        
    world._del_data_triple_raw_spod = _del_data_triple_raw_spod_observed
    
  if onto_or_world is onto_or_world.world: # Start observing all ontologies
    for onto in world.ontologies.values(): start_observing(onto)
    
    _register_ontology = world._register_ontology
    def register_ontology(ontology):
      _register_ontology(ontology)
      if not getattr(ontology, "_observed", False): start_observing(ontology)
    world._register_ontology = register_ontology
    
  else:
    onto = onto_or_world
    if not getattr(onto, "_observed", False):
      onto._observed = True
      onto._add_obj_triple_raw_spo   = _gen_triple_method_obj(onto, onto.graph._add_obj_triple_raw_spo)
      onto._set_obj_triple_raw_spo   = _gen_triple_method_obj(onto, onto.graph._set_obj_triple_raw_spo)
      onto._del_obj_triple_raw_spo   = _gen_triple_method_obj(onto, onto.graph._del_obj_triple_raw_spo)
      onto._add_data_triple_raw_spod = _gen_triple_method_data(onto, onto.graph._add_data_triple_raw_spod)
      onto._set_data_triple_raw_spod = _gen_triple_method_data(onto, onto.graph._set_data_triple_raw_spod)
      onto._del_data_triple_raw_spod = _gen_triple_method_data(onto, onto.graph._del_data_triple_raw_spod)
      
      _old_entity_destroyed = onto._entity_destroyed
      def _entity_destroyed(entity):
        _old_entity_destroyed(entity)
        if _INSTANCES_OF_CLASS and isinstance(entity, Thing):
          Classes   = [Class for Class in entity.is_a if isinstance(Class, ThingClass)]
          Ancestors = { Ancestor for Class in Classes for Ancestor in Class.ancestors() }
          for Ancestor in Ancestors:
            for l in _INSTANCES_OF_CLASS.get(Ancestor.storid, ()):
              l._changed()
      onto._entity_destroyed = _entity_destroyed
      
def stop_observing(onto_or_world):
  if onto_or_world.world is onto_or_world:
    world = onto_or_world
    for onto in world.ontologies.values(): stop_observing(onto)

    world._del_obj_triple_raw_spo   = world.graph._del_obj_triple_raw_spo
    world._del_data_triple_raw_spod = world.graph._del_data_triple_raw_spod
    if hasattr(world, "_register_ontology"): del world._register_ontology
  else:
    onto = onto_or_world
    del onto._observed
    del onto._entity_destroyed
    onto._add_obj_triple_raw_spo   = onto.graph._add_obj_triple_raw_spo
    onto._set_obj_triple_raw_spo   = onto.graph._set_obj_triple_raw_spo
    onto._del_obj_triple_raw_spo   = onto.graph._del_obj_triple_raw_spo
    onto._add_data_triple_raw_spod = onto.graph._add_data_triple_raw_spod
    onto._set_data_triple_raw_spod = onto.graph._set_data_triple_raw_spod
    onto._del_data_triple_raw_spod = onto.graph._del_data_triple_raw_spod
  

class Observation(object):
  def __init__(self, o):
    self.listeners                 = []
    self.o                         = o
    self.coalesced_changes         = set()
    
  def call(self, ps):
    if coalesced_observations.level:
      self.coalesced_changes.update(ps)
      coalesced_observations.delayed_observations.add(self)
    else:
      for listener in tuple(self.listeners): # tuple() ensures that it works if the list of listeners is modified by a listener
        listener(self.o, ps)
        
  def add_listener(self, listener):
    self.listeners.append(listener)
      
  def remove_listener(self, listener):
    if listener in self.listeners: self.listeners.remove(listener)
      
class CoalescedObservations(object):
  def __init__(self):
    self.level = 0
    self.delayed_observations = set()
    self.listeners = []
    
  def add_listener(self, listener):
    self.listeners.append(listener)
      
  def remove_listener(self, listener):
    if listener in self.listeners: self.listeners.remove(listener)
    
  def __enter__(self):
    self.level += 1
    
  def __exit__(self, exc_type = None, exc_val = None, exc_tb = None):
    self.level -= 1
    if self.level == 0: self.emit_observations()
    
  def emit_observations(self):
    for observation in self.delayed_observations:
      coalesced_changes = list(observation.coalesced_changes)
      for listener in tuple(observation.listeners): # tuple() ensures that it works if the list of listeners is modified by a listener
        listener(observation.o, coalesced_changes)
      observation.coalesced_changes.clear()
    self.delayed_observations.clear()
    for listener in self.listeners: listener()
    
coalesced_observations = CoalescedObservations()



def _prepare_tuple_o(o, world):
  if isinstance(o, tuple):
    return (_prepare_tuple_o(o[0], world), o[1] and o[1].storid, *((o[2] is not None) and world._to_rdf(o[2]) or (None, None)))
  else:
    return o.storid
  
def _prepare_args(o, world):
  if world is None:
    if   isinstance(o, AnnotatedRelation):
      world = o.namespace.world
      o     = _prepare_tuple_o(o._as_triple(), world)
    elif isinstance(o, tuple):
      o0 = o[0]
      while isinstance(o0, tuple): o0 = o0[0]
      world = o0.namespace.world
      if isinstance(o[0], AnnotatedRelation): o = (o[0]._as_triple(), o[1], o[2])
      o     = _prepare_tuple_o(o, world)
    elif hasattr(o, "storid"):
      world = o.namespace.world
      o = o.storid
    else:
      world = o.namespace.world
      o     = "_Py%s" % id(o)
  if world is owl_world: return None, None
  return o, world


def observe(o, listener, world = None):
  if o is None: return
  if hasattr(o, "observed") and o.observed(listener): return
  
  o, world = _prepare_args(o, world)
  if world is None: return
  if not hasattr(world, "_observations"): start_observing(world)
  
  observation = world._observations.get(o)
  if not observation: observation = world._observations[o] = Observation(o)
  observation.add_listener(listener)
  
def isobserved(o, listener = None, world = None):
  if o is None: return False
  if hasattr(o, "is_observed"): return o.is_observed(listener)
  
  o, world = _prepare_args(o, world)
  if world is None: return False  
  
  observation = world._observations.get(o)
  if listener: return observation and (listener in observation.listeners)
  else:        return observation and observation.listeners
  
def unobserve(o, listener = None, world = None):
  if o is None: return
  if hasattr(o, "unobserved") and o.unobserved(listener): return
  
  o, world = _prepare_args(o, world)
  if world is None: return
  
  if listener:
    observation = world._observations.get(o)
    if observation:
      observation.remove_listener(listener)
      if not observation.listeners: del world._observations[o]
      
  else:
    if o in world._observations: del world._observations[o]


def emit(o, props):
  if o is None: return
  observation = o.namespace.world.world._observations.get(o.storid)
  if observation: observation.call(props)
  

    
class StoridList(object):
  def __init__(self, namespace, storids):
    self.namespace = namespace
    self._storids = storids
    
  def _update(self): pass
      
  def __len__(self):
    if self._storids is None: self._update()
    return len(self._storids)
  
  def __iter__(self):
    if self._storids is None: self._update()
    for i in self._storids: yield self.namespace._get_by_storid(i)
    
  def __getitem__(self, i):
    if self._storids is None: self._update()
    if isinstance(i, slice):
      return [self.namespace._get_by_storid(x) for x in self._storids.__getitem__(i)]
    else:
      return self.namespace._get_by_storid(self._storids[i])
    
  def __repr__(self):
    return """<StoridList: %s>""" % list(self)

  def get_instances(self): return list(self)
  instances = property(get_instances)

_INSTANCES_OF_CLASS = {} #weakref.WeakValueDictionary()

from owlready2.util import FirstList
class InstancesOfClass(StoridList):
  def __init__(self, Class, onto = None, order_by = "", lang = "", use_observe = False):
    self._Class         = Class
    self._lang          = lang
    self._onto          = onto
    self._use_observe   = use_observe
    self._Class_storids = ",".join((["'%s'" % child.storid for child in Class.descendants()]))
    
    if use_observe:
      ws = _INSTANCES_OF_CLASS.get(Class.storid)
      if ws is None: ws = _INSTANCES_OF_CLASS[Class.storid] = weakref.WeakSet()
      ws.add(self)
      
    StoridList.__init__(self, Class.namespace.world, None)
    
    if order_by:
      if   isinstance(order_by, str):
        self._order_by = self.namespace.world._props[order_by].storid
      elif order_by:
        self._order_by = order_by.storid
    else:
      self._order_by = ""
      
  def __repr__(self):
    return """<InstancesOfClass "%s": %s>""" % (self._Class, list(self))
  
  def _update(self):
    if self._onto: extra = " AND c = %s" % self._onto.graph.c
    else:          extra = ""
    if self._order_by:
      if self._lang:
        self._storids = [x[0] for x in self.namespace.graph.execute("""SELECT s FROM objs WHERE p = ?%s AND o IN (%s) ORDER BY (select q2.o FROM quads q2 WHERE q2.s = objs.s AND q2.p = ? AND q2.d LIKE '@%s')""" % (extra, self._Class_storids, self._lang), (rdf_type, self._order_by))]
      else:
        self._storids = [x[0] for x in self.namespace.graph.execute("""SELECT s FROM objs WHERE p = ?%s AND o IN (%s) ORDER BY (select q2.o FROM quads q2 WHERE q2.s = objs.s AND q2.p = ?)""" % (extra, self._Class_storids), (rdf_type, self._order_by))]
    else:
      self._storids = [x[0] for x in self.namespace.graph.execute("""SELECT s FROM objs WHERE p = ?%s AND o IN (%s)""" % (extra, self._Class_storids), (rdf_type,)).fetchall()]
      
  def _get_storids(self):
    if self._storids is None: self._update()
    return self._storids
    
  def _get_old_value(self):
    if self._storids is None: self._update()
    return StoridList(self.namespace, self._storids)
  
  def _changed(self, onto = None):
    if onto and (not onto is self._onto): return
    #observation = self.namespace.world._observations.get(self._Class.storid)
    observation = self.namespace.world._observations.get("_Py%s" % id(self))
    self._storids = None
    if observation: observation.call(["Inverse(http://www.w3.org/1999/02/22-rdf-syntax-ns#type)"])
    
  def add(self, o):
    if not self._Class in o.is_a: o.is_a.append(self._Class)
  append = add
  
  def remove(self, o):
    destroy_entity(o)
    
